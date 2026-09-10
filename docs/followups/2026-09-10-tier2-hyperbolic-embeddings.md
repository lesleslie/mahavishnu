______________________________________________________________________

## status: active role: deferred topic: tier2-hyperbolic-embeddings date: 2026-09-10 last_reviewed: 2026-09-10 superseded_by: null blocks_on: []

# Tier 2 Follow-up: Hyperbolic Embeddings for Session-Buddy Code Graphs

**Created**: 2026-09-10
**Status**: Active — **deferred work, NOT a defect**
**Originating plan**: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) (Tier 1 Phase 9)

## Why deferred

Hyperbolic embeddings (Poincaré disk) preserve the tree-like
hierarchical structure of code graphs in low-dimensional space. The
math is mature; the cost-benefit is in the *scale*. At current
Session-Buddy code-graph node counts, the embedding quality is
indistinguishable from Euclidean baselines.

## Re-evaluation trigger (machine-checked)

`scripts/feature_eligibility.py` checks:

```
hyperbolic_embeddings: state=<below|above|unknown>
    threshold: >= 10000 session_buddy.code_graph.node_count
                AND coverage >= 0.60 of indexed repos
```

The compound check (count AND coverage) guards against embedding a
small but well-covered slice of the codebase that would not exercise
the hierarchical properties the model is designed to capture.

## Activation criteria for the Tier 2 plan

When the trigger fires, open `docs/plans/YYYY-MM-DD-tier2-hyperbolic-embeddings.md` with:

1. **Scale**: confirm `node_count ≥ 10,000` and `coverage ≥ 60%` of indexed repos.
2. **Hierarchical signal**: run a pilot embedding on the live graph;
   confirm Poincaré distance separates structurally-different code
   regions better than Euclidean distance (measured by normalized
   mutual information on a holdout tree partition).
3. **Inference cost**: confirm embedding lookup + similarity search
   fits within the existing Session-Buddy retrieval latency budget
   (target p95 ≤ current p95 + 10%).
4. **Rollback path**: keep the existing Euclidean baseline as the
   default; gate hyperbolic retrieval behind a feature flag.

## Out-of-scope for this followup

- This file does NOT draft the Tier 2 plan; it documents the trigger
  and the activation criteria.
- Session-Buddy's existing embedding pipeline is NOT replaced —
  hyperbolic is added alongside.

## Related

- Tier 1 plan: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) §4.7, §6 Phase 9
- Eligibility script: [`scripts/feature_eligibility.py`](../../scripts/feature_eligibility.py)
- Feature tracking: [`docs/feature-tracking/2026-09-10-tier2-math-deferred.md`](../feature-tracking/2026-09-10-tier2-math-deferred.md)
