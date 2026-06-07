"""Unit tests for the inter-pool MessageBus protocol.

Covers:
    1. MessageType enum values
    2. Message dataclass construction
    3. MessageBus.publish routes to target queue
    4. MessageBus.publish invokes subscribers
    5. MessageBus.subscribe records handler
    6. MessageBus.receive / receive_batch
    7. MessageBus.get_queue_size, get_stats, clear_queue
    8. MessageBus with event_publisher (canonical envelope)
    9. set_event_publisher can replace the publisher
   10. publish() with unknown message type falls back to STATUS_UPDATE
   11. publish() drops on QueueFull (no exception propagates)
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.events.contract import EventPublisherProtocol
from mahavishnu.mcp.protocols.message_bus import (
    Message,
    MessageBus,
    MessageType,
)

pytestmark = pytest.mark.unit


# ============== Fixtures ==============


@pytest.fixture
def bus() -> MessageBus:
    """Create a fresh MessageBus for each test."""
    return MessageBus(max_queue_size=10)


@pytest.fixture
def small_bus() -> MessageBus:
    """Create a bus with a tiny queue to exercise backpressure."""
    return MessageBus(max_queue_size=1)


@pytest.fixture
def sample_message() -> Message:
    """Build a sample Message dataclass instance."""
    return Message(
        type=MessageType.TASK_DELEGATE,
        source_pool_id="pool_a",
        target_pool_id="pool_b",
        payload={"task": "hello"},
        timestamp=time.time(),
    )


# ============== MessageType & Message ==============


class TestMessageType:
    """Tests for the MessageType enum."""

    def test_all_expected_values_present(self):
        """MessageType exposes the documented set of values."""
        values = {m.value for m in MessageType}
        assert values == {
            "task_delegate",
            "result_share",
            "status_update",
            "heartbeat",
            "pool_created",
            "pool_closed",
            "task_completed",
        }

    def test_enum_members_are_distinct(self):
        """Each MessageType member must have a unique .value."""
        values = [m.value for m in MessageType]
        assert len(values) == len(set(values))


class TestMessageDataclass:
    """Tests for the Message dataclass."""

    def test_construction_with_all_fields(self, sample_message: Message) -> None:
        """Message stores all four required fields verbatim."""
        assert sample_message.type is MessageType.TASK_DELEGATE
        assert sample_message.source_pool_id == "pool_a"
        assert sample_message.target_pool_id == "pool_b"
        assert sample_message.payload == {"task": "hello"}
        assert isinstance(sample_message.timestamp, float)

    def test_optional_pool_ids_default_to_none(self) -> None:
        """source/target pool IDs are optional and default to None."""
        msg = Message(
            type=MessageType.HEARTBEAT,
            source_pool_id=None,
            target_pool_id=None,
            payload={},
            timestamp=0.0,
        )
        assert msg.source_pool_id is None
        assert msg.target_pool_id is None


# ============== Publish / Target Queue ==============


class TestPublishToTarget:
    """Tests for direct queue delivery via publish()."""

    @pytest.mark.asyncio
    async def test_publish_to_specific_target_creates_queue(self, bus: MessageBus) -> None:
        """Publishing to a target lazily creates its queue and stores the message."""
        await bus.publish(
            {
                "type": "task_delegate",
                "source_pool_id": "pool_a",
                "target_pool_id": "pool_b",
                "payload": {"k": "v"},
            }
        )

        assert bus.get_queue_size("pool_b") == 1

    @pytest.mark.asyncio
    async def test_received_message_round_trip(self, bus: MessageBus) -> None:
        """A message published with a target is received in full."""
        await bus.publish(
            {
                "type": "status_update",
                "source_pool_id": "pool_a",
                "target_pool_id": "pool_b",
                "payload": {"state": "running"},
            }
        )

        msg = await bus.receive("pool_b", timeout=0.5)
        assert msg is not None
        assert msg.type is MessageType.STATUS_UPDATE
        assert msg.source_pool_id == "pool_a"
        assert msg.payload == {"state": "running"}

    @pytest.mark.asyncio
    async def test_publish_without_target_does_not_create_queue(self, bus: MessageBus) -> None:
        """Broadcast (no target) messages do not create a queue."""
        await bus.publish(
            {
                "type": "heartbeat",
                "source_pool_id": "pool_a",
                "payload": {},
            }
        )
        # No target specified, no queues should exist
        assert bus.get_stats()["pools_with_queues"] == 0

    @pytest.mark.asyncio
    async def test_queue_full_silently_drops_message(self, small_bus: MessageBus) -> None:
        """A QueueFull does NOT raise — the message is logged and dropped."""
        # Fill the tiny queue (size 1)
        await small_bus.publish(
            {
                "type": "status_update",
                "target_pool_id": "p",
                "payload": {"i": 1},
            }
        )
        # Second publish should hit QueueFull and not raise
        await small_bus.publish(
            {
                "type": "status_update",
                "target_pool_id": "p",
                "payload": {"i": 2},
            }
        )
        assert small_bus.get_queue_size("p") == 1


# ============== Publish / Subscribers ==============


class TestPublishSubscribers:
    """Tests for the pub/sub side of publish()."""

    @pytest.mark.asyncio
    async def test_subscriber_receives_matching_message(self, bus: MessageBus) -> None:
        """A subscribed handler is invoked when matching message is published."""
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        bus.subscribe(MessageType.TASK_DELEGATE, handler)

        await bus.publish(
            {
                "type": "task_delegate",
                "source_pool_id": "pool_a",
                "payload": {"x": 1},
            }
        )

        # Subscriber is dispatched via asyncio.create_task
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.01)
        assert len(received) == 1
        assert received[0].type is MessageType.TASK_DELEGATE
        assert received[0].payload == {"x": 1}

    @pytest.mark.asyncio
    async def test_subscriber_not_invoked_for_other_types(self, bus: MessageBus) -> None:
        """Subscribers only fire for their registered message type."""
        received: list[Message] = []

        async def handler(msg: Message) -> None:
            received.append(msg)

        bus.subscribe(MessageType.HEARTBEAT, handler)

        await bus.publish({"type": "status_update", "payload": {}})

        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.01)
        assert received == []

    @pytest.mark.asyncio
    async def test_multiple_subscribers_for_same_type(self, bus: MessageBus) -> None:
        """All subscribers for a type receive each published message."""
        seen_a: list[Message] = []
        seen_b: list[Message] = []

        async def handler_a(msg: Message) -> None:
            seen_a.append(msg)

        async def handler_b(msg: Message) -> None:
            seen_b.append(msg)

        bus.subscribe(MessageType.POOL_CREATED, handler_a)
        bus.subscribe(MessageType.POOL_CREATED, handler_b)

        await bus.publish({"type": "pool_created", "payload": {"name": "p1"}})

        for _ in range(30):
            if seen_a and seen_b:
                break
            await asyncio.sleep(0.01)
        assert len(seen_a) == 1
        assert len(seen_b) == 1


# ============== Receive ==============


class TestReceive:
    """Tests for receive() and receive_batch()."""

    @pytest.mark.asyncio
    async def test_receive_returns_none_on_timeout(self, bus: MessageBus) -> None:
        """receive() returns None when the queue is empty and timeout elapses."""
        msg = await bus.receive("no_such_pool", timeout=0.05)
        assert msg is None

    @pytest.mark.asyncio
    async def test_receive_lazily_creates_queue(self, bus: MessageBus) -> None:
        """receive() for an unknown pool creates the queue, then times out cleanly."""
        # Trigger lazy creation
        assert await bus.receive("ghost", timeout=0.01) is None
        # Queue should now exist (with size 0)
        assert "ghost" in bus._queues
        assert bus.get_queue_size("ghost") == 0

    @pytest.mark.asyncio
    async def test_receive_batch_collects_messages(self, bus: MessageBus) -> None:
        """receive_batch() returns all currently-queued messages."""
        for i in range(3):
            await bus.publish(
                {
                    "type": "status_update",
                    "target_pool_id": "p",
                    "payload": {"i": i},
                }
            )
        msgs = await bus.receive_batch("p", count=3, timeout=0.1)
        assert len(msgs) == 3
        payloads = [m.payload["i"] for m in msgs]
        assert sorted(payloads) == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_receive_batch_returns_fewer_when_queue_drains(self, bus: MessageBus) -> None:
        """receive_batch() exits early when the queue empties."""
        await bus.publish(
            {
                "type": "status_update",
                "target_pool_id": "p",
                "payload": {"i": 0},
            }
        )
        msgs = await bus.receive_batch("p", count=5, timeout=0.1)
        assert len(msgs) == 1


# ============== Stats / Clear ==============


class TestStatsAndClear:
    """Tests for get_queue_size, get_stats, and clear_queue."""

    @pytest.mark.asyncio
    async def test_get_queue_size_zero_for_unknown_pool(self, bus: MessageBus) -> None:
        """Unknown pool returns 0, not raising."""
        assert bus.get_queue_size("nope") == 0

    @pytest.mark.asyncio
    async def test_get_stats_reports_queues_and_subscribers(self, bus: MessageBus) -> None:
        """get_stats returns queue sizes, subscriber counts, and max_queue_size."""
        bus.subscribe(MessageType.HEARTBEAT, lambda m: None)
        bus.subscribe(MessageType.HEARTBEAT, lambda m: None)
        await bus.publish(
            {
                "type": "status_update",
                "target_pool_id": "p1",
                "payload": {},
            }
        )
        await bus.publish(
            {
                "type": "status_update",
                "target_pool_id": "p1",
                "payload": {},
            }
        )

        stats = bus.get_stats()
        assert stats["pools_with_queues"] == 1
        assert stats["queue_sizes"] == {"p1": 2}
        assert stats["subscriber_counts"]["heartbeat"] == 2
        assert stats["max_queue_size"] == 10

    @pytest.mark.asyncio
    async def test_clear_queue_empties_messages(self, bus: MessageBus) -> None:
        """clear_queue returns the number of cleared messages and drains the queue."""
        for i in range(3):
            await bus.publish(
                {
                    "type": "status_update",
                    "target_pool_id": "p",
                    "payload": {"i": i},
                }
            )
        assert bus.get_queue_size("p") == 3

        cleared = await bus.clear_queue("p")
        assert cleared == 3
        assert bus.get_queue_size("p") == 0

    @pytest.mark.asyncio
    async def test_clear_queue_unknown_pool_returns_zero(self, bus: MessageBus) -> None:
        """Clearing an unknown pool returns 0 without raising."""
        assert await bus.clear_queue("nope") == 0


# ============== Event Publisher ==============


class TestEventPublisherIntegration:
    """Tests for the canonical event publisher plumbing."""

    @pytest.mark.asyncio
    async def test_publish_calls_event_publisher_with_envelope(self) -> None:
        """publish() forwards a canonical envelope to the configured publisher."""
        publisher = MagicMock(spec=EventPublisherProtocol)
        publisher.publish = AsyncMock()
        bus = MessageBus(event_publisher=publisher)

        await bus.publish(
            {
                "type": "task_completed",
                "source_pool_id": "pool_a",
                "target_pool_id": "pool_b",
                "payload": {"result": "ok"},
            }
        )

        publisher.publish.assert_awaited_once()
        envelope = publisher.publish.await_args.args[0]
        assert envelope.event_type == "pool.task_completed"
        assert envelope.source == "message_bus"
        assert envelope.payload["source_pool_id"] == "pool_a"
        assert envelope.payload["target_pool_id"] == "pool_b"
        assert envelope.payload["message_type"] == "task_completed"

    @pytest.mark.asyncio
    async def test_publish_without_publisher_is_safe(self) -> None:
        """No publisher configured -> publish still works (canonical step is a no-op)."""
        bus = MessageBus()  # no publisher
        await bus.publish(
            {
                "type": "heartbeat",
                "target_pool_id": "p",
                "payload": {},
            }
        )
        assert bus.get_queue_size("p") == 1

    def test_set_event_publisher_replaces_publisher(self) -> None:
        """set_event_publisher swaps the publisher instance."""
        bus = MessageBus()
        new_pub = MagicMock(spec=EventPublisherProtocol)
        bus.set_event_publisher(new_pub)
        assert bus._event_publisher is new_pub

    def test_set_event_publisher_can_clear(self) -> None:
        """set_event_publisher(None) clears the publisher."""
        bus = MessageBus(event_publisher=MagicMock(spec=EventPublisherProtocol))
        bus.set_event_publisher(None)
        assert bus._event_publisher is None


# ============== Edge cases ==============


class TestPublishEdgeCases:
    """Edge cases around unknown message types and defaulting behavior."""

    @pytest.mark.asyncio
    async def test_unknown_message_type_defaults_to_status_update(self, bus: MessageBus) -> None:
        """An unknown message type string falls back to STATUS_UPDATE."""
        await bus.publish(
            {
                "type": "totally_made_up",
                "target_pool_id": "p",
                "payload": {"k": "v"},
            }
        )
        msg = await bus.receive("p", timeout=0.1)
        assert msg is not None
        assert msg.type is MessageType.STATUS_UPDATE

    @pytest.mark.asyncio
    async def test_publish_missing_type_field_uses_unknown(self, bus: MessageBus) -> None:
        """A message without a 'type' field is treated as UNKNOWN and falls back."""
        await bus.publish({"target_pool_id": "p", "payload": {}})
        msg = await bus.receive("p", timeout=0.1)
        assert msg is not None
        assert msg.type is MessageType.STATUS_UPDATE
