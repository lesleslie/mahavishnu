# Jot Drain Sub-plan Design

> **Status:** Draft — pending user review before plan handoff.
> **Date:** 2026-09-10
> **Sub-plan:** 3 of 3 in the Jot Inbox trilogy (Capture → Read → **Drain**)
> **Author:** Brainstorming session output, validated by user
> **Spec prerequisites:** `docs/superpowers/specs/2026-09-09-jot-read-design.md` and `docs/superpowers/specs/2026-09-09-jot-capture-design.md` ship the foundational primitives that Drain extends.

## 1. Context and Scope

### 1.1 What this sub-plan delivers

Drain turns the jot inbox from a passive log into an active workflow tool. It does two things:

1. **Bulk drain command** — process multiple open jots in one interactive session, choosing actions per jot (dispatch / defer / done / delete / skip).
2. **Ambient surfacing** — at session start and after tool results, inject relevant jots into Claude's context as `additionalContext`.

The original brainstormed commitment was:

> *Hybrid: local-first append-only capture that can never fail, plus Mahavishnu MCP tools for smart resurfacing and jot-to-worker dispatch.*

This spec realizes the "smart resurfacing and jot-to-worker dispatch" leg.

### 1.2 Goals

- **Complete the Jot Inbox trilogy.** Capture + Read + Drain form the full product vision.
- **Make jots actionable.** A captured jot that sits in the log forever is a missed opportunity. Drain gives every open jot a path to resolution.
- **Respect user agency.** Every dispatched jot has a single explicit user approval. Auto-retry handles transients; persistent failures escalate.
- **Reuse the existing event log.** No new persistence layer; dispatch state lives in the same JotEvent chain.
- **Cost-aware surfacing.** Most surfacing fires are free (lexical); semantic fallback is the exception, not the rule.

### 1.3 Non-goals

- **Multi-user authorization.** Single-user / per-HOME model. Anyone with MCP access can dispatch/defer/delete any jot. (See §3.7.)
- **Capture-time changes.** Sub-plan 1 (capture) is frozen. Drain is purely read-and-act.
- **Replacement of existing tools.** `jot_done`, `jot_edit`, `jot_reopen` keep working. Drain extends, never replaces.
- **Persistence layer changes.** Jot log remains the single source of truth. No new SQLite / Postgres / etc.
- **UI for drain.** No TUI, no GUI. CLI + MCP + slash command are the surfaces.

## 2. Locked Design Decisions

These were resolved through the brainstorming Q&A. They are **not** revisitable during plan-writing without re-opening brainstorming.

| Decision | Choice | Rationale |
|---|---|---|
| UX shape | Hybrid (drain + surfacing) | Matches original brainstormed promise |
| Dispatch agency | Execute directly (single approval) | User explicitly chose dispatch — no plan-then-execute middle layer |
| Selection algorithm | Lexical primary, semantic fallback | Cheap when lexical hits; semantic only on zero lexical |
| Retry policy | **Max 2 attempts total** (1 initial + 1 auto-retry), 30s backoff, then `FAILED` | Handles transients; persistent failures escalate. `MAX_AUTO_ATTEMPTS=2` (NOT `MAX_AUTO_RETRIES`). |
| Privilege | Anyone with MCP access | Consistent with current jot model; no schema migration |
| Architecture | Tightly integrated (extend `mahavishnu/jot/`) | Drain is "actions on jots," not a peer system |

## 3. Architecture Overview

### 3.1 File layout

```
NEW:     mahavishnu/jot/drain.py          State machine, dispatch orchestration,
                                         retry policy, surfacing scorer.
                                         All drain primitives live here.

EXTEND:  mahavishnu/jot/events.py        New Op literal values (7 new ops).
EXTEND:  mahavishnu/jot/errors.py        New: JotDispatchError, JotRetryError,
                                              JotDeferred, JotPermissionError,
                                              JotSurfaceThrottled.
EXTEND:  mahavishnu/jot/fold.py          Extend state derivation for dispatch_state,
                                         deferred_until, deleted.
EXTEND:  mahavishnu/jot/render.py        New render fields in JotSummaryDict.
EXTEND:  mahavishnu/jot/cli.py           New subcommands: drain, dispatch, defer,
                                         delete, retry, resurface.
EXTEND:  mahavishnu/mcp/tools/jot_tools.py   New MCP tools (6).
EXTEND:  mahavishnu/cli/jot_cli.py       Register 6 new Typer subcommands.
EXTEND:  mahavishnu/commands/jot.md     Extend with `/jot drain` and
                                         updated `/jot vitals`.
EXTEND:  settings/mahavishnu.yaml        Add `jot.drain.*` and
                                         `jot.surfacing.*` config sections.

NEW:     .claude/hooks/jot-session-start.py    SessionStart hook: invokes
                                                jot_resurface, returns
                                                additionalContext.
NEW:     .claude/hooks/jot-post-tool-use.py    PostToolUse hook: invokes
                                                jot_resurface with tool
                                                result text, returns
                                                additionalContext (throttled).
NEW:     .claude/hooks/jot-capture.py          UserPromptSubmit hook:
                                                captures user prompt as
                                                a jot (already exists in
                                                mahavishnu/hooks/jot_capture.py
                                                but not wired).

NEW:     tests/unit/jot/test_drain.py                State machine, retry, filters.
NEW:     tests/unit/jot/test_drain_surfacing.py      Lexical + semantic scorer.
NEW:     tests/unit/jot/test_drain_reconciler.py     Lazy reconciler behavior.
NEW:     tests/unit/jot/test_drain_filters.py        State-eligibility filter tests.
NEW:     tests/unit/jot/test_drain_helpers.py        Tokenizer, retry budget math.
NEW:     tests/unit/jot/test_drain_mcp_tools.py      MCP tool wrapper tests.
NEW:     tests/integration/jot/test_drain_cli.py     Typer CLI tests for 6 new subcommands.
NEW:     tests/integration/jot/test_drain_e2e.py     Full drain flow against fake workflow substrate.
NEW:     tests/integration/jot/test_drain_resurfacing_e2e.py
NEW:     tests/integration/jot/test_drain_auto_retry_e2e.py
NEW:     tests/integration/jot/test_drain_concurrent_e2e.py
NEW:     tests/property/jot/test_drain_idempotency.py
NEW:     tests/property/jot/test_drain_state_invariants.py
NEW:     tests/property/jot/test_drain_surfacing_ranking.py

EXTEND:  tests/conftest.py                Fixtures: fake_workflow_substrate,
                                          fake_embeddings_service, fast_backoff,
                                          no_async_sleep, clock.
```

### 3.2 Module boundaries (`mahavishnu/jot/drain.py`)

```python
class DispatchState(Enum):                          # IN_FLIGHT, SUCCEEDED, FAILED
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

@dataclass(frozen=True, slots=True)
class JotDispatch:                                  # handle, workflow_id, attempt,
                                                    # max_attempts, last_error, started_at
@dataclass(frozen=True, slots=True)
class SurfacingContext:                             # trigger, source_text, candidate_jots
@dataclass(frozen=True, slots=True)
class DrainPlan:                                    # query, candidates, action proposals
@dataclass(frozen=True, slots=True)
class DispatchResult:                               # handle, workflow_id, attempt, status

# Drain primitives. All `handle` params accept full id, short_id, or unambiguous substring
# (per R8 / resolve_handle convention).
def drain_plan(
    query: str | None,
    limit: int = 20,
    include_in_flight: bool = False,
) -> DrainPlan
def execute_action(plan: DrainPlan, action: str, handle: str) -> ActionResult
def dispatch_jot(handle: str) -> DispatchResult
def retry_dispatch(handle: str) -> DispatchResult
def defer_jot(handle: str, until_ms: int, reason: str | None = None) -> DeferResult
def delete_jot(handle: str, reason: str | None = None) -> DeleteResult

# Surfacing primitives
def surface_relevant(
    trigger: Literal["session_start", "tool_result"],
    context_text: str,
    limit: int = 3,
) -> list[JotSummary]

# Reconciliation (lazy + background)
async def _reconcile_if_in_flight(jot: JotSummary) -> None
async def _background_reconciler_loop() -> None
async def _auto_retry_after(handle: str, backoff_s: int) -> None

# Scorers (internal)
def _tokenize(text: str) -> set[str]
def _lexical_score(jot_tokens: set[str], ctx_tokens: set[str]) -> float
def _semantic_score(jot_text: str, ctx_text: str, embeddings: "EmbeddingsService") -> float

# State filter (internal)
def _is_drain_eligible(jot: JotSummary, now_ms: int) -> bool
def _is_surface_eligible(jot: JotSummary, now_ms: int) -> bool

# Event-ctx helpers (TypedDict coercion; see §4.2)
def _parse_retry_budget_exhausted(value: object) -> bool
def _coerce_int(value: object, *, field: str) -> int
def _should_exhaust_retry_budget(jot: JotSummary) -> bool      # §6.3 retry policy
```

### 3.3 MCP tool surface (extends `mahavishnu/mcp/tools/jot_tools.py`)

| Tool | Inputs | Output | Purpose |
|---|---|---|---|
| `mcp__mahavishnu__jot_drain` | `query: str \| None = None`, `limit: int = 20`, `include_in_flight: bool = False` | `DrainPlanDict` | Bulk action selection. Returns plan, no execution. |
| `mcp__mahavishnu__jot_dispatch` | `handle: str` | `DispatchResultDict` | Per-jot dispatch. Includes auto-retry (max 2 attempts) internally. |
| `mcp__mahavishnu__jot_defer` | `handle: str`, `until_ms: int`, `reason: str \| None = None` | `JotSummaryDict` | Snooze until timestamp. Rejects `until_ms <= now_ms` with `JotValidationError`. |
| `mcp__mahavishnu__jot_delete` | `handle: str`, `reason: str \| None = None` | `JotSummaryDict` | Soft delete (audit retained). |
| `mcp__mahavishnu__jot_retry` | `handle: str` | `DispatchResultDict` | Manual retry of FAILED dispatch. |
| `mcp__mahavishnu__jot_resurface` | `trigger: Literal["session_start", "tool_result"]`, `context_text: str`, `limit: int = 3` | `list[JotSummaryDict]` | Ambient surfacing trigger. **Internal**: invoked by hooks, not by users. |

**`handle` parameter convention:** All mutating tools accept `handle: str`, which `resolve_handle` parses as full id / short_id / unambiguous substring (per R8 in the read sub-plan). This matches the existing 8 tools' convention.

**TypedDict additions** (in `mahavishnu/jot/drain.py` for reuse, re-exported via `jot_tools.py`):

```python
from typing import TypedDict

class DrainPlanDict(TypedDict):
    query: str | None
    candidates: list[JotSummaryDict]
    action_proposals: list[ActionProposalDict]   # see below

class ActionProposalDict(TypedDict):
    handle: str
    suggested_action: Literal["dispatch", "defer", "done", "delete", "skip"]
    reason: str

class DispatchResultDict(TypedDict):
    handle: str
    workflow_id: str
    attempt: int
    status: Literal["in_flight", "queued"]      # never "succeeded"/"failed" here;
                                                # outcomes come via dispatch_done/failed events
    dispatched_from: Literal["cli", "mcp", "slash"]
```

**`JotSummaryDict` extension** (per §4.4):

```python
class JotSummaryDict(TypedDict, total=False):
    # Existing 5 fields (unchanged)
    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]
    last_modified_ms: int
    # NEW (all optional; absent or None for jots without dispatch history)
    dispatch_state: Literal["in_flight", "succeeded", "failed"]
    dispatch_workflow_id: str | None             # workflow_id of the most recent dispatch
    current_attempt: int                         # 0 if never dispatched
    deferred_until: int | None                   # epoch ms; None = not deferred
    deleted: bool                                # soft-delete flag
```

**`JotVitalsDict` extension** (in `mahavishnu/jot/render.py`):

```python
class JotVitalsDict(TypedDict):
    # Existing fields (unchanged)
    open: int
    done: int
    # NEW
    dispatch_in_flight: int                      # count where dispatch_state == IN_FLIGHT
    dispatch_failed: int                         # count where dispatch_state == FAILED
    deferred: int                                # count where deferred_until is set
    deleted: int                                 # count where deleted is True
    log_event_count: int                         # for growth monitoring (out of scope: archival)
```

**`dispatched_from` provenance:** Each surface (MCP tool wrapper, CLI subcommand, slash command wrapper) sets `dispatched_from` automatically before invoking the dispatch primitive. No caller input required. Encoded as a Literal at the boundary; stored as the string value in the event ctx.

### 3.4 CLI surface (extends `mahavishnu/cli/jot_cli.py`)

```bash
mahavishnu jot drain [--query Q] [--limit N] [--include-in-flight]
# Interactive bulk drain: lists candidates, prompts action per jot
# Action choices: dispatch | defer | done | delete | skip
# --query filters candidates by lexical substring
# --limit caps candidate list (default 20)
# --include-in-flight forces inclusion of IN_FLIGHT jots (rare)

mahavishnu jot dispatch HANDLE                  # handle = id, short_id, or substring
# Single-jot dispatch; prints workflow_id + summary; non-interactive

mahavishnu jot defer HANDLE --until TIMESTAMP [--reason R]
# TIMESTAMP is epoch ms or ISO-8601 (parsed and converted to epoch ms internally)

mahavishnu jot delete HANDLE [--reason R]
# Typer confirmation prompt before deletion (delete is more destructive than done;
# no recovery path from the public API per §10 — see "soft delete is irreversible")

mahavishnu jot retry HANDLE
mahavishnu jot resurface --trigger {session_start,tool_result} [--context TEXT]
```

### 3.5 Slash command (extends `mahavishnu/commands/jot.md`)

```markdown
# /jot — show jot inbox vitals (existing, extended)

# Extended output for /jot vitals:
#   open: 7
#   done: 12
#   dispatch_in_flight: 2
#   dispatch_failed: 1    ← action needed (use /jot drain to act)
#   deferred: 3
#   deleted: 0

# New: /jot drain [--query Q] [--limit N]
#   Runs `mahavishnu jot drain` in interactive mode.
#   Per-jot action selection: dispatch, defer, done, delete, skip.

# Single-jot actions (defer, delete, retry) are NOT exposed as slash commands —
# they require explicit handle resolution and confirmation. Use MCP `jot_*` tools.
```

## 4. Data Model & Events

### 4.1 New event ops

Extends the `Op` literal in `mahavishnu/jot/events.py`:

```python
Op = Literal[
    "capture", "edit", "done", "reopen",         # existing (sub-plan 1)
    "dispatch",                                  # NEW: any dispatch attempt (initial or retry);
                                                 #   ctx.triggered_by distinguishes auto/manual/first
    "dispatch_done",                             # NEW: worker succeeded (system event)
    "dispatch_failed",                           # NEW: worker failed (system event)
    "defer",                                     # NEW: user snoozed
    "defer_expired",                             # NEW: snooze elapsed (lazy fold event)
    "delete",                                    # NEW: soft delete marker
]

Note: retries are NOT a distinct op type. Retries use the same `dispatch` event,
distinguished by `ctx["triggered_by"]` ∈ {`"auto"`, `"manual"`}. The initial
dispatch has `triggered_by` absent (or `"first"`). This keeps the event
chain simpler — one event type per dispatch attempt, regardless of how
that attempt was triggered.
```

**Backward compatibility:** Existing jots are unaffected. Their events use only original 4 ops. New dispatch ops are appended only when drain is used.

### 4.2 Event ctx payloads (per R10 Mapping contract)

All `ctx` values are JSON-serializable. `retry_budget_exhausted` is a JSON boolean (not a string), validated by `_parse_retry_budget_exhausted` in §3.2. Event ctx validation is enforced at fold entry per §4.6.

**Per-op TypedDict schemas** (for writers; readers use the same shapes):

```python
class DispatchCtx(TypedDict, total=False):
    workflow_id: str                    # REQUIRED
    attempt: int                        # REQUIRED; 1 for first, 2 for retry
    pool_selector: str                  # REQUIRED; e.g., "least_loaded"
    triggered_by: Literal["first", "auto", "manual"]   # default "first" if absent
    dispatched_from: Literal["cli", "mcp", "slash"]    # required; set by surface
    started_at_ms: int                  # REQUIRED; wall-clock at dispatch attempt;
                                       #   auto-filled by `_append_event` from
                                       #   `now_ms()` if caller omits (see §4.6).
                                       #   Used by Tier-2 timeout wiring (§6.3).

class DispatchDoneCtx(TypedDict, total=False):
    workflow_id: str                    # REQUIRED; MUST match parent dispatch
    summary: str                        # REQUIRED
    commit_sha: str                     # optional

class DispatchFailedCtx(TypedDict, total=False):
    workflow_id: str                    # REQUIRED; MUST match parent dispatch
    error: str                          # REQUIRED; format: "ExceptionType: message"
    error_id: str                       # REQUIRED; from constants/errorIds.py
    retry_budget_exhausted: bool        # REQUIRED; JSON bool (not "true"/"false" string)
    retry_after_seconds: int | None     # optional; future field for backoff hints

class DeferCtx(TypedDict, total=False):
    until: int                          # REQUIRED; epoch ms; must be > now_ms

class DeferExpiredCtx(TypedDict, total=False):
    # No required fields; the lazy fold event is self-describing by position.
    # Optional: defer_event_id (for idempotency under concurrent folds).
    defer_event_id: str | None

class DeleteCtx(TypedDict, total=False):
    reason: str | None
```

**Validation:** `_append_event` (called from all 3 sites — `cli._write_event`, `jot_tools._emit`, `drain._emit`) validates ctx against the per-op TypedDict before writing. Malformed ctx raises `JotValidationError` and is NOT appended. Validation prevents hand-edited logs, partial writes, and schema drift from cascading into broken fold state.

**Note:** `retry_budget_exhausted` is a JSON `true`/`false`, NOT the strings `"true"`/`"false"`. This was a string in an earlier draft; the JSON-bool decision matches JSONL convention and is enforced by `_parse_retry_budget_exhausted`.

### 4.3 Example event chains

**Auto-retry 2x that ultimately fails:**

```
[t+0]    capture                "refactor auth middleware" (status=open)
[t+30s]  dispatch               workflow_id=wfa, attempt=1, pool_selector=least_loaded,
                                  triggered_by=first
                                  → state: IN_FLIGHT
[t+5m]   dispatch_failed        workflow_id=wfa, attempt=1,
                                  error="workflow_status:FAILED",
                                  error_id="ERROR_JOT_WORKFLOW_FAILED",
                                  retry_budget_exhausted=false   # JSON bool
                                  → state: IN_FLIGHT (auto-retry scheduled at t+5m30)
[t+5m30] dispatch               workflow_id=wfb, attempt=2, pool_selector=least_loaded,
                                  triggered_by=auto
                                  → state: IN_FLIGHT
[t+10m]  dispatch_failed        workflow_id=wfb, attempt=2,
                                  error="workflow_status:FAILED",
                                  error_id="ERROR_JOT_WORKFLOW_FAILED",
                                  retry_budget_exhausted=true    # JSON bool
                                  → state: FAILED (terminal)
```

**Succeed on second attempt:**

```
[t+0]    capture   "add OAuth refresh"
[t+1m]   dispatch  workflow_id=wfc, attempt=1, pool_selector=least_loaded
[t+6m]   dispatch_failed workflow_id=wfc, attempt=1,
                                  error="workflow_status:TIMEOUT",
                                  retry_budget_exhausted=false   # JSON bool
[t+6m30] dispatch  workflow_id=wfd, attempt=2, pool_selector=least_loaded,
                                  triggered_by=auto
[t+8m]   dispatch_done workflow_id=wfd, summary="completed"
                                  → state: SUCCEEDED
[t+8m30] done       (user marks complete)
                                  → state: status=done, dispatch_state=None
```

### 4.4 JotSummary extension (orthogonal axes)

```python
@dataclass(frozen=True, slots=True)
class JotSummary:
    id: str
    short_id: str
    text: str
    status: Literal["open", "done"]            # lifecycle axis (unchanged)
    last_modified_ms: int
    dispatch_state: DispatchState | None       # NEW: orthogonal dispatch axis
    dispatch_workflow_id: str | None           # NEW: workflow_id of the most recent
                                               #   dispatch event; needed by reconciler
                                               #   to call get_workflow_status without
                                               #   re-scanning the event chain
    current_attempt: int                       # NEW: attempt number of the most recent
                                               #   dispatch (1 for first, 2 for retry);
                                               #   0 if never dispatched
    dispatch_started_at_ms: int | None         # NEW: wall-clock when the most recent
                                               #   dispatch was launched; None if never
                                               #   dispatched. Source for Tier-2
                                               #   timeout math (§6.3 Tier-1 reconciler).
    deferred_until: int | None                 # NEW: epoch ms; None = not deferred
    deleted: bool                              # NEW: soft-delete flag

    @property
    def handle(self) -> str:
        """Convenience: short_id for CLI/UX, full id for internal use.
        Resolves through resolve_handle; raises if ambiguous."""
        return self.short_id                    # see §6.3 for handle resolution rules
```

**Migration:** No schema migration. Existing jots get `dispatch_state=None`, `dispatch_workflow_id=None`, `dispatch_started_at_ms=None`, `deferred_until=None`, `deleted=False`, `current_attempt=0` by default (fold derives these from the absence of relevant events).

### 4.5 DispatchState enum

```python
class DispatchState(Enum):
    IN_FLIGHT = "in_flight"        # dispatch event exists, no terminal completion yet
    SUCCEEDED = "succeeded"        # latest completion event is dispatch_done
    FAILED    = "failed"           # latest completion is dispatch_failed with
                                   #   retry_budget_exhausted=true  (JSON bool)
```

`RETRYING` is **not** a separate enum value — it's represented as `IN_FLIGHT` with `current_attempt < max_attempts`.

### 4.6 State derivation in fold

Extends `mahavishnu/jot/fold.py`. After the existing R3/R9 logic settles `status` and `last_modified_ms`, a third pass computes dispatch/defer/delete fields.

**Algorithm:** find the most recent `dispatch` event (by file order). Then walk forward looking for terminal events (`dispatch_done` / `dispatch_failed`) **whose `workflow_id` matches the dispatch**. Old terminals from prior dispatch attempts are ignored — they belong to workflows that have already been resolved.

**Defensive parsing:** every ctx access in this function goes through `_coerce_int` / `_parse_retry_budget_exhausted` (per §3.2). A malformed ctx (missing key, non-numeric `attempt`, non-boolean `retry_budget_exhausted`) is logged at warning and treated as "unknown" — the fold continues with default behavior rather than crashing. This is what makes the log-corruption failure mode recoverable rather than cascading.

```python
def _derive_dispatch_fields(events: list[JotEvent]) -> tuple[DispatchState | None, int, str | None, int | None, int | None, bool]:
    """Returns: (dispatch_state, current_attempt, dispatch_workflow_id,
                 dispatch_started_at_ms, deferred_until, deleted)."""
    deleted = any(ev.op == "delete" for ev in events)
    if deleted:
        return None, 0, None, None, None, True

    # Find the most recent dispatch event (file order, not timestamp)
    most_recent_dispatch_idx = -1
    most_recent_dispatch_wf: str | None = None
    most_recent_current_attempt = 0
    most_recent_started_at_ms: int | None = None
    for i, ev in enumerate(events):
        if ev.op == "dispatch":
            wf_id = _coerce_str(ev.ctx.get("workflow_id"), field=f"events[{i}].ctx.workflow_id")
            attempt = _coerce_int(ev.ctx.get("attempt"), field=f"events[{i}].ctx.attempt")
            # started_at_ms auto-fills at emission (see _append_event below).
            # Fallback to HLC wall_ms for legacy log entries that pre-date the field.
            started = _coerce_int(
                ev.ctx.get("started_at_ms"),
                field=f"events[{i}].ctx.started_at_ms",
            )
            if started is None:
                started = ev.hlc.wall_ms
            if wf_id is None or attempt is None:
                continue                                  # malformed; skip
            most_recent_dispatch_idx = i
            most_recent_dispatch_wf = wf_id
            most_recent_current_attempt = attempt
            most_recent_started_at_ms = started

    # Compute deferred_until independently of dispatch state
    deferred_until = _compute_deferred_until(events)

    # No dispatch events: jot has never been dispatched
    if most_recent_dispatch_idx < 0:
        return None, 0, None, None, deferred_until, False

    # Walk forward from the most recent dispatch, looking for matching terminals
    dispatch_state = DispatchState.IN_FLIGHT
    for ev in events[most_recent_dispatch_idx + 1:]:
        if ev.ctx.get("workflow_id") != most_recent_dispatch_wf:
            continue
        if ev.op == "dispatch_done":
            dispatch_state = DispatchState.SUCCEEDED
            break
        if ev.op == "dispatch_failed":
            if _parse_retry_budget_exhausted(ev.ctx.get("retry_budget_exhausted")):
                dispatch_state = DispatchState.FAILED
            break   # else: auto-retry creates a new dispatch; stay IN_FLIGHT

    return (
        dispatch_state,
        most_recent_current_attempt,
        most_recent_dispatch_wf,
        most_recent_started_at_ms,
        deferred_until,
        False,
    )


def _append_event(op: str, ctx: dict[str, object]) -> None:
    """Validation + atomic-write wrapper. Auto-fills `started_at_ms` on dispatch.

    On `op == "dispatch"`, if the caller did not pass `started_at_ms`, the
    wrapper stamps the current wall-clock so Tier-2 reconcilers can compute
    elapsed time without re-scanning events (#56 of the review). The field is
    also validated against `DispatchCtx` after the fill so a caller-provided
    invalid value still raises `JotValidationError`.
    """
    if op == "dispatch" and "started_at_ms" not in ctx:
        ctx = {**ctx, "started_at_ms": now_ms()}
    # ... TypedDict validation against per-op schema, then append to log


def _compute_deferred_until(events: list[JotEvent]) -> int | None:
    """Find the active deferral. None if no defer or last defer was expired.

    Defensive: a malformed `defer` (missing/non-numeric `until`) is logged at
    warning and treated as "no defer" rather than crashing the fold."""
    pending_until: int | None = None
    for i, ev in enumerate(events):
        if ev.op == "defer":
            until = _coerce_int(ev.ctx.get("until"), field=f"events[{i}].ctx.until")
            if until is not None:
                pending_until = until
        elif ev.op == "defer_expired":
            pending_until = None
    return pending_until


# Coercion helpers (declared in drain.py per §3.2)

def _coerce_int(value: object, *, field: str) -> int | None:
    """Coerce ctx value to int, logging+returning None on failure."""
    if isinstance(value, bool):                          # bool is subclass of int — exclude
        log.warning("JOT_CTX_BAD_TYPE", field=field, value=type(value).__name__)
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            log.warning("JOT_CTX_UNPARSEABLE_INT", field=field, value=value)
            return None
    log.warning("JOT_CTX_BAD_TYPE", field=field, value=type(value).__name__)
    return None


def _coerce_str(value: object, *, field: str) -> str | None:
    """Coerce ctx value to str (workflow_id is always str)."""
    if isinstance(value, str):
        return value
    log.warning("JOT_CTX_BAD_TYPE", field=field, value=type(value).__name__)
    return None


def _parse_retry_budget_exhausted(value: object) -> bool:
    """Accept JSON bool true/false. Reject strings, ints, None with a warning."""
    if isinstance(value, bool):
        return value
    log.warning("JOT_CTX_RETRY_BUDGET_BAD_TYPE", value=type(value).__name__, value=value)
    return False   # default to "not exhausted" — keeps IN_FLIGHT, no auto-retry loop escape
```

**Why this algorithm:** scanning newest-first for "any terminal" misses the case where a user manually re-dispatches a previously-completed jot — the old terminal would mark SUCCEEDED even though the new dispatch is IN_FLIGHT. Matching `workflow_id` ensures we only consider terminals for the **current** dispatch attempt.

`defer_expired` is **lazy**: fold writes it when it sees a `defer` event with `until <= now_ms` and no `defer_expired` event after it. No background timer required. **Concurrency note:** two concurrent fold calls can both observe an expired `defer` and both attempt to write `defer_expired`. The write is idempotent because fold dedupes by checking the event chain before writing — second writer sees the existing `defer_expired` and exits silently. No `asyncio.Lock` needed because all `_append_event` writes in fold go through a single asyncio-bound sequential queue per process.

**Cross-process event-write atomicity (explicit assumption):** Drain assumes the jot log is written by **exactly one Mahavishnu process per HOME directory at a time**. This is the same single-process assumption the jot-capture hook already makes (per sub-plan 1). Multi-process appenders are explicitly out of scope (§10) and would require `fcntl.flock` around the file descriptor or atomic `O_APPEND` writes below `PIPE_BUF` (4 KiB on Linux). Inside one process, fold + drain + capture + MCP tools + CLI all serialize writes through `_append_event`, which acquires the same in-process asyncio lock that capture uses — no inter-process locking needed for the supported deployment.

### 4.7 Backward compatibility (explicit)

**No migration is required.** The new fields are populated by derivation, not by a one-time data migration:

- Existing jots have no `dispatch` events → `dispatch_state = None`, `current_attempt = 0`
- Existing jots have no `defer` events → `deferred_until = None`
- Existing jots have no `delete` events → `deleted = False`

Read sub-plan's existing tools (`jot_list`, `jot_show`, `jot_vitals`) work unchanged. They see the new fields as null/false.

## 5. Surfacing Algorithm

### 5.1 Trigger contexts

| Trigger | Mechanism | Context source | Output channel |
|---|---|---|---|
| **Session start** | `SessionStart` hook (Claude Code) | cwd, repo root, branch, recent files | `additionalContext` injected before first user message |
| **Tool result mention** | `PostToolUse` hook (Claude Code), throttled | Tool result text (truncated 4 KB) | `additionalContext` injected into next user turn |
| **Sidebar count** | Always-on | None | Part of `/jot vitals` output |

### 5.2 State filter (eligibility)

```python
def _is_surface_eligible(jot: JotSummary, now_ms: int) -> bool:
    """Used by ambient surfacing. Returns True if the jot may surface.

    Surfaced candidates: open + not-deleted + not-deferred-or-expired +
    (not-dispatched OR failed-dispatch).

    IN_FLIGHT is excluded because the user already sees these in /jot vitals
    (counts shown live). FAILED is included because it requires user action
    (manual retry or re-dispatch).
    """
    return (
        jot.status == "open"
        and not jot.deleted
        and (
            jot.deferred_until is None
            or jot.deferred_until <= now_ms
        )
        and (
            jot.dispatch_state is None
            or jot.dispatch_state == DispatchState.FAILED
        )
    )


def _is_drain_eligible(jot: JotSummary, now_ms: int) -> bool:
    """Used by drain_plan to build the bulk-action candidates list.

    Differs from _is_surface_eligible by INCLUDING IN_FLIGHT and SUCCEEDED
    jots. Rationale: the drain UI lets the user inspect in-flight progress
    (read-only display) and lets them re-dispatch succeeded jots (e.g.,
    after a worker produced partial output and they want a fresh attempt).

    The `drain_plan` wrapper applies a SECOND filter to drop IN_FLIGHT
    from the action set by default (since the action "dispatch" is a no-op
    on an IN_FLIGHT jot). The CLI flag `--include-in-flight` overrides this
    second filter.
    """
    return (
        jot.status == "open"
        and not jot.deleted
        and (
            jot.deferred_until is None
            or jot.deferred_until <= now_ms
        )
        # NO dispatch_state filter — IN_FLIGHT and SUCCEEDED both allowed here
    )
```

Surfaced candidates (ambient): **open + not-deleted + not-deferred-or-expired + (not-dispatched OR failed-dispatch)**.

Drain candidates (bulk action): **open + not-deleted + not-deferred-or-expired** (regardless of dispatch_state; the second filter in `drain_plan` strips IN_FLIGHT by default).

### 5.3 Lexical primary scorer

```python
import re
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens; len >= 2 to drop pure noise. Unicode-aware via \\w+."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 2}

def _lexical_score(jot_tokens: set[str], ctx_tokens: set[str]) -> float:
    """Coverage ratio: how much of the context does the jot cover?"""
    if not jot_tokens or not ctx_tokens:
        return 0.0
    overlap = jot_tokens & ctx_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(ctx_tokens)
```

**Threshold:** `>= 0.20` (at least 20% of context tokens hit a jot). Below that, the match is noise and ignored. **No LLM cost when lexical hits.**

**Algorithm:** if lexical pass over all eligible jots yields zero hits above `lexical_threshold`, run semantic scoring against the `semantic_max_jots` (default 30) most recently modified eligible jots. Otherwise return lexical hits.

### 5.4 Semantic fallback

**Uses mahavishnu's local `EmbeddingsService` (from `mahavishnu/core/embeddings_oneiric.py`), NOT Akosha.** Rationale: Akosha's `generate_embedding` is single-text only — 30 jots would require 60 sequential MCP round-trips, violating the "cost-aware surfacing" goal. Mahavishnu's `EmbeddingsService` exposes batch embed in one call.

```python
def _semantic_score(
    jot_text: str,
    ctx_text: str,
    embeddings: EmbeddingsService,
) -> float:
    """Batch cosine similarity via local EmbeddingsService.

    Single call: embeddings.embed([jot_text, ctx_text]) returns 2 vectors,
    we compute cosine of the pair. For 30 jots, all 60 vectors are fetched
    in 1 batched call (~50ms total) — not 30 calls.
    """
    emb = embeddings.embed([jot_text, ctx_text])
    return _cosine_similarity(emb[0], emb[1])
```

- **Threshold:** `>= 0.55` cosine (calibrated against a held-out set of (jot, context) pairs; see `tests/fixtures/surfacing_calibration.json` for the calibration set).
- **Capped at 30 jots** (filtered by `last_modified_ms` DESC before embedding).
- **Fires only when lexical pass yields zero hits** above the 0.20 threshold.
- **Failure handling:** if `EmbeddingsService.embed` raises (model not loaded, OOM, timeout), `surface_relevant` returns `[]` and logs at **warn** level (not debug — surfacing failures are operator-visible). The `SurfacingResult.surface_degraded: bool` flag is set so callers can render a hint.

**SurfacingResult shape** (replaces bare `list[JotSummary]`):

```python
@dataclass(frozen=True, slots=True)
class SurfacingResult:
    matches: list[JotSummary]                  # ranked by score DESC, trimmed to limit
    score_threshold_used: float                # for transparency / debugging
    surface_degraded: bool                     # True if embeddings failed and
                                              # only lexical results are returned
    surface_reason: Literal["matches",        # surfaced normally
                            "no_context",     # context was empty
                            "no_match",       # nothing above threshold
                            "throttled",      # throttle said no
                            "embeddings_down"] # EmbeddingsService unavailable
```

### 5.5 Throttling

```python
@dataclass
class _Throttle:
    last_fire_ms: int = 0
    min_interval_ms: int = 5000       # from settings (jot.surfacing.throttle_ms)
    last_skip_reason: str | None = None

    def should_fire(self, now_ms: int, context_tokens: int) -> tuple[bool, str | None]:
        if context_tokens < 50:
            self.last_skip_reason = "short_context"
            return False, self.last_skip_reason
        if now_ms - self.last_fire_ms < self.min_interval_ms:
            self.last_skip_reason = "throttled"
            return False, self.last_skip_reason
        self.last_fire_ms = now_ms
        self.last_skip_reason = None
        return True, None
```

Adaptive gate: skip if result text < 50 tokens (too short to be meaningful). Returns `(should_fire, skip_reason)` so the caller can render "Surfaced 0 (throttled; last fire 3s ago)" — surfacing is never silently dropped.

### 5.6 Surfacing output format

```
[*] 1 related jot: "refactor auth middleware" (3d old, open)
    /jot show a3f9c2 to read; /jot dispatch a3f9c2 to act
```

(ASCII markers used to stay compatible with non-UTF8 terminals; CLAUDE.md user-facing-text policy.)

**Cap:** 3 jots per surfacing event. If more match, rank by score DESC and trim.

### 5.7 Privilege (explicit)

Per decision §2: **anyone with MCP access can drain, dispatch, defer, delete any jot**. No per-jot ownership check. No schema migration of capture events to add `owner`. Consistent with current jot inbox threat model (per-HOME log, single-user).

### 5.8 Configuration

```yaml
jot:
  surfacing:
    enabled: true
    session_start: true
    tool_result: true
    throttle_ms: 5000
    lexical_threshold: 0.20
    semantic_threshold: 0.55
    semantic_enabled: true       # set false to skip fallback entirely
    semantic_max_jots: 30
    max_results: 3
    short_context_min_tokens: 50
  drain:
    retry:
      max_attempts: 2            # total (initial + retries); was "Auto-retry 2x" — clarified
      backoff_seconds: 30
    reconciler:
      background_interval_seconds: 30
      timeout_minutes: 10
      status_call_timeout_seconds: 30   # per-status-call deadline
    default_pool_selector: "least_loaded"
    default_workflow_adapter: "prefect"   # for trigger_workflow
```

## 6. State Machine & Retry Orchestration

### 6.1 Full state diagram

```
                  dispatch event (attempt=1)
                          │
   open ──────────────────┴──────────────────┐
   ▲                                          ▼
   │                                     IN_FLIGHT
   │                                          │
   │                  ┌───────────────────────┤
   │                  │                       │
   │      dispatch_done                  dispatch_failed
   │       (worker ok)                  (retry_budget_exhausted=false)
   │                  │                       │
   │                  ▼                       ▼ backoff 30s
   │              SUCCEEDED              dispatch (attempt=2,
   │              (terminal)             triggered_by=auto)
   │                  │                  triggered_by=auto)
   │                  │                       │
   │      user: `jot_done`                     ▼
   └────── (status flips)                IN_FLIGHT (attempt=2)
                                              │
                              ┌───────────────┤
                              │               │
                          dispatch_done   dispatch_failed
                                            (retry_budget_exhausted=true)
                                              │
                                              ▼
                                          FAILED (terminal)
                                              │
                                  user: `jot_retry`
                                              │
                                              ▼
                                          IN_FLIGHT (new attempt)
```

### 6.2 Transition table

| From | Event | To | Side effect |
|---|---|---|---|
| `open` | `dispatch` (attempt=1, `triggered_by=first`) | `IN_FLIGHT` | `trigger_workflow(adapter="prefect", task_type="jot_dispatch", params={"prompt": jot.text})` called; returned `workflow_id` stored |
| `IN_FLIGHT` | `dispatch_done` | `SUCCEEDED` | (none) |
| `IN_FLIGHT` | `dispatch_failed` (attempt=1, retry=false) | `IN_FLIGHT` | After 30s, `dispatch` event auto-appended (attempt=2, `triggered_by=auto`) |
| `IN_FLIGHT` | `dispatch_failed` (attempt=2, retry=true) | `FAILED` | Surfaced via `/jot vitals`; manual `jot_retry` available |
| `FAILED` | user calls `jot_retry` | `IN_FLIGHT` | New `dispatch` event (attempt=N+1, `triggered_by=manual`) |
| `SUCCEEDED` | user calls `jot_done` | `status=done`, `dispatch_state=None` | `done` event appended |
| `open` | user calls `jot_defer` | `status=open`, `deferred_until=<ts>` | `defer` event with `until` |
| `open` (deferred, until<=now) | fold runs | `deferred_until=None` | `defer_expired` event auto-written |
| any | user calls `jot_delete` | `deleted=True` | `delete` event appended; hidden from default lists |

`status` (`open` ↔ `done`) and `dispatch_state` are orthogonal. A SUCCEEDED jot can still be `done`-flipped via `jot_done`. A FAILED jot can be re-dispatched via `jot_retry`. There is no transition from `dispatch_state` back to `None` automatically — only `done`/`reopen`/`delete` reset the lifecycle.

### 6.3 Two-tier reconciliation

**Uses `mcp__mahavishnu__get_workflow_status` (the real MCP tool at `mahavishnu/mcp/server_core.py:432`) directly. There is NO `_workflow_substrate` ABC.** The tool returns a `dict[str, Any]` with `status` ∈ {`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`, `TIMEOUT`} plus optional `progress`, `repos_processed`, `errors_count`, etc.

**Tier 1 — Lazy reconciler (in fold):**

Every call to fold (read or write) inspects any `IN_FLIGHT` jot it encounters:

```python
TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"})
RECONCILER_TIMEOUT_MS = 10 * 60 * 1000                  # 10 min default; from §5.8 `timeout_minutes`

async def _reconcile_if_in_flight(jot: JotSummary) -> None:
    if jot.dispatch_state is not DispatchState.IN_FLIGHT:
        return
    workflow_id = jot.dispatch_workflow_id        # derived in fold per §4.4
    if workflow_id is None:
        log.warning("JOT_DISPATCH_NO_WORKFLOW_ID", handle=jot.handle)
        return

    # Tier-2 timeout gate: if the most recent dispatch has been IN_FLIGHT longer
    # than RECONCILER_TIMEOUT_MS, declare it failed WITHOUT calling the substrate.
    # The status call would just confirm RUNNING (or hang); skipping it saves
    # STATUS_CALL_TIMEOUT_SECONDS per stuck workflow per tick. The retry budget
    # is decided by `_should_exhaust_retry_budget(jot)` per §2's locked decision
    # ("Max 2 attempts total") — a timeout on attempt 1 still allows attempt 2.
    now_ms_ = now_ms()
    started_at = jot.dispatch_started_at_ms      # may be None for legacy entries
    if started_at is not None and (now_ms_ - started_at) >= RECONCILER_TIMEOUT_MS:
        budget_exhausted = _should_exhaust_retry_budget(jot)
        try:
            await _append_event("dispatch_failed", ctx={
                "workflow_id": workflow_id,
                "attempt": jot.current_attempt,
                "error": "workflow_timeout:tier2",
                "error_id": "ERROR_JOT_WORKFLOW_TIMEOUT",
                "retry_budget_exhausted": budget_exhausted,
            })
            log.error("JOT_WORKFLOW_TIMEOUT",
                      handle=jot.handle, workflow_id=workflow_id,
                      elapsed_ms=now_ms_ - started_at,
                      attempt=jot.current_attempt,
                      error_id="ERROR_JOT_WORKFLOW_TIMEOUT")
            if not budget_exhausted:
                asyncio.create_task(
                    _auto_retry_after(jot.handle, backoff_s=RETRY_BACKOFF_SECONDS)
                )
        except (JotLogUnwritableError, JotValidationError) as exc:
            log.error("JOT_RECONCILE_TIMEOUT_WRITE_FAILED",
                      handle=jot.handle, error=str(exc))
            # Don't raise — fold must not fail because reconciliation can't persist
        return                                      # done; FAILED is terminal if budget exhausted

    try:
        # Per-call deadline: don't let a slow substrate freeze fold
        status_dict = await asyncio.wait_for(
            _mcp_get_workflow_status(workflow_id),
            timeout=STATUS_CALL_TIMEOUT_SECONDS,    # 30s default per §5.8
        )
    except asyncio.TimeoutError:
        log.warning("JOT_RECONCILE_STATUS_TIMEOUT",
                    handle=jot.handle, workflow_id=workflow_id)
        return                                      # leave as IN_FLIGHT; Tier-2 will retry
    except Exception as exc:
        log.error("JOT_RECONCILE_STATUS_FAILED",
                  handle=jot.handle, workflow_id=workflow_id,
                  error_id="ERROR_JOT_RECONCILE_STATUS",
                  error=f"{type(exc).__name__}: {exc}")
        return                                      # leave as IN_FLIGHT; don't crash fold

    status_str = status_dict.get("status", "UNKNOWN")
    if status_str not in TERMINAL_STATUSES:
        return                                      # still RUNNING/PENDING; nothing to do

    succeeded = status_str == "COMPLETED"
    try:
        if succeeded:
            await _append_event("dispatch_done", ctx={
                "workflow_id": workflow_id,
                "summary": ("ok" if status_dict.get("results_count") else "completed"),
                **({"commit_sha": status_dict["commit_sha"]}
                   if status_dict.get("commit_sha") else {}),
            })
        else:
            budget_exhausted = _should_exhaust_retry_budget(jot)
            await _append_event("dispatch_failed", ctx={
                "workflow_id": workflow_id,
                "attempt": jot.current_attempt,
                "error": f"workflow_status:{status_str}",
                "error_id": "ERROR_JOT_WORKFLOW_FAILED",
                "retry_budget_exhausted": budget_exhausted,
            })
            if not budget_exhausted:
                asyncio.create_task(
                    _auto_retry_after(jot.handle, backoff_s=RETRY_BACKOFF_SECONDS)
                )
    except (JotLogUnwritableError, JotValidationError) as exc:
        log.error("JOT_RECONCILE_WRITE_FAILED",
                  handle=jot.handle, error=str(exc))
        # Don't raise — fold must not fail because reconciliation can't persist
```

**Why exceptions don't propagate:** fold is called from user-facing reads (`jot_list`, `jot_show`, `jot_vitals`). A reconciler exception that escaped into fold would convert a transient substrate hiccup into "list failed" for the user. Wrapping in try/except and logging preserves fold's contract.

**Cost per fold call:** zero if no IN_FLIGHT; one workflow status check per IN_FLIGHT. Status check is bounded by `STATUS_CALL_TIMEOUT_SECONDS=30`.

**Tier 2 — Background reconciler (every 30s):**

```python
async def _background_reconciler_loop() -> None:
    """Started at Mahavishnu server boot. Idempotent with Tier 1.

    Per-jot exception handling: a single failing jot does NOT crash the loop.
    Each iteration catches per-jot exceptions and logs them.
    """
    while True:
        await asyncio.sleep(RECONCILER_INTERVAL_SECONDS)
        try:
            jots = fold(log_path()).states
        except Exception as exc:
            log.error("JOT_RECONCILER_FOLD_FAILED", error=str(exc))
            continue                                 # try again next tick
        for jot in jots:
            if jot.dispatch_state is not DispatchState.IN_FLIGHT:
                continue
            try:
                await _reconcile_if_in_flight(jot)
            except Exception as exc:
                # A single jot's reconciliation failing must not stop the loop.
                log.error("JOT_RECONCILE_PER_JOT_FAILED",
                          handle=jot.handle, error=f"{type(exc).__name__}: {exc}")
                continue
```

Handles the "user dispatches and never reads" case. Tier-1 already covered most cases, so this is a safety net with its own self-healing: one bad jot, one bad fold, one bad tick — none of them kill the loop.

#### 6.3.1 Retry budget policy (`_should_exhaust_retry_budget`)

The lazy reconciler (§6.3) calls `_should_exhaust_retry_budget(jot)` when it observes a terminal `dispatch_failed` event to decide whether to schedule an auto-retry or mark the jot terminally `FAILED`. The policy is the single source of truth for what "budget exhausted" means; both auto-retry (§6.4) and the failure-mode table (§6.7) reference it.

```python
MAX_AUTO_ATTEMPTS = 2                                # total (1 initial + 1 auto-retry)

def _should_exhaust_retry_budget(jot: JotSummary) -> bool:
    """Return True iff this dispatch failure should NOT auto-retry.

    Policy: a failed dispatch on the LAST configured attempt exhausts the
    budget. With MAX_AUTO_ATTEMPTS=2, attempt 2 failure → exhausted (True);
    attempt 1 failure → budget remaining (False, auto-retry fires).

    Source of truth for `retry_budget_exhausted` ctx on emitted `dispatch_failed`
    events (see §4.2). The same constant is used by:
      - Lazy reconciler (this section) — emits dispatch_failed with the flag.
      - Auto-retry (§6.4) — guards re-dispatch with `current_attempt >= MAX_AUTO_ATTEMPTS`.
      - Manual retry (§6.5) — RESETS the counter to current_attempt + 1, so
        this policy is not re-applied to manual retries.

    Edge case: malformed ctx where `current_attempt` is missing or 0 (e.g.,
    log corruption) is treated as `attempt=1` for this check. Reason: a 0
    attempt shouldn't happen — the spec guarantees `attempt >= 1` on every
    dispatched event — but if it does, fail-safe behavior (retry once) is
    safer than fail-stop (terminal FAILED) since the user can't recover.
    """
    return max(jot.current_attempt, 1) >= MAX_AUTO_ATTEMPTS
```

**Test coverage** (see §7.2): `test_should_exhaust_retry_budget_true_on_second_attempt`, `test_should_exhaust_retry_budget_false_on_first_attempt`, `test_should_exhaust_retry_budget_treats_zero_as_first_attempt` (fail-safe behavior).

### 6.4 Auto-retry with idempotency

**Max 2 attempts total** (1 initial + 1 auto-retry). `MAX_AUTO_ATTEMPTS = 2` (the constant name encodes "total attempts" not "retry count").

```python
async def _auto_retry_after(handle: str, backoff_s: int) -> None:
    try:
        await asyncio.sleep(backoff_s)
    except asyncio.CancelledError:
        raise                                       # preserve cancellation semantics

    try:
        current = fold(log_path()).find(handle)
    except Exception as exc:
        log.error("JOT_AUTO_RETRY_FOLD_FAILED",
                  handle=handle, error=f"{type(exc).__name__}: {exc}")
        return                                      # skip this retry; user can retry manually

    if current.dispatch_state is not DispatchState.FAILED:
        return                                      # user already retried manually; exit
    if current.current_attempt >= MAX_AUTO_ATTEMPTS:
        return

    try:
        result = await _trigger_jot_workflow(current.text)
        workflow_id = result["workflow_id"]
    except JotDispatchError as exc:
        # Pre-flight or workflow creation failed. Write the failure to the log
        # so the user sees it via /jot vitals; do NOT silently swallow.
        try:
            await _append_event("dispatch_failed", ctx={
                "workflow_id": f"failed_to_create:{exc.error_id}",
                "attempt": current.current_attempt + 1,
                "error": f"{type(exc).__name__}: {exc}",
                "error_id": exc.error_id,
                "retry_budget_exhausted": True,        # no more retries — escalate to manual
            })
        except Exception as log_exc:
            log.error("JOT_AUTO_RETRY_LOG_FAILED",
                      handle=handle, error=str(log_exc))
        return

    try:
        await _append_event("dispatch", ctx={
            "workflow_id": workflow_id,
            "attempt": current.current_attempt + 1,
            "pool_selector": "least_loaded",
            "triggered_by": "auto",
        })
    except Exception as exc:
        # Workflow was created but the event append failed. The workflow will
        # complete but we lose the audit trail. Log loudly.
        log.error("JOT_AUTO_RETRY_EVENT_APPEND_FAILED",
                  handle=handle, workflow_id=workflow_id,
                  error_id="ERROR_JOT_DISPATCH_EVENT_APPEND",
                  error=f"{type(exc).__name__}: {exc}")
```

**Idempotency:** the post-sleep state check ensures racing auto-retry and manual retry don't both fire. The user-initiated event always wins; auto-retry exits when it sees a state that isn't FAILED.

**Error budget:** every code path that can fail (sleep cancel, fold read, trigger_workflow call, event append) is wrapped in try/except with a dedicated error_id. There are no silent failures.

### 6.5 Manual retry (`jot_retry`)

```python
async def retry_dispatch(handle: str) -> DispatchResult:
    """Manual retry of a FAILED-dispatched jot.

    Raises JotRetryError if jot is not in FAILED state.
    Raises JotDispatchError if trigger_workflow fails.
    """
    jot = fold(log_path()).find(handle)
    if jot.dispatch_state is not DispatchState.FAILED:
        raise JotRetryError(
            f"jot {jot.short_id} is not in FAILED state "
            f"(current: {jot.dispatch_state.value if jot.dispatch_state else 'none'})"
        )

    try:
        result = await _trigger_jot_workflow(jot.text)
        workflow_id = result["workflow_id"]
    except JotDispatchError:
        raise                                       # let caller handle
    except Exception as exc:
        # Unexpected — wrap with structured error
        raise JotDispatchError(
            f"unexpected error triggering workflow: {type(exc).__name__}: {exc}",
            error_id="ERROR_JOT_RETRY_UNEXPECTED",
        ) from exc

    next_attempt = jot.current_attempt + 1
    try:
        await _append_event("dispatch", ctx={
            "workflow_id": workflow_id,
            "attempt": next_attempt,
            "pool_selector": "least_loaded",
            "triggered_by": "manual",
        })
    except Exception as exc:
        log.error("JOT_RETRY_EVENT_APPEND_FAILED",
                  handle=handle, workflow_id=workflow_id,
                  error_id="ERROR_JOT_DISPATCH_EVENT_APPEND",
                  error=f"{type(exc).__name__}: {exc}")
        # Workflow was triggered; the failure to log is a serious audit gap.
        # Don't try to "undo" the trigger — the workflow will complete.
        # Surface to caller via the return shape (attempt recorded in error).

    return DispatchResult(
        handle=handle,
        workflow_id=workflow_id,
        attempt=next_attempt,
        status="in_flight",
    )


async def _trigger_jot_workflow(prompt: str) -> dict[str, Any]:
    """Thin wrapper around mcp__mahavishnu__trigger_workflow.

    Returns the workflow_id-bearing dict. Translates exceptions to JotDispatchError.
    """
    try:
        return await _mcp_trigger_workflow(
            adapter="prefect",           # default_workflow_adapter from settings
            task_type="jot_dispatch",
            params={"prompt": prompt},
        )
    except Exception as exc:
        # Surface as structured error; let caller decide retry vs. fail-fast
        raise JotDispatchError(
            f"{type(exc).__name__}: {exc}",
            error_id="ERROR_JOT_TRIGGER_WORKFLOW_FAILED",
        ) from exc
```

### 6.6 Concurrent drain handling

`drain_plan` filters candidates via `_is_drain_eligible` (§5.2) and applies a second filter to strip IN_FLIGHT by default. The second filter is a UX optimization (you can't "dispatch" an already-IN_FLIGHT jot); `--include-in-flight` overrides.

```python
def drain_plan(query: str | None, limit: int = 20, include_in_flight: bool = False) -> DrainPlan:
    try:
        all_states = fold(log_path()).states
    except Exception as exc:
        log.error("JOT_DRAIN_PLAN_FOLD_FAILED", error=str(exc))
        return DrainPlan(query=query, candidates=[], error=str(exc))

    now_ms = now()
    candidates = [j for j in all_states if _is_drain_eligible(j, now_ms=now_ms)]
    if not include_in_flight:
        candidates = [j for j in candidates if j.dispatch_state is not DispatchState.IN_FLIGHT]
    if query:
        q_tokens = _tokenize(query)
        candidates = [j for j in candidates
                      if _lexical_score(_tokenize(j.text), q_tokens) >= 0.20]
    return DrainPlan(query=query, candidates=candidates[:limit])
```

`_is_drain_eligible` is defined in §5.2. It includes IN_FLIGHT and SUCCEEDED; `drain_plan` strips IN_FLIGHT by default.

### 6.7 Failure modes

Every failure mode has an explicit detection point, recovery path, and `error_id` for Sentry/Dhara correlation.

| Failure | Detection | Recovery | error_id | Test (§7.2/§7.3) |
|---|---|---|---|---|
| Workflow substrate unreachable | `asyncio.wait_for` timeout in `_get_workflow_status` | Log warn; leave IN_FLIGHT; Tier-2 retries next tick | (warn log) | `test_lazy_reconciler_logs_warn_on_substrate_timeout` |
| Substrate returns unexpected shape | Type-check access; defensive coercion | Log warn; treat as "still running"; IN_FLIGHT unchanged | (warn log) | `test_lazy_reconciler_treats_unknown_status_as_running` |
| Worker never reports back | Tier-1 reconciler: `now_ms - jot.dispatch_started_at_ms >= RECONCILER_TIMEOUT_MS` (see §6.3 timeout gate) | Write `dispatch_failed` with `retry_budget_exhausted=_should_exhaust_retry_budget(jot)` (per §2's locked "Max 2 attempts total" — timeout on attempt 1 still allows attempt 2); skip substrate call | `ERROR_JOT_WORKFLOW_TIMEOUT` | `test_reconciler_times_out_in_flight_dispatch_after_window`, `test_reconciler_timeout_attempt_one_preserves_retry_budget`, `test_reconciler_timeout_attempt_two_exhausts_retry_budget` |
| HOME directory read-only | `_append_event` raises `JotLogUnwritableError` | Catch at every event site; surface `JotPermissionError` to caller | `ERROR_JOT_LOG_UNWRITABLE` | `test_dispatch_surfaces_permission_error_when_log_unwritable` |
| `trigger_workflow` raises (network, auth) | Caught in `_trigger_jot_workflow` | Raise `JotDispatchError(error_id=ERROR_JOT_TRIGGER_WORKFLOW_FAILED)`; for auto-retry path, write `dispatch_failed` with `retry_budget_exhausted=true` | `ERROR_JOT_TRIGGER_WORKFLOW_FAILED` | `test_dispatch_translates_trigger_failure_to_dispatch_error` |
| Auto-retry exception | Caught in `_auto_retry_after` (per-error_type) | Specific recovery per type; always logs an error_id | per-exception-type | `test_auto_retry_logs_error_id_per_exception_type` |
| Reconciler crash mid-write | Lazy reconciler (Tier 1) catches up on next read | Self-healing; logs `JOT_RECONCILE_PER_JOT_FAILED` | `JOT_RECONCILE_PER_JOT_FAILED` | `test_lazy_reconciler_logs_per_jot_error_and_continues` |
| Tier-2 reconciler per-jot failure | Caught per-jot in `_background_reconciler_loop` | Other jots still reconciled; failed jot logged | `JOT_RECONCILE_PER_JOT_FAILED` | `test_background_reconciler_skips_failing_jot_continues_others` |
| Tier-2 reconciler per-tick failure (fold crash) | Caught per-tick | Loop continues next tick | `JOT_RECONCILER_FOLD_FAILED` | `test_background_reconciler_continues_after_fold_failure` |
| User dispatches same jot twice rapidly | Two `dispatch` events appended; fold sees new IN_FLIGHT, old workflow abandoned | User can `jot_retry` to manually re-trigger | (no error) | `test_rapid_double_dispatch_abandons_old_workflow` |
| Mahavishnu server down during dispatch | `trigger_workflow` raises | `JotDispatchError(error_id=ERROR_JOT_TRIGGER_WORKFLOW_FAILED)`; user retries when server is back | `ERROR_JOT_TRIGGER_WORKFLOW_FAILED` | `test_dispatch_when_mahavishnu_down_surfaces_dispatch_error` |
| Embeddings service unreachable during surfacing | Caught in `_semantic_score`; lexical results still returned | `SurfacingResult.surface_degraded=true`; log warn | `JOT_EMBEDDINGS_DOWN` | `test_semantic_fallback_returns_degraded_when_embeddings_unreachable` |
| `_reconcile_if_in_flight` raises (unexpected) | Caught in Tier-2 loop per-jot AND in Tier-1 caller | Logged; fold continues | `JOT_RECONCILE_PER_JOT_FAILED` | `test_lazy_reconciler_unexpected_exception_logged_not_propagated` |
| Embeddings returns empty list | Detected in `_semantic_score` (length mismatch) | Return 0.0 for that pair; mark `surface_degraded=true` | `JOT_EMBEDDINGS_EMPTY` | `test_semantic_fallback_treats_empty_embed_as_no_match_with_degraded_flag` |
| Embeddings returns wrong-shape vectors | Detected in `_cosine_similarity` (length mismatch) | Return 0.0 for that pair; mark `surface_degraded=true` | `JOT_EMBEDDINGS_BAD_SHAPE` | `test_semantic_fallback_treats_wrong_shape_as_no_match_with_degraded_flag` |
| Embeddings timeout (slow model) | `asyncio.wait_for` around `embed()` | Return 0.0; mark `surface_degraded=true` | `JOT_EMBEDDINGS_TIMEOUT` | `test_semantic_fallback_returns_degraded_when_embeddings_timeout` |
| `defer_expired` lazy write races between two fold calls | Fold dedupes by checking event chain before writing | Second writer sees existing `defer_expired`, exits silently | (no error) | `test_defer_expired_lazy_write_is_idempotent_under_concurrent_folds` |

### 6.8 Configuration

`settings/mahavishnu.yaml`:

```yaml
jot:
  drain:
    retry:
      max_attempts: 2                # total (1 initial + 1 retry)
      backoff_seconds: 30
    reconciler:
      background_interval_seconds: 30
      timeout_minutes: 10
      status_call_timeout_seconds: 30
    default_pool_selector: "least_loaded"
    default_workflow_adapter: "prefect"
```

The Oneiric loader exposes these via a new `JotSettings` pydantic model nested in `MahavishnuSettings`. Reading: `from mahavishnu.core.config import get_settings; get_settings().jot.drain.retry.max_attempts`.

### 6.9 Hook wiring (precondition for surfacing)

Surfacing fires from `SessionStart` and `PostToolUse` Claude Code hooks. These hooks **are not currently wired** in `.claude/settings.json`. Drain's implementation plan creates the wrapper scripts AND wires the hooks in a single atomic commit; surfacing stays disabled until the plan completes.

**Preconditions** (all must land before the wiring commit can merge):

1. `mahavishnu/jot/drain.py` must exist with `surface_relevant(trigger, context_text, limit)` callable. The wrappers import this; without it the wiring fails with `ModuleNotFoundError`.
2. `.claude/hooks/jot-session-start.py` — thin wrapper: `from mahavishnu.jot.drain import surface_relevant; print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...}}))`
3. `.claude/hooks/jot-post-tool-use.py` — thin wrapper: same import, gated by `_Throttle.should_fire()` (§5.5).
4. `.claude/hooks/jot-capture.py` — thin wrapper around the existing `mahavishnu/hooks/jot_capture.py::capture_hook` (sub-plan 1 already shipped the capture hook logic).

**Wiring** (`.claude/settings.json` additions — added verbatim at implementation time):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {"type": "command", "command": "/Users/les/Projects/mahavishnu/.venv/bin/python3 .claude/hooks/jot-session-start.py"}
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "mcp__*",
        "hooks": [
          {"type": "command", "command": "/Users/les/Projects/mahavishnu/.venv/bin/python3 .claude/hooks/jot-post-tool-use.py"}
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {"type": "command", "command": "/Users/les/Projects/mahavishnu/.venv/bin/python3 .claude/hooks/jot-capture.py"}
        ]
      }
    ]
  }
}
```

**Notes on the JSON literal above** (review-fixed):

- **No `jot-capture.py` under SessionStart.** `capture_hook` reads `prompt` from the stdin payload; SessionStart events carry no `prompt`, so a SessionStart→capture hook is a no-op. Capture belongs only on UserPromptSubmit.
- **No `"matcher"` key on UserPromptSubmit.** Per Claude Code's hook schema, matchers apply to PreToolUse / PostToolUse / PermissionRequest / etc. UserPromptSubmit fires on every prompt unconditionally; the empty matcher key would be silently ignored and signals a misunderstanding of the schema.
- **Absolute venv path, not bare `python`.** The existing `.claude/settings.json` entries (lines 7, 18, 22, 33, 37) use `/Users/les/Projects/mahavishnu/.venv/bin/python3`. Bare `python` resolves against the parent shell's PATH; if `.venv/bin` isn't on PATH, the hooks fail with `ModuleNotFoundError` on `mahavishnu.*`. The hook wrappers must use the same absolute path as the rest of the project's hooks.

**Tests required:**

- `tests/unit/test_claude_settings_hooks_format.py::test_project_settings_hook_commands_resolve` (existing) — asserts every command path resolves on disk. **Will fail until the wrapper scripts (§6.9 preconditions 2-4) exist.** Implementation must land all four preconditions before this test can pass.
- `tests/integration/jot/test_drain_hooks_e2e.py` — NEW, exercised by the implementation plan. Subprocess-imports each wrapper, feeds it a synthetic hook payload, asserts the `additionalContext` output. Created as part of this work, not pre-existing.

## 7. Testing Strategy

### 7.1 Test category matrix

| Category | File pattern | Purpose | Mocks needed |
|---|---|---|---|
| Unit (state machine) | `tests/unit/jot/test_drain.py::TestStateMachine` | Pure logic | None (pure fold tests; uses `_coerce_int`/`_parse_retry_budget_exhausted` directly) |
| Unit (retry) | `tests/unit/jot/test_drain.py::TestRetry` | Retry orchestration | `fake_trigger_workflow`, `fast_backoff`, `no_async_sleep` |
| Unit (scorer) | `tests/unit/jot/test_drain_surfacing.py` | Lexical + semantic scoring | `fake_embeddings_service` |
| Unit (reconciler, async) | `tests/unit/jot/test_drain_reconciler.py` | Lazy reconciler — `async def` tests run under `pytest-asyncio` (`asyncio_mode = "auto"` per CLAUDE.md). No real workflow calls; uses `fake_get_workflow_status`. | `fake_get_workflow_status`, `clock` |
| Unit (filters) | `tests/unit/jot/test_drain_filters.py` | State eligibility | None |
| Unit (helpers) | `tests/unit/jot/test_drain_helpers.py` | Tokenizer, coercion, budget math | None |
| Unit (MCP wrappers) | `tests/unit/jot/test_drain_mcp_tools.py` | 6 new MCP tool wrappers | `fake_trigger_workflow`, fold fixture |
| Integration (CLI) | `tests/integration/jot/test_drain_cli.py` | Typer CLI for 6 new subcommands | `CliRunner`, fold fixture |
| Integration (e2e) | `tests/integration/jot/test_drain_e2e.py` | Full drain flow | `fake_workflow_substrate` (returns dict per real tool) |
| Integration (resurfacing) | `tests/integration/jot/test_drain_resurfacing_e2e.py` | Surfacing paths | `fake_embeddings_service` |
| Integration (auto-retry) | `tests/integration/jot/test_drain_auto_retry_e2e.py` | Full auto-retry sequence | `fast_backoff`, `fake_trigger_workflow_sequence` |
| Integration (concurrent) | `tests/integration/jot/test_drain_concurrent_e2e.py` | Race conditions | `asyncio.gather`, fake workflow substrate |
| Integration (hooks) | `tests/integration/jot/test_drain_hooks_e2e.py` | SessionStart + PostToolUse hook scripts in isolation | subprocess |
| Property (idempotency) | `tests/property/jot/test_drain_idempotency.py` | Re-drain invariants | `fake_embeddings_service` |
| Property (state invariants) | `tests/property/jot/test_drain_state_invariants.py` | Attempt count monotonicity, workflow_id match correctness | None (pure fold) |
| Property (ranking) | `tests/property/jot/test_drain_surfacing_ranking.py` | Ranking determinism + score-monotonicity under lexical ties | `fake_embeddings_service` |

**Mocking catalog** (§7.5 in the previous draft):

| Dependency | How to mock | Fixture location |
|---|---|---|
| `mcp__mahavishnu__trigger_workflow` | `monkeypatch.setattr(drain, "_mcp_trigger_workflow", fake)` | `tests/conftest.py::fake_trigger_workflow` |
| `mcp__mahavishnu__get_workflow_status` | `monkeypatch.setattr(drain, "_mcp_get_workflow_status", fake_dict_by_workflow_id)` | `tests/conftest.py::fake_workflow_substrate` |
| `EmbeddingsService.embed` | `monkeypatch.setattr(drain, "_embeddings", fake)` | `tests/conftest.py::fake_embeddings_service` |
| Claude Code hook runner | Bypass entirely — call hook function with synthetic context | (no fixture; just import + call) |
| `asyncio.sleep` | Patched to no-op (`no_async_sleep` fixture) | `tests/conftest.py::no_async_sleep` |
| Backoff | `fast_backoff` fixture sets `RETRY_BACKOFF_SECONDS = 0` | `tests/conftest.py::fast_backoff` |
| Wall clock for `until` expiry | `monkeypatch.setattr("time.time", fake_clock)` (preferred over `time-machine`) | `tests/conftest.py::clock` |

### 7.2 Key unit test specifications

**State machine:**
- `test_dispatch_appends_event_with_workflow_id`
- `test_dispatch_done_transitions_to_succeeded`
- `test_dispatch_failed_with_budget_remaining_keeps_in_flight`
- `test_dispatch_failed_with_budget_exhausted_marks_failed`
- `test_unordered_events_resolve_to_correct_final_state`
- `test_defer_sets_deferred_until`
- `test_defer_expired_clears_deferred_until`
- `test_delete_marks_jot_deleted`
- `test_deleted_jots_excluded_from_default_lists`

**Retry:**
- `test_auto_retry_after_first_failure_with_fast_backoff`
- `test_auto_retry_exhausted_marks_terminal_failure`
- `test_manual_retry_after_failed_resets_attempt_count`
- `test_manual_retry_during_auto_retry_backoff_wins`
- `test_retry_state_guard_raises_on_non_failed`

**Surfacing scorer:**
- `test_lexical_score_zero_on_no_overlap`
- `test_lexical_score_proportional_to_overlap`
- `test_short_tokens_filtered`
- `test_lexical_threshold_filters_low_score`
- `test_semantic_fallback_only_invoked_on_zero_lexical`
- `test_semantic_fallback_skipped_when_lexical_hits`
- `test_semantic_fallback_silent_when_akosha_unreachable` → renamed `test_semantic_fallback_returns_degraded_when_embeddings_unreachable`
- `test_surfacing_throttles_five_second_window`
- `test_surfacing_skips_short_context`

**Lazy reconciler:**
- `test_lazy_reconciler_writes_dispatch_done_for_in_flight`
- `test_lazy_reconciler_idempotent_when_already_terminal`
- `test_lazy_reconciler_writes_dispatch_failed_with_correct_budget`
- `test_lazy_reconciler_logs_warn_on_substrate_timeout`
- `test_lazy_reconciler_treats_unknown_status_as_running`
- `test_lazy_reconciler_logs_per_jot_error_and_continues`
- `test_lazy_reconciler_unexpected_exception_logged_not_propagated`

**State filter:**
- `test_open_jots_are_drain_eligible`
- `test_done_jots_excluded_from_drain`
- `test_deferred_jots_excluded_until_expiry`
- `test_in_flight_jots_excluded_from_drain_candidates`
- `test_failed_jots_surfaced_for_attention`
- `test_deleted_jots_excluded_from_both`

**Retry budget policy (`_should_exhaust_retry_budget`, §6.3.1):**
- `test_should_exhaust_retry_budget_true_on_second_attempt` — `current_attempt=2` returns True
- `test_should_exhaust_retry_budget_false_on_first_attempt` — `current_attempt=1` returns False
- `test_should_exhaust_retry_budget_treats_zero_as_first_attempt` — fail-safe: `current_attempt=0` returns False (lets retry fire)

**Tier-2 timeout gate (§6.3):**
- `test_reconciler_times_out_in_flight_dispatch_after_window` — at `now - started_at_ms >= RECONCILER_TIMEOUT_MS`, write `dispatch_failed` and skip the substrate call
- `test_reconciler_timeout_attempt_one_preserves_retry_budget` — timeout on attempt 1: `_should_exhaust_retry_budget` returns False → auto-retry scheduled, jot returns to IN_FLIGHT
- `test_reconciler_timeout_attempt_two_exhausts_retry_budget` — timeout on attempt 2: `_should_exhaust_retry_budget` returns True → terminal FAILED, no auto-retry
- `test_reconciler_skips_timeout_check_when_started_at_ms_is_none` — legacy log entries with missing `started_at_ms` skip the gate (fall through to status check)
- `test_reconciler_calls_substrate_when_within_timeout_window` — sanity: short-lived dispatches go through `_get_workflow_status` normally

**Fold edge cases (`_derive_dispatch_fields`, §4.6):**
- `test_fold_handles_orphan_terminal_with_no_dispatch_event` — `dispatch_done` without a preceding `dispatch` is logged warn and treated as no-state (defensive)
- `test_fold_hlc_tiebreaker_breaks_workflow_id_match_correctly` — when two `dispatch` events have identical `(wall_ms, ctr)`, lex on workflow_id picks the canonical match
- `test_fold_keeps_parked_event_when_workflow_id_matches` — defensive: malformed `workflow_id` in terminal → treat as "still running", IN_FLIGHT unchanged
- `test_fold_drops_jot_with_dispatch_and_then_delete` — `delete` after dispatch: deleted flag wins, all dispatch state cleared
- `test_fold_deferred_until_from_later_defer_overrides_earlier` — two `defer` events: the LATER one wins (regardless of timestamp)
- `test_fold_defer_expired_after_defer_clears_pending_until` — `defer_expired` always clears the pending `until`
- `test_fold_malformed_ctx_logs_warning_continues` — non-numeric `attempt` or non-bool `retry_budget_exhausted` → log warn, treat as unknown
- `test_fold_started_at_ms_falls_back_to_event_hlc_wall_ms` — legacy entries without `started_at_ms` use `ev.hlc.wall_ms`
- `test_fold_no_dispatch_yields_none_state_and_zero_attempt` — baseline: capture-only jot has `dispatch_state=None`, `current_attempt=0`, `dispatch_started_at_ms=None`

**Defer_expired lazy-write idempotency (§4.6 concurrency note):**
- `test_defer_expired_lazy_write_is_idempotent_under_concurrent_folds` — two concurrent `fold()` calls both observing an expired `defer` result in exactly ONE `defer_expired` event written (second writer sees existing event and exits)
- `test_defer_expired_skipped_when_defer_was_already_expired_before_call` — `defer(until=past)` with no subsequent event: fold writes `defer_expired`
- `test_defer_expired_skipped_when_newer_defer_supersedes` — `defer(until=past)` then `defer(until=future)`: NO `defer_expired` written

**Embeddings failure modes (`_semantic_score`, §5.4):**
- `test_semantic_fallback_returns_degraded_when_embeddings_unreachable` — `embed()` raises (network/OOM); `surface_degraded=true`, lexical results still returned
- `test_semantic_fallback_treats_empty_embed_as_no_match_with_degraded_flag` — `embed()` returns `[]`; `surface_degraded=true`, no matches
- `test_semantic_fallback_treats_wrong_shape_as_no_match_with_degraded_flag` — vector length mismatch (e.g., embed returns 1D but model expects 384); `surface_degraded=true`
- `test_semantic_fallback_returns_degraded_when_embeddings_timeout` — `asyncio.wait_for` around `embed()` triggers; `surface_degraded=true`, lexical preserved

**Cross-process atomicity assumption (§4.6 explicit policy):**
- `test_append_event_serializes_through_in_process_lock` — concurrent `_append_event` calls within one process produce ordered, non-interleaved lines
- `test_dispatch_surfaces_permission_error_when_log_unwritable` — read-only HOME: `_append_event` raises `JotLogUnwritableError`, dispatcher surfaces to caller

### 7.3 Key integration test specifications

**Full dispatch flow:**
- `test_full_dispatch_to_succeeded`
- `test_full_dispatch_to_failed_then_succeeded`
- `test_concurrent_drain_plan_excludes_in_flight`

**Surfacing paths:**
- `test_lexical_hit_skips_semantic`
- `test_zero_lexical_triggers_semantic_fallback`

**Concurrent drain:**
- `test_two_concurrent_drain_plans_dont_double_dispatch`

### 7.4 Key property test specifications

**Strategy:** each Hypothesis example asserts a *load-bearing* property — one that a naive implementation could plausibly violate. Avoid tautologies like "fold returns something" or "rank produces a list". Each test names what could be wrong and the test exercises it.

```python
# Re-drain idempotency: applying drain twice (or N times) to the same log
# yields the same final state and writes the same set of events as one drain.
# Catches: accidental event accumulation, off-by-one state derivation.
@given(events=event_chains(), n_calls=st.integers(min_value=1, max_value=10))
def test_drain_is_idempotent_under_repeated_application(events, n_calls):
    log = setup_log(events)
    before = log.snapshot()
    for _ in range(n_calls):
        drain_plan(query=None).execute()
    after = log.snapshot()
    assert drain_plan(query=None).candidates == drain_plan(query=None).candidates
    assert after.event_count <= before.event_count + MAX_EVENTS_PER_DRAIN

# Attempt-count monotonicity: current_attempt never exceeds MAX_AUTO_ATTEMPTS=2,
# and never goes BACKWARDS without a manual retry event.
# Catches: off-by-one in auto-retry guard, lost-update in fold re-derivation.
@given(events=random_event_chains_with_dispatch_ops())
def test_attempt_count_never_exceeds_max_and_only_advances_on_retry(events):
    state = fold(events)
    assert 0 <= state.current_attempt <= MAX_AUTO_ATTEMPTS
    # If two dispatch events exist with attempts 1 and 2, no third
    # auto-dispatch can produce attempt=3 without an intervening manual_retry.
    assert count_dispatch_events(events) <= MAX_AUTO_ATTEMPTS + manual_retries(events)

# State derivation determinism: the same event chain always produces the
# same JotSummary, regardless of insertion order (within monotonic HLC).
# Catches: non-deterministic dict iteration, clock-dependent state.
@given(events=random_event_chains())
def test_state_derivation_is_pure_function_of_events(events):
    s1 = fold(events).find(handle)
    s2 = fold(events[::-1]).find(handle) if all_hlc_monotonic(events[::-1]) else None
    if s2 is not None:
        assert s1 == s2

# Ranking transitivity: for any jots a, b, c and threshold t, if score(a) >= t
# and score(a) > score(b) and score(b) > score(c), then score(a) > score(c).
# Catches: scoring instability, sort non-determinism.
@given(jots=random_jot_texts(min_count=3, max_count=20), threshold=st.floats(0.0, 1.0))
def test_ranking_is_transitive(jots, threshold):
    results = surface_relevant("session_start", context_text="refactor auth", limit=10).matches
    scores = [r.score for r in results]
    for i in range(len(scores)):
        for j in range(i + 1, len(scores)):
            assert scores[i] >= scores[j]                # ranking is sorted DESC

# Top-N truncation: surfacing always returns ≤ limit results, even when many
# jots match above threshold. Result set is a subset of the full match set.
@given(
    jots=random_jot_texts(min_count=20, max_count=100),
    limit=st.integers(min_value=1, max_value=10),
    threshold=st.floats(0.0, 0.5),
)
def test_top_n_truncates_to_limit(jots, limit, threshold):
    full = surface_relevant("session_start", context_text="x", limit=len(jots)).matches
    truncated = surface_relevant("session_start", context_text="x", limit=limit).matches
    assert len(truncated) <= limit
    assert set(r.id for r in truncated).issubset(set(r.id for r in full))

# Embedding determinism via fake: drain's surfacing logic should be
# deterministic when the embeddings service is deterministic. This test
# exercises drain's `_semantic_score` against a deterministic fake; a
# non-deterministic real-model test would belong in `tests/unit/test_embeddings_*`
# (drain's contract is "given a deterministic embeddings service, surface
# deterministically" — NOT "guarantee model determinism", which is an
# embeddings-service concern, not drain).
@given(text=st.text(min_size=1, max_size=200))
def test_semantic_fallback_is_deterministic_when_embeddings_deterministic(text):
    fake = fake_embeddings_service(deterministic=True)    # per §7.1 mocking catalog
    e1 = _semantic_score(jot_text=text, ctx_text=text, embeddings=fake)
    e2 = _semantic_score(jot_text=text, ctx_text=text, embeddings=fake)
    assert e1 == e2                                       # exact equality — fake is deterministic

# Tier-2 timeout invariance: dispatch_started_at_ms derived from any
# dispatch event satisfies |derived - emitted - clock_skew| ≤ max_event_loop_lag.
# Catches: clock regression, HLC/wall-clock mismatch.
@given(events=random_event_chains_with_dispatch_ops())
def test_started_at_ms_within_clock_skew_bound(events):
    state = fold(events)
    if state.dispatch_started_at_ms is not None and events:
        # No event in the chain should have hlc.wall_ms earlier than derived.
        assert state.dispatch_started_at_ms >= min(ev.hlc.wall_ms for ev in events)
```

### 7.5 Mocking catalog

(Moved to §7.1 — see "Mocking catalog" subsection there.)

### 7.6 Coverage targets

| Module | Min | Rationale |
|---|---|---|
| `mahavishnu/jot/drain.py` | 90% | New logic; centerpiece state machine |
| Scorers (`_lexical_score`, `_semantic_score`) | 95% | Pure functions; cheap to fully cover |
| Reconciler (`_reconcile_if_in_flight`) | 85% | I/O-heavy; branches harder to cover |
| `mahavishnu/jot/fold.py` (extended) | 89% (gate) | New state derivation must keep coverage |

## 8. Configuration Reference

### 8.1 `settings/mahavishnu.yaml` (extend)

```yaml
jot:
  surfacing:
    enabled: true
    session_start: true
    tool_result: true
    throttle_ms: 5000
    lexical_threshold: 0.20
    semantic_threshold: 0.55
    semantic_enabled: true
    semantic_max_jots: 30
    max_results: 3
  drain:
    retry:
      enabled: true
      max_attempts: 2
      backoff_seconds: 30
    reconciler:
      background_interval_seconds: 30
      timeout_minutes: 10
```

### 8.2 Environment variables (none new)

Drain reads configuration from `settings/mahavishnu.yaml` exclusively. No new env vars.

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Auto-retry doubles cost on persistent failures | Medium | Low (auto-retry is bounded at 2) | `retry_budget_exhausted` flag prevents indefinite retry; manual `jot_retry` is the escalation path |
| Surfacing clutters Claude's context | Medium | Medium (annoyance) | Cap at 3 jots; threshold 0.20 lexical; 5s throttle; opt-out per setting |
| Akosha dependency becomes a hard requirement | Low | Medium | Fallback to lexical-only when Akosha unreachable; never crashes |
| Lazy reconciler races with concurrent dispatch | Low | Medium (duplicate events) | Idempotency check in `_reconcile_if_in_flight`; event chain is append-only so duplicates are detectable |
| Soft delete accumulates forever | Low | Low | `/jot vitals` includes deleted count; users can purge via separate tool (out of scope) |
| `defer_expired` lazy writes cause state divergence | Low | Low | Fold writes it consistently on any read; reconciler triggers reads |
| Background reconciler never starts | Low | Medium (stuck jots) | Tied to Mahavishnu server boot; manual `jot_retry` available as escape hatch |

## 10. Out of Scope (Explicit)

- **Multi-user authorization.** Anyone with MCP access can act on any jot.
- **Capture changes.** Sub-plan 1 is frozen.
- **Drain as a separate adapter.** Tightly integrated per architecture decision.
- **Drain UI / TUI.** CLI + MCP + slash command only.
- **Persistent dispatch state outside the log.** Jot log is the only store.
- **Tag/priority system for surfacing.** Could be added later if lexical + semantic insufficient.
- **Scheduling (cron-like) for surfacing.** Only hooks fire surfacing; no cron.
- **Pagination on drain output.** Hard cap at 20 candidates per plan; bulk-by-query.
- **Cross-jot dependencies** (e.g., "dispatch B after A succeeds"). Sequential dispatches are user's responsibility.
- **Audit log export.** The JotEvent chain IS the audit log.

## 11. References

- `docs/superpowers/specs/2026-09-09-jot-capture-design.md` — Sub-plan 1: capture primitives, HLC, redact
- `docs/superpowers/specs/2026-09-09-jot-read-design.md` — Sub-plan 2: fold, render, MCP tools (read surface)
- `docs/superpowers/specs/2026-09-09-jot-inbox-design.md` — Umbrella spec for the Jot Inbox trilogy
- `mahavishnu/mcp/tools/profiles.py` — Tool profile registration (8 existing jot tools → 14 with drain)
- `mahavishnu/mcp/server_core.py` — `trigger_workflow` (line 273), `get_workflow_status` (line 432). Drain's actual dispatch + status-check primitives.
- `mahavishnu/workers/cloud_worker.py` — Worker contract that dispatched jots consume
- `mahavishnu/pools/` — Pool routing (Drain does NOT use `pool_route_execute` directly; goes via `trigger_workflow`)
- `mahavishnu/core/embeddings_oneiric.py` — `EmbeddingsService.embed([texts])` for semantic fallback
- `.claude/settings.json` — must be wired with `SessionStart` + `PostToolUse` + `UserPromptSubmit` hooks (§6.9)
- CLAUDE.md `mahavishnu-tool-preference-policy.md` — Pool-routing-first doctrine

## 12. Open Questions

**None.** All design decisions resolved via the brainstorming Q&A (see §2). Sub-decisions within sections were taken during design and noted inline.
