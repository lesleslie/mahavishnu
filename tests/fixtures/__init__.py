"""Test fixtures package for Mahavishnu.

This package provides comprehensive pytest fixtures for testing
Mahavishnu's workflow management, shell commands, and integration
points.

Modules:
    workflow_fixtures: Fixtures for workflow state and execution tests
    shell_fixtures: Fixtures for admin shell and terminal tests
    conftest: Shared fixtures for integration and configuration tests

Example usage:
    ```python
    # In your test file
    import pytest
    from tests.fixtures.workflow_fixtures import WorkflowFixtures

    def test_workflow_execution(sample_workflow, mock_app):
        # sample_workflow and mock_app are automatically injected
        workflow = sample_workflow
        app = mock_app
        # Test code here...
    ```

Available fixtures:
    # Workflow fixtures
    - workflow_fixtures: WorkflowFixtures factory class
    - sample_workflow: Active workflow in RUNNING state
    - completed_workflow: Successfully completed workflow
    - failed_workflow: Workflow with errors
    - partial_workflow: Partial success workflow
    - pending_workflow: Workflow not yet started
    - multiple_workflows: List of various workflows
    - mock_workflow_state_manager: Mock state manager

    # Shell fixtures
    - shell_fixtures: ShellFixtures factory class
    - mock_shell_output: Terminal command output
    - mock_repos_list: Repository listing data
    - mock_workflow_status: Workflow status display
    - mock_error_output: Error log entries
    - mock_terminal_output: Formatted terminal data
    - mock_shell_commands: Shell command registry
    - mock_role_output: Role taxonomy data
    - mock_opensearch_logs: OpenSearch log entries
    - mock_health_check_output: System health status

    # Integration fixtures
    - integration_fixtures: IntegrationFixtures factory class
    - mock_config: MahavishnuSettings configuration
    - mock_app: MahavishnuApp instance
    - mock_adapter: OrchestratorAdapter instance
    - temp_dir: Temporary directory
    - temp_git_repo: Temporary Git repository
    - temp_config_file: Temporary configuration file
    - temp_repos_file: Temporary repos.yaml file
    - mock_event_loop: Async event loop
    - clean_env: Clean environment variables
    - test_env_vars: Test environment variables
"""

from tests.fixtures.workflow_fixtures import WorkflowFixtures
from tests.fixtures.shell_fixtures import ShellFixtures
from tests.fixtures.conftest import IntegrationFixtures

__all__ = [
    "WorkflowFixtures",
    "ShellFixtures",
    "IntegrationFixtures",
]
