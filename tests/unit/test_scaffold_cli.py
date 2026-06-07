"""Unit tests for the mahavishnu.cli.scaffold_cli Typer app.

Covers:
    1. patterns list (all + category filter)
    2. patterns show (found / not found)
    3. patterns validate (clean / with issues)
    4. patterns search (matching / not matching)
    5. scaffold (dry-run, real scaffold, path-traversal guard, missing pattern)
    6. scaffold-validate (valid project, invalid project)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner
import yaml

from mahavishnu.cli.scaffold_cli import app
from mahavishnu.scaffolding.library import PatternLibrary

pytestmark = pytest.mark.unit

runner = CliRunner()


# ============== Fixtures ==============


@pytest.fixture
def patterns_root(tmp_path: Path) -> Path:
    """Create a temporary patterns root with a couple of sample patterns."""
    root = tmp_path / "patterns"
    root.mkdir()

    base = {
        "id": "components/nav",
        "name": "Navigation",
        "version": "1.0.0",
        "description": "Top navigation component",
        "source_repos": ["splashstand"],
        "tags": ["nav", "ui"],
        "depends": [],
        "structure": {"dirs": [], "files": []},
        "templates": {},
    }
    (root / "components__nav.yaml").write_text(yaml.safe_dump(base))

    adapters = {
        "id": "adapters/admin",
        "name": "Admin",
        "version": "1.0.0",
        "description": "Admin panel adapter",
        "source_repos": ["splashstand"],
        "tags": ["admin", "db"],
        "depends": [{"id": "scaffolding/project", "version": ">=1.0.0"}],
        "structure": {"dirs": [], "files": []},
        "templates": {},
    }
    (root / "adapters__admin.yaml").write_text(yaml.safe_dump(adapters))

    return root


@pytest.fixture
def real_library() -> PatternLibrary:
    """Library backed by the real patterns/ root in the repo (read-only checks)."""
    lib = PatternLibrary()
    lib.load_all()
    return lib


# ============== patterns list ==============


class TestPatternsList:
    """Tests for `mahavishnu patterns list`."""

    def test_list_shows_all_categories_and_patterns(self, patterns_root: Path) -> None:
        """Without filters, every category and pattern is listed."""
        with patch("mahavishnu.cli.scaffold_cli._get_library") as get_lib:
            lib = PatternLibrary(patterns_root)
            lib.load_all()
            get_lib.return_value = lib

            result = runner.invoke(app, ["patterns", "list"])
            assert result.exit_code == 0
            assert "adapters/" in result.output
            assert "components/" in result.output
            assert "adapters/admin" in result.output
            assert "components/nav" in result.output

    def test_list_filtered_by_category(self, patterns_root: Path) -> None:
        """--category restricts the output to that single category."""
        with patch("mahavishnu.cli.scaffold_cli._get_library") as get_lib:
            lib = PatternLibrary(patterns_root)
            lib.load_all()
            get_lib.return_value = lib

            result = runner.invoke(app, ["patterns", "list", "--category", "components"])
            assert result.exit_code == 0
            assert "components/" in result.output
            assert "adapters/" not in result.output

    def test_list_unknown_category_reports_available(self, patterns_root: Path) -> None:
        """An unknown category name lists the available ones and exits 0."""
        with patch("mahavishnu.cli.scaffold_cli._get_library") as get_lib:
            lib = PatternLibrary(patterns_root)
            lib.load_all()
            get_lib.return_value = lib

            result = runner.invoke(app, ["patterns", "list", "--category", "missing"])
            assert result.exit_code == 0
            assert "Category 'missing' not found" in result.output
            assert "adapters" in result.output
            assert "components" in result.output

    def test_list_shows_dependencies_for_patterns_with_deps(self, patterns_root: Path) -> None:
        """Patterns that declare dependencies get the (depends: N) hint."""
        with patch("mahavishnu.cli.scaffold_cli._get_library") as get_lib:
            lib = PatternLibrary(patterns_root)
            lib.load_all()
            get_lib.return_value = lib

            result = runner.invoke(app, ["patterns", "list"])
            assert "depends: 1" in result.output


# ============== patterns show ==============


class TestPatternsShow:
    """Tests for `mahavishnu patterns show`."""

    def test_show_existing_pattern(self, patterns_root: Path) -> None:
        """`patterns show <id>` prints ID, name, version, and structure."""
        with patch("mahavishnu.cli.scaffold_cli._get_library") as get_lib:
            lib = PatternLibrary(patterns_root)
            lib.load_all()
            get_lib.return_value = lib

            result = runner.invoke(app, ["patterns", "show", "components/nav"])
            assert result.exit_code == 0
            assert "ID:          components/nav" in result.output
            assert "Name:        Navigation" in result.output
            assert "Version:     1.0.0" in result.output
            assert "Description: Top navigation component" in result.output
            assert "splashstand" in result.output
            assert "Tags:" in result.output

    def test_show_pattern_with_dependencies(self, patterns_root: Path) -> None:
        """A pattern with depends shows the Depends section listing each dep."""
        with patch("mahavishnu.cli.scaffold_cli._get_library") as get_lib:
            lib = PatternLibrary(patterns_root)
            lib.load_all()
            get_lib.return_value = lib

            result = runner.invoke(app, ["patterns", "show", "adapters/admin"])
            assert result.exit_code == 0
            assert "Depends:" in result.output
            assert "scaffolding/project" in result.output
            assert "version: >=1.0.0" in result.output

    def test_show_missing_pattern_exits_nonzero(self, patterns_root: Path) -> None:
        """An unknown pattern id yields a 'not found' message and exit code 1."""
        with patch("mahavishnu.cli.scaffold_cli._get_library") as get_lib:
            lib = PatternLibrary(patterns_root)
            lib.load_all()
            get_lib.return_value = lib

            result = runner.invoke(app, ["patterns", "show", "missing/foo"])
            assert result.exit_code == 1
            assert "not found" in result.output


# ============== patterns validate ==============


class TestPatternsValidate:
    """Tests for `mahavishnu patterns validate`."""

    def test_validate_clean_library_exits_zero(self) -> None:
        """A library with all-valid patterns reports clean and exits 0."""
        good = MagicMock()
        good.id = "ok/thing"
        with patch("mahavishnu.cli.scaffold_cli.validate_pattern", return_value=[]):
            with patch("mahavishnu.cli.scaffold_cli._get_library") as get_lib:
                lib = MagicMock()
                lib._cache = {"ok/thing": good}
                get_lib.return_value = lib

                result = runner.invoke(app, ["patterns", "validate"])
                assert result.exit_code == 0, result.output
                assert "All patterns valid." in result.output

    def test_validate_with_issues_exits_nonzero(self) -> None:
        """A pattern that fails validation surfaces issues and exits with code 1."""
        bad = MagicMock()
        bad.id = "broken/thing"
        # Pretend this pattern has 2 validation issues
        with (
            patch("mahavishnu.cli.scaffold_cli.validate_pattern", return_value=["err1", "err2"]),
            patch("mahavishnu.cli.scaffold_cli._get_library") as get_lib,
        ):
            lib = MagicMock()
            lib._cache = {"broken/thing": bad}
            get_lib.return_value = lib

            result = runner.invoke(app, ["patterns", "validate"])
            assert result.exit_code == 1
            assert "broken/thing" in result.output
            assert "err1" in result.output
            assert "err2" in result.output
            assert "2 validation errors" in result.output


# ============== patterns search ==============


class TestPatternsSearch:
    """Tests for `mahavishnu patterns search`."""

    def test_search_returns_matching_patterns(self, real_library: PatternLibrary) -> None:
        """Search returns matching patterns by name/description/tags."""
        with patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library):
            # Search for "admin" which is in tag and description
            result = runner.invoke(app, ["patterns", "search", "admin"])
            assert result.exit_code == 0
            assert "Found" in result.output
            assert "adapters/admin" in result.output

    def test_search_no_results(self, real_library: PatternLibrary) -> None:
        """Empty results print a 'no patterns matching' notice."""
        with patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library):
            result = runner.invoke(app, ["patterns", "search", "zzz_no_such_token"])
            assert result.exit_code == 0
            assert "No patterns matching" in result.output

    def test_search_with_source_repos_filter(self, real_library: PatternLibrary) -> None:
        """--source-repos filters by source_repos containing the value."""
        with patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library):
            result = runner.invoke(
                app,
                ["patterns", "search", "admin", "--source-repos", "splashstand"],
            )
            assert result.exit_code == 0
            assert "Found" in result.output
            assert "adapters/admin" in result.output


# ============== scaffold ==============


class TestScaffoldCommand:
    """Tests for the `scaffold` subcommand."""

    def test_dry_run_resolves_dependencies(self, real_library: PatternLibrary) -> None:
        """--dry-run prints the resolved pattern list without touching the filesystem."""
        with patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library):
            result = runner.invoke(
                app,
                [
                    "scaffold",
                    "demo-app",
                    "--patterns",
                    "adapters/admin",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 0, result.output
            assert "dry-run" in result.output
            assert "demo-app" in result.output
            assert "adapters/admin" in result.output
            # Dependencies of adapters/admin are auto-resolved in the dry-run output
            assert "scaffolding/project" in result.output

    def test_dry_run_unknown_pattern_exits_nonzero(self, real_library: PatternLibrary) -> None:
        """An unknown pattern id in --patterns yields a non-zero exit code."""
        with patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library):
            result = runner.invoke(
                app,
                [
                    "scaffold",
                    "demo-app",
                    "--patterns",
                    "nope/missing",
                    "--dry-run",
                ],
            )
            assert result.exit_code == 1
            assert "not found" in result.output

    def test_real_scaffold_creates_project_directory(
        self, real_library: PatternLibrary, tmp_path: Path
    ) -> None:
        """A non-dry-run scaffold writes the project to the output directory."""
        with patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library):
            output = tmp_path / "out"
            result = runner.invoke(
                app,
                [
                    "scaffold",
                    "my-app",
                    "--patterns",
                    "adapters/admin",
                    "--output",
                    str(output),
                    "--title",
                    "My App",
                    "--author",
                    "Tester",
                    "--version",
                    "0.0.1",
                ],
            )
            assert result.exit_code == 0, result.output
            assert "Scaffolded" in result.output
            # The engine writes the project to the output directory directly,
            # so a manifest/pyproject.toml file should appear under output.
            assert (output / "pyproject.toml").exists()

    def test_scaffold_rejects_path_traversal(self, real_library: PatternLibrary) -> None:
        """Project names containing '/', '\\', or '..' are rejected."""
        with patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library):
            result = runner.invoke(
                app,
                [
                    "scaffold",
                    "../escape",
                    "--patterns",
                    "adapters/admin",
                ],
            )
            assert result.exit_code == 1
            assert "must not contain" in result.output

    def test_scaffold_engine_value_error_exits_nonzero(self, real_library: PatternLibrary) -> None:
        """A ValueError raised by the engine is converted to a CLI exit code 1."""
        with (
            patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library),
            patch("mahavishnu.cli.scaffold_cli.ScaffoldingEngine") as engine_cls,
        ):
            engine = engine_cls.return_value
            engine.scaffold.side_effect = ValueError("nope")
            result = runner.invoke(
                app,
                [
                    "scaffold",
                    "ok-name",
                    "--patterns",
                    "adapters/admin",
                ],
            )
            assert result.exit_code == 1
            assert "nope" in result.output


# ============== scaffold-validate ==============


class TestScaffoldValidate:
    """Tests for the `scaffold-validate` subcommand."""

    def test_validate_clean_project_exits_zero(
        self, real_library: PatternLibrary, tmp_path: Path
    ) -> None:
        """A freshly scaffolded project should validate cleanly."""
        with patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library):
            # First scaffold
            scaffold_result = runner.invoke(
                app,
                [
                    "scaffold",
                    "ok-app",
                    "--patterns",
                    "adapters/admin",
                    "--output",
                    str(tmp_path),
                ],
            )
            assert scaffold_result.exit_code == 0, scaffold_result.output
            # The engine writes to the output directory directly
            project = tmp_path
            assert (project / "pyproject.toml").exists()

            # Then validate it
            validate_result = runner.invoke(app, ["scaffold-validate", "--project", str(project)])
            assert validate_result.exit_code == 0, validate_result.output
            assert "is valid" in validate_result.output

    def test_validate_with_issues_exits_nonzero(
        self, real_library: PatternLibrary, tmp_path: Path
    ) -> None:
        """If the engine reports issues, the CLI exits with code 1."""
        with (
            patch("mahavishnu.cli.scaffold_cli._get_library", return_value=real_library),
            patch("mahavishnu.cli.scaffold_cli.ScaffoldingEngine") as engine_cls,
        ):
            engine = engine_cls.return_value
            engine.validate_project.return_value = ["issue 1", "issue 2"]
            result = runner.invoke(
                app,
                ["scaffold-validate", "--project", str(tmp_path / "anything")],
            )
            assert result.exit_code == 1
            assert "Validation issues" in result.output
            assert "issue 1" in result.output
            assert "issue 2" in result.output
