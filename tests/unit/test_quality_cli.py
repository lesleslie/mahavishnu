"""Tests for quality_cli.py — quality management CLI commands."""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from mahavishnu.quality_cli import add_quality_commands, quality_app

runner = CliRunner()


class TestQualityCheck:
    def test_default_path(self):
        result = runner.invoke(quality_app, ["check"])
        assert result.exit_code == 0
        assert "Quality check for ." in result.output
        assert "Quality check complete (stub)" in result.output

    def test_custom_path(self):
        result = runner.invoke(quality_app, ["check", "/some/path"])
        assert result.exit_code == 0
        assert "Quality check for /some/path" in result.output

    def test_verbose(self):
        result = runner.invoke(quality_app, ["check", "--verbose"])
        assert result.exit_code == 0
        assert "Verbose output enabled" in result.output

    def test_verbose_short_flag(self):
        result = runner.invoke(quality_app, ["check", "-v"])
        assert result.exit_code == 0
        assert "Verbose output enabled" in result.output

    def test_check_verbose_does_not_change_check_message(self):
        """Verbose should be a no-op for the primary check message."""
        result = runner.invoke(quality_app, ["check", "--verbose"])
        assert result.exit_code == 0
        assert "Quality check for ." in result.output

    def test_check_unicode_path(self):
        """Check should accept a unicode path without error."""
        result = runner.invoke(quality_app, ["check", "テスト"])
        assert result.exit_code == 0
        assert "Quality check for テスト" in result.output

    def test_check_path_with_spaces(self):
        """Check should accept paths containing spaces."""
        result = runner.invoke(quality_app, ["check", "some path/with spaces"])
        assert result.exit_code == 0
        assert "some path/with spaces" in result.output

    def test_check_output_order(self):
        """The verbose message should appear between the start and finish lines."""
        result = runner.invoke(quality_app, ["check", "--verbose"])
        assert result.exit_code == 0
        start = result.output.find("Quality check for")
        verbose = result.output.find("Verbose output enabled")
        end = result.output.find("Quality check complete")
        assert start < verbose < end

    def test_check_help_describes_command(self):
        """The check subcommand should expose help text."""
        result = runner.invoke(quality_app, ["check", "--help"])
        assert result.exit_code == 0
        assert "Run quality checks" in result.output

    def test_check_default_path_is_current_dir_token(self):
        """The default path should be the literal '.' string."""
        result = runner.invoke(quality_app, ["check"])
        assert result.exit_code == 0
        assert "Quality check for ." in result.output


class TestQualityFix:
    def test_default_path(self):
        result = runner.invoke(quality_app, ["fix"])
        assert result.exit_code == 0
        assert "Quality fix for ." in result.output
        assert "Quality fix complete" in result.output

    def test_custom_path(self):
        result = runner.invoke(quality_app, ["fix", "/tmp/code"])
        assert result.exit_code == 0
        assert "Quality fix for /tmp/code" in result.output

    def test_auto_flag(self):
        with patch("mahavishnu.quality_cli.subprocess.run") as mock_run:
            result = runner.invoke(quality_app, ["fix", "--auto"])
        assert result.exit_code == 0
        assert "Auto-fixing issues" in result.output
        assert mock_run.call_count == 3

    def test_auto_short_flag(self):
        with patch("mahavishnu.quality_cli.subprocess.run") as mock_run:
            result = runner.invoke(quality_app, ["fix", "-a"])
        assert result.exit_code == 0
        assert "Auto-fixing issues" in result.output
        assert mock_run.call_count == 3

    def test_no_auto_no_subprocess_calls(self):
        """Without --auto, no subprocess calls should be made."""
        with patch("mahavishnu.quality_cli.subprocess.run") as mock_run:
            result = runner.invoke(quality_app, ["fix"])
        assert result.exit_code == 0
        assert "Auto-fixing issues" not in result.output
        mock_run.assert_not_called()

    def test_auto_invokes_three_ruff_subcommands(self):
        """Auto-fix should run ruff check --fix, ruff format, and ruff check."""
        with patch("mahavishnu.quality_cli.subprocess.run") as mock_run:
            result = runner.invoke(quality_app, ["fix", "--auto"])
        assert result.exit_code == 0
        # Collect the first positional arg of each call
        first_args = [call.args[0] for call in mock_run.call_args_list]
        assert ["ruff", "check", "--fix", "."] in first_args
        assert ["ruff", "format", "."] in first_args
        # Final verification: ruff check (no --fix)
        assert ["ruff", "check", "."] in first_args

    def test_auto_passes_path_to_subprocess(self):
        """Auto-fix should pass the path argument through to each subprocess call."""
        with patch("mahavishnu.quality_cli.subprocess.run") as mock_run:
            result = runner.invoke(quality_app, ["fix", "/tmp/code", "--auto"])
        assert result.exit_code == 0
        # Each call's last positional arg should be the path
        for call in mock_run.call_args_list:
            assert call.args[0][-1] == "/tmp/code"

    def test_auto_check_false_on_subprocess(self):
        """Auto-fix subprocess calls should not raise on non-zero exit codes."""
        with patch("mahavishnu.quality_cli.subprocess.run") as mock_run:
            result = runner.invoke(quality_app, ["fix", "--auto"])
        assert result.exit_code == 0
        for call in mock_run.call_args_list:
            assert call.kwargs.get("check") is False

    def test_fix_unicode_path_with_auto(self):
        """Auto-fix should work with a unicode path argument."""
        with patch("mahavishnu.quality_cli.subprocess.run") as mock_run:
            result = runner.invoke(quality_app, ["fix", "テスト", "--auto"])
        assert result.exit_code == 0
        assert "Quality fix for テスト" in result.output
        assert mock_run.call_count == 3

    def test_fix_output_order(self):
        """Auto-fix output should appear between start and finish lines."""
        with patch("mahavishnu.quality_cli.subprocess.run"):
            result = runner.invoke(quality_app, ["fix", "--auto"])
        assert result.exit_code == 0
        start = result.output.find("Quality fix for")
        autofix = result.output.find("Auto-fixing issues")
        end = result.output.find("Quality fix complete")
        assert start < autofix < end

    def test_fix_help_describes_command(self):
        """The fix subcommand should expose help text."""
        result = runner.invoke(quality_app, ["fix", "--help"])
        assert result.exit_code == 0
        assert "Fix quality issues" in result.output


class TestQualityAppRegistration:
    """Test quality_app Typer registration and properties."""

    def test_quality_app_is_typer_instance(self):
        """quality_app should be a Typer application."""
        import typer

        assert isinstance(quality_app, typer.Typer)

    def test_quality_app_has_help_text(self):
        """The help message should match the Typer help argument."""
        result = runner.invoke(quality_app, ["--help"])
        assert result.exit_code == 0
        assert "Quality management" in result.output

    def test_quality_app_registers_exactly_two_commands(self):
        """Quality app should expose exactly 'check' and 'fix'."""
        assert len(quality_app.registered_commands) == 2
        names = {cmd.name for cmd in quality_app.registered_commands}
        assert names == {"check", "fix"}

    def test_quality_app_has_no_subgroups(self):
        """Quality app should not have any nested sub-groups."""
        assert len(quality_app.registered_groups) == 0


class TestAddQualityCommands:
    def test_registers_with_parent(self):
        import typer

        parent = typer.Typer()
        add_quality_commands(parent)
        # The subcommand should be registered under "quality"
        result = runner.invoke(parent, ["quality", "check"])
        assert result.exit_code == 0
        assert "Quality check" in result.output

    def test_add_quality_commands_is_idempotent_for_fresh_parents(self):
        """Calling add_quality_commands on fresh parents should not raise."""
        import typer

        for _ in range(3):
            parent = typer.Typer()
            add_quality_commands(parent)
            assert isinstance(parent, typer.Typer)

    def test_add_quality_commands_subtyper_help_visible(self):
        """The 'quality' sub-typer should be discoverable via parent help."""
        import typer

        parent = typer.Typer()
        add_quality_commands(parent)
        result = runner.invoke(parent, ["quality", "--help"])
        assert result.exit_code == 0
        assert "check" in result.output
        assert "fix" in result.output

    def test_add_quality_commands_preserves_other_subapps(self):
        """Adding quality should not disturb other sub-apps already on the parent."""
        import typer

        parent = typer.Typer()
        other = typer.Typer(help="Other")
        parent.add_typer(other, name="other")
        add_quality_commands(parent)

        names = [g.name for g in parent.registered_groups]
        assert "other" in names
        assert "quality" in names
