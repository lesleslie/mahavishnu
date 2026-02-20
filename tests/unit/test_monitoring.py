"""Tests for Monitoring and Alerting Infrastructure - Metrics and alerts."""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from mahavishnu.core.monitoring_infra import (
    MetricsExporter,
    AlertManager,
    AlertRule,
    Alert,
    AlertSeverity,
    HealthChecker,
    HealthStatus,
    HealthCheckResult,
    Metric,
    MetricType,
    DashboardConfig,
    DashboardPanel,
)


@pytest.fixture
def sample_metric() -> Metric:
    """Create a sample metric."""
    return Metric(
        name="http_requests_total",
        value=100.0,
        metric_type=MetricType.COUNTER,
        labels={"method": "GET", "endpoint": "/api/tasks"},
    )


@pytest.fixture
def sample_alert_rule() -> AlertRule:
    """Create a sample alert rule."""
    return AlertRule(
        name="high_error_rate",
        expression="error_rate > 0.05",
        severity=AlertSeverity.WARNING,
        duration_seconds=60,
    )


class TestMetricType:
    """Tests for MetricType enum."""

    def test_metric_types(self) -> None:
        """Test available metric types."""
        assert MetricType.COUNTER.value == "counter"
        assert MetricType.GAUGE.value == "gauge"
        assert MetricType.HISTOGRAM.value == "histogram"
        assert MetricType.SUMMARY.value == "summary"


class TestMetric:
    """Tests for Metric class."""

    def test_create_metric(self) -> None:
        """Create a metric."""
        metric = Metric(
            name="requests_total",
            value=100.0,
            metric_type=MetricType.COUNTER,
        )

        assert metric.name == "requests_total"
        assert metric.value == 100.0
        assert metric.metric_type == MetricType.COUNTER

    def test_metric_with_labels(self) -> None:
        """Create metric with labels."""
        metric = Metric(
            name="http_requests",
            value=50.0,
            metric_type=MetricType.GAUGE,
            labels={"service": "api", "env": "prod"},
        )

        assert metric.labels["service"] == "api"
        assert metric.labels["env"] == "prod"

    def test_metric_to_prometheus(self) -> None:
        """Convert to Prometheus format."""
        metric = Metric(
            name="http_requests_total",
            value=100.0,
            metric_type=MetricType.COUNTER,
            labels={"method": "GET"},
        )

        prom = metric.to_prometheus()

        assert "http_requests_total" in prom
        assert 'method="GET"' in prom
        assert "100.0" in prom

    def test_metric_to_prometheus_no_labels(self) -> None:
        """Convert to Prometheus without labels."""
        metric = Metric(
            name="uptime_seconds",
            value=3600.0,
            metric_type=MetricType.GAUGE,
        )

        prom = metric.to_prometheus()

        assert "uptime_seconds 3600.0" in prom


class TestAlertSeverity:
    """Tests for AlertSeverity enum."""

    def test_severity_levels(self) -> None:
        """Test available severity levels."""
        assert AlertSeverity.INFO.value == "info"
        assert AlertSeverity.WARNING.value == "warning"
        assert AlertSeverity.CRITICAL.value == "critical"
        assert AlertSeverity.EMERGENCY.value == "emergency"


class TestAlertRule:
    """Tests for AlertRule class."""

    def test_create_rule(self) -> None:
        """Create an alert rule."""
        rule = AlertRule(
            name="high_latency",
            expression="latency_p99 > 1.0",
            severity=AlertSeverity.WARNING,
            duration_seconds=60,
        )

        assert rule.name == "high_latency"
        assert rule.expression == "latency_p99 > 1.0"
        assert rule.severity == AlertSeverity.WARNING

    def test_rule_defaults(self) -> None:
        """Test rule defaults."""
        rule = AlertRule(
            name="test",
            expression="value > 0",
        )

        assert rule.severity == AlertSeverity.WARNING
        assert rule.duration_seconds == 60
        assert rule.enabled is True

    def test_rule_to_dict(self) -> None:
        """Convert rule to dictionary."""
        rule = AlertRule(
            name="test",
            expression="value > 0",
            severity=AlertSeverity.CRITICAL,
        )

        d = rule.to_dict()

        assert d["name"] == "test"
        assert d["severity"] == "critical"


class TestAlert:
    """Tests for Alert class."""

    def test_create_alert(self) -> None:
        """Create an alert."""
        alert = Alert(
            rule_name="high_error_rate",
            severity=AlertSeverity.WARNING,
            message="Error rate is 10%",
            labels={"service": "api"},
        )

        assert alert.rule_name == "high_error_rate"
        assert alert.severity == AlertSeverity.WARNING
        assert alert.message == "Error rate is 10%"

    def test_alert_is_firing(self) -> None:
        """Check if alert is firing."""
        alert = Alert(
            rule_name="test",
            severity=AlertSeverity.WARNING,
            message="Test alert",
            firing=True,
        )

        assert alert.is_firing is True

    def test_alert_acknowledge(self) -> None:
        """Acknowledge an alert."""
        alert = Alert(
            rule_name="test",
            severity=AlertSeverity.WARNING,
            message="Test",
        )

        alert.acknowledge("admin")

        assert alert.acknowledged is True
        assert alert.acknowledged_by == "admin"

    def test_alert_to_dict(self) -> None:
        """Convert alert to dictionary."""
        alert = Alert(
            rule_name="test",
            severity=AlertSeverity.CRITICAL,
            message="Critical issue",
        )

        d = alert.to_dict()

        assert d["rule_name"] == "test"
        assert d["severity"] == "critical"
        assert d["message"] == "Critical issue"


class TestHealthStatus:
    """Tests for HealthStatus enum."""

    def test_health_statuses(self) -> None:
        """Test available health statuses."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"


class TestHealthCheckResult:
    """Tests for HealthCheckResult class."""

    def test_healthy_result(self) -> None:
        """Create a healthy result."""
        result = HealthCheckResult(
            component="database",
            status=HealthStatus.HEALTHY,
            message="Connection OK",
        )

        assert result.component == "database"
        assert result.status == HealthStatus.HEALTHY
        assert result.healthy is True

    def test_unhealthy_result(self) -> None:
        """Create an unhealthy result."""
        result = HealthCheckResult(
            component="cache",
            status=HealthStatus.UNHEALTHY,
            message="Connection refused",
        )

        assert result.status == HealthStatus.UNHEALTHY
        assert result.healthy is False

    def test_degraded_result(self) -> None:
        """Create a degraded result."""
        result = HealthCheckResult(
            component="api",
            status=HealthStatus.DEGRADED,
            message="High latency",
        )

        assert result.status == HealthStatus.DEGRADED
        assert result.healthy is False

    def test_result_to_dict(self) -> None:
        """Convert result to dictionary."""
        result = HealthCheckResult(
            component="db",
            status=HealthStatus.HEALTHY,
            message="OK",
        )

        d = result.to_dict()

        assert d["component"] == "db"
        assert d["status"] == "healthy"
        assert d["healthy"] is True


class TestMetricsExporter:
    """Tests for MetricsExporter class."""

    def test_create_exporter(self) -> None:
        """Create a metrics exporter."""
        exporter = MetricsExporter()

        assert exporter is not None
        assert len(exporter.metrics) == 0

    def test_register_metric(
        self,
        sample_metric: Metric,
    ) -> None:
        """Register a metric."""
        exporter = MetricsExporter()

        exporter.register(sample_metric)

        assert len(exporter.metrics) == 1

    def test_record_counter(self) -> None:
        """Record a counter metric."""
        exporter = MetricsExporter()

        exporter.record_counter("requests_total", 1.0, {"method": "GET"})
        exporter.record_counter("requests_total", 1.0, {"method": "GET"})

        assert exporter.get_value("requests_total") == 2.0

    def test_set_gauge(self) -> None:
        """Set a gauge metric."""
        exporter = MetricsExporter()

        exporter.set_gauge("temperature", 25.5)
        exporter.set_gauge("temperature", 26.0)

        assert exporter.get_value("temperature") == 26.0

    def test_observe_histogram(self) -> None:
        """Observe a histogram metric."""
        exporter = MetricsExporter()

        exporter.observe_histogram("latency_seconds", 0.1)
        exporter.observe_histogram("latency_seconds", 0.2)
        exporter.observe_histogram("latency_seconds", 0.3)

        # Just check it doesn't raise
        assert True

    def test_export_prometheus(self) -> None:
        """Export metrics in Prometheus format."""
        exporter = MetricsExporter()

        exporter.record_counter("http_requests", 100.0)
        exporter.set_gauge("active_connections", 5.0)

        output = exporter.export_prometheus()

        assert "http_requests" in output
        assert "active_connections" in output

    def test_get_metric_names(self) -> None:
        """Get all metric names."""
        exporter = MetricsExporter()

        exporter.record_counter("counter1", 1.0)
        exporter.set_gauge("gauge1", 1.0)

        names = exporter.get_metric_names()

        assert "counter1" in names
        assert "gauge1" in names


class TestAlertManager:
    """Tests for AlertManager class."""

    def test_create_manager(self) -> None:
        """Create an alert manager."""
        manager = AlertManager()

        assert manager is not None
        assert len(manager.rules) == 0
        assert len(manager.active_alerts) == 0

    def test_add_rule(
        self,
        sample_alert_rule: AlertRule,
    ) -> None:
        """Add an alert rule."""
        manager = AlertManager()

        manager.add_rule(sample_alert_rule)

        assert len(manager.rules) == 1
        assert "high_error_rate" in manager.rules

    def test_remove_rule(self) -> None:
        """Remove an alert rule."""
        manager = AlertManager()
        rule = AlertRule(name="test", expression="value > 0")

        manager.add_rule(rule)
        manager.remove_rule("test")

        assert len(manager.rules) == 0

    def test_fire_alert(self) -> None:
        """Fire an alert."""
        manager = AlertManager()
        rule = AlertRule(name="test", expression="value > 0")
        manager.add_rule(rule)

        manager.fire_alert("test", "Value exceeded threshold")

        assert len(manager.active_alerts) == 1

    def test_resolve_alert(self) -> None:
        """Resolve an alert."""
        manager = AlertManager()
        rule = AlertRule(name="test", expression="value > 0")
        manager.add_rule(rule)

        manager.fire_alert("test", "Alert message")
        manager.resolve_alert("test")

        # Alert should still exist but not be firing
        alert = manager.get_alert("test")
        assert alert is not None
        assert alert.firing is False

    def test_get_active_alerts(self) -> None:
        """Get all active (firing) alerts."""
        manager = AlertManager()

        # Add rules first
        manager.add_rule(AlertRule(name="alert1", expression="value > 0"))
        manager.add_rule(AlertRule(name="alert2", expression="value > 0"))

        manager.fire_alert("alert1", "First alert")
        manager.fire_alert("alert2", "Second alert")
        manager.resolve_alert("alert1")

        active = manager.get_active_alerts()

        assert len(active) == 1
        assert active[0].rule_name == "alert2"

    def test_enable_disable_rule(self) -> None:
        """Enable and disable rules."""
        manager = AlertManager()
        rule = AlertRule(name="test", expression="value > 0")
        manager.add_rule(rule)

        manager.disable_rule("test")
        assert manager.rules["test"].enabled is False

        manager.enable_rule("test")
        assert manager.rules["test"].enabled is True

    def test_evaluate_rules(self) -> None:
        """Evaluate all rules."""
        manager = AlertManager()
        rule = AlertRule(
            name="high_cpu",
            expression="cpu_usage > 80",
            severity=AlertSeverity.WARNING,
        )
        manager.add_rule(rule)

        # Mock evaluation - should return list of triggered rules
        triggered = manager.evaluate_rules({"cpu_usage": 90})

        assert len(triggered) == 1
        assert triggered[0] == "high_cpu"


class TestHealthChecker:
    """Tests for HealthChecker class."""

    def test_create_checker(self) -> None:
        """Create a health checker."""
        checker = HealthChecker()

        assert checker is not None

    def test_register_check(self) -> None:
        """Register a health check."""
        checker = HealthChecker()

        checker.register_check("database", lambda: HealthCheckResult(
            component="database",
            status=HealthStatus.HEALTHY,
            message="OK",
        ))

        assert "database" in checker.checks

    @pytest.mark.asyncio
    async def test_run_check(self) -> None:
        """Run a health check."""
        checker = HealthChecker()

        async def db_check() -> HealthCheckResult:
            return HealthCheckResult(
                component="database",
                status=HealthStatus.HEALTHY,
                message="OK",
            )

        checker.register_check("database", db_check)

        result = await checker.run_check("database")

        assert result.status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_run_all_checks(self) -> None:
        """Run all health checks."""
        checker = HealthChecker()

        checker.register_check("db", lambda: HealthCheckResult(
            component="db",
            status=HealthStatus.HEALTHY,
            message="OK",
        ))
        checker.register_check("cache", lambda: HealthCheckResult(
            component="cache",
            status=HealthStatus.HEALTHY,
            message="OK",
        ))

        results = await checker.run_all_checks()

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_overall_status_healthy(self) -> None:
        """Get overall healthy status."""
        checker = HealthChecker()

        checker.register_check("db", lambda: HealthCheckResult(
            component="db",
            status=HealthStatus.HEALTHY,
            message="OK",
        ))

        status = await checker.get_overall_status()

        assert status == HealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_overall_status_unhealthy(self) -> None:
        """Get overall unhealthy status."""
        checker = HealthChecker()

        checker.register_check("db", lambda: HealthCheckResult(
            component="db",
            status=HealthStatus.HEALTHY,
            message="OK",
        ))
        checker.register_check("cache", lambda: HealthCheckResult(
            component="cache",
            status=HealthStatus.UNHEALTHY,
            message="Failed",
        ))

        status = await checker.get_overall_status()

        assert status == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_overall_status_degraded(self) -> None:
        """Get overall degraded status."""
        checker = HealthChecker()

        checker.register_check("db", lambda: HealthCheckResult(
            component="db",
            status=HealthStatus.HEALTHY,
            message="OK",
        ))
        checker.register_check("cache", lambda: HealthCheckResult(
            component="cache",
            status=HealthStatus.DEGRADED,
            message="Slow",
        ))

        status = await checker.get_overall_status()

        assert status == HealthStatus.DEGRADED


class TestDashboardPanel:
    """Tests for DashboardPanel class."""

    def test_create_panel(self) -> None:
        """Create a dashboard panel."""
        panel = DashboardPanel(
            title="Request Rate",
            query="rate(http_requests_total[5m])",
            panel_type="graph",
        )

        assert panel.title == "Request Rate"
        assert panel.panel_type == "graph"

    def test_panel_defaults(self) -> None:
        """Test panel defaults."""
        panel = DashboardPanel(
            title="Test",
            query="metric",
        )

        assert panel.panel_type == "graph"
        assert panel.width == 12
        assert panel.height == 6

    def test_panel_to_dict(self) -> None:
        """Convert panel to dictionary."""
        panel = DashboardPanel(
            title="CPU Usage",
            query="cpu_usage",
            panel_type="gauge",
        )

        d = panel.to_dict()

        assert d["title"] == "CPU Usage"
        assert d["type"] == "gauge"


class TestDashboardConfig:
    """Tests for DashboardConfig class."""

    def test_create_dashboard(self) -> None:
        """Create a dashboard configuration."""
        dashboard = DashboardConfig(
            title="System Overview",
            panels=[
                DashboardPanel(title="CPU", query="cpu"),
                DashboardPanel(title="Memory", query="memory"),
            ],
        )

        assert dashboard.title == "System Overview"
        assert len(dashboard.panels) == 2

    def test_add_panel(self) -> None:
        """Add a panel to dashboard."""
        dashboard = DashboardConfig(title="Test")

        dashboard.add_panel(DashboardPanel(title="New Panel", query="metric"))

        assert len(dashboard.panels) == 1

    def test_dashboard_to_dict(self) -> None:
        """Convert dashboard to dictionary."""
        dashboard = DashboardConfig(
            title="Test",
            panels=[DashboardPanel(title="P1", query="m1")],
        )

        d = dashboard.to_dict()

        assert d["title"] == "Test"
        assert len(d["panels"]) == 1

    def test_to_grafana_json(self) -> None:
        """Export to Grafana JSON format."""
        dashboard = DashboardConfig(
            title="API Dashboard",
            panels=[
                DashboardPanel(title="Requests", query="requests_total"),
            ],
        )

        json_str = dashboard.to_grafana_json()

        assert "API Dashboard" in json_str
        assert "Requests" in json_str
