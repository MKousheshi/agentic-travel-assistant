from datetime import date
from typing import Any, Dict

from langchain.agents import create_agent
from langchain.agents.middleware.types import InputAgentState
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from langsmith import traceable
from app.models import PlanStep, CapabilityResult, CapabilityFailure
from app.prompts.capability import CAPABILITY_PROMPT
from app.capabilities.booking.tools import booking_tools
from app.chat_models import capability_model
from app.registry import register_capability


@register_capability(
    id="booking",
    description=(
        "- Retrieve bookings by reference\n"
        "- Search bookings by date or date range\n"
        "- Calculate booking counts and revenue for a period\n"
        "- Create new booking with a reference, date, and total amount\n"
        "- Delete booking"
    ),
)
@traceable
def booking_capability(
    step: PlanStep, state: dict, config: RunnableConfig
) -> CapabilityResult:
    messages: list[AnyMessage | Dict[str, Any]] = state.get("messages", [])
    config = config | {"recursion_limit": 10}
    agent = create_agent(
        model=capability_model,
        tools=booking_tools,
        system_prompt=CAPABILITY_PROMPT.format(
            current_date=date.today().isoformat(),
            action=step.action,
            goal=step.goal,
        ),
        response_format=ToolStrategy(CapabilityResult),
    )
    try:
        result = agent.invoke(
            InputAgentState(messages=messages),
            config=config,
        )
        response: CapabilityResult = result["structured_response"]
        return response
    except GraphRecursionError as e:
        return CapabilityFailure(message=str(e), reason=str(e), details={})
