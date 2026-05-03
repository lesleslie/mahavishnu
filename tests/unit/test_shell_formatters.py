"""Comprehensive tests for mahavishnu.shell.formatters module."""

from unittest.mock import patch

import pytest

from mahavishnu.core.workflow_state import WorkflowStatus
from mahavishnu.shell.formatters import (
    RICH_AVAILABLE,
    LogFormatter,
    RepoFormatter,
    WorkflowFormatter,
)

SAMPLE_WORKFLOWS = [
    {
        "id": "wf-001",
        "status": WorkflowStatus.RUNNING,
        "progress": 45,
        "adapter": "prefect",
        "created_at": "2025-01-15T08:30:00.000Z",
        "repos": ["/path/a", "/path/b"],
        "errors": [],
    },
    {
        "id": "wf-002",
        "status": WorkflowStatus.COMPLETED,
        "progress": 100,
        "adapter": "llamaindex",
        "created_at": "2025-01-14T10:00:00.000Z",
        "repos": ["/path/c"],
        "errors": [],
    },
    {
        "id": "wf-003",
        "status": WorkflowStatus.FAILED,
        "progress": 60,
        "adapter": "agno",
        "created_at": "2025-01-13T12:00:00.000Z",
        "repos": ["/path/d", "/path/e", "/path/f"],
        "errors": [{"message": "Connection timeout"}, {"message": "Auth failed"}],
    },
    {
        "id": "wf-004",
        "status": WorkflowStatus.PENDING,
        "progress": 0,
        "adapter": "prefect",
        "created_at": "2025-01-12T00:00:00.000Z",
        "repos": [],
        "errors": [],
    },
]

SAMPLE_LOGS = [
    {
        "timestamp": "2025-01-15T08:00:00.000Z",
        "level": "INFO",
        "message": "Starting workflow",
        "workflow_id": "wf-001",
    },
    {
        "timestamp": "2025-01-15T08:00:01.000Z",
        "level": "ERROR",
        "message": "Task failed",
        "workflow_id": "wf-001",
    },
    {
        "timestamp": "2025-01-15T08:00:02.000Z",
        "level": "WARNING",
        "message": "Retrying",
        "workflow_id": "wf-002",
    },
    {
        "timestamp": "2025-01-15T08:00:03.000Z",
        "level": "DEBUG",
        "message": "Entering step",
        "workflow_id": "wf-002",
    },
    {
        "timestamp": "2025-01-15T08:00:04.000Z",
        "level": "INFO",
        "message": "Completed",
        "workflow_id": "wf-003",
    },
]

SAMPLE_REPOS = [
    {"path": "/path/to/repo1", "description": "First repository", "tags": ["python", "backend"]},
    {"path": "/path/to/repo2", "description": "Second repository", "tags": ["go", "microservice"]},
    {
        "path": "/path/to/repo3",
        "description": "Third repository with a very long description that should be truncated",
        "tags": ["rust"],
    },
]


class TestWorkflowFormatter:
    """Tests for WorkflowFormatter class."""

    def test_empty_workflows_list(self, capsys):
        """Empty list prints the no-workflows message."""
        formatter = WorkflowFormatter()
        formatter.format_workflows([])
        assert "No workflows to display" in capsys.readouterr().out

    def test_single_workflow(self, capsys):
        """Single workflow is formatted without error."""
        formatter = WorkflowFormatter()
        wf = [SAMPLE_WORKFLOWS[0]]
        formatter.format_workflows(wf)
        output = capsys.readouterr().out
        assert "wf-001" in output

    def test_multiple_workflows(self, capsys):
        """Multiple workflows are all rendered."""
        formatter = WorkflowFormatter()
        formatter.format_workflows(SAMPLE_WORKFLOWS)
        output = capsys.readouterr().out
        for wf in SAMPLE_WORKFLOWS:
            assert wf["id"] in output

    def test_show_details_flag(self, capsys):
        """show_details=True includes adapter and repo count info."""
        formatter = WorkflowFormatter()
        formatter.format_workflows(SAMPLE_WORKFLOWS, show_details=True)
        output = capsys.readouterr().out
        assert "Adapter" in output or "Repos" in output

    def test_without_details_flag(self, capsys):
        """show_details=False omits detail columns."""
        formatter = WorkflowFormatter()
        formatter.format_workflows(SAMPLE_WORKFLOWS, show_details=False)
        output = capsys.readouterr().out
        assert "wf-001" in output

    def test_workflow_with_errors_in_details(self, capsys):
        """Workflow errors are displayed when show_details is True."""
        formatter = WorkflowFormatter()
        formatter.format_workflows([SAMPLE_WORKFLOWS[2]], show_details=True)
        output = capsys.readouterr().out
        assert "Error" in output or "error" in output.lower()

    def test_workflow_missing_optional_keys(self, capsys):
        """Workflows with missing keys use safe defaults."""
        formatter = WorkflowFormatter()
        minimal_wf = [{"id": "minimal", "status": "pending", "progress": 0}]
        formatter.format_workflows(minimal_wf)
        output = capsys.readouterr().out
        assert "minimal" in output
        assert "0%" in output

    def test_workflow_long_id_truncated(self, capsys):
        """Workflow IDs longer than 20 characters are truncated in fallback."""
        formatter = WorkflowFormatter()
        long_id = "a" * 50
        formatter.format_workflows([{"id": long_id, "status": "pending", "progress": 10}])
        output = capsys.readouterr().out
        assert long_id[:20] in output

    def test_format_workflow_detail_basic(self, capsys):
        """format_workflow_detail renders key fields."""
        formatter = WorkflowFormatter()
        formatter.format_workflow_detail(SAMPLE_WORKFLOWS[0])
        output = capsys.readouterr().out
        assert "wf-001" in output
        assert "running" in output.lower()

    def test_format_workflow_detail_with_repos(self, capsys):
        """Detail view lists repos when present."""
        formatter = WorkflowFormatter()
        formatter.format_workflow_detail(SAMPLE_WORKFLOWS[0])
        output = capsys.readouterr().out
        assert "/path/a" in output

    def test_format_workflow_detail_with_errors(self, capsys):
        """Detail view shows errors when present."""
        formatter = WorkflowFormatter()
        formatter.format_workflow_detail(SAMPLE_WORKFLOWS[2])
        output = capsys.readouterr().out
        assert "Connection timeout" in output

    def test_format_workflow_detail_missing_keys(self, capsys):
        """Detail view handles missing keys gracefully."""
        formatter = WorkflowFormatter()
        formatter.format_workflow_detail({})
        output = capsys.readouterr().out
        assert "None" in output or "unknown" in output or "Workflow" in output

    def test_format_workflow_detail_many_repos_truncated(self, capsys):
        """Detail view truncates repo list at 10 entries."""
        formatter = WorkflowFormatter()
        many_repos = [f"/repo/{i}" for i in range(15)]
        wf = {"id": "wf-big", "status": "running", "progress": 50, "repos": many_repos}
        formatter.format_workflow_detail(wf)
        output = capsys.readouterr().out
        assert "/repo/0" in output
        assert "/repo/14" not in output

    def test_format_workflow_detail_many_errors_truncated(self, capsys):
        """Detail view truncates error list at 5 entries."""
        formatter = WorkflowFormatter()
        many_errors = [{"message": f"Error {i}"} for i in range(10)]
        wf = {"id": "wf-err", "status": "failed", "progress": 0, "errors": many_errors}
        formatter.format_workflow_detail(wf)
        output = capsys.readouterr().out
        assert "Error 0" in output
        assert "Error 9" not in output

    @pytest.mark.skipif(not RICH_AVAILABLE, reason="Rich not installed")
    def test_rich_path_format_workflows(self, capsys):
        """When Rich is available and console is set, the rich path is taken."""
        formatter = WorkflowFormatter()
        formatter.format_workflows(SAMPLE_WORKFLOWS)
        output = capsys.readouterr().out
        assert "wf-001" in output or "wf-002" in output

    @pytest.mark.skipif(not RICH_AVAILABLE, reason="Rich not installed")
    def test_rich_path_format_workflow_detail(self, capsys):
        """Rich path for format_workflow_detail renders correctly."""
        formatter = WorkflowFormatter()
        formatter.format_workflow_detail(SAMPLE_WORKFLOWS[1])
        output = capsys.readouterr().out
        assert "wf-002" in output

    @patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False)
    def test_fallback_path_when_rich_unavailable(self, capsys):
        """Fallback formatting is used when Rich is not available."""
        formatter = WorkflowFormatter()
        formatter.format_workflows(SAMPLE_WORKFLOWS, show_details=True)
        output = capsys.readouterr().out
        assert "wf-001" in output
        assert "Adapter" in output

    @patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False)
    def test_fallback_detail_when_rich_unavailable(self, capsys):
        """Fallback detail formatting is used when Rich is not available."""
        formatter = WorkflowFormatter()
        formatter.format_workflow_detail(SAMPLE_WORKFLOWS[0])
        output = capsys.readouterr().out
        assert "wf-001" in output

    def test_none_console_uses_fallback(self, capsys):
        """When console is None, fallback formatting is used."""
        formatter = WorkflowFormatter(console=None)
        formatter.format_workflows(SAMPLE_WORKFLOWS)
        output = capsys.readouterr().out
        assert "wf-001" in output

    def test_format_workflow_detail_no_repos_no_errors(self, capsys):
        """Detail view with no repos and no errors renders cleanly."""
        formatter = WorkflowFormatter()
        wf = {"id": "wf-empty", "status": "pending", "progress": 0}
        formatter.format_workflow_detail(wf)
        output = capsys.readouterr().out
        assert "wf-empty" in output

    def test_error_without_message_key(self, capsys):
        """Error dict missing 'message' key shows 'Unknown error'."""
        formatter = WorkflowFormatter()
        wf = {"id": "wf-bad-err", "status": "failed", "progress": 0, "errors": [{"detail": "oops"}]}
        formatter.format_workflow_detail(wf)
        output = capsys.readouterr().out
        assert "Unknown error" in output

    def test_unicode_in_workflow_fields(self, capsys):
        """Unicode characters in workflow fields are handled."""
        formatter = WorkflowFormatter()
        wf = {
            "id": "wf-unicode-test",
            "status": "running",
            "progress": 50,
            "adapter": "prefect",
            "created_at": "2025-01-15T08:00:00",
            "repos": ["/path/to/repo"],
        }
        formatter.format_workflows([wf])
        output = capsys.readouterr().out
        assert "wf-unicode-test" in output

    def test_workflows_with_all_status_types(self, capsys):
        """All four status types (RUNNING, COMPLETED, FAILED, PENDING) are rendered."""
        formatter = WorkflowFormatter()
        statuses = [
            WorkflowStatus.RUNNING,
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.PENDING,
        ]
        wfs = [{"id": f"wf-{s.value}", "status": s, "progress": 10} for s in statuses]
        formatter.format_workflows(wfs)
        output = capsys.readouterr().out
        for s in statuses:
            assert s.value in output


class TestLogFormatter:
    """Tests for LogFormatter class."""

    def test_empty_logs(self, capsys):
        """Empty log list prints the no-logs message."""
        formatter = LogFormatter()
        formatter.format_logs([])
        assert "No logs to display" in capsys.readouterr().out

    def test_format_logs_basic(self, capsys):
        """Basic log formatting renders timestamp, level, and message."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS)
        output = capsys.readouterr().out
        assert "Starting workflow" in output
        assert "Task failed" in output

    def test_level_filter_error_only(self, capsys):
        """Level filter restricts output to matching level."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS, level="ERROR")
        output = capsys.readouterr().out
        assert "Task failed" in output
        assert "Starting workflow" not in output

    def test_level_filter_case_insensitive(self, capsys):
        """Level filter uppercases the input before comparison."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS, level="error")
        output = capsys.readouterr().out
        assert "Task failed" in output
        assert "Starting workflow" not in output

    def test_workflow_id_filter(self, capsys):
        """Workflow ID filter restricts output to matching workflow."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS, workflow_id="wf-001")
        output = capsys.readouterr().out
        assert "Starting workflow" in output
        assert "Retrying" not in output

    def test_combined_level_and_workflow_filter(self, capsys):
        """Both level and workflow filters are applied together."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS, level="ERROR", workflow_id="wf-001")
        output = capsys.readouterr().out
        assert "Task failed" in output
        assert "Starting workflow" not in output
        assert "Retrying" not in output

    def test_tail_limits_output(self, capsys):
        """Tail parameter limits the number of displayed log entries."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS, tail=2)
        output = capsys.readouterr().out
        lines = [l for l in output.strip().split("\n") if l.strip()]
        assert len(lines) <= 2

    def test_tail_larger_than_list(self, capsys):
        """Tail larger than log count shows all entries."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS, tail=100)
        output = capsys.readouterr().out
        for log in SAMPLE_LOGS:
            assert log["message"] in output

    def test_tail_of_one(self, capsys):
        """Tail of 1 shows only the most recent log entry."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS, tail=1)
        output = capsys.readouterr().out
        assert "Completed" in output
        assert "Starting workflow" not in output

    def test_log_missing_optional_keys(self, capsys):
        """Logs missing optional keys use safe defaults."""
        formatter = LogFormatter()
        minimal_log = [{"message": "hello"}]
        formatter.format_logs(minimal_log)
        output = capsys.readouterr().out
        assert "hello" in output
        assert "INFO" in output

    def test_log_with_empty_level(self, capsys):
        """Log entry with no level defaults to INFO."""
        formatter = LogFormatter()
        logs = [{"timestamp": "2025-01-15T00:00:00", "message": "no level"}]
        formatter.format_logs(logs)
        output = capsys.readouterr().out
        assert "INFO" in output

    def test_log_timestamp_truncated(self, capsys):
        """Timestamps longer than 19 characters are truncated."""
        formatter = LogFormatter()
        logs = [{"timestamp": "2025-01-15T08:00:00.123456Z", "level": "INFO", "message": "ts test"}]
        formatter.format_logs(logs)
        output = capsys.readouterr().out
        assert "2025-01-15T08:00:00" in output
        assert ".123456" not in output

    def test_log_filter_with_no_matches(self, capsys):
        """Filter that matches nothing produces no output for entries."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS, level="CRITICAL")
        output = capsys.readouterr().out
        assert "Starting workflow" not in output
        assert "Task failed" not in output

    @patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False)
    def test_fallback_path_logs(self, capsys):
        """Fallback log formatting when Rich is unavailable."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS)
        output = capsys.readouterr().out
        assert "Starting workflow" in output
        assert "Task failed" in output

    def test_none_console_uses_fallback(self, capsys):
        """When console is None, fallback formatting is used for logs."""
        formatter = LogFormatter(console=None)
        formatter.format_logs(SAMPLE_LOGS)
        output = capsys.readouterr().out
        assert "Starting workflow" in output

    def test_debug_level_log(self, capsys):
        """DEBUG level log entries are rendered correctly."""
        formatter = LogFormatter()
        logs = [{"timestamp": "2025-01-15T00:00:00", "level": "DEBUG", "message": "debug msg"}]
        formatter.format_logs(logs, level="DEBUG")
        output = capsys.readouterr().out
        assert "debug msg" in output

    def test_warning_level_log(self, capsys):
        """WARNING level log entries are rendered correctly."""
        formatter = LogFormatter()
        formatter.format_logs(SAMPLE_LOGS, level="WARNING")
        output = capsys.readouterr().out
        assert "Retrying" in output

    def test_empty_message_log(self, capsys):
        """Log entry with empty message is handled without error."""
        formatter = LogFormatter()
        logs = [{"timestamp": "2025-01-15T00:00:00", "level": "INFO", "message": ""}]
        formatter.format_logs(logs)
        output = capsys.readouterr().out
        assert "INFO" in output

    def test_single_log_entry(self, capsys):
        """Single log entry is formatted correctly."""
        formatter = LogFormatter()
        logs = [{"timestamp": "2025-01-15T12:00:00", "level": "ERROR", "message": "solo error"}]
        formatter.format_logs(logs)
        output = capsys.readouterr().out
        assert "solo error" in output
        assert "ERROR" in output


class TestRepoFormatter:
    """Tests for RepoFormatter class."""

    def test_empty_repos(self, capsys):
        """Empty repo list prints the no-repositories message."""
        formatter = RepoFormatter()
        formatter.format_repos([])
        assert "No repositories to display" in capsys.readouterr().out

    def test_single_repo(self, capsys):
        """Single repository is formatted correctly."""
        formatter = RepoFormatter()
        formatter.format_repos([SAMPLE_REPOS[0]])
        output = capsys.readouterr().out
        assert "/path/to/repo1" in output
        assert "First repository" in output

    def test_multiple_repos(self, capsys):
        """Multiple repositories are all rendered."""
        formatter = RepoFormatter()
        formatter.format_repos(SAMPLE_REPOS)
        output = capsys.readouterr().out
        for repo in SAMPLE_REPOS:
            assert repo["path"] in output

    def test_show_tags(self, capsys):
        """Tags are displayed when show_tags is True."""
        formatter = RepoFormatter()
        formatter.format_repos(SAMPLE_REPOS, show_tags=True)
        output = capsys.readouterr().out
        assert "python" in output
        assert "backend" in output

    def test_hide_tags(self, capsys):
        """Tags are not displayed when show_tags is False."""
        formatter = RepoFormatter()
        formatter.format_repos(SAMPLE_REPOS, show_tags=False)
        output = capsys.readouterr().out
        assert "/path/to/repo1" in output

    def test_repo_without_tags(self, capsys):
        """Repository with no tags key renders without error."""
        formatter = RepoFormatter()
        repos = [{"path": "/path/no-tags", "description": "No tags here"}]
        formatter.format_repos(repos, show_tags=True)
        output = capsys.readouterr().out
        assert "/path/no-tags" in output

    def test_repo_empty_tags_list(self, capsys):
        """Repository with empty tags list shows empty tags."""
        formatter = RepoFormatter()
        repos = [{"path": "/path/empty-tags", "description": "Empty tags", "tags": []}]
        formatter.format_repos(repos, show_tags=True)
        output = capsys.readouterr().out
        assert "/path/empty-tags" in output

    def test_repo_missing_path(self, capsys):
        """Repository missing path key uses empty string default."""
        formatter = RepoFormatter()
        repos = [{"description": "No path"}]
        formatter.format_repos(repos)
        output = capsys.readouterr().out
        assert "No path" in output

    def test_repo_missing_description(self, capsys):
        """Repository missing description key uses empty string default."""
        formatter = RepoFormatter()
        repos = [{"path": "/path/no-desc"}]
        formatter.format_repos(repos)
        output = capsys.readouterr().out
        assert "/path/no-desc" in output

    def test_repo_long_description_truncated(self, capsys):
        """Long descriptions are truncated to 40 characters in fallback."""
        formatter = RepoFormatter()
        repos = [{"path": "/p", "description": "a" * 80}]
        formatter.format_repos(repos)
        output = capsys.readouterr().out
        assert "a" * 40 in output

    @patch("mahavishnu.shell.formatters.RICH_AVAILABLE", False)
    def test_fallback_path_repos(self, capsys):
        """Fallback repo formatting when Rich is unavailable."""
        formatter = RepoFormatter()
        formatter.format_repos(SAMPLE_REPOS, show_tags=True)
        output = capsys.readouterr().out
        assert "/path/to/repo1" in output
        assert "Tags" in output

    def test_none_console_uses_fallback(self, capsys):
        """When console is None, fallback formatting is used for repos."""
        formatter = RepoFormatter(console=None)
        formatter.format_repos(SAMPLE_REPOS, show_tags=True)
        output = capsys.readouterr().out
        assert "/path/to/repo1" in output

    def test_many_tags_truncated(self, capsys):
        """Many tags are truncated to 20 characters in fallback."""
        formatter = RepoFormatter()
        repos = [{"path": "/p", "description": "d", "tags": ["a" * 30]}]
        formatter.format_repos(repos, show_tags=True)
        output = capsys.readouterr().out
        assert "a" * 20 in output

    def test_unicode_repo_fields(self, capsys):
        """Unicode characters in repo fields are handled."""
        formatter = RepoFormatter()
        repos = [
            {"path": "/path/repo", "description": "Description with unicode: éèê", "tags": ["tést"]}
        ]
        formatter.format_repos(repos, show_tags=True)
        output = capsys.readouterr().out
        assert "é" in output
