"""Focused tests for Mahavishnu MCP server components."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMcpretentiousMCPClient:
    """Test McpretentiousMCPClient wrapper."""

    def test_initialization(self):
        """Test client initializes correctly."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()

        assert client._started is False
        assert client._client is not None

    @pytest.mark.asyncio
    async def test_ensure_started(self):
        """Test starting the mcpretentious server."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.start = AsyncMock()

        await client._ensure_started()

        assert client._started is True
        client._client.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_tool_mcpretentious_open(self):
        """Test calling mcpretentious-open tool."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.open_terminal = AsyncMock(return_value="term_123")

        await client._ensure_started()

        result = await client.call_tool("mcpretentious-open", {"columns": 100, "rows": 30})

        assert result["terminal_id"] == "term_123"
        client._client.open_terminal.assert_called_once_with(columns=100, rows=30)

    @pytest.mark.asyncio
    async def test_call_tool_mcpretentious_type(self):
        """Test calling mcpretentious-type tool."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.type_text = AsyncMock()

        await client._ensure_started()

        result = await client.call_tool(
            "mcpretentious-type", {"terminal_id": "term_123", "input": ["hello", "world"]}
        )

        assert result == {}
        client._client.type_text.assert_called_once_with("term_123", "hello", "world")

    @pytest.mark.asyncio
    async def test_call_tool_mcpretentious_read(self):
        """Test calling mcpretentious-read tool."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.read_text = AsyncMock(return_value="output text")

        await client._ensure_started()

        result = await client.call_tool(
            "mcpretentious-read", {"terminal_id": "term_123", "limit_lines": 10}
        )

        assert result["output"] == "output text"
        client._client.read_text.assert_called_once_with("term_123", lines=10)

    @pytest.mark.asyncio
    async def test_call_tool_mcpretentious_close(self):
        """Test calling mcpretentious-close tool."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.close_terminal = AsyncMock()

        await client._ensure_started()

        result = await client.call_tool("mcpretentious-close", {"terminal_id": "term_123"})

        assert result == {}
        client._client.close_terminal.assert_called_once_with("term_123")

    @pytest.mark.asyncio
    async def test_call_tool_mcpretentious_list(self):
        """Test calling mcpretentious-list tool."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.list_terminals = AsyncMock(return_value=["term_1", "term_2"])

        await client._ensure_started()

        result = await client.call_tool("mcpretentious-list", {})

        assert result["terminals"] == ["term_1", "term_2"]
        client._client.list_terminals.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool(self):
        """Test calling unknown tool raises ValueError."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.start = AsyncMock()

        await client._ensure_started()

        with pytest.raises(ValueError, match="Unknown tool"):
            await client.call_tool("unknown-tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_start_failure(self):
        """Test that start failures raise RuntimeError."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.start = AsyncMock(side_effect=Exception("Not installed"))

        with pytest.raises(RuntimeError, match="Could not start mcpretentious server"):
            await client.call_tool("mcpretentious-open", {})


class TestFastMCPServer:
    """Test FastMCPServer implementation."""

    def test_fastmcp_server_initialization(self):
        """Test FastMCPServer initializes with app and config."""
        from mahavishnu.core.config import MahavishnuSettings
        from mahavishnu.mcp.server_core import FastMCPServer

        config = MahavishnuSettings(server_name="Test Server")
        server = FastMCPServer(app=None, config=config)

        assert server.app.config == config
        assert server.app.config.server_name == "Test Server"

    def test_fastmcp_server_with_default_config(self):
        """Test FastMCPServer with default configuration."""
        from mahavishnu.mcp.server_core import FastMCPServer

        server = FastMCPServer()

        assert server.app.config is not None


class TestMCPServerIntegration:
    """Test MCP server integration points."""

    @pytest.mark.asyncio
    async def test_run_server_with_config(self):
        """Test running server with custom configuration."""
        from mahavishnu.core.config import MahavishnuSettings
        from mahavishnu.mcp.server_core import run_server

        config = MahavishnuSettings(
            server_name="Test Server",
            mcp_enabled=True,
        )

        # Mock the server creation and run
        with patch("mahavishnu.mcp.server_core.FastMCPServer") as MockServer:
            mock_server = MagicMock()
            mock_server.start = AsyncMock()
            MockServer.return_value = mock_server

            # This should not raise
            await run_server(config=config)

            MockServer.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_server_with_defaults(self):
        """Test running server with default configuration."""
        from mahavishnu.mcp.server_core import run_server

        with patch("mahavishnu.mcp.server_core.FastMCPServer") as MockServer:
            mock_server = MagicMock()
            mock_server.start = AsyncMock()
            MockServer.return_value = mock_server

            await run_server()

            MockServer.assert_called_once()


class TestMCPComponentLoading:
    """Test MCP component loading and initialization."""

    def test_mcp_module_imports(self):
        """Test that MCP module can be imported."""
        import mahavishnu.mcp.server_core

        assert hasattr(mahavishnu.mcp.server_core, "McpretentiousMCPClient")
        assert hasattr(mahavishnu.mcp.server_core, "FastMCPServer")
        assert hasattr(mahavishnu.mcp.server_core, "run_server")

    def test_mcp_tools_modules_import(self):
        """Test that all MCP tools modules can be imported."""
        import mahavishnu.mcp.tools.coordination_tools
        import mahavishnu.mcp.tools.otel_tools
        import mahavishnu.mcp.tools.pool_tools
        import mahavishnu.mcp.tools.terminal_tools
        import mahavishnu.mcp.tools.worker_tools

        # Verify pool_tools registration function exists
        assert hasattr(mahavishnu.mcp.tools.pool_tools, "register_pool_tools")


class TestMCPEndpointRegistration:
    """Test MCP endpoint registration patterns."""

    def test_pool_tools_signature(self):
        """Test pool tools registration function signature."""
        import inspect

        from mahavishnu.mcp.tools.pool_tools import register_pool_tools

        sig = inspect.signature(register_pool_tools)

        # Should accept mcp and pool_manager
        params = list(sig.parameters.keys())
        assert "mcp" in params
        assert "pool_manager" in params

    def test_pool_tools_signature(self):
        """Test pool tools registration function signature."""
        import inspect

        from mahavishnu.mcp.tools.pool_tools import register_pool_tools

        sig = inspect.signature(register_pool_tools)

        # Should accept mcp and pool_manager
        params = list(sig.parameters.keys())
        assert "mcp" in params
        assert "pool_manager" in params


class TestMCPErrorHandling:
    """Test MCP error handling patterns."""

    @pytest.mark.asyncio
    async def test_tool_error_wrapper(self):
        """Test that tool errors are wrapped properly."""
        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.start = AsyncMock(side_effect=RuntimeError("Server error"))

        with pytest.raises(RuntimeError, match="Could not start"):
            await client._ensure_started()

    @pytest.mark.asyncio
    async def test_tool_call_error_logging(self, caplog):
        """Test that tool call errors are logged."""
        import logging

        from mahavishnu.mcp.server_core import McpretentiousMCPClient

        client = McpretentiousMCPClient()
        client._client.start = AsyncMock()
        client._client.list_terminals = AsyncMock(side_effect=Exception("List failed"))

        await client._ensure_started()

        with caplog.at_level(logging.ERROR), pytest.raises(Exception):
            await client.call_tool("mcpretentious-list", {})

        # Verify error was logged
        assert "Error calling mcpretentious tool" in caplog.text or "List failed" in caplog.text


class TestMCPConfiguration:
    """Test MCP configuration handling."""

    def test_server_config_defaults(self):
        """Test that server configuration has proper defaults."""
        from mahavishnu.core.config import MahavishnuSettings

        config = MahavishnuSettings()

        # Should have defaults for basic settings
        assert hasattr(config, "server_name")
        assert hasattr(config, "cache_root")

    def test_server_config_customization(self):
        """Test that server configuration can be customized."""
        from mahavishnu.core.config import MahavishnuSettings

        config = MahavishnuSettings(
            server_name="Custom Server",
            cache_root=".custom_cache",
        )

        assert config.server_name == "Custom Server"
        assert config.cache_root == ".custom_cache"
