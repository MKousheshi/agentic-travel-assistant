import os

import pytest

# Env vars Claude Code (and, by convention, other coding agents) set in every
# shell it runs commands in. Their presence means a human is not typing this
# command at an interactive prompt.
_AGENT_ENV_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT")

GUARD_MESSAGE = (
    "Refusing to collect tests/paid: these tests call the real LLM and cost "
    "real money. Run them only via `./scripts/test-paid.sh`, never directly "
    "and never from an agent."
)

if os.environ.get("RUN_PAID_TESTS") != "1" or any(
    os.environ.get(var) for var in _AGENT_ENV_VARS
):
    pytest.exit(GUARD_MESSAGE, returncode=2)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.paid)
