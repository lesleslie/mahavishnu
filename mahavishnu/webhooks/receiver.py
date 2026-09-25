"""Durable webhook receiver.

Validates inbound webhook payloads against the locally-owned
:class:`mahavishnu.core.models.persistence.WebhookIngress` schema and
persists the typed record via :func:`mcp.put` so downstream consumers
(M-WEBHOOK-DURABLE) can pick it up durably.

This module is intentionally separate from :mod:`mahavishnu.webhooks.router`
(OpenClaw-typed sweep / workflow endpoints) — the receiver accepts an
untyped JSON body, validates it against the cross-system durable schema,
and returns a 202 once the record is enqueued. The router keeps its
typed-Pydantic contract for OpenClaw's per-endpoint payload shapes.

Substrate contract: ``mcp.put(...)`` is synchronous at the call boundary;
internal async behavior (MemoryOutbox flush, PostgresBackendLock
resolution) is the substrate's concern and is invisible to callers. See
``mcp/docs/superpowers/specs/2026-08-10-substrate-call-boundary-contract.md``
for the cross-portfolio rationale.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
import msgspec
from oneiric.core.logging import get_logger

from mahavishnu.core._mcp_substrate_compat import mcp_calltime
from mahavishnu.core._producer_metrics import COUNTERS
from mahavishnu.core.models.persistence import WebhookIngress

# Producer name used for Prometheus label cardinality.
_PRODUCER_NAME = "webhook_receiver"


def _webhook_durable_v1_enabled() -> bool:
    """Read the WEBHOOK_DURABLE_V1_ENABLED feature flag (default true).

    Returns:
        ``False`` when the operator has set ``WEBHOOK_DURABLE_V1_ENABLED=false``
        (case-insensitive). All other values — including unset — resolve to
        ``True`` so existing deployments default to the durable path.
    """
    return os.environ.get("WEBHOOK_DURABLE_V1_ENABLED", "true").lower() != "false"


logger = get_logger(__name__)

app = FastAPI(
    title="Mahavishnu Webhook Receiver",
    description="Durable ingest endpoint for cross-system webhook payloads.",
    version="1.0.0",
)


# wired: FastAPI route registered on `app` via the @app.post(...) decorator
# immediately above. Mounted at POST /durable-webhooks/webhook by
# mahavishnu/webhooks/__init__.py::mount_durable_webhooks, which mounts
# `app` as a Starlette sub-app at /durable-webhooks on the parent
# FastAPI app. Covered by tests/unit/test_webhooks_mount.py. The audit's
# DECORATOR_REGISTRATION_PATTERN matches `app.command` / `tool` but not
# `app.post`, so it cannot see this wiring.
@app.post("/webhook", status_code=status.HTTP_202_ACCEPTED, response_model=None)
def receive_webhook(payload: dict[str, object]) -> JSONResponse | dict[str, str]:
    """Validate ``payload`` as a ``WebhookIngress`` and persist via ``mcp.put``.

    Returns:
        On the durable path: ``{"status": "accepted", "webhook_id": <id>}``.
        On the in-memory fallback path (``WEBHOOK_DURABLE_V1_ENABLED=false`` or
        ``mcp.put`` unbound): a 202 ``JSONResponse`` with
        ``{"status": "accepted_in_memory_only"}`` and a structured
        ``webhook_persistence_skipped`` warning log entry.

    Raises:
        HTTPException: 422 when the payload fails schema validation. The
            underlying :class:`msgspec.ValidationError` is logged with the
            ``invalid_webhook`` event key (no exception message in ``extra``).
    """
    try:
        validated: WebhookIngress = msgspec.convert(payload, WebhookIngress)  # ty: ignore[invalid-assignment]
    except msgspec.ValidationError:
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

    if not _webhook_durable_v1_enabled():
        logger.warning(
            "webhook_persistence_skipped",
            extra={
                "reason": "v1_disabled",
                "webhook_id": webhook_id,
            },
        )
        return JSONResponse(
            {"status": "accepted_in_memory_only"},
            status_code=status.HTTP_202_ACCEPTED,
        )

    # Substrate-compat gate: only persist when mcp.put is exposed.
    put = mcp_calltime("put")
    COUNTERS.attempted.labels(producer=_PRODUCER_NAME).inc()
    if put is not None:
        put(f"webhook-ingress/{webhook_id}/", validated)
        COUNTERS.succeeded.labels(producer=_PRODUCER_NAME).inc()
    else:
        COUNTERS.skipped.labels(producer=_PRODUCER_NAME).inc()
        logger.warning(
            "webhook_persistence_skipped",
            extra={
                "reason": "mcp.put_unbound",
                "webhook_id": webhook_id,
                "v1_enabled": _webhook_durable_v1_enabled(),
            },
        )
        return JSONResponse(
            {"status": "accepted_in_memory_only"},
            status_code=status.HTTP_202_ACCEPTED,
        )

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
