from collections.abc import AsyncGenerator
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.sse import ServerSentEvent
from langchain_core.messages import AIMessageChunk


def _to_json(obj: Any) -> Any:
    try:
        return jsonable_encoder(obj)
    except Exception:  # noqa: BLE001 - encoding must never break the stream
        return str(obj)


async def stream_run(
    graph: Any,
    graph_input: Any,
    config: dict,
    session: Any,
) -> AsyncGenerator[ServerSentEvent, None]:
    """
    Stream one graph run as SSE events.

    Consumes `graph.astream(..., stream_mode=["updates", "messages"])`, emitting
    `node` events for each node's output, `token` events for the synthesizer's
    streamed answer, and `interrupt` when the graph pauses for user input. The
    final `user_message` any node produced is emitted once as `message` after
    the stream ends, and `end` always closes the sequence.
    """
    # A disconnect (client gone) is deliberately NOT caught here. LangGraph
    # runs sync nodes like `execute_plan` in a worker thread that cancellation
    # cannot stop, so calling `session.rollback()` from a cancel/GeneratorExit
    # path could run concurrently with that thread against the same
    # (non-thread-safe) Session. The router catches disconnects instead and
    # only drops/closes the session, without touching its transaction state.
    final_message: str | None = None
    interrupted = False

    try:
        async for mode, data in graph.astream(
            graph_input, config=config, stream_mode=["updates", "messages"]
        ):
            if mode == "updates":
                if "__interrupt__" in data:
                    interrupted = True
                    pending_interrupt = data["__interrupt__"][-1]
                    yield ServerSentEvent(
                        event="interrupt",
                        data={
                            "id": pending_interrupt.id,
                            "value": _to_json(pending_interrupt.value),
                        },
                    )
                    continue

                for node_name, node_output in data.items():
                    if node_name.startswith("__"):
                        continue
                    if isinstance(node_output, dict) and "user_message" in node_output:
                        final_message = node_output["user_message"]
                    yield ServerSentEvent(
                        event="node",
                        data={"node": node_name, "output": _to_json(node_output)},
                    )
            elif mode == "messages":
                message, metadata = data
                if (
                    isinstance(message, AIMessageChunk)
                    and metadata.get("langgraph_node") == "synth"
                    and message.content
                ):
                    yield ServerSentEvent(
                        event="token", data={"content": message.content}
                    )
    except Exception as exc:  # noqa: BLE001 - any run failure must surface as an `error` event
        if session is not None and session.in_transaction():
            session.rollback()
        yield ServerSentEvent(event="error", data={"detail": str(exc)})
        yield ServerSentEvent(event="end", data={"interrupted": interrupted})
        return

    if final_message is not None:
        yield ServerSentEvent(event="message", data={"content": str(final_message)})

    yield ServerSentEvent(event="end", data={"interrupted": interrupted})
