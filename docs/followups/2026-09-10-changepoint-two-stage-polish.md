# Followups — Tier 1 changepoint two-stage polish

**Date:** 2026-09-10
**Originating plan:** `docs/superpowers/plans/2026-09-10-changepoint-two-stage-warn-confirm.md`
**Status:** Round-6 fixes landed (`3f61fa3a` + `b758ebba`); 115 tests pass; ops-UX re-review and audit-honesty re-review both clean (no CRITICAL/HIGH/MEDIUM remaining in Round-6 scope). 11 LOW items parked here for the next docs/code sweep.

**Convention:** Each item lists severity, lens, location, defect, proposed fix, acceptance criteria. Items in **bold** are new (introduced or revealed by Round-6 review); items in *italic* were parked before Round-6 dispatch. All are non-blocking.

---

## LOW-1: `drift_warning` log line lacks `severity=` and `samples=%d` for parity with `drift_detected`

- **Severity:** LOW
- **Lens:** ops-UX (Round-6 re-review)
- **Location:** `mahavishnu/core/observability.py:1033` (`_on_drift_warning._log_warning` format string)
- **Defect:** The detected log emits `severity=%s direction=%s samples=%d trace_id=… host=…`. The warning log omits `severity=` and `samples=%d`. Operators piping `loki … | json | severity=~".*"` will match only one signal half.
- **Proposed fix:** Add `severity=warning` (sentinel) and `samples=%d` (the warn detector's `samples_since_reset=0` post-reset, indicating detector is fresh) to the warning log format string.
- **Acceptance:** `grep "drift_warning" mahavishnu/core/observability.py` shows both fields in the format string; running `pytest -s` with `-k drift_warning` and inspecting the captured log shows the new fields.

---

## LOW-2: `detector` attribute on `drift_warning` vs `drift_detected` spans disagrees for two-stage events

- **Severity:** LOW
- **Lens:** ops-UX (Round-6 re-review)
- **Location:** `mahavishnu/core/observability.py:935-940` (warning) vs `:753-762` (detected)
- **Defect:** A chained warn→confirm sequence produces `detector="cusum"` on the warning span (warn detector's class name) but `detector="two_stage"` on the confirmed span (pipeline name). Both are individually correct, but a 3 a.m. operator following `tmp.traces.find({ detector = "two_stage" })` will see confirmed alerts and lose the link to the matching warning.
- **Proposed fix:** Add a sentence to `docs/runbooks/mahavishnu-drift-detection.md` between lines 19–25 explaining the dual-attribute convention: "When `detector == "two_stage"` on a confirmed alert, the corresponding warning carries `detector == "cusum"` (or `"page_hinkley"`) because each signal names its own underlying detector class. To correlate, match `samples_since_warning` on the confirmed span to the warning span's timestamp."
- **Acceptance:** Runbook has a paragraph between the `samples_since_warning` and `confirm_detector` lines explaining the dual-attribute convention; no code change required.

---

## LOW-3: `drift_warning_total` counter lacks `severity` label for uniform PromQL query shape

- **Severity:** LOW
- **Lens:** ops-UX (Round-6 re-review)
- **Location:** `mahavishnu/core/observability.py:952-961` (`_on_drift_warning` counter)
- **Defect:** Warnings aren't severity-classified, so the counter emits without `severity`. Operators accustomed to `sum by(severity) (rate(drift_detected_total[5m]))` will not find an analogous query for warnings.
- **Proposed fix:** Add `severity="warning"` (fixed string per emission) to the warning counter's label set. Tradeoff: improves query-template uniformity vs. label-cardinality cost (a constant cardinality of 1 is negligible).
- **Acceptance:** `_on_drift_warning` calls `counter.add(1, attributes={..., "severity": "warning"})`; `_validate_labels` allowlist at `mahavishnu/observability/metrics.py:74` includes `severity` (it already does for the detected path).
- **Status:** **Document but don't change** per the ops-UX reviewer's recommendation. Trivial uniformity win, but skipping the label is also defensible. Skip unless a downstream dashboard needs it.

---

## LOW-4: Source-plan snapshot stale "108/4" claim

- **Severity:** LOW
- **Lens:** audit-honesty (Round-6 re-review; **pre-existing drift, not a Round-6 regression**)
- **Location:** `docs/superpowers/plans/2026-09-10-changepoint-two-stage-warn-confirm.md:1344` (Status line)
- **Defect:** The original plan snapshot still claims `108 tests collected across 4 files` — pre-dates both the F10 dispatch seam test (which added 2) and the F1 correction (which moved the count to 115/8). The audit doc itself was correctly updated; only the plan snapshot is stale.
- **Proposed fix:** One-line edit to bring the plan snapshot into parity with the audit doc:

  ```diff
  - 108 tests collected across 4 files (4 detection integration + 6 benchmark integration + 90 unit + 8 two_stage unit; pre-round-2 claim of 10/10 was the benchmark file alone before unit tests expanded
  + 115 tests collected across 8 .py files (4 detection integration + 6 benchmark integration + 4 two_stage benchmark integration + 2 two_stage dispatch integration + 39 CUSUM unit + 47 sampler unit + 9 two_stage unit + 4 worker_metrics unit
  ```

- **Acceptance:** The plan snapshot's Status line matches the audit doc's count and file list.
- **Note:** This is a plan snapshot, not an operator-facing or audit-referenced doc. Parked but easy to do.

---

## *LOW-5: Healthy `drift_warning_total` rate heuristic missing from runbook*

- **Severity:** LOW
- **Lens:** ops-UX (Round-5 original; parked before Round-6)
- **Location:** `docs/runbooks/mahavishnu-drift-detection.md:103-105`
- **Defect:** Runbook names `mahavishnu.observability.drift_warning_total` as a metric to monitor but provides no concrete "if your rate is > X / 10,080, the warn threshold is too sensitive" heuristic. The validation report cites "~30 per 10,080" as the design point at production defaults.
- **Proposed fix:** Add a sentence: "~30 warnings per 10,080 is the design point at `warn_threshold=8.0` on stationary Gaussian noise; sustained rates > 2× that on stationary traffic suggest a mis-tuned warn threshold or non-stationary input."
- **Acceptance:** Runbook has the design-point rate plus the >2× heuristic for operators.

---

## *LOW-6: Feature-tracking two-stage section migration narrative incomplete*

- **Severity:** LOW
- **Lens:** ops-UX (Round-5 original; parked before Round-6)
- **Location:** `docs/feature-tracking/2026-09-10-observability-changepoint.md` (Round-5 section, ~lines 152–160)
- **Defect:** The Round-5 entry mentions two_stage opt-in but doesn't link the migration narrative to the spec's Phase 8 promotion timing.
- **Proposed fix:** Cross-link to `docs/plans/2026-09-10-bodai-math-initiatives-tier1.md §6 Phase 8` and the runbook migration section.
- **Acceptance:** Feature-tracking entry mentions Phase 8 promotion as the migration window.

---

## *LOW-7: `TwoStageDetector` state-machine diagram does not document the `_last_warning_result` extension*

- **Severity:** LOW
- **Lens:** math (Round-5 original; parked before Round-6)
- **Location:** `mahavishnu/observability/changepoint/two_stage.py:11-16` (module docstring state diagram)
- **Defect:** The state-machine diagram doesn't document that `warning_pending → warning_pending` (a warn re-fire inside the window) updates `_last_warning_result` and resets the warn detector.
- **Proposed fix:** Add a sentence to the docstring: "If `warn_detector` fires again while in `warning_pending`, the latest warning result captures in `_last_warning_result` and the warn detector resets; the next confirm carries the LATEST warning score, not the first."
- **Acceptance:** Module docstring state diagram mentions the warn re-fire transition.

---

## *LOW-8: Boundary-sample unit test missing for `confirm_window_samples` boundary*

- **Severity:** LOW
- **Lens:** math (Round-5 original; parked before Round-6)
- **Location:** `tests/unit/observability/test_changepoint_two_stage.py` (new test file)
- **Defect:** No unit test exercises the boundary case where confirm fires on the exact `confirm_window_samples`-th sample after a warn. The state-machine behavior is correct (confirm runs before window-expiry), but no test pins it.
- **Proposed fix:** Add a test that constructs a `TwoStageDetector(warn=h=8.0, confirm=h=14.0, confirm_window_samples=100)`, drives a stream where warn fires at sample N and confirm fires at sample N+100, and asserts the confirmed span is emitted.
- **Acceptance:** New unit test `test_confirm_fires_on_boundary_sample` passes; covers the ≤ N inclusive boundary semantics.

---

## *LOW-9: Detector-name normalization duplicated across `_on_drift_detected` and `_on_drift_warning`*

- **Severity:** LOW
- **Lens:** architecture (Round-5 original; parked before Round-6)
- **Location:** `mahavishnu/core/observability.py:753-762` (detected) vs `:932-938` (warning)
- **Defect:** Both methods produce the canonical tokens `cusum` / `page_hinkley` / `two_stage` but use different comparison strategies (class-name capitalized vs lowercased). Drift hazard if a new detector class is added.
- **Proposed fix:** Extract `_canonical_detector_name(detector_or_result)` helper that handles both `TwoStageResult.detector_warn` (lowercased) and `type(detector).__name__` (capitalized) inputs.
- **Acceptance:** Helper exists in `_metrics` or `observability` private utility; both call sites use it; behavior unchanged.

---

## *LOW-10: Dispatch uses two `if` statements instead of `elif` (mutually exclusive states)*

- **Severity:** LOW
- **Lens:** architecture (Round-5 original; parked before Round-6)
- **Location:** `mahavishnu/core/observability.py:458-468`
- **Defect:** The two branches are mutually exclusive (TwoStageResult.state is `Literal["idle", "warning_pending", "confirmed"]`) but written as two `if` statements. Could mislead reviewers into thinking both branches can fire on one update.
- **Proposed fix:** Change `if result.state == "confirmed"...` to `elif result.state == "confirmed"...`.
- **Acceptance:** Dispatch uses `elif`; tests still pass.

---

## *LOW-11: Redundant `isinstance(result, TwoStageResult)` guard inside `_on_drift_warning`*

- **Severity:** LOW
- **Lens:** architecture (Round-5 original; parked before Round-6)
- **Location:** `mahavishnu/core/observability.py:929` (`_on_drift_warning` first line)
- **Defect:** `_on_drift_warning` checks `if not isinstance(result, TwoStageResult): return` on its first line, but the only call site (the dispatch at line 458) already enforces this precondition.
- **Proposed fix:** Add a one-line comment in the method docstring noting that the guard preserves the property if the method is called from elsewhere (defensive coding). No code change.
- **Acceptance:** Method docstring mentions the defensive rationale.

---

## How to attack these items

- Run `git grep -nE "drift_warning|drift_detected"` to find every site that touches the two signal paths when working on LOW-1 / LOW-2 / LOW-3.
- LOW-9, LOW-10, LOW-11 are mechanical refactors scoped to `mahavishnu/core/observability.py`.
- LOW-4 is a 1-line doc fix in a plan snapshot — quickest win if you want to close one item.
- LOW-7, LOW-8 require reading the `TwoStageDetector` module closely to ensure the new test/docstring matches the actual state-machine behavior.

Each item is independently shippable as a single commit; batch related items (e.g., LOW-9 + LOW-10 + LOW-11 in one commit) if they're all in the same file.
