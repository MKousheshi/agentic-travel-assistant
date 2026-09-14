"""One real end-to-end run, taken from scenario 1 in tests.md.

Calls the real LLM through `create_app()`'s default (non-fake) graph and
session factory. Manual-only: see `tests/paid/conftest.py` and
`scripts/test-paid.sh`.
"""

import httpx_sse
from fastapi.testclient import TestClient

from app.api.server import create_app


def test_booking_lookup_mentions_reference_and_amount():
    app = create_app()
    events = []
    with (
        TestClient(app) as client,
        httpx_sse.connect_sse(
            client,  # type: ignore[arg-type]
            "POST",
            "/threads/t-paid-smoke/stream",
            json={"message": "اطلاعات booking  00044E  را نشان بده."},
        ) as event_source,
    ):
        event_source.response.raise_for_status()
        for sse in event_source.iter_sse():
            events.append((sse.event, sse.json()))

    message = next(data["content"] for event, data in events if event == "message")
    assert "00044E" in message
    assert "140100" in message
