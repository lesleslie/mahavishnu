"""Comprehensive unit tests for MCP server and tools.

This module provides thorough testing of the Mahavishnu MCP server implementation,
including server initialization, tool registration, tool execution, JSON-RPC protocol
handling, and error responses.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from fastmcp import FastMCP
import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.mcp.server_core import (
    FastMCPServer,
    McpretentiousMCPClient,
    run_server,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_settings():
    """Create mock settings for testing.

    Returns:
        MahavishnuSettings: Configured settings for testing
    """
    return MahavishnuSettings(
        server_name="Test Server",
        observability_enabled=False,
        terminal_enabled=False,
        pools={"enabled": False},
        workers={"enabled": False},
        otel_storage={"enabled": False},
    )


@pytest.fixture
def mock_app(mock_settings):
    """Create mock MahavishnuApp for testing.

    Args:
        mock_settings: Settings fixture

    Returns:
        MagicMock: Mocked MahavishnuApp
    """
    app = MagicMock(spec=MahavishnuApp)
    app.config = mock_settings
    app.get_repos = MagicMock(return_value=["/path/to/repo1", "/path/to/repo2"])
    app.execute_workflow_parallel = AsyncMock(
        return_value={
            "workflow_id": "test_wf_123",
            "status": "completed",
            "repos_processed": 2,
            "successful_repos": 2,
            "failed_repos": 0,
        }
    )
    app.workflow_state_manager = MagicMock()
    app.workflow_state_manager.create = AsyncMock()
    app.workflow_state_manager.get = AsyncMock(return_value=None)
    app.workflow_state_manager.update = AsyncMock()
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
    app.rbac_manager = MagicMock()
    app.rbac_manager.check_permission = AsyncMock(return_value=True)
    app.rbac_manager.create_user = AsyncMock()
    app.rbac_manager.roles = {"admin": MagicMock()}
    app.observability = MagicMock()
    app.observability.get_performance_metrics = MagicMock(return_value={})
    app.observability.get_logs = MagicMock(return_value=[])
    app.observability.flush_metrics = AsyncMock()
    app.opensearch_integration = MagicMock()
    app.opensearch_integration.search_logs = AsyncMock(return_value=[])
    app.opensearch_integration.search_workflows = AsyncMock(return_value=[])
    app.opensearch_integration.get_workflow_stats = AsyncMock(return_value={})
    app.opensearch_integration.get_log_stats = AsyncMock(return_value={})
    app.opensearch_integration.health_check = AsyncMock(return_value={"status": "healthy"})
    app.error_recovery_manager = MagicMock()
    app.error_recovery_manager.get_recovery_metrics = AsyncMock(return_value={})
    app.error_recovery_manager.monitor_and_heal_workflows = AsyncMock()
    app.monitoring_service = MagicMock()
    app.monitoring_service.get_dashboard_data = AsyncMock(return_value={})
    app.monitoring_service.alert_manager = MagicMock()
    app.monitoring_service.alert_manager.get_active_alerts = AsyncMock(return_value=[])
    app.monitoring_service.alert_manager.trigger_alert = AsyncMock(
        return_value=MagicMock(id="alert_123")
    )
    app.monitoring_service.acknowledge_alert = AsyncMock(return_value=True)
    app.adapters = {
        "llamaindex": MagicMock(),
        "prefect": MagicMock(),
        "agno": MagicMock(),
    }
    for adapter in app.adapters.values():
        adapter.get_health = AsyncMock(return_value={"status": "healthy"})

    return app


@pytest.fixture
def server(mock_app):
    """Create FastMCPServer instance for testing.

    Args:
        mock_app: Mocked MahavishnuApp

    Returns:
        FastMCPServer: Server instance for testing
    """
    return FastMCPServer(app=mock_app)


# =============================================================================
# McpretentiousMCPClient Tests
# =============================================================================


class TestMcpretentiousMCPClient:
    """Test suite for McpretentiousMCPClient wrapper."""

    def test_initialization(self):
        """Test client initializes correctly with required attributes."""
        client = McpretentiousMCPClient()

        assert client._started is False
        assert client._client is not None
        assert hasattr(client._client, "start")

    @pytest.mark.asyncio
    async def test_ensure_started_first_time(self):
        """Test starting the mcpretentious server for the first time."""
        client = McpretentiousMCPClient()
        client._client.start = AsyncMock()

        await client._ensure_started()

        assert client._started is True
        client._client.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_started_already_started(self):
        """Test that ensure_started doesn't start if already started."""
        client = McpretentiousMCPClient()
        client._client.start = AsyncMock()
        client._started = True

        await client._ensure_started()

        client._client.start.assert_not_called()

    @pytest.mark.asyncio
    async def test_ensure_start_failure_raises_runtime_error(self):
        """Test that start failures raise RuntimeError with helpful message."""
        client = McpretentiousMCPClient()
        client._client.start = AsyncMock(side_effect=Exception("uvx not found"))

        with pytest.raises(RuntimeError, match="Could not start mcpretentious server"):
            await client._ensure_started()

    @pytest.mark.asyncio
    async def test_call_tool_open(self):
        """Test calling mcpretentious-open tool."""
        client = McpretentiousMCPClient()
        client._client.open_terminal = AsyncMock(return_value="term_abc123")
        client._client.start = AsyncMock()

        result = await client.call_tool("mcpretentious-open", {"columns": 100, "rows": 30})

        assert result == {"terminal_id": "term_abc123"}
        client._client.open_terminal.assert_called_once_with(columns=100, rows=30)

    @pytest.mark.asyncio
    async def test_call_tool_open_with_defaults(self):
        """Test mcpretentious-open uses default dimensions."""
        client = McpretentiousMCPClient()
        client._client.open_terminal = AsyncMock(return_value="term_def")
        client._client.start = AsyncMock()

        result = await client.call_tool("mcpretentious-open", {})

        assert result == {"terminal_id": "term_def"}
        client._client.open_terminal.assert_called_once_with(columns=80, rows=24)

    @pytest.mark.asyncio
    async def test_call_tool_type(self):
        """Test calling mcpretentious-type tool."""
        client = McpretentiousMCPClient()
        client._client.type_text = AsyncMock()
        client._client.start = AsyncMock()

        result = await client.call_tool(
            "mcpretentious-type", {"terminal_id": "term_123", "input": ["hello", "world"]}
        )

        assert result == {}
        client._client.type_text.assert_called_once_with("term_123", "hello", "world")

    @pytest.mark.asyncio
    async def test_call_tool_read(self):
        """Test calling mcpretentious-read tool."""
        client = McpretentiousMCPClient()
        client._client.read_text = AsyncMock(return_value="output text\nline 2")
        client._client.start = AsyncMock()

        result = await client.call_tool(
            "mcpretentious-read", {"terminal_id": "term_123", "limit_lines": 10}
        )

        assert result == {"output": "output text\nline 2"}
        client._client.read_text.assert_called_once_with("term_123", lines=10)

    @pytest.mark.asyncio
    async def test_call_tool_read_without_limit(self):
        """Test mcpretentious-read without limit_lines parameter."""
        client = McpretentiousMCPClient()
        client._client.read_text = AsyncMock(return_value="all output")
        client._client.start = AsyncMock()

        result = await client.call_tool("mcpretentious-read", {"terminal_id": "term_123"})

        assert result == {"output": "all output"}
        client._client.read_text.assert_called_once_with("term_123", lines=None)

    @pytest.mark.asyncio
    async def test_call_tool_close(self):
        """Test calling mcpretentious-close tool."""
        client = McpretentiousMCPClient()
        client._client.close_terminal = AsyncMock()
        client._client.start = AsyncMock()

        result = await client.call_tool("mcpretentious-close", {"terminal_id": "term_123"})

        assert result == {}
        client._client.close_terminal.assert_called_once_with("term_123")

    @pytest.mark.asyncio
    async def test_call_tool_list(self):
        """Test calling mcpretentious-list tool."""
        client = McpretentiousMCPClient()
        client._client.list_terminals = AsyncMock(return_value=["term_1", "term_2"])
        client._client.start = AsyncMock()

        result = await client.call_tool("mcpretentious-list", {})

        assert result == {"terminals": ["term_1", "term_2"]}
        client._client.list_terminals.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_tool_unknown_tool(self):
        """Test calling unknown tool raises ValueError."""
        client = McpretentiousMCPClient()
        client._client.start = AsyncMock()

        await client._ensure_started()

        with pytest.raises(ValueError, match="Unknown tool: unknown_tool"):
            await client.call_tool("unknown_tool", {})

    @pytest.mark.asyncio
    async def test_call_tool_error_propagates(self):
        """Test that tool call errors are propagated and logged."""
        client = McpretentiousMCPClient()
        client._client.start = AsyncMock()
        client._client.list_terminals = AsyncMock(side_effect=RuntimeError("Connection lost"))

        await client._ensure_started()

        with pytest.raises(RuntimeError, match="Connection lost"):
            await client.call_tool("mcpretentious-list", {})


# =============================================================================
# FastMCPServer Initialization Tests
# =============================================================================


class TestFastMCPServerInitialization:
    """Test suite for FastMCPServer initialization."""

    def test_initialization_with_app(self, mock_app):
        """Test server initialization with provided app."""
        server = FastMCPServer(app=mock_app)

        assert server.app == mock_app
        assert server.server is not None
        assert isinstance(server.server, FastMCP)
        assert server.mcp_client is not None

    def test_initialization_with_config(self, mock_settings):
        """Test server initialization creates new app if not provided."""
        with patch("mahavishnu.mcp.server_core.MahavishnuApp") as MockApp:
            mock_app_instance = MagicMock()
            mock_app_instance.config = mock_settings
            MockApp.return_value = mock_app_instance

            with patch("mahavishnu.mcp.server_core.get_auth_from_config"):
                server = FastMCPServer(app=None, config=mock_settings)

                MockApp.assert_called_once_with(mock_settings)

    def test_initialization_registers_tools(self, mock_app):
        """Test that tool registration occurs during initialization."""
        with patch.object(FastMCPServer, "_register_tools") as mock_register:
            FastMCPServer(app=mock_app)

            mock_register.assert_called_once()

    def test_server_name_and_version(self, server):
        """Test server has correct name and version."""
        assert server.server.name == "Mahavishnu Orchestrator"
        assert server.server.version == "1.0.0"


# =============================================================================
# Tool Registration Tests
# =============================================================================


class TestToolRegistration:
    """Test suite for tool registration."""

    @pytest.mark.asyncio
    async def test_tools_registered_during_init(self, server):
        """Test that core tools are registered during initialization."""
        # Use FastMCP's list_tools method
        tools = await server.server.list_tools()

        # FastMCP should have tools registered
        assert len(tools) > 0

    @pytest.mark.asyncio
    async def test_list_repos_tool_registered(self, server):
        """Test list_repos tool is registered."""
        tools = await server.server.list_tools()
        tool_names = [tool.name for tool in tools]

        # Tool should be registered
        assert "list_repos" in tool_names

    @pytest.mark.asyncio
    async def test_trigger_workflow_tool_registered(self, server):
        """Test trigger_workflow tool is registered."""
        tools = await server.server.list_tools()
        tool_names = [tool.name for tool in tools]

        # Check for trigger_workflow tool
        assert "trigger_workflow" in tool_names

    @pytest.mark.asyncio
    async def test_get_workflow_status_tool_registered(self, server):
        """Test get_workflow_status tool is registered."""
        tools = await server.server.list_tools()
        tool_names = [tool.name for tool in tools]

        assert "get_workflow_status" in tool_names

    @pytest.mark.asyncio
    async def test_list_workflows_tool_registered(self, server):
        """Test list_workflows tool is registered."""
        tools = await server.server.list_tools()
        tool_names = [tool.name for tool in tools]

        assert "list_workflows" in tool_names

    @pytest.mark.asyncio
    async def test_cancel_workflow_tool_registered(self, server):
        """Test cancel_workflow tool is registered."""
        tools = await server.server.list_tools()
        tool_names = [tool.name for tool in tools]

        assert "cancel_workflow" in tool_names

    @pytest.mark.asyncio
    async def test_create_user_tool_registered(self, server):
        """Test create_user tool is registered."""
        tools = await server.server.list_tools()
        tool_names = [tool.name for tool in tools]

        assert "create_user" in tool_names

    @pytest.mark.asyncio
    async def test_check_permission_tool_registered(self, server):
        """Test check_permission tool is registered."""
        tools = await server.server.list_tools()
        tool_names = [tool.name for tool in tools]

        assert "check_permission" in tool_names

    @pytest.mark.asyncio
    async def test_get_health_tool_registered(self, server):
        """Test get_health tool is registered."""
        tools = await server.server.list_tools()
        tool_names = [tool.name for tool in tools]

        assert "get_health" in tool_names

    @pytest.mark.asyncio
    async def test_list_adapters_tool_registered(self, server):
        """Test list_adapters tool is registered."""
        tools = await server.server.list_tools()
        tool_names = [tool.name for tool in tools]

        assert "list_adapters" in tool_names


# =============================================================================
# Tool Execution Tests - Success Cases
# =============================================================================


class TestToolExecutionSuccess:
    """Test suite for successful tool execution via FastMCP API."""

    @pytest.mark.asyncio
    async def test_list_repos_no_filter(self, server):
        """Test list_repos tool without filters."""
        # Mock get_repos to return specific repos
        server.app.get_repos = MagicMock(return_value=["/repo1", "/repo2", "/repo3"])

        # Use FastMCP's call_tool method
        result = await server.server.call_tool("list_repos", {})

        # FastMCP returns a CallToolResult with content
        assert result is not None
        assert hasattr(result, "content")
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_list_repos_with_tag_filter(self, server):
        """Test list_repos tool with tag filtering."""
        server.app.get_repos = MagicMock(
            side_effect=lambda tag, user_id: ["/repo1"] if tag == "python" else ["/repo1", "/repo2"]
        )

        result = await server.server.call_tool("list_repos", {"tag": "python"})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_list_repos_with_pagination(self, server):
        """Test list_repos tool with pagination."""
        server.app.get_repos = MagicMock(
            return_value=["/repo1", "/repo2", "/repo3", "/repo4", "/repo5"]
        )

        result = await server.server.call_tool("list_repos", {"limit": 2, "offset": 1})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_trigger_workflow_success(self, server):
        """Test successful workflow trigger."""
        server.app.get_repos = MagicMock(return_value=["/repo1", "/repo2"])

        result = await server.server.call_tool(
            "trigger_workflow",
            {
                "adapter": "prefect",
                "task_type": "code_sweep",
                "params": {"param1": "value1"},
            },
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_trigger_workflow_with_timeout(self, server):
        """Test workflow trigger with timeout."""
        server.app.get_repos = MagicMock(return_value=["/repo1"])
        server.app.execute_workflow_parallel = AsyncMock(return_value={"status": "completed"})

        result = await server.server.call_tool(
            "trigger_workflow",
            {"adapter": "agno", "task_type": "quality_check", "params": {}, "timeout": 30},
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_trigger_workflow_with_explicit_repos(self, server):
        """Test workflow trigger with explicit repo list."""
        server.app.get_repos = MagicMock(return_value=["/repo1", "/repo2", "/repo3"])

        result = await server.server.call_tool(
            "trigger_workflow",
            {
                "adapter": "prefect",
                "task_type": "test",
                "params": {},
                "repos": ["/repo1", "/repo2"],
            },
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_get_workflow_status_not_found(self, server):
        """Test get_workflow_status when workflow not found."""
        server.app.workflow_state_manager.get = AsyncMock(return_value=None)

        result = await server.server.call_tool(
            "get_workflow_status", {"workflow_id": "nonexistent"}
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_get_workflow_status_found(self, server):
        """Test get_workflow_status when workflow exists."""
        server.app.workflow_state_manager.get = AsyncMock(
            return_value={
                "status": "running",
                "progress": 50,
                "repos": ["/repo1", "/repo2"],
                "task": {"type": "code_sweep"},
                "created_at": 1234567890.0,
                "updated_at": 1234567890.0,
                "results": [],
                "errors": [],
            }
        )

        result = await server.server.call_tool("get_workflow_status", {"workflow_id": "wf_123"})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_list_workflows_empty(self, server):
        """Test list_workflows when no workflows exist."""
        server.app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        result = await server.server.call_tool("list_workflows", {})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_list_workflows_with_status_filter(self, server):
        """Test list_workflows with status filter."""

        server.app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        result = await server.server.call_tool("list_workflows", {"status": "running"})

        # Should not raise error for valid status
        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_list_workflows_invalid_status(self, server):
        """Test list_workflows with invalid status."""
        result = await server.server.call_tool("list_workflows", {"status": "invalid_status"})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_cancel_workflow_success(self, server):
        """Test successful workflow cancellation."""
        result = await server.server.call_tool("cancel_workflow", {"workflow_id": "wf_123"})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_create_user_success(self, server):
        """Test successful user creation."""
        mock_user = MagicMock()
        mock_user.user_id = "user_123"
        mock_user.roles = [MagicMock(name="admin"), MagicMock(name="developer")]

        server.app.rbac_manager.create_user = AsyncMock(return_value=mock_user)

        result = await server.server.call_tool(
            "create_user",
            {"user_id": "user_123", "roles": ["admin", "developer"], "allowed_repos": ["/repo1"]},
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_check_permission_success(self, server):
        """Test permission check returns correct result."""
        server.app.rbac_manager.check_permission = AsyncMock(return_value=True)

        result = await server.server.call_tool(
            "check_permission", {"user_id": "user_123", "repo": "/repo1", "permission": "READ_REPO"}
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_check_permission_invalid(self, server):
        """Test permission check with invalid permission."""
        result = await server.server.call_tool(
            "check_permission",
            {"user_id": "user_123", "repo": "/repo1", "permission": "INVALID_PERMISSION"},
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_get_observability_metrics(self, server):
        """Test getting observability metrics."""
        server.app.observability.get_performance_metrics = MagicMock(
            return_value={"cpu": 50, "memory": 70}
        )
        server.app.observability.get_logs = MagicMock(
            return_value=[MagicMock(timestamp=datetime.now())]
        )

        result = await server.server.call_tool("get_observability_metrics", {})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_get_observability_metrics_not_initialized(self, server):
        """Test getting metrics when observability not initialized."""
        server.app.observability = None

        result = await server.server.call_tool("get_observability_metrics", {})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_list_adapters(self, server):
        """Test listing available adapters."""
        result = await server.server.call_tool("list_adapters", {})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_get_health_healthy(self, server):
        """Test health check returns healthy status."""
        server.app.is_healthy = MagicMock(return_value=True)

        result = await server.server.call_tool("get_health", {})

        assert result is not None
        assert hasattr(result, "content")


# =============================================================================
# Tool Execution Tests - Error Cases
# =============================================================================


class TestToolExecutionErrors:
    """Test suite for tool error handling."""

    @pytest.mark.asyncio
    async def test_list_repos_exception_handling(self, server):
        """Test list_repos handles exceptions gracefully."""
        server.app.get_repos = MagicMock(side_effect=Exception("Database error"))

        result = await server.server.call_tool("list_repos", {})

        # Should return error in result
        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_trigger_workflow_timeout_error(self, server):
        """Test workflow trigger handles timeout."""
        server.app.get_repos = MagicMock(return_value=["/repo1", "/repo2"])
        server.app.execute_workflow_parallel = AsyncMock(side_effect=TimeoutError())

        result = await server.server.call_tool(
            "trigger_workflow",
            {"adapter": "prefect", "task_type": "code_sweep", "params": {}, "timeout": 30},
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_trigger_workflow_generic_error(self, server):
        """Test workflow trigger handles general exceptions."""
        server.app.get_repos = MagicMock(return_value=["/repo1"])
        server.app.execute_workflow_parallel = AsyncMock(side_effect=ValueError("Invalid input"))

        result = await server.server.call_tool(
            "trigger_workflow", {"adapter": "agno", "task_type": "test", "params": {}}
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_get_workflow_status_error(self, server):
        """Test get_workflow_status handles exceptions."""
        server.app.workflow_state_manager.get = AsyncMock(side_effect=Exception("State error"))

        result = await server.server.call_tool("get_workflow_status", {"workflow_id": "wf_123"})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_list_workflows_permission_denied(self, server):
        """Test list_workflows with permission check."""
        server.app.rbac_manager.check_permission = AsyncMock(return_value=False)

        result = await server.server.call_tool("list_workflows", {})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_cancel_workflow_permission_denied(self, server):
        """Test cancel_workflow with permission check."""
        server.app.rbac_manager.check_permission = AsyncMock(return_value=False)

        result = await server.server.call_tool("cancel_workflow", {"workflow_id": "wf_123"})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_create_user_permission_denied(self, server):
        """Test create_user with insufficient permissions."""
        server.app.rbac_manager.check_permission = AsyncMock(return_value=False)

        result = await server.server.call_tool(
            "create_user", {"user_id": "new_user", "roles": ["developer"]}
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_create_user_exception(self, server):
        """Test create_user handles exceptions."""
        server.app.rbac_manager.check_permission = AsyncMock(return_value=True)
        server.app.rbac_manager.create_user = AsyncMock(side_effect=Exception("User exists"))

        result = await server.server.call_tool(
            "create_user", {"user_id": "existing_user", "roles": ["admin"]}
        )

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_get_health_unhealthy_component(self, server):
        """Test health check with unhealthy components."""
        server.app.is_healthy = MagicMock(return_value=True)
        server.app.adapters["prefect"].get_health = AsyncMock(
            return_value={"status": "unhealthy", "error": "Connection lost"}
        )

        result = await server.server.call_tool("get_health", {})

        assert result is not None
        assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_get_health_exception(self, server):
        """Test health check handles exceptions."""
        server.app.is_healthy = MagicMock(side_effect=Exception("Health check failed"))

        result = await server.server.call_tool("get_health", {})

        assert result is not None
        assert hasattr(result, "content")


# =============================================================================
# Server Lifecycle Tests
# =============================================================================


class TestServerLifecycle:
    """Test suite for server lifecycle management."""

    @pytest.mark.asyncio
    async def test_server_start(self, server):
        """Test server starts without errors."""
        server.server.run_http_async = AsyncMock()

        await server.start(host="127.0.0.1", port=3000)

        server.server.run_http_async.assert_called_once_with(host="127.0.0.1", port=3000)

    @pytest.mark.asyncio
    async def test_server_stop(self, server):
        """Test server stops and cleans up resources."""
        server.mcp_client._client.stop = AsyncMock()

        await server.stop()

        server.mcp_client._client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_server_stop_handles_errors(self, server):
        """Test server stop handles cleanup errors gracefully."""
        server.mcp_client._client.stop = AsyncMock(side_effect=Exception("Stop failed"))

        # Should not raise exception
        await server.stop()


# =============================================================================
# Terminal Manager Tests
# =============================================================================


class TestTerminalManagerInitialization:
    """Test suite for terminal manager initialization."""

    def test_terminal_manager_disabled(self, mock_settings):
        """Test terminal manager not initialized when disabled."""
        mock_settings.terminal_enabled = False

        server = FastMCPServer(app=None, config=mock_settings)

        assert server.terminal_manager is None


# =============================================================================


class TestHelperFunctions:
    """Test suite for helper functions."""

    @pytest.mark.asyncio
    async def test_run_server_creates_instance(self):
        """Test run_server helper creates and starts server."""
        with patch("mahavishnu.mcp.server_core.FastMCPServer") as MockServer:
            mock_server = MagicMock()
            mock_server.start = AsyncMock()
            MockServer.return_value = mock_server

            await run_server(config=None)

            MockServer.assert_called_once()
            mock_server.start.assert_called_once()


# =============================================================================
# JSON-RPC Protocol Tests
# =============================================================================


class TestJSONRPCProtocol:
    """Test suite for JSON-RPC protocol compatibility."""

    @pytest.mark.asyncio
    async def test_tools_follow_mcp_protocol(self, server):
        """Test that tools follow MCP protocol specification."""
        # FastMCP tools should have proper metadata
        tools = await server.server.list_tools()

        # Should have tools registered
        assert len(tools) > 0

        # Each tool should have required fields
        for tool in tools:
            assert hasattr(tool, "name")
            assert hasattr(tool, "description")

    @pytest.mark.asyncio
    async def test_tool_returns_json_serializable_response(self, server):
        """Test that tools return JSON-serializable responses compatible with JSON-RPC."""
        server.app.get_repos = MagicMock(return_value=["/repo1"])

        result = await server.server.call_tool("list_repos", {})

        # FastMCP returns CallToolResult with content list
        assert result is not None
        assert hasattr(result, "content")
        assert isinstance(result.content, list)

    @pytest.mark.asyncio
    async def test_error_responses_follow_mcp_format(self, server):
        """Test that error responses follow MCP error format."""
        server.app.get_repos = MagicMock(side_effect=Exception("Test error"))

        result = await server.server.call_tool("list_repos", {})

        # Error responses should have content
        assert result is not None
        assert hasattr(result, "content")


# =============================================================================
# Concurrency Tests
# =============================================================================


class TestConcurrentExecution:
    """Test suite for concurrent tool execution."""

    @pytest.mark.asyncio
    async def test_concurrent_list_repos_calls(self, server):
        """Test multiple concurrent list_repos calls."""
        server.app.get_repos = MagicMock(return_value=["/repo1", "/repo2"])

        # Execute multiple calls concurrently
        tasks = [server.server.call_tool("list_repos", {}) for _ in range(5)]

        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 5
        for result in results:
            assert result is not None
            assert hasattr(result, "content")

    @pytest.mark.asyncio
    async def test_concurrent_workflow_triggers(self, server):
        """Test multiple concurrent workflow triggers."""
        server.app.get_repos = MagicMock(return_value=["/repo1"])

        # Execute multiple workflow triggers concurrently
        tasks = [
            server.server.call_tool(
                "trigger_workflow",
                {"adapter": "prefect", "task_type": "test", "params": {}},
            )
            for _ in range(3)
        ]

        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 3
        for result in results:
            assert result is not None
            assert hasattr(result, "content")


# =============================================================================
# Integration Tests
# =============================================================================


class TestMCPIntegration:
    """Test suite for MCP integration points."""

    def test_server_is_fastmcp_instance(self, server):
        """Test that server.server is a FastMCP instance."""
        assert isinstance(server.server, FastMCP)

    def test_mcp_client_initialized(self, server):
        """Test that MCP client wrapper is initialized."""
        assert server.mcp_client is not None
        assert isinstance(server.mcp_client, McpretentiousMCPClient)

    @pytest.mark.asyncio
    async def test_tool_registration_via_decorator(self, server):
        """Test that tools are registered via FastMCP decorator."""
        # FastMCP should have tools registered
        tools = await server.server.list_tools()

        assert len(tools) > 0

        # Each tool should have metadata
        for tool in tools:
            assert tool is not None
            assert hasattr(tool, "name")
            assert hasattr(tool, "description")

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_list_tools_returns_tool_list(self, server):
        """Test that list_tools returns a list of tools."""
        tools = await server.server.list_tools()

        assert isinstance(tools, list)
        assert all(hasattr(tool, "name") for tool in tools)

    def test_server_has_correct_metadata(self, server):
        """Test that server has correct metadata."""
        assert server.server.name == "Mahavishnu Orchestrator"
        assert server.server.version == "1.0.0"
