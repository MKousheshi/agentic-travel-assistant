from langgraph.graph import START, StateGraph, END
from app.graph.state import OverallState
from app.graph.nodes import (
    create_plan,
    verify_plan,
    execute_plan,
    synthesize,
    exit,
    execution_router,
)


def build_graph(checkpointer=None):
    workflow = StateGraph(OverallState)

    workflow.add_node("plan", create_plan)
    workflow.add_node("verify", verify_plan)
    workflow.add_node("execution", execute_plan)
    workflow.add_node("synth", synthesize)

    workflow.add_node("exit", exit)

    workflow.add_edge(START, "plan")
    workflow.add_conditional_edges("execution", execution_router)
    workflow.add_edge("synth", "exit")
    workflow.add_edge("exit", END)

    return workflow.compile(checkpointer)


graph = build_graph()
