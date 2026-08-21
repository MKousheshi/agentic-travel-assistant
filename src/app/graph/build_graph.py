from langgraph.graph import START, StateGraph, END
from app.graph.state import OverallState
from app.graph.nodes import (
    # extract_book_ref,
    # route_after_extraction,
    # query_booking,
    # respond_booking_node,
    # classify_intent,
    create_plan
)


def build_graph(checkpointer=None):
    workflow = StateGraph(OverallState)
    workflow.add_node('plan', create_plan)

    # workflow.add_node("classify", classify_intent)
    # workflow.add_node("extraction", extract_book_ref)
    # workflow.add_node("query", query_booking)
    # workflow.add_node("respond", respond_booking_node)

    # workflow.add_edge(START, "input")
    workflow.add_edge(START, "plan")
    # workflow.add_edge("classify", "extraction")
    # workflow.add_edge("extraction", "query")
    # workflow.add_edge("query", "respond")

    workflow.add_edge("plan", END)

    return workflow.compile(checkpointer)
