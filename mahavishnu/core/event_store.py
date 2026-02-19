"""Event Store for Mahavishnu Task Orchestration.

Implements event sourcing for:
- Complete audit trail of all task changes
- Event replay for state reconstruction
- Temporal queries (what was the state at time T?)
- Event-based integrations

Usage:
    from mahavishnu.core.event_store import EventStore, TaskEvent

    store = EventStore(db)

    # Record an event
    await store.append(
        task_id="task-123",
        event_type=TaskEventType.CREATED,
        data={"title": "New task", "repository": "mahavishnu"},
        actor="user@example.com",
    )

    # Get task history
    events = await store.get_task_events("task-123")

    # Replay events to reconstruct state
    state = await store.replay_task_state("task-123")
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, AsyncIterator

from mahavishnu.core.database import Database
from mahavishnu.core.errors import DatabaseError, MahavishnuError

logger = logging.getLogger(__name__)


class TaskEventType(str, Enum):
    """Types of task events."""

    # Lifecycle events
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"

    # Status events
    STATUS_CHANGED = "status_changed"
    PRIORITY_CHANGED = "priority_changed"
    ASSIGNED = "assigned"
    UNASSIGNED = "unassigned"

    # Blocking events
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"

    # Completion events
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    # Relationship events
    DEPENDENCY_ADDED = "dependency_added"
    DEPENDENCY_REMOVED = "dependency_removed"
    COMMENT_ADDED = "comment_added"
    TAG_ADDED = "tag_added"
    TAG_REMOVED = "tag_removed"

    # Integration events
    WEBHOOK_RECEIVED = "webhook_received"
    SYNCED = "synced"


@dataclass
class TaskEvent:
    """Represents a task event."""

    id: str
    task_id: str
    event_type: TaskEventType
    data: dict[str, Any]
    actor: str
    occurred_at: datetime
    correlation_id: str | None = None
    idempotency_key: str | None = None
    version: int = 1

    @classmethod
    def create(
        cls,
        task_id: str,
        event_type: TaskEventType,
        data: dict[str, Any],
        actor: str,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> "TaskEvent":
        """Create a new event.

        Args:
            task_id: Task identifier
            event_type: Type of event
            data: Event data
            actor: Who triggered the event
            correlation_id: Optional correlation ID for linking events
            idempotency_key: Optional key for deduplication

        Returns:
            New TaskEvent instance
        """
        return cls(
            id=str(uuid.uuid4()),
            task_id=task_id,
            event_type=event_type,
            data=data,
            actor=actor,
            occurred_at=datetime.now(UTC),
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "task_id": self.task_id,
            "event_type": self.event_type.value,
            "data": self.data,
            "actor": self.actor,
            "occurred_at": self.occurred_at.isoformat(),
            "correlation_id": self.correlation_id,
            "idempotency_key": self.idempotency_key,
            "version": self.version,
        }

    @classmethod
    def from_row(cls, row: Any) -> "TaskEvent":
        """Create from database row."""
        return cls(
            id=str(row["id"]),
            task_id=str(row["task_id"]),
            event_type=TaskEventType(row["event_type"]),
            data=row["event_data"] if isinstance(row["event_data"], dict) else json.loads(row["event_data"]),
            actor=row["actor"],
            occurred_at=row["occurred_at"],
            correlation_id=str(row["correlation_id"]) if row["correlation_id"] else None,
            idempotency_key=row["idempotency_key"],
            version=1,
        )


@dataclass
class TaskState:
    """Reconstructed task state from events."""

    task_id: str
    title: str = ""
    description: str | None = None
    repository: str = ""
    status: str = "pending"
    priority: str = "medium"
    assignee: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    is_deleted: bool = False
    version: int = 0

    def apply_event(self, event: TaskEvent) -> None:
        """Apply an event to update state.

        Args:
            event: Event to apply
        """
        self.version += 1

        if event.event_type == TaskEventType.CREATED:
            self.title = event.data.get("title", "")
            self.description = event.data.get("description")
            self.repository = event.data.get("repository", "")
            self.status = event.data.get("status", "pending")
            self.priority = event.data.get("priority", "medium")
            self.tags = event.data.get("tags", [])
            self.created_at = event.occurred_at
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.UPDATED:
            if "title" in event.data:
                self.title = event.data["title"]
            if "description" in event.data:
                self.description = event.data["description"]
            if "metadata" in event.data:
                self.metadata.update(event.data["metadata"])
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.STATUS_CHANGED:
            self.status = event.data.get("new_status", self.status)
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.PRIORITY_CHANGED:
            self.priority = event.data.get("new_priority", self.priority)
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.ASSIGNED:
            self.assignee = event.data.get("assignee")
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.UNASSIGNED:
            self.assignee = None
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.COMPLETED:
            self.status = "completed"
            self.completed_at = event.occurred_at
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.FAILED:
            self.status = "failed"
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.CANCELLED:
            self.status = "cancelled"
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.TAG_ADDED:
            tag = event.data.get("tag")
            if tag and tag not in self.tags:
                self.tags.append(tag)
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.TAG_REMOVED:
            tag = event.data.get("tag")
            if tag in self.tags:
                self.tags.remove(tag)
            self.updated_at = event.occurred_at

        elif event.event_type == TaskEventType.DELETED:
            self.is_deleted = True
            self.updated_at = event.occurred_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "repository": self.repository,
            "status": self.status,
            "priority": self.priority,
            "assignee": self.assignee,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "is_deleted": self.is_deleted,
            "version": self.version,
        }


class EventStore:
    """Event store for task events.

    Provides:
    - Event persistence
    - Event retrieval by task
    - Event replay for state reconstruction
    - Temporal queries

    Example:
        store = EventStore(db)

        # Append event
        event = await store.append(
            task_id="task-123",
            event_type=TaskEventType.CREATED,
            data={"title": "New task"},
            actor="user@example.com",
        )

        # Get all events for a task
        events = await store.get_task_events("task-123")

        # Reconstruct state at a point in time
        state = await store.replay_task_state("task-123", as_of=some_datetime)
    """

    def __init__(self, db: Database):
        """Initialize event store.

        Args:
            db: Database connection
        """
        self.db = db

    async def append(
        self,
        task_id: str,
        event_type: TaskEventType,
        data: dict[str, Any],
        actor: str,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> TaskEvent:
        """Append an event to the store.

        Args:
            task_id: Task identifier
            event_type: Type of event
            data: Event data
            actor: Who triggered the event
            correlation_id: Optional correlation ID for linking events
            idempotency_key: Optional key for deduplication

        Returns:
            Created event

        Raises:
            DatabaseError: If event cannot be appended
        """
        event = TaskEvent.create(
            task_id=task_id,
            event_type=event_type,
            data=data,
            actor=actor,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

        try:
            await self.db.execute(
                """
                INSERT INTO task_events
                    (id, task_id, event_type, event_data, actor, occurred_at,
                     correlation_id, idempotency_key)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                event.id,
                event.task_id,
                event.event_type.value,
                json.dumps(event.data),
                event.actor,
                event.occurred_at,
                event.correlation_id,
                event.idempotency_key,
            )

            logger.debug(
                f"Appended event {event.event_type.value} for task {task_id} by {actor}"
            )
            return event

        except Exception as e:
            logger.error(f"Failed to append event: {e}")
            raise DatabaseError(
                f"Failed to append event: {e}",
                details={"task_id": task_id, "event_type": event_type.value},
            ) from e

    async def get_task_events(
        self,
        task_id: str,
        since: datetime | None = None,
        until: datetime | None = None,
        event_types: list[TaskEventType] | None = None,
        limit: int = 1000,
    ) -> list[TaskEvent]:
        """Get all events for a task.

        Args:
            task_id: Task identifier
            since: Only events after this time
            until: Only events before this time
            event_types: Filter by event types
            limit: Maximum number of events to return

        Returns:
            List of events ordered by occurrence time
        """
        query = """
            SELECT * FROM task_events
            WHERE task_id = $1
        """
        params: list[Any] = [task_id]
        param_count = 1

        if since:
            param_count += 1
            query += f" AND occurred_at >= ${param_count}"
            params.append(since)

        if until:
            param_count += 1
            query += f" AND occurred_at <= ${param_count}"
            params.append(until)

        if event_types:
            param_count += 1
            placeholders = ", ".join(f"${param_count + i}" for i in range(len(event_types)))
            query += f" AND event_type IN ({placeholders})"
            params.extend(et.value for et in event_types)

        query += " ORDER BY occurred_at ASC LIMIT $"
        param_count += 1
        query += str(param_count)
        params.append(limit)

        rows = await self.db.fetch(query, *params)
        return [TaskEvent.from_row(row) for row in rows]

    async def replay_task_state(
        self,
        task_id: str,
        as_of: datetime | None = None,
    ) -> TaskState | None:
        """Reconstruct task state from events.

        Args:
            task_id: Task identifier
            as_of: Reconstruct state as of this time (None = current)

        Returns:
            Reconstructed task state, or None if no events found
        """
        events = await self.get_task_events(
            task_id=task_id,
            until=as_of,
            limit=10000,
        )

        if not events:
            return None

        state = TaskState(task_id=task_id)
        for event in events:
            state.apply_event(event)

        return state

    async def get_events_by_correlation(
        self,
        correlation_id: str,
    ) -> list[TaskEvent]:
        """Get all events with a correlation ID.

        Args:
            correlation_id: Correlation ID

        Returns:
            List of events
        """
        rows = await self.db.fetch(
            """
            SELECT * FROM task_events
            WHERE correlation_id = $1
            ORDER BY occurred_at ASC
            """,
            correlation_id,
        )
        return [TaskEvent.from_row(row) for row in rows]

    async def get_event_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> TaskEvent | None:
        """Get event by idempotency key.

        Args:
            idempotency_key: Idempotency key

        Returns:
            Event if found, None otherwise
        """
        row = await self.db.fetchrow(
            """
            SELECT * FROM task_events
            WHERE idempotency_key = $1
            """,
            idempotency_key,
        )
        return TaskEvent.from_row(row) if row else None

    async def get_events_by_type(
        self,
        event_type: TaskEventType,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[TaskEvent]:
        """Get events by type.

        Args:
            event_type: Type of events to get
            since: Only events after this time
            limit: Maximum number of events

        Returns:
            List of events
        """
        if since:
            rows = await self.db.fetch(
                """
                SELECT * FROM task_events
                WHERE event_type = $1 AND occurred_at >= $2
                ORDER BY occurred_at DESC
                LIMIT $3
                """,
                event_type.value,
                since,
                limit,
            )
        else:
            rows = await self.db.fetch(
                """
                SELECT * FROM task_events
                WHERE event_type = $1
                ORDER BY occurred_at DESC
                LIMIT $2
                """,
                event_type.value,
                limit,
            )

        return [TaskEvent.from_row(row) for row in rows]

    async def iter_all_events(
        self,
        since: datetime | None = None,
        batch_size: int = 1000,
    ) -> AsyncIterator[list[TaskEvent]]:
        """Iterate over all events in batches.

        Args:
            since: Only events after this time
            batch_size: Number of events per batch

        Yields:
            Lists of events
        """
        last_id: str | None = None

        while True:
            if since and last_id is None:
                rows = await self.db.fetch(
                    """
                    SELECT * FROM task_events
                    WHERE occurred_at >= $1
                    ORDER BY occurred_at ASC, id ASC
                    LIMIT $2
                    """,
                    since,
                    batch_size,
                )
            elif last_id:
                rows = await self.db.fetch(
                    """
                    SELECT * FROM task_events
                    WHERE id > $1
                    ORDER BY occurred_at ASC, id ASC
                    LIMIT $2
                    """,
                    last_id,
                    batch_size,
                )
            else:
                rows = await self.db.fetch(
                    """
                    SELECT * FROM task_events
                    ORDER BY occurred_at ASC, id ASC
                    LIMIT $1
                    """,
                    batch_size,
                )

            if not rows:
                break

            events = [TaskEvent.from_row(row) for row in rows]
            yield events

            last_id = events[-1].id

            if len(events) < batch_size:
                break
