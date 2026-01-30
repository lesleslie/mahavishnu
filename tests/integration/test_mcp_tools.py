"""Tests for MCP server tools and functionality."""

from unittest.mock import AsyncMock, Mock

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.mcp.server_core import FastMCPServer


@pytest.fixture
def mock_app():
    """Create a mock app for testing."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = Mock()
    app.workflow_state_manager = Mock()
    app.rbac_manager = Mock()
    app.resilience_manager = Mock()
    app.error_recovery_manager = Mock()
    app.monitoring_service = Mock()
    app.adapters = {"test_adapter": Mock()}
    app.config = Mock()
    app.config.max_concurrent_workflows = 10
    app.config.auth_enabled = False
    app.config.qc_enabled = False
    app.config.session_enabled = False
    app.config.subscription_auth_enabled = False
    app.config.subscription_auth_secret = None

    # Mock the workflow state manager
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
    app.workflow_state_manager.get = AsyncMock(return_value={"status": "completed"})
    app.workflow_state_manager.create = AsyncMock()
    app.workflow_state_manager.update = AsyncMock()

    # Mock the RBAC manager
    app.rbac_manager.check_permission = AsyncMock(return_value=True)
    app.rbac_manager.get_user_permissions = AsyncMock(return_value=[])

    # Mock the monitoring service
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

    # Mock the backup manager
    app.backup_manager = Mock()
    app.backup_manager.create_backup = AsyncMock(return_value=Mock())
    app.backup_manager.list_backups = AsyncMock(return_value=[])
    app.backup_manager.restore_backup = AsyncMock(return_value=True)

    # Mock the error recovery manager
    app.error_recovery_manager.monitor_and_heal_workflows = AsyncMock()

    return app


@pytest.mark.asyncio
async def test_mcp_server_initialization(mock_app):
    """Test that MCP server initializes correctly."""
    server = FastMCPServer(mock_app)

    # Verify server was initialized
    assert server.app == mock_app
    assert server.server is not None
    assert server.mcp_client is not None


@pytest.mark.asyncio
async def test_list_repos_tool(mock_app):
    """Test the list_repos MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the app's get_repos method
    mock_app.get_repos = Mock(return_value=["/repo1", "/repo2", "/repo3"])

    # Call the tool directly
    result = await server.server._tools["list_repos"].handler(tag="test_tag")

    # Verify result structure
    assert "repos" in result
    assert "total_count" in result
    assert "filtered_count" in result
    assert result["total_count"] >= 0


@pytest.mark.asyncio
async def test_trigger_workflow_tool(mock_app):
    """Test the trigger_workflow MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the execute_workflow_parallel method
    mock_app.execute_workflow_parallel = AsyncMock(
        return_value={"status": "completed", "results": [], "repos_processed": 1}
    )

    # Call the tool directly
    result = await server.server._tools["trigger_workflow"].handler(
        adapter="test_adapter", task_type="test_task", params={"test": True}
    )

    # Verify result structure
    assert "workflow_id" in result
    assert "status" in result
    assert "result" in result


@pytest.mark.asyncio
async def test_get_workflow_status_tool(mock_app):
    """Test the get_workflow_status MCP tool."""
    server = FastMCPServer(mock_app)

    # Call the tool directly
    result = await server.server._tools["get_workflow_status"].handler(workflow_id="test_wf_123")

    # Verify result structure
    assert "workflow_id" in result
    assert result["workflow_id"] == "test_wf_123"
    assert "status" in result


@pytest.mark.asyncio
async def test_cancel_workflow_tool(mock_app):
    """Test the cancel_workflow MCP tool."""
    server = FastMCPServer(mock_app)

    # Call the tool directly
    result = await server.server._tools["cancel_workflow"].handler(workflow_id="test_wf_123")

    # Verify result structure
    assert "workflow_id" in result
    assert result["workflow_id"] == "test_wf_123"
    assert "status" in result


@pytest.mark.asyncio
async def test_list_adapters_tool(mock_app):
    """Test the list_adapters MCP tool."""
    server = FastMCPServer(mock_app)

    # Call the tool directly
    result = await server.server._tools["list_adapters"].handler()

    # Verify result structure
    assert "adapters" in result
    assert "count" in result
    assert "available_names" in result


@pytest.mark.asyncio
async def test_get_health_tool(mock_app):
    """Test the get_health MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock adapter health
    mock_adapter = Mock()
    mock_adapter.get_health = AsyncMock(return_value={"status": "healthy"})
    mock_app.adapters = {"test_adapter": mock_adapter}

    # Call the tool directly
    result = await server.server._tools["get_health"].handler()

    # Verify result structure
    assert "status" in result
    assert "adapter_health" in result
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_list_workflows_tool(mock_app):
    """Test the list_workflows MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the workflow state manager
    mock_app.workflow_state_manager.list_workflows = AsyncMock(
        return_value=[{"id": "wf1", "status": "completed"}, {"id": "wf2", "status": "running"}]
    )

    # Call the tool directly
    result = await server.server._tools["list_workflows"].handler()

    # Verify result structure
    assert "workflows" in result
    assert "total_count" in result
    assert "returned_count" in result


@pytest.mark.asyncio
async def test_check_permission_tool(mock_app):
    """Test the check_permission MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the RBAC manager
    mock_app.rbac_manager.check_permission = AsyncMock(return_value=True)

    # Call the tool directly
    result = await server.server._tools["check_permission"].handler(
        user_id="test_user", repo="test_repo", permission="READ_REPO"
    )

    # Verify result structure
    assert "user_id" in result
    assert "repo" in result
    assert "permission" in result
    assert "has_permission" in result


@pytest.mark.asyncio
async def test_get_observability_metrics_tool(mock_app):
    """Test the get_observability_metrics MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the observability manager
    mock_app.observability.get_performance_metrics = Mock(return_value={})
    mock_app.observability.get_logs = Mock(return_value=[])

    # Call the tool directly
    result = await server.server._tools["get_observability_metrics"].handler()

    # Verify result structure
    assert "status" in result
    assert result["status"] == "success"
    assert "performance_metrics" in result


@pytest.mark.asyncio
async def test_create_user_tool(mock_app):
    """Test the create_user MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the RBAC manager
    mock_app.rbac_manager.create_user = AsyncMock(return_value=Mock())

    # Call the tool directly
    result = await server.server._tools["create_user"].handler(
        user_id="new_user", roles=["developer"], allowed_repos=["/repo1"]
    )

    # Verify result structure
    assert "status" in result
    assert "user_id" in result
    assert result["user_id"] == "new_user"


@pytest.mark.asyncio
async def test_get_monitoring_dashboard_tool(mock_app):
    """Test the get_monitoring_dashboard MCP tool."""
    server = FastMCPServer(mock_app)

    # Call the tool directly
    result = await server.server._tools["get_monitoring_dashboard"].handler()

    # Verify result structure
    assert "status" in result
    assert result["status"] == "success"
    assert "dashboard" in result


@pytest.mark.asyncio
async def test_get_active_alerts_tool(mock_app):
    """Test the get_active_alerts MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the alert manager
    mock_alert = Mock()
    mock_alert.id = "alert_123"
    mock_alert.timestamp = "2023-01-01T00:00:00"
    mock_alert.severity = Mock()
    mock_alert.severity.value = "high"
    mock_alert.type = Mock()
    mock_alert.type.value = "system_health"
    mock_alert.title = "Test Alert"
    mock_alert.description = "Test description"
    mock_alert.details = {}

    mock_app.monitoring_service.alert_manager.get_active_alerts = AsyncMock(
        return_value=[mock_alert]
    )

    # Call the tool directly
    result = await server.server._tools["get_active_alerts"].handler()

    # Verify result structure
    assert "status" in result
    assert "alerts" in result
    assert "count" in result


@pytest.mark.asyncio
async def test_acknowledge_alert_tool(mock_app):
    """Test the acknowledge_alert MCP tool."""
    server = FastMCPServer(mock_app)

    # Call the tool directly
    result = await server.server._tools["acknowledge_alert"].handler(
        alert_id="alert_123", user="test_user"
    )

    # Verify result structure
    assert "status" in result


@pytest.mark.asyncio
async def test_trigger_test_alert_tool(mock_app):
    """Test the trigger_test_alert MCP tool."""
    server = FastMCPServer(mock_app)

    # Call the tool directly
    result = await server.server._tools["trigger_test_alert"].handler(
        severity="medium", title="Test Alert", description="This is a test alert"
    )

    # Verify result structure
    assert "status" in result
    assert "alert_id" in result


@pytest.mark.asyncio
async def test_flush_metrics_tool(mock_app):
    """Test the flush_metrics MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the observability flush method
    mock_app.observability.flush_metrics = AsyncMock()

    # Call the tool directly
    result = await server.server._tools["flush_metrics"].handler()

    # Verify result structure
    assert "status" in result


@pytest.mark.asyncio
async def test_create_backup_tool(mock_app):
    """Test the create_backup MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the backup manager
    mock_backup_info = Mock()
    mock_backup_info.backup_id = "backup_123"
    mock_backup_info.location = "/path/to/backup"
    mock_backup_info.size_bytes = 1024
    mock_backup_info.timestamp = "2023-01-01T00:00:00"

    mock_app.backup_manager.create_backup = AsyncMock(return_value=mock_backup_info)

    # Call the tool directly
    result = await server.server._tools["create_backup"].handler(backup_type="full")

    # Verify result structure
    assert "status" in result
    assert "backup_id" in result
    assert "location" in result
    assert "size_bytes" in result


@pytest.mark.asyncio
async def test_list_backups_tool(mock_app):
    """Test the list_backups MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the backup manager
    mock_backup_info = Mock()
    mock_backup_info.backup_id = "backup_123"
    mock_backup_info.timestamp = "2023-01-01T00:00:00"
    mock_backup_info.size_bytes = 1024
    mock_backup_info.location = "/path/to/backup"
    mock_backup_info.status = "available"

    mock_app.backup_manager.list_backups = AsyncMock(return_value=[mock_backup_info])

    # Call the tool directly
    result = await server.server._tools["list_backups"].handler()

    # Verify result structure
    assert "status" in result
    assert "backups" in result
    assert "total_count" in result


@pytest.mark.asyncio
async def test_restore_backup_tool(mock_app):
    """Test the restore_backup MCP tool."""
    server = FastMCPServer(mock_app)

    # Call the tool directly
    result = await server.server._tools["restore_backup"].handler(backup_id="backup_123")

    # Verify result structure
    assert "status" in result
    assert "backup_id" in result


@pytest.mark.asyncio
async def test_run_disaster_recovery_check_tool(mock_app):
    """Test the run_disaster_recovery_check MCP tool."""
    server = FastMCPServer(mock_app)

    # Mock the disaster recovery manager
    mock_app.disaster_recovery_manager = Mock()
    mock_app.disaster_recovery_manager.run_disaster_recovery_check = AsyncMock(
        return_value={"timestamp": "2023-01-01T00:00:00", "checks": {}, "status": "healthy"}
    )

    # Call the tool directly
    result = await server.server._tools["run_disaster_recovery_check"].handler()

    # Verify result structure
    assert "status" in result
    assert "results" in result


@pytest.mark.asyncio
async def test_heal_workflows_tool(mock_app):
    """Test the heal_workflows MCP tool."""
    server = FastMCPServer(mock_app)

    # Call the tool directly
    result = await server.server._tools["heal_workflows"].handler()

    # Verify result structure
    assert "status" in result
    assert "message" in result
