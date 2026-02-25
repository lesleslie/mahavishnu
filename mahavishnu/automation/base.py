"""Base data classes for desktop automation.

Provides dataclasses for representing applications, windows, and UI elements.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class WindowState(StrEnum):
    """Window state enumeration."""

    NORMAL = "normal"
    MINIMIZED = "minimized"
    MAXIMIZED = "maximized"
    FULLSCREEN = "fullscreen"
    HIDDEN = "hidden"


class MouseButton(StrEnum):
    """Mouse button enumeration."""

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


class KeyModifier(StrEnum):
    """Key modifier enumeration for keyboard shortcuts."""

    CMD = "cmd"
    COMMAND = "command"
    SHIFT = "shift"
    OPTION = "option"
    ALT = "alt"
    CONTROL = "control"
    CTRL = "ctrl"
    FN = "fn"


@dataclass
class WindowInfo:
    """Information about a window.

    Attributes:
        id: Unique window identifier (backend-specific)
        title: Window title
        position: Window position as (x, y) tuple
        size: Window size as (width, height) tuple
        state: Current window state
        focused: Whether window is currently focused
        bundle_id: Bundle ID of owning application
        window_number: Window number within application (for accessibility)
    """

    id: str
    title: str
    position: tuple[int, int]
    size: tuple[int, int]
    state: WindowState = WindowState.NORMAL
    focused: bool = False
    bundle_id: str | None = None
    window_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "title": self.title,
            "position": self.position,
            "size": self.size,
            "state": self.state.value,
            "focused": self.focused,
            "bundle_id": self.bundle_id,
            "window_number": self.window_number,
        }


@dataclass
class ApplicationInfo:
    """Information about a running application.

    Attributes:
        bundle_id: Application bundle identifier (e.g., com.apple.finder)
        name: Display name of the application
        pid: Process ID
        frontmost: Whether this is the active application
        windows: List of application windows
        url: URL to application bundle (macOS)
        version: Application version string
    """

    bundle_id: str
    name: str
    pid: int
    frontmost: bool = False
    windows: list[WindowInfo] = field(default_factory=list)
    url: str | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "bundle_id": self.bundle_id,
            "name": self.name,
            "pid": self.pid,
            "frontmost": self.frontmost,
            "windows": [w.to_dict() for w in self.windows],
            "url": self.url,
            "version": self.version,
        }


@dataclass
class MenuInfo:
    """Information about a menu or menu item.

    Attributes:
        name: Menu item name/title
        path: Full path to menu item (e.g., ["File", "Save"])
        enabled: Whether the menu item is enabled
        shortcut: Keyboard shortcut if any (e.g., "Cmd+S")
        children: Sub-menu items
    """

    name: str
    path: list[str] = field(default_factory=list)
    enabled: bool = True
    shortcut: str | None = None
    children: list["MenuInfo"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "path": self.path,
            "enabled": self.enabled,
            "shortcut": self.shortcut,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class UIElement:
    """Information about a UI element for accessibility.

    Attributes:
        role: Accessibility role (e.g., "button", "textfield", "checkbox")
        title: Element title/label
        value: Current value (for text fields, checkboxes, etc.)
        position: Element position as (x, y)
        size: Element size as (width, height)
        enabled: Whether element is interactive
        focused: Whether element has focus
        identifier: Accessibility identifier
        description: Accessibility description
    """

    role: str
    title: str | None = None
    value: Any | None = None
    position: tuple[int, int] | None = None
    size: tuple[int, int] | None = None
    enabled: bool = True
    focused: bool = False
    identifier: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "role": self.role,
            "title": self.title,
            "value": self.value,
            "position": self.position,
            "size": self.size,
            "enabled": self.enabled,
            "focused": self.focused,
            "identifier": self.identifier,
            "description": self.description,
        }


@dataclass
class ScreenInfo:
    """Information about a display screen.

    Attributes:
        id: Screen identifier
        name: Display name
        position: Screen position in virtual desktop (x, y)
        size: Screen resolution (width, height)
        scale: Retina scaling factor (1.0 for standard, 2.0 for Retina)
        primary: Whether this is the primary display
    """

    id: int
    name: str
    position: tuple[int, int]
    size: tuple[int, int]
    scale: float = 1.0
    primary: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "size": self.size,
            "scale": self.scale,
            "primary": self.primary,
        }


@dataclass
class AutomationContext:
    """Context for automation operations.

    Tracks the current state of automation for multi-step workflows.

    Attributes:
        active_bundle_id: Currently active application
        active_window_id: Currently active window
        last_operation: Timestamp of last operation
        operation_count: Total operations performed
        dry_run: Whether operations should be simulated
        metadata: Additional context metadata
    """

    active_bundle_id: str | None = None
    active_window_id: str | None = None
    last_operation: datetime | None = None
    operation_count: int = 0
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_operation(self) -> None:
        """Record that an operation was performed."""
        self.last_operation = datetime.now()
        self.operation_count += 1
