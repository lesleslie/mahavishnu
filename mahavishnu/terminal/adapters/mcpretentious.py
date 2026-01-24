"""mcpretentious MCP server adapter for terminal management."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from ..adapters.base import TerminalAdapter
from ...core.errors import MahavishnuError


class TerminalError(MahavishnuError):
    """Base exception for terminal operations."""

    pass


class SessionNotFound(TerminalError):
    """Exception raised when session ID is not found."""

    pass


class McpretentiousAdapter(TerminalAdapter):
    """mcpretentious MCP server adapter for terminal management.

    This adapter uses the mcpretentious MCP server to manage terminal
    sessions with PTY-based command injection and output capture.

    Example:
        >>> from mahavishnu.terminal.adapters import McpretentiousAdapter
        >>> adapter = McpretentiousAdapter(mcp_client)
        >>> session_id = await adapter.launch_session("qwen", 120, 40)
        >>> await adapter.send_command(session_id, "hello")
        >>> output = await adapter.capture_output(session_id)
    """

    def __init__(self, mcp_client: Any):
        """Initialize mcpretentious adapter.

        Args:
            mcp_client: MCP client with call_tool method
        """
        self.mcp = mcp_client
        self._sessions: Dict[str, Dict[str, Any]] = {}

    @property
    def adapter_name(self) -> str:
        """Return adapter name."""
        return "mcpretentious"

    async def launch_session(
        self,
        command: str,
        columns: int = 80,
        rows: int = 24,
        **kwargs: Any,
    ) -> str:
        """Launch a terminal session via mcpretentious.

        Args:
            command: Command to run in the terminal
            columns: Terminal width in characters
            rows: Terminal height in lines
            **kwargs: Ignored (for compatibility with other adapters)

        Returns:
            Terminal session ID

        Raises:
            TerminalError: If session launch fails
        """
        try:
            # Open terminal window
            result = await self.mcp.call_tool(
                "mcpretentious-open",
                {
                    "columns": columns,
                    "rows": rows,
                },
            )
            session_id = result["terminal_id"]

            # Store session metadata
            self._sessions[session_id] = {
                "command": command,
                "created_at": datetime.now(),
                "columns": columns,
                "rows": rows,
            }

            # Send initial command
            await self.send_command(session_id, command)

            return session_id

        except Exception as e:
            raise TerminalError(
                message=f"Failed to launch session: {e}",
                details={"command": command, "columns": columns, "rows": rows},
            ) from e

    async def send_command(
        self,
        session_id: str,
        command: str,
    ) -> None:
        """Send command to a terminal session.

        Args:
            session_id: Terminal session ID
            command: Command string to send

        Raises:
            SessionNotFound: If session_id doesn't exist
            TerminalError: If command send fails
        """
        if session_id not in self._sessions:
            raise SessionNotFound(
                message=f"Session {session_id} not found",
                details={"session_id": session_id},
            )

        try:
            await self.mcp.call_tool(
                "mcpretentious-type",
                {
                    "terminal_id": session_id,
                    "input": [command, "enter"],
                },
            )
        except Exception as e:
            raise TerminalError(
                message=f"Failed to send command: {e}",
                details={"session_id": session_id, "command": command},
            ) from e

    async def capture_output(
        self,
        session_id: str,
        lines: Optional[int] = None,
    ) -> str:
        """Capture output from a terminal session.

        Args:
            session_id: Terminal session ID
            lines: Number of lines to capture (None for all)

        Returns:
            Terminal output as string

        Raises:
            SessionNotFound: If session_id doesn't exist
            TerminalError: If output capture fails
        """
        if session_id not in self._sessions:
            raise SessionNotFound(
                message=f"Session {session_id} not found",
                details={"session_id": session_id},
            )

        try:
            kwargs: Dict[str, Any] = {"terminal_id": session_id}
            if lines is not None:
                kwargs["limit_lines"] = lines

            result = await self.mcp.call_tool("mcpretentious-read", kwargs)
            return result["output"]

        except Exception as e:
            raise TerminalError(
                message=f"Failed to capture output: {e}",
                details={"session_id": session_id, "lines": lines},
            ) from e

    async def close_session(self, session_id: str) -> None:
        """Close a terminal session.

        Args:
            session_id: Terminal session ID to close

        Raises:
            TerminalError: If session close fails
        """
        try:
            await self.mcp.call_tool(
                "mcpretentious-close",
                {
                    "terminal_id": session_id,
                },
            )
        except Exception as e:
            raise TerminalError(
                message=f"Failed to close session: {e}",
                details={"session_id": session_id},
            ) from e
        finally:
            # Clean up session metadata
            if session_id in self._sessions:
                del self._sessions[session_id]

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """List all active terminal sessions.

        Returns:
            List of session information dictionaries

        Raises:
            TerminalError: If listing fails
        """
        try:
            result = await self.mcp.call_tool("mcpretentious-list", {})
            return result.get("terminals", [])

        except Exception as e:
            raise TerminalError(
                message=f"Failed to list sessions: {e}",
                details={},
            ) from e
