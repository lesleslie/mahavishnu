"""Integration tests for test fixtures.

This module validates that all fixtures work correctly and can be
used in actual tests.
"""

import pytest
from tests.fixtures.workflow_fixtures import WorkflowFixtures
from tests.fixtures.shell_fixtures import ShellFixtures
from tests.fixtures.conftest import IntegrationFixtures


class TestWorkflowFixtures:
    """Test workflow fixtures."""

    def test_sample_workflow_fixture(self, sample_workflow):
        """Test sample_workflow fixture."""
        assert sample_workflow is not None
        assert sample_workflow["status"] == "running"
        assert sample_workflow["progress"] == 45
        assert "task" in sample_workflow
        assert "repos" in sample_workflow

    def test_completed_workflow_fixture(self, completed_workflow):
        """Test completed_workflow fixture."""
        assert completed_workflow is not None
        assert completed_workflow["status"] == "completed"
        assert completed_workflow["progress"] == 100
        assert len(completed_workflow["results"]) > 0

    def test_failed_workflow_fixture(self, failed_workflow):
        """Test failed_workflow fixture."""
        assert failed_workflow is not None
        assert failed_workflow["status"] == "failed"
        assert len(failed_workflow["errors"]) > 0
        assert "error" in failed_workflow["errors"][0]

    def test_partial_workflow_fixture(self, partial_workflow):
        """Test partial_workflow fixture."""
        assert partial_workflow is not None
        assert partial_workflow["status"] == "partial"
        assert len(partial_workflow["results"]) > 0
        assert len(partial_workflow["errors"]) > 0

    def test_pending_workflow_fixture(self, pending_workflow):
        """Test pending_workflow fixture."""
        assert pending_workflow is not None
        assert pending_workflow["status"] == "pending"
        assert pending_workflow["progress"] == 0
        assert len(pending_workflow["results"]) == 0

    def test_multiple_workflows_fixture(self, multiple_workflows):
        """Test multiple_workflows fixture."""
        assert multiple_workflows is not None
        assert len(multiple_workflows) == 5
        statuses = [wf["status"] for wf in multiple_workflows]
        assert "running" in statuses
        assert "completed" in statuses
        assert "failed" in statuses

    def test_workflow_state_manager_mock(self, mock_workflow_state_manager):
        """Test mock_workflow_state_manager fixture."""
        assert mock_workflow_state_manager is not None
        # It's an AsyncMock, so we can't call it directly in sync test
        assert hasattr(mock_workflow_state_manager, "create")
        assert hasattr(mock_workflow_state_manager, "get")
        assert hasattr(mock_workflow_state_manager, "update")

    def test_sample_task_fixture(self, sample_task):
        """Test sample_task fixture."""
        assert sample_task is not None
        assert sample_task["type"] == "code_sweep"
        assert "params" in sample_task
        assert "pattern" in sample_task["params"]

    def test_sample_repos_fixture(self, sample_repos):
        """Test sample_repos fixture."""
        assert sample_repos is not None
        assert len(sample_repos) == 3
        assert all(isinstance(repo, str) for repo in sample_repos)


class TestShellFixtures:
    """Test shell fixtures."""

    def test_mock_repos_list_fixture(self, mock_repos_list):
        """Test mock_repos_list fixture."""
        assert mock_repos_list is not None
        assert len(mock_repos_list) == 6
        assert all("path" in repo for repo in mock_repos_list)
        assert all("role" in repo for repo in mock_repos_list)

    def test_mock_workflow_status_fixture(self, mock_workflow_status):
        """Test mock_workflow_status fixture."""
        assert mock_workflow_status is not None
        assert isinstance(mock_workflow_status, str)
        assert "running" in mock_workflow_status

    def test_mock_error_output_fixture(self, mock_error_output):
        """Test mock_error_output fixture."""
        assert mock_error_output is not None
        assert len(mock_error_output) == 3
        assert all("level" in error for error in mock_error_output)
        assert all(error["level"] == "ERROR" for error in mock_error_output)

    def test_mock_terminal_output_fixture(self, mock_terminal_output):
        """Test mock_terminal_output fixture."""
        assert mock_terminal_output is not None
        assert "raw" in mock_terminal_output
        assert "plain" in mock_terminal_output
        assert "lines" in mock_terminal_output

    def test_mock_shell_commands_fixture(self, mock_shell_commands):
        """Test mock_shell_commands fixture."""
        assert mock_shell_commands is not None
        assert "ps" in mock_shell_commands
        assert "help" in mock_shell_commands
        assert "errors" in mock_shell_commands

    def test_mock_role_output_fixture(self, mock_role_output):
        """Test mock_role_output fixture."""
        assert mock_role_output is not None
        assert "roles" in mock_role_output
        assert len(mock_role_output["roles"]) > 0

    def test_mock_opensearch_logs_fixture(self, mock_opensearch_logs):
        """Test mock_opensearch_logs fixture."""
        assert mock_opensearch_logs is not None
        assert len(mock_opensearch_logs) == 4
        assert all("timestamp" in log for log in mock_opensearch_logs)
        assert all("level" in log for log in mock_opensearch_logs)

    def test_mock_health_check_output_fixture(self, mock_health_check_output):
        """Test mock_health_check_output fixture."""
        assert mock_health_check_output is not None
        assert "status" in mock_health_check_output
        assert "components" in mock_health_check_output


class TestIntegrationFixtures:
    """Test integration fixtures."""

    def test_mock_config_fixture(self, mock_config):
        """Test mock_config fixture."""
        assert mock_config is not None
        assert hasattr(mock_config, "server_name")
        assert hasattr(mock_config, "debug")
        assert hasattr(mock_config, "log_level")

    def test_mock_app_fixture(self, mock_app):
        """Test mock_app fixture."""
        assert mock_app is not None
        assert mock_app.config is not None
        assert hasattr(mock_app, "workflow_state_manager")
        assert hasattr(mock_app, "execute_workflow")

    def test_mock_adapter_fixture(self, mock_adapter):
        """Test mock_adapter fixture."""
        assert mock_adapter is not None
        assert hasattr(mock_adapter, "name")
        assert hasattr(mock_adapter, "get_health")
        assert hasattr(mock_adapter, "execute")

    def test_temp_dir_fixture(self, temp_dir):
        """Test temp_dir fixture."""
        assert temp_dir is not None
        assert temp_dir.exists()
        assert temp_dir.is_dir()

        # Create a test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("test content")
        assert test_file.exists()
        assert test_file.read_text() == "test content"

    def test_temp_git_repo_fixture(self, temp_git_repo):
        """Test temp_git_repo fixture."""
        assert temp_git_repo is not None
        assert temp_git_repo.exists()
        assert (temp_git_repo / ".git").exists()
        assert (temp_git_repo / "README.md").exists()

    def test_temp_config_file_fixture(self, temp_config_file):
        """Test temp_config_file fixture."""
        assert temp_config_file is not None
        assert temp_config_file.exists()
        assert temp_config_file.suffix == ".yaml"

    def test_temp_repos_file_fixture(self, temp_repos_file):
        """Test temp_repos_file fixture."""
        assert temp_repos_file is not None
        assert temp_repos_file.exists()
        assert temp_repos_file.name == "repos.yaml"

    def test_sample_user_id_fixture(self, sample_user_id):
        """Test sample_user_id fixture."""
        assert sample_user_id is not None
        assert isinstance(sample_user_id, str)
        assert sample_user_id == "test_user_123"

    def test_sample_workflow_id_fixture(self, sample_workflow_id):
        """Test sample_workflow_id fixture."""
        assert sample_workflow_id is not None
        assert isinstance(sample_workflow_id, str)
        assert sample_workflow_id.startswith("wf_")

    def test_sample_timestamp_fixture(self, sample_timestamp):
        """Test sample_timestamp fixture."""
        assert sample_timestamp is not None
        assert isinstance(sample_timestamp, str)
        assert "T" in sample_timestamp  # ISO format


class TestFixtureFactories:
    """Test fixture factory classes."""

    def test_workflow_fixtures_factory(self):
        """Test WorkflowFixtures factory class."""
        workflow = WorkflowFixtures.sample_workflow()
        assert workflow["status"] == "running"

        completed = WorkflowFixtures.completed_workflow()
        assert completed["status"] == "completed"

        failed = WorkflowFixtures.failed_workflow()
        assert failed["status"] == "failed"

        multiple = WorkflowFixtures.multiple_workflows(count=3)
        assert len(multiple) == 3

    def test_shell_fixtures_factory(self):
        """Test ShellFixtures factory class."""
        repos = ShellFixtures.mock_repos_list()
        assert len(repos) == 6

        errors = ShellFixtures.mock_error_output()
        assert len(errors) == 3

        commands = ShellFixtures.mock_shell_commands()
        assert "ps" in commands

    def test_integration_fixtures_factory(self):
        """Test IntegrationFixtures factory class."""
        config = IntegrationFixtures.mock_config()
        assert config.server_name is not None

        app = IntegrationFixtures.mock_app(config)
        assert app.config is not None

        adapter = IntegrationFixtures.mock_adapter()
        assert adapter.name is not None


class TestAsyncFixtures:
    """Test async fixtures."""

    @pytest.mark.asyncio
    async def test_mock_app_async_methods(self, mock_app):
        """Test mock_app async methods."""
        # Test health check
        health = await mock_app.is_healthy()
        assert health is True

        # Test execute_workflow
        result = await mock_app.execute_workflow(
            task={"type": "test"},
            adapter_name="test",
        )
        assert "workflow_id" in result

    @pytest.mark.asyncio
    async def test_workflow_state_manager_async(self, mock_workflow_state_manager):
        """Test mock_workflow_state_manager async methods."""
        # Test create
        result = await mock_workflow_state_manager.create(
            workflow_id="wf_test",
            task={"type": "test"},
            repos=["/test"],
        )
        assert "id" in result

        # Test get
        workflow = await mock_workflow_state_manager.get("wf_test")
        assert workflow is not None

        # Test update
        await mock_workflow_state_manager.update("wf_test", status="running")

        # Test list
        workflows = await mock_workflow_state_manager.list_workflows()
        assert isinstance(workflows, list)
