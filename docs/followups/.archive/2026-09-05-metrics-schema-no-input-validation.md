---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: metrics-schema-no-input-validation
---

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
