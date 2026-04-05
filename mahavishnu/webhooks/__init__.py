"""Webhook models, handlers, and router for external platform integrations.

This module provides Pydantic models for validating webhook requests
from external platforms like OpenClaw, plus a FastAPI router with
rate limiting and authentication.

Design Reference:
- docs/plans/PRE_IMPLEMENTATION_CHECKLIST.md (P0-3, P0-4, P0-5)
- Security: Path traversal prevention, input validation, rate limiting

Usage:
    from mahavishnu.webhooks import webhook_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(webhook_router, prefix="/webhooks")
"""

from mahavishnu.webhooks.models import (
    OpenClawSweepRequest,
    OpenClawWorkflowRequest,
    WebhookResponse,
    WebhookErrorResponse,
    WebhookStatus,
)
from mahavishnu.webhooks.router import (
    webhook_router,
    validate_auth,
)

__all__ = [
    # Models
    "OpenClawSweepRequest",
    "OpenClawWorkflowRequest",
    "WebhookResponse",
    "WebhookErrorResponse",
    "WebhookStatus",
    # Router
    "webhook_router",
    "validate_auth",
]
