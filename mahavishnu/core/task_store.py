"""Task Store for Mahavishnu Task Orchestration.

Provides CRUD operations for tasks with:
- Async database operations
- Batch operations for efficiency
- Task relationships and dependencies
- Full-text and semantic search
- Event sourcing integration

Usage:
    from mahavishnu.core.task_store import TaskStore, TaskCreate, TaskUpdate

    store = TaskStore(db)

    # Create a task
    task = await store.create(TaskCreate(
        title="Implement feature",
        repository="mahavishnu",
        priority="high",
    ))

    # Get task by ID
    task = await store.get(task_id)

    # List tasks with filters
    tasks = await store.list(repository="mahavishnu", status="in_progress")

    # Update task
    task = await store.update(task_id, TaskUpdate(status="completed"))

    # Delete task
    await store.delete(task_id)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any

from mahavishnu.core.database import Database
from mahavishnu.core.errors import DatabaseError, MahavishnuError, ValidationError
from mahavishnu.core.event_store import EventStore, TaskEventType

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task status values."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class TaskPriority(str, Enum):
    """Task priority values."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class TaskCreate:
    """Data for creating a task."""

    title: str
    repository: str
    description: str | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    assignee: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    due_date: datetime | None = None
    external_id: str | None = None  # GitHub issue ID, etc.
    created_by: str = "system"

    def validate(self) -> list[str]:
        """Validate task data.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not self.title or len(self.title.strip()) < 3:
            errors.append("Title must be at least 3 characters")

        if len(self.title) > 500:
            errors.append("Title must be at most 500 characters")

        if not self.repository or len(self.repository.strip()) < 1:
            errors.append("Repository is required")

        return errors


@dataclass
class TaskUpdate:
    """Data for updating a task."""

    title: str | None = None
    description: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    due_date: datetime | None = None

    def validate(self) -> list[str]:
        """Validate update data.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if self.title is not None and len(self.title.strip()) < 3:
            errors.append("Title must be at least 3 characters")

        if self.title is not None and len(self.title) > 500:
            errors.append("Title must be at most 500 characters")

        return errors

    def has_updates(self) -> bool:
        """Check if any updates are present."""
        return any([
            self.title is not None,
            self.description is not None,
            self.status is not None,
            self.priority is not None,
            self.assignee is not None,
            self.tags is not None,
            self.metadata is not None,
            self.due_date is not None,
        ])


@dataclass
class Task:
    """A task entity."""

    id: str
    title: str
    repository: str
    description: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    due_date: datetime | None = None
    external_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    created_by: str = "system"

    @classmethod
    def from_row(cls, row: Any) -> "Task":
        """Create Task from database row."""
        return cls(
            id=str(row["id"]),
            title=row["title"],
            repository=row["repository"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            priority=TaskPriority(row["priority"]),
            assignee=row["assignee"],
            tags=list(row["tags"]) if row["tags"] else [],
            metadata=dict(row["metadata"]) if row["metadata"] else {},
            due_date=row["due_date"],
            external_id=row["external_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            created_by=row["created_by"],
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "repository": self.repository,
            "description": self.description,
            "status": self.status.value,
            "priority": self.priority.value,
            "assignee": self.assignee,
            "tags": self.tags,
            "metadata": self.metadata,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "external_id": self.external_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_by": self.created_by,
        }


@dataclass
class TaskListFilter:
    """Filters for listing tasks."""

    repository: str | None = None
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee: str | None = None
    tags: list[str] | None = None
    search: str | None = None
    due_before: datetime | None = None
    due_after: datetime | None = None
    created_after: datetime | None = None
    limit: int = 100
    offset: int = 0


@dataclass
class TaskDependency:
    """A task dependency relationship."""

    task_id: str
    depends_on_task_id: str
    dependency_type: str = "blocks"  # blocks, requires, related
    created_at: datetime | None = None

    @classmethod
    def from_row(cls, row: Any) -> "TaskDependency":
        """Create from database row."""
        return cls(
            task_id=str(row["task_id"]),
            depends_on_task_id=str(row["depends_on_task_id"]),
            dependency_type=row["dependency_type"],
            created_at=row["created_at"],
        )


class TaskStore:
    """Task store with CRUD operations.

    Features:
    - Create, read, update, delete operations
    - Batch operations for efficiency
    - Filtering and search
    - Task dependencies
    - Event sourcing integration

    Example:
        store = TaskStore(db)

        # Create
        task = await store.create(TaskCreate(
            title="Implement feature",
            repository="mahavishnu",
        ))

        # Read
        task = await store.get(task.id)

        # Update
        task = await store.update(task.id, TaskUpdate(status="completed"))

        # Delete
        await store.delete(task.id)

        # List with filters
        tasks = await store.list(repository="mahavishnu", status="in_progress")
    """

    def __init__(self, db: Database, event_store: EventStore | None = None):
        """Initialize task store.

        Args:
            db: Database connection
            event_store: Optional event store for audit trail
        """
        self.db = db
        self.event_store = event_store or EventStore(db)

    async def create(self, data: TaskCreate) -> Task:
        """Create a new task.

        Args:
            data: Task creation data

        Returns:
            Created task

        Raises:
            ValidationError: If data is invalid
            DatabaseError: If creation fails
        """
        # Validate
        errors = data.validate()
        if errors:
            raise ValidationError(
                f"Invalid task data: {'; '.join(errors)}",
                details={"errors": errors},
            )

        task_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        try:
            await self.db.execute(
                """
                INSERT INTO tasks
                    (id, title, description, repository, status, priority,
                     assignee, tags, metadata, due_date, external_id,
                     created_at, updated_at, created_by)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                """,
                task_id,
                data.title,
                data.description,
                data.repository,
                data.status.value,
                data.priority.value,
                data.assignee,
                data.tags,
                data.metadata,
                data.due_date,
                data.external_id,
                now,
                now,
                data.created_by,
            )

            # Record event
            await self.event_store.append(
                task_id=task_id,
                event_type=TaskEventType.CREATED,
                data={
                    "title": data.title,
                    "description": data.description,
                    "repository": data.repository,
                    "status": data.status.value,
                    "priority": data.priority.value,
                    "tags": data.tags,
                },
                actor=data.created_by,
            )

            # Fetch and return
            task = await self.get(task_id)
            logger.info(f"Created task {task_id}: {data.title}")
            return task

        except Exception as e:
            logger.error(f"Failed to create task: {e}")
            raise DatabaseError(
                f"Failed to create task: {e}",
                details={"title": data.title},
            ) from e

    async def get(self, task_id: str) -> Task:
        """Get a task by ID.

        Args:
            task_id: Task identifier

        Returns:
            Task

        Raises:
            DatabaseError: If task not found or query fails
        """
        row = await self.db.fetchrow(
            """
            SELECT * FROM tasks WHERE id = $1
            """,
            task_id,
        )

        if row is None:
            raise DatabaseError(
                f"Task not found: {task_id}",
                details={"task_id": task_id},
            )

        return Task.from_row(row)

    async def get_by_external_id(self, external_id: str) -> Task | None:
        """Get a task by external ID (e.g., GitHub issue ID).

        Args:
            external_id: External identifier

        Returns:
            Task if found, None otherwise
        """
        row = await self.db.fetchrow(
            """
            SELECT * FROM tasks WHERE external_id = $1
            """,
            external_id,
        )

        return Task.from_row(row) if row else None

    async def update(self, task_id: str, data: TaskUpdate, actor: str = "system") -> Task:
        """Update a task.

        Args:
            task_id: Task identifier
            data: Update data
            actor: Who is making the update

        Returns:
            Updated task

        Raises:
            ValidationError: If data is invalid
            DatabaseError: If update fails
        """
        # Validate
        errors = data.validate()
        if errors:
            raise ValidationError(
                f"Invalid update data: {'; '.join(errors)}",
                details={"errors": errors},
            )

        if not data.has_updates():
            return await self.get(task_id)

        # Build update query dynamically
        updates: list[str] = []
        params: list[Any] = [task_id]
        param_count = 1

        event_data: dict[str, Any] = {}

        if data.title is not None:
            param_count += 1
            updates.append(f"title = ${param_count}")
            params.append(data.title)
            event_data["title"] = data.title

        if data.description is not None:
            param_count += 1
            updates.append(f"description = ${param_count}")
            params.append(data.description)
            event_data["description"] = data.description

        if data.status is not None:
            param_count += 1
            updates.append(f"status = ${param_count}")
            params.append(data.status.value)
            event_data["new_status"] = data.status.value

            # Set completed_at if completing
            if data.status == TaskStatus.COMPLETED:
                param_count += 1
                updates.append(f"completed_at = ${param_count}")
                params.append(datetime.now(UTC))

        if data.priority is not None:
            param_count += 1
            updates.append(f"priority = ${param_count}")
            params.append(data.priority.value)
            event_data["new_priority"] = data.priority.value

        if data.assignee is not None:
            param_count += 1
            updates.append(f"assignee = ${param_count}")
            params.append(data.assignee)
            event_data["assignee"] = data.assignee

        if data.tags is not None:
            param_count += 1
            updates.append(f"tags = ${param_count}")
            params.append(data.tags)
            event_data["tags"] = data.tags

        if data.metadata is not None:
            param_count += 1
            updates.append(f"metadata = ${param_count}")
            params.append(data.metadata)
            event_data["metadata"] = data.metadata

        if data.due_date is not None:
            param_count += 1
            updates.append(f"due_date = ${param_count}")
            params.append(data.due_date)
            event_data["due_date"] = data.due_date.isoformat()

        # Add updated_at
        param_count += 1
        updates.append(f"updated_at = ${param_count}")
        params.append(datetime.now(UTC))

        try:
            query = f"""
                UPDATE tasks
                SET {', '.join(updates)}
                WHERE id = $1
            """
            await self.db.execute(query, *params)

            # Record event
            await self.event_store.append(
                task_id=task_id,
                event_type=TaskEventType.UPDATED,
                data=event_data,
                actor=actor,
            )

            return await self.get(task_id)

        except Exception as e:
            logger.error(f"Failed to update task {task_id}: {e}")
            raise DatabaseError(
                f"Failed to update task: {e}",
                details={"task_id": task_id},
            ) from e

    async def delete(self, task_id: str, actor: str = "system") -> None:
        """Delete a task.

        Args:
            task_id: Task identifier
            actor: Who is deleting the task

        Raises:
            DatabaseError: If deletion fails
        """
        try:
            # Record event before deletion
            await self.event_store.append(
                task_id=task_id,
                event_type=TaskEventType.DELETED,
                data={},
                actor=actor,
            )

            await self.db.execute(
                """
                DELETE FROM tasks WHERE id = $1
                """,
                task_id,
            )

            logger.info(f"Deleted task {task_id}")

        except Exception as e:
            logger.error(f"Failed to delete task {task_id}: {e}")
            raise DatabaseError(
                f"Failed to delete task: {e}",
                details={"task_id": task_id},
            ) from e

    async def list(self, filters: TaskListFilter | None = None, **kwargs: Any) -> list[Task]:
        """List tasks with optional filters.

        Args:
            filters: Filter criteria
            **kwargs: Filter criteria as keyword arguments

        Returns:
            List of tasks
        """
        if filters is None:
            filters = TaskListFilter(**kwargs)

        query = "SELECT * FROM tasks WHERE 1=1"
        params: list[Any] = []
        param_count = 0

        if filters.repository:
            param_count += 1
            query += f" AND repository = ${param_count}"
            params.append(filters.repository)

        if filters.status:
            param_count += 1
            query += f" AND status = ${param_count}"
            params.append(filters.status.value)

        if filters.priority:
            param_count += 1
            query += f" AND priority = ${param_count}"
            params.append(filters.priority.value)

        if filters.assignee:
            param_count += 1
            query += f" AND assignee = ${param_count}"
            params.append(filters.assignee)

        if filters.tags:
            param_count += 1
            query += f" AND tags && ${param_count}"
            params.append(filters.tags)

        if filters.search:
            param_count += 1
            query += f" AND to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(description, '')) @@ plainto_tsquery('english', ${param_count})"
            params.append(filters.search)

        if filters.due_before:
            param_count += 1
            query += f" AND due_date < ${param_count}"
            params.append(filters.due_before)

        if filters.due_after:
            param_count += 1
            query += f" AND due_date > ${param_count}"
            params.append(filters.due_after)

        if filters.created_after:
            param_count += 1
            query += f" AND created_at > ${param_count}"
            params.append(filters.created_after)

        query += " ORDER BY created_at DESC"

        param_count += 1
        query += f" LIMIT ${param_count}"
        params.append(filters.limit)

        param_count += 1
        query += f" OFFSET ${param_count}"
        params.append(filters.offset)

        rows = await self.db.fetch(query, *params)
        return [Task.from_row(row) for row in rows]

    async def count(self, filters: TaskListFilter | None = None, **kwargs: Any) -> int:
        """Count tasks with optional filters.

        Args:
            filters: Filter criteria
            **kwargs: Filter criteria as keyword arguments

        Returns:
            Number of matching tasks
        """
        if filters is None:
            filters = TaskListFilter(**kwargs)

        query = "SELECT COUNT(*) FROM tasks WHERE 1=1"
        params: list[Any] = []
        param_count = 0

        if filters.repository:
            param_count += 1
            query += f" AND repository = ${param_count}"
            params.append(filters.repository)

        if filters.status:
            param_count += 1
            query += f" AND status = ${param_count}"
            params.append(filters.status.value)

        if filters.priority:
            param_count += 1
            query += f" AND priority = ${param_count}"
            params.append(filters.priority.value)

        if filters.assignee:
            param_count += 1
            query += f" AND assignee = ${param_count}"
            params.append(filters.assignee)

        return await self.db.fetchval(query, *params)

    # Batch operations

    async def create_batch(self, tasks: list[TaskCreate], actor: str = "system") -> list[Task]:
        """Create multiple tasks in a batch.

        Args:
            tasks: List of task creation data
            actor: Who is creating the tasks

        Returns:
            List of created tasks
        """
        created: list[Task] = []

        async with self.db.transaction():
            for task_data in tasks:
                task = await self.create(task_data)
                created.append(task)

        logger.info(f"Created {len(created)} tasks in batch")
        return created

    async def update_status_batch(
        self,
        task_ids: list[str],
        status: TaskStatus,
        actor: str = "system",
    ) -> int:
        """Update status for multiple tasks.

        Args:
            task_ids: List of task identifiers
            status: New status
            actor: Who is updating the tasks

        Returns:
            Number of tasks updated
        """
        if not task_ids:
            return 0

        now = datetime.now(UTC)
        completed_at = now if status == TaskStatus.COMPLETED else None

        async with self.db.transaction() as conn:
            # Update tasks
            if completed_at:
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = $1, updated_at = $2, completed_at = $3
                    WHERE id = ANY($4)
                    """,
                    status.value,
                    now,
                    completed_at,
                    task_ids,
                )
            else:
                await conn.execute(
                    """
                    UPDATE tasks
                    SET status = $1, updated_at = $2
                    WHERE id = ANY($3)
                    """,
                    status.value,
                    now,
                    task_ids,
                )

            # Record events
            for task_id in task_ids:
                await self.event_store.append(
                    task_id=task_id,
                    event_type=TaskEventType.STATUS_CHANGED,
                    data={"new_status": status.value},
                    actor=actor,
                )

        logger.info(f"Updated status to {status.value} for {len(task_ids)} tasks")
        return len(task_ids)

    # Dependency operations

    async def add_dependency(
        self,
        task_id: str,
        depends_on_task_id: str,
        dependency_type: str = "blocks",
        actor: str = "system",
    ) -> TaskDependency:
        """Add a dependency between tasks.

        Args:
            task_id: Task that has the dependency
            depends_on_task_id: Task that is depended upon
            dependency_type: Type of dependency (blocks, requires, related)
            actor: Who is adding the dependency

        Returns:
            Created dependency

        Raises:
            DatabaseError: If dependency creation fails
        """
        if task_id == depends_on_task_id:
            raise ValidationError("Task cannot depend on itself")

        try:
            await self.db.execute(
                """
                INSERT INTO task_dependencies
                    (task_id, depends_on_task_id, dependency_type)
                VALUES
                    ($1, $2, $3)
                """,
                task_id,
                depends_on_task_id,
                dependency_type,
            )

            # Record event
            await self.event_store.append(
                task_id=task_id,
                event_type=TaskEventType.DEPENDENCY_ADDED,
                data={"depends_on_task_id": depends_on_task_id, "type": dependency_type},
                actor=actor,
            )

            return TaskDependency(
                task_id=task_id,
                depends_on_task_id=depends_on_task_id,
                dependency_type=dependency_type,
            )

        except Exception as e:
            logger.error(f"Failed to add dependency: {e}")
            raise DatabaseError(
                f"Failed to add dependency: {e}",
                details={"task_id": task_id, "depends_on": depends_on_task_id},
            ) from e

    async def remove_dependency(
        self,
        task_id: str,
        depends_on_task_id: str,
        actor: str = "system",
    ) -> None:
        """Remove a dependency between tasks.

        Args:
            task_id: Task that has the dependency
            depends_on_task_id: Task that is depended upon
            actor: Who is removing the dependency
        """
        await self.db.execute(
            """
            DELETE FROM task_dependencies
            WHERE task_id = $1 AND depends_on_task_id = $2
            """,
            task_id,
            depends_on_task_id,
        )

        # Record event
        await self.event_store.append(
            task_id=task_id,
            event_type=TaskEventType.DEPENDENCY_REMOVED,
            data={"depends_on_task_id": depends_on_task_id},
            actor=actor,
        )

    async def get_dependencies(self, task_id: str) -> list[TaskDependency]:
        """Get all dependencies for a task.

        Args:
            task_id: Task identifier

        Returns:
            List of dependencies
        """
        rows = await self.db.fetch(
            """
            SELECT * FROM task_dependencies WHERE task_id = $1
            """,
            task_id,
        )
        return [TaskDependency.from_row(row) for row in rows]

    async def get_dependents(self, task_id: str) -> list[TaskDependency]:
        """Get all tasks that depend on a task.

        Args:
            task_id: Task identifier

        Returns:
            List of dependencies where this task is depended upon
        """
        rows = await self.db.fetch(
            """
            SELECT * FROM task_dependencies WHERE depends_on_task_id = $1
            """,
            task_id,
        )
        return [TaskDependency.from_row(row) for row in rows]
