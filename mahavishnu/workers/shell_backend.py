"""Shell-worker backend for RuntimeKind.SHELL workers.

Workers with ``runtime_kind=RuntimeKind.SHELL`` (e.g.
``terminal-claude``, ``terminal-qwen``, ``terminal-codex``) run a
shell command from their :class:`WorkerConfig` via the
:mod:`mahavishnu.terminal.manager` TerminalManager. This module
replaces the dispatch path that the 2026-09-24 legacy-worker-deprecation
inadvertently broke — that ADR only retired the OS-level syscall-jail
isolated backends (``apple_container``, ``e2b_sandbox``) and kept
``shepherd_backend``, but the implementation in
``WorkerManager._create_worker`` was changed to route *every*
worker_type through ``_create_isolated_worker`` (which only accepts
``shepherd``). This module restores the SHELL path.

The Bifrost Phase D env-injection (``_resolve_worker_env`` in
``mahavishnu/terminal/manager.py``) is what makes the SHELL path
the right place for the ``route_qwen_code`` / ``route_claude_code``
wiring: when a pool spawns a SHELL worker, the terminal manager
adds the gateway's ``OPENAI_BASE_URL`` / ``ANTHROPIC_BASE_URL`` env
vars to the session, so the spawned CLI's outbound HTTP flows
through Bifrost.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .base import BaseWorker, WorkerResult, WorkerStatus
from .registry import PERMISSION_MODES, PROMPT_ENV_VAR

if TYPE_CHECKING:
    from ..terminal.manager import TerminalManager
    from .registry import WorkerConfig

logger = logging.getLogger(__name__)

#: Prefix for the completion token appended to every dispatched prompt.
_DONE_SENTINEL_PREFIX = "MAHAVISHNU-DONE-"

#: Placed *after* the sentinel in the instruction, so it marks where the echo
#: of the input ends. The sentinel alone is not a completion signal: the
#: terminal echoes the instruction we sent, so a naive search finds it in the
#: echo within a second and reports completion before the model has replied.
#: Searching for the sentinel *after* this anchor distinguishes the reply.
_ECHO_ANCHOR = "MAHAVISHNU-END-OF-INSTRUCTION"

#: How often the pane is re-read while waiting for the sentinel. One second
#: keeps end-to-end latency close to the CLI's own while costing one tmux
#: capture per poll.
_POLL_INTERVAL_SECONDS = 1.0

#: Fallback when neither the task nor the worker config carries a timeout.
_DEFAULT_TIMEOUT_SECONDS = 300

#: How long to wait for the CLI to draw something before typing into it.
#: The session is launched and the prompt is typed immediately, so without
#: this wait the keystrokes can land while the CLI is still starting --
#: before it has put the terminal into its own input mode -- and be
#: dropped. A CLI that never draws (a plain shell) costs the wait.
_READY_TIMEOUT_SECONDS = 8.0


def build_instruction(prompt: str, marker: str) -> str:
    """The instruction typed into the CLI's input buffer, on ONE line.

    A TUI submits on CR -- what the Enter key sends. A literal LF is not
    a submit; it is inserted into the buffer. So an instruction with
    embedded newlines is delivered as ONE message with the line breaks
    folded to spaces.

    This matters because the instruction carries the completion token:
    delivered across several lines, the CLI's buffer holds the token in
    the middle of the message rather than at the end of the final line,
    and the model is asked to repeat a token it has just been shown
    mid-sentence. Folded, the token is the last thing the model reads
    before it answers.
    """
    flat = re.sub(r"\s*\n\s*", " ", prompt).strip()
    return (
        f"{flat} When you are finished, give your answer and then, on its own "
        f"final line, reply with exactly this token: {marker} {_ECHO_ANCHOR}"
    )


def resolve_permission_mode(
    config: WorkerConfig,
    override: str | None = None,
) -> str | None:
    """Return the agent's approval/sandbox mode, validated against its CLI.

    The settings override (``workers.permission_modes``) wins over the
    registry default. The value is checked against the allowlist for that
    CLI, because it is substituted into a command line -- an unchecked
    settings value could otherwise smuggle a flag into the agent's argv.

    Returns ``None`` for a worker whose CLI has no such flag, and raises
    ``ValueError`` for a mode the CLI does not support.
    """
    mode = override if override is not None else config.permission_mode
    if mode is None:
        return None
    allowed = PERMISSION_MODES.get(config.requires_tool or "")
    if allowed is None:
        raise ValueError(
            f"worker {config.worker_type!r} has tool {config.requires_tool!r} with no "
            f"known permission modes; cannot validate {mode!r}"
        )
    if mode not in allowed:
        raise ValueError(
            f"permission mode {mode!r} is not valid for {config.requires_tool!r}; "
            f"expected one of {sorted(allowed)}"
        )
    return mode


def render_command(config: WorkerConfig, permission_mode: str | None) -> str:
    """Render the registry command with the resolved permission mode.

    The prompt is deliberately *not* substituted here. It reaches the CLI as
    the environment variable ``MAHAVISHNU_PROMPT``, read by the command as
    ``"$MAHAVISHNU_PROMPT"``.

    Interpolating it into the command string would be a shell-injection
    vector: the command reaches tmux as one string that tmux runs via
    ``/bin/sh -c``, so a prompt containing ``;`` or ``$(...)`` would execute.
    The prompt is data and must travel as data.
    """
    command = config.command
    if "{permission_mode}" in command:
        if permission_mode is None:
            raise ValueError(
                f"worker {config.worker_type!r} needs a permission mode but none resolved"
            )
        command = command.replace("{permission_mode}", permission_mode)
    if "{prompt}" in command:
        # Defence in depth: the placeholder is gone from the registry, and a
        # reintroduced one must fail loudly rather than reach a shell.
        raise ValueError(
            f"worker {config.worker_type!r} still carries a {{prompt}} placeholder; "
            "the prompt must be passed as data (MAHAVISHNU_PROMPT), never "
            "interpolated into the command"
        )
    return command


def _resolve_timeout(task: dict[str, Any], config: WorkerConfig) -> float:
    """Pick the execution timeout from the task, then the worker config."""
    for source in (task.get("timeout"), getattr(config, "default_timeout", None)):
        if source is None:
            continue
        try:
            value = float(source)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return float(_DEFAULT_TIMEOUT_SECONDS)


def _sentinel_span(pane: str, marker: str) -> tuple[int, int] | None:
    """Locate a genuine reply's sentinel in the pane.

    Returns ``(answer_start, marker_end)`` for the model's own reply, or
    ``None`` when the model has not answered yet.

    The instruction we send contains the sentinel, so the terminal's echo of
    that instruction contains it too. A plain substring search therefore
    finds the sentinel in the echo within a second -- before the model has
    produced anything -- and reports a completed dispatch that never
    happened. Verified live: a dispatch "succeeded" in 1.05s with the
    prompt's own text as its output, and Bifrost logged no request at all.

    The instruction ends with an anchor *after* the sentinel, so the echo
    reads ``... <marker> <anchor>`` while a genuine reply puts the marker
    on its own, further down the pane. The sentinel therefore only counts
    when it appears after the anchor.

    The pane is flattened first: tmux renders wrapped lines as separate
    rows, so the anchor can straddle a newline. Flattening replaces each
    newline with one space, so indices are unchanged and still address the
    original string.

    An adapter that does not echo at all (the mock) has no anchor; there the
    sentinel can only have come from a reply.
    """
    flat = pane.replace("\n", " ")
    anchor_at = flat.rfind(_ECHO_ANCHOR)
    search_from = anchor_at + len(_ECHO_ANCHOR) if anchor_at != -1 else 0
    found = flat.find(marker, search_from)
    if found == -1:
        return None
    return search_from, found + len(marker)


def _sentinel_replied(pane: str, marker: str) -> bool:
    """True only when the *model* replied, not when the terminal echoed us."""
    return _sentinel_span(pane, marker) is not None


def _strip_markers(pane: str, markers: list[str]) -> str:
    """The pane text with the completion markers removed.

    The marker is the shell's own signal that the CLI exited; it is not
    part of what the CLI produced, so it is not part of the answer.
    """
    text = pane
    for marker in markers:
        text = text.replace(marker, "")
    return text.strip()


def _output_since(before: str, pane: str, marker: str) -> str:
    """Return the model's answer for this call, without prior history.

    ``capture_output`` returns the whole scrollback, so a long-lived session
    would otherwise hand every ``execute()`` the output of all previous ones.
    The slice starts past the pre-send snapshot; if that anchor is gone (the
    adapter trimmed its buffer), fall back to everything rather than
    silently returning nothing.

    The answer is the text between the end of the echoed instruction and the
    sentinel the model was asked to append -- not the echo, and not the
    sentinel itself.
    """
    if before and pane.startswith(before):
        pane = pane[len(before) :]
    span = _sentinel_span(pane, marker)
    if span is None:
        return pane.strip()
    answer_start, marker_end = span
    return pane[answer_start : marker_end - len(marker)].strip()


class ShellWorker(BaseWorker):
    """A worker that runs a registered shell command in a terminal session.

    The session is launched via the shared :class:`TerminalManager`
    (which routes through the configured adapter — ``mock``,
    ``tmux``, or ``crow``). The session id becomes the
    worker id; one session per worker. ``execute()`` is a
    thin pass-through to the terminal manager's execute interface
    for one-shot prompts; long-lived sessions stay up between
    ``execute()`` calls and only get torn down by ``stop()``.
    """

    def __init__(
        self,
        *,
        config: WorkerConfig,
        terminal_manager: TerminalManager | None,
        session_buddy_client: Any | None = None,
        permission_mode: str | None = None,
    ) -> None:
        super().__init__(worker_type=config.worker_type)
        self.config = config
        # The resolved approval/sandbox mode, already validated against the
        # CLI's allowlist by :func:`resolve_permission_mode`. ``None`` means
        # "use the registry default", resolved at start().
        self._permission_mode = permission_mode
        # terminal_manager may be None at __init__ time when the
        # pool hasn't finished wiring it; the first ``start()``
        # call surfaces the diagnostic. We don't pre-validate
        # here so the pool can construct the worker first and the
        # error message is in the right lifecycle frame.
        self._terminal_manager = terminal_manager
        self._session_buddy_client = session_buddy_client
        self._session_id: str | None = None
        # True when the prompt was delivered with the launch command (the
        # one-shot shape) rather than typed into the session by execute().
        self._prompt_delivered = False

    async def start(self, *, prompt: str | None = None) -> str:
        if self._terminal_manager is None:
            raise RuntimeError(
                f"ShellWorker {self.worker_type!r} requires an initialized "
                f"terminal_manager. Check the pool's terminal_manager wiring "
                f"and the orchestrator's startup logs."
            )
        # The Bifrost Phase D env-injection runs inside
        # ``terminal_manager.launch_sessions`` — it injects
        # OPENAI_BASE_URL / ANTHROPIC_BASE_URL based on the
        # configured bifrost.routing flags. We don't need to
        # know about that here; it's the terminal manager's job.
        mode = resolve_permission_mode(self.config, self._permission_mode)
        command = render_command(self.config, mode)

        # The prompt is data, so it travels as an environment variable that
        # the command reads as "$MAHAVISHNU_PROMPT". It is never
        # interpolated into the command string: the command reaches tmux as
        # a single string that tmux runs via /bin/sh -c, so an interpolated
        # prompt containing ";" or "$(...)" would execute.
        env_overrides: dict[str, str] = {}
        if prompt is not None:
            env_overrides[PROMPT_ENV_VAR] = prompt
            # The prompt went out with the launch command, so the CLI is
            # already running it. ``execute()`` must not type it again --
            # it waits for the CLI to finish instead.
            self._prompt_delivered = True

        sessions = await self._terminal_manager.launch_sessions(
            command=command,
            count=1,
            worker_type=self.worker_type,
            env_overrides=env_overrides,
        )
        if not sessions:
            raise RuntimeError(
                f"ShellWorker {self.worker_type!r} failed to launch a "
                f"terminal session (adapter returned no session ids)"
            )
        self._session_id = sessions[0]
        self._status = WorkerStatus.RUNNING
        logger.info(
            f"ShellWorker started: worker_type={self.worker_type} session_id={self._session_id}"
        )
        return self._session_id

    async def execute(self, task: dict[str, Any]) -> WorkerResult:
        """Wait for the CLI to finish and report what it produced.

        req: Phase 4 -- this used to return ``COMPLETED`` unconditionally
        without sending anything, which was indistinguishable from real work:
        a dispatch through ``WorkerOrchestratorAdapter`` went green in
        0.187s with empty output while Bifrost logged nothing at all.

        Two shapes, picked by how the prompt was delivered:

        - **One-shot** (the prompt went out with the launch command, so the
          CLI is already running it): wait for a completion marker to
          appear in the pane. The registry's command ends with a
          ``printf`` of that marker, so it lands when the CLI exits --
          no cooperation from the model required.
        - **Interactive** (the prompt is typed into a live session): the
          CLI has no completion signal of its own, so the prompt is
          suffixed with a unique sentinel and the pane is polled until
          the sentinel comes back. Polling ``capture_output`` alone
          cannot work -- an LLM pausing between tokens is
          indistinguishable from being done.

        The session is long-lived and is left running; only ``stop()`` tears
        it down. Output is the pane text produced by *this* call, computed by
        slicing away the snapshot taken before the prompt was sent, so
        consecutive calls on one worker do not return each other's history.
        """
        if not self._session_id:
            return WorkerResult(
                worker_id="unknown",
                status=WorkerStatus.FAILED,
                error="ShellWorker.execute called before start()",
            )
        if self._terminal_manager is None:
            # ``start()`` is the guard for this, but ``execute`` may be reached
            # through a pool that constructed the worker before wiring it.
            return WorkerResult(
                worker_id=self._session_id,
                status=WorkerStatus.FAILED,
                error=f"ShellWorker {self.worker_type!r} has no terminal_manager",
            )
        prompt = task.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return WorkerResult(
                worker_id=self._session_id,
                status=WorkerStatus.FAILED,
                error="ShellWorker.execute requires a non-empty 'prompt' in the task",
            )

        if self._prompt_delivered:
            return await self._await_completion(task)

        marker = f"{_DONE_SENTINEL_PREFIX}{uuid4().hex[:12]}"
        # Wait for the CLI to draw before typing: the session was launched
        # a moment ago and the keystrokes would otherwise land before the
        # CLI owns the terminal, and be dropped.
        await self._await_ready()
        before = await self._terminal_manager.capture_output(self._session_id)
        await self._terminal_manager.send_command(
            self._session_id,
            build_instruction(prompt, marker),
        )

        timeout_s = _resolve_timeout(task, self.config)
        deadline = time.monotonic() + timeout_s
        pane = before
        while time.monotonic() < deadline:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            pane = await self._terminal_manager.capture_output(self._session_id)
            if _sentinel_replied(pane, marker):
                return WorkerResult(
                    worker_id=self._session_id,
                    status=WorkerStatus.COMPLETED,
                    output=_output_since(before, pane, marker),
                    exit_code=0,
                    duration_seconds=timeout_s - (deadline - time.monotonic()),
                    metadata={"session_id": self._session_id, "sentinel": marker},
                )
            if self._status is WorkerStatus.CANCELLED:
                break

        return WorkerResult(
            worker_id=self._session_id,
            status=WorkerStatus.TIMEOUT,
            output=_output_since(before, pane, marker),
            error=(
                f"CLI did not emit sentinel {marker!r} within {timeout_s}s; "
                "the prompt may not have been accepted by the session"
            ),
            duration_seconds=timeout_s,
            metadata={"session_id": self._session_id, "sentinel": marker, "timed_out": True},
        )

    async def _await_completion(self, task: dict[str, Any]) -> WorkerResult:
        """Wait for the CLI to exit, signalled by a completion marker.

        The registry's one-shot commands end with a ``printf`` of the
        marker, so the marker lands exactly when the CLI is done -- no
        cooperation from the model required, and no dependence on the
        model emitting a token on a line of its own.

        A worker whose config declares no completion marker can only be
        waited on until the timeout; that is reported as a timeout
        rather than a silent success.
        """
        markers = list(self.config.completion_markers or [])
        timeout_s = _resolve_timeout(task, self.config)
        deadline = time.monotonic() + timeout_s
        manager = self._terminal_manager
        session_id = self._session_id
        if manager is None or session_id is None:
            return WorkerResult(
                worker_id=session_id or "unknown",
                status=WorkerStatus.FAILED,
                error=f"ShellWorker {self.worker_type!r} has no terminal session",
            )
        pane = await manager.capture_output(session_id)
        while time.monotonic() < deadline:
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            pane = await manager.capture_output(session_id)
            if any(marker in pane for marker in markers):
                return WorkerResult(
                    worker_id=session_id,
                    status=WorkerStatus.COMPLETED,
                    output=_strip_markers(pane, markers),
                    exit_code=0,
                    duration_seconds=timeout_s - (deadline - time.monotonic()),
                    metadata={"session_id": session_id, "completion_markers": markers},
                )
            if self._status is WorkerStatus.CANCELLED:
                break

        return WorkerResult(
            worker_id=session_id,
            status=WorkerStatus.TIMEOUT,
            output=_strip_markers(pane, markers),
            error=(
                f"CLI did not emit any completion marker {markers!r} within {timeout_s}s"
            ),
            duration_seconds=timeout_s,
            metadata={"session_id": session_id, "timed_out": True},
        )

    async def _await_ready(self, timeout_s: float = _READY_TIMEOUT_SECONDS) -> None:
        """Wait for the CLI to draw something before typing into it.

        The session is launched and the prompt is typed immediately, so
        without this wait the keystrokes can land while the CLI is still
        starting -- before it has put the terminal into its own input
        mode -- and be dropped. A live dispatch then waits the full
        timeout for a model reply that was never asked for.

        A CLI that never draws (a plain shell) costs the wait and then
        the input is typed anyway.
        """
        deadline = time.monotonic() + timeout_s
        manager = self._terminal_manager
        session_id = self._session_id
        if manager is None or session_id is None:
            return
        while time.monotonic() < deadline:
            pane = await manager.capture_output(session_id)
            if pane.strip():
                return
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        if self._session_id and self._terminal_manager is not None:
            try:
                # TerminalManager exposes close_session (singular); close_sessions
                # does not exist on the manager — that was an API drift typo.
                await self._terminal_manager.close_session(self._session_id)
            except Exception:  # shutdown cleanup — best-effort, never fatal
                logger.exception(
                    f"ShellWorker.stop: close_session failed for session_id={self._session_id}"
                )
        # WorkerStatus has no STOPPED; CANCELLED is the right value for a
        # cooperative shutdown (DEGRADED is for runtime degradation, not stop).
        self._status = WorkerStatus.CANCELLED

    async def status(self) -> WorkerStatus:
        """Return the worker's current status.

        SHELL workers are long-lived sessions; the status field
        is the source of truth (set by ``start()`` and ``stop()``).
        A future iteration could poll the terminal manager for
        session liveness, but for the gate's purpose the cached
        status is sufficient.
        """
        return self._status

    async def get_progress(self) -> dict[str, Any]:
        """Return a minimal progress snapshot.

        The Qwen gate's pass criterion is the bifrost.log
        caller_id line, not progress metrics. This method
        returns the cached status + session_id so any future
        progress-aware caller (e.g. a CLI ``worker status``
        command) can see at least the worker_type and session_id.
        """
        return {
            "status": self._status.value,
            "session_id": self._session_id,
            "worker_type": self.worker_type,
            "output_preview": "",
        }


__all__ = ["ShellWorker"]
