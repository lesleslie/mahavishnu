"""Shared fixtures for Mahavishnu tests.

This module provides integration and shared fixtures used across multiple
test files, including application mocks, configuration objects, and
temporary test resources with proper cleanup.

Fixtures are organized into:
- IntegrationFixtures: Mock application and configuration objects
- Test Resources: Temporary directories and test repositories
- Common Test Data: Shared across workflow, shell, and CLI tests
"""

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import uuid
import pytest
import yaml

# Try importing Mahavishnu modules for type hints
try:
    from mahavishnu.core.app import MahavishnuApp
    from mahavishnu.core.config import MahavishnuSettings
    from mahavishnu.core.workflow_state import WorkflowState
    from mahavishnu.core.adapters.base import OrchestratorAdapter
    MAHAVISHNU_AVAILABLE = True
except ImportError:
    MAHAVISHNU_AVAILABLE = False
    MahavishnuApp = None  # type: ignore
    MahavishnuSettings = None  # type: ignore
    WorkflowState = None  # type: ignore
    OrchestratorAdapter = None  # type: ignore


class IntegrationFixtures:
    """Factory class for creating integration test mocks.

    Provides mock objects for MahavishnuApp, configuration, adapters,
    and related components with realistic behavior for integration testing.
    """

    @staticmethod
    def mock_config(**overrides) -> Any:
        """Create a mock MahavishnuSettings configuration.

        Args:
            **overrides: Optional configuration overrides.

        Returns:
            Mock MahavishnuSettings with default values.
        """
        if MAHAVISHNU_AVAILABLE and MahavishnuSettings is not None:
            # Try to create real config with minimal dependencies
            try:
                config = MahavishnuSettings()
                # Apply overrides
                for key, value in overrides.items():
                    if hasattr(config, key):
                        setattr(config, key, value)
                return config
            except Exception:
                # Fall back to mock if real config fails
                pass

        # Create comprehensive mock
        config = MagicMock()

        # Top-level settings
        config.server_name = overrides.get("server_name", "Mahavishnu Test Server")
        config.debug = overrides.get("debug", True)
        config.log_level = overrides.get("log_level", "DEBUG")
        config.repos_path = overrides.get("repos_path", "/tmp/test_repos.yaml")
        config.allowed_repo_paths = overrides.get("allowed_repo_paths", ["/tmp"])
        config.max_concurrent_workflows = overrides.get("max_concurrent_workflows", 5)
        config.shell_enabled = overrides.get("shell_enabled", True)

        # Terminal settings
        terminal = MagicMock()
        terminal.enabled = overrides.get("terminal_enabled", False)
        terminal.max_sessions = overrides.get("max_sessions", 10)
        terminal.session_timeout_seconds = overrides.get("session_timeout", 3600)
        config.terminal = terminal

        # Pool configuration
        pools = MagicMock()
        pools.enabled = overrides.get("pools_enabled", False)
        pools.default_type = overrides.get("default_pool_type", "mahavishnu")
        pools.routing_strategy = overrides.get("routing_strategy", "least_loaded")
        pools.min_workers = overrides.get("min_workers", 1)
        pools.max_workers = overrides.get("max_workers", 10)
        pools.memory_aggregation_enabled = overrides.get("memory_aggregation", False)
        config.pools = pools

        # Adapter configuration
        adapters = MagicMock()
        adapters.prefect_enabled = overrides.get("prefect_enabled", False)
        adapters.llamaindex_enabled = overrides.get("llamaindex_enabled", True)
        adapters.agno_enabled = overrides.get("agno_enabled", True)
        config.adapters = adapters

        # Quality control
        qc = MagicMock()
        qc.enabled = overrides.get("qc_enabled", True)
        qc.min_score = overrides.get("min_score", 80)
        config.qc = qc

        # Session management
        session = MagicMock()
        session.enabled = overrides.get("session_enabled", True)
        session.checkpoint_interval = overrides.get("checkpoint_interval", 60)
        config.session = session

        # Observability
        observability = MagicMock()
        observability.metrics_enabled = overrides.get("metrics_enabled", True)
        observability.tracing_enabled = overrides.get("tracing_enabled", False)
        config.observability = observability

        # Auth
        auth = MagicMock()
        auth.enabled = overrides.get("auth_enabled", False)
        auth.secret = overrides.get("auth_secret", None)
        config.auth = auth

        return config

    @staticmethod
    def mock_app(config: Any = None) -> Any:
        """Create a mock MahavishnuApp instance.

        Args:
            config: Optional configuration object. If not provided,
                   creates a default mock config.

        Returns:
            Mock MahavishnuApp with common methods configured.
        """
        if config is None:
            config = IntegrationFixtures.mock_config()

        app = MagicMock()

        # Basic attributes
        app.config = config
        app.adapters = {}
        app.active_workflows = set()
        app.repos_config = {"repos": IntegrationFixtures.mock_repos_config()}

        # Mock workflow state manager
        app.workflow_state_manager = AsyncMock()
        app.workflow_state_manager.create = AsyncMock(
            return_value={"id": "wf_test", "status": "pending"}
        )
        app.workflow_state_manager.get = AsyncMock(return_value={"id": "wf_test", "status": "running"})
        app.workflow_state_manager.update = AsyncMock()
        app.workflow_state_manager.list_workflows = AsyncMock(return_value=[])
        app.workflow_state_manager.delete = AsyncMock()

        # Mock observability
        app.observability = MagicMock()
        app.observability.create_workflow_counter = MagicMock(return_value=None)
        app.observability.create_error_counter = MagicMock(return_value=None)
        app.observability.start_workflow_trace = MagicMock()
        app.observability.end_workflow_trace = MagicMock()
        app.observability.record_repo_processing_time = MagicMock()

        # Mock circuit breaker
        app.circuit_breaker = MagicMock()
        app.circuit_breaker.call = AsyncMock()

        # Mock quality control
        app.qc = MagicMock()
        app.qc.validate_pre_execution = AsyncMock(return_value=True)
        app.qc.validate_post_execution = AsyncMock(return_value=True)

        # Mock session buddy
        app.session_buddy = MagicMock()
        app.session_buddy.create_checkpoint = AsyncMock(return_value="cp_test_123")
        app.session_buddy.update_checkpoint = AsyncMock()

        # Mock OpenSearch integration
        app.opensearch_integration = MagicMock()
        app.opensearch_integration.log_workflow_start = AsyncMock()
        app.opensearch_integration.log_workflow_completion = AsyncMock()
        app.opensearch_integration.log_error = AsyncMock()
        app.opensearch_integration.health_check = AsyncMock(return_value={"status": "healthy"})
        app.opensearch_integration.get_workflow_stats = AsyncMock(return_value={"total_workflows": 0})

        # Mock RBAC manager
        app.rbac_manager = MagicMock()
        app.rbac_manager.check_permission = AsyncMock(return_value=True)

        # Mock pool manager
        app.pool_manager = None
        if config.pools.enabled:
            app.pool_manager = MagicMock()

        # Common methods
        app.get_repos = MagicMock(return_value=["/tmp/repo1", "/tmp/repo2"])
        app.get_all_repos = MagicMock(return_value=IntegrationFixtures.mock_repos_config())
        app.get_roles = MagicMock(return_value=IntegrationFixtures.mock_roles())
        app.is_healthy = AsyncMock(return_value=True)
        app.execute_workflow = AsyncMock(
            return_value={
                "workflow_id": "wf_test_123",
                "status": "completed",
                "repos_processed": 2,
            }
        )
        app.execute_workflow_parallel = AsyncMock(
            return_value={
                "workflow_id": "wf_test_123",
                "status": "completed",
                "repos_processed": 2,
                "successful_repos": 2,
                "failed_repos": 0,
                "execution_time_seconds": 10.5,
            }
        )

        return app

    @staticmethod
    def mock_adapter(adapter_name: str = "test_adapter") -> Any:
        """Create a mock orchestrator adapter.

        Args:
            adapter_name: Name for the adapter.

        Returns:
            Mock OrchestratorAdapter with common methods.
        """
        adapter = MagicMock()

        adapter.name = adapter_name
        adapter.get_health = AsyncMock(return_value={"status": "healthy"})
        adapter.execute = AsyncMock(
            return_value={
                "status": "success",
                "repos_processed": 1,
                "results": [],
            }
        )

        return adapter

    @staticmethod
    def mock_repos_config() -> list[dict[str, Any]]:
        """Create mock repository configuration.

        Returns:
            List of repository configuration dictionaries.
        """
        return [
            {
                "path": "/tmp/test_repo1",
                "name": "test_repo1",
                "package": "test_repo1",
                "nickname": "repo1",
                "role": "orchestrator",
                "tags": ["test", "python"],
                "description": "Test repository 1",
                "mcp": "native",
            },
            {
                "path": "/tmp/test_repo2",
                "name": "test_repo2",
                "package": "test_repo2",
                "nickname": "repo2",
                "role": "inspector",
                "tags": ["test", "testing"],
                "description": "Test repository 2",
                "mcp": "3rd-party",
            },
        ]

    @staticmethod
    def mock_roles() -> list[dict[str, Any]]:
        """Create mock role definitions.

        Returns:
            List of role definition dictionaries.
        """
        return [
            {
                "name": "orchestrator",
                "description": "Coordinates workflows and manages operations",
                "capabilities": ["sweep", "schedule", "monitor"],
                "duties": ["Execute workflows", "Manage queues"],
                "tags": ["backend", "orchestration"],
            },
            {
                "name": "inspector",
                "description": "Validates code quality and enforces standards",
                "capabilities": ["test", "lint", "scan"],
                "duties": ["Run tests", "Check quality"],
                "tags": ["backend", "testing"],
            },
        ]


# Pytest integration fixtures

@pytest.fixture
def integration_fixtures():
    """Provide IntegrationFixtures factory class.

    Returns:
        IntegrationFixtures class for creating test mocks.
    """
    return IntegrationFixtures


@pytest.fixture
def mock_config():
    """Provide a mock MahavishnuSettings configuration.

    Returns:
        Mock configuration object with sensible defaults.
    """
    return IntegrationFixtures.mock_config()


@pytest.fixture
def mock_app(mock_config):
    """Provide a mock MahavishnuApp instance.

    Args:
        mock_config: Injected mock configuration fixture.

    Returns:
        Mock MahavishnuApp with common methods configured.
    """
    return IntegrationFixtures.mock_app(mock_config)


@pytest.fixture
def mock_adapter():
    """Provide a mock orchestrator adapter.

    Returns:
        Mock adapter with execute and health check methods.
    """
    return IntegrationFixtures.mock_adapter()


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing.

    Yields:
        Path to temporary directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_git_repo(temp_dir):
    """Create a temporary Git repository for testing.

    Args:
        temp_dir: Injected temporary directory fixture.

    Yields:
        Path to temporary Git repository.
    """
    import subprocess

    repo_path = temp_dir / "test_repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    # Create a dummy file and commit
    (repo_path / "README.md").write_text("# Test Repository\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )

    yield repo_path


@pytest.fixture
def temp_config_file(temp_dir):
    """Create a temporary configuration file.

    Args:
        temp_dir: Injected temporary directory fixture.

    Yields:
        Path to temporary configuration file.
    """
    config_path = temp_dir / "test_config.yaml"

    config_data = {
        "server_name": "Test Mahavishnu",
        "debug": True,
        "log_level": "DEBUG",
        "repos_path": str(temp_dir / "repos.yaml"),
        "adapters": {
            "prefect_enabled": False,
            "llamaindex_enabled": True,
            "agno_enabled": True,
        },
        "qc": {
            "enabled": True,
            "min_score": 80,
        },
    }

    with config_path.open("w") as f:
        yaml.dump(config_data, f)

    yield config_path


@pytest.fixture
def temp_repos_file(temp_dir):
    """Create a temporary repos.yaml file.

    Args:
        temp_dir: Injected temporary directory fixture.

    Yields:
        Path to temporary repos.yaml file.
    """
    repos_path = temp_dir / "repos.yaml"

    repos_data = {
        "repos": [
            {
                "path": str(temp_dir / "repo1"),
                "name": "repo1",
                "package": "repo1",
                "role": "orchestrator",
                "tags": ["test"],
                "description": "Test repository 1",
            },
            {
                "path": str(temp_dir / "repo2"),
                "name": "repo2",
                "package": "repo2",
                "role": "inspector",
                "tags": ["test"],
                "description": "Test repository 2",
            },
        ],
        "roles": [
            {
                "name": "orchestrator",
                "description": "Test orchestrator role",
                "capabilities": ["test"],
                "duties": ["Test duty"],
                "tags": ["test"],
            },
        ],
    }

    with repos_path.open("w") as f:
        yaml.dump(repos_data, f)

    yield repos_path


@pytest.fixture
def mock_event_loop():
    """Create a mock event loop for async testing.

    Yields:
        Mock event loop.
    """
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    yield loop

    loop.close()


@pytest.fixture
def sample_user_id():
    """Provide a sample user ID for testing.

    Returns:
        Sample user ID string.
    """
    return "test_user_123"


@pytest.fixture
def sample_workflow_id():
    """Provide a sample workflow ID for testing.

    Returns:
        Sample workflow ID string.
    """
    return f"wf_{uuid.uuid4().hex[:8]}_test"


@pytest.fixture
def sample_timestamp():
    """Provide a sample timestamp for testing.

    Returns:
        ISO format timestamp string.
    """
    from datetime import datetime

    return datetime.now().isoformat()


# Environment variable fixtures

@pytest.fixture
def clean_env():
    """Provide clean environment without Mahavishnu variables.

    Yields:
        Clean environment dict.
    """
    original_env = os.environ.copy()

    # Remove all MAHAVISHNU_* variables
    for key in list(os.environ.keys()):
        if key.startswith("MAHAVISHNU_"):
            del os.environ[key]

    yield os.environ

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def test_env_vars():
    """Provide test environment variables.

    Yields:
        Environment dict with test variables.
    """
    original_env = os.environ.copy()

    test_vars = {
        "MAHAVISHNU_SERVER_NAME": "Test Server",
        "MAHAVISHNU_DEBUG": "true",
        "MAHAVISHNU_LOG_LEVEL": "DEBUG",
        "MAHAVISHNU_POOLS__ENABLED": "false",
        "MAHAVISHNU_QC__ENABLED": "true",
    }

    os.environ.update(test_vars)

    yield os.environ

    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


# Async context manager fixtures

@pytest.fixture
async def async_mock_app():
    """Provide an async mock app context.

    Yields:
        Mock app suitable for async tests.
    """
    app = IntegrationFixtures.mock_app()

    # Make key methods async
    app.execute_workflow = AsyncMock(
        return_value={
            "workflow_id": "wf_test",
            "status": "completed",
        }
    )
    app.execute_workflow_parallel = AsyncMock(
        return_value={
            "workflow_id": "wf_test",
            "status": "completed",
            "repos_processed": 2,
        }
    )

    yield app


# Performance monitoring fixtures

@pytest.fixture
def mock_performance_tracker():
    """Create a mock performance tracker.

    Returns:
        Mock object for tracking performance metrics.
    """
    tracker = MagicMock()

    tracker.start_timer = MagicMock(return_value="timer_123")
    tracker.stop_timer = MagicMock(return_value=1.5)
    tracker.record_metric = MagicMock()
    tracker.get_metrics = MagicMock(return_value={"execution_time": 1.5})

    return tracker


# Logging fixtures

@pytest.fixture
def mock_logger():
    """Create a mock logger.

    Returns:
        Mock logger with common log methods.
    """
    logger = MagicMock()

    logger.debug = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.critical = MagicMock()

    return logger


# File system fixtures

@pytest.fixture
def mock_filesystem():
    """Create a mock filesystem with common operations.

    Returns:
        Mock object with file system operations.
    """
    fs = MagicMock()

    fs.exists = MagicMock(return_value=True)
    fs.is_file = MagicMock(return_value=True)
    fs.is_dir = MagicMock(return_value=False)
    fs.read_text = MagicMock(return_value="test content")
    fs.write_text = MagicMock()
    fs.unlink = MagicMock()
    fs.mkdir = MagicMock()

    return fs
