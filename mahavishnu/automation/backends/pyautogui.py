"""PyAutoGUI backend for cross-platform desktop automation.

PyAutoGUI provides cross-platform input automation:
- Mouse movement and clicking
- Keyboard input
- Screenshot capture
- Image finding

Limitations:
- Coordinate-based (no application/window awareness)
- Less reliable than native backends
- Use as fallback only

Requirements:
- pyautogui library (pip install pyautogui)
- Pillow for screenshots
- mss for fast screenshots (optional)
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from logging import getLogger
from typing import Any

from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.base import (
    ApplicationInfo,
    MenuInfo,
    ScreenInfo,
    WindowInfo,
)
from mahavishnu.automation.errors import (
    AutomationError,
    ScreenshotError,
)

logger = getLogger(__name__)


class PyAutoGUIBackend(DesktopAutomationBackend):
    """PyAutoGUI-based automation backend for cross-platform support.

    This backend provides basic automation capabilities on any platform
    but lacks application and window awareness. It's intended as a
    fallback when native backends are not available.

    Limitations:
    - No application management (launch, quit, activate)
    - No window management
    - No menu interaction
    - No UI element access
    - Coordinate-based only

    Usage:
        backend = PyAutoGUIBackend()
        if backend.is_available():
            await backend.type_text("Hello World")
            await backend.click(100, 100)
    """

    def __init__(self) -> None:
        """Initialize the PyAutoGUI backend."""
        super().__init__()
        self._pyautogui: Any = None
        self._executor = ThreadPoolExecutor(max_workers=1)

    @staticmethod
    def is_available() -> bool:
        """Check if PyAutoGUI is available."""
        try:
            import pyautogui  # noqa: F401

            return True
        except ImportError:
            return False

    @property
    def backend_name(self) -> str:
        """Get backend name."""
        return "pyautogui"

    def _get_pyautogui(self) -> Any:
        """Get or import pyautogui module."""
        if self._pyautogui is None:
            try:
                import pyautogui

                self._pyautogui = pyautogui

                # Configure safety
                pyautogui.FAILSAFE = True
                pyautogui.PAUSE = 0.05  # Small pause between actions
            except ImportError as e:
                raise AutomationError(
                    "PyAutoGUI not installed. Install with: pip install pyautogui",
                    details={"error": str(e)},
                ) from e
        return self._pyautogui

    async def _run_sync(self, func: Any, *args: Any) -> Any:
        """Run a synchronous function in the executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    # =========================================================================
    # Application Operations (Not Supported)
    # =========================================================================

    async def launch_application(self, bundle_id: str) -> ApplicationInfo:
        """Launch an application. Not supported by PyAutoGUI."""
        raise AutomationError(
            "Application management not supported by PyAutoGUI backend",
            details={"operation": "launch_application", "bundle_id": bundle_id},
        )

    async def get_application(self, bundle_id: str) -> ApplicationInfo | None:
        """Get application info. Not supported by PyAutoGUI."""
        return None

    async def list_applications(self) -> list[ApplicationInfo]:
        """List applications. Not supported by PyAutoGUI."""
        return []

    async def quit_application(self, bundle_id: str, force: bool = False) -> bool:
        """Quit an application. Not supported by PyAutoGUI."""
        raise AutomationError(
            "Application management not supported by PyAutoGUI backend",
            details={"operation": "quit_application", "bundle_id": bundle_id},
        )

    async def activate_application(self, bundle_id: str) -> bool:
        """Activate an application. Not supported by PyAutoGUI."""
        raise AutomationError(
            "Application management not supported by PyAutoGUI backend",
            details={"operation": "activate_application", "bundle_id": bundle_id},
        )

    async def get_active_application(self) -> ApplicationInfo | None:
        """Get active application. Not supported by PyAutoGUI."""
        return None

    # =========================================================================
    # Window Operations (Not Supported)
    # =========================================================================

    async def get_windows(self, bundle_id: str) -> list[WindowInfo]:
        """Get windows. Not supported by PyAutoGUI."""
        return []

    async def activate_window(self, window_id: str) -> bool:
        """Activate window. Not supported by PyAutoGUI."""
        raise AutomationError(
            "Window management not supported by PyAutoGUI backend",
            details={"operation": "activate_window", "window_id": window_id},
        )

    async def resize_window(self, window_id: str, width: int, height: int) -> bool:
        """Resize window. Not supported by PyAutoGUI."""
        raise AutomationError(
            "Window management not supported by PyAutoGUI backend",
            details={"operation": "resize_window", "window_id": window_id},
        )

    async def move_window(self, window_id: str, x: int, y: int) -> bool:
        """Move window. Not supported by PyAutoGUI."""
        raise AutomationError(
            "Window management not supported by PyAutoGUI backend",
            details={"operation": "move_window", "window_id": window_id},
        )

    async def close_window(self, window_id: str) -> bool:
        """Close window. Not supported by PyAutoGUI."""
        raise AutomationError(
            "Window management not supported by PyAutoGUI backend",
            details={"operation": "close_window", "window_id": window_id},
        )

    # =========================================================================
    # Menu Operations (Not Supported)
    # =========================================================================

    async def click_menu_item(self, bundle_id: str, menu_path: list[str]) -> bool:
        """Click menu item. Not supported by PyAutoGUI."""
        raise AutomationError(
            "Menu interaction not supported by PyAutoGUI backend",
            details={"operation": "click_menu_item", "bundle_id": bundle_id},
        )

    async def list_menus(self, bundle_id: str) -> list[MenuInfo]:
        """List menus. Not supported by PyAutoGUI."""
        return []

    # =========================================================================
    # Input Operations (Supported)
    # =========================================================================

    async def type_text(self, text: str, interval: float = 0.05) -> bool:
        """Type text at the current cursor position."""
        pyautogui = self._get_pyautogui()

        def _type() -> bool:
            try:
                pyautogui.write(text, interval=interval)
                return True
            except Exception as e:
                logger.error(f"Failed to type text: {e}")
                return False

        return await self._run_sync(_type)

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> bool:
        """Press a key with optional modifiers."""
        pyautogui = self._get_pyautogui()

        def _press() -> bool:
            try:
                # Normalize key name
                key_normalized = self._normalize_key(key)

                if modifiers:
                    # Press with hotkey
                    hotkey = modifiers + [key_normalized]
                    pyautogui.hotkey(*hotkey)
                else:
                    pyautogui.press(key_normalized)

                return True
            except Exception as e:
                logger.error(f"Failed to press key {key}: {e}")
                return False

        return await self._run_sync(_press)

    def _normalize_key(self, key: str) -> str:
        """Normalize key name for PyAutoGUI."""
        key_map = {
            "return": "enter",
            "backspace": "backspace",
            "escape": "escape",
            "esc": "escape",
            "pageup": "pageup",
            "pagedown": "pagedown",
            "capslock": "capslock",
        }

        key_lower = key.lower()
        if key_lower in key_map:
            return key_map[key_lower]

        # Single character - return as is
        if len(key) == 1:
            return key

        # F keys
        if key_lower.startswith("f") and key_lower[1:].isdigit():
            return key_lower

        return key_lower

    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
        """Click at coordinates."""
        pyautogui = self._get_pyautogui()

        def _click() -> bool:
            try:
                pyautogui.click(x, y, clicks=clicks, button=button)
                return True
            except Exception as e:
                logger.error(f"Failed to click at ({x}, {y}): {e}")
                return False

        return await self._run_sync(_click)

    async def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
        button: str = "left",
    ) -> bool:
        """Drag from one point to another."""
        pyautogui = self._get_pyautogui()

        def _drag() -> bool:
            try:
                pyautogui.moveTo(start_x, start_y)
                pyautogui.drag(
                    end_x - start_x,
                    end_y - start_y,
                    duration=duration,
                    button=button,
                )
                return True
            except Exception as e:
                logger.error(f"Failed to drag: {e}")
                return False

        return await self._run_sync(_drag)

    async def scroll(self, x: int, y: int, dx: int, dy: int) -> bool:
        """Scroll at coordinates."""
        pyautogui = self._get_pyautogui()

        def _scroll() -> bool:
            try:
                pyautogui.moveTo(x, y)
                pyautogui.scroll(dy, x, y)
                # Horizontal scroll not directly supported
                return True
            except Exception as e:
                logger.error(f"Failed to scroll: {e}")
                return False

        return await self._run_sync(_scroll)

    # =========================================================================
    # Screenshot Operations (Supported)
    # =========================================================================

    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes:
        """Capture a screenshot."""
        pyautogui = self._get_pyautogui()

        def _capture() -> bytes:
            try:
                # Try mss first (faster)
                try:
                    import mss

                    with mss.mss() as sct:
                        if region:
                            x, y, width, height = region
                            monitor = {"left": x, "top": y, "width": width, "height": height}
                        else:
                            monitor = sct.monitors[1]  # Primary monitor

                        screenshot = sct.grab(monitor)
                        img = self._mss_to_pil(screenshot)
                except ImportError:
                    # Fall back to pyautogui
                    if region:
                        x, y, width, height = region
                        img = pyautogui.screenshot(region=(x, y, width, height))
                    else:
                        img = pyautogui.screenshot()

                # Convert to PNG bytes
                buffer = BytesIO()
                img.save(buffer, format="PNG")
                return buffer.getvalue()
            except Exception as e:
                raise ScreenshotError(
                    f"Failed to capture screenshot: {e}",
                    region=region,
                ) from e

        return await self._run_sync(_capture)

    def _mss_to_pil(self, screenshot: Any) -> Any:
        """Convert mss screenshot to PIL Image."""
        from PIL import Image

        return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

    # =========================================================================
    # Screen Operations (Supported)
    # =========================================================================

    async def list_screens(self) -> list[ScreenInfo]:
        """List all connected displays."""
        pyautogui = self._get_pyautogui()

        def _list() -> list[ScreenInfo]:
            try:
                screens = []

                # Get screen info from pyautogui
                # PyAutoGUI provides screen size
                size = pyautogui.size()

                # Primary screen
                screens.append(
                    ScreenInfo(
                        id=0,
                        name="Primary Display",
                        position=(0, 0),
                        size=(size.width, size.height),
                        scale=1.0,
                        primary=True,
                    )
                )

                # Try to get additional screens with mss
                try:
                    import mss

                    with mss.mss() as sct:
                        for i, monitor in enumerate(sct.monitors[1:]):  # Skip all-in-one
                            if i == 0:
                                # Update primary screen info
                                screens[0] = ScreenInfo(
                                    id=0,
                                    name="Primary Display",
                                    position=(monitor["left"], monitor["top"]),
                                    size=(monitor["width"], monitor["height"]),
                                    scale=1.0,
                                    primary=True,
                                )
                            else:
                                screens.append(
                                    ScreenInfo(
                                        id=i,
                                        name=f"Display {i + 1}",
                                        position=(monitor["left"], monitor["top"]),
                                        size=(monitor["width"], monitor["height"]),
                                        scale=1.0,
                                        primary=False,
                                    )
                                )
                except ImportError:
                    pass

                return screens
            except Exception as e:
                logger.error(f"Failed to list screens: {e}")
                return []

        return await self._run_sync(_list)

    # =========================================================================
    # Additional PyAutoGUI-specific Methods
    # =========================================================================

    async def move_to(self, x: int, y: int, duration: float = 0.0) -> bool:
        """Move mouse to coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
            duration: Duration of movement in seconds.

        Returns:
            True if successful.
        """
        pyautogui = self._get_pyautogui()

        def _move() -> bool:
            try:
                pyautogui.moveTo(x, y, duration=duration)
                return True
            except Exception as e:
                logger.error(f"Failed to move to ({x}, {y}): {e}")
                return False

        return await self._run_sync(_move)

    async def get_mouse_position(self) -> tuple[int, int]:
        """Get current mouse position.

        Returns:
            Tuple of (x, y) coordinates.
        """
        pyautogui = self._get_pyautogui()

        def _get() -> tuple[int, int]:
            pos = pyautogui.position()
            return (pos.x, pos.y)

        return await self._run_sync(_get)

    async def locate_on_screen(
        self,
        image_path: str,
        confidence: float = 0.9,
    ) -> tuple[int, int, int, int] | None:
        """Locate an image on screen.

        Args:
            image_path: Path to image file.
            confidence: Matching confidence (0.0 to 1.0).

        Returns:
            Tuple of (x, y, width, height) if found, None otherwise.
        """
        pyautogui = self._get_pyautogui()

        def _locate() -> tuple[int, int, int, int] | None:
            try:
                location = pyautogui.locateOnScreen(image_path, confidence=confidence)
                if location:
                    return (location.left, location.top, location.width, location.height)
                return None
            except Exception as e:
                logger.error(f"Failed to locate image: {e}")
                return None

        return await self._run_sync(_locate)

    async def locate_center_on_screen(
        self,
        image_path: str,
        confidence: float = 0.9,
    ) -> tuple[int, int] | None:
        """Locate center of an image on screen.

        Args:
            image_path: Path to image file.
            confidence: Matching confidence.

        Returns:
            Tuple of (x, y) for center position if found.
        """
        pyautogui = self._get_pyautogui()

        def _locate() -> tuple[int, int] | None:
            try:
                location = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
                if location:
                    return (location.x, location.y)
                return None
            except Exception as e:
                logger.error(f"Failed to locate image center: {e}")
                return None

        return await self._run_sync(_locate)

    async def alert(self, text: str, title: str = "Alert") -> None:
        """Show an alert dialog.

        Args:
            text: Alert text.
            title: Alert title.
        """
        pyautogui = self._get_pyautogui()

        def _alert() -> None:
            pyautogui.alert(text=text, title=title)

        await self._run_sync(_alert)

    async def confirm(self, text: str, title: str = "Confirm") -> bool:
        """Show a confirmation dialog.

        Args:
            text: Confirmation text.
            title: Dialog title.

        Returns:
            True if confirmed, False otherwise.
        """
        pyautogui = self._get_pyautogui()

        def _confirm() -> bool:
            return pyautogui.confirm(text=text, title=title) == "OK"

        return await self._run_sync(_confirm)

    async def prompt(
        self,
        text: str,
        title: str = "Prompt",
        default: str = "",
    ) -> str | None:
        """Show a prompt dialog.

        Args:
            text: Prompt text.
            title: Dialog title.
            default: Default value.

        Returns:
            User input or None if cancelled.
        """
        pyautogui = self._get_pyautogui()

        def _prompt() -> str | None:
            return pyautogui.prompt(text=text, title=title, default=default)

        return await self._run_sync(_prompt)

    async def close(self) -> None:
        """Clean up backend resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._pyautogui = None
