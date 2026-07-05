"""stdio proxy to a persistent ``crow-mcp`` subprocess.

The crow HTTP server (Task 10 of Plan 1) uses FastMCP for its transport
and ``mcp.client.stdio.stdio_client`` to multiplex a long-running
``crow-mcp`` subprocess. This module owns that subprocess lifecycle.

Lifecycle:

- ``init_crow_stdio_client(settings)`` — start the subprocess and enter
  the stdio + ClientSession contexts through an ``AsyncExitStack``. The
  stack is rolled back if ``session.initialize()`` raises so we never
  leak a half-started subprocess. The full ``_CrowState`` dataclass is
  assigned atomically AFTER initialization succeeds.
- ``close_crow_stdio_client()`` — close the exit stack and clear state.
  Idempotent: safe to call when no session is active.
- ``get_crow_session()`` — accessor that raises ``RuntimeError`` if no
  session is live. Used by ``terminal_proxy_tool.py``.

The dataclass + atomic-publish pattern is the "heavy lifting" from
Plan Task 9 — implemented here in Task 4 because the tests for this
task depend on ``_state`` being a single assignable object.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

if TYPE_CHECKING:
    from mahavishnu.mcp.crow.settings import CrowSettings


@dataclass
class _CrowState:
    """Atomic state for the crow stdio client.

    Single dataclass assignment prevents the partial-publish race where
    concurrent readers see a session whose AsyncExitStack has not yet
    been assigned.
    """

    session: ClientSession
    exit_stack: AsyncExitStack


_state: _CrowState | None = None
_crow_lock = asyncio.Lock()


async def init_crow_stdio_client(settings: CrowSettings) -> None:
    """Start the crow-mcp subprocess and enter stdio + ClientSession."""
    global _state
    async with _crow_lock:
        if _state is not None:
            raise RuntimeError(
                "crow stdio client already initialized; call close_crow_stdio_client first"
            )
        stack = AsyncExitStack()
        try:
            params = StdioServerParameters(command=settings.crow_mcp_command, args=[])
            _read, _write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(_read, _write))
            await session.initialize()
        except BaseException:
            # Any failure during init: roll back the partially-entered
            # contexts so the subprocess is not leaked.
            await stack.aclose()
            raise
        # Atomic publish: both fields assigned together.
        _state = _CrowState(session=session, exit_stack=stack)


async def close_crow_stdio_client() -> None:
    """Close the crow stdio client. Idempotent."""
    global _state
    state = _state
    _state = None
    if state is not None:
        await state.exit_stack.aclose()


def get_crow_session() -> ClientSession:
    """Return the live crow ClientSession. Raises if not initialized."""
    if _state is None:
        raise RuntimeError("crow stdio client not initialized — server lifespan not running")
    return _state.session


__all__ = ["init_crow_stdio_client", "close_crow_stdio_client", "get_crow_session"]
