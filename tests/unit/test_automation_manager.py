"""Unit tests for automation manager.

Tests cover:
- AutomationManager initialization and lifecycle
- Security validation integration
- Operation execution and statistics
- Backend selection and routing
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.automation.errors import (
    BlockedAppError,
    BlockedTextError,
    NoBackendAvailableError,
    PermissionDeniedError,
)
from mahavishnu.automation.manager import AutomationManager, ManagerStats


class TestManagerStats:
    """Test ManagerStats dataclass."""

    def test_creation_defaults(self):
        """ManagerStats can be created with defaults."""
        stats = ManagerStats()
        assert stats.operations_total == 0
        assert stats.operations_success == 0
        assert stats.operations_failed == 0
        assert stats.operations_dry_run == 0
        assert stats.last_operation is None
        assert stats.backend_name is None

    def test_to_dict(self):
        """to_dict returns correct structure."""
        stats = ManagerStats(
            operations_total=10,
            operations_success=8,
            operations_failed=1,
            operations_dry_run=1,
            backend_name="native_macos",
        )
        d = stats.to_dict()
        assert d["operations_total"] == 10
        assert d["operations_success"] == 8
        assert d["operations_failed"] == 1
        assert d["operations_dry_run"] == 1
        assert d["backend_name"] == "native_macos"
        assert d["last_operation"] is None


class TestAutomationManager:
    """Test AutomationManager class."""

    def test_creation_defaults(self):
        """AutomationManager can be created with defaults."""
        manager = AutomationManager()
        assert manager.config is not None
        assert manager.preferred_backend == "auto"
        assert manager._backend is None
        assert manager._initialized is False

    def test_creation_with_config(self):
        """AutomationManager accepts custom config."""
        from mahavishnu.automation.models import AutomationConfig

        config = AutomationConfig(dry_run_default=True)
        manager = AutomationManager(config=config)
        assert manager.config.dry_run_default is True

    def test_creation_with_preferred_backend(self):
        """AutomationManager accepts preferred backend."""
        manager = AutomationManager(preferred_backend="pyautogui")
        assert manager.preferred_backend == "pyautogui"

    @pytest.mark.asyncio
    async def test_initialize_no_backend(self):
        """initialize raises when no backend available."""
        manager = AutomationManager()

        with (
            patch("mahavishnu.automation.manager.NativeMacOSBackend") as mock_native,
            patch("mahavishnu.automation.manager.PyAutoGUIBackend") as mock_pyautogui,
        ):
            mock_native.is_available.return_value = False
            mock_pyautogui.is_available.return_value = False

            with pytest.raises(NoBackendAvailableError):
                await manager.initialize()

    @pytest.mark.asyncio
    async def test_initialize_permission_denied(self):
        """initialize raises when permissions not granted."""
        manager = AutomationManager()

        with (
            patch("mahavishnu.automation.manager.PermissionChecker") as mock_perm_cls,
            patch("mahavishnu.automation.manager.NativeMacOSBackend") as mock_native,
        ):
            mock_perm = MagicMock()
            mock_perm.check_accessibility.return_value = False
            mock_perm.request_accessibility.return_value = False
            mock_perm_cls.return_value = mock_perm
            mock_native.is_available.return_value = True
            mock_native_instance = MagicMock()
            mock_native_instance.backend_name = "native_macos"
            mock_native.return_value = mock_native_instance

            with pytest.raises(PermissionDeniedError):
                await manager.initialize()

    @pytest.mark.asyncio
    async def test_initialize_already_initialized(self):
        """initialize returns early if already initialized."""
        manager = AutomationManager()
        manager._initialized = True

        result = await manager.initialize()
        assert result is None
        assert manager._initialized is True

    def test_select_backend_auto(self):
        """_select_backend tries backends in order."""
        manager = AutomationManager()
        manager.preferred_backend = "auto"

        with (
            patch("mahavishnu.automation.manager.NativeMacOSBackend") as mock_native,
            patch("mahavishnu.automation.manager.PyAutoGUIBackend") as mock_pyautogui,
        ):
            mock_native.is_available.return_value = False
            mock_pyautogui.is_available.return_value = False
            manager._select_backend()

            # Both backends unavailable
            assert manager._backend is None

    def test_select_backend_specific(self):
        """_select_backend uses specific backend when requested."""
        manager = AutomationManager()
        manager.preferred_backend = "pyautogui"

        with patch("mahavishnu.automation.manager.PyAutoGUIBackend") as mock_pyautogui:
            mock_pyautogui.is_available.return_value = True
            mock_pyautogui_instance = MagicMock()
            mock_pyautogui_instance.backend_name = "pyautogui"
            mock_pyautogui.return_value = mock_pyautogui_instance

            manager._select_backend()

            assert manager._backend is not None
            mock_pyautogui.assert_called_once()

    def test_select_backend_unknown(self):
        """_select_backend falls back to auto for unknown backend."""
        manager = AutomationManager()
        manager.preferred_backend = "unknown_backend"

        with patch("mahavishnu.automation.manager.NativeMacOSBackend") as mock_native:
            mock_native.is_available.return_value = False

            manager._select_backend()
            # Should not raise, just log warning

    def test_record_operation_success(self):
        """_record_operation increments success counter."""
        manager = AutomationManager()
        manager._record_operation(success=True)

        assert manager._stats.operations_total == 1
        assert manager._stats.operations_success == 1
        assert manager._stats.operations_failed == 0
        assert manager._stats.last_operation is not None

    def test_record_operation_failure(self):
        """_record_operation increments failure counter."""
        manager = AutomationManager()
        manager._record_operation(success=False)

        assert manager._stats.operations_total == 1
        assert manager._stats.operations_success == 0
        assert manager._stats.operations_failed == 1

    def test_record_operation_dry_run(self):
        """_record_operation increments dry_run counter."""
        manager = AutomationManager()
        manager._record_operation(success=True, dry_run=True)

        assert manager._stats.operations_total == 1
        assert manager._stats.operations_dry_run == 1
        assert manager._stats.operations_success == 0

    @pytest.mark.asyncio
    async def test_execute_no_backend(self):
        """_execute returns failure when no backend."""
        manager = AutomationManager()
        manager._initialized = True
        manager._backend = None

        from mahavishnu.automation.models import OperationType

        result = await manager._execute(
            OperationType.LAUNCH_APP,
            lambda: None,
        )

        assert result.status == "failed"
        assert "No backend available" in result.error

    @pytest.mark.asyncio
    async def test_execute_dry_run(self):
        """_execute returns dry_run result when dry_run=True."""
        from mahavishnu.automation.models import OperationType

        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        manager._backend = mock_backend

        result = await manager._execute(
            OperationType.LAUNCH_APP,
            lambda: {},
            dry_run=True,
        )

        assert result.status == "dry_run"
        assert result.dry_run is True

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """_execute returns success when operation succeeds."""
        from mahavishnu.automation.models import OperationType

        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        manager._backend = mock_backend

        async def mock_operation():
            return {"bundle_id": "com.apple.finder"}

        result = await manager._execute(
            OperationType.LAUNCH_APP,
            mock_operation,
        )

        assert result.status == "success"
        assert result.data == {"bundle_id": "com.apple.finder"}

    @pytest.mark.asyncio
    async def test_execute_failure(self):
        """_execute returns failure when operation raises."""
        from mahavishnu.automation.models import OperationType

        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        manager._backend = mock_backend

        async def mock_operation():
            raise ValueError("Test error")

        result = await manager._execute(
            OperationType.LAUNCH_APP,
            mock_operation,
        )

        assert result.status == "failed"
        assert "Test error" in result.error


class TestAutomationManagerSecurity:
    """Test AutomationManager security integration."""

    @pytest.mark.asyncio
    async def test_launch_app_blocked(self):
        """launch_app raises BlockedAppError for blocked app."""
        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        manager._backend = mock_backend
        manager._security = MagicMock()
        manager._security.validate_app.side_effect = BlockedAppError("com.apple.loginwindow")

        with pytest.raises(BlockedAppError):
            await manager.launch_application("com.apple.loginwindow")

        manager._security.validate_app.assert_called_once_with("com.apple.loginwindow")

    @pytest.mark.asyncio
    async def test_type_text_blocked(self):
        """type_text raises BlockedTextError for blocked text."""
        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        manager._backend = mock_backend
        manager._security = MagicMock()
        manager._security.validate_text.side_effect = BlockedTextError("password")

        with pytest.raises(BlockedTextError):
            await manager.type_text("my_password_is_secret")


class TestAutomationManagerOperations:
    """Test AutomationManager operation methods."""

    @pytest.mark.asyncio
    async def test_launch_application(self):
        """launch_application calls backend correctly."""
        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        mock_backend.launch_application = AsyncMock(return_value=MagicMock())
        manager._backend = mock_backend
        manager._security = MagicMock()

        await manager.launch_application("com.apple.finder")

        mock_backend.launch_application.assert_called_once_with("com.apple.finder")

    @pytest.mark.asyncio
    async def test_quit_application(self):
        """quit_application calls backend correctly."""
        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        mock_backend.quit_application = AsyncMock(return_value=True)
        manager._backend = mock_backend
        manager._security = MagicMock()

        await manager.quit_application("com.apple.finder", force=True)

        mock_backend.quit_application.assert_called_once_with("com.apple.finder", force=True)

    @pytest.mark.asyncio
    async def test_type_text(self):
        """type_text calls backend correctly."""
        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        mock_backend.type_text = AsyncMock(return_value=True)
        manager._backend = mock_backend
        manager._security = MagicMock()

        await manager.type_text("Hello", interval=0.1)

        mock_backend.type_text.assert_called_once_with("Hello", interval=0.1)

    @pytest.mark.asyncio
    async def test_click(self):
        """click calls backend correctly."""
        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        mock_backend.click = AsyncMock(return_value=True)
        manager._backend = mock_backend

        await manager.click(100, 200, button="right", clicks=2)

        mock_backend.click.assert_called_once_with(100, 200, button="right", clicks=2)

    @pytest.mark.asyncio
    async def test_screenshot(self):
        """screenshot calls backend correctly."""
        manager = AutomationManager()
        manager._initialized = True

        mock_backend = MagicMock()
        mock_backend.backend_name = "test"
        mock_backend.screenshot = AsyncMock(return_value=b"png_data")
        manager._backend = mock_backend

        result = await manager.screenshot(region=(0, 0, 800, 600))

        mock_backend.screenshot.assert_called_once_with(region=(0, 0, 800, 600))
        assert result.data == {"result": b"png_data"}


class TestAutomationManagerUtilities:
    """Test AutomationManager utility methods."""

    def test_get_stats(self):
        """get_stats returns manager statistics."""
        manager = AutomationManager()
        manager._stats.operations_total = 5
        manager._stats.backend_name = "native_macos"

        stats = manager.get_stats()
        assert stats["operations_total"] == 5
        assert stats["backend_name"] == "native_macos"

    def test_get_backend_name(self):
        """get_backend_name returns backend name."""
        manager = AutomationManager()
        mock_backend = MagicMock()
        mock_backend.backend_name = "native_macos"
        manager._backend = mock_backend

        assert manager.get_backend_name() == "native_macos"

    def test_get_backend_name_no_backend(self):
        """get_backend_name returns None when no backend."""
        manager = AutomationManager()
        assert manager.get_backend_name() is None

    def test_get_capabilities(self):
        """get_capabilities returns backend capabilities."""
        manager = AutomationManager()
        manager._capability_detector = MagicMock()

        mock_status = MagicMock()
        mock_caps = MagicMock()
        mock_caps.capabilities = {"LAUNCH_APP", "CLICK"}
        mock_status.capabilities = mock_caps

        manager._backend = MagicMock()
        manager._backend.backend_name = "native_macos"
        manager._capability_detector.get_backend_status.return_value = mock_status

        caps = manager.get_capabilities()
        assert caps == {"LAUNCH_APP", "CLICK"}

    def test_get_capabilities_no_detector(self):
        """get_capabilities returns empty set when no detector."""
        manager = AutomationManager()
        manager._capability_detector = None

        caps = manager.get_capabilities()
        assert caps == set()


class TestAutomationManagerContextManager:
    """Test AutomationManager async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """__aenter__ initializes, __aexit__ cleans up."""
        manager = AutomationManager()

        with patch("mahavishnu.automation.manager.NativeMacOSBackend") as mock_native:
            mock_native.is_available.return_value = True
            mock_native_instance = MagicMock()
            mock_native_instance.backend_name = "native_macos"
            mock_native_instance.close = AsyncMock()
            mock_native.return_value = mock_native_instance

            async with manager as mgr:
                assert mgr._initialized is True

            assert manager._initialized is False
            assert manager._backend is None

    @pytest.mark.asyncio
    async def test_close(self):
        """close cleans up backend."""
        manager = AutomationManager()

        mock_backend = MagicMock()
        mock_backend.close = AsyncMock()
        manager._backend = mock_backend
        manager._initialized = True

        await manager.close()

        mock_backend.close.assert_called_once()
        assert manager._backend is None
        assert manager._initialized is False
