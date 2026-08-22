from typing import Any

from langchain_openai import ChatOpenAI
from langgraph.types import Command, interrupt
from langsmith import traceable
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.graph.state import OverallState
from app.models import (
    PlannerResponse,
    ExecutionState,
    Clarification,
    CapabilityFailure,
    StepExecution,
    CapabilitySuccess,
    CapabilityNeedsInformation,
    CapabilityContext,
)
from app.config import get_settings
from app.agents import planner_llm, PLANNER_PROMPT
from app._capabilities import registry

# TODO: set by config
# llm = ChatOpenAI(
#     model="deepseek/deepseek-v4-flash",
#     api_key=get_settings().openrouter_api_key,
#     base_url="https://openrouter.ai/api/v1",
# )

# llm = ChatOpenAI(
#     model="gpt-4o-mini",
#     api_key=get_settings().metis_api_key,
#     base_url="https://api.metisai.ir/openai/v1",
# )


@traceable
def create_plan(state: OverallState) -> Command:
    # Avoid mutating state["messages"] in place
    messages = list(state["messages"])

    previous_plan = state.get("plan")
    if previous_plan:
        errors = state.get("errors", [])

        messages.append(AIMessage(content=previous_plan.model_dump_json()))

        if errors:
            messages.append(
                HumanMessage(
                    content=(
                        "The previous plan failed verification.\n"
                        f"Available capabilities: {[c.id for c in registry.all()]}\n"
                        "Create a corrected plan based on these errors:\n"
                        + "\n".join(f"- {error}" for error in errors)
                    )
                )
            )

    response: PlannerResponse = planner_llm.invoke(
        [
            SystemMessage(PLANNER_PROMPT),
            *messages,
        ]
    )

    if isinstance(response.response, Clarification):
        clarification = response.response

        return Command(
            update={
                **clarification.model_dump(),
                "messages": [AIMessage(content=clarification.user_message)],
            },
            goto="exit",
        )

    return Command(
        update={"plan": response.response},
        goto="verify",
    )


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
            #todo use llm
            return {"user_message": execution.results}
        case "failed":
            #todo
            return {}
        case "waiting_for_user":
            return {"user_message": execution.pending_question}
        case _:
            return {}


@traceable
def exit(state: OverallState):
    return {}
