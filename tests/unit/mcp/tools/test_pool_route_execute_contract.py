"""Tests for pool_route_execute / dispatch_to_pool durable routing.

The durable-worker contract (F1, F12) routes shell-based worker types
through ``DurableWorkerManager.spawn`` for both ``pool_route_execute``
and ``dispatch_to_pool``. The ``worker_type`` parameter is added to
both nested tool functions; non-shell types continue on the legacy path.

Calls the registered tools through ``stub.tools[...]`` (mirror
``test_worker_list_filter.py`` and ``test_worker_tools.py`` conventions)
because ``pool_route_execute`` / ``dispatch_to_pool`` are nested inside
``register_pool_tools`` for FastMCP's decorator contract.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.workers.contract.manager import SpawnResult
from mahavishnu.workers.contract.record import DurableWorkerRecord, TmuxTarget
from mahavishnu.workers.contract.state import WorkerLifecycleState

pytestmark = pytest.mark.unit


class _StubMCP:
    """Minimal FastMCP stand-in that captures tool functions by name."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _make_record(worker_id: str) -> DurableWorkerRecord:
    now = dt.datetime(2026, 7, 27, 10, 0, 0, tzinfo=dt.UTC)
    return DurableWorkerRecord(
        worker_id=worker_id,
        worker_type="terminal-claude",
        backend="claude_tui",
        tmux=TmuxTarget(socket="/x", session=worker_id, window="@0", pane="%0"),
        state=WorkerLifecycleState.STARTING,
        created_at=now,
        last_seen_at=now,
    )


def _stub_pool_manager() -> MagicMock:
    """A legacy pool manager that should NOT be called on the durable path."""
    return MagicMock()


def test_pool_route_execute_routes_shell_type_through_durable() -> None:
    """``pool_route_execute`` with a shell ``worker_type`` spawns via ``_durable_manager.spawn``."""
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    record = _make_record("w-1")
    spawn_result = SpawnResult(worker_id="w-1", record=record, pane="%0")
    durable_manager = MagicMock()
    durable_manager.spawn = MagicMock(return_value=spawn_result)

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=_stub_pool_manager(),
        durable_manager=durable_manager,
        dhara=None,
    )

    fn = stub.tools["pool_route_execute"]
    out = asyncio.run(
        fn(
            prompt="do it",
            worker_type="terminal-claude",
        )
    )
    assert out == {"worker_id": "w-1", "pane": "%0"}
    durable_manager.spawn.assert_called_once_with(
        worker_type="terminal-claude",
        backend="claude_tui",
        command=["terminal-claude"],
    )


def test_dispatch_to_pool_records_worker_id_in_dhara() -> None:
    """``dispatch_to_pool`` persists worker_id at ``workflow-results/{wf_id}/``."""
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    record = _make_record("w-42")
    spawn_result = SpawnResult(worker_id="w-42", record=record, pane="%3")
    durable_manager = MagicMock()
    durable_manager.spawn = MagicMock(return_value=spawn_result)

    fake_dhara = MagicMock()
    fake_dhara.put = MagicMock()

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=_stub_pool_manager(),
        durable_manager=durable_manager,
        dhara=fake_dhara,
    )

    fn = stub.tools["dispatch_to_pool"]
    out = asyncio.run(
        fn(
            prompt="do it",
            worker_type="terminal-claude",
            workflow_id="wf-42",
        )
    )
    assert out == {"worker_id": "w-42", "workflow_id": "wf-42"}
    fake_dhara.put.assert_called_once()
    call_args = fake_dhara.put.call_args
    assert call_args.args[0] == "workflow-results/wf-42/"
    assert call_args.args[1]["worker_id"] == "w-42"


def test_dispatch_to_pool_rejects_path_traversal_workflow_id() -> None:
    """``dispatch_to_pool`` rejects caller-supplied workflow IDs outside the
    conservative ``^[A-Za-z0-9._-]{1,128}$`` regex BEFORE splicing into the
    Dhara key (path-traversal fix from Task 24 security review).

    A malicious caller could otherwise supply ``../../etc/passwd`` and
    escape the ``workflow-results/`` prefix on the persist layer.

    Both ``dispatch_to_pool`` and ``workflow_result`` use the shared
    ``_validate_workflow_id`` helper and return the consistent error
    shape ``{"workflow_id": ..., "status": "invalid_workflow_id"}``.
    """
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    record = _make_record("w-99")
    spawn_result = SpawnResult(worker_id="w-99", record=record, pane="%9")
    durable_manager = MagicMock()
    durable_manager.spawn = MagicMock(return_value=spawn_result)

    fake_dhara = MagicMock()
    fake_dhara.put = MagicMock()

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=_stub_pool_manager(),
        durable_manager=durable_manager,
        dhara=fake_dhara,
    )

    fn = stub.tools["dispatch_to_pool"]
    out = asyncio.run(
        fn(
            prompt="do it",
            worker_type="terminal-claude",
            workflow_id="../../etc/passwd",  # path-traversal payload
        )
    )
    assert out["status"] == "invalid_workflow_id"
    assert out["workflow_id"] == "../../etc/passwd"
    # Durable spawn MUST NOT have happened for an invalid workflow_id.
    durable_manager.spawn.assert_not_called()
    # Dhara put MUST NOT have happened for an invalid workflow_id.
    fake_dhara.put.assert_not_called()


def test_workflow_result_rejects_path_traversal_workflow_id() -> None:
    """``workflow_result`` rejects caller-supplied workflow IDs outside the
    conservative regex BEFORE the Dhara read (sibling-gate-parity fix).

    A malicious caller could otherwise supply ``../../etc/passwd`` to
    escape the ``workflow-results/`` prefix on the persist layer and
    read arbitrary Dhara keys via the tool surface.
    """
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    fake_dhara = MagicMock()
    fake_dhara.get = AsyncMock()

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=_stub_pool_manager(),
        durable_manager=MagicMock(),
        dhara=fake_dhara,
    )

    fn = stub.tools["workflow_result"]
    out = asyncio.run(fn("../../etc/passwd"))

    assert out["status"] == "invalid_workflow_id"
    assert out["workflow_id"] == "../../etc/passwd"
    # Dhara read MUST NOT have happened for an invalid workflow_id.
    fake_dhara.get.assert_not_called()


def test_workflow_result_rejects_empty_workflow_id() -> None:
    """``workflow_result`` rejects the empty string (regex requires >=1 char)."""
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    fake_dhara = MagicMock()
    fake_dhara.get = AsyncMock()

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=_stub_pool_manager(),
        durable_manager=MagicMock(),
        dhara=fake_dhara,
    )

    fn = stub.tools["workflow_result"]
    out = asyncio.run(fn(""))

    assert out["status"] == "invalid_workflow_id"
    assert out["workflow_id"] == ""
    fake_dhara.get.assert_not_called()


def test_workflow_result_rejects_overly_long_workflow_id() -> None:
    """``workflow_result`` rejects workflow IDs longer than 128 chars."""
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    fake_dhara = MagicMock()
    fake_dhara.get = AsyncMock()

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=_stub_pool_manager(),
        durable_manager=MagicMock(),
        dhara=fake_dhara,
    )

    fn = stub.tools["workflow_result"]
    long_id = "a" * 129
    out = asyncio.run(fn(long_id))

    assert out["status"] == "invalid_workflow_id"
    assert out["workflow_id"] == long_id
    fake_dhara.get.assert_not_called()


def test_pool_route_execute_rejects_worker_type_outside_allowlist() -> None:
    """``pool_route_execute`` falls back to the legacy pool-router path when
    the caller pins a ``worker_type`` NOT in the explicit per-worker_type
    allowlist (allowlist-semantic-escape fix from Task 24 security review).

    A category-level allowlist (``WorkerCategory.SHELL``,
    ``WorkerCategory.AI_ASSISTANT``, ``WorkerCategory.REMOTE``) was too
    broad — any worker in those categories could route through durable
    even if its spawn template was unverified. The fix replaces
    categories with an explicit per-worker_type set: SSH (REMOTE) and
    AI assistants without explicit verification are deliberately
    excluded.
    """
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    spawn_result = MagicMock()
    durable_manager = MagicMock()
    durable_manager.spawn = MagicMock(return_value=spawn_result)

    legacy_pool_manager = MagicMock()
    legacy_pool_manager.route_task = AsyncMock(
        return_value={"status": "completed", "result": "ok"}
    )
    # No-op quota gate so the pre-durable auth gate passes.
    legacy_pool_manager._enforce_caller_quota = MagicMock()

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=legacy_pool_manager,
        durable_manager=durable_manager,
        dhara=None,
    )

    fn = stub.tools["pool_route_execute"]
    out = asyncio.run(
        fn(
            prompt="do it",
            worker_type="terminal-ssh",  # REMOTE — NOT in durable allowlist
        )
    )
    # Durable spawn MUST NOT have happened.
    durable_manager.spawn.assert_not_called()
    # Legacy pool router SHOULD have been called.
    legacy_pool_manager.route_task.assert_called_once()
    # The legacy path returned the result.
    assert out == {"status": "completed", "result": "ok"}


def test_pool_route_execute_fast_path_enforces_quota() -> None:
    """``pool_route_execute`` exercises the per-caller_kind quota on the
    durable fast path (gate-action-field-mismatch fix from Task 24
    security review).

    Without the pre-durable auth gate, a caller could bypass
    ``_enforce_caller_quota`` by routing through the durable branch
    and inflate (or, with a saturated bucket, ignore) their quota.
    The MCP boundary surfaces the rate-limit response unchanged.
    """
    from mahavishnu.core.errors import RateLimitError
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools
    from mahavishnu.pools.manager import CallerKind

    spawn_result = MagicMock()
    durable_manager = MagicMock()
    durable_manager.spawn = MagicMock(return_value=spawn_result)

    pool_manager = MagicMock()
    pool_manager._enforce_caller_quota = MagicMock(
        side_effect=RateLimitError(
            limit="caller_kind=claude_code",
            retry_after=7,
        )
    )

    stub = _StubMCP()
    register_pool_tools(
        stub,
        pool_manager=pool_manager,
        durable_manager=durable_manager,
        dhara=None,
    )

    fn = stub.tools["pool_route_execute"]
    out = asyncio.run(
        fn(
            prompt="do it",
            worker_type="terminal-claude",
            caller_kind="claude_code",
        )
    )
    # Quota gate MUST have been exercised on the fast path.
    pool_manager._enforce_caller_quota.assert_called_once_with(CallerKind.CLAUDE_CODE)
    # No durable spawn should have happened.
    durable_manager.spawn.assert_not_called()
    # MCP boundary surfaces rate-limit.
    assert out["status"] == "rate_limited"
    assert out["retry_after_seconds"] == 7
