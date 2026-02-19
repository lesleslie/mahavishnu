"""Tests for Task CLI Module.

Tests cover:
- Shell completion functions
- Due date parsing
- Command structure
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from click.testing import CliRunner

from mahavishnu.task_cli import (
    complete_repository,
    complete_status,
    complete_priority,
    complete_task_id,
    complete_tag,
    parse_due_date,
    task_group,
    generate_completion_script,
)


class TestCompletionFunctions:
    """Test shell completion functions."""

    def test_complete_repository_from_env(self) -> None:
        """Test repository completion from environment."""
        with patch.dict("os.environ", {"MAHAVISHNU_REPOS": "custom-repo,another-repo"}):
            result = complete_repository(
                ctx=MagicMock(), args=[], incomplete="custom"
            )
            assert "custom-repo" in result

    def test_complete_repository_common_repos(self) -> None:
        """Test repository completion includes common repos."""
        result = complete_repository(ctx=MagicMock(), args=[], incomplete="mah")
        assert "mahavishnu" in result

    def test_complete_repository_no_match(self) -> None:
        """Test repository completion with no match."""
        result = complete_repository(ctx=MagicMock(), args=[], incomplete="xyz")
        assert result == []

    def test_complete_status(self) -> None:
        """Test status completion."""
        result = complete_status(ctx=MagicMock(), args=[], incomplete="pend")
        assert "pending" in result

    def test_complete_status_partial(self) -> None:
        """Test status completion with partial match."""
        result = complete_status(ctx=MagicMock(), args=[], incomplete="in")
        assert "in_progress" in result

    def test_complete_priority(self) -> None:
        """Test priority completion."""
        result = complete_priority(ctx=MagicMock(), args=[], incomplete="hi")
        assert "high" in result

    def test_complete_priority_all(self) -> None:
        """Test all priorities returned for empty input."""
        result = complete_priority(ctx=MagicMock(), args=[], incomplete="")
        assert len(result) == 4
        assert "low" in result
        assert "medium" in result
        assert "high" in result
        assert "critical" in result

    def test_complete_task_id(self) -> None:
        """Test task ID completion returns empty (database not available)."""
        result = complete_task_id(ctx=MagicMock(), args=[], incomplete="task")
        assert result == []

    def test_complete_tag_common(self) -> None:
        """Test tag completion with common tags."""
        result = complete_tag(ctx=MagicMock(), args=[], incomplete="bug")
        assert "bug" in result

    def test_complete_tag_partial(self) -> None:
        """Test tag completion with partial match."""
        result = complete_tag(ctx=MagicMock(), args=[], incomplete="back")
        assert "backend" in result

    def test_complete_tag_no_match(self) -> None:
        """Test tag completion with no match."""
        result = complete_tag(ctx=MagicMock(), args=[], incomplete="xyz")
        assert result == []


class TestParseDueDate:
    """Test due date parsing."""

    def test_parse_today(self) -> None:
        """Test parsing 'today'."""
        result = parse_due_date("today")
        assert result is not None
        assert result.hour == 23
        assert result.minute == 59

    def test_parse_tomorrow(self) -> None:
        """Test parsing 'tomorrow'."""
        result = parse_due_date("tomorrow")
        assert result is not None
        now = datetime.now()
        expected = (now + timedelta(days=1)).date()
        assert result.date() == expected

    def test_parse_next_week(self) -> None:
        """Test parsing 'next week'."""
        result = parse_due_date("next week")
        assert result is not None
        now = datetime.now()
        expected = (now + timedelta(weeks=1)).date()
        assert result.date() == expected

    def test_parse_next_month(self) -> None:
        """Test parsing 'next month'."""
        result = parse_due_date("next month")
        assert result is not None
        now = datetime.now()
        expected = (now + timedelta(days=30)).date()
        assert result.date() == expected

    def test_parse_in_n_days(self) -> None:
        """Test parsing 'in N days'."""
        result = parse_due_date("in 5 days")
        assert result is not None
        now = datetime.now()
        expected = (now + timedelta(days=5)).date()
        assert result.date() == expected

    def test_parse_in_n_weeks(self) -> None:
        """Test parsing 'in N weeks'."""
        result = parse_due_date("in 2 weeks")
        assert result is not None
        now = datetime.now()
        expected = (now + timedelta(weeks=2)).date()
        assert result.date() == expected

    def test_parse_iso_date(self) -> None:
        """Test parsing ISO date format."""
        result = parse_due_date("2026-12-31")
        assert result is not None
        assert result.year == 2026
        assert result.month == 12
        assert result.day == 31

    def test_parse_invalid(self) -> None:
        """Test parsing invalid date returns None."""
        result = parse_due_date("not a date")
        assert result is None

    def test_parse_case_insensitive(self) -> None:
        """Test parsing is case insensitive."""
        result = parse_due_date("TOMORROW")
        assert result is not None
        now = datetime.now()
        expected = (now + timedelta(days=1)).date()
        assert result.date() == expected


class TestTaskGroup:
    """Test task CLI group."""

    def test_group_exists(self) -> None:
        """Test task group exists."""
        assert task_group is not None
        assert task_group.name == "task"

    def test_group_has_commands(self) -> None:
        """Test task group has expected commands."""
        commands = list(task_group.commands.keys())
        assert "create" in commands
        assert "list" in commands
        assert "update" in commands
        assert "delete" in commands
        assert "status" in commands

    def test_create_command_structure(self) -> None:
        """Test create command has correct options."""
        create_cmd = task_group.commands["create"]
        params = {p.name for p in create_cmd.params}
        assert "title" in params
        assert "repository" in params
        assert "description" in params
        assert "priority" in params
        assert "status" in params
        assert "assignee" in params
        assert "tag" in params
        assert "due" in params

    def test_list_command_structure(self) -> None:
        """Test list command has correct options."""
        list_cmd = task_group.commands["list"]
        params = {p.name for p in list_cmd.params}
        assert "repository" in params
        assert "status" in params
        assert "priority" in params
        assert "assignee" in params
        assert "search" in params
        assert "limit" in params
        assert "tag" in params

    def test_update_command_structure(self) -> None:
        """Test update command has correct options."""
        update_cmd = task_group.commands["update"]
        params = {p.name for p in update_cmd.params}
        assert "task_id" in params
        assert "title" in params
        assert "description" in params
        assert "status" in params
        assert "priority" in params
        assert "assignee" in params

    def test_delete_command_structure(self) -> None:
        """Test delete command has correct options."""
        delete_cmd = task_group.commands["delete"]
        params = {p.name for p in delete_cmd.params}
        assert "task_id" in params
        assert "force" in params

    def test_status_command_structure(self) -> None:
        """Test status command has correct options."""
        status_cmd = task_group.commands["status"]
        params = {p.name for p in status_cmd.params}
        assert "task_id" in params
        assert "status" in params


class TestGenerateCompletionScript:
    """Test shell completion script generation."""

    def test_bash_completion(self) -> None:
        """Test bash completion script generation."""
        result = generate_completion_script("bash")
        assert "_mahavishnu_completion" in result
        assert "complete -F" in result
        assert "mahavishnu" in result
        assert "mhv" in result

    def test_zsh_completion(self) -> None:
        """Test zsh completion script generation."""
        result = generate_completion_script("zsh")
        assert "compinit" in result
        assert "bashcompinit" in result

    def test_fish_completion(self) -> None:
        """Test fish completion script generation."""
        result = generate_completion_script("fish")
        assert "fish" in result
        assert "--show-completion" in result

    def test_unknown_shell(self) -> None:
        """Test unknown shell returns empty."""
        result = generate_completion_script("unknown")
        assert result == ""


class TestCLIIntegration:
    """Integration tests for CLI commands."""

    @pytest.fixture
    def runner(self) -> CliRunner:
        """Create CLI runner."""
        return CliRunner()

    def test_list_command_help(self, runner: CliRunner) -> None:
        """Test list command help."""
        result = runner.invoke(task_group, ["list", "--help"])
        assert result.exit_code == 0
        assert "List tasks" in result.output

    def test_create_command_help(self, runner: CliRunner) -> None:
        """Test create command help."""
        result = runner.invoke(task_group, ["create", "--help"])
        assert result.exit_code == 0
        assert "Create a new task" in result.output

    def test_update_command_help(self, runner: CliRunner) -> None:
        """Test update command help."""
        result = runner.invoke(task_group, ["update", "--help"])
        assert result.exit_code == 0
        assert "Update a task" in result.output

    def test_delete_command_help(self, runner: CliRunner) -> None:
        """Test delete command help."""
        result = runner.invoke(task_group, ["delete", "--help"])
        assert result.exit_code == 0
        assert "Delete a task" in result.output

    def test_status_command_help(self, runner: CliRunner) -> None:
        """Test status command help."""
        result = runner.invoke(task_group, ["status", "--help"])
        assert result.exit_code == 0
        assert "Update task status" in result.output

    def test_create_requires_repository(self, runner: CliRunner) -> None:
        """Test create command requires repository."""
        result = runner.invoke(task_group, ["create", "Test Task"])
        assert result.exit_code != 0
        assert "repository" in result.output.lower() or "required" in result.output.lower()

    def test_update_requires_task_id(self, runner: CliRunner) -> None:
        """Test update command requires task_id."""
        result = runner.invoke(task_group, ["update"])
        assert result.exit_code != 0

    def test_delete_requires_task_id(self, runner: CliRunner) -> None:
        """Test delete command requires task_id."""
        result = runner.invoke(task_group, ["delete"])
        assert result.exit_code != 0

    def test_status_requires_arguments(self, runner: CliRunner) -> None:
        """Test status command requires task_id and status."""
        result = runner.invoke(task_group, ["status"])
        assert result.exit_code != 0
