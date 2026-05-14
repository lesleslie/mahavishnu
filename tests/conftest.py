"""Pytest configuration for unit tests.

This file automatically marks all tests in tests/unit/ as unit tests,
allowing the production readiness checker to run only unit tests with the
`-m unit` flag.
"""

import os

# Remove AI_AGENT before any imports so crackerjack's AISettings.ai_agent bool
# field doesn't receive a string value set by the outer Claude Code environment.
os.environ.pop("AI_AGENT", None)

import pytest

# Import fixtures from fixtures package for global availability
# Use try/except to handle cases where fixtures might not be available
try:
    from tests.fixtures.workflow_fixtures import (
        WorkflowFixtures,
        completed_workflow,
        failed_workflow,
        mock_workflow_state_manager,
        multiple_workflows,
        partial_workflow,
        pending_workflow,
        sample_repos,
        sample_task,
        sample_workflow,
        workflow_fixtures,
    )
except ImportError:
    pass

try:
    from tests.fixtures.shell_fixtures import (
        ShellFixtures,
        mock_error_output,
        mock_health_check_output,
        mock_log_formatter,
        mock_opensearch_logs,
        mock_repo_formatter,
        mock_repos_list,
        mock_rich_console,
        mock_role_output,
        mock_shell_commands,
        mock_shell_output,
        mock_terminal_output,
        mock_workflow_formatter,
        mock_workflow_status,
        shell_fixtures,
    )
except ImportError:
    pass

try:
    from tests.fixtures.conftest import (
        IntegrationFixtures,
        async_mock_app,
        clean_env,
        integration_fixtures,
        mock_adapter,
        mock_app,
        mock_config,
        mock_event_loop,
        mock_filesystem,
        mock_logger,
        mock_performance_tracker,
        sample_timestamp,
        sample_user_id,
        sample_workflow_id,
        suppress_prefect_console_shutdown_noise,
        temp_config_file,
        temp_dir,
        temp_git_repo,
        temp_repos_file,
        test_env_vars,
    )
except ImportError:
    pass


def pytest_collection_modifyitems(items, config):
    """Automatically mark all tests in tests/unit/ as unit tests."""
    # Add Oneiric to path for ULID resolution imports
    import os
    import sys

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
