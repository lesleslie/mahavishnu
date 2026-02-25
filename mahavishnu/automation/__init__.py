"""Desktop automation module for Mahavishnu.

This module provides desktop automation capabilities with:
- Multiple backend support (PyXA, ATOMac, PyAutoGUI)
- Security-first design with blocklist and input validation
- Permission checks for accessibility and screen recording
- Multi-worker coordination for distributed automation

Usage:
    from mahavishnu.automation import AutomationManager

    manager = AutomationManager()
    await manager.initialize()

    # Launch and control applications
    app = await manager.launch_application("com.apple.finder")
    windows = await manager.get_windows("com.apple.finder")

    # Type text with safety validation
    await manager.type_text("Hello World")

    # Take screenshots
    screenshot = await manager.screenshot()
"""

from mahavishnu.automation.backends.atomac import ATOMacBackend
from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.backends.pyautogui import PyAutoGUIBackend
from mahavishnu.automation.backends.pyxa import PyXABackend
from mahavishnu.automation.base import ApplicationInfo, WindowInfo
from mahavishnu.automation.errors import (
    AutomationError,
    BackendNotAvailableError,
    BlockedAppError,
    BlockedTextError,
    PermissionDeniedError,
)
from mahavishnu.automation.manager import AutomationManager
from mahavishnu.automation.models import (
    AutomationOperation,
    AutomationResult,
    ClickOperation,
    DragOperation,
    KeyPressOperation,
    MenuClickOperation,
    ScreenshotOperation,
    TypeTextOperation,
    WindowOperation,
)

__all__ = [
    # Manager
    "AutomationManager",
    # Backends
    "DesktopAutomationBackend",
    "PyXABackend",
    "ATOMacBackend",
    "PyAutoGUIBackend",
    # Data classes
    "ApplicationInfo",
    "WindowInfo",
    # Models
    "AutomationOperation",
    "AutomationResult",
    "ClickOperation",
    "DragOperation",
    "KeyPressOperation",
    "MenuClickOperation",
    "ScreenshotOperation",
    "TypeTextOperation",
    "WindowOperation",
    # Errors
    "AutomationError",
    "BackendNotAvailableError",
    "BlockedAppError",
    "BlockedTextError",
    "PermissionDeniedError",
]
