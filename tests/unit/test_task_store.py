"""Tests for Task Store Module.

Tests cover:
- Task CRUD operations
- Batch operations
- Filtering and search
- Dependencies
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, UTC

from mahavishnu.core.task_store import (
    TaskStore,
    Task,
    TaskCreate,
    TaskUpdate,
    TaskStatus,
    TaskPriority,
    TaskListFilter,
    TaskDependency,
)


class TestTaskStatus:
    """Test task status enum."""

    def test_all_statuses(self) -> None:
        """Test all status values exist."""
        expected = ["pending", "in_progress", "completed", "failed", "cancelled", "blocked"]
        for status in expected:
            assert TaskStatus(status).value == status


class TestTaskPriority:
    """Test task priority enum."""

    def test_all_priorities(self) -> None:
        """Test all priority values exist."""
        expected = ["low", "medium", "high", "critical"]
        for priority in expected:
            assert TaskPriority(priority).value == priority


class TestTaskCreate:
    """Test task creation data."""

    def test_default_values(self) -> None:
        """Test default values."""
        data = TaskCreate(title="Test", repository="test-repo")

        assert data.title == "Test"
        assert data.repository == "test-repo"
        assert data.description is None
        assert data.priority == TaskPriority.MEDIUM
        assert data.status == TaskStatus.PENDING
        assert data.assignee is None
        assert data.tags == []
        assert data.metadata == {}

    def test_validate_valid(self) -> None:
        """Test validation of valid data."""
        data = TaskCreate(title="Valid Task", repository="repo")
        errors = data.validate()

        assert errors == []

    def test_validate_short_title(self) -> None:
        """Test validation rejects short title."""
        data = TaskCreate(title="AB", repository="repo")
        errors = data.validate()

        assert len(errors) == 1
        assert "at least 3 characters" in errors[0]

    def test_validate_long_title(self) -> None:
        """Test validation rejects long title."""
        data = TaskCreate(title="X" * 501, repository="repo")
        errors = data.validate()

        assert len(errors) == 1
        assert "at most 500 characters" in errors[0]

    def test_validate_missing_repository(self) -> None:
        """Test validation rejects missing repository."""
        data = TaskCreate(title="Valid Task", repository="")
        errors = data.validate()

        assert len(errors) == 1
        assert "Repository is required" in errors[0]


class TestTaskUpdate:
    """Test task update data."""

    def test_has_updates_false(self) -> None:
        """Test has_updates returns False for empty update."""
        data = TaskUpdate()

        assert data.has_updates() is False

    def test_has_updates_true(self) -> None:
        """Test has_updates returns True when updates present."""
        data = TaskUpdate(title="New Title")

        assert data.has_updates() is True

    def test_validate_valid(self) -> None:
        """Test validation of valid update."""
        data = TaskUpdate(title="Valid Title")
        errors = data.validate()

        assert errors == []

    def test_validate_short_title(self) -> None:
        """Test validation rejects short title."""
        data = TaskUpdate(title="AB")
        errors = data.validate()

        assert len(errors) == 1


class TestTask:
    """Test Task entity."""

    def test_from_row(self) -> None:
        """Test creating task from database row."""
        row = {
            "id": "task-123",
            "title": "Test Task",
            "repository": "mahavishnu",
            "description": "Description",
            "status": "in_progress",
            "priority": "high",
            "assignee": "user@example.com",
            "tags": ["backend", "api"],
            "metadata": {"key": "value"},
            "due_date": None,
            "external_id": None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "completed_at": None,
            "created_by": "system",
        }

        task = Task.from_row(row)

        assert task.id == "task-123"
        assert task.title == "Test Task"
        assert task.repository == "mahavishnu"
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.priority == TaskPriority.HIGH
        assert task.assignee == "user@example.com"
        assert task.tags == ["backend", "api"]

    def test_to_dict(self) -> None:
        """Test task serialization."""
        task = Task(
            id="task-123",
            title="Test Task",
            repository="mahavishnu",
            status=TaskStatus.PENDING,
            priority=TaskPriority.MEDIUM,
        )

        result = task.to_dict()

        assert result["id"] == "task-123"
        assert result["title"] == "Test Task"
        assert result["repository"] == "mahavishnu"
        assert result["status"] == "pending"
        assert result["priority"] == "medium"


class TestTaskListFilter:
    """Test task list filter."""

    def test_default_values(self) -> None:
        """Test default filter values."""
        filter = TaskListFilter()

        assert filter.repository is None
        assert filter.status is None
        assert filter.priority is None
        assert filter.limit == 100
        assert filter.offset == 0


class TestTaskStore:
    """Test task store."""

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        """Create mock database."""
        db = MagicMock()

        # Mock async methods
        db.execute = AsyncMock()
        db.fetch = AsyncMock(return_value=[])
        db.fetchrow = AsyncMock(return_value=None)
        db.fetchval = AsyncMock(return_value=0)

        # Mock connection for transactions
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_acquire = MagicMock()
        mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.__aexit__ = AsyncMock(return_value=None)
        db.acquire.return_value = mock_acquire

        # Mock transaction
        mock_transaction = MagicMock()
        mock_transaction.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_transaction.__aexit__ = AsyncMock(return_value=None)
        db.transaction.return_value = mock_transaction

        return db

    @pytest.fixture
    def mock_event_store(self) -> MagicMock:
        """Create mock event store."""
        store = MagicMock()
        store.append = AsyncMock()
        return store

    @pytest.fixture
    def store(self, mock_db: MagicMock, mock_event_store: MagicMock) -> TaskStore:
        """Create task store with mocks."""
        return TaskStore(mock_db, mock_event_store)

    @pytest.mark.asyncio
    async def test_create_task(self, store: TaskStore, mock_db: MagicMock) -> None:
        """Test creating a task."""
        task_data = TaskCreate(
            title="New Task",
            repository="mahavishnu",
            priority=TaskPriority.HIGH,
        )

        # Mock the get call after create
        mock_db.fetchrow = AsyncMock(
            return_value={
                "id": "task-123",
                "title": "New Task",
                "repository": "mahavishnu",
                "description": None,
                "status": "pending",
                "priority": "high",
                "assignee": None,
                "tags": [],
                "metadata": {},
                "due_date": None,
                "external_id": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "completed_at": None,
                "created_by": "system",
            }
        )

        task = await store.create(task_data)

        assert task is not None
        assert task.title == "New Task"
        mock_db.execute.assert_called()
        store.event_store.append.assert_called()

    @pytest.mark.asyncio
    async def test_get_task(self, store: TaskStore, mock_db: MagicMock) -> None:
        """Test getting a task."""
        mock_db.fetchrow = AsyncMock(
            return_value={
                "id": "task-123",
                "title": "Test Task",
                "repository": "mahavishnu",
                "description": None,
                "status": "pending",
                "priority": "medium",
                "assignee": None,
                "tags": [],
                "metadata": {},
                "due_date": None,
                "external_id": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "completed_at": None,
                "created_by": "system",
            }
        )

        task = await store.get("task-123")

        assert task.id == "task-123"
        assert task.title == "Test Task"

    @pytest.mark.asyncio
    async def test_update_task(self, store: TaskStore, mock_db: MagicMock) -> None:
        """Test updating a task."""
        update_data = TaskUpdate(status=TaskStatus.COMPLETED)

        mock_db.fetchrow = AsyncMock(
            return_value={
                "id": "task-123",
                "title": "Test Task",
                "repository": "mahavishnu",
                "description": None,
                "status": "completed",
                "priority": "medium",
                "assignee": None,
                "tags": [],
                "metadata": {},
                "due_date": None,
                "external_id": None,
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "completed_at": datetime.now(UTC),
                "created_by": "system",
            }
        )

        task = await store.update("task-123", update_data, actor="user@example.com")

        mock_db.execute.assert_called()
        store.event_store.append.assert_called()

    @pytest.mark.asyncio
    async def test_delete_task(self, store: TaskStore, mock_db: MagicMock) -> None:
        """Test deleting a task."""
        await store.delete("task-123", actor="user@example.com")

        mock_db.execute.assert_called()
        store.event_store.append.assert_called()

    @pytest.mark.asyncio
    async def test_list_tasks(self, store: TaskStore, mock_db: MagicMock) -> None:
        """Test listing tasks."""
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "id": "task-1",
                    "title": "Task 1",
                    "repository": "mahavishnu",
                    "description": None,
                    "status": "pending",
                    "priority": "medium",
                    "assignee": None,
                    "tags": [],
                    "metadata": {},
                    "due_date": None,
                    "external_id": None,
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "completed_at": None,
                    "created_by": "system",
                },
                {
                    "id": "task-2",
                    "title": "Task 2",
                    "repository": "mahavishnu",
                    "description": None,
                    "status": "in_progress",
                    "priority": "high",
                    "assignee": None,
                    "tags": [],
                    "metadata": {},
                    "due_date": None,
                    "external_id": None,
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "completed_at": None,
                    "created_by": "system",
                },
            ]
        )

        tasks = await store.list(repository="mahavishnu")

        assert len(tasks) == 2
        mock_db.fetch.assert_called()

    @pytest.mark.asyncio
    async def test_count_tasks(self, store: TaskStore, mock_db: MagicMock) -> None:
        """Test counting tasks."""
        mock_db.fetchval = AsyncMock(return_value=42)

        count = await store.count(repository="mahavishnu")

        assert count == 42

    @pytest.mark.asyncio
    async def test_add_dependency(self, store: TaskStore, mock_db: MagicMock) -> None:
        """Test adding a dependency."""
        dependency = await store.add_dependency(
            task_id="task-1",
            depends_on_task_id="task-2",
            dependency_type="blocks",
        )

        assert dependency.task_id == "task-1"
        assert dependency.depends_on_task_id == "task-2"
        mock_db.execute.assert_called()

    @pytest.mark.asyncio
    async def test_add_dependency_self_fails(self, store: TaskStore) -> None:
        """Test that self-dependency is rejected."""
        from mahavishnu.core.errors import ValidationError

        with pytest.raises(ValidationError):
            await store.add_dependency(
                task_id="task-1",
                depends_on_task_id="task-1",
            )

    @pytest.mark.asyncio
    async def test_get_dependencies(self, store: TaskStore, mock_db: MagicMock) -> None:
        """Test getting dependencies."""
        mock_db.fetch = AsyncMock(
            return_value=[
                {
                    "task_id": "task-1",
                    "depends_on_task_id": "task-2",
                    "dependency_type": "blocks",
                    "created_at": datetime.now(UTC),
                }
            ]
        )

        deps = await store.get_dependencies("task-1")

        assert len(deps) == 1
        assert deps[0].depends_on_task_id == "task-2"


class TestTaskDependency:
    """Test task dependency."""

    def test_from_row(self) -> None:
        """Test creating from database row."""
        row = {
            "task_id": "task-1",
            "depends_on_task_id": "task-2",
            "dependency_type": "blocks",
            "created_at": datetime.now(UTC),
        }

        dep = TaskDependency.from_row(row)

        assert dep.task_id == "task-1"
        assert dep.depends_on_task_id == "task-2"
        assert dep.dependency_type == "blocks"
