"""Unit tests for automation backends.

Tests cover:
- DesktopAutomationBackend abstract base class
- NativeMacOSBackend, PyAutoGUIBackend implementations
- Backend availability checks
- Mock-based operation testing
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.backends.native_macos import NativeMacOSBackend
from mahavishnu.automation.backends.pyautogui import PyAutoGUIBackend
from mahavishnu.automation.errors import (
    AutomationError,
)


class TestDesktopAutomationBackend:
    """Test DesktopAutomationBackend abstract base class."""

    def test_is_abstract(self):
        """DesktopAutomationBackend cannot be instantiated directly."""
        with pytest.raises(TypeError):
            DesktopAutomationBackend()

    def test_backend_name_property(self):
        """Backends must implement backend_name property."""
        backend = NativeMacOSBackend()
        assert backend.backend_name == "native_macos"

    def test_supports_operation(self):
        """supports_operation returns True for implemented methods."""
        backend = NativeMacOSBackend()
        assert backend.supports_operation("launch_application") is True
        assert backend.supports_operation("click") is True
        assert backend.supports_operation("nonexistent") is False

    def test_supports_operation_abstract(self):
        """Abstract methods return True for operation check."""
        backend = NativeMacOSBackend()
        assert backend.supports_operation("resize_window") is True  # Returns False but is implemented


class TestNativeMacOSBackend:
    """Test NativeMacOSBackend implementation."""

    def test_is_available_on_non_macos(self):
        """is_available returns False on non-macOS."""
        with patch.object(sys, "platform", "linux"):
            assert NativeMacOSBackend.is_available() is False

    def test_is_available_without_cliclick(self):
        """is_available returns False when cliclick not installed."""
        with patch.object(sys, "platform", "darwin"):
            with patch("shutil.which", return_value=None):
                assert NativeMacOSBackend.is_available() is False

    def test_backend_name(self):
        """backend_name returns 'native_macos'."""
        backend = NativeMacOSBackend()
        assert backend.backend_name == "native_macos"

    @pytest.mark.asyncio
    async def test_launch_application_fake(self, monkeypatch):
        """launch_application returns fake app info for testing."""
        from mahavishnu.automation.base import ApplicationInfo

        async def fake_osascript_runner(func, script):
            return "name:FakeApp|pid:12345"

        backend = NativeMacOSBackend()
        monkeypatch.setattr("mahavishnu.automation.backends.native_macos._async_run_sync", fake_osascript_runner)
        result = await backend.launch_application("com.apple.fake")
        assert isinstance(result, ApplicationInfo)
        assert result.name == "FakeApp"
        assert result.pid == 12345

    @pytest.mark.asyncio
    async def test_resize_window_returns_false(self):
        """resize_window returns False (not supported via osascript)."""
        backend = NativeMacOSBackend()
        result = await backend.resize_window("1", 800, 600)
        assert result is False

    @pytest.mark.asyncio
    async def test_move_window_returns_false(self):
        """move_window returns False (not supported via osascript)."""
        backend = NativeMacOSBackend()
        result = await backend.move_window("1", 100, 100)
        assert result is False

    @pytest.mark.asyncio
    async def test_list_menus_returns_empty(self):
        """list_menus returns empty (AppleScript limitation)."""
        backend = NativeMacOSBackend()
        result = await backend.list_menus("com.apple.finder")
        assert result == []


class TestPyAutoGUIBackend:
    """Test PyAutoGUIBackend implementation."""

    def test_backend_name(self):
        """backend_name returns 'pyautogui'."""
        backend = PyAutoGUIBackend()
        assert backend.backend_name == "pyautogui"
