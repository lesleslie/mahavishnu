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