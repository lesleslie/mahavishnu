"""Terminal adapters for different terminal backends.

Available adapters:
- CrowTerminalAdapter: crow-mcp PTY terminal (requires crow-mcp MCP server)
- MockTerminalAdapter: Simulated terminal for testing

The mcpretentious adapter was removed 2026-08-12 (see
``docs/followups/2026-08-12-mcpretentious-removed.md``). The default
``adapter_preference`` is now ``tmux``; ``crow`` remains opt-in via
``adapter_preference: "crow"`` + ``crow_enabled: true``.

Example usage:
    >>> from mahavishnu.terminal.adapters import MockTerminalAdapter
    >>> adapter = MockTerminalAdapter()
    >>> session_id = await adapter.launch_session("qwen")
"""

from __future__ import annotations

from mahavishnu.terminal.adapters.base import (
    SessionNotFoundError,
    TerminalAdapter,
    TerminalError,
)
from mahavishnu.terminal.adapters.mock import MockTerminalAdapter

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

    if CrowTerminalAdapter is not None:
        adapters.append("crow")

    return adapters


def get_adapter_class(name: str) -> type[TerminalAdapter] | None:
    """Get adapter class by name.

    Args:
        name: Adapter name ('mock', 'crow')

    Returns:
        Adapter class or None if not available
    """
    if name == "mock":
        return MockTerminalAdapter
    if name == "crow" and CrowTerminalAdapter is not None:
        return CrowTerminalAdapter
    return None


__all__ = [
    # Crow adapter (requires crow-mcp MCP server)
    "CrowTerminalAdapter",
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
