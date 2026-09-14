# Agentic Travel Assistant

An agentic workflow system for an airline/travel domain that handles natural-language user queries by planning the required actions, executing them through available system capabilities, and synthesizing a unified final response.

The system turns ambiguous, multi-step requests (for example, *"find flight PG0405, where does it land, and what is the weather there?"*) into a validated, transactionally-safe sequence of domain actions run against an airline database, with human-in-the-loop confirmation for risky operations.

## Technology Stack

- **Language:** Python 3.12 (pinned via `.python-version`)
- **Orchestration:** LangGraph (`StateGraph`, `MemorySaver` checkpointer, `interrupt` / `Command` for human-in-the-loop)
- **Agents & LLM:** LangChain (`create_agent`, `ToolStrategy` structured output), `langchain-openai` (OpenAI `gpt-4o` / `gpt-4o-mini`)
- **Validation & Config:** Pydantic v2 (structured outputs and plan validation), `pydantic-settings` (`SecretStr` secret handling)
- **Data & Persistence:** SQLModel / SQLAlchemy 2.0 over SQLite (8 relational tables)
- **UI:** Chainlit chat application
- **Observability:** LangSmith tracing (`@traceable` on every graph node)
- **Tooling:** `uv` for dependency and environment management, LangGraph CLI (`langgraph.json`)

## Project Metrics

| Metric                            | Value                                                                                                                                 |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Graph nodes / conditional routers | 7 nodes, 4 routers                                                                                                                    |
| Capabilities (sub-agents)         | 5 implemented (`flight`, `booking`, `ticket`, `airport`, `weather`); 4 registered by default                                |
| Domain tools                      | 25 LangChain tools, each with a dedicated Pydantic`args_schema`                                                                     |
| Database tables                   | 8 (`aircrafts_data`, `airports_data`, `bookings`, `tickets`, `flights`, `seats`, `ticket_flights`, `boarding_passes`) |
| Planning retries                  | up to 3 before graceful exit                                                                                                          |

## Brief Architecture Description

The project is built around a LangGraph workflow with three main phases:

1. **Planning**
2. **Execution**
3. **Synthesis**

A user message first enters the planning phase. The planner uses an LLM and structured Pydantic output to create an `ExecutionPlan` based on the user’s request and the available capabilities.

The generated plan is validated by two evaluators:

- A **rule-based evaluator**, which verifies structural and system-level constraints.
- An **LLM evaluator**, which verifies whether the plan is semantically appropriate for the user’s goal.

If the plan is invalid, the planner can retry up to a limited number of attempts. If the system needs additional user information at any point, it pauses the workflow and requests clarification.

After a valid plan is produced, its steps are executed sequentially through registered capabilities. The execution phase runs inside a database transaction to preserve atomicity. Finally, the synthesis phase combines successful step results into one response, or reports the failure if execution could not be completed.

The main project modules are organized as follows:

```text
app/
├── api/
├── capabilities/
│   ├── airport/
│   ├── booking/
│   ├── flight/
│   ├── ticket/
│   └── weather/
├── db/
├── graph/
├── prompts/
└── ui/
```

- `api/`: FastAPI backend — owns the graph, checkpointer, and DB sessions, and streams the run over SSE.
- `capabilities/`: Domain-specific packages that expose actions the agent can perform.
- `db/`: Database setup and shared persistence infrastructure.
- `graph/`: LangGraph workflow, nodes, transitions, and execution control flow.
- `prompts/`: System prompts used by the planner, evaluators, and response synthesis stages.
- `ui/`: Chainlit application — a thin HTTP/SSE client of the backend, with no dependency on the graph, DB, or config.

## Architecture Diagram

![Architecture Diagram](/workflow.png)

## Agent / Tool / Service Boundaries

The system separates orchestration from domain-specific business logic.

### Workflow / Agent Layer

The LangGraph workflow is responsible for:

- Receiving and managing user messages.
- Generating and evaluating execution plans.
- Routing plan steps to the appropriate capability.
- Managing planning retries.
- Managing workflow state transitions.
- Starting, committing, and rolling back the shared database transaction.
- Pausing execution when user clarification or confirmation is required.
- Synthesizing the final response.

### Capability Layer

Implemented capabilities include:

- **Booking**
- **Ticket**
- **Flight**
- **Airport**
- **Weather** — fully implemented against an OpenWeather client, but currently disabled (not registered) by default.

Each capability is an independent package containing its own:

- Service layer
- Tools (25 LangChain tools total across all capabilities, each with a Pydantic `args_schema`)
- Utilities
- Domain-specific logic

Each capability is itself a bounded sub-agent: a plan step identifies its target capability through a `capability_id`, and the workflow routes the step to a decorator-registered capability function. That function spins up a ReAct-style agent over the capability's tools, bounded by a recursion limit so a runaway sub-agent degrades into a structured failure rather than hanging the workflow. This yields a hierarchical design — a top-level planner/validator orchestrator delegating to per-domain sub-agents.

Capabilities are discovered and registered automatically through a custom decorator-based `CapabilityRegistry`, which walks the `app.capabilities` package, validates each handler's signature and return type at registration time, and generates the capability catalog injected into the planner and validator prompts. New capabilities can therefore be added without changing the graph.

Capabilities may use the shared database session provided through `RunnableConfig`. They do not independently control transaction commit or rollback; transaction lifecycle ownership remains at the workflow layer.

## State Management Strategy

Each user/session is isolated through a unique LangGraph `thread_id`.

Workflow state is persisted using LangGraph’s `MemorySaver`, allowing multi-turn conversations and interrupted workflows to continue within the correct user thread.

The execution state is modeled as follows:

```python
class ExecutionState(BaseModel):
    current_step_index: int = 0
    results: list[StepResult] = Field(default_factory=list)
    status: Literal[
        "running",
        "waiting_for_user",
        "failed",
        "completed",
    ] = "running"
    pending_question: str | None = None
```

The overall workflow state is represented using a typed dictionary:

```python
class WorkflowState(TypedDict, total=False):
    messages: Required[Annotated[list[AnyMessage], add_messages]]
    plan: ExecutionPlan
    feedback: Feedback
    execution: ExecutionState
    user_message: str
    retries: int
```

Key state fields include:

- `messages`: Conversation messages managed by LangGraph.
- `plan`: The generated execution plan.
- `feedback`: Evaluator feedback for invalid plans.
- `execution`: Current execution status, progress, results, and pending user question.
- `user_message`: The original user request.
- `retries`: Number of planning/evaluation retries performed.

## Planning Strategy

Planning follows a **generator-evaluator pattern**.

1. The planner receives the user request.
2. It uses an LLM to generate a structured `ExecutionPlan`.
3. The plan format is enforced through Pydantic structured output.
4. The generated plan is first checked by the rule-based evaluator.
5. If it passes structural validation, it is sent to the LLM evaluator for semantic validation.
6. If evaluation fails, feedback is passed back to the planner for regeneration.
7. The system retries plan generation and evaluation up to three times.
8. If no valid plan is produced after the retry limit, the workflow exits with an error.

A valid plan must satisfy both structural and semantic requirements:

- Its fields must satisfy Pydantic validation.
- Each step must target an available capability.
- Each step identifier must be unique.
- Steps must be ordered correctly.
- Dependencies must be respected.
- The plan should satisfy the user’s goal using the minimum necessary steps.
- Each action should be singular and clearly scoped.

## Safety Architecture

The system includes several safety and consistency measures:

- **Structured plan validation:** Plans are constrained through Pydantic models and validated before execution.
- **Capability catalog validation:** Every plan step must reference a capability that exists in the system catalog.
- **Unique step validation:** Step identifiers must be unique within a plan.
- **Semantic plan evaluation:** An LLM evaluator checks that the plan is appropriate for the user goal and respects dependencies.
- **Controlled capability routing:** Steps can only be routed to registered capability functions.
- **ORM-based database access:** SQLModel ORM is used instead of constructing raw SQL queries, helping reduce SQL injection risk.
- **Defensive data coercion:** A custom `SafeDateTime` SQLAlchemy type decorator safely reads malformed SQLite datetime values (for example `\N`, empty strings, or `NULL`) without crashing on the provided dataset.
- **Bounded sub-agents:** Capability sub-agents run under a recursion limit, and a `GraphRecursionError` is converted into a structured `CapabilityFailure` rather than propagating as an unhandled error.
- **Human confirmation for risky operations:** Before executing operations that require user approval, the workflow sends an interrupt containing the effect of the operation and waits for the user’s decision.

## Database Transaction Strategy

The project uses the provided SQLite database through SQLModel.

A new transaction is created when plan execution begins. The same unified database session is made available to capabilities through `RunnableConfig`.

Transaction ownership belongs to the workflow layer:

- If all execution steps complete successfully, the workflow commits the transaction.
- If an error occurs during execution, the workflow interrupts execution and rolls back the transaction.
- Capabilities and their service layers use the shared session but do not independently commit or roll back the transaction.

This provides all-or-nothing behavior for multi-step plans and helps prevent partially completed operations from being persisted.

## Human-in-the-Loop Design

The workflow supports user clarification and confirmation through LangGraph interrupts.

When a capability requires more information or user approval:

1. The workflow issues an interrupt containing the required question or confirmation details.
2. Chainlit catches the interrupt event.
3. Chainlit displays an appropriate clarification or confirmation message to the user.
4. The user provides a response.
5. The response is returned to the LangGraph workflow using:

```python
Command(resume=...)
```

6. The workflow resumes from the paused state and continues execution.

This mechanism is used especially for risky operations, where users are informed of the expected effect before the operation is executed.

## Retry / Failure Strategy

### Planning retries

The planner may retry plan generation when the generated plan fails either the rule-based evaluator or the LLM evaluator.

- Maximum evaluation retries: **3**
- After three unsuccessful attempts, the workflow produces an error and exits.

### Execution failures

During execution, each plan step may result in one of three outcomes:

1. **Success:** The result is stored and execution proceeds to the next step.
2. **Failure:** Execution is interrupted, the transaction is rolled back, and the workflow moves to synthesis.
3. **User input required:** The workflow pauses through an interrupt and waits for clarification or confirmation.

After execution ends, the synthesis phase either:

- Combines step results into a unified user-facing response, or
- Reports the encountered error.

## Dependency Installation

The project uses [uv](https://docs.astral.sh/uv/) for dependency and environment management.

The required Python version is defined in the `.python-version` file.

### Install uv

If `uv` is not already installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

For alternative installation methods, refer to the official uv documentation.

### Install project dependencies

From the project root:

```bash
uv sync
```

This creates or updates the managed environment and installs dependencies declared by the project.

## Environment Variable Configuration

An example environment file is provided:

```text
.env.example
```

Create your local environment configuration file:

```bash
cp .env.example .env
```

Then fill in the required values, such as the API key and configuration required by the LLM provider.

> Do not commit `.env` files containing secrets to source control.

## Running the Project

The app is split into two processes: a FastAPI backend that owns the agent, the database session, and the checkpointer, and a Chainlit UI that talks to it purely over HTTP/SSE. Start both, from the project root, after installing dependencies and configuring environment variables.

Backend:

```bash
uv run api
```

UI, in a second terminal:

```bash
uv run ui
```

Chainlit will display the local application URL in the terminal after startup (port 8001, since Chainlit's own default port collides with the API's). The UI reads the backend's address from the `API_BASE_URL` environment variable, defaulting to `http://localhost:8000`.

`uv run api` and `uv run ui` are shorthand for `uv run uvicorn app.api.server:app --reload` and `uv run chainlit run src/app/ui/chainlit_app.py -w --port 8001`, respectively.

### Backend API

- `GET /health` — liveness check.
- `POST /threads/{thread_id}/stream` — runs the graph for a thread and streams the result as Server-Sent Events. The body is `{"message": "..."}` for a new user message or `{"resume": {...}}` to answer a pending confirmation/clarification. Event types: `node` (an intermediate step's output), `token` (the final answer streaming in), `message` (the complete final answer), `interrupt` (a confirmation is required), `error`, and `end`.
- `DELETE /threads/{thread_id}` — idempotently drops a thread's session and checkpoint.

## Testing & Verification

Tests are split by cost:

- `tests/free` — zero-cost, runs against a fake graph and fake session; no LLM calls and no `.env` required.
- `tests/paid` — calls the real LLM through the full graph; human-only, run via `./scripts/test-paid.sh` (asks for a typed confirmation).

```bash
./scripts/verify.sh   # format, lint, pyright, mypy, bandit, pip-audit, then tests/free
uv run pytest          # tests/free only
./scripts/test-paid.sh # tests/paid, real LLM, interactive confirmation required
```

## Example Prompts

Example prompts and test scenarios are available in:

```text
tests.md
```

These examples demonstrate the supported workflows for the booking, ticket, flight, and airport capabilities. Scenario 1 is also encoded as the automated (paid) `tests/paid/test_graph_smoke.py`.

## Known Failure Modes and Limitations

- Not all requested or potential system capabilities are currently implemented and tested.
- The behavior of the system under very long conversations has not yet been fully evaluated.
- Sequential plan execution may increase latency for plans with many steps.
- Later plan steps can access results from earlier steps. While this can provide useful context, it may also increase context size and cause context bloat in longer plans.
- The system assumes that users interact with it according to the intended workflow and state-machine procedure.
- `MemorySaver` is suitable for the current workflow and thread-based continuation design, but it may not be sufficient as the only persistence mechanism for a production-scale deployment.
- The current implementation uses SQLite, which may not be appropriate for high-concurrency production workloads.

## Key Architectural Trade-offs

### Planner-evaluator workflow

The planner-evaluator design adds extra LLM calls and latency before execution. However, it improves reliability by validating plans before database-related actions are performed.

### Sequential execution

Plan steps are executed sequentially. This simplifies dependency handling, transaction management, error recovery, and debugging.

The trade-off is that independent steps are not executed in parallel. In addition, earlier step results remain available to later steps, which can increase context size for larger plans.

### One transaction per execution plan

Using one transaction for the full execution plan provides atomic behavior: either all steps are successfully persisted, or the entire operation is rolled back.

The trade-off is that long-running plans may hold database resources for longer periods.

### Human-in-the-loop interrupts

Interrupts and explicit confirmation improve user control and reduce the risk of unintended operations.

The trade-off is that execution becomes multi-turn and cannot always complete automatically in a single request-response cycle.

### MemorySaver-based persistence

Thread-based persistence with `MemorySaver` makes it straightforward to pause and resume workflows for each user/session.

The trade-off is that additional persistence and operational design may be needed for durable, production-scale deployments.
