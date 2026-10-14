---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: metrics-schema-confidence-dead-parameter
---

# `calculate_confidence_interval` ignores `confidence` parameter

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/core/metrics_schema.py:329-342`
(new `_Z_SCORES` dict with `0.80/0.85/0.90/0.95/0.99` entries) and
`mahavishnu/core/metrics_schema.py:330-331` (extracted `_MIN_SAMPLE_SIZE_FOR_CI = 10` constant).
Regression tests at
`tests/unit/test_metrics_schema_extended.py::TestCalculateConfidenceIntervalBranches::test_higher_confidence_yields_wider_interval`
and `::test_unknown_confidence_falls_back_to_1_96`.

## Trigger

Coverage fanout 2026-09-05 (Brief 1) — subagent discovered
`calculate_confidence_interval` at `mahavishnu/core/metrics_schema.py:327-366`
has a `confidence: float = 0.95` parameter that is **never read** inside the
function body. The hardcoded z-score `1.96` (line 353) is always used,
regardless of the `confidence` value passed. A caller requesting
`confidence=0.99` would silently get a 95% interval.

Additionally, the `< 10` sample-size threshold on line 344 is a hardcoded
magic number with no constant — should be extracted.

`grep` confirms no production callers of `calculate_confidence_interval` from
this module — `predictions.py:227` defines its own method-local
`_calculate_confidence_interval`. Zero blast radius.

## Action

1. File `Open` followup note (this file).
2. Extract `_MIN_SAMPLE_SIZE_FOR_CI = 10` module constant.
3. Replace hardcoded `z = 1.96` with a z-score lookup keyed on `confidence`:
   common values `0.90 → 1.645`, `0.95 → 1.96`, `0.99 → 2.576`. Fall back to
   1.96 for unknown values.
4. Add regression tests asserting different confidence values produce
   different z-scores / different widths.
5. Mark Resolved citing fix location + regression test name.
