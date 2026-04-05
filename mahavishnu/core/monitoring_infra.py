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

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from .dashboard_config import DashboardConfig, DashboardPanel
from .monitoring import Alert, AlertManager as _BaseAlertManager, AlertRule, AlertSeverity
from mahavishnu.core.status import HealthStatus

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)


class MetricType(StrEnum):
    """Prometheus metric types."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


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


class AlertManager(_BaseAlertManager):
    """Compatibility wrapper around the canonical alert manager."""

    def __init__(self) -> None:
        super().__init__(app=None)

    def get_active_alerts(self) -> list[Alert]:
        """Get all non-acknowledged alerts."""
        return [alert for alert in self.alerts if not alert.acknowledged and alert.firing]


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


class HealthChecker:
    """Performs health checks on system components."""

    def __init__(self) -> None:
        self.checks: dict[
            str, Callable[[], HealthCheckResult | Coroutine[Any, Any, HealthCheckResult]]
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
