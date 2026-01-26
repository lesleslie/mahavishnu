"""Test shell formatters."""

import pytest

from mahavishnu.shell.formatters import WorkflowFormatter, LogFormatter, RepoFormatter


@pytest.mark.unit
def test_workflow_formatter_with_empty_list():
    """Test workflow formatter handles empty list."""
    formatter = WorkflowFormatter()
    formatter.format_workflows([])  # Should not raise


@pytest.mark.unit
def test_workflow_formatter_with_single_workflow():
    """Test workflow formatter displays single workflow."""
    formatter = WorkflowFormatter()
    workflows = [
        {
            "id": "test-workflow-1",
            "status": "completed",
            "progress": 100,
            "adapter": "prefect",
            "created_at": "2025-01-25T12:00:00",
            "repos": ["/path/to/repo"],
        }
    ]
    formatter.format_workflows(workflows)  # Should not raise


@pytest.mark.unit
def test_log_formatter_with_filters():
    """Test log formatter with level filter."""
    formatter = LogFormatter()
    logs = [
        {
            "timestamp": "2025-01-25T10:00:00",
            "level": "ERROR",
            "message": "Test error",
            "workflow_id": "wf-1",
        },
        {
            "timestamp": "2025-01-25T10:00:01",
            "level": "INFO",
            "message": "Test info",
            "workflow_id": "wf-1",
        },
    ]
    formatter.format_logs(logs, level="ERROR")  # Should only show ERROR


@pytest.mark.unit
def test_log_formatter_with_workflow_filter():
    """Test log formatter filters by workflow ID."""
    formatter = LogFormatter()
    logs = [
        {
            "timestamp": "2025-01-25T10:00:00",
            "level": "ERROR",
            "message": "Error in workflow 1",
            "workflow_id": "wf-1",
        },
        {
            "timestamp": "2025-01-25T10:00:01",
            "level": "ERROR",
            "message": "Error in workflow 2",
            "workflow_id": "wf-2",
        },
    ]
    formatter.format_logs(logs, workflow_id="wf-1")  # Should only show wf-1


@pytest.mark.unit
def test_repo_formatter_with_empty_list():
    """Test repo formatter handles empty list."""
    formatter = RepoFormatter()
    formatter.format_repos([])  # Should not raise


@pytest.mark.unit
def test_repo_formatter_with_repos():
    """Test repo formatter displays repositories."""
    formatter = RepoFormatter()
    repos = [
        {
            "path": "/path/to/repo1",
            "description": "Test repository 1",
            "tags": ["python", "testing"],
        },
        {
            "path": "/path/to/repo2",
            "description": "Test repository 2",
            "tags": ["python", "integration"],
        },
    ]
    formatter.format_repos(repos, show_tags=True)  # Should not raise
