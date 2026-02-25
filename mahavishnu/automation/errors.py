"""Error hierarchy for desktop automation.

Provides structured error handling with error codes and recovery guidance.
Follows the same pattern as mahavishnu.core.errors.
"""

from enum import Enum
from typing import Any


class AutomationErrorCode(str, Enum):
    """Error codes for desktop automation.

    Error codes follow format: AUT-XXX
    - AUT-001 to AUT-099: Permission and security errors
    - AUT-100 to AUT-199: Backend errors
    - AUT-200 to AUT-299: Application errors
    - AUT-300 to AUT-399: Window errors
    - AUT-400 to AUT-499: Input errors
    - AUT-500 to AUT-599: Screenshot errors
    """

    # Permission and security errors (001-099)
    PERMISSION_DENIED = "AUT-001"
    ACCESSIBILITY_DENIED = "AUT-002"
    SCREEN_RECORDING_DENIED = "AUT-003"
    BLOCKED_APP = "AUT-010"
    BLOCKED_TEXT = "AUT-011"
    RATE_LIMITED = "AUT-012"

    # Backend errors (100-199)
    BACKEND_NOT_AVAILABLE = "AUT-100"
    BACKEND_INITIALIZATION_FAILED = "AUT-101"
    BACKEND_ERROR = "AUT-102"
    NO_BACKEND_AVAILABLE = "AUT-103"

    # Application errors (200-299)
    APP_NOT_FOUND = "AUT-200"
    APP_LAUNCH_FAILED = "AUT-201"
    APP_QUIT_FAILED = "AUT-202"
    APP_NOT_RUNNING = "AUT-203"

    # Window errors (300-399)
    WINDOW_NOT_FOUND = "AUT-300"
    WINDOW_OPERATION_FAILED = "AUT-301"
    INVALID_WINDOW_STATE = "AUT-302"

    # Input errors (400-499)
    INPUT_VALIDATION_FAILED = "AUT-400"
    INVALID_KEY = "AUT-401"
    INVALID_COORDINATES = "AUT-402"
    MENU_NOT_FOUND = "AUT-403"
    ELEMENT_NOT_FOUND = "AUT-404"

    # Screenshot errors (500-599)
    SCREENSHOT_FAILED = "AUT-500"
    INVALID_REGION = "AUT-501"


class AutomationError(Exception):
    """Base exception for automation errors.

    Attributes:
        code: Error code for programmatic handling
        message: Human-readable error message
        details: Additional error details
        recovery_hint: Suggestion for how to resolve the error
    """

    def __init__(
        self,
        message: str,
        code: AutomationErrorCode = AutomationErrorCode.BACKEND_ERROR,
        details: dict[str, Any] | None = None,
        recovery_hint: str | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.recovery_hint = recovery_hint

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "error": self.code.value,
            "message": self.message,
            "details": self.details,
            "recovery_hint": self.recovery_hint,
        }

    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"


class PermissionDeniedError(AutomationError):
    """Raised when accessibility permissions are not granted."""

    def __init__(
        self,
        message: str = "Accessibility permissions not granted",
        permission_type: str = "accessibility",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=AutomationErrorCode.ACCESSIBILITY_DENIED,
            details={"permission_type": permission_type, **(details or {})},
            recovery_hint=(
                "Grant accessibility permissions:\n"
                "1. Open System Settings > Privacy & Security > Accessibility\n"
                "2. Add your terminal or Python to the allowed apps\n"
                "3. Restart the application"
            ),
        )


class ScreenRecordingDeniedError(AutomationError):
    """Raised when screen recording permissions are not granted."""

    def __init__(
        self,
        message: str = "Screen recording permissions not granted",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=message,
            code=AutomationErrorCode.SCREEN_RECORDING_DENIED,
            details=details,
            recovery_hint=(
                "Grant screen recording permissions:\n"
                "1. Open System Settings > Privacy & Security > Screen Recording\n"
                "2. Add your terminal or Python to the allowed apps\n"
                "3. Restart the application"
            ),
        )


class BlockedAppError(AutomationError):
    """Raised when attempting to automate a blocked application."""

    def __init__(
        self,
        bundle_id: str,
        reason: str = "Application is in security blocklist",
    ):
        super().__init__(
            message=f"Cannot automate '{bundle_id}': {reason}",
            code=AutomationErrorCode.BLOCKED_APP,
            details={"bundle_id": bundle_id, "reason": reason},
            recovery_hint=(
                f"'{bundle_id}' is blocked for security reasons. "
                "To allow this app, add it to the allowed_apps list in settings."
            ),
        )


class BlockedTextError(AutomationError):
    """Raised when text contains blocked patterns."""

    def __init__(
        self,
        pattern: str,
        reason: str = "Text contains sensitive pattern",
    ):
        super().__init__(
            message=f"Cannot type text: {reason}",
            code=AutomationErrorCode.BLOCKED_TEXT,
            details={"pattern": pattern, "reason": reason},
            recovery_hint="The text contains sensitive data that should not be typed automatically.",
        )


class BackendNotAvailableError(AutomationError):
    """Raised when a requested backend is not available."""

    def __init__(
        self,
        backend_name: str,
        reason: str | None = None,
    ):
        super().__init__(
            message=f"Backend '{backend_name}' is not available"
            + (f": {reason}" if reason else ""),
            code=AutomationErrorCode.BACKEND_NOT_AVAILABLE,
            details={"backend_name": backend_name, "reason": reason},
            recovery_hint=(
                "Ensure the required dependencies are installed:\n"
                "  pip install mahavishnu[automation]\n"
                "On macOS, PyXA is the recommended backend."
            ),
        )


class NoBackendAvailableError(AutomationError):
    """Raised when no automation backend is available."""

    def __init__(self, platform: str | None = None):
        super().__init__(
            message="No automation backend available"
            + (f" for platform '{platform}'" if platform else ""),
            code=AutomationErrorCode.NO_BACKEND_AVAILABLE,
            details={"platform": platform},
            recovery_hint=(
                "Install automation dependencies:\n"
                "  pip install mahavishnu[automation]\n\n"
                "Supported platforms:\n"
                "- macOS: PyXA (recommended), ATOMac, PyAutoGUI\n"
                "- Windows/Linux: PyAutoGUI"
            ),
        )


class ApplicationNotFoundError(AutomationError):
    """Raised when an application cannot be found."""

    def __init__(
        self,
        bundle_id: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(
            message=f"Application '{bundle_id}' not found",
            code=AutomationErrorCode.APP_NOT_FOUND,
            details={"bundle_id": bundle_id, **(details or {})},
            recovery_hint=(
                "Verify the bundle identifier is correct.\n"
                "Common bundle IDs:\n"
                "- com.apple.finder (Finder)\n"
                "- com.apple.Safari (Safari)\n"
                "- com.apple.Terminal (Terminal)\n"
                "Use: mdfind 'kMDItemCFBundleIdentifier == \"*\"' to list all apps."
            ),
        )


class WindowNotFoundError(AutomationError):
    """Raised when a window cannot be found."""

    def __init__(
        self,
        window_id: str,
        bundle_id: str | None = None,
    ):
        super().__init__(
            message=f"Window '{window_id}' not found",
            code=AutomationErrorCode.WINDOW_NOT_FOUND,
            details={"window_id": window_id, "bundle_id": bundle_id},
            recovery_hint=(
                "The window may have been closed. "
                "Use list_windows() to get current window IDs."
            ),
        )


class MenuNotFoundError(AutomationError):
    """Raised when a menu item cannot be found."""

    def __init__(
        self,
        menu_path: list[str],
        bundle_id: str | None = None,
    ):
        super().__init__(
            message=f"Menu item not found: {' > '.join(menu_path)}",
            code=AutomationErrorCode.MENU_NOT_FOUND,
            details={"menu_path": menu_path, "bundle_id": bundle_id},
            recovery_hint=(
                "Verify the menu path is correct. "
                "Menu items are case-sensitive and must match exactly."
            ),
        )


class InputValidationError(AutomationError):
    """Raised when input validation fails."""

    def __init__(
        self,
        message: str,
        field: str | None = None,
        value: Any | None = None,
    ):
        super().__init__(
            message=message,
            code=AutomationErrorCode.INPUT_VALIDATION_FAILED,
            details={"field": field, "value": value},
            recovery_hint="Check that the input parameters are valid.",
        )


class InvalidCoordinatesError(AutomationError):
    """Raised when coordinates are invalid."""

    def __init__(
        self,
        x: int,
        y: int,
        screen_bounds: tuple[int, int] | None = None,
    ):
        super().__init__(
            message=f"Invalid coordinates ({x}, {y})",
            code=AutomationErrorCode.INVALID_COORDINATES,
            details={"x": x, "y": y, "screen_bounds": screen_bounds},
            recovery_hint=(
                f"Coordinates must be within screen bounds: {screen_bounds}"
                if screen_bounds
                else "Coordinates must be positive integers within screen bounds."
            ),
        )


class ScreenshotError(AutomationError):
    """Raised when screenshot capture fails."""

    def __init__(
        self,
        message: str = "Failed to capture screenshot",
        region: tuple[int, int, int, int] | None = None,
    ):
        super().__init__(
            message=message,
            code=AutomationErrorCode.SCREENSHOT_FAILED,
            details={"region": region},
            recovery_hint=(
                "Ensure screen recording permissions are granted. "
                "If specifying a region, verify coordinates are valid."
            ),
        )


class RateLimitedError(AutomationError):
    """Raised when rate limit is exceeded."""

    def __init__(
        self,
        retry_after: float,
        operation: str | None = None,
    ):
        super().__init__(
            message=f"Rate limit exceeded. Retry after {retry_after:.1f}s",
            code=AutomationErrorCode.RATE_LIMITED,
            details={"retry_after": retry_after, "operation": operation},
            recovery_hint=f"Wait {retry_after:.1f} seconds before retrying.",
        )
