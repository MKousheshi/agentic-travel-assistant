import logging
from typing import Any, Literal

from langchain.agents.middleware.types import InputAgentState
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langsmith import traceable

from app.agents import get_eval_agent, get_planner_agent, get_synthesizer_model
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

logger = logging.getLogger(__name__)


class MissingPlanError(RuntimeError):
    """Raised when a graph node that requires a plan is reached without one."""


PLANNING_FAILED_MESSAGE = (
    "I couldn't put together a reliable plan for that request. Could you "
    "rephrase it or split it into smaller parts?"
)


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
    if previous_plan and feedback and feedback.validated is False:
        messages.append(
            HumanMessage(
                content=(
                    "[Plan validator feedback: internal, not written by the "
                    "user]\n"
                    "The plan you proposed for the latest user request was "
                    "rejected.\n"
                    f"Rejected plan: {previous_plan.model_dump_json()}\n"
                    f"Problems to fix: {feedback.message}"
                )
            )
        )

    result = get_planner_agent().invoke(InputAgentState(messages=messages))
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
        raise MissingPlanError("validate_plan_by_rules reached with no plan in state")
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


def route_after_validation(
    state: WorkflowState,
) -> Literal["planning-failed", "next", "planning"]:
    feedback = state.get("feedback", None)
    retries = state.get("retries", 0)
    if not feedback:
        raise MissingPlanError(
            "route_after_validation reached with no feedback in state"
        )
    if feedback.validated:
        return "next"
    if retries >= get_settings().max_planning_retries:
        return "planning-failed"
    return "planning"


@traceable
def validate_plan_by_llm(state: WorkflowState) -> dict:
    messages: list[AnyMessage | dict[str, Any]] = list(state["messages"])
    plan = state.get("plan", None)
    retries = state.get("retries", 0)
    if not plan:
        raise MissingPlanError("validate_plan_by_llm reached with no plan in state")
    messages.append(HumanMessage(content=f"Plan: {plan.model_dump_json()}"))

    result = get_eval_agent().invoke(InputAgentState(messages=messages))
    response: Feedback = result["structured_response"]
    return {"feedback": response, "retries": 0 if response.validated else retries + 1}


@traceable
def execution_init(state: WorkflowState, config: RunnableConfig) -> dict:
    session = config.get("configurable", {}).get("session", None)
    if session:
        session.begin()
    exec_state = ExecutionState()
    return {"execution": exec_state}


def execution_router(
    state: WorkflowState, config: RunnableConfig
) -> Literal["execution", "synth"]:
    execution = state.get("execution", None)
    session = config.get("configurable", {}).get("session", None)

    plan = state.get("plan", None)
    if not plan or not execution:
        raise MissingPlanError(
            "execution_router reached with no plan/execution in state"
        )
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
        raise MissingPlanError("execute_plan reached with no plan/execution in state")
    logger.debug("Executing plan step %s", execution.current_step_index)
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
    next_exec_state = execution.model_copy(
        deep=True, update={"status": "running", "pending_question": None}
    )
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
        raise MissingPlanError("synthesize reached with no plan/execution in state")
    match execution.status:
        case "completed":
            response = get_synthesizer_model().invoke(
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
            raise MissingPlanError(
                f"synthesize reached with unexpected execution status {execution.status!r}"
            )


@traceable
def planning_failed(state: WorkflowState) -> dict:
    return {
        "user_message": PLANNING_FAILED_MESSAGE,
        "messages": [AIMessage(PLANNING_FAILED_MESSAGE)],
    }


@traceable
def exit(state: WorkflowState) -> dict:
    execution = state.get("execution")
    if execution and execution.status == "waiting_for_user":
        return {}
    return {"execution": None, "plan": None, "feedback": None, "retries": 0}
