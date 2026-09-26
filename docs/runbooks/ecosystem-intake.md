# Runbook: Ecosystem Intake (C-10)

Operational guide for `POST /webhooks/ecosystem/{source_name}`. Per round-5 niche filter: this endpoint is for **internal Bodai components only** (`git-monitor`, `crontroller`, `ops-bridge`). External systems (GitHub, Stripe, etc.) publish to Akosha directly — not through Mahavishnu. Per ADR 0001.

The endpoint sanitizes via `DataSanitizeAction` and forwards via `safe_publish`. **No HMAC, no nonce, no DLQ, no registration tool.** Rollback signal: `webhook_intake.enabled: false` returns 503.

## Scenario 1: Source not in allowlist (404)

**Symptoms:**
- `ecosystem_intake_total{source="<unknown>", result="not_found"}` rate increases
- Operators see 404s in their HTTP logs for `/webhooks/ecosystem/<unknown>`

**Diagnosis:**
1. Identify the source: `grep '<unknown>' /var/log/mahavishnu/access.log | tail -5`
2. Check whether the source is a legitimate Bodai component that should be added to the allowlist
3. Check whether the source is an external system probing for endpoints (potential security concern)
4. Check whether the path is a typo: `<unknown>` might be a misspelling of `git-monitor` or `crontroller`

**Recovery:**
1. **If legitimate component**: add to `ALLOWED_SOURCES` in `mahavishnu/webhooks/ecosystem_intake.py` AND to `webhook_intake.allowed_sources` in `settings/mahavishnu.yaml`. The endpoint reads both lists (default + override).
2. **If typo**: notify the operator who is sending to the wrong path. No code change.
3. **If external system probing**: log the IP address; consider blocking at the load-balancer level. **Do NOT add external systems to the allowlist** — they should publish to Akosha directly per the niche filter.
4. **If attack**: check Akosha for `anomaly.detected` events from this source; consider rate-limiting at the FastAPI middleware level.

**Verification:**
- `ecosystem_intake_total{source="<unknown>", result="not_found"}` returns to 0 within 5 minutes (or stays at 0 for attacks, which is the desired state)
- New legitimate source is added to allowlist; tests pass

## Scenario 2: Payload too large (413)

**Symptoms:**
- `ecosystem_intake_total{result="too_large"}` rate increases
- HTTP 413 in access logs
- Source system reports payload-too-large errors

**Diagnosis:**
1. Check current `max_payload_size_bytes` setting: `cat settings/mahavishnu.yaml | grep max_payload_size`
2. Identify the oversized payloads: `grep 'too_large' /var/log/mahavishnu/access.log | head -5`
3. Check what changed: did the source system start sending bigger payloads (new feature) or is one-off large data?

**Recovery:**
1. **If legitimate growth**: increase `webhook_intake.max_payload_size_bytes` (default 1 MiB; max depends on memory headroom)
2. **If single oversized event**: contact the source operator; ask them to chunk the payload
3. **If attack**: the 413 is correct behavior. Add rate-limiting if not already present.

**Verification:**
- Oversized source's `result="accepted"` rate returns to baseline
- No 413s in access logs within 1 hour

## Scenario 3: `safe_publish` returns False (no Akosha publisher configured)

**Symptoms:**
- `ecosystem_intake_total{result="queued_no_publisher"}` rate increases
- Operators see HTTP 202 with `{"status": "queued_no_publisher"}` in responses
- `eventbridge_publish_total{result="skip"}` rate increases
- No events arrive in Akosha

**Diagnosis:**
1. Check whether the EventBridgePublisher is wired: `curl http://localhost:8680/health | jq .eventbridge_publisher`
2. Check `mahavishnu/factories.py:_wire_eventbridge_publisher` is called at boot
3. Check Akosha reachability: `curl http://localhost:8682/health` (Akosha is at port 8682 per ecosystem port table)

**Recovery:**
1. **If publisher not wired**: check `settings/webhook_intake.yaml` for `eventbridge_publisher` configuration; restart Mahavishnu to re-run `_wire_eventbridge_publisher`
2. **If Akosha unreachable**: bring Akosha back up; `safe_publish` will succeed on retry
3. **If misconfigured**: fix the config; restart Mahavishnu

**Verification:**
- `eventbridge_publish_total{result="success"}` rate >0 within 5 minutes of recovery
- `ecosystem_intake_total{result="queued_no_publisher"}` rate returns to 0

## Sanitization rules

The endpoint masks the following fields per `DataSanitizeAction` config:

| Field name (substring match) | Action |
|---|---|
| `Authorization` | mask |
| `token` | mask |
| `key` | mask |
| `secret` | mask |

If new credential-like fields are added to a payload, **add them to the `mask_fields` list** in `mahavishnu/webhooks/ecosystem_intake.py` AND add an integration test in `tests/integration/test_ecosystem_intake.py`.

## Related

- [docs/adr/0001-mahavishnu-niche.md](../adr/0001-mahavishnu-niche.md) — niche filter (external systems publish to Akosha, not Mahavishnu)
- [docs/plans/2026-09-26-impl-C-10-ecosystem-intake.md](../plans/2026-09-26-impl-C-10-ecosystem-intake.md) — implementation plan
- [docs/slos/2026-09-26-wireup-ecosystem-intake.md](../slos/2026-09-26-wireup-ecosystem-intake.md) — SLO targets
