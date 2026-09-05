"""Coverage-push tests for SessionBuddyPool; complements the basic pool tests by exercising httpx MockTransport paths and _await_if_needed helper dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import httpx2 as httpx
import pytest

from mahavishnu.pools.base import PoolConfig, PoolMetrics, PoolStatus
from mahavishnu.pools.session_buddy_pool import SessionBuddyPool, _await_if_needed

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def config() -> PoolConfig:
    return PoolConfig(
        name="test-session-buddy", pool_type="session-buddy",
        min_workers=3, max_workers=3, worker_type="terminal-claude",
    )


@pytest.fixture
def make_pool(config: PoolConfig) -> Callable[[Handler], SessionBuddyPool]:
    """Factory: build a SessionBuddyPool whose AsyncClient uses a MockTransport."""

    def _factory(handler: Handler) -> SessionBuddyPool:
        transport = httpx.MockTransport(handler)
        real_async_client = httpx.AsyncClient

        def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
            kwargs.setdefault("transport", transport)
            return real_async_client(*args, **kwargs)

        with patch("mahavishnu.pools.session_buddy_pool.httpx.AsyncClient", new=factory):
            return SessionBuddyPool(config=config)

    return _factory


def _static(response: httpx.Response) -> Handler:
    return lambda req: response


def _ok(payload: Any) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _boom(exc: Exception) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc
    return handler


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
@pytest.mark.parametrize(
    ("status_code", "body", "expect_error"),
    [
        (200, {"result": [{"status": "completed", "output": "ok", "error": None}]}, None),
        (500, {"detail": "server exploded"}, httpx.HTTPStatusError),
        (404, {"detail": "no such tool"}, httpx.HTTPStatusError),
    ],
)
async def test_call_mcp_tool_http_responses(
    status_code: int,
    body: dict[str, Any],
    expect_error: type[Exception] | None,
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(lambda req: httpx.Response(status_code, json=body))
    if expect_error is not None:
        with pytest.raises(expect_error):
            await pool._call_mcp_tool("worker_spawn", {"count": 3})
    else:
        assert await pool._call_mcp_tool("worker_spawn", {"count": 3}) == body


@pytest.mark.asyncio
async def test_call_mcp_tool_network_error(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_boom(httpx.ConnectError("refused")))
    with pytest.raises(httpx.ConnectError):
        await pool._call_mcp_tool("worker_spawn", {"count": 3})


@pytest.mark.asyncio
async def test_call_mcp_tool_timeout(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_boom(httpx.TimeoutException("t")))
    with pytest.raises(httpx.TimeoutException):
        await pool._call_mcp_tool("worker_spawn", {"count": 3})


# --- start ---


@pytest.mark.asyncio
async def test_start_pool_happy_path(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    seen: list[httpx.Request] = []
    pool = make_pool(
        lambda req: (seen.append(req), _ok({"result": ["w1", "w2", "w3"]}))[1]
    )
    result = await pool.start()
    assert result == pool.pool_id
    assert pool._status == PoolStatus.RUNNING
    assert len(pool._workers) == 3
    assert seen[0].method == "POST" and seen[0].url.path.endswith("/tools/call")


@pytest.mark.asyncio
async def test_start_pool_non_list_worker_ids(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    """start() tolerates a non-list 'result' by treating it as zero workers."""
    pool = make_pool(_static(_ok({"result": "unexpected"})))
    await pool.start()
    assert pool._workers == {} and pool._status == PoolStatus.RUNNING


@pytest.mark.asyncio
async def test_start_pool_propagates_http_error(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_boom(httpx.ConnectError("down")))
    with pytest.raises(httpx.ConnectError):
        await pool.start()
    assert pool._status == PoolStatus.FAILED


# --- execute_task ---


@pytest.mark.asyncio
async def test_execute_task_happy_path(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(
        _static(_ok({"result": {"status": "completed", "output": "ok", "error": None}}))
    )
    pool._workers = {"w1": "worker_w1"}
    result = await pool.execute_task({"prompt": "do thing", "timeout": 60})
    assert result["status"] == "completed" and result["output"] == "ok"
    assert result["error"] is None
    assert pool._tasks_completed == 1 and pool._tasks_failed == 0


@pytest.mark.asyncio
async def test_execute_task_no_workers(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_static(_ok({"result": {}})))
    with pytest.raises(RuntimeError, match="No workers"):
        await pool.execute_task({"prompt": "noop"})


@pytest.mark.asyncio
async def test_execute_task_http_error_returns_failed_envelope(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_boom(httpx.ConnectError("upstream gone")))
    pool._workers = {"w1": "worker_w1"}
    result = await pool.execute_task({"prompt": "do thing"})
    assert result["status"] == "failed" and result["error"] == "upstream gone"
    assert pool._tasks_failed == 1


# --- execute_batch, scale, health, metrics, memory, stop ---


@pytest.mark.asyncio
async def test_execute_batch_branches(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_static(_ok({
        "result": {
            "0": {"status": "completed", "output": "a", "error": None},
            "1": {"status": "failed", "output": None, "error": "boom"},
        }
    })))
    pool._workers = {"w1": "w1", "w2": "w2"}
    results = await pool.execute_batch([{"prompt": "a"}, {"prompt": "b"}])
    assert results["0"]["status"] == "completed" and results["1"]["status"] == "failed"
    assert pool._tasks_completed == 1 and pool._tasks_failed == 1


@pytest.mark.asyncio
async def test_execute_batch_http_error(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_boom(httpx.ConnectError("nope")))
    pool._workers = {"w1": "w1", "w2": "w2"}
    results = await pool.execute_batch([{"prompt": "x"}, {"prompt": "y"}])
    assert set(results.keys()) == {"0", "1"}
    for r in results.values():
        assert r["status"] == "failed" and r["pool_id"] == pool.pool_id
    assert pool._tasks_failed == 2


@pytest.mark.asyncio
async def test_scale_raises_not_implemented(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_static(_ok({"result": {}})))
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
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_static(_ok({"result": {"ok": True}})))
    pool._workers = active_workers
    assert (await pool.health_check())["status"] == expected_status


@pytest.mark.asyncio
async def test_health_check_error_path(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_boom(httpx.ConnectError("down")))
    health = await pool.health_check()
    assert health["status"] == "unhealthy" and health["error"] == "down"


@pytest.mark.asyncio
async def test_get_metrics_returns_poolmetrics(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_static(_ok({"result": {"ok": True}})))
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
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    pool = make_pool(_static(_ok({"result": {"conversations": [{"id": "c1"}, {"id": "c2"}]}})))
    assert await pool.collect_memory() == [{"id": "c1"}, {"id": "c2"}]


@pytest.mark.asyncio
async def test_collect_memory_error_returns_empty_list(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    """collect_memory swallows HTTPError and returns [] (graceful degradation)."""
    pool = make_pool(_boom(httpx.ConnectError("down")))
    assert await pool.collect_memory() == []


@pytest.mark.asyncio
async def test_stop_closes_client_and_marks_stopped(
    make_pool: Callable[[Handler], SessionBuddyPool],
) -> None:
    """stop() always transitions to STOPPED even if worker_close_all fails."""
    pool = make_pool(_boom(httpx.ConnectError("gone")))
    await pool.stop()
    assert pool._status == PoolStatus.STOPPED
