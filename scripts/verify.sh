#!/usr/bin/env bash
# One command that checks an agent's work before it's handed back for review:
# format, lint, type-check (pyright + mypy), security scan, and the free test
# suite. Every step runs even if an earlier one fails, so a single run
# reports everything wrong at once instead of stopping at the first failure.
#
# tests/paid is never invoked from here — see tests/paid/conftest.py and
# scripts/test-paid.sh. This script only runs read-only git commands.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

declare -a STEP_NAMES=()
declare -a STEP_STATUS=()

record() {
    STEP_NAMES+=("$1")
    STEP_STATUS+=("$2")
}

# Content hashes, not `git status --porcelain`: a file the agent already
# modified before this script ran keeps the same porcelain status letter
# (` M`) even after the formatter/linter touches it again, so a porcelain
# diff misses exactly the "agent edits a file, formatter touches it" case
# this report exists to catch. Hashing every tracked *.py file's actual
# content catches that case too, at the cost of also catching an untracked
# file's content moving (which porcelain would have caught anyway).
hash_py_files() {
    find src tests -type f -name '*.py' -print0 | sort -z | xargs -0 sha256sum 2>/dev/null
}

before_autofix=$(hash_py_files)

echo "== 1/7: format (autofix) =="
uv run --locked ruff format src tests
record "format" $?

echo
echo "== 2/7: lint (safe autofix) =="
uv run --locked ruff check --fix src tests
record "lint" $?

after_autofix=$(hash_py_files)
if [ "$before_autofix" != "$after_autofix" ]; then
    echo
    echo "Autofix changed these files - review them:"
    diff <(echo "$before_autofix") <(echo "$after_autofix") | grep -E '^[<>]' | awk '{print $NF}' | sort -u | sed 's/^/  /'
fi

echo
echo "== 3/7: pyright =="
uv run --locked pyright
record "pyright" $?

echo
echo "== 4/7: mypy =="
uv run --locked mypy
record "mypy" $?

echo
echo "== 5/7: bandit =="
uv run --locked bandit -c pyproject.toml -r src --severity-level medium --confidence-level medium
record "bandit" $?

echo
echo "== 6/7: pip-audit =="
# --vulnerability-service osv: pip-audit's default "pypi" service lags OSV
# for freshly-published advisories (verified during this pipeline's build:
# it missed a then-current CRITICAL chainlit CVE that OSV already had). The
# reachability probe below therefore checks OSV's own API host, not PyPI,
# and uses bash's /dev/tcp instead of curl so a missing `curl` binary can't
# make this silently SKIP.
if (exec 3<>"/dev/tcp/api.osv.dev/443") 2>/dev/null; then
    exec 3>&- 3<&-
    tmp_requirements=$(mktemp)
    trap 'rm -f "$tmp_requirements"' EXIT
    if uv export --frozen --all-groups --no-emit-project --format requirements.txt -o "$tmp_requirements" >/dev/null; then  uv run --locked pip-audit --disable-pip --no-deps --vulnerability-service osv -r "$tmp_requirements"
        record "pip-audit" $?
    else
        echo "uv export failed; cannot run pip-audit" >&2
        record "pip-audit" 1
    fi
else
    echo "SKIP (api.osv.dev unreachable)"
    record "pip-audit" "SKIP"
fi

echo
echo "== 7/7: free tests =="
uv run --locked pytest tests/free
record "free tests" $?

echo
echo "== Summary =="
overall=0
for i in "${!STEP_NAMES[@]}"; do
    status="${STEP_STATUS[$i]}"
    if [ "$status" = "SKIP" ]; then
        result="SKIP"
        elif [ "$status" = "0" ]; then
        result="PASS"
    else
        result="FAIL"
        overall=1
    fi
    printf "  %-16s %s\n" "${STEP_NAMES[$i]}" "$result"
done

exit $overall