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
from mahavishnu.workers.shell_backend import ShellWorker


class _FakeManager:
    """Terminal manager double that mimics a pane.

    ``replies`` is how many ``capture_output`` calls it takes before the CLI
    "answers"; every poll before that appends filler so the sentinel logic
    cannot pass on the first read.
    """

    def __init__(self, *, replies: int = 2, echo_marker: bool = True) -> None:
        self.pane = ""
        self.sent: list[str] = []
        self.captures = 0
        self.replies = replies
        self.echo_marker = echo_marker
        self.launched: list[str] = []

    async def launch_sessions(self, command: str, count: int, worker_type: str) -> list[str]:
        self.launched.append(command)
        self.pane = f"$ {command}\n"
        return ["sess-1"]

    async def send_command(self, session_id: str, command: str) -> None:
        self.sent.append(command)

    async def capture_output(self, session_id: str, lines: int | None = None) -> str:
        self.captures += 1
        if self.captures < self.replies:
            self.pane += "thinking...\n"
            return self.pane
        if self.echo_marker:
            marker = self.sent[0].rsplit(" ", 1)[-1]
            self.pane += f"working done\n{marker}\n"
        else:
            self.pane += "finished without the token\n"
        return self.pane

    async def close_session(self, session_id: str) -> None:
        return None


def _config(**overrides: Any) -> Any:
    base = {"worker_type": "terminal-claude", "command": "claude", "default_timeout": 5}
    base.update(overrides)
    return type("C", (), base)()


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

    first = manager.sent[0].rsplit(" ", 1)[-1]
    second = manager.sent[1].rsplit(" ", 1)[-1]
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