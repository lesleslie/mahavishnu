"""TUI (Terminal User Interface) components for Mahavishnu.

This package provides:
- Command palette (Ctrl+K)
- Interactive prompts
- Progress displays
- Fallback Rich formatter for non-Textual environments
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

from oneiric.core.logging import get_logger

if TYPE_CHECKING:
    from typing import Any
from rich.console import Console
from rich.table import Table

from mahavishnu.tui.command_palette import Command, CommandCategory, CommandPalette

logger = get_logger(__name__)

# Evaluated once at module load — patch this bool in tests, not find_spec.
TUI_AVAILABLE: bool = importlib.util.find_spec("textual") is not None

_console: Console | None = None


def get_console() -> Console:
    """Return a shared Rich Console instance."""
    global _console
    if _console is None:
        _console = Console()
    return _console


class FallbackRichFormatter:
    """Plain Rich-formatted output for environments without Textual."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or get_console()

    def format_dict(self, data: dict[str, Any], title: str = "") -> None:
        """Render a dict as a two-column Rich table."""
        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("Key", style="bold")
        table.add_column("Value")
        for key, value in data.items():
            table.add_row(str(key), str(value))
        self._console.print(table)

    def format_list(
        self, items: list[dict[str, Any]], columns: list[str], title: str = ""
    ) -> None:
        """Render a list of dicts as a Rich table with specified columns."""
        table = Table(title=title, show_header=True, header_style="bold cyan")
        for col in columns:
            table.add_column(col.title(), style="bold" if col == "name" else "")
        for item in items:
            table.add_row(*[str(item.get(col, "—")) for col in columns])
        self._console.print(table)


__all__ = [
    "CommandPalette",
    "Command",
    "CommandCategory",
    "TUI_AVAILABLE",
    "get_console",
    "FallbackRichFormatter",
]
