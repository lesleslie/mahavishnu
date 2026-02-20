"""Task Dashboard - Textual-based TUI for task management.

Provides a rich terminal user interface for:
- Task list with filtering and selection
- Task detail view
- Keyboard navigation
- Theme support
- Help system

Usage:
    from mahavishnu.core.task_dashboard import TaskDashboard

    dashboard = TaskDashboard(task_store=task_store)
    await dashboard.load_tasks()
    dashboard.run()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class DashboardState(str, Enum):
    """State of the dashboard."""

    NORMAL = "normal"
    INSERT = "insert"
    SEARCH = "search"
    HELP = "help"


@dataclass
class DashboardTheme:
    """Theme for dashboard display.

    Attributes:
        name: Theme name
        background: Background color (hex)
        foreground: Foreground color (hex)
        accent: Accent color (hex)
        error: Error color (hex)
        warning: Warning color (hex)
        success: Success color (hex)
    """

    name: str
    background: str = "#1a1a2e"
    foreground: str = "#eaeaea"
    accent: str = "#00d4ff"
    error: str = "#ff6b6b"
    warning: str = "#ffd93d"
    success: str = "#6bcb77"


@dataclass
class KeyBinding:
    """A key binding for the dashboard.

    Attributes:
        key: Key combination (e.g., "ctrl+n", "up", "q")
        action: Action to perform
        description: Human-readable description
        modes: Modes where this binding is active (empty = all modes)
    """

    key: str
    action: str
    description: str
    modes: list[DashboardState] = field(default_factory=list)


class TaskListPanel:
    """Panel displaying a list of tasks.

    Features:
    - Scrollable task list
    - Selection highlighting
    - Task filtering
    - Status indicators
    """

    def __init__(self, title: str = "Tasks") -> None:
        """Initialize task list panel.

        Args:
            title: Panel title
        """
        self.title = title
        self.tasks: list[dict[str, Any]] = []
        self.filtered_tasks: list[dict[str, Any]] = []
        self.selected_index = 0
        self._filter_query = ""

    def set_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Set the task list.

        Args:
            tasks: List of task dictionaries
        """
        self.tasks = tasks
        self.filtered_tasks = tasks.copy()
        self.selected_index = 0

    def get_selected_task(self) -> dict[str, Any] | None:
        """Get the currently selected task.

        Returns:
            Selected task dictionary or None if no selection
        """
        if 0 <= self.selected_index < len(self.filtered_tasks):
            return self.filtered_tasks[self.selected_index]
        return None

    def move_selection(self, delta: int) -> None:
        """Move selection by delta positions.

        Args:
            delta: Number of positions to move (negative = up)
        """
        if not self.filtered_tasks:
            self.selected_index = 0
            return

        new_index = self.selected_index + delta
        # Clamp to valid range
        self.selected_index = max(0, min(new_index, len(self.filtered_tasks) - 1))

    def filter_tasks(self, query: str) -> None:
        """Filter tasks by search query.

        Args:
            query: Search query string
        """
        self._filter_query = query.lower()

        if not query:
            self.filtered_tasks = self.tasks.copy()
            return

        self.filtered_tasks = [
            task for task in self.tasks
            if self._matches_filter(task)
        ]

        # Reset selection if current selection is out of bounds
        if self.selected_index >= len(self.filtered_tasks):
            self.selected_index = max(0, len(self.filtered_tasks) - 1)

    def _matches_filter(self, task: dict[str, Any]) -> bool:
        """Check if task matches filter query.

        Args:
            task: Task dictionary

        Returns:
            True if task matches filter
        """
        # Search in title, description, and tags
        searchable_fields = ["title", "description", "status", "priority", "repository"]

        for field_name in searchable_fields:
            value = task.get(field_name, "")
            if isinstance(value, str) and self._filter_query in value.lower():
                return True

        # Search in tags
        tags = task.get("tags", [])
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, str) and self._filter_query in tag.lower():
                    return True

        return False

    def clear_filter(self) -> None:
        """Clear the current filter."""
        self._filter_query = ""
        self.filtered_tasks = self.tasks.copy()


class TaskDetailPanel:
    """Panel displaying task details.

    Features:
    - Task information display
    - Metadata formatting
    - Status and priority indicators
    """

    def __init__(self) -> None:
        """Initialize task detail panel."""
        self.task: dict[str, Any] | None = None

    def set_task(self, task: dict[str, Any]) -> None:
        """Set the task to display.

        Args:
            task: Task dictionary
        """
        self.task = task

    def clear_task(self) -> None:
        """Clear the displayed task."""
        self.task = None


class HelpPanel:
    """Panel displaying help and key bindings.

    Features:
    - Key binding list
    - Mode-specific bindings
    - Searchable help
    """

    def __init__(self) -> None:
        """Initialize help panel."""
        self.bindings: list[KeyBinding] = []
        self._add_default_bindings()

    def _add_default_bindings(self) -> None:
        """Add default key bindings."""
        default_bindings = [
            KeyBinding("q", "quit", "Quit application"),
            KeyBinding("?", "help", "Toggle help"),
            KeyBinding("up", "move_up", "Move selection up"),
            KeyBinding("down", "move_down", "Move selection down"),
            KeyBinding("enter", "select", "Select task"),
            KeyBinding("/", "search", "Enter search mode"),
            KeyBinding("escape", "cancel", "Cancel/Return"),
            KeyBinding("r", "refresh", "Refresh task list"),
        ]
        self.bindings = default_bindings

    def add_binding(self, binding: KeyBinding) -> None:
        """Add a key binding.

        Args:
            binding: KeyBinding to add
        """
        self.bindings.append(binding)

    def get_bindings_for_mode(self, mode: DashboardState) -> list[KeyBinding]:
        """Get key bindings for a specific mode.

        Args:
            mode: Dashboard mode

        Returns:
            List of bindings active in this mode
        """
        result = []
        for binding in self.bindings:
            if not binding.modes or mode in binding.modes:
                result.append(binding)
        return result


class TaskDashboard:
    """Main task dashboard TUI.

    Features:
    - Split pane layout (list + details)
    - Keyboard navigation
    - Search and filter
    - Theme support
    - Help overlay

    Example:
        dashboard = TaskDashboard(task_store=store)
        await dashboard.load_tasks()
        # Run the dashboard (Textual app)
    """

    # Default key bindings
    DEFAULT_BINDINGS = [
        KeyBinding("q", "quit", "Quit"),
        KeyBinding("ctrl+q", "quit", "Quit"),
        KeyBinding("?", "help", "Help"),
        KeyBinding("/", "search", "Search"),
        KeyBinding("escape", "cancel", "Cancel"),
        KeyBinding("up", "move_up", "Up"),
        KeyBinding("down", "move_down", "Down"),
        KeyBinding("j", "move_down", "Down"),
        KeyBinding("k", "move_up", "Up"),
        KeyBinding("enter", "select", "Select"),
        KeyBinding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        task_store: Any = None,
        theme: DashboardTheme | None = None,
    ) -> None:
        """Initialize task dashboard.

        Args:
            task_store: Task store for loading tasks
            theme: Optional custom theme
        """
        self.task_store = task_store
        self.theme = theme or DashboardTheme(name="default")
        self.state = DashboardState.NORMAL

        # Panels
        self.task_list = TaskListPanel(title="Tasks")
        self.task_detail = TaskDetailPanel()
        self.help_panel = HelpPanel()

        # Key bindings
        self._bindings = self.DEFAULT_BINDINGS.copy()

        # Internal state
        self._should_exit = False
        self._show_help = False
        self._search_query = ""

    async def load_tasks(self) -> None:
        """Load tasks from the task store."""
        if self.task_store is None:
            return

        try:
            tasks = await self.task_store.list()
            self.task_list.set_tasks(tasks)
        except Exception as e:
            logger.error(f"Failed to load tasks: {e}")
            self.task_list.set_tasks([])

    def select_task(self, index: int) -> None:
        """Select a task by index.

        Args:
            index: Task index in the list
        """
        self.task_list.selected_index = index
        task = self.task_list.get_selected_task()
        if task:
            self.task_detail.set_task(task)

    async def refresh(self) -> None:
        """Refresh the task list."""
        await self.load_tasks()

    def handle_key(self, key: str) -> bool:
        """Handle a key press.

        Args:
            key: Key that was pressed

        Returns:
            True if key was handled, False otherwise
        """
        # State-specific handling
        if self.state == DashboardState.SEARCH:
            return self._handle_search_key(key)

        if self.state == DashboardState.HELP:
            if key in ("escape", "q", "?"):
                self.toggle_help()
                return True
            return False

        # Normal mode handling
        key_mapping = {
            "up": self._move_up,
            "down": self._move_down,
            "k": self._move_up,
            "j": self._move_down,
            "q": self._quit,
            "ctrl+q": self._quit,
            "?": self._show_help_panel,
            "/": self._enter_search_mode,
            "enter": self._select_current,
            "r": self._refresh_list,
            "escape": self._cancel,
        }

        handler = key_mapping.get(key)
        if handler:
            handler()
            return True

        return False

    def _move_up(self) -> None:
        """Move selection up."""
        self.task_list.move_selection(-1)
        self._update_detail()

    def _move_down(self) -> None:
        """Move selection down."""
        self.task_list.move_selection(1)
        self._update_detail()

    def _update_detail(self) -> None:
        """Update detail panel with selected task."""
        task = self.task_list.get_selected_task()
        if task:
            self.task_detail.set_task(task)

    def _quit(self) -> None:
        """Quit the dashboard."""
        self._should_exit = True

    def _show_help_panel(self) -> None:
        """Show help panel."""
        self.toggle_help()

    def _enter_search_mode(self) -> None:
        """Enter search mode."""
        self.enter_search()

    def _select_current(self) -> None:
        """Select current task."""
        self._update_detail()

    def _refresh_list(self) -> None:
        """Refresh task list (async, no wait)."""
        # Just mark that refresh was requested
        pass

    def _cancel(self) -> None:
        """Cancel current action."""
        if self.state == DashboardState.SEARCH:
            self.exit_search()
        elif self.state == DashboardState.HELP:
            self.toggle_help()

    def _handle_search_key(self, key: str) -> bool:
        """Handle key in search mode.

        Args:
            key: Key that was pressed

        Returns:
            True if handled
        """
        if key == "escape":
            self.exit_search()
            return True
        elif key == "enter":
            # Confirm search
            self.state = DashboardState.NORMAL
            return True
        elif key == "backspace":
            self._search_query = self._search_query[:-1]
            self.search(self._search_query)
            return True
        elif len(key) == 1 and key.isprintable():
            self._search_query += key
            self.search(self._search_query)
            return True
        return False

    def get_status(self) -> dict[str, Any]:
        """Get dashboard status.

        Returns:
            Dictionary with status information
        """
        return {
            "state": self.state.value,
            "total_tasks": len(self.task_list.tasks),
            "filtered_tasks": len(self.task_list.filtered_tasks),
            "selected_index": self.task_list.selected_index,
            "theme": self.theme.name,
        }

    def set_theme(self, theme: DashboardTheme) -> None:
        """Set the dashboard theme.

        Args:
            theme: New theme to apply
        """
        self.theme = theme

    def get_bindings(self) -> list[KeyBinding]:
        """Get all key bindings.

        Returns:
            List of key bindings
        """
        return self._bindings.copy()

    def toggle_help(self) -> None:
        """Toggle help display."""
        self._show_help = not self._show_help
        if self._show_help:
            self.state = DashboardState.HELP
        else:
            self.state = DashboardState.NORMAL

    def enter_search(self) -> None:
        """Enter search mode."""
        self.state = DashboardState.SEARCH
        self._search_query = ""

    def exit_search(self) -> None:
        """Exit search mode."""
        self.state = DashboardState.NORMAL
        self._search_query = ""
        self.task_list.clear_filter()

    def search(self, query: str) -> None:
        """Perform search.

        Args:
            query: Search query
        """
        self.task_list.filter_tasks(query)


__all__ = [
    "TaskDashboard",
    "DashboardState",
    "DashboardTheme",
    "KeyBinding",
    "TaskListPanel",
    "TaskDetailPanel",
    "HelpPanel",
]
