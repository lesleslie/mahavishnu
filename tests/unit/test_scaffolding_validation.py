"""Tests for pattern validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mahavishnu.scaffolding.library import PatternLibrary
from mahavishnu.scaffolding.models import Pattern
from mahavishnu.scaffolding.validation import validate_pattern


@pytest.fixture
def library_with_project(tmp_path: Path) -> PatternLibrary:
    lib = PatternLibrary(root=tmp_path)
    data = {
        "id": "scaffolding/project",
        "name": "Project",
        "version": "1.0.0",
        "schema_version": 1,
        "structure": {
            "dirs": [{"path": "settings/", "required": True}],
            "files": [{"path": "main.py", "required": True, "template": "entry-point"}],
        },
        "templates": {"entry-point": "pass"},
    }
    lib.root.joinpath("scaffolding").mkdir()
    lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(data))
    lib.load_all()
    return lib


class TestValidatePattern:
    def test_valid_pattern_passes(self, library_with_project: PatternLibrary):
        p = library_with_project.get("scaffolding/project")
        issues = validate_pattern(p, library_with_project)
        assert issues == []

    def test_required_file_missing_template(self, library_with_project: PatternLibrary):
        p = Pattern(
            id="test/missing-tmpl",
            name="Missing Template",
            structure={"dirs": [], "files": [{"path": "missing.py", "required": True}]},
        )
        issues = validate_pattern(p, library_with_project)
        assert any("missing.py" in i for i in issues)

    def test_dependency_not_found(self, library_with_project: PatternLibrary):
        p = Pattern(
            id="test/deps",
            name="Deps",
            depends=[{"id": "nonexistent/pattern"}],
        )
        issues = validate_pattern(p, library_with_project)
        assert any("nonexistent" in i for i in issues)

    def test_id_matches_directory(self, tmp_path: Path):
        lib = PatternLibrary(root=tmp_path)
        lib.root.joinpath("adapters").mkdir()
        data = {
            "id": "WRONG_DIR/auth",
            "name": "Bad",
            "schema_version": 1,
            "structure": {"dirs": [], "files": []},
        }
        lib.root.joinpath("adapters", "auth.yaml").write_text(yaml.dump(data))
        lib.load_all()
        p = lib.get("WRONG_DIR/auth")
        issues = validate_pattern(p, lib)
        assert any("directory" in i.lower() for i in issues)

    def test_jinja2_syntax_error(self, library_with_project: PatternLibrary):
        p = Pattern(
            id="test/bad-jinja",
            name="Bad Jinja",
            templates={"bad": "{% if %}"},
        )
        issues = validate_pattern(p, library_with_project)
        assert any("Jinja2" in i for i in issues)

    def test_duplicate_id(self, tmp_path: Path):
        lib = PatternLibrary(root=tmp_path)
        lib.root.joinpath("cat").mkdir()
        for name in ["a", "b"]:
            lib.root.joinpath("cat", f"{name}.yaml").write_text(
                yaml.dump({"id": "cat/dup", "name": name, "schema_version": 1})
            )
        lib.load_all()
        p = lib.get("cat/dup")
        issues = validate_pattern(p, lib)
        assert any("Duplicate" in i for i in issues)
