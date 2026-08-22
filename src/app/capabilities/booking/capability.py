from datetime import date

from langchain.agents import create_agent
from langchain.agents.middleware.types import InputAgentState

from app.capabilities.capability import Capability, CapabilityState
from app.models import PlanStep, AgentResponse
from app.prompts.prompts import CAPABILITY_PROMPT
from app.capabilities.booking.tools import booking_tools
from app.chat_models import mini_model


class BookingCapability(Capability):
    id: str = "booking"
    description: str = (
        "Retrieve bookings by reference, search bookings by date or date range, "
        "calculate booking counts and revenue for a period, "
        "create new bookings with a reference, date, and total amount, and "
        "delete bookings after checking dependencies."
    )

    def execute(self, plan_step: PlanStep, state: CapabilityState) -> dict:
        messages = state["messages"]
        agent = create_agent(
            model=mini_model,
            tools=booking_tools,
            system_prompt=CAPABILITY_PROMPT.format(
                current_date=date.today().isoformat(),
                action=plan_step.action,
                goal=plan_step.goal,
            ),
            response_format=AgentResponse,
        )
        result = agent.invoke(InputAgentState(messages=messages))
        response: AgentResponse = result["structured_response"]
        return {"user_message": response.response}
