"""Tests for scripts.audit_orphans.

Covers the cross-module ``__all__`` resolution that drops symbols defined
in one module but re-exported by another from the orphan list. The
resolution builds a ``{symbol_name -> defining_file}`` map from the
top-level public surface and then treats any ``__all__`` entry whose
defining file differs from the ``__all__`` file as a wire-up reference
for that symbol.

The previous loop-2 fix already counted same-file ``__all__`` entries;
this layer extends the rule to cross-file re-exports (the gap closed
by ``_add_cross_module_all_refs``).
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from scripts.audit_orphans import (
    _add_cross_module_all_refs,
    _build_defining_file_map,
    collect_references,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping
    from pathlib import Path


def _write(tmp_path: Path, rel: str, body: str) -> Path:
    """Write a Python source file under ``tmp_path`` and return its path."""
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_cross_module_all_entry_attaches_importer_file(tmp_path: Path) -> None:
    """``__all__`` in pkg_a re-exports ``FooBar`` from pkg_b → pkg_a is a reference."""
    _write(tmp_path, "pkg_a/__init__.py", "")
    _write(tmp_path, "pkg_a/exporter.py", '__all__ = ["FooBar"]\n')
    _write(tmp_path, "pkg_b/__init__.py", "")
    _write(
        tmp_path,
        "pkg_b/definitions.py",
        "class FooBar:\n    pass\n",
    )

    refs: MutableMapping[str, set[Path]] = defaultdict(set)
    defining = _build_defining_file_map(tmp_path, excludes=[], include_tests=False)
    _add_cross_module_all_refs(tmp_path, excludes=[], include_tests=False, defining_files=defining, refs=refs)

    foo_path = tmp_path / "pkg_b" / "definitions.py"
    exporter_path = tmp_path / "pkg_a" / "exporter.py"
    assert refs.get("FooBar") == {exporter_path}
    assert defining["FooBar"] == foo_path


def test_same_file_all_entry_not_re_attached(tmp_path: Path) -> None:
    """``__all__ = ["FooBar"]`` in the file that defines FooBar is not a cross-module reference."""
    _write(
        tmp_path,
        "pkg/__init__.py",
        "class FooBar:\n    pass\n\n__all__ = ['FooBar']\n",
    )

    refs: MutableMapping[str, set[Path]] = defaultdict(set)
    defining = _build_defining_file_map(tmp_path, excludes=[], include_tests=False)
    _add_cross_module_all_refs(tmp_path, excludes=[], include_tests=False, defining_files=defining, refs=refs)

    # Cross-module resolver deliberately skips same-file entries; the main
    # walker already records them (and the cross-file filter discards them).
    assert "FooBar" not in refs


def test_undefined_all_entry_does_not_crash(tmp_path: Path) -> None:
    """``__all__`` may list names that aren't defined anywhere (external imports)."""
    _write(
        tmp_path,
        "pkg/__init__.py",
        '__all__ = ["ExternalLib", "AnotherOne"]\n',
    )

    refs: MutableMapping[str, set[Path]] = defaultdict(set)
    defining = _build_defining_file_map(tmp_path, excludes=[], include_tests=False)
    _add_cross_module_all_refs(tmp_path, excludes=[], include_tests=False, defining_files=defining, refs=refs)

    assert refs == {}


def test_method_names_are_qualified_in_defining_map(tmp_path: Path) -> None:
    """Method names don't shadow top-level symbols in the defining-file map."""
    _write(
        tmp_path,
        "pkg/__init__.py",
        (
            "def render():\n"
            "    pass\n\n"
            "class Renderer:\n"
            "    def render(self):\n"
            "        pass\n\n"
            "__all__ = ['render', 'Renderer.render']\n"
        ),
    )

    defining = _build_defining_file_map(tmp_path, excludes=[], include_tests=False)

    pkg_init = tmp_path / "pkg" / "__init__.py"
    assert defining["render"] == pkg_init
    assert defining["Renderer.render"] == pkg_init


def test_collect_references_includes_cross_module_all(tmp_path: Path) -> None:
    """End-to-end: ``collect_references`` attaches the cross-module __all__ importer."""
    _write(tmp_path, "pkg_a/__init__.py", "")
    _write(tmp_path, "pkg_a/exporter.py", '__all__ = ["FooBar"]\n')
    _write(tmp_path, "pkg_b/__init__.py", "")
    _write(tmp_path, "pkg_b/definitions.py", "class FooBar:\n    pass\n")

    refs = collect_references(tmp_path, excludes=[], include_tests=False)

    exporter_path = tmp_path / "pkg_a" / "exporter.py"
    # The cross-module resolver attaches pkg_a/exporter.py as a reference
    # for FooBar (its defining file is in pkg_b/, so the resolver records
    # the importer).
    assert exporter_path in refs["FooBar"]
    # The defining file is NOT in refs unless it ALSO has an ``__all__``
    # listing FooBar — the main walker only attaches references via
    # Name/Attribute/Assign+__all__ shapes, not via definition sites.
    foo_defining_path = tmp_path / "pkg_b" / "definitions.py"
    assert foo_defining_path not in refs["FooBar"]


def test_collect_references_respects_include_tests(tmp_path: Path) -> None:
    """``--include-tests`` lets test-defined symbols participate in cross-module resolution."""
    _write(tmp_path, "pkg_a/__init__.py", "")
    _write(tmp_path, "pkg_a/exporter.py", '__all__ = ["helper"]\n')
    _write(tmp_path, "tests/__init__.py", "")
    _write(
        tmp_path,
        "tests/test_helper.py",
        "def helper():\n    pass\n",
    )

    test_helper = tmp_path / "tests" / "test_helper.py"
    exporter = tmp_path / "pkg_a" / "exporter.py"

    # Without tests: helper has no defining file in the scanned tree, so
    # the defining-file map omits it and the resolver skips the
    # cross-module attachment. pkg_a/exporter.py is still a reference for
    # helper via the loop-2 __all__ walker (it contains the __all__).
    defining_no_tests = _build_defining_file_map(tmp_path, excludes=[], include_tests=False)
    assert "helper" not in defining_no_tests
    refs_no_tests = collect_references(tmp_path, excludes=[], include_tests=False)
    assert exporter in refs_no_tests["helper"]

    # With tests: the defining-file map locates helper in tests/, so the
    # resolver recognises the cross-module re-export and adds the
    # importer as a reference (which the loop-2 walker already recorded).
    defining_with_tests = _build_defining_file_map(tmp_path, excludes=[], include_tests=True)
    assert defining_with_tests["helper"] == test_helper
    refs_with_tests = collect_references(tmp_path, excludes=[], include_tests=True)
    assert exporter in refs_with_tests["helper"]


def test_collect_references_respects_excludes(tmp_path: Path) -> None:
    """Excluded directories are skipped by both the main walker and the cross-module resolver."""
    _write(tmp_path, "pkg/__init__.py", "class FooBar:\n    pass\n")
    _write(tmp_path, "pkg/exporter.py", '__all__ = ["FooBar"]\n')
    _write(tmp_path, "scripts/__init__.py", "")
    _write(tmp_path, "scripts/other.py", '__all__ = ["FooBar"]\n')

    # scripts/ is excluded; the main walker + resolver both skip it.
    refs = collect_references(tmp_path, excludes=["scripts"], include_tests=False)

    pkg_exporter = tmp_path / "pkg" / "exporter.py"
    scripts_other = tmp_path / "scripts" / "other.py"
    # The non-excluded pkg/exporter.py is the cross-module reference.
    assert pkg_exporter in refs["FooBar"]
    # The defining file is not in refs (no __all__ in pkg/__init__.py).
    foo_defining = tmp_path / "pkg" / "__init__.py"
    assert foo_defining not in refs["FooBar"]
    # scripts/ is excluded so neither walker nor resolver touches it.
    assert scripts_other not in refs["FooBar"]
