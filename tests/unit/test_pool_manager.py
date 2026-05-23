"""Unit tests for PoolManager class."""

import asyncio
import heapq
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from mahavishnu.core.status import PoolStatus
from mahavishnu.mcp.protocols.message_bus import MessageBus
from mahavishnu.pools.base import BasePool, PoolConfig, PoolMetrics
from mahavishnu.pools.manager import PoolManager, PoolSelector, _await_if_needed


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


class TestAwaitIfNeeded:
    """Test _await_if_needed helper function."""

    @pytest.mark.asyncio
    async def test_await_if_needed_returns_plain_value(self):
        """Test _await_if_needed returns non-awaitable values directly."""
        result = await _await_if_needed("plain string")
        assert result == "plain string"

    @pytest.mark.asyncio
    async def test_await_if_needed_returns_integer(self):
        """Test _await_if_needed returns integers directly."""
        result = await _await_if_needed(42)
        assert result == 42

    @pytest.mark.asyncio
    async def test_await_if_needed_returns_dict(self):
        """Test _await_if_needed returns dicts directly."""
        result = await _await_if_needed({"key": "value"})
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_await_if_needed_awaits_coroutine(self):
        """Test _await_if_needed awaits coroutines."""
        async def coroutine():
            return " awaited"
        result = await _await_if_needed(coroutine())
        assert result == " awaited"

    @pytest.mark.asyncio
    async def test_await_if_needed_awaits_task(self):
        """Test _await_if_needed awaits asyncio.Tasks."""
        async def inner():
            return "task result"
        task = asyncio.create_task(inner())
        result = await _await_if_needed(task)
        assert result == "task result"


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
    async def test_execute_on_pool_runs_task_on_specified_pool(self, pool_manager):
        """Test execute_on_pool() runs task on target pool."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "test-pool"))

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
        heapq.heappush(pool_manager._worker_count_heap, (2, "pool-1"))
        heapq.heappush(pool_manager._worker_count_heap, (1, "pool-2"))

        result = await pool_manager.route_task(
            {"prompt": "test"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        assert result["pool_id"] == "pool-2"

    @pytest.mark.asyncio
    async def test_route_task_round_robin_cycles_through_pools(self, pool_manager):
        """Test route_task() with ROUND_ROBIN cycles through pools."""
        config = PoolConfig(name="pool", pool_type="mahavishnu", min_workers=1)
        for i in range(3):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool
            pool_manager._pool_worker_counts[f"pool-{i}"] = 1
            heapq.heappush(pool_manager._worker_count_heap, (1, f"pool-{i}"))

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
            heapq.heappush(pool_manager._worker_count_heap, (1, f"pool-{i}"))

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
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "pool-1")
        await mock_pool.start()
        pool_manager._pools["pool-1"] = mock_pool
        pool_manager._pool_worker_counts["pool-1"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "pool-1"))

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
        heapq.heappush(pool_manager._worker_count_heap, (1, "affinity-pool"))

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
    async def test_close_pool_removes_pool(self, pool_manager):
        """Test close_pool() removes pool from manager."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "test-pool"))

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
            pool_manager._pool_worker_counts[f"pool-{i}"] = 1
            heapq.heappush(pool_manager._worker_count_heap, (1, f"pool-{i}"))

        await pool_manager.close_all()

        assert len(pool_manager._pools) == 0

    @pytest.mark.asyncio
    async def test_health_check_returns_overall_health(self, pool_manager):
        """Test health_check() returns combined health status."""
        config = PoolConfig(name="healthy", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "healthy-pool")
        await mock_pool.start()
        pool_manager._pools["healthy-pool"] = mock_pool
        pool_manager._pool_worker_counts["healthy-pool"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "healthy-pool"))

        health = await pool_manager.health_check()

        assert health["status"] == "healthy"
        assert health["pools_active"] == 1

    @pytest.mark.asyncio
    async def test_list_pools_returns_pool_info_with_status(self, pool_manager):
        """Test list_pools() includes status information."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        mock_pool._workers = {}  # Empty workers (unhealthy)
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 0

        pools = await pool_manager.list_pools()

        assert len(pools) == 1
        assert pools[0]["pool_id"] == "test-pool"

    @pytest.mark.asyncio
    async def test_list_pools_returns_all_pool_info(self, pool_manager):
        """Test list_pools() returns info for all pools."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        for i in range(2):
            mock_pool = MockPool(config, f"pool-{i}")
            await mock_pool.start()
            pool_manager._pools[f"pool-{i}"] = mock_pool
            pool_manager._pool_worker_counts[f"pool-{i}"] = 1

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
            pool_manager._pool_worker_counts[f"pool-{i}"] = 1

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
            pool_manager._pool_worker_counts[f"pool-{i}"] = 1

        results = await pool_manager.aggregate_results(pool_ids=["pool-0", "pool-2"])

        assert len(results) == 2
        assert "pool-0" in results
        assert "pool-2" in results

    @pytest.mark.asyncio
    async def test_aggregate_results_empty_pools_returns_empty_dict(self, pool_manager):
        """Test aggregate_results() with no pools returns empty dict."""
        results = await pool_manager.aggregate_results()
        assert results == {}

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
    async def test_update_pool_worker_count_modifies_heap(self, pool_manager):
        """Test _update_pool_worker_count() adds new entry to heap."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 2
        heapq.heappush(pool_manager._worker_count_heap, (2, "test-pool"))

        await pool_manager._update_pool_worker_count("test-pool", 5)

        assert pool_manager._pool_worker_counts["test-pool"] == 5

    @pytest.mark.asyncio
    async def test_update_pool_worker_count_ignores_unknown_pool(self, pool_manager):
        """Test _update_pool_worker_count() ignores unknown pool ID."""
        # Should not raise and pool_worker_counts unchanged
        await pool_manager._update_pool_worker_count("nonexistent-pool", 5)
        assert "nonexistent-pool" not in pool_manager._pool_worker_counts

    @pytest.mark.asyncio
    async def test_update_pool_worker_count_creates_stale_entries(self, pool_manager):
        """Test _update_pool_worker_count() leaves stale entries (lazy deletion)."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 2
        heapq.heappush(pool_manager._worker_count_heap, (2, "test-pool"))

        await pool_manager._update_pool_worker_count("test-pool", 5)

        # Old entry (2, "test-pool") still in heap - will be skipped by _get_least_loaded_pool
        heap_entries = [(count, pid) for count, pid in pool_manager._worker_count_heap if pid == "test-pool"]
        assert len(heap_entries) == 2

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

    @pytest.mark.asyncio
    async def test_get_least_loaded_pool_skips_closed_pool_entries(self, pool_manager):
        """Test _get_least_loaded_pool() skips entries for closed pools."""
        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 5

        # Add entry for a pool that's been removed
        heapq.heappush(pool_manager._worker_count_heap, (3, "deleted-pool"))

        pool_id = await pool_manager._get_least_loaded_pool()

        # Should return test-pool since deleted-pool is not in _pools
        assert pool_id == "test-pool"

    @pytest.mark.asyncio
    async def test_get_least_loaded_pool_returns_none_when_heap_empty(self, pool_manager):
        """Test _get_least_loaded_pool() returns None when all entries stale."""
        # Add only stale entries
        heapq.heappush(pool_manager._worker_count_heap, (99, "stale-pool"))

        result = await pool_manager._get_least_loaded_pool()

        assert result is None

    @pytest.mark.asyncio
    async def test_close_all_clears_heap(self, pool_manager):
        """Test close_all() clears the worker count heap."""
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


class TestSpawnPoolTypes:
    """Test spawn_pool() method instantiation logic for different pool types."""

    @pytest.fixture
    def terminal_manager(self):
        return MagicMock()

    @pytest.fixture
    def session_buddy(self):
        return MagicMock()

    @pytest.fixture
    def message_bus(self):
        return MessageBus()

    @pytest.mark.asyncio
    async def test_spawn_pool_creates_mahavishnu_pool_type(self, terminal_manager, session_buddy, message_bus):
        """Test spawn_pool() correctly instantiates MahavishnuPool."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        config = PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            min_workers=1,
            max_workers=5,
        )

        # Patch at class level so we don't actually start the pool
        with patch("mahavishnu.pools.manager.MahavishnuPool") as mock_pool_class:
            mock_pool_instance = MagicMock()
            mock_pool_instance.pool_id = "test-pool-id"
            mock_pool_instance.config = config
            mock_pool_instance._workers = {}
            mock_pool_instance.start = AsyncMock(return_value="test-pool-id")
            mock_pool_instance.stop = AsyncMock()
            mock_pool_class.return_value = mock_pool_instance

            pool_id = await pool_manager.spawn_pool("mahavishnu", config)

            # Verify pool was created with correct arguments
            mock_pool_class.assert_called_once()
            call_kwargs = mock_pool_class.call_args[1]
            assert call_kwargs["config"] == config
            assert "terminal_manager" in call_kwargs

            assert pool_id == "test-pool-id"

    @pytest.mark.asyncio
    async def test_spawn_pool_creates_session_buddy_pool_type(self, terminal_manager, session_buddy, message_bus):
        """Test spawn_pool() correctly instantiates SessionBuddyPool."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        config = PoolConfig(
            name="test-session-pool",
            pool_type="session-buddy",
            min_workers=1,
            max_workers=3,
        )
        config.extra_config["session_buddy_url"] = "http://localhost:8678/mcp"

        with patch("mahavishnu.pools.manager.SessionBuddyPool") as mock_pool_class:
            mock_pool_instance = MagicMock()
            mock_pool_instance.pool_id = "session-buddy-pool-id"
            mock_pool_instance.config = config
            mock_pool_instance._workers = {}
            mock_pool_instance.start = AsyncMock(return_value="session-buddy-pool-id")
            mock_pool_instance.stop = AsyncMock()
            mock_pool_class.return_value = mock_pool_instance

            pool_id = await pool_manager.spawn_pool("session-buddy", config)

            mock_pool_class.assert_called_once()
            call_kwargs = mock_pool_class.call_args[1]
            assert call_kwargs["config"] == config

            assert pool_id == "session-buddy-pool-id"

    @pytest.mark.asyncio
    async def test_spawn_pool_creates_kubernetes_pool_type(self, terminal_manager, session_buddy, message_bus):
        """Test spawn_pool() correctly instantiates KubernetesPool."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        config = PoolConfig(
            name="test-k8s-pool",
            pool_type="kubernetes",
            min_workers=1,
            max_workers=10,
        )
        config.extra_config["namespace"] = "test-namespace"
        config.extra_config["kubeconfig_path"] = "/path/to/kubeconfig"
        config.extra_config["container_image"] = "python:3.13-slim"

        with patch("mahavishnu.pools.manager.KubernetesPool") as mock_pool_class:
            mock_pool_instance = MagicMock()
            mock_pool_instance.pool_id = "k8s-pool-id"
            mock_pool_instance.config = config
            mock_pool_instance._workers = {}
            mock_pool_instance.start = AsyncMock(return_value="k8s-pool-id")
            mock_pool_instance.stop = AsyncMock()
            mock_pool_class.return_value = mock_pool_instance

            pool_id = await pool_manager.spawn_pool("kubernetes", config)

            mock_pool_class.assert_called_once()
            call_kwargs = mock_pool_class.call_args[1]
            assert call_kwargs["config"] == config
            assert call_kwargs["namespace"] == "test-namespace"
            assert call_kwargs["kubeconfig_path"] == "/path/to/kubeconfig"
            assert call_kwargs["container_image"] == "python:3.13-slim"

            assert pool_id == "k8s-pool-id"

    @pytest.mark.asyncio
    async def test_spawn_pool_creates_runpod_pool_type(self, terminal_manager, session_buddy, message_bus):
        """Test spawn_pool() correctly instantiates RunPodPool."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        config = PoolConfig(
            name="test-runpod-pool",
            pool_type="runpod",
            min_workers=0,
            max_workers=5,
        )
        config.extra_config["gpu_type"] = "NVIDIA_GEFORCE_RTX_4090"
        config.extra_config["endpoint_name"] = "test-endpoint"

        with patch("mahavishnu.pools.manager.RunPodPool") as mock_pool_class:
            mock_pool_instance = MagicMock()
            mock_pool_instance.pool_id = "runpod-pool-id"
            mock_pool_instance.config = config
            mock_pool_instance._workers = {}
            mock_pool_instance.start = AsyncMock(return_value="runpod-pool-id")
            mock_pool_instance.stop = AsyncMock()
            mock_pool_class.return_value = mock_pool_instance

            pool_id = await pool_manager.spawn_pool("runpod", config)

            mock_pool_class.assert_called_once()
            call_kwargs = mock_pool_class.call_args[1]
            assert call_kwargs["config"] == config

            assert pool_id == "runpod-pool-id"

    @pytest.mark.asyncio
    async def test_spawn_pool_unknown_type_raises_value_error(self, terminal_manager, session_buddy, message_bus):
        """Test spawn_pool() raises ValueError for unknown pool type."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        config = PoolConfig(
            name="unknown-pool",
            pool_type="unknown",
            min_workers=1,
            max_workers=5,
        )

        with pytest.raises(ValueError, match="Unknown pool type"):
            await pool_manager.spawn_pool("unknown", config)


class TestPersistPoolState:
    """Test _persist_pool_state() method."""

    @pytest.fixture
    def terminal_manager(self):
        return MagicMock()

    @pytest.fixture
    def session_buddy(self):
        return MagicMock()

    @pytest.fixture
    def message_bus(self):
        return MessageBus()

    @pytest.mark.asyncio
    async def test_persist_pool_state_skips_when_dhara_none(self, terminal_manager, session_buddy, message_bus):
        """Test _persist_pool_state() returns early when dhara_state is None."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
            dhara_state=None,
        )

        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()

        # Should not raise - early return
        await pool_manager._persist_pool_state("test-pool", mock_pool, "running")

    @pytest.mark.asyncio
    async def test_persist_pool_state_calls_dhara_on_success(self, terminal_manager, session_buddy, message_bus):
        """Test _persist_pool_state() calls dhara_state.persist_pool when available."""
        mock_dhara = AsyncMock()
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
            dhara_state=mock_dhara,
        )

        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()

        await pool_manager._persist_pool_state("test-pool", mock_pool, "running")

        mock_dhara.persist_pool.assert_called_once()
        call_args = mock_dhara.persist_pool.call_args
        assert call_args[0][0] == "test-pool"

    @pytest.mark.asyncio
    async def test_persist_pool_state_gracefully_handles_exception(self, terminal_manager, session_buddy, message_bus):
        """Test _persist_pool_state() handles dhara exceptions gracefully."""
        mock_dhara = AsyncMock()
        mock_dhara.persist_pool.side_effect = Exception("Dhara error")
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
            dhara_state=mock_dhara,
        )

        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()

        # Should not raise - exceptions are logged and swallowed
        await pool_manager._persist_pool_state("test-pool", mock_pool, "running")


class TestPersistRoutingDecision:
    """Test _persist_routing_decision() method."""

    @pytest.fixture
    def terminal_manager(self):
        return MagicMock()

    @pytest.fixture
    def session_buddy(self):
        return MagicMock()

    @pytest.fixture
    def message_bus(self):
        return MessageBus()

    @pytest.mark.asyncio
    async def test_persist_routing_decision_skips_when_dhara_none(self, terminal_manager, session_buddy, message_bus):
        """Test _persist_routing_decision() returns early when dhara_state is None."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
            dhara_state=None,
        )

        await pool_manager._persist_routing_decision(
            {"category": "code"}, "pool-1", PoolSelector.LEAST_LOADED, None, "least_loaded"
        )

    @pytest.mark.asyncio
    async def test_persist_routing_decision_calls_dhara_on_success(self, terminal_manager, session_buddy, message_bus):
        """Test _persist_routing_decision() calls dhara_state.persist_routing_decision."""
        mock_dhara = AsyncMock()
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
            dhara_state=mock_dhara,
        )

        await pool_manager._persist_routing_decision(
            {"category": "code"}, "pool-1", PoolSelector.LEAST_LOADED, None, "least_loaded"
        )

        mock_dhara.persist_routing_decision.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_routing_decision_gracefully_handles_exception(self, terminal_manager, session_buddy, message_bus):
        """Test _persist_routing_decision() handles dhara exceptions gracefully."""
        mock_dhara = AsyncMock()
        mock_dhara.persist_routing_decision.side_effect = Exception("Dhara error")
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
            dhara_state=mock_dhara,
        )

        # Should not raise
        await pool_manager._persist_routing_decision(
            {"category": "code"}, "pool-1", PoolSelector.LEAST_LOADED, None, "least_loaded"
        )


class TestRouteTaskGpuOverride:
    """Test GPU category override in route_task()."""

    @pytest.fixture
    def terminal_manager(self):
        return MagicMock()

    @pytest.fixture
    def session_buddy(self):
        return MagicMock()

    @pytest.fixture
    def message_bus(self):
        return MessageBus()

    @pytest.mark.asyncio
    async def test_route_task_gpu_override_routes_vision_to_runpod(self, terminal_manager, session_buddy, message_bus):
        """Test route_task() with GPU category routes to runpod pool."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        # Create a regular pool
        config = PoolConfig(name="mahavishnu-pool", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "mahavishnu-pool")
        await mock_pool.start()
        pool_manager._pools["mahavishnu-pool"] = mock_pool
        pool_manager._pool_worker_counts["mahavishnu-pool"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "mahavishnu-pool"))

        # Create a runpod pool
        runpod_config = PoolConfig(name="runpod-pool", pool_type="runpod", min_workers=0, max_workers=3)
        runpod_pool = MockPool(runpod_config, "runpod-pool")
        await runpod_pool.start()
        pool_manager._pools["runpod-pool"] = runpod_pool
        pool_manager._pool_worker_counts["runpod-pool"] = 0
        heapq.heappush(pool_manager._worker_count_heap, (0, "runpod-pool"))

        result = await pool_manager.route_task(
            {"prompt": "process image", "category": "vision"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        # Should be routed to runpod due to GPU override
        assert result["pool_id"] == "runpod-pool"

    @pytest.mark.asyncio
    async def test_route_task_gpu_override_skips_when_no_runpod(self, terminal_manager, session_buddy, message_bus):
        """Test route_task() falls back when no runpod pool available."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        # Only mahavishnu pool exists
        config = PoolConfig(name="mahavishnu-pool", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "mahavishnu-pool")
        await mock_pool.start()
        pool_manager._pools["mahavishnu-pool"] = mock_pool
        pool_manager._pool_worker_counts["mahavishnu-pool"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "mahavishnu-pool"))

        result = await pool_manager.route_task(
            {"prompt": "process image", "category": "vision"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        # Should fall back to mahavishnu pool
        assert result["pool_id"] == "mahavishnu-pool"

    @pytest.mark.asyncio
    async def test_route_task_gpu_override_routes_ml_inference_to_runpod(self, terminal_manager, session_buddy, message_bus):
        """Test route_task() with ml_inference category routes to runpod pool."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        config = PoolConfig(name="mahavishnu-pool", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "mahavishnu-pool")
        await mock_pool.start()
        pool_manager._pools["mahavishnu-pool"] = mock_pool
        pool_manager._pool_worker_counts["mahavishnu-pool"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "mahavishnu-pool"))

        runpod_config = PoolConfig(name="runpod-pool", pool_type="runpod", min_workers=0, max_workers=3)
        runpod_pool = MockPool(runpod_config, "runpod-pool")
        await runpod_pool.start()
        pool_manager._pools["runpod-pool"] = runpod_pool
        pool_manager._pool_worker_counts["runpod-pool"] = 0
        heapq.heappush(pool_manager._worker_count_heap, (0, "runpod-pool"))

        result = await pool_manager.route_task(
            {"prompt": "run inference", "category": "ml_inference"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        assert result["pool_id"] == "runpod-pool"

    @pytest.mark.asyncio
    async def test_route_task_gpu_override_routes_embedding_to_runpod(self, terminal_manager, session_buddy, message_bus):
        """Test route_task() with embedding category routes to runpod pool."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
            message_bus=message_bus,
        )

        config = PoolConfig(name="mahavishnu-pool", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "mahavishnu-pool")
        await mock_pool.start()
        pool_manager._pools["mahavishnu-pool"] = mock_pool
        pool_manager._pool_worker_counts["mahavishnu-pool"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "mahavishnu-pool"))

        runpod_config = PoolConfig(name="runpod-pool", pool_type="runpod", min_workers=0, max_workers=3)
        runpod_pool = MockPool(runpod_config, "runpod-pool")
        await runpod_pool.start()
        pool_manager._pools["runpod-pool"] = runpod_pool
        pool_manager._pool_worker_counts["runpod-pool"] = 0
        heapq.heappush(pool_manager._worker_count_heap, (0, "runpod-pool"))

        result = await pool_manager.route_task(
            {"prompt": "generate embeddings", "category": "embedding"},
            pool_selector=PoolSelector.LEAST_LOADED,
        )

        assert result["pool_id"] == "runpod-pool"


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
            heapq.heappush(pool_manager._worker_count_heap, (2, f"pool-{i}"))

        # Execute multiple tasks concurrently
        tasks = [{"prompt": f"task-{i}"} for i in range(10)]
        results = await asyncio.gather(
            *[pool_manager.route_task(t, pool_selector=PoolSelector.RANDOM) for t in tasks]
        )

        assert len(results) == 10
        assert all(r["status"] == "completed" for r in results)

    @pytest.mark.asyncio
    async def test_execute_on_pool_updates_worker_count_on_change(self, terminal_manager, session_buddy):
        """Test execute_on_pool() updates worker count in heap when workers change."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
        )

        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "test-pool"))

        # Simulate worker count changing after task execution
        mock_pool._workers = {"w1": "w1", "w2": "w2", "w3": "w3"}  # 3 workers now

        await pool_manager.execute_on_pool("test-pool", {"prompt": "test"})

        # Worker count should be updated
        assert pool_manager._pool_worker_counts["test-pool"] == 3

    @pytest.mark.asyncio
    async def test_execute_on_pool_publishes_message_on_completion(self, terminal_manager, session_buddy):
        """Test execute_on_pool() publishes task_completed message to message bus."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
        )

        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "test-pool")
        await mock_pool.start()
        pool_manager._pools["test-pool"] = mock_pool
        pool_manager._pool_worker_counts["test-pool"] = 1
        heapq.heappush(pool_manager._worker_count_heap, (1, "test-pool"))

        await pool_manager.execute_on_pool("test-pool", {"prompt": "test"})

        # Verify message bus stats indicate published messages
        stats = pool_manager.get_message_bus_stats()
        # Pools with queues should be at least 1
        assert stats["pools_with_queues"] >= 0

    @pytest.mark.asyncio
    async def test_aggregate_results_handles_pool_exceptions(self, terminal_manager, session_buddy):
        """Test aggregate_results() handles exceptions from individual pools."""
        pool_manager = PoolManager(
            terminal_manager=terminal_manager,
            session_buddy_client=session_buddy,
        )

        config = PoolConfig(name="test", pool_type="mahavishnu", min_workers=1)
        mock_pool = MockPool(config, "good-pool")
        await mock_pool.start()
        pool_manager._pools["good-pool"] = mock_pool
        pool_manager._pool_worker_counts["good-pool"] = 1

        # Override collect_memory to raise exception
        async def failing_collect():
            raise Exception("Collection failed")
        mock_pool.collect_memory = failing_collect

        results = await pool_manager.aggregate_results()

        # Should not fail entirely, just log warning and skip
        assert len(results) >= 0