# Terminal Grid Orchestration — Design Spec

**Date:** 2026-05-22
**Approach:** Pure AppleScript + iTerm2 window bounds (zero external dependencies)
**Status:** Approved for implementation

---

## 1. Overview

Deploy a grid of iTerm2 terminal sessions across multiple macOS Spaces (Desktops), one session per window, arranged in a 2×2 quadrant layout, with full programmatic control at every level of the identity hierarchy.

**Primary motivation:** Enable monitored, interactive terminal sessions for pool workers where each worker's terminal is isolated to its own window — with the ability to send input and monitor output without stealing focus.

---

## 2. Architecture

### 2.1 Identity Hierarchy

Three-level tracking tree:

```
Grid (grid_id)
└── Desktop (desktop_id)     ← iTerm2 window acting as desktop proxy
    └── Window (window_name)  ← iTerm2 window name (quadrant handle)
        └── Tab (tab_id)      ← iTerm2 unique tab id
            └── Session (session_id)  ← internal UUID[:8]
```

### 2.2 Module Layout

```
mahavishnu/terminal/
├── adapters/
│   ├── base.py              ← TerminalAdapter (existing)
│   ├── iterm2.py             ← ITerm2Adapter (existing, identity fix applied)
│   └── mcpretentious.py      ← For actual output capture (existing)
├── grid/
│   ├── __init__.py
│   ├── manager.py            ← TerminalGridManager (orchestration layer)
│   ├── models.py             ← GridSession, DesktopSession, WindowSession dataclasses
│   └── exceptions.py         ← GridError, DesktopCreationError, WindowTilingError
```

```
mcp-common/
└── apple_script/
    ├── __init__.py
    ├── bridge.py             ← async run(script: str) -> str  (shared AppleScript bridge)
    └── exceptions.py         ← AppleScriptError, ScriptTimeoutError
```

### 2.3 Shared AppleScript Bridge

Both `mcp-common/apple_script/bridge.py` and `mahavishnu/terminal/adapters/iterm2.py` will import from the shared bridge.

```python
# mcp-common/apple_script/bridge.py
import asyncio
import shutil
from .exceptions import AppleScriptError, ScriptTimeoutError

OSASCRIPT_AVAILABLE = shutil.which("osascript") is not None

async def run(script: str, timeout: float = 30.0) -> str:
    """Run an AppleScript and return output. Raises AppleScriptError on failure."""
    if not OSASCRIPT_AVAILABLE:
        raise AppleScriptError("osascript not available (macOS only)")
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e", script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            raise AppleScriptError(stderr.decode().strip() or "Unknown AppleScript error")
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        proc.kill()
        raise ScriptTimeoutError(f"AppleScript timed out after {timeout}s")
    except Exception as e:
        raise AppleScriptError(f"Failed to run AppleScript: {e}") from e
```

---

## 3. Data Model

### 3.1 GridSession

```python
@dataclass
class GridSession:
    grid_id: str                          # top-level UUID prefix "grid_"
    created_at: datetime
    desktops: dict[str, DesktopSession]  # desktop_id → DesktopSession
    task_count: int
    status: Literal["active", "closed"]

@dataclass
class DesktopSession:
    desktop_id: str                       # iTerm2 unique window ID acting as proxy
    position: int                        # 1-indexed ordinal
    windows: dict[str, WindowSession]    # window_name → WindowSession

@dataclass
class WindowSession:
    window_name: str                      # e.g. "grid_abc_d1_win_tl"
    tab_id: str | None
    session_id: str                       # internal UUID[:8]
    task: str                             # command being run
    bounds: dict[str, int]                # {"x": int, "y": int, "w": int, "h": int}
    quadrant: Literal["tl", "tr", "bl", "br"]
```

---

## 4. AppleScript Patterns

### 4.1 Create New Desktop (Spaces)

```applescript
-- Via System Events keyboard shortcut simulation (tested empirically)
tell application "System Events"
    tell application process "Dock"
        keystroke " " using {control down, command down}
    end tell
end tell
```

**Risk note:** This is the most fragile part — depends on user's Spaces hotkey binding. Fallback: skip multi-desktop, deploy all windows on current desktop (single-desktop 4-window grid).

### 4.2 Create + Position 4 Windows in Quadrants

Screen bounds: full display width/height. Quadrant size: `(width/2, height/2)` each.

```applescript
tell application "iTerm2"
    activate
    
    -- Top-left
    set w1 to (create window with default profile)
    set name of w1 to "grid_abc_d1_win_tl"
    set bounds of w1 to {0, 0, halfW, halfH}
    
    delay 0.2  -- let settle
    
    -- Top-right
    set w2 to (create window with default profile)
    set name of w2 to "grid_abc_d1_win_tr"
    set bounds of w2 to {halfW, 0, screenW, halfH}
    
    delay 0.2
    
    -- Bottom-left
    set w3 to (create window with default profile)
    set name of w3 to "grid_abc_d1_win_bl"
    set bounds of w3 to {0, halfH, halfW, screenH}
    
    delay 0.2
    
    -- Bottom-right
    set w4 to (create window with default profile)
    set name of w4 to "grid_abc_d1_win_br"
    set bounds of w4 to {halfW, halfH, screenW, screenH}
end tell
```

### 4.3 Inject Command into Named Window

```applescript
tell application "iTerm2"
    set targetWindow to window named "grid_abc_d1_win_tl"
    tell targetWindow
        tell current session
            write text "python agent-a.py"
        end tell
    end tell
end tell
```

### 4.4 Capture Unique IDs for Tracking

```applescript
tell application "iTerm2"
    set w to window named "grid_abc_d1_win_tl"
    set winID to unique id of w
    tell current session of w
        set tabID to id of it
    end tell
    return winID & "," & tabID
end tell
```

### 4.5 Close Grid (all windows by name prefix)

```applescript
tell application "iTerm2"
    repeat with w in windows
        if name of w starts with "grid_abc_" then
            close w
        end if
    end repeat
end tell
```

---

## 5. API Surface

### 5.1 TerminalGridManager

```python
class TerminalGridManager:
    def __init__(self, iterm2_adapter: ITerm2Adapter):
        self._adapter = iterm2_adapter
        self._grids: dict[str, GridSession] = {}

    async def deploy_terminal_grid(
        self,
        tasks: list[str],
        columns: int = 80,
        rows: int = 24,
        profile: str | None = None,
    ) -> str:
        """
        Deploy a terminal grid for the given tasks.
        Creates desktops → tiles windows → injects commands.
        Returns grid_id.
        """

    async def send_to_session(
        self, grid_id: str, session_id: str, command: str
    ) -> None:
        """Send a command to a specific session."""

    async def capture_session_output(
        self, grid_id: str, session_id: str
    ) -> str:
        """Capture output from a specific session (via mcpretentious adapter)."""

    async def broadcast_to_grid(self, grid_id: str, command: str) -> None:
        """Send a command to all sessions in the grid."""

    async def close_grid(self, grid_id: str) -> None:
        """Close all windows and tear down all desktops for a grid."""

    async def list_grid_sessions(self, grid_id: str) -> list[dict]:
        """Return full 3-level session tree as list of dicts."""

    def get_grid(self, grid_id: str) -> GridSession | None:
        """Retrieve grid by id."""
```

### 5.2 Quadrant Positions

Quadrant positions are computed from the screen's primary display bounds:

```python
QUADRANT_BOUNDS = {
    "tl": {"x": 0,           "y": 0,            "w": half_w, "h": half_h},
    "tr": {"x": half_w,      "y": 0,            "w": half_w, "h": half_h},
    "bl": {"x": 0,           "y": half_h,       "w": half_w, "h": half_h},
    "br": {"x": half_w,       "y": half_h,        "w": half_w, "h": half_h},
}
```

---

## 6. Single-Desktop Fallback

If multi-desktop Space creation fails or is not configured, the grid manager falls back to **single-desktop mode**:

- Creates up to 4 windows on the current Desktop in 2×2 quadrant layout
- Same `window_name` prefix scheme
- Same tracking hierarchy — just `desktop_id` is the single shared proxy

Triggered when `allow_multi_desktop=True` (default) but Space creation AppleScript returns an error.

---

## 7. mcpretentious Adapter for Output Capture

AppleScript does not support reading terminal buffer content. For output capture, the `TerminalGridManager` falls back to `mcpretentious` adapter for sessions that need streaming output. The mcpretentious adapter provides a PTY-based terminal with full output capture.

---

## 8. Exception Handling

| Exception | Cause | Recovery |
|-----------|-------|----------|
| `GridError` | Base grid exception | — |
| `DesktopCreationError` | AppleScript fails to create Space | Fall back to single-desktop |
| `WindowTilingError` | `set bounds` fails | Retry per-window, skip if persistent |
| `SessionNotFoundError` | session_id not in grid | Raise with grid context |
| `AppleScriptError` | osascript subprocess failure | Propagate from bridge |

---

## 9. Dependencies

- **macOS only** (osascript required)
- **iTerm2** must be running
- **No external deps** beyond standard library + existing mahavishnu adapters
- mcpretentious adapter used for output capture (already in codebase)

---

## 10. Out of Scope

- Window arrangement on non-primary displays (primary display only)
- Dynamic resize of active grids
- Creating tabs within windows (each window = one session = one tab)
- Sending input without focus-stealing via non-visible session targeting (limited by iTerm2 AppleScript)