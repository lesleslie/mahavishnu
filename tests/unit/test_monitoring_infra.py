"""Coverage tests for monitoring infrastructure module."""

from __future__ import annotations

import pytest

from mahavishnu.core.monitoring_infra import (
    AlertManager,
    HealthCheckResult,
    HealthChecker,
    HealthStatus,
    Metric,
    MetricType,
    MetricsExporter,
)


def test_metric_to_prometheus_with_and_without_labels() -> None:
    plain = Metric(name="requests_total", value=3.0, metric_type=MetricType.COUNTER)
    assert plain.to_prometheus() == "requests_total 3.0"

    with_labels = Metric(
        name="latency_ms",
        value=12.5,
        metric_type=MetricType.GAUGE,
        labels={"service": "api", "env": "test"},
    )
    rendered = with_labels.to_prometheus()
    assert rendered.startswith("latency_ms{")
    assert 'service="api"' in rendered
    assert 'env="test"' in rendered


def test_health_check_result_to_dict_and_healthy_property() -> None:
    ok = HealthCheckResult(component="db", status=HealthStatus.HEALTHY, message="ok")
    bad = HealthCheckResult(component="db", status=HealthStatus.UNHEALTHY, message="bad")
    assert ok.healthy is True
    assert bad.healthy is False
    payload = ok.to_dict()
    assert payload["component"] == "db"
    assert payload["status"] == "healthy"
    assert payload["healthy"] is True


def test_metrics_exporter_end_to_end() -> None:
    exporter = MetricsExporter()
    exporter.record_counter("runs_total")
    exporter.record_counter("runs_total", 2)
    exporter.set_gauge("queue_depth", 4.0)
    exporter.observe_histogram("latency_ms", 10.0)
    exporter.observe_histogram("latency_ms", 20.0)
    exporter.register(Metric(name="custom_metric", value=1.0, metric_type=MetricType.GAUGE))

    assert exporter.get_value("runs_total") == 3.0
    assert exporter.get_value("queue_depth") == 4.0
    assert exporter.get_value("missing") == 0.0

    names = set(exporter.get_metric_names())
    assert {"runs_total", "queue_depth", "latency_ms"} <= names

    rendered = exporter.export_prometheus()
    assert "runs_total 3.0" in rendered
    assert "queue_depth 4.0" in rendered
    assert "latency_ms_count 2" in rendered
    assert "latency_ms_sum 30.0" in rendered


@pytest.mark.asyncio
async def test_health_checker_not_found_sync_async_and_exception() -> None:
    checker = HealthChecker()

    missing = await checker.run_check("nope")
    assert missing.status == HealthStatus.UNHEALTHY
    assert missing.message == "Check not found"

    checker.register_check(
        "sync_ok",
        lambda: HealthCheckResult("sync_ok", HealthStatus.HEALTHY, "ok"),
    )

    async def async_check():
        return HealthCheckResult("async_ok", HealthStatus.DEGRADED, "slow")

    checker.register_check("async_ok", async_check)

    def raises():
        raise RuntimeError("boom")

    checker.register_check("raises", raises)

    assert (await checker.run_check("sync_ok")).status == HealthStatus.HEALTHY
    assert (await checker.run_check("async_ok")).status == HealthStatus.DEGRADED
    failed = await checker.run_check("raises")
    assert failed.status == HealthStatus.UNHEALTHY
    assert failed.message == "boom"


@pytest.mark.asyncio
async def test_health_checker_overall_status_ordering() -> None:
    checker = HealthChecker()
    assert await checker.get_overall_status() == HealthStatus.HEALTHY

    checker.register_check(
        "only_healthy",
        lambda: HealthCheckResult("only_healthy", HealthStatus.HEALTHY, "ok"),
    )
    assert await checker.get_overall_status() == HealthStatus.HEALTHY

    checker.checks.clear()
    checker.register_check(
        "a",
        lambda: HealthCheckResult("a", HealthStatus.HEALTHY, "ok"),
    )
    checker.register_check(
        "b",
        lambda: HealthCheckResult("b", HealthStatus.DEGRADED, "warn"),
    )
    assert await checker.get_overall_status() == HealthStatus.DEGRADED

    checker.register_check(
        "c",
        lambda: HealthCheckResult("c", HealthStatus.UNHEALTHY, "down"),
    )
    assert await checker.get_overall_status() == HealthStatus.UNHEALTHY


def test_alert_manager_get_active_alerts_filters() -> None:
    manager = AlertManager()
    manager.alerts = [
        type("A", (), {"acknowledged": False, "firing": True})(),
        type("A", (), {"acknowledged": True, "firing": True})(),
        type("A", (), {"acknowledged": False, "firing": False})(),
    ]
    active = manager.get_active_alerts()
    assert len(active) == 1
