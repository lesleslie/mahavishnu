"""Tests for pattern Pydantic models."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from mahavishnu.scaffolding.models import (
    DirSpec,
    FileSpec,
    Pattern,
    PatternDependency,
    SlotSpec,
)


class TestPatternDependency:
    def test_minimal_dependency(self):
        dep = PatternDependency(id="scaffolding/project")
        assert dep.id == "scaffolding/project"
        assert dep.version is None

    def test_dependency_with_version(self):
        dep = PatternDependency(id="scaffolding/project", version=">=1.0.0")
        assert dep.version == ">=1.0.0"

    def test_dependency_rejects_empty_id(self):
        with pytest.raises(ValidationError):
            PatternDependency(id="")


class TestDirSpec:
    def test_required_dir(self):
        d = DirSpec(path="settings/", required=True, description="Config dir")
        assert d.path == "settings/"
        assert d.required is True

    def test_optional_dir(self):
        d = DirSpec(path="static/", required=False, description="Assets")
        assert d.required is False


class TestFileSpec:
    def test_required_file_with_template(self):
        f = FileSpec(path="main.py", required=True, template="entry-point")
        assert f.template == "entry-point"

    def test_file_without_template_defaults_to_path(self):
        f = FileSpec(path="pyproject.toml", required=True)
        assert f.template == "pyproject.toml"


class TestSlotSpec:
    def test_directory_slot_defaults(self):
        s = SlotSpec(path="templates/base/blocks/", files=["nav.html"])
        assert s.type == "directory"
        assert s.required is False

    def test_file_merge_slot(self):
        s = SlotSpec(
            path="main.py",
            type="file-merge",
            merge_strategy="marker-injection",
        )
        assert s.type == "file-merge"
        assert s.merge_strategy == "marker-injection"

    def test_slot_rejects_bad_type(self):
        with pytest.raises(ValidationError):
            SlotSpec(path="main.py", type="symlink")


class TestPattern:
    def test_minimal_pattern(self):
        p = Pattern(id="scaffolding/project", name="Project Skeleton")
        assert p.schema_version == 1
        assert p.confidence == 1.0
        assert p.depends == []
        assert p.tags == []

    def test_full_pattern(self):
        p = Pattern(
            id="adapters/auth",
            name="Auth Adapter",
            description="Session-based auth",
            version="1.0.0",
            source_repos=["splashstand"],
            tags=["auth", "session"],
            structure={
                "dirs": [{"path": "adapters/", "required": True, "description": "Adapters"}],
                "files": [{"path": "adapters/auth.py", "required": True}],
            },
            templates={"auth-module": "from starlette.middleware import Middleware"},
            slots={
                "middleware": {
                    "path": "main.py",
                    "type": "file-merge",
                    "merge_strategy": "marker-injection",
                }
            },
        )
        assert len(p.structure["dirs"]) == 1
        assert p.templates["auth-module"] == "from starlette.middleware import Middleware"

    def test_rejects_path_traversal_in_dirs(self):
        with pytest.raises(ValidationError):
            Pattern(
                id="bad/pattern",
                name="Bad",
                structure={"dirs": [{"path": "../../etc/", "required": True}], "files": []},
            )

    def test_rejects_path_traversal_in_files(self):
        with pytest.raises(ValidationError):
            Pattern(
                id="bad/pattern",
                name="Bad",
                structure={"dirs": [], "files": [{"path": "/etc/passwd", "required": True}]},
            )
