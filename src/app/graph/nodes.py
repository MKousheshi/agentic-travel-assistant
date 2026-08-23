from typing import Any, Dict

from langchain.agents.middleware.types import InputAgentState
from langgraph.types import Command
from langsmith import traceable
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage
from app.graph.state import OverallState
from app.models import (
    PlannerResponse,
    PlanResponse,
    ClarificationResponse,
    ExecutionState,
    CapabilityContext,
)
from app.agents import planner_agent
from app._capabilities import registry


@traceable
def create_plan(state: OverallState) -> dict:
    messages: list[AnyMessage | Dict[str, Any]] = list(state["messages"])
    previous_plan = state.get("plan", None)
    feedback = state.get("feedback", None)
    if previous_plan:
        messages.append(
            AIMessage(content=f"Previous plan: {previous_plan.model_dump_json()}")
        )
    if feedback:
        messages.append(HumanMessage(content=f"Feedback: {feedback}"))

    result = planner_agent.invoke(InputAgentState(messages=messages))
    response: PlannerResponse = result["structured_response"]
    match response:
        case PlanResponse(kind="plan", response=plan):
            return {"plan": plan}

        case ClarificationResponse(kind="clarification", response=clarification):
            return {
                "user_message": clarification.user_message,
                "messages": [AIMessage(content=clarification.user_message)],
            }


@traceable
def route_after_plan(state: OverallState) -> str:
    plan = state.get("plan", None)
    if not plan:
        return "exit"
    return "verify"


@traceable
def verify_plan(state: OverallState) -> Command:
    plan = state["plan"]
    errors = []
    for step in plan.steps:
        if registry.has(step.capability_id):
            continue
        errors.append(
            f"capability id: {step.capability_id} for step: {step} does not exist."
        )
    if errors:
        return Command(update={"errors": errors}, goto="plan")
    return Command(goto="execution", update={"execution": ExecutionState()})


# def build_capability_context(
#     state: OverallState,
#     execution: ExecutionState,
# ) -> dict[str, Any]:
#     return {
#         "messages": state.get("messages", []),
#         "completed_steps": [item.model_dump() for item in execution.completed_steps],
#         "results": {
#             item.capability_id: item.result
#             for item in execution.completed_steps
#             if item.status == "success"
#         },
#     }


@traceable
def execution_router(state: OverallState) -> str:
    exec_state = state.get("execution", None)
    plan = state.get("plan", None)
    if not plan or not exec_state:
        return "exit"
    if exec_state.status == "completed":
        return "synth"
    return "execution"


@traceable
def execute_plan(state: OverallState) -> dict:
    exec_state = state.get("execution", None)
    plan = state.get("plan", None)
    if not plan or not exec_state:
        return {}

    step = plan.steps[exec_state.current_step_index]
    capability = registry.get(step.capability_id)
    if not capability:
        raise ReferenceError(f"Capability {step.capability_id} not found")
    context = CapabilityContext(
        messages=state["messages"], prior_results=exec_state.results
    )
    result = capability.execute(step, context)
    next_exec_state = exec_state.model_copy()
    match (result.status):
        case "success":
            next_exec_state.results.append(result.data)
            next_exec_state.current_step_index += 1
            if next_exec_state.current_step_index == len(plan.steps):
                next_exec_state.status = "completed"
        case "failure":
            next_exec_state.status = "failed"
        case "needs_information":
            next_exec_state.status = "waiting_for_user"
            next_exec_state.pending_question = result.question

    return {"execution": next_exec_state}


@traceable
def synthesize(state: OverallState) -> dict:
    execution = state.get("execution")
    if not execution:
        return {}
    match (execution.status):
        case "completed":
            # todo use llm
            return {"user_message": execution.results}
        case "failed":
            # todo
            return {}
        case "waiting_for_user":
            return {"user_message": execution.pending_question}
        case _:
            return {}


@traceable
def exit(state: OverallState):
    return {}
