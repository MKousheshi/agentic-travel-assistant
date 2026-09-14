from datetime import UTC, datetime
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware.types import InputAgentState
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from app.capabilities.airport.tools import airport_tools
from app.chat_models import capability_model
from app.models import CapabilityFailure, CapabilityResult, PlanStep
from app.prompts.capability import CAPABILITY_PROMPT
from app.registry import register_capability


@register_capability(
    id="airport",
    description=(
        "- Search for an airport by airport_code\n"
        "- Search for an airport based on city\n"
        "- Display airport_name, city, coordinates, and timezone\n"
        "- Find incoming and outgoing flights of an airport\n"
        "- Resolve the destination/origin city or location for Weather capability\n"
    ),
)
def airport_capability(
    step: PlanStep, state: dict, config: RunnableConfig
) -> CapabilityResult:
    messages: list[AnyMessage | dict[str, Any]] = state.get("messages", [])
    config = config | {"recursion_limit": 10}
    agent = create_agent(
        model=capability_model,
        tools=airport_tools,
        system_prompt=CAPABILITY_PROMPT.format(
            current_date=datetime.now(UTC).date().isoformat(),
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
