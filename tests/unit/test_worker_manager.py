"""Comprehensive unit tests for the WorkerManager class.

Covers initialization, worker creation, spawning, task execution,
batch execution, monitoring, result collection, lifecycle management,
debug monitor launching, and health checks.
"""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.status import WorkerStatus
from mahavishnu.workers.base import BaseWorker, WorkerResult
from mahavishnu.workers.manager import WorkerManager
from mahavishnu.workers.registry import WorkerCategory, WorkerConfig


def _make_terminal_manager():
    tm = MagicMock()
    tm.adapter = MagicMock()
    return tm


def _make_worker(
    worker_id: str = "worker-1",
    worker_type: str = "terminal-claude",
    status: WorkerStatus = WorkerStatus.RUNNING,
    execute_result: WorkerResult | None = None,
    progress: dict | None = None,
):
    worker = MagicMock(spec=BaseWorker)
    worker.worker_type = worker_type
    worker.start = AsyncMock(return_value=worker_id)
    worker.stop = AsyncMock()
    worker.status = AsyncMock(return_value=status)
    worker.execute = AsyncMock(
        return_value=execute_result
        or WorkerResult(
            worker_id=worker_id,
            status=WorkerStatus.COMPLETED,
            output="done",
            exit_code=0,
            duration_seconds=1.0,
        )
    )
    worker.get_progress = AsyncMock(
        return_value=progress
        or {
            "status": "completed",
            "output_preview": "done",
            "duration_seconds": 1.0,
        }
    )
    return worker


class TestWorkerManagerInit:
    """Tests for WorkerManager initialization."""

    def test_default_initialization(self):
        """Test WorkerManager initializes with default parameters."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        assert mgr.terminal_manager is tm
        assert mgr.max_concurrent == 10
        assert mgr.debug_mode is False
        assert mgr.session_buddy_client is None
        assert mgr.mcp_client is None
        assert mgr._workers == {}
        assert mgr._debug_monitor_worker is None

    def test_custom_max_concurrent(self):
        """Test max_concurrent is set correctly."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, max_concurrent=5)
        assert mgr.max_concurrent == 5

    def test_max_concurrent_clamped_to_minimum(self):
        """Test max_concurrent is clamped to 1 when below minimum."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, max_concurrent=0)
        assert mgr.max_concurrent == 1

    def test_max_concurrent_clamped_to_maximum(self):
        """Test max_concurrent is clamped to 100 when above maximum."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, max_concurrent=200)
        assert mgr.max_concurrent == 100

    def test_max_concurrent_at_boundaries(self):
        """Test max_concurrent at exact boundary values."""
        tm = _make_terminal_manager()
        mgr1 = WorkerManager(terminal_manager=tm, max_concurrent=1)
        assert mgr1.max_concurrent == 1

        mgr2 = WorkerManager(terminal_manager=tm, max_concurrent=100)
        assert mgr2.max_concurrent == 100

    def test_debug_mode_enabled(self):
        """Test debug_mode is stored correctly."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, debug_mode=True)
        assert mgr.debug_mode is True

    def test_optional_clients_stored(self):
        """Test optional session_buddy_client and mcp_client are stored."""
        tm = _make_terminal_manager()
        sb = MagicMock()
        mcp = MagicMock()
        mgr = WorkerManager(
            terminal_manager=tm,
            session_buddy_client=sb,
            mcp_client=mcp,
        )
        assert mgr.session_buddy_client is sb
        assert mgr.mcp_client is mcp

    def test_semaphore_created_with_max_concurrent(self):
        """Test that the internal semaphore is created."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, max_concurrent=3)
        assert isinstance(mgr._semaphore, asyncio.Semaphore)


class TestCreateWorker:
    """Tests for the _create_worker factory method."""

    def test_unknown_worker_type_raises(self):
        """Test that an unknown worker type raises ValueError."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        with pytest.raises(ValueError, match="Unknown worker type"):
            mgr._create_worker("nonexistent-type")

    def test_container_worker_created(self):
        """Test that a container category creates a ContainerWorker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        config = WorkerConfig(
            name="Test Container",
            worker_type="container",
            command="",
            category=WorkerCategory.CONTAINER,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=config),
            patch("mahavishnu.workers.manager.ContainerWorker") as MockCW,
        ):
            worker = mgr._create_worker("container")
            MockCW.assert_called_once_with(
                runtime="docker",
                image="python:3.13-slim",
                session_buddy_client=None,
            )
            assert worker is not None

    def test_container_worker_with_custom_kwargs(self):
        """Test container worker with custom runtime and image kwargs."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        config = WorkerConfig(
            name="Test Container",
            worker_type="container-executor",
            command="",
            category=WorkerCategory.CONTAINER,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=config),
            patch("mahavishnu.workers.manager.ContainerWorker") as MockCW,
        ):
            mgr._create_worker("container-executor", runtime="podman", image="alpine")
            MockCW.assert_called_once_with(
                runtime="podman",
                image="alpine",
                session_buddy_client=None,
            )

    def test_shell_worker_created(self):
        """Test that a shell category creates a GenericShellWorker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        config = WorkerConfig(
            name="Bash Shell",
            worker_type="terminal-shell",
            command="bash",
            category=WorkerCategory.SHELL,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=config),
            patch("mahavishnu.workers.generic_shell.GenericShellWorker") as MockGSH,
        ):
            worker = mgr._create_worker("terminal-shell")
            MockGSH.assert_called_once()
            call_kwargs = MockGSH.call_args[1]
            assert call_kwargs["terminal_manager"] is tm
            assert call_kwargs["worker_type"] == "terminal-shell"
            assert call_kwargs["config"] is config
            assert worker is not None

    def test_ai_assistant_worker_created(self):
        """Test that an AI assistant category creates a GenericShellWorker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        config = WorkerConfig(
            name="Qwen",
            worker_type="terminal-qwen",
            command="qwen",
            category=WorkerCategory.AI_ASSISTANT,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=config),
            patch("mahavishnu.workers.generic_shell.GenericShellWorker") as MockGSH,
        ):
            worker = mgr._create_worker("terminal-qwen")
            MockGSH.assert_called_once()
            assert worker is not None

    def test_remote_worker_created(self):
        """Test that a remote category creates a GenericShellWorker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        config = WorkerConfig(
            name="SSH",
            worker_type="terminal-ssh",
            command="ssh {host}",
            category=WorkerCategory.REMOTE,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=config),
            patch("mahavishnu.workers.generic_shell.GenericShellWorker") as MockGSH,
        ):
            worker = mgr._create_worker("terminal-ssh", host="remotehost")
            MockGSH.assert_called_once()
            call_kwargs = MockGSH.call_args[1]
            assert call_kwargs["host"] == "remotehost"
            assert worker is not None

    def test_application_worker_requires_mcp_client(self):
        """Test that application workers raise ValueError when mcp_client is None."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, mcp_client=None)
        config = WorkerConfig(
            name="GIMP",
            worker_type="application-gimp",
            command="",
            category=WorkerCategory.APPLICATION,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=config),
            pytest.raises(ValueError, match="requires MCP client"),
        ):
            mgr._create_worker("application-gimp")

    def test_application_worker_created_with_mcp_client(self):
        """Test that application workers are created when mcp_client is provided."""
        tm = _make_terminal_manager()
        mcp = MagicMock()
        mgr = WorkerManager(terminal_manager=tm, mcp_client=mcp)
        config = WorkerConfig(
            name="GIMP",
            worker_type="application-gimp",
            command="",
            category=WorkerCategory.APPLICATION,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=config),
            patch("mahavishnu.workers.application.ApplicationWorker") as MockAW,
        ):
            worker = mgr._create_worker("application-gimp")
            MockAW.assert_called_once()
            call_kwargs = MockAW.call_args[1]
            assert call_kwargs["mcp_client"] is mcp
            assert call_kwargs["worker_type"] == "application-gimp"
            assert worker is not None

    def test_gateway_openclaw_worker_created(self):
        """Test that gateway-openclaw creates an OpenClawGatewayWorker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        config = WorkerConfig(
            name="OpenClaw Gateway",
            worker_type="gateway-openclaw",
            command="",
            category=WorkerCategory.GATEWAY,
            default_timeout=300,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=config),
            patch(
                "mahavishnu.workers.openclaw_gateway.HTTPOpenClawGatewayClient", create=True
            ) as MockClient,
            patch(
                "mahavishnu.workers.openclaw_gateway.OpenClawGatewayConfig", create=True
            ) as MockConfig,
            patch(
                "mahavishnu.workers.openclaw_gateway.OpenClawGatewayWorker", create=True
            ) as MockWorker,
        ):
            worker = mgr._create_worker("gateway-openclaw")
            MockClient.assert_called_once()
            MockConfig.assert_called_once()
            MockWorker.assert_called_once()
            assert worker is not None

    def test_unknown_gateway_worker_type_raises(self):
        """Test that an unknown gateway worker type raises ValueError."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        config = WorkerConfig(
            name="Unknown Gateway",
            worker_type="gateway-unknown",
            command="",
            category=WorkerCategory.GATEWAY,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=config),
            pytest.raises(ValueError, match="Unknown gateway worker type"),
        ):
            mgr._create_worker("gateway-unknown")

    def test_fallback_creates_generic_shell_worker(self):
        """Test that an unrecognized category falls back to GenericShellWorker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        custom_config = WorkerConfig(
            name="Custom",
            worker_type="custom-type",
            command="custom-cmd",
            category=WorkerCategory.SHELL,
        )

        with (
            patch("mahavishnu.workers.registry.get_worker_config", return_value=custom_config),
            patch("mahavishnu.workers.generic_shell.GenericShellWorker") as MockGSH,
        ):
            worker = mgr._create_worker("custom-type")
            MockGSH.assert_called_once()
            assert worker is not None


class TestSpawnWorkers:
    """Tests for the spawn_workers method."""

    @pytest.mark.asyncio
    async def test_spawn_single_worker(self):
        """Test spawning a single worker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        worker = _make_worker(worker_id="w-1")

        with patch.object(mgr, "_create_worker", return_value=worker):
            ids = await mgr.spawn_workers("terminal-qwen", 1)
            assert ids == ["w-1"]
            assert "w-1" in mgr._workers

    @pytest.mark.asyncio
    async def test_spawn_multiple_workers(self):
        """Test spawning multiple workers."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        workers = [_make_worker(worker_id=f"w-{i}") for i in range(3)]

        with (
            patch.object(mgr, "_create_worker", side_effect=workers),
            patch.object(mgr, "_launch_debug_monitor", new_callable=AsyncMock),
        ):
            ids = await mgr.spawn_workers("terminal-qwen", 3)
            assert ids == ["w-0", "w-1", "w-2"]
            assert len(mgr._workers) == 3

    @pytest.mark.asyncio
    async def test_spawn_workers_with_debug_mode(self):
        """Test that debug monitor is launched when debug_mode is True."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, debug_mode=True)
        worker = _make_worker()

        with (
            patch.object(mgr, "_create_worker", return_value=worker),
            patch.object(mgr, "_launch_debug_monitor", new_callable=AsyncMock) as mock_debug,
        ):
            await mgr.spawn_workers("terminal-qwen", 1)
            mock_debug.assert_called_once()

    @pytest.mark.asyncio
    async def test_spawn_workers_without_debug_mode(self):
        """Test that debug monitor is not launched when debug_mode is False."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, debug_mode=False)
        worker = _make_worker()

        with (
            patch.object(mgr, "_create_worker", return_value=worker),
            patch.object(mgr, "_launch_debug_monitor", new_callable=AsyncMock) as mock_debug,
        ):
            await mgr.spawn_workers("terminal-qwen", 1)
            mock_debug.assert_not_called()

    @pytest.mark.asyncio
    async def test_spawn_zero_workers(self):
        """Test spawning zero workers returns empty list."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        ids = await mgr.spawn_workers("terminal-qwen", 0)
        assert ids == []
        assert len(mgr._workers) == 0


class TestExecuteTask:
    """Tests for the execute_task method."""

    @pytest.mark.asyncio
    async def test_execute_task_success(self):
        """Test successful task execution returns a WorkerResult."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        result = WorkerResult(
            worker_id="w-1",
            status=WorkerStatus.COMPLETED,
            output="output",
            exit_code=0,
            duration_seconds=2.5,
        )
        worker = _make_worker(worker_id="w-1", execute_result=result)
        mgr._workers["w-1"] = worker

        ret = await mgr.execute_task("w-1", {"prompt": "hello"})
        assert ret.status == WorkerStatus.COMPLETED
        assert ret.worker_id == "w-1"
        worker.execute.assert_called_once_with({"prompt": "hello"})

    @pytest.mark.asyncio
    async def test_execute_task_worker_not_found(self):
        """Test that executing on a nonexistent worker raises ValueError."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        with pytest.raises(ValueError, match="Worker not found"):
            await mgr.execute_task("nonexistent", {"prompt": "test"})

    @pytest.mark.asyncio
    async def test_execute_task_exception_returns_failure_result(self):
        """Test that an exception during execution returns a FAILED result."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        worker = _make_worker(worker_id="w-1")
        worker.execute = AsyncMock(side_effect=RuntimeError("boom"))
        mgr._workers["w-1"] = worker

        ret = await mgr.execute_task("w-1", {"prompt": "test"})
        assert ret.status == WorkerStatus.FAILED
        assert ret.worker_id == "w-1"
        assert "boom" in ret.error
        assert ret.metadata["exception"] == "RuntimeError"

    @pytest.mark.asyncio
    async def test_execute_task_respects_semaphore_concurrency(self):
        """Test that the semaphore limits concurrent task execution."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, max_concurrent=1)

        execution_count = 0
        max_concurrent = 0

        async def slow_execute(task):
            nonlocal execution_count, max_concurrent
            execution_count += 1
            max_concurrent = max(max_concurrent, execution_count)
            await asyncio.sleep(0.05)
            execution_count -= 1
            return WorkerResult(
                worker_id="w-1",
                status=WorkerStatus.COMPLETED,
                output="done",
                exit_code=0,
                duration_seconds=0.05,
            )

        worker = _make_worker(worker_id="w-1")
        worker.execute = slow_execute
        mgr._workers["w-1"] = worker

        tasks = [mgr.execute_task("w-1", {"prompt": "test"}) for _ in range(3)]
        results = await asyncio.gather(*tasks)

        assert max_concurrent <= 1
        assert all(r.status == WorkerStatus.COMPLETED for r in results)


class TestExecuteBatch:
    """Tests for the execute_batch method."""

    @pytest.mark.asyncio
    async def test_execute_batch_success(self):
        """Test batch execution returns results for all workers."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        for i in range(3):
            mgr._workers[f"w-{i}"] = _make_worker(
                worker_id=f"w-{i}",
                execute_result=WorkerResult(
                    worker_id=f"w-{i}",
                    status=WorkerStatus.COMPLETED,
                    output=f"result-{i}",
                    exit_code=0,
                    duration_seconds=1.0,
                ),
            )

        results = await mgr.execute_batch(
            ["w-0", "w-1", "w-2"],
            [{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}],
        )
        assert len(results) == 3
        assert all(results[f"w-{i}"].output == f"result-{i}" for i in range(3))

    @pytest.mark.asyncio
    async def test_execute_batch_length_mismatch_raises(self):
        """Test that mismatched worker_ids and tasks length raises ValueError."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        with pytest.raises(ValueError, match="must have same length"):
            await mgr.execute_batch(["w-0"], [{"prompt": "a"}, {"prompt": "b"}])

    @pytest.mark.asyncio
    async def test_execute_batch_empty(self):
        """Test batch execution with empty lists returns empty dict."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        results = await mgr.execute_batch([], [])
        assert results == {}


class TestMonitorWorkers:
    """Tests for the monitor_workers method."""

    @pytest.mark.asyncio
    async def test_monitor_all_workers(self):
        """Test monitoring all workers when worker_ids is None."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._workers["w-0"] = _make_worker("w-0", status=WorkerStatus.RUNNING)
        mgr._workers["w-1"] = _make_worker("w-1", status=WorkerStatus.COMPLETED)

        statuses = await mgr.monitor_workers(interval=0)
        assert statuses["w-0"] == WorkerStatus.RUNNING
        assert statuses["w-1"] == WorkerStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_monitor_specific_workers(self):
        """Test monitoring a specific subset of workers."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._workers["w-0"] = _make_worker("w-0", status=WorkerStatus.RUNNING)
        mgr._workers["w-1"] = _make_worker("w-1", status=WorkerStatus.PENDING)

        statuses = await mgr.monitor_workers(worker_ids=["w-0"], interval=0)
        assert len(statuses) == 1
        assert statuses["w-0"] == WorkerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_monitor_nonexistent_worker_skipped(self):
        """Test that monitoring a nonexistent worker ID is skipped."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        statuses = await mgr.monitor_workers(worker_ids=["nonexistent"], interval=0)
        assert statuses == {}

    @pytest.mark.asyncio
    async def test_monitor_worker_status_exception(self):
        """Test that a status() exception sets FAILED status for that worker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        worker = _make_worker("w-1")
        worker.status = AsyncMock(side_effect=RuntimeError("status error"))
        mgr._workers["w-1"] = worker

        statuses = await mgr.monitor_workers(interval=0)
        assert statuses["w-1"] == WorkerStatus.FAILED

    @pytest.mark.asyncio
    async def test_monitor_empty_workers(self):
        """Test monitoring when no workers exist returns empty dict."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        statuses = await mgr.monitor_workers(interval=0)
        assert statuses == {}

    @pytest.mark.asyncio
    async def test_monitor_sleeps_for_interval(self):
        """Test that monitor_workers sleeps for the specified interval."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await mgr.monitor_workers(interval=0.5)
            mock_sleep.assert_called_once_with(0.5)


class TestCollectResults:
    """Tests for the collect_results method."""

    @pytest.mark.asyncio
    async def test_collect_all_results(self):
        """Test collecting results from all workers."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._workers["w-0"] = _make_worker(
            "w-0",
            progress={
                "status": "completed",
                "output_preview": "done",
                "duration_seconds": 2.0,
            },
        )

        results = await mgr.collect_results()
        assert "w-0" in results
        assert results["w-0"].status == WorkerStatus.COMPLETED
        assert results["w-0"].exit_code == 0
        assert results["w-0"].duration_seconds == 2.0

    @pytest.mark.asyncio
    async def test_collect_results_non_completed_exit_code(self):
        """Test that non-completed workers get exit_code 1."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._workers["w-0"] = _make_worker(
            "w-0",
            progress={
                "status": "failed",
                "output_preview": None,
                "duration_seconds": 0.5,
            },
        )

        results = await mgr.collect_results()
        assert results["w-0"].exit_code == 1

    @pytest.mark.asyncio
    async def test_collect_results_specific_workers(self):
        """Test collecting results from specific workers only."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._workers["w-0"] = _make_worker("w-0")
        mgr._workers["w-1"] = _make_worker("w-1")

        results = await mgr.collect_results(worker_ids=["w-0"])
        assert len(results) == 1
        assert "w-0" in results

    @pytest.mark.asyncio
    async def test_collect_results_exception_returns_failure(self):
        """Test that an exception during collection returns a FAILED result."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        worker = _make_worker("w-0")
        worker.get_progress = AsyncMock(side_effect=RuntimeError("progress error"))
        mgr._workers["w-0"] = worker

        results = await mgr.collect_results()
        assert results["w-0"].status == WorkerStatus.FAILED
        assert "progress error" in results["w-0"].error

    @pytest.mark.asyncio
    async def test_collect_results_empty(self):
        """Test collecting results when no workers exist returns empty dict."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        results = await mgr.collect_results()
        assert results == {}

    @pytest.mark.asyncio
    async def test_collect_results_nonexistent_worker_skipped(self):
        """Test that nonexistent worker IDs are skipped during collection."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        results = await mgr.collect_results(worker_ids=["nonexistent"])
        assert results == {}

    @pytest.mark.asyncio
    async def test_collect_results_invalid_status_returns_failure(self):
        """Test that an invalid status string in progress triggers the error path."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._workers["w-0"] = _make_worker(
            "w-0",
            progress={"status": "invalid_status", "output_preview": None},
        )

        results = await mgr.collect_results()
        assert results["w-0"].status == WorkerStatus.FAILED
        assert "invalid_status" in results["w-0"].error


class TestCloseWorker:
    """Tests for the close_worker method."""

    @pytest.mark.asyncio
    async def test_close_existing_worker(self):
        """Test closing an existing worker calls stop and removes it."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        worker = _make_worker("w-1")
        mgr._workers["w-1"] = worker

        await mgr.close_worker("w-1")
        worker.stop.assert_called_once()
        assert "w-1" not in mgr._workers

    @pytest.mark.asyncio
    async def test_close_nonexistent_worker(self):
        """Test closing a nonexistent worker does nothing."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        await mgr.close_worker("nonexistent")
        assert len(mgr._workers) == 0

    @pytest.mark.asyncio
    async def test_close_worker_exception_still_removes(self):
        """Test that an exception during stop still removes the worker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        worker = _make_worker("w-1")
        worker.stop = AsyncMock(side_effect=RuntimeError("stop error"))
        mgr._workers["w-1"] = worker

        await mgr.close_worker("w-1")
        assert "w-1" not in mgr._workers


class TestCloseAll:
    """Tests for the close_all method."""

    @pytest.mark.asyncio
    async def test_close_all_workers(self):
        """Test that close_all closes every registered worker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        workers = {}
        for i in range(4):
            w = _make_worker(f"w-{i}")
            mgr._workers[f"w-{i}"] = w
            workers[f"w-{i}"] = w

        await mgr.close_all()
        assert len(mgr._workers) == 0
        for w in workers.values():
            w.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all_empty(self):
        """Test close_all when no workers exist."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        await mgr.close_all()
        assert len(mgr._workers) == 0

    @pytest.mark.asyncio
    async def test_close_all_with_debug_monitor(self):
        """Test that close_all also closes the debug monitor worker."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        debug_worker = _make_worker("debug-monitor")
        mgr._debug_monitor_worker = debug_worker

        await mgr.close_all()
        debug_worker.stop.assert_called_once()
        assert mgr._debug_monitor_worker is None

    @pytest.mark.asyncio
    async def test_close_all_debug_monitor_exception_ignored(self):
        """Test that exceptions from debug monitor stop are silently caught."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        debug_worker = _make_worker("debug-monitor")
        debug_worker.stop = AsyncMock(side_effect=RuntimeError("debug stop fail"))
        mgr._debug_monitor_worker = debug_worker

        await mgr.close_all()
        assert mgr._debug_monitor_worker is None


class TestLaunchDebugMonitor:
    """Tests for the _launch_debug_monitor method."""

    @pytest.mark.asyncio
    async def test_launch_debug_monitor_already_running(self):
        """Test that launching a debug monitor when one exists is a no-op."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._debug_monitor_worker = MagicMock()

        await mgr._launch_debug_monitor()
        assert mgr._debug_monitor_worker is not None

    @pytest.mark.asyncio
    async def test_launch_debug_monitor_no_log_path(self):
        """Test that the debug monitor is not launched when no log path is found."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()
        root_logger.addHandler(logging.NullHandler())

        try:
            await mgr._launch_debug_monitor()
            assert mgr._debug_monitor_worker is None
        finally:
            root_logger.handlers = original_handlers

    @pytest.mark.asyncio
    async def test_launch_debug_monitor_success(self):
        """Test successful debug monitor launch."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        mock_handler = MagicMock(spec=logging.FileHandler)
        mock_handler.baseFilename = "/tmp/test.log"
        mock_handler.level = logging.DEBUG
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()
        root_logger.addHandler(mock_handler)

        mock_debug_worker = MagicMock()
        mock_debug_worker.start = AsyncMock(return_value="debug-1")

        try:
            with patch(
                "mahavishnu.workers.debug_monitor.DebugMonitorWorker",
                return_value=mock_debug_worker,
            ):
                await mgr._launch_debug_monitor()
                assert mgr._debug_monitor_worker is mock_debug_worker
                mock_debug_worker.start.assert_called_once()
        finally:
            root_logger.handlers = original_handlers

    @pytest.mark.asyncio
    async def test_launch_debug_monitor_import_error(self):
        """Test that ImportError for DebugMonitorWorker is handled gracefully."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        mock_handler = MagicMock(spec=logging.FileHandler)
        mock_handler.baseFilename = "/tmp/test.log"
        mock_handler.level = logging.DEBUG
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()
        root_logger.addHandler(mock_handler)

        try:
            with patch(
                "mahavishnu.workers.debug_monitor.DebugMonitorWorker",
                side_effect=ImportError("not implemented"),
            ):
                await mgr._launch_debug_monitor()
                assert mgr._debug_monitor_worker is None
        finally:
            root_logger.handlers = original_handlers

    @pytest.mark.asyncio
    async def test_launch_debug_monitor_handler_without_base_filename(self):
        """Test that handlers without baseFilename attribute are skipped."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        mock_handler = MagicMock(spec=logging.StreamHandler)
        mock_handler.level = logging.WARNING
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()
        root_logger.addHandler(mock_handler)

        try:
            await mgr._launch_debug_monitor()
            assert mgr._debug_monitor_worker is None
        finally:
            root_logger.handlers = original_handlers


class TestListWorkers:
    """Tests for the list_workers method."""

    @pytest.mark.asyncio
    async def test_list_workers_empty(self):
        """Test listing workers when none exist returns empty list."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)

        result = await mgr.list_workers()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_workers_returns_info(self):
        """Test listing workers returns correct information dictionaries."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._workers["w-0"] = _make_worker(
            "w-0", worker_type="terminal-qwen", status=WorkerStatus.RUNNING
        )
        mgr._workers["w-1"] = _make_worker(
            "w-1", worker_type="terminal-shell", status=WorkerStatus.COMPLETED
        )

        result = await mgr.list_workers()
        assert len(result) == 2

        info_by_id = {r["worker_id"]: r for r in result}
        assert info_by_id["w-0"]["worker_type"] == "terminal-qwen"
        assert info_by_id["w-0"]["status"] == "running"
        assert info_by_id["w-1"]["worker_type"] == "terminal-shell"
        assert info_by_id["w-1"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_list_workers_status_exception(self):
        """Test that a worker with a failing status() shows 'unknown'."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        worker = _make_worker("w-1")
        worker.status = AsyncMock(side_effect=RuntimeError("status fail"))
        mgr._workers["w-1"] = worker

        result = await mgr.list_workers()
        assert len(result) == 1
        assert result[0]["status"] == "unknown"


class TestHealthCheck:
    """Tests for the health_check method."""

    @pytest.mark.asyncio
    async def test_health_check_basic(self):
        """Test health_check returns expected structure."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm, max_concurrent=5, debug_mode=True)

        health = await mgr.health_check()
        assert health["status"] == "healthy"
        assert health["workers_active"] == 0
        assert health["max_concurrent"] == 5
        assert health["debug_mode"] is True
        assert health["debug_monitor_active"] is False
        assert health["workers"] == []

    @pytest.mark.asyncio
    async def test_health_check_with_active_workers(self):
        """Test health_check with active workers reports them."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._workers["w-0"] = _make_worker(
            "w-0", worker_type="terminal-qwen", status=WorkerStatus.RUNNING
        )

        health = await mgr.health_check()
        assert health["workers_active"] == 1
        assert len(health["workers"]) == 1
        assert health["workers"][0]["worker_id"] == "w-0"

    @pytest.mark.asyncio
    async def test_health_check_debug_monitor_active(self):
        """Test health_check reflects active debug monitor."""
        tm = _make_terminal_manager()
        mgr = WorkerManager(terminal_manager=tm)
        mgr._debug_monitor_worker = MagicMock()

        health = await mgr.health_check()
        assert health["debug_monitor_active"] is True
