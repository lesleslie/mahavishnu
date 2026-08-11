"""Webhook models, handlers, router, and durable receiver mount helper.

This module provides Pydantic models for validating webhook requests
from external platforms like OpenClaw, plus a FastAPI router with
rate limiting and authentication, and a ``mount_durable_webhooks``
helper that wires the durable receiver sub-app
(:mod:`mahavishnu.webhooks.receiver`) into the main mahavishnu
FastAPI app.

Design Reference:
- docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md (P0-3, P0-4, P0-5)
- Security: Path traversal prevention, input validation, rate limiting

Usage:
    from fastapi import FastAPI

    from mahavishnu.webhooks import webhook_router, mount_durable_webhooks

    app = FastAPI()
    app.include_router(webhook_router, prefix="/webhooks")
    mount_durable_webhooks(app)  # mounts receiver at /durable-webhooks
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mahavishnu.webhooks.models import (
    OpenClawSweepRequest,
    OpenClawWorkflowRequest,
    WebhookErrorResponse,
    WebhookResponse,
    WebhookStatus,
)
from mahavishnu.webhooks.router import (
    validate_auth,
    webhook_router,
)

if TYPE_CHECKING:
    from fastapi import FastAPI


def mount_durable_webhooks(parent_app: "FastAPI") -> None:
    """Mount the durable webhook receiver under ``/durable-webhooks``.

    The receiver (:mod:`mahavishnu.webhooks.receiver`) is a standalone
    FastAPI app that exposes ``POST /webhook`` for cross-system durable
    ingest. Mounting it as a sub-app keeps the receiver self-contained
    (its own lifecycle, validation, and metrics counters) while making
    it reachable at ``POST /durable-webhooks/webhook`` on the parent
    mahavishnu FastAPI app.

    Order matters: Starlette resolves mounts in declaration order, so
    the caller MUST mount ``/durable-webhooks`` before any catch-all
    mount such as ``app.mount("/", ...)``. The bootstrap module honors
    this contract by calling :func:`mount_durable_webhooks` before
    ``app.mount("/", a2a_app)``.

    The receiver's persistence layer is substrate-compat gated
    (``dhara.put``); when no binding is injected the receiver returns
    ``202 accepted_in_memory_only`` so the production mount is safe to
    enable even before Dhara is wired.
    """
    # Lazy import: receiver pulls FastAPI app-level module load (logging,
    # substrate-compat stamping). Avoid paying that cost at package import.
    from mahavishnu.webhooks.receiver import app as receiver_app

    parent_app.mount("/durable-webhooks", receiver_app)


__all__ = [
    # Models
    "OpenClawSweepRequest",
    "OpenClawWorkflowRequest",
    "WebhookErrorResponse",
    "WebhookResponse",
    "WebhookStatus",
    "validate_auth",
    # Router
    "webhook_router",
    # Mount helper
    "mount_durable_webhooks",
]
