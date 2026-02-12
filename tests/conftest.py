"""Pytest configuration for unit tests.

This file automatically marks all tests in tests/unit/ as unit tests,
allowing the production readiness checker to run only unit tests with the
`-m unit` flag.
"""

import pytest

# Import fixtures from fixtures package for global availability
# Use try/except to handle cases where fixtures might not be available
try:
    from tests.fixtures.workflow_fixtures import (
        WorkflowFixtures,
        sample_workflow,
        completed_workflow,
        failed_workflow,
        partial_workflow,
        pending_workflow,
        multiple_workflows,
        mock_workflow_state_manager,
        sample_task,
        sample_repos,
        workflow_fixtures,
    )
except ImportError:
    pass

try:
    from tests.fixtures.shell_fixtures import (
        ShellFixtures,
        mock_shell_output,
        mock_repos_list,
        mock_workflow_status,
        mock_error_output,
        mock_terminal_output,
        mock_shell_commands,
        mock_role_output,
        mock_opensearch_logs,
        mock_health_check_output,
        shell_fixtures,
        mock_rich_console,
        mock_workflow_formatter,
        mock_log_formatter,
        mock_repo_formatter,
    )
except ImportError:
    pass

try:
    from tests.fixtures.conftest import (
        IntegrationFixtures,
        integration_fixtures,
        mock_config,
        mock_app,
        mock_adapter,
        temp_dir,
        temp_git_repo,
        temp_config_file,
        temp_repos_file,
        mock_event_loop,
        sample_user_id,
        sample_workflow_id,
        sample_timestamp,
        clean_env,
        test_env_vars,
        async_mock_app,
        mock_performance_tracker,
        mock_logger,
        mock_filesystem,
    )
except ImportError:
    pass


def pytest_collection_modifyitems(items, config):
    """Automatically mark all tests in tests/unit/ as unit tests."""
    # Add Oneiric to path for ULID resolution imports
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)  # mahavishnu/
    oneiric_path = os.path.join(project_root, "../oneiric")
    oneiric_path = os.path.abspath(oneiric_path)
    if oneiric_path not in sys.path:
        sys.path.insert(0, oneiric_path)

    for item in items:
        # Mark tests in tests/unit/ directory as unit tests
        if "/tests/unit/" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        # Mark tests in tests/integration/ directory as integration tests
        elif "/tests/integration/" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        # Mark tests in tests/property/ directory as property tests
        elif "/tests/property/" in str(item.fspath):
            item.add_marker(pytest.mark.property)
