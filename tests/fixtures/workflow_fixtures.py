"""Workflow fixtures for testing.

This module provides comprehensive fixtures for workflow-related tests,
including sample workflows in various states (pending, running, completed,
failed) for testing workflow state management, execution, and monitoring.
"""

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest


class WorkflowFixtures:
    """Factory class for creating workflow test data.

    Provides methods to generate realistic workflow objects for testing
    various scenarios including successful execution, partial failures,
    and error handling.
    """

    @staticmethod
    def sample_workflow(workflow_id: str | None = None) -> dict[str, Any]:
        """Create a sample active workflow in RUNNING state.

        Args:
            workflow_id: Optional custom workflow ID. If not provided,
                        generates a unique ID.

        Returns:
            Dictionary representing a workflow in running state with
            task, repos, progress, and metadata.
        """
        if workflow_id is None:
            workflow_id = f"wf_{uuid.uuid4().hex[:8]}_code_sweep"

        return {
            "id": workflow_id,
            "status": "running",
            "task": {
                "type": "code_sweep",
                "params": {"pattern": "TODO", "replace": "FIXME"},
            },
            "repos": [
                "/Users/les/Projects/mahavishnu",
                "/Users/les/Projects/oneiric",
            ],
            "adapter": "llamaindex",
            "progress": 45,
            "created_at": (datetime.now() - timedelta(minutes=5)).isoformat(),
            "updated_at": datetime.now().isoformat(),
            "results": [
                {
                    "repo": "/Users/les/Projects/mahavishnu",
                    "status": "success",
                    "matches_found": 3,
                }
            ],
            "errors": [],
            "execution_time_seconds": None,
            "completed_at": None,
        }

    @staticmethod
    def completed_workflow(workflow_id: str | None = None) -> dict[str, Any]:
        """Create a sample workflow in COMPLETED state.

        Args:
            workflow_id: Optional custom workflow ID. If not provided,
                        generates a unique ID.

        Returns:
            Dictionary representing a successfully completed workflow
            with results and execution time.
        """
        if workflow_id is None:
            workflow_id = f"wf_{uuid.uuid4().hex[:8]}_test_generation"

        completed_at = datetime.now()
        created_at = completed_at - timedelta(minutes=10)

        return {
            "id": workflow_id,
            "status": "completed",
            "task": {
                "type": "test_generation",
                "params": {"coverage_target": 80},
            },
            "repos": [
                "/Users/les/Projects/mahavishnu",
                "/Users/les/Projects/crackerjack",
                "/Users/les/Projects/oneiric",
            ],
            "adapter": "agno",
            "progress": 100,
            "created_at": created_at.isoformat(),
            "updated_at": completed_at.isoformat(),
            "results": [
                {
                    "repo": "/Users/les/Projects/mahavishnu",
                    "status": "success",
                    "tests_generated": 25,
                    "coverage": 82,
                },
                {
                    "repo": "/Users/les/Projects/crackerjack",
                    "status": "success",
                    "tests_generated": 18,
                    "coverage": 78,
                },
                {
                    "repo": "/Users/les/Projects/oneiric",
                    "status": "success",
                    "tests_generated": 31,
                    "coverage": 85,
                },
            ],
            "errors": [],
            "execution_time_seconds": 600.5,
            "completed_at": completed_at.isoformat(),
        }

    @staticmethod
    def failed_workflow(workflow_id: str | None = None) -> dict[str, Any]:
        """Create a sample workflow in FAILED state with errors.

        Args:
            workflow_id: Optional custom workflow ID. If not provided,
                        generates a unique ID.

        Returns:
            Dictionary representing a failed workflow with detailed
            error information including timestamps and error types.
        """
        if workflow_id is None:
            workflow_id = f"wf_{uuid.uuid4().hex[:8]}_refactor"

        failed_at = datetime.now()
        created_at = failed_at - timedelta(minutes=3)

        return {
            "id": workflow_id,
            "status": "failed",
            "task": {
                "type": "refactor",
                "params": {"target": "modernize_python"},
            },
            "repos": [
                "/Users/les/Projects/mahavishnu",
                "/Users/les/Projects/session-buddy",
            ],
            "adapter": "prefect",
            "progress": 50,
            "created_at": created_at.isoformat(),
            "updated_at": failed_at.isoformat(),
            "results": [
                {
                    "repo": "/Users/les/Projects/mahavishnu",
                    "status": "success",
                    "files_refactored": 5,
                }
            ],
            "errors": [
                {
                    "repo": "/Users/les/Projects/session-buddy",
                    "error": "ImportError: No module named 'deprecated_package'",
                    "type": "ImportError",
                    "timestamp": (created_at + timedelta(minutes=2)).isoformat(),
                },
                {
                    "repo": "/Users/les/Projects/session-buddy",
                    "error": "SyntaxError in session_manager.py line 42",
                    "type": "SyntaxError",
                    "timestamp": (created_at + timedelta(minutes=2, seconds=30)).isoformat(),
                },
            ],
            "execution_time_seconds": 180.0,
            "completed_at": failed_at.isoformat(),
        }

    @staticmethod
    def partial_workflow(workflow_id: str | None = None) -> dict[str, Any]:
        """Create a workflow with partial success (some repos failed).

        Args:
            workflow_id: Optional custom workflow ID. If not provided,
                        generates a unique ID.

        Returns:
            Dictionary representing a workflow that completed but had
            some failures (partial success state).
        """
        if workflow_id is None:
            workflow_id = f"wf_{uuid.uuid4().hex[:8]}_lint"

        completed_at = datetime.now()
        created_at = completed_at - timedelta(minutes=7)

        return {
            "id": workflow_id,
            "status": "partial",
            "task": {
                "type": "lint",
                "params": {"fix": True},
            },
            "repos": [
                "/Users/les/Projects/mahavishnu",
                "/Users/les/Projects/crackerjack",
                "/Users/les/Projects/oneiric",
                "/Users/les/Projects/session-buddy",
            ],
            "adapter": "agno",
            "progress": 100,
            "created_at": created_at.isoformat(),
            "updated_at": completed_at.isoformat(),
            "results": [
                {
                    "repo": "/Users/les/Projects/mahavishnu",
                    "status": "success",
                    "issues_fixed": 5,
                },
                {
                    "repo": "/Users/les/Projects/crackerjack",
                    "status": "success",
                    "issues_fixed": 3,
                },
                {
                    "repo": "/Users/les/Projects/session-buddy",
                    "status": "success",
                    "issues_fixed": 2,
                },
            ],
            "errors": [
                {
                    "repo": "/Users/les/Projects/oneiric",
                    "error": "ConfigurationError: Invalid linting rule",
                    "type": "ConfigurationError",
                    "timestamp": (created_at + timedelta(minutes=5)).isoformat(),
                }
            ],
            "execution_time_seconds": 420.0,
            "completed_at": completed_at.isoformat(),
        }

    @staticmethod
    def pending_workflow(workflow_id: str | None = None) -> dict[str, Any]:
        """Create a workflow in PENDING state (not yet started).

        Args:
            workflow_id: Optional custom workflow ID. If not provided,
                        generates a unique ID.

        Returns:
            Dictionary representing a workflow that has been created
            but not yet started execution.
        """
        if workflow_id is None:
            workflow_id = f"wf_{uuid.uuid4().hex[:8]}_documentation"

        created_at = datetime.now()

        return {
            "id": workflow_id,
            "status": "pending",
            "task": {
                "type": "documentation",
                "params": {"format": "markdown"},
            },
            "repos": ["/Users/les/Projects/mahavishnu"],
            "adapter": "llamaindex",
            "progress": 0,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "results": [],
            "errors": [],
            "execution_time_seconds": None,
            "completed_at": None,
        }

    @staticmethod
    def multiple_workflows(count: int = 5) -> list[dict[str, Any]]:
        """Create multiple workflows with various states.

        Args:
            count: Number of workflows to generate (default: 5).

        Returns:
            List of workflow dictionaries with different statuses
            and configurations.
        """
        workflows = []

        # Always include one of each type
        workflows.append(WorkflowFixtures.pending_workflow())
        workflows.append(WorkflowFixtures.sample_workflow())
        workflows.append(WorkflowFixtures.completed_workflow())
        workflows.append(WorkflowFixtures.failed_workflow())
        workflows.append(WorkflowFixtures.partial_workflow())

        # Add more if requested
        if count > 5:
            for i in range(count - 5):
                workflow_type = i % 4
                if workflow_type == 0:
                    workflows.append(WorkflowFixtures.sample_workflow())
                elif workflow_type == 1:
                    workflows.append(WorkflowFixtures.completed_workflow())
                elif workflow_type == 2:
                    workflows.append(WorkflowFixtures.failed_workflow())
                else:
                    workflows.append(WorkflowFixtures.partial_workflow())

        return workflows[:count]


# Pytest fixtures
@pytest.fixture
def workflow_fixtures():
    """Provide WorkflowFixtures factory class.

    Returns:
        WorkflowFixtures class for creating test workflow data.
    """
    return WorkflowFixtures


@pytest.fixture
def sample_workflow():
    """Provide a sample active workflow.

    Returns:
        Dictionary representing a running workflow.
    """
    return WorkflowFixtures.sample_workflow()


@pytest.fixture
def completed_workflow():
    """Provide a completed workflow.

    Returns:
        Dictionary representing a successfully completed workflow.
    """
    return WorkflowFixtures.completed_workflow()


@pytest.fixture
def failed_workflow():
    """Provide a failed workflow.

    Returns:
        Dictionary representing a failed workflow with errors.
    """
    return WorkflowFixtures.failed_workflow()


@pytest.fixture
def partial_workflow():
    """Provide a partial success workflow.

    Returns:
        Dictionary representing a workflow with some failures.
    """
    return WorkflowFixtures.partial_workflow()


@pytest.fixture
def pending_workflow():
    """Provide a pending workflow.

    Returns:
        Dictionary representing a workflow not yet started.
    """
    return WorkflowFixtures.pending_workflow()


@pytest.fixture
def multiple_workflows():
    """Provide multiple workflows.

    Returns:
        List of workflow dictionaries in various states.
    """
    return WorkflowFixtures.multiple_workflows()


@pytest.fixture
def mock_workflow_state_manager():
    """Create a mock WorkflowStateManager.

    Returns:
        AsyncMock of WorkflowStateManager with common methods configured.
    """
    manager = AsyncMock()

    # Configure common methods
    manager.create = AsyncMock(return_value={"id": "wf_test_123", "status": "pending"})
    manager.get = AsyncMock(return_value=WorkflowFixtures.sample_workflow())
    manager.update = AsyncMock()
    manager.list_workflows = AsyncMock(return_value=WorkflowFixtures.multiple_workflows())
    manager.delete = AsyncMock()
    manager.update_progress = AsyncMock()
    manager.get_completed_count = AsyncMock(return_value=1)
    manager.add_result = AsyncMock()
    manager.add_error = AsyncMock()

    return manager


@pytest.fixture
def sample_task():
    """Provide a sample task specification.

    Returns:
        Dictionary representing a workflow task.
    """
    return {
        "type": "code_sweep",
        "params": {
            "pattern": "TODO",
            "replace": "FIXME",
            "file_pattern": "*.py",
        },
    }


@pytest.fixture
def sample_repos():
    """Provide sample repository paths.

    Returns:
        List of repository path strings.
    """
    return [
        "/Users/les/Projects/mahavishnu",
        "/Users/les/Projects/oneiric",
        "/Users/les/Projects/crackerjack",
    ]
