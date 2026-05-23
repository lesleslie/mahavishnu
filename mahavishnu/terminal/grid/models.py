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