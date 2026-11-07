"""Unit tests for MahavishnuPool class."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.errors import ErrorCode, MahavishnuError
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
    async def test_start_swallows_resource_not_found_for_unknown_worker_type(
        self, mock_terminal_manager, pool_config
    ):
        """Regression test: ``get_worker_entry`` raising ``RESOURCE_NOT_FOUND`` must
        be swallowed by the requires_tool guard. Bug caught by ``ty``: the previous
        code referenced ``exc.code`` which doesn't exist on ``MahavishnuError``
        (the attribute is ``error_code``)."""
        mock_wm = self._create_mock_worker_manager()

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ), patch(
            "mahavishnu.workers.registry.get_worker_entry",
            side_effect=MahavishnuError(
                "unknown worker_type", ErrorCode.RESOURCE_NOT_FOUND
            ),
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )

            pool_id = await pool.start()

            assert pool_id == pool.pool_id
            assert pool._status == PoolStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_reraises_non_resource_not_found_errors(
        self, mock_terminal_manager, pool_config
    ):
        """``get_worker_entry`` raising a non-``RESOURCE_NOT_FOUND`` error must propagate
        (e.g. CONFIGURATION_ERROR) — not be silently swallowed as a missing entry."""
        mock_wm = self._create_mock_worker_manager()

        with patch(
            "mahavishnu.pools.mahavishnu_pool.WorkerManager",
            return_value=mock_wm,
        ), patch(
            "mahavishnu.workers.registry.get_worker_entry",
            side_effect=MahavishnuError(
                "malformed config", ErrorCode.CONFIGURATION_ERROR
            ),
        ):
            pool = MahavishnuPool(
                config=pool_config,
                terminal_manager=mock_terminal_manager,
            )

            with pytest.raises(MahavishnuError) as exc_info:
                await pool.start()

            assert exc_info.value.error_code is ErrorCode.CONFIGURATION_ERROR

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


class TestShepherdWorkspaceAutoInit:
    """The pool initializes the Shepherd workspace it creates.

    A pool workspace is a Shepherd workspace, and a Shepherd workspace is
    a git-backed store (``.vcscore``) inside the directory -- not the
    directory itself. Creating the directory alone left every Shepherd
    worker failing closed with MHV-312 ("not a Shepherd workspace. Run
    `sp init` first"), which put an invisible operator step between
    "spawn a pool" and "it works".
    """

    def test_the_helper_creates_the_marker(self, tmp_path):
        from mahavishnu.pools.mahavishnu_pool import _initialize_shepherd_workspace

        workspace = tmp_path / "pool" / "workspace"
        workspace.mkdir(parents=True)
        assert not (workspace / ".vcscore").exists()

        assert _initialize_shepherd_workspace(workspace) is True
        assert (workspace / ".vcscore").is_dir()

    def test_the_helper_reports_failure_without_raising(self, tmp_path):
        from mahavishnu.pools import mahavishnu_pool

        workspace = tmp_path / "pool" / "workspace"
        workspace.mkdir(parents=True)

        with patch.object(
            mahavishnu_pool,
            "_initialize_shepherd_workspace",
            return_value=False,
        ):
            # A failed auto-init must not take the pool down: the worker
            # still fails closed on the workspace, which is the operator's
            # signal to run `sp init` by hand.
            pool = MahavishnuPool(
                config=PoolConfig(
                    name="auto-init-pool",
                    pool_type="mahavishnu",
                    min_workers=1,
                    max_workers=1,
                    worker_type="terminal-claude",
                    writable_root=str(tmp_path / "pool" / "workspace"),
                ),
                terminal_manager=MagicMock(),
            )
        assert pool.writable_root.exists()

    def test_a_pool_initializes_a_workspace_it_creates(self, tmp_path):
        """The regression test.

        The pool creates the workspace directory, so it owns initializing
        the Shepherd workspace inside it. Before this, the directory was
        created but the workspace was not, and the worker's MHV-312 was
        the only clue.
        """
        workspace = tmp_path / "pool" / "workspace"
        assert not workspace.exists()

        MahavishnuPool(
            config=PoolConfig(
                name="auto-init-pool",
                pool_type="mahavishnu",
                min_workers=1,
                max_workers=1,
                worker_type="terminal-claude",
                writable_root=str(workspace),
            ),
            terminal_manager=MagicMock(),
        )

        assert workspace.is_dir()
        assert (workspace / ".vcscore").is_dir(), (
            "the pool created the workspace directory but did not initialize "
            "the Shepherd workspace inside it -- the worker will fail "
            "closed with MHV-312"
        )

    def test_a_pool_initializes_an_existing_empty_workspace(self, tmp_path):
        """A pre-existing but EMPTY workspace directory is initialized too.

        This is what makes the fix reach pools that were created before it
        existed: their workspace directory is there, but uninitialized, and
        the worker failed closed on it. An empty directory holds nothing
        of the operator's, so filling it is safe.
        """
        workspace = tmp_path / "legacy-pool"
        workspace.mkdir(parents=True)
        assert not (workspace / ".vcscore").exists()

        MahavishnuPool(
            config=PoolConfig(
                name="legacy-pool",
                pool_type="mahavishnu",
                min_workers=1,
                max_workers=1,
                worker_type="terminal-claude",
                writable_root=str(workspace),
            ),
            terminal_manager=MagicMock(),
        )

        assert (workspace / ".vcscore").is_dir(), (
            "an existing but empty workspace directory was not initialized -- "
            "a pool created before the fix would still fail with MHV-312"
        )

    def test_a_pool_leaves_a_directory_with_content_alone(self, tmp_path):
        """A directory that holds something belongs to the operator.

        Initializing a Shepherd workspace inside it would drop a
        ``.vcscore`` store into somebody's directory without asking, and
        would paper over the misconfiguration that put a pool there in the
        first place.
        """
        workspace = tmp_path / "operator-owned"
        workspace.mkdir(parents=True)
        (workspace / "important.txt").write_text("not ours to touch")

        MahavishnuPool(
            config=PoolConfig(
                name="operator-pool",
                pool_type="mahavishnu",
                min_workers=1,
                max_workers=1,
                worker_type="terminal-claude",
                writable_root=str(workspace),
            ),
            terminal_manager=MagicMock(),
        )

        assert (workspace / "important.txt").exists()
        assert not (workspace / ".vcscore").exists(), (
            "the pool initialized a workspace directory that had content in it"
        )
