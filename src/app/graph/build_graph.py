from langgraph.graph import START, StateGraph, END
from app.graph.state import OverallState
from app.graph.nodes import (
    create_plan,
    validate_plan_by_rules,
    validate_plan_by_llm,
    execute_plan,
    synthesize,
    exit,
    execution_router,
    route_after_plan,
    route_after_validation,
)


def build_graph(checkpointer=None):
    workflow = StateGraph(OverallState)

    workflow.add_node("planning", create_plan)
    workflow.add_node("verify-rules", validate_plan_by_rules)
    workflow.add_node("verify-llm", validate_plan_by_llm)

    workflow.add_node("execution", execute_plan)
    workflow.add_node("synth", synthesize)

    workflow.add_node("exit", exit)

    workflow.add_edge(START, "planning")
    workflow.add_conditional_edges("planning", route_after_plan)
    workflow.add_conditional_edges(
        "verify-rules",
        route_after_validation,
        {"next": "verify-llm", "planning": "planning", "exit": "exit"},
    )
    workflow.add_conditional_edges(
        "verify-llm",
        route_after_validation,
        {"next": "execution", "planning": "planning", "exit": "exit"},
    )

    workflow.add_conditional_edges("execution", execution_router)
    workflow.add_edge("synth", "exit")
    workflow.add_edge("exit", END)

    return workflow.compile(checkpointer)


graph = build_graph()
