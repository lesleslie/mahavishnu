"""Output Formatter for Mahavishnu.

Rich console output formatting with multiple formats:
- Table formatting with colors and styles
- JSON, YAML, Markdown output formats
- Progress and status indicators
- Verbosity-aware output

Usage:
    from mahavishnu.core.output_formatter import OutputFormatter, OutputFormat

    formatter = OutputFormatter(format=OutputFormat.TABLE)

    # Format tasks as table
    formatter.format_task_list(tasks)

    # Print with colors
    formatter.print_success("Task completed!")
    formatter.print_error("Task failed!")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class OutputFormat(str, Enum):
    """Output format types."""

    TABLE = "table"
    JSON = "json"
    YAML = "yaml"
    MARKDOWN = "markdown"
    PLAIN = "plain"


class OutputTheme(str, Enum):
    """Output color theme."""

    DARK = "dark"
    LIGHT = "light"
    MONOCHROME = "monochrome"


class OutputLevel(str, Enum):
    """Output verbosity level."""

    QUIET = "quiet"  # Only errors
    NORMAL = "normal"  # Standard output
    VERBOSE = "verbose"  # Extra details
    DEBUG = "debug"  # Everything


@dataclass
class TableColumn:
    """A column in a table.

    Attributes:
        name: Display name for column header
        key: Key to extract from data dict
        width: Optional fixed width
        align: Text alignment (left, right, center)
        format_fn: Optional formatting function
        hide_if_empty: Hide column if all values are empty
    """

    name: str
    key: str
    width: int | None = None
    align: str = "left"
    format_fn: Callable[[Any], str] | None = None
    hide_if_empty: bool = False

    def get_value(self, row: dict[str, Any]) -> str:
        """Get formatted value from row."""
        value = row.get(self.key, "")

        if self.format_fn:
            return self.format_fn(value)

        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")

        return str(value) if value is not None else ""


@dataclass
class TableConfig:
    """Configuration for table output.

    Attributes:
        columns: List of table columns
        title: Optional table title
        show_header: Show column headers
        show_border: Show table border
        show_row_numbers: Show row numbers
        expand: Expand table to full width
    """

    columns: list[TableColumn]
    title: str | None = None
    show_header: bool = True
    show_border: bool = True
    show_row_numbers: bool = False
    expand: bool = False


class OutputFormatter:
    """Rich output formatter for console and files.

    Features:
    - Multiple output formats (table, json, yaml, markdown, plain)
    - Color themes (dark, light, monochrome)
    - Verbosity levels (quiet, normal, verbose, debug)
    - Rich console integration
    - Status and priority indicators

    Example:
        formatter = OutputFormatter(format=OutputFormat.JSON)

        # Print formatted data
        formatter.format_data(tasks)

        # Print with style
        formatter.print_success("Done!")
        formatter.print_error("Failed!")
    """

    # Status color mappings
    STATUS_COLORS = {
        "completed": "green",
        "done": "green",
        "success": "green",
        "in_progress": "yellow",
        "running": "yellow",
        "pending": "blue",
        "waiting": "blue",
        "failed": "red",
        "error": "red",
        "cancelled": "dim",
        "blocked": "magenta",
    }

    # Priority indicators
    PRIORITY_INDICATORS = {
        "critical": "!!!",
        "high": "!!",
        "medium": "!",
        "low": "",
        "normal": "",
    }

    def __init__(
        self,
        console: Any = None,  # Rich Console
        format: OutputFormat = OutputFormat.TABLE,
        theme: OutputTheme = OutputTheme.DARK,
        level: OutputLevel = OutputLevel.NORMAL,
        width: int = 80,
    ) -> None:
        """Initialize the output formatter.

        Args:
            console: Optional Rich Console instance
            format: Output format
            theme: Color theme
            level: Verbosity level
            width: Output width for wrapping
        """
        self._console = console
        self.format = format
        self.theme = theme
        self.level = level
        self.width = width

        # Try to import Rich if no console provided
        if self._console is None:
            try:
                from rich.console import Console
                self._console = Console()
            except ImportError:
                self._console = None

    def is_quiet(self) -> bool:
        """Check if output level is quiet."""
        return self.level == OutputLevel.QUIET

    def is_verbose(self) -> bool:
        """Check if output level is verbose or higher."""
        return self.level in (OutputLevel.VERBOSE, OutputLevel.DEBUG)

    def is_debug(self) -> bool:
        """Check if output level is debug."""
        return self.level == OutputLevel.DEBUG

    def get_status_color(self, status: str) -> str:
        """Get color for status value."""
        return self.STATUS_COLORS.get(status.lower(), "white")

    def get_priority_indicator(self, priority: str) -> str:
        """Get indicator for priority level."""
        return self.PRIORITY_INDICATORS.get(priority.lower(), "")

    def format_duration(self, seconds: float) -> str:
        """Format duration in human-readable form.

        Args:
            seconds: Duration in seconds

        Returns:
            Formatted duration string
        """
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    def format_timestamp(self, ts: datetime) -> str:
        """Format timestamp for display.

        Args:
            ts: Datetime to format

        Returns:
            Formatted timestamp string
        """
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        diff = now - ts

        if diff.days == 0:
            if diff.seconds < 3600:
                return f"{diff.seconds // 60}m ago"
            else:
                return f"{diff.seconds // 3600}h ago"
        elif diff.days == 1:
            return "yesterday"
        elif diff.days < 7:
            return f"{diff.days}d ago"
        else:
            return ts.strftime("%Y-%m-%d")

    def truncate_text(self, text: str, max_length: int = 50) -> str:
        """Truncate text to max length.

        Args:
            text: Text to truncate
            max_length: Maximum length

        Returns:
            Truncated text with ellipsis if needed
        """
        if len(text) <= max_length:
            return text
        return text[:max_length - 3] + "..."

    def wrap_text(self, text: str, width: int | None = None) -> str:
        """Wrap text to specified width.

        Args:
            text: Text to wrap
            width: Width to wrap to (uses self.width if None)

        Returns:
            Wrapped text
        """
        width = width or self.width

        if len(text) <= width:
            return text

        words = text.split()
        lines: list[str] = []
        current_line = ""

        for word in words:
            if len(current_line) + len(word) + 1 <= width:
                current_line += (" " if current_line else "") + word
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return "\n".join(lines)

    def format_data(self, data: Any) -> str:
        """Format data according to current format.

        Args:
            data: Data to format

        Returns:
            Formatted string
        """
        if self.format == OutputFormat.JSON:
            return self._format_json(data)
        elif self.format == OutputFormat.YAML:
            return self._format_yaml(data)
        elif self.format == OutputFormat.MARKDOWN:
            return self._format_markdown(data)
        elif self.format == OutputFormat.PLAIN:
            return self._format_plain(data)
        else:
            return str(data)

    def _format_json(self, data: Any) -> str:
        """Format as JSON."""
        def json_serial(obj: Any) -> Any:
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")

        return json.dumps(data, indent=2, default=json_serial)

    def _format_yaml(self, data: Any) -> str:
        """Format as YAML (simple implementation)."""
        try:
            import yaml
            return yaml.dump(data, default_flow_style=False)
        except ImportError:
            # Fallback to simple YAML-like format
            return self._simple_yaml(data)

    def _simple_yaml(self, data: Any, indent: int = 0) -> str:
        """Simple YAML formatting without pyyaml."""
        lines: list[str] = []
        prefix = "  " * indent

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    lines.append(f"{prefix}-")
                    for key, value in item.items():
                        lines.append(f"{prefix}  {key}: {value}")
                else:
                    lines.append(f"{prefix}- {item}")
        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    lines.append(f"{prefix}{key}:")
                    lines.append(self._simple_yaml(value, indent + 1))
                else:
                    lines.append(f"{prefix}{key}: {value}")
        else:
            lines.append(f"{prefix}{data}")

        return "\n".join(lines)

    def _format_markdown(self, data: Any) -> str:
        """Format as Markdown."""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            # Format as table
            headers = list(data[0].keys())
            lines = [
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join(["---"] * len(headers)) + " |",
            ]
            for row in data:
                values = [str(row.get(h, "")) for h in headers]
                lines.append("| " + " | ".join(values) + " |")
            return "\n".join(lines)
        return str(data)

    def _format_plain(self, data: Any) -> str:
        """Format as plain text."""
        if isinstance(data, list):
            return "\n".join(str(item) for item in data)
        return str(data)

    def format_table(
        self,
        data: list[dict[str, Any]],
        config: TableConfig,
    ) -> str:
        """Format data as a table.

        Args:
            data: List of row dictionaries
            config: Table configuration

        Returns:
            Formatted table string
        """
        if not data:
            return "No data to display"

        if self.format == OutputFormat.JSON:
            return self._format_json(data)
        elif self.format == OutputFormat.YAML:
            return self._format_yaml(data)
        elif self.format == OutputFormat.MARKDOWN:
            return self._format_markdown_table(data, config)
        elif self.format == OutputFormat.PLAIN:
            return self._format_plain_table(data, config)

        # Rich table output
        if self._console:
            return self._format_rich_table(data, config)

        return self._format_plain_table(data, config)

    def _format_markdown_table(
        self,
        data: list[dict[str, Any]],
        config: TableConfig,
    ) -> str:
        """Format as Markdown table."""
        lines: list[str] = []

        if config.title:
            lines.append(f"## {config.title}\n")

        # Header
        headers = [col.name for col in config.columns]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        # Rows
        for row in data:
            values = [col.get_value(row) for col in config.columns]
            lines.append("| " + " | ".join(values) + " |")

        return "\n".join(lines)

    def _format_plain_table(
        self,
        data: list[dict[str, Any]],
        config: TableConfig,
    ) -> str:
        """Format as plain text table."""
        lines: list[str] = []

        if config.title:
            lines.append(config.title)
            lines.append("-" * len(config.title))

        # Header
        if config.show_header:
            headers = [col.name for col in config.columns]
            lines.append("  ".join(headers))
            lines.append("  ".join("-" * len(h) for h in headers))

        # Rows
        for i, row in enumerate(data):
            values = [col.get_value(row) for col in config.columns]
            prefix = f"{i + 1}. " if config.show_row_numbers else ""
            lines.append(prefix + "  ".join(values))

        return "\n".join(lines)

    def _format_rich_table(
        self,
        data: list[dict[str, Any]],
        config: TableConfig,
    ) -> str:
        """Format as Rich table."""
        try:
            from rich.table import Table
            from rich.console import Console
            from io import StringIO

            table = Table(
                title=config.title,
                show_header=config.show_header,
                show_lines=config.show_border,
                expand=config.expand,
            )

            # Add columns
            for col in config.columns:
                table.add_column(
                    col.name,
                    width=col.width,
                    justify=col.align,
                )

            # Add rows
            for row in data:
                values = [col.get_value(row) for col in config.columns]
                table.add_row(*values)

            # Render to string
            string_io = StringIO()
            console = Console(file=string_io, width=self.width)
            console.print(table)
            return string_io.getvalue()

        except ImportError:
            return self._format_plain_table(data, config)

    def format_task_list(self, tasks: list[dict[str, Any]]) -> str:
        """Format a list of tasks.

        Args:
            tasks: List of task dictionaries

        Returns:
            Formatted task list
        """
        config = TableConfig(
            title="Tasks",
            columns=[
                TableColumn("ID", "id", width=12),
                TableColumn("Title", "title", width=40, format_fn=lambda x: self.truncate_text(str(x), 40)),
                TableColumn("Status", "status", width=12),
                TableColumn("Priority", "priority", width=8),
            ],
        )

        return self.format_table(tasks, config)

    def format_task_detail(self, task: dict[str, Any]) -> str:
        """Format a single task's details.

        Args:
            task: Task dictionary

        Returns:
            Formatted task details
        """
        lines: list[str] = []

        lines.append(f"Task: {task.get('id', 'Unknown')}")
        lines.append("=" * 40)
        lines.append(f"Title: {task.get('title', 'N/A')}")
        lines.append(f"Status: {task.get('status', 'N/A')}")
        lines.append(f"Priority: {task.get('priority', 'N/A')}")

        if "description" in task:
            lines.append(f"\nDescription:\n{self.wrap_text(task['description'])}")

        if "metadata" in task:
            lines.append(f"\nMetadata: {self._format_json(task['metadata'])}")

        return "\n".join(lines)

    def print(self, message: str, **kwargs: Any) -> None:
        """Print a message."""
        if self._console:
            self._console.print(message, **kwargs)
        else:
            print(message)

    def print_success(self, message: str) -> None:
        """Print success message."""
        if self.is_quiet():
            return
        self.print(f"[green]✓[/green] {message}")

    def print_error(self, message: str) -> None:
        """Print error message."""
        self.print(f"[red]✗[/red] {message}")

    def print_warning(self, message: str) -> None:
        """Print warning message."""
        if self.is_quiet():
            return
        self.print(f"[yellow]![/yellow] {message}")

    def print_info(self, message: str) -> None:
        """Print info message."""
        if self.is_quiet():
            return
        self.print(f"[blue]ℹ[/blue] {message}")

    def print_debug(self, message: str) -> None:
        """Print debug message."""
        if not self.is_debug():
            return
        self.print(f"[dim]DEBUG: {message}[/dim]")

    def print_header(self, title: str) -> None:
        """Print a header."""
        if self.is_quiet():
            return
        self.print(f"\n[bold]{title}[/bold]")
        self.print("=" * len(title))

    def print_panel(self, content: str, title: str | None = None) -> None:
        """Print content in a panel."""
        if self.is_quiet():
            return

        if self._console:
            try:
                from rich.panel import Panel
                self._console.print(Panel(content, title=title))
                return
            except ImportError:
                pass

        # Fallback
        if title:
            self.print(f"\n┌─ {title} ─{'─' * (40 - len(title))}")
        else:
            self.print("┌" + "─" * 44)
        for line in content.split("\n"):
            self.print(f"│ {line}")
        self.print("└" + "─" * 44)

    def print_rule(self, title: str = "") -> None:
        """Print a horizontal rule."""
        if self.is_quiet():
            return

        if self._console:
            try:
                from rich.rule import Rule
                self._console.print(Rule(title))
                return
            except ImportError:
                pass

        # Fallback
        if title:
            self.print(f"── {title} {'─' * (40 - len(title))}")
        else:
            self.print("─" * 50)

    def print_columns(self, items: list[str], columns: int = 2) -> None:
        """Print items in columns."""
        if self.is_quiet():
            return

        col_width = self.width // columns

        rows: list[list[str]] = []
        current_row: list[str] = []

        for item in items:
            current_row.append(item.ljust(col_width))
            if len(current_row) >= columns:
                rows.append(current_row)
                current_row = []

        if current_row:
            rows.append(current_row)

        for row in rows:
            self.print("".join(row))

    def print_tree(self, data: dict[str, Any], indent: int = 0) -> None:
        """Print a tree structure.

        Args:
            data: Tree data with 'label' and 'children' keys
            indent: Current indent level
        """
        if self.is_quiet():
            return

        prefix = "  " * indent
        label = data.get("label", "")

        children = data.get("children", [])
        for i, child in enumerate(children):
            is_last = i == len(children) - 1
            connector = "└── " if is_last else "├── "
            self.print(f"{prefix}{connector}{child.get('label', '')}")
            if child.get("children"):
                self.print_tree(child, indent + 1)


__all__ = [
    "OutputFormatter",
    "OutputFormat",
    "OutputTheme",
    "OutputLevel",
    "TableColumn",
    "TableConfig",
]
