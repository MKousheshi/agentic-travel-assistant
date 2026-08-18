
from langgraph.graph.state import CompiledStateGraph

from app.graph.build_graph import build_graph

from langchain.messages import HumanMessage



import chainlit as cl
from langchain_core.messages import HumanMessage


@cl.on_chat_start
async def on_chat_start():
    cl.user_session.set("graph", build_graph())

@cl.on_message
async def on_message(message: cl.Message):
    graph: CompiledStateGraph = cl.user_session.get("graph") # type: ignore
    
    cb = cl.LangchainCallbackHandler()
    
    final_response = cl.Message(content="")
    
    # Stream events from LangGraph
    async for event in graph.astream_events(
        {"messages": [HumanMessage(content=message.content)]},
        version="v2",
    ):
        kind = event["event"]
        if kind == "on_chat_model_stream":
            content = event["data"]["chunk"].content
            if content:
                await final_response.stream_token(content)
                
    await final_response.send()


