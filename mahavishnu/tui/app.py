"""Mahavishnu Dashboard — read-only Textual TUI for ecosystem diagnostics.

Eleven tabs:
- Overview: System health, active workflows, recent alerts
- Sweep: Workflow history, success/fail rates
- Routing: Adapter health, resolution decisions
- Alerts: Active alerts, severity filter
- Reviews: Pending skill drafts from the governance system
- Session: Session-Buddy checkpoint posture and enabled status
- Recovery: Durable restart/recovery checkpoints
- Approvals: Pending durable approvals and their options
- Files: Read-only file previews and diff summaries
- Events: Recent canonical event activity
- Agno: Recent Agno execution summaries
- Trace: Correlation-aware fix trace timeline

All screens are read-only. Auto-refreshes every 30 seconds (press R for immediate refresh).
Launch with: mahavishnu dashboard
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path
import subprocess
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
_COCKPIT_FILES = (
    "README.md",
    "CLAUDE.md",
    "docs/plans/PLAN_INDEX.md",
    "docs/plans/2026-05-10-bodai-control-plane-convergence-plan.md",
)


# ---------------------------------------------------------------------------
# Data-fetching helpers (read-only, no side effects)
# ---------------------------------------------------------------------------


async def _get_report() -> EcosystemStatusReport | None:
    try:
        from mahavishnu.core.config import MahavishnuSettings
        from mahavishnu.core.context import get_app_from_context
        from mahavishnu.core.ecosystem_status import EcosystemStatusService

        settings = MahavishnuSettings()
        service_configs: dict[str, dict[str, Any]] = {}
        for name, url in {
            "session-buddy": settings.session_buddy_url,  # type: ignore[attr-defined]
            "akosha": settings.akosha_url,  # type: ignore[attr-defined]
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

        app = get_app_from_context()
        return await EcosystemStatusService(
            service_configs=service_configs or None,
            recovery_provider=app if app and hasattr(app, "get_recovery_summary") else None,
        ).generate_report()
    except Exception:
        return None


async def fetch_system_overview() -> dict[str, Any]:
    report = await _get_report()
    if report is None:
        return {
            "status": "unknown",
            "active_workflows": 0,
            "total_adapters": 0,
            "healthy_adapters": 0,
            "recent_alerts": 0,
        }
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
    report = await _get_report()
    if report is None:
        return {"adapters": [], "total_decisions": 0, "cache_hit_rate": 0.0}
    adapters = report.adapters or {}
    adapter_list = [
        {
            "name": name,
            "status": adp.status.value,
            "capabilities": adp.capabilities or {},
            "preference_score": adp.preference_score,
        }
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
            {
                "id": str(i),
                "severity": a.severity,
                "title": f"{a.source}: {a.message}",
                "description": a.message,
                "time": a.created_at.isoformat() if a.created_at else "",
            }
            for i, a in enumerate(alerts.top_alerts)
        ]
    return []


async def fetch_recovery_summary() -> dict[str, Any]:
    report = await _get_report()
    if report is None:
        return {
            "recovered_workflows": 0,
            "recovered_approvals": 0,
            "recovered_pools": 0,
            "recovered_routing_decisions": 0,
            "dhara_available": False,
            "last_recovered_at": None,
        }

    recovery = report.recovery
    return {
        "recovered_workflows": recovery.recovered_workflows,
        "recovered_approvals": recovery.recovered_approvals,
        "recovered_pools": recovery.recovered_pools,
        "recovered_routing_decisions": recovery.recovered_routing_decisions,
        "dhara_available": recovery.dhara_available,
        "last_recovered_at": (
            recovery.last_recovered_at.isoformat() if recovery.last_recovered_at else None
        ),
    }


async def fetch_skill_drafts() -> list[dict[str, Any]]:
    """Fetch skill drafts from the canonical registry when available.

    Falls back to scanning ~/.claude/skills/ for SKILL.md files so local
    operator visibility still works when no registry is attached to the app.
    """
    from pathlib import Path
    import re

    from mahavishnu.core.context import get_app_from_context

    app = get_app_from_context()
    skill_registry = getattr(app, "skill_registry", None) if app else None
    if skill_registry is not None and hasattr(skill_registry, "list_active"):
        try:
            records = skill_registry.list_active()
            drafts: list[dict[str, Any]] = []
            for record in records:
                activation = getattr(record, "activation", None)
                review = getattr(record, "review", None)
                created_at = getattr(activation, "activated_at", None) or getattr(
                    review, "reviewed_at", None
                )
                body = getattr(record, "body", "")
                description = body.splitlines()[0].lstrip("# ").strip() if body else ""
                drafts.append(
                    {
                        "skill_id": getattr(record, "skill_id", "-"),
                        "name": getattr(record, "skill_id", "-"),
                        "version": getattr(record, "version", "-"),
                        "state": getattr(record, "state", "active"),
                        "proposed_by": getattr(activation, "activated_by", "ecosystem"),
                        "created_at": created_at or datetime.now(),
                        "description": description,
                    }
                )
            return drafts
        except Exception:
            pass

    skills_root = Path.home() / ".claude" / "skills"
    if not skills_root.exists():
        return []

    drafts = []
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
            drafts.append(
                {
                    "skill_id": name,
                    "name": name,
                    "version": "1.0",
                    "state": "active",
                    "proposed_by": "ecosystem",
                    "created_at": mtime,
                    "description": description,
                }
            )
        except Exception:
            continue
    return drafts


async def fetch_session_summary() -> dict[str, Any]:
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.core.context import get_app_from_context

    app = get_app_from_context()
    if app is not None:
        session_buddy = getattr(app, "session_buddy", None)
        session_config = getattr(app, "config", None)
        session_settings = getattr(session_config, "session", None) if session_config else None
        enabled = bool(
            getattr(session_buddy, "enabled", getattr(session_settings, "enabled", False))
            if session_config
            else getattr(session_buddy, "enabled", False)
        )
        checkpoint_interval = getattr(
            session_buddy,
            "checkpoint_interval",
            getattr(session_settings, "checkpoint_interval", 0),
        )
        session_buddy_url = getattr(session_buddy, "_base_url", None) or getattr(
            getattr(session_config, "pools", None), "session_buddy_url", None
        )
        return {
            "enabled": enabled,
            "checkpoint_interval": checkpoint_interval,
            "session_buddy_url": session_buddy_url,
            "checkpoint_mode": "write-forward" if enabled else "disabled",
        }

    settings = MahavishnuSettings()
    return {
        "enabled": settings.session.enabled,
        "checkpoint_interval": settings.session.checkpoint_interval,
        "session_buddy_url": settings.pools.session_buddy_url,
        "checkpoint_mode": "write-forward" if settings.session.enabled else "disabled",
    }


async def fetch_pending_approvals() -> list[dict[str, Any]]:
    from mahavishnu.core.context import get_app_from_context

    app = get_app_from_context()
    if app is None or not hasattr(app, "list_pending_approvals"):
        return []
    try:
        return list(app.list_pending_approvals())
    except Exception:
        return []


async def fetch_event_activity(limit: int = 25) -> list[dict[str, Any]]:
    from mahavishnu.core.context import get_app_from_context

    app = get_app_from_context()
    if app is None or not hasattr(app, "get_event_activity"):
        return []
    try:
        return list(app.get_event_activity(limit=limit))
    except Exception:
        return []


async def fetch_agno_activity(limit: int = 25) -> list[dict[str, Any]]:
    from mahavishnu.core.context import get_app_from_context

    app = get_app_from_context()
    adapter = getattr(app, "adapters", {}).get("agno") if app is not None else None
    if adapter is None or not hasattr(adapter, "get_execution_log"):
        return []
    try:
        return list(adapter.get_execution_log(limit=limit))
    except Exception:
        return []


async def fetch_correlation_trace(
    correlation_id: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    from mahavishnu.core.context import get_app_from_context

    app = get_app_from_context()
    if (
        app is None
        or not hasattr(app, "get_fix_trace")
        or not hasattr(app, "get_correlation_status")
    ):
        return {
            "correlation_id": correlation_id,
            "trace": [],
            "trace_count": 0,
            "latest_stage": None,
            "latest_message": None,
        }
    try:
        status = app.get_correlation_status(correlation_id=correlation_id)
        trace = list(app.get_fix_trace(correlation_id=correlation_id, limit=limit))
        return {
            "correlation_id": correlation_id,
            "trace": trace,
            **status,
        }
    except Exception:
        return {
            "correlation_id": correlation_id,
            "trace": [],
            "trace_count": 0,
            "latest_stage": None,
            "latest_message": None,
        }


async def forward_approval_request(
    approval_type: str,
    context: dict[str, Any],
    options: list[Any] | None = None,
    timeout_minutes: int | None = None,
) -> dict[str, Any]:
    from mahavishnu.core.context import get_app_from_context

    app = get_app_from_context()
    if app is None or not hasattr(app, "request_approval"):
        return {
            "error": "Approval manager unavailable",
            "approval_type": approval_type,
            "status": "failed",
        }
    try:
        return app.request_approval(  # type: ignore[no-any-return]
            approval_type=approval_type,
            context=context,
            options=options,
            timeout_minutes=timeout_minutes,
        )
    except Exception as exc:
        return {
            "error": str(exc),
            "approval_type": approval_type,
            "status": "failed",
        }


async def forward_approval_response(
    request_id: str,
    approved: bool,
    selected_option: int | None = None,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    from mahavishnu.core.context import get_app_from_context

    app = get_app_from_context()
    if app is None or not hasattr(app, "respond_to_approval"):
        return {
            "error": "Approval manager unavailable",
            "request_id": request_id,
            "approved": approved,
            "status": "failed",
        }
    try:
        return app.respond_to_approval(  # type: ignore[no-any-return]
            request_id=request_id,
            approved=approved,
            selected_option=selected_option,
            rejection_reason=rejection_reason,
        )
    except Exception as exc:
        return {
            "error": str(exc),
            "request_id": request_id,
            "approved": approved,
            "status": "failed",
        }


def _read_cockpit_file(path: Path) -> dict[str, Any]:
    from mahavishnu.core.worktree_validation import WorktreePathValidator

    validator = WorktreePathValidator([Path.cwd()])
    is_valid, error = validator.validate_worktree_path(str(path))
    if not is_valid:
        return {"path": str(path), "exists": False, "error": error or "invalid path"}

    resolved = Path(path).resolve()
    if not resolved.exists() or not resolved.is_file():
        return {"path": str(resolved), "exists": False, "error": "missing file"}

    try:
        content = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = resolved.read_text(encoding="latin-1")

    preview_lines = content.splitlines()[:20]
    return {
        "path": str(resolved.relative_to(Path.cwd())),
        "exists": True,
        "line_count": len(content.splitlines()),
        "preview": "\n".join(preview_lines) if preview_lines else "",
    }


async def fetch_file_views(paths: tuple[str, ...] = _COCKPIT_FILES) -> list[dict[str, Any]]:
    views: list[dict[str, Any]] = []
    for rel_path in paths:
        views.append(_read_cockpit_file(Path.cwd() / rel_path))
    return views


async def fetch_diff_views(paths: tuple[str, ...] = _COCKPIT_FILES) -> list[dict[str, Any]]:
    from mahavishnu.core.worktree_validation import WorktreePathValidator

    repo_root = Path.cwd()
    validator = WorktreePathValidator([repo_root])
    diffs: list[dict[str, Any]] = []
    for rel_path in paths:
        is_valid, error = validator.validate_worktree_path(str(repo_root / rel_path))
        if not is_valid:
            diffs.append({"path": rel_path, "diff": "", "error": error or "invalid path"})
            continue
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--unified=0", "--", rel_path],
            capture_output=True,
            text=True,
            check=False,
        )
        diffs.append(
            {
                "path": rel_path,
                "diff": completed.stdout.strip(),
                "changed": bool(completed.stdout.strip()),
            }
        )
    return diffs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEVERITY_COLORS = {
    "critical": "red",
    "error": "red",
    "warning": "yellow",
    "info": "cyan",
    "debug": "dim",
}
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
        table = DataTable(id="sweep-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
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
                table.add_row(
                    entry.get("status", "-"),
                    str(entry.get("active", 0)),
                    fail_str,
                    str(entry.get("recent", 0)),
                )
        else:
            table.add_row("[dim]No sweeps yet[/]", "-", "-", "-")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class RoutingScreen(VerticalScroll):
    """Adapter health and routing decisions."""

    def compose(self) -> ComposeResult:
        yield Label("Adapter Routing", classes="screen-title")
        yield Static(id="routing-summary", classes="overview-block")
        table = DataTable(id="routing-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
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
        color = _status_color(
            "ok" if healthy == total and total > 0 else "degraded" if healthy else "error"
        )
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
                table.add_row(
                    a["name"], status_str, str(round(score, 2)) if score is not None else "-", caps
                )
        else:
            table.add_row("[dim]No adapters registered[/]", "-", "-", "-")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class AlertsScreen(VerticalScroll):
    """Active alerts with severity."""

    def compose(self) -> ComposeResult:
        yield Label("Active Alerts", classes="screen-title")
        yield Static(id="alerts-count", classes="overview-block")
        table = DataTable(id="alerts-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
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
                table.add_row(
                    _severity_markup(a.get("severity", "info")),
                    a.get("title", ""),
                    a.get("time", ""),
                )
        else:
            table.add_row("[dim green]No active alerts[/]", "", "")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class ReviewsScreen(VerticalScroll):
    """Skill governance: pending drafts and reviews."""

    def compose(self) -> ComposeResult:
        yield Label("Skill Drafts", classes="screen-title")
        yield Static(id="reviews-count", classes="overview-block")
        table = DataTable(id="reviews-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
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
                created_str = (
                    created.strftime("%Y-%m-%d %H:%M")
                    if isinstance(created, datetime)
                    else str(created)
                    if created
                    else "-"
                )
                table.add_row(
                    d.get("skill_id", "-"),
                    d.get("name", "-"),
                    d.get("version", "-"),
                    _state_markup(d.get("state", "draft")),
                    d.get("proposed_by", "-"),
                    created_str,
                )
        else:
            table.add_row("-", "[dim]No skill drafts found[/]", "-", "-", "-", "-")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class SessionScreen(VerticalScroll):
    """Session-Buddy checkpoint posture and session-local configuration."""

    def compose(self) -> ComposeResult:
        yield Label("Session Posture", classes="screen-title")
        yield Static(id="session-summary", classes="overview-block")
        table = DataTable(id="session-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
        table.add_columns("Field", "Value")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        data = await fetch_session_summary()
        color = "green" if data.get("enabled") else "yellow"
        self.query_one("#session-summary", Static).update(
            f"[bold {color}]Session-Buddy {data.get('checkpoint_mode', 'unknown')}[/]   "
            f"[bold]Checkpoint interval:[/] {data.get('checkpoint_interval', 0)}s"
        )
        table = self.query_one("#session-table", DataTable)
        table.clear()
        table.add_row("Enabled", "yes" if data.get("enabled") else "no")
        table.add_row("Session-Buddy URL", str(data.get("session_buddy_url") or "-"))

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class RecoveryScreen(VerticalScroll):
    """Durable recovery summary backed by the canonical ecosystem status surface."""

    def compose(self) -> ComposeResult:
        yield Label("Recovery Summary", classes="screen-title")
        yield Static(id="recovery-summary", classes="overview-block")
        table = DataTable(id="recovery-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
        table.add_columns("Area", "Recovered")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        data = await fetch_recovery_summary()
        dhara_state = "available" if data.get("dhara_available") else "unavailable"
        last_recovered_at = data.get("last_recovered_at") or "-"
        color = "green" if data.get("dhara_available") else "yellow"
        self.query_one("#recovery-summary", Static).update(
            f"[bold {color}]Dhara {dhara_state}[/]   [bold]Last recovery:[/] {last_recovered_at}"
        )
        table = self.query_one("#recovery-table", DataTable)
        table.clear()
        table.add_row("Workflows", str(data.get("recovered_workflows", 0)))
        table.add_row("Approvals", str(data.get("recovered_approvals", 0)))
        table.add_row("Pools", str(data.get("recovered_pools", 0)))
        table.add_row("Routing", str(data.get("recovered_routing_decisions", 0)))

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class ApprovalsScreen(VerticalScroll):
    """Pending approvals backed by the durable approval manager."""

    _approval_ids: list[str] = []

    def compose(self) -> ComposeResult:
        yield Label("Pending Approvals", classes="screen-title")
        yield Static(id="approvals-summary", classes="overview-block")
        yield Static(id="approval-details", classes="overview-block")
        table = DataTable(id="approvals-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
        table.add_columns("ID", "Type", "Expires", "Options")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        approvals = await fetch_pending_approvals()
        self._approval_ids = [str(request.get("id", "")) for request in approvals]
        summary = self.query_one("#approvals-summary", Static)
        pending = sum(1 for request in approvals if not request.get("is_expired"))
        color = "cyan" if pending else "green"
        summary.update(f"[bold {color}]{pending} pending approval{'s' if pending != 1 else ''}[/]")
        table = self.query_one("#approvals-table", DataTable)
        table.clear()
        if approvals:
            for request in approvals:
                options = request.get("options", [])
                expires = str(request.get("expires_at") or "-")
                table.add_row(
                    request.get("id", "-"),
                    request.get("approval_type", "-"),
                    expires[:19].replace("T", " "),
                    str(len(options)),
                )
        else:
            table.add_row("[dim]No pending approvals[/]", "-", "-", "-")
        self._render_selected_approval()

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    def _selected_approval_id(self) -> str | None:
        table = self.query_one("#approvals-table", DataTable)
        index = getattr(table, "cursor_row", 0)
        if index is None:
            return None
        if index < 0 or index >= len(self._approval_ids):
            return None
        return self._approval_ids[index]

    def _render_selected_approval(self) -> None:
        details = self.query_one("#approval-details", Static)
        selected_id = self._selected_approval_id()
        if not selected_id:
            details.update("[dim]Select an approval to review options and context[/]")
            return
        details.update(f"[bold]Selected approval:[/] {selected_id}")

    async def _submit_selected_response(self, approved: bool) -> None:
        selected_id = self._selected_approval_id()
        if not selected_id:
            return
        await forward_approval_response(request_id=selected_id, approved=approved)
        self.run_worker(self._fetch(), exclusive=True)

    def action_approve_selected_approval(self) -> None:
        self.run_worker(self._submit_selected_response(True), exclusive=True)

    def action_reject_selected_approval(self) -> None:
        self.run_worker(self._submit_selected_response(False), exclusive=True)


class FilesScreen(VerticalScroll):
    """Read-only file previews and diff summaries."""

    def compose(self) -> ComposeResult:
        yield Label("Repository Files", classes="screen-title")
        yield Static(id="files-summary", classes="overview-block")
        previews = DataTable(id="files-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
        previews.add_columns("Path", "Lines", "Preview")
        yield previews
        diffs = DataTable(id="diff-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
        diffs.add_columns("Path", "Changed", "Diff Summary")
        yield diffs

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        file_views = await fetch_file_views()
        diff_views = await fetch_diff_views()

        summary = self.query_one("#files-summary", Static)
        summary.update(
            f"[bold]Files tracked:[/] {len(file_views)}   [bold]Diff targets:[/] {len(diff_views)}"
        )

        files_table = self.query_one("#files-table", DataTable)
        files_table.clear()
        for item in file_views:
            preview = item.get("preview", "")
            if preview:
                preview = preview.splitlines()[0][:90]
            files_table.add_row(
                item.get("path", "-"),
                str(item.get("line_count", 0)),
                preview or item.get("error", "-"),
            )

        diff_table = self.query_one("#diff-table", DataTable)
        diff_table.clear()
        for item in diff_views:
            diff_text = item.get("diff", "")
            if item.get("error"):
                summary_text = item["error"]
            elif diff_text:
                summary_text = diff_text.splitlines()[0][:120]
            else:
                summary_text = "clean"
            diff_table.add_row(
                item.get("path", "-"),
                "yes" if item.get("changed") else "no",
                summary_text,
            )

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class EventStreamScreen(VerticalScroll):
    """Recent canonical event activity recorded by the event spine."""

    def compose(self) -> ComposeResult:
        yield Label("Event Activity", classes="screen-title")
        yield Static(id="events-summary", classes="overview-block")
        table = DataTable(id="events-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
        table.add_columns("Time", "Type", "Source", "Correlation")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        events = await fetch_event_activity()
        summary = self.query_one("#events-summary", Static)
        summary.update(f"[bold]Recent events:[/] {len(events)}")
        table = self.query_one("#events-table", DataTable)
        table.clear()
        if events:
            for item in events:
                timestamp = str(item.get("timestamp") or "-")[:19].replace("T", " ")
                table.add_row(
                    timestamp,
                    str(item.get("event_type", "-")),
                    str(item.get("source", "-")),
                    str(item.get("correlation_id") or "-"),
                )
        else:
            table.add_row("[dim]No recorded events yet[/]", "-", "-", "-")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class AgnoScreen(VerticalScroll):
    """Agno execution summaries without owning the runtime."""

    def compose(self) -> ComposeResult:
        yield Label("Agno Activity", classes="screen-title")
        yield Static(id="agno-summary", classes="overview-block")
        table = DataTable(id="agno-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
        table.add_columns("Time", "Kind", "Team", "Details")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        activity = await fetch_agno_activity()
        summary = self.query_one("#agno-summary", Static)
        summary.update(f"[bold]Recent Agno executions:[/] {len(activity)}")
        table = self.query_one("#agno-table", DataTable)
        table.clear()
        if activity:
            for item in activity:
                timestamp = str(item.get("timestamp") or "-")[:19].replace("T", " ")
                details = (
                    item.get("task") or item.get("success_count") or item.get("response_count")
                )
                if isinstance(details, dict):
                    details = details.get("type") or details.get("operation") or str(details)
                table.add_row(
                    timestamp,
                    str(item.get("kind", "-")),
                    str(item.get("team_id") or item.get("task_type") or "-"),
                    str(details),
                )
        else:
            table.add_row("[dim]No Agno activity recorded[/]", "-", "-", "-")

    def refresh_data(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)


class TraceScreen(VerticalScroll):
    """Correlation-aware fix trace timeline."""

    def compose(self) -> ComposeResult:
        yield Label("Fix Trace", classes="screen-title")
        yield Static(id="trace-summary", classes="overview-block")
        table = DataTable(id="trace-table", cursor_type="row", zebra_stripes=True)  # type: ignore[var-annotated]
        table.add_columns("Time", "Stage", "Correlation", "Message")
        yield table

    def on_mount(self) -> None:
        self.run_worker(self._fetch(), exclusive=True)

    async def _fetch(self) -> None:
        data = await fetch_correlation_trace()
        summary = self.query_one("#trace-summary", Static)
        correlation_id = data.get("correlation_id") or "-"
        latest_stage = data.get("latest_stage") or "-"
        latest_message = data.get("latest_message") or "-"
        trace_count = data.get("trace_count", 0)
        summary.update(
            f"[bold]Correlation:[/] {correlation_id}   "
            f"[bold]Entries:[/] {trace_count}   "
            f"[bold]Latest stage:[/] {latest_stage}   "
            f"[bold]Latest message:[/] {latest_message}"
        )
        table = self.query_one("#trace-table", DataTable)
        table.clear()
        trace = data.get("trace", [])
        if trace:
            for item in trace:
                timestamp = str(item.get("timestamp") or "-")[:19].replace("T", " ")
                table.add_row(
                    timestamp,
                    str(item.get("stage", "-")),
                    str(item.get("correlation_id") or "-"),
                    str(item.get("message") or "-"),
                )
        else:
            table.add_row("[dim]No fix trace recorded yet[/]", "-", "-", "-")

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
        Binding("6", "switch_tab('session')", "Session"),
        Binding("7", "switch_tab('recovery')", "Recovery"),
        Binding("8", "switch_tab('approvals')", "Approvals"),
        Binding("9", "switch_tab('files')", "Files"),
        Binding("0", "switch_tab('events')", "Events"),
        Binding("g", "switch_tab('agno')", "Agno"),
        Binding("c", "switch_tab('trace')", "Trace"),
        Binding("a", "approve_selected_approval", "Approve"),
        Binding("x", "reject_selected_approval", "Reject"),
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
            with TabPane("6 Session", id="session"):
                yield SessionScreen()
            with TabPane("7 Recovery", id="recovery"):
                yield RecoveryScreen()
            with TabPane("8 Approvals", id="approvals"):
                yield ApprovalsScreen()
            with TabPane("9 Files", id="files"):
                yield FilesScreen()
            with TabPane("10 Events", id="events"):
                yield EventStreamScreen()
            with TabPane("11 Agno", id="agno"):
                yield AgnoScreen()
            with TabPane("12 Trace", id="trace"):
                yield TraceScreen()
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(_REFRESH_INTERVAL, self.action_refresh_all)

    def action_switch_tab(self, tab_id: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one(TabbedContent).active = tab_id

    def action_refresh_all(self) -> None:
        """Refresh all screens from live data."""
        for screen_cls in (
            OverviewScreen,
            SweepScreen,
            RoutingScreen,
            AlertsScreen,
            ReviewsScreen,
            SessionScreen,
            RecoveryScreen,
            ApprovalsScreen,
            FilesScreen,
            EventStreamScreen,
            AgnoScreen,
            TraceScreen,
        ):
            for widget in self.query(screen_cls):
                widget.refresh_data()  # type: ignore[attr-defined]

    def action_approve_selected_approval(self) -> None:
        for widget in self.query(ApprovalsScreen):
            widget.action_approve_selected_approval()
            return

    def action_reject_selected_approval(self) -> None:
        for widget in self.query(ApprovalsScreen):
            widget.action_reject_selected_approval()
            return


# Alias for convenience
MahavishnuDashboard = DashboardApp
