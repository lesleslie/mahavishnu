"""Tests for mahavishnu.mcp.crow.tools.rg_search — ripgrep-backed search.

RED phase: tests written before implementation.
"""
from __future__ import annotations

import pytest

from mahavishnu.mcp.crow.tools.rg_search import rg_search

# ---- happy path -------------------------------------------------------------


@pytest.mark.unit
async def test_rg_search_finds_matches_in_workspace(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    (tmp_path / "b.py").write_text("def world(): pass\n")
    result = await rg_search("hello", settings_with_rg, path=str(tmp_path))
    assert result["engine"] == "ripgrep"
    assert result["pattern"] == "hello"
    assert result["format"] == "content"
    assert result["total_found"] == 1
    assert len(result["matches"]) == 1
    m = result["matches"][0]
    assert m["file"].endswith("a.py")
    assert m["line_number"] == 1
    assert "hello" in m["match"]


@pytest.mark.unit
async def test_rg_search_empty_matches(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    result = await rg_search("ZZZNOTHERE", settings_with_rg, path=str(tmp_path))
    assert result["matches"] == []
    assert result["total_found"] == 0
    assert result["truncated"] is False


@pytest.mark.unit
async def test_rg_search_returns_files_with_matches_format(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    (tmp_path / "b.py").write_text("def hello(): pass\n")
    (tmp_path / "c.py").write_text("unrelated\n")
    result = await rg_search(
        "hello", settings_with_rg, path=str(tmp_path), format="files_with_matches"
    )
    assert result["format"] == "files_with_matches"
    assert result["total_found"] == 2
    assert all(isinstance(f, str) for f in result["matches"])


@pytest.mark.unit
async def test_rg_search_returns_json_format(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("def hello(): pass\n")
    result = await rg_search(
        "hello", settings_with_rg, path=str(tmp_path), format="json"
    )
    assert result["format"] == "json"
    assert result["total_found"] >= 1
    # JSON entries must include a "type"=="match" field
    assert result["matches"][0].get("type") == "match"


@pytest.mark.unit
async def test_rg_search_case_insensitive(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("Hello World\n")
    result = await rg_search(
        "hello", settings_with_rg, path=str(tmp_path), case_sensitive=False
    )
    assert result["total_found"] == 1


@pytest.mark.unit
async def test_rg_search_fixed_string_no_regex(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("a + b = c\n")
    # Without -F, "a + b" is interpreted as regex (literal in this case OK)
    # But "(a)" would differ — test that . is escaped by fixed_string
    (tmp_path / "b.py").write_text("foo.bar\n")
    result_fixed = await rg_search(
        "foo.bar", settings_with_rg, path=str(tmp_path), fixed_string=True
    )
    assert result_fixed["total_found"] == 1
    assert result_fixed["matches"][0]["file"].endswith("b.py")


@pytest.mark.unit
async def test_rg_search_truncates_at_max(tmp_path, settings_with_rg):
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text(f"hello line in file {i}\n")
    result = await rg_search(
        "hello", settings_with_rg, path=str(tmp_path), max_matches=3
    )
    assert result["truncated"] is True
    assert result["total_found"] == 3


@pytest.mark.unit
async def test_rg_search_include_glob(tmp_path, settings_with_rg):
    (tmp_path / "a.py").write_text("hello\n")
    (tmp_path / "b.txt").write_text("hello\n")
    result = await rg_search(
        "hello", settings_with_rg, path=str(tmp_path), include="*.py"
    )
    assert result["total_found"] == 1
    assert result["matches"][0]["file"].endswith("a.py")


# ---- security --------------------------------------------------------------


@pytest.mark.unit
async def test_rg_search_rejects_path_outside_workspace(tmp_path, settings_with_rg):
    with pytest.raises(PermissionError, match="outside workspace"):
        await rg_search("anything", settings_with_rg, path="/etc")


@pytest.mark.unit
async def test_rg_search_rejects_null_byte(tmp_path, settings_with_rg):
    with pytest.raises(PermissionError, match="null byte"):
        await rg_search("anything", settings_with_rg, path="/tmp/a\x00.py")


@pytest.mark.unit
async def test_rg_search_rejects_symlink_escape(tmp_path, settings_with_rg):
    import os

    link = tmp_path / "escape"
    os.symlink("/etc", link)
    with pytest.raises(PermissionError, match="outside workspace"):
        await rg_search("anything", settings_with_rg, path=str(link / "passwd"))


# ---- availability -----------------------------------------------------------


@pytest.mark.unit
async def test_rg_search_raises_when_rg_unavailable(tmp_path, settings_no_rg):
    (tmp_path / "a.py").write_text("hello\n")
    with pytest.raises(RuntimeError, match="ripgrep"):
        await rg_search("hello", settings_no_rg, path=str(tmp_path))
