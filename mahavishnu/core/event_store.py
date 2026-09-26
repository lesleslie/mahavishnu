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

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import json
import logging
from typing import TYPE_CHECKING, Any
import uuid

from mahavishnu.core.errors import DatabaseError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mahavishnu.core.database import Database

logger = logging.getLogger(__name__)


class TaskEventType(StrEnum):
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

    # NEW per round-4 review (mahavishnu specialist). C-6 idempotency
    # path sets PENDING before COMPLETED. C-10 historical webhook path
    # reads PENDING from the row state column. Appended LAST (not
    # alphabetically) so downstream plans (C-6, C-10) can rely on stable
    # iteration order — the test `test_pending_is_last_value` enforces
    # this invariant.
    PENDING = "pending"


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
    ) -> TaskEvent:
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
    def from_row(cls, row: Any) -> TaskEvent:
        """Create from database row."""
        return cls(
            id=str(row["id"]),
            task_id=str(row["task_id"]),
            event_type=TaskEventType(row["event_type"]),
            data=row["event_data"]
            if isinstance(row["event_data"], dict)
            else json.loads(row["event_data"]),
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

    def _apply_created(self, event: TaskEvent) -> None:
        """Handle CREATED event: initialise task fields from event data."""
        self.title = event.data.get("title", "")
        self.description = event.data.get("description")
        self.repository = event.data.get("repository", "")
        self.status = event.data.get("status", "pending")
        self.priority = event.data.get("priority", "medium")
        self.tags = event.data.get("tags", [])
        self.created_at = event.occurred_at
        self.updated_at = event.occurred_at

    def _apply_updated(self, event: TaskEvent) -> None:
        """Handle UPDATED event: copy any of title/description/metadata if present."""
        if "title" in event.data:
            self.title = event.data["title"]
        if "description" in event.data:
            self.description = event.data["description"]
        if "metadata" in event.data:
            self.metadata.update(event.data["metadata"])
        self.updated_at = event.occurred_at

    def _apply_status_changed(self, event: TaskEvent) -> None:
        """Handle STATUS_CHANGED event: update status if new_status provided."""
        self.status = event.data.get("new_status", self.status)
        self.updated_at = event.occurred_at

    def _apply_priority_changed(self, event: TaskEvent) -> None:
        """Handle PRIORITY_CHANGED event: update priority if new_priority provided."""
        self.priority = event.data.get("new_priority", self.priority)
        self.updated_at = event.occurred_at

    def _apply_assigned(self, event: TaskEvent) -> None:
        """Handle ASSIGNED event: set assignee."""
        self.assignee = event.data.get("assignee")
        self.updated_at = event.occurred_at

    def _apply_unassigned(self, event: TaskEvent) -> None:
        """Handle UNASSIGNED event: clear assignee."""
        self.assignee = None
        self.updated_at = event.occurred_at

    def _apply_completed(self, event: TaskEvent) -> None:
        """Handle COMPLETED event: mark status completed and stamp completed_at."""
        self.status = "completed"
        self.completed_at = event.occurred_at
        self.updated_at = event.occurred_at

    def _apply_failed(self, event: TaskEvent) -> None:
        """Handle FAILED event: mark status failed."""
        self.status = "failed"
        self.updated_at = event.occurred_at

    def _apply_cancelled(self, event: TaskEvent) -> None:
        """Handle CANCELLED event: mark status cancelled."""
        self.status = "cancelled"
        self.updated_at = event.occurred_at

    def _apply_tag_added(self, event: TaskEvent) -> None:
        """Handle TAG_ADDED event: append tag if not already present."""
        tag = event.data.get("tag")
        if tag and tag not in self.tags:
            self.tags.append(tag)
        self.updated_at = event.occurred_at

    def _apply_tag_removed(self, event: TaskEvent) -> None:
        """Handle TAG_REMOVED event: drop tag if present."""
        tag = event.data.get("tag")
        if tag in self.tags:
            self.tags.remove(tag)
        self.updated_at = event.occurred_at

    def _apply_deleted(self, event: TaskEvent) -> None:
        """Handle DELETED event: mark task as soft-deleted."""
        self.is_deleted = True
        self.updated_at = event.occurred_at

    def apply_event(self, event: TaskEvent) -> None:
        """Apply an event to update state.

        Args:
            event: Event to apply
        """
        self.version += 1
        handler = _TASK_EVENT_HANDLERS.get(event.event_type)
        if handler is not None:
            handler(self, event)
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


# Dispatch table mapping TaskEventType → TaskState handler method.
# Defined at module level so apply_event stays a thin dispatcher and
# each handler has its own (small) complexity count.
_TASK_EVENT_HANDLERS: dict[TaskEventType, Any] = {
    TaskEventType.CREATED: TaskState._apply_created,
    TaskEventType.UPDATED: TaskState._apply_updated,
    TaskEventType.STATUS_CHANGED: TaskState._apply_status_changed,
    TaskEventType.PRIORITY_CHANGED: TaskState._apply_priority_changed,
    TaskEventType.ASSIGNED: TaskState._apply_assigned,
    TaskEventType.UNASSIGNED: TaskState._apply_unassigned,
    TaskEventType.COMPLETED: TaskState._apply_completed,
    TaskEventType.FAILED: TaskState._apply_failed,
    TaskEventType.CANCELLED: TaskState._apply_cancelled,
    TaskEventType.TAG_ADDED: TaskState._apply_tag_added,
    TaskEventType.TAG_REMOVED: TaskState._apply_tag_removed,
    TaskEventType.DELETED: TaskState._apply_deleted,
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

            logger.debug(f"Appended event {event.event_type.value} for task {task_id} by {actor}")
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


# ============================================================================
# Execution Events (REQ-003) — C-3 forward-only schema + module-level helpers
# ============================================================================
#
# Distinct from `task_events` (idempotency tracking in C-6). The
# `execution_events` table is for workflow lifecycle history consumed by
# `mahavishnu executions show` (C-12). They share the file but not the
# schema — no FK between them.

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class _Base(DeclarativeBase):
    """SQLAlchemy 2.0 declarative base for execution_events table."""


class ExecutionEvent(_Base):
    """One row per workflow lifecycle event.

    The autoincrement primary key prevents duplicate-row inserts.
    Duplicate (execution_id, event_type, occurred_at) tuples ARE allowed —
    e.g., two CREATED events for the same execution across retries are
    valid history.

    Implements: REQ-003
    """  # req: REQ-003

    __tablename__ = "execution_events"
    __table_args__ = (
        Index(
            "ix_execution_events_execution_id_occurred_at",
            "execution_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    actor: Mapped[str] = mapped_column(String(255))
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )


# Module-level engine + session factory. Lazy-initialized via
# ``init_engine``; tests can monkey-patch ``_session_factory`` to inject
# an isolated in-memory engine. Production callers run ``init_engine``
# during app startup.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(database_url: str) -> AsyncEngine:
    """Initialise the module-level async engine.

    Args:
        database_url: SQLAlchemy URL — asyncpg for Postgres, aiosqlite for SQLite.

    Returns:
        The created ``AsyncEngine``.

    Raises:
        DatabaseError: If the engine cannot be created.
    """
    global _engine, _session_factory
    try:
        _engine = create_async_engine(database_url, future=True)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    except Exception as e:
        raise DatabaseError(
            f"Failed to create execution_events engine: {e}",
            details={"database_url": database_url},
        ) from e
    return _engine


async def dispose_engine() -> None:
    """Dispose the module-level engine. Idempotent."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def _require_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the active session factory or raise DatabaseError."""
    if _session_factory is None:
        raise DatabaseError(
            "execution_events engine not initialised; call init_engine() first",
        )
    return _session_factory


async def record_execution_event(
    execution_id: str,
    event_type: TaskEventType,
    data: dict[str, Any],
    actor: str,
    *,
    correlation_id: str | None = None,
    occurred_at: datetime | None = None,
) -> ExecutionEvent:
    """Persist one workflow lifecycle event.

    Autoincrement primary key prevents duplicate-row inserts. Duplicate
    (execution_id, event_type, occurred_at) tuples ARE allowed — e.g.,
    two CREATED events for the same execution across retries are valid
    history.

    Implements: REQ-003
    """  # req: REQ-003
    import time

    factory = _require_session_factory()
    event = ExecutionEvent(
        execution_id=execution_id,
        event_type=event_type.value,
        data=data,
        actor=actor,
        correlation_id=correlation_id,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    start = time.perf_counter()
    try:
        async with factory() as session:
            session.add(event)
            await session.flush()
            await session.commit()
    finally:
        EXECUTION_EVENT_LOG_LATENCY.observe(time.perf_counter() - start)
    # Counter is incremented AFTER successful commit so failed inserts
    # do not inflate the metric. Matches Prometheus Counter semantics.
    EXECUTION_EVENTS_TOTAL.labels(event_type=event_type.value).inc()
    return event


async def get_execution_events(execution_id: str) -> list[ExecutionEvent]:
    """Return all events for an execution, ordered by occurred_at ASC.

    Implements: REQ-003
    """  # req: REQ-003
    from sqlalchemy import select

    factory = _require_session_factory()
    async with factory() as session:
        stmt = (
            select(ExecutionEvent)
            .where(ExecutionEvent.execution_id == execution_id)
            .order_by(ExecutionEvent.occurred_at.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


__all__ = [
    "EXECUTION_EVENTS_TOTAL",
    "EXECUTION_EVENT_LOG_LATENCY",
    "EventStore",
    "ExecutionEvent",
    "TaskEvent",
    "TaskEventType",
    "TaskState",
    "dispose_engine",
    "get_execution_events",
    "init_engine",
    "record_execution_event",
]


# Prometheus metrics (REQ-003 observability). Increment only AFTER successful
# flush so failed inserts do not inflate counters. Wrapped in try/except so
# missing prometheus_client (e.g. slim build) does not break event-store imports.
try:
    from prometheus_client import Counter, Histogram

    EXECUTION_EVENTS_TOTAL = Counter(
        "execution_events_total",
        "Total execution events persisted, labeled by event_type.",
        labelnames=["event_type"],
    )

    EXECUTION_EVENT_LOG_LATENCY = Histogram(
        "execution_event_log_latency_seconds",
        "Latency of record_execution_event() from call to commit.",
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    )
except ImportError:
    # Module-level fallbacks so callers can still reference the symbols
    # even if prometheus_client is unavailable. The fallbacks swallow
    # ``.labels(...)``/``.observe(...)`` calls without side-effects.

    class _NoOpMetric:
        def labels(self, **_kwargs: object) -> _NoOpMetric:
            return self

        def inc(self, *_args: object, **_kwargs: object) -> None:
            return None

        def observe(self, *_args: object, **_kwargs: object) -> None:
            return None

    EXECUTION_EVENTS_TOTAL = _NoOpMetric()
    EXECUTION_EVENT_LOG_LATENCY = _NoOpMetric()
