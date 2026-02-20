"""Tests for Task Notification System - Real-time task event broadcasting."""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from mahavishnu.core.task_notifications import (
    TaskEventEmitter,
    TaskEventType,
    TaskEvent,
    EventSubscription,
    EventFilter,
)


@pytest.fixture
def sample_task() -> dict[str, Any]:
    """Create a sample task."""
    return {
        "id": "task-123",
        "title": "Test Task",
        "status": "in_progress",
        "priority": "high",
        "repository": "mahavishnu",
        "created_at": datetime.now(UTC),
    }


@pytest.fixture
def sample_event_data(sample_task: dict[str, Any]) -> dict[str, Any]:
    """Create sample event data."""
    return {
        "task": sample_task,
        "previous_status": "pending",
        "changed_by": "user-1",
    }


class TestTaskEventType:
    """Tests for TaskEventType enum."""

    def test_event_types(self) -> None:
        """Test available event types."""
        assert TaskEventType.CREATED.value == "created"
        assert TaskEventType.UPDATED.value == "updated"
        assert TaskEventType.DELETED.value == "deleted"
        assert TaskEventType.COMPLETED.value == "completed"
        assert TaskEventType.FAILED.value == "failed"
        assert TaskEventType.BLOCKED.value == "blocked"
        assert TaskEventType.UNBLOCKED.value == "unblocked"
        assert TaskEventType.PRIORITY_CHANGED.value == "priority_changed"
        assert TaskEventType.ASSIGNED.value == "assigned"


class TestTaskEvent:
    """Tests for TaskEvent class."""

    def test_create_event(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Create a task event."""
        event = TaskEvent(
            event_type=TaskEventType.UPDATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        assert event.event_type == TaskEventType.UPDATED
        assert event.task_id == "task-123"
        assert event.data["task"]["id"] == "task-123"
        assert event.timestamp is not None

    def test_event_with_metadata(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Create event with metadata."""
        event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id="task-123",
            data={"task": sample_task},
            metadata={"source": "api", "version": "1.0"},
        )

        assert event.metadata["source"] == "api"
        assert event.metadata["version"] == "1.0"

    def test_event_to_dict(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Convert event to dictionary."""
        event = TaskEvent(
            event_type=TaskEventType.COMPLETED,
            task_id="task-123",
            data={"task": sample_task},
        )

        d = event.to_dict()

        assert d["event_type"] == "completed"
        assert d["task_id"] == "task-123"
        assert "timestamp" in d
        assert d["data"]["task"]["id"] == "task-123"

    def test_event_to_json(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Convert event to JSON string."""
        event = TaskEvent(
            event_type=TaskEventType.UPDATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        json_str = event.to_json()

        assert '"event_type": "updated"' in json_str
        assert '"task_id": "task-123"' in json_str


class TestEventFilter:
    """Tests for EventFilter class."""

    def test_create_filter(self) -> None:
        """Create an event filter."""
        filter = EventFilter(
            event_types=[TaskEventType.CREATED, TaskEventType.UPDATED],
            task_ids=["task-123"],
        )

        assert TaskEventType.CREATED in filter.event_types
        assert "task-123" in filter.task_ids

    def test_filter_matches_event_type(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Filter matches by event type."""
        filter = EventFilter(event_types=[TaskEventType.CREATED])

        event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        assert filter.matches(event) is True

    def test_filter_excludes_event_type(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Filter excludes by event type."""
        filter = EventFilter(event_types=[TaskEventType.CREATED])

        event = TaskEvent(
            event_type=TaskEventType.DELETED,
            task_id="task-123",
            data={"task": sample_task},
        )

        assert filter.matches(event) is False

    def test_filter_matches_task_id(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Filter matches by task ID."""
        filter = EventFilter(task_ids=["task-123", "task-456"])

        event = TaskEvent(
            event_type=TaskEventType.UPDATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        assert filter.matches(event) is True

    def test_filter_excludes_task_id(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Filter excludes by task ID."""
        filter = EventFilter(task_ids=["task-456"])

        event = TaskEvent(
            event_type=TaskEventType.UPDATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        assert filter.matches(event) is False

    def test_filter_matches_repository(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Filter matches by repository."""
        filter = EventFilter(repositories=["mahavishnu"])

        event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        assert filter.matches(event) is True

    def test_filter_no_restrictions(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Filter with no restrictions matches all."""
        filter = EventFilter()

        event = TaskEvent(
            event_type=TaskEventType.DELETED,
            task_id="task-999",
            data={"task": {"repository": "unknown"}},
        )

        assert filter.matches(event) is True

    def test_filter_custom_predicate(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Filter with custom predicate."""
        filter = EventFilter(
            predicate=lambda e: e.data.get("task", {}).get("priority") == "high"
        )

        event = TaskEvent(
            event_type=TaskEventType.UPDATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        assert filter.matches(event) is True


class TestEventSubscription:
    """Tests for EventSubscription class."""

    def test_create_subscription(self) -> None:
        """Create an event subscription."""
        callback = MagicMock()
        filter = EventFilter(event_types=[TaskEventType.CREATED])

        sub = EventSubscription(
            subscription_id="sub-123",
            callback=callback,
            filter=filter,
        )

        assert sub.subscription_id == "sub-123"
        assert sub.callback == callback
        assert sub.active is True

    def test_subscription_deactivate(self) -> None:
        """Deactivate a subscription."""
        callback = MagicMock()
        sub = EventSubscription(
            subscription_id="sub-123",
            callback=callback,
        )

        sub.deactivate()

        assert sub.active is False

    def test_subscription_should_receive(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Check if subscription should receive event."""
        callback = MagicMock()
        filter = EventFilter(event_types=[TaskEventType.CREATED])
        sub = EventSubscription(
            subscription_id="sub-123",
            callback=callback,
            filter=filter,
        )

        event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        assert sub.should_receive(event) is True

    def test_inactive_subscription_should_not_receive(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Inactive subscription should not receive events."""
        callback = MagicMock()
        sub = EventSubscription(
            subscription_id="sub-123",
            callback=callback,
        )
        sub.deactivate()

        event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        assert sub.should_receive(event) is False


class TestTaskEventEmitter:
    """Tests for TaskEventEmitter class."""

    def test_create_emitter(self) -> None:
        """Create a task event emitter."""
        emitter = TaskEventEmitter()

        assert emitter is not None
        assert len(emitter.subscriptions) == 0

    def test_subscribe(self) -> None:
        """Subscribe to events."""
        emitter = TaskEventEmitter()
        callback = MagicMock()

        sub_id = emitter.subscribe(callback)

        assert sub_id is not None
        assert len(emitter.subscriptions) == 1

    def test_subscribe_with_filter(self) -> None:
        """Subscribe with event filter."""
        emitter = TaskEventEmitter()
        callback = MagicMock()
        filter = EventFilter(event_types=[TaskEventType.CREATED])

        sub_id = emitter.subscribe(callback, filter=filter)

        assert sub_id is not None
        sub = emitter.subscriptions[sub_id]
        assert sub.filter == filter

    def test_unsubscribe(self) -> None:
        """Unsubscribe from events."""
        emitter = TaskEventEmitter()
        callback = MagicMock()

        sub_id = emitter.subscribe(callback)
        assert len(emitter.subscriptions) == 1

        result = emitter.unsubscribe(sub_id)

        assert result is True
        assert len(emitter.subscriptions) == 0

    def test_unsubscribe_nonexistent(self) -> None:
        """Unsubscribe from nonexistent subscription."""
        emitter = TaskEventEmitter()

        result = emitter.unsubscribe("nonexistent")

        assert result is False

    def test_emit_event(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit an event to subscribers."""
        emitter = TaskEventEmitter()
        callback = MagicMock()
        emitter.subscribe(callback)

        event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id="task-123",
            data={"task": sample_task},
        )
        emitter.emit(event)

        callback.assert_called_once_with(event)

    def test_emit_to_multiple_subscribers(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit event to multiple subscribers."""
        emitter = TaskEventEmitter()
        callback1 = MagicMock()
        callback2 = MagicMock()

        emitter.subscribe(callback1)
        emitter.subscribe(callback2)

        event = TaskEvent(
            event_type=TaskEventType.UPDATED,
            task_id="task-123",
            data={"task": sample_task},
        )
        emitter.emit(event)

        callback1.assert_called_once_with(event)
        callback2.assert_called_once_with(event)

    def test_emit_with_filter(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit event with filtered subscription."""
        emitter = TaskEventEmitter()

        # Only receive CREATED events
        callback_created = MagicMock()
        filter_created = EventFilter(event_types=[TaskEventType.CREATED])
        emitter.subscribe(callback_created, filter=filter_created)

        # Receive all events
        callback_all = MagicMock()
        emitter.subscribe(callback_all)

        created_event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id="task-123",
            data={"task": sample_task},
        )
        updated_event = TaskEvent(
            event_type=TaskEventType.UPDATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        emitter.emit(created_event)
        emitter.emit(updated_event)

        # callback_created only receives CREATED
        callback_created.assert_called_once_with(created_event)

        # callback_all receives both
        assert callback_all.call_count == 2

    def test_emit_to_inactive_subscription(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit event to inactive subscription."""
        emitter = TaskEventEmitter()
        callback = MagicMock()

        sub_id = emitter.subscribe(callback)
        emitter.subscriptions[sub_id].deactivate()

        event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id="task-123",
            data={"task": sample_task},
        )
        emitter.emit(event)

        callback.assert_not_called()

    def test_emit_task_created(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit task created event."""
        emitter = TaskEventEmitter()
        callback = MagicMock()
        emitter.subscribe(callback)

        event = emitter.emit_task_created(sample_task)

        assert event.event_type == TaskEventType.CREATED
        assert event.task_id == "task-123"
        callback.assert_called_once()

    def test_emit_task_updated(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit task updated event."""
        emitter = TaskEventEmitter()
        callback = MagicMock()
        emitter.subscribe(callback)

        event = emitter.emit_task_updated(
            sample_task,
            changes=["status", "priority"],
        )

        assert event.event_type == TaskEventType.UPDATED
        assert "changes" in event.data
        assert "status" in event.data["changes"]

    def test_emit_task_deleted(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit task deleted event."""
        emitter = TaskEventEmitter()
        callback = MagicMock()
        emitter.subscribe(callback)

        event = emitter.emit_task_deleted("task-123")

        assert event.event_type == TaskEventType.DELETED
        assert event.task_id == "task-123"

    def test_emit_task_completed(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit task completed event."""
        emitter = TaskEventEmitter()
        callback = MagicMock()
        emitter.subscribe(callback)

        event = emitter.emit_task_completed(sample_task)

        assert event.event_type == TaskEventType.COMPLETED

    def test_emit_task_failed(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit task failed event."""
        emitter = TaskEventEmitter()
        callback = MagicMock()
        emitter.subscribe(callback)

        event = emitter.emit_task_failed(
            sample_task,
            error_message="Something went wrong",
        )

        assert event.event_type == TaskEventType.FAILED
        assert event.data["error_message"] == "Something went wrong"

    def test_emit_task_blocked(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit task blocked event."""
        emitter = TaskEventEmitter()
        callback = MagicMock()
        emitter.subscribe(callback)

        event = emitter.emit_task_blocked(
            sample_task,
            blocked_by=["task-456"],
        )

        assert event.event_type == TaskEventType.BLOCKED
        assert "task-456" in event.data["blocked_by"]

    def test_emit_task_unblocked(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Emit task unblocked event."""
        emitter = TaskEventEmitter()
        callback = MagicMock()
        emitter.subscribe(callback)

        event = emitter.emit_task_unblocked(sample_task)

        assert event.event_type == TaskEventType.UNBLOCKED

    def test_get_subscription_count(self) -> None:
        """Get active subscription count."""
        emitter = TaskEventEmitter()
        callback = MagicMock()

        assert emitter.get_subscription_count() == 0

        sub_id = emitter.subscribe(callback)
        assert emitter.get_subscription_count() == 1

        emitter.subscriptions[sub_id].deactivate()
        assert emitter.get_subscription_count() == 0

    def test_clear_all_subscriptions(self) -> None:
        """Clear all subscriptions."""
        emitter = TaskEventEmitter()
        callback = MagicMock()

        emitter.subscribe(callback)
        emitter.subscribe(callback)
        assert len(emitter.subscriptions) == 2

        emitter.clear_all()

        assert len(emitter.subscriptions) == 0

    def test_callback_error_handling(
        self,
        sample_task: dict[str, Any],
    ) -> None:
        """Callback errors don't affect other callbacks."""
        emitter = TaskEventEmitter()

        # First callback raises error
        def error_callback(event: TaskEvent) -> None:
            raise RuntimeError("Callback error")

        callback_ok = MagicMock()

        emitter.subscribe(error_callback)
        emitter.subscribe(callback_ok)

        event = TaskEvent(
            event_type=TaskEventType.CREATED,
            task_id="task-123",
            data={"task": sample_task},
        )

        # Should not raise, and second callback should still be called
        emitter.emit(event)

        callback_ok.assert_called_once_with(event)
