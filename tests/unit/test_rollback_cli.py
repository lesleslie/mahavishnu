"""Unit tests for the rollback CLI (audit finding H8).

These tests cover:
- Arg parsing for `mahavishnu rollback bodai-crow --to-version <sha>`
- Arg parsing for `mahavishnu rollback distilled-workflow --id <ulid>`
- Handler dispatch (each subcommand routes to its handler function)
- Surface registration (both subcommands are wired into the main app)

The handlers themselves are stubs that print "not yet implemented" — the goal
of this PR is the surface, the wiring, and the test, not the rollback
implementation (which lands in a follow-up).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from mahavishnu._main_cli import app
from mahavishnu.cli.rollback_cli import (
    add_rollback_commands,
    rollback_bodai_crow,
    rollback_distilled_workflow,
)


@pytest.mark.unit
class TestRollbackCLIRegistration:
    """Verify both subcommands register on the main CLI app."""

    def test_rollback_subcommand_registered_on_main_app(self) -> None:
        """`mahavishnu rollback ...` is reachable from the main app."""
        runner = CliRunner()
        result = runner.invoke(app, ["rollback", "--help"])
        assert result.exit_code == 0
        assert "bodai-crow" in result.stdout
        assert "distilled-workflow" in result.stdout

    def test_add_rollback_commands_attaches_typer_subapp(self) -> None:
        """add_rollback_commands attaches the rollback sub-app under 'rollback'."""
        import typer

        from mahavishnu.cli.rollback_cli import rollback_app

        test_app = typer.Typer()
        add_rollback_commands(test_app)
        # Typer sub-apps are stored in `registered_groups` keyed by name
        group_names = {
            getattr(g, "name", None) or getattr(g, "typer_instance", None) and g.typer_instance.info.name
            for g in test_app.registered_groups
        }
        assert "rollback" in group_names

    def test_rollback_subapp_declares_both_subcommands(self) -> None:
        """Both subcommands are declared on the rollback sub-app."""
        from mahavishnu.cli.rollback_cli import rollback_app

        runner = CliRunner()
        result = runner.invoke(rollback_app, ["--help"])
        assert result.exit_code == 0
        assert "bodai-crow" in result.stdout
        assert "distilled-workflow" in result.stdout


@pytest.mark.unit
class TestBodaiCrowRollback:
    """Arg parsing + dispatch for `mahavishnu rollback bodai-crow`."""

    def test_handler_exists_and_is_callable(self) -> None:
        """The bodai-crow rollback handler is exported and callable."""
        assert callable(rollback_bodai_crow)

    def test_bodai_crow_requires_to_version_flag(self) -> None:
        """Missing --to-version exits with non-zero status."""
        runner = CliRunner()
        result = runner.invoke(app, ["rollback", "bodai-crow"])
        assert result.exit_code != 0

    def test_bodai_crow_handler_called_with_sha(self) -> None:
        """`--to-version <sha>` is forwarded to rollback_bodai_crow."""
        runner = CliRunner()
        with patch(
            "mahavishnu.cli.rollback_cli.rollback_bodai_crow"
        ) as mock_handler:
            result = runner.invoke(
                app,
                ["rollback", "bodai-crow", "--to-version", "abc1234"],
            )
        assert result.exit_code == 0, result.stdout
        mock_handler.assert_called_once()
        # The handler should have received the sha
        _, kwargs = mock_handler.call_args
        assert kwargs.get("to_version") == "abc1234" or (
            len(mock_handler.call_args.args) > 0
            and mock_handler.call_args.args[0] == "abc1234"
        )

    def test_bodai_crow_subcommand_help_describes_to_version(self) -> None:
        """The --help output mentions --to-version."""
        from mahavishnu.cli.rollback_cli import rollback_app

        runner = CliRunner()
        result = runner.invoke(rollback_app, ["bodai-crow", "--help"])
        assert result.exit_code == 0
        assert "--to-version" in result.stdout


@pytest.mark.unit
class TestDistilledWorkflowRollback:
    """Arg parsing + dispatch for `mahavishnu rollback distilled-workflow`."""

    def test_handler_exists_and_is_callable(self) -> None:
        """The distilled-workflow rollback handler is exported and callable."""
        assert callable(rollback_distilled_workflow)

    def test_distilled_workflow_requires_id_flag(self) -> None:
        """Missing --id exits with non-zero status."""
        runner = CliRunner()
        result = runner.invoke(app, ["rollback", "distilled-workflow"])
        assert result.exit_code != 0

    def test_distilled_workflow_handler_called_with_ulid(self) -> None:
        """`--id <ulid>` is forwarded to rollback_distilled_workflow."""
        runner = CliRunner()
        with patch(
            "mahavishnu.cli.rollback_cli.rollback_distilled_workflow"
        ) as mock_handler:
            result = runner.invoke(
                app,
                [
                    "rollback",
                    "distilled-workflow",
                    "--id",
                    "01JABCDEFGHJKMNPQRSTVWXYZ",
                ],
            )
        assert result.exit_code == 0, result.stdout
        mock_handler.assert_called_once()
        _, kwargs = mock_handler.call_args
        assert kwargs.get("id") == "01JABCDEFGHJKMNPQRSTVWXYZ" or (
            len(mock_handler.call_args.args) > 0
            and mock_handler.call_args.args[0] == "01JABCDEFGHJKMNPQRSTVWXYZ"
        )

    def test_distilled_workflow_subcommand_help_describes_id(self) -> None:
        """The --help output mentions --id."""
        from mahavishnu.cli.rollback_cli import rollback_app

        runner = CliRunner()
        result = runner.invoke(rollback_app, ["distilled-workflow", "--help"])
        assert result.exit_code == 0
        assert "--id" in result.stdout


@pytest.mark.unit
class TestRollbackHandlerStubs:
    """Handlers are surface stubs; they print a clear not-yet-implemented message."""

    def test_bodai_crow_handler_echoes_target_sha(self, capsys) -> None:
        """Stub handler echoes the target version so callers see what they passed."""
        rollback_bodai_crow(to_version="deadbeef")
        captured = capsys.readouterr()
        assert "deadbeef" in captured.out

    def test_distilled_workflow_handler_echoes_target_id(self, capsys) -> None:
        """Stub handler echoes the target id so callers see what they passed."""
        rollback_distilled_workflow(id="01JABCDEFGHJKMNPQRSTVWXYZ")
        captured = capsys.readouterr()
        assert "01JABCDEFGHJKMNPQRSTVWXYZ" in captured.out
