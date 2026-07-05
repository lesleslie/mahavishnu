"""Tests for mahavishnu.mcp.crow.tools.file_tools.

RED phase: tests written before implementation.
"""
from __future__ import annotations

import os

import pytest

from mahavishnu.mcp.crow.tools.file_tools import (
    delete_file,
    list_directory,
    read_file,
    stat,
    write_file,
)
from tests.unit.mcp.crow.conftest import mock_settings

# ---- read_file --------------------------------------------------------------


@pytest.mark.unit
async def test_read_file_returns_full_content(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("line1\nline2\nline3\n")
    result = await read_file(str(f), mock_settings(tmp_path))
    assert result["content"] == "line1\nline2\nline3\n"
    assert result["total_lines"] == 3
    assert result["truncated"] is False


@pytest.mark.unit
async def test_read_file_with_pagination(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a\nb\nc\nd\ne\n")
    result = await read_file(str(f), mock_settings(tmp_path), offset=1, limit=2)
    assert result["content"] == "b\nc\n"
    assert result["line_start"] == 2
    assert result["line_end"] == 3
    assert result["truncated"] is True


@pytest.mark.unit
async def test_read_file_rejects_path_outside_workspace(tmp_path):
    with pytest.raises(PermissionError, match="outside workspace"):
        await read_file("/etc/passwd", mock_settings(tmp_path))


@pytest.mark.unit
async def test_read_file_raises_on_binary(tmp_path):
    f = tmp_path / "bin.dat"
    f.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ValueError, match="binary"):
        await read_file(str(f), mock_settings(tmp_path))


@pytest.mark.unit
async def test_read_file_raises_on_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        await read_file(str(tmp_path / "nope.py"), mock_settings(tmp_path))


# ---- write_file -------------------------------------------------------------


@pytest.mark.unit
async def test_write_file_creates_new(tmp_path):
    f = tmp_path / "new.py"
    result = await write_file(str(f), "x = 1\n", mock_settings(tmp_path))
    assert result["written"] is True
    assert f.read_text() == "x = 1\n"
    assert result["bytes"] == 6


@pytest.mark.unit
async def test_write_file_overwrites_existing(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("old")
    await write_file(str(f), "new content", mock_settings(tmp_path))
    assert f.read_text() == "new content"


@pytest.mark.unit
async def test_write_file_creates_parent_dirs(tmp_path):
    f = tmp_path / "deep" / "nested" / "x.py"
    await write_file(str(f), "content", mock_settings(tmp_path))
    assert f.read_text() == "content"


@pytest.mark.unit
async def test_write_file_preserves_permissions(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("old")
    f.chmod(0o755)
    await write_file(str(f), "new", mock_settings(tmp_path))
    assert oct(f.stat().st_mode & 0o777) == oct(0o755)


@pytest.mark.unit
async def test_write_file_atomic_on_failure(tmp_path, monkeypatch):
    """If os.replace fails, original file must remain intact."""
    f = tmp_path / "x.py"
    f.write_text("original")
    def boom(*_a, **_k):
        raise OSError("disk full")
    monkeypatch.setattr("mahavishnu.mcp.crow.tools.file_tools.os.replace", boom)
    with pytest.raises(OSError):
        await write_file(str(f), "new content", mock_settings(tmp_path))
    assert f.read_text() == "original"


@pytest.mark.unit
async def test_write_file_dry_run_does_not_write(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("original")
    result = await write_file(str(f), "new", mock_settings(tmp_path), dry_run=True)
    assert result["written"] is False
    assert f.read_text() == "original"


@pytest.mark.unit
async def test_write_file_rejects_outside_workspace(tmp_path):
    with pytest.raises(PermissionError, match="outside workspace"):
        await write_file("/etc/foo", "x", mock_settings(tmp_path))


# ---- list_directory ---------------------------------------------------------


@pytest.mark.unit
async def test_list_directory_returns_entries(tmp_path):
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "sub").mkdir()
    result = await list_directory(str(tmp_path), mock_settings(tmp_path))
    names = {e["name"] for e in result["entries"]}
    assert {"a.py", "b.txt", "sub"}.issubset(names)
    assert result["count"] >= 3


@pytest.mark.unit
async def test_list_directory_excludes_hidden_by_default(tmp_path):
    (tmp_path / "visible.py").write_text("x")
    (tmp_path / ".hidden.py").write_text("x")
    result = await list_directory(str(tmp_path), mock_settings(tmp_path))
    names = {e["name"] for e in result["entries"]}
    assert "visible.py" in names
    assert ".hidden.py" not in names


@pytest.mark.unit
async def test_list_directory_include_hidden(tmp_path):
    (tmp_path / ".hidden.py").write_text("x")
    result = await list_directory(
        str(tmp_path), mock_settings(tmp_path), include_hidden=True
    )
    names = {e["name"] for e in result["entries"]}
    assert ".hidden.py" in names


@pytest.mark.unit
async def test_list_directory_skips_always_skip_dirs(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "x.py").write_text("x")
    result = await list_directory(str(tmp_path), mock_settings(tmp_path))
    names = {e["name"] for e in result["entries"]}
    assert ".git" not in names
    assert "node_modules" not in names
    assert "__pycache__" not in names


@pytest.mark.unit
async def test_list_directory_rejects_outside_workspace(tmp_path):
    with pytest.raises(PermissionError, match="outside workspace"):
        await list_directory("/etc", mock_settings(tmp_path))


# ---- stat -------------------------------------------------------------------


@pytest.mark.unit
async def test_stat_returns_file_metadata(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("hello\n")
    result = await stat(str(f), mock_settings(tmp_path))
    assert result["is_file"] is True
    assert result["is_dir"] is False
    assert result["size_bytes"] == 6
    assert result["path"] == str(f.resolve())


@pytest.mark.unit
async def test_stat_returns_dir_metadata(tmp_path):
    d = tmp_path / "subdir"
    d.mkdir()
    result = await stat(str(d), mock_settings(tmp_path))
    assert result["is_dir"] is True
    assert result["is_file"] is False


@pytest.mark.unit
async def test_stat_raises_on_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        await stat(str(tmp_path / "nope.py"), mock_settings(tmp_path))


@pytest.mark.unit
async def test_stat_rejects_outside_workspace(tmp_path):
    with pytest.raises(PermissionError, match="outside workspace"):
        await stat("/etc/passwd", mock_settings(tmp_path))


# ---- delete_file ------------------------------------------------------------


@pytest.mark.unit
async def test_delete_file_removes_existing(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("hello")
    result = await delete_file(str(f), mock_settings(tmp_path))
    assert result["deleted"] is True
    assert not f.exists()


@pytest.mark.unit
async def test_delete_file_missing_returns_false(tmp_path):
    result = await delete_file(str(tmp_path / "nope.py"), mock_settings(tmp_path))
    assert result["deleted"] is False


@pytest.mark.unit
async def test_delete_file_rejects_directory_by_default(tmp_path):
    d = tmp_path / "subdir"
    d.mkdir()
    with pytest.raises(ValueError, match="directory"):
        await delete_file(str(d), mock_settings(tmp_path))


@pytest.mark.unit
async def test_delete_file_rejects_outside_workspace(tmp_path):
    with pytest.raises(PermissionError, match="outside workspace"):
        await delete_file("/etc/foo", mock_settings(tmp_path))


# ---- null byte / symlink across all tools -----------------------------------


@pytest.mark.unit
async def test_write_file_rejects_null_byte(tmp_path):
    with pytest.raises(PermissionError, match="null byte"):
        await write_file("/tmp/a\x00.py", "x", mock_settings(tmp_path))


@pytest.mark.unit
async def test_read_file_rejects_null_byte(tmp_path):
    with pytest.raises(PermissionError, match="null byte"):
        await read_file("/tmp/a\x00.py", mock_settings(tmp_path))


@pytest.mark.unit
async def test_read_file_rejects_symlink_escape(tmp_path):
    link = tmp_path / "escape"
    os.symlink("/etc", link)
    with pytest.raises(PermissionError, match="outside workspace"):
        await read_file(str(link / "passwd"), mock_settings(tmp_path))
