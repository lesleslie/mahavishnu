"""Unit tests for role-based repository management."""
import pytest
from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.errors import ValidationError


class TestRoles:
    """Test role-related functionality in MahavishnuApp."""

    def test_get_roles(self):
        """Test retrieving all available roles."""
        app = MahavishnuApp()
        roles = app.get_roles()

        # Should return 12 roles
        assert len(roles) == 12

        # Check structure of role objects
        role = roles[0]
        assert "name" in role
        assert "description" in role
        assert "tags" in role
        assert "duties" in role
        assert "capabilities" in role

    def test_get_role_by_name_valid(self):
        """Test retrieving a role by valid name."""
        app = MahavishnuApp()
        role = app.get_role_by_name("orchestrator")

        assert role is not None
        assert role["name"] == "orchestrator"
        assert "coordinates workflows" in role["description"].lower()
        assert "sweep" in role["capabilities"]

    def test_get_role_by_name_invalid(self):
        """Test retrieving a non-existent role."""
        app = MahavishnuApp()
        role = app.get_role_by_name("nonexistent_role")

        assert role is None

    def test_get_repos_by_role_valid(self):
        """Test filtering repositories by valid role."""
        app = MahavishnuApp()
        repos = app.get_repos_by_role("tool")

        # Should return MCP tool repos
        assert len(repos) > 0
        for repo in repos:
            assert repo.get("role") == "tool"

    def test_get_repos_by_role_invalid(self):
        """Test filtering repositories by invalid role."""
        app = MahavishnuApp()

        with pytest.raises(ValidationError) as exc_info:
            app.get_repos_by_role("invalid_role")

        assert "Invalid role" in str(exc_info.value)
        assert "invalid_role" in exc_info.value.details["role"]

    def test_get_all_nicknames(self):
        """Test retrieving all repository nicknames."""
        app = MahavishnuApp()
        nicknames = app.get_all_nicknames()

        # Should have 3 nicknames
        assert len(nicknames) == 3

        # Check specific nicknames
        assert "vishnu" in nicknames
        assert nicknames["vishnu"] == "mahavishnu"
        assert "jack" in nicknames
        assert nicknames["jack"] == "crackerjack"
        assert "buddy" in nicknames
        assert nicknames["buddy"] == "session-buddy"

    def test_get_repos_with_role_filter(self):
        """Test get_repos with role parameter."""
        app = MahavishnuApp()

        # Test with orchestrator role
        repos = app.get_repos(role="orchestrator")
        assert len(repos) == 1
        assert "/Users/les/Projects/mahavishnu" in repos

        # Test with tool role
        repos = app.get_repos(role="tool")
        assert len(repos) >= 9  # All the MCP tools
        for repo in repos:
            # Verify the path contains the repo name
            assert "mcp" in repo.lower()

    def test_get_repos_without_filter(self):
        """Test get_repos without any filters returns all repos."""
        app = MahavishnuApp()
        repos = app.get_repos()

        # Should return all 24 repos
        assert len(repos) == 24

    def test_get_repos_with_tag_still_works(self):
        """Test that tag filtering still works alongside role filtering."""
        app = MahavishnuApp()

        # Test tag filtering
        repos = app.get_repos(tag="mcp")
        assert len(repos) > 0
        # All repos should have "mcp" in their tags
        for repo_path in repos:
            # Get the repo from config to check tags
            repos_list = app.get_all_repos()
            matching_repo = next(
                (r for r in repos_list if r["path"] == repo_path),
                None
            )
            assert matching_repo is not None
            assert "mcp" in matching_repo.get("tags", [])

    def test_role_validation_in_get_repos(self):
        """Test that invalid role raises ValidationError in get_repos."""
        app = MahavishnuApp()

        with pytest.raises(ValidationError) as exc_info:
            app.get_repos(role="nonexistent_role")

        error = exc_info.value
        assert "Invalid role" in error.message
        assert "nonexistent_role" in error.details["role"]
        assert "valid_roles" in error.details

    def test_role_capabilities_list(self):
        """Test that all roles have capabilities defined."""
        app = MahavishnuApp()
        roles = app.get_roles()

        for role in roles:
            # Every role should have capabilities
            assert "capabilities" in role
            assert isinstance(role["capabilities"], list)
            assert len(role["capabilities"]) > 0

    def test_role_duties_list(self):
        """Test that all roles have duties defined."""
        app = MahavishnuApp()
        roles = app.get_roles()

        for role in roles:
            # Every role should have duties
            assert "duties" in role
            assert isinstance(role["duties"], list)
            assert len(role["duties"]) > 0

    def test_role_tags_list(self):
        """Test that all roles have tags defined."""
        app = MahavishnuApp()
        roles = app.get_roles()

        for role in roles:
            # Every role should have tags
            assert "tags" in role
            assert isinstance(role["tags"], list)
            assert len(role["tags"]) > 0


class TestRoleIntegration:
    """Integration tests for role-based workflows."""

    def test_show_role_workflow(self):
        """Test the complete show-role workflow."""
        app = MahavishnuApp()

        # Get role details
        role = app.get_role_by_name("orchestrator")
        assert role is not None

        # Get repos with this role
        repos = app.get_repos_by_role("orchestrator")
        assert len(repos) >= 1

        # Verify repos match the role
        for repo in repos:
            assert repo.get("role") == "orchestrator"

    def test_list_roles_then_filter(self):
        """Test listing roles then filtering by each role."""
        app = MahavishnuApp()

        # Get all roles
        roles = app.get_roles()
        role_names = [r["name"] for r in roles]

        # For each role, verify filtering works
        for role_name in role_names:
            repos = app.get_repos_by_role(role_name)
            # All returned repos should have this role
            for repo in repos:
                assert repo.get("role") == role_name

    def test_nicknames_map_to_correct_repos(self):
        """Test that nicknames map to the correct repository names."""
        app = MahavishnuApp()
        nicknames = app.get_all_nicknames()
        all_repos = app.get_all_repos()

        for nickname, full_name in nicknames.items():
            # Find the repo with this name
            matching_repo = next(
                (r for r in all_repos if r.get("name") == full_name),
                None
            )
            assert matching_repo is not None
            # Verify nickname matches
            assert matching_repo.get("nickname") == nickname
