import os


def run_api() -> None:
    """Entry point for `uv run api`: the FastAPI backend, with auto-reload."""
    os.execvp("uvicorn", ["uvicorn", "app.api.server:app", "--reload"])


def run_ui() -> None:
    """Entry point for `uv run ui`: the Chainlit UI, with auto-reload.

    Chainlit's own default port (8000) collides with the API's default port,
    so this pins the UI to 8001 instead.
    """
    os.execvp(
        "chainlit",
        ["chainlit", "run", "src/app/ui/chainlit_app.py", "-w", "--port", "8001"],
    )
