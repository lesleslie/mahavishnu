"""Unit tests for mahavishnu.automation.capabilities.

Covers capability enums, BackendCapabilities, BackendStatus, the
CapabilityDetector class, and the module-level singleton helpers.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from mahavishnu.automation.capabilities import (
    NATIVE_MACOS_CAPABILITIES,
    PYAUTOGUI_CAPABILITIES,
    BackendCapabilities,
    BackendStatus,
    Capability,
    CapabilityDetector,
    Platform,
    find_best_backend,
    get_available_backends,
    get_capability_detector,
)

# =============================================================================
# Capability Enum Tests
# =============================================================================


class TestCapabilityEnum:
    @pytest.mark.unit
    def test_capability_count_minimum(self):
        # 21 capabilities are defined
        assert len(Capability) >= 21

    @pytest.mark.unit
    def test_application_capabilities(self):
        assert Capability.LAUNCH_APP
        assert Capability.QUIT_APP
        assert Capability.ACTIVATE_APP
        assert Capability.LIST_APPS

    @pytest.mark.unit
    def test_window_capabilities(self):
        for cap in (
            Capability.LIST_WINDOWS,
            Capability.ACTIVATE_WINDOW,
            Capability.RESIZE_WINDOW,
            Capability.MOVE_WINDOW,
            Capability.CLOSE_WINDOW,
        ):
            assert cap is not None

    @pytest.mark.unit
    def test_input_capabilities(self):
        for cap in (
            Capability.TYPE_TEXT,
            Capability.PRESS_KEY,
            Capability.CLICK,
            Capability.DRAG,
            Capability.SCROLL,
        ):
            assert cap is not None

    @pytest.mark.unit
    def test_screenshot_capabilities(self):
        assert Capability.SCREENSHOT
        assert Capability.SCREENSHOT_REGION

    @pytest.mark.unit
    def test_clipboard_capabilities(self):
        assert Capability.GET_CLIPBOARD
        assert Capability.SET_CLIPBOARD

    @pytest.mark.unit
    def test_values_are_strings(self):
        for cap in Capability:
            assert isinstance(cap.value, str)
            assert len(cap.value) > 0


# =============================================================================
# Platform Enum Tests
# =============================================================================


class TestPlatformEnum:
    @pytest.mark.unit
    def test_platform_values(self):
        assert Platform.MACOS == "darwin"
        assert Platform.WINDOWS == "win32"
        assert Platform.LINUX == "linux"


# =============================================================================
# BackendCapabilities Tests
# =============================================================================


class TestBackendCapabilities:
    @pytest.mark.unit
    def test_supports_single(self):
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.CLICK, Capability.DRAG},
        )
        assert caps.supports(Capability.CLICK) is True
        assert caps.supports(Capability.SCROLL) is False

    @pytest.mark.unit
    def test_supports_all(self):
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.CLICK, Capability.DRAG, Capability.SCROLL},
        )
        assert caps.supports_all({Capability.CLICK, Capability.DRAG}) is True
        assert caps.supports_all({Capability.CLICK, Capability.SCREENSHOT}) is False
        # empty set is trivially a subset
        assert caps.supports_all(set()) is True

    @pytest.mark.unit
    def test_supports_any(self):
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.CLICK},
        )
        assert caps.supports_any({Capability.CLICK, Capability.DRAG}) is True
        assert caps.supports_any({Capability.DRAG, Capability.SCROLL}) is False
        assert caps.supports_any(set()) is False

    @pytest.mark.unit
    def test_to_dict_single_platform(self):
        caps = BackendCapabilities(
            name="test",
            platform=Platform.MACOS,
            capabilities={Capability.CLICK},
            priority=50,
            notes="test notes",
        )
        d = caps.to_dict()
        assert d["name"] == "test"
        assert d["platform"] == "darwin"
        assert d["capabilities"] == ["click"]
        assert d["priority"] == 50
        assert d["notes"] == "test notes"

    @pytest.mark.unit
    def test_to_dict_multi_platform(self):
        caps = BackendCapabilities(
            name="test",
            platform={Platform.MACOS, Platform.LINUX},
            capabilities=set(),
        )
        d = caps.to_dict()
        assert isinstance(d["platform"], list)
        assert "darwin" in d["platform"]
        assert "linux" in d["platform"]


# =============================================================================
# Pre-defined Capability Sets
# =============================================================================


class TestNativeMacOSCapabilities:
    @pytest.mark.unit
    def test_has_application_management(self):
        assert Capability.LAUNCH_APP in NATIVE_MACOS_CAPABILITIES.capabilities
        assert Capability.QUIT_APP in NATIVE_MACOS_CAPABILITIES.capabilities
        assert Capability.ACTIVATE_APP in NATIVE_MACOS_CAPABILITIES.capabilities
        assert Capability.LIST_APPS in NATIVE_MACOS_CAPABILITIES.capabilities

    @pytest.mark.unit
    def test_lacks_resize_and_move_window(self):
        # osascript cannot resize or move windows
        assert Capability.RESIZE_WINDOW not in NATIVE_MACOS_CAPABILITIES.capabilities
        assert Capability.MOVE_WINDOW not in NATIVE_MACOS_CAPABILITIES.capabilities

    @pytest.mark.unit
    def test_lacks_ui_element_access(self):
        assert Capability.GET_UI_ELEMENTS not in NATIVE_MACOS_CAPABILITIES.capabilities
        assert Capability.CLICK_UI_ELEMENT not in NATIVE_MACOS_CAPABILITIES.capabilities

    @pytest.mark.unit
    def test_platform_is_macos(self):
        assert NATIVE_MACOS_CAPABILITIES.platform == Platform.MACOS

    @pytest.mark.unit
    def test_priority_higher_than_pyautogui(self):
        # native backend should be preferred on macOS
        assert NATIVE_MACOS_CAPABILITIES.priority > PYAUTOGUI_CAPABILITIES.priority


class TestPyAutoGUICapabilities:
    @pytest.mark.unit
    def test_cross_platform(self):
        assert Platform.MACOS in PYAUTOGUI_CAPABILITIES.platform
        assert Platform.WINDOWS in PYAUTOGUI_CAPABILITIES.platform
        assert Platform.LINUX in PYAUTOGUI_CAPABILITIES.platform

    @pytest.mark.unit
    def test_has_input_capabilities(self):
        for cap in (
            Capability.TYPE_TEXT,
            Capability.PRESS_KEY,
            Capability.CLICK,
            Capability.DRAG,
            Capability.SCROLL,
        ):
            assert cap in PYAUTOGUI_CAPABILITIES.capabilities

    @pytest.mark.unit
    def test_lacks_application_management(self):
        assert Capability.LAUNCH_APP not in PYAUTOGUI_CAPABILITIES.capabilities
        assert Capability.QUIT_APP not in PYAUTOGUI_CAPABILITIES.capabilities

    @pytest.mark.unit
    def test_lacks_window_management(self):
        assert Capability.LIST_WINDOWS not in PYAUTOGUI_CAPABILITIES.capabilities
        assert Capability.RESIZE_WINDOW not in PYAUTOGUI_CAPABILITIES.capabilities


# =============================================================================
# BackendStatus Tests
# =============================================================================


class TestBackendStatus:
    @pytest.mark.unit
    def test_construction_minimal(self):
        status = BackendStatus(name="x", available=True)
        assert status.name == "x"
        assert status.available is True
        assert status.reason is None
        assert status.capabilities is None

    @pytest.mark.unit
    def test_construction_with_capabilities(self):
        status = BackendStatus(
            name="x",
            available=False,
            reason="missing",
            capabilities=PYAUTOGUI_CAPABILITIES,
        )
        assert status.reason == "missing"
        assert status.capabilities is PYAUTOGUI_CAPABILITIES

    @pytest.mark.unit
    def test_to_dict_without_capabilities(self):
        status = BackendStatus(name="x", available=False, reason="no")
        d = status.to_dict()
        assert d == {"name": "x", "available": False, "reason": "no", "capabilities": None}

    @pytest.mark.unit
    def test_to_dict_with_capabilities(self):
        status = BackendStatus(
            name="x",
            available=True,
            capabilities=PYAUTOGUI_CAPABILITIES,
        )
        d = status.to_dict()
        assert d["capabilities"] is not None
        assert d["capabilities"]["name"] == "pyautogui"


# =============================================================================
# CapabilityDetector Tests
# =============================================================================


@pytest.fixture
def detector() -> CapabilityDetector:
    return CapabilityDetector()


class TestCapabilityDetectorInit:
    @pytest.mark.unit
    def test_detects_macos(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        d = CapabilityDetector()
        assert d.get_platform() == Platform.MACOS

    @pytest.mark.unit
    def test_detects_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        d = CapabilityDetector()
        assert d.get_platform() == Platform.WINDOWS

    @pytest.mark.unit
    def test_detects_linux(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        d = CapabilityDetector()
        assert d.get_platform() == Platform.LINUX


class TestCheckNativeMacOS:
    @pytest.mark.unit
    def test_native_macos_unavailable_on_non_macos(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        d = CapabilityDetector()
        status = d._check_native_macos()
        assert status.available is False
        assert "macOS" in status.reason
        assert status.capabilities is NATIVE_MACOS_CAPABILITIES

    @pytest.mark.unit
    def test_native_macos_unavailable_when_backend_unavailable(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch(
            "mahavishnu.automation.backends.native_macos.NativeMacOSBackend.is_available",
            return_value=False,
        ):
            d = CapabilityDetector()
            status = d._check_native_macos()
        assert status.available is False
        assert "cliclick" in (status.reason or "")

    @pytest.mark.unit
    def test_native_macos_available_when_installed(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch(
            "mahavishnu.automation.backends.native_macos.NativeMacOSBackend.is_available",
            return_value=True,
        ):
            d = CapabilityDetector()
            status = d._check_native_macos()
        assert status.available is True
        assert status.reason is None

    @pytest.mark.unit
    def test_native_macos_handles_import_error(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        # Simulate a transient import failure by raising ImportError on access
        with patch.dict("sys.modules", {"mahavishnu.automation.backends.native_macos": None}):
            d = CapabilityDetector()
            status = d._check_native_macos()
        # When the module is None, importing raises ImportError -> not installed
        assert status.available is False
        assert "not installed" in (status.reason or "")


class TestCheckPyautogui:
    @pytest.mark.unit
    def test_pyautogui_available(self):
        with patch.dict(sys.modules, {"pyautogui": MagicMock()}):
            d = CapabilityDetector()
            status = d._check_pyautogui()
        assert status.available is True
        assert status.capabilities is PYAUTOGUI_CAPABILITIES

    @pytest.mark.unit
    def test_pyautogui_unavailable(self):
        # Ensure import fails
        with patch.dict(sys.modules, {"pyautogui": None}):
            d = CapabilityDetector()
            status = d._check_pyautogui()
        assert status.available is False
        assert "pip install pyautogui" in (status.reason or "")


class TestGetBackendStatus:
    @pytest.mark.unit
    def test_unknown_backend(self, detector):
        status = detector.get_backend_status("nonexistent")
        assert status.available is False
        assert "Unknown backend" in (status.reason or "")
        assert status.capabilities is None

    @pytest.mark.unit
    def test_caching(self, detector):
        # First call populates cache
        first = detector.get_backend_status("pyautogui")
        # Force the second call to return a different object if not cached
        with patch.object(
            detector, "_check_pyautogui", return_value=BackendStatus(name="x", available=False)
        ):
            cached = detector.get_backend_status("pyautogui")
        # Should be the same object that was first cached
        assert cached is first

    @pytest.mark.unit
    def test_name_case_insensitive(self, detector):
        s_lower = detector.get_backend_status("pyautogui")
        s_upper = detector.get_backend_status("PYAUTOGUI")
        assert s_lower is s_upper


class TestGetAvailableBackends:
    @pytest.mark.unit
    def test_returns_list(self, detector):
        results = detector.get_available_backends()
        assert isinstance(results, list)
        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"native_macos", "pyautogui"}


class TestFindBestBackend:
    @pytest.mark.unit
    def test_returns_none_when_no_backend_available(self, monkeypatch):
        # Force every check to return unavailable
        monkeypatch.setattr(sys, "platform", "linux")
        with patch.dict(sys.modules, {"pyautogui": None}):
            d = CapabilityDetector()
            result = d.find_best_backend()
        assert result is None

    @pytest.mark.unit
    def test_preferred_backend_returned_when_available(self):
        # Pretend pyautogui is the only available backend
        with patch.dict(sys.modules, {"pyautogui": MagicMock()}):
            d = CapabilityDetector()
            with patch.object(
                d,
                "_check_native_macos",
                return_value=BackendStatus(name="native_macos", available=False, reason="no"),
            ):
                result = d.find_best_backend(preferred="pyautogui")
        assert result is not None
        assert result.name == "pyautogui"

    @pytest.mark.unit
    def test_preferred_skipped_when_required_caps_unsupported(self):
        with patch.dict(sys.modules, {"pyautogui": MagicMock()}):
            d = CapabilityDetector()
            # native macOS is preferred but doesn't have RESIZE_WINDOW
            with patch.object(
                d,
                "_check_native_macos",
                return_value=BackendStatus(
                    name="native_macos", available=True, capabilities=NATIVE_MACOS_CAPABILITIES
                ),
            ):
                # Request something the native backend can't do
                result = d.find_best_backend(
                    required_capabilities={Capability.RESIZE_WINDOW},
                    preferred="native_macos",
                )
        # falls through to other backends; if none match, returns None
        # since pyautogui also lacks RESIZE_WINDOW, this is None
        assert result is None

    @pytest.mark.unit
    def test_required_capabilities_filter(self):
        with patch.dict(sys.modules, {"pyautogui": MagicMock()}):
            d = CapabilityDetector()
            with patch.object(
                d,
                "_check_native_macos",
                return_value=BackendStatus(
                    name="native_macos", available=True, capabilities=NATIVE_MACOS_CAPABILITIES
                ),
            ):
                # LAUNCH_APP is supported by native but not pyautogui
                result = d.find_best_backend(
                    required_capabilities={Capability.LAUNCH_APP},
                )
        assert result is not None
        assert result.name == "native_macos"

    @pytest.mark.unit
    def test_auto_preferred_does_not_short_circuit(self):
        # "auto" should be treated like no preference
        with patch.dict(sys.modules, {"pyautogui": MagicMock()}):
            d = CapabilityDetector()
            with patch.object(
                d,
                "_check_native_macos",
                return_value=BackendStatus(name="native_macos", available=False, reason="no"),
            ):
                result = d.find_best_backend(preferred="auto")
        # falls through to pyautogui (only available backend)
        assert result is not None
        assert result.name == "pyautogui"

    @pytest.mark.unit
    def test_higher_priority_wins(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "darwin")
        with patch.dict(sys.modules, {"pyautogui": MagicMock()}):
            d = CapabilityDetector()
            with patch.object(
                d,
                "_check_native_macos",
                return_value=BackendStatus(
                    name="native_macos", available=True, capabilities=NATIVE_MACOS_CAPABILITIES
                ),
            ):
                result = d.find_best_backend()
        # native_macos has priority 90, pyautogui 50
        assert result.name == "native_macos"


class TestToDict:
    @pytest.mark.unit
    def test_to_dict_includes_platform(self, detector):
        d = detector.to_dict()
        assert "platform" in d
        assert "backends" in d
        assert isinstance(d["backends"], list)


# =============================================================================
# Module-level helpers
# =============================================================================


class TestModuleLevelHelpers:
    @pytest.mark.unit
    def test_get_capability_detector_returns_singleton(self):
        a = get_capability_detector()
        b = get_capability_detector()
        assert a is b

    @pytest.mark.unit
    def test_get_available_backends_returns_list(self):
        result = get_available_backends()
        assert isinstance(result, list)
        assert all(isinstance(s, BackendStatus) for s in result)

    @pytest.mark.unit
    def test_find_best_backend_module_helper(self):
        # When no caps are required, it should return SOMETHING (or None on
        # a clean CI box), but it must not raise.
        result = find_best_backend()
        # result is None OR a BackendStatus
        assert result is None or isinstance(result, BackendStatus)
