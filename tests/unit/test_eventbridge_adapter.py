"""Unit tests for ``mahavishnu.core.events.eventbridge_adapter``.

The adapter bridges ``publisher.publish(envelope)`` (the API the
publisher module expects) and ``EventBridge.emit(topic, payload, headers)``
(the API Oneiric's EventBridge exposes).

Mirrors the parallel ``tests/unit/test_eventbridge_adapter.py`` in
Crackerjack and Akosha.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from oneiric.runtime.events import EventEnvelope

from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher


def test_adaptor_publish_calls_emit_with_envelope_fields() -> None:
    """publish() unpacks the envelope and forwards to bridge.emit()."""
    bridge = MagicMock()
    bridge.emit = AsyncMock()
    adapter = EventBridgePublisher(bridge)
    envelope = EventEnvelope(
        topic="workflow.started",
        payload={"workflow_id": "wf-1", "metadata": {"adapter": "prefect"}},
        headers={"source": "mahavishnu", "event_id": "abc-123"},
    )

    asyncio.run(adapter.publish(envelope))

    bridge.emit.assert_awaited_once_with(
        "workflow.started",
        {"workflow_id": "wf-1", "metadata": {"adapter": "prefect"}},
        {"source": "mahavishnu", "event_id": "abc-123"},
    )
