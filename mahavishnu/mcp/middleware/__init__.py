"""FastMCP middleware for Mahavishnu's MCP server.

Each submodule is a :class:`fastmcp.server.middleware.Middleware` subclass
that hooks into the FastMCP request lifecycle to wire cross-cutting concerns
(auth, telemetry, audit) into the tool dispatch path.
"""

from __future__ import annotations
