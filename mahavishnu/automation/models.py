"""Pydantic models for desktop automation operations.

Provides validated models for all automation operations with comprehensive
input validation and serialization.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from mahavishnu.automation.base import KeyModifier, MouseButton


class OperationType(StrEnum):
    """Types of automation operations."""

    LAUNCH_APP = "launch_app"
    QUIT_APP = "quit_app"
    ACTIVATE_APP = "activate_app"
    LIST_APPS = "list_apps"
    LIST_WINDOWS = "list_windows"
    ACTIVATE_WINDOW = "activate_window"
    RESIZE_WINDOW = "resize_window"
    MOVE_WINDOW = "move_window"
    CLOSE_WINDOW = "close_window"
    CLICK_MENU = "click_menu"
    LIST_MENUS = "list_menus"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    CLICK = "click"
    DRAG = "drag"
    SCROLL = "scroll"
    SCREENSHOT = "screenshot"
    SCREENSHOT_REGION = "screenshot_region"
    GET_ACTIVE_APP = "get_active_app"
    CHECK_PERMISSIONS = "check_permissions"


class OperationStatus(StrEnum):
    """Status of an automation operation."""

    SUCCESS = "success"
    FAILED = "failed"
    DRY_RUN = "dry_run"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class AutomationOperation(BaseModel):
    """Base model for all automation operations.

    All operations support dry_run mode for validation without execution.
    """

    operation_type: OperationType
    dry_run: bool = False
    timeout: float = Field(default=30.0, ge=1.0, le=300.0)

    model_config = {
        "extra": "forbid",
        "use_enum_values": True,
    }


class ApplicationOperation(AutomationOperation):
    """Base for application-related operations."""

    bundle_id: str = Field(..., min_length=1, max_length=255)

    @field_validator("bundle_id")
    @classmethod
    def validate_bundle_id(cls, v: str) -> str:
        """Validate bundle ID format."""
        # Bundle IDs should be reverse domain notation
        if not v or v.isspace():
            raise ValueError("Bundle ID cannot be empty")
        # Basic format check (allow wildcards for testing)
        if "*" not in v and "." not in v:
            raise ValueError(
                "Bundle ID should be in reverse domain format (e.g., com.apple.finder)"
            )
        return v.strip()


class LaunchAppOperation(ApplicationOperation):
    """Launch an application by bundle ID."""

    operation_type: OperationType = OperationType.LAUNCH_APP
    activate: bool = True  # Bring to front after launch
    wait_for_launch: bool = True
    launch_timeout: float = Field(default=10.0, ge=1.0, le=60.0)


class QuitAppOperation(ApplicationOperation):
    """Quit an application by bundle ID."""

    operation_type: OperationType = OperationType.QUIT_APP
    force: bool = False  # Force quit if normal quit fails
    save_documents: bool = True  # Prompt to save if needed


class ActivateAppOperation(ApplicationOperation):
    """Activate (bring to front) an application."""

    operation_type: OperationType = OperationType.ACTIVATE_APP


class ListAppsOperation(AutomationOperation):
    """List all running applications."""

    operation_type: OperationType = OperationType.LIST_APPS
    include_windows: bool = False  # Include window information


class WindowOperation(AutomationOperation):
    """Base for window-related operations."""

    window_id: str = Field(..., min_length=1)
    bundle_id: str | None = None  # Optional, for validation


class ListWindowsOperation(ApplicationOperation):
    """List windows for an application."""

    operation_type: OperationType = OperationType.LIST_WINDOWS


class ActivateWindowOperation(WindowOperation):
    """Activate (bring to front) a window."""

    operation_type: OperationType = OperationType.ACTIVATE_WINDOW


class ResizeWindowOperation(WindowOperation):
    """Resize a window."""

    operation_type: OperationType = OperationType.RESIZE_WINDOW
    width: int = Field(..., ge=100, le=8192)
    height: int = Field(..., ge=100, le=8192)


class MoveWindowOperation(WindowOperation):
    """Move a window."""

    operation_type: OperationType = OperationType.MOVE_WINDOW
    x: int = Field(..., ge=-8192, le=8192)
    y: int = Field(..., ge=-8192, le=8192)


class CloseWindowOperation(WindowOperation):
    """Close a window."""

    operation_type: OperationType = OperationType.CLOSE_WINDOW


class MenuClickOperation(ApplicationOperation):
    """Click a menu item."""

    operation_type: OperationType = OperationType.CLICK_MENU
    menu_path: list[str] = Field(..., min_length=1)

    @field_validator("menu_path")
    @classmethod
    def validate_menu_path(cls, v: list[str]) -> list[str]:
        """Validate menu path."""
        if not v:
            raise ValueError("Menu path cannot be empty")
        return [item.strip() for item in v if item.strip()]


class ListMenusOperation(ApplicationOperation):
    """List menus for an application."""

    operation_type: OperationType = OperationType.LIST_MENUS


class TypeTextOperation(AutomationOperation):
    """Type text at current cursor position."""

    operation_type: OperationType = OperationType.TYPE_TEXT
    text: str = Field(..., max_length=10000)  # Limit for safety
    interval: float = Field(default=0.05, ge=0.0, le=1.0)  # Delay between keystrokes

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        """Validate text doesn't contain null bytes."""
        if "\x00" in v:
            raise ValueError("Text cannot contain null bytes")
        return v


class KeyPressOperation(AutomationOperation):
    """Press a key with optional modifiers."""

    operation_type: OperationType = OperationType.PRESS_KEY
    key: str = Field(..., min_length=1, max_length=50)
    modifiers: list[KeyModifier] = Field(default_factory=list)

    @field_validator("key")
    @classmethod
    def validate_key(cls, v: str) -> str:
        """Validate key name."""
        # Common key names
        valid_keys = {
            "return",
            "enter",
            "tab",
            "space",
            "delete",
            "backspace",
            "escape",
            "esc",
            "up",
            "down",
            "left",
            "right",
            "home",
            "end",
            "pageup",
            "pagedown",
            "f1",
            "f2",
            "f3",
            "f4",
            "f5",
            "f6",
            "f7",
            "f8",
            "f9",
            "f10",
            "f11",
            "f12",
            "a",
            "b",
            "c",
            "d",
            "e",
            "f",
            "g",
            "h",
            "i",
            "j",
            "k",
            "l",
            "m",
            "n",
            "o",
            "p",
            "q",
            "r",
            "s",
            "t",
            "u",
            "v",
            "w",
            "x",
            "y",
            "z",
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
            "7",
            "8",
            "9",
            "-",
            "=",
            "[",
            "]",
            "\\",
            ";",
            "'",
            ",",
            ".",
            "/",
        }
        v_lower = v.lower()
        if v_lower not in valid_keys:
            # Allow single character keys
            if len(v) == 1:
                return v
            raise ValueError(f"Invalid key: {v}")
        return v_lower


class ClickOperation(AutomationOperation):
    """Click at coordinates."""

    operation_type: OperationType = OperationType.CLICK
    x: int = Field(..., ge=0, le=16384)
    y: int = Field(..., ge=0, le=16384)
    button: MouseButton = MouseButton.LEFT
    clicks: int = Field(default=1, ge=1, le=3)  # Single, double, or triple click


class DragOperation(AutomationOperation):
    """Drag from one point to another."""

    operation_type: OperationType = OperationType.DRAG
    start_x: int = Field(..., ge=0, le=16384)
    start_y: int = Field(..., ge=0, le=16384)
    end_x: int = Field(..., ge=0, le=16384)
    end_y: int = Field(..., ge=0, le=16384)
    duration: float = Field(default=0.5, ge=0.1, le=10.0)
    button: MouseButton = MouseButton.LEFT


class ScrollOperation(AutomationOperation):
    """Scroll at coordinates."""

    operation_type: OperationType = OperationType.SCROLL
    x: int = Field(..., ge=0, le=16384)
    y: int = Field(..., ge=0, le=16384)
    dx: int = Field(default=0, ge=-100, le=100)  # Horizontal scroll
    dy: int = Field(default=0, ge=-100, le=100)  # Vertical scroll (negative = down)


class ScreenshotOperation(AutomationOperation):
    """Capture screenshot."""

    operation_type: OperationType = OperationType.SCREENSHOT
    screen_id: int | None = None  # None = all screens
    format: str = Field(default="png", pattern="^(png|jpeg|webp)$")
    quality: int = Field(default=95, ge=1, le=100)  # For JPEG/WebP


class ScreenshotRegionOperation(ScreenshotOperation):
    """Capture screenshot of a region."""

    operation_type: OperationType = OperationType.SCREENSHOT_REGION
    region: tuple[int, int, int, int]  # (x, y, width, height)

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        """Validate region coordinates."""
        x, y, width, height = v
        if width <= 0 or height <= 0:
            raise ValueError("Region width and height must be positive")
        if x < 0 or y < 0:
            raise ValueError("Region coordinates must be non-negative")
        return v


class GetActiveAppOperation(AutomationOperation):
    """Get the currently active application."""

    operation_type: OperationType = OperationType.GET_ACTIVE_APP


class CheckPermissionsOperation(AutomationOperation):
    """Check automation permissions."""

    operation_type: OperationType = OperationType.CHECK_PERMISSIONS


class AutomationResult(BaseModel):
    """Result of an automation operation."""

    operation_type: OperationType
    status: OperationStatus
    data: dict[str, Any] | None = None
    error: str | None = None
    error_code: str | None = None
    duration_ms: float | None = None
    timestamp: datetime = Field(default_factory=datetime.now)
    dry_run: bool = False

    model_config = {
        "use_enum_values": True,
    }

    @classmethod
    def success(
        cls,
        operation_type: OperationType,
        data: dict[str, Any] | None = None,
        duration_ms: float | None = None,
        dry_run: bool = False,
    ) -> AutomationResult:
        """Create a successful result."""
        return cls(
            operation_type=operation_type,
            status=OperationStatus.SUCCESS if not dry_run else OperationStatus.DRY_RUN,
            data=data,
            duration_ms=duration_ms,
            dry_run=dry_run,
        )

    @classmethod
    def failure(
        cls,
        operation_type: OperationType,
        error: str,
        error_code: str | None = None,
        data: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> AutomationResult:
        """Create a failed result."""
        return cls(
            operation_type=operation_type,
            status=OperationStatus.FAILED,
            error=error,
            error_code=error_code,
            data=data,
            duration_ms=duration_ms,
        )


class AutomationConfig(BaseModel):
    """Configuration for automation manager."""

    enabled: bool = True
    default_backend: str = "auto"  # auto, pyxa, atomac, pyautogui
    dry_run_default: bool = False
    default_timeout: float = Field(default=30.0, ge=1.0, le=300.0)

    # Rate limiting
    max_operations_per_second: int = Field(default=10, ge=1, le=100)

    # Security
    require_accessibility_check: bool = True
    require_screen_recording_check: bool = True

    # Blocked apps (always blocked - security critical)
    blocked_apps: set[str] = Field(
        default_factory=lambda: {
            # System security
            "com.apple.securityd",
            "com.apple.KeychainAccess",
            "com.apple.systempreferences",
            "com.apple.Passwords",
            "com.apple.loginwindow",
            "com.apple.ScreenSaverEngine",
            # Password managers
            "com.agilebits.onepassword",
            "com.lastpass.LastPass",
            "com.bitwarden.desktop",
            # Financial apps
            "com.intuit.QuickBooks",
            "com.quicken.Quicken",
        }
    )

    # Blocked text patterns (never type these)
    blocked_text_patterns: set[str] = Field(
        default_factory=lambda: {
            "password",
            "api_key",
            "secret",
            "token",
            "credential",
            "private_key",
        }
    )

    # Allowed apps (if set, only these are allowed)
    allowed_apps: set[str] | None = None

    # Operations requiring confirmation
    require_confirmation_for: set[str] = Field(
        default_factory=lambda: {
            "quit_app",
        }
    )

    model_config = {
        "extra": "forbid",
    }
