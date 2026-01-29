"""Advanced monitoring and alerting system for Mahavishnu."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
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

from ..core.workflow_state import WorkflowStatus


class AlertSeverity(Enum):
    """Alert severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(Enum):
    """Types of alerts."""

    SYSTEM_HEALTH = "system_health"
    WORKFLOW_FAILURE = "workflow_failure"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    SECURITY_ISSUE = "security_issue"
    BACKUP_FAILURE = "backup_failure"


@dataclass
class Alert:
    """Data structure for an alert."""

    id: str
    timestamp: datetime
    severity: AlertSeverity
    type: AlertType
    title: str
    description: str
    details: dict[str, Any]
    acknowledged: bool = False
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None


class AlertManager:
    """Manages alerts and notifications."""

    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger(__name__)
        self.alerts: list[Alert] = []
        self.alert_handlers: dict[AlertType, list[Callable]] = {}
        self.notification_channels = []

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

    async def trigger_alert(
        self,
        severity: AlertSeverity,
        alert_type: AlertType,
        title: str,
        description: str,
        details: dict[str, Any] = None,
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

        # Execute registered handlers
        if alert_type in self.alert_handlers:
            for handler in self.alert_handlers[alert_type]:
                try:
                    await handler(alert)
                except Exception as e:
                    self.logger.error(f"Error in alert handler: {str(e)}")

        # Send notifications
        await self._send_notifications(alert)

        self.logger.info(f"Alert triggered: {title} [{severity.value}]")
        return alert

    async def acknowledge_alert(self, alert_id: str, user: str):
        """Acknowledge an alert."""
        for alert in self.alerts:
            if alert.id == alert_id:
                alert.acknowledged = True
                alert.acknowledged_by = user
                alert.acknowledged_at = datetime.now()
                self.logger.info(f"Alert {alert_id} acknowledged by {user}")
                break

    async def get_active_alerts(self) -> list[Alert]:
        """Get all non-acknowledged alerts."""
        return [alert for alert in self.alerts if not alert.acknowledged]

    async def _send_notifications(self, alert: Alert):
        """Send notifications through all registered channels."""
        for channel in self.notification_channels:
            try:
                await channel.send_notification(alert)
            except Exception as e:
                self.logger.error(f"Failed to send notification via {channel.name}: {str(e)}")

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
                    self.logger.error(f"Failed to auto-heal workflow: {str(e)}")

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
            self.logger.error(f"Failed to retry backup: {str(e)}")

    async def _monitoring_loop(self):
        """Background monitoring loop."""
        while True:
            try:
                # Run various health checks
                await self._check_system_health()
                await self._check_workflow_health()
                await self._check_resource_usage()
                await self._check_backup_status()

                # Sleep before next check
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {str(e)}")
                await asyncio.sleep(60)  # Wait longer if there's an error

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
            self.logger.error(f"Error checking system health: {str(e)}")

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
            self.logger.error(f"Error checking workflow health: {str(e)}")

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
            self.logger.error(f"Error checking resource usage: {str(e)}")

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
            self.logger.error(f"Error checking backup status: {str(e)}")


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

            print(f"Email notification sent for alert {alert.id}")
        except Exception as e:
            print(f"Failed to send email notification: {str(e)}")


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
                        if alert.severity in [AlertSeverity.HIGH, AlertSeverity.CRITICAL]
                        else "warning"
                        if alert.severity == AlertSeverity.MEDIUM
                        else "good",
                        "fields": [
                            {"title": "Description", "value": alert.description, "short": False},
                            {"title": "Time", "value": alert.timestamp.isoformat(), "short": True},
                            {"title": "Type", "value": alert.type.value, "short": True},
                        ],
                    }
                ],
            }

            response = requests.post(self.webhook_url, json=message)
            if response.status_code != 200:
                print(f"Failed to send Slack notification: {response.text}")
            else:
                print(f"Slack notification sent for alert {alert.id}")
        except Exception as e:
            print(f"Failed to send Slack notification: {str(e)}")


class PagerDutyNotificationChannel(NotificationChannel):
    """PagerDuty notification channel."""

    def __init__(self, integration_key: str):
        super().__init__("pagerduty")
        self.integration_key = integration_key

    async def send_notification(self, alert: Alert):
        """Send a PagerDuty notification."""
        try:
            severity_map = {
                AlertSeverity.LOW: "info",
                AlertSeverity.MEDIUM: "warning",
                AlertSeverity.HIGH: "error",
                AlertSeverity.CRITICAL: "critical",
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
                        "type": alert.type.value,
                        "details": alert.details,
                    },
                },
            }

            headers = {"Content-Type": "application/json"}

            response = requests.post(
                "https://events.pagerduty.com/v2/enqueue", json=payload, headers=headers
            )

            if response.status_code != 202:
                print(f"Failed to send PagerDuty notification: {response.text}")
            else:
                print(f"PagerDuty notification sent for alert {alert.id}")
        except Exception as e:
            print(f"Failed to send PagerDuty notification: {str(e)}")


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
            return {"critical": 0, "high": 0, "medium": 0, "low": 0}

        alerts = await self.alert_manager.get_active_alerts()
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}

        for alert in alerts:
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
                "type": alert.type.value,
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
