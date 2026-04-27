"""Tests for Scaffolding Engine Phase 1."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from mahavishnu.scaffolding.models import Pattern
from mahavishnu.scaffolding.library import PatternLibrary
from mahavishnu.scaffolding.engine import ScaffoldingEngine


@pytest.fixture
def engine(tmp_path: Path) -> ScaffoldingEngine:
    lib = PatternLibrary(root=Path(__file__).resolve().parent.parent.parent / "patterns")
    lib.load_all()
    return ScaffoldingEngine(library=lib)


class TestEngineScaffold:
    def test_scaffold_minimal_project(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-app",
            patterns=["scaffolding/minimal"],
            output_dir=tmp_path / "test-app",
        )
        assert (result / "main.py").exists()
        assert (result / "pyproject.toml").exists()
        assert "test-app" in (result / "pyproject.toml").read_text()

    def test_scaffold_project_creates_dirs(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-app",
            patterns=["scaffolding/project"],
            output_dir=tmp_path / "test-app",
        )
        assert (result / "settings").is_dir()
        assert (result / "templates" / "base" / "blocks").is_dir()

    def test_variables_rendered(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="my-cool-app",
            patterns=["scaffolding/minimal"],
            output_dir=tmp_path / "test-app",
            title="My Cool App",
        )
        content = (result / "main.py").read_text()
        assert "my-cool-app" in content
        assert "My Cool App" in content

    def test_composite_patterns(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-pwa",
            patterns=["composite/pwa-app"],
            output_dir=tmp_path / "test-pwa",
        )
        assert (result / "main.py").exists()
        assert (result / "Dockerfile").exists()

    def test_manifest_written(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-app",
            patterns=["scaffolding/minimal"],
            output_dir=tmp_path / "test-app",
        )
        manifest = result / ".mahavishnu" / "manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text())
        assert data["project_name"] == "test-app"
        assert len(data["patterns"]) >= 1

    def test_file_merge_slot(self, engine: ScaffoldingEngine, tmp_path: Path):
        result = engine.scaffold(
            project_name="test-auth",
            patterns=["scaffolding/project", "adapters/auth"],
            output_dir=tmp_path / "test-auth",
        )
        content = (result / "main.py").read_text()
        assert "middleware" in content.lower() or "Middleware" in content

    def test_circular_dependency_fails(self, tmp_path: Path):
        lib = PatternLibrary(root=tmp_path)
        lib.root.joinpath("a").mkdir()
        lib.root.joinpath("b").mkdir()
        lib.root.joinpath("a", "a.yaml").write_text(
            yaml.dump({
                "id": "a/x",
                "name": "X",
                "depends": [{"id": "b/y"}],
                "structure": {"dirs": [], "files": []},
                "schema_version": 1,
            })
        )
        lib.root.joinpath("b", "b.yaml").write_text(
            yaml.dump({
                "id": "b/y",
                "name": "Y",
                "depends": [{"id": "a/x"}],
                "structure": {"dirs": [], "files": []},
                "schema_version": 1,
            })
        )
        lib.load_all()
        eng = ScaffoldingEngine(library=lib)
        with pytest.raises(Exception, match="ircular"):
            eng.scaffold("test", ["a/x", "b/y"], tmp_path / "test")

    def test_missing_dependency_fails(self, engine: ScaffoldingEngine, tmp_path: Path):
        with pytest.raises(Exception, match="not found"):
            engine.scaffold("test", ["nonexistent/x"], tmp_path / "test")

    def test_atomic_rollback_on_failure(self, engine: ScaffoldingEngine, tmp_path: Path):
        output = tmp_path / "should-not-exist"
        with pytest.raises(Exception):
            engine.scaffold("test", ["nonexistent/x"], output)
        assert not output.exists()
