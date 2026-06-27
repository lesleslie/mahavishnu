# SLOs: Distilled Workflows (Plan 5)

- **Name**: distilled-workflows
- **Owner**: mahavishnu-orchestration
- **Plan / RFC**: Plan 5 — Distilled Workflows substrate (commit `8f333b5`)
- **Date ratified**: 2026-06-27

Distilled workflows are session-derived, source-pure, reusable workflows
that get published under ULIDs. These SLOs cover the distillation
pipeline and the publish surface.

## SLOs

### SLO 1 — Distill success rate

| Field | Value |
|-------|-------|
| SLI | `sum(rate(distill_runs_total{result="success"}[5m])) / sum(rate(distill_runs_total[5m]))` |
| Objective | `>= 95%` over rolling 30 days |
| Burn-rate alert | `5%` of budget consumed in `1h` |
| Page after | `30m` of sustained breach |
| Runbook | `docs/runbooks/distill-failures.md` (TODO) |

### SLO 2 — Publish latency

| Field | Value |
|-------|-------|
| SLI | `histogram_quantile(0.95, sum by (le) (rate(distill_publish_duration_seconds_bucket[5m])))` |
| Objective | `<= 30 s` (p95, end-to-end from distill start to ULID-assigned publish) over rolling 30 days |
| Burn-rate alert | `10%` of budget consumed in `1h` |
| Page after | `30m` of sustained breach |
| Runbook | `docs/runbooks/distill-publish-latency.md` (TODO) |

### SLO 3 — Source-purity rejection rate

| Field | Value |
|-------|-------|
| SLI | `sum(rate(distill_rejections_total{reason="source_impure"}[5m])) / sum(rate(distill_inputs_total[5m]))` |
| Objective | Track-only (no hard SLO target — baseline informs thresholds) |
| Burn-rate alert | Sudden `3x` deviation from rolling 7-day baseline |
| Page after | `2h` of sustained anomaly |
| Runbook | `docs/runbooks/distill-source-purity.md` (TODO) |

> Rationale for "track-only": a high rejection rate is **good** (we are
> catching impurities before publish). A low rate is **bad** if a
> regression quietly admits impure inputs. We alert on deviation, not
> direction.

## Rollback

- **Command**: `mahavishnu rollback distilled-workflow --id <ulid>`
- **Selector options**: `--id` is the ULID of a previously published workflow version
- **What it reverts**: the currently-active distilled workflow to the version identified by ULID
- **What it preserves**: session provenance, source-purity logs, the ULID ledger
- **Average time to complete**: target `< 30s` (operator-initiated)

## Error budget policy

- **Window**: rolling 30 days
- **Actions when exhausted**:
  1. Pause new distill promotions until budget recovers.
  2. File an incident for SLO 1 and SLO 2 breaches; SLO 3 deviation
     triggers investigation but not an incident.
  3. Re-baseline SLOs only after a documented post-mortem.

## Change log

| Date | Author | Change |
|------|--------|--------|
| 2026-06-27 | audit-H8 | Initial SLOs added per audit finding H8 |
