"""Bodai Crow HTTP MCP server (Plan 1 Task 10).

Factory + lifespan for the HTTP transport. Subclasses
``mcp_common.profiles.standard.StandardServer`` so the rest of the
Bodai ecosystem (CLI, pools, ACP agents) can connect at
``http://localhost:8675/mcp`` and access the same file/web/terminal
tools that Claude Code uses via the stdio ``crow-mcp`` server.

Why a FastMCP-owned lifespan:
``StandardServer`` is a thin wrapper around FastMCP. The lifespan API
is a FastMCP concept (``lifespan=`` constructor parameter that accepts
an async context manager). Passing it via the FastMCP constructor is
the only documented integration point — ``set_lifespan`` does not
exist on ``StandardServer`` (v2 audit finding).

Tool registration:
``CrowServer`` carries a FastMCP instance. ``tools.register_all`` is
called with ``self`` so each ``register(server, settings)`` function
can dispatch decorators to either ``server.fastmcp.tool()`` or
``server.tool()`` (depending on what it is given).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastmcp import FastMCP
from mcp_common.profiles.standard import StandardServer

from mahavishnu.mcp.crow import tools
from mahavishnu.mcp.crow.client import close_http_client, init_http_client
from mahavishnu.mcp.crow.settings import CrowSettings
from mahavishnu.mcp.crow.terminal_proxy import (
    close_crow_stdio_client,
    init_crow_stdio_client,
)


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncGenerator[None, None]:
    """FastMCP lifespan: init shared HTTP client + crow stdio subprocess.

    Settings are stashed on the FastMCP instance via a private attribute
    (FastMCP has no public "dependencies" hook). The lifespan closure
    reads them back here without coupling to FastMCP internals.
    """
    settings: CrowSettings = getattr(server, "_crow_settings")
    await init_http_client(settings)
    await init_crow_stdio_client(settings)
    try:
        yield
    finally:
        # Reverse order: stdio first (subprocess teardown is best-effort),
        # HTTP client last.
        await close_crow_stdio_client()
        await close_http_client()


class CrowServer(StandardServer):
    """StandardServer subclass that owns a FastMCP transport with lifespan.

    ``StandardServer.run()`` is a stub — concrete transports are wired
    by subclasses. We attach a FastMCP instance whose ``lifespan=``
    constructor parameter accepts our async context manager.
    """

    def __init__(self, settings: CrowSettings) -> None:
        super().__init__(
            name="bodai-crow",
            description=(
                "Bodai-native file, web, and terminal tools over HTTP MCP"
            ),
            settings=settings,
        )
        self._mcp = FastMCP(
            name="bodai-crow",
            instructions=self.description,
            lifespan=_lifespan,
        )
        # Stash settings so the lifespan can reach them.
        self._mcp._crow_settings = settings
        tools.register_all(self, settings)

    @property
    def fastmcp(self) -> FastMCP:
        """The underlying FastMCP instance (for tests and advanced wiring)."""
        return self._mcp

    def run(self, **kwargs: Any) -> None:
        """Forward ``run`` to the FastMCP instance."""
        self._mcp.run(**kwargs)


def create_crow_server(settings: CrowSettings | None = None) -> CrowServer:
    """Construct the Bodai crow HTTP MCP server."""
    cfg = settings or CrowSettings()
    return CrowServer(cfg)


__all__ = ["CrowServer", "create_crow_server", "_lifespan"]
