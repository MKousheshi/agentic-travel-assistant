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
from app.capabilities.flight.tools import flight_tools
from app.chat_models import mini_model
from app.registry import register_capability


@register_capability(
    id="flight",
    description=(
        "- Retrieve flights by ID or flight number\n"
        "- Find flights between departure and arrival airports\n"
        "- Show flight status\n"
        "- Analyze actual_departure and actual_arrival based on status\n"
        "- Find the aircraft associated with a flight using aircraft_code\n"
        "- Analyze high-traffic routes and their associated revenue\n"
    ),
)
def flight_capability(
    step: PlanStep, state: dict, config: RunnableConfig
) -> CapabilityResult:
    messages: list[AnyMessage | Dict[str, Any]] = state.get("messages", [])
    config = config | {"recursion_limit": 10}
    agent = create_agent(
        model=mini_model,
        tools=flight_tools,
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
