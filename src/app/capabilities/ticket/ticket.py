from langchain_core.runnables import RunnableConfig

from app.models import PlanStep, CapabilityResult
from app.registry import register_capability


@register_capability(
    id="ticket",
    description=(
        "- Retrieve ticket information using ticket_no\n"
        "- Search for tickets using passenger_id\n"
        "- Find the flights associated with a ticket through ticket_flights\n"
        "- Create a new ticket for an existing book_ref\n"
        "- Delete a ticket after performing a dependency check\n"
        "- Analyze fare_conditions and amount\n"
    ),
)
def flight_capability(
    step: PlanStep, state: dict, config: RunnableConfig
) -> CapabilityResult:
    pass
