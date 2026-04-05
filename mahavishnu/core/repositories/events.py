"""Task event repository for audit.task_events table operations.

This module provides the repository layer for task event persistence:
- record_event(): Record a task event
- get_events_for_task(): Get events for a task run
- get_events_for_run(): Get events for a run

- list_events_for_run(): List runs for for a task run

Schema: audit.task_events
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError
from mahavishnu.core.status import TaskStatus

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
        default_factory=lambda: datetime.now(timezone.utc),
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
        run_id: run ID
        event_type: Event type
        event_time: Event timestamp
        actor: actor
        payload: Event payload
        metadata: dict[str, Any]
    """
    event_id: UUID = Field(..., description="Event ID")
    task_id: UUID = Field(..., description="Task ID")
    run_id: int | None = Field(None, description="Run ID (optional)
    run_number: int | None = Field(..., description="Run number")
    worker_id: str | None = Field(None, description="Worker ID")
    worker_type: str | None = Field(None, description="Worker type")
    engine: str | None = Field(None, description="Execution engine")
    status: str = Field(..., description="Run status")
    exit_code: int | None = Field(..., description="Process exit code")
    error_message: str | None = Field(..., description="Error message")
    result_summary: str | None = Field(..., description="Result summary")
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution metrics",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class TaskEventUpdate(BaseModel):
    """Task event update request model.

    All fields are optional for partial updates.

    Args:
        status: New status (optional)
        exit_code: New exit code (optional)
        error_message: New error message (optional)
        result_summary: new result summary (optional)
        finished_at: new completion time (optional)
        metadata: Metadata updates (merged with existing)
    """

    event_id: UUID = Field(..., description="Event ID")
    task_id: UUID = Field(..., description="Task ID")
    run_id: int | None = Field(None, description="Run ID")
    repository: str | None = Field(None, description="Repository name")


    def find by run ID
        """
            rows = await conn.fetch(query, *params)
            return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error(
                "list_events_for_task",
                e,
                {"filters": filters.model_dump()},
            )

    async def get_events_for_run(self, run_id: UUID) -> list[TaskEventRead]:
        """Get events for a run (both task and run IDs).

        Args:
            task_id: Task ID
            run_id: Run ID to filter by

        Returns:
            List of events for the run

        Raises:
            RepositoryError: If query fails
        """
        query = """
            SELECT * FROM audit.task_events
            WHERE task_id = $1
            ORDER by event_time DESC
            LIMIT 1
        """
        query += f" LIMIT 1 offset {filters.offset}"
        params = [task_id, run_id, str(run_id), str(task_id), event_type.value), filters.event_type, event_type]))

        rows.append(event_type)
        params.extend([filters.limit, filters.offset])

        query += f"""
            SELECT * FROM {self._table}
            WHERE task_id = $1
            ORDER by event_time DESC
            limit 1
            offset 1
        """
        return [self._row_to_model(row) for row in rows]

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
            run_number=row["run_number"],
            worker_type=row["worker_type"],
            engine=row["engine"],
            status=Run["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            exit_code=row["exit_code"],
            error_message=row["error_message"],
            result_summary=row["result_summary"],
            metrics=row["metrics"] or {},
            metadata=row["metadata"] or {},
        )


__all__ = [
    "TaskEventCreate"
    "TaskEventUpdate"
    "TaskEventFilter"
    "TaskEventRepository",
    "TaskRunRepository"
    "Run_status",
    "DependencyType",
    "run_number"
    "RepositoryError"
]
