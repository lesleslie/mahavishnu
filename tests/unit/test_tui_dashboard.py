"""Tests for Mahavishnu TUI dashboard screens and widget structure.

Uses widget tree assertions (no headless rendering required).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Conditional import — textual may not be installed
# ---------------------------------------------------------------------------

_textual_available = True
try:
    from textual.app import App
except ImportError:
    _textual_available = False

pytestmark = pytest.mark.skipif(
    not _textual_available,
    reason="textual not installed (pip install mahavishnu[tui])",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDashboardAppStructure:
    """Verify the dashboard app class structure without running it."""

    def test_app_import(self) -> None:
        from mahavishnu.tui.app import DashboardApp, MahavishnuDashboard

        assert DashboardApp is not None
        assert MahavishnuDashboard is DashboardApp

    def test_app_is_textual_app(self) -> None:
        from mahavishnu.tui.app import DashboardApp

        assert issubclass(DashboardApp, App)

    def test_app_has_bindings(self) -> None:
        from mahavishnu.tui.app import DashboardApp

        binding_keys = [b.key for b in DashboardApp.BINDINGS]
        assert "q" in binding_keys  # quit
        assert "1" in binding_keys  # overview tab
        assert "2" in binding_keys  # sweep tab
        assert "3" in binding_keys  # routing tab
        assert "4" in binding_keys  # alerts tab
        assert "5" in binding_keys  # reviews tab
        assert "6" in binding_keys  # recovery tab
        assert "7" in binding_keys  # session tab
        assert "8" in binding_keys  # approvals tab
        assert "9" in binding_keys  # files tab
        assert "0" in binding_keys  # events tab
        assert "g" in binding_keys  # agno tab
        assert "c" in binding_keys  # trace tab
        assert "a" in binding_keys  # approve selected approval
        assert "x" in binding_keys  # reject selected approval

    def test_app_title(self) -> None:
        from mahavishnu.tui.app import DashboardApp

        assert DashboardApp.TITLE == "Mahavishnu Dashboard"

    def test_app_has_css(self) -> None:
        from mahavishnu.tui.app import DashboardApp

        assert DashboardApp.CSS is not None
        assert len(DashboardApp.CSS) > 0


class TestScreenModules:
    """Verify screen classes exist and are importable."""

    def test_overview_screen(self) -> None:
        from mahavishnu.tui.app import OverviewScreen

        assert OverviewScreen is not None

    def test_sweep_screen(self) -> None:
        from mahavishnu.tui.app import SweepScreen

        assert SweepScreen is not None

    def test_routing_screen(self) -> None:
        from mahavishnu.tui.app import RoutingScreen

        assert RoutingScreen is not None

    def test_alerts_screen(self) -> None:
        from mahavishnu.tui.app import AlertsScreen

        assert AlertsScreen is not None

    def test_reviews_screen(self) -> None:
        from mahavishnu.tui.app import ReviewsScreen

        assert ReviewsScreen is not None

    def test_session_screen(self) -> None:
        from mahavishnu.tui.app import SessionScreen

        assert SessionScreen is not None

    def test_recovery_screen(self) -> None:
        from mahavishnu.tui.app import RecoveryScreen

        assert RecoveryScreen is not None

    def test_approvals_screen(self) -> None:
        from mahavishnu.tui.app import ApprovalsScreen

        assert ApprovalsScreen is not None

    def test_approvals_screen_actions(self) -> None:
        from mahavishnu.tui.app import ApprovalsScreen

        assert hasattr(ApprovalsScreen, "action_approve_selected_approval")
        assert hasattr(ApprovalsScreen, "action_reject_selected_approval")

    def test_files_screen(self) -> None:
        from mahavishnu.tui.app import FilesScreen

        assert FilesScreen is not None

    def test_event_stream_screen(self) -> None:
        from mahavishnu.tui.app import EventStreamScreen

        assert EventStreamScreen is not None

    def test_agno_screen(self) -> None:
        from mahavishnu.tui.app import AgnoScreen

        assert AgnoScreen is not None

    def test_trace_screen(self) -> None:
        from mahavishnu.tui.app import TraceScreen

        assert TraceScreen is not None


class TestDataFetchers:
    """Verify data-fetching helpers return expected shapes."""

    @pytest.mark.asyncio
    async def test_fetch_system_overview(self) -> None:
        from mahavishnu.tui.app import fetch_system_overview

        data = await fetch_system_overview()
        assert "status" in data
        assert "active_workflows" in data
        assert "total_adapters" in data

    @pytest.mark.asyncio
    async def test_fetch_sweep_history(self) -> None:
        from mahavishnu.tui.app import fetch_sweep_history

        data = await fetch_sweep_history()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_fetch_routing_stats(self) -> None:
        from mahavishnu.tui.app import fetch_routing_stats

        data = await fetch_routing_stats()
        assert "adapters" in data
        assert "total_decisions" in data

    @pytest.mark.asyncio
    async def test_fetch_active_alerts(self) -> None:
        from mahavishnu.tui.app import fetch_active_alerts

        data = await fetch_active_alerts()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_fetch_skill_drafts_uses_registry_when_available(self, monkeypatch) -> None:
        from types import SimpleNamespace

        from mahavishnu.tui import app as tui_app

        class _FakeRegistry:
            def list_active(self):
                return [
                    SimpleNamespace(
                        skill_id="skill-1",
                        version="1.0.0",
                        state="active",
                        body="# Skill 1\nBody",
                        activation=SimpleNamespace(activated_by="ci", activated_at=tui_app.datetime.now()),
                        review=None,
                    )
                ]

        monkeypatch.setattr(
            "mahavishnu.core.context.get_app_from_context",
            lambda: SimpleNamespace(skill_registry=_FakeRegistry()),
        )

        data = await tui_app.fetch_skill_drafts()
        assert len(data) == 1
        assert data[0]["skill_id"] == "skill-1"
        assert data[0]["proposed_by"] == "ci"

    @pytest.mark.asyncio
    async def test_fetch_session_summary(self) -> None:
        from mahavishnu.tui.app import fetch_session_summary

        data = await fetch_session_summary()
        assert "enabled" in data
        assert "checkpoint_interval" in data
        assert "session_buddy_url" in data

    @pytest.mark.asyncio
    async def test_fetch_recovery_summary(self) -> None:
        from mahavishnu.tui.app import fetch_recovery_summary

        data = await fetch_recovery_summary()
        assert "recovered_workflows" in data
        assert "recovered_approvals" in data
        assert "dhara_available" in data

    @pytest.mark.asyncio
    async def test_fetch_pending_approvals(self) -> None:
        from mahavishnu.tui.app import fetch_pending_approvals

        data = await fetch_pending_approvals()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_fetch_event_activity(self) -> None:
        from mahavishnu.tui.app import fetch_event_activity

        data = await fetch_event_activity()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_fetch_agno_activity(self) -> None:
        from mahavishnu.tui.app import fetch_agno_activity

        data = await fetch_agno_activity()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_fetch_correlation_trace(self) -> None:
        from mahavishnu.tui.app import fetch_correlation_trace

        data = await fetch_correlation_trace()
        assert "trace" in data
        assert "trace_count" in data
        assert "latest_stage" in data

    @pytest.mark.asyncio
    async def test_forward_approval_request(self, monkeypatch) -> None:
        from types import SimpleNamespace

        from mahavishnu.tui.app import forward_approval_request

        class _FakeApp:
            def request_approval(self, **kwargs):
                return {"status": "pending", "approval_id": "approval-1", **kwargs}

        monkeypatch.setattr(
            "mahavishnu.core.context.get_app_from_context",
            lambda: SimpleNamespace(request_approval=_FakeApp().request_approval),
        )

        result = await forward_approval_request(
            approval_type="version_bump",
            context={"current_version": "1.0.0"},
        )
        assert result["status"] == "pending"
        assert result["approval_type"] == "version_bump"

    @pytest.mark.asyncio
    async def test_forward_approval_response(self, monkeypatch) -> None:
        from types import SimpleNamespace

        from mahavishnu.tui.app import forward_approval_response

        class _FakeApp:
            def respond_to_approval(self, **kwargs):
                return {"status": "ok", "request_id": kwargs["request_id"], **kwargs}

        monkeypatch.setattr(
            "mahavishnu.core.context.get_app_from_context",
            lambda: SimpleNamespace(respond_to_approval=_FakeApp().respond_to_approval),
        )

        result = await forward_approval_response(
            request_id="approval-1",
            approved=True,
            selected_option=0,
        )
        assert result["status"] == "ok"
        assert result["request_id"] == "approval-1"

    def test_app_approval_actions_exist(self) -> None:
        from mahavishnu.tui.app import DashboardApp

        assert hasattr(DashboardApp, "action_approve_selected_approval")
        assert hasattr(DashboardApp, "action_reject_selected_approval")

    @pytest.mark.asyncio
    async def test_fetch_file_views(self) -> None:
        from mahavishnu.tui.app import fetch_file_views

        data = await fetch_file_views()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "path" in data[0]

    @pytest.mark.asyncio
    async def test_fetch_diff_views(self) -> None:
        from mahavishnu.tui.app import fetch_diff_views

        data = await fetch_diff_views()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "path" in data[0]

    @pytest.mark.asyncio
    async def test_fetch_skill_drafts(self) -> None:
        from mahavishnu.tui.app import fetch_skill_drafts

        data = await fetch_skill_drafts()
        assert isinstance(data, list)
        for draft in data:
            assert "skill_id" in draft
            assert "name" in draft
            assert "version" in draft
            assert "state" in draft
            assert "proposed_by" in draft
            assert "created_at" in draft

    @pytest.mark.asyncio
    async def test_fetch_skill_drafts_returns_list_no_mock(self) -> None:
        """fetch_skill_drafts returns a list (no hardcoded mock data)."""
        from mahavishnu.tui.app import fetch_skill_drafts

        data = await fetch_skill_drafts()
        assert isinstance(data, list)
        # No mock data — returns empty when no registry is available
        assert all("skill_id" in d for d in data)


class TestDashboardCLI:
    """Verify dashboard CLI command is wired correctly."""

    def test_dashboard_command_registered(self) -> None:
        """The 'dashboard' command should be in the Typer app."""
        from mahavishnu._main_cli import app

        command_names = [cmd.name for cmd in app.registered_commands]
        assert "dashboard" in command_names


@pytest.mark.skipif(not _textual_available, reason="textual not installed")
class TestOverviewScreenCompose:
    """Test OverviewScreen widget composition."""

    def test_compose_yields_widgets(self):
        from textual.containers import VerticalScroll

        from mahavishnu.tui.app import OverviewScreen

        assert issubclass(OverviewScreen, VerticalScroll)

    def test_overview_screen_has_status_text_reactive(self):
        from textual.reactive import Reactive

        from mahavishnu.tui.app import OverviewScreen

        assert hasattr(OverviewScreen, "_status")
        reactive = OverviewScreen._status
        assert isinstance(reactive, Reactive)


@pytest.mark.skipif(not _textual_available, reason="textual not installed")
class TestSweepScreenCompose:
    """Test SweepScreen widget composition."""

    def test_compose_yields_table(self):
        from textual.containers import VerticalScroll

        from mahavishnu.tui.app import SweepScreen

        assert issubclass(SweepScreen, VerticalScroll)


@pytest.mark.skipif(not _textual_available, reason="textual not installed")
class TestRoutingScreenCompose:
    """Test RoutingScreen widget composition."""

    def test_compose_yields_table(self):
        from textual.containers import VerticalScroll

        from mahavishnu.tui.app import RoutingScreen

        assert issubclass(RoutingScreen, VerticalScroll)


@pytest.mark.skipif(not _textual_available, reason="textual not installed")
class TestAlertsScreenCompose:
    """Test AlertsScreen widget composition."""

    def test_compose_yields_table(self):
        from textual.containers import VerticalScroll

        from mahavishnu.tui.app import AlertsScreen

        assert issubclass(AlertsScreen, VerticalScroll)


@pytest.mark.skipif(not _textual_available, reason="textual not installed")
class TestReviewsScreenCompose:
    """Test ReviewsScreen widget composition."""

    def test_compose_yields_table(self):
        from textual.containers import VerticalScroll

        from mahavishnu.tui.app import ReviewsScreen

        assert issubclass(ReviewsScreen, VerticalScroll)

    def test_reviews_screen_has_fetch(self):
        from mahavishnu.tui.app import ReviewsScreen

        assert hasattr(ReviewsScreen, "_fetch")
        assert callable(ReviewsScreen._fetch)


@pytest.mark.skipif(not _textual_available, reason="textual not installed")
class TestDashboardAppCompose:
    """Test DashboardApp compose and actions."""

    def test_action_switch_tab_valid(self):
        from mahavishnu.tui.app import DashboardApp

        app = DashboardApp()
        app.action_switch_tab("sweep")  # Should not raise

    def test_action_switch_tab_invalid(self):
        from mahavishnu.tui.app import DashboardApp

        app = DashboardApp()
        app.action_switch_tab("nonexistent")  # Should not raise

    def test_app_compose_structure(self):
        from mahavishnu.tui.app import DashboardApp

        app = DashboardApp()
        # Verify the app can be instantiated (compose is deferred)
        assert app.TITLE == "Mahavishnu Dashboard"
        assert len(app.BINDINGS) >= 5

    def test_action_switch_tab_reviews(self):
        from mahavishnu.tui.app import DashboardApp

        app = DashboardApp()
        app.action_switch_tab("reviews")  # Should not raise

    def test_action_switch_tab_recovery(self):
        from mahavishnu.tui.app import DashboardApp

        app = DashboardApp()
        app.action_switch_tab("recovery")  # Should not raise

    def test_action_switch_tab_session(self):
        from mahavishnu.tui.app import DashboardApp

        app = DashboardApp()
        app.action_switch_tab("session")  # Should not raise

    def test_action_switch_tab_trace(self):
        from mahavishnu.tui.app import DashboardApp

        app = DashboardApp()
        app.action_switch_tab("trace")  # Should not raise
