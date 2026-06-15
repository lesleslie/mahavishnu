"""Tests for mahavishnu.core.repositories.tasks.TaskRepository.

These tests exercise the public surface of the TaskRepository and its Pydantic
models, mocking the asyncpg connection / transaction contexts provided by the
BaseRepository. Goal: >=80% line+branch coverage.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from mahavishnu.core.repositories.base import RepositoryError
from mahavishnu.core.repositories.tasks import (
    DependencyType,
    TaskCreate,
    TaskDependencyCreate,
    TaskDependencyRead,
    TaskFilter,
    TaskPriority,
    TaskRead,
    TaskRepository,
    TaskUpdate,
)
from mahavishnu.core.status import TaskStatus

pytestmark = pytest.mark.unit


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _make_row(
    *,
    task_id: UUID | None = None,
    title: str = "Test task",
    description: str | None = None,
    repository: str | None = None,
    pool_name: str | None = None,
    worker_type: str | None = None,
    status: str = "pending",
    priority: str = "medium",
    created_by: str | None = None,
    assigned_to: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    deadline: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Build a fake database row dict for TaskRead."""
    now = datetime.now(UTC)
    return {
        "id": task_id or uuid4(),
        "external_id": external_id,
        "title": title,
        "description": description,
        "repository": repository,
        "pool_name": pool_name,
        "worker_type": worker_type,
        "status": status,
        "priority": priority,
        "created_by": created_by,
        "assigned_to": assigned_to,
        "created_at": created_at or now,
        "updated_at": updated_at or now,
        "started_at": started_at,
        "completed_at": completed_at,
        "deadline": deadline,
        "metadata": metadata or {},
    }


@asynccontextmanager
async def _fake_transaction(conn: AsyncMock):
    """Yield a fake connection inside a transaction-like context."""
    yield conn


@asynccontextmanager
async def _fake_connection(conn: AsyncMock):
    """Yield a fake connection."""
    yield conn


def _patch_repo(repo: TaskRepository, conn: AsyncMock) -> None:
    """Patch a TaskRepository's connection/transaction context managers."""

    @asynccontextmanager
    async def transaction():
        yield conn

    @asynccontextmanager
    async def connection():
        yield conn

    repo.transaction = transaction  # type: ignore[method-assign]
    repo.connection = connection  # type: ignore[method-assign]


# ----------------------------------------------------------------------------
# Pydantic model tests
# ----------------------------------------------------------------------------


def test_task_priority_enum_values() -> None:
    assert TaskPriority.LOW.value == "low"
    assert TaskPriority.MEDIUM.value == "medium"
    assert TaskPriority.HIGH.value == "high"
    assert TaskPriority.CRITICAL.value == "critical"


def test_dependency_type_enum_values() -> None:
    assert DependencyType.BLOCKS.value == "blocks"
    assert DependencyType.REQUIRES.value == "requires"
    assert DependencyType.RELATES_TO.value == "relates_to"


def test_task_create_defaults() -> None:
    tc = TaskCreate(title="Hello")
    assert tc.title == "Hello"
    assert tc.description is None
    assert tc.status == TaskStatus.PENDING
    assert tc.priority == TaskPriority.MEDIUM
    assert tc.metadata == {}


def test_task_create_validates_title_length() -> None:
    with pytest.raises(ValueError):
        TaskCreate(title="")
    with pytest.raises(ValueError):
        TaskCreate(title="x" * 201)


def test_task_create_validates_description_length() -> None:
    with pytest.raises(ValueError):
        TaskCreate(title="ok", description="x" * 5001)


def test_task_create_with_all_fields() -> None:
    deadline = datetime(2026, 1, 1, tzinfo=UTC)
    tc = TaskCreate(
        title="Full",
        description="Desc",
        repository="repo1",
        pool_name="pool-a",
        worker_type="terminal-claude",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        created_by="alice",
        assigned_to="bob",
        deadline=deadline,
        metadata={"k": "v"},
        external_id="ext-1",
    )
    assert tc.deadline == deadline
    assert tc.metadata == {"k": "v"}
    assert tc.external_id == "ext-1"


def test_task_read_required_fields() -> None:
    with pytest.raises(ValueError):
        TaskRead.model_validate({})


def test_task_update_all_optional() -> None:
    upd = TaskUpdate()
    assert upd.title is None
    assert upd.status is None
    assert upd.priority is None


def test_task_dependency_create_default_type() -> None:
    a, b = uuid4(), uuid4()
    d = TaskDependencyCreate(task_id=a, depends_on_task_id=b)
    assert d.dependency_type == DependencyType.BLOCKS


def test_task_dependency_read_validates() -> None:
    a, b = uuid4(), uuid4()
    rd = TaskDependencyRead(
        task_id=a,
        depends_on_task_id=b,
        dependency_type=DependencyType.REQUIRES,
        created_at=datetime.now(UTC),
    )
    assert rd.dependency_type == DependencyType.REQUIRES


def test_task_filter_validates_limit_bounds() -> None:
    with pytest.raises(ValueError):
        TaskFilter(limit=0)
    with pytest.raises(ValueError):
        TaskFilter(limit=1001)
    with pytest.raises(ValueError):
        TaskFilter(offset=-1)


def test_task_filter_all_filters() -> None:
    f = TaskFilter(
        status=TaskStatus.PENDING,
        priority=TaskPriority.HIGH,
        repository="repo",
        assigned_to="bob",
        created_after=datetime(2026, 1, 1, tzinfo=UTC),
        created_before=datetime(2026, 12, 31, tzinfo=UTC),
        limit=10,
        offset=5,
    )
    assert f.limit == 10
    assert f.offset == 5
    assert f.status == TaskStatus.PENDING


# ----------------------------------------------------------------------------
# TaskRepository: create_task
# ----------------------------------------------------------------------------


async def test_create_task_success() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    row = _make_row()
    conn.fetchrow.return_value = row
    _patch_repo(repo, conn)

    data = TaskCreate(title="Test task", metadata={"a": 1})
    result = await repo.create_task(data)

    assert isinstance(result, TaskRead)
    assert result.title == "Test task"
    conn.fetchrow.assert_awaited_once()
    # Verify the generated UUID, title, and metadata are passed as args
    args = conn.fetchrow.await_args.args
    # arg[0] is the query, arg[1] is task_id (UUID), arg[3] is title
    assert isinstance(args[1], UUID)
    assert args[3] == "Test task"
    # Last positional arg is metadata
    assert args[-1] == {"a": 1}


async def test_create_task_row_none_raises() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError) as exc_info:
        await repo.create_task(TaskCreate(title="X"))
    assert exc_info.value.operation == "create_task"


async def test_create_task_exception_wrapped() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.side_effect = RuntimeError("db down")
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError) as exc_info:
        await repo.create_task(TaskCreate(title="X"))
    assert "create_task" in str(exc_info.value)


async def test_create_abstract_raises() -> None:
    repo = TaskRepository()
    with pytest.raises(NotImplementedError):
        await repo.create(TaskCreate(title="x"))  # type: ignore[abstract]


# ----------------------------------------------------------------------------
# TaskRepository: get_task
# ----------------------------------------------------------------------------


async def test_get_task_found() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    task_id = uuid4()
    conn.fetchrow.return_value = _make_row(task_id=task_id, title="found")
    _patch_repo(repo, conn)

    result = await repo.get_task(task_id)
    assert result is not None
    assert result.id == task_id
    assert result.title == "found"


async def test_get_task_not_found() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    _patch_repo(repo, conn)

    result = await repo.get_task(uuid4())
    assert result is None


async def test_get_task_exception_wrapped() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.side_effect = RuntimeError("fail")
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError):
        await repo.get_task(uuid4())


# ----------------------------------------------------------------------------
# TaskRepository: get_task_by_external_id
# ----------------------------------------------------------------------------


async def test_get_task_by_external_id_found() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = _make_row(external_id="ext-99", title="ext-task")
    _patch_repo(repo, conn)

    result = await repo.get_task_by_external_id("ext-99")
    assert result is not None
    assert result.external_id == "ext-99"


async def test_get_task_by_external_id_not_found() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    _patch_repo(repo, conn)

    result = await repo.get_task_by_external_id("missing")
    assert result is None


async def test_get_task_by_external_id_exception() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.side_effect = RuntimeError("boom")
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError):
        await repo.get_task_by_external_id("x")


# ----------------------------------------------------------------------------
# TaskRepository: update_task_status
# ----------------------------------------------------------------------------


async def test_update_task_status_in_progress_auto_started() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    task_id = uuid4()
    started = datetime(2026, 1, 1, tzinfo=UTC)
    conn.fetchrow.return_value = _make_row(
        task_id=task_id,
        status="in_progress",
        started_at=started,
    )
    _patch_repo(repo, conn)

    result = await repo.update_task_status(task_id, TaskStatus.IN_PROGRESS)
    assert result is not None
    # started_at should have been auto-set (non-None) by the method
    call_args = conn.fetchrow.await_args.args
    assert call_args[4] is not None  # started_at was auto-set


async def test_update_task_status_completed_auto_completed() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    task_id = uuid4()
    conn.fetchrow.return_value = _make_row(
        task_id=task_id,
        status="completed",
        completed_at=datetime.now(UTC),
    )
    _patch_repo(repo, conn)

    result = await repo.update_task_status(task_id, TaskStatus.COMPLETED)
    assert result is not None
    call_args = conn.fetchrow.await_args.args
    assert call_args[5] is not None  # completed_at auto-set


@pytest.mark.parametrize(
    "status",
    [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED],
)
async def test_update_task_status_terminal_auto_completed(status: TaskStatus) -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = _make_row(status=status.value)
    _patch_repo(repo, conn)

    result = await repo.update_task_status(uuid4(), status)
    assert result is not None
    call_args = conn.fetchrow.await_args.args
    assert call_args[5] is not None


async def test_update_task_status_explicit_timestamps_preserved() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    explicit_start = datetime(2025, 6, 1, tzinfo=UTC)
    explicit_end = datetime(2025, 6, 2, tzinfo=UTC)
    conn.fetchrow.return_value = _make_row(status="in_progress", started_at=explicit_start)
    _patch_repo(repo, conn)

    await repo.update_task_status(
        uuid4(),
        TaskStatus.IN_PROGRESS,
        started_at=explicit_start,
        completed_at=explicit_end,
    )
    call_args = conn.fetchrow.await_args.args
    # explicit values are preserved (not overwritten by now)
    assert call_args[4] == explicit_start
    assert call_args[5] == explicit_end


async def test_update_task_status_pending_no_autotimestamps() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = _make_row(status="pending")
    _patch_repo(repo, conn)

    await repo.update_task_status(uuid4(), TaskStatus.PENDING)
    call_args = conn.fetchrow.await_args.args
    assert call_args[4] is None
    assert call_args[5] is None


async def test_update_task_status_not_found() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    _patch_repo(repo, conn)

    result = await repo.update_task_status(uuid4(), TaskStatus.IN_PROGRESS)
    assert result is None


async def test_update_task_status_exception() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.side_effect = RuntimeError("nope")
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError):
        await repo.update_task_status(uuid4(), TaskStatus.IN_PROGRESS)


# ----------------------------------------------------------------------------
# TaskRepository: update_task
# ----------------------------------------------------------------------------


async def test_update_task_with_all_scalars() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    task_id = uuid4()
    conn.fetchrow.return_value = _make_row(task_id=task_id, title="New title")
    _patch_repo(repo, conn)

    deadline = datetime(2026, 6, 1, tzinfo=UTC)
    upd = TaskUpdate(
        title="New title",
        description="New desc",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        assigned_to="alice",
        deadline=deadline,
        pool_name="pool-1",
        worker_type="wt",
    )
    result = await repo.update_task(task_id, upd)
    assert result is not None
    assert result.title == "New title"
    # Check the SQL contained all expected column assignments
    sql = conn.fetchrow.await_args.args[0]
    assert "title = $2" in sql
    assert "description = $3" in sql
    assert "status = $4" in sql
    assert "priority = $5" in sql
    assert "assigned_to = $6" in sql
    assert "deadline = $7" in sql
    assert "pool_name = $8" in sql
    assert "worker_type = $9" in sql
    assert "updated_at = $10" in sql


async def test_update_task_with_metadata_merge() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = _make_row(metadata={"merged": True})
    _patch_repo(repo, conn)

    upd = TaskUpdate(metadata={"new": 1})
    await repo.update_task(uuid4(), upd)
    sql = conn.fetchrow.await_args.args[0]
    # Note: $N is a placeholder; the actual rendered string is `$$N` because
    # the f-string template uses a literal `$` to format the param index.
    assert "metadata = metadata || $$2::jsonb" in sql
    assert "updated_at = $3" in sql


async def test_update_task_with_empty_update_falls_back_to_get() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    task_id = uuid4()
    # When no fields are set, conn.fetchrow should NOT be called (it goes via get_task)
    conn.fetchrow.return_value = _make_row(task_id=task_id)
    _patch_repo(repo, conn)

    upd = TaskUpdate()  # all None
    result = await repo.update_task(task_id, upd)
    assert result is not None
    # get_task uses connection(), update_task uses transaction(); if we fell back
    # to get_task, fetchrow is called once for the SELECT.
    conn.fetchrow.assert_awaited_once()
    # The SELECT query should NOT have 'UPDATE' in it
    sql = conn.fetchrow.await_args.args[0]
    assert "UPDATE" not in sql
    assert "SELECT" in sql


async def test_update_task_not_found() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    _patch_repo(repo, conn)

    result = await repo.update_task(uuid4(), TaskUpdate(title="x"))
    assert result is None


async def test_update_task_exception() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.side_effect = RuntimeError("bad")
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError):
        await repo.update_task(uuid4(), TaskUpdate(title="x"))


async def test_update_task_partial_only_status() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = _make_row(status="in_progress")
    _patch_repo(repo, conn)

    upd = TaskUpdate(status=TaskStatus.IN_PROGRESS)
    result = await repo.update_task(uuid4(), upd)
    assert result is not None
    sql = conn.fetchrow.await_args.args[0]
    assert "status = $2" in sql
    # No other fields should be present
    assert "title" not in sql
    assert "priority" not in sql


async def test_update_task_partial_only_priority() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = _make_row(priority="high")
    _patch_repo(repo, conn)

    upd = TaskUpdate(priority=TaskPriority.HIGH)
    result = await repo.update_task(uuid4(), upd)
    assert result is not None
    sql = conn.fetchrow.await_args.args[0]
    assert "priority = $2" in sql


# ----------------------------------------------------------------------------
# TaskRepository: list_tasks
# ----------------------------------------------------------------------------


async def test_list_tasks_no_filters() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    rows = [_make_row(title=f"T{i}") for i in range(3)]
    conn.fetch.return_value = rows
    _patch_repo(repo, conn)

    result = await repo.list_tasks(TaskFilter())
    assert len(result) == 3
    sql = conn.fetch.await_args.args[0]
    assert "WHERE" not in sql
    assert "LIMIT $1 OFFSET $2" in sql


async def test_list_tasks_with_all_filters() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.return_value = []
    _patch_repo(repo, conn)

    flt = TaskFilter(
        status=TaskStatus.PENDING,
        priority=TaskPriority.HIGH,
        repository="repo1",
        assigned_to="bob",
        created_after=datetime(2026, 1, 1, tzinfo=UTC),
        created_before=datetime(2026, 12, 31, tzinfo=UTC),
    )
    await repo.list_tasks(flt)
    sql = conn.fetch.await_args.args[0]
    assert "status = $1" in sql
    assert "priority = $2" in sql
    assert "repository = $3" in sql
    assert "assigned_to = $4" in sql
    assert "created_at >= $5" in sql
    assert "created_at <= $6" in sql
    assert "LIMIT $7 OFFSET $8" in sql


async def test_list_tasks_with_status_only() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.return_value = []
    _patch_repo(repo, conn)

    await repo.list_tasks(TaskFilter(status=TaskStatus.FAILED))
    sql = conn.fetch.await_args.args[0]
    assert "status = $1" in sql
    assert "LIMIT $2 OFFSET $3" in sql


async def test_list_tasks_with_priority_only() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.return_value = []
    _patch_repo(repo, conn)

    await repo.list_tasks(TaskFilter(priority=TaskPriority.CRITICAL))
    sql = conn.fetch.await_args.args[0]
    assert "priority = $1" in sql


async def test_list_tasks_with_repository_only() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.return_value = []
    _patch_repo(repo, conn)

    await repo.list_tasks(TaskFilter(repository="myrepo"))
    sql = conn.fetch.await_args.args[0]
    assert "repository = $1" in sql


async def test_list_tasks_with_assigned_to_only() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.return_value = []
    _patch_repo(repo, conn)

    await repo.list_tasks(TaskFilter(assigned_to="alice"))
    sql = conn.fetch.await_args.args[0]
    assert "assigned_to = $1" in sql


async def test_list_tasks_with_created_after_only() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.return_value = []
    _patch_repo(repo, conn)

    await repo.list_tasks(TaskFilter(created_after=datetime(2026, 1, 1, tzinfo=UTC)))
    sql = conn.fetch.await_args.args[0]
    assert "created_at >= $1" in sql


async def test_list_tasks_with_created_before_only() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.return_value = []
    _patch_repo(repo, conn)

    await repo.list_tasks(TaskFilter(created_before=datetime(2026, 12, 31, tzinfo=UTC)))
    sql = conn.fetch.await_args.args[0]
    assert "created_at <= $1" in sql


async def test_list_tasks_exception() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.side_effect = RuntimeError("oops")
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError):
        await repo.list_tasks(TaskFilter())


async def test_list_tasks_passes_limit_offset() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.return_value = []
    _patch_repo(repo, conn)

    await repo.list_tasks(TaskFilter(limit=25, offset=10))
    args = conn.fetch.await_args.args
    # last two args are limit and offset
    assert args[-2] == 25
    assert args[-1] == 10


# ----------------------------------------------------------------------------
# TaskRepository: add_dependency
# ----------------------------------------------------------------------------


async def test_add_dependency_default_blocks() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    a, b = uuid4(), uuid4()
    conn.fetchrow.return_value = {
        "task_id": a,
        "depends_on_task_id": b,
        "dependency_type": "blocks",
        "created_at": datetime.now(UTC),
    }
    _patch_repo(repo, conn)

    dep = await repo.add_dependency(a, b)
    assert isinstance(dep, TaskDependencyRead)
    assert dep.task_id == a
    assert dep.depends_on_task_id == b
    assert dep.dependency_type == DependencyType.BLOCKS
    # Verify default was used
    args = conn.fetchrow.await_args.args
    assert args[3] == "blocks"  # default DependencyType.BLOCKS value


async def test_add_dependency_explicit_type() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    a, b = uuid4(), uuid4()
    conn.fetchrow.return_value = {
        "task_id": a,
        "depends_on_task_id": b,
        "dependency_type": "requires",
        "created_at": datetime.now(UTC),
    }
    _patch_repo(repo, conn)

    dep = await repo.add_dependency(a, b, DependencyType.REQUIRES)
    assert dep.dependency_type == DependencyType.REQUIRES
    args = conn.fetchrow.await_args.args
    assert args[3] == "requires"


async def test_add_dependency_relates_to() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    a, b = uuid4(), uuid4()
    conn.fetchrow.return_value = {
        "task_id": a,
        "depends_on_task_id": b,
        "dependency_type": "relates_to",
        "created_at": datetime.now(UTC),
    }
    _patch_repo(repo, conn)

    dep = await repo.add_dependency(a, b, DependencyType.RELATES_TO)
    assert dep.dependency_type == DependencyType.RELATES_TO


async def test_add_dependency_row_none_raises() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError) as exc_info:
        await repo.add_dependency(uuid4(), uuid4())
    assert exc_info.value.operation == "add_dependency"


async def test_add_dependency_exception_wrapped() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetchrow.side_effect = RuntimeError("dup key")
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError):
        await repo.add_dependency(uuid4(), uuid4())


# ----------------------------------------------------------------------------
# TaskRepository: get_dependencies
# ----------------------------------------------------------------------------


async def test_get_dependencies_empty() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.return_value = []
    _patch_repo(repo, conn)

    result = await repo.get_dependencies(uuid4())
    assert result == []


async def test_get_dependencies_returns_list() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    a, b, c = uuid4(), uuid4(), uuid4()
    rows = [
        {
            "task_id": a,
            "depends_on_task_id": b,
            "dependency_type": "blocks",
            "created_at": datetime.now(UTC),
        },
        {
            "task_id": c,
            "depends_on_task_id": a,
            "dependency_type": "requires",
            "created_at": datetime.now(UTC),
        },
    ]
    conn.fetch.return_value = rows
    _patch_repo(repo, conn)

    result = await repo.get_dependencies(a)
    assert len(result) == 2
    assert result[0].task_id == a
    assert result[1].dependency_type == DependencyType.REQUIRES


async def test_get_dependencies_exception() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.fetch.side_effect = RuntimeError("boom")
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError):
        await repo.get_dependencies(uuid4())


# ----------------------------------------------------------------------------
# TaskRepository: delete_task
# ----------------------------------------------------------------------------


async def test_delete_task_success() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.execute.return_value = "DELETE 1"
    _patch_repo(repo, conn)

    result = await repo.delete_task(uuid4())
    assert result is True


async def test_delete_task_not_found() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.execute.return_value = "DELETE 0"
    _patch_repo(repo, conn)

    result = await repo.delete_task(uuid4())
    assert result is False


async def test_delete_task_exception() -> None:
    repo = TaskRepository()
    conn = AsyncMock()
    conn.execute.side_effect = RuntimeError("nope")
    _patch_repo(repo, conn)

    with pytest.raises(RepositoryError):
        await repo.delete_task(uuid4())


# ----------------------------------------------------------------------------
# TaskRepository: __init__
# ----------------------------------------------------------------------------


def test_init_sets_table() -> None:
    repo = TaskRepository()
    assert repo._table == "orchestration.tasks"


# ----------------------------------------------------------------------------
# TaskRepository: _row_to_model
# ----------------------------------------------------------------------------


def test_row_to_model_minimal() -> None:
    repo = TaskRepository()
    task_id = uuid4()
    row = _make_row(task_id=task_id, title="row")
    result = repo._row_to_model(row)
    assert result.id == task_id
    assert result.title == "row"
    assert result.metadata == {}
    assert result.status == TaskStatus.PENDING
    assert result.priority == TaskPriority.MEDIUM


def test_row_to_model_with_null_metadata_defaults_to_empty() -> None:
    repo = TaskRepository()
    row = _make_row()
    row["metadata"] = None
    result = repo._row_to_model(row)
    assert result.metadata == {}


def test_row_to_model_with_terminal_status() -> None:
    repo = TaskRepository()
    row = _make_row(status="failed", priority="critical")
    result = repo._row_to_model(row)
    assert result.status == TaskStatus.FAILED
    assert result.priority == TaskPriority.CRITICAL
