"""Tests for mahavishnu.core.dev_log.write_entry() — per-merge audit-log
writer for the trunk-based agent-review workflow (REQ-003).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.dev_log import write_entry


@pytest.fixture
def tmp_dev_log_dir(tmp_path, monkeypatch):
    """Redirect DEV_LOG_DIR to a tmp path for test isolation."""
    from mahavishnu.core import paths

    monkeypatch.setattr(paths, "DEV_LOG_DIR", tmp_path)
    return tmp_path


def test_write_entry_creates_file_with_yaml_frontmatter(tmp_dev_log_dir: Path) -> None:
    """write_entry() writes a file with YAML frontmatter + body."""
    metadata = {"date": "2026-10-03", "branch": "fix-ty", "commits_merged": 1}
    body = "# fix-ty\n\nWorker prompt: foo\n"
    path = write_entry(metadata=metadata, body=body, mirror_to_session_buddy=False)
    assert path.exists()
    assert path.parent == tmp_dev_log_dir
    content = path.read_text()
    assert content.startswith("---\n")
    assert "date: 2026-10-03\n" in content
    assert "branch: fix-ty\n" in content
    assert content.endswith("\n# fix-ty\n\nWorker prompt: foo\n")
    assert path.name == "2026-10-03-fix-ty.md"


def test_write_entry_with_nested_reviewers_serializes_to_yaml(tmp_dev_log_dir: Path) -> None:
    """Nested reviewer list renders as YAML block list."""
    metadata = {
        "date": "2026-10-03",
        "branch": "fix-ty",
        "reviewers": [
            {"agent": "python-pro", "verdict": "pass", "note": ""},
            {"agent": "critical-audit-specialist", "verdict": "pass", "note": ""},
        ],
    }
    path = write_entry(metadata=metadata, body="body", mirror_to_session_buddy=False)
    text = path.read_text()
    assert "reviewers:" in text
    assert "  - agent: python-pro" in text
    assert "  - verdict: pass" in text


def test_write_entry_uses_atomic_rename(tmp_dev_log_dir: Path) -> None:
    """A partial write (interrupted mid-flight) leaves no .tmp file."""
    metadata = {"date": "2026-10-03", "branch": "fix-ty"}
    write_entry(metadata=metadata, body="body", mirror_to_session_buddy=False)
    # No leftover .tmp file (rename should have cleaned up)
    tmp_files = list(tmp_dev_log_dir.glob("*.md.tmp"))
    assert tmp_files == []