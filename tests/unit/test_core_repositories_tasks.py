"""Unit tests for TaskRepository (mahavishnu.core.repositories.tasks)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from mahavishnu.core.repositories.base import RepositoryError
from mahavishnu.core.repositories.tasks import (
    DependencyType,
    TaskCreate,
    TaskDependencyRead,
    TaskFilter,
    TaskPriority,
    TaskRepository,
    TaskUpdate,
)
from mahavishnu.core.status import TaskStatus

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers and Fixtures
# =============================================================================


VALID_KEY = "x" * 32


def make_repo_row(**overrides):
    """Build a fake database row dict matching the tasks table."""
    base = {
        "id": uuid4(),
        "external_id": None,
        "title": "Test task",
        "description": "Test description",
        "repository": "mahavishnu",
        "pool_name": "default",
        "worker_type": "claude",
        "status": TaskStatus.PENDING.value,
        "priority": TaskPriority.MEDIUM.value,
        "created_by": "alice",
        "assigned_to": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "started_at": None,
        "completed_at": None,
        "deadline": None,
        "metadata": {},
    }
    base.update(overrides)
    return base


class _FakeConn:
    """Async context-manager-friendly fake connection."""

    def __init__(self, fetchrow_result=None, fetch_results=None, execute_result="INSERT 0 1"):
        self._fetchrow_result = fetchrow_result
        self._fetch_results = fetch_results or []
        self._execute_result = execute_result
        self.last_query = None
        self.last_params = None

    async def fetchrow(self, query, *params):
        self.last_query = query
        self.last_params = params
        return self._fetchrow_result

    async def fetch(self, query, *params):
        self.last_query = query
        self.last_params = params
        return self._fetch_results

    async def execute(self, query, *params):
        self.last_query = query
        self.last_params = params
        return self._execute_result


class _FakeTransaction:
    def __init__(self, conn: _FakeConn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, conn: _FakeConn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def patch_repo_connection(repo, conn: _FakeConn) -> None:
    """Patch repo.connection() and repo.transaction() to use a fake conn."""

    @asynccontextmanager
    async def fake_connection():
        yield conn

    @asynccontextmanager
    async def fake_transaction():
        yield conn

    repo.connection = fake_connection  # type: ignore[assignment]
    repo.transaction = fake_transaction  # type: ignore[assignment]


@pytest.fixture
def repo():
    """Build a TaskRepository with patched connection/transaction contexts."""
    return TaskRepository()


@pytest.fixture
def sample_create():
    return TaskCreate(title="Write tests", repository="mahavishnu")


# =============================================================================
# Pydantic Model Tests
# =============================================================================


class TestTaskCreateModel:
    def test_minimal_valid_creation(self):
        task = TaskCreate(title="hello")
        assert task.title == "hello"
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.MEDIUM
        assert task.metadata == {}

    def test_title_length_validation(self):
        with pytest.raises(Exception):
            TaskCreate(title="")
        with pytest.raises(Exception):
            TaskCreate(title="x" * 201)

    def test_status_and_priority_accept_enums(self):
        task = TaskCreate(
            title="x",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.CRITICAL,
        )
        assert task.status == TaskStatus.IN_PROGRESS
        assert task.priority == TaskPriority.CRITICAL

    def test_description_max_length(self):
        with pytest.raises(Exception):
            TaskCreate(title="x", description="d" * 5001)

    def test_deadline_accepts_datetime(self):
        now = datetime.now(UTC)
        task = TaskCreate(title="x", deadline=now)
        assert task.deadline == now


class TestTaskFilterModel:
    def test_default_values(self):
        f = TaskFilter()
        assert f.limit == 50
        assert f.offset == 0
        assert f.status is None

    def test_limit_bounds(self):
        with pytest.raises(Exception):
            TaskFilter(limit=0)
        with pytest.raises(Exception):
            TaskFilter(limit=1001)

    def test_offset_must_be_nonnegative(self):
        with pytest.raises(Exception):
            TaskFilter(offset=-1)


class TestTaskUpdateModel:
    def test_all_optional(self):
        u = TaskUpdate()
        assert u.title is None
        assert u.status is None


class TestDependencyTypeEnum:
    def test_values(self):
        assert DependencyType.BLOCKS.value == "blocks"
        assert DependencyType.REQUIRES.value == "requires"
        assert DependencyType.RELATES_TO.value == "relates_to"


# =============================================================================
# Repository Init
# =============================================================================


class TestTaskRepositoryInit:
    def test_table_set(self, repo):
        assert repo._table == "orchestration.tasks"

    def test_create_not_implemented(self, repo):
        # Abstract method override raises NotImplementedError
        with pytest.raises(NotImplementedError):
            import asyncio

            asyncio.run(repo.create(TaskCreate(title="x")))


# =============================================================================
# create_task
# =============================================================================


class TestCreateTask:
    async def test_create_task_returns_read_model(self, repo, sample_create):
        row = make_repo_row(title="Write tests")
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.create_task(sample_create)

        assert result.title == "Write tests"
        assert result.status == TaskStatus.PENDING
        # INSERT and UPDATE-RETURNING * should be in the query
        assert "INSERT INTO orchestration.tasks" in conn.last_query
        assert "RETURNING *" in conn.last_query

    async def test_create_task_passes_id_and_timestamps(self, repo, sample_create):
        row = make_repo_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.create_task(sample_create)
        params = conn.last_params
        # First param is the generated task_id
        assert params[0] is not None
        # created_at and updated_at are timestamps (0-indexed 11 and 12)
        assert isinstance(params[11], datetime)
        assert isinstance(params[12], datetime)

    async def test_create_task_passes_metadata(self, repo):
        row = make_repo_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)
        data = TaskCreate(title="x", metadata={"foo": "bar"})

        await repo.create_task(data)
        # metadata is the 15th positional value passed to fetchrow (0-indexed: 14)
        assert conn.last_params[14] == {"foo": "bar"}

    async def test_create_task_returns_none_row_raises(self, repo, sample_create):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        with pytest.raises(RepositoryError):
            await repo.create_task(sample_create)

    async def test_create_task_db_error_wrapped(self, repo, sample_create):
        @asynccontextmanager
        async def boom():
            raise RuntimeError("db down")
            yield  # unreachable, satisfies asyncgen-async

        repo.transaction = boom  # type: ignore[assignment]
        with pytest.raises(RepositoryError):
            await repo.create_task(sample_create)


# =============================================================================
# get_task / get_task_by_external_id
# =============================================================================


class TestGetTask:
    async def test_get_task_found(self, repo):
        task_id = uuid4()
        row = make_repo_row(id=task_id, title="found")
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_task(task_id)
        assert result is not None
        assert result.id == task_id
        assert "WHERE id = $1" in conn.last_query

    async def test_get_task_not_found_returns_none(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_task(uuid4())
        assert result is None

    async def test_get_task_by_external_id_found(self, repo):
        row = make_repo_row(external_id="ext-1")
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_task_by_external_id("ext-1")
        assert result is not None
        assert result.external_id == "ext-1"
        assert conn.last_params == ("ext-1",)

    async def test_get_task_by_external_id_not_found(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_task_by_external_id("missing")
        assert result is None


# =============================================================================
# update_task_status
# =============================================================================


class TestUpdateTaskStatus:
    async def test_in_progress_auto_sets_started_at(self, repo):
        task_id = uuid4()
        row = make_repo_row(id=task_id, status=TaskStatus.IN_PROGRESS.value)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.update_task_status(task_id, TaskStatus.IN_PROGRESS)
        assert result is not None
        # started_at is param index 3 (0=id, 1=status, 2=now, 3=started_at)
        assert isinstance(conn.last_params[3], datetime)

    async def test_completed_auto_sets_completed_at(self, repo):
        task_id = uuid4()
        row = make_repo_row(status=TaskStatus.COMPLETED.value)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_task_status(task_id, TaskStatus.COMPLETED)
        # completed_at is param index 4
        assert isinstance(conn.last_params[4], datetime)

    async def test_explicit_started_at_respected(self, repo):
        task_id = uuid4()
        row = make_repo_row(id=task_id)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)
        explicit = datetime(2025, 1, 1, tzinfo=UTC)

        await repo.update_task_status(task_id, TaskStatus.IN_PROGRESS, started_at=explicit)
        assert conn.last_params[3] == explicit

    async def test_status_not_found_returns_none(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.update_task_status(uuid4(), TaskStatus.FAILED)
        assert result is None


# =============================================================================
# update_task
# =============================================================================


class TestUpdateTask:
    async def test_update_no_fields_returns_current(self, repo):
        # With all-None TaskUpdate, repo should return current via get_task
        row = make_repo_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.update_task(uuid4(), TaskUpdate())
        assert result is not None
        # Should have used the SELECT, not an UPDATE
        assert "SELECT" in conn.last_query

    async def test_update_title_field(self, repo):
        row = make_repo_row(title="new")
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)
        task_id = uuid4()

        result = await repo.update_task(task_id, TaskUpdate(title="new"))
        assert result is not None
        # Query should be an UPDATE
        assert "UPDATE" in conn.last_query
        assert "title = $2" in conn.last_query

    async def test_update_status_uses_value_string(self, repo):
        row = make_repo_row(status=TaskStatus.COMPLETED.value)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_task(uuid4(), TaskUpdate(status=TaskStatus.COMPLETED))
        # status param is the enum's string value
        assert TaskStatus.COMPLETED.value in conn.last_params

    async def test_update_metadata_uses_jsonb_merge(self, repo):
        row = make_repo_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_task(uuid4(), TaskUpdate(metadata={"k": "v"}))
        assert "::jsonb" in conn.last_query

    async def test_update_returns_none_when_missing(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.update_task(uuid4(), TaskUpdate(title="x"))
        assert result is None


# =============================================================================
# list_tasks
# =============================================================================


class TestListTasks:
    async def test_list_no_filters(self, repo):
        conn = _FakeConn(fetch_results=[make_repo_row(), make_repo_row()])
        patch_repo_connection(repo, conn)

        result = await repo.list_tasks(TaskFilter())
        assert len(result) == 2
        assert "ORDER BY created_at DESC" in conn.last_query
        assert "LIMIT" in conn.last_query

    async def test_list_with_status_filter(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_tasks(TaskFilter(status=TaskStatus.PENDING))
        assert "status = $1" in conn.last_query

    async def test_list_with_priority_filter(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_tasks(TaskFilter(priority=TaskPriority.HIGH))
        assert "priority = $1" in conn.last_query

    async def test_list_with_repository_filter(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_tasks(TaskFilter(repository="mahavishnu"))
        assert "repository = $1" in conn.last_query
        assert "mahavishnu" in conn.last_params

    async def test_list_with_assigned_to_filter(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_tasks(TaskFilter(assigned_to="bob"))
        assert "assigned_to = $1" in conn.last_query

    async def test_list_with_date_range(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 12, 31, tzinfo=UTC)

        await repo.list_tasks(TaskFilter(created_after=start, created_before=end))
        assert "created_at >= $1" in conn.last_query
        assert "created_at <= $2" in conn.last_query

    async def test_list_with_limit_and_offset(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_tasks(TaskFilter(limit=10, offset=20))
        # last two params should be limit/offset
        params = conn.last_params
        assert params[-2] == 10
        assert params[-1] == 20


# =============================================================================
# add_dependency / get_dependencies
# =============================================================================


class TestDependencies:
    async def test_add_dependency_default_type(self, repo):
        task_id = uuid4()
        depends_on = uuid4()
        dep_row = {
            "task_id": task_id,
            "depends_on_task_id": depends_on,
            "dependency_type": "blocks",
            "created_at": datetime.now(UTC),
        }
        conn = _FakeConn(fetchrow_result=dep_row)
        patch_repo_connection(repo, conn)

        result = await repo.add_dependency(task_id, depends_on)
        assert isinstance(result, TaskDependencyRead)
        assert result.dependency_type == DependencyType.BLOCKS
        assert "INSERT INTO orchestration.task_dependencies" in conn.last_query

    async def test_add_dependency_explicit_type(self, repo):
        dep_row = {
            "task_id": uuid4(),
            "depends_on_task_id": uuid4(),
            "dependency_type": "requires",
            "created_at": datetime.now(UTC),
        }
        conn = _FakeConn(fetchrow_result=dep_row)
        patch_repo_connection(repo, conn)

        result = await repo.add_dependency(uuid4(), uuid4(), DependencyType.REQUIRES)
        assert result.dependency_type == DependencyType.REQUIRES

    async def test_add_dependency_no_row_raises(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        with pytest.raises(RepositoryError):
            await repo.add_dependency(uuid4(), uuid4())

    async def test_get_dependencies_empty(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        result = await repo.get_dependencies(uuid4())
        assert result == []
        assert "FROM orchestration.task_dependencies" in conn.last_query

    async def test_get_dependencies_returns_reads(self, repo):
        dep_row = {
            "task_id": uuid4(),
            "depends_on_task_id": uuid4(),
            "dependency_type": "relates_to",
            "created_at": datetime.now(UTC),
        }
        conn = _FakeConn(fetch_results=[dep_row, dep_row])
        patch_repo_connection(repo, conn)

        result = await repo.get_dependencies(uuid4())
        assert len(result) == 2
        assert all(isinstance(d, TaskDependencyRead) for d in result)
        assert result[0].dependency_type == DependencyType.RELATES_TO


# =============================================================================
# delete_task
# =============================================================================


class TestDeleteTask:
    async def test_delete_task_success(self, repo):
        conn = _FakeConn(execute_result="DELETE 1")
        patch_repo_connection(repo, conn)

        result = await repo.delete_task(uuid4())
        assert result is True

    async def test_delete_task_not_found(self, repo):
        conn = _FakeConn(execute_result="DELETE 0")
        patch_repo_connection(repo, conn)

        result = await repo.delete_task(uuid4())
        assert result is False

    async def test_delete_task_uses_correct_query(self, repo):
        conn = _FakeConn(execute_result="DELETE 1")
        patch_repo_connection(repo, conn)

        await repo.delete_task(uuid4())
        assert "DELETE FROM orchestration.tasks" in conn.last_query
        assert "WHERE id = $1" in conn.last_query


# =============================================================================
# _row_to_model
# =============================================================================


class TestRowToModel:
    def test_row_to_model_defaults_metadata(self, repo):
        row = make_repo_row(metadata=None)
        model = repo._row_to_model(row)
        assert model.metadata == {}

    def test_row_to_model_preserves_fields(self, repo):
        task_id = uuid4()
        external_id = "ext-99"
        row = make_repo_row(
            id=task_id,
            external_id=external_id,
            title="Title",
            status=TaskStatus.FAILED.value,
            priority=TaskPriority.CRITICAL.value,
            metadata={"k": "v"},
        )
        model = repo._row_to_model(row)
        assert model.id == task_id
        assert model.external_id == external_id
        assert model.title == "Title"
        assert model.status == TaskStatus.FAILED
        assert model.priority == TaskPriority.CRITICAL
        assert model.metadata == {"k": "v"}


# =============================================================================
# __all__ exports
# =============================================================================


class TestExports:
    def test_all_exports(self):
        from mahavishnu.core.repositories import tasks as t

        for name in (
            "TaskPriority",
            "DependencyType",
            "TaskCreate",
            "TaskRead",
            "TaskUpdate",
            "TaskDependencyCreate",
            "TaskDependencyRead",
            "TaskFilter",
            "TaskRepository",
        ):
            assert name in t.__all__
