"""Containment tests for the doc-drift resolver.

A document reference is untrusted text once a hostile document reaches a
scanned store. The resolver must not follow such a reference out of the
repository: the script parses the Python files it resolves, so escaping the
root turns a documentation gate into an arbitrary-file reader.

Kept in its own module so it does not entangle with the drift-gate
behaviour tests.
"""

from __future__ import annotations

import os
from pathlib import Path

from scripts.audit_doc_drift import (
    TreeIndex,
    contain_within,
    path_candidates,
    resolve_path,
)


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_path_candidates_rejects_parent_traversal(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    candidates = path_candidates("../../etc/passwd", root, None, "mahavishnu")

    assert candidates == []


def test_path_candidates_keeps_repo_relative_references(tmp_path: Path) -> None:
    root = _repo(tmp_path)

    candidates = path_candidates("docs/specs/a.md", root, None, "mahavishnu")

    assert root / "docs/specs/a.md" in candidates


def test_contain_within_accepts_a_file_inside_the_root(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    inside = root / "inside.py"
    inside.write_text("def ok() -> None: ...\n")

    assert contain_within(inside, root) == Path(os.path.realpath(inside))


def test_contain_within_rejects_a_symlink_escaping_the_root(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("def secret() -> None: ...\n")
    (root / "link.py").symlink_to(outside)

    assert contain_within(root / "link.py", root) is None


def test_resolve_path_does_not_resolve_outside_the_repository(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    secret = tmp_path / "secret.py"
    secret.write_text("def leaked() -> None: ...\n")

    resolved, _in_scope = resolve_path(
        "../secret.py", root, None, set(), "mahavishnu", TreeIndex(root)
    )

    assert resolved is None


def test_resolve_path_still_resolves_a_file_inside_the_repository(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "docs" / "specs").mkdir(parents=True)
    spec = root / "docs" / "specs" / "a.md"
    spec.write_text("# spec\n")

    resolved, in_scope = resolve_path(
        "docs/specs/a.md", root, None, set(), "mahavishnu", TreeIndex(root)
    )

    assert resolved == Path(os.path.realpath(spec))
    assert in_scope is True
