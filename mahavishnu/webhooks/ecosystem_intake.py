"""Radically-simplified ecosystem event intake.

Per ``feedback-no-backwards-compat-pre-1.0`` and the niche filter
(see ``docs/adr/0001-mahavishnu-niche.md``):
- No HMAC, no nonce, no DLQ, no registration tool, no multi-secret rotation.
- Single endpoint ``POST /webhooks/ecosystem/{source_name}``.
- ``source_name`` must be in :data:`ALLOWED_SOURCES` (configured default)
  OR in ``webhook_intake.allowed_sources`` settings (operator extension).
- Body is parsed as JSON, sanitized via :class:`DataSanitizeAction`, and
  forwarded via :func:`safe_publish`.

External systems (GitHub, Stripe, etc.) publish to Akosha directly via
the standard Akosha publisher — NOT through this endpoint. Crackerjack's
``review-pr`` skill subscribes to an Akosha pattern, not to this
endpoint.

Req: REQ-016 (C-10 simplified ecosystem intake)
"""  # req: REQ-016
from __future__ import annotations

import json
import time
from typing import Final
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from oneiric.actions.data import DataSanitizeAction
from oneiric.core.logging import get_logger

from mahavishnu.core._producer_metrics import (
    ECOSYSTEM_INTAKE_SANITIZE_DURATION,
    ECOSYSTEM_INTAKE_TOTAL,
)
from mahavishnu.core.config import get_settings
from mahavishnu.core.errors import EcosystemIntakeError
from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.core.events.publisher import safe_publish

router = APIRouter()
ALLOWED_SOURCES: Final[frozenset[str]] = frozenset(
    {"git-monitor", "crontroller", "ops-bridge"}
)
"""Default allowlist. Operators extend via ``webhook_intake.allowed_sources``
in settings; the endpoint reads both lists (union)."""
logger = get_logger(__name__)


@router.post("/webhooks/ecosystem/{source_name}")
async def ecosystem_intake(source_name: str, request: Request) -> JSONResponse:
    """Accept ecosystem events from configured sources.

    Returns:
        202 Accepted — event sanitized and forwarded to Akosha
        404 Not Found — ``source_name`` not in allowlist
        413 Payload Too Large — body exceeds ``max_payload_size_bytes``
        503 Service Unavailable — ``webhook_intake.enabled`` is False
        500 Internal Server Error — sanitize failed (logged, no exception leaks)
    """
    settings = get_settings()
    configured_sources = settings.webhook_intake.allowed_sources or frozenset()
    if source_name not in ALLOWED_SOURCES and source_name not in configured_sources:
        ECOSYSTEM_INTAKE_TOTAL.labels(source=source_name, result="not_found").inc()
        return JSONResponse({"status": "not_found"}, status_code=404)
    if not settings.webhook_intake.enabled:
        ECOSYSTEM_INTAKE_TOTAL.labels(source=source_name, result="disabled").inc()
        return JSONResponse({"status": "disabled"}, status_code=503)
    payload = await request.body()
    if len(payload) > settings.webhook_intake.max_payload_size_bytes:
        ECOSYSTEM_INTAKE_TOTAL.labels(source=source_name, result="too_large").inc()
        return JSONResponse({"status": "too_large"}, status_code=413)
    try:
        # FIX round-8 (Tier 4): parse JSON before sanitize, then sanitize
        # the dict. Sanitizing the raw string would force consumers (C-13)
        # to read ``payload.data.pr_url`` (dict access) against a string,
        # raising AttributeError. Parse first → sanitize the dict → emit
        # a dict payload.
        try:
            raw_body = json.loads(payload.decode(errors="replace"))
        except json.JSONDecodeError:
            # Non-JSON body — preserve the raw text under ``_raw`` so the
            # sanitize call still receives a dict.
            raw_body = {"_raw": payload.decode(errors="replace")}

        if not isinstance(raw_body, dict):
            raw_body = {"_value": raw_body}

        sanitize_start = time.perf_counter()
        sanitized = await DataSanitizeAction().execute({
            "data": raw_body,
            "mask_fields": ["Authorization", "token", "key", "secret"],
        })
        ECOSYSTEM_INTAKE_SANITIZE_DURATION.observe(
            time.perf_counter() - sanitize_start
        )

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
        ECOSYSTEM_INTAKE_TOTAL.labels(source=source_name, result="error").inc()
        raise
    except Exception:
        # Catch Exception, not BaseException — CancelledError propagates.
        logger.exception(
            "ecosystem intake failed", extra={"source": source_name}
        )
        ECOSYSTEM_INTAKE_TOTAL.labels(source=source_name, result="error").inc()
        return JSONResponse({"status": "error"}, status_code=500)
    result_label = "accepted" if published else "queued_no_publisher"
    ECOSYSTEM_INTAKE_TOTAL.labels(source=source_name, result=result_label).inc()
    return JSONResponse({"status": result_label}, status_code=202)


__all__ = ["ALLOWED_SOURCES", "router"]
