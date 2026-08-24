
from langchain_core.runnables import RunnableConfig

from app.models import PlanStep, CapabilityResult
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
def flight_capability(
    step: PlanStep, state: dict, config: RunnableConfig
) -> CapabilityResult:
    pass
