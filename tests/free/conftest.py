import os

# Set before any `app.*` module is imported, so that an accidental real LLM
# call from a free test fails fast (connection refused) instead of spending
# money. A hard assignment, not `setdefault`, because pydantic-settings lets
# env vars win over `.env` regardless of what's already in the process.
os.environ["OPENAI_API_KEY"] = "sk-free-tests-dummy"
os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:9/v1"
os.environ["LANGSMITH_API_KEY"] = "dummy"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ.setdefault("DB_PATH", "var/travel.sqlite")
