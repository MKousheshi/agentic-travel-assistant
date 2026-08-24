
from langchain_core.runnables import RunnableConfig

from app.models import PlanStep, CapabilityResult
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
def flight_capability(
    step: PlanStep, state: dict, config: RunnableConfig
) -> CapabilityResult:
    pass
