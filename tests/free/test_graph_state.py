from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.graph.build_graph import build_graph
from app.graph.nodes import PLANNING_FAILED_MESSAGE, execute_plan
from app.graph.state import ExecutionState
from app.models import (
    CapabilityNeedsInformation,
    CapabilitySuccess,
    Clarification,
    ClarificationResponse,
    ExecutionPlan,
    Feedback,
    PlanResponse,
    PlanStep,
)
from app.prompts.planner import PLANNER_SYSTEM_PROMPT
from app.prompts.validator import VALIDATOR_SYSTEM_PROMPT
from app.registry import Capability, registry
from tests.free.test_api import FakeSession


class FakeStructuredAgent:
    """Stands in for `planner_agent`/`eval_agent`: returns scripted
    structured responses from a queue and records the messages it received."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.calls: list[list[Any]] = []

    def invoke(self, input_state: dict) -> dict:
        self.calls.append(list(input_state["messages"]))
        return {"structured_response": self._responses.pop(0)}


def make_plan(step_ids: list[int], capability_id: str = "fake") -> ExecutionPlan:
    return ExecutionPlan(
        user_query="do the thing",
        goal="do the thing",
        steps=[
            PlanStep(
                step_id=step_id,
                capability_id=capability_id,
                action=f"step {step_id}",
                goal=f"goal {step_id}",
                reason="because",
            )
            for step_id in step_ids
        ],
    )


def fake_synthesizer(content: str) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter([AIMessageChunk(content=content)]))


@pytest.fixture
def fake_capability():
    results: list[Any] = []

    def execute(step, state, config):
        return results.pop(0)

    capability = Capability(
        id="fake", description="A fake capability.", execute=execute
    )
    registry.register(capability)
    yield results
    registry.unregister("fake")


@pytest.fixture
def graph():
    return build_graph(MemorySaver())


def _config(thread_id: str, session: FakeSession) -> dict:
    return {"configurable": {"thread_id": thread_id, "session": session}}


def test_resumed_multi_step_plan_finishes(graph, monkeypatch, fake_capability):
    plan = make_plan([1, 2])
    planner = FakeStructuredAgent([PlanResponse(kind="plan", response=plan)])
    evaluator = FakeStructuredAgent([Feedback(validated=True, message="ok")])
    monkeypatch.setattr("app.graph.nodes.get_planner_agent", lambda: planner)
    monkeypatch.setattr("app.graph.nodes.get_eval_agent", lambda: evaluator)
    monkeypatch.setattr(
        "app.graph.nodes.get_synthesizer_model",
        lambda: fake_synthesizer("final answer"),
    )

    fake_capability.append(
        CapabilityNeedsInformation(
            message="need more info",
            missing_fields=["x"],
            question="What is x?",
        )
    )

    session = FakeSession()
    config = _config("t-resume", session)

    first = graph.invoke({"messages": [HumanMessage(content="do the thing")]}, config)
    assert first["user_message"] == "What is x?"
    assert first["plan"] is not None
    assert first["execution"] is not None
    assert first["execution"].status == "waiting_for_user"

    fake_capability.append(CapabilitySuccess(message="step 1 done", data={}))
    fake_capability.append(CapabilitySuccess(message="step 2 done", data={}))

    second = graph.invoke({"messages": [HumanMessage(content="x is 5")]}, config)
    assert second["user_message"] == "final answer"
    assert second["execution"] is None
    assert second["plan"] is None
    assert fake_capability == []  # both steps' scripted results were consumed
    assert session.commit_called is True


def test_execute_plan_does_not_alias_results(fake_capability):
    plan = make_plan([1])
    execution = ExecutionState()
    fake_capability.append(CapabilitySuccess(message="ok", data={}))

    out = execute_plan(
        {"messages": [], "plan": plan, "execution": execution},
        {"configurable": {}},
    )

    assert execution.results == []
    assert len(out["execution"].results) == 1


def test_state_cleared_after_completed_run(graph, monkeypatch, fake_capability):
    plan = make_plan([1])
    planner = FakeStructuredAgent(
        [
            PlanResponse(kind="plan", response=plan),
            ClarificationResponse(
                kind="clarification",
                response=Clarification(user_message="anything else?"),
            ),
        ]
    )
    evaluator = FakeStructuredAgent([Feedback(validated=True, message="ok")])
    monkeypatch.setattr("app.graph.nodes.get_planner_agent", lambda: planner)
    monkeypatch.setattr("app.graph.nodes.get_eval_agent", lambda: evaluator)
    monkeypatch.setattr(
        "app.graph.nodes.get_synthesizer_model",
        lambda: fake_synthesizer("final answer"),
    )
    fake_capability.append(CapabilitySuccess(message="done", data={}))

    session = FakeSession()
    config = _config("t-cleared", session)

    first = graph.invoke({"messages": [HumanMessage(content="do the thing")]}, config)
    assert first["plan"] is None
    assert first["feedback"] is None
    assert first["retries"] == 0

    second_message = HumanMessage(content="a brand new unrelated request")
    graph.invoke({"messages": [second_message]}, config)

    last_message = planner.calls[-1][-1]
    assert isinstance(last_message, HumanMessage)
    assert last_message.content == second_message.content


def test_retry_feedback_is_labelled(graph, monkeypatch, fake_capability):
    plan_v1 = make_plan([1])
    plan_v2 = make_plan([1, 2])
    planner = FakeStructuredAgent(
        [
            PlanResponse(kind="plan", response=plan_v1),
            PlanResponse(kind="plan", response=plan_v2),
        ]
    )
    evaluator = FakeStructuredAgent(
        [
            Feedback(validated=False, message="step 1 is missing a prerequisite"),
            Feedback(validated=True, message="ok"),
        ]
    )
    monkeypatch.setattr("app.graph.nodes.get_planner_agent", lambda: planner)
    monkeypatch.setattr("app.graph.nodes.get_eval_agent", lambda: evaluator)
    monkeypatch.setattr(
        "app.graph.nodes.get_synthesizer_model",
        lambda: fake_synthesizer("final answer"),
    )
    fake_capability.append(CapabilitySuccess(message="ok", data={}))
    fake_capability.append(CapabilitySuccess(message="ok", data={}))

    session = FakeSession()
    config = _config("t-retry", session)
    graph.invoke({"messages": [HumanMessage(content="do the thing")]}, config)

    assert len(planner.calls) == 2
    revision_message = planner.calls[1][-1]
    assert "[Plan validator feedback: internal, not written by the user]" in (
        revision_message.content
    )
    assert "step 1 is missing a prerequisite" in revision_message.content
    assert plan_v1.model_dump_json() in revision_message.content
    assert "validated=" not in revision_message.content


def test_planning_failure_answers_the_user(graph, monkeypatch):
    plan = make_plan([1])
    planner = FakeStructuredAgent(
        [PlanResponse(kind="plan", response=plan) for _ in range(3)]
    )
    evaluator = FakeStructuredAgent(
        [Feedback(validated=False, message="still wrong") for _ in range(3)]
    )
    monkeypatch.setattr("app.graph.nodes.get_planner_agent", lambda: planner)
    monkeypatch.setattr("app.graph.nodes.get_eval_agent", lambda: evaluator)

    session = FakeSession()
    config = _config("t-planning-failed", session)
    result = graph.invoke({"messages": [HumanMessage(content="do the thing")]}, config)

    assert len(planner.calls) == 3
    assert result["user_message"] == PLANNING_FAILED_MESSAGE
    assert any(
        isinstance(m, AIMessage) and m.content == PLANNING_FAILED_MESSAGE
        for m in result["messages"]
    )
    assert result["plan"] is None
    assert result["feedback"] is None
    assert result["retries"] == 0


def test_clarification_clears_state(graph, monkeypatch):
    planner = FakeStructuredAgent(
        [
            ClarificationResponse(
                kind="clarification",
                response=Clarification(user_message="which flight do you mean?"),
            )
        ]
    )
    monkeypatch.setattr("app.graph.nodes.get_planner_agent", lambda: planner)

    session = FakeSession()
    config = _config("t-clarify", session)
    result = graph.invoke({"messages": [HumanMessage(content="do the thing")]}, config)

    assert result["user_message"] == "which flight do you mean?"
    assert result["plan"] is None
    assert result["feedback"] is None


def test_planner_required_information_rule_has_no_duplicates_or_truncation():
    assert PLANNER_SYSTEM_PROMPT.count("proceed without it.") == 1
    assert "3 later capability step." not in PLANNER_SYSTEM_PROMPT
    assert (
        "3. The capability catalog explicitly declares it as an input"
        in PLANNER_SYSTEM_PROMPT
    )


def test_validator_no_longer_grants_inherent_domain_support():
    assert "inherently supported" not in VALIDATOR_SYSTEM_PROMPT


def test_prompts_format_without_keyerror():
    PLANNER_SYSTEM_PROMPT.format(capability_catalog="catalog", capability_ids="ids")
    VALIDATOR_SYSTEM_PROMPT.format(capability_catalog="catalog", capability_ids="ids")
