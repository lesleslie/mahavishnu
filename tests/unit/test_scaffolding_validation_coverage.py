"""Coverage-push tests for scaffolding.validation.validate_pattern; one parametrized case per issues.append branch."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from mahavishnu.scaffolding.library import PatternLibrary
from mahavishnu.scaffolding.models import Pattern
from mahavishnu.scaffolding.validation import validate_pattern


@pytest.fixture
def empty_library(tmp_path: Path) -> PatternLibrary:
    """Empty PatternLibrary rooted at a tmp_path; nothing resolves via has()."""
    return PatternLibrary(root=tmp_path)


def _fake_library(store: dict[str, Pattern]) -> Any:
    """Minimal stand-in for PatternLibrary exposing has()/get().

    _file_paths is left empty so the duplicate-ID branch never fires during
    cycle-detection tests.
    """

    class FakeLib:
        _file_paths: dict[str, Path | None] = {}

        def __init__(self) -> None:
            self._store = store

        def has(self, pid: str) -> bool:
            return pid in self._store

        def get(self, pid: str) -> Pattern | None:
            return self._store.get(pid)

    return FakeLib()


class TestHappyPathBranches:
    """validate_pattern returns [] when no validation rule fires."""

    @pytest.mark.parametrize(
        "pattern_factory",
        [
            pytest.param(
                lambda: Pattern(
                    id="happy/empty",
                    name="Empty",
                    structure={"dirs": [], "files": []},
                ),
                id="empty-pattern-no-issues",
            ),
            pytest.param(
                lambda: Pattern(
                    id="happy/jinja",
                    name="Valid Jinja",
                    structure={"dirs": [], "files": []},
                    templates={
                        "ok1": "Hello {{ name }}",
                        "ok2": "{% if x %}yes{% endif %}",
                    },
                ),
                id="valid-jinja-templates-no-issues",
            ),
            pytest.param(
                lambda: Pattern(
                    id="happy/slot",
                    name="Valid Slot",
                    structure={"dirs": [{"path": "src/"}]},
                    slots={
                        "s": {"name": "s", "path": "src/sub/file.py", "type": "file-merge"},
                    },
                ),
                id="slot-inside-declared-dir-no-issues",
            ),
        ],
    )
    def test_returns_empty_issues(
        self,
        pattern_factory: Callable[[], Pattern],
        empty_library: PatternLibrary,
    ) -> None:
        issues = validate_pattern(pattern_factory(), empty_library)
        assert issues == []


class TestSingleIssueBranches:
    """One parametrize case per issues.append branch; each fires exactly once."""

    @pytest.mark.parametrize(
        ("pattern_factory", "expected_substrings"),
        [
            pytest.param(
                lambda: Pattern(
                    id="missing/tmpl",
                    name="Missing Tmpl",
                    structure={
                        "dirs": [],
                        "files": [
                            {"path": "x.py", "required": True, "template": "nope"},
                        ],
                    },
                    templates={},
                ),
                ["x.py", "nope"],
                id="missing-template-branch",
            ),
            pytest.param(
                lambda: Pattern(
                    id="slot/orphan",
                    name="Orphan",
                    structure={"dirs": [{"path": "src/"}]},
                    slots={
                        "s": {"name": "s", "path": "elsewhere/foo.py", "type": "file-merge"},
                    },
                ),
                ["outside all pattern dirs"],
                id="slot-outside-dirs-branch",
            ),
            pytest.param(
                lambda: Pattern(
                    id="jinja/bad",
                    name="Bad Jinja",
                    templates={"bad": "{% if %}"},
                ),
                ["Jinja2 syntax error"],
                id="jinja-syntax-error-branch",
            ),
            pytest.param(
                lambda: Pattern(
                    id="deps/missing",
                    name="Missing Dep",
                    depends=[{"id": "ghost/pattern"}],
                ),
                ["ghost/pattern", "not found"],
                id="dep-not-found-branch",
            ),
        ],
    )
    def test_single_branch(
        self,
        pattern_factory: Callable[[], Pattern],
        expected_substrings: list[str],
        empty_library: PatternLibrary,
    ) -> None:
        issues = validate_pattern(pattern_factory(), empty_library)
        for substr in expected_substrings:
            assert any(substr in i for i in issues), (
                f"Expected substring {substr!r} in issues {issues!r}"
            )


class TestCircularDependencyBranches:
    """Cycle detection via the recursive _check_cycles helper."""

    def test_two_node_cycle(self) -> None:
        a = Pattern(id="a/x", name="A", depends=[{"id": "b/y"}])
        b = Pattern(id="b/y", name="B", depends=[{"id": "a/x"}])
        lib = _fake_library({"a/x": a, "b/y": b})
        issues = validate_pattern(a, lib)
        assert any("Circular dependency" in i for i in issues)

    def test_three_node_cycle(self) -> None:
        a = Pattern(id="a/x", name="A", depends=[{"id": "b/y"}])
        b = Pattern(id="b/y", name="B", depends=[{"id": "c/z"}])
        c = Pattern(id="c/z", name="C", depends=[{"id": "a/x"}])
        lib = _fake_library({"a/x": a, "b/y": b, "c/z": c})
        issues = validate_pattern(a, lib)
        assert any("Circular dependency" in i for i in issues)

    def test_self_dependency_cycle(self) -> None:
        """A pattern that depends on itself triggers the cycle branch."""
        a = Pattern(id="self/x", name="Self", depends=[{"id": "self/x"}])
        lib = _fake_library({"self/x": a})
        issues = validate_pattern(a, lib)
        assert any("Circular dependency" in i for i in issues)


class TestDuplicateAndIdDirMismatchBranches:
    """Duplicate-ID and ID/dir-mismatch both rely on _file_paths / _file_path."""

    def test_duplicate_id_branch(self, tmp_path: Path) -> None:
        lib = PatternLibrary(root=tmp_path)
        cat = tmp_path / "cat"
        cat.mkdir()
        for n in ("a", "b"):
            (cat / f"{n}.yaml").write_text(
                yaml.dump({"id": "cat/dup", "name": n, "schema_version": 1}),
            )
        lib.load_all()
        p = lib.get("cat/dup")
        assert p is not None
        issues = validate_pattern(p, lib)
        assert any("Duplicate pattern ID" in i for i in issues)

    def test_id_dir_mismatch_branch(self, tmp_path: Path) -> None:
        lib = PatternLibrary(root=tmp_path)
        cat = tmp_path / "actual_dir"
        cat.mkdir()
        (cat / "x.yaml").write_text(
            yaml.dump({"id": "wrong_id/x", "name": "X", "schema_version": 1}),
        )
        lib.load_all()
        p = lib.get("wrong_id/x")
        assert p is not None
        issues = validate_pattern(p, lib)
        assert any("doesn't match directory" in i for i in issues)

    def test_no_file_path_skips_id_dir_check(self, empty_library: PatternLibrary) -> None:
        """A Pattern built directly (no _file_path attribute) skips the ID/dir check."""
        p = Pattern(
            id="any/id-format",
            name="Any",
            structure={"dirs": [], "files": []},
        )
        issues = validate_pattern(p, empty_library)
        assert not any("directory" in i.lower() for i in issues)

    def test_non_path_file_path_skips_id_dir_check(self, empty_library: PatternLibrary) -> None:
        """A _file_path set to a non-Path value also skips the ID/dir check."""
        p = Pattern(
            id="any/other-id",
            name="Other",
            structure={"dirs": [], "files": []},
        )
        object.__setattr__(p, "_file_path", "not-a-path")
        issues = validate_pattern(p, empty_library)
        assert not any("directory" in i.lower() for i in issues)


class TestMultiBranchAggregation:
    """Patterns with multiple issues should produce multiple issue lines."""

    def test_multiple_missing_templates(self, empty_library: PatternLibrary) -> None:
        p = Pattern(
            id="multi/tmpl",
            name="Multi Tmpl",
            structure={
                "dirs": [],
                "files": [
                    {"path": "a.py", "required": True, "template": "tA"},
                    {"path": "b.py", "required": True, "template": "tB"},
                ],
            },
            templates={},
        )
        issues = validate_pattern(p, empty_library)
        assert sum(1 for i in issues if "missing" in i.lower()) == 2

    def test_valid_complex_jinja_template(self, empty_library: PatternLibrary) -> None:
        """A well-formed template with for-loops and conditionals must NOT trip the jinja branch."""
        p = Pattern(
            id="good/jinja",
            name="Good Jinja",
            templates={"x": "{% for i in items %}{{ i.name }}: {{ i.value }}\n{% endfor %}"},
        )
        issues = validate_pattern(p, empty_library)
        assert not any("Jinja2" in i for i in issues)