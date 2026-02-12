"""Tests for routing metrics and alerting system."""

import pytest
import asyncio
from datetime import datetime, UTC

from mahavishnu.core.routing_metrics import (
    RoutingMetrics,
    get_routing_metrics,
    reset_routing_metrics,
)
from mahavishnu.core.routing_alerts import (
    Alert,
    AlertSeverity,
    AlertType,
    LoggingAlertHandler,
    RoutingAlertManager,
    get_alert_manager,
)
from mahavishnu.core.metrics_schema import AdapterType, TaskType


@pytest.fixture
def reset_metrics():
    """Reset metrics before each test."""
    reset_routing_metrics()
    yield
    reset_routing_metrics()


class TestRoutingMetrics:
    """Test routing metrics collection."""

    def test_get_routing_metrics_singleton(self):
        """Should return singleton instance."""
        metrics1 = get_routing_metrics("test_server")
        metrics2 = get_routing_metrics("test_server")
        assert metrics1 is metrics2

    def test_get_routing_metrics_different_servers(self):
        """Should create separate instances for different servers."""
        metrics1 = get_routing_metrics("server1")
        metrics2 = get_routing_metrics("server2")
        assert metrics1 is not metrics2

    def test_metrics_summary(self, reset_metrics):
        """Should return metrics summary."""
        metrics = get_routing_metrics()
        summary = metrics.get_metrics_summary()
        assert summary["server"] == "mahavishnu"
        assert "enabled" in summary
        assert "routing_tracking" in summary

    def test_record_routing_decision(self, reset_metrics):
        """Should record routing decision."""
        metrics = get_routing_metrics()
        metrics.record_routing_decision(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.WORKFLOW,
            preference_order=1,
        )
        summary = metrics.get_metrics_summary()
        assert summary["routing_tracking"]

    def test_record_adapter_execution_success(self, reset_metrics):
        """Should record successful adapter execution."""
        metrics = get_routing_metrics()
        metrics.record_adapter_execution(
            adapter=AdapterType.LLAMAINDEX,
            success=True,
            latency_ms=123,
        )
        # Just verify no exception raised
        summary = metrics.get_metrics_summary()
        assert summary["adapter_execution_tracking"]

    def test_record_adapter_execution_failure(self, reset_metrics):
        """Should record failed adapter execution."""
        metrics = get_routing_metrics()
        metrics.record_adapter_execution(
            adapter=AdapterType.AGNO,
            success=False,
            latency_ms=5000,
        )
        summary = metrics.get_metrics_summary()
        assert summary["adapter_execution_tracking"]

    def test_record_fallback(self, reset_metrics):
        """Should record adapter fallback."""
        metrics = get_routing_metrics()
        metrics.record_fallback(
            original_adapter=AdapterType.PREFECT,
            fallback_adapter=AdapterType.AGNO,
        )
        summary = metrics.get_metrics_summary()
        assert summary["fallback_tracking"]

    def test_record_cost(self, reset_metrics):
        """Should record routing cost."""
        metrics = get_routing_metrics()
        metrics.record_cost(
            adapter=AdapterType.PREFECT,
            task_type=TaskType.AI_TASK,
            cost_usd=0.123,
        )
        summary = metrics.get_metrics_summary()
        assert summary["cost_tracking"]

    def test_set_current_cost(self, reset_metrics):
        """Should set current cost gauge."""
        metrics = get_routing_metrics()
        metrics.set_current_cost("daily", 15.50)
        summary = metrics.get_metrics_summary()
        assert summary["cost_tracking"]

    def test_trigger_budget_alert(self, reset_metrics):
        """Should trigger budget alert."""
        metrics = get_routing_metrics()
        metrics.trigger_budget_alert("daily", "warning")
        summary = metrics.get_metrics_summary()
        assert summary["alert_tracking"]

    def test_record_ab_test_event(self, reset_metrics):
        """Should record A/B test event."""
        metrics = get_routing_metrics()
        metrics.record_ab_test_event("exp_123", "start")
        summary = metrics.get_metrics_summary()
        assert summary["ab_test_tracking"]

    def test_set_active_experiments(self, reset_metrics):
        """Should set active experiments count."""
        metrics = get_routing_metrics()
        metrics.set_active_experiments(3)
        summary = metrics.get_metrics_summary()
        assert summary["ab_test_tracking"]


class TestAlertDataclass:
    """Test Alert dataclass."""

    def test_alert_to_dict(self):
        """Should convert alert to dictionary."""
        alert = Alert(
            alert_type=AlertType.ADAPTER_DEGRADATION,
            severity=AlertSeverity.WARNING,
            message="Test alert",
            adapter=AdapterType.PREFECT,
            current_value=0.85,
            threshold_value=0.95,
            metadata={"test": True},
        )
        alert_dict = alert.to_dict()
        assert alert_dict["alert_type"] == "adapter_degradation"
        assert alert_dict["severity"] == "warning"
        assert alert_dict["adapter"] == "prefect"
        assert alert_dict["current_value"] == 0.85
        assert alert_dict["threshold_value"] == 0.95
        assert alert_dict["metadata"]["test"] is True

    def test_alert_without_adapter(self):
        """Should handle alert without adapter."""
        alert = Alert(
            alert_type=AlertType.COST_SPIKE,
            severity=AlertSeverity.CRITICAL,
            message="Cost spike detected",
            current_value=100.0,
            threshold_value=50.0,
        )
        alert_dict = alert.to_dict()
        assert alert_dict["adapter"] is None


class TestLoggingAlertHandler:
    """Test logging alert handler."""

    @pytest.mark.asyncio
    async def test_send_alert_logs(self):
        """Should log alert."""
        handler = LoggingAlertHandler()
        alert = Alert(
            alert_type=AlertType.ADAPTER_DEGRADATION,
            severity=AlertSeverity.INFO,
            message="Test info alert",
        )
        # Should not raise exception
        await handler.send_alert(alert)


class TestRoutingAlertManager:
    """Test routing alert manager."""

    def test_get_alert_manager_singleton(self):
        """Should return singleton instance."""
        manager1 = get_alert_manager()
        manager2 = get_alert_manager()
        assert manager1 is manager2

    def test_get_status(self):
        """Should return status."""
        manager = get_alert_manager()
        status = manager.get_status()
        assert "success_rate_threshold" in status
        assert "fallback_rate_threshold" in status
        assert "latency_p95_threshold_ms" in status
        assert "running" in status

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """Should start and stop evaluation loop."""
        manager = get_alert_manager()
        await manager.start()
        status = manager.get_status()
        assert status["running"] is True
        await manager.stop()
        status = manager.get_status()
        assert status["running"] is False

    @pytest.mark.asyncio
    async def test_evaluate_adapter_health_empty_tracker(self):
        """Should handle empty tracker gracefully."""
        manager = RoutingAlertManager()
        alerts = await manager.evaluate_adapter_health()
        # Should return empty list if no executions tracked
        assert isinstance(alerts, list)

    @pytest.mark.asyncio
    async def test_evaluate_cost_anomalies_first_call(self):
        """Should establish baseline on first call."""
        manager = RoutingAlertManager()
        alerts = await manager.evaluate_cost_anomalies(current_cost_usd=10.0)
        # First call should establish baseline, no alerts
        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_evaluate_cost_anomalies_spike(self):
        """Should detect cost spike."""
        manager = RoutingAlertManager(cost_spike_multiplier=2.0)
        # Establish baseline
        await manager.evaluate_cost_anomalies(current_cost_usd=10.0)
        # Trigger spike (20.0 is 2x 10.0)
        alerts = await manager.evaluate_cost_anomalies(current_cost_usd=20.0)
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.COST_SPIKE
        assert alerts[0].severity == AlertSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_evaluate_cost_anomalies_increase(self):
        """Should detect cost increase (warning)."""
        manager = RoutingAlertManager(cost_spike_multiplier=2.0)
        # Establish baseline
        await manager.evaluate_cost_anomalies(current_cost_usd=10.0)
        # Trigger increase (16.0 is 1.6x 10.0, below 2.0 threshold)
        alerts = await manager.evaluate_cost_anomalies(current_cost_usd=16.0)
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.COST_SPIKE
        assert alerts[0].severity == AlertSeverity.WARNING

    @pytest.mark.asyncio
    async def test_evaluate_fallback_patterns_excessive(self):
        """Should detect excessive fallbacks."""
        manager = RoutingAlertManager(fallback_rate_threshold=0.1)
        alerts = await manager.evaluate_fallback_patterns(
            fallback_count=15,
            total_executions=100,
        )
        # 15% is above 10% threshold
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.EXCESSIVE_FALLBACKS
        assert alerts[0].severity == AlertSeverity.WARNING

    @pytest.mark.asyncio
    async def test_evaluate_fallback_patterns_critical(self):
        """Should detect critical excessive fallbacks."""
        manager = RoutingAlertManager(fallback_rate_threshold=0.1)
        alerts = await manager.evaluate_fallback_patterns(
            fallback_count=40,
            total_executions=100,
        )
        # 40% is well above threshold
        assert len(alerts) == 1
        assert alerts[0].alert_type == AlertType.EXCESSIVE_FALLBACKS
        assert alerts[0].severity == AlertSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_evaluate_fallback_patterns_acceptable(self):
        """Should not alert for acceptable fallback rate."""
        manager = RoutingAlertManager(fallback_rate_threshold=0.1)
        alerts = await manager.evaluate_fallback_patterns(
            fallback_count=5,
            total_executions=100,
        )
        # 5% is below 10% threshold
        assert len(alerts) == 0

    @pytest.mark.asyncio
    async def test_evaluate_fallback_patterns_zero_executions(self):
        """Should handle zero total executions."""
        manager = RoutingAlertManager()
        alerts = await manager.evaluate_fallback_patterns(
            fallback_count=0,
            total_executions=0,
        )
        assert len(alerts) == 0
