from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mahavishnu.terminal.adapters.base import TerminalAdapter

if TYPE_CHECKING:
    from mahavishnu.workers.contract.manager import DurableWorkerManager


class TmuxTerminalAdapter(TerminalAdapter):
    """Bridge terminal operations to the durable worker manager."""

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
        **kwargs: Any,
    ) -> str:
        """Launch one durable Claude terminal worker."""
        result = self._manager.spawn(
            worker_type="terminal-claude",
            backend="claude_tui",
            command=[command],
        )
        return result.worker_id

    async def launch_sessions(self, command: str, count: int) -> list[str]:
        """Launch multiple durable Claude terminal workers."""
        return [await self.launch_session(command) for _ in range(count)]

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
