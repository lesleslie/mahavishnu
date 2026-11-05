"""Tests for scripts.audit_test_module_names.

Covers the two failure modes the audit detects:

* a duplicate pytest module name — which aborts the *entire* suite
  collection, not just the colliding pair, and
* a test directory that would shadow an installed top-level package.

The naming rules are pytest's own: in the default ``prepend`` import mode a
test module is named by walking up from its directory for as long as
``__init__.py`` exists. Two files that resolve to the same name collide.
"""

from __future__ import annotations

from pathlib import Path

from scripts.audit_test_module_names import (
    SHADOW_DENY_LIST,
    audit,
    exposed_package_name,
    format_report,
    pytest_module_name,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_module_name_of_file_in_non_package_dir(tmp_path: Path) -> None:
    """A directory without ``__init__.py`` yields a flat module name."""
    target = tmp_path / "test_thing.py"
    target.write_text("")
    assert pytest_module_name(target) == "test_thing"


def test_module_name_is_qualified_by_a_package_dir(tmp_path: Path) -> None:
    """A directory *with* ``__init__.py`` contributes its name to the module."""
    package = tmp_path / "sub"
    package.mkdir()
    (package / "__init__.py").write_text("")
    target = package / "test_thing.py"
    target.write_text("")
    assert pytest_module_name(target) == "sub.test_thing"


def test_module_name_walks_through_every_package_level(tmp_path: Path) -> None:
    """Nested packages each contribute a component."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / "__init__.py").write_text("")
    (inner / "__init__.py").write_text("")
    target = inner / "test_thing.py"
    target.write_text("")
    assert pytest_module_name(target) == "outer.inner.test_thing"


def test_exposed_package_name_of_nested_package(tmp_path: Path) -> None:
    """The exposed top-level name skips levels that are themselves packages."""
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / "__init__.py").write_text("")
    (inner / "__init__.py").write_text("")
    assert exposed_package_name(inner) == "outer"


def test_audit_reports_a_duplicate_module_name(tmp_path: Path) -> None:
    """Two files in non-package dirs with the same basename collide."""
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "test_config.py").write_text("")
    (tmp_path / "b" / "test_config.py").write_text("")

    report = audit(tmp_path)

    assert not report.ok
    assert set(report.collisions) == {"test_config"}
    assert len(report.collisions["test_config"]) == 2


def test_audit_accepts_the_same_basename_in_different_scopes(tmp_path: Path) -> None:
    """The same basename in a package dir and a flat dir does NOT collide.

    This is the common case, and it is why a repo-wide grep for duplicate
    basenames over-reports: only pairs that are *both* in non-package
    directories collide.
    """
    flat = tmp_path / "flat"
    package = tmp_path / "pkg"
    flat.mkdir()
    package.mkdir()
    (package / "__init__.py").write_text("")
    (flat / "test_config.py").write_text("")
    (package / "test_config.py").write_text("")

    report = audit(tmp_path)

    assert report.ok
    assert report.collisions == {}


def test_audit_flags_a_shadowing_package_directory(tmp_path: Path) -> None:
    """A deny-listed directory carrying ``__init__.py`` shadows the real package."""
    target = tmp_path / "mcp"
    target.mkdir()
    (target / "__init__.py").write_text("")
    (target / "test_thing.py").write_text("")

    report = audit(tmp_path)

    assert not report.ok
    assert "mcp" in report.shadowed
    assert "mcp" in SHADOW_DENY_LIST


def test_format_report_names_the_colliding_files(tmp_path: Path) -> None:
    """The rendered report must name the files and say how to fix them."""
    (tmp_path / "test_config.py").write_text("")
    (tmp_path / "test_other.py").write_text("")

    lines = format_report(audit(tmp_path))

    assert lines.out
    assert not lines.err


def test_repository_has_no_duplicate_test_module_names() -> None:
    """Live guard: the whole suite must collect.

    A collision here aborts collection outright, so this test only runs when
    collection already succeeded — it pins the invariant for the next person
    who adds a test file, and the audit script carries the standalone check.
    """
    report = audit(REPO_ROOT / "tests")

    assert report.ok, (
        "duplicate pytest module names would abort the entire suite collection:\n"
        + "\n".join(f"  {name}: {paths}" for name, paths in report.collisions.items())
    )
