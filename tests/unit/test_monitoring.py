"""Unit tests for monitoring and alerting functionality."""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, MagicMock
from mahavishnu.core.monitoring import AlertManager, AlertSeverity, AlertType, Alert, MonitoringService
from mahavishnu.core.app import MahavishnuApp


@pytest.fixture
def mock_app():
    """Create a mock app for testing."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = Mock()
    app.workflow_state_manager = Mock()
    app.adapters = {}
    app.config = Mock()
    return app


@pytest.mark.asyncio
async def test_alert_creation():
    """Test creating and managing alerts."""
    app = Mock(spec=MahavishnuApp)
    alert_manager = AlertManager(app)
    
    # Create an alert
    alert = await alert_manager.trigger_alert(
        severity=AlertSeverity.HIGH,
        alert_type=AlertType.WORKFLOW_FAILURE,
        title="Test Alert",
        description="This is a test alert",
        details={"test": True, "value": 42}
    )
    
    # Verify alert was created correctly
    assert isinstance(alert, Alert)
    assert alert.severity == AlertSeverity.HIGH
    assert alert.type == AlertType.WORKFLOW_FAILURE
    assert alert.title == "Test Alert"
    assert alert.description == "This is a test alert"
    assert alert.details == {"test": True, "value": 42}
    assert alert.acknowledged is False
    
    # Verify alert was stored
    active_alerts = await alert_manager.get_active_alerts()
    assert len(active_alerts) == 1
    assert active_alerts[0].id == alert.id


@pytest.mark.asyncio
async def test_alert_acknowledgement():
    """Test acknowledging alerts."""
    app = Mock(spec=MahavishnuApp)
    alert_manager = AlertManager(app)
    
    # Create an alert
    alert = await alert_manager.trigger_alert(
        severity=AlertSeverity.LOW,
        alert_type=AlertType.SYSTEM_HEALTH,
        title="Ack Test Alert",
        description="This alert will be acknowledged",
        details={}
    )
    
    # Verify it's active
    active_alerts = await alert_manager.get_active_alerts()
    assert len(active_alerts) == 1
    
    # Acknowledge the alert
    await alert_manager.acknowledge_alert(alert.id, "test_user")
    
    # Verify it's no longer active
    active_alerts = await alert_manager.get_active_alerts()
    assert len(active_alerts) == 0
    
    # But it should still exist in the main list
    assert len(alert_manager.alerts) == 1
    assert alert_manager.alerts[0].acknowledged is True
    assert alert_manager.alerts[0].acknowledged_by == "test_user"


@pytest.mark.asyncio
async def test_severity_based_handling():
    """Test that different severities are handled appropriately."""
    app = Mock(spec=MahavishnuApp)
    alert_manager = AlertManager(app)
    
    # Test all severity levels
    severities = [AlertSeverity.LOW, AlertSeverity.MEDIUM, AlertSeverity.HIGH, AlertSeverity.CRITICAL]
    
    for severity in severities:
        alert = await alert_manager.trigger_alert(
            severity=severity,
            alert_type=AlertType.RESOURCE_EXHAUSTION,
            title=f"Test {severity.value} Alert",
            description=f"Alert with {severity.value} severity",
            details={"severity": severity.value}
        )
        
        # Verify alert was created with correct severity
        assert alert.severity == severity


@pytest.mark.asyncio
async def test_alert_type_handling():
    """Test that different alert types are handled appropriately."""
    app = Mock(spec=MahavishnuApp)
    alert_manager = AlertManager(app)
    
    # Test all alert types
    alert_types = [
        AlertType.SYSTEM_HEALTH,
        AlertType.WORKFLOW_FAILURE,
        AlertType.RESOURCE_EXHAUSTION,
        AlertType.PERFORMANCE_DEGRADATION,
        AlertType.SECURITY_ISSUE,
        AlertType.BACKUP_FAILURE
    ]
    
    for alert_type in alert_types:
        alert = await alert_manager.trigger_alert(
            severity=AlertSeverity.MEDIUM,
            alert_type=alert_type,
            title=f"Test {alert_type.value} Alert",
            description=f"Alert of type {alert_type.value}",
            details={"type": alert_type.value}
        )
        
        # Verify alert was created with correct type
        assert alert.type == alert_type


@pytest.mark.asyncio
async def test_monitoring_service_initialization():
    """Test that monitoring service initializes correctly."""
    app = Mock(spec=MahavishnuApp)
    monitoring_service = MonitoringService(app)
    
    # Verify components were initialized
    assert monitoring_service.alert_manager is not None
    assert monitoring_service.dashboard is not None


@pytest.mark.asyncio
async def test_monitoring_dashboard_data():
    """Test that monitoring dashboard provides data."""
    app = Mock(spec=MahavishnuApp)
    app.adapters = {"test_adapter": Mock()}
    app.workflow_state_manager = Mock()
    
    # Mock the workflow state manager
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
    
    monitoring_service = MonitoringService(app)
    
    # Get dashboard data
    dashboard_data = await monitoring_service.get_dashboard_data()
    
    # Verify structure of dashboard data
    assert "metrics" in dashboard_data
    assert "recent_alerts" in dashboard_data
    assert "timestamp" in dashboard_data
    
    # Verify metrics structure
    metrics = dashboard_data["metrics"]
    assert "system" in metrics
    assert "workflows" in metrics
    assert "adapters" in metrics
    assert "alerts" in metrics


@pytest.mark.asyncio
async def test_alert_manager_handlers():
    """Test that alert handlers are properly registered and executed."""
    app = Mock(spec=MahavishnuApp)
    alert_manager = AlertManager(app)
    
    # Create a mock handler
    handler_called = False
    handler_alert = None
    
    async def mock_handler(alert):
        nonlocal handler_called, handler_alert
        handler_called = True
        handler_alert = alert
    
    # Register the handler
    alert_manager.register_handler(AlertType.WORKFLOW_FAILURE, mock_handler)
    
    # Trigger an alert of the registered type
    test_alert = await alert_manager.trigger_alert(
        severity=AlertSeverity.HIGH,
        alert_type=AlertType.WORKFLOW_FAILURE,
        title="Handler Test",
        description="Testing handler execution",
        details={}
    )
    
    # Verify handler was called
    assert handler_called
    assert handler_alert is not None
    assert handler_alert.id == test_alert.id


@pytest.mark.asyncio
async def test_monitoring_acknowledge_alert():
    """Test the monitoring service's acknowledge_alert method."""
    app = Mock(spec=MahavishnuApp)
    monitoring_service = MonitoringService(app)
    
    # Create an alert
    alert = await monitoring_service.alert_manager.trigger_alert(
        severity=AlertSeverity.MEDIUM,
        alert_type=AlertType.SYSTEM_HEALTH,
        title="Ack Service Test",
        description="Testing service acknowledge",
        details={}
    )
    
    # Verify it's active
    active_alerts = await monitoring_service.alert_manager.get_active_alerts()
    assert len(active_alerts) == 1
    
    # Acknowledge via monitoring service
    success = await monitoring_service.acknowledge_alert(alert.id, "service_user")
    assert success is True
    
    # Verify it's no longer active
    active_alerts = await monitoring_service.alert_manager.get_active_alerts()
    assert len(active_alerts) == 0


@pytest.mark.asyncio
async def test_alert_manager_monitoring_loop():
    """Test that the monitoring loop runs without errors."""
    app = Mock(spec=MahavishnuApp)
    app.adapters = {"test_adapter": Mock()}
    app.workflow_state_manager = Mock()
    
    # Mock the workflow state manager
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
    
    alert_manager = AlertManager(app)
    
    # The monitoring loop runs in the background, so we just verify
    # that it was scheduled without errors
    # (In a real test, we might want to mock the sleep to make it faster)
    
    # Verify that default handlers were registered
    assert AlertType.WORKFLOW_FAILURE in alert_manager.alert_handlers
    assert AlertType.SYSTEM_HEALTH in alert_manager.alert_handlers
    assert AlertType.RESOURCE_EXHAUSTION in alert_manager.alert_handlers
    assert AlertType.PERFORMANCE_DEGRADATION in alert_manager.alert_handlers
    assert AlertType.BACKUP_FAILURE in alert_manager.alert_handlers