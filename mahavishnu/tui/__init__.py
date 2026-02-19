"""TUI (Terminal User Interface) components for Mahavishnu.

This package provides:
- Command palette (Ctrl+K)
- Interactive prompts
- Progress displays
"""

from mahavishnu.tui.command_palette import CommandPalette, Command, CommandCategory

__all__ = ["CommandPalette", "Command", "CommandCategory"]
