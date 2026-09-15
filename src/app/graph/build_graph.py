from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    create_plan,
    execute_plan,
    execution_init,
    execution_router,
    exit,
    planning_failed,
    route_after_plan,
    route_after_validation,
    route_from_start,
    synthesize,
    validate_plan_by_llm,
    validate_plan_by_rules,
)
from app.graph.state import WorkflowState


def build_graph(checkpointer=None):
    workflow = StateGraph(WorkflowState)

    workflow.add_node("planning", create_plan)
    workflow.add_node("verify-rules", validate_plan_by_rules)
    workflow.add_node("verify-llm", validate_plan_by_llm)
    workflow.add_node("execution-init", execution_init)
    workflow.add_node("execution", execute_plan)

    workflow.add_node("synth", synthesize)

    workflow.add_node("planning-failed", planning_failed)

    workflow.add_node("exit", exit)

    workflow.add_conditional_edges(START, route_from_start)
    workflow.add_conditional_edges("planning", route_after_plan)
    workflow.add_conditional_edges(
        "verify-rules",
        route_after_validation,
        {
            "next": "verify-llm",
            "planning": "planning",
            "planning-failed": "planning-failed",
        },
    )
    workflow.add_conditional_edges(
        "verify-llm",
        route_after_validation,
        {
            "next": "execution-init",
            "planning": "planning",
            "planning-failed": "planning-failed",
        },
    )
    workflow.add_edge("execution-init", "execution")
    workflow.add_conditional_edges("execution", execution_router)
    workflow.add_edge("synth", "exit")
    workflow.add_edge("planning-failed", "exit")
    workflow.add_edge("exit", END)

    return workflow.compile(checkpointer)


graph = build_graph()
