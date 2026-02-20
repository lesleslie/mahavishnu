"""Monitoring and Alerting Infrastructure - Metrics, alerts, and health checks.

Provides monitoring infrastructure:

- Prometheus metrics exporter
- Alert manager with rules
- Health check system
- Dashboard configuration

Usage:
    from mahavishnu.core.monitoring_infra import MetricsExporter, AlertManager

    exporter = MetricsExporter()
    exporter.record_counter("requests_total", 1.0)

    manager = AlertManager()
    manager.add_rule(AlertRule(name="high_error", expression="error_rate > 0.05"))
"""

from __future__ import annotations

import json
import logging
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Prometheus metric types."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class HealthStatus(str, Enum):
    """Health check status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class Metric:
    """A Prometheus metric."""

    name: str
    value: float
    metric_type: MetricType
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_prometheus(self) -> str:
        """Convert to Prometheus format."""
        if self.labels:
            labels_str = ",".join(f'{k}="{v}"' for k, v in self.labels.items())
            return f"{self.name}{{{labels_str}}} {self.value}"
        return f"{self.name} {self.value}"


@dataclass
class AlertRule:
    """An alert rule."""

    name: str
    expression: str
    severity: AlertSeverity = AlertSeverity.WARNING
    duration_seconds: int = 60
    enabled: bool = True
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "expression": self.expression,
            "severity": self.severity.value,
            "duration_seconds": self.duration_seconds,
            "enabled": self.enabled,
            "labels": self.labels,
            "annotations": self.annotations,
        }


@dataclass
class Alert:
    """An active alert."""

    rule_name: str
    severity: AlertSeverity
    message: str
    labels: dict[str, str] = field(default_factory=dict)
    firing: bool = True
    acknowledged: bool = False
    acknowledged_by: str | None = None
    fired_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_firing(self) -> bool:
        return self.firing

    def acknowledge(self, by: str) -> None:
        self.acknowledged = True
        self.acknowledged_by = by

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "severity": self.severity.value,
            "message": self.message,
            "labels": self.labels,
            "firing": self.firing,
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "fired_at": self.fired_at.isoformat(),
        }


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    component: str
    status: HealthStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "status": self.status.value,
            "healthy": self.healthy,
            "message": self.message,
            "details": self.details,
            "checked_at": self.checked_at.isoformat(),
        }


@dataclass
class DashboardPanel:
    """A dashboard panel."""

    title: str
    query: str
    panel_type: str = "graph"
    width: int = 12
    height: int = 6
    datasource: str = "Prometheus"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "query": self.query,
            "type": self.panel_type,
            "width": self.width,
            "height": self.height,
            "datasource": self.datasource,
        }


@dataclass
class DashboardConfig:
    """Dashboard configuration."""

    title: str
    panels: list[DashboardPanel] = field(default_factory=list)
    refresh_interval: int = 30
    tags: list[str] = field(default_factory=list)

    def add_panel(self, panel: DashboardPanel) -> None:
        self.panels.append(panel)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "panels": [p.to_dict() for p in self.panels],
            "refresh_interval": self.refresh_interval,
            "tags": self.tags,
        }

    def to_grafana_json(self) -> str:
        grafana = {
            "dashboard": {
                "title": self.title,
                "uid": self.title.lower().replace(" ", "-"),
                "panels": [
                    {
                        "id": i + 1,
                        "title": p.title,
                        "type": p.panel_type,
                        "gridPos": {
                            "x": 0,
                            "y": i * p.height,
                            "w": p.width,
                            "h": p.height,
                        },
                        "targets": [{"expr": p.query, "datasource": p.datasource}],
                    }
                    for i, p in enumerate(self.panels)
                ],
                "refresh": f"{self.refresh_interval}s",
                "tags": self.tags,
            },
            "overwrite": True,
        }
        return json.dumps(grafana, indent=2)


class MetricsExporter:
    """Exports metrics in Prometheus format."""

    def __init__(self) -> None:
        self.metrics: dict[str, Metric] = {}
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)

    def register(self, metric: Metric) -> None:
        self.metrics[metric.name] = metric

    def record_counter(
        self,
        name: str,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        self._counters[name] += value

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        self._gauges[name] = value

    def observe_histogram(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        self._histograms[name].append(value)

    def get_value(self, name: str) -> float:
        if name in self._counters:
            return self._counters[name]
        if name in self._gauges:
            return self._gauges[name]
        return 0.0

    def get_metric_names(self) -> list[str]:
        names = set(self._counters.keys())
        names.update(self._gauges.keys())
        names.update(self._histograms.keys())
        return list(names)

    def export_prometheus(self) -> str:
        lines: list[str] = []
        for name, value in self._counters.items():
            lines.append(f"{name} {value}")
        for name, value in self._gauges.items():
            lines.append(f"{name} {value}")
        for name, values in self._histograms.items():
            if values:
                lines.append(f"{name}_count {len(values)}")
                lines.append(f"{name}_sum {sum(values)}")
        return "\n".join(lines)


class AlertManager:
    """Manages alerts and alert rules."""

    def __init__(self) -> None:
        self.rules: dict[str, AlertRule] = {}
        self.active_alerts: dict[str, Alert] = {}

    def add_rule(self, rule: AlertRule) -> None:
        self.rules[rule.name] = rule

    def remove_rule(self, name: str) -> None:
        if name in self.rules:
            del self.rules[name]

    def enable_rule(self, name: str) -> None:
        if name in self.rules:
            self.rules[name].enabled = True

    def disable_rule(self, name: str) -> None:
        if name in self.rules:
            self.rules[name].enabled = False

    def fire_alert(self, rule_name: str, message: str) -> None:
        rule = self.rules.get(rule_name)
        if not rule:
            return
        alert = Alert(
            rule_name=rule_name,
            severity=rule.severity,
            message=message,
            labels=rule.labels.copy(),
            firing=True,
        )
        self.active_alerts[rule_name] = alert
        logger.warning(f"Alert fired: {rule_name} - {message}")

    def resolve_alert(self, rule_name: str) -> None:
        if rule_name in self.active_alerts:
            self.active_alerts[rule_name].firing = False

    def get_alert(self, rule_name: str) -> Alert | None:
        return self.active_alerts.get(rule_name)

    def get_active_alerts(self) -> list[Alert]:
        return [a for a in self.active_alerts.values() if a.firing]

    def evaluate_rules(self, metrics: dict[str, float]) -> list[str]:
        triggered: list[str] = []
        for name, rule in self.rules.items():
            if not rule.enabled:
                continue
            if self._evaluate_expression(rule.expression, metrics):
                triggered.append(name)
        return triggered

    def _evaluate_expression(
        self,
        expression: str,
        metrics: dict[str, float],
    ) -> bool:
        parts = expression.split()
        if len(parts) != 3:
            return False
        metric_name, operator, threshold_str = parts
        value = metrics.get(metric_name, 0.0)
        try:
            threshold = float(threshold_str)
        except ValueError:
            return False
        if operator == ">":
            return value > threshold
        elif operator == ">=":
            return value >= threshold
        elif operator == "<":
            return value < threshold
        elif operator == "<=":
            return value <= threshold
        elif operator == "==":
            return value == threshold
        elif operator == "!=":
            return value != threshold
        return False


class HealthChecker:
    """Performs health checks on system components."""

    def __init__(self) -> None:
        self.checks: dict[
            str,
            Callable[[], HealthCheckResult | Coroutine[Any, Any, HealthCheckResult]]
        ] = {}

    def register_check(
        self,
        name: str,
        check_func: Callable[[], HealthCheckResult | Coroutine[Any, Any, HealthCheckResult]],
    ) -> None:
        self.checks[name] = check_func

    async def run_check(self, name: str) -> HealthCheckResult:
        check_func = self.checks.get(name)
        if not check_func:
            return HealthCheckResult(
                component=name,
                status=HealthStatus.UNHEALTHY,
                message="Check not found",
            )
        try:
            result = check_func()
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            return HealthCheckResult(
                component=name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    async def run_all_checks(self) -> list[HealthCheckResult]:
        results: list[HealthCheckResult] = []
        for name in self.checks:
            result = await self.run_check(name)
            results.append(result)
        return results

    async def get_overall_status(self) -> HealthStatus:
        results = await self.run_all_checks()
        if not results:
            return HealthStatus.HEALTHY
        for result in results:
            if result.status == HealthStatus.UNHEALTHY:
                return HealthStatus.UNHEALTHY
        for result in results:
            if result.status == HealthStatus.DEGRADED:
                return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY


__all__ = [
    "MetricsExporter",
    "AlertManager",
    "AlertRule",
    "Alert",
    "AlertSeverity",
    "HealthChecker",
    "HealthStatus",
    "HealthCheckResult",
    "Metric",
    "MetricType",
    "DashboardConfig",
    "DashboardPanel",
]
