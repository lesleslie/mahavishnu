"""Tests for mahavishnu.engines.agno_tools.file_tools.

Targeted at >=80% line+branch coverage of file_tools.py.
Covers:
  * Module-level constants (sanity)
  * _get_allowed_base_dirs (settings + fallback)
  * _validate_path_within_allowed (allowed / not allowed)
  * _detect_path_traversal_attempts (unix, windows, null byte)
  * _validate_path (success, traversal, blocked dir, generic wrap)
  * _validate_file_extension (with / without / disallowed / case-insensitive)
  * _check_file_size (missing, ok, too large)
  * _read_file_impl (utf-8, latin-1 fallback, not found, not file, not allowed)
  * _write_file_impl (success, content too large, parent creation)
  * _list_directory_impl (not found, not a dir, blocked path filter, ordering)
  * _search_files_impl (not found, not a dir, blocked, symlink escape, ok)
  * Agno @tool wrappers (read_file, write_file, list_directory, search_files)
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import pytest

from mahavishnu.core.errors import AgnoError, ErrorCode
from mahavishnu.engines.agno_tools import file_tools
from mahavishnu.engines.agno_tools.file_tools import (
    ALLOWED_EXTENSIONS,
    BLOCKED_PATHS,
    DEFAULT_ALLOWED_BASE_DIRS,
    MAX_FILE_SIZE_BYTES,
    MAX_FILE_SIZE_MB,
    _check_file_size,
    _detect_path_traversal_attempts,
    _get_allowed_base_dirs,
    _list_directory_impl,
    _read_file_impl,
    _search_files_impl,
    _validate_file_extension,
    _validate_path,
    _validate_path_within_allowed,
    _write_file_impl,
    list_directory,
    read_file,
    search_files,
    write_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Provide a tmp_path that is also within DEFAULT_ALLOWED_BASE_DIRS for cwd.

    We will use tmp_path directly (which is in the temp dir, always allowed
    because DEFAULT_ALLOWED_BASE_DIRS includes tempfile.gettempdir()).
    """
    return tmp_path


@pytest.fixture
def inside_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a directory under CWD (which is allowed) and return its path."""
    cwd = Path.cwd()
    workspace = cwd / f"._agno_file_tools_test_{os.getpid()}"
    workspace.mkdir(exist_ok=True)
    monkeypatch.chdir(workspace)
    yield workspace
    # cleanup
    try:
        for child in workspace.iterdir():
            try:
                if child.is_file():
                    child.unlink()
                else:
                    for sub in child.rglob("*"):
                        if sub.is_file():
                            sub.unlink()
                    child.rmdir()
            except OSError:
                pass
        workspace.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_constants_sanity() -> None:
    assert MAX_FILE_SIZE_MB == 10
    assert MAX_FILE_SIZE_BYTES == 10 * 1024 * 1024
    assert ".py" in ALLOWED_EXTENSIONS
    assert ".json" in ALLOWED_EXTENSIONS
    assert ".env" in BLOCKED_PATHS
    assert ".git" in BLOCKED_PATHS
    assert "node_modules" in BLOCKED_PATHS
    assert isinstance(DEFAULT_ALLOWED_BASE_DIRS, list)


# ---------------------------------------------------------------------------
# _get_allowed_base_dirs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_get_allowed_base_dirs_with_settings() -> None:
    """When settings load successfully and allowed_repo_paths is set."""
    sentinel_dir = Path(tempfile.gettempdir()) / "fake_allowed_dir"
    sentinel_dir.mkdir(exist_ok=True)
    try:
        with patch(
            "mahavishnu.core.config.MahavishnuSettings"
        ) as settings_cls:
            instance = settings_cls.return_value
            instance.allowed_repo_paths = [str(sentinel_dir)]
            result = _get_allowed_base_dirs()
        # The first entry should be the resolved sentinel
        assert Path(result[0]).resolve() == sentinel_dir.resolve()
    finally:
        try:
            sentinel_dir.rmdir()
        except OSError:
            pass


@pytest.mark.unit
def test_get_allowed_base_dirs_fallback_when_settings_fails() -> None:
    """When settings import or instantiation fails, fall back to defaults."""
    # Force ImportError inside the function
    with patch.dict(sys.modules, {"mahavishnu.core.config": None}):
        result = _get_allowed_base_dirs()
    # All DEFAULT entries are resolved
    assert all(isinstance(p, Path) for p in result)
    # tempfile.gettempdir() and cwd should be in there
    assert any(Path(p).resolve() == Path(tempfile.gettempdir()).resolve() for p in result)


@pytest.mark.unit
def test_get_allowed_base_dirs_fallback_when_allowed_repo_paths_empty() -> None:
    """When allowed_repo_paths is empty, fall back to defaults."""
    with patch(
        "mahavishnu.core.config.MahavishnuSettings"
    ) as settings_cls:
        instance = settings_cls.return_value
        instance.allowed_repo_paths = []
        result = _get_allowed_base_dirs()
    # Will go to the empty branch (settings.allowed_repo_paths is falsy)
    # so defaults are returned
    assert len(result) >= 2


# ---------------------------------------------------------------------------
# _validate_path_within_allowed
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_path_within_allowed_ok(tmp_workspace: Path) -> None:
    inside = tmp_workspace / "sub.txt"
    _validate_path_within_allowed(inside, [tmp_workspace])
    # No exception


@pytest.mark.unit
def test_validate_path_within_allowed_denied(tmp_workspace: Path) -> None:
    outside = tmp_workspace.parent / "evil.txt"
    with pytest.raises(AgnoError) as exc:
        _validate_path_within_allowed(outside, [tmp_workspace])
    assert exc.value.error_code == ErrorCode.AGNO_TOOL_EXECUTION_ERROR
    assert exc.value.details["error_type"] == "path_traversal_blocked"


@pytest.mark.unit
def test_validate_path_within_allowed_python38_fallback(
    tmp_workspace: Path,
) -> None:
    """Cover the AttributeError fallback to relative_to."""
    inside = tmp_workspace / "ok.txt"
    # Simulate Python <3.9 where Path.is_relative_to is missing
    with patch.object(Path, "is_relative_to", side_effect=AttributeError):
        _validate_path_within_allowed(inside, [tmp_workspace])


@pytest.mark.unit
def test_validate_path_within_allowed_python38_fallback_denied(
    tmp_workspace: Path,
) -> None:
    """Python 3.8-style fallback where relative_to raises ValueError."""
    outside = tmp_workspace.parent / "x.txt"
    with patch.object(Path, "is_relative_to", side_effect=AttributeError):
        with pytest.raises(AgnoError):
            _validate_path_within_allowed(outside, [tmp_workspace])


# ---------------------------------------------------------------------------
# _detect_path_traversal_attempts
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",
        "foo/../bar",
        "/var/../log",
        "foo\\..\\bar",
        "..\\windows",
    ],
)
def test_detect_path_traversal_unix_and_windows(bad: str) -> None:
    with pytest.raises(AgnoError) as exc:
        _detect_path_traversal_attempts(bad)
    assert exc.value.details["error_type"] == "path_traversal_detected"


@pytest.mark.unit
def test_detect_path_traversal_null_byte() -> None:
    with pytest.raises(AgnoError) as exc:
        _detect_path_traversal_attempts("hello\x00world")
    assert exc.value.details["error_type"] == "null_byte_injection"


@pytest.mark.unit
def test_detect_path_traversal_null_byte_url_encoded() -> None:
    with pytest.raises(AgnoError) as exc:
        _detect_path_traversal_attempts("hello%00world")
    assert exc.value.details["error_type"] == "null_byte_injection"


@pytest.mark.unit
def test_detect_path_traversal_clean(tmp_workspace: Path) -> None:
    safe = str(tmp_workspace / "fine.txt")
    _detect_path_traversal_attempts(safe)
    # No exception


# ---------------------------------------------------------------------------
# _validate_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_path_success(tmp_workspace: Path) -> None:
    target = tmp_workspace / "valid.py"
    result = _validate_path(str(target))
    assert result == target.resolve()


@pytest.mark.unit
def test_validate_path_traversal_blocked(tmp_workspace: Path) -> None:
    with pytest.raises(AgnoError) as exc:
        _validate_path("../escape.py")
    assert exc.value.details["error_type"] == "path_traversal_detected"


@pytest.mark.unit
def test_validate_path_blocked_directory(tmp_workspace: Path) -> None:
    # Construct a path that resolves under tmp_workspace but contains a
    # blocked path component like .git
    target = tmp_workspace / ".git" / "config.py"
    with pytest.raises(AgnoError) as exc:
        _validate_path(str(target))
    assert exc.value.details["error_type"] == "blocked_path"
    assert exc.value.details["blocked"] == ".git"


@pytest.mark.unit
def test_validate_path_outside_allowed(tmp_workspace: Path) -> None:
    # Use a path that's well outside allowed dirs (and has a clean path
    # string so we get past _detect_path_traversal_attempts)
    with pytest.raises(AgnoError) as exc:
        _validate_path("/etc/secret_passwd")
    assert exc.value.details["error_type"] == "path_traversal_blocked"


@pytest.mark.unit
def test_validate_path_wraps_unexpected_error() -> None:
    """If something exotic triggers a non-AgnoError exception, wrap it."""
    with patch.object(Path, "resolve", side_effect=OSError("boom")):
        with pytest.raises(AgnoError) as exc:
            _validate_path("/tmp/anything")
    assert exc.value.details["error_type"] == "invalid_path"


# ---------------------------------------------------------------------------
# _validate_file_extension
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_file_extension_no_suffix(tmp_workspace: Path) -> None:
    p = tmp_workspace / "Makefile"
    _validate_file_extension(p)  # no exception


@pytest.mark.unit
def test_validate_file_extension_allowed(tmp_workspace: Path) -> None:
    p = tmp_workspace / "a.py"
    _validate_file_extension(p)


@pytest.mark.unit
def test_validate_file_extension_case_insensitive(tmp_workspace: Path) -> None:
    p = tmp_workspace / "A.PY"
    _validate_file_extension(p)


@pytest.mark.unit
def test_validate_file_extension_blocked(tmp_workspace: Path) -> None:
    p = tmp_workspace / "evil.exe"
    with pytest.raises(AgnoError) as exc:
        _validate_file_extension(p)
    assert exc.value.details["extension"] == ".exe"


# ---------------------------------------------------------------------------
# _check_file_size
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_check_file_size_missing(tmp_workspace: Path) -> None:
    p = tmp_workspace / "does_not_exist.py"
    _check_file_size(p)  # No exception


@pytest.mark.unit
def test_check_file_size_ok(tmp_workspace: Path) -> None:
    p = tmp_workspace / "ok.py"
    p.write_text("hi")
    _check_file_size(p)


@pytest.mark.unit
def test_check_file_size_too_large(tmp_workspace: Path) -> None:
    p = tmp_workspace / "big.py"
    # stat().st_size patched high
    with patch.object(Path, "stat") as stat_mock:
        stat_mock.return_value.st_size = MAX_FILE_SIZE_BYTES + 1
        # Need path.exists() to return True
        with patch.object(Path, "exists", return_value=True):
            with pytest.raises(AgnoError) as exc:
                _check_file_size(p)
    assert "too large" in str(exc.value)


# ---------------------------------------------------------------------------
# _read_file_impl
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_read_file_impl_success(tmp_workspace: Path) -> None:
    p = tmp_workspace / "hello.py"
    p.write_text("print('hi')")
    assert _read_file_impl(str(p)) == "print('hi')"


@pytest.mark.unit
def test_read_file_impl_latin1_fallback(tmp_workspace: Path) -> None:
    p = tmp_workspace / "latin.py"
    # Write raw latin-1 encoded bytes that fail UTF-8 decode
    p.write_bytes(b"caf\xe9")
    result = _read_file_impl(str(p))
    assert "caf" in result


@pytest.mark.unit
def test_read_file_impl_not_found(tmp_workspace: Path) -> None:
    target = tmp_workspace / "missing.py"
    with pytest.raises(AgnoError) as exc:
        _read_file_impl(str(target))
    assert "not found" in str(exc.value).lower()


@pytest.mark.unit
def test_read_file_impl_not_a_file(tmp_workspace: Path) -> None:
    target = tmp_workspace
    with pytest.raises(AgnoError) as exc:
        _read_file_impl(str(target))
    assert "not a file" in str(exc.value).lower()


@pytest.mark.unit
def test_read_file_impl_path_traversal() -> None:
    with pytest.raises(AgnoError):
        _read_file_impl("../escape.py")


@pytest.mark.unit
def test_read_file_impl_blocked_extension(tmp_workspace: Path) -> None:
    p = tmp_workspace / "evil.exe"
    p.write_text("x")
    with pytest.raises(AgnoError) as exc:
        _read_file_impl(str(p))
    assert "not allowed" in str(exc.value)


# ---------------------------------------------------------------------------
# _write_file_impl
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_file_impl_success(tmp_workspace: Path) -> None:
    p = tmp_workspace / "out.py"
    result = _write_file_impl(str(p), "hello")
    assert result["success"] is True
    assert p.read_text() == "hello"


@pytest.mark.unit
def test_write_file_impl_creates_parents(tmp_workspace: Path) -> None:
    p = tmp_workspace / "nested" / "deeper" / "out.py"
    _write_file_impl(str(p), "x")
    assert p.exists()


@pytest.mark.unit
def test_write_file_impl_content_too_large(tmp_workspace: Path) -> None:
    p = tmp_workspace / "huge.py"
    big = "a" * (MAX_FILE_SIZE_BYTES + 1)
    with pytest.raises(AgnoError) as exc:
        _write_file_impl(str(p), big)
    assert "too large" in str(exc.value).lower()


@pytest.mark.unit
def test_write_file_impl_blocked_extension(tmp_workspace: Path) -> None:
    p = tmp_workspace / "evil.exe"
    with pytest.raises(AgnoError):
        _write_file_impl(str(p), "x")


@pytest.mark.unit
def test_write_file_impl_path_traversal() -> None:
    with pytest.raises(AgnoError):
        _write_file_impl("../escape.py", "x")


# ---------------------------------------------------------------------------
# _list_directory_impl
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_directory_impl_success(tmp_workspace: Path) -> None:
    (tmp_workspace / "a.py").write_text("x")
    (tmp_workspace / "b").mkdir()
    entries = _list_directory_impl(str(tmp_workspace))
    assert "a.py" in entries
    assert "b/" in entries
    # Dirs should come first
    assert entries[0] == "b/"


@pytest.mark.unit
def test_list_directory_impl_filters_blocked(tmp_workspace: Path) -> None:
    (tmp_workspace / ".git").mkdir()
    (tmp_workspace / "a.py").write_text("x")
    entries = _list_directory_impl(str(tmp_workspace))
    assert ".git/" not in entries
    assert "a.py" in entries


@pytest.mark.unit
def test_list_directory_impl_not_found(tmp_workspace: Path) -> None:
    target = tmp_workspace / "missing_dir_xyz"
    with pytest.raises(AgnoError) as exc:
        _list_directory_impl(str(target))
    assert "not found" in str(exc.value).lower()


@pytest.mark.unit
def test_list_directory_impl_not_a_dir(tmp_workspace: Path) -> None:
    p = tmp_workspace / "file.py"
    p.write_text("x")
    with pytest.raises(AgnoError) as exc:
        _list_directory_impl(str(p))
    assert "not a directory" in str(exc.value).lower()


@pytest.mark.unit
def test_list_directory_impl_traversal() -> None:
    with pytest.raises(AgnoError):
        _list_directory_impl("../")


# ---------------------------------------------------------------------------
# _search_files_impl
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_search_files_impl_success(tmp_workspace: Path) -> None:
    (tmp_workspace / "a.py").write_text("x")
    (tmp_workspace / "b.txt").write_text("x")
    (tmp_workspace / "sub").mkdir()
    (tmp_workspace / "sub" / "c.py").write_text("x")
    matches = _search_files_impl("*.py", str(tmp_workspace))
    names = {m.replace("\\", "/") for m in matches}
    assert "a.py" in names
    assert "sub/c.py" in names
    assert "b.txt" not in names


@pytest.mark.unit
def test_search_files_impl_filters_blocked(tmp_workspace: Path) -> None:
    (tmp_workspace / "a.py").write_text("x")
    blocked = tmp_workspace / "node_modules"
    blocked.mkdir()
    (blocked / "evil.py").write_text("x")
    matches = _search_files_impl("*.py", str(tmp_workspace))
    joined = " ".join(matches)
    assert "node_modules" not in joined


@pytest.mark.unit
def test_search_files_impl_not_found(tmp_workspace: Path) -> None:
    target = tmp_workspace / "no_such_dir_xyz"
    with pytest.raises(AgnoError) as exc:
        _search_files_impl("*.py", str(target))
    assert "not found" in str(exc.value).lower()


@pytest.mark.unit
def test_search_files_impl_not_a_dir(tmp_workspace: Path) -> None:
    p = tmp_workspace / "file.py"
    p.write_text("x")
    with pytest.raises(AgnoError) as exc:
        _search_files_impl("*.py", str(p))
    assert "not a directory" in str(exc.value).lower()


@pytest.mark.unit
def test_search_files_impl_traversal() -> None:
    with pytest.raises(AgnoError):
        _search_files_impl("*.py", "../")


@pytest.mark.unit
def test_search_files_impl_skips_outside_allowed_match(
    tmp_workspace: Path,
) -> None:
    """If a match is outside allowed dirs, the search skips it.

    Strategy: create a real file, but make its `is_relative_to` always
    return False on the match. We patch the resolved attribute directly
    on the match object to point outside the allowed dirs.
    """
    ok = tmp_workspace / "ok.py"
    ok.write_text("x")
    resolved_root = tmp_workspace.resolve()
    real_ok = ok.resolve()

    # Build the match ahead of time and patch its resolve to escape.
    def fake_rglob(self: Path, pattern: str) -> object:
        yield real_ok

    # On the *match* path, override resolve() to return /etc/passwd.
    # We can't patch globally without breaking _validate_path. Instead,
    # subclass the resolved match to behave like it's outside.
    with patch.object(Path, "rglob", fake_rglob), patch.object(
        Path, "is_file", return_value=True
    ):
        # Replace Path.resolve with a function that escapes only for the match
        original_resolve = Path.resolve

        def selective_resolve(self: Path, *a: object, **kw: object) -> Path:
            r = original_resolve(self)
            if r == real_ok:
                return Path("/etc/passwd")
            return r

        with patch.object(Path, "resolve", selective_resolve):
            matches = _search_files_impl("*.py", str(tmp_workspace))
    assert matches == []


@pytest.mark.unit
def test_search_files_impl_match_validation_exception(
    tmp_workspace: Path,
) -> None:
    """If per-match validation raises an unexpected exception, skip it."""
    ok = tmp_workspace / "ok.py"
    ok.write_text("x")
    real_ok = ok.resolve()

    def fake_rglob(self: Path, pattern: str) -> object:
        yield real_ok

    original_resolve = Path.resolve

    def selective_resolve(self: Path, *a: object, **kw: object) -> Path:
        r = original_resolve(self)
        if r == real_ok:
            raise OSError("boom")
        return r

    with patch.object(Path, "rglob", fake_rglob), patch.object(
        Path, "is_file", return_value=True
    ), patch.object(Path, "resolve", selective_resolve):
        matches = _search_files_impl("*.py", str(tmp_workspace))
    assert matches == []


# ---------------------------------------------------------------------------
# @tool wrappers
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_read_file_tool_wrapper(tmp_workspace: Path) -> None:
    p = tmp_workspace / "tool.py"
    p.write_text("x")
    # The @tool decorator wraps the function as a Function object with
    # the original callable available as .entrypoint
    result = read_file.entrypoint(str(p))
    assert result == "x"


@pytest.mark.unit
def test_write_file_tool_wrapper(tmp_workspace: Path) -> None:
    p = tmp_workspace / "tool2.py"
    result = write_file.entrypoint(str(p), "hello")
    assert result["success"] is True
    assert p.read_text() == "hello"


@pytest.mark.unit
def test_list_directory_tool_wrapper(tmp_workspace: Path) -> None:
    (tmp_workspace / "a.py").write_text("x")
    result = list_directory.entrypoint(str(tmp_workspace))
    assert "a.py" in result


@pytest.mark.unit
def test_search_files_tool_wrapper(tmp_workspace: Path) -> None:
    (tmp_workspace / "a.py").write_text("x")
    result = search_files.entrypoint("*.py", str(tmp_workspace))
    assert "a.py" in result


@pytest.mark.unit
def test_read_file_tool_metadata() -> None:
    """@tool exposes metadata on the Function object."""
    assert read_file.name == "read_file"
    assert "Read the contents" in read_file.description
    assert write_file.name == "write_file"
    assert list_directory.name == "list_directory"
    assert search_files.name == "search_files"


# ---------------------------------------------------------------------------
# Module re-import / __all__ sanity
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_module_all_exports() -> None:
    for name in file_tools.__all__:
        assert hasattr(file_tools, name), f"missing export: {name}"


@pytest.mark.unit
def test_module_reimport() -> None:
    """Cover importlib.reload to make the module loadable twice."""
    mod = importlib.reload(file_tools)
    assert mod is not None
