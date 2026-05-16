"""Event transport wrapper for Redis-backed publish/subscribe delivery."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from oneiric.runtime.notifications import NotificationRoute, NotificationRouter

from mahavishnu.core.dead_letter_queue import DeadLetterQueue, RetryPolicy
from mahavishnu.core.events.envelope import EventEnvelope

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    PubSubCallback = Callable[[str, bytes], Awaitable[None] | None]
else:
    PubSubCallback = Any


@runtime_checkable
class EventEnvelopeHandler(Protocol):
    async def handle(self, envelope: EventEnvelope) -> Any: ...


@dataclass
class CompositeEventEnvelopeHandler:
    """Fan-out handler that invokes multiple envelope handlers in order."""

    handlers: tuple[EventEnvelopeHandler, ...]

    async def handle(self, envelope: EventEnvelope) -> list[Any]:
        try:
            from mahavishnu.core.context import get_app_from_context

            app = get_app_from_context()
            if app is not None and hasattr(app, "record_event_activity"):
                app.record_event_activity(envelope)
        except Exception:
            pass
        results: list[Any] = []
        for handler in self.handlers:
            results.append(await handler.handle(envelope))
        return results


@dataclass
class NotificationEventHandler:
    """Bridge canonical event envelopes into Oneiric notifications."""

    notification_router: NotificationRouter
    route_factory: Any = None
    record_factory: Any = None

    async def handle(self, envelope: EventEnvelope) -> Any:
        route = self._resolve_route(envelope)
        if route is None:
            return None
        record = self._resolve_record(envelope)
        return await self.notification_router.send(record, route)

    def _resolve_route(self, envelope: EventEnvelope) -> NotificationRoute | None:
        if callable(self.route_factory):
            return self.route_factory(envelope)
        route_data = self._extract_notification_data(envelope)
        if route_data is None:
            return None
        extra_payload = route_data.get("extra_payload")
        return NotificationRoute(
            adapter_key=route_data.get("adapter_key") or route_data.get("adapter"),
            adapter_provider=route_data.get("adapter_provider") or route_data.get("provider"),
            target=route_data.get("target"),
            channel=route_data.get("channel"),
            title=route_data.get("title"),
            title_template=route_data.get("title_template"),
            include_context=bool(route_data.get("include_context", True)),
            extra_payload=extra_payload if isinstance(extra_payload, dict) else None,
        )

    def _resolve_record(self, envelope: EventEnvelope) -> dict[str, Any]:
        if callable(self.record_factory):
            record = self.record_factory(envelope)
            if isinstance(record, dict):
                return record
            return dict(record)

        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        message = str(
            payload.get("message")
            or payload.get("description")
            or envelope.metadata.get("message")
            or envelope.event_type.replace(".", " ")
        ).strip()
        context = payload.get("context")
        if not isinstance(context, dict):
            context = dict(payload)
        built: dict[str, Any] = {
            "message": message,
            "channel": str(
                payload.get("channel") or envelope.metadata.get("channel") or envelope.event_type
            ),
            "level": str(payload.get("level") or envelope.metadata.get("level") or "info"),
            "context": context,
            "source": envelope.source,
            "correlation_id": (str(envelope.correlation_id) if envelope.correlation_id else None),
            "causation_id": str(envelope.causation_id) if envelope.causation_id else None,
        }
        extra_payload = envelope.metadata.get("notification_extra_payload")
        if isinstance(extra_payload, dict):
            built.update(extra_payload)
        return built

    def _extract_notification_data(self, envelope: EventEnvelope) -> dict[str, Any] | None:
        for candidate in (envelope.metadata, envelope.payload):
            if not isinstance(candidate, dict):
                continue
            notification_data = candidate.get("notification")
            if isinstance(notification_data, dict):
                return notification_data
        return None


@dataclass
class DLQEventHandler:
    """Persist exhausted event deliveries in the Mahavishnu DLQ."""

    dead_letter_queue: DeadLetterQueue

    async def handle(
        self,
        envelope: EventEnvelope,
        *,
        handler_name: str,
        error: Exception,
        attempts: int,
    ) -> Any:
        task = {
            "event_envelope": envelope.to_dict(),
            "handler_name": handler_name,
            "error": str(error),
            "attempts": attempts,
        }
        metadata = {
            "event_type": envelope.event_type,
            "source": envelope.source,
            "correlation_id": str(envelope.correlation_id) if envelope.correlation_id else None,
            "causation_id": str(envelope.causation_id) if envelope.causation_id else None,
            "handler_name": handler_name,
        }
        return await self.dead_letter_queue.enqueue(
            task_id=str(envelope.event_id),
            task=task,
            repos=[],
            error=str(error),
            retry_policy=RetryPolicy.NEVER,
            max_retries=0,
            metadata=metadata,
            error_category="event_handler",
        )


@dataclass
class RetryingEventEnvelopeHandler:
    """Retry an envelope handler and route exhausted failures to the DLQ."""

    handler: EventEnvelopeHandler
    handler_name: str
    max_attempts: int = 3
    retry_delay_seconds: float = 0.0
    dead_letter_handler: DLQEventHandler | None = None

    async def handle(self, envelope: EventEnvelope) -> Any:
        attempts = max(int(self.max_attempts), 1)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await self.handler.handle(envelope)
            except Exception as exc:
                last_error = exc
                if attempt < attempts and self.retry_delay_seconds > 0:
                    delay = self.retry_delay_seconds * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
        if last_error is not None and self.dead_letter_handler is not None:
            return await self.dead_letter_handler.handle(
                envelope,
                handler_name=self.handler_name,
                error=last_error,
                attempts=attempts,
            )
        if last_error is not None:
            raise last_error
        return None


@dataclass
class RedisEventTransport:
    """Thin wrapper around a queue adapter with Redis stream + pub/sub support."""

    adapter: Any
    channel_prefix: str = "bodai:events:"
    stream_name: str = "bodai:events"

    async def publish(self, envelope: EventEnvelope) -> EventEnvelope:
        """Persist and fan out an event envelope."""
        payload = envelope.to_dict()
        await self.adapter.enqueue(
            {
                "event_id": payload["event_id"],
                "event_type": payload["event_type"],
                "version": payload["version"],
                "timestamp": payload["timestamp"],
                "source": payload["source"],
                "correlation_id": payload["correlation_id"] or "",
                "causation_id": payload["causation_id"] or "",
                "payload": json.dumps(payload["payload"], sort_keys=True),
                "metadata": json.dumps(payload["metadata"], sort_keys=True),
                "envelope": envelope.to_json(),
            }
        )
        await self.adapter.pubsub_publish(
            f"{self.channel_prefix}{envelope.event_type}",
            envelope.to_json(),
        )
        return envelope

    async def subscribe(
        self,
        *,
        channel: str | None = None,
        pattern: str | None = None,
        callback: PubSubCallback,
    ) -> Any:
        return await self.adapter.pubsub_subscribe(
            channel=channel,
            pattern=pattern,
            callback=callback,
        )


@dataclass
class EventBusConsumer:
    """Replay-and-subscribe consumer for Redis event streams."""

    transport: RedisEventTransport
    handler: EventEnvelopeHandler
    stream_count: int = 50
    _subscription_task: Any = None
    _running: bool = False
    _replayed_message_ids: set[str] = field(default_factory=set)

    async def start(self) -> None:
        self._running = True
        await self.replay_pending()
        self._subscription_task = await self.transport.subscribe(
            pattern=f"{self.transport.channel_prefix}*",
            callback=self._on_pubsub_message,
        )

    async def stop(self) -> None:
        self._running = False
        if self._subscription_task:
            self._subscription_task.cancel()
            self._subscription_task = None

    async def replay_pending(self) -> list[EventEnvelope]:
        entries = await self.transport.adapter.read(count=self.stream_count)
        envelopes: list[EventEnvelope] = []
        for entry in entries:
            message_id = entry.get("message_id")
            if message_id and message_id in self._replayed_message_ids:
                continue
            payload = entry.get("payload") or {}
            envelope_data = payload.get("envelope") if isinstance(payload, dict) else None
            if not envelope_data:
                continue
            if isinstance(envelope_data, bytes):
                envelope_data = envelope_data.decode("utf-8")
            envelope = EventEnvelope.from_json(str(envelope_data))
            envelopes.append(envelope)
            self._replayed_message_ids.add(message_id or str(envelope.event_id))
            await self.handler.handle(envelope)
        return envelopes

    async def _on_pubsub_message(self, channel: str, raw: bytes) -> None:
        if not self._running:
            return
        envelope = EventEnvelope.from_json(raw.decode("utf-8"))
        await self.handler.handle(envelope)


@dataclass
class WebSocketEventHandler:
    """Bridge event envelopes into WebSocket rooms."""

    websocket_server: Any

    async def handle(self, envelope: EventEnvelope) -> Any:
        room = self._resolve_room(envelope.event_type, envelope.payload)
        event_payload = {
            "event_type": envelope.event_type,
            "event_id": str(envelope.event_id),
            "source": envelope.source,
            "correlation_id": str(envelope.correlation_id) if envelope.correlation_id else None,
            "causation_id": str(envelope.causation_id) if envelope.causation_id else None,
            "payload": envelope.payload,
            "metadata": envelope.metadata,
            "timestamp": envelope.timestamp.isoformat(),
            "version": envelope.version,
        }
        await self.websocket_server.broadcast_to_room(room, event_payload)
        if room.startswith("workflow:"):
            await self.websocket_server.broadcast_to_room("global", event_payload)
        return event_payload

    def _resolve_room(self, event_type: str, payload: dict[str, Any]) -> str:
        if event_type.startswith("workflow.") and payload.get("workflow_id"):
            return f"workflow:{payload['workflow_id']}"
        if event_type.startswith("pool.") and payload.get("pool_id"):
            return f"pool:{payload['pool_id']}"
        if event_type.startswith("worker.") and payload.get("pool_id"):
            return f"pool:{payload['pool_id']}"
        if event_type.startswith("adapter."):
            return "adapters"
        if event_type.startswith("goal_team.") or event_type.startswith("goal-teams."):
            user_id = payload.get("user_id")
            return f"goal-teams:{user_id}" if user_id else "goal-teams"
        if event_type.startswith("code."):
            return "code"
        if event_type.startswith("backup."):
            return "global"
        return "global"
