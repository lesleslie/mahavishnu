"""Native macOS automation backend using built-in tools.

This backend uses only built-in macOS tools:
- osascript: AppleScript execution for app/window/menu operations
- screencapture: Built-in screenshot utility
- cliclick: CLI mouse/keyboard via `brew install cliclick`

This replaces the deprecated PyXA and ATOMac backends.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from mahavishnu.automation.backends.base import DesktopAutomationBackend

if TYPE_CHECKING:
    from mahavishnu.automation.base import (
        ApplicationInfo,
        MenuInfo,
        ScreenInfo,
        WindowInfo,
    )

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Thread pool for async-to-sync bridging (max_workers=2 for some concurrency)
_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=2)


async def _async_run_sync(func: Callable[..., T], *args: Any) -> T:
    """Run blocking function in thread pool, await the result async."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, func, *args)


def _run_osascript(script: str) -> str:
    """Execute osascript command and return stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _run_cliclick(args: str) -> str:
    """Execute cliclick command and return stdout."""
    result = subprocess.run(
        ["cliclick"] + args.split(),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cliclick failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _parse_bool(value: str) -> bool:
    """Parse osascript boolean string."""
    return value.lower() in ("true", "true\n")


class NativeMacOSBackend(DesktopAutomationBackend):
    """Native macOS automation backend using osascript, screencapture, and cliclick.

    Availability: Requires macOS (sys.platform == "darwin") AND cliclick installed.
    If cliclick is not found, is_available() returns False and the backend is skipped.
    """

    @staticmethod
    def is_available() -> bool:
        """Check if native macOS backend is available.

        Requires:
        - macOS (sys.platform == "darwin")
        - cliclick installed (shutil.which("cliclick"))
        """
        import sys

        if sys.platform != "darwin":
            return False
        return shutil.which("cliclick") is not None

    @property
    def backend_name(self) -> str:
        """Return backend name."""
        return "native_macos"

    # =====================================================================
    # Application Operations
    # =====================================================================

    async def launch_application(self, bundle_id: str) -> "ApplicationInfo":
        """Launch an application by bundle identifier."""
        from mahavishnu.automation.base import ApplicationInfo

        script = f'''
        tell application id "{bundle_id}"
            launch
            delay 0.5
            set appName to name
            set appPID to pid
        end tell
        return "name:" & appName & "|pid:" & appPID
        '''
        result = await _async_run_sync(_run_osascript, script)

        # Parse: "name:Finder|pid:1234"
        parts = dict(p.split(":", 1) for p in result.split("|"))
        name = parts.get("name", bundle_id.split(".")[-1])
        pid = int(parts.get("pid", "0"))

        return ApplicationInfo(
            bundle_id=bundle_id,
            name=name,
            pid=pid,
            frontmost=True,
            windows=[],
        )

    async def get_application(self, bundle_id: str) -> "ApplicationInfo | None":
        """Get information about a running application."""
        from mahavishnu.automation.base import ApplicationInfo

        script = f'''
        tell application "System Events"
            set appProc to first application process whose bundle identifier is "{bundle_id}"
            set appName to name of appProc
            set appPID to pid of appProc
            set appFrontmost to frontmost of appProc
        end tell
        return "name:" & appName & "|pid:" & appPID & "|frontmost:" & appFrontmost
        '''
        try:
            result = await _async_run_sync(_run_osascript, script)
            parts = dict(p.split(":", 1) for p in result.split("|"))
            return ApplicationInfo(
                bundle_id=bundle_id,
                name=parts.get("name", bundle_id),
                pid=int(parts.get("pid", "0")),
                frontmost=_parse_bool(parts.get("frontmost", "false")),
            )
        except RuntimeError:
            return None

    async def list_applications(self) -> list["ApplicationInfo"]:
        """List all running applications."""
        from mahavishnu.automation.base import ApplicationInfo

        script = '''
        tell application "System Events"
            set appList to {}
            repeat with appProc in (every application process)
                set bundleId to bundle identifier of appProc
                set appName to name of appProc
                set appPID to pid of appProc
                set appFrontmost to frontmost of appProc
                copy "name:" & appName & "|pid:" & appPID & "|frontmost:" & appFrontmost & "|bundle:" & bundleId to end of appList
            end repeat
        end tell
        return appList
        '''
        try:
            result = await _async_run_sync(_run_osascript, script)
            if not result or result == "{}":
                return []
            # Parse each line: "name:Finder|pid:1234|frontmost:true|bundle:com.apple.finder"
            apps = []
            for line in result.strip().split("\n"):
                if not line.strip():
                    continue
                parts = dict(p.split(":", 1) for p in line.split("|"))
                apps.append(
                    ApplicationInfo(
                        bundle_id=parts.get("bundle", "unknown"),
                        name=parts.get("name", "Unknown"),
                        pid=int(parts.get("pid", "0")),
                        frontmost=_parse_bool(parts.get("frontmost", "false")),
                    )
                )
            return apps
        except Exception as e:
            logger.error("Failed to list applications: %s", e)
            return []

    async def quit_application(self, bundle_id: str, force: bool = False) -> bool:
        """Quit an application."""
        if force:
            script = f'''
            tell application id "{bundle_id}"
                quit
            end tell
            '''
        else:
            script = f'''
            tell application "System Events"
                set appProc to first application process whose bundle identifier is "{bundle_id}"
                if exists appProc then
                    tell appProc to quit
                end if
            end tell
            '''
        try:
            await _async_run_sync(_run_osascript, script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to quit %s: %s", bundle_id, e)
            return False

    async def activate_application(self, bundle_id: str) -> bool:
        """Activate (bring to front) an application."""
        script = f'''
        tell application id "{bundle_id}"
            activate
        end tell
        '''
        try:
            await _async_run_sync(_run_osascript, script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to activate %s: %s", bundle_id, e)
            return False

    async def get_active_application(self) -> "ApplicationInfo | None":
        """Get the currently active (frontmost) application."""
        from mahavishnu.automation.base import ApplicationInfo

        script = '''
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set appName to name of frontApp
            set appPID to pid of frontApp
            set bundleId to bundle identifier of frontApp
        end tell
        return "name:" & appName & "|pid:" & appPID & "|bundle:" & bundleId
        '''
        try:
            result = await _async_run_sync(_run_osascript, script)
            parts = dict(p.split(":", 1) for p in result.split("|"))
            return ApplicationInfo(
                bundle_id=parts.get("bundle", "unknown"),
                name=parts.get("name", "Unknown"),
                pid=int(parts.get("pid", "0")),
                frontmost=True,
            )
        except RuntimeError:
            return None

    # =====================================================================
    # Window Operations
    # =====================================================================

    async def get_windows(self, bundle_id: str) -> list["WindowInfo"]:
        """Get all windows for an application."""
        from mahavishnu.automation.base import ApplicationInfo, WindowInfo

        script = f'''
        tell application "System Events"
            set appProc to first application process whose bundle identifier is "{bundle_id}"
            set windowList to every window of appProc
            set resultText to ""
            repeat with winIdx from 1 to count of windowList
                set win to item winIdx of windowList
                set winTitle to name of win
                set winPos to position of win
                set winSize to size of win
                set winMini to minimized of win
                set winFront to frontmost of win
                if resultText is "" then
                    set resultText to "idx:" & winIdx & "|title:" & winTitle & "|x:" & (item 1 of winPos as string) & "|y:" & (item 2 of winPos as string) & "|w:" & (item 1 of winSize as string) & "|h:" & (item 2 of winSize as string) & "|mini:" & winMini & "|front:" & winFront
                else
                    set resultText to resultText & ASCII character 10 & "idx:" & winIdx & "|title:" & winTitle & "|x:" & (item 1 of winPos as string) & "|y:" & (item 2 of winPos as string) & "|w:" & (item 1 of winSize as string) & "|h:" & (item 2 of winSize as string) & "|mini:" & winMini & "|front:" & winFront
                end if
            end repeat
        end tell
        return resultText
        '''
        try:
            result = await _async_run_sync(_run_osascript, script)
            if not result.strip():
                return []
            windows = []
            for line in result.strip().split("\n"):
                if not line.strip():
                    continue
                parts = dict(p.split(":", 1) for p in line.split("|"))
                try:
                    windows.append(
                        WindowInfo(
                            id=parts.get("idx", "0"),
                            title=parts.get("title", ""),
                            position=(
                                int(parts.get("x", "0")),
                                int(parts.get("y", "0")),
                            ),
                            size=(
                                int(parts.get("w", "800")),
                                int(parts.get("h", "600")),
                            ),
                            bundle_id=bundle_id,
                            window_number=int(parts.get("idx", "0")) or None,
                        )
                    )
                except (ValueError, IndexError):
                    continue
            return windows
        except RuntimeError as e:
            logger.warning("Failed to get windows for %s: %s", bundle_id, e)
            return []

    async def activate_window(self, window_id: str) -> bool:
        """Activate (bring to front) a window.

        Note: window_id is treated as a 1-based window index (osascript convention).
        """
        script = f'''
        tell application "System Events"
            set win to window {window_id}
            set frontmost of win to true
        end tell
        '''
        try:
            await _async_run_sync(_run_osascript, script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to activate window %s: %s", window_id, e)
            return False

    async def resize_window(self, window_id: str, width: int, height: int) -> bool:
        """Resize a window.

        Not supported via osascript. Returns False with warning log.
        """
        logger.warning(
            "resize_window not supported by NativeMacOSBackend (osascript limitation). "
            "Use PyAutoGUI for coordinate-based window positioning."
        )
        return False

    async def move_window(self, window_id: str, x: int, y: int) -> bool:
        """Move a window to a new position.

        Not supported via osascript. Returns False with warning log.
        """
        logger.warning(
            "move_window not supported by NativeMacOSBackend (osascript limitation). "
            "Use PyAutoGUI for coordinate-based window positioning."
        )
        return False

    async def close_window(self, window_id: str) -> bool:
        """Close a window.

        Note: window_id is treated as a 1-based window index (osascript convention).
        """
        script = f'''
        tell application "System Events"
            close window {window_id}
        end tell
        '''
        try:
            await _async_run_sync(_run_osascript, script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to close window %s: %s", window_id, e)
            return False

    # =====================================================================
    # Menu Operations
    # =====================================================================

    async def click_menu_item(self, bundle_id: str, menu_path: list[str]) -> bool:
        """Navigate menu and click an item.

        Args:
            bundle_id: Application bundle identifier.
            menu_path: Path to menu item (e.g., ["File", "Save"]).
        """
        if len(menu_path) < 2:
            return False

        menu_name = menu_path[0]
        item_name = menu_path[-1]

        script = f'''
        tell application id "{bundle_id}"
            activate
        end tell
        tell application "System Events"
            tell process "{menu_name}"
                click menu item "{item_name}" of menu "{menu_name}"
            end tell
        end tell
        '''
        try:
            await _async_run_sync(_run_osascript, script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to click menu %s/%s: %s", menu_name, item_name, e)
            return False

    async def list_menus(self, bundle_id: str) -> list["MenuInfo"]:
        """List all menus for an application.

        Note: AppleScript cannot reliably enumerate all menu items across apps.
        This returns limited info — only standard app-level menus.
        """
        from mahavishnu.automation.base import MenuInfo

        # AppleScript menu listing is limited. Return empty with note.
        logger.debug("list_menus: AppleScript cannot reliably enumerate menus for %s", bundle_id)
        return []

    # =====================================================================
    # Clipboard Operations
    # =====================================================================

    async def get_clipboard(self) -> str:
        """Get clipboard content."""
        script = '''
        set clipboardText to the clipboard as string
        return clipboardText
        '''
        try:
            return await _async_run_sync(_run_osascript, script)
        except RuntimeError as e:
            logger.warning("Failed to get clipboard: %s", e)
            return ""

    async def set_clipboard(self, text: str) -> bool:
        """Set clipboard content."""
        # Escape quotes for AppleScript
        escaped = text.replace('"', '\\"').replace("\n", "\\n")
        script = f'''
        set the clipboard to "{escaped}"
        '''
        try:
            await _async_run_sync(_run_osascript, script)
            return True
        except RuntimeError as e:
            logger.warning("Failed to set clipboard: %s", e)
            return False

    # =====================================================================
    # Input Operations (via cliclick)
    # =====================================================================

    async def type_text(self, text: str, interval: float = 0.05) -> bool:
        """Type text at the current cursor position."""
        try:
            # Type each character with interval delay
            for char in text:
                if char == " ":
                    await _async_run_sync(_run_cliclick, "t:' '")
                else:
                    await _async_run_sync(_run_cliclick, f't:{char}')
                if interval > 0:
                    await asyncio.sleep(interval)
            return True
        except Exception as e:
            logger.warning("Failed to type text: %s", e)
            return False

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> bool:
        """Press a key with optional modifiers.

        Args:
            key: Key to press (e.g., "return", "a", "f1").
            modifiers: List of modifiers (e.g., ["cmd", "shift"]).
                       cliclick uses 'k:modifier+key' syntax.
        """
        try:
            if modifiers:
                mod_str = "+".join(modifiers)
                await _async_run_sync(_run_cliclick, f"k:{mod_str}+{key}")
            else:
                await _async_run_sync(_run_cliclick, f"k:{key}")
            return True
        except Exception as e:
            logger.warning("Failed to press key %s: %s", key, e)
            return False

    async def click(
        self,
        x: int,
        y: int,
        button: str = "left",
        clicks: int = 1,
    ) -> bool:
        """Click at coordinates."""
        try:
            if clicks == 1:
                await _async_run_sync(_run_cliclick, f"{x},{y}")
            elif clicks == 2:
                await _async_run_sync(_run_cliclick, f"dc:{x},{y}")
            elif clicks == 3:
                await _async_run_sync(_run_cliclick, f"tc:{x},{y}")
            return True
        except Exception as e:
            logger.warning("Failed to click at %d,%d: %s", x, y, e)
            return False

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
        try:
            # cliclick dc:x,y does mouse down, then use -g for drag (grid equiv)
            # Full drag: down at start, move, up at end
            await _async_run_sync(_run_cliclick, f"dc:{start_x},{start_y}")
            await asyncio.sleep(duration)
            await _async_run_sync(_run_cliclick, f"{end_x},{end_y}")
            return True
        except Exception as e:
            logger.warning("Failed to drag from %d,%d to %d,%d: %s", start_x, start_y, end_x, end_y, e)
            return False

    async def scroll(self, x: int, y: int, dx: int, dy: int) -> bool:
        """Scroll at coordinates."""
        try:
            # cliclick sw:dx,dy scrolls at current mouse position
            # For absolute position scroll, move first then scroll
            await _async_run_sync(_run_cliclick, f"m:{x},{y}")
            await _async_run_sync(_run_cliclick, f"sw:{dx},{dy}")
            return True
        except Exception as e:
            logger.warning("Failed to scroll at %d,%d: %s", x, y, e)
            return False

    # =====================================================================
    # Screenshot Operations
    # =====================================================================

    async def screenshot(self, region: tuple[int, int, int, int] | None = None) -> bytes:
        """Capture a screenshot.

        Args:
            region: Optional region as (x, y, width, height).
                    If None, captures entire screen.
        """
        import tempfile

        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                path = f.name

            if region:
                x, y, w, h = region
                cmd = ["screencapture", "-x", "-R", f"{x},{y},{w},{h}", path]
            else:
                cmd = ["screencapture", "-x", path]

            subprocess.run(cmd, capture_output=True, timeout=10, check=True)

            with open(path, "rb") as f:
                data = f.read()

            subprocess.run(["rm", "-f", path], capture_output=True)
            return data

        except subprocess.TimeoutExpired:
            raise RuntimeError("screenshot timed out")
        except Exception as e:
            raise RuntimeError(f"screenshot failed: {e}")

    # =====================================================================
    # Screen Operations
    # =====================================================================

    async def list_screens(self) -> list["ScreenInfo"]:
        """List all connected displays."""
        from mahavishnu.automation.base import ScreenInfo

        script = '''
        tell application "System Events"
            set screenCount to count of screens
            set resultText to ""
            repeat with scrIdx from 1 to screenCount
                set scr to item scrIdx of screens
                set scrName to name of scr
                set scrPos to position of scr
                set scrSize to size of scr
                set scrPrimary to (scrIdx is 1)
                if resultText is "" then
                    set resultText to "idx:" & scrIdx & "|name:" & scrName & "|x:" & (item 1 of scrPos as string) & "|y:" & (item 2 of scrPos as string) & "|w:" & (item 1 of scrSize as string) & "|h:" & (item 2 of scrSize as string) & "|primary:" & scrPrimary
                else
                    set resultText to resultText & ASCII character 10 & "idx:" & scrIdx & "|name:" & scrName & "|x:" & (item 1 of scrPos as string) & "|y:" & (item 2 of scrPos as string) & "|w:" & (item 1 of scrSize as string) & "|h:" & (item 2 of scrSize as string) & "|primary:" & scrPrimary
                end if
            end repeat
        end tell
        return resultText
        '''
        try:
            result = await _async_run_sync(_run_osascript, script)
            if not result.strip():
                return []
            screens = []
            for line in result.strip().split("\n"):
                if not line.strip():
                    continue
                parts = dict(p.split(":", 1) for p in line.split("|"))
                screens.append(
                    ScreenInfo(
                        id=int(parts.get("idx", "0")),
                        name=parts.get("name", f"Display {parts.get('idx', '0')}"),
                        position=(
                            int(parts.get("x", "0")),
                            int(parts.get("y", "0")),
                        ),
                        size=(
                            int(parts.get("w", "0")),
                            int(parts.get("h", "0")),
                        ),
                        primary=_parse_bool(parts.get("primary", "false")),
                    )
                )
            return screens
        except Exception as e:
            logger.error("Failed to list screens: %s", e)
            return []