#!/usr/bin/env bash
# The only supported way to run tests/paid. These call the real LLM through
# your OPENAI_API_KEY and cost real money, so this refuses to run for an
# agent or a non-interactive shell, and makes a human type "yes" first.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

for var in CLAUDECODE CLAUDE_CODE_ENTRYPOINT AI_AGENT; do
  if [ -n "${!var:-}" ]; then
    echo "Refusing: \$$var is set, so this isn't a human at an interactive shell." >&2
    exit 1
  fi
done

if [ ! -t 0 ] || [ ! -t 1 ]; then
  echo "Refusing: stdin/stdout is not a TTY." >&2
  exit 1
fi

echo "tests/paid calls the real LLM through your OPENAI_API_KEY and spends real money." >&2
read -r -p "Type 'yes' to continue: " confirmation < /dev/tty
if [ "$confirmation" != "yes" ]; then
  echo "Aborted." >&2
  exit 1
fi

RUN_PAID_TESTS=1 uv run pytest tests/paid "$@"
