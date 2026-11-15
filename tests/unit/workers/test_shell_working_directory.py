"""The worker session's working directory.

The worktree isolation path in ``pool_route_execute`` creates a git
worktree and needs the worker session to *start inside it*. The directory
reaches the session as a ``cd`` in the launch command, so this file pins
three properties of that rendering:

1. The directory is quoted. It reaches ``/bin/sh -c`` as shell text, so an
   unquoted path with a space or a metacharacter would split or execute.
2. The whole command is skipped when the directory cannot be entered. A
   bare ``cd X && cmd`` leaves a trailing ``;``-separated command running
   in the previous directory — the exact failure the isolation exists to
   prevent.
3. No directory means no ``cd``: the default session start is untouched.
"""

from __future__ import annotations

import asyncio
import shlex
from typing import TYPE_CHECKING, Any

from mahavishnu.workers import shell_backend
from mahavishnu.workers.registry import WORKER_REGISTRY

if TYPE_CHECKING:
    from pathlib import Path


def _render(cwd: str | Path | None, *, prompt_file: bool = False) -> str:
    config = WORKER_REGISTRY["terminal-claude"]
    mode = shell_backend.resolve_permission_mode(config)
    assert mode is not None
    return shell_backend.render_command(config, mode, prompt_file=prompt_file, cwd=cwd)


def test_no_cwd_leaves_the_command_untouched() -> None:
    """The default session start must not gain a ``cd``."""
    rendered = _render(None)
    assert not rendered.startswith("cd ")
    assert "&& (" not in rendered


def test_cwd_becomes_a_quoted_cd() -> None:
    rendered = _render("/tmp/worktree")
    assert rendered.startswith("cd /tmp/worktree && ( ")


def test_cwd_with_spaces_is_quoted() -> None:
    """An unquoted path would split into two arguments."""
    rendered = _render("/tmp/my worktree")
    assert rendered.startswith("cd '/tmp/my worktree' && ( ")


def test_cwd_cannot_inject_shell_text() -> None:
    """The path reaches ``/bin/sh -c``; a metacharacter must not execute."""
    rendered = _render("/tmp/x; touch /tmp/pwned")
    assert "touch /tmp/pwned" not in rendered.replace(shlex.quote("/tmp/x; touch /tmp/pwned"), "")
    assert rendered.startswith("cd '/tmp/x; touch /tmp/pwned' && ( ")


def test_failed_cd_skips_the_whole_command() -> None:
    """The prompt prologue must not run outside the target directory.

    The prologue is ``;``-separated, so chaining the ``cd`` with ``&&``
    alone would leave it running when the ``cd`` fails.
    """
    rendered = _render("/nonexistent", prompt_file=True)
    assert rendered.startswith("cd /nonexistent && ( ")
    # Everything the session needs sits inside the parenthesised group.
    assert rendered.endswith(")")
    assert rendered.count("(") == rendered.count(")")


def test_cwd_is_applied_to_the_prompt_prologue_too() -> None:
    """The prompt file is read inside the directory, not before it."""
    rendered = _render("/tmp/worktree", prompt_file=True)
    assert rendered.index("cd /tmp/worktree") < rendered.index("MAHAVISHNU_PROMPT")


def test_shell_worker_launches_the_session_in_its_cwd() -> None:
    """The worker's cwd must reach the launch command handed to tmux.

    This is the link between the dispatch and the session: the pool
    builds the worker with the directory, and the worker puts it in the
    command it launches.
    """
    captured: dict[str, Any] = {}

    class _Manager:
        async def launch_sessions(
            self, command, count, worker_type, env_overrides=None
        ):
            captured["command"] = command
            return ["sess-1"]

    config = WORKER_REGISTRY["terminal-claude"]
    worker = shell_backend.ShellWorker(
        config=config,
        terminal_manager=_Manager(),
        cwd="/tmp/worktree",
    )
    asyncio.run(worker.start(prompt="do the thing"))

    assert captured["command"].startswith("cd /tmp/worktree && ( ")


def test_shell_worker_without_a_cwd_launches_where_it_always_did() -> None:
    """No cwd means the session start is unchanged."""
    captured: dict[str, Any] = {}

    class _Manager:
        async def launch_sessions(
            self, command, count, worker_type, env_overrides=None
        ):
            captured["command"] = command
            return ["sess-1"]

    config = WORKER_REGISTRY["terminal-claude"]
    worker = shell_backend.ShellWorker(config=config, terminal_manager=_Manager())
    asyncio.run(worker.start(prompt="do the thing"))

    assert not captured["command"].startswith("cd ")
