"""Tests for scripts/agent_metadata_audit.py — the agent-directory layout guard.

The guard exists because Claude Code scans agent directories *recursively*:
any ``.md`` file under an agents directory is loaded as an agent, including
files parked in a dot-prefixed subdirectory that looks like an archive.
Untracking those files in git hides them from version control but not from
the loader — 49 retired agents sat in ``.claude/agents/.archive/`` for four
months that way. See ``docs/decisions/agent-curation-strategy.md``.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from scripts.agent_metadata_audit import (
    check_dot_prefixed_subdirectories,
    find_dot_prefixed_agent_files,
    main,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def _write_agent(path: Path, name: str = "demo") -> Path:
    """Write a minimal but valid agent definition."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: A demo agent used by the layout guard tests.\nmodel: inherit\n---\n\nBody text.\n",
        encoding="utf-8",
    )
    return path


def test_clean_agents_dir_has_no_findings(tmp_path: Path) -> None:
    """A directory with only top-level agents is clean."""
    _write_agent(tmp_path / "alpha.md", "alpha")
    _write_agent(tmp_path / "beta.md", "beta")

    assert find_dot_prefixed_agent_files(tmp_path) == []
    assert check_dot_prefixed_subdirectories(str(tmp_path)) == 0


def test_detects_agent_in_dot_prefixed_subdirectory(tmp_path: Path) -> None:
    """The regression this guard exists for: an archive inside the agents dir."""
    hidden = _write_agent(tmp_path / ".archive" / "retired.md", "retired")

    findings = find_dot_prefixed_agent_files(tmp_path)

    assert len(findings) == 1
    assert findings[0][0] == hidden
    assert findings[0][1] == ".archive"
    assert check_dot_prefixed_subdirectories(str(tmp_path)) == 1


def test_detects_nested_dot_prefixed_subdirectory(tmp_path: Path) -> None:
    """A dot-directory several levels down is still inside the scan path."""
    hidden = _write_agent(tmp_path / "sub" / ".deep" / "agent.md", "nested")

    findings = find_dot_prefixed_agent_files(tmp_path)

    assert len(findings) == 1
    assert findings[0][0] == hidden


def test_ignores_non_dot_subdirectory(tmp_path: Path) -> None:
    """A plain subdirectory is not a violation — only dot-prefixed ones are."""
    _write_agent(tmp_path / "subdir" / "agent.md", "nested")

    assert find_dot_prefixed_agent_files(tmp_path) == []


def test_ignores_dot_prefixed_filename_at_top_level(tmp_path: Path) -> None:
    """A dot-prefixed *file* is a different concern from a dot-prefixed dir."""
    _write_agent(tmp_path / ".hidden.md", "hidden")

    assert find_dot_prefixed_agent_files(tmp_path) == []


def test_missing_agents_dir_is_not_an_error(tmp_path: Path) -> None:
    """A missing agents directory yields no findings rather than raising."""
    missing = tmp_path / "does-not-exist"

    assert find_dot_prefixed_agent_files(missing) == []
    assert check_dot_prefixed_subdirectories(str(missing)) == 0


def test_main_exits_nonzero_on_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() returns 1 when an agent is hidden in a dot-prefixed subdirectory."""
    _write_agent(tmp_path / ".archive" / "retired.md", "retired")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent_metadata_audit.py",
            "--agents-dir",
            str(tmp_path),
            "--skip-user-agents-dir",
        ],
    )

    exit_code = main()
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "DOT-PREFIXED SUBDIRECTORY SCAN" in out
    assert "FAILED:" in out


def test_main_exits_zero_when_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() returns 0 when the agents directory layout is clean."""
    _write_agent(tmp_path / "alpha.md", "alpha")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent_metadata_audit.py",
            "--agents-dir",
            str(tmp_path),
            "--skip-user-agents-dir",
        ],
    )

    exit_code = main()
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "No agent files hidden in dot-prefixed subdirectories" in out
