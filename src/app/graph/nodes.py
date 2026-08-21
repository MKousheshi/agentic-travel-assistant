from langchain_openai import ChatOpenAI
from app.graph.state import OverallState
from app.schemas.booking import BookingRequest
from app.prompts.extraction import EXTRACTION_PROMPT
from app.prompts.classification import CLASSIFICATION_PROMPT
from app.prompts.response import RESPONSE_PROMPT

from app.tools.booking import get_booking_details

from app.schemas.booking import InputClassification
from app.config import get_settings
from app.db import get_connection
from app.agents import planner_agent
from app.models import ExecutionPlan

llm = ChatOpenAI(
    model="deepseek/deepseek-v4-flash",
    api_key=get_settings().openrouter_api_key,
    base_url="https://openrouter.ai/api/v1",
)

# llm = ChatOpenAI(
#     model="gpt-4o-mini",
#     api_key=get_settings().metis_api_key,
#     base_url="https://api.metisai.ir/openai/v1",
# )


def create_plan(state: OverallState) -> dict:
    messages = state["messages"]
    data = planner_agent.invoke({"messages": messages})
    # plan = ExecutionPlan(**data)
    # print(plan)
    return {}


def classify_intent(state: OverallState) -> dict:
    messages = state["messages"]
    last_message = messages[-1]
    user_message = last_message.content
    structured_llm = llm.with_structured_output(InputClassification)
    classification = structured_llm.invoke(CLASSIFICATION_PROMPT.format(user_message))
    return classification


def extract_book_ref(state: OverallState) -> dict:
    messages = state["messages"]
    last_message = messages[-1]
    user_message = last_message.content
    messages = [
        {"role": "system", "content": EXTRACTION_PROMPT},
        {"role": "user", "content": user_message},
    ]

    extraction = llm.with_structured_output(BookingRequest).invoke(messages)

    return extraction


def route_after_extraction(state: OverallState) -> str:
    if state.get("intent") == "get_booking_by_ref_book":
        if state.get("ref_book"):
            return "query_booking"
        return "ask_missing_ref_book"
    return "fallback"


def query_booking(state: OverallState) -> OverallState:
    ref_book = state.get("book_ref", "")
    with get_connection() as conn:
        result = get_booking_details(conn, ref_book)

    if result is None:
        state["booking_result"] = None
    else:
        state["booking_result"] = result.model_dump()

    return state


def respond_booking_node(state: OverallState) -> OverallState:
    messages = state["messages"]
    last_message = messages[-1]
    user_message = last_message.content
    response = llm.invoke(
        RESPONSE_PROMPT.format(user_message, state.get("booking_result"))
    )
    return {"response": response.text}
