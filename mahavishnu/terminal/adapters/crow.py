"""crow-mcp PTY toolserver adapter for terminal management."""

from __future__ import annotations

from typing import Any
import uuid

from oneiric.core.logging import get_logger

from mahavishnu.core.errors import ErrorCode

from ..adapters.base import TerminalAdapter
from .mcpretentious import SessionNotFoundError, TerminalError

logger = get_logger(__name__)


def _canonical_session_id(result: Any, fallback: str) -> str:
    """Return the server-canonical session_id when present, else *fallback*.

    The server-side ``crow_terminal_open`` returns ``{"session_id": <handle>}``
    so the producer can normalise the handle (strip whitespace, lowercase,
    etc.). Callers that hand us a pre-shaped mapping without ``session_id``
    (tests, mock clients) fall back to the input handle.
    """
    if isinstance(result, dict):
        sid = result.get("session_id")
        if isinstance(sid, str) and sid:
            return sid
    return fallback


def _extract_output(result: Any) -> str:
    """Extract the output text from either an MCP ``CallToolResult`` or a dict.

    ``crow_terminal_read`` returns ``{"output": "..."}``. The legacy
    ``terminal`` tool (still registered on the server) and some test
    doubles wrap the text in ``CallToolResult.content[0].text``. Accept
    either shape so the adapter works against both.
    """
    if isinstance(result, dict):
        return result.get("output") or ""
    content = getattr(result, "content", None)
    if content:
        first = content[0]
        text = getattr(first, "text", None)
        if text:
            return str(text)
    return ""


class CrowTerminalAdapter(TerminalAdapter):
    """Terminal adapter backed by crow-mcp PTY toolserver.

    Allocates a dedicated server-side session per ``launch_session`` call
    via ``crow_terminal_open`` (a UUID4 handle) and threads that handle
    through ``crow_terminal_exec`` / ``_read`` / ``_close``. Concurrent
    callers therefore get isolated PTYs instead of sharing a single
    multiplexer.

    The legacy ``terminal`` tool is still registered on the server for
    one-shot callers; this adapter no longer uses it.
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
        """Allocate a dedicated crow-mcp session and run *command* in it.

        Args:
            command: Command to run in the terminal session.
            columns: Terminal width in characters.
            rows: Terminal height in lines.
            **kwargs: Ignored (for compatibility with other adapters).

        Returns:
            Server-canonical session identifier (UUID string). Concurrent
            callers receive distinct identifiers and isolated PTYs.

        Raises:
            TerminalError: If the crow-mcp call fails.
        """
        handle = str(uuid.uuid4())
        try:
            open_result = await self.mcp.call_tool(
                "crow_terminal_open",
                {"handle": handle},
            )
            session_id = _canonical_session_id(open_result, handle)
            await self.mcp.call_tool(
                "crow_terminal_exec",
                {"session_id": session_id, "command": command},
            )
            self._sessions[session_id] = {
                "command": command,
                "columns": columns,
                "rows": rows,
            }
            logger.debug("crow-mcp session launched: %s", session_id)
            return session_id
        except Exception as e:
            raise TerminalError(
                message=f"crow-mcp: failed to launch session: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"command": command, "handle": handle},
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
                "crow_terminal_exec",
                {"session_id": session_id, "command": command},
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
            params: dict[str, Any] = {"session_id": session_id}
            if lines is not None:
                params["limit_lines"] = lines
            result = await self.mcp.call_tool(
                "crow_terminal_read",
                params,
            )
            return _extract_output(result)
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
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"crow-mcp: session {session_id} not found",
                details={"session_id": session_id},
            )
        try:
            await self.mcp.call_tool(
                "crow_terminal_close",
                {"session_id": session_id},
            )
        except Exception as e:
            logger.warning("crow-mcp: close_session failed (non-fatal): %s", e)
        finally:
            self._sessions.pop(session_id, None)
            logger.debug("crow-mcp session closed: %s", session_id)

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Return all locally tracked crow-mcp sessions.

        Returns:
            List of session information dictionaries.
        """
        return [{"id": sid, **meta} for sid, meta in self._sessions.items()]
