______________________________________________________________________

## status: active role: deferred topic: tier2-optimal-transport date: 2026-09-10 last_reviewed: 2026-09-10 superseded_by: null blocks_on: []

# Tier 2 Follow-up: Optimal Transport for Akosha Pattern Comparison

**Created**: 2026-09-10
**Status**: Active — **deferred work, NOT a defect**
**Originating plan**: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) (Tier 1 Phase 9)

## Why deferred

Optimal transport (Wasserstein distance) is a powerful way to compare
pattern distributions across Bodai components, but it only pays off
when the cross-system pattern snapshots have **shape differences
statistically meaningful enough** to distinguish. At current volumes,
the histograms are too sparse for OT-based comparison to outperform
existing cosine-similarity scoring.

## Re-evaluation trigger (machine-checked)

`scripts/feature_eligibility.py` checks:

```
optimal_transport: state=<below|above|unknown>
    threshold: >= 10000 akosha.patterns.cross_system_snapshot_count (30-day window)
```

When the trigger fires, the script exits 1 (CI fail) UNLESS this
followup has `status: active` (which it does) — operators see the
firing and decide whether to draft the Tier 2 follow-on plan.

## Activation criteria for the Tier 2 plan

When the trigger fires, open `docs/plans/YYYY-MM-DD-tier2-optimal-transport.md` with:

1. **Sample size**: confirm `akosha.patterns.cross_system_snapshot_count` ≥ 10,000 over 30 days.
2. **Distribution shape**: run a pilot comparison on the live data; confirm
   the OT-based distance produces a different ranking than cosine
   similarity on ≥ 25% of paired pattern vectors.
3. **Cost ceiling**: prototype end-to-end within a 2-day effort budget
   (per the Tier 1 spec's parallel-engineering cost framing).
4. **Rollback path**: the new scoring path lives behind
   `akosha.patterns.optimal_transport_enabled` config flag
   (default `false`) so the cosine path remains the default until
   the OT path is independently validated.

## Out-of-scope for this followup

- This file does NOT draft the Tier 2 plan; it documents the trigger
  and the activation criteria. The Tier 2 plan is opened when the
  trigger fires.
- The Akosha Z-score and pytrendy detectors are NOT replaced by
  optimal transport — they answer different questions (see
  [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md` §4.6](../plans/2026-09-10-bodai-math-initiatives-tier1.md)).

## Related

- Tier 1 plan: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) §4.7, §6 Phase 9
- Eligibility script: [`scripts/feature_eligibility.py`](../../scripts/feature_eligibility.py)
- Feature tracking: [`docs/feature-tracking/2026-09-10-tier2-math-deferred.md`](../feature-tracking/2026-09-10-tier2-math-deferred.md)
