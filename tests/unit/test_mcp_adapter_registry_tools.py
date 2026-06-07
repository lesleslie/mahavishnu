"""Unit tests for mahavishnu.mcp.tools.adapter_registry_tools.

The module decorates async functions with ``@mcp.tool()`` at module
import time. Tests use a ``_StubMCP`` to capture the tool functions,
then invoke them directly with a mocked ``get_registry``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.mcp.tools.adapter_registry_tools import register_adapter_registry_tools

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


class _StubMCP:
    """Minimal FastMCP stand-in that records decorated functions."""

    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _run(coro):
    return asyncio.run(coro)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def stub_mcp() -> _StubMCP:
    return _StubMCP()


@pytest.fixture
def fake_registry() -> MagicMock:
    """MagicMock for the HybridAdapterRegistry returned by get_registry()."""
    reg = MagicMock(name="registry")
    reg.list_adapters = MagicMock(return_value=[{"name": "prefect"}])
    reg.resolve = AsyncMock(return_value=None)
    reg.check_adapter_health = AsyncMock(return_value={"status": "healthy"})
    reg.check_all_health = AsyncMock(
        return_value={"a": {"status": "healthy"}, "b": {"status": "unhealthy"}}
    )
    reg.set_adapter_enabled = AsyncMock(return_value=True)
    reg.get_metadata = MagicMock(return_value=None)
    reg.invalidate_cache = MagicMock()
    reg.discovery = MagicMock()
    reg.discovery.invalidate_cache = MagicMock()
    reg.resolution_cache = MagicMock()
    reg.resolution_cache.invalidate = MagicMock()
    reg.discover_and_register = AsyncMock(
        return_value=MagicMock(to_dict=MagicMock(return_value={"discovered": 0, "registered": 0}))
    )
    return reg


@pytest.fixture
def registered(stub_mcp, fake_registry, monkeypatch):
    """Register all tools on a stub MCP and patch get_registry to return fake."""
    monkeypatch.setattr("mahavishnu.core.adapter_registry.get_registry", lambda: fake_registry)
    register_adapter_registry_tools(stub_mcp)
    return stub_mcp


# =============================================================================
# adapter_list
# =============================================================================


class TestAdapterList:
    """Tests for adapter_list tool."""

    def test_lists_all_adapters(self, registered, fake_registry):
        """No filters returns the full adapter list."""
        tool = registered.tools["adapter_list"]
        result = _run(tool())
        assert result["success"] is True
        assert result["adapters"] == [{"name": "prefect"}]
        assert result["count"] == 1
        assert result["filters"] == {
            "domain": None,
            "capabilities": None,
            "healthy_only": False,
        }

    def test_passes_filters_through(self, registered, fake_registry):
        """All filter arguments must be forwarded to registry.list_adapters."""
        tool = registered.tools["adapter_list"]
        result = _run(tool(domain="orchestration", capabilities=["cap1"], healthy_only=True))
        assert result["success"] is True
        fake_registry.list_adapters.assert_called_once_with(
            domain="orchestration", capabilities=["cap1"], healthy_only=True
        )

    def test_runtime_error_returns_known_shape(self, registered, fake_registry, monkeypatch):
        """Uninitialized registry returns the documented error shape."""
        monkeypatch.setattr(
            "mahavishnu.core.adapter_registry.get_registry",
            MagicMock(side_effect=RuntimeError("not init")),
        )
        # Recreate the registered fixture? No — use the original stub_mcp and re-patch.
        # Simpler: re-call register with patched module.
        new_stub = _StubMCP()
        register_adapter_registry_tools(new_stub)
        tool = new_stub.tools["adapter_list"]
        result = _run(tool())
        assert result["success"] is False
        assert result["error"] == "Adapter registry not initialized"
        assert result["adapters"] == []
        assert result["count"] == 0

    def test_generic_exception_returns_error(self, stub_mcp, monkeypatch):
        """Any other exception is caught and returned as a tool error."""
        monkeypatch.setattr(
            "mahavishnu.core.adapter_registry.get_registry",
            MagicMock(side_effect=ValueError("boom")),
        )
        register_adapter_registry_tools(stub_mcp)
        tool = stub_mcp.tools["adapter_list"]
        result = _run(tool())
        assert result["success"] is False
        assert "boom" in result["error"]


# =============================================================================
# adapter_resolve
# =============================================================================


class TestAdapterResolve:
    """Tests for adapter_resolve tool."""

    def test_resolves_adapter(self, registered, fake_registry):
        """A non-None decision produces a success response with all fields."""
        decision = MagicMock()
        decision.adapter_name = "prefect"
        decision.matched_capabilities = ["cap1"]
        decision.resolution_time_ms = 1.5
        decision.fallback_used = False
        decision.explanation = "matched"
        fake_registry.resolve = AsyncMock(return_value=decision)
        tool = registered.tools["adapter_resolve"]
        result = _run(tool(task_type="workflow", required_capabilities=["cap1"]))
        assert result["success"] is True
        assert result["adapter_name"] == "prefect"
        assert result["matched_capabilities"] == ["cap1"]
        assert result["resolution_time_ms"] == 1.5
        assert result["fallback_used"] is False
        assert result["explanation"] == "matched"

    def test_no_match_returns_failure(self, registered, fake_registry):
        """A None decision (no matching adapter) returns failure."""
        fake_registry.resolve = AsyncMock(return_value=None)
        tool = registered.tools["adapter_resolve"]
        result = _run(tool(task_type="workflow", required_capabilities=["missing"]))
        assert result["success"] is False
        assert "No adapter found" in result["error"]
        assert result["task_type"] == "workflow"

    def test_runtime_error(self, stub_mcp, monkeypatch):
        """Uninitialized registry returns known error."""
        monkeypatch.setattr(
            "mahavishnu.core.adapter_registry.get_registry",
            MagicMock(side_effect=RuntimeError("not init")),
        )
        register_adapter_registry_tools(stub_mcp)
        tool = stub_mcp.tools["adapter_resolve"]
        result = _run(tool(task_type="x", required_capabilities=[]))
        assert result == {"success": False, "error": "Adapter registry not initialized"}


# =============================================================================
# adapter_health
# =============================================================================


class TestAdapterHealth:
    """Tests for adapter_health tool."""

    def test_single_adapter_found(self, registered, fake_registry):
        """Health check for a specific adapter returns its health dict."""
        fake_registry.check_adapter_health = AsyncMock(return_value={"status": "healthy"})
        tool = registered.tools["adapter_health"]
        result = _run(tool(adapter_name="prefect"))
        assert result["success"] is True
        assert result["adapter_name"] == "prefect"
        assert result["health"] == {"status": "healthy"}

    def test_single_adapter_not_found(self, registered, fake_registry):
        """Returns failure when the adapter is unknown."""
        fake_registry.check_adapter_health = AsyncMock(return_value=None)
        tool = registered.tools["adapter_health"]
        result = _run(tool(adapter_name="missing"))
        assert result["success"] is False
        assert "not found" in result["error"]

    def test_all_adapters_summary(self, registered, fake_registry):
        """When adapter_name is None, returns the aggregate summary."""
        fake_registry.check_all_health = AsyncMock(
            return_value={
                "a": {"status": "healthy"},
                "b": {"status": "unhealthy"},
            }
        )
        tool = registered.tools["adapter_health"]
        result = _run(tool())
        assert result["success"] is True
        assert result["summary"] == {"total": 2, "healthy": 1, "unhealthy": 1}


# =============================================================================
# adapter_enable
# =============================================================================


class TestAdapterEnable:
    """Tests for adapter_enable tool."""

    def test_enable_succeeds(self, registered, fake_registry):
        """Enabling an existing adapter returns success."""
        fake_registry.set_adapter_enabled = AsyncMock(return_value=True)
        tool = registered.tools["adapter_enable"]
        result = _run(tool(adapter_name="prefect", enabled=True, reason="test"))
        assert result["success"] is True
        assert result["enabled"] is True
        assert "enabled" in result["message"]
        fake_registry.set_adapter_enabled.assert_awaited_once_with(
            name="prefect", enabled=True, reason="test"
        )

    def test_disable_succeeds(self, registered, fake_registry):
        """Disabling returns success with enabled=False and the right message."""
        fake_registry.set_adapter_enabled = AsyncMock(return_value=True)
        tool = registered.tools["adapter_enable"]
        result = _run(tool(adapter_name="prefect", enabled=False))
        assert result["success"] is True
        assert result["enabled"] is False
        assert "disabled" in result["message"]

    def test_adapter_not_found(self, registered, fake_registry):
        """set_adapter_enabled returning False means the adapter doesn't exist."""
        fake_registry.set_adapter_enabled = AsyncMock(return_value=False)
        tool = registered.tools["adapter_enable"]
        result = _run(tool(adapter_name="missing", enabled=True))
        assert result["success"] is False
        assert "not found" in result["error"]


# =============================================================================
# adapter_metadata
# =============================================================================


class TestAdapterMetadata:
    """Tests for adapter_metadata tool."""

    def test_returns_metadata_dict(self, registered, fake_registry):
        """Returns the to_dict() of the AdapterMetadata."""
        metadata = MagicMock()
        metadata.to_dict = MagicMock(return_value={"adapter_id": "prefect", "priority": 90})
        fake_registry.get_metadata = MagicMock(return_value=metadata)
        tool = registered.tools["adapter_metadata"]
        result = _run(tool(adapter_name="prefect"))
        assert result["success"] is True
        assert result["metadata"] == {"adapter_id": "prefect", "priority": 90}

    def test_not_found(self, registered, fake_registry):
        """Returns failure when get_metadata returns None."""
        fake_registry.get_metadata = MagicMock(return_value=None)
        tool = registered.tools["adapter_metadata"]
        result = _run(tool(adapter_name="missing"))
        assert result["success"] is False


# =============================================================================
# adapter_cache_invalidate
# =============================================================================


class TestAdapterCacheInvalidate:
    """Tests for adapter_cache_invalidate tool."""

    def test_no_source_invalidates_all(self, registered, fake_registry):
        """source=None calls registry.invalidate_cache() and reports 'all'."""
        tool = registered.tools["adapter_cache_invalidate"]
        result = _run(tool())
        assert result["success"] is True
        assert "all" in result["message"]
        fake_registry.invalidate_cache.assert_called_once()

    def test_discovery_source(self, registered, fake_registry):
        """source='discovery' invalidates discovery cache only."""
        tool = registered.tools["adapter_cache_invalidate"]
        result = _run(tool(source="discovery"))
        assert result["success"] is True
        assert "discovery" in result["message"]
        fake_registry.discovery.invalidate_cache.assert_called_once()
        fake_registry.invalidate_cache.assert_not_called()

    def test_resolution_source(self, registered, fake_registry):
        """source='resolution' invalidates resolution cache only."""
        tool = registered.tools["adapter_cache_invalidate"]
        result = _run(tool(source="resolution"))
        assert result["success"] is True
        assert "resolution" in result["message"]
        fake_registry.resolution_cache.invalidate.assert_called_once()
        fake_registry.invalidate_cache.assert_not_called()

    def test_unknown_source_falls_back_to_invalidate_all(self, registered, fake_registry):
        """Any source name that isn't 'discovery' or 'resolution' falls back to invalidate_cache()."""
        tool = registered.tools["adapter_cache_invalidate"]
        result = _run(tool(source="other"))
        assert result["success"] is True
        fake_registry.invalidate_cache.assert_called_once()


# =============================================================================
# adapter_discover
# =============================================================================


class TestAdapterDiscover:
    """Tests for adapter_discover tool."""

    def test_default_no_force_refresh(self, registered, fake_registry):
        """Without force_refresh, registry.invalidate_cache is NOT called."""
        tool = registered.tools["adapter_discover"]
        result = _run(tool())
        assert result["success"] is True
        assert result["report"] == {"discovered": 0, "registered": 0}
        fake_registry.invalidate_cache.assert_not_called()
        fake_registry.discover_and_register.assert_awaited_once()

    def test_force_refresh_invalidates_first(self, registered, fake_registry):
        """With force_refresh=True, registry.invalidate_cache is called before discover."""
        tool = registered.tools["adapter_discover"]
        result = _run(tool(force_refresh=True))
        assert result["success"] is True
        fake_registry.invalidate_cache.assert_called_once()
        fake_registry.discover_and_register.assert_awaited_once()
