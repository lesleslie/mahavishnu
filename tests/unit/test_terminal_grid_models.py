"""Unit tests for mahavishnu.terminal.grid.models data classes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mahavishnu.terminal.grid.models import (
    DesktopSession,
    GridSession,
    GridStatus,
    Quadrant,
    WindowSession,
)

# ---------------------------------------------------------------------------
# Enum value pinning
# ---------------------------------------------------------------------------


def test_grid_status_values() -> None:
    assert GridStatus.ACTIVE.value == "active"
    assert GridStatus.CLOSED.value == "closed"


def test_quadrant_values_match_window_quadrant_literal() -> None:
    """Quadrant enum codes must equal the WindowSession.quadrant Literal type."""
    assert {q.value for q in Quadrant} == {"tl", "tr", "bl", "br"}


# ---------------------------------------------------------------------------
# WindowSession
# ---------------------------------------------------------------------------


def test_window_session_stores_all_fields() -> None:
    window = WindowSession(
        window_name="grid_abc_d1_win_tl",
        tab_id="tab-42",
        session_id="sess-001",
        task="echo hi",
        bounds={"x": 0, "y": 0, "w": 960, "h": 540},
        quadrant="tl",
    )

    assert window.window_name == "grid_abc_d1_win_tl"
    assert window.tab_id == "tab-42"
    assert window.session_id == "sess-001"
    assert window.task == "echo hi"
    assert window.bounds == {"x": 0, "y": 0, "w": 960, "h": 540}
    assert window.quadrant == "tl"


def test_window_session_tab_id_optional() -> None:
    window = WindowSession(
        window_name="w",
        tab_id=None,
        session_id="s1",
        task="t",
        bounds={},
        quadrant="tr",
    )
    assert window.tab_id is None


@pytest.mark.parametrize("quadrant", ["tl", "tr", "bl", "br"])
def test_window_session_accepts_each_quadrant_literal(quadrant: str) -> None:
    window = WindowSession("w", "t", "s", "task", {}, quadrant)
    assert window.quadrant == quadrant


# ---------------------------------------------------------------------------
# DesktopSession
# ---------------------------------------------------------------------------


def test_desktop_session_defaults_to_empty_windows() -> None:
    desktop = DesktopSession(desktop_id="win-1", position=1)
    assert desktop.desktop_id == "win-1"
    assert desktop.position == 1
    assert desktop.windows == {}


def test_desktop_session_window_mutation_independent() -> None:
    """Two default-constructed desktops must have separate window dicts."""
    d1 = DesktopSession(desktop_id="d1", position=1)
    d2 = DesktopSession(desktop_id="d2", position=2)

    d1.windows["tl"] = WindowSession("w", "tab", "s", "task", {}, "tl")

    assert d2.windows == {}


# ---------------------------------------------------------------------------
# GridSession.find_session
# ---------------------------------------------------------------------------


def _make_grid() -> GridSession:
    """Build a 2-desktop, 3-window grid for traversal tests."""
    d1 = DesktopSession(desktop_id="win-1", position=1)
    d1.windows["tl"] = WindowSession(
        window_name="g_d1_tl",
        tab_id="t1",
        session_id="sess-a",
        task="t1",
        bounds={},
        quadrant="tl",
    )
    d1.windows["tr"] = WindowSession(
        window_name="g_d1_tr",
        tab_id="t2",
        session_id="sess-b",
        task="t2",
        bounds={},
        quadrant="tr",
    )

    d2 = DesktopSession(desktop_id="win-2", position=2)
    d2.windows["bl"] = WindowSession(
        window_name="g_d2_bl",
        tab_id="t3",
        session_id="sess-c",
        task="t3",
        bounds={},
        quadrant="bl",
    )

    return GridSession(
        grid_id="grid-xyz",
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        desktops={"d1": d1, "d2": d2},
    )


def test_find_session_returns_desktop_and_window_tuple() -> None:
    grid = _make_grid()

    result = grid.find_session("sess-b")

    assert result is not None
    desktop, window = result
    assert desktop.desktop_id == "win-1"
    assert window.session_id == "sess-b"
    assert window.quadrant == "tr"


def test_find_session_searches_all_desktops() -> None:
    """The search must not stop at the first desktop."""
    grid = _make_grid()

    result = grid.find_session("sess-c")

    assert result is not None
    desktop, window = result
    assert desktop.desktop_id == "win-2"
    assert window.session_id == "sess-c"


def test_find_session_returns_none_for_missing_id() -> None:
    grid = _make_grid()
    assert grid.find_session("nonexistent") is None


def test_find_session_returns_none_on_empty_grid() -> None:
    grid = GridSession(grid_id="g", created_at=datetime.now())
    assert grid.find_session("anything") is None


# ---------------------------------------------------------------------------
# GridSession.all_sessions
# ---------------------------------------------------------------------------


def test_all_sessions_flattens_all_desktops_and_windows() -> None:
    grid = _make_grid()
    sessions = grid.all_sessions()

    assert [s.session_id for s in sessions] == ["sess-a", "sess-b", "sess-c"]


def test_all_sessions_returns_empty_list_for_empty_grid() -> None:
    grid = GridSession(grid_id="g", created_at=datetime.now())
    assert grid.all_sessions() == []


def test_all_sessions_handles_desktop_with_no_windows() -> None:
    """Desktops with empty windows dicts should be skipped, not crash."""
    d_empty = DesktopSession(desktop_id="empty", position=1)
    d_full = DesktopSession(desktop_id="full", position=2)
    d_full.windows["tl"] = WindowSession("w", "t", "s1", "task", {}, "tl")

    grid = GridSession(
        grid_id="g",
        created_at=datetime.now(),
        desktops={"empty": d_empty, "full": d_full},
    )

    sessions = grid.all_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_id == "s1"


# ---------------------------------------------------------------------------
# GridSession defaults
# ---------------------------------------------------------------------------


def test_grid_session_default_status_is_active() -> None:
    grid = GridSession(grid_id="g", created_at=datetime.now())
    assert grid.status == GridStatus.ACTIVE
    assert grid.task_count == 0
    assert grid.desktops == {}


def test_grid_session_status_can_be_set_to_closed() -> None:
    grid = GridSession(
        grid_id="g",
        created_at=datetime.now(),
        status=GridStatus.CLOSED,
        task_count=4,
    )
    assert grid.status == GridStatus.CLOSED
    assert grid.task_count == 4
