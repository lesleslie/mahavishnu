from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from mahavishnu.core.events.contract import (
    EventPublisherProtocol,
    InMemoryEventTransport,
    create_event_envelope,
)
from mahavishnu.core.events.envelope import EventEnvelope


def test_create_event_envelope_includes_canonical_metadata():
    correlation_id = UUID("12345678-1234-1234-1234-123456789012")
    causation_id = UUID("87654321-4321-4321-4321-210987654321")
    timestamp = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)

    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={"workflow_id": "wf-1"},
        correlation_id=correlation_id,
        causation_id=causation_id,
        timestamp=timestamp,
        metadata={"trace_id": "abc"},
    )

    assert isinstance(envelope, EventEnvelope)
    assert envelope.event_type == "workflow.started"
    assert envelope.source == "test_service"
    assert envelope.correlation_id == correlation_id
    assert envelope.causation_id == causation_id
    assert envelope.timestamp == timestamp
    assert envelope.payload == {"workflow_id": "wf-1"}
    assert envelope.metadata == {"trace_id": "abc"}


@pytest.mark.asyncio
async def test_in_memory_transport_publishes_and_records_history():
    transport = InMemoryEventTransport()
    seen: list[EventEnvelope] = []

    async def handler(envelope: EventEnvelope) -> None:
        seen.append(envelope)

    subscription_id = transport.subscribe("workflow.*", handler)
    envelope = create_event_envelope("workflow.started", "test_service", payload={"workflow_id": "wf-1"})

    returned = await transport.publish(envelope)

    assert isinstance(returned, EventEnvelope)
    assert returned is envelope
    assert seen == [envelope]
    assert transport.history() == [envelope]
    assert transport.unsubscribe(subscription_id) is True


@pytest.mark.asyncio
async def test_in_memory_transport_supports_exact_and_pattern_matches():
    transport = InMemoryEventTransport()
    exact_seen: list[str] = []
    pattern_seen: list[str] = []

    def exact_handler(envelope: EventEnvelope) -> None:
        exact_seen.append(envelope.event_type)

    async def pattern_handler(envelope: EventEnvelope) -> None:
        pattern_seen.append(envelope.event_type)

    transport.subscribe("pool.spawned", exact_handler)
    transport.subscribe("pool.*", pattern_handler)

    await transport.publish(create_event_envelope("pool.spawned", "test_service"))
    await transport.publish(create_event_envelope("pool.closed", "test_service"))

    assert exact_seen == ["pool.spawned"]
    assert pattern_seen == ["pool.spawned", "pool.closed"]


def test_protocol_accepts_in_memory_transport():
    transport = InMemoryEventTransport()
    assert isinstance(transport, EventPublisherProtocol)


def test_coerce_uuid_with_uuid_object():
    """_coerce_uuid returns UUID unchanged when already a UUID (line 33)."""
    from mahavishnu.core.events.contract import _coerce_uuid

    uid = UUID("12345678-1234-5678-1234-567812345678")
    assert _coerce_uuid(uid) is uid


@pytest.mark.asyncio
async def test_in_memory_transport_clear():
    """InMemoryEventTransport.clear() resets history and subscriptions (lines 137-138)."""
    transport = InMemoryEventTransport()
    transport.subscribe("test.event", lambda e: None)
    await transport.publish(create_event_envelope("test.event", "svc"))

    assert len(transport.history()) == 1
    transport.clear()
    assert transport.history() == []
    assert transport._subscriptions == {}
