#!/usr/bin/env python3
"""Extended coverage tests for ``mahavishnu.cli.monitoring_cli``.

Target: lift coverage of ``mahavishnu/cli/monitoring_cli.py`` from ~18% to
70%+ by exercising the actual command bodies (the existing
``test_monitoring_cli.py`` only checks ``--help`` registration surface).

Strategy
--------
The CLI commands instantiate ``MahavishnuApp()`` then call async helpers
on ``self.monitoring_service.alert_manager`` / ``self.monitoring_service``.
``MahavishnuApp`` declares ``monitoring_service: Any`` (see
``mahavishnu/core/app.py``), so we can stub it freely with a small object
exposing just the methods we need. We monkeypatch the ``MahavishnuApp``
symbol bound into ``mahavishnu.cli.monitoring_cli`` (the production file
does ``from ..core.app import MahavishnuApp`` at module scope, so the
binding lives in the wrapper module's namespace and is patchable there).

For ``watch`` we monkeypatch ``mahavishnu.cli.monitoring_cli.TUI_AVAILABLE``
to ``False`` so the fallback ``_print_rich_dashboard`` path is exercised
without spinning up a Textual app inside CliRunner.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import typer
from typer.testing import CliRunner

from mahavishnu.cli.monitoring_cli import add_monitoring_commands
from mahavishnu.core.monitoring import Alert, AlertSeverity, AlertType

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_RUNNER = CliRunner()


class _StubMonitoringService:
    """Async stub standing in for ``MonitoringService``.

    Only the methods the CLI actually invokes are wired up; everything else
    raises ``AttributeError`` so we notice if a command starts reaching for
    a new dependency.
    """

    def __init__(self) -> None:
        self.get_dashboard_data = AsyncMock(
            return_value={
                "metrics": {
                    "system": {
                        "cpu_percent": 12.3,
                        "memory_percent": 45.6,
                        "memory_available_gb": 8.0,
                        "disk_percent": 50.0,
                        "disk_available_gb": 100.0,
                        "uptime_seconds": 1234.5,
                    },
                    "workflows": {"running": 2, "completed": 7},
                    "adapters": {"prefect": "healthy", "llamaindex": "degraded"},
                    "alerts": {"critical": 0, "high": 1, "medium": 2},
                },
            },
        )
        self.acknowledge_alert = AsyncMock(return_value=True)
        # Nested alert_manager.get_active_alerts() + alert_manager.trigger_alert(...)
        self.alert_manager = MagicMock()
        self.alert_manager.get_active_alerts = AsyncMock(return_value=[])
        self.alert_manager.trigger_alert = AsyncMock(
            return_value=Alert(
                id="alert_test_999",
                timestamp=datetime(2026, 9, 5, 12, 0, 0),
                severity=AlertSeverity.MEDIUM,
                type=AlertType.SYSTEM_HEALTH,
                title="Test Alert",
                description="hello",
            ),
        )


class _StubApp:
    """Stand-in for ``MahavishnuApp`` (only the attrs the CLI dereferences)."""

    def __init__(self, monitoring: _StubMonitoringService | None = None) -> None:
        self.monitoring_service = monitoring or _StubMonitoringService()
        # Used by ``_print_rich_dashboard`` (watch fallback) -> ``app_instance.get_metrics()``
        self.get_metrics = AsyncMock(
            return_value={
                "workflows_active": 3,
                "workflows_completed": 11,
                "pools_active": 1,
                "workers_running": 4,
                "adapter_health": "healthy",
            },
        )


@pytest.fixture
def stub_app(monkeypatch: pytest.MonkeyPatch) -> _StubApp:
    """Patch ``MahavishnuApp`` and ``TUI_AVAILABLE`` for the duration of one test.

    ``MahavishnuApp`` is referenced in two ways inside ``monitoring_cli``:

    - The get-dashboard / get-alerts / acknowledge-alert / trigger-test-alert
      commands bind it via the module-top ``from ..core.app import ...``,
      so the symbol lives on ``mahavishnu.cli.monitoring_cli``.
    - The ``_print_rich_dashboard`` helper called from ``watch`` does an
      *inline* ``from ..core.app import MahavishnuApp`` inside its body;
      that re-reads the class from the source module at call time
      (the wrapper module never re-exports the symbol, so patching the
      wrapper would raise ``AttributeError`` there). See
      ``monkeypatch-inline-import-target.md`` for the same pattern.

    We patch both call sites so every CLI command path uses the stub.
    """
    app_stub = _StubApp()

    def _factory() -> _StubApp:
        return app_stub

    # Module-top binding (used by get-dashboard / get-alerts / acknowledge-alert
    # / trigger-test-alert).
    monkeypatch.setattr(
        "mahavishnu.cli.monitoring_cli.MahavishnuApp", _factory
    )
    # Inline-import binding (used by ``_print_rich_dashboard`` from ``watch``).
    monkeypatch.setattr("mahavishnu.core.app.MahavishnuApp", _factory)

    # Force the watch-command fallback branch (textual is installed in this venv
    # so TUI_AVAILABLE is True otherwise — the Textual app would not run under CliRunner).
    monkeypatch.setattr("mahavishnu.cli.monitoring_cli.TUI_AVAILABLE", False)
    return app_stub


def _build_app() -> typer.Typer:
    parent = typer.Typer()
    add_monitoring_commands(parent)
    return parent


# ---------------------------------------------------------------------------
# get-dashboard
# ---------------------------------------------------------------------------


class TestGetDashboard:
    """``monitor get-dashboard`` with mocked ``monitoring_service``."""

    def test_prints_dashboard_to_stdout(self, stub_app: _StubApp) -> None:
        """Default invocation pretty-prints system / workflow / adapter / alert panels."""
        app = _build_app()
        result = _RUNNER.invoke(app, ["monitor", "get-dashboard"])
        assert result.exit_code == 0, result.output

        out = result.output
        # Each panel header should have been emitted.
        assert "SYSTEM METRICS" in out
        assert "WORKFLOW COUNTS" in out
        assert "ADAPTER HEALTH" in out
        assert "ALERT COUNTS" in out
        # Specific values from the stub.
        assert "CPU Usage: 12.3%" in out
        assert "running: 2" in out
        assert "prefect:" in out and "healthy" in out
        assert "high: 1" in out

    def test_writes_dashboard_to_output_file(
        self, stub_app: _StubApp, tmp_path: Path
    ) -> None:
        """``--output FILE`` dumps the dashboard payload as JSON."""
        out_file = tmp_path / "dash.json"
        app = _build_app()
        result = _RUNNER.invoke(
            app,
            ["monitor", "get-dashboard", "--output", str(out_file)],
        )
        assert result.exit_code == 0, result.output

        payload = json.loads(out_file.read_text())
        assert payload["metrics"]["system"]["cpu_percent"] == 12.3
        assert payload["metrics"]["adapters"]["prefect"] == "healthy"

        # Stdout message confirms the path written to. Rich console may
        # wrap the absolute path across lines, so we check for the basename
        # rather than the full string.
        assert out_file.name in result.output
        assert "Dashboard data saved to" in result.output


# ---------------------------------------------------------------------------
# get-alerts
# ---------------------------------------------------------------------------


def _make_alert(
    sev: AlertSeverity,
    title: str,
    desc: str = "desc",
    ts: datetime | None = None,
) -> Alert:
    return Alert(
        id=f"alert_{title}",
        timestamp=ts or datetime(2026, 9, 5, 10, 0, 0),
        severity=sev,
        type=AlertType.SYSTEM_HEALTH,
        title=title,
        description=desc,
    )


class TestGetAlerts:
    """``monitor get-alerts`` — empty branch, populated branch, and JSON branch."""

    def test_no_alerts_prints_confirmation(self, stub_app: _StubApp) -> None:
        stub_app.monitoring_service.alert_manager.get_active_alerts.return_value = []
        app = _build_app()
        result = _RUNNER.invoke(app, ["monitor", "get-alerts"])
        assert result.exit_code == 0, result.output
        assert "No active alerts" in result.output

    def test_lists_populated_alerts_with_severity_icons(self, stub_app: _StubApp) -> None:
        stub_app.monitoring_service.alert_manager.get_active_alerts.return_value = [
            _make_alert(AlertSeverity.CRITICAL, "Disk Full", "No space left"),
            _make_alert(AlertSeverity.HIGH, "API Latency", "p99 > 2s"),
            _make_alert(AlertSeverity.MEDIUM, "Queue Backed Up", "DLQ growing"),
            _make_alert(AlertSeverity.LOW, "Job Stalled", "no progress"),
        ]
        app = _build_app()
        result = _RUNNER.invoke(app, ["monitor", "get-alerts"])
        assert result.exit_code == 0, result.output

        out = result.output
        # Header + count line.
        assert "Found 4 active alert(s)" in out
        # Each severity picks a different icon.
        assert "[CRITICAL]" in out and "Disk Full" in out
        assert "[HIGH]" in out and "API Latency" in out
        assert "[MEDIUM]" in out and "Queue Backed Up" in out
        # Default branch in the ternary (everything not CRITICAL/HIGH/MEDIUM → 🟢).
        assert "[LOW]" in out and "Job Stalled" in out

    def test_output_flag_dumps_alerts_as_json(
        self, stub_app: _StubApp, tmp_path: Path
    ) -> None:
        stub_app.monitoring_service.alert_manager.get_active_alerts.return_value = [
            _make_alert(AlertSeverity.CRITICAL, "Disk Full"),
        ]
        out_file = tmp_path / "alerts.json"
        app = _build_app()
        result = _RUNNER.invoke(
            app, ["monitor", "get-alerts", "--output", str(out_file)]
        )
        assert result.exit_code == 0, result.output

        payload = json.loads(out_file.read_text())
        assert isinstance(payload, list) and len(payload) == 1
        row = payload[0]
        assert row["title"] == "Disk Full"
        assert row["severity"] == "critical"
        assert row["type"] == "system_health"

        assert "Alerts saved to" in result.output


# ---------------------------------------------------------------------------
# acknowledge-alert
# ---------------------------------------------------------------------------


class TestAcknowledgeAlert:
    """Both code paths in ``acknowledge_alert``."""

    def test_acknowledge_success_exits_zero(self, stub_app: _StubApp) -> None:
        stub_app.monitoring_service.acknowledge_alert.return_value = True
        app = _build_app()
        result = _RUNNER.invoke(app, ["monitor", "acknowledge-alert", "alert-42"])
        assert result.exit_code == 0, result.output

        out = result.output
        assert "Acknowledging alert: alert-42" in out
        assert "Alert alert-42 acknowledged by system" in out
        # Default user is "system" because we did not pass --user.
        stub_app.monitoring_service.acknowledge_alert.assert_awaited_once_with(
            "alert-42", "system"
        )

    def test_acknowledge_success_with_explicit_user(self, stub_app: _StubApp) -> None:
        stub_app.monitoring_service.acknowledge_alert.return_value = True
        app = _build_app()
        result = _RUNNER.invoke(
            app,
            [
                "monitor",
                "acknowledge-alert",
                "alert-99",
                "--user",
                "ops-alice",
            ],
        )
        assert result.exit_code == 0, result.output
        stub_app.monitoring_service.acknowledge_alert.assert_awaited_once_with(
            "alert-99", "ops-alice"
        )

    def test_acknowledge_failure_exits_one(self, stub_app: _StubApp) -> None:
        stub_app.monitoring_service.acknowledge_alert.return_value = False
        app = _build_app()
        result = _RUNNER.invoke(app, ["monitor", "acknowledge-alert", "alert-bogus"])
        # The ``raise typer.Exit(code=1)`` branch.
        assert result.exit_code == 1
        assert "Failed to acknowledge alert alert-bogus" in result.output


# ---------------------------------------------------------------------------
# trigger-test-alert
# ---------------------------------------------------------------------------


class TestTriggerTestAlert:
    """``monitor trigger-test-alert`` — both success and exception paths."""

    def test_default_arguments_trigger_medium_alert(self, stub_app: _StubApp) -> None:
        app = _build_app()
        result = _RUNNER.invoke(app, ["monitor", "trigger-test-alert"])
        assert result.exit_code == 0, result.output

        out = result.output
        assert "Triggering test alert: Test Alert" in out
        assert "Test alert created with ID: alert_test_999" in out

        stub_app.monitoring_service.alert_manager.trigger_alert.assert_awaited_once()
        call_kwargs: dict[str, Any] = (
            stub_app.monitoring_service.alert_manager.trigger_alert.await_args.kwargs
        )
        assert call_kwargs["severity"] is AlertSeverity.MEDIUM
        assert call_kwargs["alert_type"] is AlertType.SYSTEM_HEALTH
        assert call_kwargs["title"] == "Test Alert"
        assert call_kwargs["description"] == "This is a test alert"
        assert call_kwargs["details"] == {"test_alert": True}

    def test_custom_severity_title_desc_are_forwarded(self, stub_app: _StubApp) -> None:
        app = _build_app()
        result = _RUNNER.invoke(
            app,
            [
                "monitor",
                "trigger-test-alert",
                "--severity",
                "critical",
                "--title",
                "Ping",
                "--desc",
                "Custom body",
            ],
        )
        assert result.exit_code == 0, result.output

        kwargs = (
            stub_app.monitoring_service.alert_manager.trigger_alert.await_args.kwargs
        )
        assert kwargs["severity"] is AlertSeverity.CRITICAL
        assert kwargs["title"] == "Ping"
        assert kwargs["description"] == "Custom body"

    def test_invalid_severity_value_exits_one(self, stub_app: _StubApp) -> None:
        """A bad ``--severity`` raises ValueError from the AlertSeverity() ctor.
        The CLI catches the Exception handler and exits with code 1."""
        app = _build_app()
        result = _RUNNER.invoke(
            app,
            ["monitor", "trigger-test-alert", "--severity", "alligator"],
        )
        assert result.exit_code == 1
        out = result.output
        assert "Failed to create test alert" in out
        # The trigger_alert path was never reached for an invalid severity.
        stub_app.monitoring_service.alert_manager.trigger_alert.assert_not_awaited()


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


class TestWatch:
    """``monitor watch`` exercises the rich-fallback branch
    (``TUI_AVAILABLE=False`` is forced by ``stub_app``)."""

    def test_watch_uses_rich_fallback_and_prints_metrics(self, stub_app: _StubApp) -> None:
        app = _build_app()
        result = _RUNNER.invoke(app, ["monitor", "watch"])
        assert result.exit_code == 0, result.output

        out = result.output
        # ``_print_rich_dashboard`` calls FallbackRichFormatter.format_dict, which
        # prints via Rich's Console. Rich output is buffered + wrapped — assert on
        # the title text (which Rich pads into a panel header) instead of trying
        # to match exact markup.
        assert "Mahavishnu System Status" in out
        # Stub metrics values are visible in the formatted output.
        assert "workflows_active" in out
        assert "adapter_health" in out
        stub_app.get_metrics.assert_awaited_once()

    def test_watch_fallback_handles_metrics_failure(self, stub_app: _StubApp) -> None:
        """If ``get_metrics()`` raises, the fallback prints an error panel
        instead of propagating the exception."""

        async def _boom() -> dict[str, Any]:
            raise RuntimeError("simulated metrics outage")

        stub_app.get_metrics.side_effect = _boom
        app = _build_app()
        result = _RUNNER.invoke(app, ["monitor", "watch"])
        # The exception is swallowed by the ``except Exception`` guard, so the
        # command returns 0 and emits the error panel.
        assert result.exit_code == 0, result.output
        out = result.output
        assert "Monitor Error" in out
        assert "simulated metrics outage" in out
