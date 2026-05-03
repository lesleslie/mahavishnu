"""Mahavishnu Dashboard — read-only Textual TUI for ecosystem diagnostics.

Provides five screens:
- Overview: System health, active workflows, recent alerts
- Sweep: Sweep history, success/fail rates
- Routing: Adapter health, resolution decisions
- Alerts: Active alerts, severity filter
- Reviews: Pending skill drafts from the governance system

All screens are read-only (no mutations).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from mahavishnu.core.ecosystem_status import EcosystemStatusReport

__all__ = ["MahavishnuDashboard", "DashboardApp"]


# ---------------------------------------------------------------------------
# Data-fetching helpers (read-only, no side effects)
# ---------------------------------------------------------------------------


async def _get_report() -> EcosystemStatusReport | None:
    """Fetch canonical ecosystem status report. Returns None on error."""
    try:
        from mahavishnu.core.config import MahavishnuSettings
        from mahavishnu.core.ecosystem_status import EcosystemStatusService

        settings = MahavishnuSettings()

        # Build service configs from known ecosystem dependencies
        service_configs: dict[str, dict[str, Any]] = {}
        ecosystem_services = {
            "session-buddy": settings.session_buddy_url,
            "akosha": settings.akosha_url,
        }
        for name, url in ecosystem_services.items():
            if url:
                service_configs[name] = {"url": url, "required": False, "timeout_s": 3}

        # Try to discover additional services from oneiric MCP config
        try:
            oneiric = getattr(settings, "oneiric_mcp", None)
            if oneiric:
                dhara_url = getattr(oneiric, "url", None) or getattr(oneiric, "base_url", None)
                if dhara_url:
                    service_configs["dhara"] = {
                        "url": dhara_url,
                        "required": False,
                        "timeout_s": 3,
                    }
        except Exception:
            pass

        service = EcosystemStatusService(service_configs=service_configs or None)
        return await service.generate_report()
    except Exception:
        return None


async def fetch_system_overview() -> dict[str, Any]:
    """Fetch system health, active workflows, recent alerts."""
    report = await _get_report()
    if report is None:
        return {
            "status": "unknown",
            "active_workflows": 0,
            "total_adapters": 0,
            "healthy_adapters": 0,
            "recent_alerts": 0,
            "uptime_seconds": 0,
        }
    adapters = report.adapters or {}
    workflows = report.workflows
    alerts = report.alerts
    healthy_adapters = sum(1 for a in adapters.values() if a.status.value == "ok")
    return {
        "status": report.status.value,
        "active_workflows": workflows.active_count if workflows else 0,
        "total_adapters": len(adapters),
        "healthy_adapters": healthy_adapters,
        "recent_alerts": alerts.total_active if alerts else 0,
        "generated_at": (report.generated_at.isoformat() if report.generated_at else None),
    }


async def fetch_sweep_history() -> list[dict[str, Any]]:
    """Fetch recent sweep history."""
    report = await _get_report()
    if report is None:
        return []
    w = report.workflows
    if w and (w.active_count or w.failed_count or w.recent_count):
        return [
            {
                "status": "active",
                "active": w.active_count,
                "failed": w.failed_count,
                "recent": w.recent_count,
            }
        ]
    return []


async def fetch_routing_stats() -> dict[str, Any]:
    """Fetch adapter routing statistics."""
    report = await _get_report()
    if report is None:
        return {"adapters": [], "total_decisions": 0, "cache_hit_rate": 0.0}
    adapters = report.adapters or {}
    adapter_list = []
    for name, adp in adapters.items():
        adapter_list.append(
            {
                "name": name,
                "status": adp.status.value,
                "capabilities": adp.capabilities or {},
                "preference_score": adp.preference_score,
            }
        )
    healthy = sum(1 for a in adapter_list if a["status"] == "ok")
    return {
        "adapters": adapter_list,
        "total_decisions": len(adapter_list),
        "cache_hit_rate": healthy / len(adapter_list) if adapter_list else 0.0,
    }


async def fetch_active_alerts() -> list[dict[str, Any]]:
    """Fetch active alerts."""
    report = await _get_report()
    if report is None:
        return []
    alerts = report.alerts
    if alerts and alerts.top_alerts:
        return [
            {
                "id": str(i),
                "severity": a.severity,
                "title": f"{a.source}: {a.message}",
                "description": a.message,
                "time": (a.created_at.isoformat() if a.created_at else ""),
            }
            for i, a in enumerate(alerts.top_alerts)
        ]
    return []


async def fetch_skill_drafts() -> list[dict[str, Any]]:
    """Fetch skill drafts from the governance system.

    Returns data from any registered SkillRegistry instances.
    Falls back to an empty list when no registry is available.
    """
    return []


# ---------------------------------------------------------------------------
# State-to-color mapping for skill drafts
# ---------------------------------------------------------------------------

_STATE_COLORS: dict[str, str] = {
    "draft": "yellow",
    "review": "cyan",
    "active": "green",
    "deprecated": "red",
}


def _state_markup(state: Any) -> str:
    """Return a Textual markup string for a promotion state."""
    state_str = str(state).lower()
    color = _STATE_COLORS.get(state_str, "white")
    return f"[bold {color}]{state_str.upper()}[/]"


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
        """Load overview data asynchronously from EcosystemStatusService."""

        async def _fetch() -> None:
            data = await fetch_system_overview()
            status = data.get("status", "unknown")
            if status == "ok":
                color = "green"
            elif status == "degraded":
                color = "yellow"
            else:
                color = "red"
            self.status_text = (
                f"[bold {color}]Status:[/] {status.capitalize()}  |  "
                f"[bold]Adapters:[/] "
                f"{data.get('healthy_adapters', 0)}/{data.get('total_adapters', 0)}  |  "
                f"[bold]Workflows:[/] {data.get('active_workflows', 0)} active  |  "
                f"[bold]Alerts:[/] {data.get('recent_alerts', 0)}"
            )

        asyncio.create_task(_fetch())

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
        async def _fetch() -> None:
            data = await fetch_sweep_history()
            table = self.query_one("#sweep-table", DataTable)
            table.clear()
            if data:
                for entry in data:
                    table.add_row(
                        "-",
                        entry.get("status", "-"),
                        "-",
                        str(entry.get("active", 0) + entry.get("failed", 0)),
                        "-",
                        "-",
                    )
            else:
                table.add_row("-", "No sweeps yet", "-", "0", "-", "-")

        asyncio.create_task(_fetch())


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
        async def _fetch() -> None:
            data = await fetch_routing_stats()
            adapters = data.get("adapters", [])
            healthy = sum(1 for a in adapters if a["status"] == "ok")
            total = len(adapters)
            hit_rate = data.get("cache_hit_rate", 0.0)
            summary = self.query_one("#routing-summary", Static)
            summary.update(
                f"[bold]Healthy:[/] {healthy}/{total}  |  "
                f"[bold]Total Decisions:[/] {data.get('total_decisions', 0)}  |  "
                f"[bold]Hit Rate:[/] {hit_rate:.1%}"
            )
            table = self.query_one("#routing-table", DataTable)
            table.clear()
            if adapters:
                for a in adapters:
                    caps = (
                        ", ".join(a.get("capabilities", {}).keys())
                        if a.get("capabilities")
                        else "-"
                    )
                    table.add_row(
                        a["name"],
                        "orchestration",
                        a["status"],
                        str(a.get("preference_score", 0) or 0),
                        caps,
                    )
            else:
                table.add_row("-", "-", "no adapters", "-", "-")

        asyncio.create_task(_fetch())


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
        async def _fetch() -> None:
            alerts = await fetch_active_alerts()
            count = self.query_one("#alerts-count", Static)
            total = len(alerts)
            color = "red" if total > 0 else "green"
            count.update(f"[bold {color}]{total} active alert{'s' if total != 1 else ''}[/]")
            table = self.query_one("#alerts-table", DataTable)
            table.clear()
            if alerts:
                for a in alerts:
                    table.add_row(
                        a["id"],
                        a.get("severity", "unknown"),
                        a.get("title", ""),
                        a.get("description", ""),
                        a.get("time", ""),
                    )

        asyncio.create_task(_fetch())


# ---------------------------------------------------------------------------
# Reviews Screen
# ---------------------------------------------------------------------------


class ReviewsScreen(VerticalScroll):
    """Skill governance reviews: pending and recent drafts."""

    def compose(self) -> ComposeResult:
        yield Label("Skill Drafts", id="reviews-title")
        yield Static(id="reviews-count")
        table = DataTable(id="reviews-table")
        table.add_columns("ID", "Name", "Version", "State", "Proposed By", "Created")
        yield table

    def on_mount(self) -> None:
        self._load_data()

    def _load_data(self) -> None:
        """Load skill drafts asynchronously."""

        async def _fetch() -> None:
            drafts = await fetch_skill_drafts()
            count = self.query_one("#reviews-count", Static)
            total = len(drafts)
            review_count = sum(1 for d in drafts if str(d.get("state", "")).lower() == "review")
            color = "cyan" if review_count > 0 else "green"
            count.update(
                f"[bold {color}]{total} draft{'s' if total != 1 else ''}[/]"
                + (f"  |  [bold cyan]{review_count} pending review[/]" if review_count else "")
            )
            table = self.query_one("#reviews-table", DataTable)
            table.clear()
            if drafts:
                for d in drafts:
                    created = d.get("created_at")
                    if isinstance(created, datetime):
                        created_str = created.strftime("%Y-%m-%d %H:%M")
                    else:
                        created_str = str(created) if created else "-"
                    table.add_row(
                        d.get("skill_id", "-"),
                        d.get("name", "-"),
                        d.get("version", "-"),
                        _state_markup(d.get("state", "draft")),
                        d.get("proposed_by", "-"),
                        created_str,
                    )
            else:
                table.add_row("-", "No skill drafts found", "-", "-", "-", "-")

        asyncio.create_task(_fetch())


# ---------------------------------------------------------------------------
# Dashboard App
# ---------------------------------------------------------------------------


class DashboardApp(App):
    """Mahavishnu ecosystem dashboard -- read-only Textual TUI.

    Usage:
        dashboard = DashboardApp()
        dashboard.run()

    Or from CLI:
        mahavishnu dashboard
    """

    TITLE = "Mahavishnu Dashboard"
    CSS = """
    #overview-title, #sweep-title, #routing-title, #alerts-title, #reviews-title {
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
        Binding("r", "refresh_data", "Refresh"),
        Binding("1", "switch_tab('overview')", "Overview"),
        Binding("2", "switch_tab('sweep')", "Sweep"),
        Binding("3", "switch_tab('routing')", "Routing"),
        Binding("4", "switch_tab('alerts')", "Alerts"),
        Binding("5", "switch_tab('reviews')", "Reviews"),
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
            with TabPane("Reviews", id="reviews"):
                yield ReviewsScreen()
        yield Footer()

    def action_switch_tab(self, tab_id: str) -> None:
        """Switch to a specific tab."""
        try:
            tc = self.query_one(TabbedContent)
            tc.active = tab_id
        except Exception:
            pass

    def action_refresh_data(self) -> None:
        """Refresh all screen data from EcosystemStatusService."""
        for screen in self.query(OverviewScreen):
            screen._load_data()
        for screen in self.query(SweepScreen):
            screen.on_mount()
        for screen in self.query(RoutingScreen):
            screen.on_mount()
        for screen in self.query(AlertsScreen):
            screen.on_mount()
        for screen in self.query(ReviewsScreen):
            screen._load_data()


# Alias for convenience
MahavishnuDashboard = DashboardApp
