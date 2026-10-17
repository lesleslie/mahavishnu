"""crow-mcp one-shot ``terminal`` adapter for terminal management.

The installed ``crow-mcp`` server (0.1.x) exposes the one-shot
``terminal`` tool (each call runs a fresh bash process — cwd, env,
and venv do NOT persist between calls; chain with ``&&`` or ``;``).
The server does NOT yet expose the per-session ``crow_terminal_open``
/ ``exec`` / ``read`` / ``close`` family this adapter was originally
written against. This module keeps the ``TerminalAdapter`` session-
shaped interface stable (so callers don't churn) by wrapping the
stateless ``terminal`` tool in a local per-session output cache.
"""

from __future__ import annotations

from typing import Any
import uuid

from oneiric.core.logging import get_logger

from mahavishnu.core.errors import ErrorCode

from ..adapters.base import SessionNotFoundError, TerminalAdapter, TerminalError

logger = get_logger(__name__)


def _extract_output(result: Any) -> str:
    """Pull the output text out of an MCP ``tools/call`` result.

    crow-mcp's ``terminal`` tool returns the MCP-typed
    ``CallToolResult`` shape::

        {"content": [{"type": "text", "text": "..."}], "isError": false}

    The test doubles that hand us a plain ``{"output": "..."}`` dict
    also work via the same accessor. Returns the empty string for any
    shape we can't read.
    """
    if isinstance(result, dict):
        out = result.get("output")
        if isinstance(out, str):
            return out
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text")
                if isinstance(text, str):
                    return text
    content = getattr(result, "content", None)
    if content:
        first = content[0]
        text = getattr(first, "text", None)
        if text:
            return str(text)
    return ""


class CrowTerminalAdapter(TerminalAdapter):
    """Terminal adapter that wraps crow-mcp's one-shot ``terminal`` tool.

    Each call to ``launch_session`` / ``send_command`` invokes the
    ``terminal`` tool (a fresh ``bash -c '<command>'`` on the server).
    The adapter keeps the ``TerminalAdapter`` session-shaped ABC stable
    by maintaining a local per-session cache that stores the most
    recent output for each synthetic session_id; ``capture_output``
    reads from the cache, ``close_session`` clears it.

    The server's behaviour of "each call starts a fresh shell" is
    documented at the tool level — the adapter doesn't try to preserve
    cwd / env / venv between calls. Callers that need a single command
    to span multiple lines of work should chain with ``&&`` or ``;``
    at the call site.
    """

    def __init__(self, mcp_client: Any) -> None:
        self.mcp = mcp_client
        # session_id (synthetic) → {"output": <str>, "command": <str>}
        self._sessions: dict[str, dict[str, str]] = {}

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
        """Allocate a synthetic session id and run *command* in a fresh shell.

        The server runs ``bash -c '<command>'`` (or its one-shot
        equivalent) per call. The returned session_id is local —
        there is no server-side persistent shell to attach to.

        Args:
            command: Command to run in the terminal session.
            columns: Ignored (no PTY dimensions on the one-shot tool).
            rows: Ignored (no PTY dimensions on the one-shot tool).
            **kwargs: Ignored.

        Returns:
            Synthetic session identifier (UUID4 string). Distinct per
            call so concurrent callers don't see each other's cached
            output.

        Raises:
            TerminalError: If the crow-mcp call fails.
        """
        handle = str(uuid.uuid4())
        try:
            result = await self.mcp.call_tool(
                "terminal",
                {"command": command},
            )
        except (
            Exception
        ) as e:  # terminal adapter — broad catch to wrap any crow-mcp failure into TerminalError
            raise TerminalError(
                message=f"crow-mcp: failed to launch session: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"command": command, "handle": handle},
            ) from e
        output = _extract_output(result)
        self._sessions[handle] = {"output": output, "command": command}
        logger.debug("crow-mcp one-shot session launched: %s", handle)
        return handle

    async def send_command(self, session_id: str, command: str) -> None:
        """Run *command* in a fresh shell and update the session cache.

        Because crow-mcp's ``terminal`` is one-shot, this isn't a
        "send into existing session" — it's a fresh invocation that
        overwrites the cached output for the synthetic session_id.

        Args:
            session_id: Synthetic session identifier from
                ``launch_session``.
            command: Command string to run.

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
                {"command": command},
            )
        except (
            Exception
        ) as e:  # terminal adapter — broad catch to wrap any crow-mcp failure into TerminalError
            raise TerminalError(
                message=f"crow-mcp: failed to send command: {e}",
                error_code=ErrorCode.CROW_MCP_UNAVAILABLE,
                details={"session_id": session_id, "command": command},
            ) from e
        self._sessions[session_id] = {
            "output": _extract_output(result),
            "command": command,
        }

    async def capture_output(
        self,
        session_id: str,
        lines: int | None = None,
    ) -> str:
        """Return the most recently cached output for *session_id*.

        The ``terminal`` tool runs synchronously and returns its
        output inline; there is no async read-back. ``capture_output``
        here is the ABC's hook for the tmux/crow-session adapters that
        do have a long-lived PTY — for the one-shot ``terminal`` tool
        it's a cache lookup.

        Args:
            session_id: Synthetic session identifier.
            lines: Ignored (caller already has the full output).

        Returns:
            Cached output string for the session.

        Raises:
            SessionNotFoundError: If session_id is not tracked locally.
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"crow-mcp: session {session_id} not found",
                details={"session_id": session_id},
            )
        return self._sessions[session_id].get("output", "")

    async def close_session(self, session_id: str) -> None:
        """Clear the local session cache for *session_id*.

        The server has no per-session resource to release (one-shot
        tool spawns a fresh shell per call and tears it down
        synchronously). We just drop the cached output.

        Args:
            session_id: Synthetic session identifier to close.

        Raises:
            SessionNotFoundError: If session_id is not tracked locally.
        """
        if session_id not in self._sessions:
            raise SessionNotFoundError(
                message=f"crow-mcp: session {session_id} not found",
                details={"session_id": session_id},
            )
        self._sessions.pop(session_id, None)
        logger.debug("crow-mcp one-shot session closed: %s", session_id)

    async def list_sessions(self) -> list[dict[str, Any]]:
        """Return all locally tracked crow-mcp sessions.

        Returns:
            List of session information dictionaries.
        """
        return [{"id": sid, **meta} for sid, meta in self._sessions.items()]
