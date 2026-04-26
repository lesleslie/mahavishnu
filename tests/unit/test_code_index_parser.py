"""Tests for file parser."""

from pathlib import Path

import pytest

from mahavishnu.core.code_index.parser import (
    SKIP_DIRS,
    PARSABLE_EXTENSIONS,
    filter_changed_files,
    parse_file,
)


def test_parse_file_skips_non_python(tmp_path):
    """Non-Python files return None."""
    test_file = tmp_path / "readme.md"
    test_file.write_text("# Hello")
    result = parse_file(str(test_file), str(tmp_path), "abc123")
    assert result is None


def test_parse_file_skips_pycache(tmp_path):
    """Files in __pycache__ return None."""
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    test_file = cache_dir / "mod.cpython-312.pyc"
    test_file.write_text("not real python")
    result = parse_file(str(test_file), str(tmp_path), "abc123")
    assert result is None


def test_parse_file_skips_git(tmp_path):
    """Files in .git return None."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    test_file = git_dir / "config"
    test_file.write_text("not real python")
    result = parse_file(str(test_file), str(tmp_path), "abc123")
    assert result is None


def test_parse_file_raises_on_bad_python(tmp_path):
    """Actual parse failures should raise, not return None."""
    test_file = tmp_path / "bad.py"
    test_file.write_text("def (")
    with pytest.raises(Exception):
        parse_file(str(test_file), str(tmp_path), "abc123")


def test_parsable_extensions():
    assert ".py" in PARSABLE_EXTENSIONS
    assert ".js" not in PARSABLE_EXTENSIONS


def test_skip_dirs():
    assert ".git" in SKIP_DIRS
    assert "node_modules" in SKIP_DIRS
    assert "__pycache__" in SKIP_DIRS


def test_filter_changed_files_full_index(tmp_path):
    """Full re-index (commit_hash=None) returns all .py files."""
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    (tmp_path / "c.md").write_text("c")
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "d.py").write_text("d")

    result = filter_changed_files(str(tmp_path), None)
    assert str(tmp_path / "a.py") in result
    assert str(tmp_path / "b.py") in result
    assert str(tmp_path / "c.md") not in result
    # filter_changed_files does NOT skip directories (it is for git diff output).
    # The skip logic lives in parse_file.
