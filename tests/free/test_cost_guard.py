"""Confirms tests/paid refuses to collect without an explicit human opt-in.

Runs a real pytest subprocess against tests/paid, but the guard in
tests/paid/conftest.py exits before collection starts, so this never touches
the network or the real LLM.
"""

import os
import subprocess
import sys
from pathlib import Path

# Kept in sync with tests/paid/conftest.py's GUARD_MESSAGE. Not imported from
# there: importing that module runs its guard check immediately (it may call
# `pytest.exit`, which would abort this very test run).
GUARD_MESSAGE = (
    "Refusing to collect tests/paid: these tests call the real LLM and cost "
    "real money. Run them only via `./scripts/test-paid.sh`, never directly "
    "and never from an agent."
)

# Repo root, regardless of the cwd this test itself was started from.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_paid(extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = {**os.environ, **extra_env}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/paid"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=_REPO_ROOT,
    )


def test_paid_tests_refuse_without_opt_in():
    result = _run_paid({"RUN_PAID_TESTS": ""})
    assert result.returncode != 0
    assert GUARD_MESSAGE in result.stdout + result.stderr


def test_paid_tests_refuse_for_an_agent_even_with_opt_in():
    result = _run_paid({"RUN_PAID_TESTS": "1", "CLAUDECODE": "1"})
    assert result.returncode != 0
    assert GUARD_MESSAGE in result.stdout + result.stderr
