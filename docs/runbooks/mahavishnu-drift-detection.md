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

* An OTel span `mahavishnu.observability.drift_detected` with
  attributes `metric_name`, `detector`, `score_high`,
  `score_low`, `score`, `threshold`, `samples_since_reset`,
  `direction` (`up` / `down`), and `severity` (`minor` /
  `moderate` / `critical`).
* A structured log line at WARNING level on the same shape.
* When the 3-sigma reference detector is enabled (default), an
  independent `three_sigma_anomaly` log line for the same
  metric (if both detectors fire, you see two signals).

## What to check first (≤ 5 minutes)

1. **Is the drift real or transient?** Look at
   `mahavishnu.observability.metric_samples` (Dhara table) for
   the last 60 minutes of the affected metric. A real drift is
   sustained; a transient is a single spike that recovered.
2. **What is the severity?**
   - `minor` (score < 2 × threshold, default score < 16): typical
     0.5-σ shift. Safe to investigate at low urgency.
   - `moderate` (2 × threshold ≤ score < 4 × threshold, score 16-32):
     a 0.7-σ shift territory. Investigate within an hour.
   - `critical` (score ≥ 4 × threshold, score ≥ 32): a 1-σ or
     larger shift. Page the on-call; the metric is materially
     off-baseline.
3. **Is the threshold current?** Check
   `changepoint.target_metric` and the recent
   `effective_selector` field on the routing-decision record.
   If operators recently changed the routing strategy, the
   in-control mean of the metric shifted — that's a real
   drift, not a bug.
4. **Is this the first time?** If the same metric has fired
   twice in the last 24 hours, escalate to the on-call even if
   the current severity is `minor`.

## When to silence vs escalate

* **Silence (15 minutes)** when:
  - The severity is `minor` and the affected metric is one
    operator can correct in seconds (e.g. a pool with one
    bad worker).
  - The drift coincides with a known deployment; the
    `remediation` step is to wait for the new steady state and
    re-check.
* **Escalate** when:
  - Severity is `moderate` or `critical`.
  - The same metric has fired twice in 24 hours.
  - The drift correlates with user-visible symptoms (failed
    workflows, dropped tasks, budget alerts).
  - The drift coincides with a Mahavishnu restart, a config
    change, or a pool topology change.

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
2. **Akosha** for 5-30 minute ecosystem-wide correlation
   (Akosha reads the same metric from a wider lens —
   multi-pool, multi-component).
3. **Upstream investigation** when both fire within 30
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

* Accept that the post-restart 24-hour window is a
  re-warmup period (no detector events are actioned).
* Or, when planning a known restart during a drift incident,
  manually export the detector state pre-restart and
  re-import post-restart (not yet implemented in Tier 1).

## Escalation paths

* **L1 (operator on-call):** severity `minor`, first fire in
  24h. Read this runbook; check the metric_samples table.
* **L2 (platform team):** severity `moderate`, or second fire
  in 24h. Open an incident in the platform Slack channel;
  link the OTel trace.
* **L3 (incident response):** severity `critical`, or third
  fire in 24h, or correlated with user-visible symptoms.
  Page the on-call rotation; open a Grafana incident.

## Related

* Tier 1 plan §6 Phase 6: [`docs/plans/2026-09-10-bodai-math-initiatives-tier1.md`](../plans/2026-09-10-bodai-math-initiatives-tier1.md) §6
* Feature tracking: [`docs/feature-tracking/2026-09-10-observability-changepoint.md`](../feature-tracking/) (added in Phase 8)
* Eligibility script: [`scripts/feature_eligibility.py`](../../scripts/feature_eligibility.py) (Phase 9 — fires when the multi-metric trigger accumulates ≥ 3 distinct operator requests in 30 days)
