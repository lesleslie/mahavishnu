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

__all__ = [
    "TerminalManager",
    "TerminalSession",
    "TerminalAdapter",
    "McpretentiousAdapter",
    "ITerm2Adapter",
    "ITERM2_AVAILABLE",
]

# Mapping of export name -> (module_path, attribute_name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "TerminalAdapter": ("mahavishnu.terminal.adapters.base", "TerminalAdapter"),
    "ITerm2Adapter": ("mahavishnu.terminal.adapters.iterm2", "ITerm2Adapter"),
    "ITERM2_AVAILABLE": ("mahavishnu.terminal.adapters.iterm2", "ITERM2_AVAILABLE"),
    "McpretentiousAdapter": ("mahavishnu.terminal.adapters.mcpretentious", "McpretentiousAdapter"),
    "TerminalManager": ("mahavishnu.terminal.manager", "TerminalManager"),
    "TerminalSession": ("mahavishnu.terminal.session", "TerminalSession"),
}


def __getattr__(name: str):
    """Lazy import to avoid heavy initialization on package import."""
    if entry := _LAZY_IMPORTS.get(name):
        from importlib import import_module

        module = import_module(entry[0])
        return getattr(module, entry[1])
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
