---
status: active
role: implementation
kind: plan
date: 2026-09-27
last_reviewed: 2026-09-29
superseded_by: null
blocks_on: []
unblocks:
  - docs/plans/drafts/2026-09-26-eval-methodology.md (Plan 2 — REQ-EVAL-004 sink path)
  - docs/proposals/2026-09-27-eval-fixture-proposal.md (metric_name convention must be locked before Phase 1 fixtures ship)
activation_signal: Plan 2 eval suite ready to run nightly (≥7 days of mcp_tool_call traces captured)
delivered:
  - phase_1: commit f09035f (akosha local main, 2026-09-29) — REQ-MS-001 + REQ-MS-003 + REQ-MS-006. MCP write-side tool `akosha_add_eval_metric`, suffixed metric_name guard `is_eval_metric_name(name)`, `AddEvalMetricRequest` Pydantic schema. In-memory cache only; persistence is Phase 2.
  - phase_2: commit d07c473 (akosha local main, 2026-09-29) — REQ-MS-002 + REQ-MS-004 + REQ-MS-005. TimeSeriesAnalytics SQLite write-through backing: `metric_points` table indexed by `metric_name`, PK `(metric_name, timestamp, system_id)`, DB path via `AKOSHA_METRICS_DB_PATH` (default `~/.akosha/state/metrics.db`). `__init__` opens connection + creates schema; soft-fail on write errors (try/except + record_counter, never raise). Observability: `analytics.metrics.sqlite_write_ms` histogram + `analytics.metrics.sqlite_write_failures` counter + open-failure counter. 38 passed / 0 failed (7 unit + 3 integration + 28 backwards-compat). Plan 2's REQ-EVAL-004 now has durable eval history.
remaining:
  - phase_3: Plan 2 activation gate + Plan 2 promotion from `draft` to `active`. The Akosha-side blocker (`docs/plans/drafts/2026-09-27-akosha-eval-metric-sink.md` Phase 1+2) is now met; only Plan 2 itself remains.
topic: akosha-eval-integration
---

# Akosha Eval Metric Sink — Cross-Repo Follow-On Plan (DRAFT)

> **Status:** `draft` — **explicit cross-repo dependency**. Without this plan's deliverables, the eval fixture proposal (and therefore Plan 2 / Eval Methodology) cannot activate.
>
> **Origin:** Phase 0 multi-agent review of `docs/proposals/2026-09-27-eval-fixture-proposal.md` (2026-09-27) surfaced two **critical** findings that block the eval metric sink + one **high** finding on metric-name granularity. All three are scoped to Akosha code work, not Mahavishnu.

## 1. Outcome (target)

- **User-observable change:** `mahavishnu eval run --suite mini-v1` posts per-`(adapter, fixture)` pass rates to Akosha, which then exposes them via `mcp__akosha__analyze_trends(metric_name="eval_pass_rate:prefect", ...)` for the >10% week-over-week anomaly detector. Persistence: eval history survives Akosha process restarts.
- **Success metric:** Eval metrics land in Akosha's `analyze_trends` output within 60s of CI post. Trend storage survives a clean Akosha restart. Per-`(adapter, fixture)` breakdown queryable.

## 2. Goals (when activated)

1. Mahavishnu workers / nightly CI can write eval results to Akosha via a discoverable MCP write-side tool (currently `add_metric()` is in-process only — REQ-MS-001).
2. `TimeSeriesAnalytics._metrics_cache` survives Akosha process restarts via a serializable persistence layer (currently in-memory only — REQ-MS-002). No reliance on the decommissioned Dhara persistence layer.
3. Eval metrics use the suffixed-name convention (`eval_pass_rate:<adapter>:<fixture>`) because Akosha's `analyze_trends` keys on `metric_name` alone (no metadata-as-filter — REQ-MS-003, captured from Phase 0 review High finding #8).
4. The integration test in `tests/integration/test_eval_metric_sink.py` asserts the round trip: write from Mahavishnu → queryable from `analyze_trends` → survives restart.

## 3. Non-Goals (initial sketch)

1. Cross-tenant metric storage (single-tenant only).
2. Real-time metric ingestion (batch nightly CI is the cadence).
3. Cardinality budget enforcement on the metric namespace (separate concern from this plan's bounded set of ~144 series).
4. Auto-expiry / retention policy on `TimeSeriesAnalytics` data (orthogonal to the eval use case; could be a follow-on).
5. Re-introducing Dhara or any warm/cold tier (Dhara was decommissioned; a separate plan if reintroduced).

## 4. Current Findings

### 4.1 Phase 0 review surfaced two critical blockers (both on Akosha side)

**Critical #1 — `add_metric()` is in-process only.**
`akosha/processing/analytics.py:89-130` defines `async def add_metric(...)` on `TimeSeriesAnalytics`, but the Akosha MCP surface (`akosha/mcp/tools/akosha_tools.py:435-468`) registers only `get_system_metrics`, `analyze_trends`, `detect_anomalies`, `correlate_systems` — all read-side. Mahavishnu workers / nightly CI have no entrypoint to push eval results into `_metrics_cache`. EventBridge path (`akosha_publish_to_eventbridge` at `eventbridge_tools.py:105`) does NOT call `add_metric` (verified by grep).

**Critical #2 — `TimeSeriesAnalytics` has no persistence.**
`akosha/processing/analytics.py:86`: `_metrics_cache: dict[str, list[DataPoint]] = defaultdict(list)` is an in-memory dict. Dhara (the historical persistence layer) was decommissioned; `fitness_analyzer.py:8,52` explicitly state this. A single Akosha process restart wipes the entire eval_pass_rate history, breaking the proposal's ">10% week-over-week" detector.

### 4.2 Phase 0 review surfaced one high finding (already partially addressed)

**High #8 — per-(adapter, fixture) granularity requires suffixed metric names.**
`akosha/processing/analytics.py:86` cache key is `metric_name: str`, not `(metric_name, *dimensions)`. `DataPoint.metadata` exists (line 36) but no read path filters by metadata (lines 158, 254, 390 all use `self._metrics_cache.get(metric_name, [])`). Validation regex `^[a-zA-Z0-9_:-]+$` (validation.py:321, 398, 464) already permits suffixed names like `eval_pass_rate:prefect:code_review_py_typo` — convention is in the regex, just not documented.

The proposal `docs/proposals/2026-09-27-eval-fixture-proposal.md` already commits to this convention (revision landed in commit `38eb319a`, "Per (adapter, task_class) breakdown requires suffixed metric names"). This plan documents the Akosha side.

## 4.5 Requirements (sketch — finalized when activated)

```yaml
requirements:
  - id: REQ-MS-001
    title: "MCP write-side tool: mcp__akosha__add_eval_metric"
    description: "Expose TimeSeriesAnalytics.add_metric() via the Akosha MCP surface. One new tool, gated by existing auth, validated by the same regex as existing metric names."
  - id: REQ-MS-002
    title: "TimeSeriesAnalytics persistence layer"
    description: "Replace the in-memory _metrics_cache with a persistence-backed equivalent that survives Akosha process restart. SQLite on local disk is the recommended backing store (Akosha already uses DuckDB in the same project for HotStore; SQLite is lighter for a key-value cache)."
  - id: REQ-MS-003
    title: "Suffixed metric_name convention for eval"
    description: "Document and pin the convention `eval_pass_rate:<adapter>:<fixture_slug>` as the only valid form for eval metrics. Validation regex already permits this; add a separate validation helper for the eval namespace."
  - id: REQ-MS-004
    title: "Integration test: eval round-trip"
    description: "tests/integration/test_eval_metric_sink.py asserts: (a) Mahavishnu worker can call mcp__akosha__add_eval_metric via the MCP client, (b) mcp__akosha__analyze_trends(metric_name='eval_pass_rate:prefect:code_review_py_typo', ...) returns the posted point, (c) the point survives a clean Akosha restart (subprocess bounce + query)."
  - id: REQ-MS-005
    title: "Existing metric tooling unaffected"
    description: "get_system_metrics, analyze_trends, detect_anomalies, correlate_systems must continue to work for system metrics (CPU, memory, etc.). Persistence backing must not regress any of these. Backwards compatibility test required."
  - id: REQ-MS-006
    title: "Suffixed metric validation"
    description: "A new helper `is_eval_metric_name(name: str) -> bool` that returns True for strings matching `^eval_pass_rate:[a-z0-9_]+:[a-z0-9_]+$` and False otherwise. Used as a guard in `mcp__akosha__add_eval_metric` to prevent accidental collisions with system metrics."
```

## 5. Implementation Phases (sketch)

### Phase 1: MCP write-side tool + suffixed-metric validation (REQ-MS-001, REQ-MS-003, REQ-MS-006)

**Goal:** Mahavishnu workers can call a new Akosha MCP tool that validates the suffixed-metric-name convention and forwards into the (still in-memory) `_metrics_cache`. Persistence is Phase 2.

**Sketch tasks:**

- Add `mcp__akosha__add_eval_metric(metric_name: str, value: float, metadata: dict | None)` to `akosha/mcp/tools/akosha_tools.py` (or a new `eval_tools.py` if separation is preferred).
- Reuse the existing validation regex `^[a-zA-Z0-9_:-]+$` at the MCP boundary AND add the strict `is_eval_metric_name()` guard from REQ-MS-006. Reject on mismatch with a clear error message.
- Wire to `analytics_service.add_metric(metric_name=metric_name, value=value, metadata=metadata)` (existing method, no changes).
- Update `register_analytics_tools()` to register the new tool.
- Add `tests/unit/test_add_eval_metric.py` covering: valid suffixed names accepted; system-metric-shaped names rejected; malformed names rejected; metadata is preserved through the round-trip.

**Exit criteria:**

- `mcp__akosha__discover_tools` returns the new tool.
- Unit tests pin the validation contract.
- Integration test (Phase 2 of the parent eval plan) can post + read back.

#### Integration Contract (Phase 1)

- **Triggered from:** Mahavishnu worker (after an eval run), or nightly CI script.
- **Returns to / updates:** `TimeSeriesAnalytics._metrics_cache` (in-memory; persistence comes Phase 2).
- **Demonstrable by:** `mcp__akosha__add_eval_metric(metric_name="eval_pass_rate:prefect:code_review_py_typo", value=0.85)` → `mcp__akosha__analyze_trends(metric_name="eval_pass_rate:prefect:code_review_py_typo")` returns the posted point within the same Akosha process lifetime.
- **Rollback signal:** `mcp__akosha__add_eval_metric` rejects >5% of valid calls (validation regex too strict), or returns points that `analyze_trends` cannot read back.
- **Observability added:** `mcp__akosha__add_eval_metric` increments a call counter so operators can see eval-side write activity. No new metric namespace; the existing `get_system_metrics` surfaces the count.

---

### Phase 2: Persistence layer + restart-survival test (REQ-MS-002, REQ-MS-004, REQ-MS-005)

**Goal:** `_metrics_cache` survives Akosha process restart. Existing read-side tooling unaffected.

**Sketch tasks:**

- Replace `_metrics_cache: dict[str, list[DataPoint]] = defaultdict(list)` with a SQLite-backed equivalent. Schema:
  ```sql
  CREATE TABLE IF NOT EXISTS metric_points (
    metric_name TEXT NOT NULL,
    timestamp REAL NOT NULL,
    value REAL NOT NULL,
    system_id TEXT,
    metadata_json TEXT,
    PRIMARY KEY (metric_name, timestamp)
  );
  CREATE INDEX IF NOT EXISTS idx_metric_name ON metric_points(metric_name);
  ```
- The in-memory dict stays as a write-through cache (read path consults cache first, falls back to SQLite on miss; writes go to both). This preserves current `analyze_trends` performance characteristics.
- Migration: on Akosha startup, if `metric_points` table is empty AND `_metrics_cache` (legacy in-memory) has entries, write them to SQLite (one-time migration for existing deployments).
- `tests/integration/test_eval_metric_sink.py`: subprocess bounce test — start Akosha, post a metric, kill it cleanly, restart it, query the metric, assert it's still there.
- Backwards-compat: every existing `get_system_metrics` / `analyze_trends` / `detect_anomalies` / `correlate_systems` test must still pass.

**Exit criteria:**

- Subprocess bounce test passes (metric survives restart).
- All existing TimeSeriesAnalytics tests pass without modification.
- No regression in `analyze_trends` latency (cache-first read path).

#### Integration Contract (Phase 2)

- **Triggered from:** Akosha lifespan startup (migration check); MCP write calls (Phase 1's tool).
- **Returns to / updates:** Persistent SQLite database alongside the in-memory cache; on restart, the cache is repopulated from SQLite.
- **Demonstrable by:** `mcp__akosha__analyze_trends` returns historical points across Akosha restarts.
- **Rollback signal:** SQLite write failures >1% over 24h (disk full, permissions) — should surface as MCP error responses, not silent data loss.
- **Observability added:** SQLite write duration recorded; cache miss → SQLite hit count recorded.

---

### Phase 3: Plan 2 unblock + activation gate (no code, coordination only)

**Goal:** Document that Plan 2 can now activate.

**Sketch tasks:**

- Update Plan 2 `activation_readiness` block to reflect REQ-MS-001 + REQ-MS-002 + REQ-MS-003 shipped.
- Update the eval fixture proposal's "Cross-repo dependencies" section to remove the explicit dependency on this draft plan.
- Run a quick Phase 0 review on this plan's deliverables before declaring Plan 2 activatable.

## 6. Why this is its own plan, not folded into Plan 2

Three reasons:

1. **Cross-repo scope.** Plan 2 is Mahavishnu-side; this is Akosha-side. Per `bodai-pre-1.0-merge-policy.md` and the established paired-commit-on-each-repo-main convention, the work belongs in separate repos with separate reviews.
2. **Independent activation signal.** Plan 2 needs eval traffic to activate; this Akosha plan needs the metric-sink plumbing to activate. Either can ship first; neither blocks the other architecturally. (Plan 2 ALSO needs the plumbing, but the plumbing is correct on its own without eval traffic.)
3. **Akosha retention-tier plan is a different concern.** `docs/plans/drafts/2026-09-27-akosha-tool-call-feed-lifecycle.md` covers OTel trace retention (HotStore → WarmStore). TimeSeriesAnalytics is a separate storage system (in-memory → SQLite). Confusing the two would conflate HotStore retention with eval-metric persistence.

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| SQLite write contention under high eval cardinality (144 series × nightly = trivial volume, but extending to per-task-class × per-fixture-version could grow) | Low | Add per-series cap; explicit `cutoff_days` filter; consider future sharding if volume grows past ~10K points/series. |
| Migration corrupts existing in-memory data on first deploy | Low | Migration is write-once-if-empty-and-cache-non-empty. Idempotent. Test with synthetic pre-populated cache. |
| Suffixed-metric naming collides with future system metrics | Low | REQ-MS-006 + the `is_eval_metric_name()` guard make `eval_pass_rate:*` reserved. System metrics cannot start with `eval_pass_rate`. |
| Backwards-compat regression in `analyze_trends` after persistence backing | Medium | Pin all existing tests as pre-condition for Phase 2 commit; explicit `test_existing_metrics_unaffected.py` smoke test. |

## 8. Review Notes

No review yet — this plan is `draft` and was authored as part of resolving the
Phase 0 review of the eval fixture proposal (commit `38eb319a`). The author
intentionally kept the plan in `draft` status so a Phase 0 multi-agent
review can pin the requirements before any code is written.

**Suggested reviewers when activated:**
- `akosha-specialist` — covers the persistence choice (SQLite vs other) and
  the backwards-compat contract.
- `mcp-integration-expert` — covers the new MCP tool's signature + validation.
- `feature-dev:code-architect` — covers the migration strategy and write-through
  cache design.
- Plus a Mahavishnu-side reviewer (e.g. `mahavishnu-specialist`) to confirm
  the worker-side contract.

Reviewers should reply with **APPROVED**, **APPROVED WITH REVISIONS**, or
**REQUIRED HARDENING** per the established convention.

## 9. Decision Rule (for activation)

Activate this plan when ALL of the following are true:

1. Plan 2 (`docs/plans/drafts/2026-09-26-eval-methodology.md`) Phase 0
   reviewer sign-off on the fixture list proposal is APPROVED or APPROVED
   WITH REVISIONS (the proposal confirms this Akosha-side work is the
   blocker for metric-sink REQ-EVAL-004).
2. The eval fixture proposal's activation pre-conditions are met
   (≥7 days of `mcp_tool_call` traces OR an explicit decision to relax
   that gate for early eval smoke runs).
3. The Akosha team (or whoever owns the persistence work) is ready to
   commit to a 2-week delivery window.

When all three are true, promote this plan from `draft` to `active`
and run a Phase 0 multi-agent review before code begins.
