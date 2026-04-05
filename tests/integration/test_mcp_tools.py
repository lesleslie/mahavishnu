"""Integration tests for FastMCP tool registration and execution."""

from unittest.mock import AsyncMock, Mock

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.mcp.server_core import FastMCPServer


@pytest.fixture
def mock_app():
    """Create a lightweight app fixture for end-to-end FastMCP tool calls."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.observability.get_performance_metrics = Mock(return_value={})
    app.observability.get_logs = Mock(return_value=[])
    app.observability.flush_metrics = AsyncMock()
    app.opensearch_integration = Mock()
    app.workflow_state_manager = Mock()
    app.rbac_manager = Mock()
    app.resilience_manager = Mock()
    app.error_recovery_manager = Mock()
    app.monitoring_service = Mock()
    app.adapters = {"test_adapter": Mock()}
    app.config = Mock()
    app.config.server_name = "mahavishnu"
    app.config.max_concurrent_workflows = 10
    app.config.auth.enabled = False
    app.config.qc.enabled = False
    app.config.session.enabled = False
    app.config.subscription_auth.enabled = False
    app.config.subscription_auth.secret = None
    app.config.terminal.enabled = False

    app.get_repos = Mock(return_value=["/repo1", "/repo2", "/repo3"])
    app.execute_workflow_parallel = AsyncMock(
        return_value={"status": "completed", "results": [], "repos_processed": 1}
    )
    app.is_healthy = Mock(return_value=True)

    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
    app.workflow_state_manager.get = AsyncMock(return_value={"status": "completed"})
    app.workflow_state_manager.create = AsyncMock()
    app.workflow_state_manager.update = AsyncMock()

    app.rbac_manager.check_permission = AsyncMock(return_value=True)
    app.rbac_manager.get_user_permissions = AsyncMock(return_value=[])
    app.rbac_manager.create_user = AsyncMock(return_value=Mock())

    app.monitoring_service.get_dashboard_data = AsyncMock(
        return_value={
            "metrics": {"system": {}, "workflows": {}, "adapters": {}, "alerts": {}},
            "recent_alerts": [],
            "timestamp": "2023-01-01T00:00:00",
        }
    )
    app.monitoring_service.alert_manager = Mock()
    app.monitoring_service.alert_manager.get_active_alerts = AsyncMock(return_value=[])
    app.monitoring_service.acknowledge_alert = AsyncMock(return_value=True)

    app.backup_manager = Mock()
    app.backup_manager.create_backup = AsyncMock(return_value=Mock())
    app.backup_manager.list_backups = AsyncMock(return_value=[])
    app.backup_manager.restore_backup = AsyncMock(return_value=True)

    app.error_recovery_manager.monitor_and_heal_workflows = AsyncMock()

    return app


@pytest.fixture
def server(mock_app):
    """Create a FastMCP server with the integration fixture app."""
    return FastMCPServer(mock_app)


@pytest.mark.asyncio
async def test_core_tools_are_listed(server):
    """The server should publish the expected core tool inventory."""
    tools = await server.server.list_tools()
    tool_names = {tool.name for tool in tools}

    assert "list_repos" in tool_names
    assert "trigger_workflow" in tool_names
    assert "get_workflow_status" in tool_names
    assert "list_workflows" in tool_names
    assert "get_health" in tool_names


@pytest.mark.asyncio
async def test_list_repos_executes_via_fastmcp_call_tool(server, mock_app):
    """FastMCP should execute list_repos through the public call_tool surface."""
    mock_app.get_repos = Mock(return_value=["/repo1", "/repo2"])

    result = await server.server.call_tool("list_repos", {"tag": "test_tag"})

    assert result is not None
    assert hasattr(result, "content")
    mock_app.get_repos.assert_any_call(tag="test_tag", user_id=None)


@pytest.mark.asyncio
async def test_trigger_workflow_executes_via_fastmcp_call_tool(server, mock_app):
    """Workflow triggering should work through the public FastMCP API."""
    mock_app.execute_workflow_parallel = AsyncMock(
        return_value={"status": "completed", "results": [], "repos_processed": 1}
    )

    result = await server.server.call_tool(
        "trigger_workflow",
        {"adapter": "test_adapter", "task_type": "test_task", "params": {"test": True}},
    )

    assert result is not None
    assert hasattr(result, "content")
    mock_app.execute_workflow_parallel.assert_awaited()


@pytest.mark.asyncio
async def test_get_workflow_status_executes_via_fastmcp_call_tool(server):
    """Workflow status lookup should use the current public tool interface."""
    result = await server.server.call_tool("get_workflow_status", {"workflow_id": "test_wf_123"})

    assert result is not None
    assert hasattr(result, "content")


@pytest.mark.asyncio
async def test_get_health_executes_via_fastmcp_call_tool(server):
    """Health checks should execute without reaching into FastMCP internals."""
    result = await server.server.call_tool("get_health", {})

    assert result is not None
    assert hasattr(result, "content")


@pytest.mark.asyncio
async def test_monitoring_dashboard_executes_via_fastmcp_call_tool(server):
    """Dashboard retrieval should work through the public FastMCP call path."""
    result = await server.server.call_tool("get_monitoring_dashboard", {})

    assert result is not None
    assert hasattr(result, "content")
