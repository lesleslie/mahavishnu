"""L1/L2 tests for style SOP content validator."""

from __future__ import annotations

from pathlib import Path

import pytest

from mahavishnu.core.style_sop_validator import check_content


@pytest.fixture
def sop_with_bans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".bodai").mkdir()
    (tmp_path / ".bodai" / "style-sop.md").write_text(
        "---\n"
        "bans:\n"
        "  - pattern: 'Co-Authored-By: Claude'\n"
        "    message: 'No AI attribution'\n"
        "  - pattern: '\\*\\*Root cause:\\*\\*'\n"
        "    message: 'No bold-tag structure'\n"
        "---\n"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_check_returns_empty_for_clean_content(sop_with_bans: Path):
    violations = check_content("# Clean MR\n\nThis is fine.", sop_with_bans)
    assert violations == []


def test_check_detects_banned_pattern(sop_with_bans: Path):
    content = "feat: add thing\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    violations = check_content(content, sop_with_bans)
    assert len(violations) == 1
    assert "AI attribution" in violations[0]["message"]


def test_check_detects_multiple_violations(sop_with_bans: Path):
    content = (
        "feat: add thing\n\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>\n\n"
        "**Root cause:** the bug."
    )
    violations = check_content(content, sop_with_bans)
    assert len(violations) == 2


def test_check_uses_default_when_no_repo_sop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # No repo SOP — uses packaged default.
    (tmp_path / "no_sop.py").write_text("")
    monkeypatch.chdir(tmp_path)
    # Default SOP bans "Co-Authored-By: Claude"
    content = "feat: x\n\nCo-Authored-By: Claude <noreply@anthropic.com>"
    violations = check_content(content, tmp_path)
    assert len(violations) >= 1
