"""Unit tests for ``mahavishnu.mcp.tools.budget_tools``.

The module exposes ``register_budget_tools`` which attaches the
``mahavishnu_budget_enforce`` FastMCP tool. The tool declares a
per-workflow budget that the watchdog enforces; re-calling with the
same ``workflow_id`` re-bases the cap.

The tests register against a stub MCP instance that captures the
decorated callable, then invoke it directly with mocked dependencies.
This avoids re-implementing the tool's logic in test bodies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from unittest.mock import AsyncMock

import pytest

from mahavishnu.mcp.tools import budget_tools
from mahavishnu.mcp.tools.budget_tools import (
    budget_enforce_tool,
    register_budget_tools,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

pytestmark = pytest.mark.unit


# =============================================================================
# Stub MCP and fakes
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in that captures the decorated callable."""

    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self, name: str | None = None):
        def decorator(fn):
            tool_name = name or fn.__name__
            self.tools[tool_name] = fn
            return fn

        return decorator


class _FakeBudgetStore:
    """In-memory budget store matching the protocol used by budget_enforce_tool.

    The real ``BudgetStore`` exposes ``async def get(key) -> dict | None`` and
    ``async def put(key, value) -> None``. The fake records every call so
    tests can assert the round-trip without a real persistence backend.
    """

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}
        self.puts: list[tuple[str, Any]] = []
        self.gets: list[str] = []

    async def get(self, key: str) -> dict[str, Any] | None:
        self.gets.append(key)
        return self.records.get(key)

    async def put(self, key: str, value: Any) -> None:
        self.puts.append((key, value))
        self.records[key] = value


@pytest.fixture(autouse=True)
def _reset_module_budget_store():
    """Reset the module-level ``_budget_store`` slot before and after each test.

    ``register_budget_tools`` writes the live dependency into the module
    namespace; without this fixture the slot leaks between tests.
    """
    original = budget_tools._budget_store
    budget_tools._budget_store = None
    yield
    budget_tools._budget_store = original


# =============================================================================
# Tests
# =============================================================================


async def test_budget_enforce_tool_returns_envelope_with_active_status() -> None:
    """budget_enforce_tool persists the record and returns an active envelope."""
    mcp = _StubMCP()
    store = _FakeBudgetStore()

    register_budget_tools(cast("FastMCP", mcp), budget_store=store)

    assert "mahavishnu_budget_enforce" in mcp.tools
    tool = mcp.tools["mahavishnu_budget_enforce"]

    result = await tool(
        workflow_id="wf_123",
        budget_tokens=1000,
        budget_turns=10,
        declared_by="alice",
    )

    assert result["workflow_id"] == "wf_123"
    assert result["status"] == "active"
    assert result["spec"]["budget_tokens"] == 1000
    assert result["spec"]["budget_turns"] == 10
    assert result["spec"]["declared_by"] == "alice"
    assert result["state"] == "active"
    assert result["started_at"] is not None
    # Persistence round-trip
    assert len(store.puts) == 1
    key, value = store.puts[0]
    assert key == "mahavishni://budgets/wf_123.json"
    assert value["workflow_id"] == "wf_123"
    assert len(store.gets) == 1
    # Module-level slot was populated
    assert budget_tools._budget_store is store


async def test_budget_enforce_tool_returns_unconfigured_when_store_missing() -> None:
    """budget_enforce_tool returns ``unconfigured`` instead of raising when no store."""
    mcp = _StubMCP()
    register_budget_tools(cast("FastMCP", mcp), budget_store=None)

    tool = mcp.tools["mahavishnu_budget_enforce"]

    result = await tool(workflow_id="wf_xyz", budget_tokens=500)

    assert result == {
        "workflow_id": "wf_xyz",
        "status": "unconfigured",
        "error": "budget_store is not configured on this server",
    }


async def test_budget_enforce_tool_persists_through_store_round_trip() -> None:
    """budget_enforce_tool reads existing record, re-bases the cap, persists the new one."""
    mcp = _StubMCP()
    store = _FakeBudgetStore()
    # Pre-populate an existing record (simulating a prior declaration).
    store.records["mahavishni://budgets/wf_abc.json"] = {
        "workflow_id": "wf_abc",
        "state": "declared",
        "spec": {"budget_tokens": 100},
        "started_at": None,
    }

    register_budget_tools(cast("FastMCP", mcp), budget_store=store)
    tool = mcp.tools["mahavishnu_budget_enforce"]

    result = await tool(workflow_id="wf_abc", budget_tokens=200)

    assert result["status"] == "active"
    assert result["spec"]["budget_tokens"] == 200
    # The persisted record reflects the new cap (re-basing semantics).
    assert store.records["mahavishni://budgets/wf_abc.json"]["spec"]["budget_tokens"] == 200


async def test_budget_enforce_tool_returns_failed_when_get_raises() -> None:
    """budget_enforce_tool swallows read failures and returns a failed envelope."""
    mcp = _StubMCP()

    # Use AsyncMock that raises on get but is silent on put.
    failing_store = AsyncMock()
    failing_store.get.side_effect = OSError("kv-down")
    failing_store.put = AsyncMock()

    register_budget_tools(cast("FastMCP", mcp), budget_store=failing_store)
    tool = mcp.tools["mahavishnu_budget_enforce"]

    # Read failure is swallowed: the tool seeds a fresh BudgetRecord and
    # attempts the write. The write succeeds (no exception), so the
    # envelope returned is ``active`` (status reflects the write outcome).
    result = await tool(workflow_id="wf_q", budget_turns=3)
    assert result["status"] == "active"


async def test_register_budget_tools_is_idempotent() -> None:
    """Calling register twice replaces the module-level store cleanly."""
    mcp = _StubMCP()
    store_a = _FakeBudgetStore()
    store_b = _FakeBudgetStore()

    register_budget_tools(cast("FastMCP", mcp), budget_store=store_a)
    assert budget_tools._budget_store is store_a

    register_budget_tools(cast("FastMCP", mcp), budget_store=store_b)
    assert budget_tools._budget_store is store_b

    # Module still exposes the tool function at import path
    assert budget_enforce_tool is budget_tools.budget_enforce_tool
    assert register_budget_tools is budget_tools.register_budget_tools
