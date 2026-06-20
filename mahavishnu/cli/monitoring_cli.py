"""Monitoring CLI commands for Mahavishnu."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

from ..core.app import MahavishnuApp
from ..tui import TUI_AVAILABLE, FallbackRichFormatter, get_console

app = typer.Typer(help="Monitoring and alerting commands for Mahavishnu")


@app.command("get-dashboard")
def get_dashboard(
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
    output_file: Path | None = typer.Option(
        None, "--output", "-o", help="Output file for dashboard data (JSON)"
    ),
):
    """
    Get the monitoring dashboard data.

    Shows system metrics, workflow stats, and alert information.
    """
    typer.echo("📊 Getting monitoring dashboard...")

    # Initialize app with config if provided
    maha_app = MahavishnuApp()

    # Get dashboard data
    async def _get_dashboard():
        return await maha_app.monitoring_service.get_dashboard_data()

    dashboard_data = asyncio.run(_get_dashboard())

    if output_file:
        with open(output_file, "w") as f:
            json.dump(dashboard_data, f, indent=2)
        typer.echo(f"✅ Dashboard data saved to: {output_file}")
    else:
        console = get_console()
        console.print("\n📈 SYSTEM METRICS:")
        system = dashboard_data["metrics"]["system"]
        console.print(f"   CPU Usage: {system['cpu_percent']}%")
        console.print(f"   Memory Usage: {system['memory_percent']}%")
        console.print(f"   Memory Available: {system['memory_available_gb']} GB")
        console.print(f"   Disk Usage: {system['disk_percent']:.1f}%")
        console.print(f"   Disk Available: {system['disk_available_gb']} GB")
        console.print(f"   Uptime: {system['uptime_seconds']:.2f} seconds")

        console.print("\n🔄 WORKFLOW COUNTS:")
        workflows = dashboard_data["metrics"]["workflows"]
        for status, count in workflows.items():
            console.print(f"   {status}: {count}")

        console.print("\n⚙️  ADAPTER HEALTH:")
        adapters = dashboard_data["metrics"]["adapters"]
        for adapter, health in adapters.items():
            status_icon = "✅" if health == "healthy" else "❌"
            console.print(f"   {adapter}: {status_icon} {health}")

        console.print("\n🚨 ALERT COUNTS:")
        alerts = dashboard_data["metrics"]["alerts"]
        for severity, count in alerts.items():
            console.print(f"   {severity}: {count}")

    raise typer.Exit(code=0)


@app.command("get-alerts")
def get_alerts(
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
    output_file: Path | None = typer.Option(
        None, "--output", "-o", help="Output file for alerts (JSON)"
    ),
):
    """
    Get active alerts.

    Shows all non-acknowledged alerts in the system.
    """
    typer.echo("🚨 Getting active alerts...")

    # Initialize app with config if provided
    maha_app = MahavishnuApp()

    # Get active alerts
    async def _get_alerts():
        return await maha_app.monitoring_service.alert_manager.get_active_alerts()

    alerts = asyncio.run(_get_alerts())

    if output_file:
        alert_data = [
            {
                "id": alert.id,
                "timestamp": alert.timestamp.isoformat(),
                "severity": alert.severity.value,
                "type": alert.type.value,
                "title": alert.title,
                "description": alert.description,
                "details": alert.details,
            }
            for alert in alerts
        ]
        with open(output_file, "w") as f:
            json.dump(alert_data, f, indent=2)
        typer.echo(f"✅ Alerts saved to: {output_file}")
    else:
        if not alerts:
            typer.echo("✅ No active alerts")
        else:
            typer.echo(f"📝 Found {len(alerts)} active alert(s):")
            for alert in alerts:
                severity_icon = (
                    "🔴"
                    if alert.severity.value == "critical"
                    else "🟠"
                    if alert.severity.value == "high"
                    else "🟡"
                    if alert.severity.value == "medium"
                    else "🟢"
                )

                typer.echo(f"   {severity_icon} [{alert.severity.value.upper()}] {alert.title}")
                typer.echo(f"      {alert.description}")
                typer.echo(f"      Time: {alert.timestamp}")
                typer.echo("")

    raise typer.Exit(code=0)


@app.command("acknowledge-alert")
def acknowledge_alert(
    alert_id: str = typer.Argument(..., help="ID of the alert to acknowledge"),
    user: str = typer.Option("system", "--user", "-u", help="User acknowledging the alert"),
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
):
    """
    Acknowledge an alert.

    Marks an alert as acknowledged so it stops appearing as active.
    """
    typer.echo(f"✅ Acknowledging alert: {alert_id}")

    # Initialize app with config if provided
    maha_app = MahavishnuApp()

    # Acknowledge alert
    async def _acknowledge():
        return await maha_app.monitoring_service.acknowledge_alert(alert_id, user)

    success = asyncio.run(_acknowledge())

    if success:
        typer.echo(f"✅ Alert {alert_id} acknowledged by {user}")
        raise typer.Exit(code=0)
    else:
        typer.echo(f"❌ Failed to acknowledge alert {alert_id}")
        raise typer.Exit(code=1)


@app.command("trigger-test-alert")
def trigger_test_alert(
    severity: str = typer.Option(
        "medium", "--severity", "-s", help="Severity level (low, medium, high, critical)"
    ),
    title: str = typer.Option("Test Alert", "--title", "-t", help="Title of the alert"),
    description: str = typer.Option(
        "This is a test alert", "--desc", "-d", help="Description of the alert"
    ),
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
):
    """
    Trigger a test alert.

    Creates a test alert for testing notification systems.
    """
    typer.echo(f"🔔 Triggering test alert: {title}")

    # Initialize app with config if provided
    maha_app = MahavishnuApp()

    # Trigger test alert
    async def _trigger():
        from ..core.monitoring import AlertSeverity, AlertType

        severity_enum = AlertSeverity(severity.lower())
        return await maha_app.monitoring_service.alert_manager.trigger_alert(
            severity=severity_enum,
            alert_type=AlertType.SYSTEM_HEALTH,
            title=title,
            description=description,
            details={"test_alert": True},
        )

    try:
        alert = asyncio.run(_trigger())
        typer.echo(f"✅ Test alert created with ID: {alert.id}")
        raise typer.Exit(code=0)
    except typer.Exit:
        raise  # Propagate typer exits directly
    except Exception as e:
        typer.echo(f"❌ Failed to create test alert: {e}")
        raise typer.Exit(code=1) from None


@app.command(name="watch")
def watch_dashboard(
    refresh: int = typer.Option(5, help="Refresh interval in seconds"),
) -> None:
    """Launch a live Textual monitor dashboard (requires tui extra)."""
    if TUI_AVAILABLE:
        from ..tui.monitor_app import MonitorApp  # noqa: PLC0415

        monitor = MonitorApp()
        monitor.run()
    else:
        console = get_console()
        console.print(
            "[yellow]Textual not installed.[/yellow] "
            "Install: [bold]uv add --optional tui textual[/bold]\n"
            "Falling back to one-shot Rich output...\n"
        )
        _print_rich_dashboard()


def _print_rich_dashboard() -> None:
    """Print a one-shot Rich-formatted system status to the terminal."""
    from ..core.app import MahavishnuApp  # noqa: PLC0415

    formatter = FallbackRichFormatter()

    try:
        app_instance = MahavishnuApp()
        metrics = asyncio.run(app_instance.get_metrics())
    except Exception as e:
        formatter.format_dict({"error": str(e)}, title="Monitor Error")
        return

    formatter.format_dict(
        {
            "workflows_active": metrics.get("workflows_active", 0),
            "workflows_completed": metrics.get("workflows_completed", 0),
            "pools_active": metrics.get("pools_active", 0),
            "workers_running": metrics.get("workers_running", 0),
            "adapter_health": metrics.get("adapter_health", "unknown"),
        },
        title="Mahavishnu System Status",
    )


# Add this command group to the main CLI
def add_monitoring_commands(main_app):
    """Add monitoring commands to the main CLI app."""
    main_app.add_typer(app, name="monitor", help="Monitoring and alerting commands")
