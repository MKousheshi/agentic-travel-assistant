from datetime import date
from typing import Any, Dict

from langchain.agents import create_agent
from langchain.agents.middleware.types import InputAgentState
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import AnyMessage
from langchain_core.runnables import RunnableConfig
from langsmith import traceable

from app.capabilities.capability import Capability, dict
from app.models import PlanStep, CapabilityResult, CapabilityContext
from app.prompts.prompts import CAPABILITY_PROMPT
from app.capabilities.booking.tools import booking_tools
from app.chat_models import mini_model


class BookingCapability(Capability):
    id: str = "booking"
    description: str = (
        "- Retrieve bookings by reference\n"
        "- Search bookings by date or date range\n"
        "- Calculate booking counts and revenue for a period\n"
        "- Create new bookings with a reference, date, and total amount\n"
        "- Delete bookings"
    )

    def execute(
        self, step: PlanStep, context: CapabilityContext, config: RunnableConfig
    ) -> CapabilityResult:
        return self._execute(step, context, config)

    @traceable
    def _execute(
        self, step: PlanStep, context: CapabilityContext, config: RunnableConfig
    ) -> CapabilityResult:
        messages: list[AnyMessage | Dict[str, Any]] = [*context.messages]
        agent = create_agent(
            model=mini_model,
            tools=booking_tools,
            system_prompt=CAPABILITY_PROMPT.format(
                current_date=date.today().isoformat(),
                action=step.action,
                goal=step.goal,
            ),
            response_format=ToolStrategy(CapabilityResult),
        )
        result = agent.invoke(
            InputAgentState(messages=messages),
            config=config,
        )
        response: CapabilityResult = result["structured_response"]
        return response
