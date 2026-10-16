from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mahavishnu.terminal.adapters.base import TerminalAdapter

if TYPE_CHECKING:
    from mahavishnu.workers.contract.manager import DurableWorkerManager


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
        future (e.g. terminal-qwen, terminal-goose).
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
        """Capture the current durable worker pane output."""
        result = self._manager.capture_output(
            session_id,
            since_offset=0,
            max_bytes=65_536,
        )
        return result.text

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
