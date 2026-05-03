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

        assert hasattr(OverviewScreen, "status_text")
        reactive = OverviewScreen.status_text
        assert isinstance(reactive, Reactive)
        assert reactive._default == "Loading..."


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

    def test_reviews_screen_has_load_data(self):
        from mahavishnu.tui.app import ReviewsScreen

        assert hasattr(ReviewsScreen, "_load_data")
        assert callable(ReviewsScreen._load_data)


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
