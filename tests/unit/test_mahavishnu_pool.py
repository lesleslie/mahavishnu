"""Unit tests for MahavishnuPool class."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from mahavishnu.core.status import PoolStatus, WorkerStatus
from mahavishnu.pools.mahavishnu_pool import MahavishnuPool
from mahavishnu.pools.base import PoolConfig
from mahavishnu.workers.base import WorkerResult


class TestMahavishnuPool:
    """Test MahavishnuPool direct worker management."""

    @pytest.fixture
    def mock_terminal_manager(self):
        """Create a mock TerminalManager."""
        return MagicMock()

    @pytest.fixture
    def pool_config(self):
        """Create a test PoolConfig."""
        return PoolConfig(
            name="test-pool",
            pool_type="mahavishnu",
            min_workers=2,
            max_workers=5,
            worker_type="terminal-claude",
        )

    @pytest.fixture
       def mock_worker_manager(self):
        """Create a mock WorkerManager."""
        mock = MagicMock()
        mock.spawn_workers = AsyncMock(return_value=["worker-1", "worker-2"])
        mock.execute_task = AsyncMock()
        mock.execute_batch = AsyncMock()
        mock.close_worker = AsyncMock()
        mock.close_all = AsyncMock()
        mock.collect_results = AsyncMock()
        mock.health_check = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_start_raises_when_no_terminal_manager(self, pool_config):
        """Test start() raises RuntimeError when terminal_manager is None."""
        pool = MahavishnuPool(
            config=pool_config,
            terminal_manager=None,
        )

        with pytest.raises(RuntimeError, match="terminal_manager is not available"):
            await pool.start()

        assert pool._status == PoolStatus.FAILED

    @pytest.mark.asyncio
    async def test_start_spawns_min_workers(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test start() spawns min_workers workers."""
        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )

            pool_id = await pool.start()

            assert pool_id == pool.pool_id
            assert pool._status == PoolStatus.RUNNING
            mock_worker_manager.spawn_workers.assert_called_once_with(
                worker_type="terminal-claude",
                count=2,
            )
            assert len(pool._workers) == 2

    @pytest.mark.asyncio
    async def test_execute_task_uses_first_available_worker(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test execute_task() selects first available worker."""
        mock_result = WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.COMPLETED,
            output="test output",
            error=None,
            exit_code=0,
            duration_seconds=1.5,
        )
        mock_worker_manager.execute_task.return_value = mock_result

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            result = await pool.execute_task({"prompt": "test task"})

            assert result["pool_id"] == pool.pool_id
            assert result["worker_id"] == "worker-1"
            assert result["status"] == "completed"
            assert result["output"] == "test output"
            assert "duration" in result

    @pytest.mark.asyncio
    async def test_execute_task_tracks_stats_on_success(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test execute_task() increments tasks_completed on success."""
        mock_result = WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.COMPLETED,
            output="output",
            error=None,
            exit_code=0,
            duration_seconds=1.0,
        )
        mock_worker_manager.execute_task.return_value = mock_result

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            await pool.execute_task({"prompt": "task1"})
            await pool.execute_task({"prompt": "task2"})

            assert pool._tasks_completed == 2
            assert pool._tasks_failed == 0

    @pytest.mark.asyncio
    async def test_execute_task_tracks_stats_on_failure(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test execute_task() increments tasks_failed on failure."""
        mock_result = WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.FAILED,
            output=None,
            error="task failed",
            exit_code=1,
            duration_seconds=1.0,
        )
        mock_worker_manager.execute_task.return_value = mock_result

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            await pool.execute_task({"prompt": "failing task"})

            assert pool._tasks_failed == 1
            assert pool._tasks_completed == 0

    @pytest.mark.asyncio
    async def test_execute_task_raises_when_no_workers(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test execute_task() raises when no workers available."""
        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            # Don't start pool, workers dict is empty

            with pytest.raises(RuntimeError, match="No workers available"):
                await pool.execute_task({"prompt": "test"})

    @pytest.mark.asyncio
    async def test_execute_batch_round_robin(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test execute_batch() distributes tasks round-robin."""
        mock_results = {
            "worker-1": WorkerResult(
                worker_id="worker-1",
                status=WorkerStatus.COMPLETED,
                output="result1",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
            ),
            "worker-2": WorkerResult(
                worker_id="worker-2",
                status=WorkerStatus.COMPLETED,
                output="result2",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
            ),
        }
        mock_worker_manager.execute_batch.return_value = mock_results

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            tasks = [{"prompt": f"task-{i}"} for i in range(4)]
            results = await pool.execute_batch(tasks)

            # 4 tasks distributed round-robin across 2 workers
            assert len(results) == 4

    @pytest.mark.asyncio
    async def test_execute_batch_tracks_stats(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test execute_batch() tracks task statistics."""
        mock_results = {
            "worker-1": WorkerResult(
                worker_id="worker-1",
                status=WorkerStatus.COMPLETED,
                output="result1",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
            ),
            "worker-2": WorkerResult(
                worker_id="worker-2",
                status=WorkerStatus.COMPLETED,
                output="result2",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
            ),
        }
        mock_worker_manager.execute_batch.return_value = mock_results

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            tasks = [{"prompt": "task1"}, {"prompt": "task2"}]
            await pool.execute_batch(tasks)

            # Each task in batch increases stats
            assert pool._tasks_completed == 2

    @pytest.mark.asyncio
    async def test_scale_up_spawns_new_workers(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test scale() increases worker count within bounds."""
        mock_worker_manager.spawn_workers.return_value = ["worker-3"]

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            initial_workers = len(pool._workers)
            await pool.scale(4)  # Scale up to 4

            assert len(pool._workers) == 4
            assert pool._status == PoolStatus.RUNNING

    @pytest.mark.asyncio
    async def test_scale_down_removes_workers(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test scale() decreases worker count within bounds."""
        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            await pool.scale(1)  # Scale down to 1

            assert len(pool._workers) == 1
            mock_worker_manager.close_worker.assert_called()
            assert pool._status == PoolStatus.RUNNING

    @pytest.mark.asyncio
    async def test_scale_raises_when_below_min(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test scale() raises ValueError when target < min_workers."""
        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            with pytest.raises(ValueError, match="outside range"):
                await pool.scale(0)

    @pytest.mark.asyncio
    async def test_scale_raises_when_above_max(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test scale() raises ValueError when target > max_workers."""
        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            with pytest.raises(ValueError, match="outside range"):
                await pool.scale(10)  # max is 5

    @pytest.mark.asyncio
    async def test_scale_sets_status_to_scaling(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test scale() sets status to SCALING during operation."""
        mock_worker_manager.spawn_workers.return_value = ["worker-3"]

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            await pool.scale(4)

            assert pool._status == PoolStatus.RUNNING

    @pytest.mark.asyncio
    async def test_health_check_healthy(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test health_check() returns healthy when workers meet min."""
        mock_worker_manager.health_check.return_value = {
            "status": "healthy",
            "workers_active": 2,
        }

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            health = await pool.health_check()

            assert health["status"] == "healthy"
            assert health["pool_type"] == "mahavishnu"
            assert health["workers_active"] == 2

    @pytest.mark.asyncio
    async def test_health_check_degraded(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test health_check() returns degraded when workers reduced."""
        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            # Simulate worker count below min but > 0
            pool._workers = {"worker-1": "worker_1"}  # Only 1 worker

            health = await pool.health_check()

            assert health["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test health_check() returns unhealthy when no workers."""
        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            pool._workers = {}  # No workers

            health = await pool.health_check()

            assert health["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_get_metrics_returns_pool_metrics(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test get_metrics() returns PoolMetrics with stats."""
        mock_worker_manager.health_check.return_value = {
            "status": "healthy",
            "workers_active": 2,
        }

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            # Add some task history
            pool._tasks_completed = 10
            pool._tasks_failed = 2
            pool._task_durations = [1.0, 2.0, 3.0]

            metrics = await pool.get_metrics()

            assert metrics.pool_id == pool.pool_id
            assert metrics.status == PoolStatus.RUNNING
            assert metrics.active_workers == 2
            assert metrics.total_workers == 2
            assert metrics.tasks_completed == 10
            assert metrics.tasks_failed == 2
            assert metrics.avg_task_duration == 2.0

    @pytest.mark.asyncio
    async def test_get_metrics_empty_duration(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test get_metrics() handles empty task durations."""
        mock_worker_manager.health_check.return_value = {
            "status": "healthy",
            "workers_active": 2,
        }

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            metrics = await pool.get_metrics()

            assert metrics.avg_task_duration == 0.0

    @pytest.mark.asyncio
    async def test_collect_memory_returns_worker_results(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test collect_memory() transforms worker results for Session-Buddy."""
        mock_results = {
            "worker-1": WorkerResult(
                worker_id="worker-1",
                status=WorkerStatus.COMPLETED,
                output="task output",
                error=None,
                exit_code=0,
                duration_seconds=1.5,
            ),
        }
        mock_worker_manager.collect_results.return_value = mock_results

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            memory = await pool.collect_memory()

            assert len(memory) == 1
            assert memory[0]["content"] == "task output"
            assert memory[0]["metadata"]["pool_id"] == pool.pool_id
            assert memory[0]["metadata"]["pool_type"] == "mahavishnu"
            assert memory[0]["metadata"]["worker_id"] == "worker-1"
            assert memory[0]["metadata"]["type"] == "pool_worker_execution"

    @pytest.mark.asyncio
    async def test_stop_closes_all_workers(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test stop() calls worker_manager.close_all()."""
        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            await pool.stop()

            mock_worker_manager.close_all.assert_called_once()
            assert pool._status == PoolStatus.STOPPED

    @pytest.mark.asyncio
    async def test_status_returns_current_status(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test status() returns current pool status."""
        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            status = await pool.status()

            assert status == PoolStatus.RUNNING

    @pytest.mark.asyncio
    async def test_execute_task_records_duration(
        self, mock_terminal_manager, pool_config, mock_worker_manager
    ):
        """Test execute_task() records task duration."""
        mock_result = WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.COMPLETED,
            output="output",
            error=None,
            exit_code=0,
            duration_seconds=2.5,
        )
        mock_worker_manager.execute_task.return_value = mock_result

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_worker_manager,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            await pool.execute_task({"prompt": "task"})

            assert len(pool._task_durations) == 1
            assert 2.5 in pool._task_durations