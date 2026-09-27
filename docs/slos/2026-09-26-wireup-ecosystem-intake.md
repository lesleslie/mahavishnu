# SLO: Ecosystem Intake (C-10)

## Service

`POST /webhooks/ecosystem/{source_name}` — the simplified ecosystem intake endpoint for **internal Bodai components only**. Per round-5 niche filter: external systems publish to Akosha directly, not through Mahavishnu. Per ADR 0001.

The endpoint sanitizes via `DataSanitizeAction` and forwards via `safe_publish`. **No HMAC, no nonce, no DLQ, no registration tool.**

## SLI

### Latency SLI

`ecosystem_intake_sanitize_duration_seconds` histogram (bucketed: 0.001 to 1.0s):

- **p50 < 10ms**: typical sanitization is regex replacement over JSON
- **p99 < 100ms**: large payloads with many credential fields
- **p99.9 < 1s**: worst-case payloads near `max_payload_size_bytes` (default 1 MiB)

### Availability SLI

`ecosystem_intake_total{result="accepted"} / ecosystem_intake_total`

- **Success rate >99% over 30-day rolling window**
- `result="error"` rate \<0.05/s sustained (per round-4 ops gap-fix)
- `result="not_found"` rate is informational, not part of SLO (sources not in allowlist are correctly rejected)

## SLO Targets

| Metric | Target | Burn-rate alert |
|---|---|---|
| `ecosystem_intake_sanitize_duration_seconds{p99}` | \<100ms | >100ms for 5m → warn; >500ms for 5m → page |
| `ecosystem_intake_total{result="error"}` rate | \<0.05/s sustained | >0.05/s for 5m → Slack + page on-call (per round-4 ops gap-fix) |
| `ecosystem_intake_total{result="accepted"}` rate | >0 (when publishers wired) | rate = 0 for >5m → page (Akosha publisher broken) |
| `eventbridge_publish_total{result="error"}` rate from this endpoint | \<0.01/s | >0.05/s for 5m → page |

## Critical alerts (round-4 ops gap-fix)

1. **`ecosystem_intake_total{result="error"} rate > 0.05/s for 5m`** → Slack + page on-call (per spec)
1. **`eventbridge_publish_total{result="error"} rate > 0.1/s for 5m`** → Slack + page on-call (publish failures)
1. **`ecosystem_intake_total{result="accepted"}` rate = 0 for 5m when sources are sending** → page (publisher broken or config drift)

## Error Budget

- **30-day budget**: 1% × 30 days = 7.2 hours of error rate allowed
- **Burn-rate policy**:
  - 1h burn rate >14.4× → page
  - 6h burn rate >6× → page
  - 24h burn rate >3× → ticket

## Page-after field

- **Initial response**: 5 minutes
- **Update frequency**: every 15 minutes until resolved
- **Resolution target**: 30 minutes for P0; 4 hours for P1

## Rollback signal

`webhook_intake.enabled: false` in `settings/mahavishnu.yaml` returns 503 from the handler. **This does NOT unregister the route** — it remains mounted in OpenAPI docs. To fully remove C-10, `git revert <commit-sha>`. Per the no-backcompat policy, no deprecation window.

## Runbooks

- [docs/runbooks/ecosystem-intake.md](../runbooks/ecosystem-intake.md) — ecosystem-intake scenarios
- [docs/runbooks/on_call_handbook.md](../runbooks/on_call_handbook.md) — escalation procedures

## Related

- [docs/plans/2026-09-26-impl-C-10-ecosystem-intake.md](../plans/2026-09-26-impl-C-10-ecosystem-intake.md)
- [docs/adr/0001-mahavishnu-niche.md](../adr/0001-mahavishnu-niche.md)
