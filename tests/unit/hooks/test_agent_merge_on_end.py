"""Unit tests for ``.claude/hooks/agent-merge-on-end.py``.

Loads the hook as a module via ``importlib.util.spec_from_file_location``
(mirrors the pattern in
``tests/unit/test_worktree_session_isolation_hook.py``).

Per spec §4.2 the SessionEnd hook's primary skip condition (after the
``MAHAVISHNU_AUTO_MERGE`` env-var gate and the ``is_worktree`` check)
is the sticky-failure marker in ``.review-state.json``. These two
tests cover that branch:

- ``test_is_sticky_failed_true_when_stage_failed_set`` — writes a
  review-state JSON with a non-null ``stage_failed`` and asserts the
  helper returns True.
- ``test_is_sticky_failed_false_when_marker_absent_or_clean`` — same
  fixture with the field absent (clean state) and asserts False.

Both tests exercise the helper directly rather than the end-to-end
``run_hook`` lifecycle (per the multi-agent review of 2026-07-20 on
the sister hook's test suite — helpers, not lifecycle paths).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HOOK_PATH = (
    Path(__file__).resolve().parents[3]
    / ".claude"
    / "hooks"
    / "agent-merge-on-end.py"
)
_HOOKS_DIR = _HOOK_PATH.parent


@pytest.fixture(autouse=True)
def _add_hooks_to_syspath() -> None:
    """``.claude/hooks/_hook_io.py`` is not a package — add its dir to sys.path.

    Mirrors the fixture in ``test_worktree_session_isolation_hook.py``.
    """
    import sys

    p = str(_HOOKS_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture
def hook_module() -> object:
    """Import the hook script as a module via importlib."""
    spec = importlib.util.spec_from_file_location(
        "agent_merge_on_end_hook", _HOOK_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_review_state(
    worktree_root: Path,
    *,
    stage_failed: str | None,
) -> Path:
    """Write ``.review-state.json`` with the given ``stage_failed`` field.

    Includes the minimal schema keys expected by spec §4.4 so a
    future enhancement that grows the helper (e.g. validating
    ``schema_version``) can be added without changing every call site.
    """
    payload = {
        "schema_version": 1,
        "ephemeral_branch": "test-branch",
        "base": "origin/main",
        "pre_rebase_base_sha": "b116d395",
        "stages_completed": ["stage_1_worktree"],
        "current_stage": "stage_6_cleanup",
        "stage_failed": stage_failed,
        "reviewers_invoked": [],
        "audit_log_path": None,
        "session_buddy_reflection_id": None,
    }
    target = worktree_root / ".review-state.json"
    target.write_text(json.dumps(payload))
    return target


# ── is_sticky_failed: positive case ─────────────────────────────────


def test_is_sticky_failed_true_when_stage_failed_set(
    tmp_path: Path,
    hook_module: object,
) -> None:
    """``.review-state.json`` with ``stage_failed="stage_6_cleanup"`` → True.

    Per spec §4.2 failure mode "Cleanup fails" → sticky marker →
    hook must NOT retry. This is the primary skip condition after
    the env-var gate and the ``is_worktree`` check.
    """
    _write_review_state(tmp_path, stage_failed="stage_6_cleanup")
    assert hook_module.is_sticky_failed(str(tmp_path)) is True


# ── is_sticky_failed: negative cases (absent + clean) ─────────────────


def test_is_sticky_failed_false_when_marker_absent_or_clean(
    tmp_path: Path,
    hook_module: object,
) -> None:
    """No marker file → False; clean state (stage_failed=None) → False.

    Covers both pre-merge (no marker file at all) and post-cleanup
    (marker file exists but ``stage_failed`` is null — the merge
    succeeded and cleaned up; subsequent SessionEnd calls should
    not be blocked).
    """
    # No marker file.
    assert hook_module.is_sticky_failed(str(tmp_path)) is False

    # Marker file exists but stage_failed is None.
    _write_review_state(tmp_path, stage_failed=None)
    assert hook_module.is_sticky_failed(str(tmp_path)) is False