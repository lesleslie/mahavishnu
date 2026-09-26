# C-10: ecosystem event intake (radically simplified — niche-filter scope cut)

**REQ-NNN:** REQ-016 — 200 vs 202 response distinction (kept for C-10 simplified)
**Dropped REQs:** REQ-014 (HMAC + nonce + DLQ), REQ-015 (webhook_register MCP tool) — removed per niche filter
**Risk:** Low (single endpoint; allowlist; sanitize-only; no HMAC, no nonce, no DLQ, no registration tool)
**Blocks:** None directly (C-13's crackerjack review-pr subscribes to Akosha patterns, not to this endpoint)
**Direct-to-main commit:** Yes (per `feedback-no-backwards-compat-pre-1.0` + `bodai-pre-1.0-merge-policy`).
**Status:** Draft — round-4 niche-filter corrections baked in (no HMAC, no nonce, no DLQ, no registration tool, no multi-secret rotation).

## Goal

Provide ONE minimal ecosystem intake endpoint for internal Bodai components (crontroller, git-monitor, ops-bridge) to push events into Mahavishnu. **External systems (GitHub, Stripe, etc.) publish to Akosha directly via the standard Akosha publisher — NOT through Mahavishnu.** Crackerjack's `review-pr` skill subscribes to an Akosha pattern, not to a Mahavishnu HTTP endpoint.

**Why this is Mahavishnu-shaped**: per `docs/adr/0001-mahavishnu-niche.md`, Mahavishnu is an LLM control plane + repo orchestrator + multi-engine + harness-agnostic. The original C-10 (HMAC + nonce + DLQ + multi-secret rotation + register MCP tool) was Conductor-shape scope that competes with the source tool's niche. **Replace with the minimal viable intake below.**

**No HMAC.** No nonce. No DLQ. No registration MCP tool. No multi-secret support. Body is sanitized via Oneiric `DataSanitizeAction` and forwarded via `safe_publish`.

## Pre-flight checks

1. **C-5 has landed.** `safe_publish()` is available; the singleton publisher pattern is wired.
2. **C-1 has landed.** `webhook_intake:` settings section exists with `enabled`, `bind_port`, `max_payload_size_bytes`, `allowed_sources`.
3. **No `webhook_register` MCP tool exists** (`grep -r "webhook_register" mahavishnu/mcp/tools/` returns nothing). If found, this is a stale reference — drop it.
4. **No `WebhookSecretMissingError` or `WebhookAuthError`** are added in this commit. The legacy `WebhookAuthError` may exist for OpenClaw routes (preserved); C-10 does NOT introduce new auth exceptions.
5. **`oneiric.actions.data.DataSanitizeAction` importable** with the payload shape `{"data": str, "mask_fields": list[str]}` → returns `{"data": <sanitized>}`.

## File-by-file changes

### 1. `mahavishnu/webhooks/ecosystem_intake.py` — new file (~60 LoC)

```python
"""Radically-simplified ecosystem event intake.

Per feedback-no-backwards-compat-pre-1.0 and the niche filter (see docs/adr/0001):
- No HMAC, no nonce, no DLQ, no registration tool, no multi-secret rotation.
- Single endpoint POST /webhooks/ecosystem/{source_name}.
- Source must be in a configured allowlist (NOT a registered dynamic source).
- Body is sanitized via DataSanitizeAction and forwarded via safe_publish.

External systems (GitHub, Stripe) publish to Akosha directly via standard Akosha publisher.
Crackerjack's review-pr skill subscribes to an Akosha pattern.
"""
from __future__ import annotations

import uuid
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from oneiric.actions.data import DataSanitizeAction
from oneiric.core.logging import get_logger

from mahavishnu.core.config import get_settings
from mahavishnu.core.errors import EcosystemIntakeError
from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.core.events.publisher import safe_publish

router = APIRouter()
ALLOWED_SOURCES: Final[frozenset[str]] = frozenset(
    {"git-monitor", "crontroller", "ops-bridge"}
)
"""Default allowlist. Operators extend via webhook_intake.allowed_sources in settings."""
logger = get_logger(__name__)


@router.post("/webhooks/ecosystem/{source_name}")
async def ecosystem_intake(source_name: str, request: Request) -> JSONResponse:
    """Accept ecosystem events from configured sources.

    Returns:
        202 Accepted — event sanitized and forwarded to Akosha
        404 Not Found — source_name not in allowlist
        413 Payload Too Large — body exceeds max_payload_size_bytes
        503 Service Unavailable — webhook_intake.enabled is False
        500 Internal Server Error — sanitize failed (logged, no exception leaks)
    """
    if source_name not in ALLOWED_SOURCES:
        return JSONResponse({"status": "not_found"}, status_code=404)
    settings = get_settings()
    if not settings.webhook_intake.enabled:
        return JSONResponse({"status": "disabled"}, status_code=503)
    payload = await request.body()
    if len(payload) > settings.webhook_intake.max_payload_size_bytes:
        return JSONResponse({"status": "too_large"}, status_code=413)
    try:
        # FIX round-8 (Tier 4): the actual code path must produce structured
        # dict payloads, not sanitized strings. The previous code passed
        # `payload.decode(errors="replace")` (a STRING) to DataSanitizeAction,
        # which returns a dict with `{"data": <sanitized-string>}` — but
        # consumers (C-13) read `payload.data.pr_url` (dict access). This
        # raises AttributeError at consumer side. The fix: parse JSON before
        # sanitize, then sanitize the dict, then emit a dict payload.
        try:
            raw_body = json.loads(payload.decode(errors="replace"))
        except json.JSONDecodeError:
            # Non-JSON body — sanitize as text but emit empty data dict
            raw_body = {"_raw": payload.decode(errors="replace")}

        sanitized = await DataSanitizeAction().execute({
            "data": raw_body,
            "mask_fields": ["Authorization", "token", "key", "secret"],
        })
        # Schema:
        #   {
        #     "source": "<source_name>",
        #     "data": {
        #       # For git-monitor events:
        #       "pr_url": str,
        #       "branch": str,
        #       "commit_sha": str,
        #       # For crontroller / ops-bridge events: extend as needed
        #     },
        #   }
        envelope = create_event_envelope(
            event_type="ecosystem.event.received",
            payload={
                "source": source_name,
                "data": sanitized.get("data", {}),
            },
            source=f"mahavishnu.webhooks.ecosystem.{source_name}",
            correlation_id=str(uuid4()),
            metadata={"severity": "info"},
        )
        published = await safe_publish(envelope)
    except EcosystemIntakeError:
        raise
    except Exception:
        # Catch Exception, not BaseException — CancelledError propagates
        logger.exception("ecosystem intake failed", extra={"source": source_name})
        return JSONResponse({"status": "error"}, status_code=500)
    return JSONResponse(
        {"status": "accepted" if published else "queued_no_publisher"},
        status_code=202,
    )
```

### 2. `mahavishnu/webhooks/receiver.py` — register the new route

Find the existing `receiver.py` (per CLAUDE.md it exists alongside OpenClaw webhook handling). Add the new router alongside existing routes:

```python
from mahavishnu.webhooks.ecosystem_intake import router as ecosystem_router

# ... existing OpenClaw router registration ...
app.include_router(ecosystem_router)
```

### 3. `mahavishnu/core/errors.py` — add `EcosystemIntakeError` exception

Append after the existing exception classes:

```python
class EcosystemIntakeError(MahavishnuError):
    """Raised by the ecosystem intake endpoint when sanitization or
    envelope construction fails. Returns 500 to the caller."""
```

This is the ONLY new exception class added by C-10. The exception is intentional and minimal — no `WebhookAuthError`, `WebhookSecretMissingError`, or `WebhookReplayError` additions.

### 4. `mahavishnu/core/metrics.py` — add 2 metrics

```python
ECOSYSTEM_INTAKE_TOTAL = Counter(
    "ecosystem_intake_total",
    "Total ecosystem intake requests, labeled by source and result.",
    labelnames=["source", "result"],
    # result ∈ {accepted, queued_no_publisher, not_found, disabled, too_large, error}
)

ECOSYSTEM_INTAKE_SANITIZE_DURATION = Histogram(
    "ecosystem_intake_sanitize_duration_seconds",
    "Time to sanitize the request body via DataSanitizeAction.",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)
```

Increment `ECOSYSTEM_INTAKE_TOTAL.labels(source=source_name, result="accepted")` on success; `result="not_found"`, `result="disabled"`, `result="too_large"`, `result="error"` on the respective paths.

## Tests

### 5. `tests/integration/test_ecosystem_intake.py` — new file (~250 LoC)

```python
"""Integration tests for the ecosystem intake endpoint.

Per round-4 simplification: 4 happy/sad path tests + 1 unit test for DataSanitizeAction.
"""
from __future__ import annotations

import json

import pytest


@pytest.mark.req(["REQ-016"])
class TestAllowedSource202:
    async def test_post_returns_202_when_source_allowed(
        self, ecosystem_intake_test_client, safe_publisher_monkeypatch
    ) -> None:
        payload = {"key": "value", "Authorization": "Bearer leak"}
        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/git-monitor",
            json=payload,
        )
        assert response.status_code == 202
        assert response.json()["status"] == "accepted"


@pytest.mark.req(["REQ-016"])
class TestDisallowedSource404:
    async def test_post_returns_404_when_source_not_in_allowlist(
        self, ecosystem_intake_test_client
    ) -> None:
        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/external-attacker",
            json={"data": "x"},
        )
        assert response.status_code == 404


@pytest.mark.req(["REQ-016"])
class TestOversizedPayload413:
    async def test_post_returns_413_when_payload_too_large(
        self, ecosystem_intake_test_client, monkeypatch
    ) -> None:
        # Patch max_payload_size_bytes to 100 bytes for the test
        from mahavishnu.core.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(
            settings.webhook_intake, "max_payload_size_bytes", 100
        )
        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/git-monitor",
            content=b"x" * 200,  # 200 bytes > 100 byte limit
            headers={"Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 413


@pytest.mark.req(["REQ-016"])
class TestSanitizationStripsAuth:
    async def test_authorization_field_is_masked(
        self, ecosystem_intake_test_client, safe_publisher_monkeypatch
    ) -> None:
        payload = {"Authorization": "Bearer SECRET_TOKEN"}
        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/git-monitor",
            json=payload,
        )
        assert response.status_code == 202
        # Verify the captured envelope has masked data
        from mahavishnu.core.events.publisher import _capture_singleton
        assert len(_capture_singleton) == 1
        envelope = _capture_singleton[0]
        sanitized_data = envelope["payload"]["data"]
        assert "SECRET_TOKEN" not in sanitized_data
        assert "***MASKED***" in sanitized_data or "REDACTED" in sanitized_data


@pytest.mark.req(["REQ-016"])
class TestDisabledWhenConfigured:
    async def test_post_returns_503_when_intake_disabled(
        self, ecosystem_intake_test_client, monkeypatch
    ) -> None:
        from mahavishnu.core.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings.webhook_intake, "enabled", False)
        response = ecosystem_intake_test_client.post(
            "/webhooks/ecosystem/git-monitor",
            json={"key": "value"},
        )
        assert response.status_code == 503


@pytest.mark.req(["REQ-016"])
class TestDataSanitizeActionUnit:
    async def test_action_payload_shape(self) -> None:
        """Verify the Oneiric action payload shape matches the spec."""
        from oneiric.actions.data import DataSanitizeAction
        result = await DataSanitizeAction().execute({
            "data": "Authorization: Bearer ABC\nkey: xyz\n",
            "mask_fields": ["Authorization", "key"],
        })
        assert "data" in result
        assert "Bearer ABC" not in result["data"]
        assert "xyz" not in result["data"]
```

## Crackerjack verification

```bash
uv run pytest tests/integration/test_ecosystem_intake.py -v
uv run pytest --cov=mahavishnu --cov-fail-under=89.01682905225863
uv run crackerjack run -p minor
```

## Acceptance criteria (decisive pass/fail)

1. `mahavishnu/webhooks/ecosystem_intake.py` exists with the single endpoint.
2. `ALLOWED_SOURCES` is a `frozenset[str]` containing `{"git-monitor", "crontroller", "ops-bridge"}`.
3. POST to `/webhooks/ecosystem/git-monitor` returns 202.
4. POST to `/webhooks/ecosystem/<not-in-allowlist>` returns 404.
5. POST with body > `max_payload_size_bytes` returns 413.
6. POST with `webhook_intake.enabled=false` returns 503.
7. `Authorization` field in body is masked (NOT echoed verbatim).
8. **No HMAC header is checked** (no `X-Webhook-Signature` parsing anywhere).
9. **No nonce tracking** (no DB writes to a nonces table).
10. **No DLQ** (no `DeadLetterQueue` import in the intake path).
11. **No `webhook_register` MCP tool** (`grep -r "webhook_register" mahavishnu/mcp/tools/` returns nothing).
12. `python scripts/audit_requirements.py --json` reports REQ-016 wired.
13. `crackerjack run` passes; coverage gate holds.

## Rollback / recovery narration

Per `feedback-no-backwards-compat-pre-1.0`:
- No dual-mode. The endpoint either works (200/202) or returns 503/404/413/500.
- Rollback is `webhook_intake.enabled: false` in `settings/mahavishnu.yaml` (added in C-1). All requests return 503.
- The endpoint is mounted only at `/webhooks/ecosystem/{source_name}` — legacy OpenClaw routes are NOT affected.

If a downstream consumer depends on the OLD C-10 surface (HMAC + nonce + DLQ + register tool), they break immediately. Per the niche filter, this is acceptable: external systems publish to Akosha directly; internal Bodai components use the simple allowlist.

## Observability added

Two new Prometheus metrics (covered above):

- `ecosystem_intake_total{source, result}` — Counter
- `ecosystem_intake_sanitize_duration_seconds` — Histogram

Operators alert on `rate(ecosystem_intake_total{result="error"}[5m]) > 0.05` (per spec). Sanitize duration p99 should be <100ms.

## Health aggregation

`pool_health` reports `degraded` if `safe_publish` returns False >10% over 5m. This is wired via the existing `EVENTBRIDGE_PUBLISH_TOTAL{result="skip"}` metric from C-5 — no new health check needed.

## Implementation notes / gotchas

- **`ALLOWED_SOURCES` is hardcoded.** Operators can extend via `webhook_intake.allowed_sources` in settings (added in C-1); the endpoint reads both lists. The hardcoded `frozenset` is the **minimum default** for safety — if settings are missing, only the three internal sources work.
- **No `HMAC` validation.** This is per the niche filter. Internal Bodai components trust each other; external systems publish to Akosha directly.
- **No nonce, no DLQ.** Rejected duplicates are not tracked — the source system is responsible for retry semantics.
- **Sanitization is best-effort.** `DataSanitizeAction` masks fields matching `mask_fields` patterns; it is not a substitute for proper auth.
- **`correlation_id` is a fresh `uuid4()` per request.** Downstream Akosha events use this for tracing.
- **`safe_publish` returning False is not an error.** The endpoint returns 202 with `{"status": "queued_no_publisher"}` — the event was constructed correctly, just not forwarded because no publisher is configured (test mode or Akosha down).
- **`metadata={"severity": "info"}`** — the default severity for ecosystem events. Operators can tune per source via settings.
- **`source=f"mahavishnu.webhooks.ecosystem.{source_name}"`** — follows the Akosha envelope source convention.
- **The `frozenset` literal is `Final`** to prevent accidental mutation. Python doesn't enforce `Final` at runtime but type checkers (ty) flag violations.

## Companion CLI (per spec)

`mahavishnu ecosystem list [--json]` — shows allowlist source names. Implementation is a one-line CLI that reads `ALLOWED_SOURCES` and prints. Out of scope for C-10 itself (no test required); add as a follow-up commit.

## Runbook (per spec)

`docs/runbooks/ecosystem-intake.md` — 3 scenarios: (1) source not in allowlist, (2) sanitize failure, (3) safe_publish returns False. Out of scope for C-10 itself; add as a follow-up commit.

## Files modified (summary)

| File | Action | LoC |
|---|---|---|
| `mahavishnu/webhooks/ecosystem_intake.py` | create | ~70 |
| `mahavishnu/webhooks/receiver.py` | edit (register new router) | +5 |
| `mahavishnu/core/errors.py` | edit (add `EcosystemIntakeError`) | +5 |
| `mahavishnu/core/metrics.py` | edit (add 2 metrics) | +15 |
| `tests/integration/test_ecosystem_intake.py` | create | +250 |
