from datetime import UTC, datetime
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware.types import InputAgentState
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from app.capabilities.weather.tools import weather_tools
from app.chat_models import capability_model
from app.models import CapabilityFailure, CapabilityResult, PlanStep
from app.prompts.capability import CAPABILITY_PROMPT


# @register_capability(
#     id="weather",
#     description=(
#         "- Retrieve the current weather at a flight's destination\n"
#         "- Retrieve the current weather at a flight's origin\n"
#         "- Use airport information to resolve the city/location when necessary\n"
#         "- Combine the weather result with the flight information\n"
#     ),
# )
def weather_capability(
    step: PlanStep, state: dict, config: RunnableConfig
) -> CapabilityResult:
    messages: list[AnyMessage | dict[str, Any]] = state.get("messages", [])
    config = config | {"recursion_limit": 10}
    agent = create_agent(
        model=capability_model,
        tools=weather_tools,
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
