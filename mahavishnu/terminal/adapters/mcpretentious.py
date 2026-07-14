"""mcpretentious MCP server adapter for terminal management."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...core.errors import ErrorCode, MahavishnuError
from ..adapters.base import TerminalAdapter
from ..backends import BUILTIN_BACKENDS


class TerminalError(MahavishnuError):
    """Base exception for terminal operations."""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: dict | None = None,
    ) -> None:
        super().__init__(message, error_code, details=details)


class SessionNotFoundError(TerminalError):
    """Exception raised when session ID is not found."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message, details=details)


class McpretentiousAdapter(TerminalAdapter):
    """mcpretentious MCP server adapter for terminal management.

    This adapter uses the mcpretentious MCP server to manage terminal
    sessions with PTY-based command injection and output capture.

    Example:
        >>> from mahavishnu.terminal.adapters import McpretentiousAdapter
        >>> adapter = McpretentiousAdapter(mcp_client, backend_name="mcpretentious")
        >>> session_id = await adapter.launch_session("qwen", 120, 40)
        >>> await adapter.send_command(session_id, "hello")
        >>> output = await adapter.capture_output(session_id)
    """

    def __init__(self, mcp_client: Any, backend_name: str | None = None):
        """Initialize mcpretentious adapter.

        Args:
            mcp_client: MCP client with call_tool method
            backend_name: Optional name of the PTY backend the operator
                selected via ``terminal.adapter_preference``. Stored for
                downstream consumption (e.g., tool-name resolution once a
                future task wires ``BUILTIN_BACKENDS`` into the adapter's
                ``call_tool`` dispatch). Defaults to ``None`` for backward
                compatibility with callers that pre-date the multi-backend
                wiring.
        """
        self.mcp = mcp_client
        self._backend_name = backend_name
        self._sessions: dict[str, dict[str, Any]] = {}

    def _tool_for(self, operation: str) -> str:
        """Resolve the MCP tool name for a generic PTY operation.

        Looks up ``BUILTIN_BACKENDS[self._backend_name].tool_map`` first
        (the contract for backend-specific tool names — e.g.,
        ``{"open": "custom_open"}``); falls back to the literal
        ``mcpretentious-{operation}`` for backends whose tool surface
        matches the built-in mcpretentious package.

        Args:
            operation: One of ``"open"``, ``"type"``, ``"read"``,
                ``"close"``, ``"list"``.

        Returns:
            The actual MCP tool name to call on the backend.
        """
        if self._backend_name and self._backend_name in BUILTIN_BACKENDS:
            mapped = BUILTIN_BACKENDS[self._backend_name].tool_map.get(operation)
            if mapped:
                return mapped
        return f"mcpretentious-{operation}"

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
                self._tool_for("open"),
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

            return session_id  # type: ignore[no-any-return]

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
            SessionNotFoundError: If session_id doesn't exist
            TerminalError: If command send fails
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"Session {session_id} not found",
                details={"session_id": session_id},
            )

        try:
            await self.mcp.call_tool(
                self._tool_for("type"),
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
        lines: int | None = None,
    ) -> str:
        """Capture output from a terminal session.

        Args:
            session_id: Terminal session ID
            lines: Number of lines to capture (None for all)

        Returns:
            Terminal output as string

        Raises:
            SessionNotFoundError: If session_id doesn't exist
            TerminalError: If output capture fails
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"Session {session_id} not found",
                details={"session_id": session_id},
            )

        try:
            kwargs: dict[str, Any] = {"terminal_id": session_id}
            if lines is not None:
                kwargs["limit_lines"] = lines

            result = await self.mcp.call_tool(self._tool_for("read"), kwargs)
            return result["output"]  # type: ignore[no-any-return]

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
                self._tool_for("close"),
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

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all active terminal sessions.

        Returns:
            List of session information dictionaries

        Raises:
            TerminalError: If listing fails
        """
        try:
            result = await self.mcp.call_tool(self._tool_for("list"), {})
            return result.get("terminals", [])  # type: ignore[no-any-return]

        except Exception as e:
            raise TerminalError(
                message=f"Failed to list sessions: {e}",
                details={},
            ) from e
