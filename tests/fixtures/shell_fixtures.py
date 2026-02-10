"""Shell fixtures for testing admin shell functionality.

This module provides comprehensive fixtures for shell-related tests,
including mock terminal output, repository listings, and shell command
responses for testing the admin shell interface.
"""

from typing import Any
from unittest.mock import MagicMock, Mock
import pytest


class ShellFixtures:
    """Factory class for creating shell test data.

    Provides methods to generate realistic shell output and command
    responses for testing shell formatters, commands, and terminal
    interactions.
    """

    @staticmethod
    def mock_shell_output(command: str = "mahavishnu list-repos") -> dict[str, Any]:
        """Create mock terminal shell output.

        Args:
            command: The command that was executed.

        Returns:
            Dictionary with command, exit_code, stdout, and stderr.
        """
        return {
            "command": command,
            "exit_code": 0,
            "stdout": "/Users/les/Projects/mahavishnu\n/Users/les/Projects/oneiric\n",
            "stderr": "",
            "timestamp": "2026-02-09T22:30:00",
        }

    @staticmethod
    def mock_repos_list() -> list[dict[str, Any]]:
        """Create mock repository listing output.

        Returns:
            List of repository dictionaries with path, tags, description,
            and role metadata.
        """
        return [
            {
                "path": "/Users/les/Projects/mahavishnu",
                "name": "mahavishnu",
                "package": "mahavishnu",
                "nickname": "vishnu",
                "role": "orchestrator",
                "tags": ["backend", "python", "orchestration"],
                "description": "Multi-engine orchestration platform",
                "mcp": "native",
            },
            {
                "path": "/Users/les/Projects/oneiric",
                "name": "oneiric",
                "package": "oneiric",
                "nickname": "oneiric",
                "role": "resolver",
                "tags": ["backend", "python", "configuration"],
                "description": "Configuration management framework",
                "mcp": "native",
            },
            {
                "path": "/Users/les/Projects/session-buddy",
                "name": "session-buddy",
                "package": "session_buddy",
                "nickname": "buddy",
                "role": "manager",
                "tags": ["backend", "python", "telemetry"],
                "description": "Session management and telemetry",
                "mcp": "native",
            },
            {
                "path": "/Users/les/Projects/crackerjack",
                "name": "crackerjack",
                "package": "crackerjack",
                "nickname": "jack",
                "role": "inspector",
                "tags": ["backend", "python", "testing"],
                "description": "Quality control and CI/CD automation",
                "mcp": "3rd-party",
            },
            {
                "path": "/Users/les/Projects/fastblocks",
                "name": "fastblocks",
                "package": "fastblocks",
                "nickname": "blocks",
                "role": "builder",
                "tags": ["frontend", "python", "web"],
                "description": "Fast web application builder",
                "mcp": "3rd-party",
            },
            {
                "path": "/Users/les/Projects/akosha",
                "name": "akosha",
                "package": "akosha",
                "nickname": "akosha",
                "role": "soothsayer",
                "tags": ["backend", "python", "analytics"],
                "description": "Pattern detection and analytics",
                "mcp": "native",
            },
        ]

    @staticmethod
    def mock_workflow_status(output_type: str = "table") -> str | dict[str, Any]:
        """Create mock workflow status output.

        Args:
            output_type: Type of output ('table', 'json', 'detail').

        Returns:
            Formatted workflow status output.
        """
        workflows = [
            {
                "id": "wf_a1b2c3d4_code_sweep",
                "status": "running",
                "progress": 45,
                "adapter": "llamaindex",
                "created_at": "2026-02-09T22:25:00",
            },
            {
                "id": "wf_e5f6g7h8_test_gen",
                "status": "completed",
                "progress": 100,
                "adapter": "agno",
                "created_at": "2026-02-09T22:15:00",
            },
            {
                "id": "wf_i9j0k1l2_refactor",
                "status": "failed",
                "progress": 50,
                "adapter": "prefect",
                "created_at": "2026-02-09T22:20:00",
            },
        ]

        if output_type == "json":
            return {"workflows": workflows}

        if output_type == "detail":
            return workflows[0]

        # Default: table format
        return "ID                   Status        Progress  Adapter      Created             \n" \
               "wf_a1b2c3d4_code...  running       45%       llamaindex  2026-02-09T22:25:00 \n" \
               "wf_e5f6g7h8_test_...  completed     100%      agno        2026-02-09T22:15:00 \n" \
               "wf_i9j0k1l2_refa...  failed        50%       prefect     2026-02-09T22:20:00"

    @staticmethod
    def mock_error_output() -> list[dict[str, Any]]:
        """Create mock error output for shell display.

        Returns:
            List of error dictionaries with timestamp, level, and message.
        """
        return [
            {
                "workflow_id": "wf_i9j0k1l2_refactor",
                "timestamp": "2026-02-09T22:22:30",
                "level": "ERROR",
                "message": "ImportError: No module named 'deprecated_package'",
            },
            {
                "workflow_id": "wf_i9j0k1l2_refactor",
                "timestamp": "2026-02-09T22:23:00",
                "level": "ERROR",
                "message": "SyntaxError in session_manager.py line 42",
            },
            {
                "workflow_id": "wf_m3n4o5p6_lint",
                "timestamp": "2026-02-09T22:18:45",
                "level": "ERROR",
                "message": "ConfigurationError: Invalid linting rule",
            },
        ]

    @staticmethod
    def mock_terminal_output() -> dict[str, Any]:
        """Create mock terminal output with colors and formatting.

        Returns:
            Dictionary with terminal output including formatted text.
        """
        return {
            "raw": "\x1b[32m✓ mahavishnu: healthy\x1b[0m\n\x1b[33m⚠ oneiric: degraded\x1b[0m\n",
            "plain": "✓ mahavishnu: healthy\n⚠ oneiric: degraded\n",
            "lines": [
                {"text": "✓ mahavishnu: healthy", "color": "green"},
                {"text": "⚠ oneiric: degraded", "color": "yellow"},
            ],
            "exit_code": 0,
        }

    @staticmethod
    def mock_shell_commands() -> dict[str, Any]:
        """Create mock shell command registry.

        Returns:
            Dictionary of available shell commands with metadata.
        """
        return {
            "ps": {
                "name": "ps",
                "description": "Show all workflows",
                "usage": "ps [--details]",
                "category": "workflow",
            },
            "top": {
                "name": "top",
                "description": "Show active workflows with progress",
                "usage": "top",
                "category": "workflow",
            },
            "errors": {
                "name": "errors",
                "description": "Show recent errors",
                "usage": "errors [--limit N]",
                "category": "monitoring",
            },
            "sync": {
                "name": "sync",
                "description": "Sync workflow state from backend",
                "usage": "sync",
                "category": "admin",
            },
            "repos": {
                "name": "repos",
                "description": "List repositories",
                "usage": "repos [--tags] [--role ROLE]",
                "category": "repo",
            },
            "help": {
                "name": "help",
                "description": "Show help information",
                "usage": "help [command]",
                "category": "general",
            },
        }

    @staticmethod
    def mock_role_output() -> dict[str, Any]:
        """Create mock role taxonomy output.

        Returns:
            Dictionary with role definitions and capabilities.
        """
        return {
            "roles": [
                {
                    "name": "orchestrator",
                    "description": "Coordinates workflows and manages cross-repository operations",
                    "capabilities": ["sweep", "schedule", "monitor", "route", "coordinate"],
                    "duties": ["Execute workflows across repos", "Manage task queues", "Coordinate adapters"],
                    "tags": ["backend", "python", "orchestration"],
                    "example_repos": ["mahavishnu"],
                },
                {
                    "name": "resolver",
                    "description": "Resolves components, dependencies, and lifecycle management",
                    "capabilities": ["resolve", "activate", "swap", "explain", "watch"],
                    "duties": ["Load configurations", "Resolve dependencies", "Manage lifecycle"],
                    "tags": ["backend", "python", "configuration"],
                    "example_repos": ["oneiric"],
                },
                {
                    "name": "inspector",
                    "description": "Validates code quality and enforces development standards",
                    "capabilities": ["test", "lint", "scan", "report", "validate"],
                    "duties": ["Run tests", "Check code quality", "Generate reports"],
                    "tags": ["backend", "python", "testing"],
                    "example_repos": ["crackerjack"],
                },
            ]
        }

    @staticmethod
    def mock_opensearch_logs() -> list[dict[str, Any]]:
        """Create mock OpenSearch log entries.

        Returns:
            List of log entry dictionaries.
        """
        return [
            {
                "timestamp": "2026-02-09T22:30:15",
                "level": "INFO",
                "workflow_id": "wf_a1b2c3d4_code_sweep",
                "message": "Started processing repository /Users/les/Projects/mahavishnu",
                "logger": "mahavishnu.core.app",
            },
            {
                "timestamp": "2026-02-09T22:30:20",
                "level": "WARNING",
                "workflow_id": "wf_a1b2c3d4_code_sweep",
                "message": "Repository path validation warning: symbolic link detected",
                "logger": "mahavishnu.core.app",
            },
            {
                "timestamp": "2026-02-09T22:30:25",
                "level": "ERROR",
                "workflow_id": "wf_i9j0k1l2_refactor",
                "message": "Failed to process repository: ImportError",
                "logger": "mahavishnu.engines.prefect_adapter",
            },
            {
                "timestamp": "2026-02-09T22:30:30",
                "level": "INFO",
                "workflow_id": "wf_e5f6g7h8_test_gen",
                "message": "Workflow completed successfully: 25 tests generated",
                "logger": "mahavishnu.engines.agno_adapter",
            },
        ]

    @staticmethod
    def mock_health_check_output() -> dict[str, Any]:
        """Create mock health check output.

        Returns:
            Dictionary with system health status.
        """
        return {
            "status": "healthy",
            "timestamp": "2026-02-09T22:30:00",
            "components": {
                "adapters": {
                    "prefect": {"status": "healthy", "last_check": "2026-02-09T22:29:55"},
                    "llamaindex": {"status": "healthy", "last_check": "2026-02-09T22:29:56"},
                    "agno": {"status": "degraded", "last_check": "2026-02-09T22:29:57"},
                },
                "opensearch": {
                    "status": "healthy",
                    "cluster": "production",
                    "nodes": 3,
                },
                "session_buddy": {
                    "status": "healthy",
                    "endpoint": "http://localhost:8678/mcp",
                },
            },
            "active_workflows": 3,
            "pending_workflows": 1,
        }


# Pytest fixtures
@pytest.fixture
def shell_fixtures():
    """Provide ShellFixtures factory class.

    Returns:
        ShellFixtures class for creating test shell data.
    """
    return ShellFixtures


@pytest.fixture
def mock_shell_output():
    """Provide mock shell output.

    Returns:
        Dictionary with command execution result.
    """
    return ShellFixtures.mock_shell_output()


@pytest.fixture
def mock_repos_list():
    """Provide mock repository listing.

    Returns:
        List of repository dictionaries.
    """
    return ShellFixtures.mock_repos_list()


@pytest.fixture
def mock_workflow_status():
    """Provide mock workflow status output.

    Returns:
        Formatted workflow status string.
    """
    return ShellFixtures.mock_workflow_status()


@pytest.fixture
def mock_error_output():
    """Provide mock error output.

    Returns:
        List of error dictionaries.
    """
    return ShellFixtures.mock_error_output()


@pytest.fixture
def mock_terminal_output():
    """Provide mock terminal output.

    Returns:
        Dictionary with terminal output data.
    """
    return ShellFixtures.mock_terminal_output()


@pytest.fixture
def mock_shell_commands():
    """Provide mock shell command registry.

    Returns:
        Dictionary of shell commands.
    """
    return ShellFixtures.mock_shell_commands()


@pytest.fixture
def mock_role_output():
    """Provide mock role taxonomy output.

    Returns:
        Dictionary with role definitions.
    """
    return ShellFixtures.mock_role_output()


@pytest.fixture
def mock_opensearch_logs():
    """Provide mock OpenSearch logs.

    Returns:
        List of log entry dictionaries.
    """
    return ShellFixtures.mock_opensearch_logs()


@pytest.fixture
def mock_health_check_output():
    """Provide mock health check output.

    Returns:
        Dictionary with system health status.
    """
    return ShellFixtures.mock_health_check_output()


@pytest.fixture
def mock_rich_console():
    """Create a mock Rich console.

    Returns:
        Mock object with Rich console interface.
    """
    console = MagicMock()
    console.print = MagicMock()
    return console


@pytest.fixture
def mock_workflow_formatter():
    """Create a mock WorkflowFormatter.

    Returns:
        Mock WorkflowFormatter with common methods.
    """
    formatter = MagicMock()
    formatter.format_workflows = MagicMock()
    formatter.format_workflow_detail = MagicMock()
    formatter.console = MagicMock()
    return formatter


@pytest.fixture
def mock_log_formatter():
    """Create a mock LogFormatter.

    Returns:
        Mock LogFormatter with common methods.
    """
    formatter = MagicMock()
    formatter.format_logs = MagicMock()
    formatter.console = MagicMock()
    return formatter


@pytest.fixture
def mock_repo_formatter():
    """Create a mock RepoFormatter.

    Returns:
        Mock RepoFormatter with common methods.
    """
    formatter = MagicMock()
    formatter.format_repos = MagicMock()
    formatter.console = MagicMock()
    return formatter
