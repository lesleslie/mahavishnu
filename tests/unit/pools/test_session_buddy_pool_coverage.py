"""Coverage-push tests for SessionBuddyPool; complements the basic pool tests by exercising the call_tool boundary and _await_if_needed helper dispatch.

Phase 3 (REQ-004): the transport was rewired from ``httpx2.AsyncClient``
to ``CommonMCPClient``. The coverage harness now patches
``CommonMCPClient`` instead of injecting an ``httpx.MockTransport``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from mcp_common.exceptions import MCPServerError
import pytest

from mahavishnu.pools.base import PoolConfig, PoolMetrics, PoolStatus
from mahavishnu.pools.session_buddy_pool import SessionBuddyPool, _await_if_needed


@pytest.fixture
def config() -> PoolConfig:
    return PoolConfig(
        name="test-session-buddy", pool_type="session-buddy",
        min_workers=3, max_workers=3, worker_type="terminal-claude",
    )


@pytest.fixture
def make_pool(config: PoolConfig) -> Callable[..., SessionBuddyPool]:
    """Factory: build a SessionBuddyPool whose CommonMCPClient.call_tool is mocked.

    Returns ``make_pool(call_tool_side_effect)``. ``call_tool_side_effect`` is
    either a return value, an exception class, or a callable ``(name,
    arguments) -> value|raise``. The mock auto-acks ``aclose`` calls.
    """

    def _factory(call_tool_side_effect: Any = None) -> SessionBuddyPool:
        with patch("mahavishnu.pools.session_buddy_pool.CommonMCPClient") as mock_cls:
            mock_client = MagicMock()
            if callable(call_tool_side_effect) and not isinstance(
                call_tool_side_effect, type
            ):
                # callable (name, args) -> Any
                async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
                    return call_tool_side_effect(name, arguments)
            elif isinstance(call_tool_side_effect, type) and issubclass(
                call_tool_side_effect, BaseException
            ):

                async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
                    raise call_tool_side_effect(name)
            elif isinstance(call_tool_side_effect, BaseException):

                async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
                    raise call_tool_side_effect
            else:

                async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
                    return call_tool_side_effect

            mock_client.call_tool = AsyncMock(side_effect=call_tool)
            mock_client.aclose = AsyncMock()
            mock_cls.return_value = mock_client
            pool = SessionBuddyPool(config=config)
            pool._mcp = mock_client
            return pool

    return _factory


# --- _await_if_needed ---


@pytest.mark.asyncio
async def test_await_if_needed_with_sync_value() -> None:
    assert await _await_if_needed({"result": [1, 2, 3]}) == {"result": [1, 2, 3]}


@pytest.mark.asyncio
async def test_await_if_needed_with_awaitable_value() -> None:
    async def _coro() -> str:
        return "resolved"

    assert await _await_if_needed(_coro()) == "resolved"


# --- _call_mcp_tool ---


@pytest.mark.asyncio
async def test_call_mcp_tool_returns_payload() -> None:
    """call_tool returns the raw payload; _call_mcp_tool wraps it as-is."""
    payload = {"result": [{"status": "completed", "output": "ok", "error": None}]}

    from mahavishnu.pools.base import PoolConfig as _Cfg
    from mahavishnu.pools.session_buddy_pool import SessionBuddyPool

    pool = SessionBuddyPool(
        config=_Cfg(name="x", pool_type="session-buddy", min_workers=1, max_workers=1)
    )
    pool._mcp = MagicMock()
    pool._mcp.call_tool = AsyncMock(return_value=payload)

    assert await pool._call_mcp_tool("worker_spawn", {"count": 3}) == payload


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc_cls",
    [MCPServerError, RuntimeError],
)
async def test_call_mcp_tool_propagates_server_error(
    exc_cls: type[BaseException],
) -> None:
    from mahavishnu.pools.base import PoolConfig as _Cfg
    from mahavishnu.pools.session_buddy_pool import SessionBuddyPool

    pool = SessionBuddyPool(
        config=_Cfg(name="x", pool_type="session-buddy", min_workers=1, max_workers=1)
    )
    pool._mcp = MagicMock()
    pool._mcp.call_tool = AsyncMock(side_effect=exc_cls("upstream down"))

    with pytest.raises(exc_cls):
        await pool._call_mcp_tool("worker_spawn", {"count": 3})


# --- start ---


@pytest.mark.asyncio
async def test_start_pool_happy_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """start() calls create_pool and synthesizes 3 worker_ids from returned pool_id."""
    pool = make_pool({
        "success": True,
        "pool_id": "sbpool-abc123",
        "status": "running",
        "workers_count": 3,
        "queue_size": 0,
    })
    await pool.start()
    assert len(pool._workers) == 3
    # call_tool invoked with create_pool
    pool._mcp.call_tool.assert_awaited()
    assert pool._mcp.call_tool.await_args.args[0] == "create_pool"
    # Worker IDs are derived as {pool_id}-worker-{i}
    assert set(pool._workers.keys()) == {
        "sbpool-abc123-worker-0",
        "sbpool-abc123-worker-1",
        "sbpool-abc123-worker-2",
    }


@pytest.mark.asyncio
async def test_start_pool_non_list_worker_ids(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """start() tolerates success=False by raising (audit hardening)."""
    pool = make_pool({"success": False, "error": "pool limit reached"})
    with pytest.raises(MCPServerError):
        await pool.start()
    assert pool._status == PoolStatus.FAILED


@pytest.mark.asyncio
async def test_start_pool_propagates_server_error(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool(MCPServerError("down"))
    with pytest.raises(MCPServerError):
        await pool.start()
    assert pool._status == PoolStatus.FAILED


# --- execute_task ---


@pytest.mark.asyncio
async def test_execute_task_happy_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({
        "success": True,
        "pool_id": "sbpool-abc",
        "worker_id": "sbpool-abc-worker-1",
        "result": {"status": "completed", "output": "ok"},
    })
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.execute_task({"prompt": "do thing", "timeout": 60})
    assert result["status"] == "completed"
    assert result["output"] == {"status": "completed", "output": "ok"}
    assert result["error"] is None
    # session-buddy's actual worker_id (more authoritative than our synthetic)
    assert result["worker_id"] == "sbpool-abc-worker-1"
    assert pool._tasks_completed == 1 and pool._tasks_failed == 0
    last_call = pool._mcp.call_tool.await_args_list[-1]
    assert last_call.args[0] == "execute_on_pool"


@pytest.mark.asyncio
async def test_execute_task_no_workers(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({"result": {}})
    with pytest.raises(RuntimeError, match="No workers"):
        await pool.execute_task({"prompt": "noop"})


@pytest.mark.asyncio
async def test_execute_task_server_error_returns_failed_envelope(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool(MCPServerError("upstream gone"))
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.execute_task({"prompt": "do thing"})
    assert result["status"] == "failed"
    assert result["error"] == "upstream gone"
    assert result["output"] is None
    assert pool._tasks_failed == 1
    assert result["worker_id"] == "sbpool-abc-worker-0"


# --- execute_batch, scale, health, metrics, memory, stop ---


@pytest.mark.asyncio
async def test_execute_batch_branches(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """execute_batch() returns per-task envelopes aligned to input order."""
    pool = make_pool({
        "success": True,
        "pool_id": "sbpool-abc",
        "results_count": 2,
        "results": [
            {"status": "completed", "output": "r1", "error": None},
            {"status": "failed", "output": None, "error": "boom"},
        ],
    })
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    result = await pool.execute_batch([
        {"task_id": "0", "prompt": "first"},
        {"task_id": "1", "prompt": "second"},
    ])
    assert result["0"]["status"] == "completed"
    assert result["0"]["output"] == "r1"
    assert result["1"]["status"] == "failed"
    assert result["1"]["error"] == "boom"
    assert pool._tasks_completed == 1
    assert pool._tasks_failed == 1
    last_call = pool._mcp.call_tool.await_args_list[-1]
    assert last_call.args[0] == "execute_batch_on_pool"


@pytest.mark.asyncio
async def test_execute_batch_rejects_multiple_working_dirs(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """execute_batch() fails fast on >1 distinct working_dir (audit hardening)."""
    pool = make_pool({"success": True, "results": []})
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    with pytest.raises(ValueError, match="at most one distinct working_dir"):
        await pool.execute_batch([
            {"prompt": "a", "working_dir": "/path/one"},
            {"prompt": "b", "working_dir": "/path/two"},
        ])


@pytest.mark.asyncio
async def test_execute_batch_server_error(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool(MCPServerError("nope"))
    pool._workers = {"w1": "w1", "w2": "w2"}
    results = await pool.execute_batch([{"prompt": "x"}, {"prompt": "y"}])
    assert set(results.keys()) == {"0", "1"}
    for r in results.values():
        assert r["status"] == "failed" and r["pool_id"] == pool.pool_id
    assert pool._tasks_failed == 2


@pytest.mark.asyncio
async def test_scale_raises_not_implemented(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({"result": {}})
    with pytest.raises(NotImplementedError, match="3"):
        await pool.scale(5)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("active_workers", "expected_status"),
    [
        (
            {
                "sbpool-abc-worker-0": "w0",
                "sbpool-abc-worker-1": "w1",
                "sbpool-abc-worker-2": "w2",
            },
            "healthy",
        ),
        ({"sbpool-abc-worker-0": "w0"}, "degraded"),
    ],
)
async def test_health_check_status_for_worker_count(
    active_workers: dict[str, str],
    expected_status: str,
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({"success": True, "health": {"status": "healthy"}})
    pool._workers = active_workers
    assert (await pool.health_check())["status"] == expected_status


@pytest.mark.asyncio
async def test_health_check_error_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool(MCPServerError("down"))
    pool._workers = {"sbpool-abc-worker-0": "worker_0"}
    health = await pool.health_check()
    # Local status wins (1 worker < min_workers=3 → degraded), but error
    # key is propagated from the upstream MCPServerError.
    assert health["status"] == "degraded"
    assert health["error"] == "down"


@pytest.mark.asyncio
async def test_health_check_with_empty_workers_no_upstream_call(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """health_check() skips upstream call when pool_id is empty (audit hardening)."""
    pool = make_pool({"success": True})
    pool._workers = {}  # never started
    result = await pool.health_check()
    assert result["status"] == "unhealthy"
    assert result["worker_health"] is None
    # No upstream call should have been made.
    pool._mcp.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_health_check_with_workers_calls_check_pool_health(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({
        "success": True,
        "status": "healthy",
        "workers_healthy": 3,
        "workers_total": 3,
    })
    pool._workers = {
        "sbpool-abc-worker-0": "worker_0",
        "sbpool-abc-worker-1": "worker_1",
        "sbpool-abc-worker-2": "worker_2",
    }
    result = await pool.health_check()
    assert result["status"] == "healthy"
    assert result["worker_health"]["status"] == "healthy"
    last_call = pool._mcp.call_tool.await_args_list[-1]
    assert last_call.args[0] == "check_pool_health"


@pytest.mark.asyncio
async def test_get_metrics_returns_poolmetrics(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({"result": {"ok": True}})
    pool._tasks_completed = 3
    pool._tasks_failed = 1
    pool._task_durations = [0.1, 0.2, 0.3, 0.4]
    pool._workers = {"w1": "w1"}
    metrics = await pool.get_metrics()
    assert isinstance(metrics, PoolMetrics)
    assert metrics.tasks_completed == 3 and metrics.tasks_failed == 1
    assert metrics.avg_task_duration == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_collect_memory_happy_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({"result": {"conversations": [{"id": "c1"}, {"id": "c2"}]}})
    assert await pool.collect_memory() == [{"id": "c1"}, {"id": "c2"}]


@pytest.mark.asyncio
async def test_collect_memory_error_returns_empty_list(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """collect_memory swallows MCPServerError and returns [] (graceful degradation)."""
    pool = make_pool(MCPServerError("down"))
    assert await pool.collect_memory() == []


@pytest.mark.asyncio
async def test_stop_closes_client_and_marks_stopped(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """stop() always transitions to STOPPED even if worker_close_all fails."""
    pool = make_pool(MCPServerError("gone"))
    await pool.stop()
    assert pool._status == PoolStatus.STOPPED
    pool._mcp.aclose.assert_awaited_once()
