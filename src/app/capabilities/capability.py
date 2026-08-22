from typing import Dict

from langchain_core.messages import AnyMessage
from langsmith import traceable
from pydantic import BaseModel, Field
from app.models import PlanStep, CapabilityResult, CapabilityContext


class dict(BaseModel):
    messages: list[AnyMessage] = Field(default_factory=list)


class Capability(BaseModel):
    id: str
    description: str
    is_enabled: bool = Field(default=True)

    def execute(self, step: PlanStep, context: CapabilityContext) -> CapabilityResult:
        raise NotImplementedError


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: Dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        self._items[capability.id] = capability

    def unregister(self, capability_id: str) -> None:
        self._items.pop(capability_id, None)

    def get(self, capability_id: str) -> Capability | None:
        return self._items.get(capability_id)

    def all(self) -> list[Capability]:
        return list(self._items.values())

    def has(self, capability_id: str) -> bool:
        return capability_id in self._items

    def catalog(self) -> str:
        """
        This is the only information about capabilities
        given to the planner.
        """
        lines = []

        for capability in self._items.values():
            if capability.is_enabled:
                lines.append(
                    f"- Capability ID: {capability.id}\n  Description: {capability.description}"
                )

        return "\n".join(lines)
