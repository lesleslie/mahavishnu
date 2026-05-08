"""Mahavishnu Dashboard — read-only Textual TUI for ecosystem diagnostics.

Five tabs:
- Overview: System health, active workflows, recent alerts
- Sweep: Workflow history, success/fail rates
- Routing: Adapter health, resolution decisions
- Alerts: Active alerts, severity filter
- Reviews: Pending skill drafts from the governance system

All screens are read-only. Auto-refreshes every 30 seconds (press R for immediate refresh).
Launch with: mahavishnu dashboard
"""

from __future__ import annotations

import contextlib
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

from mahavishnu.tui.command_palette import MahavishnuCommandProvider

if TYPE_CHECKING:
    from mahavishnu.core.ecosystem_status import EcosystemStatusReport

__all__ = ["MahavishnuDashboard", "DashboardApp"]

_REFRESH_INTERVAL = 30  # seconds


# ---------------------------------------------------------------------------
# Data-fetching helpers (read-only, no side effects)
# ---------------------------------------------------------------------------


async def _get_report() -> EcosystemStatusReport | None:
    try:
        from mahavishnu.core.config import MahavishnuSettings
        from mahavishnu.core.ecosystem_status import EcosystemStatusService

        settings = MahavishnuSettings()
        service_configs: dict[str, dict[str, Any]] = {}
        for name, url in {
            "session-buddy": settings.session_buddy_url,
            "akosha": settings.akosha_url,
        }.items():
            if url:
                service_configs[name] = {"url": url, "required": False, "timeout_s": 3}

        try:
            oneiric = getattr(settings, "oneiric_mcp", None)
            if oneiric:
                dhara_url = getattr(oneiric, "url", None) or getattr(oneiric, "base_url", None)
                if dhara_url:
                    service_configs["dhara"] = {"url": dhara_url, "required": False, "timeout_s": 3}
        except Exception:
            pass

        return await EcosystemStatusService(service_configs=service_configs or None).generate_report()
    except Exception:
        return None


async def fetch_system_overview() -> dict[str, Any]:
    report = await _get_report()
    if report is None:
        return {"status": "unknown", "active_workflows": 0, "total_adapters": 0,
                "healthy_adapters": 0, "recent_alerts": 0}
    adapters = report.adapters or {}
    workflows = report.workflows
    alerts = report.alerts
    return {
        "status": report.status.value,
        "active_workflows": workflows.active_count if workflows else 0,
        "total_adapters": len(adapters),
        "healthy_adapters": sum(1 for a in adapters.values() if a.status.value == "ok"),
        "recent_alerts": alerts.total_active if alerts else 0,
        "generated_at": report.generated_at.isoformat() if report.generated_at else None,
    }


async def fetch_sweep_history() -> list[dict[str, Any]]:
    report = await _get_report()
    if report is None:
        return []
    w = report.workflows
    if w and (w.active_count or w.failed_count or w.recent_count):
        return [{"status": "active", "active": w.active_count,
                 "failed": w.failed_count, "recent": w.recent_count}]
    return []


async def fetch_routing_stats() -> dict[str, Any]:
    report = await _get_report()
    if report is None:
        return {"adapters": [], "total_decisions": 0, "cache_hit_rate": 0.0}
    adapters = report.adapters or {}
    adapter_list = [
        {"name": name, "status": adp.status.value,
         "capabilities": adp.capabilities or {},
         "preference_score": adp.preference_score}
        for name, adp in adapters.items()
    ]
    healthy = sum(1 for a in adapter_list if a["status"] == "ok")
    return {
        "adapters": adapter_list,
        "total_decisions": len(adapter_list),
        "cache_hit_rate": healthy / len(adapter_list) if adapter_list else 0.0,
    }


async def fetch_active_alerts() -> list[dict[str, Any]]:
    report = await _get_report()
    if report is None:
        return []
    alerts = report.alerts
    if alerts and alerts.top_alerts:
        return [
            {"id": str(i), "severity": a.severity,
             "title": f"{a.source}: {a.message}",
             "description": a.message,
             "time": a.created_at.isoformat() if a.created_at else ""}
            for i, a in enumerate(alerts.top_alerts)
        ]
    return []


async def fetch_skill_drafts() -> list[dict[str, Any]]:
    """Fetch skill drafts by scanning ~/.claude/skills/ for SKILL.md files."""
    from pathlib import Path
    import re

    skills_root = Path.home() / ".claude" / "skills"
    if not skills_root.exists():
        return []

    drafts: list[dict[str, Any]] = []
    for skill_dir in sorted(skills_root.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            text = skill_file.read_text(encoding="utf-8")
            name = skill_dir.name
            description = ""
            m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
            if m:
                description = m.group(1).strip()
            mtime = datetime.fromtimestamp(skill_file.stat().st_mtime)
            drafts.append({
                "skill_id": name,
                "name": name,
                "version": "1.0",
                "state": "active",
                "proposed_by": "ecosystem",
                "created_at": mtime,
                "description": description,
            })
        except Exception:
            continue
    return drafts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEVERITY_COLORS = {"critical": "red", "error": "red", "warning": "yellow",
                    "info": "cyan", "debug": "dim"}
_STATE_COLORS = {"draft": "yellow", "review": "cyan", "active": "green", "deprecated": "red"}


def _severity_markup(severity: str) -> str:
    color = _SEVERITY_COLORS.get(severity.lower(), "white")
    return f"[bold {color}]{severity.upper()}[/]"


def _state_markup(state: Any) -> str:
    state_str = str(state).lower()
    color = _STATE_COLORS.get(state_str, "white")
    return f"[bold {color}]{state_str.upper()}[/]"


def _status_color(status: str) -> str:
    return {"ok": "green", "degraded": "yellow", "unknown": "dim"}.get(status.lower(), "red")


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


class OverviewScreen(VerticalScroll):
    """System health, active workflows, recent alerts."""

    _status: reactive[str] = reactive("⏳ Loading…")

    def compose(self) -> ComposeResult:
        yield Label("System Overview", classes="screen-title")
        yield Static(id="overview-status", classes="overview-block")
        yield Label("", id="overview-timestamp", classes="dim-label")

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        data = await fetch_system_overview()
        status = data.get("status", "unknown")
        color = _status_color(status)
        adapters = f"{data.get('healthy_adapters', 0)}/{data.get('total_adapters', 0)}"
        workflows = data.get("active_workflows", 0)
        alerts = data.get("recent_alerts", 0)
        alert_color = "red" if alerts > 0 else "green"

        self._status = (
            f"[bold {color}]● {status.upper()}[/]   "
            f"[bold]Adapters[/] {adapters}   "
            f"[bold]Workflows[/] {workflows} active   "
            f"[bold {alert_color}]Alerts[/] {alerts}"
        )
        ts = data.get("generated_at")
        if ts:
            self.query_one("#overview-timestamp", Label).update(f"Last updated: {ts}")

    def watch__status(self, new: str) -> None:
        self.query_one("#overview-status", Static).update(new)

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class SweepScreen(VerticalScroll):
    """Workflow sweep history."""

    def compose(self) -> ComposeResult:
        yield Label("Sweep History", classes="screen-title")
        table = DataTable(id="sweep-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Status", "Active", "Failed", "Recent")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        data = await fetch_sweep_history()
        table = self.query_one("#sweep-table", DataTable)
        table.clear()
        if data:
            for entry in data:
                failed = entry.get("failed", 0)
                fail_str = f"[red]{failed}[/]" if failed else str(failed)
                table.add_row(entry.get("status", "-"), str(entry.get("active", 0)),
                              fail_str, str(entry.get("recent", 0)))
        else:
            table.add_row("[dim]No sweeps yet[/]", "-", "-", "-")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class RoutingScreen(VerticalScroll):
    """Adapter health and routing decisions."""

    def compose(self) -> ComposeResult:
        yield Label("Adapter Routing", classes="screen-title")
        yield Static(id="routing-summary", classes="overview-block")
        table = DataTable(id="routing-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Adapter", "Status", "Score", "Capabilities")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        data = await fetch_routing_stats()
        adapters = data.get("adapters", [])
        healthy = sum(1 for a in adapters if a["status"] == "ok")
        total = len(adapters)
        hit_rate = data.get("cache_hit_rate", 0.0)
        color = _status_color("ok" if healthy == total and total > 0 else "degraded" if healthy else "error")
        self.query_one("#routing-summary", Static).update(
            f"[bold {color}]Healthy:[/] {healthy}/{total}   "
            f"[bold]Decisions:[/] {data.get('total_decisions', 0)}   "
            f"[bold]Adapter health:[/] {hit_rate:.0%}"
        )
        table = self.query_one("#routing-table", DataTable)
        table.clear()
        if adapters:
            for a in adapters:
                status = a["status"]
                status_str = f"[bold {_status_color(status)}]{status}[/]"
                caps = ", ".join(a.get("capabilities", {}).keys()) or "-"
                score = a.get("preference_score")
                table.add_row(a["name"], status_str,
                              str(round(score, 2)) if score is not None else "-", caps)
        else:
            table.add_row("[dim]No adapters registered[/]", "-", "-", "-")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class AlertsScreen(VerticalScroll):
    """Active alerts with severity."""

    def compose(self) -> ComposeResult:
        yield Label("Active Alerts", classes="screen-title")
        yield Static(id="alerts-count", classes="overview-block")
        table = DataTable(id="alerts-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("Severity", "Source / Title", "Time")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        alerts = await fetch_active_alerts()
        count_widget = self.query_one("#alerts-count", Static)
        total = len(alerts)
        color = "red" if total > 0 else "green"
        count_widget.update(f"[bold {color}]{total} active alert{'s' if total != 1 else ''}[/]")
        table = self.query_one("#alerts-table", DataTable)
        table.clear()
        if alerts:
            for a in alerts:
                table.add_row(_severity_markup(a.get("severity", "info")),
                              a.get("title", ""), a.get("time", ""))
        else:
            table.add_row("[dim green]No active alerts[/]", "", "")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class ReviewsScreen(VerticalScroll):
    """Skill governance: pending drafts and reviews."""

    def compose(self) -> ComposeResult:
        yield Label("Skill Drafts", classes="screen-title")
        yield Static(id="reviews-count", classes="overview-block")
        table = DataTable(id="reviews-table", cursor_type="row", zebra_stripes=True)
        table.add_columns("ID", "Name", "Version", "State", "Proposed By", "Created")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        drafts = await fetch_skill_drafts()
        count = self.query_one("#reviews-count", Static)
        total = len(drafts)
        review_count = sum(1 for d in drafts if str(d.get("state", "")).lower() == "review")
        color = "cyan" if review_count > 0 else "green"
        count.update(
            f"[bold {color}]{total} draft{'s' if total != 1 else ''}[/]"
            + (f"   [bold cyan]{review_count} pending review[/]" if review_count else "")
        )
        table = self.query_one("#reviews-table", DataTable)
        table.clear()
        if drafts:
            for d in drafts:
                created = d.get("created_at")
                created_str = (created.strftime("%Y-%m-%d %H:%M")
                               if isinstance(created, datetime) else str(created) if created else "-")
                table.add_row(d.get("skill_id", "-"), d.get("name", "-"), d.get("version", "-"),
                              _state_markup(d.get("state", "draft")),
                              d.get("proposed_by", "-"), created_str)
        else:
            table.add_row("-", "[dim]No skill drafts found[/]", "-", "-", "-", "-")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


# ---------------------------------------------------------------------------
# Dashboard App
# ---------------------------------------------------------------------------


class DashboardApp(App):
    """Mahavishnu ecosystem dashboard — read-only Textual TUI.

    Usage:
        mahavishnu dashboard
    """

    TITLE = "Mahavishnu Dashboard"
    SUB_TITLE = f"Auto-refresh every {_REFRESH_INTERVAL}s · Press R to refresh now · Q to quit"

    COMMANDS = {MahavishnuCommandProvider}

    CSS = """
    Screen {
        background: $surface;
    }

    .screen-title {
        text-style: bold;
        color: $accent;
        padding: 1 0 0 0;
        margin-bottom: 1;
    }

    .overview-block {
        background: $panel;
        padding: 1 2;
        border: tall $primary;
        margin-bottom: 1;
    }

    .dim-label {
        color: $text-muted;
        margin-bottom: 1;
    }

    DataTable {
        height: auto;
        max-height: 30;
        margin-bottom: 1;
    }

    DataTable > .datatable--header {
        text-style: bold;
        background: $primary-darken-2;
    }

    TabbedContent TabPane {
        padding: 0 1;
    }

    Footer {
        background: $primary-darken-3;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("r", "refresh_all", "Refresh"),
        Binding("ctrl+k", "command_palette", "Commands"),
        Binding("1", "switch_tab('overview')", "Overview"),
        Binding("2", "switch_tab('sweep')", "Sweep"),
        Binding("3", "switch_tab('routing')", "Routing"),
        Binding("4", "switch_tab('alerts')", "Alerts"),
        Binding("5", "switch_tab('reviews')", "Reviews"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="overview"):
            with TabPane("1 Overview", id="overview"):
                yield OverviewScreen()
            with TabPane("2 Sweep", id="sweep"):
                yield SweepScreen()
            with TabPane("3 Routing", id="routing"):
                yield RoutingScreen()
            with TabPane("4 Alerts", id="alerts"):
                yield AlertsScreen()
            with TabPane("5 Reviews", id="reviews"):
                yield ReviewsScreen()
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self.action_refresh_all)

    def action_switch_tab(self, tab_id: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one(TabbedContent).active = tab_id

    def action_refresh_all(self) -> None:
        """Refresh all screens from live data."""
        for screen_cls in (OverviewScreen, SweepScreen, RoutingScreen, AlertsScreen, ReviewsScreen):
            for widget in self.query(screen_cls):
                widget.refresh_data()


# Alias for convenience
MahavishnuDashboard = DashboardApp
