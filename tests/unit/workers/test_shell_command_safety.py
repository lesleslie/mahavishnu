"""Command rendering: the prompt is data, and the permission mode is bounded.

Two properties, both about what reaches a shell:

1. The prompt must never be interpolated into a command string. The command
   reaches tmux as one string that tmux runs via ``/bin/sh -c``, so an
   interpolated prompt containing ``;`` or ``$(...)`` would execute. The
   prompt travels as the environment variable ``MAHAVISHNU_PROMPT`` and the
   command reads it as ``"$MAHAVISHNU_PROMPT"``.

2. The permission mode is substituted into a command line, so it must be
   validated against the allowlist for that CLI. An unchecked settings
   value could smuggle a flag into the agent's argv.
"""

from __future__ import annotations

from typing import Any

import pytest

from mahavishnu.workers import shell_backend
from mahavishnu.workers.registry import (
    PERMISSION_MODES,
    PROMPT_ENV_VAR,
    WORKER_REGISTRY,
    WorkerConfig,
)

HOSTILE_PROMPT = 'hello"; touch /tmp/pwned; echo "'

AGENT_TYPES = ("terminal-claude", "terminal-qwen", "terminal-codex")


# ---------------------------------------------------------------------------
# the prompt is data
# ---------------------------------------------------------------------------


def test_no_registry_command_carries_a_prompt_placeholder() -> None:
    """A ``{prompt}`` in a command is a shell-injection waiting to happen."""
    offenders = [
        worker_type
        for worker_type, config in WORKER_REGISTRY.items()
        if "{prompt}" in config.command
    ]
    assert offenders == [], (
        f"{offenders} interpolate the prompt into a command string; it must be "
        f"passed as data via ${PROMPT_ENV_VAR}"
    )


def test_render_rejects_a_reintroduced_prompt_placeholder() -> None:
    """Defence in depth: a reintroduced placeholder must fail loudly."""
    config = WorkerConfig(
        name="rogue",
        worker_type="rogue",
        command="sh -lc 'echo {prompt}'",
        category=WORKER_REGISTRY["terminal-claude"].category,
    )

    with pytest.raises(ValueError, match="prompt"):
        shell_backend.render_command(config, None)


def test_hostile_prompt_never_enters_the_command() -> None:
    """Rendering is a pure function of the mode -- the prompt cannot leak in."""
    config = WORKER_REGISTRY["terminal-codex"]
    rendered = shell_backend.render_command(config, "workspace-write")

    assert HOSTILE_PROMPT not in rendered
    assert "touch /tmp/pwned" not in rendered
    assert f'"${PROMPT_ENV_VAR}"' in rendered


@pytest.mark.parametrize("worker_type", AGENT_TYPES)
def test_prompt_reaches_the_session_as_environment_data(worker_type: str) -> None:
    """The prompt must arrive as one env value, not as shell text."""
    import asyncio

    captured: dict[str, Any] = {}

    class _Manager:
        async def launch_sessions(self, command, count, worker_type, env_overrides=None):
            captured["command"] = command
            captured["env"] = dict(env_overrides or {})
            return ["sess-1"]

    config = WORKER_REGISTRY[worker_type]
    worker = shell_backend.ShellWorker(
        config=config, terminal_manager=_Manager()  # type: ignore[arg-type]
    )
    asyncio.run(worker.start(prompt=HOSTILE_PROMPT))

    assert captured["env"][PROMPT_ENV_VAR] == HOSTILE_PROMPT
    # Check the dangerous substring, not the exact prompt: an implementation
    # that quoted it would hide the literal while still executing it.
    assert "touch /tmp/pwned" not in captured["command"]
    # The only shell separators the registry's own commands use are the
    # completion-marker printf and the blocking read that keeps the pane
    # alive. Anything else would be an injection seam.
    without_known_separators = captured["command"].replace("; printf", "").replace("; read -r _", "")
    assert ";" not in without_known_separators


def test_no_prompt_means_no_env_var() -> None:
    """A worker started without a prompt must not carry an empty one."""
    import asyncio

    captured: dict[str, Any] = {}

    class _Manager:
        async def launch_sessions(self, command, count, worker_type, env_overrides=None):
            captured["env"] = dict(env_overrides or {})
            return ["sess-1"]

    worker = shell_backend.ShellWorker(
        config=WORKER_REGISTRY["terminal-codex"],
        terminal_manager=_Manager(),  # type: ignore[arg-type]
    )
    asyncio.run(worker.start())

    assert PROMPT_ENV_VAR not in captured["env"]


# ---------------------------------------------------------------------------
# the permission mode is bounded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("worker_type", AGENT_TYPES)
def test_registry_default_renders(worker_type: str) -> None:
    config = WORKER_REGISTRY[worker_type]
    mode = shell_backend.resolve_permission_mode(config)
    assert mode is not None
    rendered = shell_backend.render_command(config, mode)
    assert "{permission_mode}" not in rendered
    assert mode in rendered


def test_invalid_mode_is_rejected() -> None:
    """An unchecked mode could smuggle a flag into the agent's argv."""
    config = WORKER_REGISTRY["terminal-claude"]

    with pytest.raises(ValueError, match="not valid"):
        shell_backend.resolve_permission_mode(config, "plan; rm -rf /")


def test_mode_from_another_cli_is_rejected() -> None:
    """The vocabularies differ per tool; ``yolo`` is not a Claude mode."""
    config = WORKER_REGISTRY["terminal-claude"]

    with pytest.raises(ValueError, match="not valid"):
        shell_backend.resolve_permission_mode(config, "yolo")


def test_unknown_tool_is_rejected() -> None:
    config = WorkerConfig(
        name="x",
        worker_type="x",
        command="x",
        category=WORKER_REGISTRY["terminal-claude"].category,
        requires_tool="some-unknown-cli",
        permission_mode="plan",
    )

    with pytest.raises(ValueError, match="no known permission modes"):
        shell_backend.resolve_permission_mode(config)


def test_allowlists_match_the_clis_own_choices() -> None:
    """Pinned to the CLIs' documented enums, read from their --help."""
    assert "acceptEdits" in PERMISSION_MODES["claude"]
    assert "plan" in PERMISSION_MODES["claude"]
    # Claude Code has no "default" mode -- it is "manual"/"dontAsk".
    assert "default" not in PERMISSION_MODES["claude"]
    assert "yolo" in PERMISSION_MODES["qwen"]
    assert "default" in PERMISSION_MODES["qwen"]
    assert PERMISSION_MODES["codex"] == frozenset({"read-only", "workspace-write"})


def test_unrestricted_modes_are_not_reachable() -> None:
    """The modes that remove the enforcement boundary are absent.

    ``bypassPermissions`` skips every Claude Code permission check and
    ``danger-full-access`` removes Codex's sandbox. Both are strictly more
    permissive than any registry default, so allowing a settings line to
    reach them would let a config file disable a worker's protections
    outright. There is deliberately no opt-in flag -- a boolean in a YAML
    file is not a boundary.
    """
    assert "bypassPermissions" not in PERMISSION_MODES["claude"]
    assert "danger-full-access" not in PERMISSION_MODES["codex"]
    for tool, modes in PERMISSION_MODES.items():
        assert "bypassPermissions" not in modes, tool
        assert "danger-full-access" not in modes, tool


@pytest.mark.parametrize(
    ("worker_type", "mode"),
    [
        ("terminal-claude", "bypassPermissions"),
        ("terminal-codex", "danger-full-access"),
    ],
)
def test_requesting_an_unrestricted_mode_fails_closed(worker_type: str, mode: str) -> None:
    """Asking for one must raise, not fall back to something else."""
    config = WORKER_REGISTRY[worker_type]

    with pytest.raises(ValueError, match="not valid"):
        shell_backend.resolve_permission_mode(config, mode)


def test_settings_override_wins_over_the_registry_default() -> None:
    """``workers.permission_modes`` is the hook; the registry is the fallback."""
    from mahavishnu.core.config import MahavishnuSettings

    settings = MahavishnuSettings()
    settings.workers.permission_modes = {"terminal-claude": "plan"}

    mode = shell_backend.resolve_permission_mode(
        WORKER_REGISTRY["terminal-claude"], settings.workers.permission_modes["terminal-claude"]
    )
    assert mode == "plan"
    # Not listed -> registry default.
    assert (
        shell_backend.resolve_permission_mode(
            WORKER_REGISTRY["terminal-qwen"], settings.workers.permission_modes.get("terminal-qwen")
        )
        == "yolo"
    )


def test_settings_default_is_empty() -> None:
    """The hook must be inert until an operator opts in."""
    from mahavishnu.core.config import MahavishnuSettings

    assert MahavishnuSettings().workers.permission_modes == {}


# ---------------------------------------------------------------------------
# The one-shot shape
# ---------------------------------------------------------------------------
#
# A one-shot worker is launched WITH the prompt: it rides the command line
# as $MAHAVISHNU_PROMPT, and the shell prints a completion marker when the
# CLI exits. Nothing is typed into the session.


ONE_SHOT_AGENTS = ("terminal-qwen", "terminal-claude", "terminal-codex", "terminal-deepagents")


@pytest.mark.parametrize("worker_type", ONE_SHOT_AGENTS)
def test_the_one_shot_command_reads_the_prompt_from_the_environment(
    worker_type: str,
) -> None:
    """The prompt is data on the command line, never typed into the session."""
    command = WORKER_REGISTRY[worker_type].command

    assert f'"${PROMPT_ENV_VAR}"' in command, (
        f"{worker_type} must read the prompt from ${PROMPT_ENV_VAR}"
    )
    assert "{prompt}" not in command
    assert WORKER_REGISTRY[worker_type].one_shot is True


@pytest.mark.parametrize("worker_type", ONE_SHOT_AGENTS)
def test_the_one_shot_command_keeps_the_pane_alive_after_the_cli_exits(
    worker_type: str,
) -> None:
    """The pane must outlive the CLI, or the output dies with it.

    When the command exits, tmux closes the pane and the output the CLI
    produced goes with it -- including any error it printed on the way
    out. A blocking ``read`` keeps the shell (and the pane) alive so the
    worker can read what the CLI left behind.
    """
    command = WORKER_REGISTRY[worker_type].command

    assert "read -r _" in command, f"{worker_type} must keep its pane alive after the CLI exits"
    assert "__MAHAVISHNU_DONE__" in command
    assert WORKER_REGISTRY[worker_type].completion_markers == ["__MAHAVISHNU_DONE__"]


@pytest.mark.parametrize("worker_type", ONE_SHOT_AGENTS)
def test_the_one_shot_marker_comes_after_the_cli(worker_type: str) -> None:
    """The marker is printed when the CLI is done, so it must come last."""
    command = WORKER_REGISTRY[worker_type].command

    assert command.index("__MAHAVISHNU_DONE__") > command.index(PROMPT_ENV_VAR)
