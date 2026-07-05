"""L3 tests for Crackerjack skill anti-ai-flavor-check."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mahavishnu.quality.anti_ai_flavor_check import run_anti_ai_flavor_check

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def sop_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / ".bodai").mkdir()
    (tmp_path / ".bodai" / "style-sop.md").write_text(
        "---\n"
        "bans:\n"
        "  - pattern: 'verified locally'\n"
        "    message: 'Proof must be command-reproducible'\n"
        "---\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "module.py").write_text("# code")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_skill_returns_violations(sop_repo: Path):
    target_file = sop_repo / "src" / "module.py"
    content = "# Changelog\n\nverified locally"
    result = run_anti_ai_flavor_check(content, target_file)
    assert len(result["violations"]) == 1
    assert "command-reproducible" in result["violations"][0]["message"]


def test_skill_returns_empty_for_clean_content(sop_repo: Path):
    target_file = sop_repo / "src" / "module.py"
    content = "# Changelog\n\n- Fix bug X\n- Add test Y"
    result = run_anti_ai_flavor_check(content, target_file)
    assert result["violations"] == []


def test_skill_includes_sop_source(sop_repo: Path):
    target_file = sop_repo / "src" / "module.py"
    content = "verified locally"
    result = run_anti_ai_flavor_check(content, target_file)
    assert result["sop_source"] is not None
    assert result["sop_source"].endswith("style-sop.md")
