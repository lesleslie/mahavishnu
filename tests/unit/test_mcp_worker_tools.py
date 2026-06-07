"""Unit tests for mahavishnu.mcp.tools.worker_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools.worker_tools import register_worker_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


def _make_result(worker_id: str = "w-1", status_value: str = "completed", output: str = "ok"):
    """Build a result object with the .status.value shape used by WorkerManager."""
    result = MagicMock()
    result.worker_id = worker_id
    result.status.value = status_value
    result.status.__class__ = type("Status", (), {"value": status_value})
    # Use a simple property emulation for status
    status_obj = MagicMock()
    status_obj.value = status_value
    result.status = status_obj
    result.output = output
    result.error = None
    result.duration_seconds = 1.5
    result.has_output = MagicMock(return_value=bool(output))
    return result


@pytest.fixture
def mock_mcp():
    """Create a mock FastMCP that captures tool functions."""
    mcp = MagicMock()

    def tool_decorator():
        def wrapper(fn):
            mcp._tools[fn.__name__] = fn
            return fn

        return wrapper

    mcp.tool = MagicMock(side_effect=lambda: tool_decorator())
    mcp._tools = {}
    return mcp


@pytest.fixture
def mock_worker_manager():
    """Create a mock WorkerManager with AsyncMock methods."""
    wm = MagicMock()
    wm.spawn_workers = AsyncMock(return_value=["w-1", "w-2"])
    wm.execute_task = AsyncMock(return_value=_make_result())
    wm.execute_batch = AsyncMock(
        return_value={"w-1": _make_result("w-1", "completed", "first output")}
    )
    wm.list_workers = AsyncMock(return_value=[{"worker_id": "w-1"}, {"worker_id": "w-2"}])
    wm.monitor_workers = AsyncMock(return_value={"w-1": MagicMock(value="running")})
    wm.collect_results = AsyncMock(return_value={"w-1": _make_result()})
    wm.close_worker = AsyncMock()
    wm.close_all = AsyncMock()
    wm.health_check = AsyncMock(return_value={"status": "healthy", "worker_count": 2})
    return wm


@pytest.fixture
def registered_mcp(mock_mcp, mock_worker_manager):
    """Register worker tools on the mock MCP and return the registry."""
    register_worker_tools(mock_mcp, mock_worker_manager)
    return mock_mcp


# =============================================================================
# Tool Registration
# =============================================================================


class TestRegistration:
    """Tests for register_worker_tools."""

    def test_all_tools_registered(self, registered_mcp):
        """All 8 worker tools should be registered."""
        expected = {
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
        assert expected.issubset(set(registered_mcp._tools.keys()))


# =============================================================================
# worker_spawn
# =============================================================================


class TestWorkerSpawn:
    """Tests for the worker_spawn tool."""

    async def test_spawn_returns_worker_ids(self, registered_mcp, mock_worker_manager):
        """Should return list of worker IDs from worker_manager."""
        result = await registered_mcp._tools["worker_spawn"]()
        assert result == ["w-1", "w-2"]
        mock_worker_manager.spawn_workers.assert_awaited_once()

    async def test_spawn_passes_type_and_count(self, registered_mcp, mock_worker_manager):
        """Should pass worker_type and count to the manager."""
        await registered_mcp._tools["worker_spawn"](worker_type="container", count=3)
        mock_worker_manager.spawn_workers.assert_awaited_with(worker_type="container", count=3)

    async def test_spawn_invalid_count_raises(self, registered_mcp):
        """count < 1 should raise ValueError."""
        with pytest.raises(ValueError, match="count must be between 1 and 50"):
            await registered_mcp._tools["worker_spawn"](count=0)

    async def test_spawn_count_too_high_raises(self, registered_mcp):
        """count > 50 should raise ValueError."""
        with pytest.raises(ValueError, match="count must be between 1 and 50"):
            await registered_mcp._tools["worker_spawn"](count=51)


# =============================================================================
# worker_execute
# =============================================================================


class TestWorkerExecute:
    """Tests for the worker_execute tool."""

    async def test_execute_returns_structured_result(self, registered_mcp, mock_worker_manager):
        """Result should contain worker_id, status, output, error, duration, has_output."""
        result = await registered_mcp._tools["worker_execute"](
            worker_id="w-1", prompt="do something"
        )
        assert result["worker_id"] == "w-1"
        assert result["status"] == "completed"
        assert result["output"] == "ok"
        assert result["error"] is None
        assert result["duration"] == 1.5
        assert result["has_output"] is True

    async def test_execute_passes_timeout(self, registered_mcp, mock_worker_manager):
        """Timeout should be passed through to worker_manager."""
        await registered_mcp._tools["worker_execute"](worker_id="w-1", prompt="p", timeout=120)
        call_args = mock_worker_manager.execute_task.await_args
        assert call_args.args[0] == "w-1"
        assert call_args.args[1] == {"prompt": "p", "timeout": 120}

    async def test_execute_invalid_timeout_raises(self, registered_mcp):
        """timeout < 30 should raise ValueError."""
        with pytest.raises(ValueError, match="timeout must be between 30 and 3600"):
            await registered_mcp._tools["worker_execute"](worker_id="w-1", prompt="p", timeout=10)

    async def test_execute_timeout_too_high_raises(self, registered_mcp):
        """timeout > 3600 should raise ValueError."""
        with pytest.raises(ValueError, match="timeout must be between 30 and 3600"):
            await registered_mcp._tools["worker_execute"](worker_id="w-1", prompt="p", timeout=4000)

    async def test_execute_truncates_long_output(self, registered_mcp, mock_worker_manager):
        """Output over 500 chars should be truncated with ellipsis."""
        long_output = "x" * 800
        mock_worker_manager.execute_task = AsyncMock(return_value=_make_result(output=long_output))
        result = await registered_mcp._tools["worker_execute"](worker_id="w-1", prompt="p")
        assert result["output"].endswith("...")
        # 500 chars + "..." = 503
        assert len(result["output"]) == 503

    async def test_execute_short_output_not_truncated(self, registered_mcp, mock_worker_manager):
        """Output <= 500 chars should not be truncated."""
        mock_worker_manager.execute_task = AsyncMock(return_value=_make_result(output="short"))
        result = await registered_mcp._tools["worker_execute"](worker_id="w-1", prompt="p")
        assert result["output"] == "short"


# =============================================================================
# worker_execute_batch
# =============================================================================


class TestWorkerExecuteBatch:
    """Tests for the worker_execute_batch tool."""

    async def test_batch_returns_per_worker_results(self, registered_mcp):
        """Results dict should map each worker_id to its status."""
        result = await registered_mcp._tools["worker_execute_batch"](
            worker_ids=["w-1"], prompts=["do it"]
        )
        assert "w-1" in result
        assert result["w-1"]["status"] == "completed"

    async def test_batch_mismatched_lengths_raises(self, registered_mcp):
        """Mismatched worker_ids/prompts lengths should raise ValueError."""
        with pytest.raises(ValueError, match="worker_ids and prompts must have same length"):
            await registered_mcp._tools["worker_execute_batch"](
                worker_ids=["w-1", "w-2"], prompts=["only one"]
            )

    async def test_batch_passes_through_to_manager(self, registered_mcp, mock_worker_manager):
        """Tasks list should be built from prompts and passed to manager."""
        await registered_mcp._tools["worker_execute_batch"](
            worker_ids=["w-1", "w-2"],
            prompts=["p1", "p2"],
            timeout=120,
        )
        call_args = mock_worker_manager.execute_batch.await_args
        assert call_args.args[0] == ["w-1", "w-2"]
        assert call_args.args[1] == [
            {"prompt": "p1", "timeout": 120},
            {"prompt": "p2", "timeout": 120},
        ]


# =============================================================================
# worker_list
# =============================================================================


class TestWorkerList:
    """Tests for the worker_list tool."""

    async def test_list_returns_workers(self, registered_mcp):
        """Should return the list of workers from the manager."""
        result = await registered_mcp._tools["worker_list"]()
        assert result == [{"worker_id": "w-1"}, {"worker_id": "w-2"}]


# =============================================================================
# worker_monitor
# =============================================================================


class TestWorkerMonitor:
    """Tests for the worker_monitor tool."""

    async def test_monitor_returns_status_map(self, registered_mcp):
        """Result should map each worker_id to its status value."""
        result = await registered_mcp._tools["worker_monitor"]()
        assert result == {"w-1": "running"}

    async def test_monitor_invalid_interval_low_raises(self, registered_mcp):
        """interval < 0.1 should raise ValueError."""
        with pytest.raises(ValueError, match="interval must be between 0.1 and 10.0"):
            await registered_mcp._tools["worker_monitor"](interval=0.05)

    async def test_monitor_invalid_interval_high_raises(self, registered_mcp):
        """interval > 10.0 should raise ValueError."""
        with pytest.raises(ValueError, match="interval must be between 0.1 and 10.0"):
            await registered_mcp._tools["worker_monitor"](interval=15.0)


# =============================================================================
# worker_collect_results
# =============================================================================


class TestWorkerCollectResults:
    """Tests for the worker_collect_results tool."""

    async def test_collect_returns_per_worker_payload(self, registered_mcp):
        """Should return a dict mapping worker_id to result fields."""
        result = await registered_mcp._tools["worker_collect_results"]()
        assert "w-1" in result
        assert result["w-1"]["status"] == "completed"
        assert result["w-1"]["duration"] == 1.5
        assert result["w-1"]["has_output"] is True


# =============================================================================
# worker_close
# =============================================================================


class TestWorkerClose:
    """Tests for the worker_close tool."""

    async def test_close_success(self, registered_mcp, mock_worker_manager):
        """Successful close should return success=True."""
        result = await registered_mcp._tools["worker_close"](worker_id="w-1")
        assert result == {"success": True, "worker_id": "w-1"}
        mock_worker_manager.close_worker.assert_awaited_with("w-1")

    async def test_close_handles_exception(self, registered_mcp, mock_worker_manager):
        """If close_worker raises, the tool should return success=False."""
        mock_worker_manager.close_worker.side_effect = RuntimeError("nope")
        result = await registered_mcp._tools["worker_close"](worker_id="w-bad")
        assert result["success"] is False
        assert result["worker_id"] == "w-bad"
        assert "nope" in result["error"]


# =============================================================================
# worker_close_all
# =============================================================================


class TestWorkerCloseAll:
    """Tests for the worker_close_all tool."""

    async def test_close_all_closes_listed_workers(self, registered_mcp, mock_worker_manager):
        """Should close all workers returned from list_workers()."""
        result = await registered_mcp._tools["worker_close_all"]()
        assert result == {"closed_count": 2}
        assert mock_worker_manager.close_worker.await_count == 2

    async def test_close_all_empty(self, registered_mcp, mock_worker_manager):
        """Empty worker list should return closed_count=0."""
        mock_worker_manager.list_workers = AsyncMock(return_value=[])
        result = await registered_mcp._tools["worker_close_all"]()
        assert result == {"closed_count": 0}
        mock_worker_manager.close_worker.assert_not_awaited()


# =============================================================================
# worker_health
# =============================================================================


class TestWorkerHealth:
    """Tests for the worker_health tool."""

    async def test_health_returns_manager_payload(self, registered_mcp):
        """Should return whatever worker_manager.health_check returns."""
        result = await registered_mcp._tools["worker_health"]()
        assert result == {"status": "healthy", "worker_count": 2}
