"""Alerting system for adaptive routing.

Monitors adapter health, cost spikes, and routing anomalies
to trigger proactive alerts before issues impact users.

Design:
- Threshold-based alerts for success rates
- Anomaly detection for cost spikes
- Pattern detection for excessive fallbacks
- Webhook integration for external alerting
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC, timedelta
from enum import Enum
from typing import Any, Awaitable, Callable

from mahavishnu.core.metrics_schema import AdapterType, TaskType
from mahavishnu.core.metrics_collector import get_execution_tracker


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    """Types of routing alerts."""

    ADAPTER_DEGRADATION = "adapter_degradation"
    """Adapter success rate dropped below threshold."""

    COST_SPIKE = "cost_spike"
    """Unusual increase in routing costs."""

    EXCESSIVE_FALLBACKS = "excessive_fallbacks"
    """Too many fallback events occurring."""

    HIGH_LATENCY = "high_latency"
    """Adapter latency above acceptable threshold."""

    BUDGET_EXCEEDED = "budget_exceeded"
    """Cost budget exceeded configured limit."""


@dataclass
class Alert:
    """Routing alert with context.

    Attributes:
        alert_type: Type of alert
        severity: Severity level
        message: Human-readable description
        adapter: Related adapter (if applicable)
        current_value: Current metric value
        threshold_value: Threshold that was breached
        timestamp: When alert was triggered
        metadata: Additional context
    """
    alert_type: AlertType
    severity: AlertSeverity
    message: str
    adapter: AdapterType | None = None
    current_value: float | None = None
    threshold_value: float | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert alert to dictionary."""
        return {
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "adapter": self.adapter.value if self.adapter else None,
            "current_value": self.current_value,
            "threshold_value": self.threshold_value,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


class AlertHandler:
    """Base class for alert handlers.

    Implementations can send alerts to various destinations:
    - Slack
    - Email
    - PagerDuty
    - Webhook
    """

    async def send_alert(self, alert: Alert) -> None:
        """Send alert to destination.

        Args:
            alert: Alert to send
        """
        raise NotImplementedError("Subclasses must implement send_alert()")


class LoggingAlertHandler(AlertHandler):
    """Log alerts to system logs.

    Useful for development and testing.
    """

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.LoggingAlertHandler")

    async def send_alert(self, alert: Alert) -> None:
        """Log alert at appropriate level."""
        log_level = {
            AlertSeverity.INFO: logging.INFO,
            AlertSeverity.WARNING: logging.WARNING,
            AlertSeverity.CRITICAL: logging.CRITICAL,
        }.get(alert.severity, logging.ERROR)

        self.logger.log(
            log_level,
            f"[{alert.alert_type.value.upper()}] {alert.message}",
            extra={"alert": alert.to_dict()},
        )


class WebhookAlertHandler(AlertHandler):
    """Send alerts via webhook HTTP POST.

    Configuration:
        webhook_url: Destination URL for alerts
        timeout_seconds: HTTP request timeout (default: 5s)
    """

    def __init__(self, webhook_url: str, timeout_seconds: int = 5):
        """Initialize webhook handler.

        Args:
            webhook_url: Destination URL for POST requests
            timeout_seconds: HTTP timeout (default: 5)
        """
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds
        self.logger = logging.getLogger(f"{__name__}.WebhookAlertHandler")

    async def send_alert(self, alert: Alert) -> None:
        """Send alert via HTTP POST.

        Args:
            alert: Alert payload
        """
        import aiohttp

        payload = alert.to_dict()

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
                ) as response:
                    if response.status >= 200 and response.status < 300:
                        self.logger.info(f"Alert sent successfully: {alert.alert_type.value}")
                    else:
                        self.logger.error(
                            f"Failed to send alert: HTTP {response.status}"
                        )
        except Exception as e:
            self.logger.error(f"Webhook alert failed: {e}")


class RoutingAlertManager:
    """Manages alerting for adaptive routing system.

    Monitors:
    - Adapter success rates (degradation detection)
    - Cost trends (spike detection)
    - Fallback patterns (excessive fallbacks)
    - Latency percentiles (performance issues)

    Configurable thresholds with automatic evaluation.
    """

    def __init__(
        self,
        success_rate_threshold: float = 0.95,
        fallback_rate_threshold: float = 0.1,
        latency_p95_threshold_ms: int = 5000,
        cost_spike_multiplier: float = 2.0,
        evaluation_interval_seconds: int = 60,
        handlers: list[AlertHandler] | None = None,
    ):
        """Initialize alert manager.

        Args:
            success_rate_threshold: Min acceptable success rate (default: 95%)
            fallback_rate_threshold: Max acceptable fallback rate (default: 10%)
            latency_p95_threshold_ms: Max acceptable p95 latency (default: 5s)
            cost_spike_multiplier: Multiplier for detecting cost spikes (default: 2x)
            evaluation_interval_seconds: How often to evaluate (default: 60s)
            handlers: List of alert handlers (default: logging handler)
        """
        self.success_rate_threshold = success_rate_threshold
        self.fallback_rate_threshold = fallback_rate_threshold
        self.latency_p95_threshold_ms = latency_p95_threshold_ms
        self.cost_spike_multiplier = cost_spike_multiplier
        self.evaluation_interval_seconds = evaluation_interval_seconds

        # Alert handlers (default to logging if none provided)
        self.handlers = handlers if handlers is not None else [LoggingAlertHandler()]

        # State tracking
        self._previous_cost_usd: float | None = None
        self._alert_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._last_evaluation: datetime | None = None

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"RoutingAlertManager initialized with thresholds: "
            f"success_rate>={success_rate_threshold}, "
            f"fallback_rate<{fallback_rate_threshold}, "
            f"latency_p95<{latency_p95_threshold_ms}ms"
        )

    async def evaluate_adapter_health(self) -> list[Alert]:
        """Evaluate adapter health and generate alerts.

        Returns:
            List of generated alerts
        """
        alerts = []
        tracker = get_execution_tracker()

        # Check each adapter's success rate
        for adapter in AdapterType:
            stats = await tracker.get_adapter_stats(adapter)
            if stats is None:
                continue

            success_rate = stats["success_rate"]
            total_executions = stats["total_executions"]

            # Need minimum samples before alerting
            if total_executions < 10:
                continue

            # Check success rate threshold
            if success_rate < self.success_rate_threshold:
                severity = (
                    AlertSeverity.CRITICAL
                    if success_rate < 0.8
                    else AlertSeverity.WARNING
                )
                alerts.append(
                    Alert(
                        alert_type=AlertType.ADAPTER_DEGRADATION,
                        severity=severity,
                        message=(
                            f"Adapter {adapter.value} success rate dropped to {success_rate:.1%} "
                            f"(threshold: {self.success_rate_threshold:.1%})"
                        ),
                        adapter=adapter,
                        current_value=success_rate,
                        threshold_value=self.success_rate_threshold,
                        metadata={
                            "total_executions": total_executions,
                            "failed_executions": stats["failed_executions"],
                        },
                    )
                )

        return alerts

    async def evaluate_cost_anomalies(
        self, current_cost_usd: float
    ) -> list[Alert]:
        """Evaluate cost for spikes.

        Args:
            current_cost_usd: Current accumulated cost

        Returns:
            List of cost alerts
        """
        alerts = []

        if self._previous_cost_usd is None:
            self._previous_cost_usd = current_cost_usd
            return alerts

        # Calculate percent change
        if self._previous_cost_usd > 0:
            change_ratio = current_cost_usd / self._previous_cost_usd
            change_percent = (change_ratio - 1) * 100

            # Check for spike
            if change_ratio >= self.cost_spike_multiplier:
                alerts.append(
                    Alert(
                        alert_type=AlertType.COST_SPIKE,
                        severity=AlertSeverity.CRITICAL,
                        message=(
                            f"Cost spike detected: ${current_cost_usd:.2f} is "
                            f"{change_percent:.0f}% higher than previous ${self._previous_cost_usd:.2f}"
                        ),
                        current_value=current_cost_usd,
                        threshold_value=self._previous_cost_usd,
                        metadata={
                            "previous_cost": self._previous_cost_usd,
                            "change_percent": change_percent,
                        },
                    )
                )
            elif change_ratio >= 1.5:
                alerts.append(
                    Alert(
                        alert_type=AlertType.COST_SPIKE,
                        severity=AlertSeverity.WARNING,
                        message=(
                            f"Cost increase detected: ${current_cost_usd:.2f} is "
                            f"{change_percent:.0f}% higher than previous ${self._previous_cost_usd:.2f}"
                        ),
                        current_value=current_cost_usd,
                        threshold_value=self._previous_cost_usd,
                        metadata={
                            "previous_cost": self._previous_cost_usd,
                            "change_percent": change_percent,
                        },
                    )
                )

        self._previous_cost_usd = current_cost_usd
        return alerts

    async def evaluate_fallback_patterns(
        self, fallback_count: int, total_executions: int
    ) -> list[Alert]:
        """Evaluate fallback patterns.

        Args:
            fallback_count: Number of fallbacks in evaluation period
            total_executions: Total executions in period

        Returns:
            List of fallback alerts
        """
        alerts = []

        if total_executions == 0:
            return alerts

        fallback_rate = fallback_count / total_executions

        if fallback_rate > self.fallback_rate_threshold:
            severity = (
                AlertSeverity.CRITICAL
                if fallback_rate > 0.3
                else AlertSeverity.WARNING
            )
            alerts.append(
                Alert(
                    alert_type=AlertType.EXCESSIVE_FALLBACKS,
                    severity=severity,
                    message=(
                        f"Excessive fallbacks: {fallback_count}/{total_executions} "
                        f"({fallback_rate:.1%} of executions exceed threshold: {self.fallback_rate_threshold:.1%})"
                    ),
                    current_value=fallback_rate,
                    threshold_value=self.fallback_rate_threshold,
                    metadata={
                        "fallback_count": fallback_count,
                        "total_executions": total_executions,
                    },
                )
            )

        return alerts

    async def _evaluation_loop(self) -> None:
        """Background evaluation loop.

        Periodically evaluates:
        1. Adapter health (success rates)
        2. Cost anomalies (spikes)
        3. Fallback patterns
        """
        self.logger.info("Starting alert evaluation loop")

        while not self._shutdown_event.is_set():
            try:
                # Wait for evaluation interval
                await asyncio.sleep(self.evaluation_interval_seconds)

                # Run all evaluations
                all_alerts = []

                # Adapter health checks
                health_alerts = await self.evaluate_adapter_health()
                all_alerts.extend(health_alerts)

                # Cost anomaly detection (would need current cost from CostOptimizer)
                # This is placeholder - integration with CostOptimizer needed
                # cost_alerts = await self.evaluate_cost_anomalies(current_cost_usd)
                # all_alerts.extend(cost_alerts)

                # Fallback pattern detection
                # This would need fallback tracking from metrics
                # fallback_alerts = await self.evaluate_fallback_patterns(...)
                # all_alerts.extend(fallback_alerts)

                # Send alerts via all handlers
                for alert in all_alerts:
                    for handler in self.handlers:
                        try:
                            await handler.send_alert(alert)
                        except Exception as e:
                            self.logger.error(
                                f"Handler {handler.__class__.__name__} failed: {e}"
                            )

                if all_alerts:
                    self.logger.warning(
                        f"Generated {len(all_alerts)} alerts in evaluation cycle"
                    )
                else:
                    self.logger.debug("No alerts generated in this cycle")

                self._last_evaluation = datetime.now(UTC)

            except asyncio.CancelledError:
                self.logger.info("Alert evaluation loop cancelled")
                break
            except Exception as e:
                self.logger.error(f"Alert evaluation error: {e}", exc_info=True)

    async def start(self) -> None:
        """Start alert evaluation loop.

        Begins background periodic evaluation.
        """
        if self._alert_task is not None:
            self.logger.warning("Alert manager already started")
            return

        self._shutdown_event.clear()
        self._alert_task = asyncio.create_task(self._evaluation_loop())
        self.logger.info(
            f"RoutingAlertManager started (evaluation every {self.evaluation_interval_seconds}s)"
        )

    async def stop(self) -> None:
        """Stop alert evaluation loop.

        Stops background evaluation and waits for completion.
        """
        self.logger.info("Stopping RoutingAlertManager...")

        # Cancel evaluation loop
        if self._alert_task and not self._alert_task.done():
            self._alert_task.cancel()
            try:
                await self._alert_task
            except asyncio.CancelledError:
                pass

        # Shutdown event
        self._shutdown_event.set()
        self.logger.info("RoutingAlertManager stopped")

    def get_status(self) -> dict[str, Any]:
        """Get alert manager status.

        Returns:
            Status dictionary with configuration and state
        """
        return {
            "success_rate_threshold": self.success_rate_threshold,
            "fallback_rate_threshold": self.fallback_rate_threshold,
            "latency_p95_threshold_ms": self.latency_p95_threshold_ms,
            "cost_spike_multiplier": self.cost_spike_multiplier,
            "evaluation_interval_seconds": self.evaluation_interval_seconds,
            "handlers_count": len(self.handlers),
            "running": self._alert_task is not None and not self._alert_task.done(),
            "last_evaluation": self._last_evaluation.isoformat() if self._last_evaluation else None,
        }


# Singleton instance for global access
_manager: RoutingAlertManager | None = None


def get_alert_manager() -> RoutingAlertManager:
    """Get or create global RoutingAlertManager singleton.

    Returns:
        Global RoutingAlertManager instance
    """
    global _manager
    if _manager is None:
        _manager = RoutingAlertManager()
    return _manager


async def initialize_alert_manager(
    success_rate_threshold: float = 0.95,
    fallback_rate_threshold: float = 0.1,
    handlers: list[AlertHandler] | None = None,
) -> RoutingAlertManager:
    """Initialize and start global alert manager.

    Args:
        success_rate_threshold: Min acceptable success rate (default: 95%)
        fallback_rate_threshold: Max acceptable fallback rate (default: 10%)
        handlers: Optional list of alert handlers

    Returns:
        Started RoutingAlertManager instance
    """
    global _manager

    if _manager is None:
        _manager = RoutingAlertManager(
            success_rate_threshold=success_rate_threshold,
            fallback_rate_threshold=fallback_rate_threshold,
            handlers=handlers,
        )

    await _manager.start()
    return _manager


__all__ = [
    "Alert",
    "AlertSeverity",
    "AlertType",
    "AlertHandler",
    "LoggingAlertHandler",
    "WebhookAlertHandler",
    "RoutingAlertManager",
    "get_alert_manager",
    "initialize_alert_manager",
]
