---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: terminal-grid
---

# Terminal Grid Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Goal:** Implement terminal grid orchestration via pure AppleScript + iTerm2 window bounds, deploying worker sessions across macOS Desktops/Spaces in a 2×2 quadrant layout per desktop.
> **Architecture:** Three-level identity hierarchy (Grid → Desktop → Window → Tab → Session). ITerm2Adapter refactored to use shared async AppleScript bridge in mcp-common. TerminalGridManager orchestrates multi-desktop deployment with single-desktop fallback. mcpretentious adapter handles output capture (AppleScript cannot read terminal buffer).
> **Tech Stack:** Python 3.13+, asyncio, AppleScript/osascript, iTerm2, standard library only.

______________________________________________________________________

## File Structure

```
mcp-common/mcp_common/apple_script/
├── __init__.py
├── bridge.py              ← shared async AppleScript bridge (run script → str)
└── exceptions.py         ← AppleScriptError, ScriptTimeoutError

mahavishnu/terminal/
├── adapters/
│   ├── base.py           ← TerminalAdapter (existing)
│   ├── iterm2.py         ← ITerm2Adapter (refactor to use shared bridge)
│   └── mcpretentious.py  ← For output capture (existing)
├── grid/
│   ├── __init__.py
│   ├── manager.py        ← TerminalGridManager
│   ├── models.py         ← GridSession, DesktopSession, WindowSession
│   └── exceptions.py    ← GridError hierarchy
└── (existing files unchanged)

tests/unit/
├── test_terminal_adapters_iterm2.py  ← existing, update for refactor
└── test_terminal_grid.py             ← new, TerminalGridManager tests
```

______________________________________________________________________

## Phase 1: Shared AppleScript Bridge

### Task 1: Create mcp-common/apple_script/ Package

**Files:**

- Create: `mcp-common/mcp_common/apple_script/__init__.py`

- Create: `mcp-common/mcp_common/apple_script/exceptions.py`

- Create: `mcp-common/mcp_common/apple_script/bridge.py`

- Test: (no direct test — exercised via iterm2 adapter tests)

- [ ] **Step 1: Write exceptions**

```python
# mcp-common/mcp_common/apple_script/exceptions.py
class AppleScriptError(Exception):
    """Raised when AppleScript execution fails."""

    def __init__(self, message: str | None = None, stderr: str | None = None):
        self.stderr = stderr
        msg = message or stderr or "AppleScript execution failed"
        super().__init__(msg)


class ScriptTimeoutError(AppleScriptError):
    """Raised when AppleScript times out."""

    def __init__(self, message: str):
        super().__init__(message)
```

- [ ] **Step 2: Write bridge**

```python
# mcp-common/mcp_common/apple_script/bridge.py
"""Async AppleScript bridge for macOS subprocess execution."""

import asyncio
import shutil

from .exceptions import AppleScriptError, ScriptTimeoutError

OSASCRIPT_AVAILABLE = shutil.which("osascript") is not None


async def run(script: str, timeout: float = 30.0) -> str:
    """Run an AppleScript and return output.

    Args:
        script: AppleScript source to execute.
        timeout: Seconds before killing subprocess (default 30).

    Returns:
        stdout as decoded string.

    Raises:
        AppleScriptError: osascript not available (non-macOS) or non-zero exit.
        ScriptTimeoutError: Subprocess exceeded timeout.
    """
    if not OSASCRIPT_AVAILABLE:
        raise AppleScriptError("osascript not available (macOS only)")

    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript",
            "-e",
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            err = stderr.decode().strip() if stderr else "Unknown AppleScript error"
            raise AppleScriptError(stderr=err)
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        proc.kill()
        raise ScriptTimeoutError(f"AppleScript timed out after {timeout}s")
    except Exception as e:
        raise AppleScriptError(f"Failed to run AppleScript: {e}") from e
```

- [ ] **Step 3: Write __init__**

```python
# mcp-common/mcp_common/apple_script/__init__.py
"""AppleScript bridge shared across mcp-common and mahavishnu."""

from .bridge import OSASCRIPT_AVAILABLE, run
from .exceptions import AppleScriptError, ScriptTimeoutError

__all__ = ["run", "OSASCRIPT_AVAILABLE", "AppleScriptError", "ScriptTimeoutError"]
```

- [ ] **Step 4: Run test to verify bridge is importable**

```bash
cd /Users/les/Projects/mcp-common && python -c "from mcp_common.apple_script import run, OSASCRIPT_AVAILABLE; print('OK', OSASCRIPT_AVAILABLE)"
```

Expected: `OK True` (on macOS) or graceful failure with clear message on non-macOS

______________________________________________________________________

### Task 2: Refactor iterm2.py to Use Shared Bridge

**Files:**

- Modify: `mahavishnu/terminal/adapters/iterm2.py:75-104`

- [ ] **Step 1: Add import at top of iterm2.py**

After `from .base import TerminalAdapter`, add:

```python
from mcp_common.apple_script import run as _apple_script_run, OSASCRIPT_AVAILABLE as _OSASCRIPT_AVAILABLE
```

- [ ] **Step 2: Replace OSASCRIPT_AVAILABLE usage**

Update the `OSASCRIPT_AVAILABLE` module-level flag:

```python
# Use shared flag from mcp-common
OSASCRIPT_AVAILABLE = _OSASCRIPT_AVAILABLE
ITERM2_AVAILABLE = OSASCRIPT_AVAILABLE  # legacy export
```

- [ ] **Step 3: Replace \_run_applescript body**

Replace lines 75–104 (`async def _run_applescript`) with:

```python
    async def _run_applescript(self, script: str) -> str:
        """Run an AppleScript and return output."""
        return await _apple_script_run(script)
```

- [ ] **Step 4: Run existing iTerm2 tests**

```bash
pytest tests/unit/test_terminal_adapters_iterm2.py -v --tb=short 2>&1 | head -60
```

Expected: All 18 tests pass (or skip gracefully on non-macOS).

- [ ] **Step 5: Commit**

```bash
git add mcp-common/mcp_common/apple_script/ mahavishnu/terminal/adapters/iterm2.py
git commit -m "feat(terminal): extract shared AppleScript bridge to mcp-common

Phase 1 of terminal grid orchestration.
Refactors ITerm2Adapter to use the new shared async bridge so that
TerminalGridManager can also use it without duplicating subprocess logic."
```

______________________________________________________________________

## Phase 2: Grid Data Model

### Task 3: Create terminal/grid/ Models and Exceptions

**Files:**

- Create: `mahavishnu/terminal/grid/__init__.py`

- Create: `mahavishnu/terminal/grid/exceptions.py`

- Create: `mahavishnu/terminal/grid/models.py`

- Test: `tests/unit/test_terminal_grid_models.py`

- [ ] **Step 1: Write exceptions**

```python
# mahavishnu/terminal/grid/exceptions.py
"""Grid exception hierarchy."""

from typing import Any


class GridError(Exception):
    """Base exception for terminal grid errors."""

    def __init__(self, message: str, grid_id: str | None = None, **context: Any):
        self.grid_id = grid_id
        self.context = context
        super().__init__(message)


class GridNotFoundError(GridError):
    """Raised when grid_id not found."""

    def __init__(self, grid_id: str):
        super().__init__(f"Grid {grid_id} not found", grid_id=grid_id)


class DesktopCreationError(GridError):
    """Raised when multi-desktop Space creation fails."""

    def __init__(self, message: str, grid_id: str | None = None):
        super().__init__(message, grid_id=grid_id)


class WindowTilingError(GridError):
    """Raised when window bounds-setting fails."""

    def __init__(self, window_name: str, message: str, grid_id: str | None = None):
        super().__init__(message, grid_id=grid_id, window_name=window_name)


class SessionNotFoundError(GridError):
    """Raised when session_id not found within a grid."""

    def __init__(self, session_id: str, grid_id: str | None = None):
        super().__init__(f"Session {session_id} not found", grid_id=grid_id, session_id=session_id)


class MultiDesktopUnavailableError(GridError):
    """Raised when multi-desktop is requested but Spaces automation fails."""
```

- [ ] **Step 2: Write models**

```python
# mahavishnu/terminal/grid/models.py
"""Terminal grid data model."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class GridStatus(Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class Quadrant(Enum):
    TOP_LEFT = "tl"
    TOP_RIGHT = "tr"
    BOTTOM_LEFT = "bl"
    BOTTOM_RIGHT = "br"


@dataclass
class WindowSession:
    window_name: str
    tab_id: str | None
    session_id: str
    task: str
    bounds: dict[str, int]  # {"x": int, "y": int, "w": int, "h": int}
    quadrant: Literal["tl", "tr", "bl", "br"]


@dataclass
class DesktopSession:
    desktop_id: str  # iTerm2 unique window ID acting as desktop proxy
    position: int     # 1-indexed ordinal
    windows: dict[str, WindowSession] = field(default_factory=dict)


@dataclass
class GridSession:
    grid_id: str
    created_at: datetime
    desktops: dict[str, DesktopSession] = field(default_factory=dict)
    task_count: int = 0
    status: GridStatus = GridStatus.ACTIVE

    def find_session(self, session_id: str):
        """Find (desktop, window) pair for a session_id."""
        for desktop in self.desktops.values():
            for window in desktop.windows.values():
                if window.session_id == session_id:
                    return desktop, window
        return None

    def all_sessions(self):
        """Flatten to list of WindowSession."""
        return [w for d in self.desktops.values() for w in d.windows.values()]
```

- [ ] **Step 3: Write __init__**

```python
# mahavishnu/terminal/grid/__init__.py
"""Terminal grid orchestration."""

from .exceptions import (
    DesktopCreationError,
    GridError,
    GridNotFoundError,
    MultiDesktopUnavailableError,
    SessionNotFoundError,
    WindowTilingError,
)
from .models import DesktopSession, GridSession, GridStatus, Quadrant, WindowSession
from .manager import TerminalGridManager

__all__ = [
    "TerminalGridManager",
    "GridSession",
    "DesktopSession",
    "WindowSession",
    "GridStatus",
    "Quadrant",
    "GridError",
    "GridNotFoundError",
    "DesktopCreationError",
    "WindowTilingError",
    "SessionNotFoundError",
    "MultiDesktopUnavailableError",
]
```

- [ ] **Step 4: Write failing test for models**

```python
# tests/unit/test_terminal_grid_models.py
"""Unit tests for terminal grid models."""

from datetime import datetime

import pytest

from mahavishnu.terminal.grid import (
    DesktopSession,
    GridSession,
    GridStatus,
    Quadrant,
    WindowSession,
)


class TestGridSession:
    def test_find_session(self):
        desktop = DesktopSession(desktop_id="win1", position=1)
        window = WindowSession(
            window_name="grid_abc_d1_win_tl",
            tab_id="tab1",
            session_id="sess_001",
            task="echo hi",
            bounds={"x": 0, "y": 0, "w": 960, "h": 540},
            quadrant="tl",
        )
        desktop.windows["tl"] = window
        grid = GridSession(grid_id="grid_abc", created_at=datetime.now(), desktops={"d1": desktop})

        result = grid.find_session("sess_001")
        assert result is not None
        assert result[0].desktop_id == "win1"
        assert result[1].session_id == "sess_001"

    def test_find_session_not_found(self):
        grid = GridSession(grid_id="grid_abc", created_at=datetime.now())
        assert grid.find_session("nonexistent") is None

    def test_all_sessions(self):
        d1 = DesktopSession(desktop_id="win1", position=1)
        d1.windows["tl"] = WindowSession("tl", "tab1", "s1", "task1", {}, "tl")
        d1.windows["tr"] = WindowSession("tr", "tab2", "s2", "task2", {}, "tr")
        grid = GridSession(grid_id="g1", created_at=datetime.now(), desktops={"d1": d1})

        all_sess = grid.all_sessions()
        assert len(all_sess) == 2
        assert {s.session_id for s in all_sess} == {"s1", "s2"}
```

- [ ] **Step 5: Run model tests**

```bash
cd /Users/les/Projects/mahavishnu && pytest tests/unit/test_terminal_grid_models.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/terminal/grid/ tests/unit/test_terminal_grid_models.py
git commit -m "feat(terminal): add grid models and exception hierarchy

Phase 2 of terminal grid orchestration.
Adds GridSession, DesktopSession, WindowSession dataclasses and the full
GridError exception family (GridNotFoundError, SessionNotFoundError, etc.)."
```

______________________________________________________________________

## Phase 3: TerminalGridManager

### Task 4: Write TerminalGridManager

**Files:**

- Create: `mahavishnu/terminal/grid/manager.py`

- Create: `tests/unit/test_terminal_grid.py`

- Modify: `mahavishnu/terminal/grid/__init__.py`

- [ ] **Step 1: Write the manager (imports, constructor, \_get_primary_screen_bounds)**

```python
# mahavishnu/terminal/grid/manager.py
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
```

- [ ] **Step 2: Write failing integration test**

```python
# tests/unit/test_terminal_grid.py
"""Unit tests for TerminalGridManager."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.terminal.grid import (
    DesktopSession,
    GridSession,
    GridStatus,
    TerminalGridManager,
    WindowSession,
)
from mahavishnu.terminal.grid.exceptions import (
    GridNotFoundError,
    SessionNotFoundError,
)


@pytest.fixture
def mock_adapter():
    """Mock ITerm2Adapter for testing."""
    adapter = MagicMock()
    adapter._run_applescript = AsyncMock(return_value="tab_123")
    return adapter


@pytest.fixture
def manager(mock_adapter):
    return TerminalGridManager(mock_adapter)


class TestTerminalGridManager:
    def test_manager_name(self, manager):
        assert hasattr(manager, "_grids")
        assert hasattr(manager, "_adapter")

    @pytest.mark.asyncio
    async def test_deploy_single_desktop_four_tasks(self, manager, mock_adapter):
        """4 tasks fill tl,tr,bl,br on single desktop."""
        mock_adapter._run_applescript = AsyncMock(return_value="tab_123")

        with patch.object(manager, "_get_primary_screen_bounds", return_value=(0, 0, 1920, 1080)):
            with patch.object(manager, "_create_desktop_via_spaces", return_value=False):
                grid_id = await manager.deploy_terminal_grid(
                    tasks=["echo 1", "echo 2", "echo 3", "echo 4"]
                )

        assert grid_id.startswith("grid_")
        grid = manager.get_grid(grid_id)
        assert grid is not None
        assert grid.status == GridStatus.ACTIVE
        all_sessions = grid.all_sessions()
        assert len(all_sessions) == 4
        assert {s.task for s in all_sessions} == {"echo 1", "echo 2", "echo 3", "echo 4"}

    @pytest.mark.asyncio
    async def test_send_to_session(self, manager, mock_adapter):
        """send_to_session sends to correct window by session_id."""
        mock_adapter._run_applescript = AsyncMock(return_value="")

        grid_id = "grid_test"
        desktop = DesktopSession(desktop_id="win1", position=1)
        desktop.windows["tl"] = WindowSession(
            window_name="grid_test_d1_win_tl",
            tab_id="tab_123",
            session_id="sess_001",
            task="echo hi",
            bounds={"x": 0, "y": 0, "w": 960, "h": 540},
            quadrant="tl",
        )
        grid = GridSession(grid_id=grid_id, created_at=datetime.now(), desktops={"d1": desktop})
        manager._grids[grid_id] = grid

        await manager.send_to_session(grid_id, "sess_001", "ls -la")

        mock_adapter._run_applescript.assert_called()
        call_args = mock_adapter._run_applescript.call_args[0][0]
        assert "write text" in call_args
        assert "ls -la" in call_args
        assert "grid_test_d1_win_tl" in call_args

    @pytest.mark.asyncio
    async def test_send_to_session_not_found(self, manager):
        """SessionNotFoundError raised for unknown session."""
        grid_id = "grid_test"
        manager._grids[grid_id] = GridSession(grid_id=grid_id, created_at=datetime.now())

        with pytest.raises(SessionNotFoundError):
            await manager.send_to_session(grid_id, "nonexistent", "test")

    @pytest.mark.asyncio
    async def test_broadcast_to_grid(self, manager, mock_adapter):
        """broadcast_to_grid sends to all sessions."""
        mock_adapter._run_applescript = AsyncMock(return_value="")

        grid_id = "grid_bcast"
        desktop = DesktopSession(desktop_id="win1", position=1)
        desktop.windows["tl"] = WindowSession("tl", "tab1", "s1", "task1", {}, "tl")
        desktop.windows["tr"] = WindowSession("tr", "tab2", "s2", "task2", {}, "tr")
        grid = GridSession(grid_id=grid_id, created_at=datetime.now(), desktops={"d1": desktop})
        manager._grids[grid_id] = grid

        await manager.broadcast_to_grid(grid_id, "echo broadcast")

        assert mock_adapter._run_applescript.call_count == 2
        for call in mock_adapter._run_applescript.call_args_list:
            args = call[0][0]
            assert "echo broadcast" in args

    @pytest.mark.asyncio
    async def test_close_grid(self, manager, mock_adapter):
        """close_grid closes all windows and marks status closed."""
        mock_adapter._run_applescript = AsyncMock(return_value="")

        grid_id = "grid_close"
        desktop = DesktopSession(desktop_id="win1", position=1)
        desktop.windows["tl"] = WindowSession("tl", "tab1", "s1", "task1", {}, "tl")
        grid = GridSession(grid_id=grid_id, created_at=datetime.now(), desktops={"d1": desktop})
        manager._grids[grid_id] = grid

        await manager.close_grid(grid_id)

        call_args = mock_adapter._run_applescript.call_args[0][0]
        assert "close w" in call_args
        assert grid.status == GridStatus.CLOSED

    @pytest.mark.asyncio
    async def test_list_grid_sessions(self, manager):
        """list_grid_sessions returns full 3-level tree as flat list."""
        grid_id = "grid_list"
        desktop = DesktopSession(desktop_id="win1", position=1)
        desktop.windows["tl"] = WindowSession("tl", "tab1", "s1", "task1", {}, "tl")
        desktop.windows["tr"] = WindowSession("tr", "tab2", "s2", "task2", {}, "tr")
        grid = GridSession(grid_id=grid_id, created_at=datetime.now(), desktops={"d1": desktop})
        manager._grids[grid_id] = grid

        sessions = await manager.list_grid_sessions(grid_id)

        assert len(sessions) == 2
        assert sessions[0]["grid_id"] == grid_id
        assert sessions[0]["desktop_id"] == "win1"
        assert sessions[0]["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_capture_session_output_placeholder(self, manager):
        """capture_session_output returns a clear placeholder."""
        grid_id = "grid_capture"
        desktop = DesktopSession(desktop_id="win1", position=1)
        desktop.windows["tl"] = WindowSession("tl", "tab1", "s1", "task1", {}, "tl")
        grid = GridSession(grid_id=grid_id, created_at=datetime.now(), desktops={"d1": desktop})
        manager._grids[grid_id] = grid

        output = await manager.capture_session_output(grid_id, "s1")

        assert "Output capture not available via AppleScript" in output
        assert "mcpretentious" in output
```

- [ ] **Step 3: Run grid tests**

```bash
cd /Users/les/Projects/mahavishnu && pytest tests/unit/test_terminal_grid.py -v --tb=short
```

Expected: FAIL (manager not yet saved to file)

- [ ] **Step 4: Write manager.py to file**

Write the full manager.py content to `mahavishnu/terminal/grid/manager.py`.

- [ ] **Step 5: Re-run tests**

```bash
cd /Users/les/Projects/mahavishnu && pytest tests/unit/test_terminal_grid.py -v --tb=short
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add mahavishnu/terminal/grid/manager.py tests/unit/test_terminal_grid.py
git commit -m "feat(terminal): add TerminalGridManager for grid orchestration

Phase 3 of terminal grid orchestration.
TerminalGridManager.deploy_terminal_grid() creates iTerm2 windows in 2x2
quadrant layout per desktop with multi-desktop fallback, session tracking,
broadcast/send primitives, and mcpretentious output-capture placeholder."
```

______________________________________________________________________

## Spec Coverage Check

| Spec item | Implementation |
|-----------|----------------|
| 2x2 quadrant layout per desktop | `_create_positioned_window` + `QUADRANT_BOUNDS` |
| Multi-desktop via Spaces (Ctrl+Cmd+Space) | `_create_desktop_via_spaces` |
| Single-desktop fallback | `allow_multi_desktop=False` path in `deploy_terminal_grid` |
| Identity hierarchy: desktop_id→window_name→tab_id→session_id | `GridSession→DesktopSession→WindowSession` model |
| send_to_session | `TerminalGridManager.send_to_session` |
| broadcast_to_grid | `TerminalGridManager.broadcast_to_grid` |
| mcpretentious for output capture | `capture_session_output` placeholder directing to mcpretentious |
| Shared AppleScript bridge | `mcp-common/apple_script/bridge.py` |
| Close by name prefix | `close_grid` AppleScript loop with `name of w starts with` |
| Exception hierarchy | `exceptions.py` with `GridNotFoundError`, `SessionNotFoundError`, etc. |
| TDD, bite-sized steps, per-phase commits | Each phase commits separately |

______________________________________________________________________

## Out of Scope (from spec, not implemented)

- Dynamic resize of active grids
- Non-primary display support
- Tab creation within windows (each window = one session = one tab)
- Focus-stealing input without visible session targeting
