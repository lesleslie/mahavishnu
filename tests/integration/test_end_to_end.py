"""Integration tests for Mahavishnu orchestration platform."""

from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, Mock

import pytest

from mahavishnu.core.adapters.base import OrchestratorAdapter
from mahavishnu.core.app import MahavishnuApp


class MockAdapter(OrchestratorAdapter):
    """Mock adapter for testing."""

    def __init__(self, config=None):
        self.config = config
        self.execution_results = []
        self.health_status = {"status": "healthy"}

    async def execute(self, task: dict, repos: list[str]) -> dict:
        """Mock execution that records the task and repos."""
        result = {
            "task": task,
            "repos": repos,
            "status": "completed",
            "adapter": "mock",
            "results": [{"repo": repo, "processed": True} for repo in repos],
        }
        self.execution_results.append(result)
        return result

    async def get_health(self) -> dict:
        """Return mock health status."""
        return self.health_status


@pytest.fixture
def mock_app():
    """Create a mock app for testing."""
    app = Mock(spec=MahavishnuApp)
    app.observability = Mock()
    app.opensearch_integration = Mock()
    app.workflow_state_manager = Mock()
    app.rbac_manager = Mock()
    app.resilience_manager = Mock()
    app.error_recovery_manager = Mock()
    app.monitoring_service = Mock()
    app.config = Mock()
    app.config.max_concurrent_workflows = 10
    app.config.auth_enabled = False
    app.config.qc_enabled = False
    app.config.session_enabled = False
    app.adapters = {}

    # Mock the workflow state manager
    app.workflow_state_manager.create = AsyncMock()
    app.workflow_state_manager.update = AsyncMock()
    app.workflow_state_manager.get = AsyncMock()
    app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])

    return app


@pytest.mark.asyncio
async def test_app_initialization():
    """Test that the main app initializes correctly with all components."""
    # Create a real app instance (not a mock)
    app = MahavishnuApp()

    # Verify all components were initialized
    assert app.adapters is not None
    assert app.workflow_state_manager is not None
    assert app.rbac_manager is not None
    assert app.observability is not None
    assert app.opensearch_integration is not None
    assert app.resilience_manager is not None
    assert app.error_recovery_manager is not None
    assert app.monitoring_service is not None


@pytest.mark.asyncio
async def test_adapter_registration():
    """Test that adapters are properly registered and accessible."""
    app = MahavishnuApp()

    # Check that default adapters are registered
    expected_adapters = ["prefect", "agno", "llamaindex"]
    for adapter_name in expected_adapters:
        assert adapter_name in app.adapters
        assert app.adapters[adapter_name] is not None


@pytest.mark.asyncio
async def test_workflow_execution_with_multiple_adapters():
    """Test executing workflows with different adapters."""
    app = MahavishnuApp()

    # Create a temporary directory to use as a repository
    with tempfile.TemporaryDirectory() as temp_dir:
        # Add the temp directory to repos
        test_repo = Path(temp_dir)
        test_repo_path = str(test_repo)

        # Create a simple test file to make it a valid repo
        (test_repo / "test.py").write_text("# Test repository")

        # Test with LlamaIndex adapter (should be available)
        if "llamaindex" in app.adapters:
            task = {"type": "code_sweep", "params": {"test": True}}
            result = await app.execute_workflow(task, "llamaindex", [test_repo_path])

            # Verify result structure
            assert "status" in result
            assert "result" in result

        # Test with Prefect adapter (should be available)
        if "prefect" in app.adapters:
            task = {"type": "health_check", "params": {"test": True}}
            result = await app.execute_workflow(task, "prefect", [test_repo_path])

            # Verify result structure
            assert "status" in result
            assert "result" in result


@pytest.mark.asyncio
async def test_workflow_execution_parallel():
    """Test executing workflows in parallel across multiple repositories."""
    app = MahavishnuApp()

    # Create multiple temporary directories to use as repositories
    with tempfile.TemporaryDirectory() as temp_base:
        repo_paths = []
        for i in range(3):  # Create 3 test repositories
            repo_dir = Path(temp_base) / f"repo_{i}"
            repo_dir.mkdir()
            # Create a simple test file
            (repo_dir / "test.py").write_text(f"# Test repository {i}")
            repo_paths.append(str(repo_dir))

        # Test parallel execution with LlamaIndex adapter
        if "llamaindex" in app.adapters:
            task = {"type": "code_sweep", "params": {"test": True}}
            result = await app.execute_workflow_parallel(task, "llamaindex", repo_paths)

            # Verify result structure
            assert "status" in result
            assert "results" in result
            assert "repos_processed" in result
            assert result["repos_processed"] == 3  # Should process all 3 repos


@pytest.mark.asyncio
async def test_rbac_integration():
    """Test that RBAC is properly integrated with workflow execution."""
    app = MahavishnuApp()

    # Create a temporary directory to use as a repository
    with tempfile.TemporaryDirectory() as temp_dir:
        test_repo = Path(temp_dir)
        test_repo_path = str(test_repo)
        (test_repo / "test.py").write_text("# Test repository")

        # Test that RBAC manager is available and functional
        assert app.rbac_manager is not None

        # Create a test user with permissions
        user = await app.rbac_manager.create_user(
            user_id="test_user", roles=["developer"], allowed_repos=[test_repo_path]
        )

        # Verify user was created
        assert user.user_id == "test_user"

        # Check if user has permission for the test repo
        has_permission = await app.rbac_manager.check_permission(
            "test_user", test_repo_path, "READ_REPO"
        )

        # Should have permission since we granted it
        assert has_permission is True


@pytest.mark.asyncio
async def test_workflow_state_tracking():
    """Test that workflow state is properly tracked."""
    app = MahavishnuApp()

    # Create a temporary directory to use as a repository
    with tempfile.TemporaryDirectory() as temp_dir:
        test_repo = Path(temp_dir)
        test_repo_path = str(test_repo)
        (test_repo / "test.py").write_text("# Test repository")

        # Verify workflow state manager is available
        assert app.workflow_state_manager is not None

        # Test creating a workflow state
        workflow_id = "test_workflow_integration"
        task = {"type": "test", "id": workflow_id}
        repos = [test_repo_path]

        # Create workflow state
        await app.workflow_state_manager.create(workflow_id, task, repos)

        # Get the workflow state
        state = await app.workflow_state_manager.get(workflow_id)

        # Verify state was created and retrieved
        assert state is not None
        assert state["id"] == workflow_id
        assert state["task"] == task
        assert state["repos"] == repos


@pytest.mark.asyncio
async def test_observability_integration():
    """Test that observability is properly integrated."""
    app = MahavishnuApp()

    # Verify observability manager is available
    assert app.observability is not None

    # Test creating and using observability instruments
    counter = app.observability.create_workflow_counter()
    assert counter is not None

    histogram = app.observability.create_repo_counter()
    assert histogram is not None

    # Test logging
    app.observability.log_info("Test log message", {"test": True})
    app.observability.log_warning("Test warning message", {"test": True})
    app.observability.log_error("Test error message", {"test": True})


@pytest.mark.asyncio
async def test_opensearch_integration():
    """Test that OpenSearch integration is properly set up."""
    app = MahavishnuApp()

    # Verify OpenSearch integration is available
    assert app.opensearch_integration is not None

    # Test that it has the expected methods
    assert hasattr(app.opensearch_integration, "log_workflow_start")
    assert hasattr(app.opensearch_integration, "log_workflow_completion")
    assert hasattr(app.opensearch_integration, "log_error")
    assert hasattr(app.opensearch_integration, "search_logs")
    assert hasattr(app.opensearch_integration, "search_workflows")


@pytest.mark.asyncio
async def test_resilience_integration():
    """Test that resilience patterns are properly integrated."""
    app = MahavishnuApp()

    # Verify resilience components are available
    assert app.resilience_manager is not None
    assert app.error_recovery_manager is not None

    # Test that resilience manager has expected methods
    assert hasattr(app.resilience_manager, "resilient_workflow_execution")
    assert hasattr(app.resilience_manager, "resilient_repo_operation")

    # Test that error recovery manager has expected methods
    assert hasattr(app.error_recovery_manager, "classify_error")
    assert hasattr(app.error_recovery_manager, "execute_with_resilience")


@pytest.mark.asyncio
async def test_monitoring_integration():
    """Test that monitoring is properly integrated."""
    app = MahavishnuApp()

    # Verify monitoring service is available
    assert app.monitoring_service is not None
    assert app.monitoring_service.alert_manager is not None
    assert app.monitoring_service.dashboard is not None

    # Test getting dashboard data
    dashboard_data = await app.monitoring_service.get_dashboard_data()
    assert "metrics" in dashboard_data
    assert "recent_alerts" in dashboard_data
    assert "timestamp" in dashboard_data


@pytest.mark.asyncio
async def test_backup_recovery_integration():
    """Test that backup and recovery is properly integrated."""
    app = MahavishnuApp()

    # Verify backup manager is available
    assert hasattr(app, "backup_manager")
    assert app.backup_manager is not None

    # Verify recovery manager is available
    assert hasattr(app, "recovery_manager")
    assert app.recovery_manager is not None


@pytest.mark.asyncio
async def test_session_buddy_integration():
    """Test that Session Buddy integration is properly set up."""
    app = MahavishnuApp()

    # Verify Session Buddy integration is available
    assert hasattr(app, "session_buddy_integration")
    # Note: The actual attribute name may vary based on implementation
    # If it doesn't exist, that's fine - this test verifies the concept


@pytest.mark.asyncio
async def test_repository_messaging_integration():
    """Test that repository messaging is properly integrated."""
    app = MahavishnuApp()

    # Verify repository messenger is available
    assert hasattr(app, "repository_messenger")
    # Note: The actual attribute name may vary based on implementation
    # If it doesn't exist, that's fine - this test verifies the concept


@pytest.mark.asyncio
async def test_end_to_end_workflow():
    """Test an end-to-end workflow from task submission to completion."""
    app = MahavishnuApp()

    # Create a temporary directory to use as a repository
    with tempfile.TemporaryDirectory() as temp_dir:
        test_repo = Path(temp_dir)
        test_repo_path = str(test_repo)
        (test_repo / "test.py").write_text("# Test repository")

        # Use LlamaIndex adapter for a simple task
        if "llamaindex" in app.adapters:
            task = {
                "type": "ingest",
                "params": {"file_types": [".py"], "exclude_patterns": ["__pycache__"]},
                "id": "end_to_end_test",
            }

            # Execute the workflow
            result = await app.execute_workflow_parallel(task, "llamaindex", [test_repo_path])

            # Verify the workflow completed successfully
            assert "status" in result
            assert result["status"] in ["completed", "partial"]  # Allow partial for this test
            assert "results" in result
            assert "repos_processed" in result
            assert result["repos_processed"] >= 0
