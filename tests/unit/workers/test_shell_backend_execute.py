"""Tests for ``ShellWorker.execute`` -- req: Phase 4 per-engine dispatch.

The method previously returned ``COMPLETED`` without sending anything, so a
dispatch through ``WorkerOrchestratorAdapter`` reported success in 0.187s
while doing no work at all. These tests drive the real implementation: send
prompt, poll the pane, return on the completion sentinel.
"""

from __future__ import annotations

from typing import Any

import pytest

from mahavishnu.workers import shell_backend
from mahavishnu.workers.registry import PROMPT_ENV_VAR
from mahavishnu.workers.shell_backend import ShellWorker


class _FakeManager:
    """Terminal manager double that mimics a pane.

    ``replies`` is how many ``capture_output`` calls it takes before the CLI
    "answers"; every poll before that appends filler so the sentinel logic
    cannot pass on the first read. The first poll echoes the instruction --
    including the sentinel -- because a real terminal does, and that echo is
    what a naive completion check mistakes for a reply.
    """

    def __init__(self, *, replies: int = 2, echo_marker: bool = True) -> None:
        self.pane = ""
        self.sent: list[str] = []
        self.captures = 0
        self.replies = replies
        self.echo_marker = echo_marker
        self.launched: list[str] = []
        self.env_overrides: dict[str, str] = {}

    async def launch_sessions(
        self,
        command: str,
        count: int,
        worker_type: str,
        env_overrides: dict[str, str] | None = None,
    ) -> list[str]:
        self.launched.append(command)
        self.env_overrides = dict(env_overrides or {})
        self.pane = f"$ {command}\n"
        return ["sess-1"]

    async def send_command(self, session_id: str, command: str) -> None:
        self.sent.append(command)

    async def capture_output(self, session_id: str, lines: int | None = None) -> str:
        self.captures += 1
        if self.sent and self.captures == 2:
            # The terminal echoes the instruction we sent -- including the
            # sentinel. A naive substring search finds it here and reports
            # completion before the model has replied. (Capture #1 is the
            # pre-send snapshot, so the echo lands on the next read.)
            self.pane += self.sent[0] + "\n"
            return self.pane
        if self.captures <= self.replies:
            self.pane += "thinking...\n"
            return self.pane
        if self.echo_marker:
            marker = _marker_from(self.sent[0])
            self.pane += f"working done\n{marker}\n"
        else:
            self.pane += "finished without the token\n"
        return self.pane

    async def close_session(self, session_id: str) -> None:
        return None


def _config(**overrides: Any) -> Any:
    base = {
        "worker_type": "terminal-claude",
        "command": "claude",
        "default_timeout": 5,
        # No permission mode on this fake, and the fake command carries no
        # {permission_mode} placeholder, so rendering is a pass-through.
        "permission_mode": None,
        "requires_tool": "claude",
    }
    base.update(overrides)
    return type("C", (), base)()


def _marker_from(instruction: str) -> str:
    """Extract the sentinel from a dispatched instruction."""
    prefix = shell_backend._DONE_SENTINEL_PREFIX
    start = instruction.index(prefix)
    rest = instruction[start:]
    end = rest.index(" ")
    return rest[:end]


async def _started(manager: _FakeManager, **cfg: Any) -> ShellWorker:
    worker = ShellWorker(config=_config(**cfg), terminal_manager=manager)  # type: ignore[arg-type]
    await worker.start()
    return worker


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the 1s poll from making the suite slow."""
    monkeypatch.setattr(shell_backend, "_POLL_INTERVAL_SECONDS", 0.01)


async def test_execute_sends_the_prompt_and_returns_on_the_sentinel() -> None:
    manager = _FakeManager()
    worker = await _started(manager)

    result = await worker.execute({"prompt": "add a test"})

    assert result.status.value == "completed"
    assert "add a test" in manager.sent[0]
    assert manager.captures >= 2, "must poll, not read once and assume completion"


async def test_sentinel_is_unique_per_call() -> None:
    """Two dispatches on one session must not collide on a fixed token."""
    manager = _FakeManager()
    worker = await _started(manager)

    await worker.execute({"prompt": "first"})
    await worker.execute({"prompt": "second"})

    first = _marker_from(manager.sent[0])
    second = _marker_from(manager.sent[1])
    assert first != second
    assert first.startswith(shell_backend._DONE_SENTINEL_PREFIX)


async def test_output_excludes_prior_history() -> None:
    """A long-lived session must not return the previous call's scrollback."""
    manager = _FakeManager()
    worker = await _started(manager)
    first = await worker.execute({"prompt": "first"})

    second = await worker.execute({"prompt": "second"})

    assert second.output is not None
    assert "first" not in second.output
    assert second.output != first.output


async def test_missing_prompt_fails_loudly() -> None:
    """An empty task must not report success -- the old bug's shape."""
    manager = _FakeManager()
    worker = await _started(manager)

    result = await worker.execute({})

    assert result.status.value == "failed"
    assert "prompt" in result.error
    assert manager.sent == [], "nothing may be sent without a prompt"


async def test_execute_before_start_fails() -> None:
    worker = ShellWorker(config=_config(), terminal_manager=_FakeManager())  # type: ignore[arg-type]

    result = await worker.execute({"prompt": "anything"})

    assert result.status.value == "failed"
    assert "before start()" in result.error


async def test_no_sentinel_times_out_rather_than_claiming_success() -> None:
    """The CLI may never emit the token; that is a timeout, not a pass."""
    manager = _FakeManager(replies=99, echo_marker=False)
    worker = await _started(manager, default_timeout=1)

    result = await worker.execute({"prompt": "silent"})

    assert result.status.value == "timeout"
    assert result.metadata["timed_out"] is True
    assert "did not emit sentinel" in result.error


async def test_timeout_prefers_the_task_value() -> None:
    manager = _FakeManager(replies=99, echo_marker=False)
    worker = await _started(manager, default_timeout=1)

    result = await worker.execute({"prompt": "x", "timeout": 1})

    assert result.status.value == "timeout"


async def test_session_is_left_running_for_the_next_call() -> None:
    """``stop()`` owns teardown; execute must not close the session."""
    manager = _FakeManager()
    worker = await _started(manager)

    await worker.execute({"prompt": "one"})

    assert worker._session_id == "sess-1"
    assert manager.launched == ["claude"], "no relaunch per execute"


# ---------------------------------------------------------------------------
# echo vs reply
# ---------------------------------------------------------------------------


def test_sentinel_in_the_echo_is_not_a_reply() -> None:
    """The instruction's own echo must not satisfy the completion check.

    Regression: a live dispatch "succeeded" in 1.05s with the prompt text as
    its output, and Bifrost logged no request -- the sentinel was found in
    the terminal's echo of the instruction, before the model replied.
    """
    marker = "MAHAVISHNU-DONE-abc123"
    echo = f"Working in /repo. Do the thing\n\nreply with exactly this token and nothing else: {marker} {shell_backend._ECHO_ANCHOR}\n"

    assert marker in echo, "the echo does contain the sentinel"
    assert shell_backend._sentinel_replied(echo, marker) is False


def test_sentinel_after_the_echo_is_a_reply() -> None:
    marker = "MAHAVISHNU-DONE-abc123"
    pane = (
        f"Working in /repo. Do the thing\n\nreply with exactly this token and nothing else: "
        f"{marker} {shell_backend._ECHO_ANCHOR}\n"
        f"the work is done\n{marker}\n"
    )

    assert shell_backend._sentinel_replied(pane, marker) is True


def test_wrapped_anchor_still_counts() -> None:
    """tmux renders wrapped rows as separate lines; the anchor may straddle one."""
    marker = "MAHAVISHNU-DONE-abc123"
    pane = (
        f"reply with exactly this token and nothing else: {marker} "
        f"MAHAVISHNU-END-OF-\nINSTRUCTION\n"
        f"{marker}\n"
    )

    assert shell_backend._sentinel_replied(pane, marker) is True


def test_adapter_without_echo_still_detects_the_reply() -> None:
    """The mock adapter never echoes; the sentinel can only be a reply."""
    marker = "MAHAVISHNU-DONE-abc123"

    assert shell_backend._sentinel_replied(f"done\n{marker}\n", marker) is True


def test_answer_excludes_the_echo_and_the_sentinel() -> None:
    """The reported output is the model's answer, not our own instruction.

    Asking the model to reply with *exactly* the token would throw its work
    away, so the instruction asks for the answer first and the token on a
    final line. The answer is what lies between the echoed instruction and
    that token.
    """
    marker = "MAHAVISHNU-DONE-abc123"
    pane = (
        "Working in /repo. Do the thing\n\n"
        f"give your answer and then reply with exactly this token: {marker} "
        f"{shell_backend._ECHO_ANCHOR}\n"
        "the real answer is 42\n"
        f"{marker}\n"
    )

    out = shell_backend._output_since("", pane, marker)

    assert "the real answer is 42" in out
    assert marker not in out
    assert shell_backend._ECHO_ANCHOR not in out
    assert "Working in /repo" not in out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_resolve_timeout_precedence() -> None:
    config = _config(default_timeout=7)
    assert shell_backend._resolve_timeout({"timeout": 3}, config) == 3  # type: ignore[arg-type]
    assert shell_backend._resolve_timeout({}, config) == 7  # type: ignore[arg-type]
    assert shell_backend._resolve_timeout({"timeout": 0}, config) == 7  # type: ignore[arg-type]
    assert shell_backend._resolve_timeout({"timeout": "bad"}, config) == 7  # type: ignore[arg-type]
    assert shell_backend._resolve_timeout({}, _config(default_timeout=None)) == (
        shell_backend._DEFAULT_TIMEOUT_SECONDS
    )


def test_output_since_strips_history_and_sentinel() -> None:
    assert shell_backend._output_since("old\n", "old\nnew\n", "M") == "new"
    # Buffer trimmed by the adapter: fall back to everything rather than "".
    assert "kept" in shell_backend._output_since("gone", "kept\nM", "M")

# ---------------------------------------------------------------------------
# The one-shot shape
# ---------------------------------------------------------------------------
#
# A one-shot worker is launched WITH the prompt: it rides the command line
# as $MAHAVISHNU_PROMPT, and the shell prints a completion marker when
# the CLI exits. Nothing is typed into the session, so the worker's job is
# to wait for the marker.


class _OneShotManager:
    """Terminal manager whose pane shows the CLI's output, then the marker."""

    def __init__(self, *, emits_marker: bool = True, delay: int = 2) -> None:
        self.pane = ""
        self.sent: list[str] = []
        self.captures = 0
        self.emits_marker = emits_marker
        self.delay = delay
        self.env_overrides: dict[str, str] = {}

    async def launch_sessions(self, command, count, worker_type, env_overrides=None):
        self.env_overrides = dict(env_overrides or {})
        return ["sess-1"]

    async def send_command(self, session_id: str, command: str) -> None:
        self.sent.append(command)

    async def capture_output(self, session_id: str, lines: int | None = None) -> str:
        self.captures += 1
        if self.captures <= self.delay:
            return self.pane
        self.pane += 'the real answer is 42\n'
        if self.emits_marker:
            self.pane += "__MAHAVISHNU_DONE__\n"
        return self.pane

    async def close_session(self, session_id: str) -> None:
        return None


def _one_shot_config(**overrides: Any) -> Any:
    base = {
        "worker_type": "terminal-probe",
        "command": "sh -lc 'probe \"$MAHAVISHNU_PROMPT\"; printf \"\\n__MAHAVISHNU_DONE__\\n\"'",
        "default_timeout": 5,
        "permission_mode": None,
        "requires_tool": "claude",
        "completion_markers": ["__MAHAVISHNU_DONE__"],
    }
    base.update(overrides)
    return type("C", (), base)()


async def test_one_shot_prompt_travels_with_the_launch_command() -> None:
    """The prompt rides the command line, so it must reach the session env."""
    manager = _OneShotManager()
    worker = ShellWorker(config=_one_shot_config(), terminal_manager=manager)  # type: ignore[arg-type]

    await worker.start(prompt="do the thing")

    assert manager.env_overrides[PROMPT_ENV_VAR] == "do the thing"
    assert manager.sent == [], "a one-shot worker must not type anything"


async def test_one_shot_waits_for_the_completion_marker() -> None:
    manager = _OneShotManager()
    worker = ShellWorker(config=_one_shot_config(), terminal_manager=manager)  # type: ignore[arg-type]
    await worker.start(prompt="do the thing")

    result = await worker.execute({"prompt": "do the thing"})

    assert result.status.value == "completed"
    assert "the real answer is 42" in (result.output or "")
    assert "__MAHAVISHNU_DONE__" not in (result.output or ""), (
        "the marker is the shell's signal, not part of the answer"
    )
    assert manager.sent == []


async def test_one_shot_times_out_without_the_marker() -> None:
    """No marker means the CLI never finished -- that is a timeout."""
    manager = _OneShotManager(emits_marker=False)
    worker = ShellWorker(config=_one_shot_config(default_timeout=1), terminal_manager=manager)  # type: ignore[arg-type]
    await worker.start(prompt="do the thing")

    result = await worker.execute({"prompt": "do the thing"})

    assert result.status.value == "timeout"
    assert result.metadata["timed_out"] is True
    assert "completion marker" in result.error


async def test_one_shot_ignores_the_prompt_in_the_task() -> None:
    """The prompt went out at launch; the task's copy is not a second prompt."""
    manager = _OneShotManager()
    worker = ShellWorker(config=_one_shot_config(), terminal_manager=manager)  # type: ignore[arg-type]
    await worker.start(prompt="the real prompt")

    result = await worker.execute({"prompt": "a different prompt"})

    assert result.status.value == "completed"
    assert manager.sent == [], "the task prompt must not be typed"


# ---------------------------------------------------------------------------
# The instruction is one line
# ---------------------------------------------------------------------------


def test_the_instruction_is_a_single_line() -> None:
    """A TUI submits on CR; a literal LF is not a submit.

    A multi-line instruction is delivered as one message with the line
    breaks folded, so the completion token is the last thing the model
    reads rather than sitting in the middle of the message.
    """
    marker = "MAHAVISHNU-DONE-abc123"
    instruction = shell_backend.build_instruction("line one\nline two\n\nline three", marker)

    assert "\n" not in instruction
    assert "line one line two line three" in instruction
    assert instruction.endswith(f"{marker} {shell_backend._ECHO_ANCHOR}")


def test_the_instruction_keeps_the_token_at_the_end() -> None:
    """The model has to read the token last, or it cannot repeat it."""
    marker = "MAHAVISHNU-DONE-abc123"
    instruction = shell_backend.build_instruction("a multi\nline\nprompt", marker)

    assert instruction.rstrip().endswith(shell_backend._ECHO_ANCHOR)
    assert instruction.index(marker) < instruction.index(shell_backend._ECHO_ANCHOR)
