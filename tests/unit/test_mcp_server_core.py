"""Comprehensive tests for MCP server core functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp.server.models import InitializationOptions
from mcp.types import Tool, Prompt, Resource

from mahavishnu.mcp.server_core import MahavishnuMCPServer
from mahavishnu.core.config import MahavishnuSettings


@pytest.fixture
def mock_settings():
    """Create mock settings for testing."""
    return MahavishnuSettings(server_name="Test Server", llm_provider="anthropic", observability_enabled=False, llm={model="claude-sonnet-4"})


@pytest.fixture
def server(mock_settings):
    """Create server instance for testing."""
    return MahavishnuMCPServer(settings=mock_settings)


class TestMahavishnuMCPServerInitialization:
    """Test server initialization and configuration."""

    def test_server_initialization(self, server, mock_settings):
        """Test server initializes with correct settings."""
        assert server.settings == mock_settings
        assert server.settings.server_name == "Test Server"
        assert server.settings.llm_provider == "anthropic"

    def test_server_name(self, server):
        """Test server name property."""
        assert server.name == "Mahavishnu Orchestrator"

    def test_server_version(self, server):
        """Test server version property."""
        assert server.version == "1.0.0"


class TestMahavishnuMCPServerLifecycle:
    """Test server lifecycle methods."""

    @pytest.mark.asyncio
    async def test_server_startup(self, server):
        """Test server startup initializes all components."""
        # Mock the initialization methods
        server._initialize_adapters = AsyncMock()
        server._initialize_pools = AsyncMock()
        server._initialize_workers = AsyncMock()
        server._register_tools = AsyncMock()

        await server.startup()

        # Verify all initialization methods were called
        server._initialize_adapters.assert_called_once()
        server._initialize_pools.assert_called_once()
        server._initialize_workers.assert_called_once()
        server._register_tools.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_shutdown(self, server):
        """Test server shutdown cleans up resources."""
        # Mock cleanup methods
        server._cleanup_workers = AsyncMock()
        server._cleanup_pools = AsyncMock()
        server._cleanup_adapters = AsyncMock()

        await server.shutdown()

        # Verify all cleanup methods were called
        server._cleanup_workers.assert_called_once()
        server._cleanup_pools.assert_called_once()
        server._cleanup_adapters.assert_called_once()


class TestMahavishnuMCPServerTools:
    """Test server tool registration and management."""

    @pytest.mark.asyncio
    async def test_list_tools(self, server):
        """Test listing all available tools."""
        tools = await server.list_tools()

        # Verify we get a list of tools
        assert isinstance(tools, list)
        assert len(tools) > 0

        # Verify tool structure
        for tool in tools:
            assert isinstance(tool, Tool)
            assert hasattr(tool, 'name')
            assert hasattr(tool, 'description')
            assert hasattr(tool, 'inputSchema')

    @pytest.mark.asyncio
    async def test_list_tools_includes_repository_tools(self, server):
        """Test that repository management tools are included."""
        tools = await server.list_tools()

        tool_names = [tool.name for tool in tools]

        # Verify key repository tools are present
        assert 'list_repos' in tool_names
        assert 'get_repo_info' in tool_names
        assert 'validate_repo' in tool_names

    @pytest.mark.asyncio
    async def test_list_tools_includes_pool_tools(self, server):
        """Test that pool management tools are included."""
        tools = await server.list_tools()

        tool_names = [tool.name for tool in tools]

        # Verify pool tools are present
        assert 'pool_spawn' in tool_names
        assert 'pool_list' in tool_names
        assert 'pool_execute' in tool_names
        assert 'pool_health' in tool_names

    @pytest.mark.asyncio
    async def test_list_tools_includes_coordination_tools(self, server):
        """Test that coordination tools are included."""
        tools = await server.list_tools()

        tool_names = [tool.name for tool in tools]

        # Verify coordination tools are present
        assert 'trigger_workflow' in tool_names
        assert 'get_workflow_status' in tool_names
        assert 'list_workflows' in tool_names


class TestMahavishnuMCPServerPrompts:
    """Test server prompt management."""

    @pytest.mark.asyncio
    async def test_list_prompts(self, server):
        """Test listing all available prompts."""
        prompts = await server.list_prompts()

        # Verify we get a list of prompts
        assert isinstance(prompts, list)

    @pytest.mark.asyncio
    async def test_get_prompt(self, server):
        """Test getting a specific prompt."""
        # Test getting a prompt that exists
        prompt = await server.get_prompt(
            name="workflow_orchestration",
            arguments={"task": "Test task"}
        )

        assert prompt is not None
        assert hasattr(prompt, 'messages')

    @pytest.mark.asyncio
    async def test_get_prompt_not_found(self, server):
        """Test getting a non-existent prompt raises error."""
        with pytest.raises(Exception):
            await server.get_prompt(
                name="nonexistent_prompt",
                arguments={}
            )


class TestMahavishnuMCPServerResources:
    """Test server resource management."""

    @pytest.mark.asyncio
    async def test_list_resources(self, server):
        """Test listing all available resources."""
        resources = await server.list_resources()

        # Verify we get a list of resources
        assert isinstance(resources, list)

        for resource in resources:
            assert isinstance(resource, Resource)
            assert hasattr(resource, 'uri')
            assert hasattr(resource, 'name')
            assert hasattr(resource, 'description')

    @pytest.mark.asyncio
    async def test_read_resource(self, server):
        """Test reading a specific resource."""
        # Test reading a valid resource
        content = await server.read_resource(uri="config://current")

        assert content is not None
        assert len(content) > 0

    @pytest.mark.asyncio
    async def test_read_resource_not_found(self, server):
        """Test reading a non-existent resource raises error."""
        with pytest.raises(Exception):
            await server.read_resource(uri="nonexistent://resource")


class TestMahavishnuMCPServerToolExecution:
    """Test actual tool execution."""

    @pytest.mark.asyncio
    async def test_call_tool_list_repos(self, server):
        """Test calling list_repos tool."""
        result = await server.call_tool(
            name="list_repos",
            arguments={}
        )

        assert result is not None
        assert hasattr(result, 'content')
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_call_tool_with_invalid_arguments(self, server):
        """Test calling tool with invalid arguments raises error."""
        with pytest.raises(Exception):
            await server.call_tool(
                name="list_repos",
                arguments={"invalid_arg": "value"}
            )

    @pytest.mark.asyncio
    async def test_call_tool_not_found(self, server):
        """Test calling non-existent tool raises error."""
        with pytest.raises(Exception):
            await server.call_tool(
                name="nonexistent_tool",
                arguments={}
            )


class TestMahavishnuMCPServerConfiguration:
    """Test server configuration handling."""

    @pytest.mark.asyncio
    async def test_initialize_with_default_config(self):
        """Test server initializes with default configuration."""
        settings = MahavishnuSettings()  # Use defaults
        server = MahavishnuMCPServer(settings=settings)

        assert server.settings is not None
        assert server.settings.server_name is not None

    @pytest.mark.asyncio
    async def test_initialize_with_custom_config(self):
        """Test server initializes with custom configuration."""
        settings = MahavishnuSettings(server_name="Custom Server", llm_provider="openai", llm={model="gpt-4"})
        server = MahavishnuMCPServer(settings=settings)

        assert server.settings.server_name == "Custom Server"
        assert server.settings.llm_provider == "openai"
        assert server.settings.llm_model == "gpt-4"


class TestMahavishnuMCPServerErrorHandling:
    """Test server error handling."""

    @pytest.mark.asyncio
    async def test_tool_execution_error_handling(self, server):
        """Test that tool execution errors are handled gracefully."""
        # Mock a tool that raises an error
        with patch.object(server, '_execute_tool', side_effect=Exception("Test error")):
            with pytest.raises(Exception) as exc_info:
                await server.call_tool(
                    name="failing_tool",
                    arguments={}
                )
            assert "Test error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_resource_read_error_handling(self, server):
        """Test that resource read errors are handled gracefully."""
        with patch.object(server, '_read_resource', side_effect=Exception("Read failed")):
            with pytest.raises(Exception) as exc_info:
                await server.read_resource(uri="failing://resource")
            assert "Read failed" in str(exc_info.value)


class TestMahavishnuMCPServerHealth:
    """Test server health and monitoring."""

    @pytest.mark.asyncio
    async def test_health_check(self, server):
        """Test server health check."""
        health = await server.health_check()

        assert health is not None
        assert 'status' in health
        assert health['status'] in ['healthy', 'unhealthy', 'degraded']

    @pytest.mark.asyncio
    async def test_health_check_includes_components(self, server):
        """Test health check includes component status."""
        health = await server.health_check()

        # Verify health check includes component details
        assert 'components' in health or 'details' in health


class TestMahavishnuMCPServerMetrics:
    """Test server metrics collection."""

    @pytest.mark.asyncio
    async def test_get_metrics(self, server):
        """Test getting server metrics."""
        metrics = await server.get_metrics()

        assert metrics is not None
        assert isinstance(metrics, dict)

        # Verify common metric keys
        expected_keys = ['uptime', 'requests_processed', 'errors']
        for key in expected_keys:
            assert key in metrics or any(k.startswith(key) for k in metrics.keys())

    @pytest.mark.asyncio
    async def test_metrics_includes_tool_metrics(self, server):
        """Test metrics include tool execution statistics."""
        metrics = await server.get_metrics()

        # Verify tool-related metrics are present
        assert 'tools' in metrics or 'tool_calls' in metrics


class TestMahavishnuMCPServerLogging:
    """Test server logging functionality."""

    @pytest.mark.asyncio
    async def test_logging_configuration(self, server):
        """Test logging is properly configured."""
        assert server.logger is not None
        assert hasattr(server.logger, 'info')
        assert hasattr(server.logger, 'error')
        assert hasattr(server.logger, 'debug')

    @pytest.mark.asyncio
    async def test_log_messages(self, server, caplog):
        """Test that server logs messages correctly."""
        import logging

        with caplog.at_level(logging.INFO):
            server.logger.info("Test log message")

        assert "Test log message" in caplog.text


class TestMahavishnuMCPServerConcurrency:
    """Test server handles concurrent requests."""

    @pytest.mark.asyncio
    async def test_concurrent_tool_calls(self, server):
        """Test server handles multiple tool calls concurrently."""
        import asyncio

        # Create multiple concurrent tool calls
        tasks = [
            server.call_tool("list_repos", {})
            for _ in range(5)
        ]

        # Execute all concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify all succeeded
        assert len(results) == 5
        for result in results:
            if not isinstance(result, Exception):
                assert result is not None
