"""Unit tests for mahavishnu.mcp.tools.worker_tools.

The module exposes ``register_worker_tools`` which attaches 8 FastMCP tools
(``worker_spawn``, ``worker_execute``, ``worker_execute_batch``, ``worker_list``,
``worker_monitor``, ``worker_collect_results``, ``worker_close``,
``worker_close_all``, ``worker_health``).

The FastMCP API requires each tool function to be defined inline so the
decorator can introspect the function name and signature. We therefore
register against a stub ``FastMCP`` instance that captures the decorated
callables in a dict, then invoke each registered function directly with
mocked dependencies. This avoids re-implementing the tools in test bodies.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools.worker_tools import register_worker_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Stub MCP and fixtures
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in that captures tool functions by name."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class _WorkerStatus(str, Enum):
    """Stand-in for the project's WorkerStatus enum."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _make_result(
    *,
    worker_id: str = "w_1",
    status: _WorkerStatus = _WorkerStatus.COMPLETED,
    output: str | None = "ok",
    error: str | None = None,
    duration: float = 1.5,
) -> MagicMock:
    """Build a TaskResult-shaped MagicMock with the documented attributes."""

    result = MagicMock()
    result.worker_id = worker_id
    result.status = status
    result.output = output
    result.error = error
    result.duration_seconds = duration
    result.has_output = MagicMock(return_value=output is not None and output != "")
    return result


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def mock_worker_manager() -> AsyncMock:
    """Build an AsyncMock WorkerManager with realistic defaults."""

    manager = AsyncMock()
    manager.spawn_workers = AsyncMock(return_value=["w_1", "w_2"])
    manager.execute_task = AsyncMock(
        return_value=_make_result(
            worker_id="w_1",
            status=_WorkerStatus.COMPLETED,
            output="task completed successfully",
            duration=2.0,
        )
    )
    manager.execute_batch = AsyncMock(
        return_value={
            "w_1": _make_result(
                worker_id="w_1",
                status=_WorkerStatus.COMPLETED,
                output="result-1",
            ),
            "w_2": _make_result(
                worker_id="w_2",
                status=_WorkerStatus.COMPLETED,
                output="result-2",
            ),
        }
    )
    manager.list_workers = AsyncMock(
        return_value=[
            {"worker_id": "w_1", "worker_type": "terminal-claude"},
            {"worker_id": "w_2", "worker_type": "terminal-claude"},
        ]
    )
    manager.monitor_workers = AsyncMock(
        return_value={
            "w_1": _WorkerStatus.RUNNING,
            "w_2": _WorkerStatus.COMPLETED,
        }
    )
    manager.collect_results = AsyncMock(
        return_value={
            "w_1": _make_result(
                worker_id="w_1",
                status=_WorkerStatus.COMPLETED,
                output="collected output",
                duration=3.5,
            ),
        }
    )
    manager.close_worker = AsyncMock(return_value=None)
    manager.health_check = AsyncMock(
        return_value={"status": "healthy", "workers_active": 2}
    )
    return manager


@pytest.fixture
def registered_mcp(
    stub_mcp: _StubMCP, mock_worker_manager: AsyncMock
) -> _StubMCP:
    """Register worker tools on a stub MCP for inspection / invocation."""
    register_worker_tools(stub_mcp, mock_worker_manager)
    return stub_mcp


EXPECTED_TOOL_NAMES = {
    "worker_spawn",
    "worker_execute",
    "worker_execute_batch",
    "worker_list",
    "worker_monitor",
    "worker_collect_results",
    "worker_close",
    "worker_close_all",
    "worker_health",
}


# =============================================================================
# TestRegistration
# =============================================================================


class TestRegistration:
    """register_worker_tools attaches every documented tool to the FastMCP."""

    def test_all_nine_tools_registered(self, registered_mcp: _StubMCP) -> None:
        assert EXPECTED_TOOL_NAMES.issubset(set(registered_mcp.tools))

    def test_registers_exactly_expected_tools(
        self, registered_mcp: _StubMCP
    ) -> None:
        assert set(registered_mcp.tools) == EXPECTED_TOOL_NAMES


# =============================================================================
# TestWorkerSpawn
# =============================================================================


class TestWorkerSpawn:
    """``worker_spawn`` creates workers via WorkerManager.spawn_workers."""

    async def test_returns_worker_ids(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_spawn"]
        result = await fn(worker_type="terminal-claude", count=2)
        assert result == ["w_1", "w_2"]
        mock_worker_manager.spawn_workers.assert_awaited_once_with(
            worker_type="terminal-claude",
            count=2,
        )

    async def test_default_arguments(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_spawn"]
        result = await fn()
        assert result == ["w_1", "w_2"]
        _, kwargs = mock_worker_manager.spawn_workers.call_args
        assert kwargs["worker_type"] == "terminal-claude"
        assert kwargs["count"] == 1

    async def test_count_below_minimum_raises_value_error(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_spawn"]
        with pytest.raises(ValueError, match="count must be between 1 and 50"):
            await fn(count=0)
        mock_worker_manager.spawn_workers.assert_not_awaited()

    async def test_count_above_maximum_raises_value_error(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_spawn"]
        with pytest.raises(ValueError, match="count must be between 1 and 50"):
            await fn(count=51)
        mock_worker_manager.spawn_workers.assert_not_awaited()


# =============================================================================
# TestWorkerExecute
# =============================================================================


class TestWorkerExecute:
    """``worker_execute`` runs a task on a specific worker."""

    async def test_returns_expected_payload(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_execute"]
        result = await fn(worker_id="w_1", prompt="Write tests", timeout=300)
        assert result["worker_id"] == "w_1"
        assert result["status"] == "completed"
        assert result["output"] == "task completed successfully"
        assert result["error"] is None
        assert result["duration"] == 2.0
        assert result["has_output"] is True

    async def test_passes_task_dict_to_manager(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_execute"]
        await fn(worker_id="w_1", prompt="hi", timeout=300)
        worker_id, task = mock_worker_manager.execute_task.call_args.args
        assert worker_id == "w_1"
        assert task == {"prompt": "hi", "timeout": 300}

    async def test_uses_default_timeout(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_execute"]
        await fn(worker_id="w_1", prompt="hi")
        _, task = mock_worker_manager.execute_task.call_args.args
        assert task["timeout"] == 300

    async def test_truncates_long_output(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        long_output = "x" * 1000
        mock_worker_manager.execute_task = AsyncMock(
            return_value=_make_result(
                worker_id="w_1",
                status=_WorkerStatus.COMPLETED,
                output=long_output,
            )
        )
        fn = registered_mcp.tools["worker_execute"]
        result = await fn(worker_id="w_1", prompt="x")
        assert result["output"].endswith("...")
        # 500 chars + ellipsis
        assert len(result["output"]) == 503

    async def test_preserves_short_output(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        mock_worker_manager.execute_task = AsyncMock(
            return_value=_make_result(
                worker_id="w_1",
                status=_WorkerStatus.COMPLETED,
                output="short",
            )
        )
        fn = registered_mcp.tools["worker_execute"]
        result = await fn(worker_id="w_1", prompt="x")
        assert result["output"] == "short"

    async def test_handles_none_output(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        mock_worker_manager.execute_task = AsyncMock(
            return_value=_make_result(
                worker_id="w_1",
                status=_WorkerStatus.COMPLETED,
                output=None,
            )
        )
        fn = registered_mcp.tools["worker_execute"]
        result = await fn(worker_id="w_1", prompt="x")
        assert result["output"] is None
        assert result["has_output"] is False

    async def test_timeout_below_minimum_raises_value_error(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_execute"]
        with pytest.raises(ValueError, match="timeout must be between 30 and 3600"):
            await fn(worker_id="w_1", prompt="x", timeout=10)
        mock_worker_manager.execute_task.assert_not_awaited()

    async def test_timeout_above_maximum_raises_value_error(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_execute"]
        with pytest.raises(ValueError, match="timeout must be between 30 and 3600"):
            await fn(worker_id="w_1", prompt="x", timeout=5000)
        mock_worker_manager.execute_task.assert_not_awaited()


# =============================================================================
# TestWorkerExecuteBatch
# =============================================================================


class TestWorkerExecuteBatch:
    """``worker_execute_batch`` runs tasks on multiple workers concurrently."""

    async def test_returns_dict_per_worker(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_execute_batch"]
        result = await fn(
            worker_ids=["w_1", "w_2"], prompts=["a", "b"], timeout=300
        )
        assert set(result) == {"w_1", "w_2"}
        assert result["w_1"]["status"] == "completed"
        assert result["w_1"]["output"] == "result-1"
        assert result["w_2"]["status"] == "completed"
        assert result["w_2"]["output"] == "result-2"

    async def test_passes_worker_ids_and_tasks(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_execute_batch"]
        await fn(worker_ids=["w_1", "w_2"], prompts=["a", "b"], timeout=300)
        worker_ids, tasks = mock_worker_manager.execute_batch.call_args.args
        assert worker_ids == ["w_1", "w_2"]
        assert tasks == [
            {"prompt": "a", "timeout": 300},
            {"prompt": "b", "timeout": 300},
        ]

    async def test_truncates_long_output(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        long_output = "y" * 500
        mock_worker_manager.execute_batch = AsyncMock(
            return_value={
                "w_1": _make_result(
                    worker_id="w_1",
                    status=_WorkerStatus.COMPLETED,
                    output=long_output,
                ),
            }
        )
        fn = registered_mcp.tools["worker_execute_batch"]
        result = await fn(worker_ids=["w_1"], prompts=["x"], timeout=300)
        assert result["w_1"]["output"].endswith("...")
        # 200 chars + ellipsis
        assert len(result["w_1"]["output"]) == 203

    async def test_length_mismatch_raises_value_error(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_execute_batch"]
        with pytest.raises(
            ValueError, match="worker_ids and prompts must have same length"
        ):
            await fn(worker_ids=["w_1", "w_2"], prompts=["a"], timeout=300)
        mock_worker_manager.execute_batch.assert_not_awaited()


# =============================================================================
# TestWorkerList
# =============================================================================


class TestWorkerList:
    """``worker_list`` returns all active workers from the manager."""

    async def test_returns_worker_list(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_list"]
        workers = await fn()
        assert workers == [
            {"worker_id": "w_1", "worker_type": "terminal-claude"},
            {"worker_id": "w_2", "worker_type": "terminal-claude"},
        ]

    async def test_empty_list(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        mock_worker_manager.list_workers = AsyncMock(return_value=[])
        fn = registered_mcp.tools["worker_list"]
        assert await fn() == []


# =============================================================================
# TestWorkerMonitor
# =============================================================================


class TestWorkerMonitor:
    """``worker_monitor`` reports worker statuses in real-time."""

    async def test_returns_status_dict(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_monitor"]
        result = await fn()
        assert result == {"w_1": "running", "w_2": "completed"}

    async def test_passes_worker_ids_and_interval(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_monitor"]
        await fn(worker_ids=["w_1"], interval=2.0)
        mock_worker_manager.monitor_workers.assert_awaited_with(["w_1"], 2.0)

    async def test_default_arguments(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_monitor"]
        await fn()
        worker_ids, interval = mock_worker_manager.monitor_workers.call_args.args
        assert worker_ids is None
        assert interval == 1.0

    async def test_interval_below_minimum_raises_value_error(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_monitor"]
        with pytest.raises(ValueError, match="interval must be between 0.1 and 10.0"):
            await fn(interval=0.05)
        mock_worker_manager.monitor_workers.assert_not_awaited()

    async def test_interval_above_maximum_raises_value_error(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_monitor"]
        with pytest.raises(ValueError, match="interval must be between 0.1 and 10.0"):
            await fn(interval=11.0)
        mock_worker_manager.monitor_workers.assert_not_awaited()


# =============================================================================
# TestWorkerCollectResults
# =============================================================================


class TestWorkerCollectResults:
    """``worker_collect_results`` collects results from completed workers."""

    async def test_returns_results_dict(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_collect_results"]
        result = await fn()
        assert set(result) == {"w_1"}
        assert result["w_1"]["status"] == "completed"
        assert result["w_1"]["output"] == "collected output"
        assert result["w_1"]["duration"] == 3.5
        assert result["w_1"]["has_output"] is True

    async def test_passes_worker_ids(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_collect_results"]
        await fn(worker_ids=["w_1"])
        mock_worker_manager.collect_results.assert_awaited_with(["w_1"])

    async def test_default_worker_ids(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_collect_results"]
        await fn()
        mock_worker_manager.collect_results.assert_awaited_with(None)


# =============================================================================
# TestWorkerClose
# =============================================================================


class TestWorkerClose:
    """``worker_close`` shuts down a single worker."""

    async def test_close_success(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_close"]
        result = await fn(worker_id="w_1")
        assert result == {"success": True, "worker_id": "w_1"}
        mock_worker_manager.close_worker.assert_awaited_with("w_1")

    async def test_close_failure_returns_error_dict(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        mock_worker_manager.close_worker = AsyncMock(
            side_effect=RuntimeError("close failed")
        )
        fn = registered_mcp.tools["worker_close"]
        result = await fn(worker_id="w_1")
        assert result["success"] is False
        assert result["worker_id"] == "w_1"
        assert result["error"] == "close failed"


# =============================================================================
# TestWorkerCloseAll
# =============================================================================


class TestWorkerCloseAll:
    """``worker_close_all`` shuts down every active worker."""

    async def test_close_all_with_workers(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_close_all"]
        result = await fn()
        assert result == {"closed_count": 2}
        assert mock_worker_manager.close_worker.await_count == 2
        call_args_list = mock_worker_manager.close_worker.await_args_list
        assert {call.args[0] for call in call_args_list} == {"w_1", "w_2"}

    async def test_close_all_with_no_workers(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        mock_worker_manager.list_workers = AsyncMock(return_value=[])
        fn = registered_mcp.tools["worker_close_all"]
        result = await fn()
        assert result == {"closed_count": 0}
        mock_worker_manager.close_worker.assert_not_awaited()

    async def test_close_all_uses_list_workers_keys(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        """``worker_close_all`` reads the ``worker_id`` key from each row."""

        mock_worker_manager.list_workers = AsyncMock(
            return_value=[
                {"worker_id": "a"},
                {"worker_id": "b"},
                {"worker_id": "c"},
            ]
        )
        fn = registered_mcp.tools["worker_close_all"]
        result = await fn()
        assert result == {"closed_count": 3}
        assert mock_worker_manager.close_worker.await_count == 3


# =============================================================================
# TestWorkerHealth
# =============================================================================


class TestWorkerHealth:
    """``worker_health`` reports worker system health."""

    async def test_health_success(
        self, registered_mcp: _StubMCP, mock_worker_manager: AsyncMock
    ) -> None:
        fn = registered_mcp.tools["worker_health"]
        result = await fn()
        assert result == {"status": "healthy", "workers_active": 2}
        mock_worker_manager.health_check.assert_awaited_once()