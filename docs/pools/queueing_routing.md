# Mahavishnu Queueing-Theoretic Routing

**Owner:** bodai-orchestrator
**Created:** 2026-09-10
**Last updated:** 2026-09-10
**Spec:** [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md` §1-§3](../plans/2026-09-10-bodai-math-initiatives-tier1.md)
**Library:** `mahavishnu.pools.queueing` (Tier 1 Phase 1)
**Integration:** `mahavishnu.pools.queueing.scorer` (Tier 1 Phase 2)

## What this is

When `pools.queueing.enabled: true`, the Mahavishnu router consults
an M/M/c queueing model for expected wait time per candidate pool
and uses the prediction as an *additive* penalty on the existing
`PoolSelector` strategy. The math does NOT replace the inner
selector; it composes with it. All five `PoolSelector` values
(`ROUND_ROBIN`, `LEAST_LOADED`, `RANDOM`, `AFFINITY`,
`PEER_AFFINITY`) keep working unchanged.

## The math

The library exposes :class:`~mahavishnu.pools.queueing.mmc.MmcQueue`
— a stateless M/M/c queueing model. It fits from observed
inter-arrival and service times and produces expected-wait-time
estimates using one of two formulas:

* **`kingman`** (default) — Kingman's heavy-traffic approximation.
  For M/M/c with Poisson arrivals and exponential service, this
  simplifies to `W_q ≈ (ρ / (1 − ρ)) · (1 / μ)`. Tight in heavy
  traffic; O(1); the router's hot path uses this.
* **`erlang_c`** — the exact M/M/c Erlang-C formula. Tight for
  small `c` (single-worker pools); preferred for safety-critical
  workloads where the Kingman over-estimate is too coarse.

Both require `ρ < 1`. The router-friendly entry
`safe_expected_wait_time(utilization_cap=0.95)` returns
`math.inf` past the cap, so the router treats the pool as a
"do not route here" candidate.

## What the validation says

The Phase 3 integration test (`tests/integration/pools/test_queueing_routing.py`)
validates against the §1 success criteria:

* Poisson workload: median error on conditional-on-wait tasks < 25%.
* Bursty workload: documented (p95 of relative error can be looser
  at high burstiness; the router's pool-fit estimator remains
  meaningful but the per-task relative error is sensitive to which
  tasks waited).
* Hyperexponential service: documented; M/M/c is a worse fit at
  high CV²; the validation report
  (`docs/audits/2026-09-10-queueing-validation.md`) tabulates the
  per-shift-size error budget.

## How to interpret the prediction

`expected_wait_time()` returns `W_q` — the *expected time in queue*
(before service starts). Total time in system is `W_q + 1/μ`. The
router uses `W_q` because the routing decision is "how long will
this task wait before being served?" not "how long until
completion?".

## Composition with existing routing hooks

Per the spec, the `QueueingScorer` runs between
`_apply_fitness_aware_routing` (Dhara fitness override) and
`_apply_gpu_category_override` (runpod swap for vision/ml/embedding).
The `effective_selector` field in the routing-decision record
captures what the routing layer actually chose, distinguishing
`round_robin` (raw) from `round_robin+queueing` (composed).

## Opt-in / opt-out

```yaml
# settings/mahavishnu.yaml
pools:
  queueing_enabled: false  # default in Phase 2; Phase 4 flips to true
  queueing_warmup_min_observations: 100
  queueing_warmup_min_seconds: 600.0
```

```bash
# Env var override (Oneiric double-underscore convention)
MAHAVISHNU_POOLS__QUEUEING_ENABLED=false
```

## Observability

The new signal is observable via:

* `mahavishnu.pool.routing_decision` OTel span (predicted_wait_s,
  observed_wait_s, effective_selector).
* `mahavishnu_routing_decisions_total` Prometheus counter
  (extended with `predicted_wait_bucket` and `effective_selector`
  labels; both labels added to `_ALLOWED_LABEL_KEYS` in
  `mahavishnu/observability/metrics.py`).
* `mahavishnu.pool.queueing_prediction_error` Prometheus histogram.
* `mahavishnu.pool.queueing_warmup_pending` debug log line (one
  per `route_task` invocation while the buffer is in warmup).
* The Dhara `routing_decision` record extended with
  `predicted_wait_s`, `observed_wait_s`, `effective_selector`.

## Limitations

* M/M/c assumes exponential service. Real Mahavishnu traffic is
  closer to bursty/hyperexponential; the Kingman formula degrades
  gracefully (its error scales with `(CV_a² + CV_s²)/2`), but
  operators should expect a 50-100% error budget on bursty
  workloads.
* The fit is per-pool. Operators wanting global optimization need
  a different formulation.
* Slow drifts in service time are invisible to the queueing
  model (which assumes the in-control mean is fixed). Cross-pool
  drift detection is the change-point detector's job (Phase 6).

## References

* Tier 1 plan §1-§3, §6 Phase 1, §6 Phase 2: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md)
* Validation report: [`docs/audits/2026-09-10-queueing-validation.md`](../audits/2026-09-10-queueing-validation.md)
* Feature tracking: [`docs/feature-tracking/2026-09-10-pool-queueing-routing.md`](../feature-tracking/) (added in Phase 4)
* Library code: `mahavishnu/pools/queueing/`
* Integration test: `tests/integration/pools/test_queueing_routing.py`
* Unit tests: `tests/unit/pools/test_queueing.py`, `tests/unit/pools/test_queueing_scorer.py`
