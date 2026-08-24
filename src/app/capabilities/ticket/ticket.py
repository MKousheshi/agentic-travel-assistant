from datetime import date
from typing import Any, Dict

from langchain.agents import create_agent
from langchain.agents.middleware.types import InputAgentState
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError

from app.models import PlanStep, CapabilityResult, CapabilityFailure
from app.prompts.capability import CAPABILITY_PROMPT
from app.capabilities.ticket.tools import ticket_tools
from app.chat_models import mini_model
from app.registry import register_capability


@register_capability(
    id="ticket",
    description=(
        "- Retrieve ticket information using ticket_no\n"
        "- Search for tickets using passenger_id\n"
        "- Find the flights associated with a ticket\n"
        "- Create a new ticket for an existing book_ref\n"
        "- Delete a ticket\n"
        "- Analyze fare_conditions and amount\n"
    ),
)
def flight_capability(
    step: PlanStep, state: dict, config: RunnableConfig
) -> CapabilityResult:
    messages: list[AnyMessage | Dict[str, Any]] = state.get("messages", [])

    agent = create_agent(
        model=mini_model,
        tools=ticket_tools,
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
