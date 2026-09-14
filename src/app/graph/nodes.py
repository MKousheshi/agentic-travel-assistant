from typing import Any, Literal

from langchain.agents.middleware.types import InputAgentState
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langsmith import traceable

from app.agents import eval_agent, planner_agent, synthesizer_model
from app.config import get_settings
from app.graph.state import ExecutionState, WorkflowState
from app.models import (
    ClarificationResponse,
    Feedback,
    PlannerResponse,
    PlanResponse,
    StepResult,
)
from app.prompts.synthesizer import SYNTHESIZER_PROMPT
from app.registry import registry


class MissingPlanError(RuntimeError):
    """Raised when a graph node that requires a plan is reached without one."""


@traceable
def route_from_start(state: WorkflowState) -> Literal["execution", "planning"]:
    execution = state.get("execution")
    if execution:
        return "execution"
    return "planning"


@traceable
def create_plan(state: WorkflowState) -> dict:
    messages: list[AnyMessage | dict[str, Any]] = list(state["messages"])
    previous_plan = state.get("plan", None)
    feedback = state.get("feedback", None)
    retries = state.get("retries", 0)
    if retries >= get_settings().max_planning_retries:
        retries = 0
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
            return {"plan": plan, "retries": retries}

        case ClarificationResponse(kind="clarification", response=clarification):
            return {
                "user_message": clarification.user_message,
                "messages": [AIMessage(content=clarification.user_message)],
                "plan": None,
                "retries": retries,
            }


@traceable
def route_after_plan(state: WorkflowState) -> Literal["exit", "verify-rules"]:
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
    ids: set[int] = set()
    for step in plan.steps:
        if step.step_id in ids:
            errors.append(
                f"error in step with step_id {step.step_id}! step_id is not unique in the plan!"
            )
        ids.add(step.step_id)
        if not registry.has(step.capability_id):
            errors.append(
                f"error in step with step_id {step.step_id}! capability id: {step.capability_id} does not exist."
            )
    if errors:
        return {
            "feedback": Feedback(validated=False, message="\n".join(errors)),
            "retries": retries + 1,
        }
    return {"feedback": Feedback(validated=True, message="")}


@traceable
def route_after_validation(state: WorkflowState) -> Literal["exit", "next", "planning"]:
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
    messages: list[AnyMessage | dict[str, Any]] = list(state["messages"])
    plan = state.get("plan", None)
    retries = state.get("retries", 0)
    if not plan:
        raise MissingPlanError("validate_plan_by_llm reached with no plan in state")
    messages.append(HumanMessage(content=f"Plan: {plan.model_dump_json()}"))

    result = eval_agent.invoke(InputAgentState(messages=messages))
    response: Feedback = result["structured_response"]
    return {"feedback": response, "retries": 0 if response.validated else retries + 1}


@traceable
def execution_init(state: WorkflowState, config: RunnableConfig) -> dict:
    session = config.get("configurable", {}).get("session", None)
    if session:
        session.begin()
    exec_state = ExecutionState()
    return {"execution": exec_state}


@traceable
def execution_router(
    state: WorkflowState, config: RunnableConfig
) -> Literal["exit", "execution", "synth"]:
    execution = state.get("execution", None)
    session = config.get("configurable", {}).get("session", None)

    plan = state.get("plan", None)
    if not plan or not execution:
        return "exit"
    if execution.status == "running":
        return "execution"
    if execution.status == "completed" and session:
        session.commit()
    if execution.status == "failed" and session:
        session.rollback()
    return "synth"


@traceable
def execute_plan(state: WorkflowState, config: RunnableConfig) -> dict:
    execution = state.get("execution", None)
    plan = state.get("plan", None)
    if not plan or not execution:
        return {}
    print("execution", execution.current_step_index)
    step = plan.steps[execution.current_step_index]
    capability = registry.get(step.capability_id)
    if not capability:
        raise ReferenceError(f"Capability {step.capability_id} not found")
    result = capability.execute(
        step,
        {
            "messages": state["messages"]
            + [AIMessage(result.model_dump_json()) for result in execution.results]
        },
        config,
    )
    next_exec_state = execution.model_copy()
    match result.status:
        case "success":
            next_exec_state.results.append(
                StepResult(message=result.message, data=result.data, step=step)
            )
            next_exec_state.current_step_index += 1
            if next_exec_state.current_step_index == len(plan.steps):
                next_exec_state.status = "completed"
        case "failure":
            next_exec_state.pending_question = result.message
            next_exec_state.status = "failed"
        case "needs_information":
            next_exec_state.status = "waiting_for_user"
            next_exec_state.pending_question = result.question

    return {"execution": next_exec_state}


@traceable
def synthesize(state: WorkflowState) -> dict:
    execution = state.get("execution")
    plan = state.get("plan")

    if not execution or not plan:
        return {}
    match execution.status:
        case "completed":
            response = synthesizer_model.invoke(
                [
                    SystemMessage(
                        SYNTHESIZER_PROMPT.format(
                            user_request=plan.user_query,
                            conversation=state["messages"],
                            step_results=execution.results,
                        )
                    )
                ]
            )
            return {
                "user_message": response.content,
                "messages": [AIMessage(response.content)],
            }
        case "failed":
            return {
                "user_message": execution.pending_question,
                "messages": [AIMessage(execution.pending_question)],
            }
        case "waiting_for_user":
            return {
                "user_message": execution.pending_question,
                "messages": [AIMessage(execution.pending_question)],
            }
        case _:
            return {}


@traceable
def exit(state: WorkflowState) -> dict:
    execution = state.get("execution")
    if execution:
        match execution.status:
            case "completed":
                return {"execution": None}
            case "failed":
                return {"execution": None}
            case "waiting_for_user":
                return {}

    return {}
