"""Durable webhook receiver.

Validates inbound webhook payloads against the substrate-managed
:class:`dhara.schema.WebhookIngress` schema and persists the typed
record via :func:`dhara.put` so downstream consumers (M-WEBHOOK-DURABLE)
can pick it up durably.

This module is intentionally separate from :mod:`mahavishnu.webhooks.router`
(OpenClaw-typed sweep / workflow endpoints) — the receiver accepts an
untyped JSON body, validates it against the cross-system durable schema,
and returns a 202 once the record is enqueued. The router keeps its
typed-Pydantic contract for OpenClaw's per-endpoint payload shapes.
"""

from __future__ import annotations

import dhara
from dhara.schema import SchemaValidationError, validate
from fastapi import FastAPI, HTTPException, status
from oneiric.core.logging import get_logger

# Substrate-compat: `dhara.put` is not a module-level attribute on the
# installed dhara package — real callers pass a Dhara client instance
# (e.g. `await self.dhara.put(...)`) or import a configured binding into
# `dhara.put` at integration time. Tests substitute via
# `monkeypatch.setattr("receiver.dhara.put", ...)`; the hasattr guard
# lets that patch land even when the host package has not injected a
# binding.
if not hasattr(dhara, "put"):
    dhara.put = None  # type: ignore[attr-defined]

logger = get_logger(__name__)

app = FastAPI(
    title="Mahavishnu Webhook Receiver",
    description="Durable ingest endpoint for cross-system webhook payloads.",
    version="1.0.0",
)


@app.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
def receive_webhook(payload: dict[str, object]) -> dict[str, str]:
    """Validate ``payload`` as a ``WebhookIngress`` and persist via ``dhara.put``.

    Returns:
        ``{"status": "accepted", "webhook_id": <validated.webhook_id>}``

    Raises:
        HTTPException: 422 when the payload fails schema validation. The
            underlying :class:`SchemaValidationError` is logged with the
            ``invalid_webhook`` event key (no exception message in ``extra``).
    """
    try:
        validated = validate("webhook_ingress", payload)
    except SchemaValidationError:
        logger.warning(
            "invalid_webhook",
            extra={"source": _safe_source(payload)},
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error_code": "WEBHOOK_VALIDATION_ERROR",
                "message": "payload failed WebhookIngress validation",
            },
        ) from None

    # The registry returns a WebhookIngress for name='webhook_ingress';
    # msgspec.Struct is duck-typed so we read fields directly without an
    # isinstance check (bandit B101 forbids asserts in production).
    webhook_id = validated.webhook_id
    dhara.put(f"webhook-ingress/{webhook_id}/", validated)
    logger.info(
        "webhook_ingress_recorded",
        extra={"webhook_id": webhook_id, "source": validated.source},
    )
    return {"status": "accepted", "webhook_id": webhook_id}


def _safe_source(payload: dict[str, object]) -> str:
    """Return ``payload['source']`` coerced to ``str`` for log-only use.

    Validation has already failed by the time we log, so we cannot trust
    the payload shape; coerce defensively and fall back to ``"unknown"``
    rather than letting a TypeError mask the original error path.
    """
    raw = payload.get("source") if isinstance(payload, dict) else None
    return raw if isinstance(raw, str) else "unknown"


__all__ = ["app", "receive_webhook"]
