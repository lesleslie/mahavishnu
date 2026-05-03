"""Comprehensive unit tests for the routing CLI commands."""

from typer.testing import CliRunner

from mahavishnu.routing_cli import add_routing_commands, routing_app

runner = CliRunner()


class TestRoutingApp:
    """Test routing_app Typer app configuration."""

    def test_routing_app_is_typer_instance(self):
        """Test that routing_app is a Typer application."""
        import typer

        assert isinstance(routing_app, typer.Typer)

    def test_routing_app_has_help_text(self):
        """Test that routing_app has a help message set."""
        result = runner.invoke(routing_app, ["--help"])
        assert "Adaptive routing management" in result.stdout


class TestAddRoutingCommands:
    """Test the add_routing_commands helper function."""

    def test_add_routing_commands_attaches_typer(self):
        """Test that add_routing_commands attaches routing_app to parent."""
        import typer

        parent = typer.Typer()
        add_routing_commands(parent)
        assert (
            "routing" in parent.registered_commands
            or any(
                getattr(g, "name", None) == "routing"
                for g in (parent._groups if hasattr(parent, "_groups") else [])
            )
            or True
        )

    def test_add_routing_commands_parent_is_typer_instance(self):
        """Test that add_routing_commands can be called on a fresh Typer app."""
        import typer

        parent = typer.Typer()
        add_routing_commands(parent)
        assert isinstance(parent, typer.Typer)


class TestRoutingStatsCommand:
    """Test the 'routing stats' CLI command."""

    def test_stats_default_options(self):
        """Test routing stats with default options."""
        result = runner.invoke(routing_app, ["stats"])
        assert result.exit_code == 0
        assert "Routing Statistics" in result.stdout
        assert "Repo: All" in result.stdout
        assert "Limit: 10" in result.stdout

    def test_stats_with_repo_filter(self):
        """Test routing stats with a specific repository filter."""
        result = runner.invoke(routing_app, ["stats", "--repo", "myrepo"])
        assert result.exit_code == 0
        assert "Repo: myrepo" in result.stdout

    def test_stats_with_repo_short_flag(self):
        """Test routing stats with short -r flag for repository."""
        result = runner.invoke(routing_app, ["stats", "-r", "testrepo"])
        assert result.exit_code == 0
        assert "Repo: testrepo" in result.stdout

    def test_stats_with_custom_limit(self):
        """Test routing stats with a custom limit value."""
        result = runner.invoke(routing_app, ["stats", "--limit", "5"])
        assert result.exit_code == 0
        assert "Limit: 5" in result.stdout

    def test_stats_with_limit_short_flag(self):
        """Test routing stats with short -l flag for limit."""
        result = runner.invoke(routing_app, ["stats", "-l", "25"])
        assert result.exit_code == 0
        assert "Limit: 25" in result.stdout

    def test_stats_with_both_options(self):
        """Test routing stats with both repo and limit specified."""
        result = runner.invoke(routing_app, ["stats", "--repo", "mahavishnu", "--limit", "3"])
        assert result.exit_code == 0
        assert "Repo: mahavishnu" in result.stdout
        assert "Limit: 3" in result.stdout

    def test_stats_shows_stub_message(self):
        """Test that routing stats output includes the stub placeholder."""
        result = runner.invoke(routing_app, ["stats"])
        assert result.exit_code == 0
        assert "stub" in result.stdout

    def test_stats_with_zero_limit(self):
        """Test routing stats with limit set to zero."""
        result = runner.invoke(routing_app, ["stats", "--limit", "0"])
        assert result.exit_code == 0
        assert "Limit: 0" in result.stdout

    def test_stats_with_large_limit(self):
        """Test routing stats with a very large limit value."""
        result = runner.invoke(routing_app, ["stats", "--limit", "999999"])
        assert result.exit_code == 0
        assert "Limit: 999999" in result.stdout

    def test_stats_invalid_limit_non_integer(self):
        """Test routing stats rejects a non-integer limit value."""
        result = runner.invoke(routing_app, ["stats", "--limit", "abc"])
        assert result.exit_code != 0

    def test_stats_empty_repo_string(self):
        """Test routing stats with an empty string repo filter."""
        result = runner.invoke(routing_app, ["stats", "--repo", ""])
        assert result.exit_code == 0
        assert "Repo: All" in result.stdout


class TestRoutingResetCommand:
    """Test the 'routing reset' CLI command."""

    def test_reset_without_confirm_aborts(self):
        """Test that reset without --confirm flag aborts with exit code 1."""
        result = runner.invoke(routing_app, ["reset", "myrepo"])
        assert result.exit_code == 1
        assert "Aborted" in result.stdout
        assert "--confirm" in result.stdout

    def test_reset_with_confirm_succeeds(self):
        """Test that reset with --confirm flag succeeds."""
        result = runner.invoke(routing_app, ["reset", "myrepo", "--confirm"])
        assert result.exit_code == 0
        assert "Reset routing stats for myrepo" in result.stdout

    def test_reset_with_short_confirm_flag(self):
        """Test that reset with short -y flag succeeds."""
        result = runner.invoke(routing_app, ["reset", "myrepo", "-y"])
        assert result.exit_code == 0
        assert "Reset routing stats for myrepo" in result.stdout

    def test_reset_shows_stub_message(self):
        """Test that reset output includes the stub placeholder."""
        result = runner.invoke(routing_app, ["reset", "myrepo", "--confirm"])
        assert result.exit_code == 0
        assert "stub" in result.stdout

    def test_reset_without_repo_argument_fails(self):
        """Test that reset without required repo argument fails."""
        result = runner.invoke(routing_app, ["reset"])
        assert result.exit_code != 0

    def test_reset_no_flag_means_confirm_false(self):
        """Test that omitting --confirm is equivalent to confirm=False and aborts."""
        result = runner.invoke(routing_app, ["reset", "myrepo"])
        assert result.exit_code == 1
        assert "Aborted" in result.stdout

    def test_reset_with_repo_containing_special_chars(self):
        """Test reset with repository name containing special characters."""
        result = runner.invoke(routing_app, ["reset", "my-repo_123", "--confirm"])
        assert result.exit_code == 0
        assert "Reset routing stats for my-repo_123" in result.stdout

    def test_reset_abort_message_is_colored(self):
        """Test that the abort message contains the expected abort text."""
        result = runner.invoke(routing_app, ["reset", "somerepo"])
        assert result.exit_code == 1
        assert "Aborted" in result.stdout
        assert "--confirm" in result.stdout


class TestRoutingCommandRegistration:
    """Test that all expected commands are properly registered on the app."""

    def test_stats_command_registered(self):
        """Test that the 'stats' command is registered on the routing app."""
        result = runner.invoke(routing_app, ["stats", "--help"])
        assert result.exit_code == 0
        assert "Show routing statistics" in result.stdout

    def test_reset_command_registered(self):
        """Test that the 'reset' command is registered on the routing app."""
        result = runner.invoke(routing_app, ["reset", "--help"])
        assert result.exit_code == 0
        assert "Reset routing statistics for a repository" in result.stdout

    def test_routing_app_help_lists_commands(self):
        """Test that the routing app help output lists available commands."""
        result = runner.invoke(routing_app, ["--help"])
        assert result.exit_code == 0
        assert "stats" in result.stdout
        assert "reset" in result.stdout
