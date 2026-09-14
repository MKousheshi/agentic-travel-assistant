# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Dependencies are managed with `uv` (Python 3.12). Dev tools (`pyright`, `ruff`, `pytest`) live in the `dev` dependency group, so always invoke them through `uv run` — they are not on the global PATH, and the system `pytest` is a different interpreter.

```bash
uv sync            # install deps incl. dev group
uv run api         # run the backend (FastAPI + SSE, auto-reload, port 8000)
uv run ui          # run the UI (thin Chainlit HTTP client, auto-reload, port 8001)

uv run ruff check src                     # lint
uv run ruff format src                    # format
uv run pyright src                        # type check

uv run pytest                             # all tests
uv run pytest tests/test_x.py::test_name  # single test
```

- The app is split into two processes: a FastAPI backend (`src/app/api/`) that owns the graph, the checkpointer, and the DB session, and a Chainlit UI (`src/app/ui/chainlit_app.py`) that is a pure HTTP/SSE client of it. Run both; the UI reads the backend's base URL from `API_BASE_URL` (default `http://localhost:8000`). `uv run api` and `uv run ui` are `[project.scripts]` entry points (`src/app/scripts.py`) that just `exec` the equivalent `uvicorn`/`chainlit` CLI invocations — the UI is pinned to port 8001 because Chainlit's own default (8000) collides with the API's.
- `tests/test_api.py` covers the backend's SSE protocol against a fake graph and fake session — no LLM calls and no `.env` required. `tests.md` is a manual scenario list (Persian prompts, expected results, pass/fail status) for the full LLM-backed flow, not automated tests.
- Lint/typecheck baseline is not clean (ruff reports ~179 issues, ~16 files unformatted; pyright ~55 errors). Don't mass-fix or reformat unrelated files as part of a feature change — check that your change doesn't add new errors in the files you touch.
- Configuration comes from `.env` (see `.env.example`) through `pydantic-settings` in `src/app/config.py`. `OPENAI_API_KEY`, `DB_PATH`, `LANGSMITH_API_KEY` and `OPENAI_BASE_URL` are required, and several modules read settings **at import time** (`chat_models.py` builds `ChatOpenAI` clients, `db/engine.py` creates the SQLite engine). Only the backend process needs these; the UI process needs none of them. Tests that import `app.*` need these env vars set (dummy values are fine for code that doesn't call the LLM).
- The SQLite database is `var/travel.sqlite` (airline demo dataset). Tables are modeled in `src/app/db/schemas.py`; there are no migrations.
- **Never run the app end-to-end against the real LLM to "verify" a change, and never drive it through a browser.** Starting `uvicorn`/`chainlit` and sending prompts through them burns the user's real `OPENAI_API_KEY` quota. `uv run pytest`, `ruff`, and `pyright` are the verification budget for automated changes; the user runs the app manually themselves when they want to see it work.

## Architecture

A LangGraph workflow that turns a user's travel request into a validated plan and runs it step by step against the airline DB. It has three phases: **plan → execute → synthesize**. The graph is wired in `src/app/graph/build_graph.py`, the nodes and routers are in `src/app/graph/nodes.py`, and the state is in `src/app/graph/state.py`. The graph runs entirely inside the FastAPI backend; the UI never imports it.

### Graph flow

`START` → `route_from_start` picks `execution` if `state["execution"]` exists (the user is resuming a paused run), otherwise `planning`.

1. **planning** (`create_plan`): the planner agent returns a `PlannerResponse` union. Either it's a `PlanResponse` (an `ExecutionPlan` of `PlanStep`s, each naming a `capability_id`) or a `ClarificationResponse`, which sets `plan=None` and goes to `exit` so the user can answer.
2. **verify-rules** (deterministic: non-empty plan, unique `step_id`, capability exists in the registry), then **verify-llm** (semantic `Feedback` from the evaluator agent). Failure sends the feedback back to `planning`. `retries` is capped by `max_planning_retries` (default 3), after which the graph exits.
3. **execution-init** calls `session.begin()` and creates a fresh `ExecutionState`.
4. **execution** runs one plan step per pass. It calls the capability with the conversation plus all earlier `StepResult`s and maps the `CapabilityResult` status (`success` / `failure` / `needs_information`) onto `ExecutionState.status`. `execution_router` loops back while the status is `running`. When the run ends, the router **commits on `completed` or rolls back on `failed`**, then goes to `synth`.
5. **synth** turns the results into a final answer with the synthesizer model, or passes through the failure or pending question. **exit** clears `execution` on completed/failed and keeps it on `waiting_for_user`.

Whatever a node writes to `user_message` is streamed as the SSE `message` event and shown as the final Chainlit message. Every other node output is streamed as an SSE `node` event; the UI renders each as an intermediate `cl.Step`, **except `synth` and `exit`** (see `_HIDDEN_STEP_NODES` in `chainlit_app.py`). `synth` streams its output live as `token` events before its own `node` event can fire (a node's `updates` chunk is only emitted once the node function returns, i.e. after the LLM call — and hence all its tokens — has finished), so by the time `node("synth")` and the always-trivial `node("exit")` arrive, the answer message already exists and their steps would render trailing after it instead of before. The backend still emits both faithfully; only this UI chooses not to render them.

### Backend API (`src/app/api/`)

Follows FastAPI's standard "bigger applications" layout — an app factory, one `APIRouter` per resource, and shared dependencies in their own module — so new routes have an obvious place to go as the backend grows:

- `server.py`: `create_app(graph=None, session_factory=None) -> FastAPI`, plus `app = create_app()` for `uv run api` / ASGI servers to import. Its `lifespan` calls `load_capabilities()` and builds the graph (with `MemorySaver`) and the DB session factory lazily, unless a fake graph/session_factory was injected (as the tests do); `create_app` itself registers `routers/health.py` and `routers/threads.py` via `include_router`.
- `deps.py`: `get_graph`, `get_lock`, `get_session` (each reads `request.app.state`; the latter two also take the `thread_id` path parameter, which FastAPI fills in for a dependency the same way it does for the endpoint) and the `GraphDep` / `LockDep` / `SessionDep` `Annotated[...]` aliases routers depend on. Per-`thread_id` state — one DB session and one `asyncio.Lock` — lives on `app.state`, so concurrent requests on the same thread serialize instead of racing the shared session and checkpoint.
- `routers/health.py`: `GET /health`.
- `routers/threads.py`: `POST /threads/{thread_id}/stream` (SSE, a native FastAPI async-generator endpoint via `response_class=EventSourceResponse`) and `DELETE /threads/{thread_id}` (idempotent, drops the session and the checkpoint thread).
- `schemas.py`: `RunRequest = MessageRequest | ResumeRequest`, a discriminated-by-shape union (each model sets `extra="forbid"`) rather than one model with two optional fields — a body with both or neither key fails Pydantic validation with a 422.
- `streaming.py`: `stream_run` drives `graph.astream(..., stream_mode=["updates", "messages"])` and turns each chunk into an SSE event — `node` (per-node output), `token` (streamed synthesizer output only, filtered by `metadata["langgraph_node"] == "synth"`), `interrupt`, `message` (the final `user_message`), `error`, and a closing `end`.

### Capabilities (plugin layer)

Each package in `src/app/capabilities/` has the same layout:
- `<name>.py`: the handler, registered with `@register_capability(id=..., description=...)`. The handler signature must be exactly `(step, state, config) -> CapabilityResult`. `CapabilityRegistry._validate_signature` checks this at import time and raises `TypeError` if it doesn't match. The handler builds a **sub-agent** (`create_agent` with the package's tools, `ToolStrategy(CapabilityResult)`, `recursion_limit=10`) and converts `GraphRecursionError` into a `CapabilityFailure`.
- `tools.py`: LangChain `@tool(args_schema=...)` functions. Tools read the DB session from `config["configurable"]["session"]` and return plain dicts.
- `services.py`: SQLModel queries that take a `Session`.

The capability `description` does real work: `registry.catalog()` injects it into the planner and validator prompts, so it determines what the planner thinks each capability can do.

`weather` is implemented but disabled: its decorator is commented out, and the OpenWeather client isn't connected to any API key setting.

### Non-obvious invariants

- **Capability registration must happen before `app.agents` is imported.** `app/agents.py` formats `PLANNER_PROMPT` / `VALIDATOR_PROMPT` from `registry.catalog()` when the module is imported. `app/api/server.py`'s `lifespan` calls `load_capabilities()` before importing `app.graph.build_graph`, for this reason. Importing `app.graph.build_graph` on its own (which is what the `langgraph.json` entry point does) leaves the registry empty, so the planner sees no capabilities and every step fails `verify-rules`.
- **Transactions belong to the graph, never to capabilities.** Each thread gets one `Session`, passed through `config["configurable"]["session"]`. Tools and services must not call `commit()` or `rollback()`. The whole plan is atomic.
- **Human-in-the-loop uses `interrupt()` inside tools** (booking and ticket deletes). The interrupt propagates out of the sub-agent into the outer graph, and `stream_run` turns it into an SSE `interrupt` event. The UI renders a `Confirmation` as Confirm/Cancel actions and resumes by posting `{"resume": {...}}`, which the backend turns into `Command(resume=...)`. Two consequences:
  - Never wrap `interrupt()` in a broad `try/except`.
  - On resume, LangGraph re-runs the node from the start, so all code before the `interrupt()` call (previews, lookups) must be idempotent and read-only.
- **The UI must never import backend modules** (`app.graph`, `app.agents`, `app.db`, `app.config`, `app.registry`). It only knows `chainlit`, `httpx`, `httpx_sse`, and the SSE event protocol above.
- Checkpointing uses in-memory `MemorySaver`, with one `thread_id` per chat (generated in the UI's `on_chat_start`). State doesn't survive a backend restart.
- Model selection is in `chat_models.py`: planner, validator, capability agents and synthesizer all currently use `gpt-4o-mini` through a configurable OpenAI-compatible `base_url`. Graph nodes are decorated with LangSmith `@traceable`.
- `SafeDateTime` in `db/schemas.py` exists because the dataset stores missing timestamps as `\N` or empty strings. Use it for any nullable datetime column.
