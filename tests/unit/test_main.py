"""Tests for mahavishnu/_main_cli.py — CLI app structure and command registration."""

import pytest
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner

import mahavishnu._main_cli as cli_module


runner = CliRunner()


class TestAppStructure:
    """Test the Typer app is properly configured."""

    def test_app_is_typer_instance(self):
        import typer
        assert isinstance(cli_module.app, typer.Typer)

    def test_app_name(self):
        assert cli_module.app.info.name == "mahavishnu"

    def test_worktree_subapp_registered(self):
        registered_names = [tp.name for tp in cli_module.app.registered_groups if tp.typer_instance]
        assert "worktree" in registered_names

    def test_mcp_subapp_registered(self):
        registered_names = [tp.name for tp in cli_module.app.registered_groups if tp.typer_instance]
        assert "mcp" in registered_names

    def test_workflow_subapp_registered(self):
        registered_names = [tp.name for tp in cli_module.app.registered_groups if tp.typer_instance]
        assert "workflow" in registered_names

    def test_pool_subapp_registered(self):
        registered_names = [tp.name for tp in cli_module.app.registered_groups if tp.typer_instance]
        assert "pool" in registered_names

    def test_workers_subapp_registered(self):
        registered_names = [tp.name for tp in cli_module.app.registered_groups if tp.typer_instance]
        assert "workers" in registered_names

    def test_terminal_subapp_registered(self):
        registered_names = [tp.name for tp in cli_module.app.registered_groups if tp.typer_instance]
        assert "terminal" in registered_names

    def test_ecosystem_subapp_registered(self):
        registered_names = [tp.name for tp in cli_module.app.registered_groups if tp.typer_instance]
        assert "ecosystem" in registered_names


class TestCLICommandRegistration:
    """Test that all CLI command modules are imported and registered."""

    def test_add_backup_commands(self):
        assert hasattr(cli_module, "add_backup_commands")

    def test_add_coordination_commands(self):
        assert hasattr(cli_module, "add_coordination_commands")

    def test_add_ecosystem_commands(self):
        assert hasattr(cli_module, "add_ecosystem_commands")

    def test_add_config_validation_commands(self):
        assert hasattr(cli_module, "add_config_validation_commands")

    def test_add_metrics_commands(self):
        assert hasattr(cli_module, "add_metrics_commands")

    def test_add_monitoring_commands(self):
        assert hasattr(cli_module, "add_monitoring_commands")

    def test_add_production_commands(self):
        assert hasattr(cli_module, "add_production_commands")

    def test_add_ingestion_commands(self):
        assert hasattr(cli_module, "add_ingestion_commands")

    def test_add_routing_commands(self):
        assert hasattr(cli_module, "add_routing_commands")

    def test_worktree_app(self):
        assert hasattr(cli_module, "worktree_app")

    def test_add_team_commands(self):
        assert hasattr(cli_module, "add_team_commands")

    def test_add_events_commands(self):
        assert hasattr(cli_module, "add_events_commands")


class TestMCPDefaults:
    """Test MCP server default configuration values."""

    def test_default_host(self):
        assert cli_module.DEFAULT_MCP_HOST == "127.0.0.1"

    def test_default_port(self):
        assert cli_module.DEFAULT_MCP_PORT == 8680


class TestCLIRunnerHelp:
    """Test that CLI help text renders without errors."""

    def test_root_help(self):
        result = runner.invoke(cli_module.app, ["--help"])
        assert result.exit_code == 0
        assert "mahavishnu" in result.output.lower()

    def test_mcp_help(self):
        result = runner.invoke(cli_module.app, ["mcp", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "stop" in result.output
        assert "health" in result.output

    def test_workflow_help(self):
        result = runner.invoke(cli_module.app, ["workflow", "--help"])
        assert result.exit_code == 0
        assert "sweep" in result.output

    def test_pool_help(self):
        result = runner.invoke(cli_module.app, ["pool", "--help"])
        assert result.exit_code == 0
        assert "spawn" in result.output
        assert "list" in result.output

    def test_workers_help(self):
        result = runner.invoke(cli_module.app, ["workers", "--help"])
        assert result.exit_code == 0
        assert "spawn" in result.output
        assert "execute" in result.output
