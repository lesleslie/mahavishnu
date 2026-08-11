"""Durable webhook replay consumer.

Reads back :class:`dhara.schema.WebhookIngress` records persisted by
:mod:`mahavishnu.webhooks.receiver` and returns validated typed structs
via :func:`dhara.schema.from_dict`. The consumer/producer contract is
the persistence key ``f"webhook-ingress/{webhook_id}/"`` — producers
write here via :func:`dhara.put`, consumers read here via
:func:`dhara.get`.

This module is intentionally separate from
:mod:`mahavishnu.webhooks.receiver` — the receiver is an HTTP producer
that validates inbound payloads; this module is a leaf consumer that
reads them back. Mirrors the producer's substrate-compat guard pattern
so a host dhara install that has not injected a ``dhara.get`` binding
returns ``None`` instead of raising ``AttributeError``.
"""

from __future__ import annotations

import dhara
from dhara.schema import WebhookIngress, from_dict
from oneiric.core.logging import get_logger

from mahavishnu.mcp.tools._workflow_id_guard import validate_webhook_id

# Substrate-compat: `dhara.get` is not a module-level attribute on the
# installed dhara package — real callers pass a Dhara client instance
# (e.g. `await self.dhara.get(...)`) or import a configured binding into
# `dhara.get` at integration time. Tests substitute via
# `monkeypatch.setattr("replay.dhara.get", ...)`; the hasattr guard
# lets that patch land even when the host package has not injected a
# binding.
if not hasattr(dhara, "get"):
    dhara.get = None  # type: ignore[attr-defined]

logger = get_logger(__name__)


def webhook_replay(webhook_id: str) -> WebhookIngress | None:
    """Read back a persisted ``WebhookIngress`` and validate via ``from_dict``.

    Returns:
        The validated :class:`WebhookIngress` instance, or ``None`` when
        no record exists at the durability key, the substrate is
        unbound, or ``webhook_id`` fails the path-traversal allowlist
        check. A missing-record read emits no log line; a substrate-
        unbound read emits a structured ``webhook_replay_skipped``
        warning with ``reason='dhara.get_unbound'`` so operators can
        disambiguate the failure mode.

    Notes:
        The persistence key format
        ``f"webhook-ingress/{webhook_id}/"`` MUST match the producer
        side in :mod:`mahavishnu.webhooks.receiver` — the M-WEBHOOK-
        DURABLE producer/consumer contract relies on it.
    """
    # Path-traversal guard: ``webhook_id`` is spliced into the Dhara key
    # ``f"webhook-ingress/{webhook_id}/"`` below. Reject caller-supplied
    # values that contain traversal characters BEFORE the substrate sees
    # them. Matches the existing convention for the substrate-unbound
    # case (log warning, return None) so callers see a single error shape.
    if not validate_webhook_id(webhook_id):
        logger.warning(
            "webhook_replay_skipped",
            extra={
                "reason": "invalid_webhook_id",
                "webhook_id": webhook_id,
            },
        )
        return None

    get = getattr(dhara, "get", None)
    if get is None:
        logger.warning(
            "webhook_replay_skipped",
            extra={
                "reason": "dhara.get_unbound",
                "webhook_id": webhook_id,
            },
        )
        return None

    payload = get(f"webhook-ingress/{webhook_id}/")
    if payload is None:
        return None

    # The registry returns a WebhookIngress for name='webhook_ingress';
    # msgspec.Struct is duck-typed so we read fields directly without an
    # isinstance check (bandit B101 forbids asserts in production).
    return from_dict("webhook_ingress", payload)


__all__ = ["webhook_replay"]
