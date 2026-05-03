"""Comprehensive unit tests for mahavishnu._main_cli module.

Tests cover all registered CLI commands and subcommands, mocking
MahavishnuApp, MultiAuthHandler, and all external dependencies
to avoid network calls and filesystem access.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

import mahavishnu._main_cli as cli_module
from mahavishnu.core.health import HealthStatus

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_config(**overrides):
    """Create a mock MahavishnuSettings with sensible defaults."""
    config = MagicMock()
    config.auth.enabled = False
    config.auth.secret = None
    config.auth.algorithm = "HS256"
    config.auth.expire_minutes = 60
    config.terminal.enabled = False
    config.terminal.max_concurrent_sessions = 5
    config.terminal.default_columns = 120
    config.terminal.default_rows = 40
    config.terminal.adapter_preference = "mcpretentious"
    config.health.enabled = False
    config.pools.enabled = False
    config.pools.memory_aggregation_enabled = False
    config.workers_enabled = True
    config.max_concurrent_workers = 10
    config.shell_enabled = True
    config.subscription_auth = MagicMock()
    config.subscription_auth.enabled = False
    config.subscription_auth.secret = None
    config.subscription_auth_enabled = False
    config.subscription_auth_secret = None

    for key, value in overrides.items():
        setattr(config, key, value)

    return config


def _make_mock_app(**config_overrides):
    """Create a mock MahavishnuApp."""
    maha = MagicMock()
    maha.config = _make_mock_config(**config_overrides)
    maha.adapters = {}
    maha.terminal_manager = None
    maha.pool_manager = None
    maha.health_endpoint = None
    maha.session_buddy = None
    return maha


@pytest.fixture(autouse=True)
def _suppress_deprecation_warnings():
    """Suppress DeprecationWarning from health_schemas compatibility wrapper."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        yield


# ===========================================================================
# App structure tests
# ===========================================================================


class TestAppStructure:
    """Tests for CLI app registration and structure."""

    def test_app_is_typer_instance(self):
        import typer

        assert isinstance(cli_module.app, typer.Typer)

    def test_app_name(self):
        assert cli_module.app.info.name == "mahavishnu"

    def test_all_subapps_registered(self):
        registered_names = [g.name for g in cli_module.app.registered_groups if g.typer_instance]
        expected = [
            "worktree",
            "workflow",
            "adapter",
            "mcp",
            "ecosystem",
            "terminal",
            "pool",
            "workers",
        ]
        for name in expected:
            assert name in registered_names, f"Missing sub-app: {name}"


# ===========================================================================
# sweep command (legacy top-level)
# ===========================================================================


class TestSweepCommand:
    """Tests for the top-level 'sweep' command."""

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_sweep_basic(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = ["/path/to/repo1", "/path/to/repo2"]
        mock_app.adapters = {"langgraph": MagicMock()}
        mock_app.execute_workflow_parallel = AsyncMock(return_value={"status": "done"})
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["sweep", "--tag", "python"])
        assert result.exit_code == 0
        assert "Sweep completed" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_sweep_adapter_not_found(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = ["/path/to/repo1"]
        mock_app.adapters = {}
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["sweep", "--tag", "python", "-a", "missing"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_sweep_missing_tag(self, mock_app_cls, mock_auth_cls):
        result = runner.invoke(cli_module.app, ["sweep"])
        assert result.exit_code != 0

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_sweep_with_short_flags(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = ["/path/to/repo1"]
        mock_app.adapters = {"langgraph": MagicMock()}
        mock_app.execute_workflow_parallel = AsyncMock(return_value={"status": "done"})
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["sweep", "-t", "python", "-a", "langgraph"])
        assert result.exit_code == 0

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_sweep_claude_subscription_auth(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = ["/path/to/repo1"]
        mock_app.adapters = {"langgraph": MagicMock()}
        mock_app.execute_workflow_parallel = AsyncMock(return_value={"status": "done"})
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = True
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["sweep", "-t", "python"])
        assert result.exit_code == 0
        assert "Claude Code subscription" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_sweep_jwt_auth(self, mock_app_cls, mock_auth_cls):
        config = _make_mock_config()
        config.auth.enabled = True
        config.auth.secret = "x" * 32
        maha = _make_mock_app()
        maha.config = config
        maha.get_repos.return_value = ["/path/to/repo1"]
        maha.adapters = {"langgraph": MagicMock()}
        maha.execute_workflow_parallel = AsyncMock(return_value={"status": "done"})
        mock_app_cls.return_value = maha
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["sweep", "-t", "python"])
        assert result.exit_code == 0
        assert "JWT authentication" in result.output


# ===========================================================================
# workflow sub-app commands
# ===========================================================================


class TestWorkflowSweep:
    """Tests for the 'workflow sweep' command."""

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_workflow_sweep_basic(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = ["/path/to/repo1"]
        mock_app.adapters = {"langgraph": MagicMock()}
        mock_app.execute_workflow_parallel = AsyncMock(return_value={"status": "done"})
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["workflow", "sweep", "-t", "python"])
        assert result.exit_code == 0
        assert "Sweep completed" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_workflow_sweep_missing_tag(self, mock_app_cls, mock_auth_cls):
        result = runner.invoke(cli_module.app, ["workflow", "sweep"])
        assert result.exit_code != 0


class TestWorkflowQualityCheck:
    """Tests for the 'workflow quality-check' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_quality_check_basic(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = ["/path/to/repo1"]
        mock_app.execute_workflow_parallel = AsyncMock(return_value={"status": "done"})
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["workflow", "quality-check", "-t", "python"])
        assert result.exit_code == 0
        assert "Quality check completed" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_quality_check_with_repos(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.execute_workflow_parallel = AsyncMock(return_value={"status": "done"})
        mock_app_cls.return_value = mock_app

        result = runner.invoke(
            cli_module.app,
            ["workflow", "quality-check", "-t", "python", "-r", "repo1", "-r", "repo2"],
        )
        assert result.exit_code == 0

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_quality_check_no_repos(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = []
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["workflow", "quality-check", "-t", "python"])
        assert result.exit_code == 1
        assert "No repositories found" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_quality_check_missing_tag(self, mock_app_cls):
        result = runner.invoke(cli_module.app, ["workflow", "quality-check"])
        assert result.exit_code != 0


class TestWorkflowHeal:
    """Tests for the 'workflow heal' command."""

    @patch("mahavishnu.core.dead_letter_queue.DeadLetterQueue")
    def test_heal_empty_dlq(self, mock_dlq_cls):
        mock_dlq = MagicMock()
        mock_dlq.list_tasks = AsyncMock(return_value=[])
        mock_dlq_cls.return_value = mock_dlq

        result = runner.invoke(cli_module.app, ["workflow", "heal"])
        assert result.exit_code == 0
        assert "no_failed_workflows" in result.output

    @patch("mahavishnu.core.dead_letter_queue.DeadLetterQueue")
    def test_heal_with_failed_workflows(self, mock_dlq_cls):
        mock_task = MagicMock()
        mock_task.task_id = "task_1"

        mock_dlq = MagicMock()
        mock_dlq.list_tasks = AsyncMock(return_value=[mock_task])
        mock_dlq.retry_task = AsyncMock(return_value={"status": "retried"})
        mock_dlq_cls.return_value = mock_dlq

        result = runner.invoke(cli_module.app, ["workflow", "heal"])
        assert result.exit_code == 0
        assert "completed" in result.output
        assert "healed" in result.output

    @patch("mahavishnu.core.dead_letter_queue.DeadLetterQueue")
    def test_heal_with_errors(self, mock_dlq_cls):
        mock_task = MagicMock()
        mock_task.task_id = "task_1"

        mock_dlq = MagicMock()
        mock_dlq.list_tasks = AsyncMock(return_value=[mock_task])
        mock_dlq.retry_task = AsyncMock(side_effect=Exception("retry failed"))
        mock_dlq_cls.return_value = mock_dlq

        result = runner.invoke(cli_module.app, ["workflow", "heal"])
        assert result.exit_code == 0
        assert "retry failed" in result.output


class TestWorkflowFix:
    """Tests for the 'workflow fix' command."""

    @patch("mahavishnu.core.fix_orchestrator.FixTask")
    @patch("mahavishnu.core.fix_orchestrator.FixOrchestrator")
    def test_fix_basic(self, mock_orch_cls, mock_task_cls):
        mock_orch = MagicMock()
        mock_orch.execute_fix = AsyncMock(return_value={"status": "fixed"})
        mock_orch_cls.return_value = mock_orch
        mock_task_cls.return_value = MagicMock(prompt="test prompt")

        result = runner.invoke(
            cli_module.app,
            ["workflow", "fix", "-p", "pool1", "-i", "issue1"],
        )
        assert result.exit_code == 0
        assert "Executing fix" in result.output

    @patch("mahavishnu.core.fix_orchestrator.FixTask")
    @patch("mahavishnu.core.fix_orchestrator.FixOrchestrator")
    def test_fix_with_description_and_files(self, mock_orch_cls, mock_task_cls):
        mock_orch = MagicMock()
        mock_orch.execute_fix = AsyncMock(return_value={"status": "fixed"})
        mock_orch_cls.return_value = mock_orch
        mock_task_cls.return_value = MagicMock(prompt="test prompt")

        result = runner.invoke(
            cli_module.app,
            [
                "workflow",
                "fix",
                "-p",
                "pool1",
                "-i",
                "issue1",
                "-d",
                "Fix the bug",
                "-f",
                "file1.py",
                "-f",
                "file2.py",
            ],
        )
        assert result.exit_code == 0

    @patch("mahavishnu.core.fix_orchestrator.FixTask")
    @patch("mahavishnu.core.fix_orchestrator.FixOrchestrator")
    def test_fix_missing_required_options(self, mock_orch_cls, mock_task_cls):
        result = runner.invoke(cli_module.app, ["workflow", "fix"])
        assert result.exit_code != 0


class TestWorkflowReview:
    """Tests for the 'workflow review' command."""

    @patch("mahavishnu.mcp.tools.self_improvement_tools.ReviewScope")
    @patch("mahavishnu.mcp.tools.self_improvement_tools.SelfImprovementTools")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_review_basic(self, mock_app_cls, mock_tools_cls, mock_scope_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_tools = MagicMock()
        mock_tools.review_and_fix = AsyncMock(return_value={"findings": []})
        mock_tools_cls.return_value = mock_tools

        result = runner.invoke(cli_module.app, ["workflow", "review", "-s", "critical"])
        assert result.exit_code == 0
        assert "review" in result.output.lower()

    @patch("mahavishnu.mcp.tools.self_improvement_tools.ReviewScope")
    @patch("mahavishnu.mcp.tools.self_improvement_tools.SelfImprovementTools")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_review_with_auto_fix(self, mock_app_cls, mock_tools_cls, mock_scope_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_tools = MagicMock()
        mock_tools.review_and_fix = AsyncMock(return_value={"findings": []})
        mock_tools_cls.return_value = mock_tools

        result = runner.invoke(cli_module.app, ["workflow", "review", "-s", "all", "--fix"])
        assert result.exit_code == 0

    @patch("mahavishnu.mcp.tools.self_improvement_tools.ReviewScope")
    @patch("mahavishnu.mcp.tools.self_improvement_tools.SelfImprovementTools")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_review_dry_run(self, mock_app_cls, mock_tools_cls, mock_scope_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_tools = MagicMock()
        mock_tools.review_and_fix = AsyncMock(return_value={"findings": []})
        mock_tools_cls.return_value = mock_tools

        result = runner.invoke(cli_module.app, ["workflow", "review", "--dry-run"])
        assert result.exit_code == 0
        assert "dry-run" in result.output


# ===========================================================================
# adapter sub-app commands
# ===========================================================================


class TestAdapterList:
    """Tests for 'adapter list' command."""

    @patch("mahavishnu.core.adapter_registry.HybridAdapterRegistry")
    def test_adapter_list_all(self, mock_reg_cls):
        mock_adapter = MagicMock()
        mock_adapter.name = "prefect"
        mock_adapter.domain = "orchestration"
        mock_adapter.status = "healthy"
        mock_adapter.capabilities = ["workflow"]

        mock_reg = MagicMock()
        mock_reg.list_adapters = MagicMock(return_value=[mock_adapter])
        mock_reg_cls.return_value = mock_reg

        result = runner.invoke(cli_module.app, ["adapter", "list"])
        assert result.exit_code == 0
        assert "prefect" in result.output

    @patch("mahavishnu.core.adapter_registry.HybridAdapterRegistry")
    def test_adapter_list_with_domain_filter(self, mock_reg_cls):
        mock_reg = MagicMock()
        mock_reg.list_adapters = MagicMock(return_value=[])
        mock_reg_cls.return_value = mock_reg

        result = runner.invoke(cli_module.app, ["adapter", "list", "-d", "orchestration"])
        assert result.exit_code == 0

    @patch("mahavishnu.core.adapter_registry.HybridAdapterRegistry")
    def test_adapter_list_healthy_only(self, mock_reg_cls):
        mock_reg = MagicMock()
        mock_reg.list_adapters = MagicMock(return_value=[])
        mock_reg_cls.return_value = mock_reg

        result = runner.invoke(cli_module.app, ["adapter", "list", "--healthy"])
        assert result.exit_code == 0


class TestAdapterResolve:
    """Tests for 'adapter resolve' command."""

    @patch("mahavishnu.core.task_router.TaskRouter")
    def test_adapter_resolve_basic(self, mock_router_cls):
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value={"adapter": "prefect", "confidence": 0.9})
        mock_router_cls.return_value = mock_router

        result = runner.invoke(
            cli_module.app,
            ["adapter", "resolve", "ai_task", "-c", "workflow", "-c", "parallel"],
        )
        assert result.exit_code == 0

    @patch("mahavishnu.core.task_router.TaskRouter")
    def test_adapter_resolve_missing_args(self, mock_router_cls):
        result = runner.invoke(cli_module.app, ["adapter", "resolve", "ai_task"])
        assert result.exit_code != 0

    @patch("mahavishnu.core.task_router.TaskType", side_effect=ValueError("bad type"))
    @patch("mahavishnu.core.task_router.TaskRouter")
    def test_adapter_resolve_invalid_task_type(self, mock_router_cls, mock_task_type):
        result = runner.invoke(
            cli_module.app,
            ["adapter", "resolve", "invalid_type", "-c", "workflow"],
        )
        assert result.exit_code == 1
        assert "Unknown task type" in result.output


class TestAdapterHealth:
    """Tests for 'adapter health' command."""

    @patch("mahavishnu.core.adapter_registry.HybridAdapterRegistry")
    def test_adapter_health_all(self, mock_reg_cls):
        mock_reg = MagicMock()
        mock_reg.check_all_health = AsyncMock(return_value={"prefect": {"status": "healthy"}})
        mock_reg_cls.return_value = mock_reg

        result = runner.invoke(cli_module.app, ["adapter", "health"])
        assert result.exit_code == 0

    @patch("mahavishnu.core.adapter_registry.HybridAdapterRegistry")
    def test_adapter_health_specific_found(self, mock_reg_cls):
        mock_reg = MagicMock()
        mock_reg.check_all_health = AsyncMock(
            return_value={"prefect": {"status": "healthy", "latency_ms": 10.0}}
        )
        mock_reg_cls.return_value = mock_reg

        result = runner.invoke(cli_module.app, ["adapter", "health", "prefect"])
        assert result.exit_code == 0
        assert "prefect" in result.output

    @patch("mahavishnu.core.adapter_registry.HybridAdapterRegistry")
    def test_adapter_health_specific_not_found(self, mock_reg_cls):
        mock_reg = MagicMock()
        mock_reg.check_all_health = AsyncMock(return_value={})
        mock_reg_cls.return_value = mock_reg

        result = runner.invoke(cli_module.app, ["adapter", "health", "missing"])
        assert result.exit_code == 0
        assert "not_found" in result.output


# ===========================================================================
# MCP commands
# ===========================================================================


class TestMCPStart:
    """Tests for 'mcp start' command."""

    @patch("mahavishnu.mcp.server_core.FastMCPServer")
    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_mcp_start_basic(self, mock_app_cls, mock_auth_cls, mock_server_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth
        mock_server = MagicMock()
        mock_server.start = AsyncMock(side_effect=KeyboardInterrupt())
        mock_server.stop = AsyncMock()
        mock_server_cls.return_value = mock_server

        result = runner.invoke(cli_module.app, ["mcp", "start"])
        assert result.exit_code == 0
        assert "Authentication not configured" in result.output

    @patch("mahavishnu.mcp.server_core.FastMCPServer")
    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_mcp_start_with_terminal_enabled(self, mock_app_cls, mock_auth_cls, mock_server_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        mock_app_cls.return_value = maha
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth
        mock_server = MagicMock()
        mock_server.start = AsyncMock(side_effect=KeyboardInterrupt())
        mock_server.stop = AsyncMock()
        mock_server_cls.return_value = mock_server

        result = runner.invoke(cli_module.app, ["mcp", "start"])
        assert result.exit_code == 0
        assert "Terminal management enabled" in result.output

    @patch("mahavishnu.mcp.server_core.FastMCPServer")
    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_mcp_start_claude_subscription(self, mock_app_cls, mock_auth_cls, mock_server_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = True
        mock_auth_cls.return_value = mock_auth
        mock_server = MagicMock()
        mock_server.start = AsyncMock(side_effect=KeyboardInterrupt())
        mock_server.stop = AsyncMock()
        mock_server_cls.return_value = mock_server

        result = runner.invoke(cli_module.app, ["mcp", "start"])
        assert result.exit_code == 0
        assert "Claude Code subscription" in result.output

    @patch("mahavishnu.mcp.server_core.FastMCPServer")
    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_mcp_start_jwt_auth(self, mock_app_cls, mock_auth_cls, mock_server_cls):
        config = _make_mock_config()
        config.auth.enabled = True
        config.auth.secret = "x" * 32
        maha = _make_mock_app()
        maha.config = config
        mock_app_cls.return_value = maha
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth
        mock_server = MagicMock()
        mock_server.start = AsyncMock(side_effect=KeyboardInterrupt())
        mock_server.stop = AsyncMock()
        mock_server_cls.return_value = mock_server

        result = runner.invoke(cli_module.app, ["mcp", "start"])
        assert result.exit_code == 0
        assert "JWT authentication" in result.output


class TestMCPStop:
    """Tests for 'mcp stop' command."""

    def test_mcp_stop_not_implemented(self):
        result = runner.invoke(cli_module.app, ["mcp", "stop"])
        assert result.exit_code == 1
        assert "not yet implemented" in result.output


class TestMCPRestart:
    """Tests for 'mcp restart' command."""

    def test_mcp_restart_not_implemented(self):
        result = runner.invoke(cli_module.app, ["mcp", "restart"])
        assert result.exit_code == 1
        assert "not yet implemented" in result.output


class TestMCPStatus:
    """Tests for 'mcp status' command."""

    @patch("mahavishnu.mcp.server_core.FastMCPServer")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_mcp_status_basic(self, mock_app_cls, mock_server_cls):
        config = _make_mock_config()
        config.terminal.enabled = False
        mock_app = _make_mock_app()
        mock_app.config = config
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["mcp", "status"])
        assert result.exit_code == 0
        assert "Terminal Management: disabled" in result.output

    @patch("mahavishnu.mcp.server_core.FastMCPServer")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_mcp_status_with_terminal(self, mock_app_cls, mock_server_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        mock_app = _make_mock_app()
        mock_app.config = config
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["mcp", "status"])
        assert result.exit_code == 0
        assert "Terminal Management: enabled" in result.output


class TestMCPHealth:
    """Tests for 'mcp health' command."""

    def test_mcp_health_check_runs(self):
        """MCP health command runs without error (result depends on server state)."""
        result = runner.invoke(cli_module.app, ["mcp", "health"])
        assert result.exit_code == 0
        # Output depends on whether MCP server is running on the test machine
        assert "MCP Server" in result.output

    def test_mcp_health_with_mocked_connection_refused(self):
        """Test MCP health when connection is refused."""
        with patch("mahavishnu._main_cli.asyncio") as mock_asyncio:
            mock_asyncio.wait_for = AsyncMock(
                side_effect=ConnectionRefusedError("Connection refused")
            )
            # The mcp_health function uses asyncio.run internally,
            # so we need to patch at the open_connection level
            pass


# ===========================================================================
# health command
# ===========================================================================


class TestHealthCommand:
    """Tests for the top-level 'health' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_health_disabled(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.health_endpoint = None
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["health"])
        assert result.exit_code == 0
        assert "unhealthy" in result.output
        assert "disabled" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_health_disabled_json(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.health_endpoint = None
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["health", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "unhealthy"

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_health_ok(self, mock_app_cls):
        mock_endpoint = MagicMock()
        mock_liveness = MagicMock()
        mock_liveness.status = HealthStatus.OK
        mock_liveness.version = "0.6.0"
        mock_liveness.uptime_seconds = 120.5
        mock_liveness.model_dump.return_value = {
            "status": "ok",
            "version": "0.6.0",
            "uptime_seconds": 120.5,
        }

        mock_readiness = MagicMock()
        mock_readiness.service = "mahavishnu"
        mock_readiness.ready = True
        mock_readiness.dependencies = {}
        mock_readiness.model_dump.return_value = {
            "service": "mahavishnu",
            "ready": True,
            "dependencies": {},
        }

        mock_endpoint.liveness = AsyncMock(return_value=mock_liveness)
        mock_endpoint.readiness = AsyncMock(return_value=mock_readiness)

        mock_app = _make_mock_app()
        mock_app.health_endpoint = mock_endpoint
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["health"])
        assert result.exit_code == 0
        assert "ok" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_health_unhealthy_dependency(self, mock_app_cls):
        mock_endpoint = MagicMock()

        mock_dep = MagicMock()
        mock_dep.status = HealthStatus.UNHEALTHY
        mock_dep.latency_ms = 50.0
        mock_dep.error = "Connection refused"
        mock_dep.last_check = datetime.now(UTC)

        mock_liveness = MagicMock()
        mock_liveness.status = HealthStatus.OK
        mock_liveness.version = "0.6.0"
        mock_liveness.uptime_seconds = 10.0
        mock_liveness.model_dump.return_value = {"status": "ok", "version": "0.6.0"}

        mock_readiness = MagicMock()
        mock_readiness.service = "mahavishnu"
        mock_readiness.ready = False
        mock_readiness.dependencies = {"redis": mock_dep}
        mock_readiness.model_dump.return_value = {
            "service": "mahavishnu",
            "ready": False,
            "dependencies": {"redis": mock_dep},
        }

        mock_endpoint.liveness = AsyncMock(return_value=mock_liveness)
        mock_endpoint.readiness = AsyncMock(return_value=mock_readiness)

        mock_app = _make_mock_app()
        mock_app.health_endpoint = mock_endpoint
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["health"])
        assert result.exit_code == 0
        assert "unhealthy" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_health_degraded_dependency(self, mock_app_cls):
        mock_endpoint = MagicMock()

        mock_dep = MagicMock()
        mock_dep.status = HealthStatus.DEGRADED
        mock_dep.latency_ms = 500.0
        mock_dep.error = None
        mock_dep.last_check = datetime.now(UTC)

        mock_liveness = MagicMock()
        mock_liveness.status = HealthStatus.OK
        mock_liveness.version = "0.6.0"
        mock_liveness.uptime_seconds = 60.0
        mock_liveness.model_dump.return_value = {"status": "ok", "version": "0.6.0"}

        mock_readiness = MagicMock()
        mock_readiness.service = "mahavishnu"
        mock_readiness.ready = True
        mock_readiness.dependencies = {"db": mock_dep}
        mock_readiness.model_dump.return_value = {
            "service": "mahavishnu",
            "ready": True,
            "dependencies": {"db": mock_dep},
        }

        mock_endpoint.liveness = AsyncMock(return_value=mock_liveness)
        mock_endpoint.readiness = AsyncMock(return_value=mock_readiness)

        mock_app = _make_mock_app()
        mock_app.health_endpoint = mock_endpoint
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["health"])
        assert result.exit_code == 0
        assert "degraded" in result.output


# ===========================================================================
# list-repos command
# ===========================================================================


class TestListRepos:
    """Tests for the 'list-repos' command."""

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_list_repos_all(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = ["repo1", "repo2"]
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["list-repos"])
        assert result.exit_code == 0
        assert "repo1" in result.output
        assert "repo2" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_list_repos_by_tag(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = ["backend_repo"]
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["list-repos", "-t", "backend"])
        assert result.exit_code == 0
        assert "backend" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_list_repos_by_role(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.return_value = ["orchestrator_repo"]
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["list-repos", "-r", "orchestrator"])
        assert result.exit_code == 0
        assert "orchestrator" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_list_repos_both_filters_error(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["list-repos", "-t", "python", "-r", "orchestrator"])
        assert result.exit_code == 1
        assert "Cannot specify both" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_list_repos_exception(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app.get_repos.side_effect = Exception("config error")
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["list-repos"])
        assert result.exit_code == 1
        assert "config error" in result.output


# ===========================================================================
# list-roles command
# ===========================================================================


class TestListRoles:
    """Tests for the 'list-roles' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_list_roles_basic(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_roles.return_value = [
            {
                "name": "orchestrator",
                "description": "Coordinates workflows",
                "tags": ["core"],
                "capabilities": ["sweep"],
            },
        ]
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["list-roles"])
        assert result.exit_code == 0
        assert "ORCHESTRATOR" in result.output
        assert "Coordinates workflows" in result.output
        assert "core" in result.output
        assert "sweep" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_list_roles_empty(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_roles.return_value = []
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["list-roles"])
        assert result.exit_code == 0
        assert "(0)" in result.output


# ===========================================================================
# show-role command
# ===========================================================================


class TestShowRole:
    """Tests for the 'show-role' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_show_role_found(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_role_by_name.return_value = {
            "name": "orchestrator",
            "description": "Coordinates workflows",
            "tags": ["core"],
            "duties": ["manage"],
            "capabilities": ["sweep"],
        }
        mock_app.get_repos_by_role.return_value = [
            {"name": "mahavishnu", "path": "/path/to/mahavishnu"},
        ]
        mock_app_cls.return_value = mock_app
        mock_app.get_repo_nicknames.return_value = []

        result = runner.invoke(cli_module.app, ["show-role", "orchestrator"])
        assert result.exit_code == 0
        assert "ORCHESTRATOR" in result.output
        assert "Coordinates workflows" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_show_role_not_found(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_role_by_name.return_value = None
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["show-role", "nonexistent"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_show_role_with_nicknames(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_role_by_name.return_value = {
            "name": "tool",
            "description": "Tools",
        }
        mock_app.get_repos_by_role.return_value = [
            {"name": "mailgun-mcp", "path": "/path/to/mailgun"},
        ]
        mock_app.get_repo_nicknames.return_value = ["mailgun"]
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["show-role", "tool"])
        assert result.exit_code == 0
        assert "nickname" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_show_role_multiple_nicknames(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_role_by_name.return_value = {
            "name": "tool",
            "description": "Tools",
        }
        mock_app.get_repos_by_role.return_value = [
            {"name": "mailgun-mcp", "path": "/path/to/mailgun"},
        ]
        mock_app.get_repo_nicknames.return_value = ["mg", "mail"]
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["show-role", "tool"])
        assert result.exit_code == 0
        assert "nicknames" in result.output

    def test_show_role_missing_argument(self):
        result = runner.invoke(cli_module.app, ["show-role"])
        assert result.exit_code != 0


# ===========================================================================
# list-nicknames command
# ===========================================================================


class TestListNicknames:
    """Tests for the 'list-nicknames' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_list_nicknames_with_data(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_all_nicknames.return_value = {"vishnu": "mahavishnu", "jack": "crackerjack"}
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["list-nicknames"])
        assert result.exit_code == 0
        assert "vishnu" in result.output
        assert "jack" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_list_nicknames_empty(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app.get_all_nicknames.return_value = {}
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["list-nicknames"])
        assert result.exit_code == 0
        assert "No nicknames" in result.output


# ===========================================================================
# generate-claude-token command
# ===========================================================================


class TestGenerateClaudeToken:
    """Tests for the 'generate-claude-token' command."""

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_generate_token_success(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = True
        mock_auth.create_claude_subscription_token.return_value = "test_token_123"
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["generate-claude-token", "user1"])
        assert result.exit_code == 0
        assert "test_token_123" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_generate_token_not_subscribed(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_claude_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["generate-claude-token", "user1"])
        assert result.exit_code == 1
        assert "not configured" in result.output

    def test_generate_token_missing_argument(self):
        result = runner.invoke(cli_module.app, ["generate-claude-token"])
        assert result.exit_code != 0


# ===========================================================================
# generate-codex-token command
# ===========================================================================


class TestGenerateCodexToken:
    """Tests for the 'generate-codex-token' command."""

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_generate_codex_token_success(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_codex_subscribed.return_value = True
        mock_auth.create_codex_subscription_token.return_value = "codex_token_456"
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["generate-codex-token", "user2"])
        assert result.exit_code == 0
        assert "codex_token_456" in result.output

    @patch("mahavishnu._main_cli.MultiAuthHandler")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_generate_codex_token_not_subscribed(self, mock_app_cls, mock_auth_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_auth = MagicMock()
        mock_auth.is_codex_subscribed.return_value = False
        mock_auth_cls.return_value = mock_auth

        result = runner.invoke(cli_module.app, ["generate-codex-token", "user2"])
        assert result.exit_code == 1
        assert "not configured" in result.output

    def test_generate_codex_token_missing_argument(self):
        result = runner.invoke(cli_module.app, ["generate-codex-token"])
        assert result.exit_code != 0


# ===========================================================================
# terminal commands
# ===========================================================================


class TestTerminalLaunch:
    """Tests for 'terminal launch' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_launch_disabled(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["terminal", "launch", "echo hello"])
        assert result.exit_code == 1
        assert "not enabled" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_launch_no_manager(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = None
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "launch", "echo hello"])
        assert result.exit_code == 1
        assert "not initialized" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_launch_success(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.launch_sessions = AsyncMock(return_value=["sess_1", "sess_2"])
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "launch", "echo hello", "-c", "2"])
        assert result.exit_code == 0
        assert "sess_1" in result.output
        assert "sess_2" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_launch_error(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.launch_sessions = AsyncMock(side_effect=Exception("launch failed"))
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "launch", "echo hello"])
        assert result.exit_code == 1
        assert "launch failed" in result.output


class TestTerminalList:
    """Tests for 'terminal list' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_list_disabled(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["terminal", "list"])
        assert result.exit_code == 1

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_list_no_manager(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = None
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "list"])
        assert result.exit_code == 1
        assert "not initialized" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_list_success(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.list_sessions = AsyncMock(return_value=["sess_1"])
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "list"])
        assert result.exit_code == 0
        assert "sess_1" in result.output


class TestTerminalSend:
    """Tests for 'terminal send' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_send_disabled(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["terminal", "send", "sess_1", "ls"])
        assert result.exit_code == 1

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_send_success(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.send_command = AsyncMock()
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "send", "sess_1", "ls -la"])
        assert result.exit_code == 0
        assert "Sent command" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_send_error(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.send_command = AsyncMock(side_effect=Exception("send error"))
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "send", "sess_1", "ls"])
        assert result.exit_code == 1


class TestTerminalCapture:
    """Tests for 'terminal capture' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_capture_disabled(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["terminal", "capture", "sess_1"])
        assert result.exit_code == 1

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_capture_success(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.capture_output = AsyncMock(
            return_value="output line 1\noutput line 2"
        )
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "capture", "sess_1", "-l", "50"])
        assert result.exit_code == 0
        assert "output line 1" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_capture_error(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.capture_output = AsyncMock(side_effect=Exception("capture error"))
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "capture", "sess_1"])
        assert result.exit_code == 1


class TestTerminalClose:
    """Tests for 'terminal close' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_close_disabled(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["terminal", "close", "sess_1"])
        assert result.exit_code == 1

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_close_specific_session(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.close_session = AsyncMock()
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "close", "sess_1"])
        assert result.exit_code == 0
        assert "Closed session" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_close_all(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.list_sessions = AsyncMock(return_value=[{"id": "s1"}, {"id": "s2"}])
        maha.terminal_manager.close_all = AsyncMock()
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "close", "all"])
        assert result.exit_code == 0
        assert "2 session" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_terminal_close_all_empty(self, mock_app_cls):
        config = _make_mock_config()
        config.terminal.enabled = True
        maha = _make_mock_app()
        maha.config = config
        maha.terminal_manager = MagicMock()
        maha.terminal_manager.list_sessions = AsyncMock(return_value=[])
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["terminal", "close", "all"])
        assert result.exit_code == 0
        assert "No active sessions" in result.output


# ===========================================================================
# workers commands
# ===========================================================================


class TestWorkersSpawn:
    """Tests for 'workers spawn' command."""

    @patch("mahavishnu.workers.WorkerManager")
    @patch("mahavishnu.terminal.manager.TerminalManager")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_workers_spawn_success(self, mock_app_cls, mock_tm_cls, mock_wm_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_tm = MagicMock()
        mock_tm_cls.create = AsyncMock(return_value=mock_tm)
        mock_wm = MagicMock()
        mock_wm.spawn_workers = AsyncMock(return_value=["w1", "w2"])
        mock_wm.list_workers = AsyncMock(return_value=[])
        mock_wm_cls.return_value = mock_wm

        result = runner.invoke(
            cli_module.app, ["workers", "spawn", "-t", "terminal-qwen", "-n", "2"]
        )
        assert result.exit_code == 0
        assert "Spawned" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_workers_spawn_disabled(self, mock_app_cls):
        config = _make_mock_config()
        config.workers_enabled = False
        maha = _make_mock_app()
        maha.config = config
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["workers", "spawn", "-t", "terminal-qwen"])
        assert result.exit_code == 1
        assert "disabled" in result.output

    @patch("mahavishnu.workers.WorkerManager")
    @patch("mahavishnu.terminal.manager.TerminalManager")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_workers_spawn_error(self, mock_app_cls, mock_tm_cls, mock_wm_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_tm = MagicMock()
        mock_tm_cls.create = AsyncMock(return_value=mock_tm)
        mock_wm = MagicMock()
        mock_wm.spawn_workers = AsyncMock(side_effect=Exception("spawn failed"))
        mock_wm_cls.return_value = mock_wm

        result = runner.invoke(cli_module.app, ["workers", "spawn", "-t", "terminal-qwen"])
        assert result.exit_code == 1
        assert "spawn failed" in result.output


class TestWorkersListTypes:
    """Tests for 'workers list-types' command."""

    @patch("mahavishnu.workers.registry.validate_worker_dependencies")
    @patch("mahavishnu.workers.registry.get_workers_by_category")
    def test_workers_list_types_basic(self, mock_get_workers, mock_validate):
        from mahavishnu.workers.registry import WorkerCategory

        mock_config = MagicMock()
        mock_config.worker_type = "terminal-qwen"
        mock_config.name = "Qwen Terminal"
        mock_config.description = "Terminal worker with Qwen"
        mock_config.requires_tool = None

        mock_get_workers.return_value = {
            WorkerCategory.AI_ASSISTANT: [mock_config],
        }
        mock_validate.return_value = {"terminal-qwen": True}

        result = runner.invoke(cli_module.app, ["workers", "list-types"])
        assert result.exit_code == 0
        assert "terminal-qwen" in result.output

    @patch("mahavishnu.workers.registry.validate_worker_dependencies")
    @patch("mahavishnu.workers.registry.get_workers_by_category")
    def test_workers_list_types_invalid_category(self, mock_get_workers, mock_validate):
        mock_get_workers.return_value = {}
        mock_validate.return_value = {}

        result = runner.invoke(cli_module.app, ["workers", "list-types", "-c", "invalid_cat"])
        assert result.exit_code == 1
        assert "Invalid category" in result.output

    @patch("mahavishnu.workers.registry.validate_worker_dependencies")
    @patch("mahavishnu.workers.registry.get_workers_by_category")
    def test_workers_list_types_no_check(self, mock_get_workers, mock_validate):
        from mahavishnu.workers.registry import WorkerCategory

        mock_config = MagicMock()
        mock_config.worker_type = "terminal-qwen"
        mock_config.name = "Qwen"
        mock_config.description = "Terminal worker"
        mock_config.requires_tool = None

        mock_get_workers.return_value = {
            WorkerCategory.AI_ASSISTANT: [mock_config],
        }

        result = runner.invoke(cli_module.app, ["workers", "list-types", "--no-check"])
        assert result.exit_code == 0

    @patch("mahavishnu.workers.registry.get_worker_config")
    @patch("mahavishnu.workers.registry.validate_worker_dependencies")
    @patch("mahavishnu.workers.registry.get_workers_by_category")
    def test_workers_list_types_unavailable(self, mock_get_workers, mock_validate, mock_get_config):
        from mahavishnu.workers.registry import WorkerCategory

        mock_config = MagicMock()
        mock_config.worker_type = "special-worker"
        mock_config.name = "Special"
        mock_config.description = "Needs a tool"
        mock_config.requires_tool = "special_tool"

        mock_get_workers.return_value = {
            WorkerCategory.SHELL: [mock_config],
        }
        mock_validate.return_value = {"special-worker": False}
        mock_get_config.return_value = mock_config

        result = runner.invoke(cli_module.app, ["workers", "list-types"])
        assert result.exit_code == 0
        assert "special_tool" in result.output


# ===========================================================================
# pool commands
# ===========================================================================


class TestPoolSpawn:
    """Tests for 'pool spawn' command."""

    @patch("mahavishnu.mcp.protocols.message_bus.MessageBus")
    @patch("mahavishnu.pools.PoolManager")
    @patch("mahavishnu.terminal.manager.TerminalManager")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_spawn_success(self, mock_app_cls, mock_tm_cls, mock_pm_cls, mock_mb_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_tm = MagicMock()
        mock_tm_cls.create = AsyncMock(return_value=mock_tm)
        mock_mb = MagicMock()
        mock_mb_cls.return_value = mock_mb
        mock_pm = MagicMock()
        mock_pm.spawn_pool = AsyncMock(return_value="pool_1")
        mock_pm_cls.return_value = mock_pm

        result = runner.invoke(
            cli_module.app,
            ["pool", "spawn", "-t", "mahavishnu", "-n", "local", "-m", "2", "-M", "5"],
        )
        assert result.exit_code == 0
        assert "Spawned" in result.output
        assert "pool_1" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_spawn_disabled(self, mock_app_cls):
        config = _make_mock_config()
        config.pools.enabled = False
        config.pools_enabled = False
        maha = _make_mock_app()
        maha.config = config
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["pool", "spawn"])
        assert result.exit_code == 1
        assert "disabled" in result.output

    @patch("mahavishnu.mcp.protocols.message_bus.MessageBus")
    @patch("mahavishnu.pools.PoolManager")
    @patch("mahavishnu.terminal.manager.TerminalManager")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_spawn_error(self, mock_app_cls, mock_tm_cls, mock_pm_cls, mock_mb_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_tm = MagicMock()
        mock_tm_cls.create = AsyncMock(return_value=mock_tm)
        mock_mb = MagicMock()
        mock_mb_cls.return_value = mock_mb
        mock_pm = MagicMock()
        mock_pm.spawn_pool = AsyncMock(side_effect=Exception("spawn error"))
        mock_pm_cls.return_value = mock_pm

        result = runner.invoke(cli_module.app, ["pool", "spawn"])
        assert result.exit_code == 1


class TestPoolList:
    """Tests for 'pool list' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_list_no_manager(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "list"])
        assert result.exit_code == 1
        assert "No pool manager" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_list_empty(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(return_value=[])
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "list"])
        assert result.exit_code == 0
        assert "No active pools" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_list_with_pools(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(
            return_value=[
                {
                    "pool_id": "pool_1",
                    "pool_type": "mahavishnu",
                    "name": "local",
                    "status": "running",
                    "workers": 3,
                    "min_workers": 1,
                    "max_workers": 5,
                }
            ]
        )
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "list"])
        assert result.exit_code == 0
        assert "pool_1" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_list_error(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.list_pools = AsyncMock(side_effect=Exception("list error"))
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "list"])
        assert result.exit_code == 1


class TestPoolExecute:
    """Tests for 'pool execute' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_execute_no_manager(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "execute", "pool_1", "-p", "do something"])
        assert result.exit_code == 1

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_execute_success(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.execute_on_pool = AsyncMock(
            return_value={"status": "completed", "output": "result data"}
        )
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "execute", "pool_1", "-p", "do something"])
        assert result.exit_code == 0
        assert "completed" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_execute_with_error_output(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.execute_on_pool = AsyncMock(
            return_value={"status": "failed", "error": "something went wrong"}
        )
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "execute", "pool_1", "-p", "do something"])
        assert result.exit_code == 0
        assert "something went wrong" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_execute_value_error(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.execute_on_pool = AsyncMock(side_effect=ValueError("pool not found"))
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "execute", "pool_1", "-p", "do something"])
        assert result.exit_code == 1

    def test_pool_execute_missing_args(self):
        result = runner.invoke(cli_module.app, ["pool", "execute", "pool_1"])
        assert result.exit_code != 0


class TestPoolRoute:
    """Tests for 'pool route' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_route_no_manager(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "route", "-p", "do something"])
        assert result.exit_code == 1

    @patch("mahavishnu.pools.PoolSelector")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_route_success(self, mock_app_cls, mock_selector_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.route_task = AsyncMock(
            return_value={"pool_id": "pool_1", "status": "completed", "output": "done"}
        )
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app
        mock_selector_cls.return_value = MagicMock()

        result = runner.invoke(cli_module.app, ["pool", "route", "-p", "do something"])
        assert result.exit_code == 0
        assert "pool_1" in result.output

    @patch("mahavishnu.pools.PoolSelector")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_route_value_error(self, mock_app_cls, mock_selector_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.route_task = AsyncMock(side_effect=ValueError("bad selector"))
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app
        mock_selector_cls.return_value = MagicMock()

        result = runner.invoke(
            cli_module.app, ["pool", "route", "-p", "task", "-s", "bad_selector"]
        )
        assert result.exit_code == 1

    def test_pool_route_missing_prompt(self):
        result = runner.invoke(cli_module.app, ["pool", "route"])
        assert result.exit_code != 0


class TestPoolScale:
    """Tests for 'pool scale' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_scale_no_manager(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "scale", "pool_1", "-t", "10"])
        assert result.exit_code == 1

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_scale_not_found(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm._pools = {}
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "scale", "pool_1", "-t", "10"])
        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_scale_success(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pool = MagicMock()
        mock_pool._workers = ["w1", "w2", "w3"]
        mock_pool.scale = AsyncMock()
        mock_pm = MagicMock()
        mock_pm._pools = {"pool_1": mock_pool}
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "scale", "pool_1", "-t", "10"])
        assert result.exit_code == 0
        assert "Scaled" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_scale_not_implemented(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pool = MagicMock()
        mock_pool.scale = AsyncMock(side_effect=NotImplementedError("not implemented"))
        mock_pm = MagicMock()
        mock_pm._pools = {"pool_1": mock_pool}
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "scale", "pool_1", "-t", "10"])
        assert result.exit_code == 1

    def test_pool_scale_missing_args(self):
        result = runner.invoke(cli_module.app, ["pool", "scale", "pool_1"])
        assert result.exit_code != 0


class TestPoolClose:
    """Tests for 'pool close' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_close_no_manager(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "close", "pool_1"])
        assert result.exit_code == 1

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_close_success(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.close_pool = AsyncMock()
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "close", "pool_1"])
        assert result.exit_code == 0
        assert "Closed" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_close_error(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.close_pool = AsyncMock(side_effect=Exception("close error"))
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "close", "pool_1"])
        assert result.exit_code == 1


class TestPoolCloseAll:
    """Tests for 'pool close-all' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_close_all_no_manager(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "close-all"])
        assert result.exit_code == 1

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_close_all_success(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.close_all = AsyncMock()
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "close-all"])
        assert result.exit_code == 0
        assert "All pools closed" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_close_all_error(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.close_all = AsyncMock(side_effect=Exception("close all error"))
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "close-all"])
        assert result.exit_code == 1


class TestPoolHealth:
    """Tests for 'pool health' command."""

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_health_no_manager(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "health"])
        assert result.exit_code == 1

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_health_success(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.health_check = AsyncMock(
            return_value={
                "status": "healthy",
                "pools_active": 1,
                "pools": [
                    {
                        "pool_id": "pool_1",
                        "pool_type": "mahavishnu",
                        "status": "running",
                        "workers": 3,
                    }
                ],
            }
        )
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "health"])
        assert result.exit_code == 0
        assert "healthy" in result.output

    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_pool_health_error(self, mock_app_cls):
        mock_app = _make_mock_app()
        mock_pm = MagicMock()
        mock_pm.health_check = AsyncMock(side_effect=Exception("health error"))
        mock_app.pool_manager = mock_pm
        mock_app_cls.return_value = mock_app

        result = runner.invoke(cli_module.app, ["pool", "health"])
        assert result.exit_code == 1


# ===========================================================================
# shell command
# ===========================================================================


class TestShellCommand:
    """Tests for the 'shell' command."""

    @patch("mahavishnu.shell.MahavishnuShell")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_shell_disabled(self, mock_app_cls, mock_shell_cls):
        config = _make_mock_config()
        config.shell_enabled = False
        maha = _make_mock_app()
        maha.config = config
        mock_app_cls.return_value = maha

        result = runner.invoke(cli_module.app, ["shell"])
        assert result.exit_code == 1
        assert "disabled" in result.output

    @patch("mahavishnu.shell.MahavishnuShell")
    @patch("mahavishnu._main_cli.MahavishnuApp")
    def test_shell_success(self, mock_app_cls, mock_shell_cls):
        mock_app = _make_mock_app()
        mock_app_cls.return_value = mock_app
        mock_shell = MagicMock()
        mock_shell.start = MagicMock()
        mock_shell_cls.return_value = mock_shell

        result = runner.invoke(cli_module.app, ["shell"])
        assert result.exit_code == 0


# ===========================================================================
# dashboard command
# ===========================================================================


class TestDashboardCommand:
    """Tests for the 'dashboard' command."""

    def test_dashboard_help(self):
        """Verify dashboard command is registered."""
        result = runner.invoke(cli_module.app, ["dashboard", "--help"])
        assert result.exit_code == 0


# ===========================================================================
# Module-level constants
# ===========================================================================


class TestModuleConstants:
    """Tests for module-level constants."""

    def test_default_mcp_host(self):
        assert cli_module.DEFAULT_MCP_HOST == "127.0.0.1"

    def test_default_mcp_port(self):
        assert cli_module.DEFAULT_MCP_PORT == 8680
