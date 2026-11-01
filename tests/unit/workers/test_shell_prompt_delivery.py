"""Pin how a one-shot CLI receives its prompt.

Two properties, both learned the hard way:

**The prompt rides the launch, not the TUI.** A one-shot CLI harness
(``terminal-claude`` and friends) runs the prompt and exits. Delivering
it by typing into the CLI's TUI over tmux keystrokes depends on the
CLI being ready to read it and on its Enter semantics -- neither is
this codebase's to control, and both have gone wrong: the prompt sat
unsubmitted in the input buffer and the dispatch ran out its timeout
with the CLI idle.

**The prompt rides in a FILE.** The session is launched by handing tmux
``-e KEY=VALUE`` pairs, so tmux reads the environment out of its own
argv -- and tmux caps that command at roughly 16-24 KB (measured on
this host: 16 KB launched, 24 KB failed with "command too long"). A
prompt that big is ordinary, and the failure it produced named neither
the prompt nor the limit.
"""

from __future__ import annotations

import pathlib
import pytest

from mahavishnu.workers.registry import (
    PROMPT_ENV_VAR,
    PROMPT_FILE_ENV_VAR,
    WORKER_REGISTRY,
)
from mahavishnu.workers.shell_backend import ShellWorker, render_command

pytestmark = pytest.mark.unit

#: Larger than tmux's ~16-24 KB command ceiling, so it can only travel
#: in a file.
LARGE_PROMPT = "x" * 100_000


class _RecordingManager:
    """Terminal manager that records what the worker handed it."""

    def __init__(self) -> None:
        self.command = ""
        self.env: dict[str, str] = {}
        #: What the pane shows when the worker polls it.
        self.pane = "__MAHAVISHNU_DONE__ rc=0\n"

    async def launch_sessions(self, command, count, worker_type, env_overrides=None):
        self.command = command
        self.env = dict(env_overrides or {})
        return ["sess-1"]

    async def send_command(self, session_id: str, command: str) -> None:
        raise AssertionError("a one-shot worker must not type into the session")

    async def capture_output(self, session_id: str, lines: int | None = None) -> str:
        return self.pane

    async def close_session(self, session_id: str) -> None:
        return None


class TestPromptTravelsInAFile:
    """The environment carries a path, never the prompt itself."""

    async def test_env_carries_the_file_path_not_the_prompt(self) -> None:
        manager = _RecordingManager()
        worker = ShellWorker(
            config=WORKER_REGISTRY["terminal-claude"],
            terminal_manager=manager,  # type: ignore[arg-type]
        )

        await worker.start(prompt="do the thing")

        assert PROMPT_ENV_VAR not in manager.env, (
            "the prompt must not ride the environment: tmux reads it from argv"
        )
        prompt_path = manager.env[PROMPT_FILE_ENV_VAR]
        assert pathlib.Path(prompt_path).read_text() == "do the thing"

    async def test_a_prompt_beyond_the_tmux_command_limit_still_travels(self) -> None:
        """The whole point of the file: size stops mattering."""
        manager = _RecordingManager()
        worker = ShellWorker(
            config=WORKER_REGISTRY["terminal-claude"],
            terminal_manager=manager,  # type: ignore[arg-type]
        )

        await worker.start(prompt=LARGE_PROMPT)

        prompt_path = manager.env[PROMPT_FILE_ENV_VAR]
        assert pathlib.Path(prompt_path).read_text() == LARGE_PROMPT
        # The path is short; the prompt is not in the argv anywhere.
        assert len(prompt_path) < 200
        assert LARGE_PROMPT not in manager.command

    async def test_the_command_reads_the_file_back_into_the_variable(self) -> None:
        manager = _RecordingManager()
        worker = ShellWorker(
            config=WORKER_REGISTRY["terminal-claude"],
            terminal_manager=manager,  # type: ignore[arg-type]
        )

        await worker.start(prompt="do the thing")

        prologue = (
            f'{PROMPT_ENV_VAR}="$(cat "${PROMPT_FILE_ENV_VAR}")"; export {PROMPT_ENV_VAR}; '
        )
        assert manager.command.startswith(prologue)
        # The registry command still refers to the prompt by variable, so
        # the prompt is never shell text.
        assert f'"${PROMPT_ENV_VAR}"' in manager.command

    async def test_the_prompt_file_is_removed_when_the_run_finishes(self) -> None:
        manager = _RecordingManager()
        worker = ShellWorker(
            config=WORKER_REGISTRY["terminal-claude"],
            terminal_manager=manager,  # type: ignore[arg-type]
        )

        await worker.start(prompt="do the thing")
        prompt_path = pathlib.Path(manager.env[PROMPT_FILE_ENV_VAR])
        assert prompt_path.exists()

        await worker.execute({"prompt": "do the thing"})

        assert not prompt_path.exists(), "the prompt file must not outlive the run"

    async def test_no_prompt_means_no_file_and_no_prologue(self) -> None:
        manager = _RecordingManager()
        worker = ShellWorker(
            config=WORKER_REGISTRY["terminal-claude"],
            terminal_manager=manager,  # type: ignore[arg-type]
        )

        await worker.start()

        assert PROMPT_FILE_ENV_VAR not in manager.env
        prologue = (
            f'{PROMPT_ENV_VAR}="$(cat "${PROMPT_FILE_ENV_VAR}")"; export {PROMPT_ENV_VAR}; '
        )
        assert not manager.command.startswith(prologue)


class TestRenderCommand:
    """The prologue is opt-in: only a prompt-carrying launch gets it."""

    def test_without_a_prompt_file_the_command_is_unchanged(self) -> None:
        config = WORKER_REGISTRY["terminal-claude"]
        expected = config.command.replace("{permission_mode}", "acceptEdits")
        assert render_command(config, "acceptEdits") == expected

    def test_with_a_prompt_file_the_prologue_precedes_the_command(self) -> None:
        config = WORKER_REGISTRY["terminal-claude"]
        expected = config.command.replace("{permission_mode}", "acceptEdits")
        rendered = render_command(config, "acceptEdits", prompt_file=True)
        assert rendered.endswith(expected)
        assert PROMPT_FILE_ENV_VAR in rendered


class TestOneShotClicisAreNonInteractive:
    """A one-shot CLI harness must not open a TUI.

    ``claude`` starts an interactive session by default; only ``-p``
    runs a prompt and exits. Without ``-p`` the CLI ignores the prompt
    it was handed and waits for a human, so the worker would have to
    type the prompt into the TUI -- the path that does not work.
    """

    def test_terminal_claude_runs_the_prompt_non_interactively(self) -> None:
        command = WORKER_REGISTRY["terminal-claude"].command
        assert "claude -p " in command, (
            f"terminal-claude must run the prompt non-interactively: {command!r}"
        )

    def test_terminal_codex_runs_the_prompt_non_interactively(self) -> None:
        command = WORKER_REGISTRY["terminal-codex"].command
        assert "codex exec " in command, (
            f"terminal-codex must run the prompt non-interactively: {command!r}"
        )

    @pytest.mark.parametrize(
        "worker_type",
        ["terminal-claude", "terminal-qwen", "terminal-codex"],
    )
    def test_the_worker_is_declared_one_shot(self, worker_type: str) -> None:
        assert WORKER_REGISTRY[worker_type].one_shot is True

    def test_the_yaml_registry_mirrors_the_code_registry(self) -> None:
        """The settings copy is the operator-facing twin; it must agree."""
        settings_path = pathlib.Path("settings/mahavishnu.yaml")
        if not settings_path.exists():
            pytest.skip("not running from the repo root")
        text = settings_path.read_text()
        assert 'claude -p --verbose --output-format stream-json' in text, (
            "settings/mahavishnu.yaml still carries the interactive claude command"
        )


class TestAFailedCliIsNotASuccess:
    """The completion marker alone does not mean the work happened.

    The one-shot shell prints the marker when the CLI exits -- and a
    CLI can exit in a fraction of a second having done nothing at all
    (``claude -p --output-format stream-json`` without ``--verbose``
    exits immediately with an argument error). The marker therefore
    carries the CLI's exit status, and a non-zero status is reported as
    a failure.
    """

    def test_the_exit_code_is_parsed_from_the_marker(self) -> None:
        from mahavishnu.workers.shell_backend import _parse_exit_code

        assert _parse_exit_code("... __MAHAVISHNU_DONE__ rc=0\n") == 0
        assert _parse_exit_code("... __MAHAVISHNU_DONE__ rc=1\n") == 1
        # A marker written before the status was added carries none.
        assert _parse_exit_code("... __MAHAVISHNU_DONE__\n") is None

    async def test_a_non_zero_exit_is_reported_as_a_failure(self) -> None:
        from mahavishnu.workers.base import WorkerStatus

        manager = _RecordingManager()
        worker = ShellWorker(
            config=WORKER_REGISTRY["terminal-claude"],
            terminal_manager=manager,  # type: ignore[arg-type]
        )
        await worker.start(prompt="do the thing")

        # The CLI exited immediately with an argument error, so the
        # shell printed the marker with a non-zero status.
        manager.pane = "Error: unknown flag\n__MAHAVISHNU_DONE__ rc=1\n"

        result = await worker.execute({"prompt": "do the thing"})

        assert result.status is WorkerStatus.FAILED
        assert result.exit_code == 1
        assert "status 1" in (result.error or "")

    async def test_a_zero_exit_is_reported_as_a_success(self) -> None:
        from mahavishnu.workers.base import WorkerStatus

        manager = _RecordingManager()
        worker = ShellWorker(
            config=WORKER_REGISTRY["terminal-claude"],
            terminal_manager=manager,  # type: ignore[arg-type]
        )
        await worker.start(prompt="do the thing")

        manager.pane = '{"type":"result","result":"PONG"}\n__MAHAVISHNU_DONE__ rc=0\n'

        result = await worker.execute({"prompt": "do the thing"})

        assert result.status is WorkerStatus.COMPLETED
        assert result.exit_code == 0
        assert "PONG" in (result.output or "")
        # The shell's bookkeeping is not part of the answer.
        assert "rc=0" not in (result.output or "")


def test_the_one_shot_commands_carry_the_exit_status() -> None:
    """Every shell one-shot command must report the CLI's status."""
    from mahavishnu.workers.registry import RuntimeKind

    for worker_type, config in WORKER_REGISTRY.items():
        if not config.one_shot or config.runtime_kind is not RuntimeKind.SHELL:
            continue
        assert "__MAHAVISHNU_DONE__ rc=%s" in config.command, (
            f"{worker_type} must report the CLI's exit status: {config.command!r}"
        )
