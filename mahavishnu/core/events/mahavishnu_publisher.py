"""Mahavishnu-side publisher for workflow lifecycle events.

Wraps existing ``broadcast_workflow_started`` / ``broadcast_workflow_completed``
/ ``broadcast_workflow_failed`` broadcasts into the canonical
:class:`oneiric.runtime.events.EventEnvelope` and publishes them via the
Mahavishnu event publisher (an
:class:`OneiricEventPublisherProtocol` implementation).

The result: workflow events appear on the unified Bodai EventBridge
stream (Redis Streams via Oneiric) for consumption by ``/bodai-status``,
the PostToolUse hook, and any other Oneiric-aware subscriber — in
addition to the existing WebSocket broadcasts (which are kept for
non-Claude consumers).

The pre-Phase-12a ``~/.mahavishnu/bodai-event-queue.json`` file path is
NOT a destination here — that legacy JSON-file queue was retired in
Phase 12a Task 5 in favour of the Oneiric bus. This module publishes
to the bus; the queue file is the historical daemon-only artifact in
:mod:`mahavishnu.core.events.bodai_subscriber` (kept for backward
compatibility with long-running observer scripts).

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

import inspect
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from oneiric.runtime.events import EventEnvelope as OneiricEventEnvelope

from mahavishnu.core.events.canonical import (
    OneiricEventPublisherProtocol,
    create_oneiric_envelope,
)

logger = logging.getLogger(__name__)

SOURCE = "mahavishnu"
EVENT_VERSION = "1.0.0"

TOPIC_WORKFLOW_STARTED = "workflow.started"
TOPIC_WORKFLOW_COMPLETED = "workflow.completed"
TOPIC_WORKFLOW_FAILED = "workflow.failed"
# ACP-related worker lifecycle emissions (Phase 1 of the v1.0 ACP server build).
# Topic strings match ``mahavishnu.acp.topics`` so the consumer side can use
# a single import for routing. The dot-separated form matches the Oneiric
# canonical envelope convention used throughout this module.
TOPIC_TOOL_CALL_STARTED = "tool_call.started"
TOPIC_TOOL_CALL_COMPLETED = "tool_call.completed"


def _make_envelope(
    topic: str,
    source: str,
    payload: dict[str, Any],
) -> OneiricEventEnvelope:
    """Build the canonical Oneiric ``EventEnvelope`` for a workflow event.

    Args:
        topic: Event topic (e.g. ``workflow.started``).
        source: Producer identifier (typically ``mahavishnu``).
        payload: Event-specific payload (must be JSON-serializable).

    Returns:
        A canonical :class:`oneiric.runtime.events.EventEnvelope` with
        the canonical Oneiric reserved headers set by the
        :func:`create_oneiric_envelope` factory (so duplicate-header
        collisions and reserved-header misuse are guarded upstream of
        the publisher).
    """
    return create_oneiric_envelope(
        topic=topic,
        payload=payload,
        source=source,
        version=EVENT_VERSION,
    )


async def _publish(
    envelope: OneiricEventEnvelope,
    publisher: OneiricEventPublisherProtocol | None,
) -> None:
    """Publish an envelope via the injected publisher.

    Swallows any exception (logs at WARNING) so that a misbehaving publisher
    can never abort a workflow broadcast path. Handles both sync and async
    ``publish`` results -- the protocol permits both, since some
    implementations (e.g. ``InMemoryEventTransport``) are coroutine-only
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
    publisher: OneiricEventPublisherProtocol | None = None,
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
    publisher: OneiricEventPublisherProtocol | None = None,
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
    publisher: OneiricEventPublisherProtocol | None = None,
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


async def publish_tool_call_started(
    worker_id: str,
    task_id: str,
    *,
    name: str | None = None,
    session_id: str | None = None,
    publisher: OneiricEventPublisherProtocol | None = None,
) -> None:
    """Publish a ``tool_call.started`` event to the Bodai queue.

    Emitted by worker dispatch boundaries (Apple container, E2B sandbox, etc.)
    when a tool call begins. Consumed by ``mahavishnu.acp.events.EventSynthesizer``
    which maps it to an ACP ``session/update`` notification of type
    ``tool_call_update`` with ``status="running"``.

    Args:
        worker_id: Worker that owns this tool call (e.g. ``apple-container``,
            ``e2b-sandbox``). Maps to ACP ``title`` on the wire.
        task_id: Opaque task identifier within the worker. Maps to ACP
            ``toolCallId``.
        name: Optional human-readable name for the tool call. Defaults to
            ``worker_id`` if not provided.
        session_id: Optional correlation key for ACP routing. Stored in
            the payload (the synthesizer's third-priority location).
            Putting it in the payload rather than mutating envelope
            headers sidesteps the Oneiric envelope's missing direct
            ``source``/``version`` attributes (those live in
            ``headers["source"]``).
        publisher: Injected event publisher. ``None`` is a no-op.
    """
    payload: dict[str, Any] = {
        "worker_id": worker_id,
        "task_id": task_id,
        "name": name or worker_id,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    envelope = _make_envelope(TOPIC_TOOL_CALL_STARTED, SOURCE, payload)
    await _publish(envelope, publisher)


async def publish_tool_call_completed(
    worker_id: str,
    task_id: str,
    *,
    outcome: str = "completed",
    name: str | None = None,
    session_id: str | None = None,
    publisher: OneiricEventPublisherProtocol | None = None,
) -> None:
    """Publish a ``tool_call.completed`` event to the Bodai queue.

    Emitted by worker dispatch boundaries when a tool call ends. Consumed
    by ``mahavishnu.acp.events.EventSynthesizer`` which maps it to an ACP
    ``session/update`` notification of type ``tool_call_update`` with
    ``status="completed"`` or ``"failed"``.

    Args:
        worker_id: Worker that owns this tool call.
        task_id: Opaque task identifier within the worker. Maps to ACP
            ``toolCallId``.
        outcome: ``"completed"`` (default) or ``"failed"``. Failures
            should be loud about themselves; the synthesizer honors this
            field via ``_extract_outcome``.
        name: Optional human-readable name for the tool call.
        session_id: Optional correlation key for ACP routing (in payload).
        publisher: Injected event publisher. ``None`` is a no-op.
    """
    payload: dict[str, Any] = {
        "worker_id": worker_id,
        "task_id": task_id,
        "name": name or worker_id,
        "outcome": outcome,
    }
    if session_id is not None:
        payload["session_id"] = session_id
    envelope = _make_envelope(TOPIC_TOOL_CALL_COMPLETED, SOURCE, payload)
    await _publish(envelope, publisher)


__all__ = [
    "EVENT_VERSION",
    "SOURCE",
    "TOPIC_TOOL_CALL_COMPLETED",
    "TOPIC_TOOL_CALL_STARTED",
    "TOPIC_WORKFLOW_COMPLETED",
    "TOPIC_WORKFLOW_FAILED",
    "TOPIC_WORKFLOW_STARTED",
    "_make_envelope",
    "publish_tool_call_completed",
    "publish_tool_call_started",
    "publish_workflow_completed",
    "publish_workflow_failed",
    "publish_workflow_started",
]
