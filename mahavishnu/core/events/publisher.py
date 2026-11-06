"""Module-global EventBridgePublisher singleton.

Per ``feedback-no-backwards-compat-pre-1.0``, this replaces the
server-scoped ``eventbridge_resolver.resolve_event_publisher(server)``
path entirely. There is no dual-API; downstream callers MUST use
``get_publisher()`` / ``safe_publish()``.

Wire at app boot via ``set_publisher()`` in
``mahavishnu/factories.py:_wire_eventbridge_publisher``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

try:
    from oneiric.core.logging import get_logger
except ImportError:
    # Fallback so the `mahavishnu` CLI can start from any CWD (e.g. the
    # post-commit hook in any Bodai repo). The oneiric peer-directory
    # resolution only works when CWD is /Users/les/Projects/mahavishnu.
    # See `core/events/__init__.py` module docstring for the contract.
    from logging import (
        getLogger as get_logger,  # type: ignore[assignment]  # noqa: N813 — oneiric exposes get_logger; fallback keeps snake_case binding
    )

from mahavishnu.core._producer_metrics import EVENTBRIDGE_PUBLISH_TOTAL
from mahavishnu.core.errors import EventEnvelopeConversionError

if TYPE_CHECKING:
    from oneiric.runtime.events import EventEnvelope as OneiricEventEnvelope

    from mahavishnu.core.events.envelope import EventEnvelope as MahavishnuEventEnvelope
    from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher


_publisher: EventBridgePublisher | None = None
# Test seam only: integration tests monkeypatch this module-level list to
# capture the envelopes they publish. No production code appends to it and
# no production code reads it -- the real singleton lives in ``_publisher``.
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


def _envelope_topic(envelope: object) -> str:
    """Return the canonical topic carried by ``envelope``.

    A Oneiric envelope names the topic ``topic``; a Mahavishnu envelope
    names it ``event_type``, which
    :func:`mahavishnu.core.events.canonical.to_oneiric_envelope` maps
    onto the Oneiric ``topic``.

    Returns ``""`` when the envelope carries neither field. An empty
    label is honest about "no topic"; the previous ``"unknown"``
    fallback advertised a topic dimension that never held information,
    which is how the wrong-envelope-type defect stayed invisible.
    """
    for attribute in ("topic", "event_type"):
        value = getattr(envelope, attribute, None)
        if isinstance(value, str) and value:
            return value
    return ""


def _to_canonical_envelope(
    envelope: MahavishnuEventEnvelope | OneiricEventEnvelope,
) -> OneiricEventEnvelope:
    """Return the canonical Oneiric envelope for ``envelope``.

    The publisher protocol
    (:class:`mahavishnu.core.events.canonical.OneiricEventPublisherProtocol`)
    only accepts the Oneiric shape, so the conversion belongs here rather
    than at each call site.

    - An envelope that already carries the Oneiric wire shape (``topic``)
      is passed through unchanged.
    - A Mahavishnu envelope is converted via
      :func:`mahavishnu.core.events.canonical.to_oneiric_envelope`.

    The ``canonical`` import is deferred to call time: this module must
    stay importable when ``oneiric`` is unavailable (see
    ``tests/unit/core/events/test_package_init_lazy_canonical.py``).
    """
    if isinstance(getattr(envelope, "topic", None), str):
        return cast("OneiricEventEnvelope", envelope)
    if not isinstance(getattr(envelope, "event_type", None), str):
        raise EventEnvelopeConversionError(
            direction="mahavishnu_to_oneiric",
            reason="unknown_envelope_shape",
            details={"type": type(envelope).__name__},
        )
    from mahavishnu.core.events.canonical import to_oneiric_envelope

    return to_oneiric_envelope(cast("MahavishnuEventEnvelope", envelope))


async def safe_publish(
    envelope: MahavishnuEventEnvelope | OneiricEventEnvelope,
) -> bool:
    """Fire-and-forget publish. Returns True if published, False otherwise.

    Accepts either envelope shape:

    - ``MahavishnuEventEnvelope`` -- converted to the canonical Oneiric
      envelope before it reaches the publisher. The Mahavishnu
      ``event_type`` becomes the Oneiric ``topic``.
    - ``OneiricEventEnvelope`` -- already canonical, passed through
      unchanged.

    Returns ``False`` when:
    - no publisher is configured (counts as ``result="skip"``)
    - the envelope could not be converted (counts as ``result="error"``)
    - the publisher raised (counts as ``result="error"``)

    NEVER raises — observability must never block the dispatch path.
    Catches ``Exception`` (not ``BaseException``) so ``CancelledError``
    propagates per ``crackerjack-compliant-code`` and the asyncio
    contract.
    """
    publisher = get_publisher()
    topic = _envelope_topic(envelope)
    if publisher is None:
        EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic=topic,
            result="skip",
        ).inc()
        return False
    try:
        canonical = _to_canonical_envelope(envelope)
    except Exception:
        EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic=topic,
            result="error",
        ).inc()
        logger.exception(
            "EventBridge envelope conversion failed",
            extra={"envelope_topic": topic},
        )
        return False
    try:
        await publisher.publish(canonical)
    except Exception:
        EVENTBRIDGE_PUBLISH_TOTAL.labels(
            envelope_topic=topic,
            result="error",
        ).inc()
        logger.exception(
            "EventBridge publish failed",
            extra={"envelope_topic": topic},
        )
        return False
    EVENTBRIDGE_PUBLISH_TOTAL.labels(
        envelope_topic=topic,
        result="success",
    ).inc()
    return True


__all__ = ["get_publisher", "safe_publish", "set_publisher"]
