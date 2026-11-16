from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mahavishnu.terminal.adapters.base import TerminalAdapter

if TYPE_CHECKING:
    from mahavishnu.workers.contract.manager import DurableWorkerManager


#: How much of the pane's scrollback a capture reads.
#:
#: tmux keeps a bounded history (2,000 lines by default) and returns
#: everything it holds when asked for more, so this means "the whole
#: session" in practice while still bounding the work when the limit
#: is raised.
#:
#: Reading only the visible pane was enough to lose a reviewer's reply:
#: the pane is 24 rows, and a reply of about 1,800 characters no longer
#: fits, so it arrived with its opening cut off -- which reads as a
#: malformed verdict, and a malformed verdict is a block.
CAPTURE_SCROLLBACK_LINES: int = 2_000

#: The bound on a captured pane. The newest bytes are the ones kept, so
#: the answer -- written last -- survives the bound.
CAPTURE_MAX_BYTES: int = 65_536


class TmuxTerminalAdapter(TerminalAdapter):
    """Bridge terminal operations to the durable worker manager."""

    # Default worker_type for the singular launch_session kwargs
    # (preserved from the pre-Phase-D hardcoded "terminal-claude"
    # at the original line 31). The plural launch_sessions defaults
    # to the same value.
    _DEFAULT_WORKER_TYPE: str = "terminal-claude"

    def __init__(self, manager: DurableWorkerManager) -> None:
        self._manager = manager

    @property
    def adapter_name(self) -> str:
        """Return the adapter name used by terminal-manager telemetry."""
        return "tmux"

    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        *,
        worker_type: str = _DEFAULT_WORKER_TYPE,
        backend: str = "claude_tui",
        env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> str:
        """Launch one durable Claude terminal worker.

        Phase D (REQ-004) extends the signature with explicit
        ``worker_type`` and ``env`` kwargs. The Bifrost-specific
        env-injection happens upstream in
        ``TerminalManager._resolve_worker_env`` and the
        resulting dict is forwarded here. ``backend`` is also
        explicit so non-Claude workers can be spawned in the
        future (e.g. terminal-qwen).
        """
        result = self._manager.spawn(
            worker_type=worker_type,
            backend=backend,
            command=[command],
            env=env,
        )
        return result.worker_id

    async def launch_sessions(
        self,
        command: str,
        count: int = 1,
        columns: int = 80,
        rows: int = 24,
        *,
        worker_type: str = _DEFAULT_WORKER_TYPE,
        env: dict[str, str] | None = None,
    ) -> list[str]:
        """Launch multiple durable Claude terminal workers.

        Phase D (REQ-004) threads ``worker_type`` and ``env`` into
        the per-iteration ``launch_session`` so the plural
        contract does not lose information at the adapter
        boundary. Without this update, the v1.3 spec's
        ``TerminalManager.launch_sessions(worker_type=..., env=env)``
        would fail because the plural method only accepted
        ``(command, count)``.
        """
        return [
            await self.launch_session(
                command,
                columns=columns,
                rows=rows,
                worker_type=worker_type,
                env=env,
            )
            for _ in range(count)
        ]

    async def send_command(self, session_id: str, command: str) -> None:
        """Send a command to a durable worker session."""
        self._manager.send_input(session_id, command, submit=True)

    async def capture_output(
        self,
        session_id: str,
        lines: int | None = None,
    ) -> str:
        """Capture the current durable worker pane output.

        Reads the pane's scrollback rather than just its visible
        screenful: the visible pane is 24 rows, and a reply longer
        than that arrives with its opening cut off.

        ``lines`` bounds the read to the last N rows, matching the
        terminal adapter contract (``None`` means all of it) and the
        mock adapter's ``output_buffer[-lines:]``.

        The bound is applied here rather than left to tmux: ``-S -N``
        starts N rows above the *top* of the visible pane, so it
        returns N rows of scrollback **plus** the pane's own 24 rows
        (measured: ``-S -10`` on a 24-row pane returned 33 rows). The
        extra rows are dropped here so that ``lines`` means the same
        thing here as it does in the mock adapter.
        """
        result = self._manager.capture_output(
            session_id,
            since_offset=CAPTURE_SCROLLBACK_LINES if lines is None else lines,
            max_bytes=CAPTURE_MAX_BYTES,
        )
        if lines is None:
            return result.text
        if lines <= 0:
            # ``rows[-0:]`` is the whole list, not the empty one, so a
            # zero bound has to be handled before the slice. The
            # terminal adapter contract is that ``lines=0`` captures
            # nothing and ``None`` captures everything.
            return ""
        rows = result.text.splitlines()
        if len(rows) <= lines:
            return result.text
        return "\n".join(rows[-lines:])

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List durable worker records as terminal session metadata."""
        return [
            {
                **record.to_dict(),
                "session_id": record.worker_id,
            }
            for record in self._manager.store.list_all()
        ]

    async def close_session(self, session_id: str) -> None:
        """Gracefully cancel a durable worker session."""
        self._manager.cancel(session_id, signal="soft", grace_ms=2_000)
