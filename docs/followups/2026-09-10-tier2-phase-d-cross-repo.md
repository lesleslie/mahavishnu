______________________________________________________________________

## status: active role: deferred topic: tier2-phase-d-cross-repo date: 2026-09-10 last_reviewed: 2026-09-10 superseded_by: null blocks_on: [phase-8-adopted-and-stable]

# Tier 2 Follow-up: Phase D Cross-Repo Akosha Detector Wiring

**Created**: 2026-09-10
**Status**: Active — **deferred work, NOT a defect**
**Originating plan**: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) (Tier 1 §7 cross-repo stub + Phase 9)

## Why deferred

The Tier 1 change-point detector lives in Mahavishnu-local first.
Cross-repo integration with Akosha's existing `pytrendy`-backed
changepoint slot is a follow-on because:

1. **Validate locally first** — a detector bug in Akosha breaks both
   repos with two releases to roll back.
2. **Z-score (pointwise), pytrendy (batch segmentation), and CUSUM/PH
   (online sequential) are three orthogonal detectors** — not
   replacements for each other. CUSUM/PH belongs alongside pytrendy
   in Akosha, not as a replacement for Z-score.
3. **The cross-repo mechanism is named** at Tier 1 §7: extend
   `mahavishnu/pools/fitness_analyzer.py:279` task_classes list to
   include `"routing_change_point"`, plus write `HotRecord` objects
   with the right metadata when the detector fires. <100 LOC.

## Re-evaluation trigger (machine-checked)

`scripts/feature_eligibility.py` checks:

```
phase_d_cross_repo: state=<below|above|unknown>
    threshold: Phase 8 status == adopted AND production_days >= 7
```

The compound check (Phase 8 adopted AND ≥ 1 week of production
operation with the drift signal useful to operators) is the
"validate locally first" enforcement — operators see the drift
signal working before it expands cross-repo.

## Activation criteria for the Phase D plan

When the trigger fires, open
`docs/plans/YYYY-MM-DD-bodai-akosha-cross-repo-changepoint.md` with:

1. **Phase 8 promoted**: `docs/feature-tracking/2026-09-10-observability-changepoint.md`
   has `status: adopted`.
2. **Drift signal useful**: ≥ 1 week of production operation where
   operators found the drift signal actionable (measured by
   `mahavishnu.observability.drift_detected_total` event count +
   `effective_selector` field distribution in routing decisions).
3. **The §7 mechanism**: extend
   `mahavishnu/pools/fitness_analyzer.py:279` task_classes list, plus
   `HotRecord` writes; <100 LOC, no new transport.
4. **Three integration modes** to choose between:
   - **In-process library import** (viable; release-coordination cost).
   - **Mahosha exposes an MCP service** (rejected — inverts seer/orchestrator dependency).
   - **Akosha adds CUSUM/PH natively alongside pytrendy** (cleanest ownership; recommended).
5. **Conformance suite**: reuse Tier 1's
   `tests/integration/observability/test_changepoint_benchmark.py`
   as the cross-repo conformance test.

## Out-of-scope for this followup

- This file does NOT draft the Phase D plan; it documents the trigger
  and the activation criteria.
- Akosha's existing `akosha_analyze_changepoints` (pytrendy) is NOT
  replaced — CUSUM/PH is added alongside.

## Related

- Tier 1 plan §7 cross-repo stub:
  [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) §7
- Eligibility script: [`scripts/feature_eligibility.py`](../../scripts/feature_eligibility.py)
- Feature tracking: [`docs/feature-tracking/2026-09-10-tier2-math-deferred.md`](../feature-tracking/2026-09-10-tier2-math-deferred.md)
