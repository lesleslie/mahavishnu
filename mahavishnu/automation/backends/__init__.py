"""Automation backend implementations.

This module provides backend implementations for desktop automation:
- PyXA: macOS application automation (primary for macOS)
- ATOMac: macOS accessibility API (deprioritized)
- PyAutoGUI: Cross-platform input automation (fallback)

Backends implement the DesktopAutomationBackend interface and can be
selected automatically based on platform and available capabilities.
"""

from mahavishnu.automation.backends.atomac import ATOMacBackend
from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.backends.pyautogui import PyAutoGUIBackend
from mahavishnu.automation.backends.pyxa import PyXABackend

__all__ = [
    "DesktopAutomationBackend",
    "PyXABackend",
    "ATOMacBackend",
    "PyAutoGUIBackend",
]
