from typing import Any, Dict

from langchain.agents.middleware.types import InputAgentState
from langchain_core.runnables import RunnableConfig
from langsmith import traceable
from langchain_core.messages import AnyMessage, HumanMessage, AIMessage
from app.graph.state import WorkflowState, ExecutionState
from app.models import (
    PlannerResponse,
    PlanResponse,
    ClarificationResponse,
    Feedback,
    CapabilityContext,
)
from app.agents import planner_agent, eval_agent
from app.config import get_settings
from app.registry import registry


@traceable
def create_plan(state: WorkflowState) -> dict:
    print(registry.catalog())
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
def route_after_plan(state: WorkflowState) -> str:
    plan = state.get("plan", None)
    if not plan:
        return "exit"
    return "verify-rules"


@traceable
def validate_plan_by_rules(state: WorkflowState) -> dict:
    plan = state.get("plan", None)
    retries = state.get("retries", 0)
    if not plan:
        return {}
    errors = []
    if not plan.steps:
        errors.append("plan is empty, no steps found.")
    for step in plan.steps:
        if registry.has(step.capability_id):
            continue
        errors.append(
            f"capability id: {step.capability_id} for step: {step} does not exist."
        )
    if errors:
        return {
            "feedback": Feedback(validated=False, message="\n".join(errors)),
            "retries": retries + 1,
        }
    return {"feedback": Feedback(validated=True, message="")}


@traceable
def route_after_validation(state: WorkflowState) -> str:
    feedback = state.get("feedback", None)
    retries = state.get("retries", 0)
    if not feedback:
        return "exit"
    if feedback.validated:
        return "next"
    if retries >= get_settings().max_planning_retries:
        return "exit"
    return "planning"


@traceable
def validate_plan_by_llm(state: WorkflowState) -> dict:
    messages: list[AnyMessage | Dict[str, Any]] = list(state["messages"])
    plan = state.get("plan", None)
    retries = state.get("retries", 0)
    if not plan:
        raise Exception()
    messages.append(HumanMessage(content=f"Plan: {plan.model_dump_json()}"))

    result = eval_agent.invoke(InputAgentState(messages=messages))
    response: Feedback = result["structured_response"]
    return {"feedback": response, "retries": 0 if response.validated else retries + 1}


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
def execution_init(state: WorkflowState, config: RunnableConfig) -> dict:
    session = config.get("configurable", {}).get("session", None)
    if session:
        session.begin()
    exec_state = ExecutionState()
    return {"execution": exec_state}


@traceable
def execution_router(state: WorkflowState, config: RunnableConfig) -> str:
    execution = state.get("execution", None)
    session = config.get("configurable", {}).get("session", None)

    plan = state.get("plan", None)
    if not plan or not execution:
        return "exit"
    if execution.status == "running":
        return "execution"
    if execution.status == "completed":
        if session:
            session.commit()
    if execution.status == "failed":
        if session:
            session.rollback()
    return "synth"


@traceable
def execute_plan(state: WorkflowState, config: RunnableConfig) -> dict:
    execution = state.get("execution", None)
    plan = state.get("plan", None)
    if not plan or not execution:
        return {}

    step = plan.steps[execution.current_step_index]
    capability = registry.get(step.capability_id)
    if not capability:
        raise ReferenceError(f"Capability {step.capability_id} not found")
    # todo
    context = CapabilityContext(
        messages=state["messages"], prior_results=execution.results
    )
    result = capability.execute(step, {"messages": state["messages"]}, config)
    next_exec_state = execution.model_copy()
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
def synthesize(state: WorkflowState) -> dict:
    execution = state.get("execution")
    if not execution:
        return {}
    match (execution.status):
        case "completed":
            # todo use llm
            return {"user_message": execution.results}
        case "failed":
            # todo
            return {"user_message": execution.results}
        case "waiting_for_user":
            return {"user_message": execution.pending_question}
        case _:
            return {}


@traceable
def exit(state: WorkflowState):
    return {}
