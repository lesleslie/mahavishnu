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
| Retry policy | Auto-retry 2x with 30s backoff, then `FAILED` | Handles transients; persistent failures escalate |
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
                                         delete, retry, surfacing.
EXTEND:  mahavishnu/mcp/tools/jot_tools.py   New MCP tools (5).
EXTEND:  mahavishnu/cli/jot_cli.py       Register 5 new Typer subcommands.
EXTEND:  mahavishnu/commands/jot.md     Extend with `/jot drain` and
                                         updated `/jot vitals`.
EXTEND:  settings/mahavishnu.yaml        Add `jot.drain.*` and
                                         `jot.surfacing.*` config sections.

NEW:     tests/unit/jot/test_drain.py                State machine, retry, filters.
NEW:     tests/unit/jot/test_drain_surfacing.py      Lexical + semantic scorer.
NEW:     tests/unit/jot/test_drain_reconciler.py     Lazy reconciler behavior.
NEW:     tests/unit/jot/test_drain_filters.py        State-eligibility filter tests.
NEW:     tests/unit/jot/test_drain_helpers.py        Tokenizer, retry budget math.
NEW:     tests/integration/jot/test_drain_e2e.py     Full drain flow against fake pool.
NEW:     tests/integration/jot/test_drain_resurfacing_e2e.py
NEW:     tests/integration/jot/test_drain_auto_retry_e2e.py
NEW:     tests/integration/jot/test_drain_concurrent_e2e.py
NEW:     tests/property/jot/test_drain_idempotency.py
NEW:     tests/property/jot/test_drain_state_invariants.py
NEW:     tests/property/jot/test_drain_surfacing_ranking.py

EXTEND:  tests/conftest.py                Fixtures: mock_pool_route_execute,
                                          fake_workflow_substrate,
                                          deterministic_akosha, fast_backoff,
                                          no_async_sleep, clock.
```

### 3.2 Module boundaries (`mahavishnu/jot/drain.py`)

```python
class DispatchState(Enum):                          # IN_FLIGHT, SUCCEEDED, FAILED
    IN_FLIGHT = "in_flight"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

@dataclass(frozen=True, slots=True)
class JotDispatch:                                  # jot_id, workflow_id, attempt,
                                                    # max_attempts, last_error, started_at
@dataclass(frozen=True, slots=True)
class SurfacingContext:                             # trigger, source_text, candidate_jots
@dataclass(frozen=True, slots=True)
class DrainPlan:                                    # query, candidates, action proposals
@dataclass(frozen=True, slots=True)
class DispatchResult:                               # jot_id, workflow_id, attempt, status

# Drain primitives
def drain_plan(query: str | None, limit: int = 20) -> DrainPlan
def execute_action(plan: DrainPlan, action: str, jot_id: str) -> ActionResult
def dispatch_jot(jot_id: str) -> DispatchResult
def retry_dispatch(jot_id: str) -> DispatchResult
def defer_jot(jot_id: str, until_ms: int, reason: str | None = None) -> DeferResult
def delete_jot(jot_id: str, reason: str | None = None) -> DeleteResult

# Surfacing primitives
def surface_relevant(
    trigger: Literal["session_start", "tool_result"],
    context_text: str,
    limit: int = 3,
) -> list[JotSummary]

# Reconciliation (lazy + background)
async def _reconcile_if_in_flight(jot: JotSummary) -> None
async def _background_reconciler_loop() -> None
async def _auto_retry_after(jot_id: str, backoff_s: int) -> None

# Scorers (internal)
def _tokenize(text: str) -> set[str]
def _lexical_score(jot_tokens: set[str], ctx_tokens: set[str]) -> float
def _semantic_score(jot_text: str, ctx_text: str) -> float

# State filter (internal)
def _is_drain_eligible(jot: JotSummary, now_ms: int) -> bool
def _is_surface_eligible(jot: JotSummary, now_ms: int) -> bool
```

### 3.3 MCP tool surface (extends `mahavishnu/mcp/tools/jot_tools.py`)

| Tool | Inputs | Output | Purpose |
|---|---|---|---|
| `mcp__mahavishnu__jot_drain` | `query: str \| None = None`, `limit: int = 20`, `include_in_flight: bool = False` | `DrainPlanDict` | Bulk action selection. Returns plan, no execution. |
| `mcp__mahavishnu__jot_dispatch` | `jot_id: str` | `DispatchResultDict` | Per-jot dispatch. Includes auto-retry 2x internally. |
| `mcp__mahavishnu__jot_defer` | `jot_id: str`, `until_ms: int`, `reason: str \| None = None` | `JotSummaryDict` | Snooze until timestamp. |
| `mcp__mahavishnu__jot_delete` | `jot_id: str`, `reason: str \| None = None` | `JotSummaryDict` | Soft delete (audit retained). |
| `mcp__mahavishnu__jot_retry` | `jot_id: str` | `DispatchResultDict` | Manual retry of FAILED dispatch. |
| `mcp__mahavishnu__jot_resurface` | `trigger: str`, `context_text: str`, `limit: int = 3` | `list[JotSummaryDict]` | Ambient surfacing trigger. |

### 3.4 CLI surface (extends `mahavishnu/cli/jot_cli.py`)

```bash
mahavishnu jot drain [--query Q] [--limit N] [--include-in-flight]
# Interactive bulk drain: lists candidates, prompts action per jot
# Action choices: dispatch | defer | done | delete | skip
# --query filters candidates by lexical substring
# --limit caps candidate list (default 20)
# --include-in-flight forces inclusion of IN_FLIGHT jots (rare)

mahavishnu jot dispatch JOT_ID
# Single-jot dispatch; prints workflow_id + summary; non-interactive

mahavishnu jot defer JOT_ID --until TIMESTAMP [--reason R]
# TIMESTAMP is epoch ms or ISO-8601 (parsed and converted)
mahavishnu jot delete JOT_ID [--reason R]
mahavishnu jot retry JOT_ID
mahavishnu jot resurfacing --trigger {session_start,tool_result} [--context TEXT]
```

### 3.5 Slash command (extends `mahavishnu/commands/jot.md`)

```markdown
# /jot — show jot inbox vitals (existing, extended)

# Extended output for /jot vitals:
#   open: 7
#   done: 12
#   dispatched_in_flight: 2
#   dispatched_failed: 1   ← action needed
#   deferred: 3
#   deleted: 0

# New: /jot drain [--query Q] [--limit N]
#   Runs `mahavishnu jot drain` in interactive mode.
#   Per-jot action selection: dispatch, defer, done, delete, skip.
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

| Op | Required ctx | Optional | Notes |
|---|---|---|---|
| `dispatch` | `workflow_id`, `attempt`, `pool_selector` | `triggered_by` (`first` \| `auto` \| `manual`), `dispatched_from` (`cli` \| `mcp` \| `slash`) | Any dispatch attempt. `triggered_by` distinguishes initial (`first`, default) from auto-retry (`auto`) from manual retry (`manual`). |
| `dispatch_done` | `workflow_id`, `summary` | `commit_sha` | System event from reconciler; `workflow_id` MUST match the dispatch it completes |
| `dispatch_failed` | `workflow_id`, `attempt`, `error`, `retry_budget_exhausted` (`true` \| `false`) | — | System event; budget flag drives auto-retry decision; `workflow_id` MUST match the dispatch it fails |
| `defer` | `until` (epoch ms) | `reason` | User-initiated snooze |
| `defer_expired` | `deferred_until` | — | Lazy auto-event written by fold when `until` elapsed |
| `delete` | — | `reason` | Soft delete marker |

### 4.3 Example event chains

**Auto-retry 2x that ultimately fails:**

```
[t+0]    capture                "refactor auth middleware" (status=open)
[t+30s]  dispatch               workflow_id=wfa, attempt=1, pool_selector=least_loaded,
                                  triggered_by=first
                                  → state: IN_FLIGHT
[t+5m]   dispatch_failed        workflow_id=wfa, attempt=1,
                                  error="3 tests failed",
                                  retry_budget_exhausted=false
                                  → state: IN_FLIGHT (auto-retry scheduled at t+5m30)
[t+5m30] dispatch               workflow_id=wfb, attempt=2, pool_selector=least_loaded,
                                  triggered_by=auto
                                  → state: IN_FLIGHT
[t+10m]  dispatch_failed        workflow_id=wfb, attempt=2,
                                  error="2 tests failed",
                                  retry_budget_exhausted=true
                                  → state: FAILED (terminal)
```

**Succeed on second attempt:**

```
[t+0]    capture   "add OAuth refresh"
[t+1m]   dispatch  workflow_id=wfc, attempt=1, pool_selector=least_loaded
[t+6m]   dispatch_failed workflow_id=wfc, attempt=1, error="connection refused",
                                  retry_budget_exhausted=false
[t+6m30] dispatch  workflow_id=wfd, attempt=2, pool_selector=least_loaded,
                                  triggered_by=auto
[t+8m]   dispatch_done workflow_id=wfd, summary="oauth_refresh.py added"
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
    deferred_until: int | None                 # NEW: epoch ms; None = not deferred
    deleted: bool                              # NEW: soft-delete flag
    current_attempt: int                       # NEW: attempt number of the most recent
                                               #   dispatch (1 for first, 2 for retry);
                                               #   0 if never dispatched
```

**Migration:** No schema migration. Existing jots get `dispatch_state=None`, `deferred_until=None`, `deleted=False`, `current_attempt=0` by default (fold derives these from the absence of relevant events).

### 4.5 DispatchState enum

```python
class DispatchState(Enum):
    IN_FLIGHT = "in_flight"        # dispatch event exists, no terminal completion yet
    SUCCEEDED = "succeeded"        # latest completion event is dispatch_done
    FAILED    = "failed"           # latest completion is dispatch_failed with
                                   #   retry_budget_exhausted="true"
```

`RETRYING` is **not** a separate enum value — it's represented as `IN_FLIGHT` with `current_attempt < max_attempts`.

### 4.6 State derivation in fold

Extends `mahavishnu/jot/fold.py`. After the existing R3/R9 logic settles `status` and `last_modified_ms`, a third pass computes dispatch/defer/delete fields.

**Algorithm:** find the most recent `dispatch` event (by file order). Then walk forward looking for terminal events (`dispatch_done` / `dispatch_failed`) **whose `workflow_id` matches the dispatch**. Old terminals from prior dispatch attempts are ignored — they belong to workflows that have already been resolved.

```python
def _derive_dispatch_fields(events: list[JotEvent]) -> tuple[DispatchState | None, int, int | None, bool]:
    """Returns: (dispatch_state, current_attempt, deferred_until, deleted)."""
    deleted = any(ev.op == "delete" for ev in events)
    if deleted:
        return None, 0, None, True

    # Find the most recent dispatch event (file order, not timestamp)
    most_recent_dispatch_idx = -1
    most_recent_dispatch_wf: str | None = None
    most_recent_current_attempt = 0
    for i, ev in enumerate(events):
        if ev.op == "dispatch":
            most_recent_dispatch_idx = i
            most_recent_dispatch_wf = ev.ctx["workflow_id"]
            most_recent_current_attempt = int(ev.ctx["attempt"])

    # Compute deferred_until independently of dispatch state
    deferred_until = _compute_deferred_until(events)

    # No dispatch events: jot has never been dispatched
    if most_recent_dispatch_idx < 0:
        return None, 0, deferred_until, False

    # Walk forward from the most recent dispatch, looking for matching terminals
    dispatch_state = DispatchState.IN_FLIGHT
    for ev in events[most_recent_dispatch_idx + 1:]:
        if ev.ctx.get("workflow_id") != most_recent_dispatch_wf:
            continue
        if ev.op == "dispatch_done":
            dispatch_state = DispatchState.SUCCEEDED
            break
        if ev.op == "dispatch_failed":
            if ev.ctx.get("retry_budget_exhausted") == "true":
                dispatch_state = DispatchState.FAILED
            # else: auto-retry will create a new dispatch event; stay IN_FLIGHT
            break

    return dispatch_state, most_recent_current_attempt, deferred_until, False


def _compute_deferred_until(events: list[JotEvent]) -> int | None:
    """Find the active deferral. None if no defer or last defer was expired."""
    pending_until: int | None = None
    for ev in events:
        if ev.op == "defer":
            pending_until = int(ev.ctx["until"])
        elif ev.op == "defer_expired":
            pending_until = None
    return pending_until
```

**Why this algorithm:** scanning newest-first for "any terminal" misses the case where a user manually re-dispatches a previously-completed jot — the old terminal would mark SUCCEEDED even though the new dispatch is IN_FLIGHT. Matching `workflow_id` ensures we only consider terminals for the **current** dispatch attempt.

`defer_expired` is **lazy**: fold writes it when it sees a `defer` event with `until <= now_ms` and no `defer_expired` event after it. No background timer required.

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
            # IN_FLIGHT excluded (clutter; user already knows via vitals)
            # SUCCEEDED excluded (already done)
        )
    )
```

Surfaced candidates: **open + not-deleted + not-deferred-or-expired + (not-dispatched OR failed-dispatch)**.

### 5.3 Lexical primary scorer

```python
import re
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens; len >= 2 to drop pure noise."""
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

### 5.4 Semantic fallback

```python
def _semantic_score(jot_text: str, ctx_text: str, akosha_client) -> float:
    """Akosha-backed embedding cosine similarity."""
    emb = akosha_client.embed([jot_text, ctx_text])
    return _cosine_similarity(emb[0], emb[1])
```

- **Threshold:** `>= 0.55` cosine (calibrated from typical Akosha results; flexible).
- **Capped at 30 jots** (filtered by `last_modified_ms` DESC before embedding).
- **Fires only when lexical pass yields zero hits** above the 0.20 threshold.
- **Opt-out:** If Akosha is unreachable, fallback returns `[]` silently (logs at debug). Surfacing never fails because Akosha is down.

### 5.5 Throttling

```python
@dataclass
class _Throttle:
    last_fire_ms: int = 0
    min_interval_ms: int = 5000       # 5s between tool-result fires

    def should_fire(self, now_ms: int) -> bool:
        if now_ms - self.last_fire_ms < self.min_interval_ms:
            return False
        self.last_fire_ms = now_ms
        return True
```

Plus an adaptive gate: skip if result text < 50 tokens (too short to be meaningful).

### 5.6 Surfacing output format

```
📌 1 related jot: "refactor auth middleware" (3d old, open)
   `/jot show a3f9c2` to read; `/jot dispatch a3f9c2` to act
```

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
| `open` | `dispatch` (attempt=1, `triggered_by=first`) | `IN_FLIGHT` | `pool_route_execute(prompt=jot.text)` called; workflow_id stored |
| `IN_FLIGHT` | `dispatch_done` | `SUCCEEDED` | (none) |
| `IN_FLIGHT` | `dispatch_failed` (attempt=1, retry=false) | `IN_FLIGHT` | After 30s, `dispatch` event auto-appended (attempt=2, `triggered_by=auto`) |
| `IN_FLIGHT` | `dispatch_failed` (attempt=2, retry=true) | `FAILED` | Surfaced via `/jot vitals`; manual `jot_retry` available |
| `FAILED` | user calls `jot_retry` | `IN_FLIGHT` | New `dispatch` event (attempt=N+1, `triggered_by=manual`) |
| `SUCCEEDED` | user calls `jot_done` | `status=done`, `dispatch_state=None` | `done` event appended |
| `open` | user calls `jot_defer` | `status=open`, `deferred_until=<ts>` | `defer` event with `until` |
| `open` (deferred, until<=now) | fold runs | `deferred_until=None` | `defer_expired` event auto-written |
| any | user calls `jot_delete` | `deleted=True` | `delete` event appended; hidden from default lists |

`status` (`open` ↔ `done`) and `dispatch_state` are orthogonal. A SUCCEEDED jot can still be `done`-flipped via `jot_done`.

### 6.3 Two-tier reconciliation

**Tier 1 — Lazy reconciler (in fold):**

Every call to fold (read or write) inspects any `IN_FLIGHT` jot it encounters:

```python
async def _reconcile_if_in_flight(jot: JotSummary) -> None:
    if jot.dispatch_state is not DispatchState.IN_FLIGHT:
        return
    workflow_id = jot._dispatch_workflow_id      # derived from event chain
    status = await _workflow_substrate.get_status(workflow_id)
    if status.is_terminal:
        if status.succeeded:
            await _append_event("dispatch_done", ctx={
                "workflow_id": workflow_id,
                "summary": status.summary,
                **({"commit_sha": status.commit_sha} if status.commit_sha else {}),
            })
        else:
            await _append_event("dispatch_failed", ctx={
                "workflow_id": workflow_id,
                "attempt": str(status.attempt),
                "error": status.error,
                "retry_budget_exhausted": str(_should_exhaust_retry_budget(jot)),
            })
            if not _should_exhaust_retry_budget(jot):
                asyncio.create_task(_auto_retry_after(jot.id, backoff_s=RETRY_BACKOFF_SECONDS))
```

Cost per fold call: zero if no IN_FLIGHT; one workflow status check per IN_FLIGHT.

**Tier 2 — Background reconciler (every 30s):**

```python
async def _background_reconciler_loop() -> None:
    """Started at Mahavishnu server boot. Idempotent with Tier 1."""
    while True:
        await asyncio.sleep(RECONCILER_INTERVAL_SECONDS)
        for jot in fold(log_path()).states:
            if jot.dispatch_state is DispatchState.IN_FLIGHT:
                await _reconcile_if_in_flight(jot)
```

Handles the "user dispatches and never reads" case. Tier-1 already covered most cases, so this is a safety net.

### 6.4 Auto-retry 2x with idempotency

```python
async def _auto_retry_after(jot_id: str, backoff_s: int) -> None:
    await asyncio.sleep(backoff_s)
    current = fold(log_path()).find(jot_id)
    if current.dispatch_state is not DispatchState.FAILED:
        return                                  # user already retried manually; exit
    if current.current_attempt >= MAX_AUTO_RETRIES:
        return
    workflow_id = await _pool_route_execute(
        prompt=current.text,
        pool_selector="least_loaded",
    )
    await _append_event("dispatch", ctx={
        "workflow_id": workflow_id,
        "attempt": str(current.current_attempt + 1),
        "pool_selector": "least_loaded",
        "triggered_by": "auto",
    })
```

**Idempotency:** the post-sleep state check ensures racing auto-retry and manual retry don't both fire. The user-initiated event always wins; auto-retry exits when it sees a state that isn't FAILED.

### 6.5 Manual retry (`jot_retry`)

```python
async def retry_dispatch(jot_id: str) -> DispatchResult:
    jot = fold(log_path()).find(jot_id)
    if jot.dispatch_state is not DispatchState.FAILED:
        raise JotRetryError(
            f"jot {jot.short_id} is not in FAILED state "
            f"(current: {jot.dispatch_state.value if jot.dispatch_state else 'none'})"
        )
    workflow_id = await _pool_route_execute(
        prompt=jot.text,
        pool_selector="least_loaded",
    )
    next_attempt = jot.current_attempt + 1
    await _append_event("dispatch", ctx={
        "workflow_id": workflow_id,
        "attempt": str(next_attempt),
        "pool_selector": "least_loaded",
        "triggered_by": "manual",
    })
    return DispatchResult(
        jot_id=jot_id,
        workflow_id=workflow_id,
        attempt=next_attempt,
        status="in_flight",
    )
```

### 6.6 Concurrent drain handling

`drain_plan` naturally filters out non-actionable jots:

```python
def drain_plan(query: str | None, limit: int = 20, include_in_flight: bool = False) -> DrainPlan:
    candidates = fold(log_path()).states
    candidates = [j for j in candidates if _is_drain_eligible(j, now_ms=now_ms())]
    if not include_in_flight:
        candidates = [j for j in candidates if j.dispatch_state is not DispatchState.IN_FLIGHT]
    if query:
        # lexical pre-filter for query
        q_tokens = _tokenize(query)
        candidates = [j for j in candidates if _lexical_score(_tokenize(j.text), q_tokens) >= 0.20]
    candidates = candidates[:limit]
    return DrainPlan(query=query, candidates=candidates)
```

`_is_drain_eligible` is identical to `_is_surface_eligible` except IN_FLIGHT is **included** (so users can see in-flight state, just not re-dispatch). `--include-in-flight` forces inclusion in the action set (rare, supported).

### 6.7 Failure modes

| Failure | Detection | Recovery |
|---|---|---|
| Worker never reports back | Background reconciler times out after 10 min | Mark FAILED; surface via `/jot vitals` |
| HOME directory read-only | Drain checks writability on first dispatch | Fail fast with `JotPermissionError` |
| `pool_route_execute` raises | Caught at dispatch site | `dispatch_failed` event written immediately (no IN_FLIGHT state); user retries |
| Auto-retry itself fails | Treated as final `dispatch_failed` with `retry_budget_exhausted=true` | Manual `jot_retry` available |
| Reconciler crashes mid-write | Lazy reconciler (Tier 1) catches up on next read | Self-healing |
| User dispatches same jot twice rapidly | Second `dispatch` event appended; fold sees new IN_FLIGHT, old workflow abandoned | User can `jot_retry` to manually re-trigger |
| Mahavishnu server down during dispatch | CLI requires server; MCP tool returns `PoolUnavailableError` | User retries when server is back |
| Akosha unreachable during surfacing | Caught in semantic fallback | Returns `[]` silently; logs debug |

### 6.8 Configuration

```yaml
jot:
  drain:
    retry:
      enabled: true
      max_attempts: 2
      backoff_seconds: 30
    reconciler:
      background_interval_seconds: 30
      timeout_minutes: 10           # mark FAILED if workflow stuck > 10 min
```

## 7. Testing Strategy

### 7.1 Test category matrix

| Category | File pattern | Purpose | Mocks needed |
|---|---|---|---|
| Unit (state machine) | `tests/unit/jot/test_drain.py::TestStateMachine` | Pure logic | None (pure fold tests) |
| Unit (retry) | `tests/unit/jot/test_drain.py::TestRetry` | Retry orchestration | `mock_pool_route_execute`, `fast_backoff` |
| Unit (scorer) | `tests/unit/jot/test_drain_surfacing.py` | Lexical + semantic scoring | `deterministic_akosha` |
| Unit (reconciler) | `tests/unit/jot/test_drain_reconciler.py` | Lazy reconciler | `fake_workflow_substrate` |
| Unit (filters) | `tests/unit/jot/test_drain_filters.py` | State eligibility | None |
| Unit (helpers) | `tests/unit/jot/test_drain_helpers.py` | Tokenizer, budget math | None |
| Integration (e2e) | `tests/integration/jot/test_drain_e2e.py` | Full drain flow | `mock_pool_returns_*` |
| Integration (resurfacing) | `tests/integration/jot/test_drain_resurfacing_e2e.py` | Surfacing paths | `deterministic_akosha` |
| Integration (auto-retry) | `tests/integration/jot/test_drain_auto_retry_e2e.py` | Full auto-retry sequence | `fast_backoff`, `mock_pool_sequence` |
| Integration (concurrent) | `tests/integration/jot/test_drain_concurrent_e2e.py` | Race conditions | `mock_pool_returns_success`, asyncio.gather |
| Property (idempotency) | `tests/property/jot/test_drain_idempotency.py` | Re-drain invariants | `deterministic_akosha` |
| Property (state invariants) | `tests/property/jot/test_drain_state_invariants.py` | Attempt count, determinism | `deterministic_akosha` |
| Property (ranking) | `tests/property/jot/test_drain_surfacing_ranking.py` | Ranking transitivity | `deterministic_akosha` |

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
- `test_semantic_fallback_silent_when_akosha_unreachable`
- `test_surfacing_throttles_five_second_window`
- `test_surfacing_skips_short_context`

**Lazy reconciler:**
- `test_lazy_reconciler_writes_dispatch_done_for_in_flight`
- `test_lazy_reconciler_idempotent_when_already_terminal`
- `test_lazy_reconciler_writes_dispatch_failed_with_correct_budget`

**State filter:**
- `test_open_jots_are_drain_eligible`
- `test_done_jots_excluded_from_drain`
- `test_deferred_jots_excluded_until_expiry`
- `test_in_flight_jots_excluded_from_drain_candidates`
- `test_failed_jots_surfaced_for_attention`
- `test_deleted_jots_excluded_from_both`

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

```python
@given(events=event_chains())
def test_re_drain_idempotent(events): ...

@given(events=random_event_chains_with_dispatch_ops())
def test_attempt_count_never_exceeds_max(events): ...

@given(events=random_event_chains())
def test_state_derivation_is_deterministic(events): ...

@given(jots=random_jot_texts(min_count=5), context=random_contexts())
def test_ranking_is_transitive(jots, context): ...

@given(jots=random_jot_texts(min_count=10))
def test_top_n_truncates_to_limit(jots): ...
```

### 7.5 Mocking catalog

| Dependency | How to mock | Fixture location |
|---|---|---|
| `pool_route_execute` | `monkeypatch.setattr(drain, "_pool_route_execute", fake)` | `tests/unit/jot/conftest.py::mock_pool_route_execute` |
| Workflow substrate (`get_status`) | Fake dict `{workflow_id: WorkflowStatus}` | `tests/conftest.py::fake_workflow_substrate` |
| Akosha embeddings | Deterministic hash-based embeddings (seed=42) | `tests/conftest.py::deterministic_akosha` |
| Claude Code hook runner | Bypass entirely — call hook function with synthetic context | (no fixture; just import + call) |
| Time / `asyncio.sleep` | Patched to no-op | `tests/conftest.py::no_async_sleep` |
| Backoff | `fast_backoff` fixture sets `RETRY_BACKOFF_SECONDS = 0` | `tests/unit/jot/conftest.py::fast_backoff` |
| Wall clock for `until` expiry | `time-machine` freezer | `tests/conftest.py::clock` |

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
- `mahavishnu/workers/cloud_worker.py` — Worker contract that dispatched jots consume
- `mahavishnu/pools/` — Pool routing that `pool_route_execute` wraps
- Akosha embedding API — semantic fallback for surfacing
- CLAUDE.md `mahavishnu-tool-preference-policy.md` — Pool-routing-first doctrine

## 12. Open Questions

**None.** All design decisions resolved via the brainstorming Q&A (see §2). Sub-decisions within sections were taken during design and noted inline.
