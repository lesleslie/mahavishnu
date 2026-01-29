"""Terminal management module for Mahavishnu.

This module provides multi-terminal session management with support for
different terminal backends (mcpretentious, iTerm2, etc.).

Example:
    >>> from mahavishnu.terminal import TerminalManager
    >>> manager = TerminalManager(adapter)
    >>> session_ids = await manager.launch_sessions("qwen", count=3)
    >>> await manager.send_command(session_ids[0], "hello")
    >>> output = await manager.capture_output(session_ids[0])
"""

from mahavishnu.terminal.adapters.base import TerminalAdapter
from mahavishnu.terminal.adapters.iterm2 import ITERM2_AVAILABLE, ITerm2Adapter
from mahavishnu.terminal.adapters.mcpretentious import McpretentiousAdapter
from mahavishnu.terminal.manager import TerminalManager
from mahavishnu.terminal.session import TerminalSession

__all__ = [
    "TerminalManager",
    "TerminalSession",
    "TerminalAdapter",
    "McpretentiousAdapter",
    "ITerm2Adapter",
    "ITERM2_AVAILABLE",
]
