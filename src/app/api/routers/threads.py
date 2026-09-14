import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.api.deps import GraphDep, LockDep, SessionDep
from app.api.schemas import MessageRequest, RunRequest
from app.api.streaming import stream_run

router = APIRouter(prefix="/threads/{thread_id}")


@router.post("/stream", response_class=EventSourceResponse)
async def stream(
    thread_id: str,
    body: RunRequest,
    request: Request,
    graph: GraphDep,
    lock: LockDep,
    session: SessionDep,
) -> AsyncGenerator[ServerSentEvent, None]:
    async with lock:
        config = {"configurable": {"thread_id": thread_id, "session": session}}

        if isinstance(body, MessageRequest):
            graph_input: Any = {"messages": [HumanMessage(content=body.message)]}
        else:
            state = await graph.aget_state(config)
            if not any(task.interrupts for task in state.tasks):
                yield ServerSentEvent(
                    event="error",
                    data={"detail": "No pending interrupt to resume."},
                )
                yield ServerSentEvent(event="end", data={"interrupted": False})
                return
            graph_input = Command(resume=body.resume)

        try:
            async for event in stream_run(graph, graph_input, config, session):
                yield event
        except (asyncio.CancelledError, GeneratorExit):
            # The client disconnected. A node may still be running against
            # this session in a worker thread we cannot stop, so we must not
            # touch its transaction (rollback/commit would race with it).
            # Just stop tracking the session so the next request on this
            # thread gets a fresh one instead of the possibly-still-in-use one.
            session.close()
            request.app.state.sessions.pop(thread_id, None)
            raise


@router.delete("", status_code=204)
async def delete_thread(
    thread_id: str,
    request: Request,
    graph: GraphDep,
    lock: LockDep,
) -> None:
    # The lock is intentionally never removed from app.state.locks: the
    # session dependency for a queued stream request resolves before it
    # waits on this lock, so if we dropped the lock here a request already
    # waiting on it would keep the old lock object while a new request got a
    # fresh one, and the two would no longer be serialized against each
    # other. Leaking one Lock object per thread_id ever used is cheap.
    async with lock:
        session = request.app.state.sessions.pop(thread_id, None)
        if session is not None:
            session.close()
        await graph.checkpointer.adelete_thread(thread_id)
