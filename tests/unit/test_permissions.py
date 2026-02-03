"""Unit tests for permissions and JWT manager with comprehensive security validation."""

import pytest
from pydantic import ValidationError

from mahavishnu.core.config import MahavishnuSettings
from mahavishnu.core.errors import ConfigurationError
from mahavishnu.core.permissions import JWTManager, Permission, Role, RBACManager


class TestJWTManagerSecurity:
    """Security tests for JWTManager to prevent authentication bypass vulnerabilities."""

    def test_jwt_manager_rejects_missing_secret(self):
        """Test that JWTManager raises ConfigurationError when auth_secret is not set.

        This is CRITICAL security test to prevent authentication bypass.
        Previously, missing secrets would fallback to hardcoded secrets.
        """
        # Create config without auth_secret
        config = MahavishnuSettings(auth_enabled=False, auth_secret=None)

        # JWTManager should raise ConfigurationError
        with pytest.raises(ConfigurationError) as exc_info:
            JWTManager(config)

        error_message = str(exc_info.value)
        assert "MAHAVISHNU_AUTH_SECRET environment variable must be set" in error_message
        assert "secrets.token_urlsafe(32)" in error_message
        # Ensure no fallback secret mentioned
        assert "fallback" not in error_message.lower()

    def test_jwt_manager_rejects_short_secret(self):
        """Test that JWTManager raises ConfigurationError for secrets below minimum entropy.

        This ensures JWT secrets meet minimum security requirements (32+ characters).
        Short secrets are vulnerable to brute force attacks.
        """
        # Test with various short secrets (skip empty string as config validator catches it)
        short_secrets = [
            "x",  # 1 char
            "short",  # 5 chars
            "this_is_not_long_enough",  # 25 chars - still below 32
            "exactly_31_characters_long!!",  # 31 chars - just below threshold
        ]

        for short_secret in short_secrets:
            config = MahavishnuSettings(auth_enabled=True, auth_secret=short_secret)

            with pytest.raises(ConfigurationError) as exc_info:
                JWTManager(config)

            error_message = str(exc_info.value)
            assert "at least 32 characters long" in error_message
            assert f"Current length: {len(short_secret)} characters" in error_message

    def test_jwt_manager_accepts_minimum_length_secret(self):
        """Test that JWTManager accepts secrets that meet minimum length (32 chars)."""
        secret = "exactly_32_characters_long_12345"  # Exactly 32 chars
        assert len(secret) == 32, f"Test secret should be 32 chars, got {len(secret)}"

        config = MahavishnuSettings(auth_enabled=True, auth_secret=secret)

        # Should not raise
        jwt_manager = JWTManager(config)
        assert jwt_manager.secret == secret
        assert jwt_manager.algorithm == "HS256"
        assert jwt_manager.expire_minutes == 60

    def test_jwt_manager_accepts_long_secret(self):
        """Test that JWTManager accepts secrets longer than minimum (best practice)."""
        long_secret = "a_very_secure_secret_that_is_much_longer_than_required_12345678"
        config = MahavishnuSettings(auth_enabled=True, auth_secret=long_secret)

        # Should not raise
        jwt_manager = JWTManager(config)
        assert jwt_manager.secret == long_secret

    def test_jwt_manager_with_valid_secret(self):
        """Test that JWTManager works correctly with a valid secret."""
        secret = "test_secret_32_characters_long_xyz"
        config = MahavishnuSettings(auth_enabled=True, auth_secret=secret)

        # Should not raise
        jwt_manager = JWTManager(config)
        assert jwt_manager.secret == secret
        assert jwt_manager.algorithm == "HS256"
        assert jwt_manager.expire_minutes == 60

    def test_jwt_create_and_verify_token(self):
        """Test creating and verifying JWT tokens."""
        secret = "test_secret_32_characters_long_xyz"
        config = MahavishnuSettings(auth_enabled=True, auth_secret=secret)
        jwt_manager = JWTManager(config)

        # Create token
        token = jwt_manager.create_token("user_123")

        # Verify token
        payload = jwt_manager.verify_token(token)
        assert payload["user_id"] == "user_123"
        assert "exp" in payload
        assert "iat" in payload

    def test_jwt_token_refresh(self):
        """Test refreshing JWT tokens."""
        secret = "test_secret_32_characters_long_xyz"
        config = MahavishnuSettings(auth_enabled=True, auth_secret=secret)
        jwt_manager = JWTManager(config)

        # Create token
        original_token = jwt_manager.create_token("user_123")
        original_payload = jwt_manager.verify_token(original_token)

        # Refresh token
        refreshed_token = jwt_manager.refresh_token(original_token)
        refreshed_payload = jwt_manager.verify_token(refreshed_token)

        # User_id should be the same
        assert refreshed_payload["user_id"] == original_payload["user_id"]
        # Refreshed token should have new expiration
        assert "refreshed_at" in refreshed_payload

    def test_jwt_invalid_token_raises_error(self):
        """Test that invalid tokens raise ValueError."""
        secret = "test_secret_32_characters_long_xyz"
        config = MahavishnuSettings(auth_enabled=True, auth_secret=secret)
        jwt_manager = JWTManager(config)

        with pytest.raises(ValueError) as exc_info:
            jwt_manager.verify_token("invalid.token.here")

        assert "Invalid token" in str(exc_info.value)


class TestRBACManager:
    """Tests for Role-Based Access Control manager."""

    def test_rbac_manager_initialization(self):
        """Test RBAC manager initialization with default roles."""
        config = MahavishnuSettings()
        rbac = RBACManager(config)

        # Check default roles exist
        assert "admin" in rbac.roles
        assert "developer" in rbac.roles
        assert "viewer" in rbac.roles

        # Check admin has all permissions
        admin_role = rbac.roles["admin"]
        assert Permission.READ_REPO in admin_role.permissions
        assert Permission.WRITE_REPO in admin_role.permissions
        assert Permission.EXECUTE_WORKFLOW in admin_role.permissions

    def test_rbac_create_user(self):
        """Test creating a user with roles."""
        config = MahavishnuSettings()
        rbac = RBACManager(config)

        # Create user with developer role
        import asyncio

        user = asyncio.run(rbac.create_user("user_1", ["developer"], allowed_repos=["repo1", "repo2"]))

        assert user.user_id == "user_1"
        assert len(user.roles) == 1
        assert user.roles[0].name == "developer"
        assert user.roles[0].allowed_repos == ["repo1", "repo2"]

    def test_rbac_check_permission(self):
        """Test checking user permissions."""
        config = MahavishnuSettings()
        rbac = RBACManager(config)

        import asyncio

        # Create admin user with access to all repos
        admin = asyncio.run(rbac.create_user("admin_user", ["admin"]))

        # Admin should have all permissions on any repo
        has_perm = asyncio.run(rbac.check_permission("admin_user", "any_repo", Permission.WRITE_REPO))
        assert has_perm is True

        # Create viewer user with limited access
        viewer = asyncio.run(rbac.create_user("viewer_user", ["viewer"], allowed_repos=["repo1"]))

        # Viewer should not have write permission
        has_perm = asyncio.run(rbac.check_permission("viewer_user", "repo1", Permission.WRITE_REPO))
        assert has_perm is False

        # Viewer should have read permission on allowed repo
        has_perm = asyncio.run(rbac.check_permission("viewer_user", "repo1", Permission.READ_REPO))
        assert has_perm is True

        # Viewer should not have read permission on non-allowed repo
        has_perm = asyncio.run(rbac.check_permission("viewer_user", "repo2", Permission.READ_REPO))
        assert has_perm is False


class TestConfigurationValidation:
    """Tests for configuration-level validation of auth settings."""

    def test_config_requires_secret_when_auth_enabled(self):
        """Test that config validation requires auth_secret when auth_enabled is True."""
        with pytest.raises(ValidationError) as exc_info:
            MahavishnuSettings(auth_enabled=True, auth_secret=None)

        errors = exc_info.value.errors()
        assert any("auth_secret" in str(err.get("loc", "")) for err in errors)

    def test_config_accepts_none_secret_when_auth_disabled(self):
        """Test that config allows auth_secret=None when auth_enabled is False."""
        # Should not raise
        config = MahavishnuSettings(auth_enabled=False, auth_secret=None)
        assert config.auth_enabled is False
        assert config.auth_secret is None

    def test_config_validates_secret_length(self):
        """Test that config validates auth_secret minimum length."""
        # Config validator doesn't check length, but JWTManager does
        # This test ensures config can be created with short secret,
        # but JWTManager will reject it
        config = MahavishnuSettings(auth_enabled=True, auth_secret="short")
        assert config.auth_secret == "short"

        # JWTManager should reject it
        with pytest.raises(ConfigurationError) as exc_info:
            JWTManager(config)

        assert "at least 32 characters long" in str(exc_info.value)
