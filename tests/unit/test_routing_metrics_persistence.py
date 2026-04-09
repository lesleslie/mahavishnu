"""Tests for routing metrics PostgreSQL persistence."""

from __future__ import annotations

import asyncio
import builtins
import runpy
import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.metrics_schema import (
    AdapterStats,
    AdapterType,
    CostTracking,
    ExecutionRecord,
    ExecutionStatus,
    RoutingDecision,
    TaskType,
)
from mahavishnu.core.routing_metrics_persistence import (
    RoutingMetricsPersistence,
    get_routing_metrics_persistence,
    initialize_routing_metrics_persistence,
)


class _FakeAcquire:
    def __init__(self, connection: "_FakeConnection") -> None:
        self._connection = connection

    async def __aenter__(self) -> "_FakeConnection":
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001,ANN201,ANN202
        return None


class _FakeConnection:
    def __init__(self, pool: "_FakePool") -> None:
        self.pool = pool

    async def executemany(self, query: str, values: list[tuple[object, ...]]) -> None:
        q = query.lower()
        if "metrics.execution_records" in q:
            for value in values:
                row = {
                    "execution_id": value[0],
                    "adapter": value[1],
                    "task_type": value[2],
                    "start_timestamp": value[3],
                    "end_timestamp": value[4],
                    "status": value[5],
                    "latency_ms": value[6],
                    "error_type": value[7],
                    "error_message": value[8],
                    "cost_usd": value[9],
                    "metadata": value[10],
                }
                self.pool.execution_records[row["execution_id"]] = row
        elif "metrics.routing_decisions" in q:
            self.pool.routing_decisions.extend(values)
        elif "metrics.cost_tracking" in q:
            self.pool.cost_records.extend(values)

    async def execute(self, query: str, *params: object) -> None:
        q = query.lower()
        if "metrics.adapter_stats" in q:
            row = {
                "adapter": params[0],
                "stat_date": params[1],
                "success_rate": params[2],
                "total_executions": params[3],
                "avg_latency_ms": params[4],
                "p50_latency_ms": params[5],
                "p95_latency_ms": params[6],
                "p99_latency_ms": params[7],
                "error_counts": params[8],
                "cost_total_usd": params[9],
                "uptime_percentage": params[10],
                "sample_size": params[11],
                "confidence_interval": params[12],
            }
            self.pool.adapter_stats[(row["adapter"], row["stat_date"])] = row

    async def fetchrow(self, query: str, execution_id: str) -> dict[str, object] | None:
        if "metrics.execution_records" in query.lower():
            return self.pool.execution_records.get(execution_id)
        return None

    async def fetch(self, query: str, *params: object) -> list[dict[str, object]]:
        q = query.lower()
        if "metrics.execution_records" in q:
            adapter = params[0]
            task_type = params[1]
            limit = int(params[2])
            rows = [
                row
                for row in self.pool.execution_records.values()
                if (adapter is None or row["adapter"] == adapter)
                and (task_type is None or row["task_type"] == task_type)
            ]
            rows.sort(key=lambda row: row["start_timestamp"], reverse=True)
            return rows[:limit]

        if "metrics.adapter_stats" in q:
            adapter = params[0]
            rows = [
                row
                for (stored_adapter, _date), row in self.pool.adapter_stats.items()
                if stored_adapter == adapter
            ]
            rows.sort(key=lambda row: row["stat_date"], reverse=True)
            return rows

        return []

    async def fetchval(self, query: str) -> int:
        return 1 if query.strip().lower() == "select 1" else 0


class _FakePool:
    def __init__(self) -> None:
        self.execution_records: dict[str, dict[str, object]] = {}
        self.adapter_stats: dict[tuple[object, object], dict[str, object]] = {}
        self.routing_decisions: list[tuple[object, ...]] = []
        self.cost_records: list[tuple[object, ...]] = []
        self.closed = False

    def acquire(self) -> _FakeAcquire:
        return _FakeAcquire(_FakeConnection(self))

    def get_size(self) -> int:
        return 2

    def get_idle_size(self) -> int:
        return 1

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_pool() -> _FakePool:
    return _FakePool()


@pytest.fixture(autouse=True)
def mock_create_pool(monkeypatch: pytest.MonkeyPatch, fake_pool: _FakePool) -> None:
    monkeypatch.setattr(
        "mahavishnu.core.routing_metrics_persistence.asyncpg.create_pool",
        AsyncMock(return_value=fake_pool),
    )


@pytest.fixture
def persistence() -> RoutingMetricsPersistence:
    return RoutingMetricsPersistence(dsn="postgresql://les@localhost/mahavishnu")


class TestRoutingMetricsPersistence:
    """Test suite for RoutingMetricsPersistence."""

    @pytest.mark.asyncio
    async def test_initialize_and_close(self, persistence: RoutingMetricsPersistence) -> None:
        """Test initialization and cleanup."""
        await persistence.initialize()
        assert persistence._pool is not None

        # Idempotent initialize path
        await persistence.initialize()
        assert persistence._pool is not None

        health = await persistence.health_check()
        assert health["status"] == "healthy"
        assert health["pool_size"] == 2
        assert health["pool_idle"] == 1

        await persistence.close()
        assert persistence._pool is None

    @pytest.mark.asyncio
    async def test_write_and_get_execution(self, persistence: RoutingMetricsPersistence) -> None:
        """Test writing and retrieving execution records."""
        await persistence.initialize()

        record = ExecutionRecord(
            execution_id="test-exec-001",
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            start_timestamp=datetime.now(UTC).timestamp(),
            end_timestamp=datetime.now(UTC).timestamp(),
            status=ExecutionStatus.SUCCESS,
            latency_ms=150,
            metadata={"test": True},
        )

        await persistence.write_execution(record)
        await persistence._flush_executions()

        retrieved = await persistence.get_execution("test-exec-001")
        assert retrieved is not None
        assert retrieved.execution_id == "test-exec-001"
        assert retrieved.adapter == AdapterType.AGNO
        assert retrieved.task_type == TaskType.AI_TASK
        assert retrieved.status == ExecutionStatus.SUCCESS
        assert retrieved.latency_ms == 150
        assert retrieved.metadata == {"test": True}

        await persistence.close()

    @pytest.mark.asyncio
    async def test_write_adapter_stats(self, persistence: RoutingMetricsPersistence) -> None:
        """Test writing adapter statistics."""
        await persistence.initialize()

        stats = AdapterStats(
            adapter=AdapterType.PREFECT,
            date="2026-04-02",
            success_rate=0.95,
            total_executions=100,
            avg_latency_ms=200.5,
            sample_size=100,
        )

        await persistence.write_adapter_stats(stats)
        retrieved = await persistence.get_adapter_stats(AdapterType.PREFECT, days=1)

        assert len(retrieved) == 1
        assert retrieved[0].adapter == AdapterType.PREFECT
        assert abs(retrieved[0].success_rate - 0.95) < 0.01
        assert retrieved[0].total_executions == 100

        await persistence.close()

    @pytest.mark.asyncio
    async def test_write_routing_decision_and_cost_tracking(self, persistence: RoutingMetricsPersistence) -> None:
        """Test writing routing decisions and cost tracking records."""
        await persistence.initialize()

        decision = RoutingDecision(
            decision_id="test-decision-001",
            task_type=TaskType.RAG_QUERY,
            selected_adapter=AdapterType.LLAMAINDEX,
            alternative_adapters=[AdapterType.AGNO],
            reasoning="LlamaIndex best for RAG queries",
            adapter_scores={
                AdapterType.LLAMAINDEX: 0.9,
                AdapterType.AGNO: 0.7,
            },
        )
        await persistence.write_routing_decision(decision)
        await persistence._flush_decisions()

        cost = CostTracking(
            execution_id="test-exec-002",
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            cost_usd=0.05,
            budget_type="daily",
            budget_limit_usd=10.0,
        )
        await persistence.write_cost(cost)
        await persistence._flush_costs()

        await persistence.close()

    @pytest.mark.asyncio
    async def test_batch_write_interface(self, persistence: RoutingMetricsPersistence) -> None:
        """Test ExecutionTracker-compatible batch_write interface."""
        await persistence.initialize()

        records = [
            ExecutionRecord(
                execution_id=f"batch-test-{i}",
                adapter=AdapterType.AGNO,
                task_type=TaskType.AI_TASK,
                start_timestamp=datetime.now(UTC).timestamp(),
                status=ExecutionStatus.SUCCESS,
                latency_ms=100 + i,
            )
            for i in range(10)
        ]

        result = await persistence.batch_write(records)
        assert result["status"] == "success"
        assert result["written"] == 10

        await persistence.close()

    @pytest.mark.asyncio
    async def test_get_recent_executions(self, persistence: RoutingMetricsPersistence) -> None:
        """Test retrieving recent execution records."""
        await persistence.initialize()

        for i in range(5):
            record = ExecutionRecord(
                execution_id=f"recent-test-{i}",
                adapter=AdapterType.PREFECT,
                task_type=TaskType.WORKFLOW,
                start_timestamp=datetime.now(UTC).timestamp() + i,
                status=ExecutionStatus.SUCCESS,
                latency_ms=100,
            )
            await persistence.write_execution(record)

        await persistence._flush_executions()
        recent = await persistence.get_recent_executions(adapter=AdapterType.PREFECT, limit=10)

        assert len(recent) == 5
        assert recent[0].execution_id.startswith("recent-test-")

        await persistence.close()

    @pytest.mark.asyncio
    async def test_initialize_idempotent_and_flush_failures(
        self,
        persistence: RoutingMetricsPersistence,
        fake_pool: _FakePool,
    ) -> None:
        """Test idempotent initialization and requeue on flush failures."""
        await persistence.initialize()
        await persistence.initialize()

        record = ExecutionRecord(
            execution_id="fail-exec",
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            start_timestamp=datetime.now(UTC).timestamp(),
            status=ExecutionStatus.SUCCESS,
            latency_ms=10,
        )
        persistence._pending_executions.append(record)

        bad_conn = AsyncMock()
        bad_conn.executemany = AsyncMock(side_effect=RuntimeError("boom"))
        bad_acquire = MagicMock()
        bad_acquire.__aenter__ = AsyncMock(return_value=bad_conn)
        bad_acquire.__aexit__ = AsyncMock(return_value=None)
        persistence._pool.acquire = MagicMock(return_value=bad_acquire)  # type: ignore[method-assign]

        assert await persistence._flush_executions() == 0
        assert persistence._pending_executions

        persistence._pool = _FakePool()
        persistence._pending_costs.append(
            CostTracking(
                execution_id="cost-exec",
                adapter=AdapterType.AGNO,
                task_type=TaskType.AI_TASK,
                cost_usd=0.01,
                budget_type="daily",
            )
        )
        assert await persistence._flush_costs() == 1

        persistence._pending_decisions.append(
            RoutingDecision(
                decision_id="decision-1",
                task_type=TaskType.WORKFLOW,
                selected_adapter=AdapterType.PREFECT,
                alternative_adapters=[],
                reasoning="x",
                adapter_scores={AdapterType.PREFECT: 1.0},
            )
        )
        assert await persistence._flush_decisions() == 1

        await persistence.close()

    @pytest.mark.asyncio
    async def test_uninitialized_write_and_flush_branches(self) -> None:
        """Test write and flush branches that should no-op without a pool."""
        persistence = RoutingMetricsPersistence(dsn="postgresql://les@localhost/mahavishnu", batch_size=1)

        record = ExecutionRecord(
            execution_id="no-pool",
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            start_timestamp=datetime.now(UTC).timestamp(),
            status=ExecutionStatus.SUCCESS,
            latency_ms=1,
        )
        stats = AdapterStats(
            adapter=AdapterType.PREFECT,
            date="2026-04-02",
            success_rate=0.95,
            total_executions=1,
            sample_size=1,
        )
        decision = RoutingDecision(
            decision_id="decision-no-pool",
            task_type=TaskType.WORKFLOW,
            selected_adapter=AdapterType.PREFECT,
            alternative_adapters=[],
            reasoning="test",
            adapter_scores={AdapterType.PREFECT: 1.0},
        )
        cost = CostTracking(
            execution_id="cost-no-pool",
            adapter=AdapterType.AGNO,
            task_type=TaskType.AI_TASK,
            cost_usd=0.01,
            budget_type="daily",
        )

        await persistence.write_execution(record)
        await persistence.write_executions_batch([record])
        await persistence.write_adapter_stats(stats)
        await persistence.write_routing_decision(decision)
        await persistence.write_cost(cost)
        assert await persistence._flush_all_pending() is None

    @pytest.mark.asyncio
    async def test_periodic_flush_exception_branch(self, persistence: RoutingMetricsPersistence, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test the periodic flush loop error branch."""
        persistence = RoutingMetricsPersistence(dsn="postgresql://les@localhost/mahavishnu")

        calls = {"sleep": 0, "flush": 0}

        async def fake_sleep(_delay: float) -> None:
            calls["sleep"] += 1
            persistence._shutdown_event.set()

        async def fake_flush() -> None:
            calls["flush"] += 1
            raise RuntimeError("boom")

        monkeypatch.setattr("mahavishnu.core.routing_metrics_persistence.asyncio.sleep", fake_sleep)
        monkeypatch.setattr(persistence, "_flush_all_pending", fake_flush)

        await persistence._periodic_flush()
        assert calls["sleep"] == 1
        assert calls["flush"] == 1

    @pytest.mark.asyncio
    async def test_periodic_flush_cancelled_branch(self) -> None:
        """Test the periodic flush loop cancellation branch."""
        persistence = RoutingMetricsPersistence(dsn="postgresql://les@localhost/mahavishnu")

        started = asyncio.Event()

        async def fake_sleep(_delay: float) -> None:
            started.set()
            await asyncio.Future()

        original_sleep = asyncio.sleep
        try:
            asyncio.sleep = fake_sleep  # type: ignore[assignment]
            task = asyncio.create_task(persistence._periodic_flush())
            await started.wait()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        finally:
            asyncio.sleep = original_sleep  # type: ignore[assignment]

    @pytest.mark.asyncio
    async def test_not_initialized_branches_and_global_helpers(self) -> None:
        """Test branches that run before initialization plus global helper paths."""
        persistence = RoutingMetricsPersistence(dsn="postgresql://les@localhost/mahavishnu")
        assert await persistence.get_execution("missing") is None
        assert await persistence.get_recent_executions() == []
        assert await persistence.get_adapter_stats(AdapterType.PREFECT) == []
        assert (await persistence.health_check())["status"] == "unhealthy"

        module = sys.modules["mahavishnu.core.routing_metrics_persistence"]
        module._persistence = None

        created = await initialize_routing_metrics_persistence("postgresql://test", batch_size=3)
        assert get_routing_metrics_persistence() is created

        recreated = await initialize_routing_metrics_persistence(
            "postgresql://test",
            batch_size=3,
            force_recreate=True,
        )
        assert recreated is get_routing_metrics_persistence()
        await recreated.close()
        module._persistence = None

    @pytest.mark.asyncio
    async def test_broken_connection_error_branches(
        self,
        persistence: RoutingMetricsPersistence,
    ) -> None:
        """Test error handling for database operations."""
        await persistence.initialize()

        none_conn = AsyncMock()
        none_conn.fetchrow = AsyncMock(return_value=None)
        none_acquire = MagicMock()
        none_acquire.__aenter__ = AsyncMock(return_value=none_conn)
        none_acquire.__aexit__ = AsyncMock(return_value=None)
        persistence._pool.acquire = MagicMock(return_value=none_acquire)  # type: ignore[method-assign]
        assert await persistence.get_execution("missing") is None

        bad_conn = AsyncMock()
        bad_conn.fetchrow = AsyncMock(side_effect=RuntimeError("fetchrow boom"))
        bad_conn.fetch = AsyncMock(side_effect=RuntimeError("fetch boom"))
        bad_conn.execute = AsyncMock(side_effect=RuntimeError("execute boom"))
        bad_conn.fetchval = AsyncMock(side_effect=RuntimeError("health boom"))
        bad_conn.executemany = AsyncMock(side_effect=RuntimeError("batch boom"))

        bad_acquire = MagicMock()
        bad_acquire.__aenter__ = AsyncMock(return_value=bad_conn)
        bad_acquire.__aexit__ = AsyncMock(return_value=None)
        persistence._pool.acquire = MagicMock(return_value=bad_acquire)  # type: ignore[method-assign]

        assert await persistence.get_execution("missing") is None
        assert await persistence.get_recent_executions(adapter=AdapterType.PREFECT) == []
        assert await persistence.get_adapter_stats(AdapterType.PREFECT) == []

        await persistence.write_adapter_stats(
            AdapterStats(
                adapter=AdapterType.PREFECT,
                date="2026-04-02",
                success_rate=0.5,
                total_executions=1,
                sample_size=1,
            )
        )

        persistence._pending_executions.append(
            ExecutionRecord(
                execution_id="boom-exec",
                adapter=AdapterType.AGNO,
                task_type=TaskType.AI_TASK,
                start_timestamp=datetime.now(UTC).timestamp(),
                status=ExecutionStatus.SUCCESS,
                latency_ms=1,
            )
        )
        assert await persistence._flush_executions() == 0

        persistence._pending_decisions.append(
            RoutingDecision(
                decision_id="boom-decision",
                task_type=TaskType.WORKFLOW,
                selected_adapter=AdapterType.PREFECT,
                alternative_adapters=[],
                reasoning="boom",
                adapter_scores={AdapterType.PREFECT: 1.0},
            )
        )
        assert await persistence._flush_decisions() == 0

        persistence._pending_costs.append(
            CostTracking(
                execution_id="boom-cost",
                adapter=AdapterType.AGNO,
                task_type=TaskType.AI_TASK,
                cost_usd=0.01,
                budget_type="daily",
            )
        )
        assert await persistence._flush_costs() == 0

        assert (await persistence.health_check())["status"] == "unhealthy"

        await persistence.close()

    def test_import_error_branch_raises_without_asyncpg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test asyncpg import fallback and constructor guard."""
        original_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001,ANN002,ANN003
            if name == "asyncpg":
                raise ImportError("asyncpg unavailable")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", guarded_import)
        for module_name in [name for name in sys.modules if name == "asyncpg" or name.startswith("asyncpg.")]:
            monkeypatch.delitem(sys.modules, module_name, raising=False)

        namespace = runpy.run_module(
            "mahavishnu.core.routing_metrics_persistence",
            run_name="__routing_metrics_persistence_fallback__",
        )
        assert namespace["asyncpg"] is None

        with pytest.raises(ImportError):
            namespace["RoutingMetricsPersistence"](dsn="postgresql://test")


# Test fixture for PostgreSQL DSN
@pytest.fixture
def test_postgres_dsn() -> str:
    """Provide test PostgreSQL DSN."""
    return "postgresql://les@localhost/mahavishnu"
