"""Tests for Pattern Library storage and query."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mahavishnu.scaffolding.models import Pattern
from mahavishnu.scaffolding.library import PatternLibrary


@pytest.fixture
def lib(tmp_path: Path) -> PatternLibrary:
    return PatternLibrary(root=tmp_path)


@pytest.fixture
def sample_pattern() -> dict:
    return {
        "schema_version": 1,
        "id": "scaffolding/project",
        "name": "Fastblocks Project Skeleton",
        "description": "Base project structure",
        "version": "1.0.0",
        "source_repos": ["fastblocks"],
        "tags": ["fastblocks", "skeleton"],
        "structure": {
            "dirs": [{"path": "settings/", "required": True, "description": "Config"}],
            "files": [{"path": "main.py", "required": True, "template": "entry-point"}],
        },
        "templates": {
            "entry-point": "from starlette.routing import Route\napp = None",
        },
        "slots": {
            "nav": {"path": "templates/base/blocks/", "files": ["nav.html"]},
        },
    }


class TestPatternLibraryLoad:
    def test_load_single_pattern(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(
            yaml.dump(sample_pattern)
        )
        patterns = lib.load_all()
        assert len(patterns) == 1
        assert patterns[0].id == "scaffolding/project"

    def test_load_returns_empty_when_no_patterns(self, lib: PatternLibrary):
        patterns = lib.load_all()
        assert patterns == []

    def test_load_multiple_categories(self, lib: PatternLibrary, sample_pattern: dict):
        for cat in ["scaffolding", "components", "adapters"]:
            lib.root.joinpath(cat).mkdir(parents=True)
            p = dict(sample_pattern)
            p["id"] = f"{cat}/test"
            lib.root.joinpath(cat, "test.yaml").write_text(yaml.dump(p))
        patterns = lib.load_all()
        assert len(patterns) == 3

    def test_load_rejects_invalid_yaml(self, lib: PatternLibrary):
        lib.root.joinpath("bad").mkdir(parents=True)
        lib.root.joinpath("bad", "broken.yaml").write_text("{{invalid yaml")
        with pytest.raises(Exception):
            lib.load_all()


class TestPatternLibraryQuery:
    def test_get_by_id(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(
            yaml.dump(sample_pattern)
        )
        lib.load_all()
        p = lib.get("scaffolding/project")
        assert p is not None
        assert p.name == "Fastblocks Project Skeleton"

    def test_get_missing_returns_none(self, lib: PatternLibrary):
        lib.load_all()
        assert lib.get("nonexistent") is None

    def test_list_by_category(self, lib: PatternLibrary, sample_pattern: dict):
        for cat in ["scaffolding", "components"]:
            lib.root.joinpath(cat).mkdir(parents=True)
            p = dict(sample_pattern)
            p["id"] = f"{cat}/test"
            lib.root.joinpath(cat, "test.yaml").write_text(yaml.dump(p))
        lib.load_all()
        result = lib.list_category("scaffolding")
        assert len(result) == 1
        assert result[0].id == "scaffolding/test"

    def test_search_by_tag(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(
            yaml.dump(sample_pattern)
        )
        lib.load_all()
        results = lib.search("fastblocks")
        assert len(results) == 1

    def test_search_by_name(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(
            yaml.dump(sample_pattern)
        )
        lib.load_all()
        results = lib.search("Skeleton")
        assert len(results) == 1

    def test_has(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(
            yaml.dump(sample_pattern)
        )
        lib.load_all()
        assert lib.has("scaffolding/project") is True
        assert lib.has("nonexistent") is False


class TestPatternLibrarySave:
    def test_save_pattern(self, lib: PatternLibrary):
        p = Pattern(id="scaffolding/test", name="Test")
        lib.save(p)
        assert lib.root.joinpath("scaffolding", "test.yaml").exists()
        loaded = yaml.safe_load(
            lib.root.joinpath("scaffolding", "test.yaml").read_text()
        )
        assert loaded["id"] == "scaffolding/test"

    def test_save_creates_category_dir(self, lib: PatternLibrary):
        p = Pattern(id="newcat/item", name="New")
        lib.save(p)
        assert lib.root.joinpath("newcat").is_dir()
