"""Task Notification System - Real-time task event broadcasting.

Provides event-driven notification system for task changes:

- TaskEventEmitter for publishing events
- Event types for task lifecycle
- Subscription system with filtering
- Integration with WebSocket for real-time updates

Usage:
    from mahavishnu.core.task_notifications import TaskEventEmitter, TaskEventType

    emitter = TaskEventEmitter()

    # Subscribe to events
    def on_task_created(event):
        print(f"Task created: {event.task_id}")

    emitter.subscribe(on_task_created, filter=EventFilter(event_types=[TaskEventType.CREATED]))

    # Emit events
    emitter.emit_task_created(task)
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class TaskEventType(str, Enum):
    """Types of task events."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    PRIORITY_CHANGED = "priority_changed"
    ASSIGNED = "assigned"


@dataclass
class TaskEvent:
    """A task event for broadcasting.

    Attributes:
        event_type: Type of event
        task_id: ID of the affected task
        data: Event-specific data
        timestamp: When event occurred
        metadata: Optional additional metadata
    """

    event_type: TaskEventType
    task_id: str
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_type": self.event_type.value,
            "task_id": self.task_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Convert to JSON string."""
        def json_serial(obj: Any) -> Any:
            """Handle non-serializable objects."""
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")

        return json.dumps(self.to_dict(), default=json_serial)


@dataclass
class EventFilter:
    """Filter for event subscriptions.

    Attributes:
        event_types: Only receive these event types (empty = all)
        task_ids: Only receive events for these tasks (empty = all)
        repositories: Only receive events for these repositories (empty = all)
        predicate: Optional custom filter function
    """

    event_types: list[TaskEventType] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)
    predicate: Callable[[TaskEvent], bool] | None = None

    def matches(self, event: TaskEvent) -> bool:
        """Check if event matches the filter.

        Args:
            event: Event to check

        Returns:
            True if event matches filter
        """
        # Check event type
        if self.event_types and event.event_type not in self.event_types:
            return False

        # Check task ID
        if self.task_ids and event.task_id not in self.task_ids:
            return False

        # Check repository
        if self.repositories:
            task_repo = event.data.get("task", {}).get("repository", "")
            if task_repo not in self.repositories:
                return False

        # Check custom predicate
        if self.predicate is not None:
            return self.predicate(event)

        return True


@dataclass
class EventSubscription:
    """A subscription to task events.

    Attributes:
        subscription_id: Unique subscription identifier
        callback: Function to call when event received
        filter: Optional event filter
        active: Whether subscription is active
        created_at: When subscription was created
    """

    subscription_id: str
    callback: Callable[[TaskEvent], None]
    filter: EventFilter = field(default_factory=EventFilter)
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def deactivate(self) -> None:
        """Deactivate the subscription."""
        self.active = False

    def should_receive(self, event: TaskEvent) -> bool:
        """Check if subscription should receive event.

        Args:
            event: Event to check

        Returns:
            True if subscription should receive event
        """
        if not self.active:
            return False
        return self.filter.matches(event)


class TaskEventEmitter:
    """Event emitter for task notifications.

    Features:
    - Publish/subscribe pattern
    - Event filtering
    - Multiple subscribers per event
    - Convenient emit methods for common events

    Example:
        emitter = TaskEventEmitter()

        # Subscribe
        sub_id = emitter.subscribe(
            callback=handle_event,
            filter=EventFilter(event_types=[TaskEventType.CREATED])
        )

        # Emit events
        emitter.emit_task_created(task)

        # Unsubscribe
        emitter.unsubscribe(sub_id)
    """

    def __init__(self) -> None:
        """Initialize event emitter."""
        self.subscriptions: dict[str, EventSubscription] = {}

    def _generate_id(self) -> str:
        """Generate unique subscription ID."""
        return f"sub-{uuid.uuid4().hex[:8]}"

    def subscribe(
        self,
        callback: Callable[[TaskEvent], None],
        filter: EventFilter | None = None,
    ) -> str:
        """Subscribe to task events.

        Args:
            callback: Function to call when event received
            filter: Optional event filter

        Returns:
            Subscription ID
        """
        sub_id = self._generate_id()
        subscription = EventSubscription(
            subscription_id=sub_id,
            callback=callback,
            filter=filter or EventFilter(),
        )
        self.subscriptions[sub_id] = subscription
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from task events.

        Args:
            subscription_id: Subscription ID to remove

        Returns:
            True if subscription was removed
        """
        if subscription_id in self.subscriptions:
            del self.subscriptions[subscription_id]
            return True
        return False

    def emit(self, event: TaskEvent) -> None:
        """Emit an event to all matching subscribers.

        Args:
            event: Event to emit
        """
        for subscription in self.subscriptions.values():
            if subscription.should_receive(event):
                try:
                    subscription.callback(event)
                except Exception as e:
                    logger.error(
                        f"Error in event callback for {subscription.subscription_id}: {e}"
                    )

    def emit_task_created(
        self,
        task: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """Emit task created event.

        Args:
            task: Created task
            metadata: Optional metadata

        Returns:
            Created event
        """
        event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id=task.get("id", "unknown"),
            data={"task": task},
            metadata=metadata or {},
        )
        self.emit(event)
        return event

    def emit_task_updated(
        self,
        task: dict[str, Any],
        changes: list[str] | None = None,
        previous_values: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """Emit task updated event.

        Args:
            task: Updated task
            changes: List of changed fields
            previous_values: Previous field values
            metadata: Optional metadata

        Returns:
            Created event
        """
        event = TaskEvent(
            event_type=TaskEventType.UPDATED,
            task_id=task.get("id", "unknown"),
            data={
                "task": task,
                "changes": changes or [],
                "previous_values": previous_values or {},
            },
            metadata=metadata or {},
        )
        self.emit(event)
        return event

    def emit_task_deleted(
        self,
        task_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """Emit task deleted event.

        Args:
            task_id: ID of deleted task
            metadata: Optional metadata

        Returns:
            Created event
        """
        event = TaskEvent(
            event_type=TaskEventType.DELETED,
            task_id=task_id,
            data={},
            metadata=metadata or {},
        )
        self.emit(event)
        return event

    def emit_task_completed(
        self,
        task: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """Emit task completed event.

        Args:
            task: Completed task
            metadata: Optional metadata

        Returns:
            Created event
        """
        event = TaskEvent(
            event_type=TaskEventType.COMPLETED,
            task_id=task.get("id", "unknown"),
            data={"task": task},
            metadata=metadata or {},
        )
        self.emit(event)
        return event

    def emit_task_failed(
        self,
        task: dict[str, Any],
        error_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """Emit task failed event.

        Args:
            task: Failed task
            error_message: Error description
            metadata: Optional metadata

        Returns:
            Created event
        """
        event = TaskEvent(
            event_type=TaskEventType.FAILED,
            task_id=task.get("id", "unknown"),
            data={
                "task": task,
                "error_message": error_message,
            },
            metadata=metadata or {},
        )
        self.emit(event)
        return event

    def emit_task_blocked(
        self,
        task: dict[str, Any],
        blocked_by: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """Emit task blocked event.

        Args:
            task: Blocked task
            blocked_by: List of blocking task IDs
            metadata: Optional metadata

        Returns:
            Created event
        """
        event = TaskEvent(
            event_type=TaskEventType.BLOCKED,
            task_id=task.get("id", "unknown"),
            data={
                "task": task,
                "blocked_by": blocked_by,
            },
            metadata=metadata or {},
        )
        self.emit(event)
        return event

    def emit_task_unblocked(
        self,
        task: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> TaskEvent:
        """Emit task unblocked event.

        Args:
            task: Unblocked task
            metadata: Optional metadata

        Returns:
            Created event
        """
        event = TaskEvent(
            event_type=TaskEventType.UNBLOCKED,
            task_id=task.get("id", "unknown"),
            data={"task": task},
            metadata=metadata or {},
        )
        self.emit(event)
        return event

    def get_subscription_count(self) -> int:
        """Get count of active subscriptions.

        Returns:
            Number of active subscriptions
        """
        return sum(1 for sub in self.subscriptions.values() if sub.active)

    def clear_all(self) -> None:
        """Clear all subscriptions."""
        self.subscriptions.clear()


__all__ = [
    "TaskEventEmitter",
    "TaskEventType",
    "TaskEvent",
    "EventSubscription",
    "EventFilter",
]
