"""Terminal adapters for different terminal backends.

Available adapters:
- McpretentiousAdapter: MCP-based PTY terminal (requires mcpretentious MCP server)
- CrowTerminalAdapter: crow-mcp PTY terminal (requires crow-mcp MCP server)
- MockTerminalAdapter: Simulated terminal for testing

Example usage:
    >>> from mahavishnu.terminal.adapters import MockTerminalAdapter
    >>> adapter = MockTerminalAdapter()
    >>> session_id = await adapter.launch_session("qwen")
"""

from __future__ import annotations

from mahavishnu.terminal.adapters.base import TerminalAdapter
from mahavishnu.terminal.adapters.mock import MockTerminalAdapter

# Conditional imports for optional adapters
try:
    from mahavishnu.terminal.adapters.mcpretentious import (
        McpretentiousAdapter,
        SessionNotFoundError,
        TerminalError,
    )
except ImportError:
    McpretentiousAdapter: type[TerminalAdapter] | None = None
    SessionNotFoundError: type[BaseException] | None = None
    TerminalError: type[BaseException] | None = None

try:
    from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter
except ImportError:
    CrowTerminalAdapter: type[TerminalAdapter] | None = None


def get_available_adapters() -> list[str]:
    """Get list of available terminal adapter names.

    Returns:
        List of adapter names that are available on this system
    """
    adapters = ["mock"]  # Mock is always available

    if McpretentiousAdapter is not None:
        adapters.append("mcpretentious")

    if CrowTerminalAdapter is not None:
        adapters.append("crow")

    return adapters


def get_adapter_class(name: str) -> type[TerminalAdapter] | None:
    """Get adapter class by name.

    Args:
        name: Adapter name ('mock', 'mcpretentious', 'crow')

    Returns:
        Adapter class or None if not available
    """
    if name == "mock":
        return MockTerminalAdapter
    if name == "mcpretentious" and McpretentiousAdapter is not None:
        return McpretentiousAdapter
    elif name == "crow" and CrowTerminalAdapter is not None:
        return CrowTerminalAdapter
    return None


__all__ = [
    # Crow adapter (requires crow-mcp MCP server)
    "CrowTerminalAdapter",
    # Mcpretentious adapter (requires MCP server)
    "McpretentiousAdapter",
    # Mock adapter (always available)
    "MockTerminalAdapter",
    "SessionNotFoundError",
    # Base
    "TerminalAdapter",
    "TerminalError",
    "get_adapter_class",
    # Utility functions
    "get_available_adapters",
]
