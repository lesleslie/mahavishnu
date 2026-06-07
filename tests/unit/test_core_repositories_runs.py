"""Unit tests for TaskRunRepository (mahavishnu.core.repositories.runs)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from mahavishnu.core.repositories.base import RepositoryError
from mahavishnu.core.repositories.runs import (
    RunStatus,
    TaskRunCreate,
    TaskRunFilter,
    TaskRunRepository,
    TaskRunUpdate,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers and Fixtures
# =============================================================================


def make_run_row(**overrides):
    """Build a fake database row matching the task_runs table."""
    base = {
        "id": uuid4(),
        "task_id": uuid4(),
        "run_number": 1,
        "pool_name": "default",
        "worker_id": "w-1",
        "worker_type": "claude",
        "engine": "prefect",
        "status": RunStatus.PENDING.value,
        "started_at": datetime.now(UTC),
        "finished_at": None,
        "exit_code": None,
        "error_message": None,
        "result_summary": None,
        "metrics": {},
        "metadata": {},
    }
    base.update(overrides)
    return base


class _FakeConn:
    def __init__(
        self,
        fetchrow_result=None,
        fetch_results=None,
        fetchval_result=1,
        execute_result="INSERT 0 1",
    ):
        self._fetchrow_result = fetchrow_result
        self._fetch_results = fetch_results or []
        self._fetchval_result = fetchval_result
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

    async def fetchval(self, query, *params):
        self.last_query = query
        self.last_params = params
        return self._fetchval_result

    async def execute(self, query, *params):
        self.last_query = query
        self.last_params = params
        return self._execute_result


def patch_repo_connection(repo, conn: _FakeConn) -> None:
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
    return TaskRunRepository()


@pytest.fixture
def sample_create():
    task_id = uuid4()
    return TaskRunCreate(task_id=task_id, run_number=1, pool_name="default")


# =============================================================================
# Model Tests
# =============================================================================


class TestRunModels:
    def test_run_create_required_fields(self):
        tid = uuid4()
        c = TaskRunCreate(task_id=tid, run_number=2)
        assert c.task_id == tid
        assert c.run_number == 2
        assert c.status == RunStatus.PENDING
        assert c.metrics == {}
        assert c.metadata == {}

    def test_run_create_run_number_min(self):
        with pytest.raises(Exception):
            TaskRunCreate(task_id=uuid4(), run_number=0)

    def test_run_status_enum_values(self):
        assert RunStatus.PENDING.value == "pending"
        assert RunStatus.RUNNING.value == "running"
        assert RunStatus.COMPLETED.value == "completed"
        assert RunStatus.FAILED.value == "failed"
        assert RunStatus.CANCELLED.value == "cancelled"

    def test_run_filter_default_limit(self):
        f = TaskRunFilter()
        assert f.limit == 50
        assert f.offset == 0

    def test_run_filter_limit_bounds(self):
        with pytest.raises(Exception):
            TaskRunFilter(limit=0)
        with pytest.raises(Exception):
            TaskRunFilter(limit=2000)

    def test_run_update_all_optional(self):
        u = TaskRunUpdate()
        assert u.status is None
        assert u.exit_code is None


# =============================================================================
# Init
# =============================================================================


class TestInit:
    def test_table_set(self, repo):
        assert repo._table == "orchestration.task_runs"

    def test_create_raises_not_implemented(self, repo):
        import asyncio

        with pytest.raises(NotImplementedError):
            asyncio.run(repo.create(TaskRunCreate(task_id=uuid4(), run_number=1)))


# =============================================================================
# create_run
# =============================================================================


class TestCreateRun:
    async def test_create_run_returns_model(self, repo, sample_create):
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.create_run(sample_create)
        assert result.run_number == 1
        assert "INSERT INTO orchestration.task_runs" in conn.last_query
        assert "RETURNING *" in conn.last_query

    async def test_create_run_passes_run_id_and_started_at(self, repo, sample_create):
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.create_run(sample_create)
        params = conn.last_params
        # 0=run_id, 1=task_id, 2=run_number, ..., 8=started_at
        assert params[0] is not None
        assert isinstance(params[8], datetime)

    async def test_create_run_passes_metrics_and_metadata(self, repo):
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)
        c = TaskRunCreate(
            task_id=uuid4(),
            run_number=1,
            metrics={"duration_ms": 100},
            metadata={"trigger": "manual"},
        )

        await repo.create_run(c)
        # metrics at param 9, metadata at 10
        assert conn.last_params[9] == {"duration_ms": 100}
        assert conn.last_params[10] == {"trigger": "manual"}

    async def test_create_run_no_row_raises(self, repo, sample_create):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        with pytest.raises(RepositoryError):
            await repo.create_run(sample_create)


# =============================================================================
# get_run
# =============================================================================


class TestGetRun:
    async def test_get_run_found(self, repo):
        run_id = uuid4()
        row = make_run_row(id=run_id, run_number=5)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_run(run_id)
        assert result is not None
        assert result.id == run_id
        assert result.run_number == 5
        assert "WHERE id = $1" in conn.last_query

    async def test_get_run_not_found(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_run(uuid4())
        assert result is None


# =============================================================================
# update_run
# =============================================================================


class TestUpdateRun:
    async def test_update_no_fields_returns_current(self, repo):
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.update_run(uuid4(), TaskRunUpdate())
        # Empty updates should fall through to get_run, which SELECTs
        assert "SELECT" in conn.last_query
        assert result is not None

    async def test_update_status_field(self, repo):
        row = make_run_row(status="completed")
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.update_run(uuid4(), TaskRunUpdate(status="completed"))
        assert result is not None
        assert "UPDATE" in conn.last_query
        assert "status = $2" in conn.last_query

    async def test_update_metrics_uses_jsonb_merge(self, repo):
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_run(uuid4(), TaskRunUpdate(metrics={"k": "v"}))
        assert "::jsonb" in conn.last_query

    async def test_update_metadata_uses_jsonb_merge(self, repo):
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_run(uuid4(), TaskRunUpdate(metadata={"k": "v"}))
        assert "::jsonb" in conn.last_query

    async def test_update_exit_code(self, repo):
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_run(uuid4(), TaskRunUpdate(exit_code=0))
        assert "exit_code" in conn.last_query

    async def test_update_error_message(self, repo):
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        await repo.update_run(uuid4(), TaskRunUpdate(error_message="boom"))
        assert "error_message" in conn.last_query

    async def test_update_returns_none_when_missing(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.update_run(uuid4(), TaskRunUpdate(status="failed"))
        assert result is None


# =============================================================================
# list_runs_for_task
# =============================================================================


class TestListRunsForTask:
    async def test_list_runs_for_task(self, repo):
        task_id = uuid4()
        rows = [make_run_row(task_id=task_id, run_number=i) for i in (3, 2, 1)]
        conn = _FakeConn(fetch_results=rows)
        patch_repo_connection(repo, conn)

        result = await repo.list_runs_for_task(task_id)
        assert len(result) == 3
        # Should query with task_id, limit, offset
        assert conn.last_params[0] == task_id
        assert "ORDER BY run_number DESC" in conn.last_query

    async def test_list_runs_for_task_empty(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        result = await repo.list_runs_for_task(uuid4())
        assert result == []

    async def test_list_runs_for_task_pagination(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_runs_for_task(uuid4(), limit=10, offset=20)
        assert conn.last_params[1] == 10
        assert conn.last_params[2] == 20


# =============================================================================
# list_runs
# =============================================================================


class TestListRuns:
    async def test_list_no_filters(self, repo):
        conn = _FakeConn(fetch_results=[make_run_row()])
        patch_repo_connection(repo, conn)

        result = await repo.list_runs(TaskRunFilter())
        assert len(result) == 1
        assert "ORDER BY started_at DESC" in conn.last_query

    async def test_list_with_task_id_filter(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        tid = uuid4()

        await repo.list_runs(TaskRunFilter(task_id=tid))
        assert "task_id = $1" in conn.last_query
        assert tid in conn.last_params

    async def test_list_with_status_filter(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_runs(TaskRunFilter(status="running"))
        assert "status = $1" in conn.last_query

    async def test_list_with_pool_filter(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_runs(TaskRunFilter(pool_name="p1"))
        assert "pool_name = $1" in conn.last_query

    async def test_list_with_worker_filter(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_runs(TaskRunFilter(worker_id="w-1"))
        assert "worker_id = $1" in conn.last_query

    async def test_list_with_engine_filter(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        await repo.list_runs(TaskRunFilter(engine="prefect"))
        assert "engine = $1" in conn.last_query

    async def test_list_with_date_range(self, repo):
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 12, 31, tzinfo=UTC)

        await repo.list_runs(TaskRunFilter(started_after=start, started_before=end))
        assert "started_at >= $1" in conn.last_query
        assert "started_at <= $2" in conn.last_query


# =============================================================================
# get_latest_run_for_task
# =============================================================================


class TestGetLatestRunForTask:
    async def test_get_latest_run(self, repo):
        row = make_run_row(run_number=99)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_latest_run_for_task(uuid4())
        assert result is not None
        assert result.run_number == 99
        assert "ORDER BY run_number DESC" in conn.last_query
        assert "LIMIT 1" in conn.last_query

    async def test_get_latest_run_not_found(self, repo):
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_latest_run_for_task(uuid4())
        assert result is None


# =============================================================================
# get_next_run_number
# =============================================================================


class TestGetNextRunNumber:
    async def test_next_run_number_from_value(self, repo):
        conn = _FakeConn(fetchval_result=4)
        patch_repo_connection(repo, conn)

        result = await repo.get_next_run_number(uuid4())
        assert result == 4
        assert "MAX(run_number)" in conn.last_query
        assert "+ 1" in conn.last_query

    async def test_next_run_number_default_when_no_runs(self, repo):
        # fetchval returns None, code should default to 1
        conn = _FakeConn(fetchval_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_next_run_number(uuid4())
        assert result == 1


# =============================================================================
# _row_to_model
# =============================================================================


class TestRowToModel:
    def test_row_to_model_defaults(self, repo):
        row = make_run_row(metrics=None, metadata=None)
        model = repo._row_to_model(row)
        assert model.metrics == {}
        assert model.metadata == {}

    def test_row_to_model_preserves_fields(self, repo):
        run_id = uuid4()
        task_id = uuid4()
        row = make_run_row(
            id=run_id,
            task_id=task_id,
            run_number=7,
            status="failed",
            exit_code=1,
            error_message="err",
            metrics={"k": 1},
            metadata={"k": "v"},
        )
        model = repo._row_to_model(row)
        assert model.id == run_id
        assert model.task_id == task_id
        assert model.run_number == 7
        assert model.status == "failed"
        assert model.exit_code == 1
        assert model.error_message == "err"
        assert model.metrics == {"k": 1}
        assert model.metadata == {"k": "v"}


# =============================================================================
# __all__ exports
# =============================================================================


class TestExports:
    def test_all_exports(self):
        from mahavishnu.core.repositories import runs as r

        for name in (
            "RunStatus",
            "TaskRunCreate",
            "TaskRunRead",
            "TaskRunUpdate",
            "TaskRunFilter",
            "TaskRunRepository",
        ):
            assert name in r.__all__
