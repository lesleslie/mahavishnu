"""Unit tests for automation backends.

Tests cover:
- DesktopAutomationBackend abstract base class
- PyXABackend, ATOMacBackend, PyAutoGUIBackend implementations
- Backend availability checks
- Mock-based operation testing
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.automation.backends.atomac import ATOMacBackend
from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.backends.pyautogui import PyAutoGUIBackend
from mahavishnu.automation.backends.pyxa import PyXABackend
from mahavishnu.automation.errors import (
    AutomationError,
)


class TestDesktopAutomationBackend:
    """Test DesktopAutomationBackend abstract base class."""

    def test_is_abstract(self):
        """DesktopAutomationBackend cannot be instantiated directly."""
        with pytest.raises(TypeError) as exc_info:
            DesktopAutomationBackend()
        # ABC error message
        assert "abstract" in str(exc_info.value).lower()

    def test_has_required_abstract_methods(self):
        """DesktopAutomationBackend defines required abstract methods."""
        abstract_methods = {
            "is_available",
            "backend_name",
            "launch_application",
            "get_application",
            "list_applications",
            "quit_application",
            "activate_application",
            "get_active_application",
            "get_windows",
            "activate_window",
            "resize_window",
            "move_window",
            "close_window",
            "click_menu_item",
            "list_menus",
            "type_text",
            "press_key",
            "click",
            "drag",
            "scroll",
            "screenshot",
            "list_screens",
        }

        for method in abstract_methods:
            assert hasattr(DesktopAutomationBackend, method)

    def test_supports_operation(self):
        """supports_operation returns True for callable methods."""
        with patch("sys.platform", "win32"):
            backend = PyAutoGUIBackend()
            assert backend.supports_operation("click") is True
            assert backend.supports_operation("unknown_method") is False


class TestPyAutoGUIBackend:
    """Test PyAutoGUIBackend implementation."""

    def test_is_available_false_when_not_installed(self):
        """is_available returns False when pyautogui not installed."""
        with patch("builtins.__import__") as mock_import:
            mock_import.side_effect = ImportError()
            assert PyAutoGUIBackend.is_available() is False

    def test_is_available_true_when_installed(self):
        """is_available returns True when pyautogui is installed."""
        with patch("builtins.__import__") as mock_import:
            mock_import.return_value = MagicMock()
            assert PyAutoGUIBackend.is_available() is True

    def test_backend_name(self):
        """backend_name returns 'pyautogui'."""
        backend = PyAutoGUIBackend()
        assert backend.backend_name == "pyautogui"

    @pytest.mark.asyncio
    async def test_launch_application_not_supported(self):
        """launch_application raises AutomationError."""
        backend = PyAutoGUIBackend()

        with pytest.raises(AutomationError) as exc_info:
            await backend.launch_application("com.apple.finder")

        assert "not supported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_type_text(self):
        """type_text uses pyautogui.write."""
        backend = PyAutoGUIBackend()
        mock_pyautogui = MagicMock()
        backend._pyautogui = mock_pyautogui

        result = await backend.type_text("Hello", interval=0.1)

        assert result is True
        mock_pyautogui.write.assert_called_once_with("Hello", interval=0.1)

    @pytest.mark.asyncio
    async def test_press_key(self):
        """press_key uses pyautogui.press."""
        backend = PyAutoGUIBackend()
        mock_pyautogui = MagicMock()
        backend._pyautogui = mock_pyautogui

        result = await backend.press_key("return")

        assert result is True
        mock_pyautogui.press.assert_called_once()

    @pytest.mark.asyncio
    async def test_press_key_with_modifiers(self):
        """press_key uses hotkey when modifiers provided."""
        backend = PyAutoGUIBackend()
        mock_pyautogui = MagicMock()
        backend._pyautogui = mock_pyautogui

        result = await backend.press_key("s", modifiers=["cmd"])

        assert result is True
        mock_pyautogui.hotkey.assert_called_once()

    @pytest.mark.asyncio
    async def test_click(self):
        """click uses pyautogui.click."""
        backend = PyAutoGUIBackend()
        mock_pyautogui = MagicMock()
        backend._pyautogui = mock_pyautogui

        result = await backend.click(100, 200, button="right", clicks=2)

        assert result is True
        mock_pyautogui.click.assert_called_once_with(100, 200, clicks=2, button="right")

    @pytest.mark.asyncio
    async def test_drag(self):
        """drag uses pyautogui.moveTo and drag."""
        backend = PyAutoGUIBackend()
        mock_pyautogui = MagicMock()
        backend._pyautogui = mock_pyautogui

        result = await backend.drag(0, 0, 100, 100, duration=0.5)

        assert result is True
        mock_pyautogui.moveTo.assert_called_once_with(0, 0)
        mock_pyautogui.drag.assert_called_once()

    @pytest.mark.asyncio
    async def test_scroll(self):
        """scroll uses pyautogui.moveTo and scroll."""
        backend = PyAutoGUIBackend()
        mock_pyautogui = MagicMock()
        backend._pyautogui = mock_pyautogui

        result = await backend.scroll(100, 100, dx=0, dy=-3)

        assert result is True
        mock_pyautogui.moveTo.assert_called_once_with(100, 100)
        mock_pyautogui.scroll.assert_called_once()

    @pytest.mark.asyncio
    async def test_screenshot_uses_mss(self):
        """screenshot captures screen using mss."""
        backend = PyAutoGUIBackend()

        with patch.object(backend, "_get_pyautogui", MagicMock()):
            # Mock mss at module level since it's imported locally inside _capture()
            mock_mss_module = MagicMock()
            mock_sct = MagicMock()
            mock_sct.monitors = [None, {"left": 0, "top": 0, "width": 1920, "height": 1080}]
            mock_sct.grab.return_value = MagicMock(size=(1920, 1080), bgra=b"raw")
            mock_mss_module.mss.return_value.__enter__.return_value = mock_sct

            # Mock PIL.Image at the module where it's imported
            mock_pil_image = MagicMock()

            with patch.dict("sys.modules", {"mss": mock_mss_module}):
                with patch.dict("sys.modules", {"PIL": MagicMock(), "PIL.Image": mock_pil_image}):
                    mock_buffer = MagicMock()
                    mock_buffer.getvalue.return_value = b"png_data"
                    mock_pil_image.Image.frombytes.return_value.save = MagicMock()

                    with patch(
                        "mahavishnu.automation.backends.pyautogui.BytesIO",
                        return_value=mock_buffer,
                    ):
                        result = await backend.screenshot()

                        assert result == b"png_data"

    @pytest.mark.asyncio
    async def test_list_applications_not_supported(self):
        """list_applications returns empty list."""
        backend = PyAutoGUIBackend()
        result = await backend.list_applications()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_windows_not_supported(self):
        """get_windows returns empty list."""
        backend = PyAutoGUIBackend()
        result = await backend.get_windows("com.apple.finder")
        assert result == []

    @pytest.mark.asyncio
    async def test_activate_window_not_supported(self):
        """activate_window raises AutomationError."""
        backend = PyAutoGUIBackend()

        with pytest.raises(AutomationError) as exc_info:
            await backend.activate_window("win-123")

        assert "not supported" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_close(self):
        """close shuts down executor."""
        backend = PyAutoGUIBackend()
        mock_executor = MagicMock()
        backend._executor = mock_executor
        backend._pyautogui = MagicMock()

        await backend.close()

        mock_executor.shutdown.assert_called_once_with(wait=False)
        assert backend._executor is None


class TestPyXABackend:
    """Test PyXABackend implementation."""

    def test_is_available_darwin_required(self):
        """is_available returns False on non-macOS."""
        with patch.object(sys, "platform", "win32"):
            assert PyXABackend.is_available() is False

    def test_is_available_import_error(self):
        """is_available returns False when PyXA import fails."""
        with patch.object(sys, "platform", "darwin"):
            with patch("builtins.__import__") as mock_import:
                mock_import.side_effect = ImportError()
                assert PyXABackend.is_available() is False

    def test_backend_name(self):
        """backend_name returns 'pyxa'."""
        backend = PyXABackend()
        assert backend.backend_name == "pyxa"

    @pytest.mark.asyncio
    async def test_launch_application(self):
        """launch_application launches app via PyXA."""
        backend = PyXABackend()

        mock_pyxa = MagicMock()
        mock_app = MagicMock()
        mock_pyxa.Application.return_value = mock_app
        backend._pyxa = mock_pyxa

        result = await backend.launch_application("com.apple.finder")

        mock_app.launch.assert_called_once()
        mock_pyxa.Application.assert_called_once_with("com.apple.finder")

    @pytest.mark.asyncio
    async def test_get_application_running(self):
        """get_application returns app info when running."""
        backend = PyXABackend()

        mock_pyxa = MagicMock()
        mock_app = MagicMock()
        mock_app.is_running.return_value = True
        mock_app.bundle_identifier.return_value = "com.apple.finder"
        mock_app.name.return_value = "Finder"
        mock_app.process_identifier.return_value = 12345
        mock_app.windows.return_value = []
        mock_pyxa.Application.return_value = mock_app
        backend._pyxa = mock_pyxa

        result = await backend.get_application("com.apple.finder")

        assert result is not None
        assert result.bundle_id == "com.apple.finder"

    @pytest.mark.asyncio
    async def test_get_application_not_running(self):
        """get_application returns None when not running."""
        backend = PyXABackend()

        mock_pyxa = MagicMock()
        mock_app = MagicMock()
        mock_app.is_running.return_value = False
        mock_pyxa.Application.return_value = mock_app
        backend._pyxa = mock_pyxa

        result = await backend.get_application("com.apple.finder")

        assert result is None

    @pytest.mark.asyncio
    async def test_type_text(self):
        """type_text types text via PyXA system events."""
        backend = PyXABackend()

        mock_pyxa = MagicMock()
        mock_system = MagicMock()
        mock_pyxa.system_events.return_value = mock_system
        backend._pyxa = mock_pyxa

        result = await backend.type_text("ABC", interval=0.0)

        assert result is True

    @pytest.mark.asyncio
    async def test_click(self):
        """click performs click at coordinates using pyautogui."""
        backend = PyXABackend()

        mock_pyxa = MagicMock()
        backend._pyxa = mock_pyxa

        # Mock pyautogui module that gets imported inside _click
        mock_pyautogui = MagicMock()
        with patch.dict("sys.modules", {"pyautogui": mock_pyautogui}):
            result = await backend.click(100, 200)

        assert result is True
        mock_pyautogui.click.assert_called_once_with(100, 200, clicks=1, button="left")

    @pytest.mark.asyncio
    async def test_list_screens(self):
        """list_screens returns screen info."""
        backend = PyXABackend()

        mock_pyxa = MagicMock()
        mock_screen = MagicMock()
        mock_screen.x = 0
        mock_screen.y = 0
        mock_screen.width = 1920
        mock_screen.height = 1080
        mock_screen.scale = 2.0
        mock_pyxa.screens.return_value = [mock_screen]
        backend._pyxa = mock_pyxa

        result = await backend.list_screens()

        assert len(result) == 1
        assert result[0].size == (1920, 1080)

    @pytest.mark.asyncio
    async def test_close(self):
        """close shuts down executor."""
        backend = PyXABackend()
        mock_executor = MagicMock()
        backend._executor = mock_executor
        backend._pyxa = MagicMock()

        await backend.close()

        mock_executor.shutdown.assert_called_once_with(wait=False)


class TestATOMacBackend:
    """Test ATOMacBackend implementation."""

    def test_is_available_darwin_required(self):
        """is_available returns False on non-macOS."""
        with patch.object(sys, "platform", "win32"):
            assert ATOMacBackend.is_available() is False

    def test_is_available_import_error(self):
        """is_available returns False when atomac import fails."""
        with patch.object(sys, "platform", "darwin"):
            with patch("builtins.__import__") as mock_import:
                mock_import.side_effect = ImportError()
                assert ATOMacBackend.is_available() is False

    def test_backend_name(self):
        """backend_name returns 'atomac'."""
        backend = ATOMacBackend()
        assert backend.backend_name == "atomac"

    @pytest.mark.asyncio
    async def test_launch_application(self):
        """launch_application launches app via atomac."""
        backend = ATOMacBackend()

        mock_atomac = MagicMock()
        mock_app = MagicMock()
        mock_atomac.launchAppByBundleId.return_value = mock_app
        backend._atomac = mock_atomac

        result = await backend.launch_application("com.apple.finder")

        mock_atomac.launchAppByBundleId.assert_called_once_with("com.apple.finder")

    @pytest.mark.asyncio
    async def test_get_application(self):
        """get_application returns app info."""
        backend = ATOMacBackend()

        mock_atomac = MagicMock()
        mock_app = MagicMock()
        mock_app.localizedName.return_value = "Finder"
        mock_app.processIdentifier.return_value = 12345
        mock_atomac.getAppWithBundleId.return_value = mock_app
        backend._atomac = mock_atomac

        result = await backend.get_application("com.apple.finder")

        assert result is not None
        assert result.bundle_id == "com.apple.finder"

    @pytest.mark.asyncio
    async def test_get_application_not_found(self):
        """get_application returns None when not found."""
        backend = ATOMacBackend()

        mock_atomac = MagicMock()
        mock_atomac.getAppWithBundleId.return_value = None
        backend._atomac = mock_atomac

        result = await backend.get_application("com.apple.nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_click(self):
        """click clicks at coordinates."""
        backend = ATOMacBackend()

        mock_atomac = MagicMock()
        mock_atomac.mouse.click = MagicMock()
        backend._atomac = mock_atomac

        result = await backend.click(100, 200)

        assert result is True
        mock_atomac.mouse.click.assert_called_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_activate_window_not_implemented(self):
        """activate_window logs warning and returns False."""
        backend = ATOMacBackend()
        backend._atomac = MagicMock()

        result = await backend.activate_window("win-123")

        assert result is False

    @pytest.mark.asyncio
    async def test_resize_window_not_implemented(self):
        """resize_window logs warning and returns False."""
        backend = ATOMacBackend()
        backend._atomac = MagicMock()

        result = await backend.resize_window("win-123", 800, 600)

        assert result is False

    @pytest.mark.asyncio
    async def test_close(self):
        """close shuts down executor."""
        backend = ATOMacBackend()
        mock_executor = MagicMock()
        backend._executor = mock_executor
        backend._atomac = MagicMock()

        await backend.close()

        mock_executor.shutdown.assert_called_once_with(wait=False)


class TestBackendComparison:
    """Test differences between backends."""

    @pytest.mark.asyncio
    async def test_pyautogui_lacks_app_management(self):
        """PyAutoGUI does not support app management."""
        backend = PyAutoGUIBackend()

        with pytest.raises(AutomationError):
            await backend.launch_application("com.apple.finder")

        with pytest.raises(AutomationError):
            await backend.quit_application("com.apple.finder")

        with pytest.raises(AutomationError):
            await backend.activate_application("com.apple.finder")

    @pytest.mark.asyncio
    async def test_pyautogui_lacks_window_management(self):
        """PyAutoGUI does not support window management."""
        backend = PyAutoGUIBackend()

        with pytest.raises(AutomationError):
            await backend.activate_window("win-123")

        with pytest.raises(AutomationError):
            await backend.resize_window("win-123", 800, 600)

        with pytest.raises(AutomationError):
            await backend.move_window("win-123", 100, 100)

        with pytest.raises(AutomationError):
            await backend.close_window("win-123")

    @pytest.mark.asyncio
    async def test_pyautogui_lacks_menu_support(self):
        """PyAutoGUI does not support menu interaction."""
        backend = PyAutoGUIBackend()

        with pytest.raises(AutomationError):
            await backend.click_menu_item("com.apple.finder", ["File", "Save"])

        result = await backend.list_menus("com.apple.finder")
        assert result == []


class TestBackendNotImplemented:
    """Test backend NotImplementedError handling."""

    @pytest.mark.asyncio
    async def test_get_ui_elements_not_implemented(self):
        """get_ui_elements raises NotImplementedError."""
        backend = PyAutoGUIBackend()

        with pytest.raises(NotImplementedError):
            await backend.get_ui_elements("com.apple.finder")

    @pytest.mark.asyncio
    async def test_click_ui_element_not_implemented(self):
        """click_ui_element raises NotImplementedError."""
        backend = PyAutoGUIBackend()

        with pytest.raises(NotImplementedError):
            await backend.click_ui_element("com.apple.finder", "element-id")

    @pytest.mark.asyncio
    async def test_get_clipboard_not_implemented(self):
        """get_clipboard raises NotImplementedError."""
        backend = PyAutoGUIBackend()

        with pytest.raises(NotImplementedError):
            await backend.get_clipboard()

    @pytest.mark.asyncio
    async def test_set_clipboard_not_implemented(self):
        """set_clipboard raises NotImplementedError."""
        backend = PyAutoGUIBackend()

        with pytest.raises(NotImplementedError):
            await backend.set_clipboard("text")
