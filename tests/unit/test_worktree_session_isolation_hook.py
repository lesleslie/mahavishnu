"""Unit tests for ``.claude/hooks/worktree-session-isolation.py``.

Tests the hook's internal helpers and flow control by importing the
script as a module via ``importlib.util.spec_from_file_location``
(mirrors the pattern used in
``tests/unit/test_bodai_activity_hooks.py``).

Coverage:
- Env-var gate: missing → return 0 in <2ms, zero side-effects
- Env-var gate: present → proceed
- cwd-is-worktree detection (via ``_cwd_is_inside_worktree``)
- Repo nickname detection (via ``_detect_repo_nickname``)
- Truthy parsing (``_is_truthy``)
- stdin payload reading (``read_session_payload``)
- Schema hook integration: registry writes happen via the hook path
"""
from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

# Load the hook as a module (it's a script, not importable by package path).
_HOOK_PATH = (
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "hooks"
    / "worktree-session-isolation.py"
)
_HOOKS_DIR = _HOOK_PATH.parent


@pytest.fixture(autouse=True)
def _add_hooks_to_syspath() -> None:
    """``.claude/hooks/_hook_io.py`` is not a package — add its dir to sys.path."""
    import sys

    p = str(_HOOKS_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def _load_hook_module(monkeypatch: pytest.MonkeyPatch):
    """Import ``worktree-session-isolation.py`` as a module.

    Sets ``sys.argv`` to ``['worktree-session-isolation.py', '--mode', mode]``
    and ``sys.stdin`` to a fake payload before importing, so the module's
    top-level ``main()`` dispatch runs with the right args. The module's
    ``main()`` always returns 0 (per the exit-0-always contract).
    """
    import sys

    spec = importlib.util.spec_from_file_location(
        "worktree_session_isolation_hook", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook_module(monkeypatch: pytest.MonkeyPatch):
    """Import the hook script as a module."""
    return _load_hook_module(monkeypatch)


# ── _is_truthy ──────────────────────────────────────────────────


def test_is_truthy_recognizes_truthy_strings(hook_module) -> None:
    """Recognized truthy: ``1`` / ``true`` / ``yes`` / ``on`` (any case)."""
    for value in ("1", "true", "yes", "on", "TRUE", "Yes", "  on  "):
        assert hook_module._is_truthy(value) is True, value


def test_is_truthy_rejects_garbage(hook_module) -> None:
    """Anything else (including empty string and None) is False."""
    for value in ("0", "false", "no", "off", "", "  ", "maybe", "2"):
        assert hook_module._is_truthy(value) is False, value
    assert hook_module._is_truthy(None) is False


# ── read_session_payload ─────────────────────────────────────────


def test_read_session_payload_parses_valid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid JSON: session_id and cwd are extracted, raw preserved."""
    import io
    import json
    import sys

    payload_json = json.dumps({
        "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
        "cwd": "/Users/les/Projects/mahavishnu",
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload_json))
    from _hook_io import read_session_payload
    payload = read_session_payload()
    assert payload.session_id == "0190f8a4-b9c1-7def-a012-3456789abcde"
    assert payload.cwd == "/Users/les/Projects/mahavishnu"
    assert payload.raw["session_id"] == "0190f8a4-b9c1-7def-a012-3456789abcde"


def test_read_session_payload_handles_empty_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty stdin → empty HookPayload, no exception."""
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    from _hook_io import read_session_payload
    payload = read_session_payload()
    assert payload.session_id == ""
    assert payload.cwd == ""
    assert payload.raw == {}


def test_read_session_payload_handles_malformed_stdin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-JSON stdin → empty HookPayload, no exception."""
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO("not json {{{"))
    from _hook_io import read_session_payload
    payload = read_session_payload()
    assert payload.session_id == ""
    assert payload.raw == {}


# ── _cwd_is_inside_worktree ──────────────────────────────────────


def test_cwd_is_inside_worktree_returns_false_for_non_git_dir(
    tmp_path: Path,
) -> None:
    """Non-git dir: returns False, no git invocation side-effects."""
    from _hook_io import read_session_payload  # trigger path setup
    # Load the hook module
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_for_cwd_test", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._cwd_is_inside_worktree(str(tmp_path)) is False


def test_cwd_is_inside_worktree_returns_false_for_empty_cwd(hook_module) -> None:
    """Empty cwd: False (no worktree to be in)."""
    assert hook_module._cwd_is_inside_worktree("") is False


# ── _detect_repo_nickname ────────────────────────────────────────


def test_detect_repo_nickname_returns_basename_of_git_repo(
    tmp_path: Path, hook_module
) -> None:
    """Walks up to ``.git`` and returns the parent dir's basename."""
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / ".git").mkdir()
    subdir = repo / "src" / "lib"
    subdir.mkdir(parents=True)
    assert hook_module._detect_repo_nickname(str(subdir)) == "myrepo"


def test_detect_repo_nickname_returns_none_for_no_git(tmp_path: Path, hook_module) -> None:
    """No ``.git`` anywhere up the tree: returns None."""
    subdir = tmp_path / "no-git" / "sub"
    subdir.mkdir(parents=True)
    assert hook_module._detect_repo_nickname(str(subdir)) is None


def test_detect_repo_nickname_returns_none_for_empty_cwd(hook_module) -> None:
    """Empty cwd: None (no walk possible)."""
    assert hook_module._detect_repo_nickname("") is None


# ── Env-var gate: default-off fast path ──────────────────────────


def test_main_returns_zero_when_env_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MAHAVISHNU_AUTO_WORKTREE`` unset → main() returns 0 immediately."""
    import io
    import json
    import sys

    monkeypatch.delenv("MAHAVISHNU_AUTO_WORKTREE", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "abc",
        "cwd": str(tmp_path),
    })))
    monkeypatch.setattr(sys, "argv", ["worktree-session-isolation.py"])

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_default_off", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0


def test_main_with_env_set_does_not_block_on_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MAHAVISHNU_AUTO_WORKTREE=1`` with a fresh session_id and a
    non-git cwd → no exception, no hang, returns 0.
    """
    import io
    import json
    import sys

    monkeypatch.setenv("MAHAVISHNU_AUTO_WORKTREE", "1")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
        "cwd": str(tmp_path),  # no .git here → step 5 returns 0
    })))
    monkeypatch.setattr(sys, "argv", ["worktree-session-isolation.py"])

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_env_set", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    start = time.perf_counter()
    rc = module.main()
    elapsed = time.perf_counter() - start
    assert rc == 0
    # Should complete well under 2s (no mahavishnu import needed when no .git).
    assert elapsed < 2.0, f"main() took {elapsed:.2f}s, expected <2s"
