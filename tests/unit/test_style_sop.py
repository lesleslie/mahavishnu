"""L0 tests for style SOP parser/discovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mahavishnu.core.style_sop import (
    discover_style_sop,
    load_style_sop,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_discover_returns_none_when_no_sop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "some_file.py").write_text("# no sop here")
    monkeypatch.chdir(tmp_path)
    # Walk up to filesystem root — should return None when no SOP exists.
    # Note: packaged default exists, but discover only walks repo .bodai dirs.
    result = discover_style_sop(tmp_path)
    assert result is None


def test_discover_finds_repo_sop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".bodai").mkdir()
    sop_file = tmp_path / ".bodai" / "style-sop.md"
    sop_file.write_text("---\nbans: []\n---\n\n# Body\n")
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    result = discover_style_sop(subdir)
    assert result == sop_file


def test_load_style_sop_returns_frontmatter_and_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / ".bodai").mkdir()
    sop_text = (
        "---\n"
        "bans:\n"
        "  - pattern: 'foo'\n"
        "    message: 'no foo'\n"
        "required_disclosures:\n"
        "  - 'always include bar'\n"
        "---\n"
        "\n"
        "# Body\n"
        "This is the prose.\n"
    )
    (tmp_path / ".bodai" / "style-sop.md").write_text(sop_text)
    monkeypatch.chdir(tmp_path)
    sop = load_style_sop(tmp_path)
    assert "bans" in sop["frontmatter"]
    assert sop["frontmatter"]["bans"][0]["pattern"] == "foo"
    assert "Body" in sop["body"]
    assert "This is the prose" in sop["body"]


def test_load_style_sop_handles_missing_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / ".bodai").mkdir()
    (tmp_path / ".bodai" / "style-sop.md").write_text("# Just markdown\n\nNo frontmatter.")
    monkeypatch.chdir(tmp_path)
    sop = load_style_sop(tmp_path)
    assert sop["frontmatter"] == {}
    assert "Just markdown" in sop["body"]


def test_load_style_sop_falls_back_to_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "no_sop_here.py").write_text("")
    monkeypatch.chdir(tmp_path)
    sop = load_style_sop(tmp_path)
    # Should fall back to packaged default.
    assert sop["source_path"] is not None
    assert sop["source_path"].name == "style-sop.md"
