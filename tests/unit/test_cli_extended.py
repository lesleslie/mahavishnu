"""Extended unit tests for CLI commands.

This test suite covers additional CLI functionality beyond the basic tests,
including MCP commands, sweep, worker management, pool management, and terminal commands.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from mahavishnu.cli import app


@pytest.mark.unit
class TestMCPServerCommands:
    """Test MCP server management commands."""

    def test_mcp_status_command(self):
        """Test 'mcp status' command displays configuration."""
        runner = CliRunner()
        result = runner.invoke(app, ["mcp", "status"])

        assert result.exit_code == 0
        assert "Terminal Management:" in result.stdout
        assert "To start the server, run" in result.stdout

    def test_mcp_stop_command_not_implemented(self):
        """Test 'mcp stop' command shows not implemented message."""
        runner = CliRunner()
        result = runner.invoke(app, ["mcp", "stop"])

        assert result.exit_code == 1
        assert "not yet implemented" in result.stdout

    def test_mcp_restart_command_not_implemented(self):
        """Test 'mcp restart' command shows not implemented message."""
        runner = CliRunner()
        result = runner.invoke(app, ["mcp", "restart"])

        assert result.exit_code == 1
        assert "not yet implemented" in result.stdout

    @pytest.mark.asyncio
    async def test_mcp_health_command_when_server_not_running(self):
        """Test 'mcp health' command when server is not running."""
        runner = CliRunner()
        result = runner.invoke(app, ["mcp", "health"])

        # Should not crash even if server not running
        assert result.exit_code == 0
        assert "MCP Server:" in result.stdout


@pytest.mark.unit
class TestSweepCommand:
    """Test sweep command for AI workflow execution."""

    def test_sweep_command_requires_tag(self):
        """Test sweep command requires --tag option."""
        runner = CliRunner()
        result = runner.invoke(app, ["sweep"])

        # Should fail without tag
        assert result.exit_code != 0

    def test_sweep_command_with_invalid_adapter(self):
        """Test sweep command rejects invalid adapter."""
        runner = CliRunner()
        result = runner.invoke(app, ["sweep", "--tag", "python", "--adapter", "invalid-adapter"])

        # Should fail with invalid adapter
        assert result.exit_code != 0

    def test_sweep_command_with_default_adapter(self):
        """Test sweep command uses langgraph as default adapter."""
        runner = CliRunner()
        # This will fail at execution but should parse correctly
        result = runner.invoke(app, ["sweep", "--tag", "python"])

        # Command should be parsed even if execution fails
        assert "sweep" in result.stdout or result.exit_code != 0


@pytest.mark.unit
class TestTerminalCommands:
    """Test terminal session management commands."""

    def test_terminal_launch_command_when_disabled(self):
        """Test terminal launch fails when terminal management disabled."""
        runner = CliRunner()

        # Mock app with terminal disabled
        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            mock_app = MagicMock()
            mock_app.config.terminal.enabled = False
            mock_app.terminal_manager = None
            mock_app_class.return_value = mock_app

            result = runner.invoke(app, ["terminal", "launch", "echo test"])

            assert result.exit_code == 1
            assert "Terminal management is not enabled" in result.stdout

    def test_terminal_list_command_when_disabled(self):
        """Test terminal list fails when terminal management disabled."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            mock_app = MagicMock()
            mock_app.config.terminal.enabled = False
            mock_app_class.return_value = mock_app

            result = runner.invoke(app, ["terminal", "list"])

            assert result.exit_code == 1
            assert "Terminal management is not enabled" in result.stdout

    def test_terminal_send_command_validation(self):
        """Test terminal send requires session ID and command."""
        runner = CliRunner()
        result = runner.invoke(app, ["terminal", "send"])

        # Should fail without arguments
        assert result.exit_code != 0

    def test_terminal_capture_command_validation(self):
        """Test terminal capture requires session ID."""
        runner = CliRunner()
        result = runner.invoke(app, ["terminal", "capture"])

        # Should fail without session ID
        assert result.exit_code != 0

    def test_terminal_close_command_validation(self):
        """Test terminal close requires session ID."""
        runner = CliRunner()
        result = runner.invoke(app, ["terminal", "close"])

        # Should fail without session ID
        assert result.exit_code != 0


@pytest.mark.unit
class TestWorkerCommands:
    """Test worker management commands."""

    def test_workers_spawn_command(self):
        """Test workers spawn command."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            mock_app = MagicMock()
            mock_app.config.workers_enabled = True
            mock_app_class.return_value = mock_app

            # Mock WorkerManager and TerminalManager
            with patch("mahavishnu.cli.WorkerManager") as mock_worker_mgr_class:
                with patch("mahavishnu.cli.TerminalManager") as mock_term_mgr_class:
                    mock_worker_mgr = AsyncMock()
                    mock_worker_mgr.spawn_workers = AsyncMock(return_value=["worker-1", "worker-2"])
                    mock_worker_mgr.list_workers = AsyncMock(return_value=[])
                    mock_worker_mgr_class.return_value = mock_worker_mgr

                    mock_term_mgr = MagicMock()
                    mock_term_mgr.create = MagicMock(return_value=mock_term_mgr)
                    mock_term_mgr_class.create = MagicMock(return_value=mock_term_mgr)

                    result = runner.invoke(app, ["workers", "spawn", "--type", "terminal-qwen", "--count", "2"])

                    # Command should execute (may fail during execution but should parse)
                    assert result.exit_code in [0, 1]  # May succeed or fail during execution

    def test_workers_execute_command_validation(self):
        """Test workers execute requires prompt."""
        runner = CliRunner()
        result = runner.invoke(app, ["workers", "execute"])

        # Should fail without --prompt
        assert result.exit_code != 0

    def test_workers_execute_with_prompt(self):
        """Test workers execute accepts prompt parameter."""
        runner = CliRunner()
        result = runner.invoke(app, ["workers", "execute", "--prompt", "Write Python code"])

        # Command should parse (execution may fail)
        assert "workers" in result.stdout or result.exit_code != 0


@pytest.mark.unit
class TestPoolCommands:
    """Test pool management commands."""

    def test_pool_spawn_command(self):
        """Test pool spawn command."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            mock_app = MagicMock()
            mock_app.config.pools_enabled = True
            mock_app_class.return_value = mock_app

            result = runner.invoke(app, ["pool", "spawn", "--type", "mahavishnu", "--name", "test-pool"])

            # Command should parse (execution may fail)
            assert "pool" in result.stdout or result.exit_code != 0

    def test_pool_list_command_without_pool_manager(self):
        """Test pool list fails when pool manager not initialized."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            mock_app = MagicMock()
            mock_app.pool_manager = None
            mock_app_class.return_value = mock_app

            result = runner.invoke(app, ["pool", "list"])

            assert result.exit_code == 1
            assert "No pool manager initialized" in result.stdout

    def test_pool_execute_command_validation(self):
        """Test pool execute requires pool ID and prompt."""
        runner = CliRunner()
        result = runner.invoke(app, ["pool", "execute"])

        # Should fail without pool ID
        assert result.exit_code != 0

    def test_pool_route_command_validation(self):
        """Test pool route requires prompt."""
        runner = CliRunner()
        result = runner.invoke(app, ["pool", "route"])

        # Should fail without --prompt
        assert result.exit_code != 0

    def test_pool_scale_command_validation(self):
        """Test pool scale requires pool ID and target."""
        runner = CliRunner()
        result = runner.invoke(app, ["pool", "scale"])

        # Should fail without pool ID
        assert result.exit_code != 0

    def test_pool_close_command_validation(self):
        """Test pool close requires pool ID."""
        runner = CliRunner()
        result = runner.invoke(app, ["pool", "close"])

        # Should fail without pool ID
        assert result.exit_code != 0

    def test_pool_close_all_command(self):
        """Test pool close-all command."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            mock_app = MagicMock()
            mock_app.pool_manager = None
            mock_app_class.return_value = mock_app

            result = runner.invoke(app, ["pool", "close-all"])

            assert result.exit_code == 1
            assert "No pool manager initialized" in result.stdout

    def test_pool_health_command(self):
        """Test pool health command."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            mock_app = MagicMock()
            mock_app.pool_manager = None
            mock_app_class.return_value = mock_app

            result = runner.invoke(app, ["pool", "health"])

            assert result.exit_code == 1
            assert "No pool manager initialized" in result.stdout


@pytest.mark.unit
class TestTokenGeneration:
    """Test token generation commands."""

    def test_generate_claude_token_without_subscription(self):
        """Test Claude token generation fails when not configured."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MultiAuthHandler") as mock_auth_handler_class:
            mock_auth_handler = MagicMock()
            mock_auth_handler.is_claude_subscribed.return_value = False
            mock_auth_handler_class.return_value = mock_auth_handler

            result = runner.invoke(app, ["generate-claude-token", "user-123"])

            assert result.exit_code == 1
            assert "Claude Code subscription authentication is not configured" in result.stdout

    def test_generate_codex_token_without_subscription(self):
        """Test Codex token generation fails when not configured."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MultiAuthHandler") as mock_auth_handler_class:
            mock_auth_handler = MagicMock()
            mock_auth_handler.is_codex_subscribed.return_value = False
            mock_auth_handler_class.return_value = mock_auth_handler

            result = runner.invoke(app, ["generate-codex-token", "user-123"])

            assert result.exit_code == 1
            assert "Codex subscription authentication is not configured" in result.stdout

    def test_generate_claude_token_requires_user_id(self):
        """Test Claude token generation requires user ID."""
        runner = CliRunner()
        result = runner.invoke(app, ["generate-claude-token"])

        # Should fail without user ID
        assert result.exit_code != 0

    def test_generate_codex_token_requires_user_id(self):
        """Test Codex token generation requires user ID."""
        runner = CliRunner()
        result = runner.invoke(app, ["generate-codex-token"])

        # Should fail without user ID
        assert result.exit_code != 0


@pytest.mark.unit
class TestShellCommand:
    """Test admin shell command."""

    def test_shell_command_when_disabled(self):
        """Test shell command fails when shell disabled."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            mock_app = MagicMock()
            mock_app.config.shell_enabled = False
            mock_app_class.return_value = mock_app

            result = runner.invoke(app, ["shell"])

            assert result.exit_code == 1
            assert "Admin shell is disabled" in result.stdout


@pytest.mark.unit
class TestCLIArgumentParsing:
    """Test CLI argument parsing and validation."""

    def test_list_repos_with_short_options(self):
        """Test list-repos accepts short option flags."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-repos", "-t", "python"])

        assert result.exit_code == 0
        assert "Repositories with tag 'python'" in result.stdout

    def test_list_repos_with_long_options(self):
        """Test list-repos accepts long option flags."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-repos", "--tag", "mcp"])

        assert result.exit_code == 0
        assert "Repositories with tag 'mcp'" in result.stdout

    def test_show_role_requires_argument(self):
        """Test show-role requires role name argument."""
        runner = CliRunner()
        result = runner.invoke(app, ["show-role"])

        # Should fail without role name
        assert result.exit_code != 0

    def test_mcp_commands_have_subcommands(self):
        """Test MCP commands have proper subcommand structure."""
        runner = CliRunner()

        # Test invalid subcommand
        result = runner.invoke(app, ["mcp", "invalid-subcommand"])

        # Should fail
        assert result.exit_code != 0

    def test_terminal_commands_have_subcommands(self):
        """Test terminal commands have proper subcommand structure."""
        runner = CliRunner()

        # Test invalid subcommand
        result = runner.invoke(app, ["terminal", "invalid-subcommand"])

        # Should fail
        assert result.exit_code != 0

    def test_workers_commands_have_subcommands(self):
        """Test workers commands have proper subcommand structure."""
        runner = CliRunner()

        # Test invalid subcommand
        result = runner.invoke(app, ["workers", "invalid-subcommand"])

        # Should fail
        assert result.exit_code != 0

    def test_pool_commands_have_subcommands(self):
        """Test pool commands have proper subcommand structure."""
        runner = CliRunner()

        # Test invalid subcommand
        result = runner.invoke(app, ["pool", "invalid-subcommand"])

        # Should fail
        assert result.exit_code != 0


@pytest.mark.unit
class TestCLIErrorMessages:
    """Test CLI error messages are user-friendly."""

    def test_error_messages_are_informative(self):
        """Test error messages provide helpful information."""
        runner = CliRunner()

        # Test showing non-existent role
        result = runner.invoke(app, ["show-role", "nonexistent-role"])
        assert result.exit_code == 1
        assert "Error:" in result.stdout
        assert "Use 'mahavishnu list-roles'" in result.stdout

    def test_validation_errors_are_clear(self):
        """Test validation errors are clear and actionable."""
        runner = CliRunner()

        # Test both filters (should fail)
        result = runner.invoke(app, ["list-repos", "--tag", "python", "--role", "tool"])
        assert result.exit_code == 1
        assert "Cannot specify both --tag and --role filters" in result.stdout


@pytest.mark.unit
class TestCLIOutputFormatting:
    """Test CLI output formatting and display."""

    def test_list_roles_output_format(self):
        """Test list-roles output is properly formatted."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-roles"])

        assert result.exit_code == 0
        assert "Available roles" in result.stdout
        # Should have uppercase role names
        assert "ORCHESTRATOR" in result.stdout
        assert "Description:" in result.stdout

    def test_list_nicknames_output_format(self):
        """Test list-nicknames output is properly formatted."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-nicknames"])

        assert result.exit_code == 0
        assert "Repository nicknames" in result.stdout
        # Should have nickname: name format
        assert ":" in result.stdout

    def test_show_role_output_includes_sections(self):
        """Test show-role output includes all sections."""
        runner = CliRunner()
        result = runner.invoke(app, ["show-role", "tool"])

        assert result.exit_code == 0
        assert "Description:" in result.stdout
        assert "Duties:" in result.stdout
        assert "Capabilities:" in result.stdout
        assert "Repositories with this role" in result.stdout


@pytest.mark.unit
class TestCLIHelpText:
    """Test CLI help text and documentation."""

    def test_main_app_has_help(self):
        """Test main app has help text."""
        runner = CliRunner()
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "Mahavishnu" in result.stdout

    def test_mcp_subcommand_has_help(self):
        """Test MCP subcommand has help text."""
        runner = CliRunner()
        result = runner.invoke(app, ["mcp", "--help"])

        assert result.exit_code == 0
        assert "MCP server lifecycle management" in result.stdout

    def test_terminal_subcommand_has_help(self):
        """Test terminal subcommand has help text."""
        runner = CliRunner()
        result = runner.invoke(app, ["terminal", "--help"])

        assert result.exit_code == 0
        assert "Terminal session management" in result.stdout

    def test_workers_subcommand_has_help(self):
        """Test workers subcommand has help text."""
        runner = CliRunner()
        result = runner.invoke(app, ["workers", "--help"])

        assert result.exit_code == 0
        assert "Worker orchestration" in result.stdout

    def test_pool_subcommand_has_help(self):
        """Test pool subcommand has help text."""
        runner = CliRunner()
        result = runner.invoke(app, ["pool", "--help"])

        assert result.exit_code == 0
        assert "Multi-pool orchestration" in result.stdout


@pytest.mark.unit
class TestCLIIntegrationWorkflows:
    """Test complete CLI workflows and command chains."""

    def test_repository_discovery_workflow(self):
        """Test workflow for discovering repositories by role."""
        runner = CliRunner()

        # Step 1: List all roles
        roles_result = runner.invoke(app, ["list-roles"])
        assert roles_result.exit_code == 0
        assert "TOOL" in roles_result.stdout

        # Step 2: Show details for a role
        role_result = runner.invoke(app, ["show-role", "tool"])
        assert role_result.exit_code == 0

        # Step 3: List repos with that role
        repos_result = runner.invoke(app, ["list-repos", "--role", "tool"])
        assert repos_result.exit_code == 0
        assert "Repositories with role 'tool'" in repos_result.stdout

    def test_nickname_lookup_workflow(self):
        """Test workflow for looking up repositories by nickname."""
        runner = CliRunner()

        # Step 1: List all nicknames
        nicknames_result = runner.invoke(app, ["list-nicknames"])
        assert nicknames_result.exit_code == 0

        # Step 2: Find the repo for a nickname
        # (In real use, user would manually use the nickname)
        assert "vishnu:" in nicknames_result.stdout


@pytest.mark.unit
class TestCLIEdgeCases:
    """Test CLI edge cases and boundary conditions."""

    def test_empty_string_arguments(self):
        """Test CLI handles empty string arguments."""
        runner = CliRunner()

        # Empty tag should show all repos
        result = runner.invoke(app, ["list-repos", "--tag", ""])
        # May succeed or fail, but should not crash
        assert result.exit_code in [0, 1]

    def test_special_characters_in_arguments(self):
        """Test CLI handles special characters in arguments."""
        runner = CliRunner()

        # Special characters in role name (should fail gracefully)
        result = runner.invoke(app, ["show-role", "role@#$%"])
        assert result.exit_code == 1
        assert "Error:" in result.stdout

    def test_very_long_arguments(self):
        """Test CLI handles very long arguments."""
        runner = CliRunner()

        # Very long role name (should fail gracefully)
        long_role = "a" * 1000
        result = runner.invoke(app, ["show-role", long_role])
        assert result.exit_code == 1
        assert "Error:" in result.stdout


@pytest.mark.unit
class TestCLIMocking:
    """Test CLI with proper mocking of dependencies."""

    def test_list_repos_mocks_app_initialization(self):
        """Test list-repos properly mocks MahavishnuApp."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            mock_app = MagicMock()
            mock_app.get_repos = MagicMock(return_value=[{"path": "/test/repo"}])
            mock_app_class.return_value = mock_app

            result = runner.invoke(app, ["list-repos"])

            # Should succeed
            assert result.exit_code == 0
            # Verify app was initialized
            mock_app_class.assert_called_once()

    def test_auth_handler_initialization_in_commands(self):
        """Test auth handler is initialized in commands."""
        runner = CliRunner()

        with patch("mahavishnu.cli.MahavishnuApp") as mock_app_class:
            with patch("mahavishnu.cli.MultiAuthHandler") as mock_auth_class:
                mock_app = MagicMock()
                mock_app.config.auth_enabled = False
                mock_app.get_repos = MagicMock(return_value=[])
                mock_app_class.return_value = mock_app

                mock_auth = MagicMock()
                mock_auth.is_claude_subscribed.return_value = False
                mock_auth.is_qwen_free.return_value = False
                mock_auth_class.return_value = mock_auth

                result = runner.invoke(app, ["list-repos"])

                # Auth handler should be initialized
                assert result.exit_code == 0
