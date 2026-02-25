"""Backend capability detection for desktop automation.

Provides capability detection for different automation backends:
- PyXA: macOS application automation
- ATOMac: macOS accessibility API
- PyAutoGUI: Cross-platform input automation

This module enables automatic backend selection based on available capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto
import sys


class Capability(StrEnum):
    """Capabilities that an automation backend can provide."""

    # Application management
    LAUNCH_APP = auto()
    QUIT_APP = auto()
    ACTIVATE_APP = auto()
    LIST_APPS = auto()

    # Window management
    LIST_WINDOWS = auto()
    ACTIVATE_WINDOW = auto()
    RESIZE_WINDOW = auto()
    MOVE_WINDOW = auto()
    CLOSE_WINDOW = auto()

    # Menu interaction
    CLICK_MENU = auto()
    LIST_MENUS = auto()

    # Input
    TYPE_TEXT = auto()
    PRESS_KEY = auto()
    CLICK = auto()
    DRAG = auto()
    SCROLL = auto()

    # Screenshots
    SCREENSHOT = auto()
    SCREENSHOT_REGION = auto()

    # UI Element access (accessibility)
    GET_UI_ELEMENTS = auto()
    CLICK_UI_ELEMENT = auto()

    # Multi-display
    LIST_SCREENS = auto()

    # Clipboard
    GET_CLIPBOARD = auto()
    SET_CLIPBOARD = auto()


class Platform(StrEnum):
    """Supported platforms."""

    MACOS = "darwin"
    WINDOWS = "win32"
    LINUX = "linux"


@dataclass
class BackendCapabilities:
    """Capabilities of an automation backend.

    Attributes:
        name: Backend name
        platform: Supported platform(s)
        capabilities: Set of supported capabilities
        priority: Priority for auto-selection (higher = preferred)
        notes: Additional notes about limitations
    """

    name: str
    platform: Platform | set[Platform]
    capabilities: set[Capability]
    priority: int = 0
    notes: str | None = None

    def supports(self, capability: Capability) -> bool:
        """Check if backend supports a capability."""
        return capability in self.capabilities

    def supports_all(self, capabilities: set[Capability]) -> bool:
        """Check if backend supports all specified capabilities."""
        return capabilities.issubset(self.capabilities)

    def supports_any(self, capabilities: set[Capability]) -> bool:
        """Check if backend supports any of the specified capabilities."""
        return bool(capabilities & self.capabilities)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "platform": self.platform.value
            if isinstance(self.platform, Platform)
            else [p.value for p in self.platform],
            "capabilities": [c.value for c in self.capabilities],
            "priority": self.priority,
            "notes": self.notes,
        }


# PyXA capabilities (macOS primary)
PYXA_CAPABILITIES = BackendCapabilities(
    name="pyxa",
    platform=Platform.MACOS,
    capabilities={
        # Application management
        Capability.LAUNCH_APP,
        Capability.QUIT_APP,
        Capability.ACTIVATE_APP,
        Capability.LIST_APPS,
        # Window management
        Capability.LIST_WINDOWS,
        Capability.ACTIVATE_WINDOW,
        Capability.RESIZE_WINDOW,
        Capability.MOVE_WINDOW,
        Capability.CLOSE_WINDOW,
        # Menu interaction
        Capability.CLICK_MENU,
        Capability.LIST_MENUS,
        # Input
        Capability.TYPE_TEXT,
        Capability.PRESS_KEY,
        Capability.CLICK,
        Capability.DRAG,
        Capability.SCROLL,
        # Screenshots
        Capability.SCREENSHOT,
        Capability.SCREENSHOT_REGION,
        # UI Elements
        Capability.GET_UI_ELEMENTS,
        Capability.CLICK_UI_ELEMENT,
        # Multi-display
        Capability.LIST_SCREENS,
        # Clipboard
        Capability.GET_CLIPBOARD,
        Capability.SET_CLIPBOARD,
    },
    priority=100,  # Highest priority on macOS
    notes="Primary macOS backend with full accessibility support",
)

# ATOMac capabilities (macOS accessibility)
ATOMAC_CAPABILITIES = BackendCapabilities(
    name="atomac",
    platform=Platform.MACOS,
    capabilities={
        # Application management
        Capability.LAUNCH_APP,
        Capability.ACTIVATE_APP,
        Capability.LIST_APPS,
        # Window management
        Capability.LIST_WINDOWS,
        Capability.ACTIVATE_WINDOW,
        # Menu interaction
        Capability.CLICK_MENU,
        # UI Elements (strong point)
        Capability.GET_UI_ELEMENTS,
        Capability.CLICK_UI_ELEMENT,
    },
    priority=80,  # Secondary on macOS (deprioritized due to maintenance concerns)
    notes="Advanced accessibility API access, deprioritized due to maintenance concerns",
)

# PyAutoGUI capabilities (cross-platform)
PYAUTOGUI_CAPABILITIES = BackendCapabilities(
    name="pyautogui",
    platform={Platform.MACOS, Platform.WINDOWS, Platform.LINUX},
    capabilities={
        # Input (strong point)
        Capability.TYPE_TEXT,
        Capability.PRESS_KEY,
        Capability.CLICK,
        Capability.DRAG,
        Capability.SCROLL,
        # Screenshots
        Capability.SCREENSHOT,
        Capability.SCREENSHOT_REGION,
        # Multi-display
        Capability.LIST_SCREENS,
        # Clipboard
        Capability.GET_CLIPBOARD,
        Capability.SET_CLIPBOARD,
    },
    priority=50,  # Fallback - coordinate-based, less reliable
    notes="Cross-platform fallback. Coordinate-based automation without app/window awareness",
)


@dataclass
class BackendStatus:
    """Status of a backend on the current system."""

    name: str
    available: bool
    reason: str | None = None
    capabilities: BackendCapabilities | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "available": self.available,
            "reason": self.reason,
            "capabilities": self.capabilities.to_dict() if self.capabilities else None,
        }


class CapabilityDetector:
    """Detect available backends and their capabilities.

    This class checks which automation backends are available on the
    current system and provides capability information for each.

    Usage:
        detector = CapabilityDetector()

        # Check if a specific backend is available
        if detector.is_backend_available("pyxa"):
            print("PyXA is available")

        # Get all available backends
        for status in detector.get_available_backends():
            print(f"{status.name}: {status.available}")

        # Find best backend for capabilities
        backend = detector.find_best_backend({
            Capability.LAUNCH_APP,
            Capability.CLICK_MENU,
        })
    """

    def __init__(self) -> None:
        """Initialize the capability detector."""
        self._platform = self._detect_platform()
        self._cache: dict[str, BackendStatus] = {}

    def _detect_platform(self) -> Platform:
        """Detect the current platform."""
        if sys.platform == "darwin":
            return Platform.MACOS
        elif sys.platform == "win32":
            return Platform.WINDOWS
        else:
            return Platform.LINUX

    def _check_pyxa(self) -> BackendStatus:
        """Check if PyXA backend is available."""
        if self._platform != Platform.MACOS:
            return BackendStatus(
                name="pyxa",
                available=False,
                reason="PyXA is only available on macOS",
                capabilities=PYXA_CAPABILITIES,
            )

        try:
            import PyXA  # noqa: F401

            return BackendStatus(
                name="pyxa",
                available=True,
                capabilities=PYXA_CAPABILITIES,
            )
        except ImportError:
            return BackendStatus(
                name="pyxa",
                available=False,
                reason="PyXA not installed. Install with: pip install pyxa",
                capabilities=PYXA_CAPABILITIES,
            )

    def _check_atomac(self) -> BackendStatus:
        """Check if ATOMac backend is available."""
        if self._platform != Platform.MACOS:
            return BackendStatus(
                name="atomac",
                available=False,
                reason="ATOMac is only available on macOS",
                capabilities=ATOMAC_CAPABILITIES,
            )

        try:
            import atomac  # noqa: F401

            return BackendStatus(
                name="atomac",
                available=True,
                capabilities=ATOMAC_CAPABILITIES,
            )
        except ImportError:
            return BackendStatus(
                name="atomac",
                available=False,
                reason="ATOMac not installed. Install with: pip install pyatomac",
                capabilities=ATOMAC_CAPABILITIES,
            )

    def _check_pyautogui(self) -> BackendStatus:
        """Check if PyAutoGUI backend is available."""
        try:
            import pyautogui  # noqa: F401

            return BackendStatus(
                name="pyautogui",
                available=True,
                capabilities=PYAUTOGUI_CAPABILITIES,
            )
        except ImportError:
            return BackendStatus(
                name="pyautogui",
                available=False,
                reason="PyAutoGUI not installed. Install with: pip install pyautogui",
                capabilities=PYAUTOGUI_CAPABILITIES,
            )

    def is_backend_available(self, name: str) -> bool:
        """Check if a specific backend is available.

        Args:
            name: Backend name (pyxa, atomac, pyautogui).

        Returns:
            True if the backend is available.
        """
        status = self.get_backend_status(name)
        return status.available

    def get_backend_status(self, name: str) -> BackendStatus:
        """Get the status of a specific backend.

        Args:
            name: Backend name.

        Returns:
            BackendStatus with availability and reason.
        """
        name_lower = name.lower()

        if name_lower in self._cache:
            return self._cache[name_lower]

        checkers = {
            "pyxa": self._check_pyxa,
            "atomac": self._check_atomac,
            "pyautogui": self._check_pyautogui,
        }

        checker = checkers.get(name_lower)
        if checker:
            status = checker()
        else:
            status = BackendStatus(
                name=name,
                available=False,
                reason=f"Unknown backend: {name}",
            )

        self._cache[name_lower] = status
        return status

    def get_available_backends(self) -> list[BackendStatus]:
        """Get status of all known backends.

        Returns:
            List of BackendStatus for each backend.
        """
        return [
            self._check_pyxa(),
            self._check_atomac(),
            self._check_pyautogui(),
        ]

    def find_best_backend(
        self,
        required_capabilities: set[Capability] | None = None,
        preferred: str | None = None,
    ) -> BackendStatus | None:
        """Find the best available backend.

        Args:
            required_capabilities: Set of required capabilities.
            preferred: Preferred backend name (if available).

        Returns:
            Best available BackendStatus, or None if no backend matches.
        """
        # Check preferred backend first
        if preferred and preferred.lower() != "auto":
            status = self.get_backend_status(preferred)
            if status.available:
                if required_capabilities is None or status.capabilities is None:
                    return status
                if status.capabilities.supports_all(required_capabilities):
                    return status

        # Find best available backend
        available = [
            s for s in self.get_available_backends() if s.available and s.capabilities is not None
        ]

        # Filter by required capabilities
        if required_capabilities:
            available = [
                s
                for s in available
                if s.capabilities and s.capabilities.supports_all(required_capabilities)
            ]

        if not available:
            return None

        # Sort by priority (highest first)
        available.sort(key=lambda s: s.capabilities.priority if s.capabilities else 0, reverse=True)

        return available[0]

    def get_platform(self) -> Platform:
        """Get the current platform."""
        return self._platform

    def to_dict(self) -> dict:
        """Get detector status as dictionary."""
        return {
            "platform": self._platform.value,
            "backends": [s.to_dict() for s in self.get_available_backends()],
        }


# Global detector instance
_detector: CapabilityDetector | None = None


def get_capability_detector() -> CapabilityDetector:
    """Get the global capability detector instance."""
    global _detector
    if _detector is None:
        _detector = CapabilityDetector()
    return _detector


def get_available_backends() -> list[BackendStatus]:
    """Get status of all available backends.

    Convenience function using global detector.
    """
    return get_capability_detector().get_available_backends()


def find_best_backend(
    required_capabilities: set[Capability] | None = None,
    preferred: str | None = None,
) -> BackendStatus | None:
    """Find the best available backend.

    Convenience function using global detector.
    """
    return get_capability_detector().find_best_backend(required_capabilities, preferred)
