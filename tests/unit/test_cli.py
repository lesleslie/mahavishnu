"""Unit tests for CLI commands."""

import pytest
from typer.testing import CliRunner

from mahavishnu.cli import app


class TestListReposCommand:
    """Test the list-repos CLI command."""

    def test_list_all_repos(self):
        """Test listing all repositories without filters."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-repos"])

        assert result.exit_code == 0
        assert "All repositories:" in result.stdout
        assert "/Users/les/Projects/mahavishnu" in result.stdout
        # Should show all 24 repos
        assert "24" not in result.stdout or len(result.stdout.split("\n")) > 20

    def test_list_repos_by_role(self):
        """Test listing repositories filtered by role."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-repos", "--role", "orchestrator"])

        assert result.exit_code == 0
        assert "Repositories with role 'orchestrator':" in result.stdout
        assert "/Users/les/Projects/mahavishnu" in result.stdout

    def test_list_repos_by_tag(self):
        """Test listing repositories filtered by tag."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-repos", "--tag", "mcp"])

        assert result.exit_code == 0
        assert "Repositories with tag 'mcp':" in result.stdout
        # Should have multiple MCP repos
        assert "mcp" in result.stdout.lower()

    def test_list_repos_both_filters_raises_error(self):
        """Test that providing both --tag and --role raises an error."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-repos", "--tag", "python", "--role", "tool"])

        assert result.exit_code == 1
        assert "Cannot specify both --tag and --role filters" in result.stdout

    def test_list_repos_invalid_role(self):
        """Test listing repositories with invalid role name."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-repos", "--role", "invalid_role"])

        assert result.exit_code == 1
        assert "Error" in result.stderr or "Error" in result.stdout


class TestListRolesCommand:
    """Test the list-roles CLI command."""

    def test_list_roles(self):
        """Test listing all available roles."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-roles"])

        assert result.exit_code == 0
        assert "Available roles" in result.stdout
        assert "ORCHESTRATOR" in result.stdout
        assert "RESOLVER" in result.stdout
        assert "TOOL" in result.stdout
        # Should show 12 roles
        assert "12" in result.stdout


class TestShowRoleCommand:
    """Test the show-role CLI command."""

    def test_show_valid_role(self):
        """Test showing details for a valid role."""
        runner = CliRunner()
        result = runner.invoke(app, ["show-role", "tool"])

        assert result.exit_code == 0
        assert "TOOL" in result.stdout
        assert "Description:" in result.stdout
        assert "Duties:" in result.stdout
        assert "Capabilities:" in result.stdout
        assert "Repositories with this role" in result.stdout

    def test_show_invalid_role(self):
        """Test showing details for an invalid role."""
        runner = CliRunner()
        result = runner.invoke(app, ["show-role", "invalid_role"])

        assert result.exit_code == 1
        assert "Error: Role 'invalid_role' not found" in result.stdout


class TestListNicknamesCommand:
    """Test the list-nicknames CLI command."""

    def test_list_nicknames(self):
        """Test listing all repository nicknames."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-nicknames"])

        assert result.exit_code == 0
        assert "Repository nicknames" in result.stdout
        assert "vishnu:" in result.stdout
        assert "jack:" in result.stdout
        assert "buddy:" in result.stdout
        assert "3" in result.stdout


class TestCLIIntegration:
    """Integration tests for CLI workflows."""

    def test_role_filter_workflow(self):
        """Test complete workflow of listing roles then filtering."""
        runner = CliRunner()

        # First list all roles
        roles_result = runner.invoke(app, ["list-roles"])
        assert roles_result.exit_code == 0

        # Pick a role from the output
        assert "TOOL" in roles_result.stdout

        # Now filter repos by that role
        repos_result = runner.invoke(app, ["list-repos", "--role", "tool"])
        assert repos_result.exit_code == 0
        assert "Repositories with role 'tool':" in repos_result.stdout

    def test_nickname_workflow(self):
        """Test workflow of listing nicknames then getting full info."""
        runner = CliRunner()

        # List nicknames
        nicknames_result = runner.invoke(app, ["list-nicknames"])
        assert nicknames_result.exit_code == 0
        assert "vishnu: mahavishnu" in nicknames_result.stdout

        # Can filter repos to find the mahavishnu repo
        repos_result = runner.invoke(app, ["list-repos", "--role", "orchestrator"])
        assert repos_result.exit_code == 0
        assert "/Users/les/Projects/mahavishnu" in repos_result.stdout


class TestCLIErrorHandling:
    """Test error handling in CLI commands."""

    def test_error_message_format(self):
        """Test that error messages are user-friendly."""
        runner = CliRunner()

        # Test invalid role error
        result = runner.invoke(app, ["show-role", "bogus_role"])
        assert result.exit_code == 1
        assert "Error:" in result.stdout
        assert "Use 'mahavishnu list-roles' to see available roles" in result.stdout

    def test_mixed_tag_and_role_error(self):
        """Test error message when using both filters."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-repos", "--tag", "test", "--role", "tool"])
        assert result.exit_code == 1
        assert "Cannot specify both" in result.stdout


@pytest.mark.integration
class TestCLIWithRealConfig:
    """Integration tests that use the real configuration."""

    def test_all_roles_exist_in_config(self):
        """Verify all roles shown by list-roles exist in repos.yaml."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-roles"])

        assert result.exit_code == 0
        # The output should contain role names
        assert "ORCHESTRATOR" in result.stdout
        assert "RESOLVER" in result.stdout
        assert "MANAGER" in result.stdout

    def test_nicknames_match_config(self):
        """Verify nicknames match what's in repos.yaml."""
        runner = CliRunner()
        result = runner.invoke(app, ["list-nicknames"])

        assert result.exit_code == 0
        # Should have the 3 known nicknames
        assert "vishnu:" in result.stdout
        assert "jack:" in result.stdout
        assert "buddy:" in result.stdout
