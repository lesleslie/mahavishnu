"""Git-event handlers for ``mahavishnu git-hook <event>`` Typer sub-command.

Replaces the action lines from ``.git/hooks/{pre-commit,post-commit,
post-merge,post-rewrite}`` (which are not version-controlled — git
hooks live per-clone) with a Typer-registered CLI that publishes
to the bus after running the legacy action.

Per spec §4.13 — hook coordination via Oneiric event bus.
Per spec §4.13.3 — action exit codes propagate; the bridge
publish is fire-and-forget (failures do not alter the exit code).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


# ---------------------------------------------------------------------------
# Per-event argv + canonical bridge event-name mapping
# ---------------------------------------------------------------------------


_GIT_EVENT_COMMANDS: dict[str, list[str]] = {
    "pre-commit": ["crackerjack", "run", "--fast-hooks-only"],
    "post-commit": ["mahavishnu", "jot", "capture", "--event", "post-commit"],
    "post-merge": ["mahavishnu", "jot", "capture", "--event", "post-merge"],
    "post-rewrite": ["mahavishnu", "jot", "capture", "--event", "post-rewrite"],
}

# Bridge event names follow the PascalCase convention used by Claude/Qwen
# hooks so subscribers can filter by a single canonical event-name namespace.
_GIT_EVENT_NAMES: dict[str, str] = {
    "pre-commit": "GitPreCommit",
    "post-commit": "GitPostCommit",
    "post-merge": "GitPostMerge",
    "post-rewrite": "GitPostRewrite",
}


def _publish_git_event(event: str) -> None:
    """Fire-and-forget publish of a git lifecycle event via the bridge.

    Delegates to :func:`mahavishnu.bodai_hook_bridge.handle` so the
    sync→async publish path (with init + transient-loop driving)
    is implemented once in the bridge. Bridge failures are caught
    inside ``handle`` (fire-and-forget contract).
    """
    from mahavishnu.bodai_hook_bridge import handle

    payload: dict[str, object] = {
        "event": event,
        "harness": "git",
        "cwd": str(Path.cwd()),
        "argv": sys.argv[1:],
        "timestamp": None,
        "tool_name": None,
        "tool_input": None,
    }
    handle(
        event_name=_GIT_EVENT_NAMES[event],
        harness="git",
        payload=payload,
    )


def _safe_publish_git_event(event: str) -> None:
    """Defensive wrapper around :func:`_publish_git_event`.

    The bridge's fire-and-forget contract applies to its internal
    ``_publish`` call, but a buggy ``handle()`` implementation
    (e.g. a ``KeyError`` in the per-event handler dispatch) would
    propagate. Wrap here so the git hook's authoritative exit code
    (from the action subprocess) is preserved regardless.
    """
    try:
        _publish_git_event(event)
    except Exception:  # noqa: BLE001 - fire-and-forget boundary
        # Operator-facing signal: log to stderr so git surfaces it as
        # "Hook output" but does NOT block on it (git cares only about
        # the action's exit code).
        import traceback

        traceback.print_exc(file=sys.stderr)


def _run_action(argv: Sequence[str]) -> int:
    """Run the legacy action via ``subprocess.run`` and return its rc.

    Uses ``subprocess.run`` with ``check=False`` so the action's
    non-zero rc propagates rather than raising — we want the action
    to communicate failure via exit code, not exception. Output is
    captured (git invokes hooks with stdout/stderr connected, but we
    don't want to duplicate the output twice; Task 4's bash wrappers
    handle the operator-facing output).
    """
    completed = subprocess.run(
        list(argv),
        check=False,
        capture_output=True,
    )
    return completed.returncode


# ---------------------------------------------------------------------------
# Per-event handlers
# ---------------------------------------------------------------------------


def handle_pre_commit() -> int:
    """pre-commit: run crackerjack fast_hooks."""
    rc = _run_action(_GIT_EVENT_COMMANDS["pre-commit"])
    _safe_publish_git_event("pre-commit")
    return rc


def handle_post_commit() -> int:
    """post-commit: capture the commit in the jot log."""
    rc = _run_action(_GIT_EVENT_COMMANDS["post-commit"])
    _safe_publish_git_event("post-commit")
    return rc


def handle_post_merge() -> int:
    """post-merge: capture the merge in the jot log."""
    rc = _run_action(_GIT_EVENT_COMMANDS["post-merge"])
    _safe_publish_git_event("post-merge")
    return rc


def handle_post_rewrite() -> int:
    """post-rewrite: capture the rewrite (rebase, amend) in the jot log."""
    rc = _run_action(_GIT_EVENT_COMMANDS["post-rewrite"])
    _safe_publish_git_event("post-rewrite")
    return rc


_HANDLERS = {
    "pre-commit": handle_pre_commit,
    "post-commit": handle_post_commit,
    "post-merge": handle_post_merge,
    "post-rewrite": handle_post_rewrite,
}


def dispatch_git_hook(event: str) -> int:
    """Entry point for ``mahavishnu git-hook <event>``.

    Mirrors the bash action the legacy ``.git/hooks/<event>`` script
    ran. Unknown events return 0 so the caller (git) never blocks
    on a new event type we haven't implemented yet — git would
    surface a non-zero hook exit as a workflow error otherwise.
    """
    fn = _HANDLERS.get(event)
    if fn is None:
        return 0
    return fn()


__all__ = ["dispatch_git_hook"]
