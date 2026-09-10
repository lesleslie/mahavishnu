______________________________________________________________________

## status: active role: deferred topic: tier2-multi-metric-drift date: 2026-09-10 last_reviewed: 2026-09-10 superseded_by: null blocks_on: []

# Tier 2 Follow-up: Multi-Metric Drift Detection

**Created**: 2026-09-10
**Status**: Active — **deferred work, NOT a defect**
**Originating plan**: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) (Tier 1 Phase 9 — operational follow-on trigger)

## Why deferred

Phase 6's change-point detector is single-metric by design — one
`target_metric` is monitored at a time (default `pool_queue_depth`).
This is the right v1 cut: it reuses Phase 2's per-pool arrival
instrumentation and the cost model is bounded.

The gap: operators will hit the single-metric wall within weeks of
Phase 8 promotion. Different incident classes trigger on different
metrics (latency p99 vs error rate vs queue depth), and switching
`changepoint.target_metric` per-incident means re-warming the
detector each time.

## Re-evaluation trigger (machine-checked)

`scripts/feature_eligibility.py` checks:

```
multi_metric_drift: state=<below|above|unknown>
    threshold: >= 3 distinct metrics requested by operators in 30-day window
```

The distinct-metric count is read from
`~/.mahavishnu/metric_requests.json` (a JSON-lines file written by
the `discover_tools` flow when an operator queries for a metric).
The 30-day window guards against false positives from a one-off
investigation.

## Activation criteria for the Tier 2 plan

When the trigger fires, open `docs/plans/YYYY-MM-DD-tier2-multi-metric-drift.md` with:

1. **Volume**: confirm `>= 3` distinct metrics in the 30-day
   request log. The Tier 1 design point — "single-metric is right
   v1" — has been operationally superseded.
2. **Cost model**: extending the CUSUM/PH detector to N metrics is
   O(N) memory and O(1) compute per tick at canonical settings;
   the cost is bounded.
3. **Config schema**: extend `changepoint:` block to a list of
   `target_metrics: [{name, slack, threshold}, ...]` instead of a
   single `target_metric`.
4. **Rollback path**: operators can fall back to a single metric by
   collapsing the list to one entry; no state migration needed.
5. **Test coverage**: extend
   `tests/integration/observability/test_changepoint_detection.py`
   to drive 2-3 metrics concurrently and assert independent
   detection.

## Out-of-scope for this followup

- This file does NOT draft the Tier 2 plan; it documents the trigger
  and the activation criteria.
- The single-metric Tier 1 detector is NOT replaced — multi-metric
  is additive.

## Related

- Tier 1 plan Phase 6 single-metric gate:
  [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) §6 Phase 6
- Tier 1 v3.1 changelog (this trigger added):
  [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) top of file
- Eligibility script: [`scripts/feature_eligibility.py`](../../scripts/feature_eligibility.py)
- Feature tracking: [`docs/feature-tracking/2026-09-10-tier2-math-deferred.md`](../feature-tracking/2026-09-10-tier2-math-deferred.md)
