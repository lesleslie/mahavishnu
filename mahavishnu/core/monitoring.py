"""Advanced monitoring and alerting system for Mahavishnu."""

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
import json
import logging
import smtplib
import time
from typing import Any

import requests

from ..core.status import HealthStatus as ComponentHealthStatus
from ..core.workflow_state import WorkflowStatus

# ---------------------------------------------------------------------------
# Dashboard configuration (merged from dashboard_config.py)
# ---------------------------------------------------------------------------


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
        y_offset = 0
        panels = []
        for i, p in enumerate(self.panels):
            panels.append(
                {
                    "id": i + 1,
                    "title": p.title,
                    "type": p.panel_type,
                    "gridPos": {
                        "x": 0,
                        "y": y_offset,
                        "w": p.width,
                        "h": p.height,
                    },
                    "targets": [{"expr": p.query, "datasource": p.datasource}],
                }
            )
            y_offset += p.height
        grafana = {
            "dashboard": {
                "title": self.title,
                "uid": self.title.lower().replace(" ", "-"),
                "panels": panels,
                "refresh": f"{self.refresh_interval}s",
                "tags": self.tags,
            },
            "overwrite": True,
        }
        return json.dumps(grafana, indent=2)


class AlertSeverity(Enum):
    """Alert severity levels."""

    INFO = "info"
    LOW = "low"
    WARNING = "warning"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertType(Enum):
    """Types of alerts."""

    SYSTEM_HEALTH = "system_health"
    WORKFLOW_FAILURE = "workflow_failure"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    SECURITY_ISSUE = "security_issue"
    BACKUP_FAILURE = "backup_failure"


@dataclass
class AlertRule:
    """Rule used by the lightweight alert evaluator."""

    name: str
    expression: str
    severity: AlertSeverity = AlertSeverity.WARNING
    duration_seconds: int = 60
    enabled: bool = True
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
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
    """Data structure for an alert.

    This model supports both notification-style alerts and the simpler
    rule-engine alerts used by monitoring_infra so the alert implementation
    can live in one place.
    """

    id: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    severity: AlertSeverity = AlertSeverity.MEDIUM
    type: AlertType | None = None
    title: str = ""
    description: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    rule_name: str | None = None
    message: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    firing: bool = True
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    fired_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.fired_at is None:
            self.fired_at = self.timestamp
        if self.message is None and self.description:
            self.message = self.description
        if self.id is None:
            base = self.rule_name or self.title or "alert"
            self.id = f"alert_{base}_{int(self.timestamp.timestamp())}"

    @property
    def is_firing(self) -> bool:
        return self.firing

    def acknowledge(self, by: str) -> None:
        self.acknowledged = True
        self.acknowledged_by = by
        self.acknowledged_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "details": self.details,
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "fired_at": self.fired_at.isoformat() if self.fired_at else None,
            "firing": self.firing,
        }
        if self.type is not None:
            payload["type"] = self.type.value
        if self.rule_name is not None:
            payload["rule_name"] = self.rule_name
        if self.message is not None:
            payload["message"] = self.message
        if self.labels:
            payload["labels"] = self.labels
        return payload


class AlertManager:
    """Manages alerts and notifications."""

    def __init__(self, app=None):
        self.app = app
        self.logger = logging.getLogger(__name__)
        self.alerts: list[Alert] = []
        self.alert_handlers: dict[AlertType, list[Callable]] = {}
        self.notification_channels = []  # type: ignore[var-annotated]
        self.rules: dict[str, AlertRule] = {}
        self.active_alerts: dict[str, Alert] = {}
        self._shutdown_event = asyncio.Event()

        # Initialize default alert handlers
        self._init_default_handlers()

        # Initialize monitoring loop (will be started when event loop is available)
        self._monitoring_task = None

    def _init_default_handlers(self):
        """Initialize default alert handlers."""
        # Register default handlers for different alert types
        self.register_handler(AlertType.WORKFLOW_FAILURE, self._handle_workflow_failure)
        self.register_handler(AlertType.SYSTEM_HEALTH, self._handle_system_health)
        self.register_handler(AlertType.RESOURCE_EXHAUSTION, self._handle_resource_exhaustion)
        self.register_handler(
            AlertType.PERFORMANCE_DEGRADATION, self._handle_performance_degradation
        )
        self.register_handler(AlertType.BACKUP_FAILURE, self._handle_backup_failure)

    def register_handler(self, alert_type: AlertType, handler: Callable):
        """Register a handler for a specific alert type."""
        if alert_type not in self.alert_handlers:
            self.alert_handlers[alert_type] = []
        self.alert_handlers[alert_type].append(handler)

    def register_notification_channel(self, channel: "NotificationChannel"):
        """Register a notification channel."""
        self.notification_channels.append(channel)

    def add_rule(self, rule: AlertRule) -> None:
        self.rules[rule.name] = rule

    def remove_rule(self, name: str) -> None:
        self.rules.pop(name, None)

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
        self.alerts.append(alert)
        self.active_alerts[rule_name] = alert
        self.logger.warning("Alert fired: %s - %s", rule_name, message)

    def resolve_alert(self, rule_name: str) -> None:
        if rule_name in self.active_alerts:
            self.active_alerts[rule_name].firing = False

    def get_alert(self, rule_name: str) -> Alert | None:
        return self.active_alerts.get(rule_name)

    def get_rule_alerts(self) -> list[Alert]:
        return [a for a in self.active_alerts.values() if a.firing]

    def evaluate_rules(self, metrics: dict[str, float]) -> list[str]:
        triggered: list[str] = []
        for name, rule in self.rules.items():
            if not rule.enabled:
                continue
            if self._evaluate_expression(rule.expression, metrics):
                self.fire_alert(name, f"Rule matched for {name}")
                triggered.append(name)
        return triggered

    def _evaluate_expression(self, expression: str, metrics: dict[str, float]) -> bool:
        parts = expression.split()
        if len(parts) != 3:
            return False
        metric_name, operator, threshold_str = parts
        value = metrics.get(metric_name, 0.0)
        try:
            threshold = float(threshold_str)
        except ValueError:
            return False

        ops = {
            ">": lambda a, b: a > b,
            ">=": lambda a, b: a >= b,
            "<": lambda a, b: a < b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }
        if operator in ops:
            return ops[operator](value, threshold)  # type: ignore[no-any-return]
        return False

    async def trigger_alert(
        self,
        severity: AlertSeverity,
        alert_type: AlertType,
        title: str,
        description: str,
        details: dict[str, Any] | None = None,
    ) -> Alert:
        """Trigger an alert."""
        alert_id = f"alert_{int(time.time())}_{len(self.alerts)}"

        alert = Alert(
            id=alert_id,
            timestamp=datetime.now(),
            severity=severity,
            type=alert_type,
            title=title,
            description=description,
            details=details or {},
        )

        self.alerts.append(alert)
        self.active_alerts[alert_id] = alert

        # Execute registered handlers
        if alert_type in self.alert_handlers:
            for handler in self.alert_handlers[alert_type]:
                try:
                    await handler(alert)
                except Exception as e:
                    self.logger.error(f"Error in alert handler: {e}")

        # Send notifications
        await self._send_notifications(alert)

        self.logger.info(f"Alert triggered: {title} [{severity.value}]")
        return alert

    async def acknowledge_alert(self, alert_id: str, user: str):
        """Acknowledge an alert."""
        for alert in self.alerts:
            if alert.id == alert_id or alert.rule_name == alert_id:
                alert.acknowledge(user)
                self.logger.info(f"Alert {alert_id} acknowledged by {user}")
                break

    async def get_active_alerts(self) -> list[Alert]:
        """Get all non-acknowledged alerts."""
        return self.get_active_alerts_sync()

    def get_active_alerts_sync(self) -> list[Alert]:
        """Synchronous version of get_active_alerts."""
        return [alert for alert in self.alerts if not alert.acknowledged and alert.firing]

    async def _send_notifications(self, alert: Alert):
        """Send notifications through all registered channels."""
        for channel in self.notification_channels:
            try:
                await channel.send_notification(alert)
            except Exception as e:
                self.logger.error(f"Failed to send notification via {channel.name}: {e}")

    async def _handle_workflow_failure(self, alert: Alert):
        """Handle workflow failure alerts."""
        # Log the failure
        self.logger.error(f"Workflow failure: {alert.description}")

        # Potentially trigger recovery
        if alert.details.get("auto_recovery", True):
            workflow_id = alert.details.get("workflow_id")
            if workflow_id:
                try:
                    # Attempt to heal the workflow
                    await self.app.error_recovery_manager.monitor_and_heal_workflows()
                except Exception as e:
                    self.logger.error(f"Failed to auto-heal workflow: {e}")

    async def _handle_system_health(self, alert: Alert):
        """Handle system health alerts."""
        self.logger.warning(f"System health issue: {alert.description}")

    async def _handle_resource_exhaustion(self, alert: Alert):
        """Handle resource exhaustion alerts."""
        self.logger.critical(f"Resource exhaustion: {alert.description}")

        # Reduce concurrent operations
        if "memory" in alert.description.lower():
            # Implement memory-saving measures
            pass

    async def _handle_performance_degradation(self, alert: Alert):
        """Handle performance degradation alerts."""
        self.logger.warning(f"Performance degradation: {alert.description}")

    async def _handle_backup_failure(self, alert: Alert):
        """Handle backup failure alerts."""
        self.logger.error(f"Backup failure: {alert.description}")

        # Trigger immediate backup retry
        try:
            from ..core.backup_recovery import BackupManager

            backup_manager = BackupManager(self.app)
            await backup_manager.create_backup("full")
        except Exception as e:
            self.logger.error(f"Failed to retry backup: {e}")

    async def _monitoring_loop(self):
        """Background monitoring loop."""
        while not self._shutdown_event.is_set():
            try:
                # Run various health checks
                await self._check_system_health()
                await self._check_workflow_health()
                await self._check_resource_usage()
                await self._check_backup_status()

                # Sleep before next check (with shutdown check)
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=30)
                    break  # Shutdown signaled
                except TimeoutError:
                    pass  # Normal timeout, continue loop
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                # Wait longer if there's an error (with shutdown check)
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=60)
                    break  # Shutdown signaled
                except TimeoutError:
                    pass  # Normal timeout, continue loop

    async def stop(self):
        """Stop the monitoring service gracefully."""
        self._shutdown_event.set()
        self.logger.info("Monitoring service stopped")

    async def _check_system_health(self):
        """Check overall system health."""
        try:
            # Check if all adapters are healthy
            unhealthy_adapters = []
            for name, adapter in self.app.adapters.items():
                health = await adapter.get_health()
                if health.get("status") != "healthy":
                    unhealthy_adapters.append(name)

            if unhealthy_adapters:
                await self.trigger_alert(
                    severity=AlertSeverity.HIGH,
                    alert_type=AlertType.SYSTEM_HEALTH,
                    title="Unhealthy Adapters",
                    description=f"The following adapters are not healthy: {', '.join(unhealthy_adapters)}",
                    details={"unhealthy_adapters": unhealthy_adapters},
                )
        except Exception as e:
            self.logger.error(f"Error checking system health: {e}")

    async def _check_workflow_health(self):
        """Check workflow health."""
        try:
            # Check for workflows that have been stuck for too long
            from ..core.workflow_state import WorkflowStatus

            running_workflows = await self.app.workflow_state_manager.list_workflows(
                status=WorkflowStatus.RUNNING, limit=100
            )

            current_time = datetime.now()
            timeout_threshold = timedelta(minutes=30)  # 30-minute timeout

            for workflow in running_workflows:
                updated_at_str = workflow.get("updated_at")
                if updated_at_str:
                    try:
                        updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                        if current_time - updated_at > timeout_threshold:
                            # Workflow appears stuck
                            await self.trigger_alert(
                                severity=AlertSeverity.HIGH,
                                alert_type=AlertType.WORKFLOW_FAILURE,
                                title="Stuck Workflow",
                                description=f"Workflow {workflow.get('id', 'unknown')} appears to be stuck",
                                details={
                                    "workflow_id": workflow.get("id", "unknown"),
                                    "updated_at": updated_at_str,
                                    "timeout_minutes": timeout_threshold.total_seconds() / 60,
                                },
                            )
                    except ValueError:
                        # If we can't parse the date, skip this workflow
                        continue
        except Exception as e:
            self.logger.error(f"Error checking workflow health: {e}")

    async def _check_resource_usage(self):
        """Check resource usage."""
        try:
            import psutil

            # Check memory usage
            memory_percent = psutil.virtual_memory().percent
            if memory_percent > 90:
                await self.trigger_alert(
                    severity=AlertSeverity.HIGH,
                    alert_type=AlertType.RESOURCE_EXHAUSTION,
                    title="High Memory Usage",
                    description=f"Memory usage is at {memory_percent}%",
                    details={
                        "memory_percent": memory_percent,
                        "available_gb": round(psutil.virtual_memory().available / (1024**3), 2),
                    },
                )

            # Check disk usage
            disk_usage = psutil.disk_usage("/")
            disk_percent = (disk_usage.used / disk_usage.total) * 100
            if disk_percent > 90:
                await self.trigger_alert(
                    severity=AlertSeverity.HIGH,
                    alert_type=AlertType.RESOURCE_EXHAUSTION,
                    title="High Disk Usage",
                    description=f"Disk usage is at {disk_percent}%",
                    details={
                        "disk_percent": disk_percent,
                        "available_gb": round(disk_usage.free / (1024**3), 2),
                    },
                )
        except Exception as e:
            self.logger.error(f"Error checking resource usage: {e}")

    async def _check_backup_status(self):
        """Check backup status."""
        try:
            from ..core.backup_recovery import BackupManager

            backup_manager = BackupManager(self.app)

            backups = await backup_manager.list_backups()

            if not backups:
                await self.trigger_alert(
                    severity=AlertSeverity.HIGH,
                    alert_type=AlertType.BACKUP_FAILURE,
                    title="No Backups Available",
                    description="No backups have been created yet",
                    details={"backup_count": 0},
                )
            else:
                # Check if the latest backup is too old (older than 24 hours)
                latest_backup = backups[0]
                age = datetime.now() - latest_backup.timestamp
                if age > timedelta(hours=24):
                    await self.trigger_alert(
                        severity=AlertSeverity.MEDIUM,
                        alert_type=AlertType.BACKUP_FAILURE,
                        title="Outdated Backup",
                        description=f"Latest backup is {age.days} days old",
                        details={
                            "latest_backup_timestamp": latest_backup.timestamp.isoformat(),
                            "backup_age_hours": age.total_seconds() / 3600,
                        },
                    )
        except Exception as e:
            self.logger.error(f"Error checking backup status: {e}")


class NotificationChannel:
    """Base class for notification channels."""

    def __init__(self, name: str):
        self.name = name

    async def send_notification(self, alert: Alert):
        """Send a notification about an alert."""
        raise NotImplementedError


class EmailNotificationChannel(NotificationChannel):
    """Email notification channel."""

    def __init__(
        self, smtp_server: str, smtp_port: int, username: str, password: str, recipients: list[str]
    ):
        super().__init__("email")
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.recipients = recipients

    async def send_notification(self, alert: Alert):
        """Send an email notification."""
        try:
            msg = MIMEMultipart()
            msg["From"] = self.username
            msg["To"] = ", ".join(self.recipients)
            msg["Subject"] = f"[{alert.severity.value.upper()}] {alert.title}"

            body = f"""
Alert: {alert.title}
Severity: {alert.severity.value}
Time: {alert.timestamp.isoformat()}
Description: {alert.description}

Details:
{json.dumps(alert.details, indent=2)}

This is an automated message from the Mahavishnu monitoring system.
            """

            msg.attach(MIMEText(body, "plain"))

            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.username, self.password)
            text = msg.as_string()
            server.sendmail(self.username, self.recipients, text)
            server.quit()

            self.logger.info(f"Email notification sent for alert {alert.id}")  # type: ignore[attr-defined]
        except Exception as e:
            self.logger.error(f"Failed to send email notification: {e}")  # type: ignore[attr-defined]


class SlackNotificationChannel(NotificationChannel):
    """Slack notification channel."""

    def __init__(self, webhook_url: str, channel: str = "#alerts"):
        super().__init__("slack")
        self.webhook_url = webhook_url
        self.channel = channel

    async def send_notification(self, alert: Alert):
        """Send a Slack notification."""
        try:
            message = {
                "channel": self.channel,
                "text": f":rotating_light: *[{alert.severity.value.upper()}]* {alert.title}",
                "attachments": [
                    {
                        "color": "danger"
                        if alert.severity
                        in (AlertSeverity.HIGH, AlertSeverity.CRITICAL, AlertSeverity.EMERGENCY)
                        else "warning"
                        if alert.severity in (AlertSeverity.MEDIUM, AlertSeverity.WARNING)
                        else "good",
                        "fields": [
                            {"title": "Description", "value": alert.description, "short": False},
                            {"title": "Time", "value": alert.timestamp.isoformat(), "short": True},
                            {
                                "title": "Type",
                                "value": alert.type.value if alert.type else "rule",
                                "short": True,
                            },
                        ],
                    }
                ],
            }

            response = requests.post(self.webhook_url, json=message)  # type: ignore[arg-type]
            if response.status_code != 200:
                self.logger.warning(f"Failed to send Slack notification: {response.text}")  # type: ignore[attr-defined]
            else:
                self.logger.info(f"Slack notification sent for alert {alert.id}")  # type: ignore[attr-defined]
        except Exception as e:
            self.logger.error(f"Failed to send Slack notification: {e}")  # type: ignore[attr-defined]


class PagerDutyNotificationChannel(NotificationChannel):
    """PagerDuty notification channel."""

    def __init__(self, integration_key: str):
        super().__init__("pagerduty")
        self.integration_key = integration_key

    async def send_notification(self, alert: Alert):
        """Send a PagerDuty notification."""
        try:
            severity_map = {
                AlertSeverity.INFO: "info",
                AlertSeverity.LOW: "info",
                AlertSeverity.WARNING: "warning",
                AlertSeverity.MEDIUM: "warning",
                AlertSeverity.HIGH: "error",
                AlertSeverity.CRITICAL: "critical",
                AlertSeverity.EMERGENCY: "critical",
            }

            payload = {
                "routing_key": self.integration_key,
                "event_action": "trigger",
                "payload": {
                    "summary": f"[{alert.severity.value.upper()}] {alert.title}",
                    "source": "mahavishnu-monitoring",
                    "severity": severity_map[alert.severity],
                    "custom_details": {
                        "description": alert.description,
                        "timestamp": alert.timestamp.isoformat(),
                        "type": alert.type.value if alert.type else "rule",
                        "details": alert.details,
                    },
                },
            }

            headers = {"Content-Type": "application/json"}

            response = requests.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=payload,
                headers=headers,  # type: ignore[arg-type]
            )

            if response.status_code != 202:
                self.logger.warning(f"Failed to send PagerDuty notification: {response.text}")  # type: ignore[attr-defined]
            else:
                self.logger.info(f"PagerDuty notification sent for alert {alert.id}")  # type: ignore[attr-defined]
        except Exception as e:
            self.logger.error(f"Failed to send PagerDuty notification: {e}")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Monitoring infrastructure (merged from monitoring_infra.py)
# ---------------------------------------------------------------------------


class MetricType(Enum):
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
    timestamp: datetime = field(default_factory=datetime.now)

    def to_prometheus(self) -> str:
        """Convert to Prometheus format."""
        if self.labels:
            labels_str = ",".join(f'{k}="{v}"' for k, v in self.labels.items())
            return f"{self.name}{{{labels_str}}} {self.value}"
        return f"{self.name} {self.value}"


@dataclass
class ComponentHealthResult:
    """Result of a component health check.

    This is the internal monitoring health result, distinct from the
    Pydantic HealthCheckResult in health_schemas which serves API endpoints.
    """

    component: str
    status: ComponentHealthStatus
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)

    @property
    def healthy(self) -> bool:
        return self.status == ComponentHealthStatus.HEALTHY

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


class ComponentHealthChecker:
    """Performs health checks on system components."""

    def __init__(self) -> None:
        self.checks: dict[
            str, Callable[[], ComponentHealthResult | Coroutine[Any, Any, ComponentHealthResult]]
        ] = {}

    def register_check(
        self,
        name: str,
        check_func: Callable[
            [], ComponentHealthResult | Coroutine[Any, Any, ComponentHealthResult]
        ],
    ) -> None:
        self.checks[name] = check_func

    async def run_check(self, name: str) -> ComponentHealthResult:
        check_func = self.checks.get(name)
        if not check_func:
            return ComponentHealthResult(
                component=name,
                status=ComponentHealthStatus.UNHEALTHY,
                message="Check not found",
            )
        try:
            result = check_func()
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            return ComponentHealthResult(
                component=name,
                status=ComponentHealthStatus.UNHEALTHY,
                message=str(e),
            )

    async def run_all_checks(self) -> list[ComponentHealthResult]:
        results: list[ComponentHealthResult] = []
        for name in self.checks:
            result = await self.run_check(name)
            results.append(result)
        return results

    async def get_overall_status(self) -> ComponentHealthStatus:
        results = await self.run_all_checks()
        if not results:
            return ComponentHealthStatus.HEALTHY
        for result in results:
            if result.status == ComponentHealthStatus.UNHEALTHY:
                return ComponentHealthStatus.UNHEALTHY
        for result in results:
            if result.status == ComponentHealthStatus.DEGRADED:
                return ComponentHealthStatus.DEGRADED
        return ComponentHealthStatus.HEALTHY


class MonitoringDashboard:
    """Provides monitoring dashboard data."""

    def __init__(self, app):
        self.app = app
        self.alert_manager: AlertManager | None = None

    def set_alert_manager(self, alert_manager: AlertManager):
        """Set the alert manager."""
        self.alert_manager = alert_manager

    async def get_system_metrics(self) -> dict[str, Any]:
        """Get system metrics for the dashboard."""

        import psutil

        # Get system metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        memory_info = psutil.virtual_memory()
        disk_usage = psutil.disk_usage("/")

        # Get workflow metrics
        workflow_counts = await self._get_workflow_counts()

        # Get adapter health
        adapter_health = await self._get_adapter_health()

        # Get alert counts
        alert_counts = await self._get_alert_counts()

        return {
            "timestamp": datetime.now().isoformat(),
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_info.percent,
                "memory_available_gb": round(memory_info.available / (1024**3), 2),
                "disk_percent": (disk_usage.used / disk_usage.total) * 100,
                "disk_available_gb": round(disk_usage.free / (1024**3), 2),
                "uptime_seconds": time.time() - getattr(self.app, "_start_time", time.time()),
            },
            "workflows": workflow_counts,
            "adapters": adapter_health,
            "alerts": alert_counts,
        }

    async def _get_workflow_counts(self) -> dict[str, int]:
        """Get workflow counts by status."""
        counts = {}
        for status in WorkflowStatus:
            try:
                workflows = await self.app.workflow_state_manager.list_workflows(
                    status=status, limit=1
                )
                counts[status.value] = len(workflows)
            except Exception:
                counts[status.value] = 0

        return counts

    async def _get_adapter_health(self) -> dict[str, str]:
        """Get adapter health status."""
        health = {}
        for name, adapter in self.app.adapters.items():
            try:
                result = await adapter.get_health()
                health[name] = result.get("status", "unknown")
            except Exception:
                health[name] = "error"

        return health

    async def _get_alert_counts(self) -> dict[str, int]:
        """Get alert counts by severity."""
        if not self.alert_manager:
            return {"critical": 0, "high": 0, "medium": 0, "low": 0, "warning": 0, "info": 0}

        alerts = await self.alert_manager.get_active_alerts()
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "warning": 0, "info": 0}

        for alert in alerts:
            counts.setdefault(alert.severity.value, 0)
            counts[alert.severity.value] += 1

        return counts

    async def get_recent_alerts(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent alerts."""
        if not self.alert_manager:
            return []

        # Get all alerts and sort by timestamp
        alerts = sorted(self.alert_manager.alerts, key=lambda x: x.timestamp, reverse=True)
        recent_alerts = alerts[:limit]

        return [
            {
                "id": alert.id,
                "timestamp": alert.timestamp.isoformat(),
                "severity": alert.severity.value,
                "type": alert.type.value if alert.type else "rule",
                "title": alert.title,
                "description": alert.description,
                "acknowledged": alert.acknowledged,
            }
            for alert in recent_alerts
        ]


class MonitoringService:
    """Main monitoring service that ties everything together."""

    def __init__(self, app):
        self.app = app
        self.alert_manager = AlertManager(app)
        self.dashboard = MonitoringDashboard(app)
        self._shutdown_event = asyncio.Event()

        # Set up the dashboard to use the alert manager
        self.dashboard.set_alert_manager(self.alert_manager)

    async def get_dashboard_data(self) -> dict[str, Any]:
        """Get comprehensive dashboard data."""
        metrics = await self.dashboard.get_system_metrics()
        recent_alerts = await self.dashboard.get_recent_alerts(limit=10)

        return {
            "metrics": metrics,
            "recent_alerts": recent_alerts,
            "timestamp": datetime.now().isoformat(),
        }

    async def acknowledge_alert(self, alert_id: str, user: str) -> bool:
        """Acknowledge an alert."""
        try:
            await self.alert_manager.acknowledge_alert(alert_id, user)
            return True
        except Exception:
            return False
