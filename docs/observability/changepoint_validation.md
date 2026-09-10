# Mahavishnu Change-Point Detection Validation

**Owner:** bodai-orchestrator
**Created:** 2026-09-10
**Last updated:** 2026-09-10
**Spec:** [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md` §1, §6 Phase 5-8](../plans/2026-09-10-bodai-math-initiatives-tier1.md)
**Library:** `mahavishnu.observability.changepoint` (Tier 1 Phase 5)
**Integration:** `mahavishnu.core.observability` (Tier 1 Phase 6)

## What this is

The change-point detector (CUSUM and Page-Hinkley) is a NEW
Mahavishnu-local signal that runs alongside the 3-sigma reference
detector. The integration is in `ObservabilityManager._evaluate_change_point`
and `ObservabilityManager._evaluate_3sigma`; both are fed by a
`MetricSampler` ring buffer at 60s cadence.

## The detectors

* **CUSUM** (default, two-sided) — Cumulative Sum detector.
  Parameters `slack` (k) and `threshold` (h) drive the
  false-positive / latency trade-off. Defaults: `k=0.25σ`,
  `h=8.0` (per the spec).
* **Page-Hinkley** — online-quadratic variant; `delta` parameter
  discounts small fluctuations below the minimum detectable
  shift. Use when the metric is noisy and a single CUSUM
  threshold is too sensitive.
* **3-sigma reference** — sliding-window z-score, fires on
  `|z| >= 3`. Misses most 0.5-σ shifts; the spec's
  `reference_detector: "three_sigma"` keeps it as a fallback so
  operators see a familiar signal when the change-point detector
  is silent.

## What the validation says

The Phase 7 integration test exercises the detectors on synthetic
Gaussian streams:

* CUSUM 0.5-σ shift — fires within 30 samples (spec gate).
* CUSUM 1-σ shift — fires within 15 samples.
* 3-σ miss rate on 0.5-σ shifts — > 95% (documents the
  reference's slow-drift blindness).
* Sampler → CUSUM pipeline — end-to-end through
  `ObservabilityManager._evaluate_change_point`: a constant
  stream at the target (0) does not fire; a 50-σ shift fires
  immediately.

The §7 gate is `cusum_fp_per_10080_quiet_samples <= 2` (relaxed
from `== 0` in spec v3.1; the strict 0-FP gate would fail ~63% of
the time on a correctly-tuned detector with ARL₀ = 10,000 and
Poisson FP process).

## Operational behavior

When `changepoint.enabled: true` and the detector fires:

* OTel span `mahavishnu.observability.drift_detected` is emitted
  with `metric_name`, `detector`, `score_high`, `score_low`,
  `score`, `threshold`, `samples_since_reset`, `direction`,
  `severity` (`minor` / `moderate` / `critical`).
* A structured WARNING log line carries the same shape.
* When the 3-σ reference also fires (default), an independent
  `three_sigma_anomaly` log line is emitted.

The runbook at `docs/runbooks/mahavishnu-drift-detection.md` walks
operators through triage, with the cross-repo gap-period guidance
for Phase D (the Akosha wiring) and the post-restart re-warmup
window.

## Single-metric scope

Phase 6 is single-metric by design. The default
`changepoint.target_metric` is `pool_queue_depth` (per spec §12
Q3 resolution). Multi-metric monitoring is a Tier 2 follow-on
triggered by `scripts/feature_eligibility.py` when ≥ 3 different
metrics are requested by operators within a 30-day window.

## Opt-in / opt-out

```yaml
# settings/mahavishnu.yaml
changepoint:
  enabled: false  # default in Phase 6; Phase 8 flips to true
  target_metric: "pool_queue_depth"
  detector: "cusum"  # or "page_hinkley"
  slack: 0.25
  threshold: 8.0
  reference_detector: "three_sigma"  # or "none"
  sampler_cadence_seconds: 60.0
```

```bash
# Env var override (Oneiric double-underscore convention)
MAHAVISHNU_CHANGEPOINT__ENABLED=false
```

## References

* Tier 1 plan §1, §6 Phase 5-8: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md)
* Validation report: [`docs/audits/2026-09-10-changepoint-validation.md`](../audits/2026-09-10-changepoint-validation.md)
* Runbook: [`docs/runbooks/mahavishnu-drift-detection.md`](../runbooks/mahavishnu-drift-detection.md)
* Feature tracking: [`docs/feature-tracking/2026-09-10-observability-changepoint.md`](../feature-tracking/) (added in Phase 8)
* Library code: `mahavishnu/observability/changepoint/`
* Sampler code: `mahavishnu/observability/sampler.py`
* Integration tests: `tests/integration/observability/test_changepoint_detection.py`, `test_changepoint_benchmark.py`
* Unit tests: `tests/unit/observability/test_changepoint.py`, `test_changepoint_sampler.py`
