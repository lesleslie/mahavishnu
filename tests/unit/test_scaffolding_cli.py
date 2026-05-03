"""Tests for scaffold CLI commands."""

from __future__ import annotations

from typer.testing import CliRunner

from mahavishnu.cli.scaffold_cli import app

runner = CliRunner()


class TestPatternsList:
    def test_list_patterns(self):
        result = runner.invoke(app, ["patterns", "list"])
        assert result.exit_code == 0
        assert "scaffolding/project" in result.output

    def test_list_by_category(self):
        result = runner.invoke(app, ["patterns", "list", "--category", "components"])
        assert result.exit_code == 0
        assert "components/" in result.output
        assert "scaffolding/" not in result.output

    def test_list_empty_category(self):
        result = runner.invoke(app, ["patterns", "list", "--category", "nonexistent"])
        assert result.exit_code == 0


class TestPatternsShow:
    def test_show_pattern(self):
        result = runner.invoke(app, ["patterns", "show", "scaffolding/project"])
        assert result.exit_code == 0
        assert "Fastblocks Project Skeleton" in result.output

    def test_show_missing(self):
        result = runner.invoke(app, ["patterns", "show", "nonexistent"])
        assert result.exit_code == 1


class TestPatternsValidate:
    def test_validate_library(self):
        result = runner.invoke(app, ["patterns", "validate"])
        if "validation errors" in result.output.lower():
            # Non-zero exit when issues exist
            assert result.exit_code == 1
        else:
            assert "valid" in result.output.lower()
            assert result.exit_code == 0


class TestScaffoldCommand:
    def test_scaffold_dry_run(self):
        result = runner.invoke(
            app,
            [
                "scaffold",
                "test-dry",
                "--patterns",
                "scaffolding/minimal",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0
        assert "dry-run" in result.output.lower() or "would include" in result.output.lower()

    def test_scaffold_missing_pattern(self):
        result = runner.invoke(
            app,
            [
                "scaffold",
                "test-bad",
                "--patterns",
                "nonexistent/x",
            ],
        )
        assert result.exit_code == 1

    def test_scaffold_rejects_path_traversal(self):
        result = runner.invoke(
            app,
            [
                "scaffold",
                "../../etc",
                "--patterns",
                "scaffolding/minimal",
            ],
        )
        assert result.exit_code == 1
        assert "must not contain" in result.output


class TestScaffoldValidate:
    def test_validate_project(self):
        result = runner.invoke(app, ["scaffold-validate", "--project", "/tmp/nonexistent"])
        assert result.exit_code == 1
