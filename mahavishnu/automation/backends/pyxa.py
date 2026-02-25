"""PyXA backend for macOS desktop automation.

PyXA is the primary backend for macOS automation, providing:
- Application lifecycle control
- Window management
- Menu navigation
- UI element interaction

Requirements:
- macOS 12.0+
- PyXA library (pip install pyxa)
- Accessibility permissions
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from logging import getLogger
import sys
from typing import Any

from mahavishnu.automation.backends.base import DesktopAutomationBackend
from mahavishnu.automation.base import (
    ApplicationInfo,
    MenuInfo,
    ScreenInfo,
    UIElement,
    WindowInfo,
    WindowState,
)
from mahavishnu.automation.errors import (
    ApplicationNotFoundError,
    AutomationError,
    MenuNotFoundError,
    ScreenshotError,
)

logger = getLogger(__name__)


class PyXABackend(DesktopAutomationBackend):
    """PyXA-based automation backend for macOS.

    PyXA provides AppleScript-like Python interface for macOS automation.
    It works with any app that supports Accessibility APIs.

    Usage:
        backend = PyXABackend()
        if backend.is_available():
            await backend.launch_application("com.apple.finder")
    """

    def __init__(self) -> None:
        """Initialize the PyXA backend."""
        super().__init__()
        self._pyxa: Any = None
        self._executor = ThreadPoolExecutor(max_workers=1)

    @staticmethod
    def is_available() -> bool:
        """Check if PyXA is available on this platform."""
        if sys.platform != "darwin":
            return False
        try:
            import PyXA  # noqa: F401

            return True
        except ImportError:
            return False

    @property
    def backend_name(self) -> str:
        """Get backend name."""
        return "pyxa"

    def _get_pyxa(self) -> Any:
        """Get or import PyXA module."""
        if self._pyxa is None:
            try:
                import PyXA

                self._pyxa = PyXA
            except ImportError as e:
                raise AutomationError(
                    "PyXA not installed. Install with: pip install pyxa",
                    details={"error": str(e)},
                ) from e
        return self._pyxa

    async def _run_sync(self, func: Any, *args: Any) -> Any:
        """Run a synchronous function in the executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    # =========================================================================
    # Application Operations
    # =========================================================================

    async def launch_application(self, bundle_id: str) -> ApplicationInfo:
        """Launch an application by bundle identifier."""
        PyXA = self._get_pyxa()

        def _launch() -> ApplicationInfo:
            try:
                app = PyXA.Application(bundle_id)
                app.launch()
                return self._app_to_info(app)
            except Exception as e:
                raise ApplicationNotFoundError(
                    bundle_id,
                    details={"error": str(e)},
                ) from e

        return await self._run_sync(_launch)

    async def get_application(self, bundle_id: str) -> ApplicationInfo | None:
        """Get information about a running application."""
        PyXA = self._get_pyxa()

        def _get() -> ApplicationInfo | None:
            try:
                app = PyXA.Application(bundle_id)
                if not app.is_running():
                    return None
                return self._app_to_info(app)
            except Exception:
                return None

        return await self._run_sync(_get)

    async def list_applications(self) -> list[ApplicationInfo]:
        """List all running applications."""
        PyXA = self._get_pyxa()

        def _list() -> list[ApplicationInfo]:
            try:
                apps = PyXA.running_applications()
                return [self._app_to_info(app) for app in apps]
            except Exception as e:
                logger.error(f"Failed to list applications: {e}")
                return []

        return await self._run_sync(_list)

    async def quit_application(self, bundle_id: str, force: bool = False) -> bool:
        """Quit an application."""
        PyXA = self._get_pyxa()

        def _quit() -> bool:
            try:
                app = PyXA.Application(bundle_id)
                if not app.is_running():
                    return False
                if force:
                    app.force_quit()
                else:
                    app.quit()
                return True
            except Exception as e:
                logger.error(f"Failed to quit {bundle_id}: {e}")
                return False

        return await self._run_sync(_quit)

    async def activate_application(self, bundle_id: str) -> bool:
        """Activate (bring to front) an application."""
        PyXA = self._get_pyxa()

        def _activate() -> bool:
            try:
                app = PyXA.Application(bundle_id)
                app.activate()
                return True
            except Exception as e:
                logger.error(f"Failed to activate {bundle_id}: {e}")
                return False

        return await self._run_sync(_activate)

    async def get_active_application(self) -> ApplicationInfo | None:
        """Get the currently active application."""
        PyXA = self._get_pyxa()

        def _get() -> ApplicationInfo | None:
            try:
                app = PyXA.frontmost_application()
                return self._app_to_info(app)
            except Exception:
                return None

        return await self._run_sync(_get)

    def _app_to_info(self, app: Any) -> ApplicationInfo:
        """Convert PyXA app to ApplicationInfo."""
        try:
            bundle_id = app.bundle_identifier() or "unknown"
            name = app.name() or "Unknown"
            pid = app.process_identifier() or 0
            frontmost = app.frontmost() if hasattr(app, "frontmost") else False

            # Get windows
            windows = []
            try:
                for win in app.windows():
                    windows.append(self._window_to_info(win, bundle_id))
            except Exception:
                pass

            return ApplicationInfo(
                bundle_id=bundle_id,
                name=name,
                pid=pid,
                frontmost=frontmost,
                windows=windows,
                url=app.url() if hasattr(app, "url") else None,
                version=app.version() if hasattr(app, "version") else None,
            )
        except Exception as e:
            logger.warning(f"Error converting app to info: {e}")
            return ApplicationInfo(
                bundle_id="unknown",
                name="Unknown",
                pid=0,
            )

    def _window_to_info(self, win: Any, bundle_id: str | None = None) -> WindowInfo:
        """Convert PyXA window to WindowInfo."""
        try:
            # Get window ID (use AXUIElement hash or index)
            win_id = str(id(win))

            # Get window properties
            title = win.title() if hasattr(win, "title") else ""
            position = win.position() if hasattr(win, "position") else (0, 0)
            size = win.size() if hasattr(win, "size") else (0, 0)
            minimized = win.minimized() if hasattr(win, "minimized") else False
            focused = win.focused() if hasattr(win, "focused") else False

            # Determine window state
            if minimized:
                state = WindowState.MINIMIZED
            else:
                state = WindowState.NORMAL

            return WindowInfo(
                id=win_id,
                title=title or "",
                position=tuple(position) if position else (0, 0),
                size=tuple(size) if size else (0, 0),
                state=state,
                focused=focused,
                bundle_id=bundle_id,
            )
        except Exception as e:
            logger.warning(f"Error converting window to info: {e}")
            return WindowInfo(
                id="unknown",
                title="",
                position=(0, 0),
                size=(0, 0),
            )

    # =========================================================================
    # Window Operations
    # =========================================================================

    async def get_windows(self, bundle_id: str) -> list[WindowInfo]:
        """Get all windows for an application."""
        PyXA = self._get_pyxa()

        def _get() -> list[WindowInfo]:
            try:
                app = PyXA.Application(bundle_id)
                windows = []
                for win in app.windows():
                    windows.append(self._window_to_info(win, bundle_id))
                return windows
            except Exception as e:
                logger.error(f"Failed to get windows for {bundle_id}: {e}")
                return []

        return await self._run_sync(_get)

    async def activate_window(self, window_id: str) -> bool:
        """Activate (bring to front) a window."""
        # Note: PyXA window activation requires finding the window first
        # This is a simplified implementation
        logger.warning("Window activation by ID not fully implemented in PyXA backend")
        return False

    async def resize_window(self, window_id: str, width: int, height: int) -> bool:
        """Resize a window."""
        # Note: PyXA window operations require window object reference
        logger.warning("Window resize by ID not fully implemented in PyXA backend")
        return False

    async def move_window(self, window_id: str, x: int, y: int) -> bool:
        """Move a window to a new position."""
        logger.warning("Window move by ID not fully implemented in PyXA backend")
        return False

    async def close_window(self, window_id: str) -> bool:
        """Close a window."""
        logger.warning("Window close by ID not fully implemented in PyXA backend")
        return False

    # =========================================================================
    # Menu Operations
    # =========================================================================

    async def click_menu_item(self, bundle_id: str, menu_path: list[str]) -> bool:
        """Navigate menu and click an item."""
        PyXA = self._get_pyxa()

        def _click() -> bool:
            try:
                app = PyXA.Application(bundle_id)
                menu_bar = app.menu_bar()

                # Navigate through menu path
                current = menu_bar
                for item_name in menu_path:
                    found = False
                    for item in current.menu_items():
                        if item.title() == item_name:
                            current = item
                            found = True
                            break
                    if not found:
                        raise MenuNotFoundError(menu_path, bundle_id)

                # Click the final item
                current.click()
                return True
            except MenuNotFoundError:
                raise
            except Exception as e:
                logger.error(f"Failed to click menu {menu_path}: {e}")
                return False

        return await self._run_sync(_click)

    async def list_menus(self, bundle_id: str) -> list[MenuInfo]:
        """List all menus for an application."""
        PyXA = self._get_pyxa()

        def _list() -> list[MenuInfo]:
            try:
                app = PyXA.Application(bundle_id)
                menu_bar = app.menu_bar()
                menus = []

                for menu in menu_bar.menus():
                    menu_info = self._menu_to_info(menu, [])
                    if menu_info:
                        menus.append(menu_info)

                return menus
            except Exception as e:
                logger.error(f"Failed to list menus for {bundle_id}: {e}")
                return []

        return await self._run_sync(_list)

    def _menu_to_info(self, menu: Any, path: list[str]) -> MenuInfo | None:
        """Convert PyXA menu to MenuInfo."""
        try:
            name = menu.title() if hasattr(menu, "title") else ""
            if not name:
                return None

            current_path = path + [name]
            children = []

            if hasattr(menu, "menu_items"):
                for item in menu.menu_items():
                    child = self._menu_to_info(item, current_path)
                    if child:
                        children.append(child)

            return MenuInfo(
                name=name,
                path=current_path,
                enabled=True,  # PyXA doesn't expose enabled state easily
                children=children,
            )
        except Exception:
            return None

    # =========================================================================
    # Input Operations
    # =========================================================================

    async def type_text(self, text: str, interval: float = 0.05) -> bool:
        """Type text at the current cursor position."""
        PyXA = self._get_pyxa()

        def _type() -> bool:
            try:
                system = PyXA.system_events()
                for char in text:
                    system.keystroke(char)
                    if interval > 0:
                        import time

                        time.sleep(interval)
                return True
            except Exception as e:
                logger.error(f"Failed to type text: {e}")
                return False

        return await self._run_sync(_type)

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> bool:
        """Press a key with optional modifiers."""
        PyXA = self._get_pyxa()

        def _press() -> bool:
            try:
                system = PyXA.system_events()
                key_code = self._key_to_code(key)

                if modifiers:
                    # Press with modifiers
                    modifier_codes = [self._modifier_to_code(m) for m in modifiers]
                    system.key_code(key_code, *modifier_codes)
                else:
                    system.key_code(key_code)

                return True
            except Exception as e:
                logger.error(f"Failed to press key {key}: {e}")
                return False

        return await self._run_sync(_press)

    def _key_to_code(self, key: str) -> int:
        """Convert key name to macOS key code."""
        # macOS key codes
        key_codes = {
            "return": 36,
            "enter": 36,
            "tab": 48,
            "space": 49,
            "delete": 51,
            "backspace": 51,
            "escape": 53,
            "esc": 53,
            "up": 126,
            "down": 125,
            "left": 123,
            "right": 124,
            "home": 115,
            "end": 119,
            "pageup": 116,
            "pagedown": 121,
            "f1": 122,
            "f2": 120,
            "f3": 99,
            "f4": 118,
            "f5": 96,
            "f6": 97,
            "f7": 98,
            "f8": 100,
            "f9": 101,
            "f10": 109,
            "f11": 103,
            "f12": 111,
        }

        key_lower = key.lower()
        if key_lower in key_codes:
            return key_codes[key_lower]

        # Single character
        if len(key) == 1:
            return ord(key.upper())

        return 0

    def _modifier_to_code(self, modifier: str) -> Any:
        """Convert modifier name to PyXA modifier constant."""
        PyXA = self._get_pyxa()

        modifiers = {
            "cmd": PyXA.kMDKeyCommand,
            "command": PyXA.kMDKeyCommand,
            "shift": PyXA.kMDKeyShift,
            "option": PyXA.kMDKeyOption,
            "alt": PyXA.kMDKeyOption,
            "control": PyXA.kMDKeyControl,
            "ctrl": PyXA.kMDKeyControl,
            "fn": PyXA.kMDKeyFunction,
        }

        return modifiers.get(modifier.lower(), 0)

    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
        """Click at coordinates."""
        PyXA = self._get_pyxa()

        def _click() -> bool:
            try:
                # PyXA doesn't have direct click, use pyautogui fallback
                import pyautogui

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
        PyXA = self._get_pyxa()

        def _drag() -> bool:
            try:
                import pyautogui

                pyautogui.moveTo(start_x, start_y)
                pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration, button=button)
                return True
            except Exception as e:
                logger.error(f"Failed to drag: {e}")
                return False

        return await self._run_sync(_drag)

    async def scroll(self, x: int, y: int, dx: int, dy: int) -> bool:
        """Scroll at coordinates."""
        PyXA = self._get_pyxa()

        def _scroll() -> bool:
            try:
                import pyautogui

                pyautogui.moveTo(x, y)
                pyautogui.scroll(dy, x, y)
                return True
            except Exception as e:
                logger.error(f"Failed to scroll: {e}")
                return False

        return await self._run_sync(_scroll)

    # =========================================================================
    # Screenshot Operations
    # =========================================================================

    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes:
        """Capture a screenshot."""
        PyXA = self._get_pyxa()

        def _capture() -> bytes:
            try:
                if region:
                    x, y, width, height = region
                    img = PyXA.screenshot(x, y, width, height)
                else:
                    img = PyXA.screenshot()

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

    # =========================================================================
    # Screen Operations
    # =========================================================================

    async def list_screens(self) -> list[ScreenInfo]:
        """List all connected displays."""
        PyXA = self._get_pyxa()

        def _list() -> list[ScreenInfo]:
            try:
                screens = []
                for i, screen in enumerate(PyXA.screens()):
                    screens.append(
                        ScreenInfo(
                            id=i,
                            name=f"Display {i + 1}",
                            position=(screen.x, screen.y) if hasattr(screen, "x") else (0, 0),
                            size=(screen.width, screen.height),
                            scale=2.0 if hasattr(screen, "scale") and screen.scale > 1 else 1.0,
                            primary=i == 0,  # First screen is primary
                        )
                    )
                return screens
            except Exception as e:
                logger.error(f"Failed to list screens: {e}")
                return []

        return await self._run_sync(_list)

    # =========================================================================
    # UI Element Operations
    # =========================================================================

    async def get_ui_elements(
        self,
        bundle_id: str,
        window_id: str | None = None,
    ) -> list[UIElement]:
        """Get UI elements for an application."""
        PyXA = self._get_pyxa()

        def _get() -> list[UIElement]:
            try:
                app = PyXA.Application(bundle_id)
                elements = []

                # Get elements from all windows
                for win in app.windows():
                    for elem in win.ui_elements():
                        elements.append(self._element_to_info(elem))
                    break  # Just first window for now

                return elements
            except Exception as e:
                logger.error(f"Failed to get UI elements: {e}")
                return []

        return await self._run_sync(_get)

    def _element_to_info(self, elem: Any) -> UIElement:
        """Convert PyXA element to UIElement."""
        try:
            return UIElement(
                role=elem.role() if hasattr(elem, "role") else "unknown",
                title=elem.title() if hasattr(elem, "title") else None,
                value=elem.value() if hasattr(elem, "value") else None,
                position=elem.position() if hasattr(elem, "position") else None,
                size=elem.size() if hasattr(elem, "size") else None,
                enabled=elem.enabled() if hasattr(elem, "enabled") else True,
                focused=elem.focused() if hasattr(elem, "focused") else False,
                identifier=elem.identifier() if hasattr(elem, "identifier") else None,
                description=elem.description() if hasattr(elem, "description") else None,
            )
        except Exception:
            return UIElement(role="unknown")

    async def click_ui_element(self, bundle_id: str, element_identifier: str) -> bool:
        """Click a UI element by identifier."""
        PyXA = self._get_pyxa()

        def _click() -> bool:
            try:
                app = PyXA.Application(bundle_id)
                # Find and click element by identifier
                for win in app.windows():
                    for elem in win.ui_elements():
                        if hasattr(elem, "identifier") and elem.identifier() == element_identifier:
                            elem.click()
                            return True
                return False
            except Exception as e:
                logger.error(f"Failed to click UI element: {e}")
                return False

        return await self._run_sync(_click)

    async def close(self) -> None:
        """Clean up backend resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._pyxa = None
