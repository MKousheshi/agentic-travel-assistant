
from langchain_core.runnables import RunnableConfig

from app.models import PlanStep, CapabilityResult
from app.registry import register_capability


@register_capability(
    id="flight",
    description=(
        "- Retrieve flights by ID or flight number\n"
        "- Find flights between departure and arrival airports\n"
        "- Show flight status\n"
        "- Analyze actual_departure and actual_arrival based on scheduled, delayed, cancelled, arrived, and status\n"
        "- Find the aircraft associated with a flight using aircraft_code\n"
        "- Analyze high-traffic routes and their associated revenue\n"
    ),
)
def flight_capability(step: PlanStep, state: dict, config: RunnableConfig) -> CapabilityResult:
    pass