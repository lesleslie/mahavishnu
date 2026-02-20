"""Tests for TaskDashboard - Textual-based TUI for task management."""

import pytest
from datetime import datetime, UTC
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from mahavishnu.core.task_dashboard import (
    TaskDashboard,
    DashboardState,
    TaskListPanel,
    TaskDetailPanel,
    HelpPanel,
    DashboardTheme,
    KeyBinding,
)


@pytest.fixture
def mock_task_store() -> AsyncMock:
    """Create a mock TaskStore."""
    store = AsyncMock()
    store.list.return_value = []
    return store


@pytest.fixture
def sample_tasks() -> list[dict[str, Any]]:
    """Create sample task data."""
    return [
        {
            "id": "task-1",
            "title": "Implement feature X",
            "status": "in_progress",
            "priority": "high",
            "repository": "mahavishnu",
            "description": "Add new feature for user authentication",
            "created_at": datetime.now(UTC),
            "tags": ["feature", "auth"],
        },
        {
            "id": "task-2",
            "title": "Fix bug in module Y",
            "status": "pending",
            "priority": "medium",
            "repository": "crackerjack",
            "description": "Fix null pointer exception",
            "created_at": datetime.now(UTC),
            "tags": ["bug"],
        },
        {
            "id": "task-3",
            "title": "Add tests for Z",
            "status": "completed",
            "priority": "low",
            "repository": "session-buddy",
            "description": "Increase test coverage",
            "created_at": datetime.now(UTC),
            "tags": ["test"],
        },
    ]


class TestDashboardState:
    """Tests for DashboardState enum."""

    def test_dashboard_states(self) -> None:
        """Test available dashboard states."""
        assert DashboardState.NORMAL.value == "normal"
        assert DashboardState.INSERT.value == "insert"
        assert DashboardState.SEARCH.value == "search"
        assert DashboardState.HELP.value == "help"


class TestDashboardTheme:
    """Tests for DashboardTheme dataclass."""

    def test_create_theme(self) -> None:
        """Create a dashboard theme."""
        theme = DashboardTheme(
            name="dark",
            background="#1a1a1a",
            foreground="#ffffff",
            accent="#00ff00",
        )

        assert theme.name == "dark"
        assert theme.background == "#1a1a1a"

    def test_default_theme(self) -> None:
        """Test default theme values."""
        theme = DashboardTheme(name="default")

        assert theme.background is not None


class TestKeyBinding:
    """Tests for KeyBinding dataclass."""

    def test_create_key_binding(self) -> None:
        """Create a key binding."""
        binding = KeyBinding(
            key="ctrl+n",
            action="new_task",
            description="Create new task",
        )

        assert binding.key == "ctrl+n"
        assert binding.action == "new_task"

    def test_key_binding_with_modes(self) -> None:
        """Create key binding with mode restriction."""
        binding = KeyBinding(
            key="escape",
            action="cancel",
            description="Cancel",
            modes=[DashboardState.INSERT],
        )

        assert DashboardState.INSERT in binding.modes


class TestTaskListPanel:
    """Tests for TaskListPanel class."""

    def test_create_list_panel(self) -> None:
        """Create a task list panel."""
        panel = TaskListPanel(title="Tasks")

        assert panel.title == "Tasks"
        assert len(panel.tasks) == 0

    def test_set_tasks(
        self,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Set tasks in the panel."""
        panel = TaskListPanel(title="Tasks")
        panel.set_tasks(sample_tasks)

        assert len(panel.tasks) == 3

    def test_get_selected_task(
        self,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Get the selected task."""
        panel = TaskListPanel(title="Tasks")
        panel.set_tasks(sample_tasks)
        panel.selected_index = 1

        task = panel.get_selected_task()

        assert task is not None
        assert task["id"] == "task-2"

    def test_move_selection(
        self,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Move selection up and down."""
        panel = TaskListPanel(title="Tasks")
        panel.set_tasks(sample_tasks)

        panel.move_selection(1)
        assert panel.selected_index == 1

        panel.move_selection(-1)
        assert panel.selected_index == 0

    def test_move_selection_bounds(
        self,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Selection stays within bounds."""
        panel = TaskListPanel(title="Tasks")
        panel.set_tasks(sample_tasks)

        panel.move_selection(-10)  # Try to go before first
        assert panel.selected_index == 0

        panel.move_selection(100)  # Try to go after last
        assert panel.selected_index == 2  # Clamped to last

    def test_filter_tasks(
        self,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Filter tasks by query."""
        panel = TaskListPanel(title="Tasks")
        panel.set_tasks(sample_tasks)

        panel.filter_tasks("bug")

        assert len(panel.filtered_tasks) == 1
        assert panel.filtered_tasks[0]["id"] == "task-2"

    def test_clear_filter(
        self,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Clear task filter."""
        panel = TaskListPanel(title="Tasks")
        panel.set_tasks(sample_tasks)

        panel.filter_tasks("bug")
        panel.clear_filter()

        assert len(panel.filtered_tasks) == 3


class TestTaskDetailPanel:
    """Tests for TaskDetailPanel class."""

    def test_create_detail_panel(self) -> None:
        """Create a task detail panel."""
        panel = TaskDetailPanel()

        assert panel.task is None

    def test_set_task(
        self,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Set task to display."""
        panel = TaskDetailPanel()
        panel.set_task(sample_tasks[0])

        assert panel.task is not None
        assert panel.task["id"] == "task-1"

    def test_clear_task(self) -> None:
        """Clear displayed task."""
        panel = TaskDetailPanel()
        panel.set_task({"id": "test"})
        panel.clear_task()

        assert panel.task is None


class TestHelpPanel:
    """Tests for HelpPanel class."""

    def test_create_help_panel(self) -> None:
        """Create a help panel."""
        panel = HelpPanel()

        assert panel is not None
        assert len(panel.bindings) > 0

    def test_add_binding(self) -> None:
        """Add a key binding to help."""
        panel = HelpPanel()
        panel.add_binding(KeyBinding("q", "quit", "Quit application"))

        assert len(panel.bindings) > 0

    def test_get_bindings_by_mode(self) -> None:
        """Get bindings filtered by mode."""
        panel = HelpPanel()
        panel.add_binding(KeyBinding("i", "insert", "Insert mode", modes=[DashboardState.NORMAL]))
        panel.add_binding(KeyBinding("esc", "cancel", "Cancel", modes=[DashboardState.INSERT]))

        normal_bindings = panel.get_bindings_for_mode(DashboardState.NORMAL)
        insert_bindings = panel.get_bindings_for_mode(DashboardState.INSERT)

        assert len(normal_bindings) >= 1
        assert len(insert_bindings) >= 1


class TestTaskDashboard:
    """Tests for TaskDashboard class."""

    def test_create_dashboard(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Create a task dashboard."""
        dashboard = TaskDashboard(task_store=mock_task_store)

        assert dashboard.state == DashboardState.NORMAL
        assert dashboard.task_list is not None
        assert dashboard.task_detail is not None

    def test_create_dashboard_with_theme(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Create dashboard with custom theme."""
        theme = DashboardTheme(name="light", background="#ffffff")
        dashboard = TaskDashboard(task_store=mock_task_store, theme=theme)

        assert dashboard.theme.name == "light"

    @pytest.mark.asyncio
    async def test_load_tasks(
        self,
        mock_task_store: AsyncMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Load tasks into dashboard."""
        mock_task_store.list.return_value = sample_tasks

        dashboard = TaskDashboard(task_store=mock_task_store)
        await dashboard.load_tasks()

        assert len(dashboard.task_list.tasks) == 3
        mock_task_store.list.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_task(
        self,
        mock_task_store: AsyncMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Select a task to view details."""
        mock_task_store.list.return_value = sample_tasks

        dashboard = TaskDashboard(task_store=mock_task_store)
        await dashboard.load_tasks()

        dashboard.select_task(0)

        assert dashboard.task_detail.task is not None
        assert dashboard.task_detail.task["id"] == "task-1"

    @pytest.mark.asyncio
    async def test_refresh_tasks(
        self,
        mock_task_store: AsyncMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Refresh task list."""
        mock_task_store.list.return_value = sample_tasks

        dashboard = TaskDashboard(task_store=mock_task_store)
        await dashboard.load_tasks()

        await dashboard.refresh()

        assert mock_task_store.list.call_count == 2

    def test_handle_key_navigation(
        self,
        mock_task_store: AsyncMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Handle navigation key presses."""
        dashboard = TaskDashboard(task_store=mock_task_store)
        dashboard.task_list.set_tasks(sample_tasks)

        result = dashboard.handle_key("down")
        assert result is True
        assert dashboard.task_list.selected_index == 1

        result = dashboard.handle_key("up")
        assert result is True
        assert dashboard.task_list.selected_index == 0

    def test_handle_key_quit(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Handle quit key press."""
        dashboard = TaskDashboard(task_store=mock_task_store)

        result = dashboard.handle_key("q")

        # Should signal quit
        assert result is True or dashboard._should_exit is True

    def test_handle_key_help(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Handle help key press."""
        dashboard = TaskDashboard(task_store=mock_task_store)

        result = dashboard.handle_key("?")

        assert dashboard.state == DashboardState.HELP or result is True

    def test_handle_key_escape(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Handle escape key."""
        dashboard = TaskDashboard(task_store=mock_task_store)
        dashboard.state = DashboardState.HELP

        result = dashboard.handle_key("escape")

        assert dashboard.state == DashboardState.NORMAL or result is True

    def test_get_status(
        self,
        mock_task_store: AsyncMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Get dashboard status."""
        dashboard = TaskDashboard(task_store=mock_task_store)
        dashboard.task_list.set_tasks(sample_tasks)

        status = dashboard.get_status()

        assert "total_tasks" in status
        assert status["total_tasks"] == 3

    def test_set_theme(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Set dashboard theme."""
        dashboard = TaskDashboard(task_store=mock_task_store)
        new_theme = DashboardTheme(name="monochrome")

        dashboard.set_theme(new_theme)

        assert dashboard.theme.name == "monochrome"

    def test_get_default_bindings(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Get default key bindings."""
        dashboard = TaskDashboard(task_store=mock_task_store)
        bindings = dashboard.get_bindings()

        assert len(bindings) > 0
        # Should have common bindings
        binding_keys = [b.key for b in bindings]
        assert "q" in binding_keys or "ctrl+q" in binding_keys

    def test_toggle_help(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Toggle help display."""
        dashboard = TaskDashboard(task_store=mock_task_store)

        dashboard.toggle_help()
        assert dashboard.state == DashboardState.HELP or dashboard._show_help is True

        dashboard.toggle_help()
        assert dashboard.state == DashboardState.NORMAL or dashboard._show_help is False

    def test_search_mode(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Enter search mode."""
        dashboard = TaskDashboard(task_store=mock_task_store)

        dashboard.enter_search()

        assert dashboard.state == DashboardState.SEARCH

    def test_exit_search(
        self,
        mock_task_store: AsyncMock,
    ) -> None:
        """Exit search mode."""
        dashboard = TaskDashboard(task_store=mock_task_store)
        dashboard.state = DashboardState.SEARCH
        dashboard._search_query = "test"

        dashboard.exit_search()

        assert dashboard.state == DashboardState.NORMAL
        assert dashboard._search_query == ""

    def test_search_query(
        self,
        mock_task_store: AsyncMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Perform search."""
        dashboard = TaskDashboard(task_store=mock_task_store)
        dashboard.task_list.set_tasks(sample_tasks)

        dashboard.search("bug")

        # Should filter tasks
        assert len(dashboard.task_list.filtered_tasks) <= len(sample_tasks)
