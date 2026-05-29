# tests/unit/test_monitoring_cli.py
"""Unit tests for monitoring_cli Typer commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from mahavishnu.cli import monitoring_cli as mon_module

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class _FakeAlert:
    id: str
    title: str
    description: str
    timestamp: datetime
    severity: Any  # will be an enum-like
    type: Any
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Wrap string severity/type in fake enum wrappers
        if isinstance(self.severity, str):
            self.severity = _FakeAlertSeverity(self.severity)
        if isinstance(self.type, str):
            self.type = _FakeAlertType(self.type)


class _FakeAlertSeverity:
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    def __init__(self, value: str) -> None:
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    @classmethod
    def from_string(cls, s: str) -> _FakeAlertSeverity:
        return cls(s)


class _FakeAlertType:
    SYSTEM_HEALTH = "system_health"

    def __init__(self, value: str) -> None:
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    @classmethod
    def from_string(cls, s: str) -> _FakeAlertType:
        return cls(s)


class _FakeAlertManager:
    def __init__(self, alerts: list[_FakeAlert] | None = None) -> None:
        self._alerts = alerts or []

    async def get_active_alerts(self) -> list[_FakeAlert]:
        return self._alerts

    async def acknowledge_alert(self, alert_id: str, user: str) -> bool:
        for alert in self._alerts:
            if alert.id == alert_id:
                return True
        return False

    async def trigger_alert(self, **kwargs) -> _FakeAlert:
        severity = kwargs.get("severity", _FakeAlertSeverity.MEDIUM)
        alert_type = kwargs.get("alert_type", _FakeAlertType.SYSTEM_HEALTH)
        if isinstance(severity, _FakeAlertSeverity):
            severity = _FakeAlertSeverity(
                severity.value if hasattr(severity, "value") else severity
            )
        if isinstance(alert_type, _FakeAlertType):
            alert_type = _FakeAlertType(
                alert_type.value if hasattr(alert_type, "value") else alert_type
            )
        return _FakeAlert(
            id="test-alert-id",
            title=kwargs.get("title", "Test Alert"),
            description=kwargs.get("description", "Test description"),
            timestamp=datetime.now(),
            severity=severity,
            type=alert_type,
            details=kwargs.get("details", {}),
        )


class _FakeMonitoringService:
    def __init__(self) -> None:
        self.alert_manager = _FakeAlertManager()
        self._dashboard_data = {
            "metrics": {
                "system": {
                    "cpu_percent": 45.5,
                    "memory_percent": 62.1,
                    "memory_available_gb": 8.5,
                    "disk_percent": 55.0,
                    "disk_available_gb": 200.0,
                    "uptime_seconds": 3600.0,
                },
                "workflows": {"running": 3, "pending": 1, "completed": 10},
                "adapters": {"prefect": "healthy", "llamaindex": "healthy", "agno": "degraded"},
                "alerts": {"critical": 0, "high": 1, "medium": 2, "low": 0},
            },
            "alerts": [],
        }

    async def get_dashboard_data(self) -> dict[str, Any]:
        return self._dashboard_data

    async def acknowledge_alert(self, alert_id: str, user: str) -> bool:
        return await self.alert_manager.acknowledge_alert(alert_id, user)


class _FakeMahavishnuApp:
    def __init__(self) -> None:
        self.monitoring_service = _FakeMonitoringService()


# ---------------------------------------------------------------------------
# CliRunner
# ---------------------------------------------------------------------------

# Use CliRunner from Typer for click/typer CLI testing
_runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_app():
    return patch.object(mon_module, "MahavishnuApp", return_value=_FakeMahavishnuApp())


# ---------------------------------------------------------------------------
# get-dashboard
# ---------------------------------------------------------------------------


def test_get_dashboard_json_output(tmp_path: pytest.TempPathFactory) -> None:
    """--output should write JSON to the file."""
    out_file = tmp_path / "dashboard.json"

    with _patch_app():
        result = _runner.invoke(
            mon_module.app,
            ["get-dashboard", "--output", str(out_file)],
        )

    assert result.exit_code == 0, result.output
    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert "metrics" in data
    assert data["metrics"]["system"]["cpu_percent"] == 45.5


def test_get_dashboard_console_output() -> None:
    """No --output flag should echo human-readable summary."""
    with _patch_app():
        result = _runner.invoke(mon_module.app, ["get-dashboard"])

    assert result.exit_code == 0, result.output
    assert "SYSTEM METRICS" in result.output
    assert "CPU Usage" in result.output
    assert "WORKFLOW COUNTS" in result.output
    assert "running: 3" in result.output


# ---------------------------------------------------------------------------
# get-alerts
# ---------------------------------------------------------------------------


def test_get_alerts_no_alerts(tmp_path: pytest.TempPathFactory) -> None:
    """When no alerts exist, should show 'No active alerts'."""
    with _patch_app():
        result = _runner.invoke(mon_module.app, ["get-alerts"])

    assert result.exit_code == 0, result.output
    assert "No active alerts" in result.output


def test_get_alerts_json_output(tmp_path: pytest.TempPathFactory) -> None:
    """--output should write JSON list of alerts to file."""
    out_file = tmp_path / "alerts.json"

    # Patch in alerts
    fake_alert = _FakeAlert(
        id="alert-1",
        title="High CPU",
        description="CPU usage above 90%",
        timestamp=datetime(2026, 5, 23, 12, 0, 0),
        severity=_FakeAlertSeverity.HIGH,
        type=_FakeAlertType.SYSTEM_HEALTH,
        details={"cpu": 95},
    )

    app_with_alerts = _FakeMahavishnuApp()
    app_with_alerts.monitoring_service.alert_manager = _FakeAlertManager([fake_alert])

    with patch.object(mon_module, "MahavishnuApp", return_value=app_with_alerts):
        result = _runner.invoke(
            mon_module.app,
            ["get-alerts", "--output", str(out_file)],
        )

    assert result.exit_code == 0, result.output
    data = json.loads(out_file.read_text())
    assert len(data) == 1
    assert data[0]["id"] == "alert-1"
    assert data[0]["severity"] == "high"


def test_get_alerts_console_with_data() -> None:
    """Console output should show severity icons and descriptions."""
    fake_alert = _FakeAlert(
        id="alert-1",
        title="Disk Space Low",
        description="Available disk space below 10%",
        timestamp=datetime(2026, 5, 23, 12, 0, 0),
        severity=_FakeAlertSeverity.MEDIUM,
        type=_FakeAlertType.SYSTEM_HEALTH,
    )

    app_with_alerts = _FakeMahavishnuApp()
    app_with_alerts.monitoring_service.alert_manager = _FakeAlertManager([fake_alert])

    with patch.object(mon_module, "MahavishnuApp", return_value=app_with_alerts):
        result = _runner.invoke(mon_module.app, ["get-alerts"])

    assert result.exit_code == 0, result.output
    assert "Disk Space Low" in result.output
    assert "MEDIUM" in result.output


# ---------------------------------------------------------------------------
# acknowledge-alert
# ---------------------------------------------------------------------------


def test_acknowledge_alert_success() -> None:
    """Valid alert ID should be acknowledged and exit with code 0."""
    app_with_alerts = _FakeMahavishnuApp()
    app_with_alerts.monitoring_service.alert_manager = _FakeAlertManager(
        [
            _FakeAlert(
                id="alert-42",
                title="Test",
                description="Test alert",
                timestamp=datetime.now(),
                severity=_FakeAlertSeverity.MEDIUM,
                type=_FakeAlertType.SYSTEM_HEALTH,
            )
        ]
    )

    with patch.object(mon_module, "MahavishnuApp", return_value=app_with_alerts):
        result = _runner.invoke(
            mon_module.app,
            ["acknowledge-alert", "alert-42", "--user", "test-user"],
        )

    assert result.exit_code == 0, result.output
    assert "acknowledged by test-user" in result.output


def test_acknowledge_alert_not_found() -> None:
    """Unknown alert ID should exit with code 1."""
    with _patch_app():
        result = _runner.invoke(
            mon_module.app,
            ["acknowledge-alert", "nonexistent-alert"],
        )

    assert result.exit_code == 1, result.output
    assert "Failed to acknowledge" in result.output


# ---------------------------------------------------------------------------
# trigger-test-alert
# ---------------------------------------------------------------------------


def test_trigger_test_alert_success() -> None:
    """Triggering a test alert should succeed with default values."""
    with _patch_app():
        result = _runner.invoke(mon_module.app, ["trigger-test-alert"])

    assert result.exit_code == 0, result.output
    assert "Test alert created with ID" in result.output


def test_trigger_test_alert_custom_values() -> None:
    """Custom severity, title, description should be reflected in output."""
    with _patch_app():
        result = _runner.invoke(
            mon_module.app,
            [
                "trigger-test-alert",
                "--severity",
                "critical",
                "--title",
                "My Custom Alert",
                "--desc",
                "Custom description",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "My Custom Alert" in result.output


def test_trigger_test_alert_invalid_severity() -> None:
    """Invalid severity should exit with code 1."""
    with _patch_app():
        result = _runner.invoke(
            mon_module.app,
            ["trigger-test-alert", "--severity", "invalid-severity"],
        )

    assert result.exit_code == 1, result.output
    assert "Failed to create test alert" in result.output


# ---------------------------------------------------------------------------
# add_monitoring_commands
# ---------------------------------------------------------------------------


def test_add_monitoring_commands_adds_typer() -> None:
    """add_monitoring_commands should add our app to a parent typer app."""
    parent = MagicMock()
    mon_module.add_monitoring_commands(parent)
    parent.add_typer.assert_called_once()
    call_args = parent.add_typer.call_args
    assert call_args[1]["name"] == "monitor"


# ---------------------------------------------------------------------------
# App object sanity
# ---------------------------------------------------------------------------


def test_app_is_typer_instance() -> None:
    """mon_module.app should be a typer.Typer instance."""
    from typer import Typer

    assert isinstance(mon_module.app, Typer)
