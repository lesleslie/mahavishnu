"""Unit tests for ``mahavishnu.git_hook_handlers``.

Per spec §4.13 — git lifecycle hooks (pre-commit, post-commit,
post-merge, post-rewrite) route through ``mahavishnu git-hook
<event>`` Typer subcommand instead of per-clone bash scripts.
Each handler runs its legacy action AND publishes a bridge
event to the bus.

Tests mock ``subprocess.run`` so they don't depend on
``crackerjack`` / ``mahavishnu`` being on PATH. They mock the
bridge's ``handle`` so the unit test exercises the dispatch
path without depending on the bus.
"""

from __future__ import annotations

import subprocess
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module-level fixtures: capture subprocess.run + bridge.handle calls
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Replace ``subprocess.run`` with a recorder that always returns rc=0.

    Records the argv list of each call. Returns the list so tests
    can inspect what was invoked.
    """
    calls: list[list[str]] = []

    def _fake_run(argv: list[str], **_kwargs: Any) -> MagicMock:
        calls.append(argv)
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 0
        result.stdout = b""
        result.stderr = b""
        return result

    monkeypatch.setattr(subprocess, "run", _fake_run)
    return calls


@pytest.fixture
def fake_bridge_handle(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``mahavishnu.bodai_hook_bridge.handle`` with a recorder.

    Records the kwargs of each call (event_name, harness, payload).
    """
    calls: list[dict[str, Any]] = []

    def _fake_handle(*, event_name: str, harness: str, payload: dict[str, Any]) -> None:
        calls.append(
            {"event_name": event_name, "harness": harness, "payload": payload}
        )

    monkeypatch.setattr(
        "mahavishnu.bodai_hook_bridge.handle", _fake_handle
    )
    return calls


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_dispatch_unknown_event_returns_zero() -> None:
    """Unknown event names return 0; the caller (git) never blocks on a
    new event type we haven't implemented yet."""
    from mahavishnu.git_hook_handlers import dispatch_git_hook

    assert dispatch_git_hook("not-a-real-event") == 0


# ---------------------------------------------------------------------------
# Per-event behaviour
# ---------------------------------------------------------------------------


def test_dispatch_pre_commit_runs_crackerjack_and_publishes(
    fake_subprocess: list[list[str]], fake_bridge_handle: list[dict[str, Any]]
) -> None:
    """pre-commit runs ``crackerjack run --fast-hooks-only`` AND publishes
    the GitPreCommit bridge event.
    """
    from mahavishnu.git_hook_handlers import dispatch_git_hook

    exit_code = dispatch_git_hook("pre-commit")

    assert exit_code == 0
    assert len(fake_subprocess) == 1
    assert fake_subprocess[0] == ["crackerjack", "run", "--fast-hooks-only"]
    assert len(fake_bridge_handle) == 1
    assert fake_bridge_handle[0]["event_name"] == "GitPreCommit"
    assert fake_bridge_handle[0]["harness"] == "git"


def test_dispatch_post_commit_runs_jot_capture_and_publishes(
    fake_subprocess: list[list[str]], fake_bridge_handle: list[dict[str, Any]]
) -> None:
    """post-commit runs ``mahavishnu jot capture --event post-commit``
    AND publishes the GitPostCommit bridge event.
    """
    from mahavishnu.git_hook_handlers import dispatch_git_hook

    exit_code = dispatch_git_hook("post-commit")

    assert exit_code == 0
    assert fake_subprocess[0] == [
        "mahavishnu",
        "jot",
        "capture",
        "--event",
        "post-commit",
    ]
    assert fake_bridge_handle[0]["event_name"] == "GitPostCommit"


def test_dispatch_post_merge_runs_jot_capture_and_publishes(
    fake_subprocess: list[list[str]], fake_bridge_handle: list[dict[str, Any]]
) -> None:
    """post-merge runs ``mahavishnu jot capture --event post-merge``."""
    from mahavishnu.git_hook_handlers import dispatch_git_hook

    exit_code = dispatch_git_hook("post-merge")

    assert exit_code == 0
    assert fake_subprocess[0] == [
        "mahavishnu",
        "jot",
        "capture",
        "--event",
        "post-merge",
    ]
    assert fake_bridge_handle[0]["event_name"] == "GitPostMerge"


def test_dispatch_post_rewrite_runs_jot_capture_and_publishes(
    fake_subprocess: list[list[str]], fake_bridge_handle: list[dict[str, Any]]
) -> None:
    """post-rewrite runs ``mahavishnu jot capture --event post-rewrite``."""
    from mahavishnu.git_hook_handlers import dispatch_git_hook

    exit_code = dispatch_git_hook("post-rewrite")

    assert exit_code == 0
    assert fake_subprocess[0] == [
        "mahavishnu",
        "jot",
        "capture",
        "--event",
        "post-rewrite",
    ]
    assert fake_bridge_handle[0]["event_name"] == "GitPostRewrite"


# ---------------------------------------------------------------------------
# Bridge-publish failure must NOT alter the action's exit code
# ---------------------------------------------------------------------------


def test_bridge_failure_does_not_alter_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    fake_subprocess: list[list[str]],
) -> None:
    """If the bridge raises (bus down, adapter missing, etc.), the
    action's return code is still propagated unchanged.

    Spec §4.13.3 — sync-blocking events preserve their exit codes.
    The bridge is fire-and-forget; failures are observed but do
    not change the action's return value.
    """
    from mahavishnu.git_hook_handlers import dispatch_git_hook

    def _exploding_handle(**_kwargs: Any) -> None:
        raise RuntimeError("bus down")

    monkeypatch.setattr(
        "mahavishnu.bodai_hook_bridge.handle", _exploding_handle
    )

    # Action returns 0 (our fake subprocess) — bridge raising must
    # NOT turn this into a non-zero exit code.
    exit_code = dispatch_git_hook("post-commit")
    assert exit_code == 0


# ---------------------------------------------------------------------------
# Action failure must NOT be swallowed — non-zero rc propagates
# ---------------------------------------------------------------------------


def test_action_failure_propagates_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    fake_bridge_handle: list[dict[str, Any]],
) -> None:
    """A failing action (crackerjack lint failure, jot error) returns
    its non-zero exit code unchanged. The publish still fires (fire-
    and-forget contract).
    """
    from mahavishnu.git_hook_handlers import dispatch_git_hook

    def _failing_run(argv: list[str], **_kwargs: Any) -> MagicMock:
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.returncode = 2
        result.stdout = b"lint failed"
        result.stderr = b""
        return result

    monkeypatch.setattr(subprocess, "run", _failing_run)

    exit_code = dispatch_git_hook("pre-commit")

    assert exit_code == 2  # failed action's rc propagates
    # Bridge publish still happened — operator sees the event even on failure.
    assert len(fake_bridge_handle) == 1
    assert fake_bridge_handle[0]["event_name"] == "GitPreCommit"
