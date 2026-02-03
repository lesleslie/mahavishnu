"""Async message passing between pools."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """Message types for inter-pool communication.

    Attributes:
        TASK_DELEGATE: Delegate task from one pool to another
        RESULT_SHARE: Share execution result between pools
        STATUS_UPDATE: Broadcast pool status
        HEARTBEAT: Regular health check
        POOL_CREATED: Announce new pool creation
        POOL_CLOSED: Announce pool shutdown
        TASK_COMPLETED: Announce task completion
    """

    TASK_DELEGATE = "task_delegate"
    RESULT_SHARE = "result_share"
    STATUS_UPDATE = "status_update"
    HEARTBEAT = "heartbeat"
    POOL_CREATED = "pool_created"
    POOL_CLOSED = "pool_closed"
    TASK_COMPLETED = "task_completed"


@dataclass
class Message:
    """Message passed between pools.

    Attributes:
        type: Message type
        source_pool_id: Source pool ID (None if system message)
        target_pool_id: Target pool ID (None for broadcast)
        payload: Message payload dictionary
        timestamp: Message timestamp
    """

    type: MessageType
    source_pool_id: str | None
    target_pool_id: str | None
    payload: dict[str, Any]
    timestamp: float


class MessageBus:
    """Async message bus for inter-pool communication.

    Features:
    - Pub/sub messaging
    - Message filtering by type
    - Async message processing
    - Backpressure handling

    Example:
        ```python
        bus = MessageBus()

        # Subscribe to messages
        async def handle_task_delegate(msg: Message):
            print(f"Received task from {msg.source_pool_id}")

        bus.subscribe(MessageType.TASK_DELEGATE, handle_task_delegate)

        # Publish message
        await bus.publish({
            "type": "task_delegate",
            "source_pool_id": "pool_abc",
            "task": {"prompt": "Hello"},
        })

        # Receive messages
        msg = await bus.receive("pool_def", timeout=5.0)
        ```
    """

    def __init__(self, max_queue_size: int = 1000):
        """Initialize message bus.

        Args:
            max_queue_size: Maximum queue size per pool (backpressure limit)
        """
        self._queues: dict[str, asyncio.Queue] = {}
        self._subscribers: dict[MessageType, list[Callable]] = {}
        self._max_queue_size = max_queue_size

        logger.info(f"MessageBus initialized (max_queue_size={max_queue_size})")

    async def publish(self, message: dict[str, Any]) -> None:
        """Publish message to bus.

        Args:
            message: Message dict with 'type' field

        Message format:
            ```python
            {
                "type": "task_delegate",  # MessageType value
                "source_pool_id": "pool_abc",  # Optional
                "target_pool_id": "pool_def",  # Optional (None = broadcast)
                "payload": {...},  # Message-specific data
            }
            ```
        """
        msg_type_str = message.get("type", "UNKNOWN")
        try:
            msg_type = MessageType(msg_type_str)
        except ValueError:
            logger.warning(f"Unknown message type: {msg_type_str}")
            msg_type = MessageType.STATUS_UPDATE  # Default

        msg = Message(
            type=msg_type,
            source_pool_id=message.get("source_pool_id"),
            target_pool_id=message.get("target_pool_id"),
            payload=message.get("payload", {}),
            timestamp=time.time(),
        )

        # Deliver to target queue if specified
        if msg.target_pool_id:
            # Create queue if it doesn't exist (lazy initialization)
            if msg.target_pool_id not in self._queues:
                self._queues[msg.target_pool_id] = asyncio.Queue(maxsize=self._max_queue_size)

            queue = self._queues[msg.target_pool_id]
            try:
                queue.put_nowait(msg)
                logger.debug(
                    f"Delivered message to pool {msg.target_pool_id} (type={msg_type.value})"
                )
            except asyncio.QueueFull:
                logger.warning(f"Queue full for pool {msg.target_pool_id} - message dropped")

        # Deliver to subscribers
        for subscriber in self._subscribers.get(msg_type, []):
            try:
                # Run subscriber asynchronously
                asyncio.create_task(subscriber(msg))
            except Exception as e:
                logger.error(f"Subscriber error: {e}")

    def subscribe(
        self,
        msg_type: MessageType,
        handler: Callable,
    ) -> None:
        """Subscribe to message type.

        Args:
            msg_type: Type of message to subscribe to
            handler: Async callback function that takes Message as parameter

        Example:
            ```python
            async def handle_status(msg: Message):
                print(f"Pool {msg.source_pool_id} status: {msg.payload}")

            bus.subscribe(MessageType.STATUS_UPDATE, handle_status)
            ```
        """
        if msg_type not in self._subscribers:
            self._subscribers[msg_type] = []

        self._subscribers[msg_type].append(handler)
        logger.info(f"Subscribed to {msg_type.value} (total: {len(self._subscribers[msg_type])})")

    async def receive(
        self,
        pool_id: str,
        timeout: float | None = None,
    ) -> Message | None:
        """Receive message for specific pool.

        Args:
            pool_id: Pool ID to receive messages for
            timeout: Receive timeout in seconds (None = wait forever)

        Returns:
            Message or None if timeout

        Example:
            ```python
            # Wait for message with timeout
            msg = await bus.receive("pool_abc", timeout=5.0)
            if msg:
                print(f"Received: {msg.type}")
            ```
        """
        if pool_id not in self._queues:
            self._queues[pool_id] = asyncio.Queue(maxsize=self._max_queue_size)

        try:
            return await asyncio.wait_for(
                self._queues[pool_id].get(),
                timeout=timeout,
            )
        except TimeoutError:
            return None

    async def receive_batch(
        self,
        pool_id: str,
        count: int,
        timeout: float | None = None,
    ) -> list[Message]:
        """Receive multiple messages for specific pool.

        Args:
            pool_id: Pool ID to receive messages for
            count: Maximum number of messages to receive
            timeout: Total timeout in seconds

        Returns:
            List of messages (up to count items)
        """
        messages = []

        deadline = asyncio.get_event_loop().time() + timeout if timeout else None

        for _ in range(count):
            if deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                msg = await self.receive(pool_id, timeout=remaining)
            else:
                msg = await self.receive(pool_id, timeout=None)

            if msg:
                messages.append(msg)
            else:
                break

        return messages

    def get_queue_size(self, pool_id: str) -> int:
        """Get current queue size for pool.

        Args:
            pool_id: Pool ID

        Returns:
            Current queue size (0 if no queue)
        """
        queue = self._queues.get(pool_id)
        return queue.qsize() if queue else 0

    def get_stats(self) -> dict[str, Any]:
        """Get message bus statistics.

        Returns:
            Statistics dictionary
        """
        queue_sizes = {pool_id: self.get_queue_size(pool_id) for pool_id in self._queues.keys()}

        subscriber_counts = {
            msg_type.value: len(handlers) for msg_type, handlers in self._subscribers.items()
        }

        return {
            "pools_with_queues": len(self._queues),
            "queue_sizes": queue_sizes,
            "subscriber_counts": subscriber_counts,
            "max_queue_size": self._max_queue_size,
        }

    async def clear_queue(self, pool_id: str) -> int:
        """Clear all messages for a specific pool.

        Args:
            pool_id: Pool ID

        Returns:
            Number of messages cleared
        """
        queue = self._queues.get(pool_id)
        if not queue:
            return 0

        count = 0
        while not queue.empty():
            try:
                queue.get_nowait()
                count += 1
            except asyncio.QueueEmpty:
                break

        logger.info(f"Cleared {count} messages for pool {pool_id}")
        return count
