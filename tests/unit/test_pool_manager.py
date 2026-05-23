"""Unit tests for PoolManager class."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from mahavishnu.core.status import PoolStatus
from mahavishnu.mcp.protocols.message_bus import MessageBus
from mahavishnu.pools.base import BasePool, PoolConfig, PoolMetrics
from mahavishnu.pools.manager import PoolManager, PoolSelector


class MockPool(BasePool):
    """Mock pool implementation for testing PoolManager."""

    def __init__(self, config: PoolConfig, pool_id: str = "mock-pool"):
        super().__init__(config, pool_id)
        self._start_called = False
        self._stop_called = False
        self._scale_target = None

    async def start(self) -> str:
        self._status = PoolStatus.RUNNING
        self._start_called = True
        self._workers = {f"worker-{i}": f"worker_{i}" for i in range(self.config.min_workers)}
        return self.pool_id

    async def execute_task(self, task: dict) -> dict:
        return {
            "pool_id": self.pool_id,
            "worker_id": "worker-1",
            "status": "completed",
            "output": f"Task: {task.get('prompt', 'unknown')}",
        }

    async def execute_batch(self, tasks: list[dict]) -> dict:
        return {str(i): {"pool_id": self.pool_id, "status": "completed"} for i in range(len(tasks))}

    async def scale(self, target_worker_count: int) -> None:
        self._scale_target = target_worker_count
        self._workers = {f"worker-{i}": f"worker_{i}" for i in range(target_worker_count)}

    async def health_check(self) -> dict:
        healthy = len(self._workers) >= self.config.min_workers
        return {
            "pool_id": self.pool_id,
            "status": "healthy" if healthy else "degraded",
            "workers_active": len(self._workers),
        }

    async def get_metrics(self) -> PoolMetrics:
        return PoolMetrics(
            pool_id=self.pool_id,
            status=self._status,
            active_workers=len(self._workers),
            total_workers=len(self._workers),
        )

    async def collect_memory(self) -> list:
        return [{"content": f"memory from {self.pool_id}", "metadata": {"pool_id": self.pool_id}}]

    async def stop(self) -> None:
        self._status = PoolStatus.STOPPED
        self._stop_called = True
        self._workers.clear()


class TestPoolManager:
    """Test PoolManager multi-pool orchestration."""

    @pytest.fixture
    def terminal_manager(self):
        """Create mock terminal manager."""
        return MagicMock()

    @pytest.fixture
    def session_buddy(self):
        """Create mock session buddy client."""
        return MagicMock()

    @pytest.fixture
    def message_bus(self):
        """Create MessageBus instance."""
        return MessageBus()

    @pytest.fixture
    def pool_manager(self, terminal_manager, session_buddy, message_bus):
        """Create PoolManager instance."""
        return PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

    @pytest.mark.asyncio
    async def test_spawn_pool_creates_mahavishnu_pool(self, pool_manager):
        """Test spawn_pool() creates MahavishnuPool of correct type."""
        config = PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            min_workers=2,
            max_workers=5,
        )

        pool_id = await pool_manager.spawn_pool("mahavishnu", config)

        assert pool_id is not None
        assert pool_id in pool_manager._pools
        assert pool_manager._pools[pool_id].config.pool_type == "mahavishnu"

    @pytest.mark.asyncio
    async def test_spawn_pool_creates_session_buddy_pool(self, pool_manager):
        """Test spawn_pool() creates SessionBuddyPool."""
        config = PoolConfig(
            name="sb-pool",
            pool_type="session-buddy",
            min_workers=1,
            max_workers=3,
        )

        pool_id = await pool_manager.spawn_pool("session-buddy", config)

        assert pool_id is not None
        assert pool_id in pool_manager._pools
        assert pool_manager._pools[pool_id].config.pool_type == "session-buddy"

    @pytest.mark.asyncio
    async def test_spawn_pool_creates_kubernetes_pool(self, pool_manager):
        """Test spawn_pool() creates KubernetesPool."""
        config = PoolConfig(
            name="k8s-pool",
            pool_type="kubernetes",
            min_workers=2,
            max_workers=10,
        )

        pool_id = await pool_manager.spawn_pool("kubernetes", config)

        assert pool_id is not None
        assert pool_id in pool_manager._pools

    @pytest.mark.asyncio
    async def test_spawn_pool_raises_on_unknown_type(self, pool_manager):
        """Test spawn_pool() raises ValueError for unknown pool type."""
        config = PoolConfig(name="unknown", pool_type="unknown")

        with pytest.raises(ValueError, match="Unknown pool type"):
            await pool_manager.spawn_pool("unknown-type", config)

    @pytest.mark.asyncio
    async def test_execute_on_pool_runs_task_on_specified_pool(self, pool_manager):
        """Test execute_on_pool() runs task on target pool."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool

        result = await pool_manager.execute_on_pool(
            "test-pool",
            {"prompt": "Hello"},
        )

        assert result["pool_id"] == "test-pool"
        assert result["status"] == "completed"
        assert "Hello" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_on_pool_raises_for_missing_pool(self, pool_manager):
        """Test execute_on_pool() raises ValueError for unknown pool."""
        with pytest.raises(ValueError, match="Pool not found"):
            await pool_manager.execute_on_pool("nonexistent", {"prompt": "test"})

    @pytest.mark.asyncio
    async def test_route_task_least_loaded_selects_min_workers(self, pool_manager):
        """Test route_task() with LEAST_LOADED selects pool with fewest workers."""
        config1 = PoolConfig(name="pool1", pool_type="mahavishnu", min_workers=1)
        config2 = PoolConfig(name="pool2", pool_type="mahavishnu", min_workers=1)

        mock_pool1 = MockPool(config1, "pool-1")
        await mock_pool1.start()
        mock_pool1._workers = {"w1": "w1", "w2": "w2"}  # 2 workers

        mock_pool2 = MockPool(config2, "pool-2")
        await mock_pool2.start()
        mock_pool2._workers = {"w1": "w1"}  # 1 worker (least loaded)

        pool_manager._pools["pool-1"] = mock_pool1
        pool_manager._pools["pool-2"] = mock_pool2
        pool_manager._pool_worker_counts["pool-1"] = 2
        pool_manager._pool_worker_counts["pool-2"] = 1

        result = await pool_manager.route_task(
            {"prompt": "test"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        assert result["pool_id"] == "pool-2"

    @pytest.mark.asyncio
    async def test_route_task_round_robin_cycles_through_pools(self, pool_manager):
        """Test route_task() with ROUND_ROBIN cycles through pools."""
        config = PoolConfig(name="pool", pool_type="mahavishnu", min_workers=1)
        pools = []
        for i in range(3):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool
            pool_manager._pool_worker_counts[f"pool-{i}"] = 1
            pools.append(mock_pool)

        results = []
        for _ in range(4):
            result = await pool_manager.route_task(
                {"prompt": "test"},
                pool_selector=PoolSelector.ROUND_ROBIN,
            )
            results.append(result["pool_id"])

        # Should cycle: pool-0, pool-1, pool-2, pool-0
        assert results == ["pool-0", "pool-1", "pool-2", "pool-0"]

    @pytest.mark.asyncio
    async def test_route_task_random_selects_random_pool(self, pool_manager):
        """Test route_task() with RANDOM selects randomly."""
        config = PoolConfig(name="pool", pool_type="mahavishnu", min_workers=1)
        for i in range(5):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool
            pool_manager._pool_worker_counts[f"pool-{i}"] = 1

        # Run multiple times to ensure randomness
        results = set()
        for _ in range(20):
            result = await pool_manager.route_task(
                {"prompt": "test"},
                pool_selector=PoolSelector.RANDOM,
            )
            results.add(result["pool_id"])

        # Should select from multiple pools (probability-based)
        assert len(results) > 1

    @pytest.mark.asyncio
    async def test_route_task_affinity_requires_pool_id(self, pool_manager):
        """Test route_task() with AFFINITY requires pool_affinity."""
        pool_manager._pools["pool-1"] = MockPool(
            PoolConfig(name="test", pool_type="mahavishnu", min_workers=1),
            "pool-1",
        )

        with pytest.raises(ValueError, match="pool_affinity required"):
            await pool_manager.route_task(
                {"prompt": "test"},
                pool_selector=PoolSelector.AFFINITY,
            )

    @pytest.mark.asyncio
    async def test_route_task_affinity_routes_to_specific_pool(self, pool_manager):
        """Test route_task() with AFFINITY routes to specified pool."""
        config = PoolConfig(name="affinity-pool", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "affinity-pool")
        await mock_pool.start()
        pool_manager._pools["affinity-pool"] = mock_pool
        pool_manager._pool_worker_counts["affinity-pool"] = 1

        result = await pool_manager.route_task(
            {"prompt": "test"},
            pool_selector=PoolSelector.AFFINITY,
            pool_affinity="affinity-pool",
        )

        assert result["pool_id"] == "affinity-pool"

    @pytest.mark.asyncio
    async def test_route_task_raises_when_no_pools(self, pool_manager):
        """Test route_task() raises RuntimeError when no pools available."""
        with pytest.raises(RuntimeError, match="No pools available"):
            await pool_manager.route_task({"prompt": "test"})

    @pytest.mark.asyncio
    async def test_scale_pool_scales_target_pool(self, pool_manager):
        """Test scale_pool() scales specified pool."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1, max_workers=5)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool

        await pool_manager.scale_pool("test-pool", 3)

        assert mock_pool._scale_target == 3

    @pytest.mark.asyncio
    async def test_scale_pool_raises_for_missing_pool(self, pool_manager):
        """Test scale_pool() raises for unknown pool."""
        with pytest.raises(ValueError, match="Pool not found"):
            await pool_manager.scale_pool("nonexistent", 3)

    @pytest.mark.asyncio
    async def test_close_pool_removes_pool(self, pool_manager):
        """Test close_pool() removes pool from manager."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 1

        await pool_manager.close_pool("test-pool")

        assert "test-pool" not in pool_manager._pools
        assert mock_pool._stop_called is True
        assert "test-pool" not in pool_manager._pool_worker_counts

    @pytest.mark.asyncio
    async def test_close_pool_ignores_nonexistent(self, pool_manager):
        """Test close_pool() ignores unknown pool ID."""
        # Should not raise
        await pool_manager.close_pool("nonexistent")

    @pytest.mark.asyncio
    async def test_close_all_closes_all_pools(self, pool_manager):
        """Test close_all() closes all managed pools."""
        config = PoolConfig(name="pool", pool_type="mahavishnu", min_workers=1)
        for i in range(3):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool

        await pool_manager.close_all()

        assert len(pool_manager._pools) == 0

    @pytest.mark.asyncio
    async def test_health_check_returns_overall_health(self, pool_manager):
        """Test health_check() returns combined health status."""
        config = PoolConfig(name="healthy", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "healthy-pool")
        await mock_pool.start()
        pool_manager._pools["healthy-pool"] = mock_pool

        health = await pool_manager.health_check()

        assert health["status"] == "healthy"
        assert health["pools_active"] == 1

    @pytest.mark.asyncio
    async def test_health_check_degraded_with_unhealthy_pool(self, pool_manager):
        """Test health_check() returns degraded when any pool unhealthy."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "failing-pool")
        await mock_pool.start()
        mock_pool._workers = {}  # No workers = unhealthy
        pool_manager._pools["failing-pool"] = mock_pool

        health = await pool_manager.health_check()

        assert health["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_list_pools_returns_all_pool_info(self, pool_manager):
        """Test list_pools() returns info for all pools."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        for i in range(2):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool

        pools = await pool_manager.list_pools()

        assert len(pools) == 2
        for pool_info in pools:
            assert "pool_id" in pool_info
            assert "pool_type" in pool_info
            assert "status" in pool_info

    @pytest.mark.asyncio
    async def test_aggregate_results_collects_from_all_pools(self, pool_manager):
        """Test aggregate_results() gathers results from all pools."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        for i in range(2):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool

        results = await pool_manager.aggregate_results()

        assert len(results) == 2
        assert "pool-0" in results
        assert "pool-1" in results

    @pytest.mark.asyncio
    async def test_aggregate_results_with_specific_pools(self, pool_manager):
        """Test aggregate_results() with specific pool IDs."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        for i in range(3):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool

        results = await pool_manager.aggregate_results(pool_ids=["pool-0", "pool-2"])

        assert len(results) == 2
        assert "pool-0" in results
        assert "pool-2" in results

    @pytest.mark.asyncio
    async def test_set_pool_selector_changes_default(self, pool_manager):
        """Test set_pool_selector() changes default routing strategy."""
        pool_manager.set_pool_selector(PoolSelector.RANDOM)

        assert pool_manager._pool_selector == PoolSelector.RANDOM

    @pytest.mark.asyncio
    async def test_get_message_bus_stats_returns_stats(self, pool_manager):
        """Test get_message_bus_stats() returns message bus statistics."""
        stats = pool_manager.get_message_bus_stats()

        assert "pools_with_queues" in stats
        assert "queue_sizes" in stats

    @pytest.mark.asyncio
    async def test_least_loaded_routing_uses_heap(self, pool_manager):
        """Test least-loaded routing maintains O(log n) heap structure."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)

        # Add multiple pools with different worker counts
        for i, worker_count in enumerate([5, 3, 7, 1, 4]):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            mock_pool._workers = {f"w{j}": f"w{j}" for j in range(worker_count)}
            pool_manager._pools[f"pool-{i}"] = mock_pool
            pool_manager._pool_worker_counts[f"pool-{i}"] = worker_count
            heapq.heappush(pool_manager._worker_count_heap, (worker_count, f"pool-{i}"))

        # Verify heap structure
        assert len(pool_manager._worker_count_heap) == 5

    @pytest.mark.asyncio
    async def test_update_pool_worker_count_modifies_heap(self, pool_manager):
        """Test _update_pool_worker_count() adds new entry to heap."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 2
        pool_manager._worker_count_heap = [(2, "test-pool")]

        await pool_manager._update_pool_worker_count("test-pool", 5)

        assert pool_manager._pool_worker_counts["test-pool"] == 5

    @pytest.mark.asyncio
    async def test_get_least_loaded_pool_skips_stale_entries(self, pool_manager):
        """Test _get_least_loaded_pool() handles stale heap entries."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 5

        # Add stale entry (old count) and valid entry (current count)
        heapq.heappush(pool_manager._worker_count_heap, (2, "test-pool"))  # stale
        heapq.heappush(pool_manager._worker_count_heap, (5, "test-pool"))  # valid

        pool_id = await pool_manager._get_least_loaded_pool()

        assert pool_id == "test-pool"


class TestPoolSelector:
    """Test PoolSelector enum."""

    def test_pool_selector_values(self):
        """Test PoolSelector enum values."""
        assert PoolSelector.ROUND_ROBIN.value == "round_robin"
        assert PoolSelector.LEAST_LOADED.value == "least_loaded"
        assert PoolSelector.RANDOM.value == "random"
        assert PoolSelector.AFFINITY.value == "affinity"

    def test_pool_selector_count(self):
        """Test PoolSelector has expected number of values."""
        assert len(list(PoolSelector)) == 4


class TestPoolManagerIntegration:
    """Integration tests for PoolManager with concurrent operations."""

    @pytest.fixture
    def terminal_manager(self):
        return MagicMock()

    @pytest.fixture
    def session_buddy(self):
        return MagicMock()

    @pytest.mark.asyncio
    async def test_concurrent_task_execution(self, terminal_manager, session_buddy):
        """Test executing tasks concurrently across pools."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
        )

        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=2)
        for i in range(3):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool
            pool_manager._pool_worker_counts[f"pool-{i}"] = 2

        # Execute multiple tasks concurrently
        tasks = [{"prompt": f"task-{i}"} for i in range(10)]
        results = await asyncio.gather(
            *[pool_manager.route_task(t, pool_selector=PoolSelector.RANDOM) for t in tasks]
        )

        assert len(results) == 10
        assert all(r["status"] == "completed" for r in results)

    @pytest.mark.asyncio
    async def test_close_all_clears_heap(self, terminal_manager, session_buddy):
        """Test close_all() clears the worker count heap."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
        )

        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        for i in range(3):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool
            pool_manager._pool_worker_counts[f"pool-{i}"] = 1
            heapq.heappush(pool_manager._worker_count_heap, (1, f"pool-{i}"))

        await pool_manager.close_all()

        assert len(pool_manager._worker_count_heap) == 0
        assert len(pool_manager._pool_worker_counts) == 0


import heapq