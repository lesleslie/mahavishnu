"""Unit tests for automation module."""

import pytest

from mahavishnu.automation import AutomationManager
from mahavishnu.automation.errors import (
    AutomationError,
    BlockedAppError,
    BlockedTextError,
    PermissionDeniedError,
    ScreenshotError,
)
from mahavishnu.automation.security import (
    AutomationSecurity,
    DEFAULT_BLOCKED_APPS,
    DEFAULT_BLOCKED_PATTERNS,
)
from mahavishnu.automation.permissions import PermissionChecker


@pytest.fixture
def automation_manager():
    """Create an automation manager for testing."""
    return AutomationManager()


@pytest.fixture
def automation_security():
    """Create security instance for testing."""
    return AutomationSecurity()


@pytest.fixture
def permission_checker():
    """Create permission checker for testing."""
    return PermissionChecker()


class TestAutomationSecurity:
    """Tests for AutomationSecurity."""

    def test_default_blocked_apps_not_empty(self):
        """Test that default blocked apps are defined."""
        assert len(DEFAULT_BLOCKED_APPS) > 0
        # Critical security apps should be blocked
        assert "com.apple.KeychainAccess" in DEFAULT_BLOCKED_APPS
        assert "com.apple.securityd" in DEFAULT_BLOCKED_APPS

    def test_default_blocked_patterns_not_empty(self):
        """Test that default blocked patterns are defined."""
        assert len(DEFAULT_BLOCKED_PATTERNS) > 0
        assert "password" in DEFAULT_BLOCKED_PATTERNS
        assert "secret" in DEFAULT_BLOCKED_PATTERNS

    def test_app_validation_allowed(self, automation_security: AutomationSecurity):
        """Test that valid apps pass security check."""
        # Valid app should pass (not raise)
        automation_security.validate_app("com.apple.finder")

    def test_blocked_app_raises_error(self, automation_security: AutomationSecurity):
        """Test that blocked apps raise error."""
        with pytest.raises(BlockedAppError):
            automation_security.validate_app("com.apple.KeychainAccess")

    def test_text_validation_allowed(self, automation_security: AutomationSecurity):
        """Test that valid text passes text validation."""
        # Valid text should pass (not raise)
        automation_security.validate_text("Hello World")

    def test_text_validation_blocked_patterns(self, automation_security: AutomationSecurity):
        """Test that blocked text patterns raise error."""
        with pytest.raises(BlockedTextError):
            automation_security.validate_text("This is my password")

        with pytest.raises(BlockedTextError):
            automation_security.validate_text("my password is secret123")

    def test_rate_limiting_allows_initial(self, automation_security: AutomationSecurity):
        """Test that rate limiting allows initial operations."""
        # Should allow initially
        for _ in range(5):
            result = automation_security.check_rate_limit("session-1")
            assert result is True

    def test_rate_limiting_blocks_excess(self, automation_security: AutomationSecurity):
        """Test that rate limiting blocks excess operations."""
        # Set a low limit for testing
        automation_security.config.max_operations_per_second = 5

        # Use up the limit
        for _ in range(5):
            automation_security.check_rate_limit("session-2")

        # Next should be blocked
        result = automation_security.check_rate_limit("session-2")
        assert result is False

    def test_is_app_allowed(self, automation_security: AutomationSecurity):
        """Test is_app_allowed method."""
        assert automation_security.is_app_allowed("com.apple.finder") is True
        assert automation_security.is_app_allowed("com.apple.KeychainAccess") is False

    def test_is_text_allowed(self, automation_security: AutomationSecurity):
        """Test is_text_allowed method."""
        is_allowed, pattern = automation_security.is_text_allowed("Hello World")
        assert is_allowed is True
        assert pattern is None

        is_allowed, pattern = automation_security.is_text_allowed("my password")
        assert is_allowed is False
        assert pattern is not None


class TestPermissionChecker:
    """Tests for PermissionChecker."""

    def test_check_accessibility(self, permission_checker: PermissionChecker):
        """Test accessibility check."""
        result = permission_checker.check_accessibility()
        # Result depends on system state
        assert isinstance(result, bool)

    def test_check_screen_recording(self, permission_checker: PermissionChecker):
        """Test screen recording check."""
        result = permission_checker.check_screen_recording()
        # Result depends on system state
        assert isinstance(result, bool)

    def test_get_all_permissions(self, permission_checker: PermissionChecker):
        """Test get_all_permissions."""
        permissions = permission_checker.get_all_permissions()
        assert len(permissions) >= 2
        # First permission should be accessibility (required)
        assert permissions[0].required is True


class TestAutomationErrors:
    """Tests for automation errors."""

    def test_automation_error(self):
        """Test AutomationError creation."""
        error = AutomationError(message="Test error")
        assert error.message == "Test error"
        assert "Test error" in str(error)
        assert error.details == {}

    def test_blocked_app_error(self):
        """Test BlockedAppError creation."""
        error = BlockedAppError(bundle_id="com.apple.KeychainAccess")
        assert "com.apple.KeychainAccess" in str(error)
        assert error.details["bundle_id"] == "com.apple.KeychainAccess"

    def test_blocked_text_error(self):
        """Test BlockedTextError creation."""
        error = BlockedTextError(pattern="password")
        # Check that the error message contains relevant info
        assert error.details["pattern"] == "password"
        assert "sensitive" in error.message.lower() or "text" in error.message.lower()

    def test_permission_denied_error(self):
        """Test PermissionDeniedError creation."""
        error = PermissionDeniedError(
            message="Test permission denied",
            permission_type="accessibility",
        )
        assert error.message == "Test permission denied"
        assert error.details["permission_type"] == "accessibility"

    def test_screenshot_error(self):
        """Test ScreenshotError creation."""
        error = ScreenshotError(message="Test screenshot error")
        assert "Test screenshot error" in str(error)
        assert error.details.get("region") is None

        error_with_region = ScreenshotError(
            message="Test error",
            region=(0, 0, 100, 100),
        )
        assert error_with_region.details["region"] == (0, 0, 100, 100)

    def test_error_to_dict(self):
        """Test error serialization."""
        error = AutomationError(
            message="Test error",
            details={"key": "value"},
        )
        result = error.to_dict()
        assert "error" in result
        assert "message" in result
        assert "details" in result
        assert result["message"] == "Test error"
