"""Unit tests for MahavishnuPool class."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import PoolStatus, WorkerStatus
from mahavishnu.pools.base import PoolConfig
from mahavishnu.pools.mahavishnu_pool import MahavishnuPool
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

    def _create_mock_worker_manager(self):
        """Create a properly configured mock WorkerManager."""
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
    async def test_start_spawns_min_workers(self, mock_terminal_manager, pool_config):
        """Test start() spawns min_workers workers."""
        mock_wm = self._create_mock_worker_manager()

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )

            pool_id = await pool.start()

            assert pool_id == pool.pool_id
            assert pool._status == PoolStatus.RUNNING
            assert mock_wm.spawn_workers.call_count >= 1
            assert len(pool._workers) == 2

    @pytest.mark.asyncio
    async def test_execute_task_uses_first_available_worker(
        self, mock_terminal_manager, pool_config
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

        mock_wm = self._create_mock_worker_manager()
        mock_wm.execute_task.return_value = mock_result

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
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
    async def test_execute_task_tracks_stats_on_success(self, mock_terminal_manager, pool_config):
        """Test execute_task() increments tasks_completed on success."""
        mock_result = WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.COMPLETED,
            output="output",
            error=None,
            exit_code=0,
            duration_seconds=1.0,
        )

        mock_wm = self._create_mock_worker_manager()
        mock_wm.execute_task.return_value = mock_result

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
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
    async def test_execute_task_tracks_stats_on_failure(self, mock_terminal_manager, pool_config):
        """Test execute_task() increments tasks_failed on failure."""
        mock_result = WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.FAILED,
            output=None,
            error="task failed",
            exit_code=1,
            duration_seconds=1.0,
        )

        mock_wm = self._create_mock_worker_manager()
        mock_wm.execute_task.return_value = mock_result

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
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
    async def test_execute_task_raises_when_no_workers(self, mock_terminal_manager, pool_config):
        """Test execute_task() raises when no workers available."""
        mock_wm = self._create_mock_worker_manager()

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            # Don't start pool, workers dict is empty

            with pytest.raises(RuntimeError, match="No workers available"):
                await pool.execute_task({"prompt": "test"})

    @pytest.mark.asyncio
    async def test_execute_batch_returns_results(self, mock_terminal_manager, pool_config):
        """Test execute_batch() returns result dictionary."""
        # Mock execute_batch to return task results keyed by worker_id
        mock_results = {
            "worker-1": WorkerResult(
                worker_id="worker-1",
                status=WorkerStatus.COMPLETED,
                output="result1",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
            ),
        }

        mock_wm = self._create_mock_worker_manager()
        mock_wm.execute_batch.return_value = mock_results

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            tasks = [{"prompt": "task1"}, {"prompt": "task2"}]
            await pool.execute_batch(tasks)

            # Verify execute_batch was called
            assert mock_wm.execute_batch.called

    @pytest.mark.asyncio
    async def test_execute_batch_tracks_stats(self, mock_terminal_manager, pool_config):
        """Test execute_batch() tracks task statistics via result durations."""
        mock_results = {
            "worker-1": WorkerResult(
                worker_id="worker-1",
                status=WorkerStatus.COMPLETED,
                output="result1",
                error=None,
                exit_code=0,
                duration_seconds=1.0,
            ),
        }

        mock_wm = self._create_mock_worker_manager()
        mock_wm.execute_batch.return_value = mock_results

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            tasks = [{"prompt": "task1"}, {"prompt": "task2"}]
            await pool.execute_batch(tasks)

            # execute_batch uses result.duration_seconds from WorkerResult
            # and we track those in _task_durations
            assert len(pool._task_durations) == 1  # only 1 result for 2 tasks

    @pytest.mark.asyncio
    async def test_scale_raises_when_below_min(self, mock_terminal_manager, pool_config):
        """Test scale() raises ValueError when target < min_workers."""
        mock_wm = self._create_mock_worker_manager()

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            with pytest.raises(ValueError, match="outside range"):
                await pool.scale(0)  # min is 2

    @pytest.mark.asyncio
    async def test_scale_raises_when_above_max(self, mock_terminal_manager, pool_config):
        """Test scale() raises ValueError when target > max_workers."""
        mock_wm = self._create_mock_worker_manager()

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            with pytest.raises(ValueError, match="outside range"):
                await pool.scale(10)  # max is 5

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, mock_terminal_manager, pool_config):
        """Test health_check() returns healthy when workers meet min."""
        mock_wm = self._create_mock_worker_manager()
        mock_wm.health_check.return_value = {
            "status": "healthy",
            "workers_active": 2,
        }

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
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
    async def test_health_check_degraded(self, mock_terminal_manager, pool_config):
        """Test health_check() returns degraded when workers below min."""
        mock_wm = self._create_mock_worker_manager()
        mock_wm.health_check.return_value = {"status": "degraded", "workers_active": 0}

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
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
    async def test_health_check_unhealthy(self, mock_terminal_manager, pool_config):
        """Test health_check() returns unhealthy when no workers."""
        mock_wm = self._create_mock_worker_manager()
        mock_wm.health_check.return_value = {"status": "degraded", "workers_active": 0}

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
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
    async def test_get_metrics_returns_pool_metrics(self, mock_terminal_manager, pool_config):
        """Test get_metrics() returns PoolMetrics with stats."""
        mock_wm = self._create_mock_worker_manager()
        mock_wm.health_check.return_value = {
            "status": "healthy",
            "workers_active": 2,
        }

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
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
    async def test_get_metrics_empty_duration(self, mock_terminal_manager, pool_config):
        """Test get_metrics() handles empty task durations."""
        mock_wm = self._create_mock_worker_manager()
        mock_wm.health_check.return_value = {
            "status": "healthy",
            "workers_active": 2,
        }

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            metrics = await pool.get_metrics()

            assert metrics.avg_task_duration == 0.0

    @pytest.mark.asyncio
    async def test_collect_memory_returns_worker_results(self, mock_terminal_manager, pool_config):
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

        mock_wm = self._create_mock_worker_manager()
        mock_wm.collect_results.return_value = mock_results

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
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
    async def test_stop_closes_all_workers(self, mock_terminal_manager, pool_config):
        """Test stop() calls worker_manager.close_all()."""
        mock_wm = self._create_mock_worker_manager()

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            await pool.stop()

            mock_wm.close_all.assert_called_once()
            assert pool._status == PoolStatus.STOPPED

    @pytest.mark.asyncio
    async def test_status_returns_current_status(self, mock_terminal_manager, pool_config):
        """Test status() returns current pool status."""
        mock_wm = self._create_mock_worker_manager()

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            status = await pool.status()

            assert status == PoolStatus.RUNNING

    @pytest.mark.asyncio
    async def test_execute_task_records_wall_clock_duration(
        self, mock_terminal_manager, pool_config
    ):
        """Test execute_task() records wall-clock duration, not result duration."""
        mock_result = WorkerResult(
            worker_id="worker-1",
            status=WorkerStatus.COMPLETED,
            output="output",
            error=None,
            exit_code=0,
            duration_seconds=100.0,  # Simulated result has 100s
        )

        mock_wm = self._create_mock_worker_manager()
        mock_wm.execute_task.return_value = mock_result

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )
            await pool.start()

            await pool.execute_task({"prompt": "task"})

            # execute_task measures wall-clock time, not result.duration_seconds
            # so duration should be very small (< 1s) since mock is instant
            assert len(pool._task_durations) == 1
            # Wall-clock time for mocked call is very small
            assert pool._task_durations[0] < 1.0
