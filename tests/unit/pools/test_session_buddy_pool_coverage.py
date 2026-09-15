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

    from mahavishnu.pools.session_buddy_pool import SessionBuddyPool
    from mahavishnu.pools.base import PoolConfig as _Cfg

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
    from mahavishnu.pools.session_buddy_pool import SessionBuddyPool
    from mahavishnu.pools.base import PoolConfig as _Cfg

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
    pool = make_pool({"result": ["w1", "w2", "w3"]})
    result = await pool.start()
    assert result == pool.pool_id
    assert pool._status == PoolStatus.RUNNING
    assert len(pool._workers) == 3
    # call_tool invoked with worker_spawn
    pool._mcp.call_tool.assert_awaited()
    assert pool._mcp.call_tool.await_args.args[0] == "worker_spawn"


@pytest.mark.asyncio
async def test_start_pool_non_list_worker_ids(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    """start() tolerates a non-list 'result' by treating it as zero workers."""
    pool = make_pool({"result": "unexpected"})
    await pool.start()
    assert pool._workers == {} and pool._status == PoolStatus.RUNNING


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
    pool = make_pool({"result": {"status": "completed", "output": "ok", "error": None}})
    pool._workers = {"w1": "worker_w1"}
    result = await pool.execute_task({"prompt": "do thing", "timeout": 60})
    assert result["status"] == "completed" and result["output"] == "ok"
    assert result["error"] is None
    assert pool._tasks_completed == 1 and pool._tasks_failed == 0


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
    pool._workers = {"w1": "worker_w1"}
    result = await pool.execute_task({"prompt": "do thing"})
    assert result["status"] == "failed" and result["error"] == "upstream gone"
    assert pool._tasks_failed == 1


# --- execute_batch, scale, health, metrics, memory, stop ---


@pytest.mark.asyncio
async def test_execute_batch_branches(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool(
        {
            "result": {
                "0": {"status": "completed", "output": "a", "error": None},
                "1": {"status": "failed", "output": None, "error": "boom"},
            }
        }
    )
    pool._workers = {"w1": "w1", "w2": "w2"}
    results = await pool.execute_batch([{"prompt": "a"}, {"prompt": "b"}])
    assert results["0"]["status"] == "completed" and results["1"]["status"] == "failed"
    assert pool._tasks_completed == 1 and pool._tasks_failed == 1


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
    [({"w1": "w1", "w2": "w2", "w3": "w3"}, "healthy"), ({"w1": "w1"}, "degraded")],
)
async def test_health_check_status_for_worker_count(
    active_workers: dict[str, str],
    expected_status: str,
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool({"result": {"ok": True}})
    pool._workers = active_workers
    assert (await pool.health_check())["status"] == expected_status


@pytest.mark.asyncio
async def test_health_check_error_path(
    make_pool: Callable[..., SessionBuddyPool],
) -> None:
    pool = make_pool(MCPServerError("down"))
    health = await pool.health_check()
    assert health["status"] == "unhealthy" and health["error"] == "down"


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
