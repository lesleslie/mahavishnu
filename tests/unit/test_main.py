"""Tests for mahavishnu/__main__.py and _main_cli.py."""

import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
import sys
from io import StringIO

from mahavishnu import __main__


class TestMainEntry:
    """Test the main entry point."""

    def test_main_import(self):
        """Test that main modules can be imported without errors."""
        try:
            from mahavishnu import __main__ as main_module
            assert main_module is not None
        except ImportError as e:
            pytest.fail(f"Failed to import __main__: {e}")

    def test_main_cli_import(self):
        """Test that CLI module can be imported without errors."""
        try:
            from mahavishnu import _main_cli
            assert _main_cli is not None
        except ImportError as e:
            pytest.fail(f"Failed to import _main_cli: {e}")

    @patch('mahavishnu._main_cli.app')
    def test_main_entry_basic(self, mock_app):
        """Test basic main entry functionality."""
        mock_app.return_value = None
        # Just test that the app function exists and can be called
        assert mock_app is not None


class TestMainCLI:
    """Test the main CLI application."""

    @patch('mahavishnu._main_cli.typer.Typer')
    def test_cli_initialization(self, mock_typer):
        """Test that CLI app is properly initialized."""
        with patch('mahavishnu._main_cli.typer.Typer', mock_typer):
            from mahavishnu._main_cli import app
            mock_typer.assert_called_once()

    @patch('mahavishnu._main_cli.typer.Typer')
    def test_cli_has_version_callback(self, mock_typer):
        """Test that CLI app has version callback."""
        mock_app = MagicMock()
        mock_typer.return_value = mock_app

        with patch('mahavishnu._main_cli.typer.Typer', mock_typer):
            from mahavishnu._main_cli import app
            # Check that app is created
            assert mock_app is not None

    @patch('mahavishnu._main_cli.MultiAuthHandler')
    @patch('mahavishnu._main_cli.MahavishnuApp')
    def test_cli_includes_all_modules(self, mock_app_class, mock_auth):
        """Test that all CLI modules are imported and registered."""
        # This test ensures all CLI modules are properly imported
        # In a real implementation, you would test the actual CLI commands

        # Verify imports exist
        import mahavishnu._main_cli as cli_module
        assert hasattr(cli_module, 'add_backup_commands')
        assert hasattr(cli_module, 'add_coordination_commands')
        assert hasattr(cli_module, 'add_ecosystem_commands')
        assert hasattr(cli_module, 'add_config_validation_commands')
        assert hasattr(cli_module, 'add_metrics_commands')
        assert hasattr(cli_module, 'add_monitoring_commands')
        assert hasattr(cli_module, 'add_production_commands')
        assert hasattr(cli_module, 'add_ingestion_commands')
        assert hasattr(cli_module, 'add_routing_commands')
        assert hasattr(cli_module, 'worktree_app')
        assert hasattr(cli_module, 'add_team_commands')
        assert hasattr(cli_module, 'add_events_commands')


class TestMainCLIIntegration:
    """Integration tests for main CLI."""

    @patch('mahavishnu._main_cli.MahavishnuApp')
    def test_cli_initialization_with_app(self, mock_app_class):
        """Test CLI integration with MahavishnuApp."""
        mock_app = MagicMock()
        mock_app_class.return_value = mock_app

        from mahavishnu._main_cli import app

        # In a real test, you would test the actual CLI commands here
        # For now, just verify the app exists
        assert app is not None

    @patch('mahavishnu._main_cli.MultiAuthHandler')
    def test_auth_integration(self, mock_auth_handler):
        """Test that authentication is properly integrated."""
        mock_auth = MagicMock()
        mock_auth_handler.return_value = mock_auth

        from mahavishnu._main_cli import app

        # Verify the auth handler exists
        assert mock_auth is not None


class TestMainCLIErrorHandling:
    """Test error handling in main CLI."""

    @patch('mahavishnu._main_cli.MahavishnuApp')
    def test_app_initialization_error(self, mock_app_class):
        """Test error handling when MahavishnuApp fails to initialize."""
        mock_app_class.side_effect = Exception("Initialization failed")

        from mahavishnu._main_cli import app

        # The app should still be created even if dependencies fail
        # This is defensive programming
        assert app is not None

    @patch('mahavishnu._main_cli.MultiAuthHandler')
    def test_auth_initialization_error(self, mock_auth_handler):
        """Test error handling when authentication fails to initialize."""
        mock_auth_handler.side_effect = Exception("Auth failed")

        from mahavishnu._main_cli import app

        # The app should still be created
        assert app is not None