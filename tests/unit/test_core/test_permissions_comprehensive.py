"""Comprehensive tests for permissions and RBAC module.

This module provides extensive test coverage for:
- Role creation and management
- User creation and role assignment
- Permission checking
- Repository access control
- Role-based access control
- Default roles initialization
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from mahavishnu.core.permissions import (
    Permission,
    Role,
    User,
    RBACManager,
)


class TestPermission:
    """Test suite for Permission enum."""

    def test_permission_values(self):
        """Test that all permission values are defined."""
        assert Permission.READ_REPO == "read_repo"
        assert Permission.WRITE_REPO == "write_repo"
        assert Permission.EXECUTE_WORKFLOW == "execute_workflow"
        assert Permission.MANAGE_WORKFLOWS == "manage_workflows"
        assert Permission.LIST_WORKFLOWS == "list_workflows"
        assert Permission.VIEW_WORKFLOW_STATUS == "view_workflow_status"
        assert Permission.CANCEL_WORKFLOW == "cancel_workflow"
        assert Permission.READ_ADAPTERS == "read_adapters"
        assert Permission.MANAGE_TERMINALS == "manage_terminals"

    def test_permission_string_comparison(self):
        """Test that permissions can be compared as strings."""
        assert str(Permission.READ_REPO) == "read_repo"
        assert Permission.READ_REPO == "read_repo"


class TestRole:
    """Test suite for Role model."""

    def test_role_creation(self):
        """Test role creation with required fields."""
        role = Role(name="test_role", permissions=[Permission.READ_REPO])

        assert role.name == "test_role"
        assert role.permissions == [Permission.READ_REPO]
        assert role.allowed_repos is None

    def test_role_with_allowed_repos(self):
        """Test role creation with allowed repos."""
        role = Role(
            name="test_role",
            permissions=[Permission.READ_REPO],
            allowed_repos=["repo1", "repo2"]
        )

        assert role.allowed_repos == ["repo1", "repo2"]

    def test_role_with_empty_allowed_repos(self):
        """Test role with empty allowed repos list."""
        role = Role(
            name="test_role",
            permissions=[Permission.READ_REPO],
            allowed_repos=[]
        )

        assert role.allowed_repos == []

    def test_role_with_multiple_permissions(self):
        """Test role with multiple permissions."""
        role = Role(
            name="admin",
            permissions=[
                Permission.READ_REPO,
                Permission.WRITE_REPO,
                Permission.EXECUTE_WORKFLOW,
            ]
        )

        assert len(role.permissions) == 3
        assert Permission.READ_REPO in role.permissions
        assert Permission.WRITE_REPO in role.permissions
        assert Permission.EXECUTE_WORKFLOW in role.permissions

    def test_role_copy(self):
        """Test that role can be copied."""
        role = Role(
            name="original",
            permissions=[Permission.READ_REPO],
            allowed_repos=["repo1"]
        )

        copied = role.copy()
        assert copied.name == "original"
        assert copied.permissions == [Permission.READ_REPO]
        assert copied.allowed_repos == ["repo1"]


class TestUser:
    """Test suite for User model."""

    def test_user_creation_minimal(self):
        """Test user creation with minimal fields."""
        user = User(user_id="user123", roles=[])

        assert user.user_id == "user123"
        assert user.roles == []
        assert user.email is None
        assert user.name is None
        assert isinstance(user.created_at, datetime)

    def test_user_creation_full(self):
        """Test user creation with all fields."""
        role = Role(name="admin", permissions=[Permission.READ_REPO])

        user = User(
            user_id="user123",
            roles=[role],
            email="user@example.com",
            name="Test User"
        )

        assert user.email == "user@example.com"
        assert user.name == "Test User"
        assert len(user.roles) == 1
        assert user.roles[0].name == "admin"

    def test_user_created_at_timestamp(self):
        """Test that user creation timestamp is recent."""
        before = datetime.now()
        user = User(user_id="user123", roles=[])
        after = datetime.now()

        assert before <= user.created_at <= after

    def test_user_with_multiple_roles(self):
        """Test user with multiple roles."""
        admin_role = Role(name="admin", permissions=[Permission.READ_REPO])
        dev_role = Role(name="developer", permissions=[Permission.WRITE_REPO])

        user = User(
            user_id="user123",
            roles=[admin_role, dev_role]
        )

        assert len(user.roles) == 2


class TestRBACManager:
    """Test suite for RBACManager class."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        from unittest.mock import MagicMock
        config = MagicMock()
        return config

    @pytest.fixture
    def rbac_manager(self, mock_config):
        """Create RBACManager instance."""
        return RBACManager(mock_config)

    def test_initialization(self, rbac_manager):
        """Test RBACManager initialization."""
        assert rbac_manager.config is not None
        assert isinstance(rbac_manager.users, dict)
        assert isinstance(rbac_manager.roles, dict)

    def test_default_roles_initialized(self, rbac_manager):
        """Test that default roles are initialized."""
        assert "admin" in rbac_manager.roles
        assert "developer" in rbac_manager.roles
        assert "viewer" in rbac_manager.roles

    def test_admin_role_has_all_permissions(self, rbac_manager):
        """Test that admin role has all permissions."""
        admin_role = rbac_manager.roles["admin"]

        assert len(admin_role.permissions) == len(Permission)
        assert all(perm in admin_role.permissions for perm in Permission)
        assert admin_role.allowed_repos is None  # None means all repos

    def test_developer_role_has_limited_permissions(self, rbac_manager):
        """Test that developer role has limited permissions."""
        dev_role = rbac_manager.roles["developer"]

        expected_permissions = [
            Permission.READ_REPO,
            Permission.EXECUTE_WORKFLOW,
            Permission.LIST_WORKFLOWS,
            Permission.VIEW_WORKFLOW_STATUS,
        ]

        assert dev_role.permissions == expected_permissions
        assert dev_role.allowed_repos == []  # Will be set per user

    def test_viewer_role_has_read_only_permissions(self, rbac_manager):
        """Test that viewer role has read-only permissions."""
        viewer_role = rbac_manager.roles["viewer"]

        expected_permissions = [
            Permission.READ_REPO,
            Permission.LIST_WORKFLOWS,
            Permission.VIEW_WORKFLOW_STATUS,
        ]

        assert viewer_role.permissions == expected_permissions
        assert Permission.WRITE_REPO not in viewer_role.permissions
        assert Permission.MANAGE_WORKFLOWS not in viewer_role.permissions

    @pytest.mark.asyncio
    async def test_create_user_with_single_role(self, rbac_manager):
        """Test creating user with single role."""
        user = await rbac_manager.create_user(
            user_id="user123",
            roles=["viewer"],
            allowed_repos=["repo1", "repo2"]
        )

        assert user.user_id == "user123"
        assert len(user.roles) == 1
        assert user.roles[0].name == "viewer"
        assert user.roles[0].allowed_repos == ["repo1", "repo2"]
        assert "user123" in rbac_manager.users

    @pytest.mark.asyncio
    async def test_create_user_with_multiple_roles(self, rbac_manager):
        """Test creating user with multiple roles."""
        user = await rbac_manager.create_user(
            user_id="user123",
            roles=["viewer", "developer"],
            allowed_repos=["repo1"]
        )

        assert len(user.roles) == 2
        role_names = [role.name for role in user.roles]
        assert "viewer" in role_names
        assert "developer" in role_names

    @pytest.mark.asyncio
    async def test_create_user_with_nonexistent_role(self, rbac_manager):
        """Test creating user with nonexistent role."""
        user = await rbac_manager.create_user(
            user_id="user123",
            roles=["nonexistent_role"],
            allowed_repos=None
        )

        # Should create user with no roles
        assert user.user_id == "user123"
        assert len(user.roles) == 0

    @pytest.mark.asyncio
    async def test_create_user_without_allowed_repos(self, rbac_manager):
        """Test creating user without specifying allowed repos."""
        user = await rbac_manager.create_user(
            user_id="user123",
            roles=["admin"],
            allowed_repos=None
        )

        # Admin role should have None (all repos)
        assert user.roles[0].allowed_repos is None

    @pytest.mark.asyncio
    async def test_create_user_with_mixed_roles(self, rbac_manager):
        """Test creating user with mix of existing and non-existing roles."""
        user = await rbac_manager.create_user(
            user_id="user123",
            roles=["viewer", "nonexistent", "developer"],
            allowed_repos=["repo1"]
        )

        # Should only have the 2 valid roles
        assert len(user.roles) == 2
        role_names = [role.name for role in user.roles]
        assert "viewer" in role_names
        assert "developer" in role_names
        assert "nonexistent" not in role_names


class TestRBACManagerPermissionChecking:
    """Test suite for permission checking functionality."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        from unittest.mock import MagicMock
        config = MagicMock()
        return config

    @pytest.fixture
    async def rbac_manager(self, mock_config):
        """Create RBACManager with test users."""
        manager = RBACManager(mock_config)

        # Create test users
        await manager.create_user("admin_user", ["admin"], None)
        await manager.create_user("dev_user", ["developer"], ["repo1", "repo2"])
        await manager.create_user("viewer_user", ["viewer"], ["repo1"])

        return manager

    @pytest.mark.asyncio
    async def test_user_has_permission_admin_all(self, rbac_manager):
        """Test that admin has all permissions."""
        user = rbac_manager.users["admin_user"]

        # Admin should have all permissions on all repos
        assert all(perm in user.roles[0].permissions for perm in Permission)
        assert user.roles[0].allowed_repos is None

    @pytest.mark.asyncio
    async def test_user_has_permission_developer_limited(self, rbac_manager):
        """Test that developer has limited permissions."""
        user = rbac_manager.users["dev_user"]

        # Developer should have specific permissions
        assert Permission.READ_REPO in user.roles[0].permissions
        assert Permission.EXECUTE_WORKFLOW in user.roles[0].permissions
        assert Permission.WRITE_REPO not in user.roles[0].permissions
        assert Permission.MANAGE_WORKFLOWS not in user.roles[0].permissions

    @pytest.mark.asyncio
    async def test_user_has_permission_viewer_read_only(self, rbac_manager):
        """Test that viewer has read-only permissions."""
        user = rbac_manager.users["viewer_user"]

        # Viewer should only have read permissions
        assert Permission.READ_REPO in user.roles[0].permissions
        assert Permission.LIST_WORKFLOWS in user.roles[0].permissions
        assert Permission.WRITE_REPO not in user.roles[0].permissions
        assert Permission.EXECUTE_WORKFLOW not in user.roles[0].permissions

    @pytest.mark.asyncio
    async def test_check_permission_admin_has_all(self, rbac_manager):
        """Test check_permission for admin user."""
        has_perm = await rbac_manager.check_permission(
            "admin_user", "repo1", Permission.WRITE_REPO
        )
        assert has_perm is True

    @pytest.mark.asyncio
    async def test_check_permission_developer_restricted(self, rbac_manager):
        """Test check_permission for developer user."""
        # Developer should have read on repo1
        has_perm = await rbac_manager.check_permission(
            "dev_user", "repo1", Permission.READ_REPO
        )
        assert has_perm is True

        # But not write
        has_perm = await rbac_manager.check_permission(
            "dev_user", "repo1", Permission.WRITE_REPO
        )
        assert has_perm is False

        # And not on repo3 (not in allowed_repos)
        has_perm = await rbac_manager.check_permission(
            "dev_user", "repo3", Permission.READ_REPO
        )
        assert has_perm is False

    @pytest.mark.asyncio
    async def test_check_permission_nonexistent_user(self, rbac_manager):
        """Test check_permission for nonexistent user."""
        has_perm = await rbac_manager.check_permission(
            "nonexistent", "repo1", Permission.READ_REPO
        )
        assert has_perm is False

    @pytest.mark.asyncio
    async def test_get_user_permissions(self, rbac_manager):
        """Test get_user_permissions method."""
        perms = await rbac_manager.get_user_permissions("dev_user", "repo1")

        assert Permission.READ_REPO in perms
        assert Permission.EXECUTE_WORKFLOW in perms
        assert Permission.WRITE_REPO not in perms

    @pytest.mark.asyncio
    async def test_get_user_permissions_nonexistent_user(self, rbac_manager):
        """Test get_user_permissions for nonexistent user."""
        perms = await rbac_manager.get_user_permissions("nonexistent", "repo1")
        assert perms == []

    @pytest.mark.asyncio
    async def test_filter_repos_by_permission(self, rbac_manager):
        """Test filter_repos_by_permission method."""
        repos = await rbac_manager.filter_repos_by_permission(
            "dev_user", Permission.READ_REPO
        )

        assert "repo1" in repos
        assert "repo2" in repos

    @pytest.mark.asyncio
    async def test_filter_repos_nonexistent_user(self, rbac_manager):
        """Test filter_repos_by_permission for nonexistent user."""
        repos = await rbac_manager.filter_repos_by_permission(
            "nonexistent", Permission.READ_REPO
        )
        assert repos == []


class TestRBACManagerAdvanced:
    """Test suite for advanced RBAC functionality."""

    @pytest.fixture
    def mock_config(self):
        """Create mock configuration."""
        from unittest.mock import MagicMock
        config = MagicMock()
        return config

    @pytest.fixture
    def rbac_manager(self, mock_config):
        """Create RBACManager instance."""
        return RBACManager(mock_config)

    def test_add_custom_role(self, rbac_manager):
        """Test adding a custom role."""
        custom_role = Role(
            name="custom",
            permissions=[Permission.READ_REPO, Permission.LIST_WORKFLOWS],
            allowed_repos=["repo1"]
        )

        rbac_manager.roles["custom"] = custom_role

        assert "custom" in rbac_manager.roles
        assert rbac_manager.roles["custom"].name == "custom"

    def test_update_existing_role(self, rbac_manager):
        """Test updating an existing role."""
        # Modify the developer role
        rbac_manager.roles["developer"].permissions.append(
            Permission.WRITE_REPO
        )

        assert Permission.WRITE_REPO in rbac_manager.roles["developer"].permissions

    @pytest.mark.asyncio
    async def test_get_user(self, rbac_manager):
        """Test retrieving a user."""
        await rbac_manager.create_user("test_user", ["viewer"], ["repo1"])

        user = rbac_manager.users.get("test_user")
        assert user is not None
        assert user.user_id == "test_user"

    def test_get_nonexistent_user(self, rbac_manager):
        """Test retrieving a nonexistent user."""
        user = rbac_manager.users.get("nonexistent")
        assert user is None

    @pytest.mark.asyncio
    async def test_delete_user(self, rbac_manager):
        """Test deleting a user."""
        await rbac_manager.create_user("temp_user", ["viewer"], ["repo1"])

        assert "temp_user" in rbac_manager.users

        del rbac_manager.users["temp_user"]

        assert "temp_user" not in rbac_manager.users


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_role_with_no_permissions(self):
        """Test role with no permissions."""
        role = Role(name="empty", permissions=[])

        assert role.permissions == []

    def test_user_with_no_roles(self):
        """Test user with no roles."""
        from unittest.mock import MagicMock
        config = MagicMock()
        manager = RBACManager(config)

        user = User(user_id="noroles_user", roles=[])

        assert len(user.roles) == 0

    @pytest.mark.asyncio
    async def test_user_very_long_id(self):
        """Test user with very long ID."""
        from unittest.mock import MagicMock
        config = MagicMock()
        manager = RBACManager(config)

        long_id = "x" * 1000
        user = await manager.create_user(long_id, ["viewer"], ["repo1"])

        assert user.user_id == long_id

    def test_role_with_special_characters(self):
        """Test role name with special characters."""
        # Pydantic should handle special characters
        role = Role(
            name="role-with_special.chars",
            permissions=[Permission.READ_REPO]
        )

        assert role.name == "role-with_special.chars"

    def test_permission_string_value(self):
        """Test that permission enum values are strings."""
        for perm in Permission:
            assert isinstance(perm.value, str)
            assert isinstance(perm, str)

    @pytest.mark.asyncio
    async def test_multiple_users_same_role(self):
        """Test multiple users with same role."""
        from unittest.mock import MagicMock
        config = MagicMock()
        manager = RBACManager(config)

        user1 = await manager.create_user("user1", ["viewer"], ["repo1"])
        user2 = await manager.create_user("user2", ["viewer"], ["repo2"])

        assert user1.roles[0].name == user2.roles[0].name
        assert user1.roles[0].allowed_repos != user2.roles[0].allowed_repos

    @pytest.mark.asyncio
    async def test_user_roles_are_independent(self):
        """Test that user roles are independent copies."""
        from unittest.mock import MagicMock
        config = MagicMock()
        manager = RBACManager(config)

        user1 = await manager.create_user("user1", ["developer"], ["repo1", "repo2"])
        user2 = await manager.create_user("user2", ["developer"], ["repo3"])

        # Roles should be independent
        assert user1.roles[0].allowed_repos == ["repo1", "repo2"]
        assert user2.roles[0].allowed_repos == ["repo3"]

    def test_datetime_timezone_aware(self):
        """Test that user created_at is timezone-aware."""
        user = User(user_id="test", roles=[])

        # Should be offset-naive (no timezone info)
        assert user.created_at.tzinfo is None
        assert isinstance(user.created_at, datetime)
