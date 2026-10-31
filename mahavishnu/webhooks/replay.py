"""Durable webhook replay consumer.

Reads back :class:`mahavishnu.core.models.persistence.WebhookIngress`
records persisted by :mod:`mahavishnu.webhooks.receiver` and returns
validated typed structs via :func:`msgspec.convert`. The
consumer/producer contract is
the persistence key ``f"webhook-ingress/{webhook_id}/"`` — producers
write here via :func:`mahavishnu.core.substrate.put`, consumers read
here via :func:`mahavishnu.core.substrate.get`.

This module is intentionally separate from
:mod:`mahavishnu.webhooks.receiver` — the receiver is an HTTP producer
that validates inbound payloads; this module is a leaf consumer that
reads them back.

The read is awaitable because the substrate's read half is: reads were
MCP tool calls, so they were coroutines. The sibling readers
(:mod:`mahavishnu.core.ecosystem_state` and
:mod:`mahavishnu.mcp.tools.workflow_tools`) await the same call.
"""

from __future__ import annotations

import msgspec
from oneiric.core.logging import get_logger

# req: REQ-SUBSTR-001
from mahavishnu.core import substrate
from mahavishnu.core.models.persistence import WebhookIngress
from mahavishnu.mcp.tools._workflow_id_guard import validate_webhook_id

logger = get_logger(__name__)


# req: REQ-SUBSTR-003
# req: REQ-SUBSTR-004
async def webhook_replay(
    webhook_id: str,
    token: str | None = None,
) -> WebhookIngress | None:
    """Read back a persisted ``WebhookIngress`` and validate via ``from_dict``.

    Args:
        webhook_id: Stable ID of the webhook to read back.
        token: Optional bearer token. The check is a JWT-shape presence
            gate (mirrors the ``@require_auth`` contract on the MCP
            surface): missing or non-JWT-shaped tokens are rejected. Full
            user→role→permission mapping is enforced at the FastAPI
            middleware/dependency layer in production; here we block the
            read before any substrate call so the leaf function can never
            be exercised without auth.

    Returns:
        The validated :class:`WebhookIngress` instance, or ``None`` when
        no record exists at the durability key, ``webhook_id`` fails the
        path-traversal allowlist check, or ``token`` is missing or not a
        JWT-shaped triple.
        A missing-record read emits no log line; an invalid-id or
        RBAC-denied read emits a structured ``webhook_replay_skipped``
        warning so operators can disambiguate the failure mode.

    Notes:
        The persistence key format
        ``f"webhook-ingress/{webhook_id}/"`` MUST match the producer
        side in :mod:`mahavishnu.webhooks.receiver` — the M-WEBHOOK-
        DURABLE producer/consumer contract relies on it.
    """
    # RBAC gate: READ_WEBHOOK required (multi-agent review HIGH finding).
    # JWT-shape presence check is the local contract; full
    # RBACManager.check_permission runs at the FastAPI middleware
    # boundary.
    if not token or len(token.split(".")) != 3:
        logger.warning(
            "webhook_replay_skipped",
            extra={
                "reason": "rbac_denied",
                "webhook_id": webhook_id,
            },
        )
        return None

    # Path-traversal guard: ``webhook_id`` is spliced into the substrate
    # key ``f"webhook-ingress/{webhook_id}/"`` below. Reject
    # caller-supplied values that contain traversal characters BEFORE the
    # substrate sees them, so callers see a single error shape.
    if not validate_webhook_id(webhook_id):
        logger.warning(
            "webhook_replay_skipped",
            extra={
                "reason": "invalid_webhook_id",
                "webhook_id": webhook_id,
            },
        )
        return None

    payload = await substrate.get(f"webhook-ingress/{webhook_id}/")
    if payload is None:
        return None

    # msgspec.Struct is duck-typed so we read fields directly without an
    # isinstance check (bandit B101 forbids asserts in production).
    return msgspec.convert(payload, WebhookIngress)  # ty: ignore[invalid-return-type]


__all__ = ["webhook_replay"]
