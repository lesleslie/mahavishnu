"""Unit tests for shell formatters (WorkflowFormatter, LogFormatter, RepoFormatter)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from mahavishnu.core.workflow_state import WorkflowStatus
from mahavishnu.shell.formatters import (
    LogFormatter,
    RepoFormatter,
    WorkflowFormatter,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def recording_console():
    """Real Rich console that records its output as plain text."""
    return Console(record=True, width=200, force_terminal=False, file=open("/dev/null", "w"))


@pytest.fixture
def console_mock():
    """Plain MagicMock console for tests that only count print() calls."""
    return MagicMock(name="console")


@pytest.fixture
def workflow_formatter(console_mock):
    """WorkflowFormatter with a plain MagicMock console."""
    return WorkflowFormatter(console=console_mock)


@pytest.fixture
def log_formatter(console_mock):
    """LogFormatter with a plain MagicMock console."""
    return LogFormatter(console=console_mock)


@pytest.fixture
def repo_formatter(console_mock):
    """RepoFormatter with a plain MagicMock console."""
    return RepoFormatter(console=console_mock)


@pytest.fixture
def recording_workflow_formatter(recording_console):
    """WorkflowFormatter wired to a real recording console."""
    return WorkflowFormatter(console=recording_console)


@pytest.fixture
def recording_log_formatter(recording_console):
    """LogFormatter wired to a real recording console."""
    return LogFormatter(console=recording_console)


@pytest.fixture
def recording_repo_formatter(recording_console):
    """RepoFormatter wired to a real recording console."""
    return RepoFormatter(console=recording_console)


@pytest.fixture
def sample_workflow():
    """A single workflow dictionary used for formatting."""
    return {
        "id": "wf-1234",
        "status": WorkflowStatus.RUNNING,
        "progress": 50,
        "adapter": "prefect",
        "created_at": "2026-01-01T12:00:00",
        "repos": ["repo-a", "repo-b"],
        "errors": [{"message": "Boom"}],
    }


@pytest.fixture
def sample_log():
    """A single log entry."""
    return {
        "timestamp": "2026-01-01T12:00:00.000000",
        "level": "INFO",
        "message": "hello world",
        "workflow_id": "wf-1",
    }


@pytest.fixture
def sample_repo():
    """A single repo entry."""
    return {
        "path": "/tmp/proj",
        "description": "An example",
        "tags": ["python", "test"],
    }


def _column_cells(table, column_index):
    """Return the raw cell strings for a given column index of a Rich Table."""
    return table.columns[column_index]._cells


def _strip(text):
    """Strip ANSI control sequences from a Rich recording export."""
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# =============================================================================
# WorkflowFormatter Tests
# =============================================================================


@pytest.mark.unit
class TestWorkflowFormatterConstruction:
    """Construction behavior for WorkflowFormatter."""

    def test_inherits_from_base_table_formatter(self):
        """WorkflowFormatter subclasses BaseTableFormatter."""
        from oneiric.shell.formatters import BaseTableFormatter

        fmt = WorkflowFormatter()
        assert isinstance(fmt, BaseTableFormatter)

    def test_console_passed_through(self, console_mock):
        """Console argument is stored on instance."""
        fmt = WorkflowFormatter(console=console_mock)
        assert fmt.console is console_mock


@pytest.mark.unit
class TestWorkflowFormatterFormatWorkflows:
    """format_workflows rendering behavior."""

    def test_empty_list_prints_message(self, workflow_formatter, capsys):
        """An empty list triggers the empty-state print and does not call console."""
        workflow_formatter.format_workflows([], show_details=False)

        captured = capsys.readouterr()
        assert "No workflows to display" in captured.out
        workflow_formatter.console.print.assert_not_called()

    def test_rich_path_renders_table(self, workflow_formatter, sample_workflow):
        """When console is available, a Rich Table is built and printed."""
        workflow_formatter.format_workflows([sample_workflow], show_details=False)

        workflow_formatter.console.print.assert_called_once()
        printed = workflow_formatter.console.print.call_args.args[0]
        # The Table's title is set to "Workflows"
        assert getattr(printed, "title", "") == "Workflows"

    def test_rich_path_with_details_column(self, workflow_formatter, sample_workflow):
        """With show_details=True the rendered table includes a Details column."""
        workflow_formatter.format_workflows([sample_workflow], show_details=True)

        printed = workflow_formatter.console.print.call_args.args[0]
        column_headers = [c.header for c in printed.columns]
        assert "Details" in column_headers

    def test_no_details_column_by_default(self, workflow_formatter, sample_workflow):
        """Without show_details, no Details column is added."""
        workflow_formatter.format_workflows([sample_workflow], show_details=False)
        printed = workflow_formatter.console.print.call_args.args[0]
        column_headers = [c.header for c in printed.columns]
        assert "Details" not in column_headers

    def test_renders_workflow_id_and_status(self, recording_workflow_formatter, sample_workflow):
        """Rendered output contains the workflow ID and status text."""
        recording_workflow_formatter.format_workflows([sample_workflow], show_details=False)
        text = _strip(recording_workflow_formatter.console.export_text())
        assert "wf-1234" in text
        assert "running" in text

    @pytest.mark.parametrize(
        ("status", "expected_color"),
        [
            (WorkflowStatus.RUNNING, "yellow"),
            (WorkflowStatus.COMPLETED, "green"),
            (WorkflowStatus.FAILED, "red"),
            (WorkflowStatus.PENDING, "blue"),
        ],
    )
    def test_status_style_mapping_known_status(self, console_mock, status, expected_color):
        """Status keys map to expected Rich styles in the row text."""
        wf = {
            "id": "wf-1",
            "status": status,
            "progress": 0,
            "adapter": "prefect",
            "created_at": "2026-01-01T00:00:00",
            "repos": [],
            "errors": [],
        }
        fmt = WorkflowFormatter(console=console_mock)
        fmt.format_workflows([wf])
        printed = console_mock.print.call_args.args[0]
        # Status column is the second column (index 1)
        status_cells = _column_cells(printed, 1)
        assert any(f"[{expected_color}]" in c for c in status_cells)

    def test_unknown_status_no_style(self, console_mock):
        """An unrecognized status key yields no color markup (empty style)."""
        wf = {
            "id": "wf-1",
            "status": "weird",
            "progress": 0,
            "adapter": "prefect",
            "created_at": "2026-01-01T00:00:00",
            "repos": [],
            "errors": [],
        }
        fmt = WorkflowFormatter(console=console_mock)
        fmt.format_workflows([wf])
        printed = console_mock.print.call_args.args[0]
        status_cells = _column_cells(printed, 1)
        # When the status is unknown the style is empty, producing `[]weird[/]`
        # with no actual color tag.
        for c in status_cells:
            assert "[red]" not in c
            assert "[green]" not in c
            assert "[yellow]" not in c
            assert "[blue]" not in c

    def test_id_truncated_to_20_chars(self, recording_workflow_formatter):
        """Workflow ID longer than 20 chars is truncated in the rendered row."""
        wf = {
            "id": "x" * 40,
            "status": WorkflowStatus.PENDING,
            "progress": 0,
            "adapter": "prefect",
            "created_at": "2026-01-01T00:00:00",
            "repos": [],
            "errors": [],
        }
        recording_workflow_formatter.format_workflows([wf])
        text = _strip(recording_workflow_formatter.console.export_text())
        # Only 20 of the 40 x's appear in the rendered row
        assert "x" * 20 in text
        assert "x" * 21 not in text

    def test_details_mentions_repos_and_errors(self, recording_workflow_formatter, sample_workflow):
        """Details cell includes repo count and error count when present."""
        recording_workflow_formatter.format_workflows([sample_workflow], show_details=True)
        text = _strip(recording_workflow_formatter.console.export_text())
        assert "Repos: 2" in text
        assert "Errors: 1" in text

    def test_progress_percentage_rendered(self, recording_workflow_formatter):
        """Progress is rendered with a percent sign."""
        wf = {
            "id": "wf-1",
            "status": WorkflowStatus.RUNNING,
            "progress": 75,
            "adapter": "prefect",
            "created_at": "2026-01-01T00:00:00",
            "repos": [],
            "errors": [],
        }
        recording_workflow_formatter.format_workflows([wf])
        text = _strip(recording_workflow_formatter.console.export_text())
        assert "75%" in text


@pytest.mark.unit
class TestWorkflowFormatterFallback:
    """Plain-print fallback path for workflow formatters."""

    def test_fallback_used_when_rich_unavailable(self, sample_workflow, capsys):
        """When Rich is unavailable the fallback path prints plain text."""
        with patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False):
            fmt = WorkflowFormatter(console=None)
            fmt.format_workflows([sample_workflow], show_details=False)

        captured = capsys.readouterr()
        assert "wf-1234" in captured.out
        assert "running" in captured.out

    def test_fallback_with_details(self, sample_workflow, capsys):
        """show_details=True in the fallback prints adapter and repo count."""
        with patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False):
            fmt = WorkflowFormatter(console=None)
            fmt.format_workflows([sample_workflow], show_details=True)

        captured = capsys.readouterr()
        assert "Adapter: prefect" in captured.out
        assert "Repos: 2" in captured.out


@pytest.mark.unit
class TestWorkflowFormatterFormatDetail:
    """format_workflow_detail rendering behavior."""

    def test_detail_rich_uses_panel(self, workflow_formatter, sample_workflow):
        """Detail rendering prints a Rich Panel when console is available."""
        workflow_formatter.format_workflow_detail(sample_workflow)

        printed = workflow_formatter.console.print.call_args.args[0]
        from rich.panel import Panel

        assert isinstance(printed, Panel)
        assert "Workflow Details" in str(printed.title)

    def test_detail_fallback(self, sample_workflow, capsys):
        """Without Rich, detail printing falls back to plain text."""
        with patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False):
            fmt = WorkflowFormatter(console=None)
            fmt.format_workflow_detail(sample_workflow)

        captured = capsys.readouterr()
        assert "Workflow: wf-1234" in captured.out
        assert "Status:" in captured.out


# =============================================================================
# LogFormatter Tests
# =============================================================================


@pytest.mark.unit
class TestLogFormatterConstruction:
    """LogFormatter construction basics."""

    def test_inherits_from_base_log_formatter(self):
        """LogFormatter subclasses BaseLogFormatter."""
        from oneiric.shell.formatters import BaseLogFormatter

        fmt = LogFormatter()
        assert isinstance(fmt, BaseLogFormatter)


@pytest.mark.unit
class TestLogFormatterFormatLogs:
    """LogFormatter.format_logs behavior."""

    def test_empty_logs_message(self, log_formatter, capsys):
        """Empty input produces the empty-state message."""
        log_formatter.format_logs([], tail=10)
        captured = capsys.readouterr()
        assert "No logs to display" in captured.out
        log_formatter.console.print.assert_not_called()

    def test_level_filter_case_insensitive(self, log_formatter):
        """Filtering by 'error' matches 'ERROR' level entries."""
        logs = [
            {"level": "ERROR", "message": "boom"},
            {"level": "INFO", "message": "fine"},
        ]
        log_formatter.format_logs(logs, level="error", tail=10)
        # Only one entry was printed via Rich
        assert log_formatter.console.print.call_count == 1

    def test_workflow_id_filter(self, log_formatter):
        """Filter by workflow_id keeps only matching entries."""
        logs = [
            {"workflow_id": "wf-1", "message": "a"},
            {"workflow_id": "wf-2", "message": "b"},
        ]
        log_formatter.format_logs(logs, workflow_id="wf-1", tail=10)
        assert log_formatter.console.print.call_count == 1

    def test_tail_truncation(self, log_formatter):
        """Only the last N log entries are displayed."""
        logs = [{"message": f"m{i}"} for i in range(20)]
        log_formatter.format_logs(logs, tail=5)
        assert log_formatter.console.print.call_count == 5

    def test_fallback_when_rich_unavailable(self, sample_log, capsys):
        """When Rich is unavailable, the plain-print fallback runs."""
        with patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False):
            fmt = LogFormatter(console=None)
            fmt.format_logs([sample_log], tail=10)

        captured = capsys.readouterr()
        assert "INFO" in captured.out
        assert "hello world" in captured.out

    def test_unknown_level_still_prints(self, log_formatter):
        """A log level outside the known map still renders (with empty style)."""
        log = {"level": "DEBUG", "message": "trace", "timestamp": "2026-01-01T00:00:00"}
        log_formatter.format_logs([log], tail=10)
        # Did not raise; we got one print call
        log_formatter.console.print.assert_called_once()

    def test_no_filters_prints_all(self, log_formatter):
        """Without filters, every log is printed up to tail."""
        logs = [{"message": f"m{i}"} for i in range(3)]
        log_formatter.format_logs(logs, tail=10)
        assert log_formatter.console.print.call_count == 3


# =============================================================================
# RepoFormatter Tests
# =============================================================================


@pytest.mark.unit
class TestRepoFormatterConstruction:
    """RepoFormatter construction basics."""

    def test_inherits_from_base_table_formatter(self):
        """RepoFormatter subclasses BaseTableFormatter."""
        from oneiric.shell.formatters import BaseTableFormatter

        fmt = RepoFormatter()
        assert isinstance(fmt, BaseTableFormatter)


@pytest.mark.unit
class TestRepoFormatterFormatRepos:
    """RepoFormatter.format_repos behavior."""

    def test_empty_repos_message(self, repo_formatter, capsys):
        """Empty input prints the empty-state message."""
        repo_formatter.format_repos([])
        captured = capsys.readouterr()
        assert "No repositories to display" in captured.out
        repo_formatter.console.print.assert_not_called()

    def test_rich_path_with_tags(self, repo_formatter, sample_repo):
        """A repo with tags yields a table that includes a Tags column."""
        repo_formatter.format_repos([sample_repo], show_tags=True)
        printed = repo_formatter.console.print.call_args.args[0]
        column_headers = [c.header for c in printed.columns]
        assert "Tags" in column_headers

    def test_rich_path_without_tags(self, repo_formatter, sample_repo):
        """Without show_tags, no Tags column is added."""
        repo_formatter.format_repos([sample_repo], show_tags=False)
        printed = repo_formatter.console.print.call_args.args[0]
        column_headers = [c.header for c in printed.columns]
        assert "Tags" not in column_headers

    def test_fallback_with_tags(self, sample_repo, capsys):
        """The fallback prints tags when show_tags=True."""
        with patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False):
            fmt = RepoFormatter(console=None)
            fmt.format_repos([sample_repo], show_tags=True)
        captured = capsys.readouterr()
        assert "/tmp/proj" in captured.out
        assert "python" in captured.out

    def test_fallback_without_tags(self, sample_repo, capsys):
        """The fallback without show_tags prints no Tags line."""
        with patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False):
            fmt = RepoFormatter(console=None)
            fmt.format_repos([sample_repo], show_tags=False)
        captured = capsys.readouterr()
        assert "/tmp/proj" in captured.out
        assert "Tags:" not in captured.out

    def test_description_truncated_to_40(self, recording_repo_formatter):
        """Long descriptions are truncated to 40 chars in the rendered table."""
        repo = {
            "path": "/p",
            "description": "x" * 100,
            "tags": [],
        }
        recording_repo_formatter.format_repos([repo], show_tags=False)
        text = _strip(recording_repo_formatter.console.export_text())
        # Only 40 of the 100 x's appear in the rendered row
        assert "x" * 40 in text
        assert "x" * 41 not in text

    def test_renders_path_and_description(self, recording_repo_formatter, sample_repo):
        """The rendered table includes the path and description text."""
        recording_repo_formatter.format_repos([sample_repo], show_tags=False)
        text = _strip(recording_repo_formatter.console.export_text())
        assert "/tmp/proj" in text
        assert "An example" in text
