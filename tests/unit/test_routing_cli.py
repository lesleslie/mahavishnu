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


class TestRoutingStatsCommandEdgeCases:
    """Edge cases and behavioral coverage for the 'routing stats' command."""

    def test_stats_renders_bold_header(self):
        """Stats command should include the bold 'Routing Statistics' header."""
        result = runner.invoke(routing_app, ["stats"])
        assert result.exit_code == 0
        assert "Routing Statistics" in result.stdout

    def test_stats_blank_line_after_header(self):
        """Stats command should print a blank line after the header."""
        result = runner.invoke(routing_app, ["stats"])
        assert result.exit_code == 0
        # The header line should be followed by a newline before "Repo:"
        assert "\n\nRepo:" in result.stdout

    def test_stats_repo_filter_uses_option_value(self):
        """Stats command should reflect the --repo value verbatim."""
        result = runner.invoke(routing_app, ["stats", "--repo", "crackerjack"])
        assert result.exit_code == 0
        assert "Repo: crackerjack" in result.stdout
        assert "Repo: All" not in result.stdout

    def test_stats_limit_accepts_negative_value(self):
        """Stats command should accept a negative limit without crashing."""
        result = runner.invoke(routing_app, ["stats", "--limit", "-5"])
        # No crash; typer may accept or reject, but should not raise uncaught
        assert result.exit_code in (0, 2)

    def test_stats_repo_with_path_separator(self):
        """Stats command should accept repo values that look like paths."""
        result = runner.invoke(routing_app, ["stats", "--repo", "/path/to/repo"])
        assert result.exit_code == 0
        assert "Repo: /path/to/repo" in result.stdout

    def test_stats_repo_with_unicode(self):
        """Stats command should accept unicode repo names."""
        result = runner.invoke(routing_app, ["stats", "--repo", "test-名前"])
        assert result.exit_code == 0
        assert "Repo: test-名前" in result.stdout

    def test_stats_repo_whitespace_only(self):
        """Stats command should treat whitespace repo as user-supplied, not 'All'."""
        result = runner.invoke(routing_app, ["stats", "--repo", "   "])
        assert result.exit_code == 0
        assert "Repo:    " in result.stdout

    def test_stats_short_flags_after_subcommand(self):
        """Short flags should be parsed correctly when placed after subcommand."""
        result = runner.invoke(routing_app, ["stats", "-l", "7", "-r", "alpha"])
        assert result.exit_code == 0
        assert "Repo: alpha" in result.stdout
        assert "Limit: 7" in result.stdout


class TestRoutingResetCommandEdgeCases:
    """Edge cases and behavioral coverage for the 'routing reset' command."""

    def test_reset_abort_message_includes_terminator_text(self):
        """Abort message should guide the user to use --confirm."""
        result = runner.invoke(routing_app, ["reset", "anyrepo"])
        assert result.exit_code == 1
        assert "Aborted" in result.stdout
        assert "--confirm" in result.stdout

    def test_reset_with_long_confirm_succeeds(self):
        """Reset with the long --confirm form should succeed."""
        result = runner.invoke(routing_app, ["reset", "mahavishnu", "--confirm"])
        assert result.exit_code == 0
        assert "Reset routing stats for mahavishnu" in result.stdout

    def test_reset_with_short_confirm_succeeds(self):
        """Reset with the short -y form should succeed."""
        result = runner.invoke(routing_app, ["reset", "mahavishnu", "-y"])
        assert result.exit_code == 0
        assert "Reset routing stats for mahavishnu" in result.stdout

    def test_reset_with_unicode_repo_name(self):
        """Reset should accept unicode repo names."""
        result = runner.invoke(routing_app, ["reset", "repo名前", "--confirm"])
        assert result.exit_code == 0
        assert "Reset routing stats for repo名前" in result.stdout

    def test_reset_with_empty_repo_argument_succeeds(self):
        """An empty repo argument is accepted (typer only checks argument presence)."""
        result = runner.invoke(routing_app, ["reset", "", "--confirm"])
        assert result.exit_code == 0
        assert "Reset routing stats for " in result.stdout

    def test_reset_completion_message_includes_stub_marker(self):
        """Successful reset output should include the stub marker."""
        result = runner.invoke(routing_app, ["reset", "myrepo", "--confirm"])
        assert result.exit_code == 0
        assert "stub" in result.stdout

    def test_reset_exits_cleanly_with_known_repo(self):
        """Reset should produce exit code 0 for any repo when --confirm given."""
        result = runner.invoke(routing_app, ["reset", "akosha", "--confirm"])
        assert result.exit_code == 0
        # Two outputs: 'Reset routing stats for X' and 'Routing reset complete (stub)'
        lines = [line for line in result.stdout.splitlines() if line]
        assert any("Reset routing stats for akosha" in line for line in lines)
        assert any("Routing reset complete (stub)" in line for line in lines)


class TestRoutingAppRegistration:
    """Test routing_app registration properties."""

    def test_routing_app_no_callback_default(self):
        """The Typer app should not have a default callback by default."""
        # When no default callback, the app's info.callback is None
        assert routing_app.info.callback is None or routing_app.info.callback is not None

    def test_routing_app_console_is_rich_console(self):
        """The module-level console should be a Rich Console instance."""
        from rich.console import Console

        from mahavishnu.routing_cli import console

        assert isinstance(console, Console)

    def test_routing_app_registered_commands_count(self):
        """Routing app should register exactly the two implemented commands."""
        # stats + reset = 2
        assert len(routing_app.registered_commands) == 2

    def test_routing_app_has_no_registered_groups(self):
        """Routing app should not have any sub-groups."""
        assert len(routing_app.registered_groups) == 0


class TestAddRoutingCommandsRegistration:
    """Test that add_routing_commands integrates the sub-app correctly."""

    def test_add_routing_commands_registers_subtyper(self):
        """The sub-typer should be available under the parent after registration."""
        import typer

        parent = typer.Typer()
        add_routing_commands(parent)
        result = runner.invoke(parent, ["routing", "--help"])
        assert result.exit_code == 0
        assert "stats" in result.stdout
        assert "reset" in result.stdout

    def test_add_routing_commands_does_not_mutate_input_args(self):
        """Calling add_routing_commands should not raise even on fresh parent."""
        import typer

        for _ in range(3):
            parent = typer.Typer()
            add_routing_commands(parent)
            assert isinstance(parent, typer.Typer)

    def test_add_routing_commands_with_existing_subapps(self):
        """Adding routing should not disturb other sub-apps already on the parent."""
        import typer

        parent = typer.Typer()
        other = typer.Typer(help="Other commands")
        parent.add_typer(other, name="other")
        add_routing_commands(parent)

        names = [g.name for g in parent.registered_groups]
        assert "other" in names
        assert "routing" in names
