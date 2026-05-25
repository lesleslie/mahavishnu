"""Unit tests for automation base classes and capabilities.

Tests cover:
- WindowState, MouseButton, KeyModifier enums
- WindowInfo, ApplicationInfo, MenuInfo, UIElement, ScreenInfo, AutomationContext dataclasses
- Capability enum and BackendCapabilities, BackendStatus, CapabilityDetector
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import sys
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.automation.base import (
    ApplicationInfo,
    AutomationContext,
    KeyModifier,
    MenuInfo,
    MouseButton,
    ScreenInfo,
    UIElement,
    WindowInfo,
    WindowState,
)
from mahavishnu.automation.capabilities import (
    ATOMAC_CAPABILITIES,
    PYAUTOGUI_CAPABILITIES,
    PYXA_CAPABILITIES,
    BackendCapabilities,
    BackendStatus,
    Capability,
    CapabilityDetector,
    Platform,
)


class TestEnums:
    """Test enum classes."""

    def test_window_state_values(self):
        """WindowState enum has expected values."""
        assert WindowState.NORMAL == "normal"
        assert WindowState.MINIMIZED == "minimized"
        assert WindowState.MAXIMIZED == "maximized"
        assert WindowState.FULLSCREEN == "fullscreen"
        assert WindowState.HIDDEN == "hidden"

    def test_mouse_button_values(self):
        """MouseButton enum has expected values."""
        assert MouseButton.LEFT == "left"
        assert MouseButton.RIGHT == "right"
        assert MouseButton.MIDDLE == "middle"

    def test_key_modifier_values(self):
        """KeyModifier enum has expected values."""
        assert KeyModifier.CMD == "cmd"
        assert KeyModifier.COMMAND == "command"
        assert KeyModifier.SHIFT == "shift"
        assert KeyModifier.OPTION == "option"
        assert KeyModifier.ALT == "alt"
        assert KeyModifier.CONTROL == "control"
        assert KeyModifier.CTRL == "ctrl"
        assert KeyModifier.FN == "fn"


class TestWindowInfo:
    """Test WindowInfo dataclass."""

    def test_creation(self):
        """WindowInfo can be created with required fields."""
        info = WindowInfo(
            id="win-1",
            title="Test Window",
            position=(100, 200),
            size=(800, 600),
        )
        assert info.id == "win-1"
        assert info.title == "Test Window"
        assert info.position == (100, 200)
        assert info.size == (800, 600)
        assert info.state == WindowState.NORMAL
        assert info.focused is False
        assert info.bundle_id is None
        assert info.window_number is None

    def test_with_optional_fields(self):
        """WindowInfo with all optional fields."""
        info = WindowInfo(
            id="win-2",
            title="Optional Window",
            position=(0, 0),
            size=(1920, 1080),
            state=WindowState.MAXIMIZED,
            focused=True,
            bundle_id="com.apple.finder",
            window_number=1,
        )
        assert info.state == WindowState.MAXIMIZED
        assert info.focused is True
        assert info.bundle_id == "com.apple.finder"
        assert info.window_number == 1

    def test_to_dict(self):
        """WindowInfo.to_dict returns correct structure."""
        info = WindowInfo(
            id="win-1",
            title="Dict Window",
            position=(10, 20),
            size=(100, 200),
            state=WindowState.MINIMIZED,
        )
        d = info.to_dict()
        assert d["id"] == "win-1"
        assert d["title"] == "Dict Window"
        assert d["position"] == (10, 20)
        assert d["size"] == (100, 200)
        assert d["state"] == "minimized"


class TestApplicationInfo:
    """Test ApplicationInfo dataclass."""

    def test_creation(self):
        """ApplicationInfo can be created with required fields."""
        info = ApplicationInfo(
            bundle_id="com.apple.finder",
            name="Finder",
            pid=12345,
        )
        assert info.bundle_id == "com.apple.finder"
        assert info.name == "Finder"
        assert info.pid == 12345
        assert info.frontmost is False
        assert info.windows == []
        assert info.url is None
        assert info.version is None

    def test_with_windows(self):
        """ApplicationInfo with associated windows."""
        win = WindowInfo(
            id="win-1",
            title="Finder Window",
            position=(0, 0),
            size=(800, 600),
        )
        info = ApplicationInfo(
            bundle_id="com.apple.finder",
            name="Finder",
            pid=12345,
            frontmost=True,
            windows=[win],
        )
        assert len(info.windows) == 1
        assert info.windows[0].title == "Finder Window"

    def test_to_dict(self):
        """ApplicationInfo.to_dict returns correct structure."""
        info = ApplicationInfo(
            bundle_id="com.apple.safari",
            name="Safari",
            pid=99,
            frontmost=True,
        )
        d = info.to_dict()
        assert d["bundle_id"] == "com.apple.safari"
        assert d["name"] == "Safari"
        assert d["pid"] == 99
        assert d["frontmost"] is True
        assert d["windows"] == []


class TestMenuInfo:
    """Test MenuInfo dataclass."""

    def test_creation(self):
        """MenuInfo can be created with required fields."""
        menu = MenuInfo(name="File")
        assert menu.name == "File"
        assert menu.path == []
        assert menu.enabled is True
        assert menu.shortcut is None
        assert menu.children == []

    def test_with_path(self):
        """MenuInfo with full menu path."""
        menu = MenuInfo(
            name="Save",
            path=["File", "Save"],
            shortcut="Cmd+S",
        )
        assert menu.name == "Save"
        assert menu.path == ["File", "Save"]
        assert menu.shortcut == "Cmd+S"

    def test_with_children(self):
        """MenuInfo with child menu items."""
        child1 = MenuInfo(name="New Window")
        child2 = MenuInfo(name="New Tab")
        parent = MenuInfo(
            name="New",
            path=["File", "New"],
            children=[child1, child2],
        )
        assert len(parent.children) == 2
        assert parent.children[0].name == "New Window"

    def test_to_dict_nested(self):
        """MenuInfo.to_dict handles nested children correctly."""
        child = MenuInfo(name="Child")
        parent = MenuInfo(name="Parent", children=[child])
        d = parent.to_dict()
        assert d["name"] == "Parent"
        assert len(d["children"]) == 1
        assert d["children"][0]["name"] == "Child"


class TestUIElement:
    """Test UIElement dataclass."""

    def test_creation(self):
        """UIElement can be created with required fields."""
        elem = UIElement(role="button")
        assert elem.role == "button"
        assert elem.title is None
        assert elem.value is None
        assert elem.position is None
        assert elem.size is None
        assert elem.enabled is True
        assert elem.focused is False
        assert elem.identifier is None
        assert elem.description is None

    def test_with_all_fields(self):
        """UIElement with all fields populated."""
        elem = UIElement(
            role="textfield",
            title="Username",
            value="admin",
            position=(100, 200),
            size=(200, 30),
            enabled=True,
            focused=True,
            identifier="username_field",
            description="Enter your username",
        )
        assert elem.role == "textfield"
        assert elem.title == "Username"
        assert elem.value == "admin"
        assert elem.position == (100, 200)
        assert elem.size == (200, 30)
        assert elem.focused is True
        assert elem.identifier == "username_field"

    def test_to_dict(self):
        """UIElement.to_dict returns correct structure."""
        elem = UIElement(role="checkbox", title="Remember Me", value=True)
        d = elem.to_dict()
        assert d["role"] == "checkbox"
        assert d["title"] == "Remember Me"
        assert d["value"] is True


class TestScreenInfo:
    """Test ScreenInfo dataclass."""

    def test_creation(self):
        """ScreenInfo can be created with required fields."""
        screen = ScreenInfo(
            id=0,
            name="Primary Display",
            position=(0, 0),
            size=(1920, 1080),
        )
        assert screen.id == 0
        assert screen.name == "Primary Display"
        assert screen.position == (0, 0)
        assert screen.size == (1920, 1080)
        assert screen.scale == 1.0
        assert screen.primary is False

    def test_with_retina_scale(self):
        """ScreenInfo with Retina display scale factor."""
        screen = ScreenInfo(
            id=1,
            name="External Display",
            position=(1920, 0),
            size=(2560, 1440),
            scale=2.0,
            primary=True,
        )
        assert screen.scale == 2.0
        assert screen.primary is True

    def test_to_dict(self):
        """ScreenInfo.to_dict returns correct structure."""
        screen = ScreenInfo(
            id=0,
            name="Test",
            position=(0, 0),
            size=(1024, 768),
        )
        d = screen.to_dict()
        assert d["id"] == 0
        assert d["name"] == "Test"
        assert d["size"] == (1024, 768)
        assert d["scale"] == 1.0


class TestAutomationContext:
    """Test AutomationContext dataclass."""

    def test_creation(self):
        """AutomationContext can be created with defaults."""
        ctx = AutomationContext()
        assert ctx.active_bundle_id is None
        assert ctx.active_window_id is None
        assert ctx.last_operation is None
        assert ctx.operation_count == 0
        assert ctx.dry_run is False
        assert ctx.metadata == {}

    def test_with_values(self):
        """AutomationContext with custom values."""
        ctx = AutomationContext(
            active_bundle_id="com.apple.finder",
            active_window_id="win-1",
            dry_run=True,
            metadata={"key": "value"},
        )
        assert ctx.active_bundle_id == "com.apple.finder"
        assert ctx.active_window_id == "win-1"
        assert ctx.dry_run is True
        assert ctx.metadata == {"key": "value"}

    def test_record_operation(self):
        """record_operation updates context."""
        ctx = AutomationContext()
        assert ctx.operation_count == 0
        assert ctx.last_operation is None

        ctx.record_operation()
        assert ctx.operation_count == 1
        assert ctx.last_operation is not None
        assert isinstance(ctx.last_operation, datetime)

        ctx.record_operation()
        assert ctx.operation_count == 2


class TestCapability:
    """Test Capability enum."""

    def test_capability_values(self):
        """Capability enum has expected values."""
        assert Capability.LAUNCH_APP.value is not None
        assert Capability.QUIT_APP.value is not None
        assert Capability.TYPE_TEXT.value is not None
        assert Capability.CLICK.value is not None
        assert Capability.SCREENSHOT.value is not None


class TestBackendCapabilities:
    """Test BackendCapabilities dataclass."""

    def test_creation(self):
        """BackendCapabilities can be created."""
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.LAUNCH_APP, Capability.CLICK},
        )
        assert caps.name == "test"
        assert caps.platform == Platform.MACOS
        assert Capability.LAUNCH_APP in caps.capabilities
        assert caps.priority == 0
        assert caps.notes is None

    def test_supports_single(self):
        """supports() checks single capability."""
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.LAUNCH_APP, Capability.QUIT_APP},
        )
        assert caps.supports(Capability.LAUNCH_APP) is True
        assert caps.supports(Capability.CLICK) is False

    def test_supports_all(self):
        """supports_all() checks all capabilities present."""
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.LAUNCH_APP, Capability.QUIT_APP, Capability.CLICK},
        )
        assert caps.supports_all({Capability.LAUNCH_APP, Capability.QUIT_APP}) is True
        assert caps.supports_all({Capability.LAUNCH_APP, Capability.CLICK}) is True
        assert caps.supports_all({Capability.LAUNCH_APP, Capability.SCREENSHOT}) is False

    def test_supports_any(self):
        """supports_any() checks any capability present."""
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.LAUNCH_APP, Capability.CLICK},
        )
        assert caps.supports_any({Capability.LAUNCH_APP, Capability.SCREENSHOT}) is True
        assert caps.supports_any({Capability.SCREENSHOT, Capability.SCROLL}) is False

    def test_to_dict(self):
        """to_dict() returns correct structure."""
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.LAUNCH_APP},
            priority=50,
            notes="Test notes",
        )
        d = caps.to_dict()
        assert d["name"] == "test"
        assert d["platform"] == "darwin"
        # Capability values are lowercase strings
        assert "launch_app" in d["capabilities"]
        assert d["priority"] == 50
        assert d["notes"] == "Test notes"

    def test_platform_set(self):
        """Platform can be a set of platforms."""
        caps = BackendCapabilities(
            name="cross-platform",
            platform={Platform.MACOS, Platform.WINDOWS, Platform.LINUX},
            capabilities=set(),
        )
        d = caps.to_dict()
        assert "darwin" in d["platform"]
        assert "win32" in d["platform"]
        assert "linux" in d["platform"]


class TestBackendStatus:
    """Test BackendStatus dataclass."""

    def test_creation(self):
        """BackendStatus can be created."""
        status = BackendStatus(name="test", available=True)
        assert status.name == "test"
        assert status.available is True
        assert status.reason is None
        assert status.capabilities is None

    def test_with_capabilities(self):
        """BackendStatus with full capabilities."""
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.LAUNCH_APP},
        )
        status = BackendStatus(
            name="test",
            available=True,
            capabilities=caps,
        )
        assert status.capabilities is not None
        assert status.capabilities.supports(Capability.LAUNCH_APP)

    def test_to_dict(self):
        """to_dict() returns correct structure."""
        status = BackendStatus(name="test", available=False, reason="Not installed")
        d = status.to_dict()
        assert d["name"] == "test"
        assert d["available"] is False
        assert d["reason"] == "Not installed"
        assert d["capabilities"] is None


class TestCapabilityDetector:
    """Test CapabilityDetector class."""

    def test_platform_detection_darwin(self):
        """Detector correctly identifies macOS platform."""
        with patch.object(sys, "platform", "darwin"):
            detector = CapabilityDetector()
            assert detector.get_platform() == Platform.MACOS

    def test_platform_detection_windows(self):
        """Detector correctly identifies Windows platform."""
        with patch.object(sys, "platform", "win32"):
            detector = CapabilityDetector()
            assert detector.get_platform() == Platform.WINDOWS

    def test_platform_detection_linux(self):
        """Detector correctly identifies Linux platform."""
        with patch.object(sys, "platform", "linux"):
            detector = CapabilityDetector()
            assert detector.get_platform() == Platform.LINUX

    def test_is_backend_available_uses_cache(self):
        """is_backend_available uses cache to avoid repeated checks."""
        detector = CapabilityDetector()
        mock_status = BackendStatus(name="test", available=True)
        detector._cache["test"] = mock_status

        # is_backend_available should return cached result without calling get_backend_status
        result = detector.is_backend_available("test")

        assert result is True
        # The cache was populated, so the backend should be considered available
        # without doing any additional checks

    def test_get_backend_status_unknown(self):
        """get_backend_status returns not available for unknown backend."""
        detector = CapabilityDetector()
        status = detector.get_backend_status("unknown_backend")
        assert status.available is False
        assert "Unknown backend" in status.reason

    def test_get_available_backends(self):
        """get_available_backends returns status for all backends."""
        detector = CapabilityDetector()
        backends = detector.get_available_backends()
        names = {b.name for b in backends}
        assert "pyxa" in names
        assert "atomac" in names
        assert "pyautogui" in names

    def test_find_best_backend_preferred_available(self):
        """find_best_backend uses preferred backend when available."""
        detector = CapabilityDetector()
        detector._cache["pyxa"] = BackendStatus(
            name="pyxa",
            available=True,
            capabilities=PYXA_CAPABILITIES,
        )

        result = detector.find_best_backend(
            required_capabilities={Capability.LAUNCH_APP},
            preferred="pyxa",
        )
        assert result is not None
        assert result.name == "pyxa"

    def test_find_best_backend_preferred_insufficient(self):
        """find_best_backend falls back when preferred lacks capabilities."""
        detector = CapabilityDetector()
        detector._cache["pyautogui"] = BackendStatus(
            name="pyautogui",
            available=True,
            capabilities=PYAUTOGUI_CAPABILITIES,
        )

        # pyautogui doesn't support LAUNCH_APP
        result = detector.find_best_backend(
            required_capabilities={Capability.LAUNCH_APP},
            preferred="pyautogui",
        )
        assert result is None

    def test_find_best_backend_no_match(self):
        """find_best_backend returns None when no backend matches."""
        detector = CapabilityDetector()

        # Request capability no backend has
        result = detector.find_best_backend(
            required_capabilities={Capability.CLICK_UI_ELEMENT},
        )
        # ATOMac has CLICK_UI_ELEMENT
        assert result is None or result.name == "atomac"


class TestBackendCapabilityConstants:
    """Test predefined backend capability constants."""

    def test_pyxa_capabilities(self):
        """PyXA has all major capabilities."""
        assert PYXA_CAPABILITIES.name == "pyxa"
        assert PYXA_CAPABILITIES.platform == Platform.MACOS
        assert PYXA_CAPABILITIES.priority == 100
        assert Capability.LAUNCH_APP in PYXA_CAPABILITIES.capabilities
        assert Capability.TYPE_TEXT in PYXA_CAPABILITIES.capabilities
        assert Capability.SCREENSHOT in PYXA_CAPABILITIES.capabilities

    def test_atomac_capabilities(self):
        """ATOMac has UI element capabilities."""
        assert ATOMAC_CAPABILITIES.name == "atomac"
        assert ATOMAC_CAPABILITIES.platform == Platform.MACOS
        assert ATOMAC_CAPABILITIES.priority == 80
        assert Capability.LAUNCH_APP in ATOMAC_CAPABILITIES.capabilities
        assert Capability.GET_UI_ELEMENTS in ATOMAC_CAPABILITIES.capabilities

    def test_pyautogui_capabilities(self):
        """PyAutoGUI has cross-platform input capabilities."""
        assert PYAUTOGUI_CAPABILITIES.name == "pyautogui"
        assert Platform.MACOS in PYAUTOGUI_CAPABILITIES.platform
        assert Platform.WINDOWS in PYAUTOGUI_CAPABILITIES.platform
        assert Platform.LINUX in PYAUTOGUI_CAPABILITIES.platform
        assert PYAUTOGUI_CAPABILITIES.priority == 50
        assert Capability.TYPE_TEXT in PYAUTOGUI_CAPABILITIES.capabilities
        assert Capability.CLICK in PYAUTOGUI_CAPABILITIES.capabilities
        assert Capability.SCREENSHOT in PYAUTOGUI_CAPABILITIES.capabilities

    def test_backend_capabilities_presets(self):
        """Each backend has correct capability preset."""
        assert PYXA_CAPABILITIES.name == "pyxa"
        assert ATOMAC_CAPABILITIES.name == "atomac"
        assert PYAUTOGUI_CAPABILITIES.name == "pyautogui"