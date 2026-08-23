import pprint
from langgraph.types import Command
import uuid
from app.graph.build_graph import build_graph
from langchain.messages import HumanMessage
import chainlit as cl
from langgraph.checkpoint.memory import MemorySaver


def format_node_output(node_output: dict) -> str:
    """
    Controls what appears inside the Chainlit intermediate Step.

    Customize this to avoid displaying huge objects, full message histories,
    sensitive values, etc.
    """
    visible_output = (
        {key: value for key, value in node_output.items()} if node_output else {}
    )

    return pprint.pformat(
        visible_output,
        width=100,
        compact=False,
        sort_dicts=False,
    )


@cl.on_chat_start
async def on_chat_start():
    thread_id = str(uuid.uuid4())

    graph = build_graph(MemorySaver())
    config = {"configurable": {"thread_id": thread_id}}

    cl.user_session.set("config", config)
    cl.user_session.set("graph", graph)


async def invoke_graph(graph, graph_input, config):
    final_response = None
    actions = [
        cl.Action(name="confirm", payload={}, label="Confirm"),
        cl.Action(name="cancel", payload={}, label="Cancel"),
    ]
    try:
        async for chunk in graph.astream(
            graph_input,
            config=config,
            stream_mode="updates",
        ):
            if "__interrupt__" in chunk:
                pending_interrupt = chunk["__interrupt__"][-1]
                await cl.Message(
                    content=str(pending_interrupt.value), actions=actions
                ).send()
                cl.user_session.set("interrupted", True)
                continue

            for node_name, node_output in chunk.items():
                if node_name.startswith("__"):
                    continue

                if isinstance(node_output, dict) and "user_message" in node_output:
                    final_response = node_output["user_message"]

                step_output = format_node_output(node_output)
                async with cl.Step(name=node_name, type="tool") as step:
                    step.output = step_output
    finally:
        pass

    if final_response is not None:
        await cl.Message(content=str(final_response)).send()


@cl.action_callback("confirm")
async def on_confirm(action: cl.Action):
    graph = cl.user_session.get("graph")
    config = cl.user_session.get("config")
    await invoke_graph(graph, Command(resume="yes"), config)


@cl.action_callback("cancel")
async def on_cancel(action: cl.Action):
    graph = cl.user_session.get("graph")
    config = cl.user_session.get("config")
    await invoke_graph(graph, Command(resume="no"), config)


@cl.on_message
async def on_message(message: cl.Message):
    graph = cl.user_session.get("graph")
    config = cl.user_session.get("config")
    graph_input = {"messages": [HumanMessage(content=message.content)]}
    await invoke_graph(graph, graph_input, config)
