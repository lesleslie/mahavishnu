"""Focused tests for MCP utility tools."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastmcp import FastMCP
import pytest

from mahavishnu.core.health_schemas import HealthStatus
from mahavishnu.mcp.tools.health_tools import register_health_tools


@pytest.fixture
def mcp_server() -> FastMCP:
    """Create a bare FastMCP server with health tools registered."""
    server = FastMCP("utility-tools-test")
    register_health_tools(server)
    return server


class TestMCPUtilityTools:
    """Validate MCP utility tool registration and behavior."""

    @pytest.mark.asyncio
    async def test_mcp_utility_tools_registered(self, mcp_server):
        """The three utility tools should be discoverable."""
        tools = await mcp_server.list_tools()
        tool_names = {tool.name for tool in tools}

        assert {"mcp_list_tools", "mcp_test_connection", "mcp_get_metrics"}.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_mcp_list_tools_returns_inventory(self, mcp_server):
        """mcp_list_tools should return a serialized inventory."""
        result = await (await mcp_server.get_tool("mcp_list_tools")).fn()

        assert result["status"] == "success"
        assert result["total_tools"] >= 3
        tool_names = {item["name"] for item in result["tools"]}

        assert {"mcp_list_tools", "mcp_test_connection", "mcp_get_metrics"}.issubset(tool_names)

    @pytest.mark.asyncio
    async def test_mcp_test_connection_returns_connectivity(self, mcp_server):
        """mcp_test_connection should report a typed connectivity result."""
        fake_result = SimpleNamespace(
            status=HealthStatus.OK,
            latency_ms=12.5,
            error=None,
            response_data={"status": "ok"},
        )

        with patch(
            "mahavishnu.mcp.tools.health_tools.HealthChecker.check",
            new=AsyncMock(return_value=fake_result),
        ):
            result = await (await mcp_server.get_tool("mcp_test_connection")).fn(
                service_name="session-buddy", host="localhost", port=8678
            )

        assert result["status"] == HealthStatus.OK.value
        assert result["connected"] is True
        assert result["service_name"] == "session-buddy"
        assert result["latency_ms"] == 12.5
        assert result["response"] == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_mcp_get_metrics_returns_snapshot(self, mcp_server):
        """mcp_get_metrics should return a Prometheus snapshot."""
        fake_families = [
            SimpleNamespace(
                name="mcp_tool_calls_total",
                type="counter",
                documentation="Total MCP tool calls",
                samples=[object(), object()],
            ),
            SimpleNamespace(
                name="mcp_tools_registered",
                type="gauge",
                documentation="Number of registered MCP tools",
                samples=[object()],
            ),
        ]
        fake_registry = SimpleNamespace(collect=lambda: fake_families)

        with (
            patch(
                "mahavishnu.mcp.tools.health_tools.get_metrics_registry", return_value=fake_registry
            ),
            patch(
                "mahavishnu.mcp.tools.health_tools.expose_metrics",
                return_value=b"# HELP mcp_tool_calls_total Total MCP tool calls\nmcp_tool_calls_total 1\n",
            ),
        ):
            result = await (await mcp_server.get_tool("mcp_get_metrics")).fn()

        assert result["status"] == "success"
        assert result["registered_tools"] >= 1
        assert result["metric_family_count"] == 2
        assert result["metrics_text"].startswith("# HELP mcp_tool_calls_total")
        assert result["metrics_preview"][0].startswith("# HELP mcp_tool_calls_total")
