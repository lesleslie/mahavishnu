# 2026-08-29 — Settle vs LangGraph `interrupt()` + checkpointing vs Prefect paused-flow state

## Status

Accepted, 2026-08-29. Implements Phase 2 of the Mahavishnu v2 plan.

## Context

Phase 2 of the v2 plan ships "settle operations" to address the 5
documented memories of unverified-agent-output failures. The shape is:

1. Spawn a worker with a task signature and a list of bindings (files
   the worker will produce).
1. Persist a settle record in state=`proposed` BEFORE the worker
   writes any file.
1. The worker does its work; the operator inspects the result.
1. The operator transitions the settle run through
   `select | apply | release | discard`. `apply` shells out to
   `git merge-file` for the actual content merge.

The state machine is implemented in
`mahavishnu/settle/state_machine.py`. The MCP tools are
`worker_run_with_settle` and `worker_settle`. The architectural
question for this ADR: **why a hand-rolled state machine instead of
LangGraph's `interrupt()` + checkpointing or Prefect's paused-flow
state?**

## Alternatives considered

### Alt 1 — LangGraph `interrupt()` + checkpointing

LangGraph (langgraph-sdk 0.x) supports an `interrupt()` primitive that
pauses a graph at a node, persists state via a `checkpointer`
(typically `MemorySaver` or a Postgres-backed store), and resumes on
operator action. The shape would be:

```python
from langgraph.graph import StateGraph, interrupt
from langgraph.checkpoint.memory import MemorySaver

class SettleState(TypedDict):
    run_ref: str
    bindings: list[dict]
    state: str

def propose(state: SettleState) -> SettleState:
    # Pre-merge audit trail
    return {"state": "proposed"}

def select(state: SettleState) -> SettleState:
    decision = interrupt({"question": "Select this run?"})
    return {"state": "selected" if decision else "discarded"}

def apply(state: SettleState) -> SettleState:
    decision = interrupt({"question": "Apply with merge?"})
    if decision:
        # run git merge-file
        return {"state": "applied"}
    return {"state": "released"}

builder = StateGraph(SettleState)
builder.add_node("propose", propose)
builder.add_node("select", select)
builder.add_node("apply", apply)
memory = MemorySaver()
graph = builder.compile(checkpointer=memory)
```

**Pros:**

- Battle-tested framework with built-in checkpointing, replay, and
  resumability.
- `interrupt()` is a clean primitive for "pause and wait for human."
- LangGraph Studio gives operators a UI for free.

**Cons (decisive):**

1. **Heavyweight dependency.** LangGraph pulls in `langchain-core`,
   `langgraph`, `pydantic` v2, and async runtime support. Mahavishnu
   is a control-plane service; adding a graph framework to surface
   one feature is a 5-10x cost increase for the feature surface.
1. **Couples persistence to a `checkpointer` backend.** LangGraph's
   `MemorySaver` is in-memory; the Postgres-backed `PostgresSaver`
   requires a schema (`CREATE TABLE checkpoints`). The Bodai
   ecosystem already has Dhara for persistence; introducing a second
   persistence substrate just for one feature is unwarranted.
1. **The state machine is tiny (5 states, 4 transitions).** A graph
   framework is overkill for a transition table of 4 entries.
1. **Operator-visible audit trail.** LangGraph's checkpoint format is
   its own; subscribers would need a custom deserializer. The
   settle-record's `to_dict` / `from_dict` round-trip is a plain
   dict that any consumer can read.
1. **No `git merge-file` integration.** The actual merge has to be a
   separate step anyway. Wrapping it in a graph node adds no value.

### Alt 2 — Prefect paused-flow state

Prefect 2.x supports `pause_flow_run()` (returns control to the
scheduler; the run is parked). Combined with a manual `resume` from
the UI / CLI, this gives us a "pause and wait for human" pattern:

```python
from prefect import flow, pause_flow_run

@flow
def settle_run(run_ref: str):
    persist_initial(run_ref)
    pause_flow_run(timeout=86400)  # wait up to 24h
    if operator_decision == "apply":
        merge_result = git_merge_file(...)
        persist_transition(run_ref, "applied")
    elif operator_decision == "discard":
        persist_transition(run_ref, "discarded")
```

**Pros:**

- Prefect is already a production adapter in Mahavishnu (see
  `mahavishnu/adapters/`).
- The paused-flow state is durable across restarts.
- Prefect's UI surfaces paused runs for free.

**Cons (decisive):**

1. **Couples the feature to a specific adapter.** The v2 plan frames
   settle as a control-plane primitive; bolting it onto Prefect
   means LlamaIndex and Agno adapters would need their own
   implementations (or skip the feature). That's a regression from
   the current "production-ready across all three adapters"
   posture.
1. **Prefect is heavyweight for a CLI/MCP primitive.** Spinning up a
   Prefect flow for every settle run adds 100-300ms of latency
   (Prefect task submission) and creates durable state in the
   Prefect database, not Dhara.
1. **The state machine is not flow-shaped.** Settle is a small
   state machine with 5 states and 4 transitions; it has no
   retries, no parallel branches, no dynamic fan-out — none of the
   features Prefect's flow primitives buy you.
1. **Operator-facing commands differ.** A Prefect-paused run is
   resumed via `prefect deployment ls` + `prefect flow-run resume`;
   the MCP tool pair `worker_run_with_settle` / `worker_settle`
   gives a uniform CLI/MCP surface that doesn't depend on which
   adapter is enabled.
1. **Audit trail formatting.** Prefect's flow-run logs are
   Prefect-shaped; the settle record's transition log is a plain
   JSON list keyed by `(action, from_state, to_state, actor, at)` —
   any external audit pipeline (Grafana, Akosha, Session-Buddy)
   can ingest it directly.

### Alt 3 (chosen) — Hand-rolled state machine with Dhara persistence

The state machine is 130 lines of Python in
`mahavishnu/settle/state_machine.py` with three pieces:

- A `SettleRunRecord` dataclass that holds the audit trail.
- A `transition()` pure function that validates against a static
  transition table.
- An exception hierarchy (`SettleTransitionError`) for illegal
  transitions.

Persistence is a thin wrapper at `mahavishnu/settle/persistence.py`
that writes the record to Dhara (`settle/v1/{run_ref}`) with a
local dead-letter fallback (`~/.mahavishnu/settle-dead-letter/`).
This is the same pattern as
`docs/fixes/2026-08-29-dispatch-to-pool-dead-letter-fallback.md` —
best-effort persistence with a recoverable local mirror.

The 3-way merge is a thin wrapper around `git merge-file` in
`mahavishnu/settle/merge.py`. We do not implement our own merge
algorithm; git's existing 3-way merge is authoritative for content
conflict detection.

**Pros:**

- Zero new dependencies — uses `asyncio.subprocess` and `git` (which
  is already a hard requirement for the worker-registry worktree).
- Persistence is in Dhara, consistent with the rest of the
  Bodai control-plane state.
- The state machine is independently testable with property-based
  tests (see `tests/unit/mcp/test_settle_state_machine.py`).
- Total implementation: ~300 lines of Python + tests.
- The state machine can be reused by future adapters (LlamaIndex,
  Agno) without modification.

**Cons:**

- We hand-roll a state machine instead of reusing a framework. This
  is a one-time cost; the state machine is tiny and the property
  tests guard against drift.
- We do not get a UI for free. Operators interact via the MCP tools
  (`worker_settle --action apply`) or via the CLI (`mahavishnu settle ...`).

## Decision

Use the hand-rolled state machine + Dhara persistence + `git merge-file`. The cost is ~300 lines; the benefit is a small,
auditable, framework-independent primitive that all three adapters
(Prefect, LlamaIndex, Agno) can use without modification, and that
survives Bodai's adapter-rotation policy (the v1 Shepherd precedent:
avoid hard-coding primitives to a single engine).

## Consequences

- New module: `mahavishnu/settle/` (~300 lines).
- New MCP tools: `worker_run_with_settle`, `worker_settle` (extend
  `mahavishnu/mcp/tools/worker_contract_tools.py`).
- New WebSocket channels: `settle:`, `run:` (extend
  `MahavishnuWebSocketServer._can_subscribe_to_channel`).
- New persistence substrate: `settle/v1/{run_ref}` in Dhara with
  dead-letter fallback to `~/.mahavishnu/settle-dead-letter/`.
- New WebSocket consumer contract: `docs/WEBSOCKET_CONSUMER_GUIDE.md`.
- New property-based tests: `tests/unit/mcp/test_settle_state_machine.py`.
- New integration tests: `tests/integration/test_settle_e2e.py`.

## Follow-up considerations

- **Phase 4+ could revisit LangGraph.** If the state machine grows
  branches (e.g. parallel bindings, retry-with-feedback), LangGraph's
  graph primitives become attractive. Today's state machine is too
  small to justify the framework cost.
- **Operator UI.** A CLI for `mahavishnu settle list / inspect / drive` would let non-MCP operators interact. Out of scope for
  Phase 2; Phase 3 candidate.
- **Cross-tenant isolation.** Settle records are keyed by `run_ref`
  only. If Mahavishnu ever becomes multi-tenant, add a
  `tenant_id` prefix to the Dhara key schema. Not needed today.
