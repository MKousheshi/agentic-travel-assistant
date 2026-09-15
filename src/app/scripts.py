import os


def run_api() -> None:
    """Entry point for `uv run api`: the FastAPI backend, with auto-reload."""
    args = ["uvicorn", "app.api.server:app", "--reload"]
    if os.path.exists(".env"):
        # uvicorn loads this with python-dotenv, exporting LANGSMITH_* (and
        # everything else in .env) into the process environment. Settings
        # itself never does this: pydantic-settings reads .env directly into
        # Settings without touching os.environ, so LangSmith (which only
        # reads os.environ) would otherwise never see LANGSMITH_TRACING.
        args += ["--env-file", ".env"]
    os.execvp("uvicorn", args)


def run_ui() -> None:
    """Entry point for `uv run ui`: the Chainlit UI, with auto-reload.

    Chainlit's own default port (8000) collides with the API's default port,
    so this pins the UI to 8001 instead.
    """
    os.execvp(
        "chainlit",
        ["chainlit", "run", "src/app/ui/chainlit_app.py", "-w", "--port", "8001"],
    )
