"""FastMCP tool wrappers for the crow-mcp subprocess(es).

Two flavours live here:

Legacy ``terminal`` tool (Task 1): multiplexes every caller onto the
single crow-mcp subprocess spawned by the FastMCP lifespan. Kept for
backward compatibility with one-shot callers and CrowTerminalAdapter
pre-Task-3.

Per-session ``crow_terminal_*`` tools (Task 2): each caller passes an
explicit ``handle`` (== ``session_id``). ``acquire_session`` lazily
allocates a dedicated crow-mcp subprocess per handle, and the new
tools route to that subprocess through a per-handle ``asyncio.Lock``
to prevent JSON-RPC frame interleaving.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..terminal_proxy import (
    _locks,
    acquire_session,
    get_crow_session,
    get_crow_session_by_handle,
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


def register(server: FastMCP | StandardServer, settings: CrowSettings) -> None:
    """Register the ``terminal`` and ``crow_terminal_*`` tools.

    The legacy ``terminal`` tool is preserved unchanged. The four new
    ``crow_terminal_*`` tools accept an explicit ``handle`` and route
    every call to that handle's dedicated subprocess through the
    per-handle lock in ``mahavishnu.mcp.crow.terminal_proxy._locks``.
    Idempotent on re-registration (each call adds new closures to
    the same FastMCP tool manager).
    """
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
        # crow-mcp returns an mcp.types.CallToolResult; the FastMCP tool
        # contract here treats that as an opaque dict-shaped payload so
        # downstream MCP clients can serialize it themselves.
        return await session.call_tool("terminal", {"command": command})  # type: ignore[no-any-return]

    @deco()
    async def crow_terminal_open(handle: str) -> dict[str, str]:
        """Reserve a session handle and spawn a dedicated crow-mcp subprocess.

        Returns ``{"session_id": handle}``. Idempotent: re-opening an
        existing handle returns the same session.
        """
        await acquire_session(handle, settings)
        return {"session_id": handle}

    @deco()
    async def crow_terminal_exec(session_id: str, command: str) -> dict[str, Any]:
        """Run a command in the session's PTY.

        Acquires the session (idempotent) and serialises the call with
        the per-handle ``asyncio.Lock`` so concurrent callers cannot
        interleave JSON-RPC frames on the same subprocess.
        """
        await acquire_session(session_id, settings)
        state_proxy = _locks[session_id]
        async with state_proxy:
            session = get_crow_session_by_handle(session_id)
            return await session.call_tool(  # type: ignore[no-any-return]
                "terminal",
                {"command": command},
            )

    @deco()
    async def crow_terminal_read(session_id: str, limit_lines: int | None = None) -> dict[str, Any]:
        """Read recent output from the session's PTY.

        Acquires the session (idempotent) and serialises the call with
        the per-handle ``asyncio.Lock``. ``limit_lines`` is forwarded
        as ``{"limit_lines": N}`` to the underlying terminal tool only
        when provided.
        """
        await acquire_session(session_id, settings)
        state_proxy = _locks[session_id]
        async with state_proxy:
            session = get_crow_session_by_handle(session_id)
            params: dict[str, Any] = {"command": ""}
            if limit_lines is not None:
                params["limit_lines"] = limit_lines
            result = await session.call_tool(
                "terminal",
                params,
            )
            # The crow-mcp terminal tool returns either an
            # ``mcp.types.CallToolResult`` with a TextContent ``content``
            # list, or a plain mapping. Best-effort shape extraction;
            # any failure degrades to an empty string rather than
            # raising, because callers rely on ``output`` being a str.
            if hasattr(result, "content") and result.content:
                first = result.content[0]
                text = getattr(first, "text", None)
                if text:
                    return {"output": text}
            if isinstance(result, dict):
                return {"output": str(result.get("output", ""))}
            return {"output": ""}

    @deco()
    async def crow_terminal_close(session_id: str) -> dict[str, bool]:
        """Release the session and reap its subprocess.

        Idempotent: closing an unknown handle returns
        ``{"closed": False}`` rather than raising so callers can use
        this in ``finally`` blocks.
        """
        if session_id in _locks:
            await release_session(session_id)
            return {"closed": True}
        return {"closed": False}


__all__ = ["register"]
