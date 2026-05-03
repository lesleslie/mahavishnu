"""Comprehensive unit tests for the Task CLI module.

Tests cover all CLI commands (create, list, update, delete, status),
shell completion functions, due date parsing, completion script generation,
and register_shorthands functionality. All external dependencies are mocked.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner

from mahavishnu.task_cli import (
    complete_priority,
    complete_repository,
    complete_status,
    complete_tag,
    complete_task_id,
    generate_completion_script,
    parse_due_date,
    register_shorthands,
    task_group,
)


def _make_task(
    task_id: str = "task-abc123",
    title: str = "Fix the login bug",
    repository: str = "session-buddy",
    status_val: str = "pending",
    priority_val: str = "medium",
    assignee: str | None = "alice",
    description: str | None = "A description",
) -> MagicMock:
    task = MagicMock()
    task.id = task_id
    task.title = title
    task.repository = repository
    task.description = description
    task.assignee = assignee
    task.to_dict.return_value = {
        "id": task_id,
        "title": title,
        "repository": repository,
        "status": status_val,
        "priority": priority_val,
        "assignee": assignee,
        "description": description,
    }
    task.status = MagicMock()
    task.status.value = status_val
    task.priority = MagicMock()
    task.priority.value = priority_val
    return task


runner = CliRunner()


class TestCompletionFunctions:
    """Test shell completion functions."""

    def test_complete_repository_from_env(self) -> None:
        with patch.dict("os.environ", {"MAHAVISHNU_REPOS": "custom-repo,another-repo"}):
            result = complete_repository(ctx=MagicMock(), args=[], incomplete="custom")
            assert "custom-repo" in result

    def test_complete_repository_env_not_deduplicated(self) -> None:
        with patch.dict("os.environ", {"MAHAVISHNU_REPOS": "mahavishnu,custom"}):
            result = complete_repository(ctx=MagicMock(), args=[], incomplete="")
            count = result.count("mahavishnu")
            assert count == 1

    def test_complete_repository_common_repos_present(self) -> None:
        result = complete_repository(ctx=MagicMock(), args=[], incomplete="mah")
        assert "mahavishnu" in result

    def test_complete_repository_no_match(self) -> None:
        result = complete_repository(ctx=MagicMock(), args=[], incomplete="xyz")
        assert result == []

    def test_complete_repository_empty_incomplete_returns_all(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            result = complete_repository(ctx=MagicMock(), args=[], incomplete="")
            assert "mahavishnu" in result
            assert "session-buddy" in result
            assert "crackerjack" in result
            assert "akosha" in result
            assert "mcp-common" in result

    def test_complete_status_pending(self) -> None:
        result = complete_status(ctx=MagicMock(), args=[], incomplete="pend")
        assert "pending" in result

    def test_complete_status_in_progress(self) -> None:
        result = complete_status(ctx=MagicMock(), args=[], incomplete="in")
        assert "in_progress" in result

    def test_complete_status_all_statuses(self) -> None:
        result = complete_status(ctx=MagicMock(), args=[], incomplete="")
        assert len(result) == 6
        for s in ["pending", "in_progress", "completed", "failed", "cancelled", "blocked"]:
            assert s in result

    def test_complete_priority_all(self) -> None:
        result = complete_priority(ctx=MagicMock(), args=[], incomplete="")
        assert len(result) == 4
        assert "low" in result
        assert "medium" in result
        assert "high" in result
        assert "critical" in result

    def test_complete_priority_partial(self) -> None:
        result = complete_priority(ctx=MagicMock(), args=[], incomplete="crit")
        assert "critical" in result

    def test_complete_task_id_returns_empty(self) -> None:
        result = complete_task_id(ctx=MagicMock(), args=[], incomplete="task")
        assert result == []

    def test_complete_tag_bug(self) -> None:
        result = complete_tag(ctx=MagicMock(), args=[], incomplete="bug")
        assert "bug" in result

    def test_complete_tag_partial(self) -> None:
        result = complete_tag(ctx=MagicMock(), args=[], incomplete="back")
        assert "backend" in result

    def test_complete_tag_no_match(self) -> None:
        result = complete_tag(ctx=MagicMock(), args=[], incomplete="zzz")
        assert result == []

    def test_complete_tag_all(self) -> None:
        result = complete_tag(ctx=MagicMock(), args=[], incomplete="")
        assert "bug" in result
        assert "feature" in result
        assert "security" in result
        assert "testing" in result


class TestParseDueDate:
    """Test due date parsing."""

    def test_parse_today(self) -> None:
        result = parse_due_date("today")
        assert result is not None
        assert result.hour == 23
        assert result.minute == 59
        assert result.second == 59

    def test_parse_tomorrow(self) -> None:
        result = parse_due_date("tomorrow")
        assert result is not None
        expected = (datetime.now() + timedelta(days=1)).date()
        assert result.date() == expected

    def test_parse_next_week(self) -> None:
        result = parse_due_date("next week")
        assert result is not None
        expected = (datetime.now() + timedelta(weeks=1)).date()
        assert result.date() == expected

    def test_parse_next_month(self) -> None:
        result = parse_due_date("next month")
        assert result is not None
        expected = (datetime.now() + timedelta(days=30)).date()
        assert result.date() == expected

    def test_parse_in_5_days(self) -> None:
        result = parse_due_date("in 5 days")
        assert result is not None
        expected = (datetime.now() + timedelta(days=5)).date()
        assert result.date() == expected

    def test_parse_in_1_day(self) -> None:
        result = parse_due_date("in 1 day")
        assert result is not None
        expected = (datetime.now() + timedelta(days=1)).date()
        assert result.date() == expected

    def test_parse_in_2_weeks(self) -> None:
        result = parse_due_date("in 2 weeks")
        assert result is not None
        expected = (datetime.now() + timedelta(weeks=2)).date()
        assert result.date() == expected

    def test_parse_in_1_week(self) -> None:
        result = parse_due_date("in 1 week")
        assert result is not None
        expected = (datetime.now() + timedelta(weeks=1)).date()
        assert result.date() == expected

    def test_parse_iso_date(self) -> None:
        result = parse_due_date("2026-12-31")
        assert result is not None
        assert result.year == 2026
        assert result.month == 12
        assert result.day == 31

    def test_parse_iso_datetime(self) -> None:
        result = parse_due_date("2026-06-15T10:30:00")
        assert result is not None
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 15

    def test_parse_invalid(self) -> None:
        result = parse_due_date("not a date")
        assert result is None

    def test_parse_empty_string(self) -> None:
        result = parse_due_date("")
        assert result is None

    def test_parse_case_insensitive_today(self) -> None:
        result = parse_due_date("TODAY")
        assert result is not None
        assert result.hour == 23

    def test_parse_case_insensitive_tomorrow(self) -> None:
        result = parse_due_date("Tomorrow")
        assert result is not None
        expected = (datetime.now() + timedelta(days=1)).date()
        assert result.date() == expected

    def test_parse_in_n_without_unit(self) -> None:
        result = parse_due_date("in 5")
        assert result is None

    def test_end_of_day_time_set(self) -> None:
        result = parse_due_date("today")
        assert result is not None
        assert result.hour == 23
        assert result.minute == 59
        assert result.second == 59


class TestTaskGroup:
    """Test task CLI group structure."""

    def test_group_name(self) -> None:
        assert task_group.name == "task"

    def test_group_has_all_commands(self) -> None:
        commands = list(task_group.commands.keys())
        assert "create" in commands
        assert "list" in commands
        assert "update" in commands
        assert "delete" in commands
        assert "status" in commands

    def test_create_command_params(self) -> None:
        cmd = task_group.commands["create"]
        params = {p.name for p in cmd.params}
        assert "title" in params
        assert "repository" in params
        assert "description" in params
        assert "priority" in params
        assert "status" in params
        assert "assignee" in params
        assert "tag" in params
        assert "due" in params

    def test_list_command_params(self) -> None:
        cmd = task_group.commands["list"]
        params = {p.name for p in cmd.params}
        assert "repository" in params
        assert "status" in params
        assert "priority" in params
        assert "assignee" in params
        assert "search" in params
        assert "limit" in params
        assert "tag" in params

    def test_update_command_params(self) -> None:
        cmd = task_group.commands["update"]
        params = {p.name for p in cmd.params}
        assert "task_id" in params
        assert "title" in params
        assert "description" in params
        assert "status" in params
        assert "priority" in params
        assert "assignee" in params

    def test_delete_command_params(self) -> None:
        cmd = task_group.commands["delete"]
        params = {p.name for p in cmd.params}
        assert "task_id" in params
        assert "force" in params

    def test_status_command_params(self) -> None:
        cmd = task_group.commands["status"]
        params = {p.name for p in cmd.params}
        assert "task_id" in params
        assert "status" in params


class TestGenerateCompletionScript:
    """Test shell completion script generation."""

    def test_bash_completion(self) -> None:
        result = generate_completion_script("bash")
        assert "_mahavishnu_completion" in result
        assert "complete -F" in result
        assert "mahavishnu" in result
        assert "mhv" in result

    def test_zsh_completion(self) -> None:
        result = generate_completion_script("zsh")
        assert "compinit" in result
        assert "bashcompinit" in result

    def test_fish_completion(self) -> None:
        result = generate_completion_script("fish")
        assert "fish" in result
        assert "--show-completion" in result

    def test_unknown_shell(self) -> None:
        result = generate_completion_script("unknown")
        assert result == ""


class TestRegisterShorthands:
    """Test shorthand command registration."""

    def test_register_shorthands_adds_commands(self) -> None:
        group = MagicMock()
        register_shorthands(group)
        assert group.command.call_count == 5

    def test_register_shorthands_hidden_commands(self) -> None:
        import click

        group = click.Group(name="test")
        register_shorthands(group)
        for name in ["tc", "tl", "tu", "td", "ts"]:
            assert name in group.commands
            assert group.commands[name].hidden is True


class TestTaskCreateCommand:
    """Test task create command."""

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_create_success(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_task = _make_task()
        mock_store = MagicMock()
        mock_store.create = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            [
                "create",
                "Fix the bug",
                "-r",
                "session-buddy",
                "-p",
                "high",
            ],
        )
        assert result.exit_code == 0
        mock_store.create.assert_called_once()

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_create_with_all_options(
        self, mock_store_cls: MagicMock, mock_get_db: AsyncMock
    ) -> None:
        mock_task = _make_task()
        mock_store = MagicMock()
        mock_store.create = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            [
                "create",
                "Fix the bug",
                "-r",
                "mahavishnu",
                "-d",
                "Detailed description",
                "-p",
                "critical",
                "-s",
                "blocked",
                "-a",
                "bob@example.com",
                "-t",
                "bug",
                "-t",
                "urgent",
            ],
        )
        assert result.exit_code == 0
        mock_store.create.assert_called_once()

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_create_with_due_date(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_task = _make_task()
        mock_store = MagicMock()
        mock_store.create = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            [
                "create",
                "Task with due",
                "-r",
                "mahavishnu",
                "--due",
                "tomorrow",
            ],
        )
        assert result.exit_code == 0

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_create_with_json_output(
        self, mock_store_cls: MagicMock, mock_get_db: AsyncMock
    ) -> None:
        mock_task = _make_task()
        mock_store = MagicMock()
        mock_store.create = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            [
                "create",
                "Fix",
                "-r",
                "mahavishnu",
                "--json",
            ],
        )
        assert result.exit_code == 0

    def test_create_missing_repository(self) -> None:
        result = runner.invoke(task_group, ["create", "Fix the bug"])
        assert result.exit_code != 0

    def test_create_missing_title(self) -> None:
        result = runner.invoke(task_group, ["create"])
        assert result.exit_code != 0

    def test_create_invalid_priority(self) -> None:
        result = runner.invoke(
            task_group,
            [
                "create",
                "Fix",
                "-r",
                "mahavishnu",
                "-p",
                "invalid",
            ],
        )
        assert result.exit_code != 0

    def test_create_invalid_status(self) -> None:
        result = runner.invoke(
            task_group,
            [
                "create",
                "Fix",
                "-r",
                "mahavishnu",
                "-s",
                "invalid",
            ],
        )
        assert result.exit_code != 0

    def test_create_help(self) -> None:
        result = runner.invoke(task_group, ["create", "--help"])
        assert result.exit_code == 0
        assert "Create a new task" in result.output


class TestTaskListCommand:
    """Test task list command."""

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_list_success(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_task = _make_task()
        mock_store = MagicMock()
        mock_store.list = AsyncMock(return_value=[mock_task])
        mock_store.count = AsyncMock(return_value=1)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(task_group, ["list"])
        assert result.exit_code == 0
        mock_store.list.assert_called_once()
        mock_store.count.assert_called_once()

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_list_empty(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_store = MagicMock()
        mock_store.list = AsyncMock(return_value=[])
        mock_store.count = AsyncMock(return_value=0)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(task_group, ["list"])
        assert result.exit_code == 0

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_list_with_filters(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_store = MagicMock()
        mock_store.list = AsyncMock(return_value=[])
        mock_store.count = AsyncMock(return_value=0)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            [
                "list",
                "-r",
                "mahavishnu",
                "-s",
                "in_progress",
                "-p",
                "high",
                "-a",
                "alice",
                "--search",
                "bug",
                "-l",
                "10",
                "-t",
                "urgent",
            ],
        )
        assert result.exit_code == 0

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_list_json_output(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_task = _make_task()
        mock_store = MagicMock()
        mock_store.list = AsyncMock(return_value=[mock_task])
        mock_store.count = AsyncMock(return_value=1)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(task_group, ["list", "--json"])
        assert result.exit_code == 0

    def test_list_help(self) -> None:
        result = runner.invoke(task_group, ["list", "--help"])
        assert result.exit_code == 0
        assert "List tasks" in result.output


class TestTaskUpdateCommand:
    """Test task update command."""

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_update_status(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_task = _make_task(status_val="completed")
        mock_store = MagicMock()
        mock_store.update = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            [
                "update",
                "task-abc123",
                "-s",
                "completed",
            ],
        )
        assert result.exit_code == 0
        mock_store.update.assert_called_once()

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_update_title(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_task = _make_task(title="New title")
        mock_store = MagicMock()
        mock_store.update = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            [
                "update",
                "task-abc123",
                "--title",
                "New title",
            ],
        )
        assert result.exit_code == 0

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_update_multiple_fields(
        self, mock_store_cls: MagicMock, mock_get_db: AsyncMock
    ) -> None:
        mock_task = _make_task(priority_val="critical", assignee="bob")
        mock_store = MagicMock()
        mock_store.update = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            [
                "update",
                "task-abc123",
                "-s",
                "in_progress",
                "-p",
                "critical",
                "-a",
                "bob",
            ],
        )
        assert result.exit_code == 0

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_update_json_output(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_task = _make_task(status_val="completed")
        mock_store = MagicMock()
        mock_store.update = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            [
                "update",
                "task-abc123",
                "-s",
                "completed",
                "--json",
            ],
        )
        assert result.exit_code == 0

    def test_update_requires_task_id(self) -> None:
        result = runner.invoke(task_group, ["update"])
        assert result.exit_code != 0

    def test_update_invalid_status(self) -> None:
        result = runner.invoke(
            task_group,
            [
                "update",
                "task-abc123",
                "-s",
                "invalid",
            ],
        )
        assert result.exit_code != 0

    def test_update_invalid_priority(self) -> None:
        result = runner.invoke(
            task_group,
            [
                "update",
                "task-abc123",
                "-p",
                "urgent",
            ],
        )
        assert result.exit_code != 0

    def test_update_help(self) -> None:
        result = runner.invoke(task_group, ["update", "--help"])
        assert result.exit_code == 0
        assert "Update a task" in result.output


class TestTaskDeleteCommand:
    """Test task delete command."""

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_delete_force(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_store = MagicMock()
        mock_store.delete = AsyncMock(return_value=None)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(task_group, ["delete", "task-abc123", "-f"])
        assert result.exit_code == 0
        mock_store.delete.assert_called_once_with("task-abc123")

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_delete_interactive_yes(
        self, mock_store_cls: MagicMock, mock_get_db: AsyncMock
    ) -> None:
        mock_store = MagicMock()
        mock_store.delete = AsyncMock(return_value=None)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            ["delete", "task-abc123"],
            input="y\n",
        )
        assert result.exit_code == 0
        mock_store.delete.assert_called_once()

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_delete_interactive_no(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_store = MagicMock()
        mock_store.delete = AsyncMock(return_value=None)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            task_group,
            ["delete", "task-abc123"],
            input="n\n",
        )
        assert result.exit_code == 0
        assert "Cancelled" in result.output
        mock_store.delete.assert_not_called()

    def test_delete_requires_task_id(self) -> None:
        result = runner.invoke(task_group, ["delete"])
        assert result.exit_code != 0

    def test_delete_help(self) -> None:
        result = runner.invoke(task_group, ["delete", "--help"])
        assert result.exit_code == 0
        assert "Delete a task" in result.output


class TestTaskStatusCommand:
    """Test task status command."""

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_status_update(self, mock_store_cls: MagicMock, mock_get_db: AsyncMock) -> None:
        mock_task = _make_task(status_val="completed")
        mock_store = MagicMock()
        mock_store.update = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(task_group, ["status", "task-abc123", "completed"])
        assert result.exit_code == 0
        mock_store.update.assert_called_once()

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_status_update_to_in_progress(
        self, mock_store_cls: MagicMock, mock_get_db: AsyncMock
    ) -> None:
        mock_task = _make_task(status_val="in_progress")
        mock_store = MagicMock()
        mock_store.update = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(task_group, ["status", "task-abc123", "in_progress"])
        assert result.exit_code == 0

    @patch("mahavishnu.core.database.get_database", new_callable=AsyncMock)
    @patch("mahavishnu.core.task_store.TaskStore")
    def test_status_update_to_blocked(
        self, mock_store_cls: MagicMock, mock_get_db: AsyncMock
    ) -> None:
        mock_task = _make_task(status_val="blocked")
        mock_store = MagicMock()
        mock_store.update = AsyncMock(return_value=mock_task)
        mock_store_cls.return_value = mock_store

        result = runner.invoke(task_group, ["status", "task-abc123", "blocked"])
        assert result.exit_code == 0

    def test_status_requires_task_id(self) -> None:
        result = runner.invoke(task_group, ["status"])
        assert result.exit_code != 0

    def test_status_invalid_status_value(self) -> None:
        result = runner.invoke(task_group, ["status", "task-abc123", "invalid"])
        assert result.exit_code != 0

    def test_status_help(self) -> None:
        result = runner.invoke(task_group, ["status", "--help"])
        assert result.exit_code == 0
        assert "Update task status" in result.output


class TestCLIErrorHandling:
    """Test error handling across commands."""

    def test_create_handles_exception(self) -> None:
        with patch("mahavishnu.task_cli.asyncio.run", side_effect=RuntimeError("database error")):
            result = runner.invoke(
                task_group,
                [
                    "create",
                    "Fix",
                    "-r",
                    "mahavishnu",
                ],
            )
            assert result.exit_code != 0

    def test_list_handles_exception(self) -> None:
        with patch("mahavishnu.task_cli.asyncio.run", side_effect=RuntimeError("database error")):
            result = runner.invoke(task_group, ["list"])
            assert result.exit_code != 0

    def test_update_handles_exception(self) -> None:
        with patch("mahavishnu.task_cli.asyncio.run", side_effect=RuntimeError("database error")):
            result = runner.invoke(task_group, ["update", "task-abc123", "-s", "completed"])
            assert result.exit_code != 0

    def test_delete_handles_exception(self) -> None:
        with patch("mahavishnu.task_cli.asyncio.run", side_effect=RuntimeError("database error")):
            result = runner.invoke(task_group, ["delete", "task-abc123", "-f"])
            assert result.exit_code != 0

    def test_status_handles_exception(self) -> None:
        with patch("mahavishnu.task_cli.asyncio.run", side_effect=RuntimeError("database error")):
            result = runner.invoke(task_group, ["status", "task-abc123", "completed"])
            assert result.exit_code != 0


class TestTaskGroupHelp:
    """Test group-level help output."""

    def test_task_group_help(self) -> None:
        result = runner.invoke(task_group, ["--help"])
        assert result.exit_code == 0
        assert "create" in result.output
        assert "list" in result.output
        assert "update" in result.output
        assert "delete" in result.output
        assert "status" in result.output
