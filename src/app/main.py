import pprint

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
import uuid

from app.graph.build_graph import build_graph

from langchain.messages import HumanMessage


import chainlit as cl
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

def format_node_output(node_output: dict) -> str:
    """
    Controls what appears inside the Chainlit intermediate Step.

    Customize this to avoid displaying huge objects, full message histories,
    sensitive values, etc.
    """
    visible_output = {
        key: value
        for key, value in node_output.items()
        # Usually do not duplicate the final answer inside the node Step.
        
    } if node_output else {}


    return pprint.pformat(
        visible_output,
        width=100,
        compact=False,
        sort_dicts=False,
    )

from app.graph.build_graph import build_graph

@cl.on_chat_start
async def on_chat_start():
    # Do not hardcode "thread-1": every user/session needs its own checkpoint thread.
    thread_id = str(uuid.uuid4())

    graph = build_graph(MemorySaver())

    cl.user_session.set("thread_id", thread_id)
    cl.user_session.set("graph", graph)
    cl.user_session.set("interrupted", False)


@cl.on_message
async def on_message(message: cl.Message):
    graph: CompiledStateGraph = cl.user_session.get("graph")  # type: ignore
    thread_id: str = cl.user_session.get("thread_id") # type: ignore
    interrupted: bool = cl.user_session.get("interrupted") # type: ignore

    config = RunnableConfig(
        configurable={
            "thread_id": thread_id,
        }
    )

    # Decide whether this is a fresh graph run or input for an interrupted graph.
    if interrupted:
        graph_input = Command(resume=message.content)
        cl.user_session.set("interrupted", False)
    else:
        graph_input = {
            "messages": [HumanMessage(content=message.content)],
        }

    final_response = None

    # `updates` emits a chunk after every completed node.
    async for chunk in graph.astream(
        graph_input,
        config=config,
        stream_mode="updates",
    ):
        # LangGraph sends an interrupt like:
        # {"__interrupt__": (Interrupt(value="..."),)}
        if "__interrupt__" in chunk:
            interrupt = chunk["__interrupt__"][-1]

            cl.user_session.set("interrupted", True)

            # `interrupt.value` is the question/prompt passed to interrupt(...)
            await cl.Message(content=str(interrupt.value)).send()
            return

        # Normal streamed node update shape:
        # {
        #     "node_name": {
        #         "some_state_key": "...",
        #         "response": "...",
        #     }
        # }
        for node_name, node_output in chunk.items():
            print(node_name, node_output)
            # Ignore any special internal chunk defensively.
            if node_name.startswith("__"):
                continue

            # Save final output, but do NOT display it as a Step.
            if isinstance(node_output, dict) and "user_message" in node_output:
                final_response = node_output["user_message"]

            # Show all non-final node output in a collapsible Chainlit step.
            step_output = format_node_output(node_output)

            async with cl.Step(
                name=node_name,
                type="tool",
            ) as step:
                step.output = step_output

    # The graph finished normally: now, and only now, send the final chat message.
    if final_response is not None:
        await cl.Message(content=str(final_response)).send()
