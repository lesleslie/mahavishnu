"""Task event repository for audit.task_events table operations.

This module provides the repository layer for task event persistence:
- record_event(): Record a task event
- get_events_for_task(): Get events for a task
- get_events_for_run(): Get events for a run

Schema: audit.task_events
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel, Field

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static query constants — no f-strings, all user values via positional params.
# ---------------------------------------------------------------------------

_INSERT_EVENT = (
    "INSERT INTO audit.task_events"
    " (task_id, run_id, event_type, event_time, actor, payload, metadata)"
    " VALUES ($1, $2, $3, $4, $5, $6, $7)"
    " RETURNING *"
)

_SELECT_BY_TASK = (
    "SELECT * FROM audit.task_events WHERE task_id = $1 ORDER BY event_time DESC LIMIT $2 OFFSET $3"
)

_SELECT_BY_TASK_AND_RUN = (
    "SELECT * FROM audit.task_events WHERE task_id = $1 AND run_id = $2 ORDER BY event_time DESC"
)

# list_events: all 16 combinations of optional filters {task_id, run_id, event_type, actor}.
# Filter fields are always ordered: task_id → run_id → event_type → actor.
# $1..$N = filter values in that order; last two params are always LIMIT, OFFSET.
_T = "task_id"
_R = "run_id"
_E = "event_type"
_A = "actor"

_LIST_QUERIES: dict[frozenset[str], str] = {
    # 0 filters
    frozenset(): ("SELECT * FROM audit.task_events ORDER BY event_time DESC LIMIT $1 OFFSET $2"),
    # 1 filter
    frozenset({_T}): (
        "SELECT * FROM audit.task_events"
        " WHERE task_id = $1"
        " ORDER BY event_time DESC LIMIT $2 OFFSET $3"
    ),
    frozenset({_R}): (
        "SELECT * FROM audit.task_events"
        " WHERE run_id = $1"
        " ORDER BY event_time DESC LIMIT $2 OFFSET $3"
    ),
    frozenset({_E}): (
        "SELECT * FROM audit.task_events"
        " WHERE event_type = $1"
        " ORDER BY event_time DESC LIMIT $2 OFFSET $3"
    ),
    frozenset({_A}): (
        "SELECT * FROM audit.task_events"
        " WHERE actor = $1"
        " ORDER BY event_time DESC LIMIT $2 OFFSET $3"
    ),
    # 2 filters
    frozenset({_T, _R}): (
        "SELECT * FROM audit.task_events"
        " WHERE task_id = $1 AND run_id = $2"
        " ORDER BY event_time DESC LIMIT $3 OFFSET $4"
    ),
    frozenset({_T, _E}): (
        "SELECT * FROM audit.task_events"
        " WHERE task_id = $1 AND event_type = $2"
        " ORDER BY event_time DESC LIMIT $3 OFFSET $4"
    ),
    frozenset({_T, _A}): (
        "SELECT * FROM audit.task_events"
        " WHERE task_id = $1 AND actor = $2"
        " ORDER BY event_time DESC LIMIT $3 OFFSET $4"
    ),
    frozenset({_R, _E}): (
        "SELECT * FROM audit.task_events"
        " WHERE run_id = $1 AND event_type = $2"
        " ORDER BY event_time DESC LIMIT $3 OFFSET $4"
    ),
    frozenset({_R, _A}): (
        "SELECT * FROM audit.task_events"
        " WHERE run_id = $1 AND actor = $2"
        " ORDER BY event_time DESC LIMIT $3 OFFSET $4"
    ),
    frozenset({_E, _A}): (
        "SELECT * FROM audit.task_events"
        " WHERE event_type = $1 AND actor = $2"
        " ORDER BY event_time DESC LIMIT $3 OFFSET $4"
    ),
    # 3 filters
    frozenset({_T, _R, _E}): (
        "SELECT * FROM audit.task_events"
        " WHERE task_id = $1 AND run_id = $2 AND event_type = $3"
        " ORDER BY event_time DESC LIMIT $4 OFFSET $5"
    ),
    frozenset({_T, _R, _A}): (
        "SELECT * FROM audit.task_events"
        " WHERE task_id = $1 AND run_id = $2 AND actor = $3"
        " ORDER BY event_time DESC LIMIT $4 OFFSET $5"
    ),
    frozenset({_T, _E, _A}): (
        "SELECT * FROM audit.task_events"
        " WHERE task_id = $1 AND event_type = $2 AND actor = $3"
        " ORDER BY event_time DESC LIMIT $4 OFFSET $5"
    ),
    frozenset({_R, _E, _A}): (
        "SELECT * FROM audit.task_events"
        " WHERE run_id = $1 AND event_type = $2 AND actor = $3"
        " ORDER BY event_time DESC LIMIT $4 OFFSET $5"
    ),
    # 4 filters
    frozenset({_T, _R, _E, _A}): (
        "SELECT * FROM audit.task_events"
        " WHERE task_id = $1 AND run_id = $2 AND event_type = $3 AND actor = $4"
        " ORDER BY event_time DESC LIMIT $5 OFFSET $6"
    ),
}

_LIST_FILTER_ORDER = (_T, _R, _E, _A)


# =============================================================================
# Pydantic Models for TaskEvent Repository
# =============================================================================


class TaskEventCreate(BaseModel):
    """Task event creation request model."""

    task_id: UUID = Field(..., description="Task ID")
    run_id: UUID | None = Field(None, description="Run ID")
    event_type: str = Field(..., description="Event type")
    event_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict, description="Event data")
    actor: str | None = Field(None, description="Actor identifier")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Event metadata")


class TaskEventRead(BaseModel):
    """Task event read response model."""

    id: UUID = Field(..., description="Event ID")
    task_id: UUID = Field(..., description="Task ID")
    run_id: UUID | None = Field(None, description="Run ID")
    event_type: str = Field(..., description="Event type")
    event_time: datetime = Field(..., description="Event timestamp")
    actor: str | None = Field(None, description="Actor identifier")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event payload")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class TaskEventUpdate(BaseModel):
    """Task event update request model (all fields optional)."""

    payload: dict[str, Any] | None = Field(None, description="Updated payload")
    metadata: dict[str, Any] | None = Field(None, description="Metadata updates")


class TaskEventFilter(BaseModel):
    """Task event filter for list operations."""

    task_id: UUID | None = Field(None, description="Filter by task")
    run_id: UUID | None = Field(None, description="Filter by run")
    event_type: str | None = Field(None, description="Filter by event type")
    actor: str | None = Field(None, description="Filter by actor")
    limit: int = Field(default=50, ge=1, le=1000, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Result offset")


# =============================================================================
# TaskEvent Repository Implementation
# =============================================================================


class TaskEventRepository(BaseRepository[TaskEventCreate, TaskEventRead, TaskEventUpdate]):
    """Repository for audit.task_events table operations."""

    async def create(self, data: TaskEventCreate) -> TaskEventRead:
        """Not used directly — use record_event() instead."""
        raise NotImplementedError("Use record_event() instead")

    async def record_event(self, data: TaskEventCreate) -> TaskEventRead:
        """Record a task event."""
        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    _INSERT_EVENT,
                    data.task_id,
                    data.run_id,
                    data.event_type,
                    data.event_time,
                    data.actor,
                    data.payload,
                    data.metadata,
                )
                if row is None:
                    raise RepositoryError(
                        "Failed to create task event",
                        operation="record_event",
                        details={"task_id": str(data.task_id)},
                    )
                return self._row_to_model(row)
        except Exception as e:
            raise self._handle_error("record_event", e, {"task_id": str(data.task_id)})

    async def get_events_for_task(
        self,
        task_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskEventRead]:
        """Get events for a task."""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(_SELECT_BY_TASK, task_id, limit, offset)
                return [self._row_to_model(row) for row in rows]
        except Exception as e:
            raise self._handle_error("get_events_for_task", e, {"task_id": str(task_id)})

    async def get_events_for_run(self, task_id: UUID, run_id: UUID) -> list[TaskEventRead]:
        """Get events for a run (filtered by both task and run IDs)."""
        try:
            async with self.connection() as conn:
                rows = await conn.fetch(_SELECT_BY_TASK_AND_RUN, task_id, run_id)
                return [self._row_to_model(row) for row in rows]
        except Exception as e:
            raise self._handle_error(
                "get_events_for_run", e, {"task_id": str(task_id), "run_id": str(run_id)}
            )

    async def list_events(self, filters: TaskEventFilter) -> list[TaskEventRead]:
        """List events with optional filters."""
        active = frozenset(f for f in _LIST_FILTER_ORDER if getattr(filters, f, None) is not None)
        query = _LIST_QUERIES[active]
        params: list[Any] = [getattr(filters, f) for f in _LIST_FILTER_ORDER if f in active]
        params.extend([filters.limit, filters.offset])

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, *params)
                return [self._row_to_model(row) for row in rows]
        except Exception as e:
            raise self._handle_error("list_events", e, {"filters": filters.model_dump()})

    def _row_to_model(self, row: Any) -> TaskEventRead:
        """Convert database row to TaskEventRead model."""
        return TaskEventRead(
            id=row["id"],
            task_id=row["task_id"],
            run_id=row["run_id"],
            event_type=row["event_type"],
            event_time=row["event_time"],
            actor=row["actor"],
            payload=row["payload"] or {},
            metadata=row["metadata"] or {},
        )


__all__ = [
    "TaskEventCreate",
    "TaskEventUpdate",
    "TaskEventFilter",
    "TaskEventRead",
    "TaskEventRepository",
]
