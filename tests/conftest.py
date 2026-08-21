"""Pytest configuration for unit tests.

This file automatically marks all tests in tests/unit/ as unit tests,
allowing the production readiness checker to run only unit tests with the
`-m unit` flag.
"""

import os

# Remove AI_AGENT before any imports so crackerjack's AISettings.ai_agent bool
# field doesn't receive a string value set by the outer Claude Code environment.
os.environ.pop("AI_AGENT", None)

# ---------------------------------------------------------------------------
# Disable ANSI escape codes in CLI help / table output for the test session.
#
# Two layers need to be neutralised:
#
# 1. Typer's Rich-based help renderer is controlled at module-import time by
#    reading environment variables. Setting ``_TYPER_FORCE_DISABLE_TERMINAL``
#    forces ``FORCE_TERMINAL = False`` in ``typer.rich_utils`` so the help
#    tables render without ANSI codes (otherwise ``"--type"`` becomes
#    ``"--\\x1b[0m\\x1b[1;36mtype"`` which breaks plain-text assertions).
#
# 2. CLI modules that bind ``console = Console()`` at import time also need
#    to be constructed with ``no_color=True``. Patching ``Console.__init__``
#    here — before any test module is imported — ensures every Console in
#    the test session is built without colors.
# ---------------------------------------------------------------------------
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"

from rich.console import Console as _RichConsole

_orig_console_init = _RichConsole.__init__


def _patched_console_init(self, *args, **kwargs):
    kwargs.setdefault("no_color", True)
    kwargs.setdefault("color_system", None)
    kwargs.setdefault("force_terminal", False)
    kwargs.setdefault("force_interactive", False)
    _orig_console_init(self, *args, **kwargs)


_RichConsole.__init__ = _patched_console_init

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
