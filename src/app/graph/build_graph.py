from langgraph.graph import START, StateGraph, END
from app.graph.state import OverallState
from app.graph.nodes import (
    extract_book_ref,
    route_after_extraction,
    query_booking,
    respond_booking_node,
    classify_intent,
)


def build_graph():
    workflow = StateGraph(OverallState)

    workflow.add_node("classify", classify_intent)
    workflow.add_node("extraction", extract_book_ref)
    workflow.add_node("query", query_booking)
    workflow.add_node("respond", respond_booking_node)

    # workflow.add_edge(START, "input")
    workflow.add_edge(START, "classify")
    workflow.add_edge("classify", "extraction")
    workflow.add_edge("extraction", "query")
    workflow.add_edge("query", "respond")

    workflow.add_edge("respond", END)

    return workflow.compile()
