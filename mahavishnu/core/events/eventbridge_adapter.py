"""Oneiric EventBridge adapter for Mahavishnu.

Bridges ``publisher.publish(envelope)`` (the API the publisher module
expects) and ``EventBridge.emit(topic, payload, headers)`` (the API
Oneiric's EventBridge exposes).

Mirrors ``crackerjack.core.eventbridge_adapter`` and
``akosha.observability.eventbridge_adapter``.

This is the production injection point. Without it, the publisher
module would have no production-compatible publisher to wire into.
Tests use a duck-typed AsyncMock; production wires an
``EventBridgePublisher`` constructed against the running
``EventBridge``.
"""
from __future__ import annotations

from typing import Any

from oneiric.runtime.events import EventEnvelope


class EventBridgePublisher:
    """Adapter from ``publish(envelope)`` to ``EventBridge.emit(topic, payload, headers)``.

    Args:
        bridge: An instance of Oneiric's ``EventBridge`` (duck-typed;
            the only attribute accessed is ``emit``).
    """

    def __init__(self, bridge: Any) -> None:
        self._bridge = bridge

    async def publish(self, envelope: EventEnvelope) -> None:
        """Forward ``envelope`` to ``bridge.emit(topic, payload, headers)``."""
        await self._bridge.emit(
            envelope.topic,
            envelope.payload,
            envelope.headers,
        )


__all__ = ["EventBridgePublisher"]
