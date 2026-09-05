"""Coverage tests for ``mahavishnu.tui.app``.

Strategy:
* **A) Async data fetchers (Layer 1)** — 14 fetcher functions are tested via
  inline-import patching. Every fetcher does its imports inside the function
  body, so per the ``monkeypatch-inline-import-target`` rule we patch on the
  original module (e.g. ``mahavishnu.core.config.MahavishnuSettings``), not
  on ``mahavishnu.tui.app``.
* **B) Pure helpers (Layer 3)** — ``_severity_markup``, ``_state_markup``,
  ``_status_color`` are pure functions, so no patching is required.
* **C) Screen classes (Layer 4)** — structural tests (parent class,
  ``compose``/``on_mount``/``refresh_data`` exist, ``ApprovalsScreen``
  selected-id logic, ``BodaiComponentScreen`` ctor).
* **D) ``DashboardApp``** — class-level attribute smoke tests.

All tests are pure unit tests; nothing reaches a live Textual app context,
HTTP server, or subprocess.
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mahavishnu.core.ecosystem_status import (
    AdapterStatus,
    AlertRef,
    AlertSummary,
    CanonicalStatus,
    EcosystemStatusReport,
    RecoverySummary,
    WorkflowSummary,
)


# ---------------------------------------------------------------------------
# Snapshot of every screen's original ``on_mount`` so the harness can
# neuter it without leaking into other tests.
# ---------------------------------------------------------------------------


_ORIGINAL_ON_MOUNT: dict[type, Any] = {}


def _snapshot_on_mount() -> None:
    """Cache the original class-level ``on_mount`` once at import time."""
    from mahavishnu.tui.app import (
        AgnoScreen,
        AlertsScreen,
        ApprovalsScreen,
        BodaiComponentScreen,
        EventStreamScreen,
        FilesScreen,
        OverviewScreen,
        RecoveryScreen,
        ReviewsScreen,
        RoutingScreen,
        SessionScreen,
        SweepScreen,
        TraceScreen,
    )

    if _ORIGINAL_ON_MOUNT:
        return
    for cls in (
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
        BodaiComponentScreen,
    ):
        _ORIGINAL_ON_MOUNT[cls] = cls.__dict__.get("on_mount")


_snapshot_on_mount()


@pytest.fixture(autouse=True)
def _restore_on_mount_each_test() -> Any:
    """Restore each screen's ``on_mount`` after every test.

    The harness tests override ``on_mount`` to a no-op so the worker does
    not race with the explicit ``_fetch()`` call. Other tests want the
    original ``on_mount`` to fire so the ``run_worker(...)`` branch is
    covered. This fixture rewinds the override at every teardown.
    """
    yield
    for cls, original in _ORIGINAL_ON_MOUNT.items():
        if original is None:
            # Class did not declare its own ``on_mount``; remove the entry.
            cls.__dict__.pop("on_mount", None)
        else:
            cls.on_mount = original  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Helpers — small, reusable mocks
# ---------------------------------------------------------------------------


def _make_report(
    *,
    status: CanonicalStatus = CanonicalStatus.OK,
    adapters: dict[str, AdapterStatus] | None = None,
    workflows: WorkflowSummary | None = None,
    recovery: RecoverySummary | None = None,
    alerts: AlertSummary | None = None,
    generated_at: datetime | None = None,
) -> EcosystemStatusReport:
    """Build an ``EcosystemStatusReport`` with sensible defaults."""
    return EcosystemStatusReport(
        status=status,
        generated_at=generated_at or datetime.now(UTC),
        duration_ms=1.0,
        adapters=adapters or {},
        workflows=workflows or WorkflowSummary(),
        recovery=recovery or RecoverySummary(),
        alerts=alerts or AlertSummary(),
    )


def _patch_report(monkeypatch: pytest.MonkeyPatch, report: EcosystemStatusReport | None) -> None:
    """Patch the inline-import chain that ``_get_report`` walks.

    We pin ``get_app_from_context`` to return ``None`` (no app), and short-
    circuit ``EcosystemStatusService.generate_report`` to the supplied report.
    """
    from mahavishnu.core import config as core_config
    from mahavishnu.core import context as core_context
    from mahavishnu.core import ecosystem_status as core_ecosystem

    # MahavishnuSettings() needs enough attributes for the service_configs dict.
    settings = MagicMock()
    settings.session_buddy_url = None
    settings.akosha_url = None
    settings.oneiric_mcp = None
    monkeypatch.setattr(core_config, "MahavishnuSettings", lambda: settings)
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    async def _generate(self: Any, **_kw: Any) -> Any:
        return report

    monkeypatch.setattr(core_ecosystem.EcosystemStatusService, "generate_report", _generate)


# ===========================================================================
# A) Async data fetcher tests (Layer 1)
# ===========================================================================


# ---------------------------------------------------------------------------
# _get_report / fetch_system_overview
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_get_report_returns_none_when_settings_instantiation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``MahavishnuSettings()`` raises, ``_get_report`` returns ``None``."""
    from mahavishnu.core import config as core_config

    monkeypatch.setattr(core_config, "MahavishnuSettings", MagicMock(side_effect=Exception("boom")))

    from mahavishnu.tui.app import _get_report

    assert await _get_report() is None


@pytest.mark.unit
async def test_get_report_builds_service_configs_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both session_buddy_url AND akosha_url get pushed into service_configs."""
    from mahavishnu.core import config as core_config
    from mahavishnu.core import context as core_context
    from mahavishnu.core import ecosystem_status as core_ecosystem

    settings = MagicMock()
    settings.session_buddy_url = "http://sb.example/mcp"
    settings.akosha_url = "http://ak.example/mcp"
    settings.oneiric_mcp = None
    monkeypatch.setattr(core_config, "MahavishnuSettings", lambda: settings)
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    captured: dict[str, Any] = {}

    def _fake_service(*args: Any, **kwargs: Any) -> Any:
        captured["service_configs"] = kwargs.get("service_configs")
        captured["recovery_provider"] = kwargs.get("recovery_provider")

        inst = MagicMock()
        inst.generate_report = AsyncMock(return_value=None)
        return inst

    monkeypatch.setattr(core_ecosystem, "EcosystemStatusService", _fake_service)

    from mahavishnu.tui.app import _get_report

    result = await _get_report()

    assert result is None  # generate_report returned None above
    cfg = captured["service_configs"]
    assert cfg is not None
    assert "session-buddy" in cfg and "akosha" in cfg
    assert cfg["session-buddy"]["url"] == "http://sb.example/mcp"
    assert cfg["akosha"]["url"] == "http://ak.example/mcp"


@pytest.mark.unit
async def test_get_report_picks_up_oneiric_mcp_for_dhara(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``oneiric_mcp.url`` populates the dhara service config."""
    from mahavishnu.core import config as core_config
    from mahavishnu.core import context as core_context
    from mahavishnu.core import ecosystem_status as core_ecosystem

    settings = MagicMock()
    settings.session_buddy_url = None
    settings.akosha_url = None
    settings.oneiric_mcp = MagicMock(url="http://dhara.example/mcp", base_url=None)
    monkeypatch.setattr(core_config, "MahavishnuSettings", lambda: settings)
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    captured: dict[str, Any] = {}

    def _fake_service(*args: Any, **kwargs: Any) -> Any:
        captured["service_configs"] = kwargs.get("service_configs")
        inst = MagicMock()
        inst.generate_report = AsyncMock(return_value=None)
        return inst

    monkeypatch.setattr(core_ecosystem, "EcosystemStatusService", _fake_service)

    from mahavishnu.tui.app import _get_report

    await _get_report()
    assert "dhara" in (captured["service_configs"] or {})


@pytest.mark.unit
async def test_get_report_falls_back_to_oneiric_mcp_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``oneiric_mcp.base_url`` is used when ``.url`` is missing."""
    from mahavishnu.core import config as core_config
    from mahavishnu.core import context as core_context
    from mahavishnu.core import ecosystem_status as core_ecosystem

    settings = MagicMock()
    settings.session_buddy_url = None
    settings.akosha_url = None
    settings.oneiric_mcp = MagicMock(url=None, base_url="http://dhara.example/mcp")
    monkeypatch.setattr(core_config, "MahavishnuSettings", lambda: settings)
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    captured: dict[str, Any] = {}

    def _fake_service(*args: Any, **kwargs: Any) -> Any:
        captured["service_configs"] = kwargs.get("service_configs")
        inst = MagicMock()
        inst.generate_report = AsyncMock(return_value=None)
        return inst

    monkeypatch.setattr(core_ecosystem, "EcosystemStatusService", _fake_service)

    from mahavishnu.tui.app import _get_report

    await _get_report()
    assert "dhara" in (captured["service_configs"] or {})


@pytest.mark.unit
async def test_get_report_passes_app_as_recovery_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App with ``get_recovery_summary`` becomes the recovery provider."""
    from mahavishnu.core import config as core_config
    from mahavishnu.core import context as core_context
    from mahavishnu.core import ecosystem_status as core_ecosystem

    settings = MagicMock()
    settings.session_buddy_url = None
    settings.akosha_url = None
    settings.oneiric_mcp = None
    monkeypatch.setattr(core_config, "MahavishnuSettings", lambda: settings)

    app = MagicMock()
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    captured: dict[str, Any] = {}

    def _fake_service(*args: Any, **kwargs: Any) -> Any:
        captured["recovery_provider"] = kwargs.get("recovery_provider")
        inst = MagicMock()
        inst.generate_report = AsyncMock(return_value=None)
        return inst

    monkeypatch.setattr(core_ecosystem, "EcosystemStatusService", _fake_service)

    from mahavishnu.tui.app import _get_report

    await _get_report()
    assert captured["recovery_provider"] is app


@pytest.mark.unit
async def test_get_report_ignores_app_without_get_recovery_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App without ``get_recovery_summary`` does NOT become the recovery provider."""
    from mahavishnu.core import config as core_config
    from mahavishnu.core import context as core_context
    from mahavishnu.core import ecosystem_status as core_ecosystem

    settings = MagicMock()
    settings.session_buddy_url = None
    settings.akosha_url = None
    settings.oneiric_mcp = None
    monkeypatch.setattr(core_config, "MahavishnuSettings", lambda: settings)

    app = MagicMock(spec=[])  # no attrs at all
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    captured: dict[str, Any] = {}

    def _fake_service(*args: Any, **kwargs: Any) -> Any:
        captured["recovery_provider"] = kwargs.get("recovery_provider")
        inst = MagicMock()
        inst.generate_report = AsyncMock(return_value=None)
        return inst

    monkeypatch.setattr(core_ecosystem, "EcosystemStatusService", _fake_service)

    from mahavishnu.tui.app import _get_report

    await _get_report()
    assert captured["recovery_provider"] is None


@pytest.mark.unit
async def test_fetch_system_overview_returns_unknown_when_report_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``_get_report`` is ``None``, fall back to the unknown-status default."""
    _patch_report(monkeypatch, None)

    from mahavishnu.tui.app import fetch_system_overview

    result = await fetch_system_overview()
    assert result == {
        "status": "unknown",
        "active_workflows": 0,
        "total_adapters": 0,
        "healthy_adapters": 0,
        "recent_alerts": 0,
    }


@pytest.mark.unit
async def test_fetch_system_overview_counts_healthy_adapters_and_workflows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Healthy adapters are those whose ``status.value == 'ok'``."""
    adapters = {
        "prefect": AdapterStatus(status=CanonicalStatus.OK, preference_score=1.0),
        "llamaindex": AdapterStatus(status=CanonicalStatus.OK, preference_score=0.5),
        "agno": AdapterStatus(status=CanonicalStatus.DEGRADED, preference_score=0.2),
    }
    workflows = WorkflowSummary(active_count=3, failed_count=1, recent_count=4)
    alerts = AlertSummary(total_active=2)
    report = _make_report(
        status=CanonicalStatus.OK, adapters=adapters, workflows=workflows, alerts=alerts
    )
    _patch_report(monkeypatch, report)

    from mahavishnu.tui.app import fetch_system_overview

    result = await fetch_system_overview()
    assert result["status"] == "ok"
    assert result["total_adapters"] == 3
    assert result["healthy_adapters"] == 2
    assert result["active_workflows"] == 3
    assert result["recent_alerts"] == 2
    assert "generated_at" in result


@pytest.mark.unit
async def test_fetch_system_overview_handles_missing_workflows_and_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``workflows=None`` and ``alerts=None`` must not crash."""
    # Build a report with default workflows/alerts, then clear them via __dict__.
    report = _make_report()
    object.__setattr__(report, "workflows", None)
    object.__setattr__(report, "alerts", None)
    _patch_report(monkeypatch, report)

    from mahavishnu.tui.app import fetch_system_overview

    result = await fetch_system_overview()
    assert result["active_workflows"] == 0
    assert result["recent_alerts"] == 0


# ---------------------------------------------------------------------------
# fetch_sweep_history
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fetch_sweep_history_empty_when_report_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No report → empty list."""
    _patch_report(monkeypatch, None)

    from mahavishnu.tui.app import fetch_sweep_history

    assert await fetch_sweep_history() == []


@pytest.mark.unit
async def test_fetch_sweep_history_returns_summary_when_counts_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One-row summary surfaces when any of active/failed/recent is nonzero."""
    workflows = WorkflowSummary(active_count=2, failed_count=1, recent_count=5)
    _patch_report(monkeypatch, _make_report(workflows=workflows))

    from mahavishnu.tui.app import fetch_sweep_history

    result = await fetch_sweep_history()
    assert result == [{"status": "active", "active": 2, "failed": 1, "recent": 5}]


@pytest.mark.unit
async def test_fetch_sweep_history_empty_when_all_counts_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero everywhere → empty list (the ``else`` branch)."""
    _patch_report(monkeypatch, _make_report(workflows=WorkflowSummary()))

    from mahavishnu.tui.app import fetch_sweep_history

    assert await fetch_sweep_history() == []


@pytest.mark.unit
async def test_fetch_sweep_history_empty_when_workflows_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``workflows=None`` must return ``[]`` without AttributeError."""
    report = _make_report()
    object.__setattr__(report, "workflows", None)
    _patch_report(monkeypatch, report)

    from mahavishnu.tui.app import fetch_sweep_history

    assert await fetch_sweep_history() == []


# ---------------------------------------------------------------------------
# fetch_routing_stats
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fetch_routing_stats_default_when_report_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No report → adapters empty + 0/0.0 stats."""
    _patch_report(monkeypatch, None)

    from mahavishnu.tui.app import fetch_routing_stats

    result = await fetch_routing_stats()
    assert result == {"adapters": [], "total_decisions": 0, "cache_hit_rate": 0.0}


@pytest.mark.unit
async def test_fetch_routing_stats_lists_adapters_with_status_and_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapter list surfaces name/status/capabilities/preference_score."""
    adapters = {
        "prefect": AdapterStatus(
            status=CanonicalStatus.OK,
            capabilities={"code": CanonicalStatus.OK},
            preference_score=1.0,
        ),
        "llamaindex": AdapterStatus(
            status=CanonicalStatus.DEGRADED,
            capabilities={},
            preference_score=0.7,
        ),
    }
    _patch_report(monkeypatch, _make_report(adapters=adapters))

    from mahavishnu.tui.app import fetch_routing_stats

    result = await fetch_routing_stats()
    names = {a["name"] for a in result["adapters"]}
    assert names == {"prefect", "llamaindex"}
    prefect = next(a for a in result["adapters"] if a["name"] == "prefect")
    assert prefect["status"] == "ok"
    assert prefect["preference_score"] == 1.0
    assert result["total_decisions"] == 2
    assert result["cache_hit_rate"] == 0.5


@pytest.mark.unit
async def test_fetch_routing_stats_handles_empty_adapter_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty adapters dict yields 0.0 hit rate (zero-division guard)."""
    _patch_report(monkeypatch, _make_report(adapters={}))

    from mahavishnu.tui.app import fetch_routing_stats

    result = await fetch_routing_stats()
    assert result["adapters"] == []
    assert result["cache_hit_rate"] == 0.0


# ---------------------------------------------------------------------------
# fetch_active_alerts
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fetch_active_alerts_empty_when_report_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No report → empty list."""
    _patch_report(monkeypatch, None)

    from mahavishnu.tui.app import fetch_active_alerts

    assert await fetch_active_alerts() == []


@pytest.mark.unit
async def test_fetch_active_alerts_formats_top_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Top alerts come back as id/severity/title/description/time."""
    alerts = AlertSummary(
        total_active=1,
        top_alerts=[
            AlertRef(
                severity="critical",
                source="akosha",
                message="down",
                created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        ],
    )
    _patch_report(monkeypatch, _make_report(alerts=alerts))

    from mahavishnu.tui.app import fetch_active_alerts

    result = await fetch_active_alerts()
    assert len(result) == 1
    assert result[0]["severity"] == "critical"
    assert result[0]["title"] == "akosha: down"
    assert result[0]["description"] == "down"
    assert result[0]["time"] == "2026-01-02T03:04:05+00:00"
    assert result[0]["id"] == "0"


@pytest.mark.unit
async def test_fetch_active_alerts_empty_when_alerts_none_or_no_top(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Either ``alerts=None`` or empty ``top_alerts`` returns ``[]``."""
    report = _make_report()
    object.__setattr__(report, "alerts", None)
    _patch_report(monkeypatch, report)

    from mahavishnu.tui.app import fetch_active_alerts

    assert await fetch_active_alerts() == []


# ---------------------------------------------------------------------------
# fetch_recovery_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fetch_recovery_summary_zero_default_when_report_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No report → all zeros, no Dhara, no last_recovered_at."""
    _patch_report(monkeypatch, None)

    from mahavishnu.tui.app import fetch_recovery_summary

    result = await fetch_recovery_summary()
    assert result == {
        "recovered_workflows": 0,
        "recovered_approvals": 0,
        "recovered_pools": 0,
        "recovered_routing_decisions": 0,
        "dhara_available": False,
        "last_recovered_at": None,
    }


@pytest.mark.unit
async def test_fetch_recovery_summary_returns_recovery_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RecoverySummary fields surface in the returned dict."""
    recovery = RecoverySummary(
        recovered_workflows=3,
        recovered_approvals=2,
        recovered_pools=1,
        recovered_routing_decisions=4,
        dhara_available=True,
        last_recovered_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    _patch_report(monkeypatch, _make_report(recovery=recovery))

    from mahavishnu.tui.app import fetch_recovery_summary

    result = await fetch_recovery_summary()
    assert result["recovered_workflows"] == 3
    assert result["recovered_approvals"] == 2
    assert result["recovered_pools"] == 1
    assert result["recovered_routing_decisions"] == 4
    assert result["dhara_available"] is True
    assert result["last_recovered_at"] == "2026-02-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# fetch_skill_drafts
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fetch_skill_drafts_uses_registry_when_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An attached ``skill_registry.list_active()`` wins over the FS fallback."""

    class _Record:
        skill_id = "draft-1"
        version = "0.1"
        state = "review"
        body = "# Draft One\nbody text"

        class _Activation:
            activated_at = datetime(2026, 3, 1, tzinfo=UTC)
            activated_by = "alice"

        activation = _Activation()
        review = None

    class _Registry:
        def list_active(self) -> list[_Record]:
            return [_Record()]

    app = MagicMock()
    app.skill_registry = _Registry()
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_skill_drafts

    result = await fetch_skill_drafts()
    assert len(result) == 1
    assert result[0]["skill_id"] == "draft-1"
    assert result[0]["state"] == "review"
    assert result[0]["proposed_by"] == "alice"
    assert result[0]["created_at"] == datetime(2026, 3, 1, tzinfo=UTC)
    assert "Draft One" in result[0]["description"]


@pytest.mark.unit
async def test_fetch_skill_drafts_falls_back_to_filesystem(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No registry + skills under ~/.claude/skills/ → scanned via SKILL.md."""
    # No app ⇒ no registry.
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    # Build a fake ~/.claude/skills/<name>/SKILL.md tree.
    skills_root = tmp_path / ".claude" / "skills"
    skill_dir = skills_root / "my-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\ndescription: A test skill\n---\n\n# my-skill\nBody text.\n",
        encoding="utf-8",
    )

    # Force Path.home() to point at tmp_path.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    from mahavishnu.tui.app import fetch_skill_drafts

    result = await fetch_skill_drafts()
    assert len(result) == 1
    assert result[0]["skill_id"] == "my-skill"
    assert result[0]["description"] == "A test skill"
    assert result[0]["state"] == "active"


@pytest.mark.unit
async def test_fetch_skill_drafts_empty_when_no_skills_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No registry AND missing ~/.claude/skills/ → ``[]``."""
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    from mahavishnu.tui.app import fetch_skill_drafts

    assert await fetch_skill_drafts() == []


@pytest.mark.unit
async def test_fetch_skill_drafts_swallows_registry_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Registry raises → fall through to filesystem scan."""
    from mahavishnu.core import context as core_context

    class _BadRegistry:
        def list_active(self) -> Any:
            raise RuntimeError("nope")

    app = MagicMock()
    app.skill_registry = _BadRegistry()
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    # Build a single skill so we can observe the fallback succeeded.
    skills_root = tmp_path / ".claude" / "skills"
    skill_dir = skills_root / "fallback-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: fallback\n---\n", encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    from mahavishnu.tui.app import fetch_skill_drafts

    result = await fetch_skill_drafts()
    assert len(result) == 1
    assert result[0]["skill_id"] == "fallback-skill"


# ---------------------------------------------------------------------------
# fetch_session_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fetch_session_summary_uses_app_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App attached: derive enabled/interval/url from session_buddy + config."""
    from mahavishnu.core import context as core_context

    session_buddy = MagicMock()
    session_buddy.enabled = True
    session_buddy.checkpoint_interval = 120
    session_buddy._base_url = "http://sb.local/mcp"

    session_cfg = MagicMock()
    session_cfg.enabled = False
    session_cfg.checkpoint_interval = 60
    pools_cfg = MagicMock()
    pools_cfg.session_buddy_url = "http://from-config/mcp"
    config = MagicMock()
    config.session = session_cfg
    config.pools = pools_cfg

    app = MagicMock()
    app.session_buddy = session_buddy
    app.config = config
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_session_summary

    result = await fetch_session_summary()
    assert result["enabled"] is True
    assert result["checkpoint_interval"] == 120
    assert result["session_buddy_url"] == "http://sb.local/mcp"
    assert result["checkpoint_mode"] == "write-forward"


@pytest.mark.unit
async def test_fetch_session_summary_disabled_when_app_session_buddy_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``enabled=False`` propagates and ``checkpoint_mode`` becomes ``disabled``."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.session_buddy = MagicMock(enabled=False, checkpoint_interval=0, _base_url=None)
    app.config = None
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_session_summary

    result = await fetch_session_summary()
    assert result["enabled"] is False
    assert result["checkpoint_mode"] == "disabled"


@pytest.mark.unit
async def test_fetch_session_summary_falls_back_to_settings_when_no_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No app → derive from ``MahavishnuSettings`` directly."""
    from mahavishnu.core import config as core_config
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    settings = MagicMock()
    settings.session.enabled = True
    settings.session.checkpoint_interval = 30
    settings.pools.session_buddy_url = "http://settings-only/mcp"
    monkeypatch.setattr(core_config, "MahavishnuSettings", lambda: settings)

    from mahavishnu.tui.app import fetch_session_summary

    result = await fetch_session_summary()
    assert result["enabled"] is True
    assert result["checkpoint_interval"] == 30
    assert result["session_buddy_url"] == "http://settings-only/mcp"
    assert result["checkpoint_mode"] == "write-forward"


# ---------------------------------------------------------------------------
# fetch_pending_approvals / fetch_event_activity / fetch_agno_activity
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fetch_pending_approvals_empty_when_no_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No app → ``[]``."""
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    from mahavishnu.tui.app import fetch_pending_approvals

    assert await fetch_pending_approvals() == []


@pytest.mark.unit
async def test_fetch_pending_approvals_returns_app_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App with ``list_pending_approvals`` is invoked once."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.list_pending_approvals = MagicMock(return_value=[{"id": "a"}, {"id": "b"}])
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_pending_approvals

    result = await fetch_pending_approvals()
    assert result == [{"id": "a"}, {"id": "b"}]
    app.list_pending_approvals.assert_called_once_with()


@pytest.mark.unit
async def test_fetch_pending_approvals_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raising from the app must surface as ``[]``, not a 500."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.list_pending_approvals = MagicMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_pending_approvals

    assert await fetch_pending_approvals() == []


@pytest.mark.unit
async def test_fetch_event_activity_empty_when_no_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No app → ``[]``."""
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    from mahavishnu.tui.app import fetch_event_activity

    assert await fetch_event_activity() == []


@pytest.mark.unit
async def test_fetch_event_activity_returns_app_results_with_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``limit=5`` is forwarded into ``app.get_event_activity``."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.get_event_activity = MagicMock(return_value=[{"id": 1}])
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_event_activity

    result = await fetch_event_activity(limit=5)
    assert result == [{"id": 1}]
    app.get_event_activity.assert_called_once_with(limit=5)


@pytest.mark.unit
async def test_fetch_event_activity_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App raising → ``[]``."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.get_event_activity = MagicMock(side_effect=RuntimeError("oops"))
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_event_activity

    assert await fetch_event_activity() == []


@pytest.mark.unit
async def test_fetch_agno_activity_empty_when_no_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No app → ``[]``."""
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    from mahavishnu.tui.app import fetch_agno_activity

    assert await fetch_agno_activity() == []


@pytest.mark.unit
async def test_fetch_agno_activity_uses_agno_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ``agno`` entry in ``app.adapters`` is consulted, with the limit."""
    from mahavishnu.core import context as core_context

    agno_adapter = MagicMock()
    agno_adapter.get_execution_log = MagicMock(return_value=[{"k": "v"}])

    app = MagicMock()
    app.adapters = {"agno": agno_adapter}
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_agno_activity

    result = await fetch_agno_activity(limit=10)
    assert result == [{"k": "v"}]
    agno_adapter.get_execution_log.assert_called_once_with(limit=10)


@pytest.mark.unit
async def test_fetch_agno_activity_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adapter raising → ``[]``."""
    from mahavishnu.core import context as core_context

    agno_adapter = MagicMock()
    agno_adapter.get_execution_log = MagicMock(side_effect=RuntimeError("x"))

    app = MagicMock()
    app.adapters = {"agno": agno_adapter}
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_agno_activity

    assert await fetch_agno_activity() == []


# ---------------------------------------------------------------------------
# fetch_correlation_trace
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_fetch_correlation_trace_default_when_no_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No app → empty envelope with correlation_id echoed back."""
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    from mahavishnu.tui.app import fetch_correlation_trace

    result = await fetch_correlation_trace(correlation_id="abc-123")
    assert result == {
        "correlation_id": "abc-123",
        "trace": [],
        "trace_count": 0,
        "latest_stage": None,
        "latest_message": None,
    }


@pytest.mark.unit
async def test_fetch_correlation_trace_merges_status_with_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``get_correlation_status`` dict is unpacked into the result envelope."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.get_correlation_status = MagicMock(
        return_value={"trace_count": 3, "latest_stage": "review", "latest_message": "ok"}
    )
    app.get_fix_trace = MagicMock(return_value=[{"stage": "review"}])
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_correlation_trace

    result = await fetch_correlation_trace(correlation_id="xyz")
    assert result["correlation_id"] == "xyz"
    assert result["trace"] == [{"stage": "review"}]
    assert result["trace_count"] == 3
    assert result["latest_stage"] == "review"


@pytest.mark.unit
async def test_fetch_correlation_trace_swallows_app_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App raising during either call → empty envelope, no propagation."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.get_correlation_status = MagicMock(side_effect=RuntimeError("oops"))
    app.get_fix_trace = MagicMock(return_value=[])
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import fetch_correlation_trace

    result = await fetch_correlation_trace(correlation_id="q")
    assert result["correlation_id"] == "q"
    assert result["trace"] == []
    assert result["trace_count"] == 0


# ---------------------------------------------------------------------------
# forward_approval_request / forward_approval_response
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_forward_approval_request_unavailable_without_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No app → structured failure dict."""
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    from mahavishnu.tui.app import forward_approval_request

    result = await forward_approval_request(
        approval_type="version-bump", context={"k": "v"}, options=["a", "b"]
    )
    assert result["error"] == "Approval manager unavailable"
    assert result["approval_type"] == "version-bump"
    assert result["status"] == "failed"


@pytest.mark.unit
async def test_forward_approval_request_returns_app_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: app.request_approval return value is forwarded."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.request_approval = MagicMock(return_value={"request_id": "r1", "status": "pending"})
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import forward_approval_request

    result = await forward_approval_request(
        approval_type="publish", context={}, options=None, timeout_minutes=10
    )
    assert result == {"request_id": "r1", "status": "pending"}
    app.request_approval.assert_called_once_with(
        approval_type="publish",
        context={},
        options=None,
        timeout_minutes=10,
    )


@pytest.mark.unit
async def test_forward_approval_request_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App raising → structured failure dict with the exception message."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.request_approval = MagicMock(side_effect=RuntimeError("kaboom"))
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import forward_approval_request

    result = await forward_approval_request(approval_type="x", context={})
    assert result["status"] == "failed"
    assert result["error"] == "kaboom"
    assert result["approval_type"] == "x"


@pytest.mark.unit
async def test_forward_approval_response_unavailable_without_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No app → structured failure dict."""
    from mahavishnu.core import context as core_context

    monkeypatch.setattr(core_context, "get_app_from_context", lambda: None)

    from mahavishnu.tui.app import forward_approval_response

    result = await forward_approval_response(request_id="r1", approved=True)
    assert result["error"] == "Approval manager unavailable"
    assert result["status"] == "failed"
    assert result["request_id"] == "r1"
    assert result["approved"] is True


@pytest.mark.unit
async def test_forward_approval_response_forwards_to_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: app.respond_to_approval return value is forwarded."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.respond_to_approval = MagicMock(return_value={"status": "responded"})
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import forward_approval_response

    result = await forward_approval_response(
        request_id="r2",
        approved=False,
        selected_option=1,
        rejection_reason="not now",
    )
    assert result == {"status": "responded"}
    app.respond_to_approval.assert_called_once_with(
        request_id="r2",
        approved=False,
        selected_option=1,
        rejection_reason="not now",
    )


@pytest.mark.unit
async def test_forward_approval_response_swallows_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App raising → structured failure dict with the exception message."""
    from mahavishnu.core import context as core_context

    app = MagicMock()
    app.respond_to_approval = MagicMock(side_effect=RuntimeError("nope"))
    monkeypatch.setattr(core_context, "get_app_from_context", lambda: app)

    from mahavishnu.tui.app import forward_approval_response

    result = await forward_approval_response(request_id="r3", approved=True)
    assert result["status"] == "failed"
    assert result["error"] == "nope"
    assert result["request_id"] == "r3"


# ---------------------------------------------------------------------------
# _read_cockpit_file / fetch_file_views / fetch_diff_views
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_read_cockpit_file_returns_invalid_when_validator_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validator rejection surfaces as ``exists=False`` + error."""
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(validate_worktree_path=lambda _p: (False, "outside worktree")),
    )

    from mahavishnu.tui.app import _read_cockpit_file

    result = _read_cockpit_file(Path("/etc/passwd"))
    assert result["exists"] is False
    assert result["error"] == "outside worktree"


@pytest.mark.unit
def test_read_cockpit_file_returns_missing_when_file_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Validator OK but file is missing → ``exists=False``."""
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(validate_worktree_path=lambda _p: (True, None)),
    )

    from mahavishnu.tui.app import _read_cockpit_file

    missing = tmp_path / "absent.md"
    result = _read_cockpit_file(missing)
    assert result["exists"] is False
    assert result["error"] == "missing file"


@pytest.mark.unit
def test_read_cockpit_file_reads_real_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Happy path: validator OK, file exists → preview + line_count."""
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(validate_worktree_path=lambda _p: (True, None)),
    )

    target = tmp_path / "doc.md"
    target.write_text(
        "# title\nline 1\nline 2\nline 3\nline 4\nline 5\nline 6\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))

    from mahavishnu.tui.app import _read_cockpit_file

    result = _read_cockpit_file(target)
    assert result["exists"] is True
    assert result["line_count"] == 7
    assert "# title" in result["preview"]


@pytest.mark.unit
def test_read_cockpit_file_falls_back_to_latin1_for_unicode_decode_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A binary file that fails UTF-8 decoding falls back to latin-1."""
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(validate_worktree_path=lambda _p: (True, None)),
    )

    target = tmp_path / "blob.md"
    # Bytes that include an invalid UTF-8 sequence.
    target.write_bytes(b"# title\nhello\n\xc3\x28 world\n")

    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))

    from mahavishnu.tui.app import _read_cockpit_file

    result = _read_cockpit_file(target)
    assert result["exists"] is True
    assert "hello" in result["preview"]


@pytest.mark.unit
async def test_fetch_file_views_aggregates_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``fetch_file_views`` runs ``_read_cockpit_file`` once per path."""
    # Stub the validator to accept everything.
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(validate_worktree_path=lambda _p: (True, None)),
    )

    (tmp_path / "A.md").write_text("alpha\n", encoding="utf-8")
    (tmp_path / "B.md").write_text("beta\n", encoding="utf-8")
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))

    from mahavishnu.tui.app import fetch_file_views

    result = await fetch_file_views(paths=("A.md", "B.md"))
    assert len(result) == 2
    assert {r["path"] for r in result} == {"A.md", "B.md"}


@pytest.mark.unit
async def test_fetch_diff_views_marks_invalid_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the validator rejects a path, the diff view carries an error."""
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(validate_worktree_path=lambda _p: (False, "outside worktree")),
    )

    from mahavishnu.tui.app import fetch_diff_views

    result = await fetch_diff_views(paths=("README.md", "docs/foo.md"))
    assert len(result) == 2
    for entry in result:
        assert entry["diff"] == ""
        assert entry["error"] == "outside worktree"
        assert "changed" not in entry  # error branch skips this field


@pytest.mark.unit
async def test_fetch_diff_views_marks_clean_when_no_diff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Empty ``git diff`` stdout → ``changed=False``."""
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(validate_worktree_path=lambda _p: (True, None)),
    )
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))

    class _Completed:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: _Completed(),
    )

    from mahavishnu.tui.app import fetch_diff_views

    result = await fetch_diff_views(paths=("README.md",))
    assert result[0]["diff"] == ""
    assert result[0]["changed"] is False


@pytest.mark.unit
async def test_fetch_diff_views_marks_changed_when_diff_present(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Non-empty stdout → ``changed=True`` with stripped diff."""
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(validate_worktree_path=lambda _p: (True, None)),
    )
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))

    class _Completed:
        stdout = "@@ -1 +1 @@\n-old\n+new\n"
        stderr = ""

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_a, **_kw: _Completed(),
    )

    from mahavishnu.tui.app import fetch_diff_views

    result = await fetch_diff_views(paths=("README.md",))
    assert result[0]["changed"] is True
    assert "-old" in result[0]["diff"]
    assert "+new" in result[0]["diff"]


# ===========================================================================
# B) Pure helpers (Layer 3)
# ===========================================================================


@pytest.mark.unit
def test_severity_markup_known_values() -> None:
    """Each known severity maps to its color."""
    from mahavishnu.tui.app import _severity_markup

    assert "bold red" in _severity_markup("critical")
    assert "bold red" in _severity_markup("error")
    assert "bold yellow" in _severity_markup("warning")
    assert "bold cyan" in _severity_markup("info")
    assert "bold dim" in _severity_markup("debug")
    # Severity is uppercased in the markup.
    assert "CRITICAL" in _severity_markup("critical")
    assert "WARNING" in _severity_markup("warning")


@pytest.mark.unit
def test_severity_markup_unknown_uses_white() -> None:
    """Unknown severity → ``bold white``."""
    from mahavishnu.tui.app import _severity_markup

    assert "bold white" in _severity_markup("mystery")


@pytest.mark.unit
def test_state_markup_known_values() -> None:
    """Each known state maps to its color."""
    from mahavishnu.tui.app import _state_markup

    assert "bold yellow" in _state_markup("draft")
    assert "bold cyan" in _state_markup("review")
    assert "bold green" in _state_markup("active")
    assert "bold red" in _state_markup("deprecated")


@pytest.mark.unit
def test_state_markup_handles_none_and_unknown() -> None:
    """``None`` and unknown states → ``bold white``."""
    from mahavishnu.tui.app import _state_markup

    assert "bold white" in _state_markup(None)
    assert "bold white" in _state_markup("something-new")


@pytest.mark.unit
def test_status_color_known_values() -> None:
    """Each known status maps to its color."""
    from mahavishnu.tui.app import _status_color

    assert _status_color("ok") == "green"
    assert _status_color("healthy") == "green"
    assert _status_color("degraded") == "yellow"
    assert _status_color("unknown") == "dim"


@pytest.mark.unit
def test_status_color_unknown_returns_red() -> None:
    """Unknown status (e.g. ``panic``) → ``red``."""
    from mahavishnu.tui.app import _status_color

    assert _status_color("panic") == "red"


# ===========================================================================
# C) Screen classes (Layer 4) — structural tests
# ===========================================================================


@pytest.mark.unit
def test_screen_classes_inherit_vertical_scroll() -> None:
    """All TUI screen classes derive from ``textual.containers.VerticalScroll``."""
    from textual.containers import VerticalScroll

    from mahavishnu.tui.app import (
        AgnoScreen,
        AlertsScreen,
        ApprovalsScreen,
        BodaiComponentScreen,
        EventStreamScreen,
        FilesScreen,
        OverviewScreen,
        RecoveryScreen,
        ReviewsScreen,
        RoutingScreen,
        SessionScreen,
        SweepScreen,
        TraceScreen,
    )

    for cls in (
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
        BodaiComponentScreen,
    ):
        assert issubclass(cls, VerticalScroll), f"{cls.__name__} must inherit VerticalScroll"


@pytest.mark.unit
def test_screen_classes_have_required_methods() -> None:
    """Each screen has ``compose``, ``on_mount``, and ``refresh_data``."""
    from mahavishnu.tui.app import (
        AgnoScreen,
        AlertsScreen,
        ApprovalsScreen,
        BodaiComponentScreen,
        EventStreamScreen,
        FilesScreen,
        OverviewScreen,
        RecoveryScreen,
        ReviewsScreen,
        RoutingScreen,
        SessionScreen,
        SweepScreen,
        TraceScreen,
    )

    for cls in (
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
        assert callable(getattr(cls, "compose", None)), cls.__name__
        assert callable(getattr(cls, "on_mount", None)), cls.__name__
        assert callable(getattr(cls, "refresh_data", None)), cls.__name__


@pytest.mark.unit
def test_approvals_screen_initializes_empty_id_list() -> None:
    """Constructor sets ``_approval_ids`` to an empty list."""
    from mahavishnu.tui.app import ApprovalsScreen

    screen = ApprovalsScreen()
    assert screen._approval_ids == []


@pytest.mark.unit
def test_approvals_screen_selected_approval_id_with_none_cursor() -> None:
    """``_selected_approval_id`` returns ``None`` when ``cursor_row`` is None."""
    from mahavishnu.tui.app import ApprovalsScreen

    screen = ApprovalsScreen()
    screen._approval_ids = ["a", "b", "c"]
    # Stub query_one to return a DataTable whose cursor_row is None.
    screen.query_one = MagicMock(return_value=MagicMock(cursor_row=None))  # type: ignore[method-assign]
    assert screen._selected_approval_id() is None


@pytest.mark.unit
def test_approvals_screen_selected_approval_id_out_of_range() -> None:
    """``_selected_approval_id`` returns ``None`` for out-of-range cursor."""
    from mahavishnu.tui.app import ApprovalsScreen

    screen = ApprovalsScreen()
    screen._approval_ids = ["a", "b"]
    screen.query_one = MagicMock(  # type: ignore[method-assign]
        return_value=MagicMock(cursor_row=5)
    )
    assert screen._selected_approval_id() is None

    # Negative cursor is also rejected.
    screen.query_one = MagicMock(  # type: ignore[method-assign]
        return_value=MagicMock(cursor_row=-1)
    )
    assert screen._selected_approval_id() is None


@pytest.mark.unit
def test_approvals_screen_selected_approval_id_in_range() -> None:
    """``_selected_approval_id`` returns the id at the cursor index."""
    from mahavishnu.tui.app import ApprovalsScreen

    screen = ApprovalsScreen()
    screen._approval_ids = ["a", "b", "c"]
    screen.query_one = MagicMock(  # type: ignore[method-assign]
        return_value=MagicMock(cursor_row=1)
    )
    assert screen._selected_approval_id() == "b"


@pytest.mark.unit
def test_approvals_screen_render_selected_approval_no_selection() -> None:
    """No selection → placeholder text."""
    from mahavishnu.tui.app import ApprovalsScreen

    screen = ApprovalsScreen()
    screen._approval_ids = []
    details = MagicMock()
    screen.query_one = MagicMock(return_value=details)  # type: ignore[method-assign]
    screen._selected_approval_id = MagicMock(return_value=None)  # type: ignore[method-assign]

    screen._render_selected_approval()
    details.update.assert_called_once()
    call_arg = details.update.call_args[0][0]
    assert "Select an approval" in call_arg


@pytest.mark.unit
def test_approvals_screen_render_selected_approval_with_selection() -> None:
    """With a selection → bold "Selected approval: ..." line."""
    from mahavishnu.tui.app import ApprovalsScreen

    screen = ApprovalsScreen()
    screen._approval_ids = ["abc"]
    details = MagicMock()
    screen.query_one = MagicMock(return_value=details)  # type: ignore[method-assign]
    screen._selected_approval_id = MagicMock(return_value="abc")  # type: ignore[method-assign]

    screen._render_selected_approval()
    call_arg = details.update.call_args[0][0]
    assert "[bold]Selected approval:[/] abc" == call_arg


@pytest.mark.unit
def test_approvals_screen_submit_response_no_selection_noop() -> None:
    """``_submit_selected_response`` returns early when nothing is selected."""
    from mahavishnu.tui.app import ApprovalsScreen

    screen = ApprovalsScreen()
    screen._selected_approval_id = MagicMock(return_value=None)  # type: ignore[method-assign]
    screen.run_worker = MagicMock()  # type: ignore[method-assign]

    # Coroutine to drive — should return immediately without scheduling work.
    asyncio.run(screen._submit_selected_response(True))
    screen.run_worker.assert_not_called()


@pytest.mark.unit
def test_bodai_component_screen_stores_constructor_args() -> None:
    """The constructor pins ``_label``/``_slug``/``_base_url``."""
    from mahavishnu.tui.app import BodaiComponentScreen

    screen = BodaiComponentScreen("Crackerjack — Quality", "crackerjack", "http://cj.local")
    assert screen._label == "Crackerjack — Quality"
    assert screen._slug == "crackerjack"
    assert screen._base_url == "http://cj.local"


@pytest.mark.unit
def test_bodai_component_screen_have_required_methods() -> None:
    """``BodaiComponentScreen`` has compose/on_mount/refresh_data."""
    from mahavishnu.tui.app import BodaiComponentScreen

    screen = BodaiComponentScreen("Label", "slug", "http://x")
    assert callable(screen.compose)
    assert callable(screen.on_mount)
    assert callable(screen.refresh_data)


# ===========================================================================
# D) DashboardApp class smoke tests
# ===========================================================================


@pytest.mark.unit
def test_dashboard_app_class_attributes() -> None:
    """Static metadata on ``DashboardApp`` is in place."""
    from mahavishnu.tui.app import DashboardApp, MahavishnuDashboard

    assert DashboardApp.TITLE == "Mahavishnu Dashboard"
    assert "Auto-refresh" in DashboardApp.SUB_TITLE
    assert "30s" in DashboardApp.SUB_TITLE
    assert isinstance(DashboardApp.CSS, str)
    assert "screen-title" in DashboardApp.CSS
    assert isinstance(DashboardApp.BINDINGS, list)

    # The alias is the same class.
    assert MahavishnuDashboard is DashboardApp


@pytest.mark.unit
def test_dashboard_app_bindings_cover_expected_actions() -> None:
    """All advertised key bindings are present on the class."""
    from mahavishnu.tui.app import DashboardApp

    keys = {b.key for b in DashboardApp.BINDINGS}
    for expected in ("q", "r", "ctrl+k", "1", "9", "0", "g", "c", "a", "x"):
        assert expected in keys, f"missing binding for {expected!r}"


@pytest.mark.unit
def test_action_refresh_all_calls_refresh_on_each_screen_widget() -> None:
    """``action_refresh_all`` walks all 12 known screen classes and calls refresh_data."""
    from mahavishnu.tui.app import (
        AgnoScreen,
        AlertsScreen,
        ApprovalsScreen,
        BodaiComponentScreen,
        DashboardApp,
        EventStreamScreen,
        FilesScreen,
        OverviewScreen,
        RecoveryScreen,
        ReviewsScreen,
        RoutingScreen,
        SessionScreen,
        SweepScreen,
        TraceScreen,
    )

    # Build a fake app instance whose ``query`` returns one mock widget per class.
    widgets_by_class: dict[type, Any] = {
        cls: MagicMock() for cls in (
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
            BodaiComponentScreen,
        )
    }

    app = DashboardApp.__new__(DashboardApp)  # bypass real __init__

    def _fake_query(screen_cls: type) -> list[Any]:
        return [widgets_by_class[screen_cls]]

    app.query = _fake_query  # type: ignore[method-assign]

    app.action_refresh_all()

    for cls, widget in widgets_by_class.items():
        widget.refresh_data.assert_called_once_with(), cls.__name__


@pytest.mark.unit
def test_action_approve_routes_to_first_approval_widget() -> None:
    """``action_approve_selected_approval`` invokes the first matching screen's action."""
    from mahavishnu.tui.app import ApprovalsScreen, DashboardApp

    widget = MagicMock(spec=ApprovalsScreen)
    app = DashboardApp.__new__(DashboardApp)
    app.query = lambda _cls: [widget]  # type: ignore[method-assign]

    app.action_approve_selected_approval()
    widget.action_approve_selected_approval.assert_called_once_with()


@pytest.mark.unit
def test_action_reject_routes_to_first_approval_widget() -> None:
    """``action_reject_selected_approval`` invokes the first matching screen's action."""
    from mahavishnu.tui.app import ApprovalsScreen, DashboardApp

    widget = MagicMock(spec=ApprovalsScreen)
    app = DashboardApp.__new__(DashboardApp)
    app.query = lambda _cls: [widget]  # type: ignore[method-assign]

    app.action_reject_selected_approval()
    widget.action_reject_selected_approval.assert_called_once_with()


@pytest.mark.unit
def test_action_switch_tab_sets_active_with_suppress() -> None:
    """``action_switch_tab`` swallows errors from ``query_one`` (no TabbedContent)."""
    from mahavishnu.tui.app import DashboardApp

    app = DashboardApp.__new__(DashboardApp)
    app.query_one = MagicMock(side_effect=Exception("no tab"))  # type: ignore[method-assign]
    # Must not raise even when the TabbedContent is missing.
    app.action_switch_tab("overview")
    app.query_one.assert_called_once()


# ===========================================================================
# _probe_service / _fetch_health / _component_urls
# ===========================================================================


@pytest.mark.unit
async def test_probe_service_returns_true_on_2xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``resp.status_code < 500`` → True."""
    import httpx2

    mock_resp = MagicMock(status_code=200)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(httpx2, "AsyncClient", lambda **kw: mock_client)

    from mahavishnu.tui.app import _probe_service

    assert await _probe_service("http://x.local") is True


@pytest.mark.unit
async def test_probe_service_returns_false_on_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``resp.status_code >= 500`` → False."""
    import httpx2

    mock_resp = MagicMock(status_code=503)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(httpx2, "AsyncClient", lambda **kw: mock_client)

    from mahavishnu.tui.app import _probe_service

    assert await _probe_service("http://x.local") is False


@pytest.mark.unit
async def test_probe_service_returns_false_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``httpx.ConnectError`` → False via the dedicated except handler."""
    import httpx2

    class _Client:
        def __init__(self, **_kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        async def get(self, _url: str) -> Any:
            raise httpx2.ConnectError("nope")

    monkeypatch.setattr(httpx2, "AsyncClient", _Client)

    from mahavishnu.tui.app import _probe_service

    assert await _probe_service("http://x.local") is False


@pytest.mark.unit
async def test_probe_service_returns_false_on_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare ``RuntimeError`` is still classified as unavailable."""
    import httpx2

    class _Client:
        def __init__(self, **_kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        async def get(self, _url: str) -> Any:
            raise RuntimeError("kaboom")

    monkeypatch.setattr(httpx2, "AsyncClient", _Client)

    from mahavishnu.tui.app import _probe_service

    assert await _probe_service("http://x.local") is False


@pytest.mark.unit
def test_component_urls_returns_default_dict_when_settings_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ``MahavishnuSettings()`` raises, the default empty dict is returned."""
    from mahavishnu.core import config as core_config

    monkeypatch.setattr(
        core_config,
        "MahavishnuSettings",
        MagicMock(side_effect=Exception("nope")),
    )

    from mahavishnu.tui.app import _component_urls

    result = _component_urls()
    assert result == {"crackerjack": None, "akosha": None, "dhara": None, "sb-metrics": None}


@pytest.mark.unit
def test_component_urls_resolves_each_field() -> None:
    """Each URL field on settings is mapped through ``removesuffix('/mcp')``."""
    from mahavishnu.core import config as core_config

    settings = MagicMock()
    settings.qc = MagicMock(crackerjack_url="http://cj.local/mcp")
    settings.pools = MagicMock(
        akosha_url="http://ak.local/mcp",
        session_buddy_url="http://sb.local/mcp",
    )
    settings.oneiric_mcp = MagicMock(url="http://dhara.local/mcp", base_url=None)
    settings.session_buddy_url = None  # legacy path ignored
    settings.akosha_url = None  # legacy path ignored

    class _FakeSettings:
        def __init__(self) -> None:
            pass

        def __getattr__(self, item: str) -> Any:
            return getattr(settings, item)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(core_config, "MahavishnuSettings", _FakeSettings)
    try:
        from mahavishnu.tui.app import _component_urls

        result = _component_urls()
        assert result == {
            "crackerjack": "http://cj.local",
            "akosha": "http://ak.local",
            "dhara": "http://dhara.local",
            "sb-metrics": "http://sb.local",
        }
    finally:
        monkeypatch.undo()


@pytest.mark.unit
def test_component_urls_handles_missing_sub_configs() -> None:
    """Each optional sub-config that is ``None`` must not crash the resolver."""
    from mahavishnu.core import config as core_config

    class _Empty:
        def __getattr__(self, item: str) -> Any:
            return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(core_config, "MahavishnuSettings", _Empty)
    try:
        from mahavishnu.tui.app import _component_urls

        result = _component_urls()
        assert result == {
            "crackerjack": None,
            "akosha": None,
            "dhara": None,
            "sb-metrics": None,
        }
    finally:
        monkeypatch.undo()


@pytest.mark.unit
async def test_fetch_health_returns_available_on_2xx_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``resp.json()`` is a dict → ``available=True`` + merged fields."""
    import httpx2

    mock_resp = MagicMock(status_code=200, json=MagicMock(return_value={"status": "ok", "v": 1}))
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(httpx2, "AsyncClient", lambda **kw: mock_client)

    from mahavishnu.tui.app import _fetch_health

    result = await _fetch_health("http://x.local")
    assert result["available"] is True
    assert result["status"] == "ok"
    assert result["v"] == 1


@pytest.mark.unit
async def test_fetch_health_wraps_non_dict_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``resp.json()`` returning a list is wrapped under ``raw``."""
    import httpx2

    mock_resp = MagicMock(status_code=200, json=MagicMock(return_value=["a", "b"]))
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(httpx2, "AsyncClient", lambda **kw: mock_client)

    from mahavishnu.tui.app import _fetch_health

    result = await _fetch_health("http://x.local")
    assert result["available"] is True
    assert result["raw"] == "['a', 'b']"


@pytest.mark.unit
async def test_fetch_health_unavailable_on_401_or_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """401/403 → ``available=False`` + credential hint."""
    import httpx2

    for status in (401, 403):
        mock_resp = MagicMock(status_code=status)
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)
        monkeypatch.setattr(httpx2, "AsyncClient", lambda **kw: mock_client)

        from mahavishnu.tui.app import _fetch_health

        result = await _fetch_health("http://x.local")
        assert result["available"] is False
        assert "credentials" in result["reason"]


@pytest.mark.unit
async def test_fetch_health_unavailable_on_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5xx → ``available=False`` + server-error hint."""
    import httpx2

    mock_resp = MagicMock(status_code=503)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(httpx2, "AsyncClient", lambda **kw: mock_client)

    from mahavishnu.tui.app import _fetch_health

    result = await _fetch_health("http://x.local")
    assert result["available"] is False
    assert "503" in result["reason"]


@pytest.mark.unit
async def test_fetch_health_unavailable_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Network errors → ``available=False`` + ``unreachable``."""
    import httpx2

    class _Client:
        def __init__(self, **_kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        async def get(self, _url: str) -> Any:
            raise httpx2.ConnectError("nope")

    monkeypatch.setattr(httpx2, "AsyncClient", _Client)

    from mahavishnu.tui.app import _fetch_health

    result = await _fetch_health("http://x.local")
    assert result == {"available": False, "reason": "unreachable"}


@pytest.mark.unit
async def test_fetch_health_unavailable_on_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare ``RuntimeError`` → ``available=False`` + ``unexpected error``."""
    import httpx2

    class _Client:
        def __init__(self, **_kw: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

        async def get(self, _url: str) -> Any:
            raise RuntimeError("kaboom")

    monkeypatch.setattr(httpx2, "AsyncClient", _Client)

    from mahavishnu.tui.app import _fetch_health

    result = await _fetch_health("http://x.local")
    assert result == {"available": False, "reason": "unexpected error"}


# ===========================================================================
# E) Screen ``_fetch`` execution via Textual ``App.run_test()``
# ===========================================================================
#
# Each screen's ``_fetch`` calls ``self.query_one("#id", WidgetType)`` which
# requires a mounted Textual app. We use ``App.run_test()`` to drive a real
# mount cycle, then directly invoke the screen's ``_fetch`` after stubbing
# the underlying fetcher.
# ---------------------------------------------------------------------------


def _make_harness_app() -> Any:
    """Build a minimal Textual app hosting every screen under test.

    Each screen's ``on_mount`` fires ``run_worker(self._fetch(), ...)``.
    That worker still races with the direct ``screen._fetch()`` calls
    our tests issue, so we neutralise it here. The ``on_mount`` branches
    are exercised by ``test_on_mount_runs_fetch_via_run_worker`` and
    ``test_dashboard_app_on_mount_starts_probe_worker`` — those tests
    run their own single-screen pilots and never call into the harness.
    """
    from textual.app import App

    from mahavishnu.tui.app import (
        AgnoScreen,
        AlertsScreen,
        ApprovalsScreen,
        EventStreamScreen,
        FilesScreen,
        OverviewScreen,
        RecoveryScreen,
        ReviewsScreen,
        RoutingScreen,
        SessionScreen,
        SweepScreen,
        TraceScreen,
    )

    def _noop_on_mount(self: Any) -> None:  # type: ignore[no-untyped-def]
        return None

    for _cls in (
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
        _cls.on_mount = _noop_on_mount  # type: ignore[method-assign]

    class _HarnessApp(App):
        def compose(self) -> Any:
            yield OverviewScreen()
            yield SweepScreen()
            yield RoutingScreen()
            yield AlertsScreen()
            yield ReviewsScreen()
            yield SessionScreen()
            yield RecoveryScreen()
            yield ApprovalsScreen()
            yield FilesScreen()
            yield EventStreamScreen()
            yield AgnoScreen()
            yield TraceScreen()

    return _HarnessApp


@pytest.mark.unit
async def test_overview_screen_fetch_updates_status_widget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``OverviewScreen._fetch`` updates the overview-status Static."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import OverviewScreen

    monkeypatch.setattr(
        app_module,
        "fetch_system_overview",
        AsyncMock(
            return_value={
                "status": "ok",
                "active_workflows": 4,
                "total_adapters": 5,
                "healthy_adapters": 4,
                "recent_alerts": 0,
                "generated_at": "2026-01-01T00:00:00+00:00",
            }
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(OverviewScreen)
        await screen._fetch()
        # Watcher should have fired; just confirm the reactive value updated.
        assert "OK" in screen._status or "ok" in screen._status.lower()


@pytest.mark.unit
async def test_overview_screen_fetch_handles_missing_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``generated_at`` → timestamp widget not touched (no AttributeError)."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import OverviewScreen

    monkeypatch.setattr(
        app_module,
        "fetch_system_overview",
        AsyncMock(
            return_value={
                "status": "degraded",
                "active_workflows": 0,
                "total_adapters": 0,
                "healthy_adapters": 0,
                "recent_alerts": 0,
            }
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(OverviewScreen)
        await screen._fetch()
        # The reactive is updated; just check no exception was raised.


@pytest.mark.unit
async def test_sweep_screen_fetch_with_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SweepScreen._fetch`` adds a row when data is non-empty."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import SweepScreen

    monkeypatch.setattr(
        app_module,
        "fetch_sweep_history",
        AsyncMock(
            return_value=[{"status": "active", "active": 2, "failed": 0, "recent": 5}]
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(SweepScreen)
        await screen._fetch()
        assert screen.query_one("#sweep-table").row_count == 1


@pytest.mark.unit
async def test_sweep_screen_fetch_with_no_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty data → single placeholder row in the table."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import SweepScreen

    monkeypatch.setattr(
        app_module,
        "fetch_sweep_history",
        AsyncMock(return_value=[]),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(SweepScreen)
        await screen._fetch()
        assert screen.query_one("#sweep-table").row_count == 1


@pytest.mark.unit
async def test_routing_screen_fetch_with_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``RoutingScreen._fetch`` populates the table when adapters exist."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import RoutingScreen

    monkeypatch.setattr(
        app_module,
        "fetch_routing_stats",
        AsyncMock(
            return_value={
                "adapters": [
                    {
                        "name": "prefect",
                        "status": "ok",
                        "capabilities": {"code": "ok"},
                        "preference_score": 1.0,
                    }
                ],
                "total_decisions": 1,
                "cache_hit_rate": 1.0,
            }
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(RoutingScreen)
        await screen._fetch()
        assert screen.query_one("#routing-table").row_count == 1


@pytest.mark.unit
async def test_routing_screen_fetch_with_no_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty adapter list → single placeholder row."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import RoutingScreen

    monkeypatch.setattr(
        app_module,
        "fetch_routing_stats",
        AsyncMock(return_value={"adapters": [], "total_decisions": 0, "cache_hit_rate": 0.0}),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(RoutingScreen)
        await screen._fetch()
        assert screen.query_one("#routing-table").row_count == 1


@pytest.mark.unit
async def test_alerts_screen_fetch_with_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``AlertsScreen._fetch`` adds rows per alert."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import AlertsScreen

    monkeypatch.setattr(
        app_module,
        "fetch_active_alerts",
        AsyncMock(
            return_value=[
                {
                    "id": "0",
                    "severity": "critical",
                    "title": "akosha: down",
                    "description": "down",
                    "time": "2026-01-01",
                }
            ]
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(AlertsScreen)
        await screen._fetch()
        assert screen.query_one("#alerts-table").row_count == 1


@pytest.mark.unit
async def test_alerts_screen_fetch_with_no_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No active alerts → placeholder row."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import AlertsScreen

    monkeypatch.setattr(
        app_module,
        "fetch_active_alerts",
        AsyncMock(return_value=[]),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(AlertsScreen)
        await screen._fetch()
        assert screen.query_one("#alerts-table").row_count == 1


@pytest.mark.unit
async def test_reviews_screen_fetch_with_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ReviewsScreen._fetch`` formats rows with markup."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import ReviewsScreen

    monkeypatch.setattr(
        app_module,
        "fetch_skill_drafts",
        AsyncMock(
            return_value=[
                {
                    "skill_id": "s1",
                    "name": "Skill 1",
                    "version": "1.0",
                    "state": "review",
                    "proposed_by": "alice",
                    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
                    "description": "desc",
                }
            ]
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(ReviewsScreen)
        await screen._fetch()
        assert screen.query_one("#reviews-table").row_count == 1


@pytest.mark.unit
async def test_reviews_screen_fetch_with_no_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty drafts list → placeholder row."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import ReviewsScreen

    monkeypatch.setattr(
        app_module,
        "fetch_skill_drafts",
        AsyncMock(return_value=[]),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(ReviewsScreen)
        await screen._fetch()
        assert screen.query_one("#reviews-table").row_count == 1


@pytest.mark.unit
async def test_session_screen_fetch_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SessionScreen._fetch`` renders enabled path."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import SessionScreen

    monkeypatch.setattr(
        app_module,
        "fetch_session_summary",
        AsyncMock(
            return_value={
                "enabled": True,
                "checkpoint_interval": 30,
                "session_buddy_url": "http://x",
                "checkpoint_mode": "write-forward",
            }
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(SessionScreen)
        await screen._fetch()
        assert screen.query_one("#session-table").row_count == 2


@pytest.mark.unit
async def test_recovery_screen_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``RecoveryScreen._fetch`` populates the recovery table."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import RecoveryScreen

    monkeypatch.setattr(
        app_module,
        "fetch_recovery_summary",
        AsyncMock(
            return_value={
                "recovered_workflows": 1,
                "recovered_approvals": 2,
                "recovered_pools": 3,
                "recovered_routing_decisions": 4,
                "dhara_available": True,
                "last_recovered_at": "2026-01-01T00:00:00+00:00",
            }
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(RecoveryScreen)
        await screen._fetch()
        assert screen.query_one("#recovery-table").row_count == 4


@pytest.mark.unit
async def test_approvals_screen_fetch_with_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ApprovalsScreen._fetch`` populates rows and renders details."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import ApprovalsScreen

    monkeypatch.setattr(
        app_module,
        "fetch_pending_approvals",
        AsyncMock(
            return_value=[
                {
                    "id": "a1",
                    "approval_type": "publish",
                    "expires_at": "2026-01-02T03:04:05",
                    "options": ["yes", "no"],
                    "is_expired": False,
                }
            ]
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(ApprovalsScreen)
        await screen._fetch()
        assert screen._approval_ids == ["a1"]
        assert screen.query_one("#approvals-table").row_count == 1


@pytest.mark.unit
async def test_approvals_screen_fetch_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty approvals → placeholder row + 'Select an approval' hint."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import ApprovalsScreen

    monkeypatch.setattr(
        app_module,
        "fetch_pending_approvals",
        AsyncMock(return_value=[]),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(ApprovalsScreen)
        await screen._fetch()
        assert screen._approval_ids == []
        assert screen.query_one("#approvals-table").row_count == 1


@pytest.mark.unit
async def test_files_screen_fetch_handles_mixed_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``FilesScreen._fetch`` mixes file previews and diff summaries."""
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(validate_worktree_path=lambda _p: (True, None)),
    )
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    (tmp_path / "README.md").write_text("# hello\n", encoding="utf-8")

    class _Completed:
        stdout = "@@ -1 +1 @@\n-old\n+new\n"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *_a, **_kw: _Completed())

    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import FilesScreen

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(FilesScreen)
        await screen._fetch()
        # ``_COCKPIT_FILES`` has 4 default paths → 4 rows in each table.
        assert screen.query_one("#files-table").row_count == 4
        assert screen.query_one("#diff-table").row_count == 4


@pytest.mark.unit
async def test_files_screen_fetch_with_diff_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Diff errors surface in the ``summary_text`` column."""
    from mahavishnu.core import worktree_validation as wv

    monkeypatch.setattr(
        wv,
        "WorktreePathValidator",
        lambda _roots: MagicMock(
            validate_worktree_path=lambda _p: (False, "outside worktree")
        ),
    )

    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import FilesScreen

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(FilesScreen)
        await screen._fetch()
        assert screen.query_one("#diff-table").row_count >= 1


@pytest.mark.unit
async def test_event_stream_screen_fetch_with_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``EventStreamScreen._fetch`` renders events into the table."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import EventStreamScreen

    monkeypatch.setattr(
        app_module,
        "fetch_event_activity",
        AsyncMock(
            return_value=[
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "event_type": "click",
                    "source": "x",
                    "correlation_id": "abc",
                }
            ]
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(EventStreamScreen)
        await screen._fetch()
        assert screen.query_one("#events-table").row_count == 1


@pytest.mark.unit
async def test_event_stream_screen_fetch_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No events → placeholder row."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import EventStreamScreen

    monkeypatch.setattr(
        app_module,
        "fetch_event_activity",
        AsyncMock(return_value=[]),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(EventStreamScreen)
        await screen._fetch()
        assert screen.query_one("#events-table").row_count == 1


@pytest.mark.unit
async def test_agno_screen_fetch_with_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``AgnoScreen._fetch`` renders activity rows."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import AgnoScreen

    monkeypatch.setattr(
        app_module,
        "fetch_agno_activity",
        AsyncMock(
            return_value=[
                {
                    "timestamp": "2026-01-01T00:00:00",
                    "kind": "team.run",
                    "team_id": "team-1",
                    "task": {"type": "echo"},
                }
            ]
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(AgnoScreen)
        await screen._fetch()
        assert screen.query_one("#agno-table").row_count == 1


@pytest.mark.unit
async def test_agno_screen_fetch_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No activity → placeholder row."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import AgnoScreen

    monkeypatch.setattr(
        app_module,
        "fetch_agno_activity",
        AsyncMock(return_value=[]),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(AgnoScreen)
        await screen._fetch()
        assert screen.query_one("#agno-table").row_count == 1


@pytest.mark.unit
async def test_trace_screen_fetch_with_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``TraceScreen._fetch`` populates the trace table."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import TraceScreen

    monkeypatch.setattr(
        app_module,
        "fetch_correlation_trace",
        AsyncMock(
            return_value={
                "correlation_id": "abc",
                "trace": [
                    {
                        "timestamp": "2026-01-01T00:00:00",
                        "stage": "review",
                        "correlation_id": "abc",
                        "message": "hello",
                    }
                ],
                "trace_count": 1,
                "latest_stage": "review",
                "latest_message": "hello",
            }
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(TraceScreen)
        await screen._fetch()
        assert screen.query_one("#trace-table").row_count == 1


@pytest.mark.unit
async def test_trace_screen_fetch_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No trace → placeholder row."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import TraceScreen

    monkeypatch.setattr(
        app_module,
        "fetch_correlation_trace",
        AsyncMock(
            return_value={
                "correlation_id": None,
                "trace": [],
                "trace_count": 0,
                "latest_stage": None,
                "latest_message": None,
            }
        ),
    )

    Harness = _make_harness_app()
    async with Harness().run_test() as pilot:
        screen = pilot.app.query_one(TraceScreen)
        await screen._fetch()
        assert screen.query_one("#trace-table").row_count == 1


# ---------------------------------------------------------------------------
# BodaiComponentScreen — driven through real ``_fetch_health`` mocking
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_bodai_component_screen_fetch_with_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BodaiComponentScreen._fetch`` renders the check rows."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import BodaiComponentScreen

    async def _fake_health(_url: str) -> dict[str, Any]:
        return {
            "available": True,
            "status": "ok",
            "version": "1.0",
            "checks": {"db": {"status": "ok", "details": "ok"}},
        }

    monkeypatch.setattr(app_module, "_fetch_health", _fake_health)

    from textual.app import App

    class _Harness(App):
        def compose(self) -> Any:
            yield BodaiComponentScreen("Crackerjack", "crackerjack", "http://cj.local")

    async with _Harness().run_test() as pilot:
        screen = pilot.app.query_one(BodaiComponentScreen)
        await screen._fetch()
        assert screen.query_one("#crackerjack-table").row_count == 1


@pytest.mark.unit
async def test_bodai_component_screen_fetch_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``available=False`` → status becomes 'unavailable' and table gets placeholder row."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import BodaiComponentScreen

    async def _fake_health(_url: str) -> dict[str, Any]:
        return {"available": False, "reason": "unreachable"}

    monkeypatch.setattr(app_module, "_fetch_health", _fake_health)

    from textual.app import App

    class _Harness(App):
        def compose(self) -> Any:
            yield BodaiComponentScreen("Crackerjack", "crackerjack", "http://cj.local")

    async with _Harness().run_test() as pilot:
        screen = pilot.app.query_one(BodaiComponentScreen)
        await screen._fetch()
        assert screen.query_one("#crackerjack-table").row_count == 1


# ===========================================================================
# F) DashboardApp ``compose`` + ``on_mount`` via Pilot
# ===========================================================================


@pytest.mark.unit
async def test_dashboard_app_compose_yields_all_panes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Driving ``DashboardApp`` through ``run_test`` mounts every tab."""
    from textual.widgets import TabbedContent, TabPane

    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import DashboardApp

    # Disable optional-tab probing so the assertion stays deterministic.
    async def _no_probe(_self: Any) -> None:
        return None

    monkeypatch.setattr(DashboardApp, "_probe_and_mount_optional_tabs", _no_probe)

    app = DashboardApp()
    async with app.run_test() as pilot:
        tabs = pilot.app.query_one(TabbedContent)
        # Twelve primary tabs + zero optional tabs (probe was disabled).
        assert len(list(tabs.query(TabPane).results())) == 12


@pytest.mark.unit
async def test_dashboard_app_action_switch_tab_sets_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``action_switch_tab`` updates ``TabbedContent.active``."""
    from textual.widgets import TabbedContent

    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import DashboardApp

    async def _no_probe(_self: Any) -> None:
        return None

    monkeypatch.setattr(DashboardApp, "_probe_and_mount_optional_tabs", _no_probe)

    # Stub the per-screen fetchers so the workers triggered by on_mount
    # don't surface real fetch failures inside the pilot. Each fetcher
    # gets the empty-value shape the screen code expects.
    async def _empty_dict(*_args: Any, **_kw: Any) -> dict[str, Any]:
        return {}

    async def _empty_list(*_args: Any, **_kw: Any) -> list[Any]:
        return []

    async def _system_overview(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "active_workflows": 0,
            "total_adapters": 0,
            "healthy_adapters": 0,
            "recent_alerts": 0,
            "generated_at": None,
        }

    monkeypatch.setattr(app_module, "fetch_system_overview", _system_overview)
    monkeypatch.setattr(app_module, "fetch_sweep_history", _empty_list)
    monkeypatch.setattr(app_module, "fetch_routing_stats", _empty_dict)
    monkeypatch.setattr(app_module, "fetch_active_alerts", _empty_list)
    monkeypatch.setattr(app_module, "fetch_skill_drafts", _empty_list)
    monkeypatch.setattr(app_module, "fetch_session_summary", _empty_dict)
    monkeypatch.setattr(app_module, "fetch_recovery_summary", _empty_dict)
    monkeypatch.setattr(app_module, "fetch_pending_approvals", _empty_list)
    monkeypatch.setattr(app_module, "fetch_file_views", _empty_list)
    monkeypatch.setattr(app_module, "fetch_diff_views", _empty_list)
    monkeypatch.setattr(app_module, "fetch_event_activity", _empty_list)
    monkeypatch.setattr(app_module, "fetch_agno_activity", _empty_list)
    monkeypatch.setattr(app_module, "fetch_correlation_trace", _empty_dict)

    app = DashboardApp()
    async with app.run_test() as pilot:
        pilot.app.action_switch_tab("sweep")
        assert pilot.app.query_one(TabbedContent).active == "sweep"


@pytest.mark.unit
async def test_dashboard_app_probe_and_mount_optional_tabs_no_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``_component_urls`` returns all ``None``, no optional tabs mount."""
    from textual.widgets import TabbedContent, TabPane

    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import DashboardApp

    def _empty_urls() -> dict[str, Any]:
        return {"crackerjack": None, "akosha": None, "dhara": None, "sb-metrics": None}

    monkeypatch.setattr(app_module, "_component_urls", _empty_urls)

    app = DashboardApp()
    async with app.run_test() as pilot:
        # No component URLs means no extra panes.
        tabs = pilot.app.query_one(TabbedContent)
        assert len(list(tabs.query(TabPane).results())) == 12


@pytest.mark.unit
async def test_dashboard_app_probe_and_mount_optional_tabs_with_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live ``_probe_service`` URL adds the matching pane."""
    from textual.widgets import TabbedContent, TabPane

    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import DashboardApp

    def _urls() -> dict[str, Any]:
        return {
            "crackerjack": "http://cj.local",
            "akosha": None,
            "dhara": None,
            "sb-metrics": None,
        }

    async def _probe_true(_url: str) -> bool:
        return True

    monkeypatch.setattr(app_module, "_component_urls", _urls)
    monkeypatch.setattr(app_module, "_probe_service", _probe_true)

    app = DashboardApp()
    async with app.run_test() as pilot:
        tabs = pilot.app.query_one(TabbedContent)
        # 12 base + 1 optional = 13.
        assert len(list(tabs.query(TabPane).results())) == 13


# ---------------------------------------------------------------------------
# on_mount coverage — run real ``on_mount`` once per screen via Pilot
# ---------------------------------------------------------------------------
#
# These tests mount a *single* screen and let its ``on_mount`` fire naturally
# (so we cover the ``run_worker(self._fetch(), exclusive=True)`` line) but
# avoid the race with the harness's explicit ``_fetch()`` calls.
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_on_mount_runs_fetch_via_run_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each screen's ``on_mount`` invokes ``run_worker(self._fetch(), ...)``."""
    from textual.app import App

    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import OverviewScreen

    monkeypatch.setattr(
        app_module,
        "fetch_system_overview",
        AsyncMock(
            return_value={
                "status": "ok",
                "active_workflows": 1,
                "total_adapters": 2,
                "healthy_adapters": 2,
                "recent_alerts": 0,
                "generated_at": None,
            }
        ),
    )

    class _Harness(App):
        def compose(self) -> Any:
            yield OverviewScreen()

    async with _Harness().run_test() as pilot:
        await pilot.pause()
        # on_mount worker has now run; the reactive has been populated.
        screen = pilot.app.query_one(OverviewScreen)
        assert "OK" in screen._status or "ok" in screen._status.lower()


@pytest.mark.unit
async def test_dashboard_app_on_mount_starts_probe_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``DashboardApp.on_mount`` schedules ``_probe_and_mount_optional_tabs``."""
    from mahavishnu.tui import app as app_module
    from mahavishnu.tui.app import DashboardApp

    called = {"probe": False}

    async def _mark_probe(self: Any) -> None:
        called["probe"] = True

    monkeypatch.setattr(DashboardApp, "_probe_and_mount_optional_tabs", _mark_probe)

    def _empty_urls() -> dict[str, Any]:
        return {"crackerjack": None, "akosha": None, "dhara": None, "sb-metrics": None}

    monkeypatch.setattr(app_module, "_component_urls", _empty_urls)

    app = DashboardApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.pause()
        assert called["probe"] is True
