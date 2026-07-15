from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from mahavishnu.core.errors import EventEnvelopeConversionError
from mahavishnu.core.events.canonical import (
    decode_oneiric_envelope,
    encode_oneiric_envelope,
    to_oneiric_envelope,
)
from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.core.events.envelope import EventEnvelope
from mahavishnu.core.events.transport import (
    CompositeEventEnvelopeHandler,
    DLQEventHandler,
    EventBusConsumer,
    NotificationEventHandler,
    RedisEventTransport,
    RetryingEventEnvelopeHandler,
    WebSocketEventHandler,
)


@dataclass
class _FakeAdapter:
    enqueued: list[dict[str, Any]]
    published: list[tuple[str, str]]
    read_payloads: list[dict[str, Any]]

    def __init__(self) -> None:
        self.enqueued = []
        self.published = []
        self.read_payloads = []

    async def enqueue(self, data: dict[str, Any]) -> str:
        self.enqueued.append(data)
        return f"msg-{len(self.enqueued)}"

    async def pubsub_publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return len(self.published)

    async def pubsub_subscribe(self, *, channel=None, pattern=None, callback=None):
        self.subscribed = {"channel": channel, "pattern": pattern, "callback": callback}
        return asyncio.create_task(asyncio.sleep(0))

    async def read(self, *, count: int | None = None):
        return list(self.read_payloads[: count or len(self.read_payloads)])


class _FakeWebSocketServer:
    def __init__(self) -> None:
        self.broadcasts: list[tuple[str, dict[str, Any]]] = []

    async def broadcast_to_room(self, room: str, event: dict[str, Any]) -> None:
        self.broadcasts.append((room, event))


class _FakeNotificationRouter:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], Any]] = []

    async def send(self, record: dict[str, Any], route: Any) -> str:
        self.calls.append((record, route))
        return "sent"


class _FakeDeadLetterQueue:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def enqueue(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return kwargs


@pytest.mark.asyncio
async def test_redis_event_transport_publishes_to_stream_and_pubsub():
    adapter = _FakeAdapter()
    transport = RedisEventTransport(adapter, wire_format="legacy")
    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={"workflow_id": "wf-1"},
    )

    returned = await transport.publish(envelope)

    assert isinstance(returned, EventEnvelope)
    assert returned is envelope
    assert len(adapter.enqueued) == 1
    assert adapter.enqueued[0]["event_type"] == "workflow.started"
    assert adapter.enqueued[0]["envelope"] == envelope.to_json()
    assert adapter.published == [
        ("bodai:events:workflow.started", envelope.to_json()),
    ]


@pytest.mark.asyncio
async def test_redis_transport_defaults_to_oneiric_v1() -> None:
    adapter = _FakeAdapter()
    transport = RedisEventTransport(adapter)
    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={"workflow_id": "wf-1"},
    )

    returned = await transport.publish(envelope)

    assert returned is envelope
    assert set(adapter.enqueued[0]) == {"wire_format", "envelope"}
    assert adapter.enqueued[0]["wire_format"] == "oneiric-v1"
    canonical = decode_oneiric_envelope(adapter.enqueued[0]["envelope"])
    assert canonical.topic == envelope.event_type
    assert canonical.headers["event_id"] == str(envelope.event_id)
    assert adapter.published == [
        (
            "bodai:events:workflow.started",
            adapter.enqueued[0]["envelope"],
        )
    ]


@pytest.mark.asyncio
async def test_redis_transport_rejects_unknown_wire_format() -> None:
    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={"workflow_id": "wf-1"},
    )

    with pytest.raises(EventEnvelopeConversionError):
        transport = RedisEventTransport(_FakeAdapter(), wire_format="garbage")  # type: ignore[arg-type]
        await transport.publish(envelope)


@pytest.mark.asyncio
async def test_conversion_failure_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeAdapter()
    transport = RedisEventTransport(adapter)

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise EventEnvelopeConversionError(
            direction="mahavishnu_to_oneiric",
            reason="test_forced_failure",
        )

    monkeypatch.setattr(
        "mahavishnu.core.events.transport.to_oneiric_envelope", _raise
    )
    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={"workflow_id": "wf-1"},
    )

    with pytest.raises(EventEnvelopeConversionError):
        await transport.publish(envelope)

    assert adapter.enqueued == []
    assert adapter.published == []


@pytest.mark.asyncio
async def test_legacy_write_mode_preserves_previous_shape() -> None:
    adapter = _FakeAdapter()
    transport = RedisEventTransport(adapter, wire_format="legacy")
    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={"workflow_id": "wf-1"},
    )

    await transport.publish(envelope)

    assert adapter.enqueued[0]["event_type"] == "workflow.started"
    assert adapter.enqueued[0]["envelope"] == envelope.to_json()
    assert adapter.published == [
        ("bodai:events:workflow.started", envelope.to_json())
    ]


@pytest.mark.asyncio
async def test_replay_decodes_canonical_record_to_internal_envelope() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    canonical = to_oneiric_envelope(internal)
    adapter.read_payloads = [
        {
            "message_id": "1-0",
            "payload": {
                "wire_format": "oneiric-v1",
                "envelope": encode_oneiric_envelope(canonical),
            },
        }
    ]
    transport = RedisEventTransport(adapter)
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=transport,
        handler=Handler(),
    ).replay_pending()

    assert replayed == [internal]
    assert seen == [internal]


@pytest.mark.asyncio
async def test_consumer_continues_after_malformed_record() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    canonical = to_oneiric_envelope(internal)
    adapter.read_payloads = [
        {
            "message_id": "bad-0",
            "payload": {"wire_format": "oneiric-v1", "envelope": "{not-json"},
        },
        {
            "message_id": "1-0",
            "payload": {
                "wire_format": "oneiric-v1",
                "envelope": encode_oneiric_envelope(canonical),
            },
        },
    ]
    transport = RedisEventTransport(adapter)
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=transport,
        handler=Handler(),
    ).replay_pending()

    assert replayed == [internal]
    assert seen == [internal]


@pytest.mark.asyncio
async def test_consumer_continues_after_invalid_legacy_payload_type() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    adapter.read_payloads = [
        {
            "message_id": "bad-0",
            "payload": {"envelope": {"not": "text"}},
        },
        {
            "message_id": "1-0",
            "payload": {
                "wire_format": "oneiric-v1",
                "envelope": encode_oneiric_envelope(to_oneiric_envelope(internal)),
            },
        },
    ]
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter),
        handler=Handler(),
    ).replay_pending()

    assert replayed == [internal]
    assert seen == [internal]


@pytest.mark.asyncio
async def test_consumer_continues_after_invalid_canonical_uuid() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    invalid = to_oneiric_envelope(internal)
    invalid.headers["event_id"] = "not-a-uuid"
    adapter.read_payloads = [
        {
            "message_id": "bad-0",
            "payload": {
                "wire_format": "oneiric-v1",
                "envelope": encode_oneiric_envelope(invalid),
            },
        },
        {
            "message_id": "1-0",
            "payload": {
                "wire_format": "oneiric-v1",
                "envelope": encode_oneiric_envelope(to_oneiric_envelope(internal)),
            },
        },
    ]
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter),
        handler=Handler(),
    ).replay_pending()

    assert replayed == [internal]
    assert seen == [internal]


@pytest.mark.asyncio
async def test_canonical_reverse_conversion_failure_records_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    adapter.read_payloads = [
        {
            "message_id": "bad-0",
            "payload": {
                "wire_format": "oneiric-v1",
                "envelope": encode_oneiric_envelope(to_oneiric_envelope(internal)),
            },
        }
    ]
    failures: list[tuple[str, str]] = []
    seen: list[EventEnvelope] = []

    def _raise_reverse_conversion_error(*args: Any, **kwargs: Any) -> EventEnvelope:
        raise EventEnvelopeConversionError(
            direction="oneiric_to_mahavishnu",
            reason="reverse_conversion_failed",
        )

    monkeypatch.setattr(
        "mahavishnu.core.events.transport.to_mahavishnu_envelope",
        _raise_reverse_conversion_error,
    )
    monkeypatch.setattr(
        "mahavishnu.core.events.transport.record_wire_decode_failed",
        lambda *, consumer, reason: failures.append((consumer, reason)),
    )

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter),
        handler=Handler(),
    ).replay_pending()

    assert replayed == []
    assert seen == []
    assert failures == [("event_bus_consumer", "reverse_conversion_failed")]


@pytest.mark.asyncio
async def test_pubsub_skips_invalid_utf8_canonical_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[tuple[str, str]] = []
    seen: list[EventEnvelope] = []
    monkeypatch.setattr(
        "mahavishnu.core.events.transport.record_wire_decode_failed",
        lambda *, consumer, reason: failures.append((consumer, reason)),
    )

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    consumer = EventBusConsumer(
        transport=RedisEventTransport(_FakeAdapter()),
        handler=Handler(),
    )
    await consumer.start()
    try:
        await consumer._on_pubsub_message("bodai:events:pool.spawned", b"\xff")
    finally:
        await consumer.stop()

    assert seen == []
    assert ("event_bus_consumer", "canonical_conversion_error") in failures


@pytest.mark.asyncio
async def test_pubsub_skips_canonical_envelope_with_invalid_uuid() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "workflow.completed",
        "test_service",
        payload={"workflow_id": "wf-invalid"},
    )
    invalid = to_oneiric_envelope(internal)
    invalid.headers["event_id"] = "not-a-uuid"
    raw = encode_oneiric_envelope(invalid).encode("utf-8")
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    consumer = EventBusConsumer(
        transport=RedisEventTransport(adapter),
        handler=Handler(),
    )
    await consumer.start()
    try:
        await consumer._on_pubsub_message("bodai:events:workflow.completed", raw)
    finally:
        await consumer.stop()

    assert seen == []


@pytest.mark.asyncio
async def test_pubsub_decodes_canonical_envelope() -> None:
    adapter = _FakeAdapter()
    transport = RedisEventTransport(adapter)
    internal = create_event_envelope(
        "workflow.completed",
        "test_service",
        payload={"workflow_id": "wf-canonical"},
    )
    raw = encode_oneiric_envelope(to_oneiric_envelope(internal)).encode("utf-8")
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    consumer = EventBusConsumer(transport=transport, handler=Handler())
    await consumer.start()
    await consumer._on_pubsub_message("bodai:events:workflow.completed", raw)
    await consumer.stop()

    assert seen == [internal]


@pytest.mark.asyncio
async def test_canonical_marker_never_falls_back_to_legacy() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    adapter.read_payloads = [
        {
            "message_id": "1-0",
            "payload": {
                "wire_format": "oneiric-v1",
                "envelope": internal.to_json(),
            },
        }
    ]
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter, accept_legacy_wire=True),
        handler=Handler(),
    ).replay_pending()

    assert replayed == []
    assert seen == []


@pytest.mark.asyncio
async def test_replay_accepts_legacy_record_when_enabled() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    adapter.read_payloads = [
        {
            "message_id": "1-0",
            "payload": {"envelope": internal.to_json()},
        }
    ]
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter, accept_legacy_wire=True),
        handler=Handler(),
    ).replay_pending()

    assert replayed == [internal]
    assert seen == [internal]


@pytest.mark.asyncio
async def test_replay_rejects_legacy_record_when_disabled() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    adapter.read_payloads = [
        {
            "message_id": "1-0",
            "payload": {"envelope": internal.to_json()},
        }
    ]
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter, accept_legacy_wire=False),
        handler=Handler(),
    ).replay_pending()

    assert replayed == []
    assert seen == []


@pytest.mark.asyncio
async def test_replay_accepts_canonical_record_when_legacy_disabled() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    adapter.read_payloads = [
        {
            "message_id": "1-0",
            "payload": {
                "wire_format": "oneiric-v1",
                "envelope": encode_oneiric_envelope(to_oneiric_envelope(internal)),
            },
        }
    ]
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter, accept_legacy_wire=False),
        handler=Handler(),
    ).replay_pending()

    assert replayed == [internal]
    assert seen == [internal]


@pytest.mark.asyncio
async def test_replay_rejects_unknown_wire_format_marker() -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    adapter.read_payloads = [
        {
            "message_id": "1-0",
            "payload": {
                "wire_format": "oneiric-v2",
                "envelope": encode_oneiric_envelope(to_oneiric_envelope(internal)),
            },
        }
    ]
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter),
        handler=Handler(),
    ).replay_pending()

    assert replayed == []
    assert seen == []


@pytest.mark.asyncio
async def test_malformed_pubsub_payload_is_skipped() -> None:
    adapter = _FakeAdapter()
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            seen.append(envelope)

    consumer = EventBusConsumer(
        transport=RedisEventTransport(adapter),
        handler=Handler(),
    )
    await consumer.start()
    await consumer._on_pubsub_message("bodai:events:pool.spawned", b"{not-json")
    await consumer.stop()

    assert seen == []


@pytest.mark.asyncio
async def test_legacy_decode_records_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeAdapter()
    internal = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    adapter.read_payloads = [
        {
            "message_id": "1-0",
            "payload": {"envelope": internal.to_json()},
        }
    ]
    consumers: list[str] = []
    monkeypatch.setattr(
        "mahavishnu.core.events.transport.record_legacy_decoded",
        lambda *, consumer: consumers.append(consumer),
    )

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            return None

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter),
        handler=Handler(),
    ).replay_pending()

    assert replayed == [internal]
    assert consumers == ["event_bus_consumer"]


@pytest.mark.asyncio
async def test_canonical_decode_failure_records_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _FakeAdapter()
    adapter.read_payloads = [
        {
            "message_id": "bad-0",
            "payload": {"wire_format": "oneiric-v1", "envelope": "{not-json"},
        }
    ]
    failures: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "mahavishnu.core.events.transport.record_wire_decode_failed",
        lambda *, consumer, reason: failures.append((consumer, reason)),
    )

    class Handler:
        async def handle(self, envelope: EventEnvelope) -> None:
            return None

    replayed = await EventBusConsumer(
        transport=RedisEventTransport(adapter),
        handler=Handler(),
    ).replay_pending()

    assert replayed == []
    assert failures == [("event_bus_consumer", "malformed_json")]


@pytest.mark.asyncio
async def test_event_bus_consumer_replays_pending_envelopes():
    adapter = _FakeAdapter()
    envelope = create_event_envelope(
        "pool.spawned",
        "test_service",
        payload={"pool_id": "pool-1"},
    )
    adapter.read_payloads = [
        {
            "message_id": "1-0",
            "payload": {"envelope": envelope.to_json()},
        }
    ]
    transport = RedisEventTransport(adapter)
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, env: EventEnvelope) -> None:
            seen.append(env)

    consumer = EventBusConsumer(transport=transport, handler=Handler())
    replayed = await consumer.replay_pending()

    assert isinstance(replayed[0], EventEnvelope)
    assert replayed == [envelope]
    assert seen == [envelope]


@pytest.mark.asyncio
async def test_event_bus_consumer_subscribes_and_handles_pubsub_messages():
    adapter = _FakeAdapter()
    transport = RedisEventTransport(adapter)
    seen: list[EventEnvelope] = []

    class Handler:
        async def handle(self, env: EventEnvelope) -> None:
            seen.append(env)

    consumer = EventBusConsumer(transport=transport, handler=Handler())
    await consumer.start()

    payload = create_event_envelope(
        "workflow.completed",
        "test_service",
        payload={"workflow_id": "wf-2"},
    ).to_json()
    await consumer._on_pubsub_message("bodai:events:workflow.completed", payload.encode("utf-8"))

    assert adapter.subscribed["pattern"] == "bodai:events:*"
    assert seen[-1].event_type == "workflow.completed"
    await consumer.stop()


@pytest.mark.asyncio
async def test_websocket_event_handler_routes_to_room():
    server = _FakeWebSocketServer()
    handler = WebSocketEventHandler(server)
    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={"workflow_id": "wf-9"},
    )

    result = await handler.handle(envelope)

    assert result["event_type"] == "workflow.started"
    assert isinstance(envelope, EventEnvelope)
    assert server.broadcasts[0][0] == "workflow:wf-9"
    assert server.broadcasts[1][0] == "global"


@pytest.mark.asyncio
async def test_notification_event_handler_routes_notification_metadata():
    router = _FakeNotificationRouter()
    handler = NotificationEventHandler(router)
    envelope = create_event_envelope(
        "workflow.notify",
        "test_service",
        payload={
            "message": "Deploy complete",
            "context": {"service": "demo", "revision": "abc123"},
        },
        metadata={
            "notification": {
                "adapter_key": "notifications.demo",
                "target": "team-chat",
                "title_template": "[{level}] {channel}",
                "include_context": True,
                "extra_payload": {"source_system": "mahavishnu"},
            }
        },
    )

    result = await handler.handle(envelope)

    assert result == "sent"
    assert len(router.calls) == 1
    record, route = router.calls[0]
    assert record["message"] == "Deploy complete"
    assert record["context"] == {"service": "demo", "revision": "abc123"}
    assert record["source"] == "test_service"
    assert route.target == "team-chat"
    assert route.adapter_key == "notifications.demo"
    assert route.title_template == "[{level}] {channel}"


@pytest.mark.asyncio
async def test_composite_event_envelope_handler_invokes_all_handlers():
    websocket_server = _FakeWebSocketServer()
    router = _FakeNotificationRouter()
    composite = CompositeEventEnvelopeHandler(
        (
            WebSocketEventHandler(websocket_server),
            NotificationEventHandler(router),
        )
    )
    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={
            "workflow_id": "wf-123",
            "message": "Workflow started",
            "notification": {
                "adapter_key": "notifications.demo",
                "target": "team-chat",
            },
        },
    )

    result = await composite.handle(envelope)

    assert len(result) == 2
    assert websocket_server.broadcasts[0][0] == "workflow:wf-123"
    assert router.calls[0][1].target == "team-chat"


@pytest.mark.asyncio
async def test_composite_event_envelope_handler_records_app_activity(monkeypatch):
    recorded: list[EventEnvelope] = []
    monkeypatch.setattr(
        "mahavishnu.core.context.get_app_from_context",
        lambda: type("_App", (), {"record_event_activity": recorded.append})(),
    )

    composite = CompositeEventEnvelopeHandler(())
    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={"workflow_id": "wf-321"},
    )

    await composite.handle(envelope)

    assert recorded == [envelope]


@pytest.mark.asyncio
async def test_retrying_event_envelope_handler_routes_exhausted_failure_to_dlq():
    dlq = _FakeDeadLetterQueue()

    class FailingHandler:
        async def handle(self, envelope: EventEnvelope) -> None:
            raise RuntimeError("boom")

    handler = RetryingEventEnvelopeHandler(
        handler=FailingHandler(),
        handler_name="notification",
        max_attempts=2,
        retry_delay_seconds=0.0,
        dead_letter_handler=DLQEventHandler(dlq),
    )
    envelope = create_event_envelope(
        "workflow.started",
        "test_service",
        payload={"workflow_id": "wf-123"},
    )

    result = await handler.handle(envelope)

    assert result["task"]["event_envelope"]["event_type"] == "workflow.started"
    assert result["metadata"]["handler_name"] == "notification"
    assert dlq.calls[0]["task_id"] == str(envelope.event_id)
