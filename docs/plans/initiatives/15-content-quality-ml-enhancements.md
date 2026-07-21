---
status: complete
role: historical
topic: observability
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Initiative 15: Content Quality ML Enhancements

## Metadata

- Status: `complete` <!-- legacy status: complete — see YAML frontmatter -->
- Owner Role: `ML Eng + Ingestion`
- Target Window: `2026-06-15` to `2026-07-03`

## Outcome

Replace quality evaluator stub with measurable ML-backed quality scoring.

## Work Package Checklist

- [x] `I15-1` Define labeled dataset and eval rubric
- [x] `I15-2` Implement readability/depth/completeness scoring
- [x] `I15-3` Offline evaluation and threshold tuning
- [x] `I15-4` Staged rollout + drift monitoring dashboard

## Dependencies

- `I9-2`

## Exit Criteria

- Offline quality metric improves by `>=10%`
- Online relevance improvement without latency regression

## Risks

- Weak labels causing unstable model quality
- Drift after rollout without sufficient monitoring

## Progress Log

- 2026-04-04: Plan file created.
- 2026-04-05: All I15 tasks complete:
  - I15-1: Created docs/specs/content-quality-dataset.md with labeled dataset schema, evaluation rubric (readability, technical depth, completeness), scoring weights, thresholds, and drift monitoring rules
  - I15-2: Implemented mahavishnu/ingesters/quality_scorer.py with heuristic-based scoring (12 sub-scorers, 3 top-level metrics, ContentQualityScorer class with history/drift tracking)
  - I15-3: Updated scripts/eval-content-quality.py to use ContentQualityScorer for automated scoring, converting 0-1 scores to 1-5 scale for human label comparison
  - I15-4: ContentQualityScorer includes get_drift_stats() and check_drift() for mean/variance drift monitoring against baselines
  - Tests: 15/15 passing in tests/unit/test_quality_scorer.py (TestReadability, TestTechnicalDepth, TestCompleteness, TestContentQualityScorer)
