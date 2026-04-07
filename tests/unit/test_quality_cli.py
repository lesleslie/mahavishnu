"""Tests for quality_cli.py — quality management CLI commands."""

from typer.testing import CliRunner

from mahavishnu.quality_cli import add_quality_commands, quality_app, quality_check, quality_fix

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


class TestQualityFix:
    def test_default_path(self):
        result = runner.invoke(quality_app, ["fix"])
        assert result.exit_code == 0
        assert "Quality fix for ." in result.output
        assert "Quality fix complete (stub)" in result.output

    def test_custom_path(self):
        result = runner.invoke(quality_app, ["fix", "/tmp/code"])
        assert result.exit_code == 0
        assert "Quality fix for /tmp/code" in result.output

    def test_auto_flag(self):
        result = runner.invoke(quality_app, ["fix", "--auto"])
        assert result.exit_code == 0
        assert "Auto-fixing issues" in result.output

    def test_auto_short_flag(self):
        result = runner.invoke(quality_app, ["fix", "-a"])
        assert result.exit_code == 0
        assert "Auto-fixing issues" in result.output


class TestAddQualityCommands:
    def test_registers_with_parent(self):
        import typer
        parent = typer.Typer()
        add_quality_commands(parent)
        # The subcommand should be registered under "quality"
        result = runner.invoke(parent, ["quality", "check"])
        assert result.exit_code == 0
        assert "Quality check" in result.output
