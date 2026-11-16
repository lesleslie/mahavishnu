"""Tests for ``scripts.audit_no_secrets_in_mcp.find_mcp_json_files``.

The scan originally used ``Path.rglob(".mcp.json")``, which cannot prune
directories and therefore descends into every ``.venv`` and
``node_modules`` tree under the scan root. A fleet-wide scan took 103 s
for 32 matching files — the traversal, not the matching, was the cost.
The walk now prunes dependency and VCS directories in place.

These tests pin the pruning contract: files inside pruned directories
must NOT be reported, and files elsewhere must still be found.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scripts.audit_no_secrets_in_mcp import PRUNED_DIR_NAMES, find_mcp_json_files

if TYPE_CHECKING:
    from pathlib import Path


def _write_mcp_json(path: Path) -> Path:
    """Create a minimal ``.mcp.json`` at *path*, making parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"mcpServers": {}}\n', encoding="utf-8")
    return path


class TestFindMcpJsonFiles:
    def test_finds_files_at_root_and_nested(self, tmp_path: Path) -> None:
        """Files at the scan root and in nested dirs are found."""
        root_file = _write_mcp_json(tmp_path / ".mcp.json")
        nested_file = _write_mcp_json(tmp_path / "sub" / "deep" / ".mcp.json")

        found = find_mcp_json_files([tmp_path])

        assert root_file in found
        assert nested_file in found

    def test_prunes_dependency_and_vcs_directories(self, tmp_path: Path) -> None:
        """Files inside pruned directories are not reported.

        ``.venv``/``node_modules`` hold installed artifacts, and
        ``.git``/``.worktrees`` hold VCS metadata — a checked-in
        ``.mcp.json`` never legitimately lives in any of them.
        """
        kept = _write_mcp_json(tmp_path / ".mcp.json")
        pruned = [
            _write_mcp_json(tmp_path / ".venv" / "lib" / ".mcp.json"),
            _write_mcp_json(tmp_path / "node_modules" / "pkg" / ".mcp.json"),
            _write_mcp_json(tmp_path / ".git" / ".mcp.json"),
            _write_mcp_json(tmp_path / ".worktrees" / "wt" / ".mcp.json"),
        ]

        found = find_mcp_json_files([tmp_path])

        assert kept in found
        for path in pruned:
            assert path not in found

    def test_missing_root_is_skipped(self, tmp_path: Path) -> None:
        """A non-existent scan root yields no files, not an error."""
        found = find_mcp_json_files([tmp_path / "does-not-exist"])

        assert found == []

    def test_pruned_dir_names_cover_dependency_trees(self) -> None:
        """The prune list keeps the heavy traversal dirs out of the walk."""
        for name in (".venv", "node_modules", ".git", ".worktrees"):
            assert name in PRUNED_DIR_NAMES

    def test_returns_sorted_paths(self, tmp_path: Path) -> None:
        """Results are sorted so output ordering is deterministic."""
        first = _write_mcp_json(tmp_path / "a" / ".mcp.json")
        second = _write_mcp_json(tmp_path / "b" / ".mcp.json")

        found = find_mcp_json_files([tmp_path])

        assert found == sorted(found)
        assert {first, second} == set(found)
