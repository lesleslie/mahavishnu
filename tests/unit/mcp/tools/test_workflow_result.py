"""Unit tests for the ``workflow_result`` MCP pool tool.

The tool is registered inline via ``@mcp.tool()`` inside
``register_pool_tools`` (the FastMCP API requires inline registration so
the decorator can introspect the function name and signature). We follow
the same stub-FastMCP pattern as ``tests/unit/test_mcp/test_pool_tools.py``
and ``tests/unit/test_mcp/test_dispatch_to_pool.py``.

The implementation reads ``pool_manager._dhara_state`` (matching the
existing ``_run_async_dispatch`` helper and ``dispatch_to_pool``'s queued
write). The stub here sets ``_dhara_state`` directly on the mock manager
so the registered tool sees it via ``getattr``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

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


class _StubStore:
    """Records workflow ids it is asked to fetch; serves back canned records."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.records: dict[str, dict[str, Any]] = {}

    async def get(self, workflow_id: str) -> dict[str, Any] | None:
        self.calls.append(workflow_id)
        return self.records.get(workflow_id)


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def mock_pool_manager() -> AsyncMock:
    """A PoolManager-shaped mock whose ``_dhara_state`` is a ``_StubStore``."""
    manager = AsyncMock()
    manager._dhara_state = _StubStore()
    return manager


@pytest.fixture
def registered_mcp(stub_mcp: _StubMCP, mock_pool_manager: AsyncMock) -> _StubMCP:
    """Register pool tools on the stub MCP for direct invocation."""
    register_pool_tools(stub_mcp, mock_pool_manager)
    return stub_mcp


# =============================================================================
# TestWorkflowResult
# =============================================================================


class TestWorkflowResult:
    """``workflow_result`` retrieves persisted state from Dhara."""

    async def test_returns_persisted_state(
        self,
        registered_mcp: _StubMCP,
        mock_pool_manager: AsyncMock,
    ) -> None:
        store: _StubStore = mock_pool_manager._dhara_state  # type: ignore[assignment]
        store.records["wf-1"] = {
            "workflow_id": "wf-1",
            "status": "completed",
            "result": {"output": "ok", "status": "completed"},
            "rate_limited": False,
        }

        fn = registered_mcp.tools["workflow_result"]
        out = await fn("wf-1")

        assert out["workflow_id"] == "wf-1"
        assert out["status"] == "completed"
        assert out["result"]["output"] == "ok"
        assert store.calls == ["wf-1"]

    async def test_returns_not_found_when_missing(
        self,
        registered_mcp: _StubMCP,
        mock_pool_manager: AsyncMock,
    ) -> None:
        store: _StubStore = mock_pool_manager._dhara_state  # type: ignore[assignment]
        assert "wf-missing" not in store.records

        fn = registered_mcp.tools["workflow_result"]
        out = await fn("wf-missing")

        assert out["status"] == "not_found"
        assert out["workflow_id"] == "wf-missing"

    async def test_returns_not_found_when_dhara_state_unset(
        self,
        stub_mcp: _StubMCP,
    ) -> None:
        """When the pool manager has no ``_dhara_state`` (Dhara not wired),

        the tool must still respond with ``not_found`` rather than raising.
        """
        manager = AsyncMock()
        # Explicitly unset; AsyncMock would otherwise fabricate attributes.
        manager._dhara_state = None

        register_pool_tools(stub_mcp, manager)
        fn = stub_mcp.tools["workflow_result"]
        out = await fn("wf-anything")

        assert out == {"workflow_id": "wf-anything", "status": "not_found"}
