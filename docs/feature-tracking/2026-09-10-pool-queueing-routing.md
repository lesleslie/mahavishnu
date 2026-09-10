---
name: pool-queueing-routing
status: adopted
date: 2026-09-10
last_reviewed: 2026-09-10
owner: bodai-orchestrator
role: canonical
---

# Feature: pool-queueing-routing

**Owner:** bodai-orchestrator
**Created:** 2026-09-10
**Last updated:** 2026-09-10
**Repo(s):** `/Users/les/Projects/mahavishnu`

## State — pick one

- [x] **adopted** (in active use by ≥1 user/workflow/agent)

Default `queueing_enabled: true` after Phase 3 validation passed
on 2026-09-10. Phase 4 staged rollout playbook is in the
"Staged rollout" section below.

## Wiring checklist

- [x] Entry point registered (McpConfig + PoolConfig fields)
- [x] Trigger path identified: `PoolManager.route_task` composes the
      QueueingScorer between the fitness override and the GPU
      category override
- [x] Returns / state updates land in expected destination:
      `_dhara_state.persist_routing_decision` extended with
      `predicted_wait_s` and `effective_selector`
- [x] End-to-end smoke check documented: `pytest tests/integration/pools/test_queueing_routing.py`
- [x] Observability hook in place: OTel span
      `mahavishnu.pool.routing_decision`, Prometheus counter
      `mahavishnu_routing_decisions_total` (extended labels), new
      histogram `mahavishnu.pool.queueing_prediction_error`,
      debug log `mahavishnu.pool.queueing_warmup_pending`
- [x] Rollback signal defined: env-var
      `MAHAVISHNU_POOLS__QUEUEING_ENABLED=false` reverts to
      pre-Phase-2 behavior

## Built (yes/no)

yes (Phase 1 + Phase 2 commits; the MmcQueue library and the
QueueingScorer wrapper are merged).

## Wired (yes/no)

yes (Phase 2 commit; the scorer is invoked from
`PoolManager.route_task` and the per-pool observation buffer is
populated on every `route_task` call).

## Trigger path

* Entry point: `PoolManager.route_task` (`mahavishnu/pools/manager.py:558`)
* Composition order: `_apply_fitness_aware_routing` →
  **`QueueingScorer.score`** → `_apply_gpu_category_override` →
  `_persist_routing_decision` (with `predicted_wait_s` +
  `effective_selector`)
* Warmup: when `arrival_rate == 0` or
  `len(buffer.arrivals) < min_observations`, the scorer logs
  one `mahavishnu.pool.queueing_warmup_pending` debug line per
  call and returns the inner selector's score unchanged.

## Integration point

* Dhara `routing_decision` record (extended with
  `predicted_wait_s`, `observed_wait_s`, `effective_selector`)
* Prometheus counter `mahavishnu_routing_decisions_total`
  (extended with `predicted_wait_bucket`, `effective_selector`)
* Prometheus histogram `mahavishnu.pool.queueing_prediction_error`
* OTel span `mahavishnu.pool.routing_decision`

## End-to-end check

```bash
# 1. Unit + integration tests
uv run pytest tests/unit/pools/test_queueing.py \
              tests/unit/pools/test_queueing_scorer.py \
              tests/integration/pools/test_queueing_routing.py \
              --no-cov
# Expected: 84 passed

# 2. Local smoke (single routing call)
uv run python -c "
from mahavishnu.pools.queueing import MmcQueue
q = MmcQueue(arrival_rate=0.5, service_rate=1.0, num_workers=2)
print(f'rho={q.utilization:.3f} W_q={q.expected_wait_time():.3f}s')
"
# Expected: rho=0.250 W_q=0.333s

# 3. Per-environment opt-out
MAHAVISHNU_POOLS__QUEUEING_ENABLED=false mahavishnu mcp start
# Expected: scorer is a pass-through, no OTel span emitted
```

## Staged rollout playbook (Phase 4)

| Stage | Environment | Window | Gating metrics |
|-------|-------------|--------|----------------|
| 1 (first) | dev (your-machine or first staging) | ≥ 7 days | median predicted-vs-observed wait-time error, p95 prediction error from the integration test, sampled daily |
| 2 | staging-2 | ≥ 7 days | same |
| 3 | production-canary | ≥ 7 days | same, plus p99 latency (must not regress) |
| 4 | all production | — | continuous |

### Per-stage gating (all must hold to advance)

* Median predicted-vs-observed wait-time error stays < 25% (the
  spec's §1 success criterion for Poisson workloads).
* p95 prediction error stays < 50% (the spec's §1 success
  criterion for bursty/hyperexponential workloads).
* Routing latency does NOT regress by more than 1ms p99
  (the QueueingScorer is O(1) per pool candidate; the budget
  catches any future regression in the buffer refit).
* No errors from `mahavishnu.pool.queueing_warmup_pending` or
  `mahavishnu.pool.routing_decision` span.

### Per-environment opt-out template

Add to `settings/local.yaml`:

```yaml
pools:
  queueing_enabled: false
```

Or set the env var on the deployment target:

```bash
export MAHAVISHNU_POOLS__QUEUEING_ENABLED=false
```

The env-var path takes precedence over the YAML path (Oneiric
precedence rules).

## Blocker

None — the feature is adopted. Phase 9's eligibility script
(`scripts/feature_eligibility.py`) does not include queueing in
its triggers (the queueing feature is fully shipped, not a
re-evaluation trigger). The Tier 2 follow-ons (optimal transport,
hyperbolic embeddings, multi-metric drift) are tracked under
`docs/feature-tracking/2026-09-10-tier2-math-deferred.md`.

## Next action

1. Apply the staged rollout playbook to dev → staging-2 → canary
   → production. Document each environment's opt-out (if any) in
   the team's deployment runbook.
2. Monitor the gating metrics for 7 days per stage; do not
   advance to the next stage until the metrics hold.
3. After full production rollout, add a one-line note in
   `CHANGELOG.md` with the date and the rollout result.

## Related

* Plan: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) §6 Phase 4
* Library: `mahavishnu/pools/queueing/`
* Integration: `mahavishnu/pools/queueing/scorer.py`
* Validation: [`docs/audits/2026-09-10-queueing-validation.md`](../audits/2026-09-10-queueing-validation.md)
* Library docs: [`docs/pools/queueing_routing.md`](../pools/queueing_routing.md)

## Session-Buddy

- Reflection ID: (saved at Tier 1 promotion)
- Saved at: 2026-09-10
