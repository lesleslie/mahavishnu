"""Monitoring CLI commands."""

import asyncio

import typer


def add_monitoring_commands(app: typer.Typer) -> None:
    """Add monitoring commands to the main CLI app."""
    from .core.monitoring import AlertManager, MonitoringDashboard, MonitoringService

    monitor_app = typer.Typer(help="System monitoring and alerting")
    app.add_typer(monitor_app, name="monitor")

    @monitor_app.command("metrics")
    def monitor_metrics() -> None:
        """Show system metrics."""

        async def _metrics():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()
            dashboard = MonitoringDashboard(maha_app)

            metrics = await dashboard.get_system_metrics()

            import json

            typer.echo(json.dumps(metrics, indent=2))

        asyncio.run(_metrics())

    @monitor_app.command("alerts")
    def monitor_alerts(
        limit: int = typer.Option(10, "--limit", "-l", help="Number of alerts to show"),
        active_only: bool = typer.Option(
            True, "--active-only", "-a", help="Show only active alerts"
        ),
    ) -> None:
        """Show recent alerts."""

        async def _alerts():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()
            dashboard = MonitoringDashboard(maha_app)

            # Set up a minimal alert manager for the dashboard
            alert_manager = AlertManager(maha_app)
            dashboard.set_alert_manager(alert_manager)

            alerts = await dashboard.get_recent_alerts(limit=limit)

            if not alerts:
                typer.echo("No alerts found")
                return

            typer.echo(f"Found {len(alerts)} alert(s):")
            for alert in alerts:
                if active_only and alert.get("acknowledged"):
                    continue
                status_symbol = "!" if not alert.get("acknowledged") else "✓"
                typer.echo(f"  {status_symbol} [{alert['severity'].upper()}] {alert['title']}")
                typer.echo(f"    Time: {alert['timestamp']}")
                typer.echo(f"    Type: {alert['type']}")
                typer.echo(f"    Description: {alert['description']}")

        asyncio.run(_alerts())

    @monitor_app.command("dashboard")
    def monitor_dashboard() -> None:
        """Show monitoring dashboard data."""

        async def _dashboard():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()
            service = MonitoringService(maha_app)

            data = await service.get_dashboard_data()

            import json

            typer.echo(json.dumps(data, indent=2))

        asyncio.run(_dashboard())

    @monitor_app.command("acknowledge")
    def monitor_acknowledge(
        alert_id: str = typer.Argument(..., help="Alert ID to acknowledge"),
        user: str = typer.Option("admin", "--user", "-u", help="User acknowledging the alert"),
    ) -> None:
        """Acknowledge an alert."""

        async def _acknowledge():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()
            service = MonitoringService(maha_app)

            success = await service.acknowledge_alert(alert_id, user)

            if success:
                typer.echo(f"✓ Acknowledged alert: {alert_id}")
            else:
                typer.echo(f"✗ Failed to acknowledge alert: {alert_id}", err=True)
                raise typer.Exit(code=1)

        asyncio.run(_acknowledge())

    @monitor_app.command("health")
    def monitor_health() -> None:
        """Check system health."""

        async def _health():
            from .core.app import MahavishnuApp

            maha_app = MahavishnuApp()

            # Check adapter health
            typer.echo("Adapter Health:")
            for name, adapter in maha_app.adapters.items():
                try:
                    health = await adapter.get_health()
                    status = health.get("status", "unknown")
                    status_symbol = "✓" if status == "healthy" else "✗"
                    typer.echo(f"  {status_symbol} {name}: {status}")
                except Exception as e:
                    typer.echo(f"  ✗ {name}: error - {e}")

        asyncio.run(_health())
