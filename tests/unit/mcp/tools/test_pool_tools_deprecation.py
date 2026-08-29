"""Phase 3b.1 — DeprecationWarning tests for legacy pool/worker/dispatch tools.

Five tools (``pool_spawn``, ``pool_execute``, ``pool_route_execute``,
``dispatch_to_pool``, ``workflow_result``) emit a ``DeprecationWarning``
on every call. They continue to return their normal result shapes so
existing consumers keep working until Task 3b.3 deletes them outright.

These tests assert the warning is raised AND the existing return shape is
preserved. Each test mocks at the same boundary the existing
``test_pool_route_execute_contract.py`` tests use (a ``_StubMCP`` that
captures registered tools and an asyncio.run() invocation), so the
deprecation signal travels through the same call path as production.

The warning is emitted unconditionally inside the tool body. The
``MahavishnuSettings.legacy_tools`` flag controls whether the warning
is *visible* at the warnings-filter layer (default Python behavior
suppresses DeprecationWarning outside ``__main__``); the call itself
always emits the warning so consumers running with the standard
``PYTHONWARNINGS=default::DeprecationWarning`` opt-in see it.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


class _StubMCP:
    """Minimal FastMCP stand-in that captures tools by name (matches the
    pattern used by ``test_pool_route_execute_contract.py``).
    """

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _stub_pool_manager() -> MagicMock:
    """A pool manager with the methods the legacy tools exercise on the
    happy path. ``execute_on_pool``, ``route_task``, and ``spawn_pool``
    return canned dicts so the caller's existing assertion patterns hold.
    """
    manager = MagicMock()
    manager.spawn_pool = AsyncMock(return_value="pool_test_id")
    manager.execute_on_pool = AsyncMock(
        return_value={"status": "completed", "output": "test output"}
    )
    manager.route_task = AsyncMock(
        return_value={"status": "completed", "result": "ok"}
    )
    return manager


def _register_with_manager() -> tuple[_StubMCP, MagicMock]:
    """Register pool tools against a stub MCP and return both the stub and
    the underlying pool manager for assertion access.
    """
    from mahavishnu.mcp.tools.pool_tools import register_pool_tools

    stub = _StubMCP()
    manager = _stub_pool_manager()
    register_pool_tools(
        stub,
        pool_manager=manager,
        durable_manager=None,
        dhara=None,
    )
    return stub, manager


def test_pool_spawn_emits_deprecation_warning_and_returns_result() -> None:
    """``pool_spawn`` warns AND returns its existing ``created`` shape."""
    stub, manager = _register_with_manager()

    fn = stub.tools["pool_spawn"]
    with pytest.warns(DeprecationWarning, match="pool_spawn"):
        result = asyncio.run(
            fn(
                pool_type="mahavishnu",
                name="default",
                min_workers=1,
                max_workers=2,
                worker_type="terminal-claude",
            )
        )

    assert result["status"] == "created"
    assert result["pool_type"] == "mahavishnu"
    assert result["min_workers"] == 1
    assert result["max_workers"] == 2
    manager.spawn_pool.assert_called_once()


def test_pool_execute_emits_deprecation_warning_and_returns_result() -> None:
    """``pool_execute`` warns AND returns the routed task result."""
    stub, manager = _register_with_manager()

    fn = stub.tools["pool_execute"]
    with pytest.warns(DeprecationWarning, match="pool_execute"):
        result = asyncio.run(
            fn(
                pool_id="pool_test_id",
                prompt="do it",
                caller_kind="claude_code",
            )
        )

    assert result == {"status": "completed", "output": "test output"}
    manager.execute_on_pool.assert_called_once()


def test_pool_route_execute_emits_deprecation_warning_and_returns_result() -> None:
    """``pool_route_execute`` warns AND returns its existing result shape."""
    stub, manager = _register_with_manager()

    fn = stub.tools["pool_route_execute"]
    with pytest.warns(DeprecationWarning, match="pool_route_execute"):
        result = asyncio.run(
            fn(
                prompt="do it",
                pool_selector="least_loaded",
                caller_kind="claude_code",
            )
        )

    assert result == {"status": "completed", "result": "ok"}
    manager.route_task.assert_called_once()


def test_dispatch_to_pool_emits_deprecation_warning_and_returns_queued() -> None:
    """``dispatch_to_pool`` warns AND returns the queued shape on the
    async-callback path (the default for ``async_callback=True``). The
    warning is emitted BEFORE the background task is scheduled, so a
    caller that exits the ``with`` block before the task completes still
    captured the signal.
    """
    stub, manager = _register_with_manager()

    fn = stub.tools["dispatch_to_pool"]
    with pytest.warns(DeprecationWarning, match="dispatch_to_pool"):
        result = asyncio.run(
            fn(
                prompt="do it",
                pool_selector="least_loaded",
                caller_kind="claude_code",
                async_callback=True,
            )
        )

    assert result["status"] == "queued"
    assert "workflow_id" in result


def test_workflow_result_emits_deprecation_warning_and_returns_not_found() -> None:
    """``workflow_result`` warns AND returns the ``not_found`` shape when
    Dhara is unavailable on the pool manager.
    """
    stub, manager = _register_with_manager()
    # Explicit ``None`` for ``_dhara_state`` so the ``is None`` check in
    # ``workflow_result`` short-circuits before touching the mock's
    # default auto-MagicMock ``get`` attribute (which is not awaitable).
    manager._dhara_state = None

    fn = stub.tools["workflow_result"]
    with pytest.warns(DeprecationWarning, match="workflow_result"):
        result = asyncio.run(fn("wf-1234"))

    assert result["status"] == "not_found"
    assert result["workflow_id"] == "wf-1234"


def test_all_five_legacy_tools_listed_in_warning() -> None:
    """Sanity check: the helper mentions all five tool names so an operator
    scanning a stack trace knows exactly which entrypoint is deprecated
    even when the warning's enclosing function name is mangled.
    """
    from mahavishnu.mcp.tools.pool_tools import _warn_legacy_tool

    for name in (
        "pool_spawn",
        "pool_execute",
        "pool_route_execute",
        "dispatch_to_pool",
        "workflow_result",
    ):
        with pytest.warns(DeprecationWarning, match=name):
            _warn_legacy_tool(name)
