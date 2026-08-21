from datetime import datetime
from typing import cast

from langchain.agents.middleware.types import InputAgentState
from langchain_openai import ChatOpenAI
from langgraph.types import interrupt
from langsmith import traceable
from pydantic import ValidationError
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.graph.state import OverallState, OverallState as BookingState
from app.schemas.booking import GuidanceReply, BookingRequest
from app.prompts.extraction import BOOKING_EXTRACTION_PROMPT
from app.prompts.correction import BOOKING_CORRECTION_PROMPT
from app.utils import flatten_validation_errors
from app.models import PlannerResponse, ExecutionPlan
from app.config import get_settings
from app.agents import planner_agent

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


def create_plan(state: OverallState) -> dict:
    messages = state["messages"]
    print(messages)
    result = planner_agent.invoke(InputAgentState(messages=messages))
    print(result)
    response: PlannerResponse = result['structured_response']
    if type(response.response) is ExecutionPlan:
        return {'plan': response.response.model_dump()}
    return response.response.model_dump()


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


def execute(state: BookingState) -> dict:
    print(state["booking_request"])
    return {"response": "executed"}


def summerize(state: BookingState) -> dict:
    pass


def respond(state: BookingState) -> dict:
    pass


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
