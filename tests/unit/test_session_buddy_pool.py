"""Tests for mahavishnu/pools/session_buddy_pool.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from mahavishnu.pools.base import PoolConfig, PoolStatus
from mahavishnu.pools.session_buddy_pool import SessionBuddyPool, _await_if_needed

# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------


def _make_pool(
    url: str = "http://localhost:8678/mcp",
    max_workers: int = 3,
) -> SessionBuddyPool:
    config = PoolConfig(
        name="test-pool",
        pool_type="session-buddy",
        min_workers=1,
        max_workers=max_workers,
    )
    return SessionBuddyPool(config=config, session_buddy_url=url, max_workers=max_workers)


# ---------------------------------------------------------------------------
# _await_if_needed
# ---------------------------------------------------------------------------


class TestAwaitIfNeeded:
    @pytest.mark.asyncio
    async def test_non_awaitable_returned_as_is(self) -> None:
        result = await _await_if_needed(42)
        assert result == 42

    @pytest.mark.asyncio
    async def test_awaitable_is_awaited(self) -> None:
        async def coro():
            return "done"

        result = await _await_if_needed(coro())
        assert result == "done"


# ---------------------------------------------------------------------------
# SessionBuddyPool.__init__
# ---------------------------------------------------------------------------


class TestSessionBuddyPoolInit:
    def test_default_url_and_workers(self) -> None:
        pool = _make_pool()
        assert pool.session_buddy_url == "http://localhost:8678/mcp"
        assert pool.max_workers == 3
        assert pool._tasks_completed == 0
        assert pool._tasks_failed == 0
        assert pool._task_durations == []
        assert pool._status == PoolStatus.PENDING


# ---------------------------------------------------------------------------
# _call_mcp_tool
# ---------------------------------------------------------------------------


class TestCallMcpTool:
    @pytest.mark.asyncio
    async def test_posts_and_returns_json(self) -> None:
        pool = _make_pool()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json = MagicMock(return_value={"result": ["w1", "w2"]})
        pool._mcp_client.post = AsyncMock(return_value=mock_response)

        result = await pool._call_mcp_tool("worker_spawn", {"count": 2})
        assert result == {"result": ["w1", "w2"]}
        pool._mcp_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_http_error_on_bad_status(self) -> None:
        pool = _make_pool()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())
        )
        pool._mcp_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(httpx.HTTPStatusError):
            await pool._call_mcp_tool("worker_spawn", {})


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    @pytest.mark.asyncio
    async def test_start_success(self) -> None:
        pool = _make_pool()
        pool._call_mcp_tool = AsyncMock(return_value={"result": ["w0", "w1", "w2"]})

        pool_id = await pool.start()
        assert pool_id == pool.pool_id
        assert pool._status == PoolStatus.RUNNING
        assert len(pool._workers) == 3

    @pytest.mark.asyncio
    async def test_start_non_list_result_uses_empty(self) -> None:
        pool = _make_pool()
        pool._call_mcp_tool = AsyncMock(return_value={"result": None})

        await pool.start()
        assert pool._workers == {}
        assert pool._status == PoolStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_http_error_sets_failed_status(self) -> None:
        pool = _make_pool()
        pool._call_mcp_tool = AsyncMock(side_effect=httpx.HTTPError("connection refused"))

        with pytest.raises(httpx.HTTPError):
            await pool.start()
        assert pool._status == PoolStatus.FAILED


# ---------------------------------------------------------------------------
# execute_task()
# ---------------------------------------------------------------------------


class TestExecuteTask:
    @pytest.mark.asyncio
    async def test_no_workers_raises(self) -> None:
        pool = _make_pool()
        with pytest.raises(RuntimeError, match="No workers available"):
            await pool.execute_task({"prompt": "hello"})

    @pytest.mark.asyncio
    async def test_success_tracks_completed(self) -> None:
        pool = _make_pool()
        pool._workers = {"w0": "worker_w0"}
        pool._call_mcp_tool = AsyncMock(
            return_value={"result": {"status": "completed", "output": "ok"}}
        )

        result = await pool.execute_task({"prompt": "run this"})
        assert result["status"] == "completed"
        assert result["output"] == "ok"
        assert pool._tasks_completed == 1
        assert pool._tasks_failed == 0
        assert len(pool._task_durations) == 1

    @pytest.mark.asyncio
    async def test_non_completed_status_tracks_failed(self) -> None:
        pool = _make_pool()
        pool._workers = {"w0": "worker_w0"}
        pool._call_mcp_tool = AsyncMock(
            return_value={"result": {"status": "error", "error": "oops"}}
        )

        result = await pool.execute_task({"prompt": "x"})
        assert result["status"] == "error"
        assert pool._tasks_failed == 1

    @pytest.mark.asyncio
    async def test_http_error_returns_failed_dict(self) -> None:
        pool = _make_pool()
        pool._workers = {"w0": "worker_w0"}
        pool._call_mcp_tool = AsyncMock(side_effect=httpx.HTTPError("network error"))

        result = await pool.execute_task({"prompt": "x"})
        assert result["status"] == "failed"
        assert "network error" in result["error"]
        assert pool._tasks_failed == 1


# ---------------------------------------------------------------------------
# execute_batch()
# ---------------------------------------------------------------------------


class TestExecuteBatch:
    @pytest.mark.asyncio
    async def test_no_workers_raises(self) -> None:
        pool = _make_pool()
        with pytest.raises(RuntimeError, match="No workers available"):
            await pool.execute_batch([{"prompt": "x"}])

    @pytest.mark.asyncio
    async def test_success_returns_task_results_with_pool_id(self) -> None:
        pool = _make_pool()
        pool._workers = {"w0": "worker_w0", "w1": "worker_w1"}
        pool._call_mcp_tool = AsyncMock(
            return_value={"result": {"t0": {"status": "completed"}, "t1": {"status": "error"}}}
        )

        results = await pool.execute_batch([{"prompt": "a"}, {"prompt": "b"}])
        assert "t0" in results
        assert results["t0"]["pool_id"] == pool.pool_id
        assert pool._tasks_completed == 1
        assert pool._tasks_failed == 1

    @pytest.mark.asyncio
    async def test_http_error_returns_all_failed(self) -> None:
        pool = _make_pool()
        pool._workers = {"w0": "worker_w0"}
        pool._call_mcp_tool = AsyncMock(side_effect=httpx.HTTPError("batch error"))

        tasks = [{"prompt": "x"}, {"prompt": "y"}]
        results = await pool.execute_batch(tasks)
        assert all(r["status"] == "failed" for r in results.values())
        assert pool._tasks_failed == 2


# ---------------------------------------------------------------------------
# scale()
# ---------------------------------------------------------------------------


class TestScale:
    @pytest.mark.asyncio
    async def test_scale_always_raises(self) -> None:
        pool = _make_pool()
        with pytest.raises(NotImplementedError, match="fixed worker count"):
            await pool.scale(5)


# ---------------------------------------------------------------------------
# health_check()
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_when_workers_meet_min(self) -> None:
        pool = _make_pool()
        pool._workers = {"w0": "x", "w1": "y"}
        pool._call_mcp_tool = AsyncMock(return_value={"result": {"status": "healthy"}})

        result = await pool.health_check()
        assert result["status"] == "healthy"
        assert result["workers_active"] == 2

    @pytest.mark.asyncio
    async def test_degraded_when_below_min_workers(self) -> None:
        pool = _make_pool()
        pool._workers = {}  # below min_workers=1
        pool._call_mcp_tool = AsyncMock(return_value={"result": {}})

        result = await pool.health_check()
        assert result["status"] in ("degraded", "unhealthy")

    @pytest.mark.asyncio
    async def test_http_error_returns_unhealthy(self) -> None:
        pool = _make_pool()
        pool._call_mcp_tool = AsyncMock(side_effect=httpx.HTTPError("health check failed"))

        result = await pool.health_check()
        assert result["status"] == "unhealthy"
        assert "health check failed" in result["error"]


# ---------------------------------------------------------------------------
# get_metrics()
# ---------------------------------------------------------------------------


class TestGetMetrics:
    @pytest.mark.asyncio
    async def test_avg_duration_calculated(self) -> None:
        pool = _make_pool()
        pool._workers = {"w0": "x"}
        pool._task_durations = [1.0, 3.0]
        pool._tasks_completed = 2
        pool._call_mcp_tool = AsyncMock(return_value={"result": {}})

        metrics = await pool.get_metrics()
        assert metrics.avg_task_duration == 2.0
        assert metrics.tasks_completed == 2

    @pytest.mark.asyncio
    async def test_no_tasks_gives_zero_avg(self) -> None:
        pool = _make_pool()
        pool._call_mcp_tool = AsyncMock(return_value={"result": {}})

        metrics = await pool.get_metrics()
        assert metrics.avg_task_duration == 0.0


# ---------------------------------------------------------------------------
# collect_memory()
# ---------------------------------------------------------------------------


class TestCollectMemory:
    @pytest.mark.asyncio
    async def test_success_returns_conversations(self) -> None:
        pool = _make_pool()
        pool._call_mcp_tool = AsyncMock(
            return_value={"result": {"conversations": [{"id": "conv1"}, {"id": "conv2"}]}}
        )

        result = await pool.collect_memory()
        assert len(result) == 2
        assert result[0]["id"] == "conv1"

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_list(self) -> None:
        pool = _make_pool()
        pool._call_mcp_tool = AsyncMock(side_effect=httpx.HTTPError("memory error"))

        result = await pool.collect_memory()
        assert result == []


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sets_stopped_status(self) -> None:
        pool = _make_pool()
        pool._call_mcp_tool = AsyncMock(return_value={"result": "ok"})
        pool._mcp_client.aclose = AsyncMock()

        await pool.stop()
        assert pool._status == PoolStatus.STOPPED

    @pytest.mark.asyncio
    async def test_stop_handles_http_error(self) -> None:
        pool = _make_pool()
        pool._call_mcp_tool = AsyncMock(side_effect=httpx.HTTPError("close error"))
        pool._mcp_client.aclose = AsyncMock()

        await pool.stop()  # should not raise
        assert pool._status == PoolStatus.STOPPED
