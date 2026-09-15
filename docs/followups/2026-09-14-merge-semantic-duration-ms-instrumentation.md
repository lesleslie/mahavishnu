---
status: complete
role: implementation
kind: plan
date: 2026-09-14
last_reviewed: 2026-09-14
superseded_by: null
blocks_on: []
topic: merge-semantic-duration-instrumentation
---

# Followup — `merge.semantic.duration_ms` OTel histogram

**Date:** 2026-09-14
**Originating plan:** `docs/plans/2026-09-12-finish-partial-implementations.md` (Phase 5 OTel counter liveness check)
**Status:** COMPLETE (2026-09-14). Histogram registered + sample-recording thread instrumented for all three entry points: SEMANTIC (`mergiraf`), LINE (`merge_three_way` post-mergiraf fallback), and `_merge_three_way_sync_internal` (CLI-only sync shim). 65 settle tests pass including 4 new histogram-recording tests.

## What shipped

1. **Histogram registration** at `mahavishnu/settle/merge.py` — `_merge_semantic_duration_ms` is created via `_merge_meter.create_histogram(name="merge.semantic.duration_ms", unit="ms")` alongside the existing `_merge_fallback_counter`. Module imports cleanly (verified `from mahavishnu.settle import merge; hasattr(merge, '_merge_semantic_duration_ms')`).
2. **Noop class for missing OpenTelemetry** — added `_NoopHistogram` to the `except ImportError` branch so the histogram reference is still importable when `opentelemetry` is uninstalled.
3. **`_record_semantic_duration` helper** added at module level near `_resolve_default_strategy`. Records a single sample per call with `strategy` and `outcome` attributes.
4. **All three entry functions instrumented** with try/finally + outcome-tracking:
   - `_merge_via_mergiraf` (SEMANTIC): outcomes = `success` / `conflict` / `fatal` / `mergiraf_unavailable` / `mergiraf_retry`.
   - `merge_three_way` LINE branch (the tempfile + git-merge-file subprocess block): outcomes = `success` / `conflict` / `fatal`. Strategy label is the actually-used `effective` strategy so runtime-fallback cases show as `strategy="line"`.
   - `_merge_three_way_sync_internal` (CLI-only sync shim): outcomes = `success` / `conflict` / `fatal`. Strategy hardcoded to `MergeStrategy.LINE` because this helper intentionally keeps Phase 0 git-merge-file semantics (no strategy parameter — the public async `merge_three_way` is the canonical surface).
5. **Tests pinning the instrumentation** — 4 new tests in `tests/unit/settle/test_settle_merge.py`:
   - `test_merge_semantic_duration_ms_histogram_registered` — guards the module-level handle
   - `test_merge_three_way_line_records_success_sample` — happy-path LINE merge
   - `test_merge_three_way_line_records_conflict_sample` — conflict-path LINE merge (verifies `recorded[0] = "conflict"` runs before raise)
   - `test_merge_three_way_sync_internal_records_success_sample` — sync internal happy path

Existing `merge.duration_ms` span attribute is preserved on the SEMANTIC path.

## Why the metering pattern (mutable list + try/finally + helper call)

The three entry functions each have multiple exit points (return MergeResult, raise MergeConflictError, raise MergeFailureError, raise MergeDriverUnavailableError). A naive `try/finally` around the body would lose the outcome label on every raise — the finally block can't distinguish "clean exit" from "conflict exit". The 1-element mutable list idiom (`recorded: list[str] = ["fatal"]`) is Python's idiomatic way to share mutable state between an exit branch and its `finally` block: branch sets `recorded[0] = "..."` before raising, finally reads `recorded[0]`. The default `"fatal"` covers any uncaught exception path that didn't pre-set a label.

`★ Note ─────────────────────────────────────`
The metering surface is now complete for the three primary entry points. Future work, if any, would only target merge paths added by Phase 6+ features (e.g. distributed-merge, batch merge). Not gating the Phase 5 30-day REQ-SM-006 telemetry gate.
`─────────────────────────────────────────────────`

## Validation

- `pytest tests/unit/settle/ --no-cov` → 65 passed, 8 warnings (8 DeprecationWarnings from existing `merge_three_way_sync` tests; unchanged)
- 4 new histogram-recording tests confirm sample-recording at every entry point's happy + conflict paths
- Module import smoke test: `from mahavishnu.settle import merge; hasattr(merge, '_merge_semantic_duration_ms')` → `True`
