from datetime import datetime
from typing import cast

from langchain.agents.middleware.types import InputAgentState
from langchain_openai import ChatOpenAI
from langgraph.types import Command, interrupt
from langsmith import traceable
from pydantic import ValidationError
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.graph.state import OverallState, OverallState as BookingState
from app.schemas.booking import GuidanceReply, BookingRequest
from app.prompts.extraction import BOOKING_EXTRACTION_PROMPT
from app.prompts.correction import BOOKING_CORRECTION_PROMPT
from app.utils import flatten_validation_errors
from app.models import PlannerResponse, ExecutionPlan, Clarification
from app.config import get_settings
from app.agents import planner_agent, planner_llm, PLANNER_PROMPT
from app._capabilities import registery

llm = ChatOpenAI(
    model="deepseek/deepseek-v4-flash",
    api_key=get_settings().openrouter_api_key,
    base_url="https://openrouter.ai/api/v1",
)

llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=get_settings().metis_api_key,
    base_url="https://api.metisai.ir/openai/v1",
)


# def create_plan(state: OverallState) -> Command:
#     messages = state["messages"]
#     plan = state.get("plan", None)
#     if plan:
#         errs = state.get("errors", [])
#         errors = "plan has these errors:\n" + "\n".join(errs) if errs else None
#         messages.append(AIMessage(plan.model_dump_json()))
#         messages.append(HumanMessage(errors))


#     result = planner_agent.invoke(InputAgentState(messages=messages))
#     response: PlannerResponse = result["structured_response"]
#     if type(response.response) is Clarification:
#         return Command(
#             update=response.response.model_dump()
#             | {"messages": AIMessage(response.response.user_message)},
#             goto="exit",
#         )
#     return Command(update={"plan": response.response}, goto="verify")
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
                        f"Available capabilities: {[c.id for c in registery.all()]}\n"
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


def verify_plan(state: OverallState) -> Command:
    plan = state["plan"]
    errors = []
    for step in plan.steps:
        if registery.has(step.capability_id):
            continue
        errors.append(
            f"capability id: {step.capability_id} for step: {step} does not exist."
        )
    if errors:
        return Command(update={"errors": errors}, goto="plan")
    return Command(goto="execute")


def execute_plan(state: OverallState):
    plan = state["plan"]
    results = []
    for step in plan.steps:
        capability = registery.get(step.capability_id)
        if capability:
            result = capability.execute(step, {"messages": state["messages"]})
            if "user_message" in result:
                results.append(result["user_message"])

    return {"user_message": "\n".join(results)}


def exit(state: OverallState):
    return {}


@traceable
def extract(state: BookingState) -> dict:
    messages = state["messages"]
    print(messages)
    messages = [
        SystemMessage(BOOKING_EXTRACTION_PROMPT.format(datetime.now())),
    ] + messages
    try:
        data = agent.invoke({"messages": messages})  # type: ignore
        print(data)
        booking_request = cast(BookingRequest, data)
    except ValidationError as err:
        return {"errors": flatten_validation_errors(err)}

    return {"booking_request": booking_request.model_dump()} | {"errors": []}


@traceable
def guide_user(state: BookingState) -> dict:
    messages = [
        SystemMessage(BOOKING_CORRECTION_PROMPT),
        HumanMessage(
            f"User's latest input:\n{state['messages'][-1].content}\n\nValidation errors:\n{state.get('errors')}"
        ),
    ]
    data = llm.with_structured_output(GuidanceReply).invoke(messages)
    guidance = cast(GuidanceReply, data)
    user_input = interrupt(guidance.message)
    return {"messages": [AIMessage(guidance.message), HumanMessage(user_input)]}


def route_after_extraction(state: BookingState) -> str:
    if state.get("errors"):
        return "guidance"
    return "execution"


# def route_after_extraction(state: OverallState) -> str:
#     if state.get("intent") == "get_booking_by_ref_book":
#         if state.get("ref_book"):
#             return "query_booking"
#         return "ask_missing_ref_book"
#     return "fallback"


# def query_booking(state: OverallState) -> OverallState:
#     ref_book = state.get("book_ref", "")
#     with get_connection() as conn:
#         result = get_booking_details(conn, ref_book)

#     if result is None:
#         state["booking_result"] = None
#     else:
#         state["booking_result"] = result.model_dump()

#     return state


# def respond_booking_node(state: OverallState) -> OverallState:
#     messages = state["messages"]
#     last_message = messages[-1]
#     user_message = last_message.content
#     response = llm.invoke(
#         RESPONSE_PROMPT.format(user_message, state.get("booking_result"))
#     )
#     return {"response": response.text}
