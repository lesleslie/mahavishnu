"""Coverage tests for TaskRunRepository (mahavishnu.core.repositories.runs).

Targets >=80% line+branch coverage by exercising all public methods,
edge cases, and error paths.
"""

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
    TaskRunRead,
    TaskRunRepository,
    TaskRunUpdate,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers and Fakes
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
    ):
        self._fetchrow_result = fetchrow_result
        self._fetch_results = fetch_results or []
        self._fetchval_result = fetchval_result
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
        return "INSERT 0 1"


def patch_repo_connection(repo, conn: _FakeConn) -> None:
    @asynccontextmanager
    async def fake_connection():
        yield conn

    @asynccontextmanager
    async def fake_transaction():
        yield conn

    repo.connection = fake_connection  # type: ignore[assignment]
    repo.transaction = fake_transaction  # type: ignore[assignment]


# =============================================================================
# Model validation
# =============================================================================


class TestRunStatus:
    def test_enum_values(self):
        assert RunStatus.PENDING.value == "pending"
        assert RunStatus.RUNNING.value == "running"
        assert RunStatus.COMPLETED.value == "completed"
        assert RunStatus.FAILED.value == "failed"
        assert RunStatus.CANCELLED.value == "cancelled"


class TestTaskRunCreate:
    def test_minimal_required_fields(self):
        task_id = uuid4()
        data = TaskRunCreate(task_id=task_id, run_number=1)
        assert data.task_id == task_id
        assert data.run_number == 1
        assert data.status == RunStatus.PENDING.value
        assert data.metrics == {}
        assert data.metadata == {}
        assert data.pool_name is None
        assert data.worker_id is None
        assert data.worker_type is None
        assert data.engine is None

    def test_full_fields(self):
        task_id = uuid4()
        data = TaskRunCreate(
            task_id=task_id,
            run_number=2,
            pool_name="pool-1",
            worker_id="w-1",
            worker_type="claude",
            engine="prefect",
            status=RunStatus.RUNNING.value,
            metrics={"x": 1},
            metadata={"y": "z"},
        )
        assert data.pool_name == "pool-1"
        assert data.status == "running"
        assert data.metrics == {"x": 1}

    def test_run_number_must_be_positive(self):
        with pytest.raises(ValueError):
            TaskRunCreate(task_id=uuid4(), run_number=0)


class TestTaskRunUpdate:
    def test_all_optional(self):
        update = TaskRunUpdate()
        assert update.status is None
        assert update.metrics is None

    def test_error_message_max_length(self):
        with pytest.raises(ValueError):
            TaskRunUpdate(error_message="x" * 5001)


class TestTaskRunFilter:
    def test_defaults(self):
        f = TaskRunFilter()
        assert f.limit == 50
        assert f.offset == 0
        assert f.task_id is None

    def test_limit_bounds(self):
        with pytest.raises(ValueError):
            TaskRunFilter(limit=0)
        with pytest.raises(ValueError):
            TaskRunFilter(limit=1001)

    def test_offset_must_be_nonneg(self):
        with pytest.raises(ValueError):
            TaskRunFilter(offset=-1)

    def test_pool_name_max_length(self):
        with pytest.raises(ValueError):
            TaskRunFilter(pool_name="x" * 101)


class TestTaskRunRead:
    def test_required_fields(self):
        with pytest.raises(ValueError):
            TaskRunRead()  # type: ignore[call-arg]


# =============================================================================
# Repository Initialization
# =============================================================================


class TestInit:
    def test_init_sets_table(self):
        repo = TaskRunRepository()
        assert repo._table == "orchestration.task_runs"

    def test_create_method_not_implemented(self):
        repo = TaskRunRepository()
        with pytest.raises(NotImplementedError):
            import asyncio

            asyncio.run(repo.create(TaskRunCreate(task_id=uuid4(), run_number=1)))


# =============================================================================
# create_run
# =============================================================================


class TestCreateRun:
    async def test_creates_run(self):
        repo = TaskRunRepository()
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        data = TaskRunCreate(
            task_id=row["task_id"],
            run_number=1,
            pool_name="pool-1",
        )
        result = await repo.create_run(data)
        assert result.id == row["id"]
        assert result.task_id == row["task_id"]
        assert result.run_number == 1

    async def test_create_run_returns_none_raises(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        with pytest.raises(RepositoryError) as exc:
            await repo.create_run(TaskRunCreate(task_id=uuid4(), run_number=1))
        assert "Failed to create task run" in str(exc.value)

    async def test_create_run_query_error(self):
        repo = TaskRunRepository()

        @asynccontextmanager
        async def boom_txn():
            raise RuntimeError("db down")
            yield  # pragma: no cover

        @asynccontextmanager
        async def ok_conn():
            yield _FakeConn()

        repo.transaction = boom_txn  # type: ignore[assignment]
        repo.connection = ok_conn  # type: ignore[assignment]

        with pytest.raises(RepositoryError) as exc:
            await repo.create_run(TaskRunCreate(task_id=uuid4(), run_number=1))
        assert "create_run" in str(exc.value)


# =============================================================================
# get_run
# =============================================================================


class TestGetRun:
    async def test_returns_run(self):
        repo = TaskRunRepository()
        row = make_run_row()
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_run(row["id"])
        assert result is not None
        assert result.id == row["id"]

    async def test_returns_none_when_not_found(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_run(uuid4())
        assert result is None

    async def test_query_error(self):
        repo = TaskRunRepository()

        @asynccontextmanager
        async def boom():
            raise RuntimeError("nope")
            yield  # pragma: no cover

        repo.connection = boom  # type: ignore[assignment]
        with pytest.raises(RepositoryError):
            await repo.get_run(uuid4())


# =============================================================================
# update_run
# =============================================================================


class TestUpdateRun:
    async def test_updates_scalar_fields(self):
        repo = TaskRunRepository()
        run_id = uuid4()
        row = make_run_row(id=run_id, status="completed", exit_code=0)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        update = TaskRunUpdate(
            status="completed",
            exit_code=0,
            finished_at=datetime.now(UTC),
        )
        result = await repo.update_run(run_id, update)
        assert result is not None
        assert result.status == "completed"

    async def test_update_returns_none(self):
        repo = TaskRunRepository()
        run_id = uuid4()
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        update = TaskRunUpdate(status="completed")
        result = await repo.update_run(run_id, update)
        assert result is None

    async def test_no_updates_returns_existing_run(self):
        repo = TaskRunRepository()
        run_id = uuid4()
        row = make_run_row(id=run_id)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        update = TaskRunUpdate()
        result = await repo.update_run(run_id, update)
        assert result is not None
        assert result.id == run_id

    async def test_metrics_merge(self):
        repo = TaskRunRepository()
        run_id = uuid4()
        row = make_run_row(id=run_id, metrics={"a": 1, "b": 2})
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        update = TaskRunUpdate(metrics={"b": 99, "c": 3})
        await repo.update_run(run_id, update)
        # Verify query mentions the merge operator
        assert "metrics ||" in (conn.last_query or "")

    async def test_metadata_merge(self):
        repo = TaskRunRepository()
        run_id = uuid4()
        row = make_run_row(id=run_id, metadata={"x": 1})
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        update = TaskRunUpdate(metadata={"y": 2})
        await repo.update_run(run_id, update)
        assert "metadata ||" in (conn.last_query or "")

    async def test_all_fields_update(self):
        repo = TaskRunRepository()
        run_id = uuid4()
        row = make_run_row(id=run_id)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        update = TaskRunUpdate(
            status="failed",
            worker_id="w-new",
            finished_at=datetime.now(UTC),
            exit_code=1,
            error_message="boom",
            result_summary="nope",
            metrics={"k": "v"},
            metadata={"k2": "v2"},
        )
        await repo.update_run(run_id, update)
        assert "status" in (conn.last_query or "")
        assert "error_message" in (conn.last_query or "")

    async def test_update_query_error(self):
        repo = TaskRunRepository()

        @asynccontextmanager
        async def boom():
            raise RuntimeError("nope")
            yield  # pragma: no cover

        repo.transaction = boom  # type: ignore[assignment]
        with pytest.raises(RepositoryError):
            await repo.update_run(uuid4(), TaskRunUpdate(status="completed"))


# =============================================================================
# list_runs_for_task
# =============================================================================


class TestListRunsForTask:
    async def test_list_returns_rows(self):
        repo = TaskRunRepository()
        rows = [make_run_row(run_number=3), make_run_row(run_number=2)]
        conn = _FakeConn(fetch_results=rows)
        patch_repo_connection(repo, conn)

        result = await repo.list_runs_for_task(uuid4(), limit=10, offset=0)
        assert len(result) == 2
        assert result[0].run_number == 3

    async def test_list_empty(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        result = await repo.list_runs_for_task(uuid4())
        assert result == []

    async def test_list_query_error(self):
        repo = TaskRunRepository()

        @asynccontextmanager
        async def boom():
            raise RuntimeError("db err")
            yield  # pragma: no cover

        repo.connection = boom  # type: ignore[assignment]
        with pytest.raises(RepositoryError):
            await repo.list_runs_for_task(uuid4())


# =============================================================================
# list_runs (with filters)
# =============================================================================


class TestListRuns:
    async def test_no_filters(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)

        result = await repo.list_runs(TaskRunFilter())
        assert result == []
        # No WHERE clause when no filters
        assert "WHERE" not in (conn.last_query or "")

    async def test_all_filters(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[make_run_row()])
        patch_repo_connection(repo, conn)

        task_id = uuid4()
        filters = TaskRunFilter(
            task_id=task_id,
            status="completed",
            pool_name="pool-x",
            worker_id="w-1",
            engine="prefect",
            started_after=datetime(2024, 1, 1, tzinfo=UTC),
            started_before=datetime(2024, 12, 31, tzinfo=UTC),
            limit=10,
            offset=5,
        )
        await repo.list_runs(filters)
        q = conn.last_query or ""
        assert "task_id =" in q
        assert "status =" in q
        assert "pool_name =" in q
        assert "worker_id =" in q
        assert "engine =" in q
        assert "started_at >=" in q
        assert "started_at <=" in q

    async def test_single_filter_task_id(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        await repo.list_runs(TaskRunFilter(task_id=uuid4()))
        assert "task_id =" in (conn.last_query or "")

    async def test_single_filter_status(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        await repo.list_runs(TaskRunFilter(status="failed"))
        assert "status =" in (conn.last_query or "")

    async def test_filter_pool_name(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        await repo.list_runs(TaskRunFilter(pool_name="p1"))
        assert "pool_name =" in (conn.last_query or "")

    async def test_filter_worker_id(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        await repo.list_runs(TaskRunFilter(worker_id="w1"))
        assert "worker_id =" in (conn.last_query or "")

    async def test_filter_engine(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        await repo.list_runs(TaskRunFilter(engine="prefect"))
        assert "engine =" in (conn.last_query or "")

    async def test_filter_started_after(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        await repo.list_runs(TaskRunFilter(started_after=datetime(2024, 1, 1, tzinfo=UTC)))
        assert "started_at >=" in (conn.last_query or "")

    async def test_filter_started_before(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetch_results=[])
        patch_repo_connection(repo, conn)
        await repo.list_runs(TaskRunFilter(started_before=datetime(2024, 1, 1, tzinfo=UTC)))
        assert "started_at <=" in (conn.last_query or "")

    async def test_list_runs_query_error(self):
        repo = TaskRunRepository()

        @asynccontextmanager
        async def boom():
            raise RuntimeError("err")
            yield  # pragma: no cover

        repo.connection = boom  # type: ignore[assignment]
        with pytest.raises(RepositoryError):
            await repo.list_runs(TaskRunFilter())


# =============================================================================
# get_latest_run_for_task
# =============================================================================


class TestGetLatestRunForTask:
    async def test_returns_latest(self):
        repo = TaskRunRepository()
        row = make_run_row(run_number=99)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_latest_run_for_task(row["task_id"])
        assert result is not None
        assert result.run_number == 99

    async def test_returns_none(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetchrow_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_latest_run_for_task(uuid4())
        assert result is None

    async def test_query_error(self):
        repo = TaskRunRepository()

        @asynccontextmanager
        async def boom():
            raise RuntimeError("nope")
            yield  # pragma: no cover

        repo.connection = boom  # type: ignore[assignment]
        with pytest.raises(RepositoryError):
            await repo.get_latest_run_for_task(uuid4())


# =============================================================================
# get_next_run_number
# =============================================================================


class TestGetNextRunNumber:
    async def test_returns_value(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetchval_result=5)
        patch_repo_connection(repo, conn)

        result = await repo.get_next_run_number(uuid4())
        assert result == 5

    async def test_returns_1_when_none(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetchval_result=None)
        patch_repo_connection(repo, conn)

        result = await repo.get_next_run_number(uuid4())
        assert result == 1

    async def test_returns_1_when_zero(self):
        repo = TaskRunRepository()
        conn = _FakeConn(fetchval_result=0)
        patch_repo_connection(repo, conn)

        result = await repo.get_next_run_number(uuid4())
        assert result == 1

    async def test_query_error(self):
        repo = TaskRunRepository()

        @asynccontextmanager
        async def boom():
            raise RuntimeError("err")
            yield  # pragma: no cover

        repo.connection = boom  # type: ignore[assignment]
        with pytest.raises(RepositoryError):
            await repo.get_next_run_number(uuid4())


# =============================================================================
# _row_to_model edge cases
# =============================================================================


class TestRowToModel:
    async def test_metrics_falsy_falls_back_to_empty(self):
        repo = TaskRunRepository()
        # metrics and metadata set to None — should fall back to {}.
        row = make_run_row(metrics=None, metadata=None)
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_run(row["id"])
        assert result is not None
        assert result.metrics == {}
        assert result.metadata == {}

    async def test_full_row(self):
        repo = TaskRunRepository()
        finished = datetime.now(UTC)
        row = make_run_row(
            status="completed",
            exit_code=0,
            finished_at=finished,
            error_message=None,
            result_summary="ok",
            metrics={"k": 1},
            metadata={"k2": "v"},
        )
        conn = _FakeConn(fetchrow_result=row)
        patch_repo_connection(repo, conn)

        result = await repo.get_run(row["id"])
        assert result is not None
        assert result.finished_at == finished
        assert result.result_summary == "ok"
        assert result.metrics == {"k": 1}
