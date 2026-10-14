---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-10-13
superseded_by: null
blocks_on: []
topic: metrics-schema
---

# Metrics Schema Fixes Batch (consolidated)

This followup consolidates three former followups that each tracked a
metrics-schema recording defect. All three are complete/historical.

Each section preserves the original content verbatim.

---

## 1. `confidence` dead parameter (formerly `2026-09-05-metrics-schema-confidence-dead-parameter.md`)

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

---

## 2. No input validation (formerly `2026-09-05-metrics-schema-no-input-validation.md`)

# `calculate_percentiles` accepts negative or >100 percentile values silently

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/core/metrics_schema.py:316-317`
(raises `ValueError` when percentile outside `[0, 100]`); regression tests at
`tests/unit/test_metrics_schema_extended.py::TestCalculatePercentilesBranches::test_negative_percentile_raises_value_error`
and `tests/unit/test_metrics_schema_extended.py::TestCalculatePercentilesBranches::test_percentile_over_100_raises_value_error`.

## Trigger

Coverage fanout 2026-09-05 (Brief 1) — subagent discovered
`calculate_percentiles` at `mahavishnu/core/metrics_schema.py:291-324` has no
input validation. Negative percentile values (e.g. `[-1.0]`) and values
>100 (e.g. `[150.0]`) silently produce near-edge values or literal `-1` keys.
A caller passing bad data gets no signal.

`grep` confirms no production callers — zero blast radius.

## Action

1. File `Open` followup note (this file).
2. Add `if not 0 <= p <= 100: raise ValueError(...)` at top of the
   `for p in percentiles` loop (around line 312).
3. Add regression tests asserting `ValueError` on negative / over-100 inputs.
4. Update `test_metrics_schema_extended.py::test_negative_percentile_still_returns_something`
   to assert the new `ValueError` behavior (the existing test asserts the
   silent acceptance — it must be inverted).
5. Mark Resolved citing fix location + regression test name.

---

## 3. p50 formula (formerly `2026-09-05-metrics-schema-p50-formula.md`)

# `calculate_percentiles` p50 formula is non-standard (lower-of-two-middles)

## Status

**Resolved (2026-09-05)** — production fix at `mahavishnu/core/metrics_schema.py:320`
(`index = len(sorted_latencies) // 2` instead of the lower-of-two-middles
formula); regression tests at `tests/unit/test_metrics_schema.py` (5 assertions
updated) and `tests/unit/test_metrics_schema_extended.py::TestCalculatePercentilesBranches`
(4 assertions updated, plus a new `test_zero_percentile_returns_first_value`
boundary test).

## Trigger

Coverage fanout 2026-09-05 (Brief 1: `core/metrics_schema.py`) — subagent
discovered the p50 branch at `mahavishnu/core/metrics_schema.py:314` uses
`index = max(0, (len(sorted_latencies) - 1) // 2 - 1)`. For odd-length input
this returns `len//2 - 1` instead of the conventional textbook median
`len//2`. Example: `[10,20,30,40,50]` returns `20` instead of `30`.

Eight existing test assertions across `tests/unit/test_metrics_schema.py`
and `tests/unit/test_metrics_schema_extended.py` document the bug as
"custom formula" / "expected behavior", but this is a real semantic defect
that would silently mislead any consumer expecting textbook median.

`grep -rn 'calculate_percentiles' /Users/les/Projects/mahavishnu/mahavishnu/`
confirms **no production callers** — zero blast radius.

## Action

1. File `Open` followup note (this file).
2. Change line 314 from `index = max(0, (len(sorted_latencies) - 1) // 2 - 1)`
   to `index = len(sorted_latencies) // 2` (textbook median).
3. Update 8 existing test assertions that pin the bug.
4. Update docstring to specify "nearest-rank, 0-indexed" formula.
5. Mark Resolved citing fix location + regression test name.
