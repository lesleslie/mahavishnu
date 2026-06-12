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

    def test_slot_outside_declared_dirs(self, library_with_project: PatternLibrary) -> None:
        """A slot path that is outside all declared dirs should be flagged."""
        p = Pattern(
            id="test/orphan-slot",
            name="Orphan Slot",
            structure={"dirs": [{"path": "settings/", "required": True}]},
            slots={
                "loose": {
                    "name": "loose",
                    "path": "no-such-dir/file.py",
                    "type": "file-merge",
                }
            },
        )
        issues = validate_pattern(p, library_with_project)
        assert any("outside all pattern dirs" in i for i in issues)

    def test_slot_path_within_declared_dir(self, library_with_project: PatternLibrary) -> None:
        """A slot whose path lives under a declared dir should NOT be flagged."""
        p = Pattern(
            id="test/nested-slot",
            name="Nested Slot",
            structure={"dirs": [{"path": "settings/", "required": True}]},
            slots={
                "ok": {"name": "ok", "path": "settings/app.yaml", "type": "file-merge"}
            },
        )
        issues = validate_pattern(p, library_with_project)
        assert not any("outside all pattern dirs" in i for i in issues)

    def test_circular_dependency_detected(self, library_with_project: PatternLibrary) -> None:
        """Circular dependencies (A -> B -> A) should be detected."""
        # Build a fake library that has two patterns A and B with mutual deps.
        class FakeLib:
            _file_paths: dict = {}

            def __init__(self) -> None:
                self._store: dict[str, Pattern] = {}

            def has(self, pid: str) -> bool:
                return pid in self._store

            def get(self, pid: str) -> Pattern | None:
                return self._store.get(pid)

        a = Pattern(id="a/x", name="A", depends=[{"id": "b/y"}])
        b = Pattern(id="b/y", name="B", depends=[{"id": "a/x"}])
        lib = FakeLib()
        lib._store["a/x"] = a
        lib._store["b/y"] = b

        issues = validate_pattern(a, lib)
        assert any("Circular dependency" in i for i in issues)

    def test_dependency_chain_no_cycle(self, library_with_project: PatternLibrary) -> None:
        """Linear (non-circular) dependency chain should NOT report a cycle."""

        class FakeLib:
            _file_paths: dict = {}

            def __init__(self) -> None:
                self._store: dict[str, Pattern] = {}

            def has(self, pid: str) -> bool:
                return pid in self._store

            def get(self, pid: str) -> Pattern | None:
                return self._store.get(pid)

        a = Pattern(id="a/x", name="A", depends=[{"id": "b/y"}])
        b = Pattern(id="b/y", name="B", depends=[{"id": "c/z"}])
        c = Pattern(id="c/z", name="C")
        lib = FakeLib()
        lib._store["a/x"] = a
        lib._store["b/y"] = b
        lib._store["c/z"] = c

        issues = validate_pattern(a, lib)
        assert not any("Circular dependency" in i for i in issues)

    def test_dependency_branch_with_no_dependents(self) -> None:
        """A dep that has no further deps should not be flagged as a cycle."""

        class FakeLib:
            _file_paths: dict = {}

            def __init__(self) -> None:
                self._store: dict[str, Pattern] = {}

            def has(self, pid: str) -> bool:
                return pid in self._store

            def get(self, pid: str) -> Pattern | None:
                p = self._store.get(pid)
                return p

        a = Pattern(id="only/a", name="A", depends=[{"id": "leaf/b"}])
        b = Pattern(id="leaf/b", name="B")
        lib = FakeLib()
        lib._store["only/a"] = a
        lib._store["leaf/b"] = b

        issues = validate_pattern(a, lib)
        assert not any("Circular dependency" in i for i in issues)

    def test_slot_path_exact_match_with_dir(self, library_with_project: PatternLibrary) -> None:
        """A slot whose path is exactly a declared dir name should NOT be flagged."""
        p = Pattern(
            id="test/exact-slot",
            name="Exact Slot",
            structure={"dirs": [{"path": "settings/", "required": True}]},
            slots={
                "exact": {
                    "name": "exact",
                    "path": "settings",
                    "type": "directory",
                }
            },
        )
        issues = validate_pattern(p, library_with_project)
        assert not any("outside all pattern dirs" in i for i in issues)

    def test_no_dirs_with_slot(self, library_with_project: PatternLibrary) -> None:
        """When pattern has no dirs and a slot, the slot should not be flagged."""
        p = Pattern(
            id="test/no-dirs",
            name="No Dirs",
            structure={"dirs": []},
            slots={
                "anywhere": {
                    "name": "anywhere",
                    "path": "src/foo.py",
                    "type": "file-merge",
                }
            },
        )
        issues = validate_pattern(p, library_with_project)
        assert not any("outside all pattern dirs" in i for i in issues)
