"""MCP Server module for Mahavishnu."""

import asyncio

from .server_core import run_server


class MCPServer:
    """MCP Server to expose tools via mcp-common."""

    def __init__(self, tools=None):
        """
        Initialize the MCP server.

        Args:
            tools: List of tools to expose via MCP (deprecated - using FastMCP tools now)
        """
        # The tools parameter is kept for backward compatibility but not used
        # The new implementation uses FastMCP tools registered in server_core
        pass

    def run(self, host: str = "127.0.0.1", port: int = 3000):
        """
        Run the MCP server.

        Args:
            host: Host address to bind to
            port: Port to listen on
        """
        # Run the new FastMCP server implementation
        asyncio.run(run_server())
