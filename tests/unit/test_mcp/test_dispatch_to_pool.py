"""Unit tests for dispatch_to_pool MCP tool and pool_route_execute rate-limit surfacing.

Phase 3 Task 3.5 exit criteria items 13-18 — these tests pin the
behaviour of the new ``dispatch_to_pool`` MCP tool (and the rate-limit
surfaces on ``pool_route_execute``) end-to-end through the
``register_pool_tools`` boundary.

The tests use the same stub-FastMCP pattern as
``tests/unit/test_mcp/test_pool_tools.py`` so the decorated tool
callables are capturable without re-implementing them.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from mahavishnu.core.errors import RateLimitError
from mahavishnu.mcp.tools.pool_tools import register_pool_tools

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


class _StubPool:
    """Minimal pool stand-in so the manager has at least one registered pool."""

    pool_id = "pool_test"
    config = MagicMock(min_workers=1, max_workers=2, pool_type="mahavishnu")
    _workers: dict[str, str] = {"w1": "w1"}

    async def execute_task(self, task):
        return {"pool_id": self.pool_id, "status": "completed", "result": "ok"}

    async def status(self):  # pragma: no cover - not exercised here
        return "running"


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def mock_pool_manager() -> MagicMock:
    """A PoolManager-shaped mock with one stub pool and a MagicMock Dhara."""
    manager = MagicMock()
    manager._pools = {"pool_test": _StubPool()}
    manager._dhara_state = MagicMock()
    manager._dhara_state.put = AsyncMock(return_value=None)
    # Default async-friendly returns so sync-path tests succeed.
    manager.route_task = AsyncMock(
        return_value={
            "pool_id": "pool_test",
            "status": "completed",
            "result": "ok",
        }
    )
    return manager


@pytest.fixture
def registered_mcp(stub_mcp: _StubMCP, mock_pool_manager: MagicMock) -> _StubMCP:
    """Register pool tools on the stub MCP for direct invocation."""
    register_pool_tools(stub_mcp, mock_pool_manager)
    return stub_mcp


# =============================================================================
# 13. dispatch_to_pool sync path returns the manager's result inline
# =============================================================================


class TestDispatchToPoolSync:
    """``async_callback=False`` returns the manager's result inline."""

    async def test_dispatch_to_pool_sync_returns_result(
        self, registered_mcp: _StubMCP, mock_pool_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["dispatch_to_pool"]
        expected = {"pool_id": "pool_test", "status": "completed", "result": "ok"}
        mock_pool_manager.route_task = AsyncMock(return_value=expected)
        result = await fn(
            prompt="hi",
            caller_kind="ultracode",
            parent_session_id="ses_abc",
            async_callback=False,
        )
        assert result == expected


# =============================================================================
# 14. dispatch_to_pool async path returns a workflow_id immediately
# =============================================================================


class TestDispatchToPoolAsync:
    """``async_callback=True`` returns a workflow_id + queued status immediately."""

    async def test_dispatch_to_pool_async_returns_workflow_id(
        self, registered_mcp: _StubMCP, mock_pool_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["dispatch_to_pool"]
        # Make route_task slow so we can observe the immediate-return contract.
        async def slow_route(*_args, **_kwargs):
            await asyncio.sleep(0.5)
            return {"pool_id": "pool_test", "status": "completed"}

        mock_pool_manager.route_task = AsyncMock(side_effect=slow_route)

        result = await fn(
            prompt="hi",
            caller_kind="ultracode",
            parent_session_id="ses_abc",
            async_callback=True,
        )
        assert result["status"] == "queued"
        assert result["caller_kind"] == "ultracode"
        assert result["parent_session_id"] == "ses_abc"
        # workflow_id is a valid UUID.
        UUID(result["workflow_id"])  # raises if invalid


# =============================================================================
# 15. dispatch_to_pool surfaces RateLimitError as rate_limited
# =============================================================================


class TestDispatchToPoolRateLimited:
    """A ``RateLimitError`` from route_task is surfaced as rate_limited."""

    async def test_dispatch_to_pool_rate_limited_surfaces_retry_after(
        self, registered_mcp: _StubMCP, mock_pool_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["dispatch_to_pool"]
        mock_pool_manager.route_task = AsyncMock(
            side_effect=RateLimitError(limit="caller_kind=ultracode", retry_after=12)
        )
        result = await fn(
            prompt="hi",
            caller_kind="ultracode",
            parent_session_id="ses_abc",
            async_callback=False,
        )
        assert result["status"] == "rate_limited"
        assert result["caller_kind"] == "ultracode"
        assert result["retry_after_seconds"] == 12
        assert "error" in result


# =============================================================================
# 16. dispatch_to_pool async lifecycle: queued -> running -> completed
# =============================================================================


class TestDispatchToPoolAsyncLifecycleCompleted:
    """The background coroutine persists queued, running, then completed."""

    async def test_dispatch_to_pool_async_lifecycle_completed(
        self, registered_mcp: _StubMCP, mock_pool_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["dispatch_to_pool"]
        # Capture every put() call so we can inspect status transitions.
        put_calls: list[tuple[str, dict[str, Any]]] = []

        async def capture_put(key, value):
            put_calls.append((key, value))

        mock_pool_manager._dhara_state.put = AsyncMock(side_effect=capture_put)
        # Mock route_task returns quickly.
        mock_pool_manager.route_task = AsyncMock(
            return_value={"pool_id": "pool_test", "status": "completed"}
        )

        await fn(
            prompt="hi",
            caller_kind="ultracode",
            parent_session_id="ses_abc",
            async_callback=True,
        )

        # The async task is scheduled with create_task; let it run.
        # Pump the event loop until the background task finishes.
        for _ in range(20):
            await asyncio.sleep(0)
            if any("completed" in v.get("status", "") for _, v in put_calls):
                break

        statuses = [v.get("status") for _, v in put_calls]
        assert "queued" in statuses, f"missing 'queued' status; got {statuses!r}"
        assert "running" in statuses, f"missing 'running' status; got {statuses!r}"
        assert "completed" in statuses, f"missing 'completed' status; got {statuses!r}"


# =============================================================================
# 17. dispatch_to_pool async terminal: result_write_failed when Dhara is unreachable
# =============================================================================


class TestDispatchToPoolAsyncResultWriteFailed:
    """When the terminal-state put fails, result_write_failed is recorded."""

    async def test_dispatch_to_pool_async_result_write_failed_terminal_state(
        self,
        registered_mcp: _StubMCP,
        mock_pool_manager: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Redirect Path.home() to tmp_path so the dead-letter write goes
        # into a per-test temp dir, not the user's home.
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        fn = registered_mcp.tools["dispatch_to_pool"]

        # Track put() calls so we can verify the lifecycle.
        # - The initial "queued" write (from dispatch_to_pool itself) succeeds.
        # - The "running" write (from _run_async_dispatch) succeeds.
        # - The terminal "completed" write FAILS — this triggers the
        #   dead-letter path in _run_async_dispatch.
        statuses_seen: list[str] = []
        call_count = {"n": 0}

        async def flaky_put(key, value):
            call_count["n"] += 1
            statuses_seen.append(value.get("status", ""))
            if value.get("status") == "completed":
                raise RuntimeError("Dhara unreachable for terminal state")
            return

        mock_pool_manager._dhara_state.put = AsyncMock(side_effect=flaky_put)
        # Mock route_task returns cleanly so the only error is from the put.
        mock_pool_manager.route_task = AsyncMock(
            return_value={"pool_id": "pool_test", "status": "completed"}
        )

        await fn(
            prompt="hi",
            caller_kind="ultracode",
            parent_session_id="ses_abc",
            async_callback=True,
        )

        # Pump the event loop until the background task finishes.
        for _ in range(40):
            await asyncio.sleep(0)
            if call_count["n"] >= 3:
                break

        # Verify the lifecycle progressed far enough to trigger dead-letter.
        assert "queued" in statuses_seen
        assert "running" in statuses_seen
        # The terminal "completed" attempt was made and failed.
        assert "completed" in statuses_seen

        # Dead-letter file should exist.
        dead_letter_dir = tmp_path / ".mahavishnu" / "async-dead-letter"
        assert dead_letter_dir.exists(), (
            f"dead-letter dir was not created at {dead_letter_dir!r}"
        )
        files = list(dead_letter_dir.glob("*.json"))
        assert files, "no dead-letter file was written"

        # Verify the dead-letter file content shape.
        contents = json.loads(files[0].read_text())
        assert "workflow_id" in contents
        assert "intended_terminal_status" in contents


# =============================================================================
# 18. pool_route_execute rate-limit surfacing (sync)
# =============================================================================


class TestPoolRouteExecuteRateLimited:
    """``pool_route_execute`` also surfaces ``RateLimitError`` as rate_limited."""

    async def test_pool_route_execute_rate_limited_surfaces_retry_after(
        self, registered_mcp: _StubMCP, mock_pool_manager: MagicMock
    ) -> None:
        fn = registered_mcp.tools["pool_route_execute"]
        mock_pool_manager.route_task = AsyncMock(
            side_effect=RateLimitError(limit="caller_kind=ultracode", retry_after=5)
        )
        result = await fn(
            prompt="hi",
            caller_kind="ultracode",
            parent_session_id="ses_abc",
        )
        assert result["status"] == "rate_limited"
        assert result["caller_kind"] == "ultracode"
        assert result["retry_after_seconds"] == 5
        assert "error" in result