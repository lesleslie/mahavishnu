"""ATOMac backend for macOS desktop automation.

ATOMac provides lower-level accessibility API access for macOS.
This backend is deprioritized due to maintenance concerns with the
community fork.

Requirements:
- macOS 10.15+
- pyatomac library (pip install pyatomac)
- Accessibility permissions

Note: This backend is maintained for compatibility but PyXA is preferred.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
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


class ATOMacBackend(DesktopAutomationBackend):
    """ATOMac-based automation backend for macOS.

    ATOMac provides direct Accessibility API access for more granular
    control when PyXA can't access specific UI elements.

    WARNING: This backend is deprioritized due to maintenance concerns
    with the community fork. Use PyXA when possible.

    Usage:
        backend = ATOMacBackend()
        if backend.is_available():
            await backend.launch_application("com.apple.finder")
    """

    def __init__(self) -> None:
        """Initialize the ATOMac backend."""
        super().__init__()
        self._atomac: Any = None
        self._executor = ThreadPoolExecutor(max_workers=1)

    @staticmethod
    def is_available() -> bool:
        """Check if ATOMac is available on this platform."""
        if sys.platform != "darwin":
            return False
        try:
            import atomac  # noqa: F401

            return True
        except ImportError:
            return False

    @property
    def backend_name(self) -> str:
        """Get backend name."""
        return "atomac"

    def _get_atomac(self) -> Any:
        """Get or import atomac module."""
        if self._atomac is None:
            try:
                import atomac

                self._atomac = atomac
            except ImportError as e:
                raise AutomationError(
                    "ATOMac not installed. Install with: pip install pyatomac",
                    details={"error": str(e)},
                ) from e
        return self._atomac

    async def _run_sync(self, func: Any, *args: Any) -> Any:
        """Run a synchronous function in the executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, func, *args)

    # =========================================================================
    # Application Operations
    # =========================================================================

    async def launch_application(self, bundle_id: str) -> ApplicationInfo:
        """Launch an application by bundle identifier."""
        atomac = self._get_atomac()

        def _launch() -> ApplicationInfo:
            try:
                app = atomac.launchAppByBundleId(bundle_id)
                return self._app_to_info(app, bundle_id)
            except Exception as e:
                raise ApplicationNotFoundError(
                    bundle_id,
                    details={"error": str(e)},
                ) from e

        return await self._run_sync(_launch)

    async def get_application(self, bundle_id: str) -> ApplicationInfo | None:
        """Get information about a running application."""
        atomac = self._get_atomac()

        def _get() -> ApplicationInfo | None:
            try:
                app = atomac.getAppWithBundleId(bundle_id)
                if app is None:
                    return None
                return self._app_to_info(app, bundle_id)
            except Exception:
                return None

        return await self._run_sync(_get)

    async def list_applications(self) -> list[ApplicationInfo]:
        """List all running applications."""
        atomac = self._get_atomac()

        def _list() -> list[ApplicationInfo]:
            try:
                # ATOMac doesn't have a direct list all apps method
                # We can use NSWorkspace for this
                from AppKit import NSWorkspace

                workspace = NSWorkspace.sharedWorkspace()
                apps = workspace.runningApplications()

                result = []
                for app in apps:
                    bundle_id = app.bundleIdentifier()
                    if bundle_id:
                        result.append(
                            ApplicationInfo(
                                bundle_id=bundle_id,
                                name=app.localizedName() or "Unknown",
                                pid=app.processIdentifier(),
                                frontmost=app.isActive(),
                            )
                        )
                return result
            except Exception as e:
                logger.error(f"Failed to list applications: {e}")
                return []

        return await self._run_sync(_list)

    async def quit_application(self, bundle_id: str, force: bool = False) -> bool:
        """Quit an application."""
        atomac = self._get_atomac()

        def _quit() -> bool:
            try:
                app = atomac.getAppWithBundleId(bundle_id)
                if app is None:
                    return False
                # ATOMac doesn't have a direct quit, use AppleScript
                import subprocess

                if force:
                    subprocess.run(
                        ["killall", "-9", bundle_id.split(".")[-1]],
                        check=False,
                    )
                else:
                    subprocess.run(
                        ["osascript", "-e", f'tell application "{bundle_id}" to quit'],
                        check=False,
                    )
                return True
            except Exception as e:
                logger.error(f"Failed to quit {bundle_id}: {e}")
                return False

        return await self._run_sync(_quit)

    async def activate_application(self, bundle_id: str) -> bool:
        """Activate (bring to front) an application."""
        atomac = self._get_atomac()

        def _activate() -> bool:
            try:
                app = atomac.getAppWithBundleId(bundle_id)
                if app is None:
                    return False
                app.activate()
                return True
            except Exception as e:
                logger.error(f"Failed to activate {bundle_id}: {e}")
                return False

        return await self._run_sync(_activate)

    async def get_active_application(self) -> ApplicationInfo | None:
        """Get the currently active application."""
        atomac = self._get_atomac()

        def _get() -> ApplicationInfo | None:
            try:
                # Use NSWorkspace to get frontmost app
                from AppKit import NSWorkspace

                workspace = NSWorkspace.sharedWorkspace()
                app = workspace.frontmostApplication()
                if app:
                    return ApplicationInfo(
                        bundle_id=app.bundleIdentifier() or "unknown",
                        name=app.localizedName() or "Unknown",
                        pid=app.processIdentifier(),
                        frontmost=True,
                    )
                return None
            except Exception:
                return None

        return await self._run_sync(_get)

    def _app_to_info(self, app: Any, bundle_id: str) -> ApplicationInfo:
        """Convert ATOMac app to ApplicationInfo."""
        try:
            name = getattr(app, "localizedName", "Unknown")
            pid = getattr(app, "processIdentifier", 0)

            return ApplicationInfo(
                bundle_id=bundle_id,
                name=name if isinstance(name, str) else "Unknown",
                pid=pid if isinstance(pid, int) else 0,
                frontmost=True,  # Assumed if we got it
            )
        except Exception as e:
            logger.warning(f"Error converting app to info: {e}")
            return ApplicationInfo(
                bundle_id=bundle_id,
                name="Unknown",
                pid=0,
            )

    def _window_to_info(self, win: Any, bundle_id: str | None = None) -> WindowInfo:
        """Convert ATOMac window to WindowInfo."""
        try:
            ax_window = win.AXWindow
            title = ax_window.AXTitle or ""
            position = ax_window.AXPosition or (0, 0)
            size = ax_window.AXSize or (0, 0)

            return WindowInfo(
                id=str(id(win)),
                title=title,
                position=tuple(position),
                size=tuple(size),
                state=WindowState.NORMAL,
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
        atomac = self._get_atomac()

        def _get() -> list[WindowInfo]:
            try:
                app = atomac.getAppWithBundleId(bundle_id)
                if app is None:
                    return []

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
        logger.warning("Window activation by ID not implemented in ATOMac backend")
        return False

    async def resize_window(self, window_id: str, width: int, height: int) -> bool:
        """Resize a window."""
        logger.warning("Window resize by ID not implemented in ATOMac backend")
        return False

    async def move_window(self, window_id: str, x: int, y: int) -> bool:
        """Move a window to a new position."""
        logger.warning("Window move by ID not implemented in ATOMac backend")
        return False

    async def close_window(self, window_id: str) -> bool:
        """Close a window."""
        logger.warning("Window close by ID not implemented in ATOMac backend")
        return False

    # =========================================================================
    # Menu Operations
    # =========================================================================

    async def click_menu_item(self, bundle_id: str, menu_path: list[str]) -> bool:
        """Navigate menu and click an item."""
        atomac = self._get_atomac()

        def _click() -> bool:
            try:
                app = atomac.getAppWithBundleId(bundle_id)
                if app is None:
                    raise MenuNotFoundError(menu_path, bundle_id)

                # Navigate menu
                menu_bar = app.menuBar()
                current = menu_bar

                for item_name in menu_path[:-1]:
                    menu = current.menus(item_name)
                    if menu is None:
                        raise MenuNotFoundError(menu_path, bundle_id)
                    current = menu

                # Click final item
                final_item = menu_path[-1]
                menu_item = current.menuItems(final_item)
                if menu_item is None:
                    raise MenuNotFoundError(menu_path, bundle_id)
                menu_item.Press()

                return True
            except MenuNotFoundError:
                raise
            except Exception as e:
                logger.error(f"Failed to click menu {menu_path}: {e}")
                return False

        return await self._run_sync(_click)

    async def list_menus(self, bundle_id: str) -> list[MenuInfo]:
        """List all menus for an application."""
        atomac = self._get_atomac()

        def _list() -> list[MenuInfo]:
            try:
                app = atomac.getAppWithBundleId(bundle_id)
                if app is None:
                    return []

                menu_bar = app.menuBar()
                menus = []

                for menu in getattr(menu_bar, "menus", []):
                    menu_info = self._menu_to_info(menu, [])
                    if menu_info:
                        menus.append(menu_info)

                return menus
            except Exception as e:
                logger.error(f"Failed to list menus for {bundle_id}: {e}")
                return []

        return await self._run_sync(_list)

    def _menu_to_info(self, menu: Any, path: list[str]) -> MenuInfo | None:
        """Convert ATOMac menu to MenuInfo."""
        try:
            name = getattr(menu, "AXTitle", "")
            if not name:
                return None

            current_path = path + [name]
            children = []

            for item in getattr(menu, "menuItems", []):
                child = self._menu_to_info(item, current_path)
                if child:
                    children.append(child)

            return MenuInfo(
                name=name,
                path=current_path,
                enabled=getattr(menu, "AXEnabled", True),
                children=children,
            )
        except Exception:
            return None

    # =========================================================================
    # Input Operations
    # =========================================================================

    async def type_text(self, text: str, interval: float = 0.05) -> bool:
        """Type text at the current cursor position."""
        atomac = self._get_atomac()

        def _type() -> bool:
            try:
                import time

                for char in text:
                    atomac.keyboard.send(char)
                    if interval > 0:
                        time.sleep(interval)
                return True
            except Exception as e:
                logger.error(f"Failed to type text: {e}")
                return False

        return await self._run_sync(_type)

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> bool:
        """Press a key with optional modifiers."""
        atomac = self._get_atomac()

        def _press() -> bool:
            try:
                key_code = self._key_to_code(key)

                if modifiers:
                    mod_codes = [self._modifier_to_code(m) for m in modifiers]
                    atomac.keyboard.send(key_code, mod_codes)
                else:
                    atomac.keyboard.send(key_code)

                return True
            except Exception as e:
                logger.error(f"Failed to press key {key}: {e}")
                return False

        return await self._run_sync(_press)

    def _key_to_code(self, key: str) -> str | int:
        """Convert key name to key code."""
        # ATOMac uses key names
        key_map = {
            "return": "return",
            "enter": "return",
            "tab": "tab",
            "space": "space",
            "delete": "delete",
            "backspace": "delete",
            "escape": "escape",
            "esc": "escape",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
        }

        key_lower = key.lower()
        if key_lower in key_map:
            return key_map[key_lower]

        return key

    def _modifier_to_code(self, modifier: str) -> str:
        """Convert modifier name to ATOMac modifier."""
        modifiers = {
            "cmd": "command",
            "command": "command",
            "shift": "shift",
            "option": "option",
            "alt": "option",
            "control": "control",
            "ctrl": "control",
        }
        return modifiers.get(modifier.lower(), modifier)

    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
        """Click at coordinates."""
        atomac = self._get_atomac()

        def _click() -> bool:
            try:
                for _ in range(clicks):
                    atomac.mouse.click(x, y)
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
        atomac = self._get_atomac()

        def _drag() -> bool:
            try:
                atomac.mouse.drag(start_x, start_y, end_x, end_y)
                return True
            except Exception as e:
                logger.error(f"Failed to drag: {e}")
                return False

        return await self._run_sync(_drag)

    async def scroll(self, x: int, y: int, dx: int, dy: int) -> bool:
        """Scroll at coordinates."""
        atomac = self._get_atomac()

        def _scroll() -> bool:
            try:
                atomac.mouse.scroll(dy)
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

        # ATOMac doesn't have screenshot support, use fallback
        def _capture() -> bytes:
            try:
                import subprocess

                if region:
                    x, y, width, height = region
                    cmd = [
                        "screencapture",
                        "-x",
                        "-R",
                        str(x),
                        str(y),
                        str(width),
                        str(height),
                        "-",
                    ]
                else:
                    cmd = ["screencapture", "-x", "-"]

                result = subprocess.run(cmd, capture_output=True, check=True)
                return result.stdout
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

        def _list() -> list[ScreenInfo]:
            try:
                from AppKit import NSScreen

                screens = []
                main_screen = NSScreen.mainScreen()

                for i, screen in enumerate(NSScreen.screens()):
                    frame = screen.frame()
                    screens.append(
                        ScreenInfo(
                            id=i,
                            name=f"Display {i + 1}",
                            position=(int(frame.origin.x), int(frame.origin.y)),
                            size=(int(frame.size.width), int(frame.size.height)),
                            scale=screen.backingScaleFactor(),
                            primary=screen == main_screen,
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
        atomac = self._get_atomac()

        def _get() -> list[UIElement]:
            try:
                app = atomac.getAppWithBundleId(bundle_id)
                if app is None:
                    return []

                elements = []

                # Get all UI elements from windows
                for win in app.windows():
                    ax_window = win.AXWindow
                    for elem in self._get_all_elements(ax_window):
                        elements.append(elem)
                    break  # Just first window

                return elements
            except Exception as e:
                logger.error(f"Failed to get UI elements: {e}")
                return []

        return await self._run_sync(_get)

    def _get_all_elements(self, parent: Any) -> list[UIElement]:
        """Recursively get all UI elements."""
        elements = []

        try:
            for child in getattr(parent, "AXChildren", []):
                elem_info = UIElement(
                    role=getattr(child, "AXRole", "unknown"),
                    title=getattr(child, "AXTitle", None),
                    value=getattr(child, "AXValue", None),
                    position=getattr(child, "AXPosition", None),
                    size=getattr(child, "AXSize", None),
                    enabled=getattr(child, "AXEnabled", True),
                    identifier=getattr(child, "AXIdentifier", None),
                    description=getattr(child, "AXHelp", None),
                )
                elements.append(elem_info)

                # Recursively get children
                elements.extend(self._get_all_elements(child))
        except Exception:
            pass

        return elements

    async def close(self) -> None:
        """Clean up backend resources."""
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None
        self._atomac = None
