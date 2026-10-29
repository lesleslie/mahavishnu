"""Guard: published documents must not leak a machine's directory layout.

mahavishnu is a **public** repository. Any absolute path in a tracked file
discloses the operator's account name and local directory layout to anyone
who clones the repo. The registry already publishes root-relative paths;
these tests hold the same line for the documents that sit beside it.

A root-relative path is resolved against the "projects root" -- the
directory that holds the fleet checkouts -- via ``$BODAI_PROJECTS_ROOT``,
the repository's own location, or ``~/Projects``.
"""

from __future__ import annotations

from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKER_PATH = REPO_ROOT / "docs" / "mcp" / "SERVER_MIGRATION_TRACKER.md"
DISPATCH_PATH = REPO_ROOT / "docs" / "audit-inventory" / "PHASE_1_DISPATCH.md"

# A markdown table row: "| cell | cell | ... |". The path cell is the
# second one, and it is always written in backticks.
_ROW_RE = re.compile(r"^\|.*\|$")


def _table_cells(text: str) -> list[list[str]]:
    """Every markdown table row in `text`, as a list of trimmed cells."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not _ROW_RE.match(stripped):
            continue
        rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
    return rows


def _path_cells(text: str) -> list[str]:
    """The path cell of every row whose second cell holds a path."""
    paths: list[str] = []
    for cells in _table_cells(text):
        if len(cells) < 2:
            continue
        cell = cells[1]
        if not cell.startswith("`") or not cell.endswith("`"):
            continue
        inner = cell.strip("`")
        # A path cell is a directory reference: it ends in a slash or
        # contains a separator. Prose cells ("Migration not started") do not.
        if not (inner.endswith("/") or "/" in inner):
            continue
        paths.append(inner)
    return paths


def test_tracker_contains_no_absolute_path() -> None:
    """No absolute path may appear anywhere in the tracker."""
    text = TRACKER_PATH.read_text(encoding="utf-8")

    assert "/Users/" not in text


def test_tracker_path_cells_are_root_relative() -> None:
    """Every path cell is relative to the projects root."""
    paths = _path_cells(TRACKER_PATH.read_text(encoding="utf-8"))

    assert paths, "the tracker is expected to have path cells"
    for path in paths:
        assert not path.startswith("/"), f"{path!r} is absolute"
        assert ".." not in path, f"{path!r} escapes the projects root"


def test_tracker_declares_the_resolution_rule() -> None:
    """A reader must be able to turn a path cell back into a directory."""
    text = TRACKER_PATH.read_text(encoding="utf-8")

    assert "$BODAI_PROJECTS_ROOT" in text
    assert "~/Projects" in text


def test_dispatch_doc_contains_no_absolute_path() -> None:
    """The inventory dispatch template is tracked, so it is published too."""
    text = DISPATCH_PATH.read_text(encoding="utf-8")

    assert "/Users/" not in text
