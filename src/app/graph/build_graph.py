from langgraph.graph import START, StateGraph, END
from app.graph.state import OverallState
from app.graph.nodes import (
    # extract_book_ref,
    # route_after_extraction,
    # query_booking,
    # respond_booking_node,
    # classify_intent,
    create_plan,
    verify_plan,
    execute_plan,
    exit
)


def build_graph(checkpointer=None):
    workflow = StateGraph(OverallState)

    workflow.add_node("plan", create_plan)
    workflow.add_node("verify", verify_plan)
    workflow.add_node("execute", execute_plan)
    workflow.add_node("exit", exit)

    workflow.add_edge(START, "plan")
    
    
    # workflow.add_edge("classify", "extraction")
    # workflow.add_edge("extraction", "query")
    # workflow.add_edge("query", "respond")

    workflow.add_edge("exit", END)
    workflow.add_edge("execute", END)
    

    return workflow.compile(checkpointer)

graph = build_graph()