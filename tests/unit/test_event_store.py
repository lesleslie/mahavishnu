"""Tests for Event Store Module.

Tests cover:
- Event creation and serialization
- Event persistence
- State reconstruction
- Event queries
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, UTC

from mahavishnu.core.event_store import (
    EventStore,
    TaskEvent,
    TaskEventType,
    TaskState,
)


class TestTaskEventType:
    """Test task event type enum."""

    def test_all_event_types(self) -> None:
        """Test all event types exist."""
        expected_types = [
            "created",
            "updated",
            "deleted",
            "status_changed",
            "priority_changed",
            "assigned",
            "unassigned",
            "blocked",
            "unblocked",
            "completed",
            "failed",
            "cancelled",
            "dependency_added",
            "dependency_removed",
            "comment_added",
            "tag_added",
            "tag_removed",
            "webhook_received",
            "synced",
        ]

        for event_type in expected_types:
            assert TaskEventType(event_type).value == event_type


class TestTaskEvent:
    """Test task event."""

    def test_create_event(self) -> None:
        """Test event creation."""
        event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.CREATED,
            data={"title": "New task"},
            actor="user@example.com",
        )

        assert event.task_id == "task-123"
        assert event.event_type == TaskEventType.CREATED
        assert event.data == {"title": "New task"}
        assert event.actor == "user@example.com"
        assert event.id is not None
        assert event.occurred_at is not None

    def test_create_event_with_correlation_id(self) -> None:
        """Test event creation with correlation ID."""
        correlation_id = "corr-456"

        event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.STATUS_CHANGED,
            data={"new_status": "in_progress"},
            actor="user@example.com",
            correlation_id=correlation_id,
        )

        assert event.correlation_id == correlation_id

    def test_create_event_with_idempotency_key(self) -> None:
        """Test event creation with idempotency key."""
        idempotency_key = "idem-789"

        event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.UPDATED,
            data={"title": "Updated task"},
            actor="user@example.com",
            idempotency_key=idempotency_key,
        )

        assert event.idempotency_key == idempotency_key

    def test_to_dict(self) -> None:
        """Test event serialization."""
        event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.CREATED,
            data={"title": "Test"},
            actor="user@example.com",
        )

        result = event.to_dict()

        assert result["task_id"] == "task-123"
        assert result["event_type"] == "created"
        assert result["data"] == {"title": "Test"}
        assert result["actor"] == "user@example.com"
        assert "occurred_at" in result

    def test_from_row(self) -> None:
        """Test event deserialization from database row."""
        row = {
            "id": "event-id",
            "task_id": "task-123",
            "event_type": "created",
            "event_data": {"title": "Test"},
            "actor": "user@example.com",
            "occurred_at": datetime.now(UTC),
            "correlation_id": None,
            "idempotency_key": None,
        }

        event = TaskEvent.from_row(row)

        assert event.id == "event-id"
        assert event.task_id == "task-123"
        assert event.event_type == TaskEventType.CREATED
        assert event.data == {"title": "Test"}


class TestTaskState:
    """Test task state reconstruction."""

    def test_initial_state(self) -> None:
        """Test initial state."""
        state = TaskState(task_id="task-123")

        assert state.task_id == "task-123"
        assert state.title == ""
        assert state.status == "pending"
        assert state.priority == "medium"
        assert state.is_deleted is False
        assert state.version == 0

    def test_apply_created_event(self) -> None:
        """Test applying created event."""
        state = TaskState(task_id="task-123")
        event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.CREATED,
            data={
                "title": "New task",
                "description": "Description",
                "repository": "mahavishnu",
                "status": "pending",
                "priority": "high",
                "tags": ["backend", "api"],
            },
            actor="user@example.com",
        )

        state.apply_event(event)

        assert state.title == "New task"
        assert state.description == "Description"
        assert state.repository == "mahavishnu"
        assert state.status == "pending"
        assert state.priority == "high"
        assert state.tags == ["backend", "api"]
        assert state.version == 1
        assert state.created_at is not None

    def test_apply_status_changed_event(self) -> None:
        """Test applying status changed event."""
        state = TaskState(task_id="task-123", status="pending")
        event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.STATUS_CHANGED,
            data={"new_status": "in_progress"},
            actor="user@example.com",
        )

        state.apply_event(event)

        assert state.status == "in_progress"
        assert state.version == 1

    def test_apply_assigned_event(self) -> None:
        """Test applying assigned event."""
        state = TaskState(task_id="task-123")
        event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.ASSIGNED,
            data={"assignee": "dev@example.com"},
            actor="manager@example.com",
        )

        state.apply_event(event)

        assert state.assignee == "dev@example.com"

    def test_apply_completed_event(self) -> None:
        """Test applying completed event."""
        state = TaskState(task_id="task-123", status="in_progress")
        event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.COMPLETED,
            data={},
            actor="dev@example.com",
        )

        state.apply_event(event)

        assert state.status == "completed"
        assert state.completed_at is not None

    def test_apply_tag_events(self) -> None:
        """Test applying tag added/removed events."""
        state = TaskState(task_id="task-123", tags=[])

        # Add tag
        add_event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.TAG_ADDED,
            data={"tag": "urgent"},
            actor="user@example.com",
        )
        state.apply_event(add_event)
        assert "urgent" in state.tags

        # Remove tag
        remove_event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.TAG_REMOVED,
            data={"tag": "urgent"},
            actor="user@example.com",
        )
        state.apply_event(remove_event)
        assert "urgent" not in state.tags

    def test_apply_deleted_event(self) -> None:
        """Test applying deleted event."""
        state = TaskState(task_id="task-123")
        event = TaskEvent.create(
            task_id="task-123",
            event_type=TaskEventType.DELETED,
            data={},
            actor="user@example.com",
        )

        state.apply_event(event)

        assert state.is_deleted is True

    def test_to_dict(self) -> None:
        """Test state serialization."""
        state = TaskState(
            task_id="task-123",
            title="Test Task",
            repository="mahavishnu",
            status="in_progress",
            priority="high",
            tags=["backend"],
            version=5,
        )

        result = state.to_dict()

        assert result["task_id"] == "task-123"
        assert result["title"] == "Test Task"
        assert result["repository"] == "mahavishnu"
        assert result["status"] == "in_progress"
        assert result["priority"] == "high"
        assert result["tags"] == ["backend"]
        assert result["version"] == 5


class TestEventStore:
    """Test event store."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()
        db.execute = AsyncMock()
        db.fetch = AsyncMock(return_value=[])
        db.fetchrow = AsyncMock(return_value=None)
        return db

    @pytest.fixture
    def store(self, mock_db: MagicMock) -> EventStore:
        """Create event store with mock database."""
        return EventStore(mock_db)

    @pytest.mark.asyncio
    async def test_append_event(self, store: EventStore) -> None:
        """Test appending an event."""
        event = await store.append(
            task_id="task-123",
            event_type=TaskEventType.CREATED,
            data={"title": "New task"},
            actor="user@example.com",
        )

        assert event is not None
        assert event.task_id == "task-123"
        assert event.event_type == TaskEventType.CREATED
        store.db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_task_events(self, store: EventStore) -> None:
        """Test getting task events."""
        store.db.fetch = AsyncMock(
            return_value=[
                {
                    "id": "event-1",
                    "task_id": "task-123",
                    "event_type": "created",
                    "event_data": {"title": "Test"},
                    "actor": "user@example.com",
                    "occurred_at": datetime.now(UTC),
                    "correlation_id": None,
                    "idempotency_key": None,
                }
            ]
        )

        events = await store.get_task_events("task-123")

        assert len(events) == 1
        assert events[0].task_id == "task-123"

    @pytest.mark.asyncio
    async def test_replay_task_state_no_events(self, store: EventStore) -> None:
        """Test replaying state with no events."""
        store.db.fetch = AsyncMock(return_value=[])

        state = await store.replay_task_state("task-123")

        assert state is None

    @pytest.mark.asyncio
    async def test_replay_task_state_with_events(self, store: EventStore) -> None:
        """Test replaying state with events."""
        store.db.fetch = AsyncMock(
            return_value=[
                {
                    "id": "event-1",
                    "task_id": "task-123",
                    "event_type": "created",
                    "event_data": {
                        "title": "Test Task",
                        "repository": "mahavishnu",
                        "status": "pending",
                        "priority": "high",
                    },
                    "actor": "user@example.com",
                    "occurred_at": datetime.now(UTC),
                    "correlation_id": None,
                    "idempotency_key": None,
                },
                {
                    "id": "event-2",
                    "task_id": "task-123",
                    "event_type": "status_changed",
                    "event_data": {"new_status": "in_progress"},
                    "actor": "user@example.com",
                    "occurred_at": datetime.now(UTC),
                    "correlation_id": None,
                    "idempotency_key": None,
                },
            ]
        )

        state = await store.replay_task_state("task-123")

        assert state is not None
        assert state.title == "Test Task"
        assert state.status == "in_progress"
        assert state.priority == "high"
        assert state.version == 2

    @pytest.mark.asyncio
    async def test_get_event_by_idempotency_key(self, store: EventStore) -> None:
        """Test getting event by idempotency key."""
        store.db.fetchrow = AsyncMock(
            return_value={
                "id": "event-1",
                "task_id": "task-123",
                "event_type": "created",
                "event_data": {"title": "Test"},
                "actor": "user@example.com",
                "occurred_at": datetime.now(UTC),
                "correlation_id": None,
                "idempotency_key": "idem-123",
            }
        )

        event = await store.get_event_by_idempotency_key("idem-123")

        assert event is not None
        assert event.idempotency_key == "idem-123"

    @pytest.mark.asyncio
    async def test_get_event_by_idempotency_key_not_found(self, store: EventStore) -> None:
        """Test getting event by idempotency key when not found."""
        store.db.fetchrow = AsyncMock(return_value=None)

        event = await store.get_event_by_idempotency_key("nonexistent")

        assert event is None
