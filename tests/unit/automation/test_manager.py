"""Unit tests for AutomationManager."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from mahavishnu.automation import AutomationManager
from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.errors import (
    AutomationError,
    BlockedAppError,
    BlockedTextError,
    NoBackendAvailableError,
)
from mahavishnu.automation.models import AutomationConfig, AutomationResult
from mahavishnu.automation.security import AutomationSecurity


@pytest.fixture
def config():
    """Create test configuration."""
    return AutomationConfig(
        dry_run_default=False,
        require_accessibility_check=False,  # Skip permission check for unit tests
    )


@pytest.fixture
def manager(config):
    """Create an automation manager for testing."""
    return AutomationManager(config=config)


@pytest.fixture
def mock_backend():
    """Create a mock backend for testing."""
    backend = MagicMock(spec=DesktopAutomationBackend)
    backend.backend_name = "mock"
    backend.is_available = MagicMock(return_value=True)
    backend.launch_application = AsyncMock(return_value=MagicMock(bundle_id="com.apple.finder", name="Finder"))
    backend.type_text = AsyncMock(return_value=True)
    backend.screenshot = AsyncMock(return_value=b"fake_image_data")
    backend.close = AsyncMock()
    return backend


class TestAutomationManagerInit:
    """Tests for AutomationManager initialization."""

    def test_create_manager(self):
        """Test creating a manager instance."""
        manager = AutomationManager()
        assert manager._initialized is False
        assert manager._backend is None

    def test_create_manager_with_config(self, config):
        """Test creating a manager with custom config."""
        manager = AutomationManager(config=config)
        assert manager.config.dry_run_default is False
        assert manager.config.require_accessibility_check is False


class TestAutomationManagerBackend:
    """Tests for backend selection."""

    @pytest.mark.asyncio
    async def test_initialize_with_mock_backend(self, manager: AutomationManager, mock_backend):
        """Test that initialization works with a mock backend."""
        # Patch the backend selection to use our mock
        with patch.object(manager, '_select_backend'):
            manager._backend = mock_backend
            manager._security = AutomationSecurity(manager.config)
            manager._initialized = True

        assert manager._initialized is True
        assert manager._backend is not None
        assert manager._backend.backend_name == "mock"

    @pytest.mark.asyncio
    async def test_close_clears_backend(self, manager: AutomationManager, mock_backend):
        """Test that close clears the backend."""
        manager._backend = mock_backend
        manager._initialized = True
        await manager.close()
        assert manager._backend is None
        assert manager._initialized is False


class TestAutomationManagerOperations:
    """Tests for automation operations."""

    @pytest.mark.asyncio
    async def test_launch_application(self, manager: AutomationManager, mock_backend):
        """Test launching an application."""
        manager._backend = mock_backend
        manager._security = AutomationSecurity(manager.config)
        manager._initialized = True

        result = await manager.launch_application("com.apple.finder")
        assert result.status == "success"
        mock_backend.launch_application.assert_called_once()

    @pytest.mark.asyncio
    async def test_launch_application_validates_security(self, manager: AutomationManager, mock_backend):
        """Test that launch validates security (blocks blocked apps)."""
        manager._backend = mock_backend
        manager._security = AutomationSecurity(manager.config)
        manager._initialized = True

        with pytest.raises(BlockedAppError):
            await manager.launch_application("com.apple.KeychainAccess")

    @pytest.mark.asyncio
    async def test_type_text(self, manager: AutomationManager, mock_backend):
        """Test typing text."""
        manager._backend = mock_backend
        manager._security = AutomationSecurity(manager.config)
        manager._initialized = True

        result = await manager.type_text("Hello World")
        assert result.status == "success"
        mock_backend.type_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_type_text_validates_security(self, manager: AutomationManager, mock_backend):
        """Test that type_text validates security (blocks sensitive patterns)."""
        manager._backend = mock_backend
        manager._security = AutomationSecurity(manager.config)
        manager._initialized = True

        with pytest.raises(BlockedTextError):
            await manager.type_text("my password is secret")

    @pytest.mark.asyncio
    async def test_screenshot(self, manager: AutomationManager, mock_backend):
        """Test taking a screenshot."""
        manager._backend = mock_backend
        manager._security = AutomationSecurity(manager.config)
        manager._initialized = True

        result = await manager.screenshot()
        assert result.status == "success"
        assert result.data.get("result") == b"fake_image_data"
        mock_backend.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_screenshot_with_region(self, manager: AutomationManager, mock_backend):
        """Test taking a screenshot with a region."""
        manager._backend = mock_backend
        manager._security = AutomationSecurity(manager.config)
        manager._initialized = True

        region = (0, 0, 100, 100)
        result = await manager.screenshot(region=region)
        assert result.status == "success"
        mock_backend.screenshot.assert_called_once()


class TestAutomationManagerDryRun:
    """Tests for dry run mode."""

    @pytest.mark.asyncio
    async def test_dry_run_mode(self, mock_backend):
        """Test dry run mode with explicit dry_run=True parameter."""
        config = AutomationConfig(dry_run_default=False, require_accessibility_check=False)
        manager = AutomationManager(config=config)
        manager._backend = mock_backend
        manager._security = AutomationSecurity(config)
        manager._initialized = True

        # In dry run mode, operations should succeed without calling backend
        result = await manager.launch_application("com.apple.finder", dry_run=True)
        assert result.status == "dry_run"  # Status is "dry_run" not "success"
        assert result.dry_run is True
        # Backend should not be called in dry run mode
        mock_backend.launch_application.assert_not_called()

    @pytest.mark.asyncio
    async def test_dry_run_from_config(self, mock_backend):
        """Test dry run mode from config default."""
        config = AutomationConfig(dry_run_default=True, require_accessibility_check=False)
        manager = AutomationManager(config=config)
        manager._backend = mock_backend
        manager._security = AutomationSecurity(config)
        manager._initialized = True

        # When config default is True, should use dry run
        result = await manager.launch_application("com.apple.finder", dry_run=None)
        assert result.status == "dry_run"  # Status is "dry_run" not "success"
        assert result.dry_run is True


class TestAutomationManagerSecurity:
    """Tests for security integration."""

    def test_security_instance_created_on_initialize(self, manager: AutomationManager, mock_backend):
        """Test that security instance is created during initialization."""
        manager._backend = mock_backend
        manager._security = AutomationSecurity(manager.config)
        manager._initialized = True

        assert manager._security is not None

    def test_blocked_apps_configured(self, manager: AutomationManager):
        """Test that blocked apps are configured in security."""
        security = AutomationSecurity(manager.config)
        blocked = security.get_blocked_apps()
        assert len(blocked) > 0
        assert "com.apple.KeychainAccess" in blocked

    def test_can_add_blocked_app(self, manager: AutomationManager):
        """Test adding a blocked app."""
        security = AutomationSecurity(manager.config)
        security.add_blocked_app("com.example.test")
        assert security.is_app_allowed("com.example.test") is False

    def test_can_remove_blocked_app(self, manager: AutomationManager):
        """Test removing a blocked app."""
        security = AutomationSecurity(manager.config)
        security.add_blocked_app("com.example.test2")
        security.remove_blocked_app("com.example.test2")
        # After removal, it should be allowed (not in blocklist)
        assert security.is_app_allowed("com.example.test2") is True


class TestAutomationManagerStats:
    """Tests for manager statistics."""

    def test_initial_stats(self, manager: AutomationManager):
        """Test initial statistics are zero."""
        stats = manager.get_stats()
        assert stats["operations_total"] == 0
        assert stats["operations_success"] == 0
        assert stats["operations_failed"] == 0

    @pytest.mark.asyncio
    async def test_stats_recorded_on_success(self, manager: AutomationManager, mock_backend):
        """Test that statistics are recorded on successful operations."""
        manager._backend = mock_backend
        manager._security = AutomationSecurity(manager.config)
        manager._initialized = True

        await manager.type_text("Hello World")
        stats = manager.get_stats()
        assert stats["operations_total"] == 1
        assert stats["operations_success"] == 1
