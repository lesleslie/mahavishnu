"""crow-mcp PTY toolserver adapter for terminal management."""

from __future__ import annotations

from logging import getLogger
from typing import Any

from mahavishnu.core.errors import ErrorCode

from ..adapters.base import TerminalAdapter
from .mcpretentious import SessionNotFoundError, TerminalError

logger = getLogger(__name__)


class CrowTerminalAdapter(TerminalAdapter):
    """Terminal adapter backed by crow-mcp PTY toolserver.

    Calls crow-mcp's `terminal` tool via MCP client to provide persistent
    PTY sessions. Session state is tracked locally; crow-mcp maintains a
    single persistent PTY process.

    NOTE: Verify crow-mcp tool names against the installed package.
    Expected tool: `terminal` with ``{"command": "..."}`` parameter schema.
    """

    def __init__(self, mcp_client: Any) -> None:
        self.mcp = mcp_client
        self._sessions: dict[str, dict[str, Any]] = {}

    @property
    def adapter_name(self) -> str:
        """Return adapter name."""
        return "crow"

    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        **kwargs: Any,
    ) -> str:
        """Launch a PTY session via crow-mcp and return a local session ID.

        crow-mcp maintains a single persistent PTY. A UUID is generated
        locally so that callers can address the session by ID in subsequent
        calls.

        Args:
            command: Command to run in the terminal session.
            columns: Terminal width in characters.
            rows: Terminal height in lines.
            **kwargs: Ignored (for compatibility with other adapters).

        Returns:
            Unique session identifier (UUID string).

        Raises:
            TerminalError: If the crow-mcp call fails.
        """
        try:
            result = await self.mcp.call_tool(
                "terminal",
                {"command": command},
            )
            import uuid  # noqa: PLC0415

            session_id = str(uuid.uuid4())
            self._sessions[session_id] = {
                "command": command,
                "columns": columns,
                "rows": rows,
                "initial_output": result.content[0].text if result.content else "",
            }
            logger.debug(f"crow-mcp session launched: {session_id}")
            return session_id
        except Exception as e:
            raise TerminalError(
                message=f"crow-mcp: failed to launch session: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"command": command},
            ) from e

    async def send_command(self, session_id: str, command: str) -> None:
        """Send a command to an active crow-mcp PTY session.

        Args:
            session_id: Terminal session identifier.
            command: Command string to send.

        Raises:
            SessionNotFoundError: If session_id is not tracked locally.
            TerminalError: If the crow-mcp call fails.
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"crow-mcp: session {session_id} not found",
                details={"session_id": session_id},
            )
        try:
            await self.mcp.call_tool(
                "terminal",
                {"command": command},
            )
        except Exception as e:
            raise TerminalError(
                message=f"crow-mcp: failed to send command: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"session_id": session_id, "command": command},
            ) from e

    async def capture_output(
        self,
        session_id: str,
        lines: int | None = None,
    ) -> str:
        """Capture PTY output from crow-mcp.

        Args:
            session_id: Terminal session identifier.
            lines: Number of lines to return (None for all).

        Returns:
            Terminal output as string.

        Raises:
            SessionNotFoundError: If session_id is not tracked locally.
            TerminalError: If the crow-mcp call fails.
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"crow-mcp: session {session_id} not found",
                details={"session_id": session_id},
            )
        try:
            result = await self.mcp.call_tool(
                "terminal",
                {"command": ""},
            )
            output = result.content[0].text if result.content else ""
            if lines is not None:
                output = "\n".join(output.splitlines()[-lines:])
            return output
        except Exception as e:
            raise TerminalError(
                message=f"crow-mcp: failed to capture output: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"session_id": session_id},
            ) from e

    async def close_session(self, session_id: str) -> None:
        """Close a crow-mcp PTY session.

        Args:
            session_id: Terminal session identifier to close.

        Raises:
            SessionNotFoundError: If session_id is not tracked locally.
            TerminalError: If the crow-mcp call fails.
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"crow-mcp: session {session_id} not found",
                details={"session_id": session_id},
            )
        try:
            await self.mcp.call_tool("terminal", {"command": "exit"})
            del self._sessions[session_id]
            logger.debug(f"crow-mcp session closed: {session_id}")
        except Exception as e:
            self._sessions.pop(session_id, None)
            raise TerminalError(
                message=f"crow-mcp: failed to close session: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"session_id": session_id},
            ) from e

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Return all locally tracked crow-mcp sessions.

        Returns:
            List of session information dictionaries.
        """
        return [{"id": sid, **meta} for sid, meta in self._sessions.items()]
