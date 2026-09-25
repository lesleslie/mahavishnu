"""Tests for the subagent_marker hook wrapping SessionBuddyPool.execute_task
and SessionBuddyPool.execute_batch.

The hook fires ``subagent_marker mark`` before worker_execute and
``subagent_marker clear`` after — both in a try/finally so the consumer
side (``SubagentDetector.is_active``) never sees a stale lockfile
even when worker_execute raises. ``working_dir`` is opt-in on the task
dict; tasks without it get no marker (preserves existing behavior).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.pools.base import PoolConfig
from mahavishnu.pools.session_buddy_pool import SessionBuddyPool


@pytest.fixture
def config() -> PoolConfig:
    return PoolConfig(
        name="test-session-buddy-hook",
        pool_type="session-buddy",
        min_workers=3,
        max_workers=3,
        worker_type="terminal-claude",
    )


@pytest.fixture
def make_pool(config: PoolConfig):
    """Build a SessionBuddyPool whose CommonMCPClient.call_tool records every call.

    Returns ``(pool, calls)`` where ``calls`` is a list populated with
    ``(tool_name, arguments)`` in invocation order. Per-tool responses
    can be configured via the optional ``responses`` dict mapping
    ``tool_name -> return_value``. ``worker_execute`` defaults to a
    ``{"result": {"status": "completed", "output": "ok", "error": None}}``
    payload.
    """

    def _factory(
        responses: dict[str, Any] | None = None,
        worker_execute_raises: BaseException | None = None,
    ):
        calls: list[tuple[str, dict[str, Any]]] = []
        responses = responses or {}
        default_worker_result = {
            "success": True,
            "pool_id": "test-pool",
            "worker_id": "test-pool-worker-0",
            "result": {"output": "ok"},
        }

        default_batch_result = {
            "success": True,
            "pool_id": "test-pool",
            "results_count": 2,
            "results": [
                {"status": "completed", "output": "r1", "error": None},
                {"status": "completed", "output": "r2", "error": None},
            ],
        }

        async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
            calls.append((name, arguments))
            if name == "execute_on_pool" and worker_execute_raises is not None:
                raise worker_execute_raises
            if name in responses:
                return responses[name]
            if name == "execute_on_pool":
                return default_worker_result
            if name == "execute_batch_on_pool":
                return default_batch_result
            if name == "subagent_marker":
                return {"success": True, "action": arguments.get("action")}
            return {"result": {}}

        with patch("mahavishnu.pools.session_buddy_pool.CommonMCPClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.call_tool = AsyncMock(side_effect=call_tool)
            mock_client.aclose = AsyncMock()
            mock_cls.return_value = mock_client
            pool = SessionBuddyPool(config=config)
            pool._mcp = mock_client
            pool._workers = {"w1": "worker_w1", "w2": "worker_w2", "w3": "worker_w3"}
            return pool, calls

    return _factory


def _tool_names(calls: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in calls]


# ---------------------------------------------------------------------------
# execute_task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_task_with_working_dir_wraps_with_marker(make_pool) -> None:
    """execute_task with working_dir calls subagent_marker mark, then worker_execute, then clear."""
    pool, calls = make_pool()

    await pool.execute_task(
        {"prompt": "do work", "working_dir": "/path/to/project"}
    )

    names = _tool_names(calls)
    assert names == ["subagent_marker", "execute_on_pool", "subagent_marker"], names

    # mark args
    assert calls[0][1] == {"working_dir": "/path/to/project", "action": "mark"}
    # clear args
    assert calls[2][1] == {"working_dir": "/path/to/project", "action": "clear"}


@pytest.mark.asyncio
async def test_execute_task_without_working_dir_skips_marker(make_pool) -> None:
    """execute_task without working_dir calls only worker_execute (no marker)."""
    pool, calls = make_pool()

    await pool.execute_task({"prompt": "do work"})

    names = _tool_names(calls)
    assert names == ["execute_on_pool"], names


@pytest.mark.asyncio
async def test_execute_task_clear_runs_when_worker_execute_raises(make_pool) -> None:
    """execute_task's try/finally ensures subagent_marker clear runs even when worker_execute raises."""
    from mcp_common.exceptions import MCPServerError

    pool, calls = make_pool(worker_execute_raises=MCPServerError("worker boom"))

    result = await pool.execute_task(
        {"prompt": "do work", "working_dir": "/path/to/project"}
    )

    # Result dict reflects failure (existing behavior preserved).
    assert result["status"] == "failed"
    assert "worker boom" in result["error"]

    # But the marker was still cleared — consumer won't see a stale lockfile.
    names = _tool_names(calls)
    assert names == ["subagent_marker", "execute_on_pool", "subagent_marker"], names
    assert calls[2][1]["action"] == "clear"


@pytest.mark.asyncio
async def test_execute_task_marker_clear_failure_does_not_propagate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing ``subagent_marker clear`` is logged but does not mask the original result."""
    import logging

    # Configure the mock so subagent_marker raises only on the second call (the clear).
    call_count = {"subagent_marker": 0}

    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        if name == "subagent_marker":
            call_count["subagent_marker"] += 1
            if call_count["subagent_marker"] >= 2:
                raise RuntimeError("clear failed")
            return {"success": True, "action": arguments.get("action")}
        if name == "execute_on_pool":
            return {
                "success": True,
                "pool_id": "test-pool",
                "worker_id": "test-pool-worker-0",
                "result": {"output": "ok"},
            }
        return {"result": {}}

    with patch("mahavishnu.pools.session_buddy_pool.CommonMCPClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(side_effect=call_tool)
        mock_client.aclose = AsyncMock()
        mock_cls.return_value = mock_client
        pool = SessionBuddyPool(
            config=PoolConfig(
                name="x", pool_type="session-buddy",
                min_workers=1, max_workers=1, worker_type="terminal-claude",
            )
        )
        pool._mcp = mock_client
        pool._workers = {"w1": "worker_w1"}

        with caplog.at_level(logging.ERROR):
            result = await pool.execute_task(
                {"prompt": "do work", "working_dir": "/path/to/project"}
            )

    # Original task result still surfaces normally.
    assert result["status"] == "completed"
    # The clear failure was logged.
    assert any(
        "subagent_marker clear failed" in record.message
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# execute_batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_batch_marks_each_working_dir_once(make_pool) -> None:
    """execute_batch marks the (single) shared working_dir once before the batch and clears once after."""
    pool, calls = make_pool()

    tasks = [
        {"prompt": "a", "working_dir": "/path/a"},
        {"prompt": "b", "working_dir": "/path/a"},
        {"prompt": "c", "working_dir": "/path/a"},
    ]
    await pool.execute_batch(tasks)

    names = _tool_names(calls)
    # Mark a, execute_batch_on_pool, clear a — in that order.
    assert names == [
        "subagent_marker",
        "execute_batch_on_pool",
        "subagent_marker",
    ], names

    # Mark args for the single working_dir.
    mark_calls = [c for c in calls if c[1].get("action") == "mark"]
    assert {c[1]["working_dir"] for c in mark_calls} == {"/path/a"}
    clear_calls = [c for c in calls if c[1].get("action") == "clear"]
    assert {c[1]["working_dir"] for c in clear_calls} == {"/path/a"}


@pytest.mark.asyncio
async def test_execute_batch_without_working_dirs_skips_marker(make_pool) -> None:
    """execute_batch with no working_dirs in any task calls only worker_execute_batch."""
    pool, calls = make_pool()

    await pool.execute_batch([{"prompt": "a"}, {"prompt": "b"}])

    names = _tool_names(calls)
    assert names == ["execute_batch_on_pool"], names


@pytest.mark.asyncio
async def test_execute_batch_clears_when_batch_raises() -> None:
    """execute_batch's try/finally clears markers even when the batch MCP call raises."""
    from mcp_common.exceptions import MCPServerError

    calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        calls.append((name, arguments))
        if name == "subagent_marker":
            return {"success": True, "action": arguments.get("action")}
        if name == "execute_batch_on_pool":
            raise MCPServerError("batch boom")
        return {"result": {}}

    with patch("mahavishnu.pools.session_buddy_pool.CommonMCPClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.call_tool = AsyncMock(side_effect=call_tool)
        mock_client.aclose = AsyncMock()
        mock_cls.return_value = mock_client
        pool = SessionBuddyPool(
            config=PoolConfig(
                name="x", pool_type="session-buddy",
                min_workers=1, max_workers=1, worker_type="terminal-claude",
            )
        )
        pool._mcp = mock_client
        pool._workers = {"w1": "worker_w1"}

        result = await pool.execute_batch(
            [{"prompt": "a", "working_dir": "/path/a"}]
        )

    # Result reflects failure (existing behavior preserved).
    assert result["0"]["status"] == "failed"
    assert "batch boom" in result["0"]["error"]

    # But the marker was still cleared.
    names = [name for name, _ in calls]
    assert names == [
        "subagent_marker",  # mark
        "execute_batch_on_pool",  # raises
        "subagent_marker",  # clear (in finally)
    ], names
    assert calls[2][1] == {"working_dir": "/path/a", "action": "clear"}
