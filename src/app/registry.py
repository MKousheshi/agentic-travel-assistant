from dataclasses import dataclass
import importlib
import inspect
import pkgutil
from typing import Any, Callable, Dict, Protocol, TypeVar, runtime_checkable

from langchain_core.runnables import RunnableConfig
from app.models import PlanStep, CapabilityResult


@runtime_checkable
class CapabilityHandler(Protocol):
    def __call__(
        self,
        step: PlanStep,
        state: dict,
        config: RunnableConfig,
    ) -> CapabilityResult: ...


@dataclass
class Capability:
    id: str
    description: str
    execute: Callable[[PlanStep, dict, RunnableConfig], CapabilityResult]
    is_enabled: bool = True


F = TypeVar("F", bound=Callable[..., Any])
EXPECTED_PARAMS = ("step", "state", "config")


class CapabilityRegistry:
    def __init__(self) -> None:
        self._items: Dict[str, Capability] = {}

    def _validate_signature(self, func: Callable[..., Any]) -> None:
        sig = inspect.signature(func)
        params = list(sig.parameters.values())

        if len(params) != 3:
            raise TypeError(
                f"Handler '{func.__name__}' must accept exactly 3 parameters: "
                f"(step, state, config). Got {len(params)}."
            )

        param_names = tuple(p.name for p in params)
        if param_names != EXPECTED_PARAMS:
            raise TypeError(
                f"Handler '{func.__name__}' parameter names must be {EXPECTED_PARAMS}. "
                f"Got {param_names}."
            )

        if any(
            p.kind not in (inspect.Parameter.POSITIONAL_OR_KEYWORD,) for p in params
        ):
            raise TypeError(
                f"Handler '{func.__name__}' must use regular positional parameters only."
            )

        hints = inspect.get_annotations(func, eval_str=True)
        if hints.get("return") is not CapabilityResult:
            raise TypeError(f"Handler '{func.__name__}' must return CapabilityResult.")

    def register(self, capability: Capability) -> None:
        if capability.id in self._items:
            raise ValueError(
                f"Capability with ID '{capability.id}' is already registered."
            )
        self._items[capability.id] = capability

    def register_capability(
        self,
        id: str,
        description: str,
        is_enabled: bool = True,
    ) -> Callable[[F], F]:
        def decorator(func: F) -> F:
            if id in self._items:
                raise ValueError(f"Capability with ID '{id}' is already registered.")

            self._validate_signature(func)

            capability = Capability(
                id=id,
                description=description.strip(),
                execute=func,
                is_enabled=is_enabled,
            )
            self._items[id] = capability
            return func

        return decorator

    def discover(self, package: str | Any) -> None:
        """
        Recursively imports all modules and subpackages under the given package.

        Example:
            registry.discover("app.capabilities")
        """
        if isinstance(package, str):
            package = importlib.import_module(package)

        if not hasattr(package, "__path__"):
            raise TypeError(
                f"'{package.__name__}' is not a package and cannot be discovered."
            )

        # Import the package itself first
        importlib.import_module(package.__name__)

        # Recursively walk all nested modules and subpackages
        for _, module_name, is_pkg in pkgutil.walk_packages(
            package.__path__,
            prefix=f"{package.__name__}.",
        ):
            importlib.import_module(module_name)

    def unregister(self, capability_id: str) -> None:
        self._items.pop(capability_id, None)

    def get(self, capability_id: str) -> Capability | None:
        return self._items.get(capability_id)

    def all(self) -> list[Capability]:
        return list(self._items.values())

    def has(self, capability_id: str) -> bool:
        return capability_id in self._items

    def catalog(self) -> str:
        lines = []
        for capability in self._items.values():
            if capability.is_enabled:
                lines.append(
                    f"Capability ID: {capability.id}\n"
                    f"Description:\n {capability.description}"
                )
        return "\n".join(lines)


registry = CapabilityRegistry()
register_capability = registry.register_capability


def load_capabilities() -> None:
    registry.discover("app.capabilities")
