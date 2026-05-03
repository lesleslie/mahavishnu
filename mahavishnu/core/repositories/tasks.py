"""Task repository for orchestration.tasks table operations.

This module provides the repository layer for task persistence:
- create_task(): Create a new task
- get_task(): Retrieve a task by ID
- update_task_status(): Update task status
- list_tasks(): List tasks with filters
- add_dependency(): Add task dependency
- get_dependencies(): Get task dependencies

Schema: orchestration.tasks
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import logging
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from mahavishnu.core.repositories.base import BaseRepository, RepositoryError
from mahavishnu.core.status import TaskStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic Models for Task Repository
# =============================================================================


class TaskPriority(StrEnum):
    """Task priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DependencyType(StrEnum):
    """Task dependency types."""

    BLOCKS = "blocks"
    REQUIRES = "requires"
    RELATES_TO = "relates_to"


class TaskCreate(BaseModel):
    """Task creation request model.

    Args:
        title: Task title (required, 1-200 chars)
        description: Task description (optional, max 5000 chars)
        repository: Repository name (optional)
        pool_name: Pool name for execution (optional)
        worker_type: Worker type (optional)
        status: Initial status (default: pending)
        priority: Task priority (default: medium)
        created_by: Creator identifier (optional)
        assigned_to: Assignee identifier (optional)
        deadline: Task deadline (optional, ISO 8601)
        metadata: Additional task metadata (optional)
        external_id: External reference ID (optional)
    """

    title: str = Field(..., min_length=1, max_length=200, description="Task title")
    description: str | None = Field(None, max_length=5000, description="Task description")
    repository: str | None = Field(None, max_length=100, description="Repository name")
    pool_name: str | None = Field(None, max_length=100, description="Pool name")
    worker_type: str | None = Field(None, max_length=100, description="Worker type")
    status: TaskStatus = Field(default=TaskStatus.PENDING, description="Task status")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="Task priority")
    created_by: str | None = Field(None, max_length=100, description="Creator identifier")
    assigned_to: str | None = Field(None, max_length=100, description="Assignee identifier")
    deadline: datetime | None = Field(None, description="Task deadline")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional task metadata",
    )
    external_id: str | None = Field(None, max_length=200, description="External reference ID")


class TaskRead(BaseModel):
    """Task read response model.

    All fields from TaskCreate plus:
    - id: UUID (primary key)
    - created_at: Creation timestamp
    - updated_at: Last update timestamp
    - started_at: Execution start timestamp (optional)
    - completed_at: Completion timestamp (optional)
    """

    id: UUID = Field(..., description="Task unique identifier")
    external_id: str | None = Field(None, description="External reference ID")
    title: str = Field(..., description="Task title")
    description: str | None = Field(None, description="Task description")
    repository: str | None = Field(None, description="Repository name")
    pool_name: str | None = Field(None, description="Pool name")
    worker_type: str | None = Field(None, description="Worker type")
    status: TaskStatus = Field(..., description="Task status")
    priority: TaskPriority = Field(..., description="Task priority")
    created_by: str | None = Field(None, description="Creator identifier")
    assigned_to: str | None = Field(None, description="Assignee identifier")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    started_at: datetime | None = Field(None, description="Execution start timestamp")
    completed_at: datetime | None = Field(None, description="Completion timestamp")
    deadline: datetime | None = Field(None, description="Task deadline")
    metadata: dict[str, Any] = Field(..., description="Additional task metadata")


class TaskUpdate(BaseModel):
    """Task update request model.

    All fields are optional for partial updates.

    Args:
        title: New task title (optional)
        description: New description (optional)
        status: New status (optional)
        priority: New priority (optional)
        assigned_to: New assignee (optional)
        deadline: New deadline (optional)
        metadata: Metadata updates (optional, merged with existing)
        pool_name: New pool name (optional)
        worker_type: New worker type (optional)
    """

    title: str | None = Field(None, max_length=200, description="Task title")
    description: str | None = Field(None, max_length=5000, description="Task description")
    status: TaskStatus | None = Field(None, description="Task status")
    priority: TaskPriority | None = Field(None, description="Task priority")
    assigned_to: str | None = Field(None, max_length=100, description="Assignee identifier")
    deadline: datetime | None = Field(None, description="Task deadline")
    metadata: dict[str, Any] | None = Field(None, description="Metadata updates")
    pool_name: str | None = Field(None, max_length=100, description="Pool name")
    worker_type: str | None = Field(None, max_length=100, description="Worker type")


class TaskDependencyCreate(BaseModel):
    """Task dependency creation request.

    Args:
        task_id: Task that has the dependency
        depends_on_task_id: Task that is depended upon
        dependency_type: Type of dependency (default: blocks)
    """

    task_id: UUID = Field(..., description="Task with dependency")
    depends_on_task_id: UUID = Field(..., description="Task depended upon")
    dependency_type: DependencyType = Field(
        default=DependencyType.BLOCKS,
        description="Dependency type",
    )


class TaskDependencyRead(BaseModel):
    """Task dependency read response model.

    Args:
        task_id: Task that has the dependency
        depends_on_task_id: Task that is depended upon
        dependency_type: Type of dependency
        created_at: When dependency was created
    """

    task_id: UUID = Field(..., description="Task with dependency")
    depends_on_task_id: UUID = Field(..., description="Task depended upon")
    dependency_type: DependencyType = Field(..., description="Dependency type")
    created_at: datetime = Field(..., description="Dependency creation timestamp")


class TaskFilter(BaseModel):
    """Task filter for list operations.

    Args:
        status: Filter by status (optional)
        priority: Filter by priority (optional)
        repository: Filter by repository (optional)
        assigned_to: Filter by assignee (optional)
        created_after: Filter by creation date (optional)
        created_before: Filter by creation date (optional)
        limit: Maximum results (default: 50)
        offset: Result offset (default: 0)
    """

    status: TaskStatus | None = Field(None, description="Filter by status")
    priority: TaskPriority | None = Field(None, description="Filter by priority")
    repository: str | None = Field(None, max_length=100, description="Filter by repository")
    assigned_to: str | None = Field(None, max_length=100, description="Filter by assignee")
    created_after: datetime | None = Field(None, description="Filter created after")
    created_before: datetime | None = Field(None, description="Filter created before")
    limit: int = Field(default=50, ge=1, le=1000, description="Maximum results")
    offset: int = Field(default=0, ge=0, description="Result offset")


# =============================================================================
# Task Repository Implementation
# =============================================================================


class TaskRepository(BaseRepository[TaskCreate, TaskRead, TaskUpdate]):
    """Repository for orchestration.tasks table operations.

    Provides CRUD operations for tasks with:
    - Type-safe Pydantic model returns
    - Async context manager pattern
    - Structured error handling

    Usage:
        repo = TaskRepository()

        async with repo:
            task = await repo.create_task(TaskCreate(title="Fix bug"))
            tasks = await repo.list_tasks(TaskFilter(status=TaskStatus.PENDING))
    """

    def __init__(self) -> None:
        """Initialize task repository."""
        super().__init__()
        self._table = "orchestration.tasks"

    async def create_task(self, data: TaskCreate) -> TaskRead:
        """Create a new task.

        Args:
            data: Task creation data

        Returns:
            Created task with generated ID and timestamps

        Raises:
            RepositoryError: If creation fails
        """
        now = datetime.now(UTC)
        task_id = uuid4()

        query = f"""
            INSERT INTO {self._table} (
                id, external_id, title, description, repository, pool_name,
                worker_type, status, priority, created_by, assigned_to,
                created_at, updated_at, deadline, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            RETURNING *
        """

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    query,
                    task_id,
                    data.external_id,
                    data.title,
                    data.description,
                    data.repository,
                    data.pool_name,
                    data.worker_type,
                    data.status.value,
                    data.priority.value,
                    data.created_by,
                    data.assigned_to,
                    now,
                    now,
                    data.deadline,
                    data.metadata,
                )

                if row is None:
                    raise RepositoryError(
                        "Failed to create task",
                        operation="create_task",
                        details={"title": data.title},
                    )

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error("create_task", e, {"title": data.title})

    async def get_task(self, task_id: UUID) -> TaskRead | None:
        """Get a task by ID.

        Args:
            task_id: Task unique identifier

        Returns:
            Task if found, None otherwise

        Raises:
            RepositoryError: If query fails
        """
        query = f"SELECT * FROM {self._table} WHERE id = $1"

        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(query, task_id)

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error("get_task", e, {"task_id": str(task_id)})

    async def get_task_by_external_id(self, external_id: str) -> TaskRead | None:
        """Get a task by external ID.

        Args:
            external_id: External reference identifier

        Returns:
            Task if found, None otherwise

        Raises:
            RepositoryError: If query fails
        """
        query = f"SELECT * FROM {self._table} WHERE external_id = $1"

        try:
            async with self.connection() as conn:
                row = await conn.fetchrow(query, external_id)

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "get_task_by_external_id",
                e,
                {"external_id": external_id},
            )

    async def update_task_status(
        self,
        task_id: UUID,
        status: TaskStatus,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> TaskRead | None:
        """Update task status.

        Args:
            task_id: Task unique identifier
            status: New status
            started_at: Execution start time (optional, auto-set for in_progress)
            completed_at: Completion time (optional, auto-set for completed/failed/cancelled)

        Returns:
            Updated task if found, None otherwise

        Raises:
            RepositoryError: If update fails
        """
        now = datetime.now(UTC)

        # Auto-set timestamps based on status
        if status == TaskStatus.IN_PROGRESS and started_at is None:
            started_at = now
        elif (
            status
            in (
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            )
            and completed_at is None
        ):
            completed_at = now

        query = f"""
            UPDATE {self._table}
            SET status = $2, updated_at = $3, started_at = COALESCE($4, started_at),
                completed_at = COALESCE($5, completed_at)
            WHERE id = $1
            RETURNING *
        """

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    query,
                    task_id,
                    status.value,
                    now,
                    started_at,
                    completed_at,
                )

                if row is None:
                    return None

                return self._row_to_model(row)

        except Exception as e:
            raise self._handle_error(
                "update_task_status",
                e,
                {"task_id": str(task_id), "status": status.value},
            )

    async def update_task(self, task_id: UUID, data: TaskUpdate) -> TaskRead | None:
        """Update task fields.

        Args:
            task_id: Task unique identifier
            data: Update data (partial updates supported)

        Returns:
            Updated task if found, None otherwise

        Raises:
            RepositoryError: If update fails
        """
        # Build dynamic UPDATE query based on provided fields
        updates = []
        params = [task_id]
        param_idx = 2

        field_mapping = {
            "title": "title",
            "description": "description",
            "status": "status",
            "priority": "priority",
            "assigned_to": "assigned_to",
            "deadline": "deadline",
            "pool_name": "pool_name",
            "worker_type": "worker_type",
        }

        for field, column in field_mapping.items():
            value = getattr(data, field, None)
            if value is not None:
                if field in ("status", "priority"):
                    updates.append(f"{column} = ${param_idx}")
                    params.append(value.value)
                else:
                    updates.append(f"{column} = ${param_idx}")
                    params.append(value)
                param_idx += 1

        # Handle metadata merge
        if data.metadata is not None:
            updates.append(f"metadata = metadata || $${param_idx}::jsonb")
            params.append(data.metadata)
            param_idx += 1

        if not updates:
            # No updates provided, just return current task
            return await self.get_task(task_id)

        now = datetime.now(UTC)
        updates.append(f"updated_at = ${param_idx}")
        params.append(now)

        query = f"""
            UPDATE {self._table}
            SET {", ".join(updates)}
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
            raise self._handle_error(
                "update_task",
                e,
                {"task_id": str(task_id)},
            )

    async def list_tasks(self, filters: TaskFilter) -> list[TaskRead]:
        """List tasks with optional filters.

        Args:
            filters: Filter criteria for tasks

        Returns:
            List of tasks matching filters

        Raises:
            RepositoryError: If query fails
        """
        conditions = []
        params = []
        param_idx = 1

        if filters.status:
            conditions.append(f"status = ${param_idx}")
            params.append(filters.status.value)
            param_idx += 1

        if filters.priority:
            conditions.append(f"priority = ${param_idx}")
            params.append(filters.priority.value)
            param_idx += 1

        if filters.repository:
            conditions.append(f"repository = ${param_idx}")
            params.append(filters.repository)
            param_idx += 1

        if filters.assigned_to:
            conditions.append(f"assigned_to = ${param_idx}")
            params.append(filters.assigned_to)
            param_idx += 1

        if filters.created_after:
            conditions.append(f"created_at >= ${param_idx}")
            params.append(filters.created_after)
            param_idx += 1

        if filters.created_before:
            conditions.append(f"created_at <= ${param_idx}")
            params.append(filters.created_before)
            param_idx += 1

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([filters.limit, filters.offset])

        query = f"""
            SELECT * FROM {self._table}
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, *params)
                return [self._row_to_model(row) for row in rows]

        except Exception as e:
            raise self._handle_error("list_tasks", e, {"filters": filters.model_dump()})

    async def add_dependency(
        self,
        task_id: UUID,
        depends_on_task_id: UUID,
        dependency_type: DependencyType = DependencyType.BLOCKS,
    ) -> TaskDependencyRead:
        """Add a dependency between tasks.

        Args:
            task_id: Task that has the dependency
            depends_on_task_id: Task that is depended upon
            dependency_type: Type of dependency

        Returns:
            Created dependency relationship

        Raises:
            RepositoryError: If creation fails (e.g., cycle detection)
        """
        now = datetime.now(UTC)

        query = """
            INSERT INTO orchestration.task_dependencies (
                task_id, depends_on_task_id, dependency_type, created_at
            ) VALUES ($1, $2, $3, $4)
            RETURNING *
        """

        try:
            async with self.transaction() as conn:
                row = await conn.fetchrow(
                    query,
                    task_id,
                    depends_on_task_id,
                    dependency_type.value,
                    now,
                )

                if row is None:
                    raise RepositoryError(
                        "Failed to create dependency",
                        operation="add_dependency",
                        details={
                            "task_id": str(task_id),
                            "depends_on_task_id": str(depends_on_task_id),
                        },
                    )

                return TaskDependencyRead(
                    task_id=row["task_id"],
                    depends_on_task_id=row["depends_on_task_id"],
                    dependency_type=DependencyType(row["dependency_type"]),
                    created_at=row["created_at"],
                )

        except Exception as e:
            raise self._handle_error(
                "add_dependency",
                e,
                {
                    "task_id": str(task_id),
                    "depends_on_task_id": str(depends_on_task_id),
                },
            )

    async def get_dependencies(self, task_id: UUID) -> list[TaskDependencyRead]:
        """Get all dependencies for a task.

        Args:
            task_id: Task unique identifier

        Returns:
            List of dependencies (both outgoing and incoming)

        Raises:
            RepositoryError: If query fails
        """
        query = """
            SELECT * FROM orchestration.task_dependencies
            WHERE task_id = $1 OR depends_on_task_id = $1
            ORDER BY created_at
        """

        try:
            async with self.connection() as conn:
                rows = await conn.fetch(query, task_id)
                return [
                    TaskDependencyRead(
                        task_id=row["task_id"],
                        depends_on_task_id=row["depends_on_task_id"],
                        dependency_type=DependencyType(row["dependency_type"]),
                        created_at=row["created_at"],
                    )
                    for row in rows
                ]

        except Exception as e:
            raise self._handle_error(
                "get_dependencies",
                e,
                {"task_id": str(task_id)},
            )

    async def delete_task(self, task_id: UUID) -> bool:
        """Delete a task.

        Args:
            task_id: Task unique identifier

        Returns:
            True if deleted, False if not found

        Raises:
            RepositoryError: If deletion fails
        """
        query = f"DELETE FROM {self._table} WHERE id = $1"

        try:
            async with self.transaction() as conn:
                result = await conn.execute(query, task_id)
                return result == "DELETE 1"

        except Exception as e:
            raise self._handle_error(
                "delete_task",
                e,
                {"task_id": str(task_id)},
            )

    def _row_to_model(self, row: Any) -> TaskRead:
        """Convert database row to TaskRead model.

        Args:
            row: Database row record

        Returns:
            TaskRead model instance
        """
        return TaskRead(
            id=row["id"],
            external_id=row["external_id"],
            title=row["title"],
            description=row["description"],
            repository=row["repository"],
            pool_name=row["pool_name"],
            worker_type=row["worker_type"],
            status=TaskStatus(row["status"]),
            priority=TaskPriority(row["priority"]),
            created_by=row["created_by"],
            assigned_to=row["assigned_to"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            deadline=row["deadline"],
            metadata=row["metadata"] or {},
        )


__all__ = [
    "TaskPriority",
    "DependencyType",
    "TaskCreate",
    "TaskRead",
    "TaskUpdate",
    "TaskDependencyCreate",
    "TaskDependencyRead",
    "TaskFilter",
    "TaskRepository",
]
