"""Task run repository for orchestration.task_runs table operations.

This module provides the repository layer for task run persistence:
- create_run(): Create a new task run
- get_run(): Retrieve a run by ID
- update_run(): Update run fields
- list_runs_for_task(): List all runs for a task

Schema: orchestration.task_runs
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
# Pydantic Models for TaskRun Repository
# =============================================================================


class RunStatus:
    """Task run status values.

    Matches the CHECK constraint in orchestration.task_runs table.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskRunCreate(BaseModel):
    """Task run creation request model.

    Args:
        task_id: Parent task ID (required)
        run_number: Sequential run number (required)
        pool_name: Pool name for execution (optional)
        worker_id: Worker instance ID (optional)
        worker_type: Worker type (optional)
        engine: Execution engine (optional)
        status: Initial status (default: pending)
        metrics: Execution metrics (optional)
        metadata: Additional metadata (optional)
    """

    task_id: UUID = Field(..., description="Parent task ID")
    run_number: int = Field(..., ge=1, description="Sequential run number")
    pool_name: str | None = Field(None, max_length=100, description="Pool name")
    worker_id: str | None = Field(None, max_length=100, description="Worker instance ID")
    worker_type: str | None = Field(None, max_length=100, description="Worker type")
    engine: str | None = Field(None, max_length=50, description="Execution engine")
    status: str = Field(default=RunStatus.PENDING, description="Run status")
    metrics: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution metrics",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class TaskRunRead(BaseModel):
    """Task run read response model.

    All fields from TaskRunCreate plus:
    - id: UUID (primary key)
    - started_at: Execution start timestamp
    - finished_at: Execution finish timestamp
    - exit_code: Process exit code
    - error_message: Error message if failed
    - result_summary: Execution result summary
    """

    id: UUID = Field(..., description="Run unique identifier")
    task_id: UUID = Field(..., description="Parent task ID")
    run_number: int = Field(..., description="Sequential run number")
    pool_name: str | None = Field(None, description="Pool name")
    worker_id: str | None = Field(None, description="Worker instance ID")
    worker_type: str | None = Field(None, description="Worker type")
    engine: str | None = Field(None, description="Execution engine")
    status: str = Field(..., description="Run status")
    started_at: datetime = Field(..., description="Execution start timestamp")
    finished_at: datetime | None = Field(None, description="Execution finish timestamp")
    exit_code: int | None = Field(None, description="Process exit code")
    error_message: str | None = Field(None, description="Error message")
    result_summary: str | None = Field(None, description="Result summary")
    metrics: dict[str, Any] = Field(..., description="Execution metrics")
    metadata: dict[str, Any] = Field(..., description="Additional metadata")


class TaskRunUpdate(BaseModel):
    """Task run update request model.

    All fields are optional for partial updates.

    Args:
        status: New status (optional)
        worker_id: Worker instance ID (optional)
        finished_at: Finish timestamp (optional)
        exit_code: Process exit code (optional)
        error_message: Error message (optional)
        result_summary: Result summary (optional)
        metrics: Metrics updates (optional, merged with existing)
        metadata: Metadata updates (optional, merged with existing)
    """

    status: str | None = Field(None, description="Run status")
    worker_id: str | None = Field(None, max_length=100, description="Worker instance ID")
    finished_at: datetime | None = Field(None, description="Finish timestamp")
    exit_code: int | None = Field(None, description="Process exit code")
    error_message: str | None = Field(None, max_length=5000, description="Error message")
    result_summary: str | None = Field(None, max_length=5000, description="Result summary")
    metrics: dict[str, Any] | None = Field(None, description="Metrics updates")
    metadata: dict[str, Any] | None = Field(None, description="Metadata updates")


class TaskRunFilter(BaseModel):
    """Task run filter for list operations.

    Args:
        task_id: Filter by parent task (optional)
        status: Filter by status (optional)
        pool_name: Filter by pool name (optional)
        worker_id: Filter by worker ID (optional)
        engine: Filter by engine (optional)
        started_after: Filter by start time (optional)
        started_before: Filter by start time (optional)
        limit: Maximum results (default: 50)
        offset: Result offset (default: 0)
    """

    task_id: UUID | None = Field(None, description="Filter by parent task")
    status: str | None = Field(None, description="Filter by status")
    pool_name: str | None = Field(None, max_length=100, description="Filter by pool name")
    worker_id: str | None = Field(None, max_length=100, description="Filter by worker ID")
    engine: str | None = Field(None, max_length=50, description="Filter by engine")
    started_after: datetime | None = Field(None, description="Filter started after")
    started_before: datetime | None = Field(None, description="Filter started before")
    limit: int = Field(default=50, ge=1, le=1000, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Result offset")


# =============================================================================
# TaskRun Repository Implementation
# =============================================================================


class TaskRunRepository(BaseRepository[TaskRunRead]):
    """Repository for orchestration.task_runs table operations.

    Provides CRUD operations for task runs with:
    - Type-safe Pydantic model returns
    - Async context manager pattern
    - Structured error handling

    Usage:
        repo = TaskRunRepository()

        async with repo:
            run = await repo.create_run(TaskRunCreate(task_id=task_id, run_number=1))
            runs = await repo.list_runs_for_task(task_id)
    """

    def __init__(self) -> None:
        """Initialize task run repository."""
        super().__init__()
        self._table = "orchestration.task_runs"

    async def create_run(self, data: TaskRunCreate) -> TaskRunRead:
        """Create a new task run.

        Args:
            data: Task run creation data

        Returns:
            Created task run with generated ID and timestamps

        Raises:
            RepositoryError: If creation fails
        """
        run_id = UUID.randomUUID()
        now = datetime.now(timezone.utc)

        query = f"""
            INSERT INTO {self._table} (
                id, task_id, run_number, pool_name, worker_id, worker_type,
                engine, status, started_at, metrics, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
        """

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    query,
                    run_id,
                    data.task_id,
                    data.run_number,
                    data.pool_name,
                    data.worker_id,
                    data.worker_type,
                    data.engine,
                    data.status,
                    now,
                    data.metrics,
                    data.metadata,
                )

                if row is None:
                    raise RepositoryError(
                        "Failed to create task run",
                        operation="create_run",
                        details={"task_id": str(data.task_id)},
                    )

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "create_run",
                e,
                {"task_id": str(data.task_id)},
            )

    async def get_run(self, run_id: UUID) -> TaskRunRead | None:
        """Get a task run by ID.

        Args:
            run_id: Run unique identifier

        Returns:
            Task run if found, None otherwise

        Raises:
            RepositoryError: If query fails
        """
        query = f"SELECT * FROM {self._table} WHERE id = $1"

        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(query, run_id)

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error("get_run", e, {"run_id": str(run_id)})

    async def update_run(self, run_id: UUID, data: TaskRunUpdate) -> TaskRunRead | None:
        """Update task run fields.

        Args:
            run_id: Run unique identifier
            data: Update data (partial updates supported)

        Returns:
            Updated run if found, None otherwise

        Raises:
            RepositoryError: If update fails
        """
        # Build dynamic UPDATE query based on provided fields
        updates = []
        params = [run_id]
        param_idx = 2

        field_mapping = {
            "status": "status",
            "worker_id": "worker_id",
            "finished_at": "finished_at",
            "exit_code": "exit_code",
            "error_message": "error_message",
            "result_summary": "result_summary",
        }

        for field, field_mapping.items():
            value = getattr(data, field, None)
            if value is not None:
                updates.append(f"{field} = ${param_idx}")
                params.append(value)
                param_idx += 1

        # Handle JSONB merges
        if data.metrics is not None:
            updates.append(f"metrics = metrics || ${param_idx}::jsonb")
            params.append(data.metrics)
            param_idx += 1

        if data.metadata is not None:
            updates.append(f"metadata = metadata || ${param_idx}::jsonb")
            params.append(data.metadata)
            param_idx += 1

        if not updates:
            return await self.get_run(run_id)

        query = f"""
            UPDATE {self._table}
            SET {', '.join(updates)}
            WHERE id = $1
            RETURNING *
        """

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(query, *params)

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error("update_run", e, {"run_id": str(run_id)})

    async def list_runs_for_task(
        self,
        task_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskRunRead]:
        """List all runs for a task.

        Args:
            task_id: Parent task ID
            limit: Maximum results (default: 50)
            offset: Result offset (default: 0)

        Returns:
            List of runs for the task, ordered by run_number descending

        Raises:
            RepositoryError: If query fails
        """
        query = f"""
            SELECT * FROM {self._table}
            WHERE task_id = $1
            ORDER BY run_number DESC
            LIMIT $2 OFFSET $3
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, task_id, limit, offset)
                return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error(
                "list_runs_for_task",
                e,
                {"task_id": str(task_id)},
            )

    async def list_runs(self, filters: TaskRunFilter) -> list[TaskRunRead]:
        """List runs with optional filters.

        Args:
            filters: Filter criteria for runs

        Returns:
            List of runs matching filters

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

        if filters.status:
            conditions.append(f"status = ${param_idx}")
            params.append(filters.status)
            param_idx += 1

        if filters.pool_name:
            conditions.append(f"pool_name = ${param_idx}")
            params.append(filters.pool_name)
            param_idx += 1

        if filters.worker_id:
            conditions.append(f"worker_id = ${param_idx}")
            params.append(filters.worker_id)
            param_idx += 1

        if filters.engine:
            conditions.append(f"engine = ${param_idx}")
            params.append(filters.engine)
            param_idx += 1

        if filters.started_after:
            conditions.append(f"started_at >= ${param_idx}")
            params.append(filters.started_after)
            param_idx += 1

        if filters.started_before:
            conditions.append(f"started_at <= ${param_idx}")
            params.append(filters.started_before)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([filters.limit, filters.offset])

        query = f"""
            SELECT * FROM {self._table}
            {where_clause}
            ORDER BY started_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, *params)
                return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error("list_runs", e, {"filters": filters.model_dump()})

    async def get_latest_run_for_task(self, task_id: UUID) -> TaskRunRead | None:
        """Get the most recent run for a task.

        Args:
            task_id: Parent task ID

        Returns:
            Most recent run if exists, None otherwise

        Raises:
            RepositoryError: If query fails
        """
        query = f"""
            SELECT * FROM {self._table}
            WHERE task_id = $1
            ORDER BY run_number DESC
            LIMIT 1
        """

        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(query, task_id)

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "get_latest_run_for_task",
                e,
                {"task_id": str(task_id)},
            )

    async def get_next_run_number(self, task_id: UUID) -> int:
        """Get the next run number for a task.

        Args:
            task_id: Parent task ID

        Returns:
            Next run number (1 if no runs exist)

        Raises:
            RepositoryError: If query fails
        """
        query = f"""
            SELECT COALESCE(MAX(run_number), 0) + 1 as next_run_number
            FROM {self._table}
            WHERE task_id = $1
        """

        try:
            async with self.connection() as conn:
                result = await conn.fetchval(query, task_id)
                return result or 1

        except Exception as e:
            raise self._handle_error(
                "get_next_run_number",
                e,
                {"task_id": str(task_id)},
            )

    def _row_to_model(self, row: Any) -> TaskRunRead:
        """Convert database row to TaskRunRead model.

        Args:
            row: Database row record

        Returns:
            TaskRunRead model instance
        """
        return TaskRunRead(
            id=row["id"],
            task_id=row["task_id"],
            run_number=row["run_number"],
            pool_name=row["pool_name"],
            worker_id=row["worker_id"],
            worker_type=row["worker_type"],
            engine=row["engine"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            exit_code=row["exit_code"],
            error_message=row["error_message"],
            result_summary=row["result_summary"],
            metrics=row["metrics"] or {},
            metadata=row["metadata"] or {},
        )


__all__ = [
    "RunStatus",
    "TaskRunCreate",
    "TaskRunRead",
    "TaskRunUpdate",
    "TaskRunFilter",
    "TaskRunRepository",
]
