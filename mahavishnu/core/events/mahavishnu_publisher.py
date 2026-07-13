"""Mahavishnu-side publisher for workflow lifecycle events.

Wraps existing ``broadcast_workflow_started`` / ``broadcast_workflow_completed``
/ ``broadcast_workflow_failed`` broadcasts into the canonical
:class:`oneiric.runtime.events.EventEnvelope` and publishes them via the
Mahavishnu event publisher (an :class:`EventPublisherProtocol` implementation).

The result: events appear in the unified Bodai queue
(``~/.mahavishnu/bodai-event-queue.json``) for consumption by ``/bodai-status``
and the PostToolUse hook, in addition to the existing WebSocket broadcasts
(which are kept for non-Claude consumers).

Public API
----------
- :func:`publish_workflow_started` -- topic ``workflow.started``
- :func:`publish_workflow_completed` -- topic ``workflow.completed``
- :func:`publish_workflow_failed` -- topic ``workflow.failed``

All three functions never raise -- they log at WARNING on failure. The
canonical envelope carries ``source='mahavishnu'`` in the ``headers`` dict,
matching what :mod:`mahavishnu.core.events.bodai_subscriber` consumes.
"""

from __future__ import annotations

from datetime import UTC, datetime
import inspect
import logging
from typing import TYPE_CHECKING, Any
import uuid

from oneiric.runtime.events import EventEnvelope, create_event_envelope

if TYPE_CHECKING:
    from mahavishnu.core.events.contract import EventPublisherProtocol

logger = logging.getLogger(__name__)

SOURCE = "mahavishnu"
EVENT_VERSION = "1.0.0"

TOPIC_WORKFLOW_STARTED = "workflow.started"
TOPIC_WORKFLOW_COMPLETED = "workflow.completed"
TOPIC_WORKFLOW_FAILED = "workflow.failed"


def _make_envelope(topic: str, source: str, payload: dict[str, Any]) -> EventEnvelope:
    """Build the canonical Oneiric ``EventEnvelope`` for a workflow event.

    Args:
        topic: Event topic (e.g. ``workflow.started``).
        source: Producer identifier (typically ``mahavishnu``).
        payload: Event-specific payload (must be JSON-serializable).

    Returns:
        A canonical :class:`oneiric.runtime.events.EventEnvelope` with
        ``source``, ``event_id``, ``timestamp``, and ``version`` set in the
        ``headers`` dict.
    """
    event_id = uuid.uuid4()
    timestamp = datetime.now(UTC).isoformat()
    return create_event_envelope(
        topic=topic,
        payload=payload,
        source=source,
        version=EVENT_VERSION,
        headers={
            "source": source,
            "event_id": str(event_id),
            "timestamp": timestamp,
            "version": EVENT_VERSION,
        },
    )


async def _publish(
    envelope: EventEnvelope,
    publisher: EventPublisherProtocol | None,
) -> None:
    """Publish an envelope via the injected publisher.

    Swallows any exception (logs at WARNING) so that a misbehaving publisher
    can never abort a workflow broadcast path. Handles both sync and async
    ``publish`` results -- the protocol permits both, since some
    implementations (e.g. :class:`InMemoryEventTransport`) are coroutine-only
    while others may return a future-like object.
    """
    if publisher is None:
        return
    try:
        result = publisher.publish(envelope)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.exception(
            "mahavishnu.publisher: failed to publish topic=%s event_id=%s",
            envelope.topic,
            envelope.headers.get("event_id", "<unknown>"),
        )


async def publish_workflow_started(
    workflow_id: str,
    metadata: dict[str, Any],
    *,
    publisher: EventPublisherProtocol | None = None,
) -> None:
    """Publish a ``workflow.started`` event to the Bodai queue.

    Args:
        workflow_id: Workflow identifier.
        metadata: Workflow metadata (prompt, adapter, tags, etc.).
        publisher: Injected event publisher (typically fetched from the
            running :class:`MahavishnuApp`). ``None`` is a no-op.
    """
    payload: dict[str, Any] = {"workflow_id": workflow_id, **metadata}
    envelope = _make_envelope(TOPIC_WORKFLOW_STARTED, SOURCE, payload)
    await _publish(envelope, publisher)


async def publish_workflow_completed(
    workflow_id: str,
    result: dict[str, Any],
    *,
    publisher: EventPublisherProtocol | None = None,
) -> None:
    """Publish a ``workflow.completed`` event to the Bodai queue.

    Args:
        workflow_id: Workflow identifier.
        result: Final workflow result.
        publisher: Injected event publisher. ``None`` is a no-op.
    """
    payload: dict[str, Any] = {"workflow_id": workflow_id, **result}
    envelope = _make_envelope(TOPIC_WORKFLOW_COMPLETED, SOURCE, payload)
    await _publish(envelope, publisher)


async def publish_workflow_failed(
    workflow_id: str,
    error: str,
    *,
    publisher: EventPublisherProtocol | None = None,
) -> None:
    """Publish a ``workflow.failed`` event to the Bodai queue.

    Args:
        workflow_id: Workflow identifier.
        error: Error message string.
        publisher: Injected event publisher. ``None`` is a no-op.
    """
    payload: dict[str, Any] = {"workflow_id": workflow_id, "error": error}
    envelope = _make_envelope(TOPIC_WORKFLOW_FAILED, SOURCE, payload)
    await _publish(envelope, publisher)


__all__ = [
    "EVENT_VERSION",
    "SOURCE",
    "TOPIC_WORKFLOW_COMPLETED",
    "TOPIC_WORKFLOW_FAILED",
    "TOPIC_WORKFLOW_STARTED",
    "_make_envelope",
    "publish_workflow_completed",
    "publish_workflow_failed",
    "publish_workflow_started",
]