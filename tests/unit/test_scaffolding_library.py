"""Tests for Pattern Library storage and query."""

from __future__ import annotations

import stat
import threading
from typing import TYPE_CHECKING

import pytest
import yaml

from mahavishnu.scaffolding.library import PatternLibrary
from mahavishnu.scaffolding.models import Pattern

if TYPE_CHECKING:
    from pathlib import Path


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
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
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
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
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
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
        lib.load_all()
        results = lib.search("fastblocks")
        assert len(results) == 1

    def test_search_by_name(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
        lib.load_all()
        results = lib.search("Skeleton")
        assert len(results) == 1

    def test_has(self, lib: PatternLibrary, sample_pattern: dict):
        lib.root.joinpath("scaffolding").mkdir(parents=True)
        lib.root.joinpath("scaffolding", "project.yaml").write_text(yaml.dump(sample_pattern))
        lib.load_all()
        assert lib.has("scaffolding/project") is True
        assert lib.has("nonexistent") is False


class TestPatternLibrarySave:
    def test_save_pattern(self, lib: PatternLibrary):
        p = Pattern(id="scaffolding/test", name="Test")
        lib.save(p)
        assert lib.root.joinpath("scaffolding", "test.yaml").exists()
        loaded = yaml.safe_load(lib.root.joinpath("scaffolding", "test.yaml").read_text())
        assert loaded["id"] == "scaffolding/test"

    def test_save_creates_category_dir(self, lib: PatternLibrary):
        p = Pattern(id="newcat/item", name="New")
        lib.save(p)
        assert lib.root.joinpath("newcat").is_dir()


class TestPatternLibraryAtomicSave:
    """The pattern file is published atomically and owner-only.

    The writer used to go through a *fixed-name* temp file
    (``path.with_suffix(".tmp")``) and then rename it over the
    destination. That shares one temp file between every writer of the
    same destination, reuses whatever a crashed earlier write left
    behind, and follows a symlink planted at the predictable temp path.
    """

    def test_the_pattern_is_published_owner_only(self, lib: PatternLibrary):
        lib.save(Pattern(id="scaffolding/test", name="Test"))

        dest = lib.root / "scaffolding" / "test.yaml"
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600

    def test_save_leaves_no_temp_file_behind(self, lib: PatternLibrary):
        lib.save(Pattern(id="scaffolding/test", name="Test"))

        dest = lib.root / "scaffolding" / "test.yaml"
        leftovers = [p.name for p in dest.parent.iterdir() if p != dest]
        assert not leftovers, f"the writer left files behind: {leftovers}"

    def test_a_stale_temp_file_cannot_leak_its_permissions(self, lib: PatternLibrary):
        """A leftover temp file from a crashed write must not be reused.

        ``Path.write_text`` truncates an existing file *in place* and
        keeps its mode, so a stale temp left at 0644 would publish the
        pattern at 0644 no matter what the writer intended.
        """
        category = lib.root / "scaffolding"
        category.mkdir(parents=True)
        stale = category / "test.tmp"
        stale.write_text("poison")
        stale.chmod(0o644)

        lib.save(Pattern(id="scaffolding/test", name="Test"))

        dest = category / "test.yaml"
        assert "poison" not in dest.read_text()
        assert stat.S_IMODE(dest.stat().st_mode) == 0o600

    def test_a_symlinked_temp_path_is_not_written_through(self, lib: PatternLibrary):
        """The old temp name was ``test.tmp``; it must not be reused.

        ``Path.write_text`` opens with ``O_CREAT | O_TRUNC``, which
        follows a symlink -- so a planted link would have its target
        overwritten.
        """
        category = lib.root / "scaffolding"
        category.mkdir(parents=True)
        victim = lib.root / "victim.txt"
        victim.write_text("precious")
        (category / "test.tmp").symlink_to(victim)

        lib.save(Pattern(id="scaffolding/test", name="Test"))

        assert victim.read_text() == "precious"

    def test_concurrent_saves_all_succeed(self, lib: PatternLibrary):
        """Every writer of one destination must survive.

        With a fixed temp name the first writer to rename moves the
        file away from the others, whose rename then raises
        ``FileNotFoundError``.
        """
        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def writer(index: int) -> None:
            try:
                barrier.wait()
                for _ in range(25):
                    lib.save(Pattern(id="scaffolding/test", name=f"Test {index}"))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"concurrent saves raised: {errors[:3]}"
        dest = lib.root / "scaffolding" / "test.yaml"
        assert yaml.safe_load(dest.read_text())["id"] == "scaffolding/test"
