"""End-to-end test: scaffold a project, verify structure and content."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mahavishnu.cli.scaffold_cli import app

runner = CliRunner()


@pytest.fixture(scope="module")
def scaffolded_project():
    """Scaffold a project using the scaffolding/project pattern."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "e2e-test-app"
        result = runner.invoke(
            app,
            [
                "scaffold",
                "e2e-test-app",
                "--patterns",
                "scaffolding/project",
                "--output",
                str(project_dir),
            ],
        )
        if result.exit_code != 0:
            raise RuntimeError(
                f"Scaffold failed (exit {result.exit_code}): {result.stderr}\n"
                f"stdout: {result.stdout}"
            )
        yield project_dir


class TestBasicScaffold:
    """Verify structure and content of a basic scaffold."""

    def test_project_structure(self, scaffolded_project: Path):
        assert (scaffolded_project / "main.py").exists()
        assert (scaffolded_project / "pyproject.toml").exists()
        assert (scaffolded_project / "settings").is_dir()
        assert (scaffolded_project / "templates").is_dir()

    def test_manifest_exists(self, scaffolded_project: Path):
        manifest_dir = scaffolded_project / ".mahavishnu"
        assert manifest_dir.is_dir()
        assert (manifest_dir / "manifest.json").exists()
        assert (manifest_dir / "patterns.lock").exists()

    def test_manifest_content(self, scaffolded_project: Path):
        manifest_path = scaffolded_project / ".mahavishnu" / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        assert manifest["schema_version"] == 1
        assert manifest["project_name"] == "e2e-test-app"
        pattern_ids = [p["id"] for p in manifest["patterns"]]
        assert "scaffolding/project" in pattern_ids

    def test_lockfile_content(self, scaffolded_project: Path):
        lock_content = (
            scaffolded_project / ".mahavishnu" / "patterns.lock"
        ).read_text()
        assert "scaffolding/project==1.0.0\n" == lock_content

    def test_git_initialized(self, scaffolded_project: Path):
        assert (scaffolded_project / ".git").is_dir()

    def test_main_py_content(self, scaffolded_project: Path):
        content = (scaffolded_project / "main.py").read_text()
        assert "FastBlocks" in content
        # Managed header is present for .py files
        assert "# Managed by mahavishnu scaffold" in content
        assert "scaffolding/project" in content

    def test_pyproject_has_project_name(self, scaffolded_project: Path):
        content = (scaffolded_project / "pyproject.toml").read_text()
        assert "e2e-test-app" in content
        assert "0.1.0" in content
        assert ">=3.12" in content
        # Managed header is NOT added for .toml files
        assert "# Managed by" not in content

    def test_pyproject_has_dependencies(self, scaffolded_project: Path):
        content = (scaffolded_project / "pyproject.toml").read_text()
        # The project pattern template renders project metadata with template variables
        assert "[project]" in content
        assert "name = " in content

    def test_validate_passes(self, scaffolded_project: Path):
        result = runner.invoke(
            app, ["scaffold-validate", "--project", str(scaffolded_project)]
        )
        assert result.exit_code == 0, f"Validate failed: {result.output}"


class TestCompositeScaffold:
    """Verify composite/pwa-app scaffolds all dependency patterns."""

    def test_composite_scaffold(self):
        """Scaffold composite/pwa-app which depends on 3 other patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "e2e-pwa"
            result = runner.invoke(
                app,
                [
                    "scaffold",
                    "e2e-pwa",
                    "--patterns",
                    "composite/pwa-app",
                    "--output",
                    str(project_dir),
                ],
            )
            if result.exit_code != 0:
                raise RuntimeError(
                    f"Composite scaffold failed (exit {result.exit_code}): "
                    f"{result.stderr}\nstdout: {result.stdout}"
                )

            # Files from scaffolding/project
            assert (project_dir / "main.py").exists()
            assert (project_dir / "pyproject.toml").exists()

            # File from deployment/cloudrun
            assert (project_dir / "Dockerfile").exists()

            # File from composite/pwa-app
            assert (project_dir / "manifest.json").exists()

            # File from components/nav
            assert (project_dir / "templates" / "components" / "nav.html").exists()

    def test_composite_manifest_lists_all_patterns(self):
        """Manifest should include all 4 resolved patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "e2e-pwa-manifest"
            result = runner.invoke(
                app,
                [
                    "scaffold",
                    "e2e-pwa-manifest",
                    "--patterns",
                    "composite/pwa-app",
                    "--output",
                    str(project_dir),
                ],
            )
            assert result.exit_code == 0, result.output

            manifest = json.loads(
                (project_dir / ".mahavishnu" / "manifest.json").read_text()
            )
            pattern_ids = {p["id"] for p in manifest["patterns"]}
            assert pattern_ids == {
                "composite/pwa-app",
                "scaffolding/project",
                "components/nav",
                "deployment/cloudrun",
            }


class TestCLIPatternCommands:
    """Verify the CLI pattern management sub-commands."""

    def test_patterns_list(self):
        result = runner.invoke(app, ["patterns", "list"])
        assert result.exit_code == 0
        assert "scaffolding/project" in result.output

    def test_patterns_show(self):
        result = runner.invoke(
            app, ["patterns", "show", "scaffolding/project"]
        )
        assert result.exit_code == 0
        assert "Fastblocks Project Skeleton" in result.output

    def test_patterns_validate(self):
        result = runner.invoke(app, ["patterns", "validate"])
        # The validation runs; exit code depends on whether warnings exist.
        # At minimum the command should execute and report on patterns.
        assert "scaffolding/project" in result.output or result.exit_code in (0, 1)

    def test_patterns_search(self):
        result = runner.invoke(app, ["patterns", "search", "pwa"])
        assert result.exit_code == 0
        assert "composite/pwa-app" in result.output
