# Mahavishnu Drift Detection Runbook

**Owner:** bodai-orchestrator
**Created:** 2026-09-10
**Last updated:** 2026-09-10
**Triggered by:** `mahavishnu.observability.drift_detected` OTel span
**Spec:** [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md` §6 Phase 6](../plans/2026-09-10-bodai-math-initiatives-tier1.md)

## What this runbook is for

When the CUSUM / Page-Hinkley change-point detector on a
Mahavishnu observability metric (default: `pool_queue_depth`)
fires, you see:

- An OTel span `mahavishnu.observability.drift_detected` with
  attributes `metric_name`, `detector`, `score_high`,
  `score_low`, `score`, `threshold`, `samples_since_reset`,
  `direction` (`up` / `down`), `severity` (`minor` /
  `moderate` / `critical`), plus (for two-stage confirmed alerts)
  `samples_since_warning` and `confirm_detector`.
  `samples_since_warning` is the operator's only direct measure
  of how stale the warning was before confirmation;
  `confirm_detector` indicates whether the underlying confirm
  detector is CUSUM (`"cusumdetector"`) or Page-Hinkley
  (`"pagehinkleydetector"`).
- A structured log line at WARNING level on the same shape.
- When the 3-sigma reference detector is enabled (default), an
  independent `three_sigma_anomaly` log line for the same
  metric (if both detectors fire, you see two signals).

## What to check first (≤ 5 minutes)

1. **Is the drift real or transient?** Look at
   `mahavishnu.observability.metric_samples` (Dhara table) for
   the last 60 minutes of the affected metric. A real drift is
   sustained; a transient is a single spike that recovered.
1. **What is the severity?** (R3-H4 / round-4 L6: thresholds are
   symbolic — `2 × changepoint.threshold` and `4 × changepoint.threshold`.
   Severity classifier is `_classify_drift_severity(score, threshold)`
   in `mahavishnu/core/observability.py`. The OTel span attribute is
   authoritative; this runbook states the policy.)
   - `minor` (score < 2 × threshold): typical 0.5-σ shift. Safe
     to investigate at low urgency.
   - `moderate` (2 × threshold ≤ score < 4 × threshold): a 0.7-σ
     shift territory. Investigate within an hour.
   - `critical` (score ≥ 4 × threshold): a 1-σ or larger shift.
     Page the on-call; the metric is materially off-baseline.
1. **Is the threshold current?** Check
   `changepoint.target_metric` and the recent
   `effective_selector` field on the routing-decision record.
   If operators recently changed the routing strategy, the
   in-control mean of the metric shifted — that's a real
   drift, not a bug.
1. **Is this the first time?** If the same metric has fired
   twice in the last 24 hours, escalate to the on-call even if
   the current severity is `minor`.

## When to silence vs escalate

- **Silence (15 minutes)** when:
  - The severity is `minor` and the affected metric is one
    operator can correct in seconds (e.g. a pool with one
    bad worker).
  - The drift coincides with a known deployment; the
    `remediation` step is to wait for the new steady state and
    re-check.
- **Escalate** when:
  - Severity is `moderate` or `critical`.
  - The same metric has fired twice in 24 hours.
  - The drift correlates with user-visible symptoms (failed
    workflows, dropped tasks, budget alerts).
  - The drift coincides with a Mahavishnu restart, a config
    change, or a pool topology change.

## Known operator caveats (round-2 update)

Before acting on a drift signal, calibrate expectations against
these settings — they were the deliberate output of the round-2
empirical sweep:

### Two-stage warn/confirm semantics (RECOMMENDED operator choice post-Phase-8)

When `changepoint.detector: "two_stage"` is selected (the recommended
operator choice post-Phase-8; opt-in via `changepoint.detector: "two_stage"`),
the change-point pipeline emits two distinct OTel signals:

- `mahavishnu.observability.drift_warning` — fired by the low-threshold
  warn detector (`warn_threshold=8.0`). Operator-visible soft signal.
  Fires within ~28 samples (median) on a 0.5σ shift; emits ~30
  warnings per 10,080 quiet samples on stationary noise (this is by
  design — warnings are cheap).
- `mahavishnu.observability.drift_detected` — fired by the high-threshold
  confirm detector (`confirm_threshold=14.0`) WITHIN
  `confirm_window_samples=100` of a warning. Page-worthy hard signal.
  Fires within ~50 samples (median) on a 0.5σ shift; emits ~0 confirmed
  alerts per 10,080 quiet samples on stationary noise.

The §1 latency gate (`median ≤ 30 samples for 0.5σ shift`) is checked
on warnings. The §7 FP gate (`≤ 2 fires per 10,080 samples`) is checked
on confirmed alerts. **Both gates are achievable simultaneously**
under the two-stage architecture — see
`docs/audits/2026-09-10-changepoint-validation.md` for the empirical
numbers.

Operator action by signal:
- **`drift_warning`** — investigate at low urgency. The detector is
  saying "something looks unusual." Most warnings are noise; some
  are precursors to confirmed alerts within a few hundred samples.
  Use `mahavishnu.observability.drift_warning_total` (Prometheus) to
  monitor the warning rate. If it spikes on stationary traffic, the
  warn threshold may be too sensitive for the workload.
- **`drift_detected`** — page-worthy. The detector is saying "two
  independent tests agree the metric has shifted." Open an incident
  per the L2/L3 escalation paths below.

### Legacy single-detector mode (backwards compat)

For operators preferring the original Phase 6 single-CUSUM behavior,
`changepoint.detector: "cusum"` (the Phase 8 default) runs the
single-detector pipeline and inherits the §1/§7 trade-off documented
in the round-2 review: median latency on 0.5σ is ~50 samples (relaxed
from the spec's aspirational 30) at the production-tuned defaults
(`slack=0.25, threshold=14.0`). The single-detector mode is
appropriate when operators want one signal type only and can tolerate
either the relaxed latency bound OR the relaxed FP bound. The
two-stage mode supersedes this for production use.

### `target_mean` for raw-count metrics

The default `target_mean = 0.0` is only valid for normalized metrics.
For raw-count metrics like `pool_queue_depth`, operators MUST set an
explicit in-control mean (e.g. `target_mean: 4.0` for a typical
workload). Otherwise the detector accumulates on baseline traffic
and fires within ~30 samples on any non-zero pool_queue_depth.
The detector supports `target_mean_auto: true` to derive the mean
from the sampler's rolling baseline.

### `MAHAVISHNU_INSTANCE_ID` env var

In multi-instance deployments (e.g. 3 Mahavishnu processes behind
a load balancer), set `MAHAVISHNU_INSTANCE_ID=<unique-id>` per
deployment. This becomes the `instance_id` attribute on the
`drift_detected` OTel span, letting you disambiguate which Mahavishnu
process fired the alert. Without it, all instances emit
`instance_id="default"` and you cannot tell them apart.

In production systemd units:

```
Environment=MAHAVISHNU_INSTANCE_ID=mahavishnu-prod-east-1
```

Or in `settings/local.yaml` per environment.

### `host` attribute

The `host` OTel span attribute is `socket.gethostname()`. On most
cloud platforms this is the instance ID. If you ship OTel data to a
shared multi-tenant backend, hash or override this via
`OTEL_RESOURCE_ATTRIBUTES` to avoid leaking infrastructure names.

## Cross-repo gap-period guidance

Until Phase D (the cross-repo Akosha wiring per
[`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md` §7](../plans/2026-09-10-bodai-math-initiatives-tier1.md))
lands, the Mahavishnu drift signal and Akosha's
`akosha_detect_anomalies` are independent control planes for the
same conceptual metric. When `mahavishnu.observability.drift_detected`
fires, also check `mcp__akosha__akosha_detect_anomalies` on the
same metric class.

Order of checks:

1. **Mahavishnu** for sub-5-minute signal (Mahavishnu fires
   fast on the in-process metric; Akosha's Z-score is windowed
   over a longer span).
1. **Akosha** for 5-30 minute ecosystem-wide correlation
   (Akosha reads the same metric from a wider lens —
   multi-pool, multi-component).
1. **Upstream investigation** when both fire within 30
   minutes: look at the upstream dependency (worker runtime,
   pool topology, config change).

This is the practical answer to the two-control-plane gap
during the first 6-8 weeks of Phase 8's production operation.

## Post-restart re-warmup window

After any Mahavishnu restart, treat the next 24 hours as
re-warmup. Do not act on drift detection signals during this
window.

CUSUM warmup state is per-process; a restart at hour 47 of a
72-hour slow drift will reset to baseline and likely miss the
drift entirely. Operators can either:

- Accept that the post-restart 24-hour window is a
  re-warmup period (no detector events are actioned).
- Or, when planning a known restart during a drift incident,
  manually export the detector state pre-restart and
  re-import post-restart (not yet implemented in Tier 1).

## Escalation paths

- **L1 (operator on-call):** severity `minor`, first fire in
  24h. Read this runbook; check the metric_samples table.
- **L2 (platform team):** severity `moderate`, or second fire
  in 24h. Open an incident in the platform Slack channel;
  link the OTel trace.
- **L3 (incident response):** severity `critical`, or third
  fire in 24h, or correlated with user-visible symptoms.
  Page the on-call rotation; open a Grafana incident.

## Related

- Tier 1 plan §6 Phase 6: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) §6
- Feature tracking: [`docs/feature-tracking/2026-09-10-observability-changepoint.md`](../feature-tracking/) (added in Phase 8)
- Eligibility script: [`scripts/feature_eligibility.py`](../../scripts/feature_eligibility.py) (Phase 9 — fires when the multi-metric trigger accumulates ≥ 3 distinct operator requests in 30 days)
