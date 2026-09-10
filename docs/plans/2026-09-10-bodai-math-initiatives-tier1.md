---
status: active
role: implementation
date: 2026-09-10
last_reviewed: 2026-09-10
superseded_by: null
blocks_on: []
topic: mathematical-paradigms-orchestration
review_status: ready-for-ship-v3.1
requirements:
  - id: REQ-001
    title: "Queueing library exposes M/M/c fit and Kingman/Erlang-C wait-time prediction"
  - id: REQ-002
    title: "Queueing-theoretic wait estimate is an additive routing signal"
  - id: REQ-003
    title: "Predicted vs. observed wait time persisted alongside the routing-decision record"
  - id: REQ-004
    title: "Change-point library exposes CUSUM and Page-Hinkley with ARL₀ ≥ 10,000"
  - id: REQ-005
    title: "Change-point detector integrates with mahavishnu/core/observability.py"
  - id: REQ-006
    title: "Reference 3-sigma detector remains available as gated fallback alongside change-point"
  - id: REQ-007
    title: "Tier 2 and Phase D re-evaluation triggers implemented in scripts/feature_eligibility.py"
  - id: REQ-008
    title: "Per-pool arrival timestamps recorded at the route boundary"
  - id: REQ-009
    title: "Continuous metric sample stream available via new fixed-cadence sampler"
---

# Bodai Math Initiatives — Tier 1 Implementation Plan (v3)

> **v3.2 changelog** (2026-09-10): the §1/§7 single-CUSUM trade-off is resolved
> via a two-stage warn/confirm architecture. The §1 latency gate is now measured
> on the warn detector's fire (median ≤ 30 samples on 0.5σ shift; h=8.0); the
> §7 FP gate is measured on confirmed alerts only (≤ 2 per 10,080 quiet samples;
> confirm h=14.0 + 100-sample correlation window). Both gates pass empirically
> (see `docs/audits/2026-09-10-changepoint-validation.md`). Configuration:
> `changepoint.detector: "two_stage"` opt-in; default stays `"cusum"` for
> backwards compat with the Phase 8 promotion.
>
> **v3.1 ready for ship** (2026-09-10). The v3.1 patch addresses the senior reviewer's CRITICAL finding (statistical inconsistency between §1/§11's "zero FP in 10,080 samples" gate and ARL₀ ≥ 10,000, which would have failed the gate ~63% of the time on a correctly-tuned detector) plus the HIGH recommendation (multi-metric follow-on trigger in Phase 9) and two MEDIUM runbook gaps (cross-repo gap-period guidance, post-restart re-warmup window). Reviewers and operators: §1 and §11 are now statistically consistent with the Phase 7 programmatic gate.
>
> **v3.1 changelog** (2026-09-10): patch after senior review. Substantive changes from v3:
> 1. §1 success metric rephrased: "expected ≤ 1 false positive per week of synthetic quiet operation (10,080 samples), ≤ 2 observed in any single validation run" — was "zero false positives in 1 week" (statistically inconsistent with ARL₀ ≥ 10,000: P(zero FPs) ≈ 36.5%, gate would fail ~63% of the time).
> 2. §11 Decision Rule point 1 updated to match §1.
> 3. Phase 7 programmatic gate `cusum_fp_per_10080_quiet_samples == 0` → `<= 2` (matches §1/§11 statistical reality).
> 4. Phase 9 `feature_eligibility.py` triggers expanded with `multi_metric_drift` (fires when ≥ 3 different metrics requested by operators within 30-day window). Closes the gap that operators hit the single-metric Phase 6 wall within weeks of Phase 8 promotion.
> 5. Phase 6 runbook content expanded: cross-repo gap-period guidance (Mahavishnu sub-5-min, Akosha 5-30 min ecosystem-wide correlation, upstream 30+ min) and post-restart re-warmup window (24 hours after any restart; CUSUM state is per-process and lost on restart).
>
> **v3 ready for review** (2026-09-10). The verification report (3 agents: `feature-dev:code-reviewer` for changelog compliance, `mycelium-core:architect-reviewer` for self-consistency, `pr-review-toolkit:code-reviewer` for validation matrix implementability) is at [`docs/audits/2026-09-10-math-spec-verification.md`](../audits/2026-09-10-math-spec-verification.md). Round-1 review (9 agents) is at [`docs/audits/2026-09-10-math-spec-review.md`](../audits/2026-09-10-math-spec-review.md). Reviewers: focus first on the v3 changelog below (16 substantive fixes from v2) and the §14 Review Appendix summary.
>
> **v3 changelog** (2026-09-10): patched after 3-agent verification pass addressing BLOCKERs and CRITICAL findings. Verification findings cross-referenced against actual codebase files (`scripts/audit_requirements.py:76-92`, `_ALLOWED_LABEL_KEYS` at `mahavishnu/observability/metrics.py:74`, `mahavishnu/core/routing_metrics.py:164`, `mahavishnu/pools/fitness_analyzer.py:31` for `_MAX_BUFFER_SIZE`, etc.). Substantive changes from v2:
> 1. Frontmatter `requirements:` block added — `scripts/audit_requirements.py` reads frontmatter only; body-block REQs were invisible to the audit. (BLOCKER fix)
> 2. Top-level `Makefile` added with `tier2-eligibility` target — repo had no top-level Makefile. (BLOCKER fix)
> 3. `docs/runbooks/mahavishnu-drift-detection.md` added for OTel `runbook_url` attribute. (BLOCKER fix)
> 4. Phase 6 default `threshold: 5.0` → `8.0`; `slack: 0.5` → `0.25`. Now achieves ARL₀ ≥ 10,000 at two-sided CUSUM (v2 default achieved ARL₀ ≈ 465, violating §1 success criterion). (CRITICAL fix)
> 5. §11 Decision Rule p95 bound split: `25% on Poisson; 50% on bursty/hyperexponential` (was a single looser bound that dropped the Poisson criterion).
> 6. Phase 7 zero-FP-in-1-week gate added (`assert d['cusum_fp_per_10080_quiet_samples'] == 0`). (was orphan — §1 success metric, no Phase demonstrated it)
> 7. Phase 2 warmup description rewritten cleanly; `MMcQueue` → `MmcQueue` typo fixed; new log-line justified in §4.5 as the only surface for warmup state.
> 8. Staged rollout promoted from "Recommendation" to actual task in Phase 4 and Phase 8. (was risk with no enforced mitigation)
> 9. Phase 6 `target_metric` default changed from `workflow_duration_p99` to `pool_queue_depth` (Q3 resolved).
> 10. Phase 6 task markers changed to method-level (`# req: REQ-005` on `_evaluate_change_point`) to match §5.1 mapping.
> 11. `AnomalyResult` dataclass added to §8 New files (`mahavishnu/observability/changepoint/anomaly.py`).
> 12. Phase 6 severity classifier specified: `minor` (<2×threshold), `moderate` (<4×threshold), `critical` (≥4×threshold).
> 13. §7 cross-repo stub: queue cap corrected to 1000 (was 100); HotRecord import path corrected (`akosha.models` at `mahavishnu/ingesters/otel_ingester.py:758`).
> 14. §9: `mahavishnu_routing_decisions_total` location corrected (`mahavishnu/core/routing_metrics.py:164`, not `mahavishnu/monitoring/metrics.py:routing_metrics.py:163`).
> 15. Phase 9 `feature_eligibility.py` contract: MCP endpoint names, exit codes (0=OK, 1=trigger fired without plan, 2=internal error), per-trigger output format specified.
> 16. Phase 2: `_ALLOWED_LABEL_KEYS` allowlist verification step added (labels `predicted_wait_bucket`, `effective_selector` must be in the closed `frozenset` at `mahavishnu/observability/metrics.py:74`).
>
> **v2 changelog** (2026-09-10, historical): re-drafted after 9-agent multi-perspective review. Substantive changes from v1:
> 1. §4.4 (cross-repo) rewritten: defer Phase D; add §7 stub naming the fitness-analyzer pattern + pytrendy
> 2. §4.7 (NEW): Akosha algorithm landscape — Z-score / pytrendy / proposed CUSUM
> 3. Phases renumbered flat Phase 1–9 (was A1–A4, B1–B4, C) per project convention
> 4. Phase 6 (was B2) **re-targeted**: wire to `mahavishnu/core/observability.py::ObservabilityManager`, NOT worktree-only `observability/metrics.py`
> 5. "Replace 3-sigma" framing **corrected**: Mahavishnu has no 3-sigma baseline today; this is a *new* Mahavishnu-local signal, not a replacement
> 6. CUSUM ARL₀ criterion specified explicitly (ARL₀ ≥ 10,000) — fixes internal inconsistency in v1 where ≤30 sample detection at 0.5-σ + 0 FP/week at 1-min sampling was jointly infeasible at standard settings
> 7. Queueing model renamed `MmcQueue` in `mmc.py`; Kingman vs M/M/c distinction documented with optional `approximation="erlang_c"` knob
> 8. New explicit instrumentation deliverables: arrival timestamps (Phase 2), continuous metric sampler (Phase 6)
> 9. Env-var naming uses Oneiric double-underscore convention (`MAHAVISHNU_POOLS__QUEUEING_ENABLED`)
> 10. All 9 agent findings applied; full review at `docs/audits/2026-09-10-math-spec-review.md`

## 1. Outcome

When this plan ships, the Mahavishnu orchestrator has two math-informed signals where it currently has none:

1. **Pool routing** produces expected-wait-time estimates for each
   candidate pool based on a fitted M/M/c queueing model, supplementing
   the existing `PoolSelector` strategies (`ROUND_ROBIN`,
   `LEAST_LOADED`, `RANDOM`, `AFFINITY`, `PEER_AFFINITY`). Predictions
   and observed wait times are persisted alongside the existing
   routing-decision record so operators can see when the model is
   right and when it's drifting.

2. **Drift detection** on observability metrics uses CUSUM and
   Page-Hinkley sequential tests, providing a NEW Mahavishnu-local
   signal alongside (not replacing) a new 3-sigma reference detector.
   The 3-sigma detector is a *new* Mahavishnu-local implementation, not
   a re-targeted pre-existing one — the spec explicitly does NOT claim
   to replace any current Mahavishnu baseline.

**Success metrics**:
- Queueing model: predicted-vs-observed p95 wait-time agreement within
  ±25% on synthetic Poisson workload, ±50% on synthetic bursty
  workload. Documented per-shift-size error decomposition.
- Change-point detector (two-stage warn/confirm architecture, REQ-005 extension):
  - **§1 latency gate**: time-to-first-warning ≤ 30 samples on median (p95 ≤ 100 samples)
    for a planted 0.5-σ mean shift. Measured on the warn detector's
    fire; the integration layer emits `mahavishnu.observability.drift_warning`
    at this point and increments the `mahavishnu.observability.drift_warning_total`
    Prometheus counter. Operator-visible but not page-worthy — see
    `docs/runbooks/mahavishnu-drift-detection.md` for the operator
    response when this signal fires.
  - **§7 FP gate**: confirmed alerts ≤ 2 per 10,080 quiet samples (1 week
    at 1-min cadence). Measured on the confirmed-alert stream — a
    warning that is not corroborated by the confirm detector within
    `confirm_window_samples` is discarded. The integration layer emits
    `mahavishnu.observability.drift_detected` (the page-worthy signal)
    at this point.
  - The architecture splits the spec's original single-CUSUM target
    into two complementary signals: the warn detector catches small
    shifts fast; the confirm detector filters the warning stream down
    to a low FP-rate alert stream. Both gates pass empirically at the
    production defaults (`warn_threshold=8.0`, `confirm_threshold=14.0`,
    `confirm_window_samples=100`); see
    `docs/audits/2026-09-10-changepoint-validation.md`.
  - For operators preferring the legacy single-detector behavior,
    `changepoint.detector: "cusum"` (default for backwards compat)
    runs the original Phase 6 detector and inherits the §1/§7
    trade-off documented in the runbook.
- Both signals visible in `mahavishnu metrics` CLI output and in the
  existing Dhara-persisted routing-decision and observability records.

## 2. Goals

1. Build a pure-Python queueing library that fits M/M/c parameters from
   observed pool statistics and produces Kingman-approximation
   wait-time estimates, with an `approximation="erlang_c"` option for
   higher fidelity at small `c`. (Phase 1)
2. Wire the queueing-theoretic estimate into `mahavishnu/pools/manager.py`
   as an additive `QueueingScorer` wrapper around any existing
   `PoolSelector`, NOT a new enum member. (Phase 2)
3. Build a pure-Python sequential-test library implementing CUSUM
   (one-sided and two-sided) and Page-Hinkley with configurable
   sensitivity and ARL₀ target. (Phase 5)
4. Integrate the change-point detector into
   `mahavishnu/core/observability.py::ObservabilityManager` (the
   **general** observability surface), with a new fixed-cadence
   sampler providing the sample stream. (Phase 6)
5. Log both prediction-vs-actual (queueing) and detection-vs-baseline
   (change-point) by extending existing Dhara-persisted records and
   adding one OTel span per event. (Phase 2, Phase 6)
6. Define explicit re-evaluation triggers for the deferred Tier 2
   initiatives (optimal transport, hyperbolic embeddings) and the
   cross-repo follow-on (Phase D, deferred). (Phase 9, §7)

## 3. Non-Goals

1. **Not** replacing existing routing strategies. The math becomes an
   *additional signal* the routing selector can use; all five
   `PoolSelector` values keep working unchanged.
2. **Not** implementing M/G/c, G/G/c, or hyperexponential models in
   Phase 1. M/M/c with Kingman and Erlang-C options is the prototype.
3. **Not** touching Akosha, Dhara, Session-Buddy, or Crackerjack code
   in this plan. The cross-repo follow-on (§7) names the right
   mechanism (extend `mahavishnu/pools/fitness_analyzer.py` task_classes
   list at line 279) for when that work happens — but it is not in
   this plan.
4. **Not** introducing new dependencies beyond the Python standard
   library. (`numpy`, `scipy`, `ruptures` are explicitly rejected as
   not earning their keep at this scope.)
5. **Not** building dashboards, alerts, or operator-facing UI. The
   new signals are observable via existing `mahavishnu metrics` CLI,
   structured logs, and the Dhara-persisted records that the existing
   `routing_metrics_persistence` and `observability` code already
   maintain.
6. **Not** implementing Tier 2 initiatives (optimal transport for
   Akosha, hyperbolic embeddings for Session-Buddy) or the Phase D
   cross-repo wiring. All three are documented with explicit
   re-evaluation triggers.
7. **Not** implementing a Mahavishnu 3-sigma baseline replacement —
   because Mahavishnu has no 3-sigma baseline today. The 3-sigma
   fallback in Phase 6 is a new Mahavishnu-local reference detector,
   not a re-targeted pre-existing one.

## 4. Current Findings

### 4.1 Pool routing is heuristic-only

`mahavishnu/pools/manager.py` exposes a `PoolSelector` enum with five
members (`ROUND_ROBIN`, `LEAST_LOADED`, `RANDOM`, `AFFINITY`,
`PEER_AFFINITY`). The actual selector chain in `route_task` is a
sequence of runtime overrides: `_enforce_caller_quota` (gate before
selection), `_apply_fitness_aware_routing` (Dhara fitness override
of `selector`), `_apply_gpu_category_override` (runpod override for
`vision`/`ml_inference`/`embedding` task categories), then final
selection.

None of these selectors answer the question "what's the expected wait
time for this task on this pool?" `least_loaded` approximates by
counting current queue depth but doesn't account for:

- Worker service-rate heterogeneity (one worker type may be slower
  than another — `terminal-claude` vs `terminal-codex` etc., per the
  `worker_registry` block in `settings/mahavishnu.yaml`)
- Arrival-rate variation (a pool handling bursts is worse than one
  handling steady traffic at the same current depth)
- The convex blow-up of wait time as utilization approaches 1
  (Kingman's `(ρ / (1 − ρ))` term)

### 4.2 No Mahavishnu-local anomaly detector today

The "3-sigma baseline" v1 referenced does not exist in Mahavishnu.
What does exist:

- `mcp__akosha__akosha_detect_anomalies` (Akosha repo, separate) —
  Z-score pointwise detector using a sliding window over
  `akosha.processing.analytics._metrics_cache`. Threshold = 3σ.
- `mcp__akosha__akosha_analyze_changepoints` (Akosha repo) — segmented
  regression via `pytrendy`, gated behind Dhara wiring at MCP-server
  startup; not currently live.
- `mahavishnu/routing_alerts.py:283::evaluate_cost_anomalies` — a stub,
  not a real detector.
- `mahavishnu/pools/fitness_analyzer.py` — a polling pipeline that
  computes `failure_rate` and `p99_latency_ms` per `(task_class,
  selector)` every 60s and persists to Dhara with TTL=7200s, but does
  not emit anomaly detections.

This plan therefore adds a NEW Mahavishnu-local reference detector
(Z-score over a sliding window) **and** the change-point detector as
its CUSUM/PH replacement. The 3-sigma detector is not a re-targeting
of an existing Mahavishnu baseline.

### 4.3 Observability data is request/response, not stream

`mcp__mahavishnu__get_observability_metrics`
(`mahavishnu/mcp/server_core.py:649-677`) calls
`self.app.observability.get_performance_metrics()` and returns a
single snapshot of in-memory state. There is no continuous-sample
time-series buffer.

WebSocket channels (`workflow:*`, `pool:*`, `worker:*`, `adapters`,
`goal-teams`, `settle:*`, `cross-repo:*`, `global`) are event-driven —
they fire on state change, not on a fixed sample cadence. The
`channel.startswith(...)` allowlist in `mahavishnu/websocket/server.py`
does not currently include `metrics:*`.

The only artifact that resembles a time-series buffer is
`RoutingDecisionBuffer` in `mahavishnu/core/ecosystem_status.py:121` —
a ring buffer keyed by `pool/task_type` for routing decisions, not
metric values.

For Phase 6 to work, a new fixed-cadence sampler must be added that
pushes `(ts, value)` tuples to a new metrics time-series table in
Dhara (or to a new `metrics:*` WebSocket channel with allowlist
extension). See Phase 6 Integration Contract for the deliverable.

### 4.4 No per-pool arrival timestamps recorded today

`route_task` writes only the routing-decision timestamp at
`mahavishnu/pools/manager.py:268`. `execute_on_pool` does not stamp
arrivals. `_task_durations` in `mahavishnu/pools/mahavishnu_pool.py:81`
holds raw service-time floats per-pool, in-memory, unbounded, never
exposed.

Without new instrumentation at the route boundary, M/M/c cannot be
fit on real traffic — only on synthetic tests. Phase 2 includes
arrival-timestamp recording as an explicit deliverable.

### 4.5 Routing-decision persistence already has five surfaces (four emission surfaces + one in-memory state)

The spec's v1 plan to add a new structured log line
(`mahavishnu.pool.routing_decision`) would create a sixth parallel
emission path. Today the routing decision is persisted to:

1. In-memory state at `manager.py:242` (not an emission surface)
2. Dhara via `_dhara_state.persist_routing_decision`,
   `manager.py:684-692`
3. `MessageBus` as `task_completed`
4. Prometheus counter `mahavishnu_routing_decisions_total` at
   `mahavishnu/core/routing_metrics.py:164`
5. WebSocket event `adapter.routing_decision` at
   `mahavishnu/websocket/server.py:1133`

Items 2–5 are the four existing emission surfaces. Phase 2 extends
the Dhara record (column additions) and the Prometheus counter
(label additions) — no new parallel emission surface.

**Exception**: the queueing warmup-pending signal
(`mahavishnu.pool.queueing_warmup_pending`) is permitted as a single
debug log line because the warmup state has no other surface — no
Prometheus counter applies to "the model isn't fit yet," no OTel
span captures a not-yet-existent detector event, and the Dhara
routing-decision record only persists what the routing selector
actually did, not what it deferred. This is the only exception to
the no-new-parallel-emission-surface rule, and is referenced by
Phase 2's `QueueingScorer.score` warmup path.

### 4.6 Cross-repo deferral rationale

The v1 spec deferred cross-repo integration as a "follow-on plan."
That decision stands in v2 but for a richer set of reasons established
by the multi-agent review:

1. **Akosha already has a change-point detector** (`akosha_analyze_changepoints` backed by `pytrendy`) in the same conceptual slot. The framing in v1 of "replace Akosha's 3-sigma baseline" was wrong from the start: Z-score (pointwise), pytrendy (batch segmentation), and CUSUM/PH (online sequential) are three orthogonal detectors answering different questions. CUSUM/PH belong alongside pytrendy, not as a replacement for Z-score.

2. **The cross-repo mechanism with the lowest cost and cleanest separation is to extend `mahavishnu/pools/fitness_analyzer.py:279`**. Adding `"routing_change_point"` to its hard-coded `task_classes` list, plus writing `HotRecord` objects with the right metadata when the detector fires, is <100 LOC and reuses battle-tested plumbing (Redis stream `bodai:events`, queue cap 100, circuit breaker, DLQ after 3 consecutive write failures). No new WebSocket channel or HTTP endpoint needed.

3. **Akosha is meant to be the seer/intelligence source** for the ecosystem, not a consumer of Mahavishnu services. Routing Akosha's anomaly path through a Mahavishnu MCP call inverts the dependency direction (`CLAUDE.md` ecosystem context table).

4. **Shipping CUSUM in Akosha without Mahavishnu-side validation first** means a detector bug breaks both repos with two releases to roll back. Validate locally first, then expand.

§7 captures the cross-repo follow-on as a
documentation stub that names the right mechanism, so a future plan
author doesn't re-derive this from scratch.

### 4.7 Tier 2 deferred items + re-evaluation triggers

| Initiative | Math | Why deferred | Re-evaluation trigger |
|---|---|---|---|
| Optimal transport for Akosha pattern comparison | Wasserstein distance | Needs cross-system pattern distributions with shape differences statistically meaningful | `akosha.patterns.cross_system_snapshot_count ≥ 10,000` over a 30-day window |
| Hyperbolic embeddings for Session-Buddy code graphs | Poincaré disk / tree-structured embeddings | Needs real code graphs at training scale | `session_buddy.code_graph.node_count ≥ 10,000` AND code-graph coverage ≥ 60% of indexed repos |
| Cross-repo Phase D (Akosha detector wiring) | Extend `fitness_analyzer.py` task_classes | Phase 1–8 must ship and validate first; cross-repo risk | Phase 8 promoted AND ≥ 1 week production operation with drift signal useful to operators |

Phase 9 implements these triggers as a CI-checkable script
(`scripts/feature_eligibility.py`) and adds `docs/followups/` entries
per `.claude/decisions/followups-lifecycle.md`.

## 5. Requirements

```yaml
requirements:
  - id: REQ-001
    title: "Queueing library exposes M/M/c fit and Kingman/Erlang-C wait-time prediction"
  - id: REQ-002
    title: "Queueing-theoretic wait estimate is an additive routing signal"
  - id: REQ-003
    title: "Predicted vs. observed wait time persisted alongside the routing-decision record"
  - id: REQ-004
    title: "Change-point library exposes CUSUM and Page-Hinkley with ARL₀ ≥ 10,000"
  - id: REQ-005
    title: "Change-point detector integrates with mahavishnu/core/observability.py"
  - id: REQ-006
    title: "Reference 3-sigma detector remains available as gated fallback alongside change-point"
  - id: REQ-007
    title: "Tier 2 and Phase D re-evaluation triggers implemented in scripts/feature_eligibility.py"
  - id: REQ-008
    title: "Per-pool arrival timestamps recorded at the route boundary"
  - id: REQ-009
    title: "Continuous metric sample stream available via new fixed-cadence sampler"
```

### 5.1 REQ → file mapping

| REQ | File(s) | Marker location |
|---|---|---|
| REQ-001 | `mahavishnu/pools/queueing/mmc.py` | module docstring `# Implements: REQ-001` |
| REQ-002 | `mahavishnu/pools/manager.py` | `QueueingScorer.score` method `# req: REQ-002` |
| REQ-003 | `mahavishnu/pools/manager.py` | `_persist_routing_decision` record extension `# req: REQ-003` |
| REQ-004 | `mahavishnu/observability/changepoint/cusum.py` and `page_hinkley.py` | module docstrings `# Implements: REQ-004` |
| REQ-005 | `mahavishnu/core/observability.py` | `ObservabilityManager._evaluate_change_point` method `# req: REQ-005` |
| REQ-006 | `mahavishnu/core/observability.py` | `ObservabilityManager._evaluate_3sigma` method `# req: REQ-006` |
| REQ-007 | `scripts/feature_eligibility.py` | module docstring `# Implements: REQ-007` |
| REQ-008 | `mahavishnu/pools/manager.py` | `route_task` arrival-timestamp recording `# req: REQ-008` |
| REQ-009 | `mahavishnu/observability/sampler.py` (new) | `MetricSampler` class `# Implements: REQ-009` |

Every declared REQ ID is referenced by code or tests via these markers
so `scripts/audit_requirements.py --include-tests` passes.

## 6. Implementation Phases

### Phase 1: Queueing library

**Goal**: Pure-Python module that fits M/M/c model parameters from
observed queue statistics and produces Kingman-approximation (and
optionally Erlang-C-exact) wait-time estimates.

**Tasks**:
- Create `mahavishnu/pools/queueing/__init__.py` with public API and `__all__`
- Create `mahavishnu/pools/queueing/mmc.py` with:
  - Class `MmcQueue` (PEP 8; was `MMcQueue` in v1)
  - `from __future__ import annotations`
  - `from collections.abc import Sequence`
  - Google-style docstrings with `Args:` / `Returns:` / `Raises:`
  - Constructors validate `service_rate > 0`, `num_workers >= 1`, `arrival_rate >= 0` via `__post_init__`
  - `fit_from_observations` classmethod accepts `Sequence[float]` of inter-arrival times (gaps) and service times; raises `QueueingModelError` from `mahavishnu/core/errors.py` on empty input (propagates `statistics.StatisticsError`)
  - `expected_wait_time(approximation: Literal["kingman", "erlang_c"] = "kingman")` chooses the formula; both require ρ < 1
  - `expected_queue_length()` returns `L_q = λ · W_q`; `expected_number_in_system()` returns `L = λ · W`
  - `safe_expected_wait_time(utilization_cap: float = 0.95)` returns `inf` past the cap; router uses this for "don't route here" guardrails
  - Module docstring includes `# Implements: REQ-001`
- Create `tests/unit/pools/test_queueing.py` with:
  - Reference-value tests from Gross & Harris / Harchol-Balter
  - Hypothesis property tests: `@given(arrival_rate=..., service_rate=..., num_workers=...)` for utilization invariant, Little's law, NaN/Inf rejection, single-worker boundary, ρ→1 boundary
  - `@pytest.mark.unit` marker
  - Reference-value tests use `pytest.approx(..., rel=...)` not `assert math.isclose(...)` (bandit B101)

**Interfaces (consumed by Phase 2)**:
```python
from typing import Literal
from collections.abc import Sequence

class MmcQueue:
    def __init__(self, arrival_rate: float, service_rate: float, num_workers: int) -> None: ...
    @classmethod
    def fit_from_observations(
        cls, arrivals: Sequence[float], services: Sequence[float], num_workers: int,
    ) -> "MmcQueue": ...
    @property
    def utilization(self) -> float: ...  # ρ = λ / (c·μ); raises QueueingModelError if ≥ 1
    def expected_wait_time(
        self, approximation: Literal["kingman", "erlang_c"] = "kingman",
    ) -> float: ...
    def expected_queue_length(self) -> float: ...  # L_q
    def expected_number_in_system(self) -> float: ...  # L
    def safe_expected_wait_time(self, utilization_cap: float = 0.95) -> float: ...
```
Inputs are floats (rates in tasks/sec); outputs are floats (wait in
seconds, length in tasks). The class is stateless after construction.

#### Integration Contract — Phase 1 deliverable
- **Triggered from**: import of `mahavishnu.pools.queueing.MmcQueue` from any Mahavishnu code; direct invocation via `pytest tests/unit/pools/test_queueing.py`.
- **Returns to / updates**: in-memory objects only — no persistent effect. Test coverage ≥90% line coverage on `mmc.py`.
- **Demonstrable by**: `pytest tests/unit/pools/test_queueing.py -v` passes all reference-value and Hypothesis property tests.
- **Rollback signal**: any failing test. Library has no external wiring yet, so rollback is `git revert` of Phase 1 commit(s).
- **Observability added**: Oneiric logger (`from oneiric.logging import get_logger`) for any future debugging; test coverage report in `htmlcov/index.html`. No production telemetry — pure-math library.
- **Fulfils**: REQ-001.

### Phase 2: Pool routing integration

**Goal**: `mahavishnu/pools/manager.py` exposes a new
`QueueingScorer` wrapper class that consults the queueing model for
expected wait time and combines with the inner `PoolSelector`'s score.
NOT a new `PoolSelector` enum member.

**Tasks**:
- Add `wait_time_estimate: float | None = None` and `queueing_model: MmcQueue | None = None` to `mahavishnu/pools/base.py::PoolMetrics` (NOT a new `PoolState` class — there is no `PoolState` in the codebase)
- Add `queueing_enabled: bool = False` field to `mahavishnu/core/config.py::PoolConfig` (Pydantic model has `extra: forbid`, so the field must be declared on the model)
- Add top-level `queueing:` config block to `settings/mahavishnu.yaml` with `enabled`, `warmup_min_observations` (default 100), `warmup_min_seconds` (default 600)
- Create `mahavishnu/pools/queueing/scorer.py` with `QueueingScorer` class:
  - `def __init__(self, inner: PoolSelector, model: MmcQueue | None = None) -> None`
  - `def score(self, pool: PoolMetrics, task: Task) -> float` returns the inner selector's score during normal operation. During warmup (insufficient observations OR `arrival_rate == 0`), `score` returns the inner selector's score unchanged and emits exactly one `mahavishnu.pool.queueing_warmup_pending` debug log line per `route_task` invocation. During normal operation, `score` returns the inner selector's score minus the predicted-wait penalty (scaled so the penalty does not dominate the inner selector's signal).
  - Module docstring includes `# req: REQ-002`
- Add arrival-timestamp recording to `route_task`:
  - At `mahavishnu/pools/manager.py:693`, stamp `arrival_ts = time.monotonic()` before routing decision
  - Pair arrival with observed service time after `task_completed` event
  - Append to a `deque(maxlen=N)` per pool (the warmup window) for `MmcQueue.fit_from_observations`
  - Re-fit every `warmup_min_observations` rounds OR every `warmup_min_seconds`, whichever first
  - Module docstring includes `# req: REQ-008`
- Add new MCP tool `mcp__mahavishnu__pool_queueing_observations(pool_id: str, window_seconds: int = 600) -> JSONResponse` exposing the per-pool arrival/service observation buffer for ops/debugging
- Extend the existing Dhara routing-decision record at `_dhara_state.persist_routing_decision` (`manager.py:684-692`):
  - Add fields `predicted_wait_s: float | None`, `observed_wait_s: float | None`, `effective_selector: str` (so dashboards distinguish `round_robin` from `round_robin+queueing`)
  - Module docstring includes `# req: REQ-003`
- The `mahavishnu.pool.queueing_warmup_pending` debug log line emitted by `QueueingScorer.score` during warmup is the only new emission surface in this phase (per §4.5's exception); no other new log lines, Prometheus counters, OTel spans, or WebSocket channels are introduced
- Add Prometheus counter labels: extend `mahavishnu_routing_decisions_total` with `predicted_wait_bucket` and `effective_selector`
- Add Prometheus histogram `mahavishnu.pool.queueing_prediction_error` with labels `pool_id` and `selector`
- Add OTel span `mahavishnu.pool.routing_decision` with attributes `pool_id`, `predicted_wait_s`, `observed_wait_s`, `effective_selector`
- Composition with pre-existing hooks: `QueueingScorer` runs **between** `_apply_fitness_aware_routing` (which picks the selector) and `_apply_gpu_category_override` (which can swap to runpod). The `effective_selector` field captures what the routing layer actually chose.
- Auto-spawn path: `MmcQueue.fit_from_observations` returns a fitted model with `utilization = 0` until observations accumulate; the scorer handles this without raising
- Verify the new Prometheus labels `predicted_wait_bucket` and `effective_selector` (extending `mahavishnu_routing_decisions_total`) are accepted by the `_ALLOWED_LABEL_KEYS` set at `mahavishnu/observability/metrics.py:74`. This set is `Final[frozenset[str]]` (closed at import time); if the new labels are not in the allowlist, add them to the set in a Phase 2 commit, otherwise the counter silently drops them at emission.
- Env-var override (Oneiric double-underscore convention): `MAHAVISHNU_POOLS__QUEUEING_ENABLED=false`

**Interfaces (consumed by Phase 3)**:
```python
class QueueingScorer:
    def __init__(self, inner: PoolSelector, model: MmcQueue | None = None) -> None: ...
    def score(self, pool: PoolMetrics, task: Task) -> float: ...

class MetricSampler: ...  # placeholder for Phase 6
```

#### Integration Contract — Phase 2 deliverable
- **Triggered from**: every call to `route_task` in `mahavishnu/pools/manager.py` whenever `PoolConfig.queueing_enabled=true`. Also exercisable via `mcp__mahavishnu__pool_route_execute` (no selector change needed — the wrapper applies transparently) and `mcp__mahavishnu__pool_queueing_observations` for buffer inspection.
- **Returns to / updates**: existing `_dhara_state.persist_routing_decision` record extended with three fields; existing `mahavishnu_routing_decisions_total` Prometheus counter extended with two labels; new `mahavishnu.pool.queueing_prediction_error` histogram; new `mahavishnu.pool.queueing_warmup_pending` debug log during warmup; new OTel span `mahavishnu.pool.routing_decision`. New per-pool `deque(maxlen=N)` in pool memory.
- **Demonstrable by**: integration test `tests/integration/pools/test_queueing_routing.py` generates 1000 synthetic Poisson tasks and asserts median predicted-vs-observed wait-time error < 25%, p95 < 50%. Also asserts that during warmup the scorer returns inner-selector score unchanged with the warmup_pending log emitted.
- **Rollback signal**: setting `MAHAVISHNU_POOLS__QUEUEING_ENABLED=false` (env) or `pools.queueing.enabled: false` (YAML) immediately reverts to the prior behavior — the scorer becomes a pass-through.
- **Observability added**: new OTel span `mahavishnu.pool.routing_decision`; new Prometheus histogram `mahavishnu.pool.queueing_prediction_error`; existing routing-decision record extended; warmup debug log line.
- **Fulfils**: REQ-002, REQ-003, REQ-008.

### Phase 3: Queueing validation (documentation-only)

**Goal**: Validate the queueing-informed routing on synthetic workloads;
document the math and its assumptions; produce the validation report.

**Tasks**:
- Mark this phase explicitly as `documentation-only` per `docs/plans/TEMPLATE.md:134`
- Run `tests/integration/pools/test_queueing_routing.py` against:
  - Pure Poisson workload (should match exactly)
  - Bursty workload (validation that error stays bounded)
  - Hyperexponential service-time workload (documents where M/M/c breaks)
- Add programmatic gate: `pytest tests/integration/pools/test_queueing_routing.py --benchmark-json=bench.json && python -c "import json; d = json.load(open('bench.json')); assert d['p95_error'] < 0.25; assert d['median_error'] < 0.10"` — the doc reports the same numbers but the gate is mechanical
- Per-shift-size decomposition for bursty and hyperexponential workloads: error budget per CV² tier, so reviewers see where the model genuinely degrades
- Add `docs/pools/queueing_routing.md` explaining the math, the assumptions, and how to interpret the validation report
- Add `docs/audits/2026-09-10-queueing-validation.md` with the actual numbers
- Add `python scripts/audit_orphans.py` to the validation step (run after every phase per `.claude/decisions/wire-up-contract.md`, not only at promotion)

#### Integration Contract — Phase 3 deliverable
- **Triggered from**: `pytest tests/integration/pools/test_queueing_routing.py --benchmark-json=bench.json` runs the validation harness. `python scripts/audit_orphans.py` checks for orphaned symbols.
- **Returns to / updates**: `docs/pools/queueing_routing.md` (explanatory) + `docs/audits/2026-09-10-queueing-validation.md` (numbers); `htmlcov/index.html` coverage report; `bench.json` benchmark artifact.
- **Demonstrable by**: a reviewer can read the audit doc and see median error < 25% on Poisson, p95 < 50% across all three workload patterns, with the per-shift-size table showing where the model degrades. The programmatic gate (`python -c "...assert..."` from above) passes.
- **Rollback signal**: validation failure → Phase 4 promotion blocked; Phase 2's opt-in default stays `false`.
- **Observability added**: validation report and benchmark artifact are the only outputs. Runtime observability is unchanged from Phase 2.
- **Fulfils**: REQ-001, REQ-002, REQ-003, REQ-008 (verification).

### Phase 4: Promote queueing default

**Goal**: After Phase 3 validation passes, flip
`pools.queueing.enabled` default to `true` so the feature ships to
all users, not just opt-in adopters.

**Tasks**:
- Update `settings/mahavishnu.yaml` default
- Update `CHANGELOG.md`
- Add `docs/feature-tracking/2026-09-10-pool-queueing-routing.md` tracking `built` → `wired` → `adopted` lifecycle
- Run `python scripts/audit_orphans.py` and `python scripts/audit_requirements.py --include-tests`
- **Staged rollout**: do not flip the global default in a single commit. Sequence: (1) flip default to `true` in `settings/mahavishnu.yaml`; (2) override to `false` in `settings/local.yaml` per environment (one production environment first, others opt-in); (3) the feature-tracking entry's rollout playbook names (a) which environment is first, (b) what metrics gate progression (median predicted-vs-observed wait-time error + p95 prediction error from Phase 2 integration test, sampled daily), (c) what monitoring window applies per stage (≥ 7 days of stable metrics before next stage), (d) the per-environment opt-out template. The Playbook lives at `docs/feature-tracking/2026-09-10-pool-queueing-routing.md`.

#### Integration Contract — Phase 4 deliverable
- **Triggered from**: config change in `settings/mahavishnu.yaml`; new default takes effect on next `mahavishnu mcp start`. Staged rollout is controlled by the deployment process (e.g., `MAHAVISHNU_POOLS__QUEUEING_ENABLED=false` in env per environment).
- **Returns to / updates**: `settings/mahavishnu.yaml`, `CHANGELOG.md`, `docs/feature-tracking/`.
- **Demonstrable by**: starting Mahavishnu with default config and observing the new OTel span and Prometheus histogram populated.
- **Rollback signal**: env-var override per environment, or YAML revert.
- **Observability added**: feature-tracking entry links to validation report and lists Phase 2's metrics as ongoing health indicators.
- **Fulfils**: REQ-002, REQ-003, REQ-008 (production enablement).

### Phase 5: Change-point library

**Goal**: Pure-Python sequential-test module implementing CUSUM
(one-sided and two-sided) and Page-Hinkley with configurable
sensitivity and ARL₀ ≥ 10,000.

**Tasks**:
- Create `mahavishnu/observability/changepoint/__init__.py` with `__all__`
- Create `mahavishnu/observability/changepoint/cusum.py`:
  - `from __future__ import annotations`, Oneiric logger, Google-style docstrings
  - `@dataclass(frozen=True, slots=True)` for `ChangePointResult` per project precedent (`mahavishnu/auth.py:29`, `llm_gateway/contract.py:118`)
  - `ChangePointResult` fields: `detected: bool`, `score_high: float`, `score_low: float`, `score: float` (computed = max(score_high, score_low)), `threshold: float`, `samples_since_reset: int`, `direction: Literal["up", "down", "unknown"]`
  - `@runtime_checkable` Protocol `ChangePointDetector`
  - `CUSUMDetector.__init__(self, target_mean: float, slack: float, threshold: float, two_sided: bool = True)` — explicit Google docstring maps `slack` → classical `k` (allowance) and `threshold` → classical `h` (decision interval); defaults documented as `k = 0.5σ` for one-sided, `k = 0.25σ` for two-sided
  - Module docstring `# Implements: REQ-004`
- Create `mahavishnu/observability/changepoint/page_hinkley.py`:
  - Same patterns
  - `PageHinkleyDetector.__init__(self, target_mean: float, slack: float, threshold: float, delta: float = 0.0)` — `delta` documented as minimum detectable shift magnitude (not the post-change mean)
  - Module docstring `# Implements: REQ-004`
- Create `tests/unit/observability/test_changepoint.py` with:
  - Hypothesis property tests: stationary Gaussian series with threshold swept over a range → assert ARL₀ ≥ 10,000 at the canonical setting
  - Planted-change-point benchmarks at shift sizes 0.25σ, 0.5σ, 1.0σ with `numpy.random.Generator(PCG64)` for reproducibility
  - Edge cases: NaN/Inf rejection, single observation, reset semantics, concurrent updates (single-thread expected per the integration contract; document the lock requirement)
  - `@pytest.mark.unit` and `@pytest.mark.property` markers as appropriate

**Interfaces (consumed by Phase 6)**:
```python
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

@dataclass(frozen=True, slots=True)
class ChangePointResult:
    detected: bool
    score_high: float
    score_low: float
    score: float  # computed = max(score_high, score_low)
    threshold: float
    samples_since_reset: int
    direction: Literal["up", "down", "unknown"]

@runtime_checkable
class ChangePointDetector(Protocol):
    def update(self, observation: float) -> ChangePointResult: ...
    def reset(self) -> None: ...

class CUSUMDetector: ...
class PageHinkleyDetector: ...
```

#### Integration Contract — Phase 5 deliverable
- **Triggered from**: import of `mahavishnu.observability.changepoint`; direct invocation via `pytest tests/unit/observability/test_changepoint.py`.
- **Returns to / updates**: in-memory objects only. Test coverage ≥90% line coverage on `cusum.py` and `page_hinkley.py`.
- **Demonstrable by**: `pytest tests/unit/observability/test_changepoint.py -v` passes including the ARL₀ property test (≥ 10,000 on 10K-sample stationary Gaussian at canonical settings) and planted-shift latency benchmarks (median ≤ 30 samples at 0.5-σ shift, p95 ≤ 100 samples).
- **Rollback signal**: any failing test → git revert of Phase 5 commits. Library has no external wiring yet.
- **Observability added**: Oneiric logger for debugging; test coverage report. No production telemetry.
- **Fulfils**: REQ-004.

### Phase 6: Change-point observability integration

**Goal**: Wire CUSUM/PH detector into
`mahavishnu/core/observability.py::ObservabilityManager`, alongside a
NEW Mahavishnu-local 3-sigma reference detector (not a re-targeted
pre-existing one — see §4.2).

**Tasks**:
- Create `mahavishnu/observability/sampler.py` (new) with `MetricSampler` class:
  - Fixed-cadence sampler that pulls observations from a configurable source (initially `ObservabilityManager.get_performance_metrics()` snapshots; later extensible to WebSocket channel subscribers)
  - Pushes `(ts, value)` tuples to a new `mahavishnu.observability.metric_samples` Dhara table (also expose via new WebSocket channel `metrics:*` if low-latency consumers emerge)
  - Default sample cadence: 60 seconds (matches `fitness_analyzer.py` precedent)
  - Module docstring `# Implements: REQ-009`
- Add `changepoint:` top-level config block to `settings/mahavishnu.yaml` (NOT nested under `observability:`, per the precedent of `pi_pool:`, `runpod_pool:`, `dhara_state:`, `verification:`, `caller_quota:`, `worktree_providers:`):
  - `enabled: bool = false`
  - `target_metric: str = "pool_queue_depth"` (configurable; one metric at a time per the contract; default matches Q3 recommendation and reuses Phase 2's per-pool instrumentation)
  - `detector: Literal["cusum", "page_hinkley"] = "cusum"`
  - `slack: float = 0.25` (k parameter in σ units; 0.25σ allows detection of 0.5-σ shifts with sub-100-sample latency)
  - `threshold: float = 8.0` (h parameter; at two-sided CUSUM with k=0.25σ, achieves ARL₀ ≈ 10,000 at standard settings per Brook & Evans 1972; empirical validation in Phase 7 is the source of truth and may tune)
  - `reference_detector: Literal["three_sigma", "none"] = "three_sigma"`
- Add env-var override: `MAHAVISHNU_CHANGEPOINT__ENABLED=false` (Oneiric double-underscore)
- Extend `mahavishnu/core/config.py::ObservabilityConfig` (or add a top-level `ChangepointConfig` Pydantic sub-model under the `changepoint:` block):
  - The current flat schema with `extra: forbid` means a nested shape requires a sub-model; the spec follows the precedent of `caller_quota:`, `pi_pool:` etc. which use a top-level block with a `XXXConfig` Pydantic class
- Implement `ObservabilityManager._evaluate_change_point(self, metric_name: str, value: float) -> ChangePointResult` in `mahavishnu/core/observability.py`:
  - Routes through the `MetricSampler`-fed queue
  - On `result.detected == True`, emits an OTel span `mahavishnu.observability.drift_detected` with attributes `metric_name`, `detector`, `score_high`, `score_low`, `score`, `threshold`, `samples_since_reset`, `direction`, `current_value`, `baseline_mean`, `baseline_std`, `severity: Literal["minor", "moderate", "critical"]`, `host`, `instance_id`, `trace_id` (when available from upstream), `runbook_url`
  - **Severity classifier**: `minor` if `score < 2 * threshold`, `moderate` if `2 * threshold <= score < 4 * threshold`, `critical` if `score >= 4 * threshold`. Tunable in config; default chosen so `minor` matches typical 0.5-σ shift detections, `critical` flags > 1-σ shift territory.
  - Increments Prometheus counter `mahavishnu.observability.drift_detected_total` with labels `metric_name`, `detector`, `severity`
  - Method-level marker `# req: REQ-005` on `_evaluate_change_point` (matches §5.1 mapping)
- Create `mahavishnu/observability/changepoint/anomaly.py` with `AnomalyResult` dataclass:
  - `@dataclass(frozen=True, slots=True)` per project precedent
  - Fields: `detected: bool`, `z_score: float`, `current_value: float`, `window_mean: float`, `window_std: float`
  - Module docstring `# Implements: REQ-006` (marker location chosen to satisfy `audit_requirements.py` frontmatter scan)
- Implement `ObservabilityManager._evaluate_3sigma(self, metric_name: str, value: float) -> AnomalyResult` (NEW reference detector, not a re-target):
  - Sliding window over the same `MetricSampler`-fed queue (default 1-hour window)
  - Z-score pointwise flag at 3σ
  - Method-level marker `# req: REQ-006` on `_evaluate_3sigma` (matches §5.1 mapping)
- Create `docs/runbooks/mahavishnu-drift-detection.md` with the on-call procedure:
  - What to check first (current `metric_samples` value vs baseline), how to verify it's not a transient, when to silence vs escalate
  - **Cross-repo gap-period guidance** (until Phase D wires Mahavishnu drift detection into Akosha): when `mahavishnu.observability.drift_detected` fires, also check `mcp__akosha__akosha_detect_anomalies` results on the same metric class; the runbook names the order — Mahavishnu for sub-5-minute signal, Akosha for 5–30 minute ecosystem-wide correlation, upstream investigation for 30+ minute. This is the practical answer to the two-control-plane gap during Phase 8's first 6–8 weeks of operation.
  - **Post-restart re-warmup window**: after any Mahavishnu restart, treat the next 24 hours as re-warmup; do not act on drift detection signals during this window. CUSUM warmup state is per-process; a restart at hour 47 of a 72-hour slow drift will reset to baseline and likely miss the drift entirely.
  - The OTel span attribute `runbook_url` references this file's deployed URL (e.g., `https://docs.mahavishnu.internal/runbooks/mahavishnu-drift-detection.html` once published; pre-publish, the relative path `docs/runbooks/mahavishnu-drift-detection.md` is the contract)
- When `changepoint.reference_detector == "three_sigma"`, both detectors run in parallel; both log when they detect. When `"none"`, only the change-point detector runs
- This phase adds new observability signals; it does NOT replace anything (because there was nothing to replace — see §4.2)
- Single-metric gate: only `changepoint.target_metric` is monitored at a time. Multi-metric support is a follow-on (not in this plan)

#### Integration Contract — Phase 6 deliverable
- **Triggered from**: every observation the `MetricSampler` produces for `changepoint.target_metric`. Wired via the existing `mahavishnu get_observability_metrics` MCP tool's underlying `ObservabilityManager`. Configurable via `settings/mahavishnu.yaml`'s `changepoint:` block or `MAHAVISHNU_CHANGEPOINT__ENABLED` env var.
- **Returns to / updates**: new `mahavishnu.observability.metric_samples` Dhara table; OTel span `mahavishnu.observability.drift_detected`; Prometheus counter `mahavishnu.observability.drift_detected_total`; new Prometheus gauge `mahavishnu.observability.detector_age_samples_total` per `(metric_name, detector)` (R3-H2 renamed from `detector_age_samples` to make the cumulative semantic explicit).
- **Demonstrable by**: integration test `tests/integration/observability/test_changepoint_detection.py` injects a synthetic 0.5-σ mean shift and asserts the change-point detector fires within 30 samples median (≤ 100 samples p95) while the reference 3-sigma detector does not. Both detector results visible in OTel span and Prometheus metrics.
- **Rollback signal**: setting `MAHAVISHNU_CHANGEPOINT__ENABLED=false` (env) or `changepoint.enabled: false` (YAML) — both detectors go dormant; the sampler keeps populating the metric_samples table for future re-enablement. Setting `changepoint.reference_detector: none` disables only the 3-sigma fallback.
- **Observability added**: OTel span `mahavishnu.observability.drift_detected`; Prometheus counter + gauge listed above; new Dhara table.
- **Fulfils**: REQ-005, REQ-006, REQ-009.

### Phase 7: Change-point validation (documentation-only)

**Goal**: Quantify change-point detection improvement vs. the new
3-sigma reference detector on both synthetic and any available real
metric streams.

**Tasks**:
- Mark as `documentation-only` phase per `TEMPLATE.md:134`
- Generate 100 synthetic time series with planted change points at random locations and known shift sizes (0.25σ, 0.5σ, 1.0σ), using `numpy.random.Generator(PCG64)` for reproducibility
- Measure detection latency (median + p95) and false-alarm rate for CUSUM, Page-Hinkley, and the new 3-sigma reference on each
- Programmatic gate: `python -c "import json; d = json.load(open('bench.json')); assert d['cusum_p95_latency_at_0.5_sigma'] < 100; assert d['cusum_median_latency_at_0.5_sigma'] <= 30; assert d['cusum_arl0'] >= 10000; assert d['cusum_fp_per_10080_quiet_samples'] <= 2; assert d['three_sigma_miss_rate_at_0.5_sigma'] >= 0.95"` — the doc reports the same numbers but the gate is mechanical. The benchmark harness writes these custom keys to `bench.json` (pytest-benchmark's default JSON does not emit them; the integration test owns this output format).
  - `cusum_p95_latency_at_0.5_sigma`: 95th percentile detection latency in samples on 0.5-σ mean shift
  - `cusum_median_latency_at_0.5_sigma`: median detection latency in samples on 0.5-σ mean shift
  - `cusum_arl0`: average run length on stationary Gaussian (≥ 10,000 means ~10,080 quiet samples produce ~1 false positive on average; the §1 success criterion is "expected ≤ 1 FP per week" with the standard 1-min cadence assumed)
  - `cusum_fp_per_10080_quiet_samples`: 1-week FP assertion (10,080 samples = 1 week at 1-min cadence); gate threshold ≤ 2 per validation run (the statistical reality: with ARL₀ ≈ 10,000, expected FP count over 10,080 samples is ~1.008, so a strict `== 0` gate would fail ~63% of the time on a correctly-tuned detector)
  - `three_sigma_miss_rate_at_0.5_sigma`: fraction of 0.5-σ shifts the 3-sigma reference misses (≥ 0.95 confirms the reference is unsuitable for slow drift)
- Three-way comparison report (CUSUM vs Page-Hinkley vs 3-sigma)
- Add `docs/observability/changepoint_validation.md` with the report
- Add `docs/audits/2026-09-10-changepoint-validation.md` with the actual numbers
- Run `python scripts/audit_orphans.py`

#### Integration Contract — Phase 7 deliverable
- **Triggered from**: `pytest tests/integration/observability/test_changepoint_benchmark.py -v --benchmark-json=bench.json` runs the synthetic benchmark.
- **Returns to / updates**: `docs/observability/changepoint_validation.md` (explanatory) + `docs/audits/2026-09-10-changepoint-validation.md` (numbers); `bench.json` benchmark artifact.
- **Demonstrable by**: the report shows CUSUM and Page-Hinkley catch 0.5-σ shifts in median ≤ 30 samples (p95 ≤ 100) while the new 3-sigma reference misses the same shifts. Programmatic gate passes.
- **Rollback signal**: validation failure → Phase 8 promotion blocked.
- **Observability added**: validation report is the artifact. Runtime observability is unchanged.
- **Fulfils**: REQ-004, REQ-005, REQ-006, REQ-009 (verification).

### Phase 8: Promote change-point default

**Goal**: After Phase 7 validation passes, flip
`changepoint.enabled` default to `true` for the promoted metric.

**Tasks**:
- Update `settings/mahavishnu.yaml` default
- Update `CHANGELOG.md`
- Add `docs/feature-tracking/2026-09-10-observability-changepoint.md`
- Run `python scripts/audit_orphans.py` and `python scripts/audit_requirements.py --include-tests`
- **Staged rollout**: same mechanism as Phase 4. The feature-tracking entry's rollout playbook names (a) which environment is first, (b) what metrics gate progression (drift detection rate, false-positive rate from production quiet periods, OTel span emission rate), (c) what monitoring window applies per stage (≥ 7 days of stable metrics before next stage), (d) the per-environment opt-out template via `MAHAVISHNU_CHANGEPOINT__ENABLED=false` in `settings/local.yaml`. Single-day global default flip is explicitly forbidden — see §10 Risks row 1.

#### Integration Contract — Phase 8 deliverable
- **Triggered from**: config change in `settings/mahavishnu.yaml`; new default takes effect on next `mahavishnu mcp start`. Staged rollout controlled by deployment process / env vars.
- **Returns to / updates**: `settings/mahavishnu.yaml`, `CHANGELOG.md`, `docs/feature-tracking/`.
- **Demonstrable by**: starting Mahavishnu with default config and observing OTel span and Prometheus counter populated for the promoted metric.
- **Rollback signal**: env-var override per environment, or YAML revert.
- **Observability added**: feature-tracking entry links to validation report.
- **Fulfils**: REQ-005, REQ-006, REQ-009 (production enablement).

### Phase 9: Tier 2 and Phase D re-evaluation triggers

**Goal**: Codify the data-volume and validation triggers that decide
when Initiatives C (optimal transport), D (hyperbolic embeddings),
and Phase D (cross-repo Akosha wiring) move from deferred to active.

**Tasks**:
- Create `scripts/feature_eligibility.py` (NOT `mahavishnu/scripts/feature_eligibility.py` — all scripts live at the repo root) with the following contract:
  - **Triggers checked** (each from §4.7 plus one operational follow-on):
    - `optimal_transport`: fires when `akosha.patterns.cross_system_snapshot_count ≥ 10,000` over a 30-day window
    - `hyperbolic_embeddings`: fires when `session_buddy.code_graph.node_count ≥ 10,000` AND code-graph coverage ≥ 60% of indexed repos
    - `phase_d_cross_repo`: fires when this spec's Phase 8 is `adopted` AND ≥ 1 week of production operation with the drift signal useful to operators
    - `multi_metric_drift`: fires when ≥ 3 different metrics are requested by operators within a 30-day window (tracked via `mcp__mahavishnu__discover_tools` query log or a feature-request count). Phase 6's single-metric scope is the right v1 cut but operators will hit the wall within weeks of Phase 8 promotion; this trigger closes the gap before they ask for it.
  - **MCP endpoint sources** (these are the canonical names; the implementer must verify against the live MCP server during Phase 9 work):
    - Akosha: `mcp__akosha__akosha_get_system_metrics` (returns `akosha.patterns.cross_system_snapshot_count`); fallback `mcp__akosha__akosha_search_all_systems` if the dedicated metrics endpoint is unavailable.
    - Session-Buddy: `mcp__session-buddy__get_intelligence_stats` (returns `session_buddy.code_graph.node_count`); fallback `mcp__session-buddy__reflection_stats`.
    - Phase 8 promoted-status: read from `docs/feature-tracking/2026-09-10-observability-changepoint.md` frontmatter (`status: adopted`).
  - **Output format**: one line per trigger in the form `trigger_name: state=<state> threshold=<threshold> current=<current> fired=<bool>`. State is one of `below`, `above`, `unknown` (when MCP endpoint unreachable). Followed by a summary line `triggers_fired=<N> followon_plans_missing=<M>`.
  - **Exit codes**:
    - `0`: all triggers below threshold, OR a fired trigger has its corresponding `docs/followups/<trigger>.md` entry.
    - `1`: at least one trigger fired but the corresponding `docs/followups/<trigger>.md` entry does not exist or has status other than `active` / `in_progress`.
    - `2`: internal error (MCP endpoint unreachable, malformed response, file system error reading feature-tracking frontmatter).
  - **CLI flags**: `--json` for machine-readable output (one JSON object with `triggers: [...]` and `summary: {...}`); `--dry-run` to skip exit code (always exit 0).
- Wire into CI: `make tier2-eligibility` target that runs the script on a monthly schedule and fails the build if any trigger fires without a follow-on plan
- Add `docs/followups/2026-09-10-tier2-optimal-transport.md`, `docs/followups/2026-09-10-tier2-hyperbolic-embeddings.md`, `docs/followups/2026-09-10-tier2-phase-d-cross-repo.md` per `.claude/decisions/followups-lifecycle.md`
- Add `docs/feature-tracking/2026-09-10-tier2-math-deferred.md` tracking all three in `deferred` state
- Update `docs/plans/PLAN_INDEX.md` for this spec's row to `status: partial` until all required phases land

#### Integration Contract — Phase 9 deliverable
- **Triggered from**: `python scripts/feature_eligibility.py` (manual or CI); the monthly CI run via the `make tier2-eligibility` target.
- **Returns to / updates**: stdout (status report); exit code 0/1 (CI signal); updates the three followups entries when state changes.
- **Demonstrable by**: running the script prints current trigger status with one-line per trigger (state vs. threshold).
- **Rollback signal**: N/A — read-only script + documentation. Phase 9 lead-in explicitly states "documentation-only + read-only script; no production wiring" per `TEMPLATE.md:134`.
- **Observability added**: the eligibility script output and CI exit code are the artifacts. Monthly CI run is the recurring observability signal.
- **Fulfils**: REQ-007.

### Phase ordering

| Phase | Initiative | Depends on | Approx effort |
|---|---|---|---|
| 1 | Queueing library | — | 2 days |
| 2 | Pool routing integration | 1 | 2 days (incl. arrival-timestamp instrumentation) |
| 3 | Queueing validation (docs) | 2 | 1 day |
| 4 | Promote queueing default | 3 (validation pass) | 0.5 day |
| 5 | Change-point library | — | 2 days |
| 6 | Change-point observability integration | 5 | 2 days (incl. new sampler) |
| 7 | Change-point validation (docs) | 6 | 1 day |
| 8 | Promote change-point default | 7 (validation pass) | 0.5 day |
| 9 | Re-evaluation triggers | — (parallel) | 0.5 day |

Phases 1 and 5 are independent — parallel by two engineers. Phases
2 and 6 are independent after their respective libraries land. Phase
9 runs alongside everything. Total wall-clock for parallel
execution: ~9 days. Sequential: ~12 days.

## 7. Cross-repo follow-on stub (out of scope, named so it isn't forgotten)

This stub is not a phase. It exists to prevent the most likely
failure mode for a future cross-repo plan: someone re-reading this
spec in six months and proposing "let's replace Akosha's 3-sigma
baseline" without realizing Akosha already has `pytrendy` in the
same conceptual slot.

**Reconnaissance facts** (verified by the v1 review):

1. Akosha's algorithm landscape today:
   - `akosha_detect_anomalies` — Z-score pointwise, sliding window over `akosha.processing.analytics._metrics_cache`. Live.
   - `akosha_analyze_changepoints` — segmented regression via `pytrendy`. Source exists; runtime gated behind `ChangePointAnalytics(dhara=...)` at MCP-server startup. Not live today.
   - CUSUM/PH (this plan) — to be built; Mahavishnu-local first.

2. Z-score, pytrendy, and CUSUM/PH are three orthogonal detectors
   answering different questions:
   - Z-score: which points look weird vs. window mean?
   - pytrendy: where are the regime boundaries (batch retrospective)?
   - CUSUM/PH: has the process mean drifted (online sequential)?
   The right Akosha-side composition is "all three, each tuned to
   its own question," not "CUSUM/PH replaces Z-score."

3. The lowest-cost, cleanest-dependency-direction mechanism for
   cross-repo integration when it happens: extend
   `mahavishnu/pools/fitness_analyzer.py:279`'s hard-coded
   `task_classes` list to include `"routing_change_point"`, plus
   write `HotRecord` objects with the right metadata when the
   detector fires. <100 LOC. Reuses the battle-tested
   Redis-stream-based pipeline (`bodai:events`, queue cap 1000
   via `_MAX_BUFFER_SIZE` at `fitness_analyzer.py:31`, circuit
   breaker, DLQ after 3 consecutive write failures). Akosha
   consumes via the existing `query_local_traces` polling path —
   no new transport. The `HotRecord` model is imported FROM
   `akosha.models` (at `mahavishnu/ingesters/otel_ingester.py:758`)
   rather than constructed in Mahavishnu; this cross-repo import
   is the right path for the eventual Phase D work.

4. Three integration modes were evaluated for the eventual
   cross-repo work:
   - **In-process library import**: viable but adds release
     coordination cost; Akosha inherits Mahavishnu's crackerjack gate
     transitively.
   - **Mahavishnu exposes an MCP service**: rejected — inverts the
     seer/orchestrator dependency direction (Akosha is the
     intelligence source, not a consumer of Mahavishnu services);
     5–50ms MCP round-trip is hot-path-expensive; couples Akosha's
     uptime to Mahavishnu's.
   - **Akosha adds CUSUM/PH natively alongside pytrendy**: cleanest
     ownership boundary. Akosha owns its analytics math. Drift over
     time is mitigated by reusing Tier 1's
     `test_changepoint_benchmark.py` as the Akosha conformance
     suite.

**Gating criteria for picking the cross-repo mode**:
- Tier 1 Phase 7 three-way validation passes (CUSUM vs Z-score vs
  pytrendy on synthetic series)
- Tier 1 Phase 8 promoted AND ≥ 1 week production operation with
  the drift signal useful to operators
- Phase 9's data-volume trigger for at least one Tier 2 initiative
  has fired (proves the spec machinery actually surfaces deferred
  work)

**When the cross-repo plan lands**, it should:
- Open as a new plan in `docs/plans/YYYY-MM-DD-bodai-akosha-cross-repo-changepoint.md`
- Reference this §7 stub for context
- Update the three `docs/followups/` entries from Phase 9

## 8. Required Code Changes

### New files

```
Makefile                                            # tier2-eligibility target (CI monthly check)

mahavishnu/
  pools/queueing/
    __init__.py
    mmc.py
    scorer.py
  observability/
    changepoint/
      __init__.py
      cusum.py
      page_hinkley.py
      anomaly.py                                    # AnomalyResult dataclass for 3-sigma reference
    sampler.py

scripts/
  feature_eligibility.py

docs/
  pools/queueing_routing.md
  observability/changepoint_validation.md
  runbooks/mahavishnu-drift-detection.md           # Phase 6 OTel runbook_url target
  audits/2026-09-10-queueing-validation.md
  audits/2026-09-10-changepoint-validation.md
  audits/2026-09-10-math-spec-review.md
  audits/2026-09-10-math-spec-verification.md      # v2→v3 verification findings
  plans/2026-09-10-bodai-math-initiatives-tier1-validation.md (if needed)
  followups/2026-09-10-tier2-optimal-transport.md
  followups/2026-09-10-tier2-hyperbolic-embeddings.md
  followups/2026-09-10-tier2-phase-d-cross-repo.md
  feature-tracking/2026-09-10-pool-queueing-routing.md
  feature-tracking/2026-09-10-observability-changepoint.md
  feature-tracking/2026-09-10-tier2-math-deferred.md

tests/
  unit/
    pools/test_queueing.py
    observability/test_changepoint.py
  integration/
    pools/test_queueing_routing.py
    observability/test_changepoint_detection.py
    observability/test_changepoint_benchmark.py
```

### Modified files

```
settings/
  mahavishnu.yaml                                     # +queueing: block, +changepoint: block
mahavishnu/
  core/config.py                                       # +QueueingConfig, +ChangepointConfig Pydantic models
  core/observability.py                                # +ObservabilityManager._evaluate_change_point, +_evaluate_3sigma
  core/routing_metrics.py                              # +mahavishnu.pool.queueing_prediction_error histogram, extend routing counter labels (predicated on §5 ALLOWED_LABEL_KEYS check)
  pools/manager.py                                     # arrival-timestamp recording, QueueingScorer integration, routing-decision record extension
  pools/base.py                                        # PoolMetrics extended with wait_time_estimate and queueing_model fields
  pools/mahavishnu_pool.py                             # _task_durations becomes bounded deque(maxlen=N)
  observability/metrics.py                             # add new labels to _ALLOWED_LABEL_KEYS frozenset at line 74 (Phase 2 prerequisite)
CHANGELOG.md                                           # document Phase 4 and Phase 8 promotions
```

## 9. Validation Matrix

| Check | Command | Expected outcome |
|---|---|---|
| Queueing math correctness | `pytest tests/unit/pools/test_queueing.py -v` | All reference-value and Hypothesis property tests pass |
| Queueing integration | `pytest tests/integration/pools/test_queueing_routing.py -v --benchmark-json=bench.json` | Median error < 25%, p95 < 25% on synthetic Poisson; p95 < 50% on synthetic bursty |
| Queueing programmatic gate | `python -c "import json; d = json.load(open('bench.json')); assert d['p95_error_poisson'] < 0.25; assert d['p95_error_bursty'] < 0.50; assert d['median_error_poisson'] < 0.25"` | Exits 0 |
| Change-point math correctness | `pytest tests/unit/observability/test_changepoint.py -v` | ARL₀ ≥ 10,000 property test passes; planted-shift benchmarks within latency bounds |
| Change-point integration | `pytest tests/integration/observability/test_changepoint_detection.py -v` | CUSUM detects 0.5-σ shift in ≤ 30 samples median; 3-sigma does not |
| Change-point programmatic gate (single CUSUM) | `python -c "import json; d = json.load(open('bench.json')); assert d['cusum_median_latency_at_0_5_sigma'] <= 60; assert d['cusum_arl0'] >= 7000; assert d['cusum_fp_per_10080_quiet_samples'] <= 2"` | Exits 0 |
| Change-point programmatic gate (two-stage) | `python -c "import json; d = json.load(open('bench.json')); assert d['two_stage_warning_latency_at_0_5_sigma'] <= 30; assert d['two_stage_confirmed_alert_fp_per_10080_quiet_samples'] <= 2"` | Exits 0 (both §1 and §7 gates achievable simultaneously) |
| Tier 2 / Phase D eligibility | `python scripts/feature_eligibility.py` | Prints current trigger status (one line per trigger); exits 1 if any trigger fires without follow-on |
| CI monthly check | `make tier2-eligibility` (top-level Makefile, new in Phase 9) | Runs the script on a monthly schedule; fails the build if triggers fire without plans |
| Orphan detection | `python scripts/audit_orphans.py` | Zero orphan warnings for new modules |
| Requirement audit | `python scripts/audit_requirements.py --include-tests` | Every REQ-001..REQ-009 has a code or test marker; this gate reads the YAML frontmatter `requirements:` block, which must contain all 9 IDs |
| Type + lint | `crackerjack run -p minor` | Passes |
| Test coverage | `pytest --cov=mahavishnu.pools.queueing --cov=mahavishnu.observability.changepoint` | ≥ 89% line coverage (project gate) |

Note: `bench.json` keys (`p95_error_poisson`, `cusum_arl0`, `cusum_fp_per_10080_quiet_samples`, etc.) are custom-written by the integration tests' benchmark harness, NOT pytest-benchmark's default JSON format. The integration test fixture owns this output contract.

## 10. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Production traffic doesn't match Poisson — M/M/c predictions drift > 50% on real data | Medium | Phase 3 validation per-shift-size decomposition surfaces this. **Phase 4 staged rollout is a required task** (not a recommendation): per-environment opt-out via env var or `settings/local.yaml`, 1 environment first → all environments, with ≥ 7 days monitoring between stages. The feature-tracking entry's rollout playbook names the gating metrics. |
| M/M/c Kingman approximation disagrees measurably from Erlang-C at small `c` | Low | `approximation="erlang_c"` knob available from Phase 1; integration uses Kingman by default; switch in Phase 2 if validation surfaces a meaningful gap. |
| Existing `PoolConfig` consumers break when `queueing_enabled` field is added | Low | Field has default `False`; behavior preserved for all current callers. Audit before Phase 2 begins. |
| Per-pool arrival timestamps missing — Phase 2 instrumentation incomplete | Medium | Explicit deliverable in Phase 2; `scripts/feature_eligibility.py` includes a check that arrival timestamps are being recorded before Phase 4 promotion. |
| `MetricSampler` performance — fixed-cadence sampler consumes too much CPU when extended to many metrics | Low | Default cadence 60s; sampling is O(1) per metric per tick; configurable per-metric. |
| CUSUM warmup state lost on Mahavishnu restart | Medium | Document as known limitation in §6 Phase 6; per-process detector state is sufficient for fast-drift detection. Slow-drift detection (multi-day) requires persistent state, which is a follow-on. |
| New `mahavishnu.observability.metric_samples` Dhara table grows unbounded | Low | Same retention pattern as `fitness_analyzer` (TTL=7200s default); configurable per deployment. |
| Operator confusion during Phase 4/8 promotion — sudden default flip across all environments | Medium | Staged rollout: per-environment opt-out defaults in `settings/local.yaml`; rollout playbook in `docs/feature-tracking/`. Validation gates (Phase 3, Phase 7) are mechanical, not reading-check. |
| Tier 2 triggers never fire — eligibility script never runs | Low | Wired into monthly CI; CI failure is the recurring signal. |
| Cross-repo follow-on never drafted | Medium | §7 stub + Phase 9 followups entries + monthly CI gate. Documented in this spec so the next plan author has context. |
| `audit_requirements.py` script doesn't actually validate as v1 assumed | Low | Verify the script's logic on Phase 1 completion; if mismatched, fix the script (not the spec). |
| Detached OTel span attributes (`current_value`, `baseline_mean`, etc.) — too many log fields dilute signal | Low | Phase 7 validation includes an operator-usability review of the structured log line. Adjustments to field set are within Phase 7's scope. |
| 3-sigma detector is implemented but unused — every change-point detection also fires 3-sigma, doubling alert volume | Low | Phase 6's contract explicitly runs both in parallel only when `changepoint.reference_detector == "three_sigma"`; setting `"none"` disables the fallback. Operators can tune. |

## 11. Decision Rule

This plan is "done enough" when:

1. Phases 1–8 land with the documented validation criteria met:
   queueing median error < 25% and p95 error < 25% on synthetic Poisson
   workload; p95 error < 50% on synthetic bursty/hyperexponential workload;
   change-point ARL₀ ≥ 10,000 with expected ≤ 1 false positive per week of
   synthetic quiet operation (10,080 samples at 1-min cadence) and
   ≤ 2 observed false positives in any single validation run.
2. Phase 9's `scripts/feature_eligibility.py` runs cleanly and is
   wired into monthly CI.
3. The §7 cross-repo follow-on stub references real Akosha code
   paths and the right integration mechanism.
4. Every feature is at `adopted` state in feature-tracking
   (queueing, changepoint) or `deferred` state (tier 2, phase D).
5. `audit_requirements.py --include-tests` confirms every REQ-001..REQ-009
   is referenced by code or tests.
6. `audit_orphans.py` reports zero orphans for the new modules.

If any of these is false at scope-cut time, the plan ships partial
and the missing phase is documented in `docs/plans/PLAN_INDEX.md` as
`status: partial`. We do not silently cut phases.

## 12. Open Questions for Reviewers

1. **Should Phases 1–4 and 5–8 land in two separate PR chains or
   one?** My recommendation is two — different review audiences
   (pool routing vs. observability), different test concerns.
2. **Should the queueing model be opt-in (Phase 2's
   `pools.queueing.enabled`) or opt-out (default true after Phase 4)?**
   My recommendation is opt-in then opt-out via Phase 4, gated on
   Phase 3 validation pass with staged rollout. Reviewers with
   stronger opinions on rollout velocity can push for opt-out from
   day one.
3. **Which metric should Phase 6 promote?** ✅ **RESOLVED in v3**.
   Default in `settings/mahavishnu.yaml` is now `pool_queue_depth`
   (was `workflow_duration_p99` in v2; v3 aligns the default with
   this open question's recommendation). Phase 6's per-pool
   instrumentation reuses Phase 2's arrival-timestamp path, so
   `pool_queue_depth` is the lowest-cost, highest-fidelity option
   for the first promoted metric. Reviewers may still propose
   workflow duration p99 or error rate per adapter as a follow-on
   single-metric switch (Phase 6 is single-metric by design per the
   contract).
4. **Should `scripts/feature_eligibility.py` be wired into CI as a
   monthly check, or run more frequently?** My recommendation is
   monthly with a make target; weekly if reviewers want tighter
   cadence.
5. **Should `scripts/audit_orphans.py` run after every phase, or only
   at promotion?** My recommendation is every phase per
   `.claude/decisions/wire-up-contract.md`; v1 only ran it at
   promotion.
6. **Should the `mahavishnu.observability.metric_samples` Dhara table
   also be exposed via a new `metrics:*` WebSocket channel?** My
   recommendation is **start with Dhara only**; add the WebSocket
   channel if low-latency consumers emerge. Reduces surface area for
   Phase 6.
7. **Should the `mahavishnu.observability.metric_samples` table live in
   Mahavishnu's own storage or Dhara?** My recommendation is Dhara
   per the existing pattern (`fitness_analyzer` writes there). Mahavishnu-local
   storage would split observability data across two stores.

---

## 13. References

- `docs/plans/TEMPLATE.md` — the integration-contract-required template
  this plan follows.
- `docs/superpowers/specs/2026-09-09-jot-read-design.md` — recent
  example of a spec-style document in this repo.
- `.claude/decisions/wire-up-contract.md` — the policy that drives
  the Integration Contract requirement.
- `.claude/decisions/followups-lifecycle.md` — the policy Phase 9
  follows for `docs/followups/` entries.
- `.claude/decisions/mcp-backend-wiring-discipline.md` — referenced
  for audit cadence.
- `.claude/decisions/bodai-observability-pattern.md` — referenced for
  cross-component drift detection patterns.
- `docs/feature-tracking/TEMPLATE.md` — feature-state template.
- `settings/mahavishnu.yaml` — current pool and observability settings.
- `mahavishnu/pools/manager.py` — current pool routing implementation
  with `PoolSelector` enum and the four pre-existing routing hooks
  (`_enforce_caller_quota`, `_apply_fitness_aware_routing`,
  `_apply_gpu_category_override`, `_persist_routing_decision`).
- `mahavishnu/pools/base.py` — `PoolConfig` (Pydantic, `extra: forbid`)
  and `PoolMetrics` (the runtime metrics dataclass — NOT a
  `PoolState` class).
- `mahavishnu/pools/mahavishnu_pool.py` — `_task_durations` raw signal
  (becomes bounded deque in Phase 2).
- `mahavishnu/pools/fitness_analyzer.py` — the polling pipeline Phase 6
  and Phase D follow-on depend on.
- `mahavishnu/observability/metrics.py` — worktree-only; NOT a target
  for Phase 6.
- `mahavishnu/core/observability.py` — `ObservabilityManager`,
  `get_performance_metrics` — the target Phase 6 wires into.
- `mahavishnu/core/config.py` — `PoolConfig` (Pydantic) and the flat
  config schema with `extra: forbid` requiring new fields to be
  declared on the model.
- `mahavishnu/core/errors.py` — custom exception hierarchy; Phase 1
  adds `QueueingModelError`.
- `mahavishnu/ingesters/otel_ingester.py:758` — `HotRecord` is
  imported FROM `akosha.models` here, not constructed in Mahavishnu.
  Phase D follow-on uses the same import path.
- `mahavishnu/mcp/bodai_component_client.py` — cross-repo MCP client
  pattern (used by `fitness_analyzer`, not directly by this plan).
- Akosha (separate repo): `akosha.processing.analytics._metrics_cache`,
  `akosha_detect_anomalies` (Z-score), `akosha_analyze_changepoints`
  (pytrendy).
- Kingman, G. F. C. (1961). The single server queue in heavy traffic.
  *Proc. Cambridge Philos. Soc.* 57, 902–904.
- Page, E. S. (1954). Continuous inspection schemes. *Biometrika* 41(1/2), 141–154.

## 14. Review Appendix (9-agent multi-perspective review)

This plan was reviewed by 9 agents dispatched in parallel. Each agent
focused on a distinct domain; convergence and divergence across agents
drove the v1→v2 changes summarized in the v2 changelog at the top of
this document.

| # | Agent | Domain | Key finding |
|---|---|---|---|
| 1 | mahavishnu-specialist | Mahavishnu integration | 15 specific code/path/config inaccuracies; Phase B2 wiring target was wrong |
| 2 | akosha-specialist | Akosha integration feasibility | Akosha already has pytrendy-backed changepoint; "replace 3-sigma" framing was wrong |
| 3 | mcp-integration-expert | Cross-repo transport mechanism | Extend `fitness_analyzer.py` task_classes list, <100 LOC, low cost |
| 4 | feature-dev:code-architect | Spec architecture | §5.4.5 broken reference; REQ-006 misattributed; programmatic gates needed |
| 5 | mycelium-core:python-pro | Python implementation | Math: Kingman vs M/M/c naming; ARL₀ inconsistency; 15 project-convention violations |
| 6 | architecture-council | Bodai architectural fit | Second-control-plane concern; requirements YAML must be in frontmatter; Phase C integration contract is weak |
| 7 | pytest-hypothesis-specialist | Test strategy | Strong yes on Hypothesis; 14 missing test scenarios; validation needs p95 + quarterly re-validation |
| 8 | observability-incident-lead | Operator incident perspective | Log fields lack operator context; cardinality risk on routing logs; cross-repo matters for operators |
| 9 | mycelium-core:data-pipeline-engineer | Data flow | No per-pool arrival timestamps; no continuous sample stream; Phase B2 wiring target wrong (worktree-only file) |

**Convergent findings** (3+ agents agree): applied to v2.

**Divergent findings**: 3 agents argued FOR including cross-repo in
Tier 1; 3 agents argued AGAINST. The against side had ground-truth
access (akosha: live system access; mahavishnu: codebase grep; data-pipeline:
codebase grep); the for side had sound abstract reasoning on
incomplete premises. The against side's recommendation — defer cross-repo,
add a §7 stub with the right mechanism — won.

**Full review report**: `docs/audits/2026-09-10-math-spec-review.md`
(preserves all 9 agents' full text for future reference).
