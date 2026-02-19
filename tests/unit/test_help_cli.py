"""Tests for Comprehensive Help CLI Module.

Tests cover:
- General help display
- Command-specific help
- Category help
- All commands reference
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from mahavishnu.cli.help_cli import (
    help_group,
    show_general_help,
    show_command_help,
    show_all_help,
    COMMAND_CATEGORIES,
    _show_category_help,
)


class TestGeneralHelp:
    """Test general help display."""

    def test_show_general_help_displays_categories(self, capsys: pytest.CaptureFixture) -> None:
        """Test general help shows all categories."""
        show_general_help()

        captured = capsys.readouterr()
        output = captured.out

        # Check for key sections
        assert "Mahavishnu" in output
        assert "Quick Start" in output
        assert "Command Categories" in output

        # Check for category names
        assert "Task Management" in output
        assert "Repository Management" in output
        assert "Search & Discovery" in output

    def test_show_general_help_displays_common_workflows(self, capsys: pytest.CaptureFixture) -> None:
        """Test general help shows common workflows."""
        show_general_help()

        captured = capsys.readouterr()
        output = captured.out

        assert "Common Workflows" in output
        assert "Create a task" in output
        assert "List tasks" in output

    def test_show_general_help_displays_shorthands(self, capsys: pytest.CaptureFixture) -> None:
        """Test general help shows shorthand commands."""
        show_general_help()

        captured = capsys.readouterr()
        output = captured.out

        assert "Shorthand Commands" in output
        assert "tc = task create" in output


class TestCommandHelp:
    """Test command-specific help."""

    def test_show_command_help_task_create(self, capsys: pytest.CaptureFixture) -> None:
        """Test help for task create command."""
        show_command_help("task create")

        captured = capsys.readouterr()
        output = captured.out

        assert "task create" in output
        assert "Create a new task" in output
        assert "Usage:" in output
        assert "Examples:" in output

    def test_show_command_help_task_list(self, capsys: pytest.CaptureFixture) -> None:
        """Test help for task list command."""
        show_command_help("task list")

        captured = capsys.readouterr()
        output = captured.out

        assert "task list" in output
        assert "List tasks" in output
        assert "-r, --repository" in output

    def test_show_command_help_includes_shorthand(self, capsys: pytest.CaptureFixture) -> None:
        """Test command help includes shorthand when available."""
        show_command_help("task create")

        captured = capsys.readouterr()
        output = captured.out

        assert "Shorthand:" in output
        assert "mhv tc" in output

    def test_show_command_help_unknown_command(self, capsys: pytest.CaptureFixture) -> None:
        """Test help for unknown command shows error."""
        show_command_help("nonexistent-command")

        captured = capsys.readouterr()
        output = captured.out

        assert "Unknown command" in output

    def test_show_command_help_mcp_start(self, capsys: pytest.CaptureFixture) -> None:
        """Test help for MCP start command."""
        show_command_help("mcp start")

        captured = capsys.readouterr()
        output = captured.out

        assert "mcp start" in output
        assert "Start the MCP server" in output


class TestAllHelp:
    """Test complete reference display."""

    def test_show_all_help_displays_all_categories(self, capsys: pytest.CaptureFixture) -> None:
        """Test --all shows all categories."""
        show_all_help()

        captured = capsys.readouterr()
        output = captured.out

        for category in COMMAND_CATEGORIES:
            assert category in output

    def test_show_all_help_displays_all_commands(self, capsys: pytest.CaptureFixture) -> None:
        """Test --all shows all commands."""
        show_all_help()

        captured = capsys.readouterr()
        output = captured.out

        for category, info in COMMAND_CATEGORIES.items():
            for cmd_name in info["commands"]:
                assert cmd_name in output


class TestCategoryHelp:
    """Test category-specific help."""

    def test_show_category_help_task_management(self, capsys: pytest.CaptureFixture) -> None:
        """Test help for task management category."""
        _show_category_help("Task Management")

        captured = capsys.readouterr()
        output = captured.out

        assert "Task Management" in output
        assert "task create" in output
        assert "task list" in output
        assert "task update" in output

    def test_show_category_help_repository_management(self, capsys: pytest.CaptureFixture) -> None:
        """Test help for repository management category."""
        _show_category_help("Repository Management")

        captured = capsys.readouterr()
        output = captured.out

        assert "Repository Management" in output
        assert "list-repos" in output

    def test_show_category_help_unknown(self, capsys: pytest.CaptureFixture) -> None:
        """Test help for unknown category."""
        _show_category_help("Unknown Category")

        captured = capsys.readouterr()
        output = captured.out

        assert "Unknown category" in output


class TestHelpGroupCLI:
    """Test help group CLI commands."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create CLI runner."""
        return CliRunner()

    def test_help_group_default(self, runner: CliRunner) -> None:
        """Test help command without arguments shows general help."""
        result = runner.invoke(help_group, [])

        assert result.exit_code == 0
        assert "Mahavishnu" in result.output
        assert "Quick Start" in result.output

    def test_help_group_with_command(self, runner: CliRunner) -> None:
        """Test help command with specific command."""
        result = runner.invoke(help_group, ["task create"])

        assert result.exit_code == 0
        assert "task create" in result.output
        assert "Create a new task" in result.output

    def test_help_group_all_flag(self, runner: CliRunner) -> None:
        """Test help --all shows complete reference."""
        result = runner.invoke(help_group, ["--all"])

        assert result.exit_code == 0
        assert "Complete Command Reference" in result.output

    def test_help_tasks_subcommand(self, runner: CliRunner) -> None:
        """Test help tasks shows task management help."""
        from mahavishnu.cli.help_cli import help_tasks
        result = runner.invoke(help_tasks, [])

        assert result.exit_code == 0
        assert "Task Management" in result.output

    def test_help_repos_subcommand(self, runner: CliRunner) -> None:
        """Test help repos shows repository management help."""
        from mahavishnu.cli.help_cli import help_repos
        result = runner.invoke(help_repos, [])

        assert result.exit_code == 0
        assert "Repository Management" in result.output

    def test_help_search_subcommand(self, runner: CliRunner) -> None:
        """Test help search shows search help."""
        from mahavishnu.cli.help_cli import help_search
        result = runner.invoke(help_search, [])

        assert result.exit_code == 0
        assert "Search & Discovery" in result.output

    def test_help_mcp_subcommand(self, runner: CliRunner) -> None:
        """Test help mcp shows MCP help."""
        from mahavishnu.cli.help_cli import help_mcp
        result = runner.invoke(help_mcp, [])

        assert result.exit_code == 0
        assert "MCP Server" in result.output

    def test_help_pools_subcommand(self, runner: CliRunner) -> None:
        """Test help pools shows pool management help."""
        from mahavishnu.cli.help_cli import help_pools
        result = runner.invoke(help_pools, [])

        assert result.exit_code == 0
        assert "Worker & Pool Management" in result.output

    def test_help_terminal_subcommand(self, runner: CliRunner) -> None:
        """Test help terminal shows terminal management help."""
        from mahavishnu.cli.help_cli import help_terminal
        result = runner.invoke(help_terminal, [])

        assert result.exit_code == 0
        assert "Terminal Management" in result.output


class TestCommandCategories:
    """Test command categories data structure."""

    def test_all_categories_have_description(self) -> None:
        """Test all categories have descriptions."""
        for category, info in COMMAND_CATEGORIES.items():
            assert "description" in info
            assert info["description"]

    def test_all_commands_have_usage(self) -> None:
        """Test all commands have usage information."""
        for category, info in COMMAND_CATEGORIES.items():
            for cmd_name, cmd_info in info["commands"].items():
                assert "usage" in cmd_info, f"{cmd_name} missing usage"
                assert "description" in cmd_info, f"{cmd_name} missing description"

    def test_all_commands_have_examples(self) -> None:
        """Test all commands have examples."""
        for category, info in COMMAND_CATEGORIES.items():
            for cmd_name, cmd_info in info["commands"].items():
                assert "examples" in cmd_info, f"{cmd_name} missing examples"
                assert len(cmd_info["examples"]) > 0, f"{cmd_name} has no examples"

    def test_task_commands_have_shorthands(self) -> None:
        """Test task management commands have shorthands."""
        task_commands = COMMAND_CATEGORIES["Task Management"]["commands"]

        for cmd_name, cmd_info in task_commands.items():
            if cmd_name != "task status":  # status is itself a shorthand
                assert "shorthand" in cmd_info, f"{cmd_name} missing shorthand"
