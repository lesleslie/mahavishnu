"""Automation backend implementations.

This module provides backend implementations for desktop automation:
- NativeMacOSBackend: macOS native tools (osascript, cliclick, screencapture)
- PyAutoGUI: Cross-platform input automation (fallback)

Backends implement the DesktopAutomationBackend interface and can be
selected automatically based on platform and available capabilities.
"""

from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.backends.native_macos import NativeMacOSBackend
from mahavishnu.automation.backends.pyautogui import PyAutoGUIBackend

__all__ = [
    "DesktopAutomationBackend",
    "NativeMacOSBackend",
    "PyAutoGUIBackend",
]
