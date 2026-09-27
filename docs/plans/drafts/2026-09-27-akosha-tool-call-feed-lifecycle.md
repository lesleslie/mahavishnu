---
status: draft
role: implementation
kind: plan
date: 2026-09-27
last_reviewed: 2026-09-27
superseded_by: null
blocks_on:
  - docs/plans/2026-09-26-tool-surface-quality.md
topic: observability
---

# Akosha Tool-Call Feed Lifecycle — Follow-On Plan (DEFERRED)

> **Status:** `draft, implementation` — explicitly deferred until Phase 1 of `docs/plans/2026-09-26-tool-surface-quality.md` lands and surfaces the data shape that informs retention + `/health` wiring decisions.
>
> **Origin:** Two PARTIAL items from the v2 re-review of the parent plan:
>
> 1. **Retention policy** (akosha-specialist v1 finding #7) — `mcp_tool_call` traces are high-volume (one per `mcp__mahavishnu__*` call). Without a retention tier, the Akosha `HotStore` grows without bound. `AgingService.migrate_hot_to_warm(cutoff_days=7)` at `akosha/storage/aging.py:46` exists but is opt-in / manual.
>
> 2. **`/health` aggregator wiring for `mcp_tool_call`** (security lens v1 finding #7 + mcp-integration-expert v1 finding #6) — the v2 plan added the `HealthFeedState("mcp_tool_call")` registration requirement, but the actual wiring on the Akosha side requires a separate `hot_store.query_traces(task_class="mcp_tool_call", ...)` filter call and a second entry in the aggregator dict at `akosha/mcp/server.py:776` — a non-trivial implementation that touches the dynamic `/health` build path, not just a static config flag.
>
> This plan captures both as a single follow-on so they ship together. They share the same Akosha review surface and the same data-shape assumptions.

## 1. Outcome (target)

- **User-observable change:**
  - `mcp__akosha__query_local_traces(system_id="mahavishnu", task_class="mcp_tool_call")` returns traces persisted for at least N days (N = a real number chosen from the data observed post-Phase 1; see §4.5).
  - `GET /health` on Akosha returns a `mcp_tool_call` feed entry with `entities_count`, `last_updated_timestamp`, `cycles_total`, `errors_total` per `mcp-backend-wiring-discipline.md` §3.
  - Hot-store growth for `mcp_tool_call` traces is bounded; warm-tier storage retains longer-tail data for retrospective analysis.

## 2. Goals (when activated)

1. `mcp_tool_call` traces have an explicit retention tier — automatic migration from `HotStore` to `WarmStore` after a configurable window.
2. `mcp_tool_call` is a first-class feed in Akosha's `/health` aggregator with the four-signal surface.
3. `/health` returns 503 on degraded `mcp_tool_call` feed (per `mcp-backend-wiring-discipline.md` §1).
4. Pre-warm: the `mcp_tool_call` feed shows `cycles_total >= 1` within 60s of Akosha boot (per `feedback-oneiric-mcp-health-feed-warmup` memory).

## 3. Non-Goals (initial sketch)

1. Cardinality budget enforcement on the `selector` attribute (bounded by 173-tool catalog — see Phase 1 v2 plan §8 Risks row 8).
2. Per-tool retention differentiation (all `mcp_tool_call` traces age at the same rate; per-tool differentiation is a follow-on).
3. Real-time alerting on retention-tier breaches (operator-side, not Akosha policy).
4. Cross-tenant retention (single-tenant only).

## 4. Current Findings (initial sketch — to be expanded when activated)

- **HotStore has no TTL / max-row policy.** `akosha/storage/hot_store.py` exposes `query_traces` but no row-count cap. `AgingService.migrate_hot_to_warm(cutoff_days=7)` is opt-in. Mahavishnu emits one trace per `mcp__mahavishnu__*` call — at 173 tools × modest call rates, this is tens of thousands of rows per day without bounds.
- **`/health` is dynamic.** `akosha/mcp/server.py:776` calls `aggregate_feed_states` with a dict of feed names → `HealthFeedState` instances. The dict is built per request. Adding a `mcp_tool_call` entry requires (a) a new query against `hot_store` for `task_class == "mcp_tool_call"`, (b) a new `HealthFeedState("mcp_tool_call")` constructed from those query results, (c) adding the new feed to the aggregator dict.
- **`HealthFeedState` is imported from `mcp_common.health.feed`.** `akosha/mcp/server.py:640` does the import. The shape is the canonical four-signal surface used across Bodai MCP servers.
- **No Akosha-side pre-warm hook for new feeds.** Adding `mcp_tool_call` to the aggregator alone is insufficient — the feed needs to run at least one cycle within 60s of Akosha boot, otherwise `/health` returns `cycles_total == 0` which gates 503 per `mcp-backend-wiring-discipline.md`. Need a warm-up call to `fitness_analyzer.collect_traces("mcp_tool_call")` at boot.
- **Parent plan ships Task 1.3 (the hardcoded list edit) but NOT Task 1.5 (the /health wiring).** Task 1.3 is committed in the akosha repo (paired commit on Mahavishnu main (commit 67095d98) `67095d98`). Task 1.5 is the work captured by this plan.

## 4.5 Requirements (sketch — finalized when activated)

```yaml
requirements:
  - id: REQ-FEED-001
    title: "Retention tier: mcp_tool_call traces age from HotStore to WarmStore after N days"
  - id: REQ-FEED-002
    title: "AgingService wired for mcp_tool_call task_class (not opt-in)"
  - id: REQ-FEED-003
    title: "/health aggregator includes mcp_tool_call feed with four-signal HealthFeedState"
  - id: REQ-FEED-004
    title: "Pre-warm hook: mcp_tool_call feed runs one cycle within 60s of Akosha boot"
  - id: REQ-FEED-005
    title: "/health returns 503 when mcp_tool_call feed is degraded (errors_total > threshold for 60s)"
  - id: REQ-FEED-006
    title: "Tests: integration test asserts mcp_tool_call traces survive the retention window"
  - id: REQ-FEED-007
    title: "Tests: pre-warm test asserts /health shows cycles_total >= 1 within 60s of boot"
```

## 5. Implementation Phases (sketch)

### Phase 1: Retention tier wiring

**Goal:** Bound HotStore growth for `mcp_tool_call` traces.

**Sketch tasks:**

- Pick `N` from observed Phase 1 telemetry (target: 7 days post-Phase-1 baseline, the Akosha convention).
- Configure `AgingService.migrate_hot_to_warm(cutoff_days=N)` to migrate `mcp_tool_call` traces specifically. May require extending `AgingService` to filter by task_class.
- Wire AgingService as non-opt-in for `mcp_tool_call` (automatic, not manual).
- Integration test: ingest N+1 traces, run aging once, assert only N traces remain in HotStore and N+1 in WarmStore.

**Exit criteria:**

- Akosha `pytest tests/storage/test_aging.py` green.
- Manual check: after 7 days of Mahavishnu traffic, HotStore row count for `mcp_tool_call` is bounded.

#### Integration Contract (sketch)

- **Triggered from:** Akosha's existing AgingService tick (cron-like).
- **Returns to / updates:** Akosha HotStore (rows migrate out) + WarmStore (rows migrate in).
- **Demonstrable by:** `mcp__akosha__query_warm_traces(system_id="mahavishnu", task_class="mcp_tool_call")` returns traces older than the cutoff window.
- **Rollback signal:** HotStore row count grows unbounded for 24h straight.
- **Observability added:** AgingService emits a structured log line per migration cycle (rows migrated, cutoff applied, duration_ms).

---

### Phase 2: /health aggregator wiring

**Goal:** `mcp_tool_call` is a first-class feed in Akosha's `/health` aggregator.

**Sketch tasks:**

- Add a `hot_store.query_traces(task_class="mcp_tool_call", limit=1000)` call to `/health`'s dynamic build at `akosha/mcp/server.py:739` area.
- Construct `HealthFeedState("mcp_tool_call", entities_count=..., last_updated_timestamp=..., cycles_total=..., errors_total=..., last_error_at=..., ingester_running=...)` from the query results.
- Add `"mcp_tool_call_feed": mcp_tool_call_state` to the aggregator dict at `akosha/mcp/server.py:776`.
- Pre-warm: invoke `fitness_analyzer.collect_traces("mcp_tool_call")` once at Akosha boot (mirror `feedback-oneiric-mcp-health-feed-warmup` pattern from the Oneiric plan).

**Exit criteria:**

- `GET /health` returns 200 with `routes.mcp_tool_call_feed` populated within 60s of Akosha boot.
- `GET /health` returns 503 when the `mcp_tool_call` feed's `errors_total` exceeds threshold for 60s.

#### Integration Contract (sketch)

- **Triggered from:** `GET /health` request (existing dynamic build path).
- **Returns to / updates:** `/health` response JSON adds `routes.mcp_tool_call_feed` field.
- **Demonstrable by:** `curl -fsS http://127.0.0.1:8682/health | jq '.routes.mcp_tool_call_feed'`.
- **Rollback signal:** `/health` returns 503 with `mcp_tool_call_feed.status: unhealthy` for 60s straight.
- **Observability added:** `/health` route entry; pre-warm log line at Akosha boot.

---

## 6. Why this is deferred, summarized

Three things must land first:

1. **Mahavishnu Phase 1 commit `67095d98`** (lands today). Without this, there are no `mcp_tool_call` traces to retain or aggregate.
2. **Akkosha fitness-analyzer Task 1.3 edit** (lands as a paired commit on Mahavishnu main (commit 67095d98); partially done in this session as a working-tree change awaiting review). Without this, the analyzer ignores `mcp_tool_call` traces.
3. **Real `N` for the retention window** — chosen from observed Phase 1 telemetry, not guessed. A 7-day default is a reasonable starting point but should be validated against actual call volume.

This plan activates when all three are true. The activation step is a re-review (Phase 0) once the data shape is in hand.

## 7. Review Notes

No review yet — this plan is `draft` and blocked. Review happens at activation time, after Phase 1 telemetry surfaces enough call volume to pick a real retention window.
