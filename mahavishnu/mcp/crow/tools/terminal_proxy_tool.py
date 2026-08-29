"""FastMCP tool wrappers for the upstream ``crow-mcp`` PTY.

Both the legacy singleton (``terminal``) and the per-handle
(``crow_terminal_*``) tools route to a SHARED raw-JSON-RPC client that
wraps a single upstream ``crow-mcp`` subprocess (see
``raw_jsonrpc.py``). Per-handle state is just bookkeeping:

- ``acquire_session`` registers a handle in the per-handle dict + creates
  the per-handle ``asyncio.Lock``.
- ``crow_terminal_exec`` acquires the per-handle lock, sends a JSON-RPC
  ``tools/call terminal(command)`` to the shared client, captures the
  output via ``record_output`` so subsequent ``crow_terminal_read`` can
  return it.
- ``crow_terminal_read`` returns the last captured output for that
  handle without sending another upstream call.

Why per-handle locks at all if there is only one subprocess? Multiple
concurrent callers (e.g. several pool workers) on different handles MUST
not interleave their JSON-RPC frames on the shared stdin pipe.
The lock guarantees that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..terminal_proxy import (
    _locks,
    acquire_session,
    get_crow_session,
    get_crow_session_by_handle,
    read_output,
    record_output,
    release_session,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from mcp_common.profiles.standard import StandardServer

    from ..settings import CrowSettings


def _tool_decorator(server: FastMCP | StandardServer) -> Any:
    """Pick the tool decorator that routes through FastMCP when available.

    Mirrors the dual-target pattern used by ``file_tools``, ``rg_search``
    and the other tools in this package: a ``CrowServer`` exposes ``.fastmcp``
    whose ``tool`` decorator registers into FastMCP's tool manager; a plain
    ``StandardServer`` (used in tests) lacks that attribute, so we fall back
    to its own ``tool`` decorator.
    """
    fastmcp = getattr(server, "fastmcp", None)
    if fastmcp is not None:
        return fastmcp.tool
    return server.tool


def _extract_terminal_output(result: Any) -> str:
    """Coerce a raw JSON-RPC tool result into a terminal-output string.

    ``_RawJsonRpcClient.call_tool`` returns ``{"content": [...], "isError": ...}``
    shaped dicts (matching MCP SDK's ``CallToolResult.model_dump``). Best-effort
    shape extraction; any failure degrades to an empty string rather than
    raising, because callers rely on ``output`` being a str.
    """
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, dict):
                text = first.get("text")
                if text:
                    return str(text)
            elif hasattr(first, "text"):
                return str(getattr(first, "text", ""))
        if "output" in result:
            return str(result["output"])
        if "raw" in result:
            return str(result["raw"])
    return ""


def register(server: FastMCP | StandardServer, settings: CrowSettings) -> None:
    """Register the ``terminal`` and ``crow_terminal_*`` tools."""
    deco = _tool_decorator(server)

    @deco()
    async def terminal(command: str) -> dict[str, Any]:
        """Run a command in the persistent crow-mcp PTY session.

        Args:
            command: The shell command to execute.

        Returns:
            MCP tool result (typically ``{"output": ...}`` or similar).
        """
        session = get_crow_session()
        result = await session.call_tool("terminal", {"command": command})
        return {"output": _extract_terminal_output(result)}

    @deco()
    async def crow_terminal_open(handle: str) -> dict[str, str]:
        """Reserve a session handle and return its id.

        With the raw-JSON-RPC redesign there is no per-handle subprocess
        — every handle shares one upstream ``crow-mcp`` instance. The
        returned ``session_id`` is just the handle, used for serialisation
        of subsequent ``crow_terminal_exec`` calls on the shared client.

        Returns ``{"session_id": handle}``. Idempotent: re-opening an
        existing handle returns the same session_id.
        """
        await acquire_session(handle, settings)
        return {"session_id": handle}

    @deco()
    async def crow_terminal_exec(session_id: str, command: str) -> dict[str, Any]:
        """Run a command in the session's PTY.

        Acquires the session (idempotent) and serialises the call with
        the per-handle ``asyncio.Lock`` so concurrent callers cannot
        interleave JSON-RPC frames on the shared upstream subprocess.
        Stores the captured output so ``crow_terminal_read`` can return
        it without a second upstream call.
        """
        await acquire_session(session_id, settings)
        state_proxy = _locks[session_id]
        async with state_proxy:
            session = get_crow_session_by_handle(session_id)
            result = await session.call_tool(
                "terminal",
                {"command": command},
            )
            output = _extract_terminal_output(result)
            record_output(session_id, output)
            return {"output": output}

    @deco()
    async def crow_terminal_read(session_id: str, limit_lines: int | None = None) -> dict[str, Any]:
        """Read recent output from the session's PTY.

        Returns the most recently captured output (from the last
        ``crow_terminal_exec`` call) for this handle. ``limit_lines``
        truncates the returned output to the last ``N`` lines if
        provided. No upstream call is made — this is a pure read of the
        in-memory output buffer.
        """
        await acquire_session(session_id, settings)
        output = read_output(session_id)
        if limit_lines is not None and output:
            lines = output.splitlines()
            output = "\n".join(lines[-limit_lines:])
        return {"output": output}

    @deco()
    async def crow_terminal_close(session_id: str) -> dict[str, bool]:
        """Release the session and reap its per-handle bookkeeping.

        Idempotent: closing an unknown handle returns
        ``{"closed": False}`` rather than raising so callers can use
        this in ``finally`` blocks. The shared upstream subprocess is
        left running for other callers; only this handle's locks,
        output buffer, and session dict entry are dropped.
        """
        if session_id in _locks:
            await release_session(session_id)
            return {"closed": True}
        return {"closed": False}


__all__ = ["register"]
