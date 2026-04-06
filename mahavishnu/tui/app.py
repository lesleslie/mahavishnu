"""Mahavishnu Dashboard — read-only Textual TUI for ecosystem diagnostics.

Provides four screens:
- Overview: System health, active workflows, recent alerts
- Sweep: Sweep history, success/fail rates
- Routing: Adapter health, resolution decisions
- Alerts: Active alerts, severity filter

All screens are read-only (no mutations).
"""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Label,
    Static,
    TabbedContent,
    TabPane,
)

__all__ = ["MahavishnuDashboard", "DashboardApp"]


# ---------------------------------------------------------------------------
# Data-fetching helpers (read-only, no side effects)
# ---------------------------------------------------------------------------


async def fetch_system_overview() -> dict[str, Any]:
    """Fetch system health, active workflows, recent alerts."""
    # Stub: returns placeholder data until wired to live MCP tools
    return {
        "status": "healthy",
        "active_workflows": 0,
        "total_adapters": 3,
        "healthy_adapters": 3,
        "recent_alerts": 0,
        "uptime_seconds": 0,
    }


async def fetch_sweep_history() -> list[dict[str, Any]]:
    """Fetch recent sweep history."""
    return []


async def fetch_routing_stats() -> dict[str, Any]:
    """Fetch adapter routing statistics."""
    return {
        "adapters": [],
        "total_decisions": 0,
        "cache_hit_rate": 0.0,
    }


async def fetch_active_alerts() -> list[dict[str, Any]]:
    """Fetch active alerts."""
    return []


# ---------------------------------------------------------------------------
# Overview Screen
# ---------------------------------------------------------------------------


class OverviewScreen(VerticalScroll):
    """System overview: health, active workflows, recent alerts."""

    status_text: reactive[str] = reactive("Loading...")

    def compose(self) -> ComposeResult:
        yield Label("System Overview", id="overview-title")
        yield Static(id="overview-status")

    def on_mount(self) -> None:
        self._load_data()

    def _load_data(self) -> None:
        """Load overview data (sync for now — stub data)."""
        self.status_text = (
            "[bold green]Status:[/] Healthy  |  "
            "[bold]Adapters:[/] 3 registered  |  "
            "[bold]Workflows:[/] 0 active  |  "
            "[bold]Alerts:[/] 0"
        )

    def watch_status_text(self, new_text: str) -> None:
        status = self.query_one("#overview-status", Static)
        status.update(new_text)


# ---------------------------------------------------------------------------
# Sweep Screen
# ---------------------------------------------------------------------------


class SweepScreen(VerticalScroll):
    """Sweep history: recent sweeps with success/fail rates."""

    def compose(self) -> ComposeResult:
        yield Label("Sweep History", id="sweep-title")
        table = DataTable(id="sweep-table")
        table.add_columns("ID", "Status", "Adapter", "Repos", "Started", "Duration")
        yield table

    def on_mount(self) -> None:
        table = self.query_one("#sweep-table", DataTable)
        # Placeholder row until wired to live data
        table.add_row("—", "No sweeps yet", "—", "0", "—", "—")


# ---------------------------------------------------------------------------
# Routing Screen
# ---------------------------------------------------------------------------


class RoutingScreen(VerticalScroll):
    """Adapter health and routing decisions."""

    def compose(self) -> ComposeResult:
        yield Label("Adapter Routing", id="routing-title")
        yield Static(id="routing-summary")
        table = DataTable(id="routing-table")
        table.add_columns("Adapter", "Domain", "Status", "Priority", "Capabilities")
        yield table

    def on_mount(self) -> None:
        summary = self.query_one("#routing-summary", Static)
        summary.update("[bold]Cache Hit Rate:[/] 0.0%  |  [bold]Total Decisions:[/] 0")

        table = self.query_one("#routing-table", DataTable)
        table.add_row("prefect", "orchestration", "unknown", "0", "—")
        table.add_row("agno", "orchestration", "unknown", "0", "—")
        table.add_row("llamaindex", "orchestration", "unknown", "0", "—")


# ---------------------------------------------------------------------------
# Alerts Screen
# ---------------------------------------------------------------------------


class AlertsScreen(VerticalScroll):
    """Active alerts with severity filter."""

    def compose(self) -> ComposeResult:
        yield Label("Active Alerts", id="alerts-title")
        yield Static(id="alerts-count")
        table = DataTable(id="alerts-table")
        table.add_columns("ID", "Severity", "Title", "Description", "Time")
        yield table

    def on_mount(self) -> None:
        count = self.query_one("#alerts-count", Static)
        count.update("[bold green]No active alerts[/]")
        _table = self.query_one("#alerts-table", DataTable)


# ---------------------------------------------------------------------------
# Dashboard App
# ---------------------------------------------------------------------------


class DashboardApp(App):
    """Mahavishnu ecosystem dashboard — read-only Textual TUI.

    Usage:
        dashboard = DashboardApp()
        dashboard.run()

    Or from CLI:
        mahavishnu dashboard
    """

    TITLE = "Mahavishnu Dashboard"
    CSS = """
    #overview-title, #sweep-title, #routing-title, #alerts-title {
        text-style: bold;
        margin-bottom: 1;
    }
    DataTable {
        height: auto;
        max-height: 20;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "switch_tab('overview')", "Overview"),
        Binding("2", "switch_tab('sweep')", "Sweep"),
        Binding("3", "switch_tab('routing')", "Routing"),
        Binding("4", "switch_tab('alerts')", "Alerts"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="overview"):
            with TabPane("Overview", id="overview"):
                yield OverviewScreen()
            with TabPane("Sweep", id="sweep"):
                yield SweepScreen()
            with TabPane("Routing", id="routing"):
                yield RoutingScreen()
            with TabPane("Alerts", id="alerts"):
                yield AlertsScreen()
        yield Footer()

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch to a specific tab."""
        try:
            tc = self.query_one(TabbedContent)
            tc.active = tab_id
        except Exception:
            pass


# Alias for convenience
MahavishnuDashboard = DashboardApp
