"""macOS permission checks for desktop automation.

Provides permission checking for:
- Accessibility (required for all automation)
- Screen Recording (required for screenshots)

Uses PyObjC to access macOS Accessibility APIs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sys


class PermissionStatus(Enum):
    """Status of a permission."""

    GRANTED = "granted"
    DENIED = "denied"
    NOT_DETERMINED = "not_determined"
    UNKNOWN = "unknown"


@dataclass
class PermissionInfo:
    """Information about a permission."""

    name: str
    status: PermissionStatus
    required: bool
    description: str
    recovery_hint: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "status": self.status.value,
            "required": self.required,
            "description": self.description,
            "recovery_hint": self.recovery_hint,
        }


class PermissionChecker:
    """Check macOS permissions for desktop automation.

    This class provides methods to check if the application has the required
    permissions for desktop automation on macOS.

    Usage:
        checker = PermissionChecker()

        # Check accessibility permission
        if not checker.check_accessibility():
            print("Accessibility permission required")

        # Check screen recording permission
        if not checker.check_screen_recording():
            print("Screen recording permission required for screenshots")

        # Get all permissions
        for perm in checker.get_all_permissions():
            print(f"{perm.name}: {perm.status.value}")
    """

    def __init__(self) -> None:
        """Initialize the permission checker."""
        self._is_macos = sys.platform == "darwin"
        self._cached_accessibility: PermissionStatus | None = None
        self._cached_screen_recording: PermissionStatus | None = None

    def is_macos(self) -> bool:
        """Check if running on macOS."""
        return self._is_macos

    def check_accessibility(self) -> bool:
        """Check if accessibility permissions are granted.

        On macOS, this uses the AXIsProcessTrusted() function from the
        Accessibility API.

        Returns:
            True if accessibility permissions are granted, False otherwise.
        """
        if not self._is_macos:
            # Non-macOS platforms don't need accessibility permissions
            return True

        try:
            from ApplicationServices import AXIsProcessTrusted

            return AXIsProcessTrusted()
        except ImportError:
            # PyObjC not available, assume permissions are granted
            # This allows the code to run in test environments
            return True
        except Exception:
            return False

    def check_screen_recording(self) -> bool:
        """Check if screen recording permissions are granted.

        On macOS 10.15+, screen recording permission is required for
        taking screenshots.

        Returns:
            True if screen recording permissions are granted, False otherwise.
        """
        if not self._is_macos:
            # Non-macOS platforms don't need screen recording permissions
            return True

        try:
            # Try to capture a 1x1 pixel to test permission
            # This is the most reliable way to check on macOS 10.15+
            import Quartz

            # Create a small image to test capture
            rect = Quartz.CGRectInfinite
            image = Quartz.CGWindowListCreateImage(
                rect,
                Quartz.kCGWindowListOptionOnScreenOnly,
                Quartz.kCGNullWindowID,
                Quartz.kCGWindowImageDefault,
            )

            # If we got an image, permissions are granted
            return image is not None
        except ImportError:
            # Quartz not available, assume permissions are granted
            return True
        except Exception:
            return False

    def get_accessibility_status(self) -> PermissionStatus:
        """Get detailed accessibility permission status."""
        if not self._is_macos:
            return PermissionStatus.GRANTED

        if self.check_accessibility():
            return PermissionStatus.GRANTED
        return PermissionStatus.DENIED

    def get_screen_recording_status(self) -> PermissionStatus:
        """Get detailed screen recording permission status."""
        if not self._is_macos:
            return PermissionStatus.GRANTED

        if self.check_screen_recording():
            return PermissionStatus.GRANTED
        return PermissionStatus.DENIED

    def get_all_permissions(self) -> list[PermissionInfo]:
        """Get status of all automation-related permissions.

        Returns:
            List of PermissionInfo objects for each permission.
        """
        permissions = [
            PermissionInfo(
                name="accessibility",
                status=self.get_accessibility_status(),
                required=True,
                description="Required for controlling applications and UI elements",
                recovery_hint=(
                    "Grant accessibility permissions:\n"
                    "1. Open System Settings > Privacy & Security > Accessibility\n"
                    "2. Add your terminal or Python to the allowed apps\n"
                    "3. Restart the application"
                ),
            ),
            PermissionInfo(
                name="screen_recording",
                status=self.get_screen_recording_status(),
                required=False,  # Only required for screenshots
                description="Required for capturing screenshots",
                recovery_hint=(
                    "Grant screen recording permissions:\n"
                    "1. Open System Settings > Privacy & Security > Screen Recording\n"
                    "2. Add your terminal or Python to the allowed apps\n"
                    "3. Restart the application"
                ),
            ),
        ]
        return permissions

    def request_accessibility(self) -> bool:
        """Request accessibility permissions from the user.

        This will show a system dialog asking the user to grant accessibility
        permissions. The user will need to manually add the app in System Settings.

        Returns:
            True if permissions are already granted or the prompt was shown.
        """
        if not self._is_macos:
            return True

        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions

            # Request accessibility with prompt
            options = {"kAXTrustedCheckOptionPrompt": True}
            return AXIsProcessTrustedWithOptions(options)
        except ImportError:
            return True
        except Exception:
            return False

    def to_dict(self) -> dict:
        """Get permission status as a dictionary."""
        return {
            "platform": sys.platform,
            "permissions": {p.name: p.to_dict() for p in self.get_all_permissions()},
            "all_granted": self.check_accessibility(),
            "can_screenshot": self.check_screen_recording(),
        }


# Global instance for convenience
_checker: PermissionChecker | None = None


def get_permission_checker() -> PermissionChecker:
    """Get the global permission checker instance."""
    global _checker
    if _checker is None:
        _checker = PermissionChecker()
    return _checker


def check_accessibility_permissions() -> bool:
    """Quick check for accessibility permissions.

    Convenience function using the global checker.
    """
    return get_permission_checker().check_accessibility()


def check_screen_recording_permissions() -> bool:
    """Quick check for screen recording permissions.

    Convenience function using the global checker.
    """
    return get_permission_checker().check_screen_recording()


def get_all_permission_status() -> dict:
    """Get all permission status as a dictionary.

    Convenience function using the global checker.
    """
    return get_permission_checker().to_dict()
