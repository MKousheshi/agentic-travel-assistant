# Architecture Review: Agentic Travel Assistant

## Summary

The foundation is good. It's split into plan, validate, execute and synthesize phases, capabilities are plugins behind a registry, runs are checkpointed so they can pause and resume, the API streams progress, and the UI is a thin client. Those are the right building blocks.

The problem is how they fit together. The system is built as a **one-way pipeline that the conversation is pushed through**, not a **conversation manager that uses a pipeline when it needs one**. That one choice causes most of the weaknesses below:
- it's rigid when the user changes their mind;
- its grounding depends on what the prompt asks for, not on checks in code;
- state leaks from one turn into the next;
- DB transactions don't fit human-in-the-loop pauses.

The three goals are a flexible user experience, no invented information, and reliable context tracking. The current design delivers each of them only partly, and mostly through prompt text rather than structure.

---

## 1. How it works today

Every user message enters the graph at `START`. There is exactly one decision point: if a paused execution exists, jump back into it; otherwise plan from scratch.

Planning produces an ordered list of steps. Each step names a capability and says in free text what to do (`action`, `goal`). Two validators check the plan. Then each step runs as its own ReAct sub-agent, which sees the whole conversation and picks tools and arguments on its own. A step can succeed, fail (the whole plan rolls back) or ask the user a question (the run parks). A synthesizer writes the final answer.

Confirmations are a separate mechanism: `interrupt()` calls inside individual tools.

---

## 2. Strengths

- **Clear phases.** Planning, execution and synthesis are separate nodes with typed state, so behaviour is easy to follow and to trace.
- **Capability plugin model.** The registry, auto-discovery, the enforced handler contract and catalog injection into prompts make it cheap to add a domain. This is the right way to extend the assistant.
- **Structured outputs everywhere.** `PlannerResponse`, `Feedback` and `CapabilityResult` are discriminated unions, not parsed prose, so routing is decided in code.
- **Clarification is a first-class outcome** at both the planning level and the capability level (`needs_information`). The idea that the system asks instead of guessing is built into the types.
- **Transactions belong to the graph, not to tools.** The instinct is right: side effects should be controlled centrally.
- **Human-in-the-loop exists** through LangGraph interrupts, with checkpointed resume.
- **The backend/UI split with an SSE event protocol** is clean. The UI can be replaced, and per-thread locking prevents concurrent requests from corrupting shared state.
- **Grounding is taken seriously in the prompts.** The capability prompt's no-invention and terminal-result rules are thoughtful.

---

## 3. Weaknesses, and why they matter

### 3.1 The conversation has no "brain" between turns (the biggest UX gap)

`route_from_start` (`src/app/graph/nodes.py:27`) makes a structural choice, not a semantic one: if `execution` exists, whatever the user just typed goes straight back into the paused step.

Nothing asks what the user actually meant:
- Are they answering the pending question?
- Are they adding information to a *different* step?
- Are they cancelling ("never mind")?
- Are they changing the plan ("make it Friday instead")?
- Is it an unrelated new request, or just "thanks"?

The paused capability sub-agent gets the message and has to cope. Its prompt tells it to ignore other requests, so a change of mind is silently ignored or turned into a failure. **A paused plan can't be cancelled or amended at all**; the only reset is deleting the thread.

There's also a related bug. After the user answers a mid-plan question, `execute_plan` copies the state but never sets `status` back to `"running"` (`src/app/graph/nodes.py:174-182`). The next step is never run: the router sends the run to `synth`, which shows the *old* pending question again. In any multi-step plan with a question, the run stalls.

Confirmations use a second, parallel mechanism:
- Buttons resume an `interrupt()`. Typing "yes, delete it" instead starts a new run that re-enters the paused step.
- Old Confirm buttons are never invalidated.

So there are two ways to wait for the user, and neither understands what the user said.

**Why it matters:** the goal is that users shouldn't have to follow our workflow. Right now the workflow controls the user whenever a run is paused.

### 3.2 "Never guess" is enforced by prompt text, not by the architecture

This matters most for the hallucination goal.

- **The plan carries values as free text.** `PlanStep` has no inputs field. Any identifier, date or amount the planner decides on is embedded in `action`/`goal` prose. The capability prompt then tells the sub-agent to *"treat the assigned action and goal as authoritative."* If the planner invents a booking reference, the executor gets it as a trusted instruction. Nothing in the architecture checks where a value came from.
- **The catalog is hand-written prose** with no input schema, no required/optional marking, and no side-effect class. The tools already declare exact Pydantic input schemas, but the planner never sees them. The two will drift apart; they already disagree in places, e.g. the booking reference is "6 letters" in the description but `max_length=16`.
- **Planner and validator have opposite policies:**
  - The planner prompt says *never assume CRUD operations exist* (`src/app/prompts/planner.py:39`).
  - The validator prompt says *standard lifecycle actions (create, update, cancel…) are inherently supported unless restricted* (`src/app/prompts/validator.py:26-29`).
  - As a result, the validator can approve steps the catalog doesn't offer, such as "change flight status to Cancelled". That directly contradicts "exactly the capabilities specified". It also means the two models can argue until the retry limit is hit.
- **The planner prompt is corrupted** at its most important section: rule 2 is duplicated and rule 3 is truncated (`src/app/prompts/planner.py:67-69`). The prompt is also ~260 lines of partly overlapping absolute rules for `gpt-4o-mini`. Long, contradictory rule lists for a small model give inconsistent results.
- **Grounding is never checked in code.** Every protection against invented values is a request to a model.

**Why it matters:** a model can't be prompted into never guessing. Guessing can only be made detectable and blocked.

### 3.3 State and memory are organised around the run, not the conversation

- **Per-run state leaks into later turns.**
  - `plan` and `feedback` survive after a run finishes.
  - On the next unrelated message, `create_plan` appends "Previous plan: …" and a `HumanMessage("Feedback: …")` *after* the user's latest message (`src/app/graph/nodes.py:42-47`). The planner is told feedback came from the user, and the last thing it reads isn't the user's request.
  - The prompt's long "latest-request priority" section is compensating for a state bug.
- **Structured results are thrown away.**
  - When a run ends, `execution`, including every `StepResult`, is cleared. Only the synthesizer's prose goes into `messages`.
  - A follow-up like "what's the weather at that flight's destination?" depends on the synthesizer having happened to mention the right IDs.
  - There's no working memory of entities (flights, bookings, passengers) the conversation has touched.
- **Questions lose their structure.** `needs_information` returns `missing_fields` and `context`, but the graph keeps only the question text. On resume, the capability starts over from scratch.
- **History grows without limit.** The full message history goes into the planner, the validator, every step's sub-agent and the synthesizer. The synthesizer receives it as Python repr text inside a system prompt. Cost and latency grow with conversation length, and accuracy drops.

### 3.4 Transactions conflict with human-in-the-loop

"The whole plan is atomic" plus "the plan can pause for the user" means **a DB transaction stays open across human think-time**:
- `session.begin()` runs in `execution_init`.
- The transaction is still open while `waiting_for_user` persists across turns.
- With SQLite, a pending write holds the database write lock for as long as the user takes.

The checkpoint and the database can also disagree:
- **Client disconnect:** closing the session rolls back the DB.
- **Graph error:** `stream_run` rolls back the DB.
- **The problem:** in both cases the checkpoint still contains `execution` with progress past steps whose writes were just undone. The next message resumes from that point.

The idea behind atomicity is right. The unit is wrong: it spans user turns.

### 3.5 Side effects happen inside an LLM loop

Each step is a ReAct agent that chooses *which* tool to call and *with what arguments*, including write tools. Consequences:
- **Write safety is decided per tool, not by the architecture.**
  - Deleting a booking or ticket asks for confirmation.
  - Creating a booking or ticket writes immediately.
  - A new capability author has to remember to add `interrupt()`, and nothing checks that they did.
- **Resume replays the sub-agent.** After a confirmation, the node re-executes and replays the sub-agent to reach the resume point. It's hard to guarantee that the arguments confirmed are the arguments written.
- **The tool-result contract isn't standardized.** The capability prompt depends on `success`/`retryable`/`terminal` fields that most tools don't return.
- **Every capability repeats the same sub-agent boilerplate** and builds a new agent on every call.

### 3.6 Failure handling and partial results

- **Fail-fast plus full rollback.** If step 3 fails, results from read-only steps 1–2 are thrown away. The user gets only the failing capability's message, not what succeeded and what was reverted. The project's own scenario list (`tests.md`) expects partial-success reporting.
- **Silent exit when retries run out.** When planning retries are exhausted, the graph exits with **no user message**.
- **Internal errors reach the user.** `str(exc)` and `GraphRecursionError` text are shown as-is.

### 3.7 Cost and latency

The cheapest possible request, a single lookup, needs at least four LLM calls:
1. planner
2. LLM validator
3. the capability agent (itself several calls)
4. synthesizer

The LLM validator adds latency on every request and does little for simple read-only plans. Sequential execution is acceptable for now. But the plan model (a flat list with no dependencies) means adding parallelism later will require a schema change.

### 3.8 Extensibility

The registry is good, but a capability is only "an id, a prose description and a function". Missing:
- declared operations and input schemas;
- a side-effect class (read / write / destructive);
- a confirmation policy;
- a description of outputs.

Prompts are also formatted from a global registry **at import time**, which creates the documented ordering trap.

---

## 4. What's missing

1. **A turn interpreter / dialogue manager** that understands each user message in light of pending state.
2. **A structured capability contract**, generated from the tool schemas.
3. **Code-level argument grounding**: every value must be traceable to user text or a tool result.
4. **Thread-level working memory** of entities and results, separate from run state.
5. **A single "pending interaction" model** covering both questions and confirmations, with cancel and amend.
6. **A side-effect policy in the core** (confirm every write by default) instead of inside individual tools.
7. **A plan that can change during a run**: replanning with progress context instead of "continue or die".
8. **A scenario evaluation harness** that measures capability selection, clarification correctness and invented values. For an agent, this is the real quality signal.

---

## 5. Design decision: where information requirements live

**Recommendation: make execution time authoritative, and let planning be an optional optimization. Enforce both with schemas, not prose.**

- **The planner decides *what*, never *with which values*.**
  - It outputs intents: capability, operation, and references to where inputs come from ("from the user", "from step 1's result").
  - It is not allowed to write literal values into a step.
  - If the catalog is generated from schemas, the planner *may* ask for obviously missing required inputs early. Missing that is harmless, because execution catches it.
- **The capability decides *how*, with a `prepare → act` split:**
  1. **Prepare** (LLM plus read-only tools): extract arguments for a chosen operation.
  2. **Validate deterministically** against the operation's Pydantic schema.
  3. **Check grounding deterministically:** every argument value must appear in the user's messages or in prior tool/step results. A value that can't be traced is treated as missing.
  4. **If missing or ambiguous,** return structured `needs_information` with exactly the missing fields, so the question is precise and the partial arguments are kept.
  5. **Act** (no LLM): for writes, the core shows the *exact* validated arguments for confirmation, then calls the service directly. No model runs between "yes" and the write.

This is the only arrangement where "the planner never guesses" is true by construction. Requirements the catalog doesn't mention are still caught, because the schema is the source of truth at the moment it matters.

---

## 6. What to rethink, and what to keep

**Rethink:**
1. **Entry routing becomes a conversation controller.**
   - It reads the new message together with pending state: current plan, progress, pending question or confirmation, and working memory.
   - It classifies the message as one of: *answer pending*, *confirm/deny*, *amend plan*, *cancel*, *new request*, or *answer from context / small talk*.
   - It then resumes, replans with progress, rolls back and clears, or replies directly.
   - Button clicks and typed replies go through the same path.
2. **The plan becomes a living object.**
   - Replanning takes completed results and new user input as context, so "change the date" edits the plan instead of restarting it.
   - Give steps explicit `depends_on` now; that makes future parallelism a scheduler change, not a schema change.
3. **Transactions stay within a single run and never span a user turn.**
   - Short transactions per write action (after confirmation), with committed effects recorded in graph state so the checkpoint and the DB can't diverge.
   - If multi-write atomicity is truly needed, gather and confirm *all* inputs first, then execute every write in one uninterrupted segment.
4. **State is split by lifetime.**
   - *Conversation*: messages, summarized when long.
   - *Working memory*: entities and structured results, kept across runs.
   - *Run*: plan, feedback, execution; cleared deterministically when a run ends.
5. **Validation is mostly deterministic.**
   - A structured catalog makes capability, operation and input-reference checks possible in code.
   - Keep an LLM critic only for multi-step or write plans, and give it the *same* catalog policy as the planner.
6. **Capabilities become declarative.**
   - Each operation declares an input schema, a side-effect class and a description; the catalog is generated from those declarations.
   - A shared execution engine handles the sub-agent, grounding, confirmation and the error contract, so a capability author writes services and schemas, not agent boilerplate.

**Keep:** the phase separation, the registry and discovery, structured outputs, checkpointed interrupts, the API/UI split and SSE protocol, per-thread locking, and the principle that the graph owns side effects.

---

## 7. Suggested order of work

1. **Fix the state bugs first** (cheap, high impact):
   - reset `status` to running after a resumed step;
   - clear `plan`/`feedback` at run end and stop injecting them as user messages;
   - always emit a user message on exit;
   - repair the corrupted planner prompt;
   - make the validator policy match the planner's.
2. **Add the conversation controller and a unified pending-interaction model**, with cancel and amend. This is the biggest UX gain.
3. **Change the capability contract**: declared operations and schemas, a generated catalog, the prepare/act split, the grounding check, and a core confirmation policy for all writes. This is the biggest hallucination and safety gain.
4. **Redesign transaction scope and add working memory.**
5. **Build a scenario evaluation harness** before tuning prompts, so every later change can be measured.
