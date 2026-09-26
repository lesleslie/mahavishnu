# SLO: Pool Dispatch (C-6 + C-8 + C-9)

## Service

`mahavishnu.pool_route_execute` — the central dispatch path for LLM work. Covers:
- **C-6**: idempotency layer (PENDING → COMPLETED transitions, fail-CLOSED default)
- **C-8**: worktree isolation (per-task worktree lifecycle)
- **C-9**: per-TaskCategory concurrency limits

## SLI (Service Level Indicator)

### Latency SLI

`pool_route_execute_duration_seconds` histogram (auto-bucketed: 0.001 to 2.5s):

- **p50 < 1s**: dispatch returns immediately (no worktree, no idempotency)
- **p99 < 30s**: dispatch with full worktree setup + LLM call
- **p99.9 < 60s**: tail latency for slow LLM providers

### Availability SLI

`pool_route_execute_total{result="success"} / pool_route_execute_total`

- **Success rate >99.5% over 30-day rolling window**
- `result="error"` rate <0.05/s sustained
- `result="duplicate"` rate (idempotency hits) < 5% of total

### Correctness SLI

`task_domain_concurrency_drift_total` counter must be 0 in single-worker deployments.

- **Drift = 0**: gate's internal counter matches the observable acquire/release count
- **Drift > 0**: per-process gate is being violated (likely under contention; investigate)

## SLO Targets

| Metric | Target | Burn-rate alert |
|---|---|---|
| `pool_route_execute_duration_seconds{p99}` | <30s | >30s for 5m → page |
| `pool_route_execute_total{result="error"}` rate | <0.05/s sustained | >0.05/s for 5m → warn; >0.1/s for 5m → page |
| `task_domain_concurrency_drift_total` rate | 0 in single-worker | >0.01/s → page |
| `idempotency_hit_total` / `idempotency_miss_total` | <5% hits | >10% for 30m → warn (callers are hammering) |

## Error Budget

- **30-day budget**: 0.5% × 30 days = 3.6 hours of error rate allowed
- **Burn-rate policy** (multi-window):
  - 1h burn rate >14.4× (consuming 1% of monthly budget in 1h) → page
  - 6h burn rate >6× (consuming 1% in 6h) → page
  - 24h burn rate >3× → ticket
  - 72h burn rate >1× → ticket

## Page-after field

- **Initial response**: 5 minutes
- **Update frequency**: every 15 minutes until resolved
- **Resolution target**: 30 minutes for P0; 4 hours for P1

## Critical alerts (round-4 ops gap-fix)

The following alerts MUST fire to PagerDuty / Slack:

1. **`pool_route_execute_total{result="error"} rate > 0.05/s for 5m`** → Slack + page on-call
2. **`task_domain_concurrency_drift_total rate > 0.01/s for 5m`** → Slack + page on-call
3. **`worktree_disk_bytes > 80% of disk quota`** → Slack
4. **`markdown_board_watcher_up == 0 for 2m`** → Slack + page on-call
5. **`eventbridge_publish_total{result="error"} rate > 0.1/s for 5m`** → Slack + page on-call

## Runbooks

- [docs/runbooks/worktree-isolation.md](../runbooks/worktree-isolation.md) — worktree-isolation scenarios
- [docs/runbooks/concurrency-limit-storm.md](../runbooks/concurrency-limit-storm.md) — concurrency-limit scenarios
- [docs/runbooks/markdown-watcher.md](../runbooks/markdown-watcher.md) — markdown-watcher scenarios
- [docs/runbooks/on_call_handbook.md](../runbooks/on_call_handbook.md) — escalation procedures

## Related

- [docs/plans/2026-09-26-impl-C-6-pool-route-execute-idempotency.md](../plans/2026-09-26-impl-C-6-pool-route-execute-idempotency.md)
- [docs/plans/2026-09-26-impl-C-8-worktree-isolation.md](../plans/2026-09-26-impl-C-8-worktree-isolation.md)
- [docs/plans/2026-09-26-impl-C-9-concurrency-limits.md](../plans/2026-09-26-impl-C-9-concurrency-limits.md)
- [docs/adr/0001-mahavishnu-niche.md](../adr/0001-mahavishnu-niche.md)
