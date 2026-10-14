---
status: complete
role: historical
date: 2026-09-05
last_reviewed: 2026-09-05
topic: metrics-schema-p50-formula
---

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
