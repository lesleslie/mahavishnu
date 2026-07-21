---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: observability
---

# Phase 6 — Bodai-Wide Observability Surfacing

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Date:** 2026-07-11
> **Status:** draft, planning <!-- legacy status: draft, planning — see YAML frontmatter -->
> **Owner:** mahavishnu core
> **Scope:** Replace Mahavishnu's per-component activity hook with a Bodai-wide observability surface that reads from Oneiric EventBridge (the unified event spine from Convergence Plan C1b/C2).
> **Purpose:** Make Claude Code's "observe Bodai" path go through a single canonical subscriber rather than per-component WebSocket hooks. Phase 5's transition state (Mahavishnu-only hook at `.claude/hooks/mahavishnu-activity-stream.py`) is replaced by the steady state here.
> **Precondition (BLOCKING):** Convergence Plan C2 lands an "activity" event category in Oneiric EventBridge. Phase 6 cannot start until C2's envelope schema is published. If C2 has not landed, see the "Pre-C2 Path" section at the bottom.

______________________________________________________________________

## 1. Outcome

When this plan ships:

1. **Single Bodai activity subscriber** at `.claude/hooks/bodai-activity-subscriber.py` reads from Oneiric EventBridge (Redis Streams transport) and persists events to a queue that the existing `.claude/hooks/` PostToolUse pattern consumes.
1. **Mahavishnu WebSocket subscriber removed.** The Phase 5 hook is deleted; only the Bodai hook fires.
1. **`/bodai-status` slash command** surfaces the same shape as `/vishnu-status` but aggregated across Mahavishnu, Akosha, and Crackerjack activity.
1. **Cross-component observability is canonical.** Akosha and Crackerjack each gain an EventBridge publisher that adapts their existing WebSocket broadcasts into the canonical envelope.

User-observable change: a Claude Code session sees `[akosha] aggregation_completed suite=quality` and `[crackerjack] test_run_completed passed=42 failed=0` style summaries alongside `[mahavishnu] workflow wid_abc completed`, all from one subscriber.

Concrete success signal: `mahavishnu metrics bodai --scope 7d` shows ≥1 cross-component activity event per hour during business hours, and the `.claude/hooks/` directory contains exactly one activity subscriber (the Bodai one).

## 2. Goals

1. Replace the Mahavishnu WebSocket hook with a Bodai activity subscriber that reads from EventBridge.
1. Land EventBridge publishers for Akosha and Crackerjack activity events (one adapter per component, adapting existing WebSocket broadcasts).
1. Add `/bodai-status` slash command + `bodai-status` auto-trigger skill + companion to `/vishnu-status`.
1. Add a `mahavishnu metrics bodai` CLI that surfaces event-bridge health, subscriber state, and per-component event rates.
1. Document the canonical envelope in `.claude/decisions/` (refine the existing `bodai-observability-pattern.md` with the actual schema once C2 lands).

## 3. Non-Goals

1. **Not implementing the EventBridge envelope itself.** Convergence Plan C2 owns that. Phase 6 reads whatever C2 publishes; if C2's envelope changes, this plan is amended.
1. **Not adding per-component WebSocket subscribers for Bodai observation.** Explicitly forbidden by `.claude/decisions/bodai-observability-pattern.md`.
1. **Not changing Dhara or Session-Buddy's observability surfaces.** Both are REST-only / event-driven per Convergence Plan §4 ownership rules. Dhara/Session-Buddy visibility in `/bodai-status` is via query-side adapters, not subscriptions.
1. **Not changing the Phase 5 transition hook's protocol.** The Mahavishnu-only hook is *removed*, not refactored — its deletion is a sign of Phase 6's success.
1. **Not implementing Grafana dashboards for activity events.** Grafana already has dashboards for Mahavishnu routing (per `docs/ROUTING_GUIDE.md`); adding Grafana views for Akosha/Crackerjack activity is a follow-on.

## 4. Current Findings

| Finding | Evidence | Implication |
|---|---|---|
| EventBridge transport is Redis Streams per Convergence Plan C1b | `docs/plans/2026-05-10-bodai-control-plane-convergence-plan.md` §3.2 | Subscriber uses `redis.asyncio` client (already a dep) |
| Phase 5 hook uses WebSocket, not EventBridge | `.claude/hooks/mahavishnu-activity-stream.py:1-100` | Deletion is in scope |
| Akosha broadcasts aggregations to a `metrics` channel | `akosha/websocket/server.py:431` | Need an adapter that re-publishes to EventBridge under the C2 envelope |
| Crackerjack broadcasts test lifecycle to its WebSocket | `crackerjack/websocket/server.py:266-281` | Same as Akosha — adapter required |
| The canonical envelope shape from Convergence Plan C2 is **TBD at plan time** | — | Phase 6 includes a `BodaiEvent` Pydantic model that takes the envelope as a forward reference; updated when C2 lands |
| Oneiric is the package that owns adapter lifecycle, including EventBridge registration | `mahavishnu/core/oneiric.py`, `oneiric/adapters/` | Subscriber uses `oneiric.events.subscribe()` rather than raw Redis client |
| The project convention is `from __future__ import annotations` + sorted imports + `X \| None` | `CLAUDE.md` Crackerjack-Compliant Code | All Phase 6 files follow |

## 5. Implementation Phases

### Phase 6.1: Bodai Event Envelope + Subscriber Skeleton

**Goal:** Define the canonical `BodaiEvent` Pydantic model (matching Convergence Plan C2's envelope) and build the subscriber skeleton that reads from EventBridge.

**Tasks:**

- **Task 6.1.1:** Create `mahavishnu/core/bodai_events.py` exporting `class BodaiEvent(BaseModel)`. Fields mirror Convergence Plan C2's envelope: `event_id: str` (ULID), `event_type: str` (e.g., `workflow_completed`, `aggregation_completed`, `test_run_completed`), `component: Literal["mahavishnu", "akosha", "crackerjack"]`, `timestamp: datetime`, `summary: str` (human-readable one-liner for the `[component] ...` format), `payload: dict[str, Any]` (the full event body for callers that want details), `parent_event_id: str | None` (for cross-component correlation; e.g., a Crackerjack test_run that triggered a Mahavishnu workflow). Pydantic v2 with `model_config = ConfigDict(frozen=True)`.

- **Task 6.1.2:** Create `mahavishnu/core/bodai_subscriber.py` exporting:

  ```python
  async def subscribe_to_bodai_events(
      callback: Callable[[BodaiEvent], Awaitable[None]],
      *,
      redis_url: str = "redis://localhost:6379/0",
      consumer_group: str = "mahavishnu-claude-observers",
      consumer_name: str | None = None,  # default: socket.gethostname()
      start_from: Literal["latest", "earliest"] = "latest",
      per_event_timeout_seconds: float = 30.0,
  ) -> None:
      """Subscribe to the unified activity-event stream on EventBridge.

      Blocks until the cancellation token is set. Each event is decoded
      into a BodaiEvent and passed to callback. The callback's exception
      does not abort the subscription — it is logged and the next event
      proceeds (mirrors Phase 5's loop-until-dry error-trapping).
      """
  ```

  Internally uses `redis.asyncio.client.Redis.xreadgroup(...)` with a consumer group. Decodes the JSON payload into `BodaiEvent`. Never raises — all failures logged at WARNING.

- **Task 6.1.3:** Tests for the subscriber in `tests/unit/test_bodai_subscriber.py`. Use a fake `redis.asyncio.Redis` (returns canned `xreadgroup` payloads). Cover: (1) callback fires with decoded `BodaiEvent`, (2) callback exception logged + subscription continues, (3) reconnection on transient Redis error (mocked), (4) `start_from="earliest"` reads backlog, (5) cancellation token breaks the loop. Marked `pytest.mark.unit`.

**Exit criteria:**

- `pytest tests/unit/test_bodai_subscriber.py -v` — all tests pass
- `BodaiEvent` round-trips through `model_dump_json()` → `model_validate_json()` without loss (covered in tests)

#### Integration Contract — Phase 6.1

- **Triggered from:** `.claude/hooks/bodai-activity-subscriber.py` SessionStart hook (Phase 6.4)
- **Returns to / updates:** Read-only. The subscriber pushes decoded events into a local queue file (`~/.mahavishnu/bodai-event-queue.json`) for PostToolUse to drain.
- **Demonstrable by:** Run a Python REPL: `asyncio.run(subscribe_to_bodai_events(callback))` against a Redis with a seeded `XADD mahavishnu.events * type test payload '{"event_id":"01...", ...}'` — the callback fires within 1s.
- **Rollback signal:** None — the subscriber is non-destructive. Disable by removing the SessionStart hook entry from `.claude/settings.json`.
- **Observability added:** OTel span `bodai.subscribe` with `consumer_group`, `events_received`, `events_decoded_failed`. Metric `mahavishnu.bodai.events_received_total{component}` (counter). Structured log `bodai.event_received event_id=... component=... event_type=...`.

______________________________________________________________________

### Phase 6.2: Akosha + Crackerjack EventBridge Publishers

**Goal:** Adapt Akosha's `metrics` WebSocket channel and Crackerjack's test-lifecycle WebSocket into EventBridge publishers so the unified bus carries their activity.

**Tasks:**

- **Task 6.2.1:** Create `akosha/core/eventbridge_publisher.py` (Akosha repo). Subscribes to Akosha's existing `metrics` channel and re-publishes each event to `XADD mahavishnu.events * component akosha payload '<json>'`. The wrapper is opt-in: Akosha continues to broadcast to its WebSocket (for non-Claude consumers); the EventBridge write is parallel. Test in Akosha's CI.

- **Task 6.2.2:** Create `crackerjack/core/eventbridge_publisher.py` (Crackerjack repo). Subscribes to `test_started` / `test_completed` broadcasts. Same pattern: parallel XADD, no breaking change to the existing WebSocket. Test in Crackerjack's CI.

- **Task 6.2.3:** Mahavishnu side: extend `mahavishnu/core/eventbridge_publisher.py` (analogous to the others). Subscribes to Mahavishnu's own `global` channel and re-publishes to EventBridge. This is the *bridge* that makes Phase 5's WebSocket flow compatible with the unified bus. After this lands, the Bodai subscriber no longer needs to read Mahavishnu's WebSocket at all.

> **Important:** Phase 6.2 work happens in the **Akosha and Crackerjack repos**, not Mahavishnu. The Mahavishnu-side publisher (6.2.3) is a thin compatibility layer for the transition window. Once Phase 6 is fully landed, Phase 6.2.3 can be removed (Mahavishnu publishes directly to EventBridge without the WebSocket intermediary).

**Exit criteria:**

- Each publisher has ≥3 unit tests in its own repo covering: payload-shape mapping (Akosha `aggregation_completed` → BodaiEvent `event_type=aggregation_completed`, `component=akosha`), Redis-transient-error retry, parallel-publish resilience (WebSocket failure does not abort the EventBridge write, and vice versa).
- A `mahavishnu metrics bodai` CLI shows ≥1 event received from each component within a 60-second seeded test.

#### Integration Contract — Phase 6.2

- **Triggered from:** Component internal lifecycle (Akosha's `broadcast_aggregation_completed`, Crackerjack's `broadcast_test_*`, Mahavishnu's `broadcast_workflow_*`).
- **Returns to / updates:** Redis Streams stream `mahavishnu.events` gains a per-component event category.
- **Demonstrable by:** Run an Akosha aggregation; subscribe via `redis-cli XREADGROUP GROUP mahavishnu-claude-observers ...` — the Akosha event appears within 1s.
- **Rollback signal:** Disable each publisher via its own feature flag (`akosha.publish_to_eventbridge: bool = False` in settings). Per-component rollback is config-only.
- **Observability added:** Each publisher emits its own OTel spans and metrics (`akosha.eventbridge.publish`, `crackerjack.eventbridge.publish`, `mahavishnu.eventbridge.publish`) so an operator can detect publish-side regressions independently of the subscriber.

______________________________________________________________________

### Phase 6.3: `/bodai-status` Slash Command + Skill

**Goal:** Add a user-invocable `/bodai-status` slash command that prints Bodai-wide activity (events from all three components) and a `bodai-status` auto-trigger skill that fires on "what's happening in Bodai?" phrasings.

**Tasks:**

- **Task 6.3.1:** Create `.claude/commands/bodai-status.md`. The command reads `~/.mahavishnu/bodai-event-queue.json` (the queue file the subscriber writes to), groups by component, and prints a table per component (Mahavishnu / Akosha / Crackerjack). Format mirrors `/vishnu-status` so users get a consistent visual.

- **Task 6.3.2:** Create `.claude/skills/bodai-status/SKILL.md`. Frontmatter matches the existing `vishnu-status` skill (`name`, `title`, `id` (ULID), `description`, `owner`, `status`, `category`, `last_reviewed`). Body documents trigger phrases and the distinction from `/vishnu-status` (Bodai-wide vs. Mahavishnu-only).

- **Task 6.3.3:** Validate both via `uv run python scripts/tool_frontmatter_validator.py validate <path>` (both pass with zero critical issues).

**Exit criteria:**

- `/bodai-status` from Claude Code prints a per-component activity table without leaving the session
- `grep -rn 'ws://localhost:869[026]' .claude/hooks/` returns zero hits — all per-component WebSocket subscribers are gone (the rule from `.claude/decisions/bodai-observability-pattern.md`)
- Tool frontmatter validator passes for both new files

#### Integration Contract — Phase 6.3

- **Triggered from:** `/bodai-status` slash command, or `bodai-status` skill auto-trigger on relevant user phrasings
- **Returns to / updates:** Slash command output goes to the conversation. The skill is read by Claude's prompt and steers tool selection.
- **Demonstrable by:** Manual test: run a Crackerjack test run + an Akosha aggregation, then `/bodai-status` — both appear in their respective component sections.
- **Rollback signal:** `/bodai-status` shows empty sections for ≥1 hour during business hours → EventBridge is broken; alert.
- **Observability added:** Skill fires are visible in Claude Code's own metrics (no Mahavishnu-side metric needed). Slash command itself emits `mahavishnu.bodai.status_command_invocations_total` counter for usage tracking.

______________________________________________________________________

### Phase 6.4: Replace Phase 5 Hook + Settings Wiring

**Goal:** Delete `.claude/hooks/mahavishnu-activity-stream.py` and replace its role with `.claude/hooks/bodai-activity-subscriber.py` (SessionStart spawn) + `.claude/hooks/bodai-activity-post-tool-use.py` (PostToolUse drains the queue and emits summaries).

**Tasks:**

- **Task 6.4.1:** Create `.claude/hooks/bodai-activity-subscriber.py`. SessionStart-only mode. Spawns a detached async task that calls `mahavishnu.core.bodai_subscriber.subscribe_to_bodai_events(callback)`. The callback writes each decoded `BodaiEvent` to `~/.mahavishnu/bodai-event-queue.json` (atomic write, cap at 100 entries, oldest dropped first). Pid of the detached task stored in `~/.mahavishnu/bodai-subscriber-state.json` so SessionEnd can clean up.

- **Task 6.4.2:** Create `.claude/hooks/bodai-activity-post-tool-use.py`. PostToolUse-only mode. Reads `~/.mahavishnu/bodai-event-queue.json` and emits `[mahavishnu] workflow wid_abc completed at stage=test_run` or `[akosha] aggregation_completed suite=quality` or `[crackerjack] test_run_completed passed=42 failed=0` style one-line summaries for events that match the recent tool invocation's correlation key (e.g., a Mahavishnu dispatch → events with `component=mahavishnu` and matching `workflow_id`).

- **Task 6.4.3:** Update `.claude/settings.json` to:

  - Add SessionStart hook entry for `bodai-activity-subscriber.py`
  - Add PostToolUse hook entry for `bodai-activity-post-tool-use.py` (matcher: `mcp__*`)
  - Add SessionEnd hook entry for cleanup (same script's session-end mode)
  - REMOVE the SessionStart / PostToolUse / SessionEnd entries for `mahavishnu-activity-stream.py`

- **Task 6.4.4:** Delete `.claude/hooks/mahavishnu-activity-stream.py`. Move its tests to a `@pytest.mark.skip(reason="Phase 5 hook removed in Phase 6; see bodai-activity-* tests")` decorator — or, better, delete the test file and remove it from the integration suite.

- **Task 6.4.5:** Tests for the new hooks at `tests/integration/test_bodai_activity_subscriber.py`. Cover: SessionStart spawns the detached task and writes state file; PostToolUse reads queue and emits summaries; SessionEnd cleans up; EventBridge transient-error reconnects.

**Exit criteria:**

- `pytest tests/integration/test_bodai_activity_subscriber.py -v -m integration` — all tests pass
- `pytest tests/integration/test_websocket_subscriber.py -v -m integration` — SKIPPED (Phase 5 file removed; tests need migration or removal)
- `grep -rn 'mahavishnu-activity-stream' .claude/ .claude/settings.json 2>/dev/null` returns zero hits

#### Integration Contract — Phase 6.4

- **Triggered from:** SessionStart (spawn subscriber), PostToolUse on `mcp__*` invocations (drain queue), SessionEnd (cleanup)
- **Returns to / updates:** Conversation gets `[component] summary` one-liners; queue file at `~/.mahavishnu/bodai-event-queue.json` is the persistent artifact
- **Demonstrable by:** Manual test: trigger an Akosha aggregation + a Mahavishnu dispatch + a Crackerjack test, all within 30s — all three `[component]` lines appear in the conversation in the order events were published
- **Rollback signal:** Hook emits no events for ≥1 hour during business hours → EventBridge subscriber is broken; alert
- **Observability added:** `mahavishnu.bodai.events_emitted_total{component, event_type}` (counter), `mahavishnu.bodai.queue_overflow_total` (counter, fires when queue cap drops oldest events), `mahavishnu.bodai.subscriber_restarts_total` (counter)

______________________________________________________________________

### Phase 6.5: `mahavishnu metrics bodai` CLI + Documentation

**Goal:** Surface Phase 6 health, event rates, and per-component breakdown via the existing `mahavishnu metrics` CLI. Document the pattern in `docs/ROUTING_GUIDE.md` and `.claude/decisions/bodai-observability-pattern.md`.

**Tasks:**

- **Task 6.5.1:** Add `mahavishnu metrics bodai` command. Output:

  - Subscriber state (running/stopped, pid, uptime)
  - Event counts per component for last 1h, 24h, 7d
  - EventBridge publish-rate (events/min) per component
  - Queue state (current size, drop count)
  - Per-component health (last event timestamp; if >5min old, marked stale)

- **Task 6.5.2:** Update `docs/ROUTING_GUIDE.md` to add a "Bodai Observability — Implementation" subsection under the existing "Bodai Observability — Component Survey" table. Reference the hook paths, the subscriber entry point, and how to disable per-component publishers.

- **Task 6.5.3:** Update `.claude/decisions/bodai-observability-pattern.md` with the actual envelope shape landed by C2 (replace the "TBD" forward reference in the decision rule). Update the table of Bodai event examples with concrete payloads.

- **Task 6.5.4:** Add `mahavishnu metrics bodai --scope 7d --component akosha` filter so operators can drill into one component.

**Exit criteria:**

- `mahavishnu metrics bodai` outputs the structured table
- `mahavishnu metrics bodai --scope 7d --component akosha` filters correctly
- Documentation updated

#### Integration Contract — Phase 6.5

- **Triggered from:** `mahavishnu metrics bodai` CLI invocation
- **Returns to / updates:** Operator-facing health check
- **Demonstrable by:** Manual test: run the CLI while events are flowing — counts increment in real time
- **Rollback signal:** Component marked stale > 5min during business hours → publisher side broken
- **Observability added:** `mahavishnu.metrics.bodai.command_invocations_total` (counter)

______________________________________________________________________

### 5.1 Phase Ordering and Dependencies

```
Phase 6.1 (envelope + subscriber skeleton)  ─── independent
Phase 6.2 (publishers in 3 repos)            ─── independent (parallel-friendly)
Phase 6.3 (/bodai-status command + skill)     ─── independent (parallel-friendly)
Phase 6.4 (replace Phase 5 hook)             ─── depends on 6.1 + 6.2 (needs envelope + publishers)
Phase 6.5 (CLI + docs)                       ─── depends on 6.4 (commands observe the new state)
```

**Implications:**

- Phases 6.1, 6.2, 6.3 can land in parallel branches.
- Phase 6.4 is the integration point — it consumes everything.
- Phase 6.5 is doc + CLI polish; can land alongside 6.4.

### 5.2 Architecture Diagram

See `.claude/decisions/bodai-observability-pattern.md` for the
canonical diagram and the single-source-of-truth rules. The pattern
is: components publish to EventBridge → single subscriber reads →
PostToolUse drains → conversation sees `[component] summary`.

______________________________________________________________________

## 6. Validation Matrix

| Phase | Tests | Ruff | Frontmatter validator | Manual |
|---|---|---|---|---|
| 6.1 | `test_bodai_subscriber.py` 5 tests pass | clean | n/a | REPL subscribe works |
| 6.2 | per-repo publisher tests pass | clean | n/a | seeded events appear on EventBridge within 1s |
| 6.3 | n/a | clean | both pass | `/bodai-status` outputs table |
| 6.4 | `test_bodai_activity_subscriber.py` 5 tests pass | clean | n/a | manual cross-component test in same session |
| 6.5 | n/a | clean | n/a | `mahavishnu metrics bodai` outputs table |

## 7. Risks

| Risk | Mitigation |
|---|---|
| Convergence Plan C2 envelope schema is unstable during Phase 6 implementation | Phase 6.1 makes the envelope a forward reference; when C2 lands the canonical shape, `BodaiEvent` is the only file that needs to change |
| EventBridge outage causes subscriber to drop events | Subscriber is non-blocking and never raises; drop counts surface via `mahavishnu.bodai.subscriber_restarts_total`; alert on rate |
| Phase 5 hook's deletion breaks `/vishnu-status` (which depends on the same hook file) | Phase 6.4 lands a Bodai-wide hook that subsumes the Phase 5 hook's responsibilities; `/vishnu-status` switches to reading the Bodai queue and filtering by `component=mahavishnu` |
| Akosha and Crackerjack CI doesn't run Phase 6 publisher tests | Add a CI workflow in each repo that runs the publisher tests against a Redis service container |
| Operators don't know Phase 5 hook is being replaced | `.claude/decisions/bodai-observability-pattern.md` documents the transition explicitly with the deleted/added file paths |

## 8. Pre-C2 Path (Fallback)

If Convergence Plan C2 has not landed an "activity" event category by
the time Phase 6 starts:

1. **Define the canonical envelope in Phase 6.1** as a forward
   reference. The shape is documented as "to be reconciled with C2"
   and `BodaiEvent` is shipped with a working schema anyway.
1. **Skip Phase 6.2 publisher work** until C2 lands. The single
   Mahavishnu-side publisher (6.2.3) is the only one that's safe to
   ship pre-C2, and it provides Mahavishnu-only coverage (no
   cross-component gains).
1. **Phase 6.4 hook replacement is conditional**: only land if
   Phase 6.2 is also landing. Otherwise, leave Phase 5 in place.

The decision rule: **if C2 has not landed by the time Phase 6.1
ships, pause the plan until C2 lands.** Document the pause in
`docs/plans/2026-07-11-phase-6-bodai-observability.md` and link the
C2 status from the plan's Status field.

## 9. References

- `docs/plans/2026-07-11-ultracode-integration-wiring.md` §5 Phase 6 (deferred content)
- `docs/plans/2026-05-10-bodai-control-plane-convergence-plan.md` Non-Goal #1 + §3.2 (Redis Streams transport)
- `.claude/decisions/bodai-observability-pattern.md` (operational rule)
- `docs/ROUTING_GUIDE.md` §Bodai Observability — Component Survey (gap classification)
- `.claude/hooks/mahavishnu-activity-stream.py` (Phase 5 transition state, to be deleted)
- `docs/feature-tracking/2026-07-11-*` entries for Phases 1-5 (apply the same `{built, wired, adopted}` state machine to Phase 6 tasks)

## 10. Phase 6 — Initialized

This plan replaces the deferred Phase 6 stub in
`docs/plans/2026-07-11-ultracode-integration-wiring.md` §5 Phase 6.
Once C2 lands, swap the Status field from "draft, blocked on C2" to
"draft, ready to implement" and dispatch the workflow.
