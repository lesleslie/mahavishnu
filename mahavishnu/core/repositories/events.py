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

from pydantic import BaseModel, Field

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for TaskEvent Repository
# =============================================================================


class TaskEventCreate(BaseModel):
    """Task event creation request model.

    Args:
        task_id: Task ID (required)
        run_id: Run ID (optional)
        event_type: Event type (required)
        event_time: Event timestamp (default: now)
        actor: Actor identifier (optional)
        payload: Event data (optional)
    """

    task_id: UUID = Field(..., description="Task ID")
    run_id: UUID | None = Field(None, description="Run ID")
    event_type: str = Field(..., description="Event type")
    event_time: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event data",
    )
    actor: str | None = Field(None, description="Actor identifier")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Event metadata",
    )


class TaskEventRead(BaseModel):
    """Task event read response model.

    Args:
        id: Event ID (from database)
        task_id: Task ID
        run_id: Run ID (optional)
        event_type: Event type
        event_time: Event timestamp
        actor: Actor identifier
        payload: Event payload
        metadata: Additional metadata
    """

    id: UUID = Field(..., description="Event ID")
    task_id: UUID = Field(..., description="Task ID")
    run_id: UUID | None = Field(None, description="Run ID")
    event_type: str = Field(..., description="Event type")
    event_time: datetime = Field(..., description="Event timestamp")
    actor: str | None = Field(None, description="Actor identifier")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event payload",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class TaskEventUpdate(BaseModel):
    """Task event update request model.

    All fields are optional for partial updates.

    Args:
        payload: Updated payload (optional)
        metadata: Metadata updates (merged with existing, optional)
    """

    payload: dict[str, Any] | None = Field(None, description="Updated payload")
    metadata: dict[str, Any] | None = Field(None, description="Metadata updates")


class TaskEventFilter(BaseModel):
    """Task event filter for list operations.

    Args:
        task_id: Filter by task (optional)
        run_id: Filter by run (optional)
        event_type: Filter by event type (optional)
        actor: Filter by actor (optional)
        limit: Maximum results (default: 50)
        offset: Result offset (default: 0)
    """

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
    """Repository for audit.task_events table operations.

    Provides CRUD operations for task events with:
    - Type-safe Pydantic model returns
    - Async context manager pattern
    - Structured error handling

    Usage:
        repo = TaskEventRepository()

        async with repo:
            event = await repo.record_event(
                TaskEventCreate(task_id=task_id, event_type="status_changed")
            )
            events = await repo.get_events_for_task(task_id)
    """

    def __init__(self) -> None:
        """Initialize task event repository."""
        super().__init__()
        self._table = "audit.task_events"

    async def record_event(self, data: TaskEventCreate) -> TaskEventRead:
        """Record a task event.

        Args:
            data: Event creation data

        Returns:
            Created event with generated ID

        Raises:
            RepositoryError: If creation fails
        """
        query = f"""
            INSERT INTO {self._table} (
                task_id, run_id, event_type, event_time, actor, payload, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
        """

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    query,
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
            raise self._handle_error(
                "record_event",
                e,
                {"task_id": str(data.task_id)},
            )

    async def get_events_for_task(
        self,
        task_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskEventRead]:
        """Get events for a task.

        Args:
            task_id: Task ID
            limit: Maximum results
            offset: Result offset

        Returns:
            List of events for the task

        Raises:
            RepositoryError: If query fails
        """
        query = f"""
            SELECT * FROM {self._table}
            WHERE task_id = $1
            ORDER BY event_time DESC
            LIMIT $2 OFFSET $3
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, task_id, limit, offset)
                return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error(
                "get_events_for_task",
                e,
                {"task_id": str(task_id)},
            )

    async def get_events_for_run(
        self,
        task_id: UUID,
        run_id: UUID,
    ) -> list[TaskEventRead]:
        """Get events for a run (filtered by both task and run IDs).

        Args:
            task_id: Task ID
            run_id: Run ID to filter by

        Returns:
            List of events for the run

        Raises:
            RepositoryError: If query fails
        """
        query = f"""
            SELECT * FROM {self._table}
            WHERE task_id = $1 AND run_id = $2
            ORDER BY event_time DESC
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, task_id, run_id)
                return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error(
                "get_events_for_run",
                e,
                {"task_id": str(task_id), "run_id": str(run_id)},
            )

    async def list_events(
        self,
        filters: TaskEventFilter,
    ) -> list[TaskEventRead]:
        """List events with optional filters.

        Args:
            filters: Filter criteria for events

        Returns:
            List of events matching filters

        Raises:
            RepositoryError: If query fails
        """
        conditions = []
        params = []
        param_idx = 1

        if filters.task_id:
            conditions.append(f"task_id = ${param_idx}")
            params.append(filters.task_id)
            param_idx += 1

        if filters.run_id:
            conditions.append(f"run_id = ${param_idx}")
            params.append(filters.run_id)
            param_idx += 1

        if filters.event_type:
            conditions.append(f"event_type = ${param_idx}")
            params.append(filters.event_type)
            param_idx += 1

        if filters.actor:
            conditions.append(f"actor = ${param_idx}")
            params.append(filters.actor)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([filters.limit, filters.offset])

        query = f"""
            SELECT * FROM {self._table}
            {where_clause}
            ORDER BY event_time DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, *params)
                return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error("list_events", e, {"filters": filters.model_dump()})

    def _row_to_model(self, row: Any) -> TaskEventRead:
        """Convert database row to TaskEventRead model.

        Args:
            row: Database row record

        Returns:
            TaskEventRead model instance
        """
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
