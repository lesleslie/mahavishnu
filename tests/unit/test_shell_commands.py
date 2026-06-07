"""Unit tests for mahavishnu.shell.shell_commands (ps, top, errors, sync)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.workflow_state import WorkflowStatus
from mahavishnu.shell import shell_commands
from mahavishnu.shell.shell_commands import errors, ps, sync, top

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def app_mock():
    """MahavishnuApp mock with workflow_state_manager and opensearch_integration."""
    app = MagicMock()
    app.workflow_state_manager = MagicMock()
    app.opensearch_integration = MagicMock()
    return app


@pytest.fixture
def make_app():
    """Factory that returns a fresh app mock for tests that need isolated state."""

    def _factory():
        app = MagicMock()
        app.workflow_state_manager = MagicMock()
        app.opensearch_integration = MagicMock()
        return app

    return _factory


@pytest.fixture
def sample_workflow():
    """A single workflow dictionary."""
    return {
        "id": "wf-1",
        "status": WorkflowStatus.RUNNING,
        "progress": 50,
        "adapter": "prefect",
        "created_at": "2026-01-01T00:00:00",
        "repos": ["repo-a"],
        "errors": [],
    }


# =============================================================================
# ps tests
# =============================================================================


@pytest.mark.unit
class TestPs:
    """Tests for the `ps` shell command."""

    async def test_ps_lists_workflows_via_state_manager(self, make_app, sample_workflow):
        """ps() calls list_workflows and uses a WorkflowFormatter."""
        app = make_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[sample_workflow])

        with patch.object(shell_commands, "WorkflowFormatter") as fmt_cls:
            fmt = MagicMock()
            fmt_cls.return_value = fmt
            await ps(app)

        app.workflow_state_manager.list_workflows.assert_awaited_once_with(limit=100)
        fmt.format_workflows.assert_called_once()
        workflows_arg = fmt.format_workflows.call_args.args[0]
        assert workflows_arg == [sample_workflow]
        assert fmt.format_workflows.call_args.kwargs.get("show_details") is False

    async def test_ps_with_empty_workflows(self, make_app, capsys):
        """ps() with no workflows still calls the formatter (formatter handles empty)."""
        app = make_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        with patch.object(shell_commands, "WorkflowFormatter") as fmt_cls:
            fmt = MagicMock()
            fmt_cls.return_value = fmt
            await ps(app)

        fmt.format_workflows.assert_called_once_with([], show_details=False)


# =============================================================================
# top tests
# =============================================================================


@pytest.mark.unit
class TestTop:
    """Tests for the `top` shell command."""

    async def test_top_filters_by_running_status(self, make_app, sample_workflow):
        """top() filters workflows by RUNNING status with limit=20."""
        app = make_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[sample_workflow])

        with patch.object(shell_commands, "WorkflowFormatter") as fmt_cls:
            fmt = MagicMock()
            fmt_cls.return_value = fmt
            await top(app)

        app.workflow_state_manager.list_workflows.assert_awaited_once_with(
            status=WorkflowStatus.RUNNING, limit=20
        )

    async def test_top_uses_details(self, make_app, sample_workflow):
        """top() uses show_details=True when there are workflows."""
        app = make_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[sample_workflow])

        with patch.object(shell_commands, "WorkflowFormatter") as fmt_cls:
            fmt = MagicMock()
            fmt_cls.return_value = fmt
            await top(app)

        fmt.format_workflows.assert_called_once_with([sample_workflow], show_details=True)

    async def test_top_empty_prints_message(self, make_app, capsys):
        """top() prints 'No active workflows' and skips the formatter when empty."""
        app = make_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        with patch.object(shell_commands, "WorkflowFormatter") as fmt_cls:
            fmt = MagicMock()
            fmt_cls.return_value = fmt
            await top(app)

        captured = capsys.readouterr()
        assert "No active workflows" in captured.out
        fmt.format_workflows.assert_not_called()


# =============================================================================
# errors tests
# =============================================================================


@pytest.mark.unit
class TestErrors:
    """Tests for the `errors` shell command."""

    async def test_errors_empty_list(self, make_app, capsys):
        """errors() with no workflows prints 'No errors found'."""
        app = make_app()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        with patch.object(shell_commands, "LogFormatter") as fmt_cls:
            fmt = MagicMock()
            fmt_cls.return_value = fmt
            await errors(app, limit=5)

        captured = capsys.readouterr()
        assert "No errors found" in captured.out
        fmt.format_logs.assert_not_called()

    async def test_errors_collects_from_workflows(self, make_app):
        """errors() flattens errors from all workflows and sorts by timestamp desc."""
        app = make_app()
        workflows = [
            {
                "id": "wf-1",
                "errors": [
                    {"timestamp": "2026-01-02T00:00:00", "message": "old"},
                    {"timestamp": "2026-01-03T00:00:00", "message": "new"},
                ],
            },
            {
                "id": "wf-2",
                "errors": [
                    {"timestamp": "2026-01-01T00:00:00", "message": "older"},
                ],
            },
        ]
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=workflows)

        with patch.object(shell_commands, "LogFormatter") as fmt_cls:
            fmt = MagicMock()
            fmt_cls.return_value = fmt
            await errors(app, limit=10)

        # Verify the formatted call received sorted entries
        fmt.format_logs.assert_called_once()
        passed_logs = fmt.format_logs.call_args.args[0]
        # Newest first
        timestamps = [e["timestamp"] for e in passed_logs]
        assert timestamps == sorted(timestamps, reverse=True)
        # All errors surfaced
        assert len(passed_logs) == 3
        # Errors carry workflow_id, level, and message
        for entry in passed_logs:
            assert "workflow_id" in entry
            assert entry["level"] == "ERROR"
            assert "message" in entry

    async def test_errors_respects_limit(self, make_app):
        """errors() truncates the result to the requested limit."""
        app = make_app()
        workflows = [
            {
                "id": f"wf-{i}",
                "errors": [{"timestamp": f"2026-01-0{i + 1}T00:00:00", "message": f"err{i}"}],
            }
            for i in range(5)
        ]
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=workflows)

        with patch.object(shell_commands, "LogFormatter") as fmt_cls:
            fmt = MagicMock()
            fmt_cls.return_value = fmt
            await errors(app, limit=2)

        fmt.format_logs.assert_called_once()
        passed_logs = fmt.format_logs.call_args.args[0]
        assert len(passed_logs) == 2
        # The tail kwarg passed to format_logs is the limit
        assert fmt.format_logs.call_args.kwargs.get("tail") == 2

    async def test_errors_handles_missing_timestamp(self, make_app):
        """Errors without timestamps are still included (None sorts as empty)."""
        app = make_app()
        workflows = [
            {
                "id": "wf-1",
                "errors": [
                    {"message": "no-ts"},
                    {"timestamp": "2026-01-01T00:00:00", "message": "with-ts"},
                ],
            },
        ]
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=workflows)

        with patch.object(shell_commands, "LogFormatter") as fmt_cls:
            fmt = MagicMock()
            fmt_cls.return_value = fmt
            await errors(app, limit=10)

        passed_logs = fmt.format_logs.call_args.args[0]
        assert len(passed_logs) == 2


# =============================================================================
# sync tests
# =============================================================================


@pytest.mark.unit
class TestSync:
    """Tests for the `sync` shell command."""

    async def test_sync_calls_health_check_and_stats(self, make_app, capsys):
        """sync() runs health_check + get_workflow_stats and prints summary."""
        app = make_app()
        app.opensearch_integration.health_check = AsyncMock(return_value={"status": "green"})
        app.opensearch_integration.get_workflow_stats = AsyncMock(
            return_value={"total_workflows": 42}
        )

        await sync(app)

        app.opensearch_integration.health_check.assert_awaited_once()
        app.opensearch_integration.get_workflow_stats.assert_awaited_once()
        captured = capsys.readouterr()
        assert "Syncing workflow state from OpenSearch" in captured.out
        assert "OpenSearch status: green" in captured.out
        assert "Total workflows: 42" in captured.out
        assert "Sync complete" in captured.out

    async def test_sync_handles_missing_status(self, make_app, capsys):
        """When health_check omits 'status', the printed value defaults to 'unknown'."""
        app = make_app()
        app.opensearch_integration.health_check = AsyncMock(return_value={})
        app.opensearch_integration.get_workflow_stats = AsyncMock(
            return_value={"total_workflows": 0}
        )

        await sync(app)

        captured = capsys.readouterr()
        assert "OpenSearch status: unknown" in captured.out
        assert "Total workflows: 0" in captured.out

    async def test_sync_raises_when_health_check_fails(self, make_app):
        """If health_check raises, sync propagates the exception."""
        app = make_app()
        app.opensearch_integration.health_check = AsyncMock(side_effect=RuntimeError("boom"))
        app.opensearch_integration.get_workflow_stats = AsyncMock(
            return_value={"total_workflows": 0}
        )

        with pytest.raises(RuntimeError, match="boom"):
            await sync(app)
