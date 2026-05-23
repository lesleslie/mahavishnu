"""Terminal grid orchestration manager."""

import asyncio
import uuid
from datetime import datetime
from logging import getLogger

from mahavishnu.terminal.adapters.iterm2 import ITerm2Adapter

from .exceptions import (
    GridNotFoundError,
    SessionNotFoundError,
    WindowTilingError,
)
from .models import DesktopSession, GridSession, GridStatus, WindowSession

logger = getLogger(__name__)

QUADRANT_BOUNDS = {
    "tl": {"x": 0, "y": 0},
    "tr": {"x": 0, "y": 0},
    "bl": {"x": 0, "y": 0},
    "br": {"x": 0, "y": 0},
}
QUADRANTS = ["tl", "tr", "bl", "br"]


class TerminalGridManager:
    def __init__(self, iterm2_adapter: ITerm2Adapter):
        self._adapter = iterm2_adapter
        self._grids: dict[str, GridSession] = {}

    async def _get_primary_screen_bounds(self) -> tuple[int, int, int, int]:
        """Return (x, y, width, height) for the primary display."""
        script = '''
        tell application "iTerm2"
            get bounds of window 1
        end tell
        '''
        bounds_str = await self._adapter._run_applescript(script)
        parts = [int(p.strip()) for p in bounds_str.split(",")]
        x, y, w, h = parts[0], parts[1], parts[2], parts[3]
        return x, y, w, h

    async def _create_desktop_via_spaces(self) -> bool:
        """Create a new macOS Desktop via Spaces (Ctrl+Cmd+Space).

        Returns True on success, False if the hotkey is not bound.
        """
        script = '''
        tell application "System Events"
            tell application process "Dock"
                keystroke " " using {control down, command down}
            end tell
        end tell
        '''
        try:
            await self._adapter._run_applescript(script)
            await asyncio.sleep(0.5)
            return True
        except RuntimeError:
            return False

    async def _create_positioned_window(
        self,
        desktop_id: str,
        quadrant: str,
        half_w: int,
        half_h: int,
        screen_w: int,
        screen_h: int,
        task: str,
        profile: str | None,
    ) -> tuple[WindowSession, str]:
        """Create a named iTerm2 window at the quadrant position.

        Returns (WindowSession, tab_id).
        Raises WindowTilingError on failure.
        """
        x_offset = QUADRANT_BOUNDS[quadrant]["x"]
        y_offset = QUADRANT_BOUNDS[quadrant]["y"]
        bounds = {"x": x_offset, "y": y_offset, "w": half_w, "h": half_h}

        escaped_task = task.replace("\\", "\\\\").replace('"', '\\"')
        profile_clause = f'with profile "{profile}"' if profile else "with default profile"

        script = f'''
        tell application "iTerm2"
            activate
            set w to (create window {profile_clause})
            set name of w to "{desktop_id}_win_{quadrant}"
            set bounds of w to {{{x_offset}, {y_offset}, {x_offset + half_w}, {y_offset + half_h}}}
            delay 0.2
            tell w
                tell current session
                    write text "{escaped_task}"
                end tell
                set tabID to id of current session
            end tell
            return tabID
        end tell
        '''
        try:
            tab_id = await self._adapter._run_applescript(script)
        except RuntimeError as e:
            raise WindowTilingError(
                window_name=f"{desktop_id}_win_{quadrant}",
                message=f"Failed to create window: {e}",
                grid_id=None,
            )

        session_id = str(uuid.uuid4())[:8]
        win_session = WindowSession(
            window_name=f"{desktop_id}_win_{quadrant}",
            tab_id=tab_id,
            session_id=session_id,
            task=task,
            bounds=bounds,
            quadrant=quadrant,
        )
        return win_session, tab_id

    async def deploy_terminal_grid(
        self,
        tasks: list[str],
        columns: int = 80,
        rows: int = 24,
        profile: str | None = None,
        allow_multi_desktop: bool = True,
    ) -> str:
        """Deploy a terminal grid for the given tasks.

        Creates desktops → tiles windows → injects commands.
        Returns grid_id.
        """
        grid_id = f"grid_{str(uuid.uuid4())[:8]}"
        x, y, screen_w, screen_h = await self._get_primary_screen_bounds()
        half_w, half_h = screen_w // 2, screen_h // 2

        global QUADRANT_BOUNDS
        QUADRANT_BOUNDS = {
            "tl": {"x": x, "y": y},
            "tr": {"x": x + half_w, "y": y},
            "bl": {"x": x, "y": y + half_h},
            "br": {"x": x + half_w, "y": y + half_h},
        }

        grid = GridSession(
            grid_id=grid_id,
            created_at=datetime.now(),
            task_count=len(tasks),
        )
        self._grids[grid_id] = grid

        task_iter = iter(tasks)
        desktop_position = 1

        while True:
            if allow_multi_desktop:
                created = await self._create_desktop_via_spaces()
                if not created:
                    allow_multi_desktop = False
                    logger.warning("Spaces creation failed, falling back to single-desktop mode")

            if not allow_multi_desktop or desktop_position > 1:
                if desktop_position == 1 or not grid.desktops:
                    desktop_id = f"{grid_id}_d_single"
                    grid.desktops[desktop_id] = DesktopSession(
                        desktop_id=desktop_id, position=1
                    )
                else:
                    break

            if allow_multi_desktop and desktop_position > 1:
                await self._activate_desktop(desktop_position)

            desktop_id = f"{grid_id}_d{desktop_position}"
            desktop = DesktopSession(desktop_id=desktop_id, position=desktop_position)
            grid.desktops[desktop_id] = desktop

            for quadrant in QUADRANTS:
                try:
                    task = next(task_iter)
                except StopIteration:
                    return grid_id

                win_session, tab_id = await self._create_positioned_window(
                    desktop_id=desktop_id,
                    quadrant=quadrant,
                    half_w=half_w,
                    half_h=half_h,
                    screen_w=screen_w,
                    screen_h=screen_h,
                    task=task,
                    profile=profile,
                )
                desktop.windows[quadrant] = win_session

            desktop_position += 1

        return grid_id

    async def _activate_desktop(self, position: int) -> None:
        """Activate a Desktop by ordinal position via AppleScript."""
        script = f'''
        tell application "System Events"
            tell application process "Dock"
                keystroke "{position}" using {{control down, command down}}
            end tell
        end tell
        '''
        await self._adapter._run_applescript(script)
        await asyncio.sleep(0.3)

    async def send_to_session(self, grid_id: str, session_id: str, command: str) -> None:
        """Send a command to a specific session."""
        grid = self._grids.get(grid_id)
        if not grid:
            raise GridNotFoundError(grid_id)

        found = grid.find_session(session_id)
        if not found:
            raise SessionNotFoundError(session_id, grid_id=grid_id)

        desktop, window = found
        escaped = command.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
        tell application "iTerm2"
            set targetWindow to window named "{window.window_name}"
            tell targetWindow
                tell current session
                    write text "{escaped}"
                end tell
            end tell
        end tell
        '''
        await self._adapter._run_applescript(script)

    async def capture_session_output(self, grid_id: str, session_id: str) -> str:
        """Capture output from a session.

        AppleScript cannot read terminal buffer. Returns a placeholder message
        directing users to the mcpretentious adapter for actual output capture.
        """
        grid = self._grids.get(grid_id)
        if not grid:
            raise GridNotFoundError(grid_id)

        found = grid.find_session(session_id)
        if not found:
            raise SessionNotFoundError(session_id, grid_id=grid_id)

        _, window = found
        return (
            f"[Output capture not available via AppleScript]\n"
            f"Session: {session_id}\n"
            f"Window: {window.window_name}\n"
            f"Use mcpretentious adapter for output capture"
        )

    async def broadcast_to_grid(self, grid_id: str, command: str) -> None:
        """Send a command to all sessions in the grid."""
        grid = self._grids.get(grid_id)
        if not grid:
            raise GridNotFoundError(grid_id)

        for window in grid.all_sessions():
            await self.send_to_session(grid_id, window.session_id, command)

    async def close_grid(self, grid_id: str) -> None:
        """Close all windows and tear down all desktops for a grid."""
        grid = self._grids.get(grid_id)
        if not grid:
            raise GridNotFoundError(grid_id)

        script = f'''
        tell application "iTerm2"
            repeat with w in windows
                if name of w starts with "{grid_id}_" then
                    close w
                end if
            end repeat
        end tell
        '''
        try:
            await self._adapter._run_applescript(script)
        except RuntimeError as e:
            logger.warning(f"Error closing grid {grid_id}: {e}")

        grid.status = GridStatus.CLOSED
        logger.info(f"Closed terminal grid {grid_id}")

    async def list_grid_sessions(self, grid_id: str) -> list[dict]:
        """Return full 3-level session tree as list of dicts."""
        grid = self._grids.get(grid_id)
        if not grid:
            raise GridNotFoundError(grid_id)

        result = []
        for desktop in grid.desktops.values():
            for window in desktop.windows.values():
                result.append({
                    "grid_id": grid_id,
                    "desktop_id": desktop.desktop_id,
                    "desktop_position": desktop.position,
                    "window_name": window.window_name,
                    "tab_id": window.tab_id,
                    "session_id": window.session_id,
                    "task": window.task,
                    "bounds": window.bounds,
                    "quadrant": window.quadrant,
                })
        return result

    def get_grid(self, grid_id: str) -> GridSession | None:
        """Retrieve grid by id."""
        return self._grids.get(grid_id)