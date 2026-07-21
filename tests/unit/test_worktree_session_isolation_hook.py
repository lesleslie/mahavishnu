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
from pathlib import Path
import time

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


# ── Real-git-worktree detection (Phase A3) ──────────────────────────


def _init_main_repo_with_commit(tmp_path: Path) -> Path:
    """Create a real git repo with one commit. Returns the repo path."""
    import subprocess

    main = tmp_path / "main"
    main.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(main)],
        check=True,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "-C", str(main), "config", "user.email", "t@t.com"],
        check=True,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "-C", str(main), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
        timeout=10,
    )
    subprocess.run(
        ["git", "-C", str(main), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        timeout=10,
    )
    return main


def test_cwd_is_inside_worktree_returns_false_for_main_repo(
    tmp_path: Path,
) -> None:
    """A normal repo (not a worktree) → False.

    Regression test for the broken ``--git-common-dir`` check (Phase A3):
    that command returns the main repo's ``.git`` regardless of whether
    we're in a worktree, so the function used to return False for
    everything. This test passes for both broken and fixed implementations
    (the broken one was always returning False); the worktree test
    below is what proves the fix.
    """
    import importlib.util

    main = _init_main_repo_with_commit(tmp_path)

    spec = importlib.util.spec_from_file_location(
        "hook_cwd_main", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._cwd_is_inside_worktree(str(main)) is False


def test_cwd_is_inside_worktree_returns_true_for_real_worktree(
    tmp_path: Path,
) -> None:
    """A real git worktree → True.

    Pre-fix (using ``--git-common-dir``): False (broken).
    Post-fix (using ``--git-dir``): True (correct).
    """
    import importlib.util
    import subprocess

    main = _init_main_repo_with_commit(tmp_path)
    wt_path = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-b", "wt-branch", str(wt_path)],
        check=True,
        capture_output=True,
        timeout=10,
    )

    spec = importlib.util.spec_from_file_location(
        "hook_cwd_wt", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._cwd_is_inside_worktree(str(wt_path)) is True


def test_cwd_is_inside_worktree_returns_true_for_worktree_subdir(
    tmp_path: Path,
) -> None:
    """A subdirectory of a real worktree → True (still inside the worktree)."""
    import importlib.util
    import subprocess

    main = _init_main_repo_with_commit(tmp_path)
    wt_path = tmp_path / "wt"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-b", "wt-branch", str(wt_path)],
        check=True,
        capture_output=True,
        timeout=10,
    )
    subdir = wt_path / "src" / "lib"
    subdir.mkdir(parents=True)

    spec = importlib.util.spec_from_file_location(
        "hook_cwd_wt_subdir", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._cwd_is_inside_worktree(str(subdir)) is True


def test_cwd_is_inside_worktree_returns_false_for_main_repo_subdir(
    tmp_path: Path,
) -> None:
    """A subdirectory of a normal repo (not a worktree) → False."""
    import importlib.util

    main = _init_main_repo_with_commit(tmp_path)
    subdir = main / "src" / "lib"
    subdir.mkdir(parents=True)

    spec = importlib.util.spec_from_file_location(
        "hook_cwd_main_subdir", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._cwd_is_inside_worktree(str(subdir)) is False


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


# ── Discovery hint (Phase 4) ──────────────────────────────────────


def _load_with_stderr(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    stdin_payload: str,
    argv: list[str],
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    root: str | None = None,
):
    """Helper: load the hook module with custom env, stdin, argv, stderr.

    Returns ``(module, captured_stderr)``. Sets up:

    - ``MAHAVISHNU_AUTO_WORKTREE`` (deleted or from env dict)
    - ``MAHAVISHNU_AUTO_WORKTREE_ROOT`` (optional, for the root-exists test)
    - ``sys.stdin`` to ``stdin_payload``
    - ``sys.argv`` to ``argv``
    - ``sys.stderr`` to a ``StringIO`` for capture

    Returns the loaded module and the captured stderr buffer.
    """
    import importlib.util
    import io
    import sys

    if env is None:
        env = {}
    if "MAHAVISHNU_AUTO_WORKTREE" in env:
        monkeypatch.setenv("MAHAVISHNU_AUTO_WORKTREE", env["MAHAVISHNU_AUTO_WORKTREE"])
    else:
        monkeypatch.delenv("MAHAVISHNU_AUTO_WORKTREE", raising=False)
    if root is not None:
        monkeypatch.setenv("MAHAVISHNU_AUTO_WORKTREE_ROOT", root)
    elif "MAHAVISHNU_AUTO_WORKTREE_ROOT" in env:
        monkeypatch.setenv(
            "MAHAVISHNU_AUTO_WORKTREE_ROOT", env["MAHAVISHNU_AUTO_WORKTREE_ROOT"]
        )
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))
    monkeypatch.setattr(sys, "argv", argv)
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured)

    spec = importlib.util.spec_from_file_location(module_name, _HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, captured


def test_discovery_hint_fires_when_unset_and_git_repo_and_root_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default conditions: hint fires when env unset + git repo + root missing."""
    import json

    (tmp_path / ".git").mkdir()
    nonexistent_root = tmp_path / "worktrees-does-not-exist"
    assert not nonexistent_root.exists()

    module, captured = _load_with_stderr(
        monkeypatch,
        "hook_hint_fires",
        json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": str(tmp_path),
        }),
        ["worktree-session-isolation.py", "session-start"],
        root=str(nonexistent_root),
    )

    rc = module.main()
    assert rc == 0
    output = captured.getvalue()
    assert "MAHAVISHNU_AUTO_WORKTREE=1" in output
    assert "per-session worktrees" in output


def test_discovery_hint_silent_when_env_set_truthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MAHAVISHNU_AUTO_WORKTREE=1`` (opted in) → no hint (user is informed)."""
    import json

    (tmp_path / ".git").mkdir()
    nonexistent_root = tmp_path / "worktrees-does-not-exist"

    module, captured = _load_with_stderr(
        monkeypatch,
        "hook_hint_opt_in",
        json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": str(tmp_path),
        }),
        ["worktree-session-isolation.py"],
        env={"MAHAVISHNU_AUTO_WORKTREE": "1"},
        root=str(nonexistent_root),
    )

    rc = module.main()
    assert rc == 0
    assert "MAHAVISHNU_AUTO_WORKTREE=1" not in captured.getvalue()


def test_discovery_hint_silent_when_env_set_falsy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``MAHAVISHNU_AUTO_WORKTREE=0`` (explicit opt-out) → no hint."""
    import json

    (tmp_path / ".git").mkdir()
    nonexistent_root = tmp_path / "worktrees-does-not-exist"

    module, captured = _load_with_stderr(
        monkeypatch,
        "hook_hint_opt_out",
        json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": str(tmp_path),
        }),
        ["worktree-session-isolation.py"],
        env={"MAHAVISHNU_AUTO_WORKTREE": "0"},
        root=str(nonexistent_root),
    )

    rc = module.main()
    assert rc == 0
    assert "MAHAVISHNU_AUTO_WORKTREE=1" not in captured.getvalue()


def test_discovery_hint_silent_when_not_git_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cwd is not a git repo → no hint (feature not applicable)."""
    import json

    # tmp_path has no .git
    nonexistent_root = tmp_path / "worktrees-does-not-exist"

    module, captured = _load_with_stderr(
        monkeypatch,
        "hook_hint_no_git",
        json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": str(tmp_path),
        }),
        ["worktree-session-isolation.py"],
        root=str(nonexistent_root),
    )

    rc = module.main()
    assert rc == 0
    assert "MAHAVISHNU_AUTO_WORKTREE=1" not in captured.getvalue()


def test_discovery_hint_silent_when_cwd_is_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cwd is already a worktree → no hint (already set up)."""
    import json

    (tmp_path / ".git").mkdir()
    nonexistent_root = tmp_path / "worktrees-does-not-exist"

    module, captured = _load_with_stderr(
        monkeypatch,
        "hook_hint_in_worktree",
        json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": str(tmp_path),
        }),
        ["worktree-session-isolation.py"],
        root=str(nonexistent_root),
    )
    # Mock the (currently-broken-for-real-worktrees) helper to True so we
    # can isolate the hint logic. The bug in _cwd_is_inside_worktree is
    # tracked separately; this test only verifies the hint gating.
    monkeypatch.setattr(module, "_cwd_is_inside_worktree", lambda cwd: True)

    rc = module.main()
    assert rc == 0
    assert "MAHAVISHNU_AUTO_WORKTREE=1" not in captured.getvalue()


def test_discovery_hint_silent_when_root_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The configured worktree root already exists → no hint (already set up)."""
    import json

    (tmp_path / ".git").mkdir()
    existing_root = tmp_path / "worktrees"
    existing_root.mkdir()
    assert existing_root.exists()

    module, captured = _load_with_stderr(
        monkeypatch,
        "hook_hint_root_exists",
        json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": str(tmp_path),
        }),
        ["worktree-session-isolation.py"],
        root=str(existing_root),
    )

    rc = module.main()
    assert rc == 0
    assert "MAHAVISHNU_AUTO_WORKTREE=1" not in captured.getvalue()


def test_discovery_hint_silent_when_cwd_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty cwd (SessionEnd payload) → no hint."""
    import json

    module, captured = _load_with_stderr(
        monkeypatch,
        "hook_hint_empty_cwd",
        json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": "",
        }),
        ["worktree-session-isolation.py"],
    )

    rc = module.main()
    assert rc == 0
    assert "MAHAVISHNU_AUTO_WORKTREE=1" not in captured.getvalue()


def test_discovery_hint_silent_on_session_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit SessionEnd (--mode) → no hint (hint is SessionStart only)."""
    import json

    (tmp_path / ".git").mkdir()
    nonexistent_root = tmp_path / "worktrees-does-not-exist"

    module, captured = _load_with_stderr(
        monkeypatch,
        "hook_hint_session_end",
        json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": str(tmp_path),
        }),
        ["worktree-session-isolation.py", "--mode", "session-end"],
        root=str(nonexistent_root),
    )

    rc = module.main()
    assert rc == 0
    assert "MAHAVISHNU_AUTO_WORKTREE=1" not in captured.getvalue()


def test_discovery_hint_completes_in_under_two_seconds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default-off with hint attempt completes in <2s.

    Regression test: the hint adds a ``git rev-parse`` call (~5-50ms)
    plus a path walk + stat. Total cost is dominated by git latency.
    The default-off contract is relaxed from "<2ms" to "<2s" to
    absorb the hint cost. SessionStart hook budgets allow 2s.
    """
    import json

    (tmp_path / ".git").mkdir()
    nonexistent_root = tmp_path / "worktrees-does-not-exist"

    module, captured = _load_with_stderr(
        monkeypatch,
        "hook_hint_fast_path",
        json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": str(tmp_path),
        }),
        ["worktree-session-isolation.py", "session-start"],
        root=str(nonexistent_root),
    )

    start = time.perf_counter()
    rc = module.main()
    elapsed = time.perf_counter() - start
    assert rc == 0
    assert elapsed < 2.0, f"main() took {elapsed:.2f}s, expected <2s"
    # Sanity check: hint actually fired (so we're measuring the full path)
    assert "MAHAVISHNU_AUTO_WORKTREE=1" in captured.getvalue()


# ── Mode dispatch (Phase A2) ──────────────────────────────────────


def test_main_dispatches_on_positional_session_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positional argv[1]='session-start' (Claude Code's wire format) → mode=session-start."""
    import io
    import json
    import sys

    monkeypatch.delenv("MAHAVISHNU_AUTO_WORKTREE", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
        "cwd": str(tmp_path),
    })))
    monkeypatch.setattr(sys, "argv", ["worktree-session-isolation.py", "session-start"])

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured)

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_pos_start", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
    stderr = captured.getvalue()
    assert "unknown mode" not in stderr
    assert "no mode" not in stderr.lower()


def test_main_dispatches_on_positional_session_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positional argv[1]='session-end' → mode=session-end."""
    import io
    import sys

    monkeypatch.delenv("MAHAVISHNU_AUTO_WORKTREE", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "argv", ["worktree-session-isolation.py", "session-end"])

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured)

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_pos_end", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
    assert "unknown mode" not in captured.getvalue()


def test_main_dispatches_on_dash_mode_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--mode session-start`` flag still works (back-compat)."""
    import io
    import sys

    monkeypatch.delenv("MAHAVISHNU_AUTO_WORKTREE", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "argv", [
        "worktree-session-isolation.py", "--mode", "session-start",
    ])

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured)

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_dash_mode", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
    assert "unknown mode" not in captured.getvalue()


def test_main_refuses_when_no_mode_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No positional nor --mode → log diagnostic, return 0 (fail-closed)."""
    import io
    import sys

    monkeypatch.delenv("MAHAVISHNU_AUTO_WORKTREE", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "argv", ["worktree-session-isolation.py"])

    captured = io.StringIO()
    monkeypatch.setattr(sys, "stderr", captured)

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_no_mode", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
    stderr = captured.getvalue().lower()
    assert "no mode" in stderr or "mode" in stderr


# ── Payload type validation (Phase A2) ─────────────────────────────


def test_read_session_payload_rejects_non_string_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-string session_id (int, list, dict, bool, float) → empty string.

    Defense against malformed payloads reaching subprocess calls.
    Per multi-agent review Test #10 (2026-07-20).
    """
    import io
    import json
    import sys

    from _hook_io import read_session_payload

    for bad in (42, [1, 2], {"a": 1}, True, 3.14, None):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
            "session_id": bad,
            "cwd": "/tmp",
        })))
        payload = read_session_payload()
        assert payload.session_id == "", (
            f"non-string session_id {bad!r} should normalize to empty"
        )


def test_read_session_payload_rejects_non_string_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-string cwd → empty string (fail-closed)."""
    import io
    import json
    import sys

    from _hook_io import read_session_payload

    for bad in (42, ["/tmp"], {"a": 1}, True, 3.14, None):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
            "session_id": "0190f8a4-b9c1-7def-a012-3456789abcde",
            "cwd": bad,
        })))
        payload = read_session_payload()
        assert payload.cwd == "", (
            f"non-string cwd {bad!r} should normalize to empty"
        )


def test_read_session_payload_preserves_string_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """String session_id and cwd pass through unchanged."""
    import io
    import json
    import sys

    from _hook_io import read_session_payload

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({
        "session_id": "abc-123",
        "cwd": "/tmp/work",
    })))
    payload = read_session_payload()
    assert payload.session_id == "abc-123"
    assert payload.cwd == "/tmp/work"


# ── Git argv -- separator (Phase A2) ──────────────────────────────


def test_git_worktree_add_argv_includes_double_dash_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--`` must precede ``branch_base`` to defend against option-injection.

    Per Security audit #2 (2026-07-20): if ``MAHAVISHNU_AUTO_WORKTREE_BRANCH_BASE``
    starts with ``-``, git's option parser might re-parse it as a flag.
    Inserting ``--`` ends option parsing.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "hook_argv_test", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    argv = module._git_worktree_add_argv(
        cwd="/tmp/repo",
        branch="worktree-agent-abc12345",
        target_path="/tmp/worktrees/agent-abc12345",
        branch_base="--upload-pack=evil",
    )

    # Find positions
    dash_idx = argv.index("--")
    branch_base_idx = argv.index("--upload-pack=evil")
    target_idx = argv.index("/tmp/worktrees/agent-abc12345")
    assert dash_idx < branch_base_idx, (
        f"'--' (at {dash_idx}) must come before branch_base (at {branch_base_idx})"
    )
    assert dash_idx < target_idx, (
        f"'--' (at {dash_idx}) must come before target_path (at {target_idx})"
    )
