"""Unit tests for ``mahavishnu.terminal.grid.exceptions``.

The grid module defines a small exception hierarchy rooted at ``GridError``.
These tests verify message construction, attribute storage, and inheritance.
"""

from __future__ import annotations

import pytest

from mahavishnu.terminal.grid.exceptions import (
    DesktopCreationError,
    GridError,
    GridNotFoundError,
    MultiDesktopUnavailableError,
    SessionNotFoundError,
    WindowTilingError,
)

# =============================================================================
# GridError Tests
# =============================================================================


class TestGridError:
    """Tests for the base GridError class."""

    def test_basic_message(self):
        e = GridError("oops")
        assert str(e) == "oops"
        assert e.grid_id is None
        assert e.context == {}

    def test_with_grid_id(self):
        e = GridError("oops", grid_id="g1")
        assert e.grid_id == "g1"
        assert "g1" not in str(e)  # grid_id is metadata, not part of message

    def test_with_extra_context(self):
        e = GridError("oops", grid_id="g1", reason="timeout", code=42)
        assert e.context == {"reason": "timeout", "code": 42}
        assert e.grid_id == "g1"

    def test_is_exception(self):
        # Must inherit from Exception so it can be raised/caught normally
        e = GridError("oops")
        assert isinstance(e, Exception)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(GridError, match="oops"):
            raise GridError("oops")


# =============================================================================
# GridNotFoundError Tests
# =============================================================================


class TestGridNotFoundError:
    """Tests for GridNotFoundError."""

    def test_message_includes_grid_id(self):
        e = GridNotFoundError("g-123")
        assert "g-123" in str(e)

    def test_stores_grid_id(self):
        e = GridNotFoundError("g-123")
        assert e.grid_id == "g-123"

    def test_is_grid_error(self):
        e = GridNotFoundError("g-123")
        assert isinstance(e, GridError)

    def test_can_be_caught_as_grid_error(self):
        with pytest.raises(GridError):
            raise GridNotFoundError("g-123")


# =============================================================================
# DesktopCreationError Tests
# =============================================================================


class TestDesktopCreationError:
    """Tests for DesktopCreationError."""

    def test_message(self):
        e = DesktopCreationError("spaces disabled")
        assert "spaces disabled" in str(e)
        assert e.grid_id is None

    def test_with_grid_id(self):
        e = DesktopCreationError("spaces disabled", grid_id="g-7")
        assert e.grid_id == "g-7"
        # The base class captures explicit grid_id, so context stays empty
        assert e.context == {}

    def test_is_grid_error(self):
        e = DesktopCreationError("spaces disabled")
        assert isinstance(e, GridError)


# =============================================================================
# WindowTilingError Tests
# =============================================================================


class TestWindowTilingError:
    """Tests for WindowTilingError."""

    def test_message_and_window_name(self):
        e = WindowTilingError("w1", "bounds invalid")
        assert "bounds invalid" in str(e)
        assert e.context == {"window_name": "w1"}

    def test_with_grid_id(self):
        e = WindowTilingError("w1", "bounds invalid", grid_id="g-2")
        assert e.grid_id == "g-2"
        # grid_id is captured explicitly by the base class; window_name is the only context kwarg
        assert e.context == {"window_name": "w1"}

    def test_is_grid_error(self):
        e = WindowTilingError("w1", "bounds invalid")
        assert isinstance(e, GridError)


# =============================================================================
# SessionNotFoundError Tests
# =============================================================================


class TestGridSessionNotFoundError:
    """Tests for SessionNotFoundError (the grid-specific one)."""

    def test_message_includes_session_id(self):
        e = SessionNotFoundError("s-99")
        assert "s-99" in str(e)
        assert e.context == {"session_id": "s-99"}

    def test_with_grid_id(self):
        e = SessionNotFoundError("s-99", grid_id="g-2")
        assert e.grid_id == "g-2"
        # grid_id is captured explicitly by the base class
        assert e.context == {"session_id": "s-99"}

    def test_is_grid_error(self):
        e = SessionNotFoundError("s-99")
        assert isinstance(e, GridError)


# =============================================================================
# MultiDesktopUnavailableError Tests
# =============================================================================


class TestMultiDesktopUnavailableError:
    """Tests for MultiDesktopUnavailableError."""

    def test_is_grid_error(self):
        e = MultiDesktopUnavailableError("multi-desktop unavailable")
        assert isinstance(e, GridError)
        assert "multi-desktop unavailable" in str(e)


# =============================================================================
# Parameterised Inheritance Tests
# =============================================================================


@pytest.mark.parametrize(
    "exc_cls,args,kwargs",
    [
        (GridNotFoundError, ("g",), {}),
        (DesktopCreationError, ("msg",), {}),
        (DesktopCreationError, ("msg",), {"grid_id": "g"}),
        (WindowTilingError, ("w", "msg"), {}),
        (WindowTilingError, ("w", "msg"), {"grid_id": "g"}),
        (SessionNotFoundError, ("s",), {}),
        (SessionNotFoundError, ("s",), {"grid_id": "g"}),
        (MultiDesktopUnavailableError, ("msg",), {}),
    ],
)
def test_all_grid_errors_inherit_from_grid_error(exc_cls, args, kwargs):
    """All concrete grid exceptions must ultimately inherit from GridError."""
    instance = exc_cls(*args, **kwargs)
    assert isinstance(instance, GridError)
    assert isinstance(instance, Exception)
