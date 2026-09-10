---
name: observability-changepoint
status: wired
date: 2026-09-10
last_reviewed: 2026-09-10
owner: bodai-orchestrator
role: canonical
---

# Feature: observability-changepoint

**Owner:** bodai-orchestrator
**Created:** 2026-09-10
**Last updated:** 2026-09-10
**Repo(s):** `/Users/les/Projects/mahavishnu`

## State — pick one

- [x] **wired** (built + integrated; awaiting operator adoption of the two-stage extension)

The original CUSUM/Page-Hinkley detector has been adopted since
Phase 7. The two-stage warn/confirm extension shipped 2026-09-10
in commits `3f61fa3a` + `b758ebba` + `40cd2315`; the code default
for `changepoint.detector` remains `cusum`, so operators opt into
`two_stage` explicitly via `changepoint.detector: "two_stage"` in
`settings/mahavishnu.yaml` or `MAHAVISHNU_CHANGEPOINT__DETECTOR=two_stage`.
Status moves back to `adopted` once operators begin the staged
rollout below.

## Wiring checklist

- [x] Entry point registered: `ObservabilityManager._evaluate_change_point`,
      `_evaluate_3sigma` (`mahavishnu/core/observability.py`)
- [x] Trigger path identified: `MetricSampler` (60s cadence) →
      CUSUMDetector / 3-sigma sliding window
- [x] Returns / state updates land in expected destination:
      OTel span `mahavishnu.observability.drift_detected`, log
      `drift_detected`, log `three_sigma_anomaly`
- [x] End-to-end smoke check documented:
      `pytest tests/integration/observability/`
- [x] Observability hook in place: OTel span + structured logs
- [x] Rollback signal defined: env-var
      `MAHAVISHNU_CHANGEPOINT__ENABLED=false`; `changepoint.enabled: false` in YAML

## Built (yes/no)

yes (Phase 5 commit; the CUSUM/Page-Hinkley library is merged).

## Wired (yes/no)

yes (Phase 6 commit; the detector is invoked via
`ObservabilityManager._evaluate_change_point` on every metric
sample from the `MetricSampler`).

## Trigger path

* Entry point: `ObservabilityManager._evaluate_change_point(metric_name, value)` and
  `ObservabilityManager._evaluate_3sigma(metric_name, value)`
* Sample source: `MetricSampler` (ring buffer, default 7200 samples
  at 60s cadence; 2-hour window)
* Detector factory: lazy on first call, cached on
  `self._changepoint_detector`. Uses
  `changepoint.{slack, threshold, detector}` from config.
* Severity classifier: `minor` (< 2×threshold), `moderate`
  (2×-4×), `critical` (≥ 4×).

## Integration point

* OTel span `mahavishnu.observability.drift_detected` (when
  detector fires)
* Structured WARNING log line on the same shape
* `three_sigma_anomaly` log line (when reference detector fires
  in parallel; default config)
* New Dhara table `mahavishnu.observability.metric_samples` (when
  Phase D follow-on lands; for now the sampler is in-process only)
* Runbook: `docs/runbooks/mahavishnu-drift-detection.md` (operators
  cross-reference this when `drift_detected` fires)

## End-to-end check

```bash
# 1. Unit + integration tests
uv run pytest tests/unit/observability/test_changepoint.py \
              tests/unit/observability/test_changepoint_sampler.py \
              tests/integration/observability/ \
              --no-cov
# Expected: 63 passed

# 2. Local smoke (single detection round)
uv run python -c "
import random
from mahavishnu.observability.changepoint import CUSUMDetector
d = CUSUMDetector(target_mean=0.0, slack=0.25, threshold=8.0, two_sided=True)
rng = random.Random(42)
for _ in range(200):
    d.update(rng.gauss(0.0, 1.0))
d.reset()
for i in range(100):
    r = d.update(rng.gauss(0.5, 1.0))
    if r.detected:
        print(f'detected at sample {r.samples_since_reset}')
        break
"
# Expected: detected at sample < 30 (spec §1 gate)
```

## Staged rollout playbook (Phase 8)

| Stage | Environment | Window | Gating metrics |
|-------|-------------|--------|----------------|
| 1 (first) | dev (your-machine) | ≥ 7 days | `mahavishnu.observability.drift_detected_total` event count, FP rate from production quiet periods |
| 2 | staging-2 | ≥ 7 days | same |
| 3 | production-canary | ≥ 7 days | same, plus p99 routing latency (must not regress) |
| 4 | all production | — | continuous |

### Per-stage gating (all must hold to advance)

* `mahavishnu.observability.drift_detected_total` event rate
  does NOT exceed 2 per 10,080 samples (1 week at 60s cadence)
  on production quiet traffic — the §7 spec v3.1 gate.
* `three_sigma_miss_rate` is documented (we expect the 3-σ
  reference to miss most slow-drift shifts; if it suddenly
  starts firing, that signals a real problem the change-point
  detector isn't catching).
* No spurious drift detections that correlate with planned
  deployments (the runbook's "known deployment" silence rule
  applies for the first 24h after any deployment).
* Routing latency does NOT regress by more than 1ms p99
  (the detector is O(1) per sample; the budget catches
  integration regressions).

### Per-environment opt-out template

Add to `settings/local.yaml`:

```yaml
changepoint:
  enabled: false
```

Or set the env var on the deployment target:

```bash
export MAHAVISHNU_CHANGEPOINT__ENABLED=false
```

To disable only the 3-σ reference (keep the change-point
detector), set:

```bash
export MAHAVISHNU_CHANGEPOINT__REFERENCE_DETECTOR=none
```

### Round-5 two-stage update

The Phase 8 promotion recommends `two_stage` as the operator choice post-Phase-8; the code default for `changepoint.detector` remains `cusum` for backwards compat with the Phase 6/7 single-detector baseline. Operators opt in via `changepoint.detector: "two_stage"` in `settings/mahavishnu.yaml` or `MAHAVISHNU_CHANGEPOINT__DETECTOR=two_stage`.
The two-stage architecture resolves the §1/§7 trade-off documented
in `docs/audits/2026-09-10-changepoint-validation.md`. Operators
who have customized `changepoint.detector: "cusum"` in
`settings/local.yaml` for backwards compat should re-evaluate after
two weeks of two_stage operation in their environment — the
two-stage mode emits BOTH `drift_warning` (soft) and
`drift_detected` (hard) signals, so existing alerts on
`drift_detected` continue to work without changes.

### Round-6 review fixes (shipped 2026-09-10)

Three commits landed to close the Task 7 4-agent review's
CRITICAL + HIGH + MEDIUM findings:

- `3f61fa3a` — `docs+test(changepoint): round-6 fixes per task-7 review` (8 files, +287/−38). Bundle of F1–F10: test-count correction, `drift_warning` OTel span parity with `drift_detected` (added `instance_id`, `host`, `trace_id`, `runbook_url`, `baseline_mean`, `baseline_std`), severity-classifier factored to `mahavishnu/observability/changepoint/severity.py` to remove the `two_stage.py` ⇄ `observability.py` circular-import hazard, `confirm_window_samples` boundary docstring clarified, runbook "RECOMMENDED for production" reworded to "RECOMMENDED operator choice post-Phase-8", feature-tracking default-detector claim corrected, runbook `drift_detected` attribute list extended with `samples_since_warning` + `confirm_detector`, spec §1 names `mahavishnu.observability.drift_warning_total` counter + links runbook, dispatch-seam integration test (`tests/integration/observability/test_changepoint_two_stage_dispatch.py`).
- `b758ebba` — `docs(audit): correct changepoint test count to 115 across 8 files (post-F10 dispatch seam test)` (1 line). Audit doc's status header corrected from 113/7 to 115/8 to match the post-F10 reality.
- `40cd2315` — `docs(followups): park 11 LOW polish items from changepoint two-stage review (round-7/8)` (1 file). 11 LOW items parked for the next docs/code sweep; full list at `docs/followups/2026-09-10-changepoint-two-stage-polish.md`.

Both affected re-reviewers (ops-UX + audit-honesty) reported clean for
shipping. Ops-UX verdict: "ready to ship, 3 new LOWs (no regressions)."
Audit-honesty verdict: "CLEAN — All three Round-5 audit-honesty
findings are resolved. The fix layer landed the test-count correction
in both `3f61fa3a` (initial 113/7) AND `b758ebba` (corrected to
115/8 to match post-F10 state), and the detector-default narrative is
now consistent across all 5 doc surfaces."

Math + arch reviewers not re-dispatched (their findings were MEDIUM/LOW
and unchanged by Round-6; LOW items now parked in the followups doc).

115 tests pass across 8 .py files (live `pytest collect-only` confirmed
in audit-honesty re-review on 2026-09-10).

## Blocker

None — the feature is adopted. The Phase 9 multi-metric trigger
fires when ≥ 3 distinct metrics are requested by operators within
a 30-day window; that opens the Tier 2 multi-metric follow-on
plan, NOT a rollback of this feature.

## Next action

1. Apply the staged rollout playbook to dev → staging-2 → canary
   → production. Document each environment's opt-out (if any) in
   the team's deployment runbook.
2. Monitor the gating metrics for 7 days per stage; do not
   advance to the next stage until the metrics hold.
3. After full production rollout, add a one-line note in
   `CHANGELOG.md` with the date and the rollout result.

## Related

* Plan: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) §6 Phase 8
* Library: `mahavishnu/observability/changepoint/`
* Sampler: `mahavishnu/observability/sampler.py`
* Runbook: [`docs/runbooks/mahavishnu-drift-detection.md`](../runbooks/mahavishnu-drift-detection.md)
* Validation: [`docs/audits/2026-09-10-changepoint-validation.md`](../audits/2026-09-10-changepoint-validation.md)
* Library docs: [`docs/observability/changepoint_validation.md`](../observability/changepoint_validation.md)

## Session-Buddy

- Reflection ID: (saved at Tier 1 promotion)
- Saved at: 2026-09-10
