from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

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
    transport = RedisEventTransport(adapter)
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
