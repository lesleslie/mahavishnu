"""Abstract base class for desktop automation backends.

Defines the interface that all automation backends must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import ParamSpec, TypeVar

from mahavishnu.automation.base import ApplicationInfo, MenuInfo, ScreenInfo, UIElement, WindowInfo

P = ParamSpec("P")
R = TypeVar("R")


class DesktopAutomationBackend(ABC):
    """Abstract interface for desktop automation backends.

    All automation backends must implement this interface to provide
    consistent behavior across different platforms and automation libraries.

    Backends should be designed with these principles:
    1. **Safety First**: Never perform destructive operations without explicit consent
    2. **Graceful Degradation**: Report unsupported operations clearly
    3. **Async by Default**: All operations should be async for non-blocking use
    4. **Input Validation**: Validate all inputs before performing operations

    Usage:
        class MyBackend(DesktopAutomationBackend):
            @staticmethod
            def is_available() -> bool:
                return True

            @property
            def backend_name(self) -> str:
                return "my_backend"

            # Implement all abstract methods...
    """

    def __init__(self) -> None:
        """Initialize the backend."""
        self._executor: ThreadPoolExecutor | None = None

    def _get_executor(self) -> ThreadPoolExecutor:
        """Get or create the thread pool executor for sync-to-async bridging."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1)
        return self._executor

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        """Check if this backend is available on the current platform.

        This should check for required dependencies and platform compatibility.

        Returns:
            True if the backend can be used on this system.
        """
        pass

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Get the backend name for logging and debugging.

        Returns:
            Backend identifier string.
        """
        pass

    # =========================================================================
    # Application Operations
    # =========================================================================

    @abstractmethod
    async def launch_application(self, bundle_id: str) -> ApplicationInfo:
        """Launch an application by bundle identifier.

        Args:
            bundle_id: Application bundle identifier (e.g., com.apple.finder).

        Returns:
            ApplicationInfo for the launched application.

        Raises:
            ApplicationNotFoundError: If the application cannot be found.
            AutomationError: If the application fails to launch.
        """
        pass

    @abstractmethod
    async def get_application(self, bundle_id: str) -> ApplicationInfo | None:
        """Get information about a running application.

        Args:
            bundle_id: Application bundle identifier.

        Returns:
            ApplicationInfo if the application is running, None otherwise.
        """
        pass

    @abstractmethod
    async def list_applications(self) -> list[ApplicationInfo]:
        """List all running applications.

        Returns:
            List of ApplicationInfo for all running applications.
        """
        pass

    @abstractmethod
    async def quit_application(self, bundle_id: str, force: bool = False) -> bool:
        """Quit an application.

        Args:
            bundle_id: Application bundle identifier.
            force: Force quit if normal quit fails.

        Returns:
            True if the application was quit successfully.

        Raises:
            ApplicationNotFoundError: If the application is not running.
        """
        pass

    @abstractmethod
    async def activate_application(self, bundle_id: str) -> bool:
        """Activate (bring to front) an application.

        Args:
            bundle_id: Application bundle identifier.

        Returns:
            True if the application was activated successfully.
        """
        pass

    @abstractmethod
    async def get_active_application(self) -> ApplicationInfo | None:
        """Get the currently active (frontmost) application.

        Returns:
            ApplicationInfo for the active application, or None if no app is active.
        """
        pass

    # =========================================================================
    # Window Operations
    # =========================================================================

    @abstractmethod
    async def get_windows(self, bundle_id: str) -> list[WindowInfo]:
        """Get all windows for an application.

        Args:
            bundle_id: Application bundle identifier.

        Returns:
            List of WindowInfo for the application's windows.
        """
        pass

    @abstractmethod
    async def activate_window(self, window_id: str) -> bool:
        """Activate (bring to front) a window.

        Args:
            window_id: Window identifier (backend-specific).

        Returns:
            True if the window was activated successfully.
        """
        pass

    @abstractmethod
    async def resize_window(self, window_id: str, width: int, height: int) -> bool:
        """Resize a window.

        Args:
            window_id: Window identifier.
            width: New width in pixels.
            height: New height in pixels.

        Returns:
            True if the window was resized successfully.
        """
        pass

    @abstractmethod
    async def move_window(self, window_id: str, x: int, y: int) -> bool:
        """Move a window to a new position.

        Args:
            window_id: Window identifier.
            x: New X position.
            y: New Y position.

        Returns:
            True if the window was moved successfully.
        """
        pass

    @abstractmethod
    async def close_window(self, window_id: str) -> bool:
        """Close a window.

        Args:
            window_id: Window identifier.

        Returns:
            True if the window was closed successfully.
        """
        pass

    # =========================================================================
    # Menu Operations
    # =========================================================================

    @abstractmethod
    async def click_menu_item(self, bundle_id: str, menu_path: list[str]) -> bool:
        """Navigate menu and click an item.

        Args:
            bundle_id: Application bundle identifier.
            menu_path: Path to menu item (e.g., ["File", "Save"]).

        Returns:
            True if the menu item was clicked successfully.

        Raises:
            MenuNotFoundError: If the menu item cannot be found.
        """
        pass

    @abstractmethod
    async def list_menus(self, bundle_id: str) -> list[MenuInfo]:
        """List all menus for an application.

        Args:
            bundle_id: Application bundle identifier.

        Returns:
            List of MenuInfo for the application's menus.
        """
        pass

    # =========================================================================
    # Clipboard Operations
    # =========================================================================

    async def get_clipboard(self) -> str:
        """Get clipboard content.

        Returns:
            Clipboard text content.

        Raises:
            NotImplementedError: If not supported by this backend.
        """
        raise NotImplementedError(f"Clipboard access not supported by {self.backend_name}")

    async def set_clipboard(self, text: str) -> bool:
        """Set clipboard content.

        Args:
            text: Text to set.

        Returns:
            True if successful.

        Raises:
            NotImplementedError: If not supported by this backend.
        """
        raise NotImplementedError(f"Clipboard access not supported by {self.backend_name}")

    # =========================================================================
    # Input Operations
    # =========================================================================

    @abstractmethod
    async def type_text(self, text: str, interval: float = 0.05) -> bool:
        """Type text at the current cursor position.

        Args:
            text: Text to type.
            interval: Delay between keystrokes in seconds.

        Returns:
            True if the text was typed successfully.
        """
        pass

    @abstractmethod
    async def press_key(self, key: str, modifiers: list[str] | None = None) -> bool:
        """Press a key with optional modifiers.

        Args:
            key: Key to press (e.g., "return", "a", "f1").
            modifiers: List of modifiers (e.g., ["cmd", "shift"]).

        Returns:
            True if the key was pressed successfully.
        """
        pass

    @abstractmethod
    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
        """Click at coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
            button: Mouse button ("left", "right", "middle").
            clicks: Number of clicks (1, 2, or 3).

        Returns:
            True if the click was performed successfully.
        """
        pass

    @abstractmethod
    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
        button: str = "left",
    ) -> bool:
        """Drag from one point to another.

        Args:
            start_x: Starting X coordinate.
            start_y: Starting Y coordinate.
            end_x: Ending X coordinate.
            end_y: Ending Y coordinate.
            duration: Duration of drag in seconds.
            button: Mouse button to use.

        Returns:
            True if the drag was performed successfully.
        """
        pass

    @abstractmethod
    async def scroll(self, x: int, y: int, dx: int, dy: int) -> bool:
        """Scroll at coordinates.

        Args:
            x: X coordinate to scroll at.
            y: Y coordinate to scroll at.
            dx: Horizontal scroll amount.
            dy: Vertical scroll amount (negative = down).

        Returns:
            True if the scroll was performed successfully.
        """
        pass

    # =========================================================================
    # Screenshot Operations
    # =========================================================================

    @abstractmethod
    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes:
        """Capture a screenshot.

        Args:
            region: Optional region as (x, y, width, height). If None,
                    captures the entire screen.

        Returns:
            Screenshot as PNG bytes.

        Raises:
            ScreenshotError: If the screenshot fails.
        """
        pass

    # =========================================================================
    # Screen Operations
    # =========================================================================

    @abstractmethod
    async def list_screens(self) -> list[ScreenInfo]:
        """List all connected displays.

        Returns:
            List of ScreenInfo for each display.
        """
        pass

    # =========================================================================
    # UI Element Operations (Optional)
    # =========================================================================

    async def get_ui_elements(
        self,
        bundle_id: str,
        window_id: str | None = None,
    ) -> list[UIElement]:
        """Get UI elements for an application or window.

        This is an optional method that may not be supported by all backends.

        Args:
            bundle_id: Application bundle identifier.
            window_id: Optional window identifier.

        Returns:
            List of UIElement for the application/window.

        Raises:
            NotImplementedError: If not supported by this backend.
        """
        raise NotImplementedError(f"UI element access not supported by {self.backend_name}")

    async def click_ui_element(
        self,
        bundle_id: str,
        element_identifier: str,
    ) -> bool:
        """Click a UI element by identifier.

        This is an optional method that may not be supported by all backends.

        Args:
            bundle_id: Application bundle identifier.
            element_identifier: UI element identifier (backend-specific).

        Returns:
            True if the element was clicked successfully.

        Raises:
            NotImplementedError: If not supported by this backend.
        """
        raise NotImplementedError(f"UI element clicking not supported by {self.backend_name}")

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def supports_operation(self, operation: str) -> bool:
        """Check if the backend supports a specific operation.

        Args:
            operation: Operation name (e.g., "launch_application").

        Returns:
            True if the operation is supported.
        """
        method = getattr(self, operation, None)
        if method is None:
            return False

        # Check if it's implemented (not just raising NotImplementedError)
        # This is a heuristic - the method exists but may not be functional
        return callable(method)

    async def close(self) -> None:
        """Clean up backend resources.

        Called when the backend is no longer needed.
        """
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.backend_name}>"
