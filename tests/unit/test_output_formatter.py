"""Tests for OutputFormatter - Rich console output formatting."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from mahavishnu.core.output_formatter import (
    OutputFormat,
    OutputFormatter,
    OutputLevel,
    OutputTheme,
    TableColumn,
    TableConfig,
)


@pytest.fixture
def mock_console() -> MagicMock:
    """Create a mock Rich console."""
    return MagicMock()


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
            "created_at": datetime.now(UTC),
        },
        {
            "id": "task-2",
            "title": "Fix bug in module Y",
            "status": "pending",
            "priority": "medium",
            "repository": "crackerjack",
            "created_at": datetime.now(UTC),
        },
        {
            "id": "task-3",
            "title": "Add tests for Z",
            "status": "completed",
            "priority": "low",
            "repository": "session-buddy",
            "created_at": datetime.now(UTC),
        },
    ]


class TestOutputFormat:
    """Tests for OutputFormat enum."""

    def test_output_formats(self) -> None:
        """Test available output formats."""
        assert OutputFormat.TABLE.value == "table"
        assert OutputFormat.JSON.value == "json"
        assert OutputFormat.YAML.value == "yaml"
        assert OutputFormat.MARKDOWN.value == "markdown"
        assert OutputFormat.PLAIN.value == "plain"


class TestOutputTheme:
    """Tests for OutputTheme enum."""

    def test_output_themes(self) -> None:
        """Test available output themes."""
        assert OutputTheme.DARK.value == "dark"
        assert OutputTheme.LIGHT.value == "light"
        assert OutputTheme.MONOCHROME.value == "monochrome"


class TestOutputLevel:
    """Tests for OutputLevel enum."""

    def test_output_levels(self) -> None:
        """Test available verbosity levels."""
        assert OutputLevel.QUIET.value == "quiet"
        assert OutputLevel.NORMAL.value == "normal"
        assert OutputLevel.VERBOSE.value == "verbose"
        assert OutputLevel.DEBUG.value == "debug"


class TestTableColumn:
    """Tests for TableColumn dataclass."""

    def test_create_table_column(self) -> None:
        """Create a table column."""
        col = TableColumn(
            name="ID",
            key="id",
            width=10,
        )

        assert col.name == "ID"
        assert col.key == "id"
        assert col.width == 10

    def test_table_column_with_format(self) -> None:
        """Create column with format function."""
        col = TableColumn(
            name="Status",
            key="status",
            format_fn=lambda x: x.upper(),
        )

        assert col.format_fn is not None
        assert col.format_fn("pending") == "PENDING"


class TestTableConfig:
    """Tests for TableConfig dataclass."""

    def test_create_table_config(self) -> None:
        """Create a table configuration."""
        config = TableConfig(
            title="Tasks",
            columns=[
                TableColumn("ID", "id"),
                TableColumn("Title", "title"),
            ],
        )

        assert config.title == "Tasks"
        assert len(config.columns) == 2

    def test_table_config_defaults(self) -> None:
        """Test default table configuration."""
        config = TableConfig(
            columns=[TableColumn("ID", "id")],
        )

        assert config.title is None
        assert config.show_header is True
        assert config.show_border is True


class TestOutputFormatter:
    """Tests for OutputFormatter class."""

    def test_create_formatter(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Create an output formatter."""
        formatter = OutputFormatter(console=mock_console)

        assert formatter.format == OutputFormat.TABLE
        assert formatter.theme == OutputTheme.DARK
        assert formatter.level == OutputLevel.NORMAL

    def test_create_formatter_with_options(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Create formatter with custom options."""
        formatter = OutputFormatter(
            console=mock_console,
            format=OutputFormat.JSON,
            theme=OutputTheme.LIGHT,
            level=OutputLevel.VERBOSE,
        )

        assert formatter.format == OutputFormat.JSON
        assert formatter.theme == OutputTheme.LIGHT
        assert formatter.level == OutputLevel.VERBOSE

    def test_format_table(
        self,
        mock_console: MagicMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Format data as table."""
        formatter = OutputFormatter(console=mock_console)

        config = TableConfig(
            title="Tasks",
            columns=[
                TableColumn("ID", "id", width=10),
                TableColumn("Title", "title", width=30),
                TableColumn("Status", "status", width=12),
            ],
        )

        output = formatter.format_table(sample_tasks, config)

        # Should produce output containing task data
        assert output is not None
        assert "task-1" in output or "Tasks" in output

    def test_format_json(
        self,
        mock_console: MagicMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Format data as JSON."""
        formatter = OutputFormatter(
            console=mock_console,
            format=OutputFormat.JSON,
        )

        output = formatter.format_data(sample_tasks)

        assert output is not None
        assert '"id": "task-1"' in output or '"id":"task-1"' in output.replace(" ", "")

    def test_format_yaml(
        self,
        mock_console: MagicMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Format data as YAML."""
        formatter = OutputFormatter(
            console=mock_console,
            format=OutputFormat.YAML,
        )

        output = formatter.format_data(sample_tasks)

        assert output is not None
        assert "- id: task-1" in output or "id: task-1" in output

    def test_format_markdown(
        self,
        mock_console: MagicMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Format data as Markdown."""
        formatter = OutputFormatter(
            console=mock_console,
            format=OutputFormat.MARKDOWN,
        )

        config = TableConfig(
            title="Tasks",
            columns=[
                TableColumn("ID", "id"),
                TableColumn("Title", "title"),
            ],
        )

        output = formatter.format_table(sample_tasks, config)

        assert output is not None
        assert "|" in output  # Markdown table delimiter

    def test_format_plain(
        self,
        mock_console: MagicMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Format data as plain text."""
        formatter = OutputFormatter(
            console=mock_console,
            format=OutputFormat.PLAIN,
        )

        output = formatter.format_data(sample_tasks)

        assert output is not None
        assert "task-1" in output

    def test_print_success(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Print success message."""
        formatter = OutputFormatter(console=mock_console)

        formatter.print_success("Operation completed successfully")

        mock_console.print.assert_called()

    def test_print_error(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Print error message."""
        formatter = OutputFormatter(console=mock_console)

        formatter.print_error("Operation failed")

        mock_console.print.assert_called()

    def test_print_warning(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Print warning message."""
        formatter = OutputFormatter(console=mock_console)

        formatter.print_warning("This is a warning")

        mock_console.print.assert_called()

    def test_print_info(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Print info message."""
        formatter = OutputFormatter(console=mock_console)

        formatter.print_info("Information message")

        mock_console.print.assert_called()

    def test_print_debug(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Print debug message (only in debug level)."""
        formatter = OutputFormatter(
            console=mock_console,
            level=OutputLevel.DEBUG,
        )

        formatter.print_debug("Debug information")

        mock_console.print.assert_called()

    def test_print_debug_quiet(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Debug message not printed in quiet mode."""
        mock_console.reset_mock()
        formatter = OutputFormatter(
            console=mock_console,
            level=OutputLevel.QUIET,
        )

        formatter.print_debug("Debug information")

        # Should not print in quiet mode
        mock_console.print.assert_not_called()

    def test_print_header(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Print header."""
        formatter = OutputFormatter(console=mock_console)

        formatter.print_header("Task Manager")

        mock_console.print.assert_called()

    def test_format_task_list(
        self,
        mock_console: MagicMock,
        sample_tasks: list[dict[str, Any]],
    ) -> None:
        """Format task list with default columns."""
        formatter = OutputFormatter(console=mock_console)

        output = formatter.format_task_list(sample_tasks)

        assert output is not None

    def test_format_single_task(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Format single task details."""
        formatter = OutputFormatter(console=mock_console)

        task = {
            "id": "task-1",
            "title": "Test task",
            "status": "in_progress",
            "description": "This is a test task",
            "metadata": {"key": "value"},
        }

        output = formatter.format_task_detail(task)

        assert output is not None

    def test_format_empty_data(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Format empty data gracefully."""
        formatter = OutputFormatter(console=mock_console)

        output = formatter.format_data([])

        assert output is not None

    def test_verbosity_level_check(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Check verbosity level methods."""
        formatter = OutputFormatter(
            console=mock_console,
            level=OutputLevel.VERBOSE,
        )

        assert formatter.is_verbose() is True
        assert formatter.is_debug() is False
        assert formatter.is_quiet() is False

    def test_quiet_level(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Check quiet level."""
        formatter = OutputFormatter(
            console=mock_console,
            level=OutputLevel.QUIET,
        )

        assert formatter.is_quiet() is True
        assert formatter.is_verbose() is False

    def test_debug_level(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Check debug level."""
        formatter = OutputFormatter(
            console=mock_console,
            level=OutputLevel.DEBUG,
        )

        assert formatter.is_debug() is True
        assert formatter.is_verbose() is True

    def test_status_color_mapping(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test status to color mapping."""
        formatter = OutputFormatter(console=mock_console)

        assert formatter.get_status_color("completed") == "green"
        assert formatter.get_status_color("in_progress") == "yellow"
        assert formatter.get_status_color("pending") == "blue"
        assert formatter.get_status_color("failed") == "red"

    def test_priority_indicator(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test priority indicator."""
        formatter = OutputFormatter(console=mock_console)

        assert formatter.get_priority_indicator("critical") == "!!!"
        assert formatter.get_priority_indicator("high") == "!!"
        assert formatter.get_priority_indicator("medium") == "!"
        assert formatter.get_priority_indicator("low") == ""

    def test_format_duration(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test duration formatting."""
        formatter = OutputFormatter(console=mock_console)

        assert formatter.format_duration(30) == "30s"
        assert formatter.format_duration(90) == "1m 30s"
        assert formatter.format_duration(3661) == "1h 1m"

    def test_format_timestamp(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test timestamp formatting."""
        formatter = OutputFormatter(console=mock_console)

        # Use old timestamp (10 days ago) to get date format
        from datetime import timedelta

        ts = datetime.now(UTC) - timedelta(days=10)
        output = formatter.format_timestamp(ts)

        assert output is not None
        # Should show "Xd ago" or date format
        assert "ago" in output or "-" in output

    def test_wrap_text(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test text wrapping."""
        formatter = OutputFormatter(console=mock_console, width=40)

        text = "This is a very long text that should be wrapped to multiple lines"
        wrapped = formatter.wrap_text(text, width=20)

        # Should contain newlines for wrapping
        assert "\n" in wrapped

    def test_truncate_text(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test text truncation."""
        formatter = OutputFormatter(console=mock_console)

        text = "This is a very long text that should be truncated"
        truncated = formatter.truncate_text(text, max_length=20)

        assert len(truncated) <= 23  # 20 + "..."
        assert truncated.endswith("...")

    def test_panel_output(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test panel output."""
        formatter = OutputFormatter(console=mock_console)

        formatter.print_panel("Content here", title="Panel Title")

        mock_console.print.assert_called()

    def test_rule_output(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test rule/separator output."""
        formatter = OutputFormatter(console=mock_console)

        formatter.print_rule("Section Header")

        mock_console.print.assert_called()

    def test_columns_output(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test multi-column output."""
        formatter = OutputFormatter(console=mock_console)

        items = ["Item 1", "Item 2", "Item 3", "Item 4"]
        formatter.print_columns(items, columns=2)

        mock_console.print.assert_called()

    def test_tree_output(
        self,
        mock_console: MagicMock,
    ) -> None:
        """Test tree output."""
        formatter = OutputFormatter(console=mock_console)

        tree_data = {
            "label": "Root",
            "children": [
                {"label": "Child 1"},
                {"label": "Child 2", "children": [{"label": "Grandchild"}]},
            ],
        }

        formatter.print_tree(tree_data)

        mock_console.print.assert_called()

    # ------------------------------------------------------------------
    # format_timestamp branches
    # ------------------------------------------------------------------

    def test_format_timestamp_minutes_ago(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        ts = datetime.now(UTC) - timedelta(minutes=30)
        result = formatter.format_timestamp(ts)
        assert result.endswith("m ago")

    def test_format_timestamp_hours_ago(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        ts = datetime.now(UTC) - timedelta(hours=3)
        result = formatter.format_timestamp(ts)
        assert result.endswith("h ago")

    def test_format_timestamp_yesterday(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        ts = datetime.now(UTC) - timedelta(days=1, hours=1)
        result = formatter.format_timestamp(ts)
        assert result == "yesterday"

    def test_format_timestamp_days_ago(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        ts = datetime.now(UTC) - timedelta(days=4)
        result = formatter.format_timestamp(ts)
        assert result.endswith("d ago")

    def test_format_timestamp_naive_datetime(self, mock_console: MagicMock) -> None:
        """Naive datetime (no tzinfo) should be handled by replacing with UTC."""
        formatter = OutputFormatter(console=mock_console)
        naive_ts = datetime.now() - timedelta(days=20)
        result = formatter.format_timestamp(naive_ts)
        assert result is not None  # Should not raise

    # ------------------------------------------------------------------
    # TableColumn.get_value() with format_fn
    # ------------------------------------------------------------------

    def test_table_column_get_value_with_format_fn(self) -> None:
        col = TableColumn(name="Status", key="status", format_fn=lambda x: x.upper())
        row = {"status": "pending"}
        assert col.get_value(row) == "PENDING"

    def test_table_column_get_value_none(self) -> None:
        col = TableColumn(name="Opt", key="optional")
        row = {"optional": None}
        assert col.get_value(row) == ""

    def test_table_column_get_value_datetime(self) -> None:
        col = TableColumn(name="When", key="ts")
        now = datetime.now(UTC)
        row = {"ts": now}
        result = col.get_value(row)
        assert "-" in result  # strftime output contains dashes

    # ------------------------------------------------------------------
    # _simple_yaml
    # ------------------------------------------------------------------

    def test_simple_yaml_dict(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        result = formatter._simple_yaml({"key": "value", "num": 42})
        assert "key:" in result
        assert "value" in result

    def test_simple_yaml_list_of_dicts(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        result = formatter._simple_yaml([{"a": 1}, {"b": 2}])
        assert "-" in result

    def test_simple_yaml_list_of_scalars(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        result = formatter._simple_yaml(["foo", "bar"])
        assert "foo" in result

    def test_simple_yaml_nested_dict(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        result = formatter._simple_yaml({"outer": {"inner": "val"}})
        assert "outer:" in result
        assert "inner:" in result

    def test_simple_yaml_scalar(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        result = formatter._simple_yaml("plain string")
        assert "plain string" in result

    # ------------------------------------------------------------------
    # _format_plain_table
    # ------------------------------------------------------------------

    def test_format_plain_table_with_title_and_row_numbers(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        config = TableConfig(
            title="My Table",
            columns=[
                TableColumn(name="Name", key="name"),
                TableColumn(name="Value", key="val"),
            ],
            show_row_numbers=True,
        )
        data = [{"name": "alpha", "val": "1"}, {"name": "beta", "val": "2"}]
        result = formatter._format_plain_table(data, config)
        assert "My Table" in result
        assert "alpha" in result
        assert "1." in result

    def test_format_plain_table_no_header(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        config = TableConfig(
            columns=[TableColumn(name="X", key="x")],
            show_header=False,
        )
        data = [{"x": "hello"}]
        result = formatter._format_plain_table(data, config)
        assert "hello" in result
        assert "X" not in result  # no header row

    # ------------------------------------------------------------------
    # _format_markdown
    # ------------------------------------------------------------------

    def test_format_markdown_with_list_of_dicts(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console, format=OutputFormat.MARKDOWN)
        result = formatter.format_data({"items": [{"k": "v"}]})
        assert result is not None

    def test_format_markdown_direct_list(self, mock_console: MagicMock) -> None:
        formatter = OutputFormatter(console=mock_console)
        result = formatter._format_markdown([{"col1": "a", "col2": "b"}])
        assert "|" in result
        assert "col1" in result

    # ------------------------------------------------------------------
    # print_panel / print_rule without console (fallback path)
    # ------------------------------------------------------------------

    def test_print_panel_no_console_with_title(self) -> None:
        formatter = OutputFormatter()
        formatter._console = None
        formatter.print_panel("Some content", title="Title")  # Should not raise

    def test_print_panel_no_console_no_title(self) -> None:
        formatter = OutputFormatter()
        formatter._console = None
        formatter.print_panel("Content")  # Should not raise

    def test_print_rule_no_console_with_title(self) -> None:
        formatter = OutputFormatter()
        formatter._console = None
        formatter.print_rule("Section")  # Should not raise

    def test_print_rule_no_console_empty(self) -> None:
        formatter = OutputFormatter()
        formatter._console = None
        formatter.print_rule()  # Should not raise
