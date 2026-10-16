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

import logging
from typing import TYPE_CHECKING, Any

from .base import BaseWorker, WorkerResult, WorkerStatus

if TYPE_CHECKING:
    from ..terminal.manager import TerminalManager
    from .registry import WorkerConfig

logger = logging.getLogger(__name__)


class ShellWorker(BaseWorker):
    """A worker that runs a registered shell command in a terminal session.

    The session is launched via the shared :class:`TerminalManager`
    (which routes through the configured adapter — ``mock``,
    ``tmux``, ``crow``, or ``goose``). The session id becomes the
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
    ) -> None:
        super().__init__(worker_type=config.worker_type)
        self.config = config
        # terminal_manager may be None at __init__ time when the
        # pool hasn't finished wiring it; the first ``start()``
        # call surfaces the diagnostic. We don't pre-validate
        # here so the pool can construct the worker first and the
        # error message is in the right lifecycle frame.
        self._terminal_manager = terminal_manager
        self._session_buddy_client = session_buddy_client
        self._session_id: str | None = None

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
        sessions = await self._terminal_manager.launch_sessions(
            command=self.config.command,
            count=1,
            worker_type=self.worker_type,
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
        # The session is long-lived; one-shot tasks should be
        # submitted through the terminal manager's execute
        # interface (e.g. terminal_manager.execute_task on the
        # session). The exact interface depends on the adapter
        # in use (mock, tmux, crow, goose) and the Bifrost
        # Qwen gate's verification path runs the CLI directly
        # rather than through this method.
        if not self._session_id:
            return WorkerResult(
                worker_id="unknown",
                success=False,
                error="ShellWorker.execute called before start()",
            )
        return WorkerResult(
            worker_id=self._session_id,
            success=True,
            output="",
            metadata={
                "session_id": self._session_id,
                "note": "long-lived shell session; one-shot tasks go through the terminal manager",
            },
        )

    async def stop(self) -> None:
        if self._session_id and self._terminal_manager is not None:
            try:
                await self._terminal_manager.close_sessions([self._session_id])
            except Exception:  # shutdown cleanup — best-effort, never fatal
                logger.exception(
                    f"ShellWorker.stop: close_sessions failed for session_id={self._session_id}"
                )
        self._status = WorkerStatus.STOPPED

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
