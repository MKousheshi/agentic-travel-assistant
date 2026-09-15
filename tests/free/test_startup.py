import importlib
import subprocess
import sys

import pytest
from langgraph.errors import GraphRecursionError

from app.config import Settings
from app.models import CapabilityFailure, PlanStep
from app.registry import CapabilityRegistry


def test_agent_factories_refuse_an_empty_registry(monkeypatch):
    import app.agents as agents_module

    monkeypatch.setattr(agents_module, "registry", CapabilityRegistry())
    agents_module.get_planner_agent.cache_clear()
    agents_module.get_eval_agent.cache_clear()

    with pytest.raises(RuntimeError):
        agents_module.get_planner_agent()
    with pytest.raises(RuntimeError):
        agents_module.get_eval_agent()

    agents_module.get_planner_agent.cache_clear()
    agents_module.get_eval_agent.cache_clear()


def test_importing_modules_does_not_construct_clients():
    # A fresh interpreter, not this test process: by the time this test runs,
    # other free tests have already imported these modules, so import
    # statements here would be no-ops against an already-populated
    # sys.modules and prove nothing either way.
    script = (
        "import app.graph.build_graph, app.graph.nodes, app.agents, "
        "app.db.engine, app.graph.studio\n"
        "from app.chat_models import get_chat_model\n"
        "from app.db.engine import get_engine\n"
        "assert get_chat_model.cache_info().currsize == 0\n"
        "assert get_engine.cache_info().currsize == 0\n"
        "assert not hasattr(app.graph.build_graph, 'graph')\n"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "OPENAI_API_KEY": "sk-free-tests-dummy",
        "OPENAI_BASE_URL": "http://127.0.0.1:9/v1",
        "DB_PATH": "var/travel.sqlite",
    }
    subprocess.run([sys.executable, "-c", script], env=env, check=True, timeout=30)


def test_studio_factory_loads_capabilities():
    from app.graph.studio import make_graph

    graph = make_graph()
    nodes = graph.get_graph().nodes

    assert "planning" in nodes
    assert "execution" in nodes

    from app.registry import registry

    assert registry.has("booking")


def test_airport_weather_location_operation_is_removed():
    from app.capabilities.airport.tools import airport_tools
    from app.registry import load_capabilities, registry

    assert "resolve_weather_location" not in [t.name for t in airport_tools]

    load_capabilities()
    airport = registry.get("airport")
    assert airport is not None
    assert "Weather" not in airport.description


def test_langsmith_api_key_is_optional(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert settings.langsmith_api_key is None


CAPABILITY_MODULES = {
    "booking": ("app.capabilities.booking.booking", "booking_capability"),
    "flight": ("app.capabilities.flight.flight", "flight_capability"),
    "ticket": ("app.capabilities.ticket.ticket", "ticket_capability"),
    "airport": ("app.capabilities.airport.airport", "airport_capability"),
}


class _RaisingAgent:
    def invoke(self, *args, **kwargs):
        raise GraphRecursionError(
            "Recursion limit of 10 reached without hitting a stop condition. "
            "See https://langchain-ai.github.io/langgraph/troubleshooting/errors/GRAPH_RECURSION_LIMIT"
        )


@pytest.mark.parametrize("capability_id", list(CAPABILITY_MODULES))
def test_recursion_failure_message_is_sanitized(monkeypatch, capability_id):
    module_path, func_name = CAPABILITY_MODULES[capability_id]
    module = importlib.import_module(module_path)

    monkeypatch.setattr(module, "create_agent", lambda **kwargs: _RaisingAgent())

    handler = getattr(module, func_name)
    step = PlanStep(
        step_id=1, capability_id=capability_id, action="do it", goal="g", reason="r"
    )
    result = handler(step, {"messages": []}, {"configurable": {}})

    assert isinstance(result, CapabilityFailure)
    assert result.reason == "recursion_limit_exceeded"
    assert "Recursion limit" not in result.message
    assert "http" not in result.message


def test_run_api_passes_env_file_only_when_it_exists(monkeypatch, tmp_path):
    from app import scripts

    captured: dict = {}

    def fake_execvp(file, args):
        captured["file"] = file
        captured["args"] = args

    monkeypatch.setattr(scripts.os, "execvp", fake_execvp)
    monkeypatch.chdir(tmp_path)

    scripts.run_api()
    assert "--env-file" not in captured["args"]

    (tmp_path / ".env").write_text("")
    scripts.run_api()
    assert "--env-file" in captured["args"]
    assert ".env" in captured["args"]
