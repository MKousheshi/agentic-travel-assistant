import threading
import time
from typing import Annotated, Any, Literal, Required, TypedDict

import httpx_sse
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from app.api.server import create_app


class FakeState(TypedDict, total=False):
    messages: Required[Annotated[list, add_messages]]
    user_message: str


def _route_start(state: FakeState) -> Literal["ask", "synth"]:
    last = state["messages"][-1]
    if isinstance(last, HumanMessage) and last.content == "please confirm":
        return "ask"
    return "synth"


def _ask(state: FakeState) -> dict:
    value = interrupt({"message": "Proceed?", "data": {"amount": 10}})
    return {"messages": [HumanMessage(content=f"resumed with {value}")]}


def _synth(state: FakeState) -> dict:
    last_human = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        "",
    )
    content = f"answer for: {last_human}"
    model = GenericFakeChatModel(messages=iter([AIMessageChunk(content=content)]))
    response = model.invoke(state["messages"])
    return {"user_message": response.content, "messages": [response]}


def build_fake_graph():
    graph = StateGraph(FakeState)
    graph.add_node("ask", _ask)
    graph.add_node("synth", _synth)
    graph.add_conditional_edges(START, _route_start, {"ask": "ask", "synth": "synth"})
    graph.add_edge("ask", "synth")
    graph.add_edge("synth", END)
    return graph.compile(checkpointer=MemorySaver())


class FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.rollback_called = False
        self._in_transaction = False

    def in_transaction(self) -> bool:
        return self._in_transaction

    def begin(self) -> None:
        self._in_transaction = True

    def commit(self) -> None:
        self._in_transaction = False

    def rollback(self) -> None:
        self._in_transaction = False
        self.rollback_called = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def app_and_graph():
    graph = build_fake_graph()
    app = create_app(graph=graph, session_factory=FakeSession)
    with TestClient(app) as client:
        yield client, app, graph


def _collect_events(client: TestClient, thread_id: str, body: dict[str, Any]):
    events = []
    # TestClient subclasses starlette's vendored httpx client, which pyright
    # doesn't see as an `httpx.Client`; it is one at runtime.
    with httpx_sse.connect_sse(
        client,  # type: ignore[arg-type]
        "POST",
        f"/threads/{thread_id}/stream",
        json=body,
    ) as event_source:
        event_source.response.raise_for_status()
        for sse in event_source.iter_sse():
            events.append((sse.event, sse.json()))
    return events


def test_health(app_and_graph):
    client, _, _ = app_and_graph
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_message_stream_emits_tokens_and_final_message(app_and_graph):
    client, _, _ = app_and_graph
    events = _collect_events(client, "t-message", {"message": "hi"})

    kinds = [event for event, _ in events]
    assert "node" in kinds
    assert "token" in kinds
    assert kinds[-2:] == ["message", "end"]

    tokens = "".join(data["content"] for event, data in events if event == "token")
    assert tokens == "answer for: hi"

    message_data = next(data for event, data in events if event == "message")
    assert message_data["content"] == "answer for: hi"

    end_data = next(data for event, data in events if event == "end")
    assert end_data == {"interrupted": False}


def test_interrupt_then_resume_completes_with_resumed_value(app_and_graph):
    client, _, _ = app_and_graph
    thread_id = "t-interrupt"

    first_events = _collect_events(client, thread_id, {"message": "please confirm"})
    assert [event for event, _ in first_events] == ["interrupt", "end"]
    interrupt_data = first_events[0][1]
    assert interrupt_data["value"] == {"message": "Proceed?", "data": {"amount": 10}}
    assert first_events[1][1] == {"interrupted": True}

    resume_events = _collect_events(client, thread_id, {"resume": {"confirmed": True}})
    message_data = next(data for event, data in resume_events if event == "message")
    assert "resumed with" in message_data["content"]
    assert "True" in message_data["content"]
    assert resume_events[-1][1] == {"interrupted": False}


def test_resume_with_no_pending_interrupt_emits_error(app_and_graph):
    client, _, _ = app_and_graph
    events = _collect_events(client, "t-no-interrupt", {"resume": {"confirmed": True}})
    assert [event for event, _ in events] == ["error", "end"]
    assert events[1][1] == {"interrupted": False}


def test_delete_clears_checkpoint_and_closes_session(app_and_graph):
    client, app, graph = app_and_graph
    thread_id = "t-delete"

    _collect_events(client, thread_id, {"message": "hi"})
    session = app.state.sessions[thread_id]
    assert session.closed is False

    response = client.delete(f"/threads/{thread_id}")
    assert response.status_code == 204
    assert session.closed is True
    assert thread_id not in app.state.sessions

    config = {"configurable": {"thread_id": thread_id}}
    assert graph.get_state(config).values == {}

    # Idempotent: deleting again does not error.
    response = client.delete(f"/threads/{thread_id}")
    assert response.status_code == 204


def test_body_with_both_or_neither_field_is_rejected(app_and_graph):
    client, _, _ = app_and_graph
    response = client.post("/threads/t-invalid/stream", json={})
    assert response.status_code == 422

    response = client.post(
        "/threads/t-invalid/stream",
        json={"message": "hi", "resume": {"confirmed": True}},
    )
    assert response.status_code == 422


def _raising_node(state: FakeState) -> dict:
    raise RuntimeError("boom")


def build_raising_graph():
    graph = StateGraph(FakeState)
    graph.add_node("raise", _raising_node)
    graph.add_edge(START, "raise")
    graph.add_edge("raise", END)
    return graph.compile(checkpointer=MemorySaver())


def test_graph_error_emits_error_event_and_rolls_back():
    graph = build_raising_graph()
    sessions: list[FakeSession] = []

    def session_factory() -> FakeSession:
        # Simulate a transaction already begun by an earlier node (as
        # execution-init does in the real graph) before the failure.
        session = FakeSession()
        session.begin()
        sessions.append(session)
        return session

    app = create_app(graph=graph, session_factory=session_factory)
    with TestClient(app) as client:
        events = _collect_events(client, "t-error", {"message": "hi"})

    assert [event for event, _ in events] == ["error", "end"]
    assert "boom" in events[0][1]["detail"]
    assert events[1][1] == {"interrupted": False}
    assert sessions[0].rollback_called is True
    assert sessions[0].in_transaction() is False


def _other_llm_node(state: FakeState) -> dict:
    model = GenericFakeChatModel(
        messages=iter([AIMessageChunk(content="PLANNER_OUTPUT")])
    )
    model.invoke(state["messages"])
    return {}


def build_token_filter_graph():
    graph = StateGraph(FakeState)
    graph.add_node("other", _other_llm_node)
    graph.add_node("synth", _synth)
    graph.add_edge(START, "other")
    graph.add_edge("other", "synth")
    graph.add_edge("synth", END)
    return graph.compile(checkpointer=MemorySaver())


def test_token_events_only_come_from_synth_node():
    graph = build_token_filter_graph()
    app = create_app(graph=graph, session_factory=FakeSession)
    with TestClient(app) as client:
        events = _collect_events(client, "t-token-filter", {"message": "hi"})

    tokens = "".join(data["content"] for event, data in events if event == "token")
    assert "PLANNER_OUTPUT" not in tokens
    assert tokens == "answer for: hi"


def _slow_node(state: FakeState, log: list[tuple[str, float]]) -> dict:
    log.append(("start", time.monotonic()))
    time.sleep(0.15)
    log.append(("end", time.monotonic()))
    return {"user_message": "done", "messages": [HumanMessage(content="done")]}


def build_slow_graph(log: list[tuple[str, float]]):
    def slow(state: FakeState) -> dict:
        return _slow_node(state, log)

    graph = StateGraph(FakeState)
    graph.add_node("slow", slow)
    graph.add_edge(START, "slow")
    graph.add_edge("slow", END)
    return graph.compile(checkpointer=MemorySaver())


def test_concurrent_requests_on_same_thread_are_serialized():
    log: list[tuple[str, float]] = []
    graph = build_slow_graph(log)
    app = create_app(graph=graph, session_factory=FakeSession)

    with TestClient(app) as client:
        thread_id = "t-concurrent"

        def run() -> None:
            _collect_events(client, thread_id, {"message": "hi"})

        first = threading.Thread(target=run)
        second = threading.Thread(target=run)
        first.start()
        time.sleep(0.05)  # let the first request's node start before the second
        second.start()
        first.join()
        second.join()

    assert len(log) == 4
    starts = sorted(t for kind, t in log if kind == "start")
    ends = sorted(t for kind, t in log if kind == "end")
    # If the two runs were serialized, the second one only starts after the
    # first one's node finished.
    assert starts[1] >= ends[0]
