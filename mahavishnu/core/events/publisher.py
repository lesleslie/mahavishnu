"""Module-global EventBridgePublisher singleton.

Per ``feedback-no-backwards-compat-pre-1.0``, this replaces the
server-scoped ``eventbridge_resolver.resolve_event_publisher(server)``
path entirely. There is no dual-API; downstream callers MUST use
``get_publisher()`` / ``safe_publish()``.

Wire at app boot via ``set_publisher()`` in
``mahavishnu/factories.py:_wire_eventbridge_publisher``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from oneiric.core.logging import get_logger

from mahavishnu.core._producer_metrics import EVENTBRIDGE_PUBLISH_TOTAL

if TYPE_CHECKING:
    from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher


_publisher: EventBridgePublisher | None = None
# C-2 wire-up scaffolding uses this to capture envelopes per-test. Production
# code never reads it; the real singleton lives in ``_publisher``.
_capture_singleton: list[Any] = []
logger = get_logger(__name__)


def set_publisher(publisher: EventBridgePublisher | None) -> None:
    """Inject the publisher singleton. Called at app boot.

    Passing ``None`` disables publishing — useful for tests and degraded
    mode where Akosha is unavailable.
    """
    global _publisher
    _publisher = publisher


def get_publisher() -> EventBridgePublisher | None:
    """Return the injected publisher, or ``None`` if not configured.

    All wire-up Akosha integrations MUST handle ``None`` gracefully
    (log + metric, no-op). This function never raises.
    """
    return _publisher


async def safe_publish(envelope: Any) -> bool:
    """Fire-and-forget publish. Returns True if published, False otherwise.

    Returns ``False`` when:
    - no publisher is configured (counts as ``result="skip"``)
    - the publisher raised (counts as ``result="error"``)

    NEVER raises — observability must never block the dispatch path.
    Catches ``Exception`` (not ``BaseException``) so ``CancelledError``
    propagates per ``crackerjack-compliant-code`` and the asyncio
    contract.
    """
    publisher = get_publisher()
    if publisher is None:
        EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic=getattr(envelope, "topic", "unknown"),
            result="skip",
        ).inc()
        return False
    try:
        await publisher.publish(envelope)
    except Exception:
        EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic=getattr(envelope, "topic", "unknown"),
            result="error",
        ).inc()
        logger.exception(
            "EventBridge publish failed",
            extra={"envelope_topic": getattr(envelope, "topic", None)},
        )
        return False
    EVENTBRIDGE_PUBLISH_TOTAL.labels(
        envelope_topic=getattr(envelope, "topic", "unknown"),
        result="success",
    ).inc()
    return True


__all__ = ["get_publisher", "safe_publish", "set_publisher"]
