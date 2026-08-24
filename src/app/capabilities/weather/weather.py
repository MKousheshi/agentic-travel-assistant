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
from app.capabilities.weather.tools import weather_tools
from app.chat_models import mini_model
from app.registry import register_capability



@register_capability(
    id="weather",
    description=(
        "- Retrieve the current weather at a flight's destination\n"
        "- Retrieve the current weather at a flight's origin\n"
        "- Use airport information to resolve the city/location when necessary\n"
        "- Combine the weather result with the flight information\n"
    ),
)
def weather_capability(
    step: PlanStep, state: dict, config: RunnableConfig
) -> CapabilityResult:
    messages: list[AnyMessage | Dict[str, Any]] = state.get("messages", [])

    agent = create_agent(
        model=mini_model,
        tools=weather_tools,
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
