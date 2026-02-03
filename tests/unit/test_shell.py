"""Unit tests for Mahavishnu admin shell functionality."""

from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.workflow_state import WorkflowStatus
from mahavishnu.shell import MahavishnuShell
from mahavishnu.shell.formatters import LogFormatter, RepoFormatter, WorkflowFormatter
from mahavishnu.shell.shell_commands import errors, ps, sync, top


@pytest.mark.unit
class TestShellAdapter:
    """Test MahavishnuShell adapter initialization and configuration."""

    def test_shell_initialization(self):
        """Test shell initializes with MahavishnuApp."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.adapters = {"prefect": MagicMock(), "llamaindex": MagicMock()}

        shell = MahavishnuShell(mock_app)

        assert shell.app == mock_app
        assert hasattr(shell, "workflow_formatter")
        assert hasattr(shell, "log_formatter")
        assert hasattr(shell, "repo_formatter")

    def test_shell_namespace_contains_helpers(self):
        """Test shell namespace includes helper functions."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.adapters = {"prefect": MagicMock()}

        shell = MahavishnuShell(mock_app)

        # Check namespace has required functions
        assert "ps" in shell.namespace
        assert "top" in shell.namespace
        assert "errors" in shell.namespace
        assert "sync" in shell.namespace
        assert "WorkflowStatus" in shell.namespace
        assert "MahavishnuApp" in shell.namespace

    def test_shell_banner_contains_adapter_info(self):
        """Test shell banner displays available adapters."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.adapters = {"prefect": MagicMock(), "agno": MagicMock()}

        shell = MahavishnuShell(mock_app)
        banner = shell._get_banner()

        assert "Mahavishnu Admin Shell" in banner
        assert "prefect" in banner
        assert "agno" in banner
        assert "ps()" in banner
        assert "top()" in banner

    def test_shell_helpers_are_callable(self):
        """Test shell helper functions are callable."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.adapters = {}

        shell = MahavishnuShell(mock_app)

        # All helpers should be callable
        assert callable(shell.namespace["ps"])
        assert callable(shell.namespace["top"])
        assert callable(shell.namespace["errors"])
        assert callable(shell.namespace["sync"])


@pytest.mark.unit
class TestShellHelpers:
    """Test shell helper functions."""

    @pytest.mark.asyncio
    async def test_ps_shows_all_workflows(self):
        """Test ps() helper displays all workflows."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.workflow_state_manager = AsyncMock()
        mock_app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf-1",
                    "status": WorkflowStatus.COMPLETED,
                    "progress": 100,
                    "adapter": "prefect",
                    "created_at": "2025-01-25T12:00:00",
                },
                {
                    "id": "wf-2",
                    "status": WorkflowStatus.RUNNING,
                    "progress": 45,
                    "adapter": "agno",
                    "created_at": "2025-01-25T13:00:00",
                },
            ]
        )

        # Should not raise
        await ps(mock_app)

        # Verify list_workflows was called
        mock_app.workflow_state_manager.list_workflows.assert_called_once_with(limit=100)

    @pytest.mark.asyncio
    async def test_ps_handles_empty_workflow_list(self):
        """Test ps() helper handles empty workflow list."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.workflow_state_manager = AsyncMock()
        mock_app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        # Should not raise
        await ps(mock_app)

    @pytest.mark.asyncio
    async def test_top_shows_active_workflows(self):
        """Test top() helper filters running workflows."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.workflow_state_manager = AsyncMock()
        mock_app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf-1",
                    "status": WorkflowStatus.RUNNING,
                    "progress": 75,
                    "adapter": "prefect",
                    "created_at": "2025-01-25T12:00:00",
                }
            ]
        )

        # Should not raise
        await top(mock_app)

        # Verify called with RUNNING status filter
        mock_app.workflow_state_manager.list_workflows.assert_called_once_with(
            status=WorkflowStatus.RUNNING, limit=20
        )

    @pytest.mark.asyncio
    async def test_top_handles_no_active_workflows(self):
        """Test top() helper displays message when no active workflows."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.workflow_state_manager = AsyncMock()
        mock_app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

        # Should not raise
        await top(mock_app)

    @pytest.mark.asyncio
    async def test_errors_shows_recent_errors(self):
        """Test errors() helper extracts and displays errors."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.workflow_state_manager = AsyncMock()
        mock_app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf-1",
                    "status": WorkflowStatus.FAILED,
                    "errors": [
                        {
                            "timestamp": "2025-01-25T12:00:00",
                            "message": "Task failed",
                        }
                    ],
                }
            ]
        )

        # Should not raise
        await errors(mock_app, limit=10)

        # Verify list_workflows was called
        mock_app.workflow_state_manager.list_workflows.assert_called_once_with(limit=100)

    @pytest.mark.asyncio
    async def test_errors_respects_limit(self):
        """Test errors() helper respects limit parameter."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.workflow_state_manager = AsyncMock()

        # Create workflow with many errors
        errors_list = [
            {"timestamp": f"2025-01-25T{i:02d}:00:00", "message": f"Error {i}"} for i in range(20)
        ]
        mock_app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[
                {
                    "id": "wf-1",
                    "status": WorkflowStatus.FAILED,
                    "errors": errors_list,
                }
            ]
        )

        # Should not raise
        await errors(mock_app, limit=5)

    @pytest.mark.asyncio
    async def test_errors_handles_no_errors(self):
        """Test errors() helper handles workflow with no errors."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.workflow_state_manager = AsyncMock()
        mock_app.workflow_state_manager.list_workflows = AsyncMock(
            return_value=[{"id": "wf-1", "status": WorkflowStatus.COMPLETED, "errors": []}]
        )

        # Should not raise
        await errors(mock_app, limit=10)

    @pytest.mark.asyncio
    async def test_sync_checks_opensearch_health(self):
        """Test sync() helper checks OpenSearch health."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.opensearch_integration = AsyncMock()
        mock_app.opensearch_integration.health_check = AsyncMock(return_value={"status": "green"})
        mock_app.opensearch_integration.get_workflow_stats = AsyncMock(
            return_value={"total_workflows": 42}
        )

        # Should not raise
        await sync(mock_app)

        # Verify health check was called
        mock_app.opensearch_integration.health_check.assert_called_once()
        mock_app.opensearch_integration.get_workflow_stats.assert_called_once()


@pytest.mark.unit
class TestWorkflowFormatter:
    """Test WorkflowFormatter class."""

    def test_format_workflows_with_empty_list(self):
        """Test formatter handles empty workflow list."""
        formatter = WorkflowFormatter()
        with patch("sys.stdout", new=StringIO()) as fake_out:
            formatter.format_workflows([])
            output = fake_out.getvalue()
            assert "No workflows to display" in output

    def test_format_workflows_with_single_workflow(self):
        """Test formatter displays single workflow."""
        formatter = WorkflowFormatter()
        workflows = [
            {
                "id": "wf-1",
                "status": WorkflowStatus.COMPLETED,
                "progress": 100,
                "adapter": "prefect",
                "created_at": "2025-01-25T12:00:00",
            }
        ]

        # Should not raise
        formatter.format_workflows(workflows)

    def test_format_workflows_with_show_details(self):
        """Test formatter shows details when requested."""
        formatter = WorkflowFormatter()
        workflows = [
            {
                "id": "wf-1",
                "status": WorkflowStatus.RUNNING,
                "progress": 50,
                "adapter": "agno",
                "created_at": "2025-01-25T12:00:00",
                "repos": ["/path/to/repo1", "/path/to/repo2"],
                "errors": [{"message": "Task failed"}],
            }
        ]

        # Should not raise
        formatter.format_workflows(workflows, show_details=True)

    def test_format_workflow_detail(self):
        """Test detailed workflow formatting."""
        formatter = WorkflowFormatter()
        workflow = {
            "id": "wf-123",
            "status": WorkflowStatus.FAILED,
            "progress": 75,
            "adapter": "prefect",
            "repos": ["/path/to/repo1"],
            "errors": [{"message": "Critical error"}],
        }

        # Should not raise
        formatter.format_workflow_detail(workflow)

    def test_status_style_mapping(self):
        """Test workflow status color mapping."""
        formatter = WorkflowFormatter()
        workflows = [
            {
                "id": "wf-1",
                "status": WorkflowStatus.PENDING,
                "progress": 0,
                "adapter": "test",
                "created_at": "",
            },
            {
                "id": "wf-2",
                "status": WorkflowStatus.RUNNING,
                "progress": 50,
                "adapter": "test",
                "created_at": "",
            },
            {
                "id": "wf-3",
                "status": WorkflowStatus.COMPLETED,
                "progress": 100,
                "adapter": "test",
                "created_at": "",
            },
            {
                "id": "wf-4",
                "status": WorkflowStatus.FAILED,
                "progress": 0,
                "adapter": "test",
                "created_at": "",
            },
        ]

        # Should not raise
        formatter.format_workflows(workflows)


@pytest.mark.unit
class TestLogFormatter:
    """Test LogFormatter class."""

    def test_format_logs_with_empty_list(self):
        """Test formatter handles empty log list."""
        formatter = LogFormatter()
        with patch("sys.stdout", new=StringIO()) as fake_out:
            formatter.format_logs([])
            output = fake_out.getvalue()
            assert "No logs to display" in output

    def test_format_logs_with_level_filter(self):
        """Test formatter filters by log level."""
        formatter = LogFormatter()
        logs = [
            {
                "timestamp": "2025-01-25T10:00:00",
                "level": "ERROR",
                "message": "Error 1",
                "workflow_id": "wf-1",
            },
            {
                "timestamp": "2025-01-25T10:00:01",
                "level": "INFO",
                "message": "Info 1",
                "workflow_id": "wf-1",
            },
            {
                "timestamp": "2025-01-25T10:00:02",
                "level": "ERROR",
                "message": "Error 2",
                "workflow_id": "wf-1",
            },
        ]

        # Should not raise
        formatter.format_logs(logs, level="ERROR")

    def test_format_logs_with_workflow_filter(self):
        """Test formatter filters by workflow ID."""
        formatter = LogFormatter()
        logs = [
            {
                "timestamp": "2025-01-25T10:00:00",
                "level": "ERROR",
                "message": "Error 1",
                "workflow_id": "wf-1",
            },
            {
                "timestamp": "2025-01-25T10:00:01",
                "level": "ERROR",
                "message": "Error 2",
                "workflow_id": "wf-2",
            },
        ]

        # Should not raise
        formatter.format_logs(logs, workflow_id="wf-1")

    def test_format_logs_with_tail_limit(self):
        """Test formatter respects tail limit."""
        formatter = LogFormatter()
        # Create 100 logs
        logs = [
            {
                "timestamp": f"2025-01-25T{i:02d}:00:00",
                "level": "INFO",
                "message": f"Log {i}",
                "workflow_id": "wf-1",
            }
            for i in range(100)
        ]

        # Should only show last 10
        formatter.format_logs(logs, tail=10)

    def test_format_logs_with_combined_filters(self):
        """Test formatter with level and workflow filters."""
        formatter = LogFormatter()
        logs = [
            {
                "timestamp": "2025-01-25T10:00:00",
                "level": "ERROR",
                "message": "Error 1",
                "workflow_id": "wf-1",
            },
            {
                "timestamp": "2025-01-25T10:00:01",
                "level": "INFO",
                "message": "Info 1",
                "workflow_id": "wf-1",
            },
            {
                "timestamp": "2025-01-25T10:00:02",
                "level": "ERROR",
                "message": "Error 2",
                "workflow_id": "wf-2",
            },
        ]

        # Should only show ERROR from wf-1
        formatter.format_logs(logs, level="ERROR", workflow_id="wf-1")


@pytest.mark.unit
class TestRepoFormatter:
    """Test RepoFormatter class."""

    def test_format_repos_with_empty_list(self):
        """Test formatter handles empty repo list."""
        formatter = RepoFormatter()
        with patch("sys.stdout", new=StringIO()) as fake_out:
            formatter.format_repos([])
            output = fake_out.getvalue()
            assert "No repositories to display" in output

    def test_format_repos_without_tags(self):
        """Test formatter displays repos without tags."""
        formatter = RepoFormatter()
        repos = [
            {"path": "/path/to/repo1", "description": "Test repo 1", "tags": ["python"]},
            {"path": "/path/to/repo2", "description": "Test repo 2", "tags": ["rust"]},
        ]

        # Should not raise
        formatter.format_repos(repos, show_tags=False)

    def test_format_repos_with_tags(self):
        """Test formatter displays repos with tags."""
        formatter = RepoFormatter()
        repos = [
            {
                "path": "/path/to/repo1",
                "description": "Test repository 1",
                "tags": ["python", "testing", "mcp"],
            }
        ]

        # Should not raise
        formatter.format_repos(repos, show_tags=True)

    def test_format_repos_with_missing_fields(self):
        """Test formatter handles repos with missing fields."""
        formatter = RepoFormatter()
        repos = [
            {"path": "/path/to/repo1"},  # Missing description and tags
            {"description": "Test repo 2"},  # Missing path
        ]

        # Should not raise
        formatter.format_repos(repos)


@pytest.mark.unit
class TestShellIntegration:
    """Integration tests for shell components."""

    def test_shell_helper_async_wrappers(self):
        """Test shell namespace helpers wrap async functions properly."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.adapters = {}

        shell = MahavishnuShell(mock_app)

        # Helpers should be lambda functions wrapping asyncio.run
        assert callable(shell.namespace["ps"])
        assert callable(shell.namespace["top"])
        assert callable(shell.namespace["errors"])
        assert callable(shell.namespace["sync"])

    def test_formatter_initialization(self):
        """Test all formatters are initialized."""
        mock_app = MagicMock(spec=MahavishnuApp)
        mock_app.adapters = {}

        shell = MahavishnuShell(mock_app)

        # All formatters should be instances
        assert isinstance(shell.workflow_formatter, WorkflowFormatter)
        assert isinstance(shell.log_formatter, LogFormatter)
        assert isinstance(shell.repo_formatter, RepoFormatter)
