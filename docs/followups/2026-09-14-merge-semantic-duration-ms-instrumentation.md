---
status: active
role: implementation
kind: plan
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
blocks_on: []
topic: merge-semantic-duration-ms-instrumentation
---

# Followup — `merge.semantic.duration_ms` OTel histogram

**Date:** 2026-09-14
**Originating plan:** `docs/plans/2026-09-12-finish-partial-implementations.md` (Phase 5 OTel counter liveness check)
**Status:** OPEN — gap surfaced by Phase 5 audit, fix not yet applied.

## What the gap is

The settle-semantic-merge plan's REQ-SM-006 deferral trigger
references `merge.semantic.duration_ms` as a histogram that gates
Phase 6's candidate swap to `git merge-tree --write-tree`:

> REQ-SM-006 deferral trigger: "30 days of `merge.fallback_total`
> telemetry AND `merge.semantic.duration_ms` p99 < 50 ms; gated
> additionally on Phase-6 candidate swap to `git merge-tree --write-tree`."

Phase 5 OTel counter liveness check (2026-09-14 audit) found that
**the histogram is not emitted**. The audit grep returned:

- `drift_warning_total` — FOUND (`mahavishnu/core/observability.py:188`)
- `drift_detected_total` — FOUND (`mahavishnu/core/observability.py:175`)
- `merge.fallback_total` — FOUND (`mahavishnu/settle/merge.py`)
- **``merge.semantic.duration_ms`** — NOT FOUND.

There IS a related span attribute already: `merge.duration_ms` at
`mahavishnu/settle/merge.py:602`, set on the `merge_three_way` OTel
span via `span.set_attribute(...)`. That attribute is useful but does
not satisfy the histogram spec called for in the deferral trigger
(p99 < 50 ms computation requires per-call latency, not per-span).

## Proposed fix (acceptance criteria)

1. Create a new OTel histogram in `mahavishnu/settle/merge.py` (or
   register it in `mahavishnu/core/observability.py` depending on the
   chosen module boundary):
   - Name: `merge.semantic.duration_ms`
   - Unit: ms
   - Histogram buckets: 1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500
2. Record a sample on every call to `merge_three_way` (and
   `_merge_three_way_sync_internal` for parity) — the existing
   `(time.monotonic() - start) * 1000.0` computation at
   `mahavishnu/settle/merge.py:598` already produces the value.
3. Add labels: `strategy` (one of `MergeStrategy.LINE`,
   `MergeStrategy.MERGIRAF`, etc.) and `outcome` (`success`,
   `conflict`, `fatal_exit`, `mergiraf_unavailable`).
4. Keep the `merge.duration_ms` span attribute at line 602 (it's a
   useful per-trace signal; the histogram is aggregate).
5. Update REQ-SM-006 deferral trigger in
   `docs/plans/2026-09-10-settle-semantic-merge.md` §6 to cite the
   new histogram by name once wired.
6. Add a unit test asserting the histogram is registered on
   `ObservabilityManager` initialization (or the chosen module's
   initialization).

## Estimated size

~10-15 lines of code + test + runbook update. Trivial change; left
as a separate followup so Phase 5 audit could close the meta-plan
without dragging in new instrumentation work.

## Why not just fold into the meta-plan

Per the meta-plan's Phase 5 spec, "If any phase did NOT reach
terminal status, either fix in this phase or document the open work
as a follow-up plan." Splitting the instrumentation off preserves
the meta-plan's narrow scope (closing 4 partial items) and keeps
this followup independently reviewable.

______________________________________________________________________
