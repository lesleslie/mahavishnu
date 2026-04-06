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


class TestDashboardCLI:
    """Verify dashboard CLI command is wired correctly."""

    def test_dashboard_command_registered(self) -> None:
        """The 'dashboard' command should be in the Typer app."""
        from mahavishnu._main_cli import app

        command_names = [cmd.name for cmd in app.registered_commands]
        assert "dashboard" in command_names
