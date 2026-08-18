"""Public entry point for building the Mahavishnu MCP server.

Wires the W0 ``apply_tool_profile()`` helper from ``mcp-common`` to the
mahavishnu-specific ``REGISTRATION_MAP`` and ``PROFILE_REGISTRATIONS``.
Replaces the legacy in-process ``register_profile_tools`` dispatch so the
profile gating contract lives in one place (mcp-common).
"""

from __future__ import annotations

from .server_core import FastMCPServer


async def build_mahavishnu_mcp_server() -> FastMCPServer:
    """Construct + apply tool profile to a Mahavishnu FastMCP server.

    The returned server has its FastMCP server (``.server``) populated with
    every tool listed at the active profile. Callers MUST NOT also call
    ``start()`` unless they want to bind an HTTP socket -- this entry point
    is intended for in-process tooling (tests, CLI checks, embedded usage).
    """
    server = FastMCPServer()
    # FastMCPServer.__init__ already calls _register_tools() (core inline
    # tools). The W0 helper (via FastMCPServer.apply_tool_profile) adds the
    # profile-gated + always-on groups.
    await server.apply_tool_profile()
    return server


__all__ = ["FastMCPServer", "build_mahavishnu_mcp_server"]
