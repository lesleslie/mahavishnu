"""Unit tests for role-based repository management."""

from pathlib import Path

import yaml
import pytest

from mahavishnu.core.app import MahavishnuApp
from mahavishnu.core.errors import ValidationError


def _load_ecosystem_config() -> dict:
    """Load the current committed ecosystem config used by MahavishnuApp."""
    with open("settings/ecosystem.yaml") as f:
        return yaml.safe_load(f)


class TestRoles:
    """Test role-related functionality in MahavishnuApp."""

    def test_get_roles(self):
        """Test retrieving all available roles."""
        app = MahavishnuApp()
        roles = app.get_roles()
        ecosystem = _load_ecosystem_config()

        assert len(roles) == len(ecosystem["roles"])
        assert len(roles) > 0

        # Check structure of role objects
        role = roles[0]
        assert "name" in role
        assert "description" in role
        assert "tags" in role
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
        repos = app.get_repos_by_role("orchestrator")

        assert len(repos) == 1
        for repo in repos:
            assert repo.get("role") == "orchestrator"

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

        # Check specific nicknames
        assert "vishnu" in nicknames
        assert nicknames["vishnu"] == "mahavishnu"
        assert "vish" in nicknames
        assert nicknames["vish"] == "mahavishnu"

    def test_get_repos_with_role_filter(self):
        """Test get_repos with role parameter."""
        app = MahavishnuApp()

        # Test with orchestrator role
        repos = app.get_repos(role="orchestrator")
        assert len(repos) == 1
        assert "/Users/les/Projects/mahavishnu" in repos

        repos = app.get_repos(role="manager")
        assert len(repos) == 1
        assert "/Users/les/Projects/session-buddy" in repos

    def test_get_repos_without_filter(self):
        """Test get_repos without any filters returns all repos."""
        app = MahavishnuApp()
        repos = app.get_repos()

        expected_existing = [
            repo["path"] for repo in app.get_all_repos() if Path(repo["path"]).exists()
        ]
        assert len(repos) == len(expected_existing)

    def test_get_repos_with_tag_still_works(self):
        """Test that tag filtering still works alongside role filtering."""
        app = MahavishnuApp()

        # Test tag filtering
        repos = app.get_repos(tag="orchestrator")
        assert len(repos) > 0
        # All repos should have the requested tag
        for repo_path in repos:
            repos_list = app.get_all_repos()
            matching_repo = next((r for r in repos_list if r["path"] == repo_path), None)
            assert matching_repo is not None
            assert "orchestrator" in matching_repo.get("tags", [])

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

    def test_role_duties_are_lists_when_present(self):
        """Test that duties are lists for roles that define them."""
        app = MahavishnuApp()
        roles = app.get_roles()

        for role in roles:
            if "duties" in role:
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
            matching_repo = next((r for r in all_repos if r.get("name") == full_name), None)
            assert matching_repo is not None
            # Verify nickname matches
            assert nickname in app.get_repo_nicknames(matching_repo)
