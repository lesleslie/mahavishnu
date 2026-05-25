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


class TestQuadrant:
    def test_quadrant_values(self):
        assert Quadrant.TOP_LEFT.value == "tl"
        assert Quadrant.TOP_RIGHT.value == "tr"
        assert Quadrant.BOTTOM_LEFT.value == "bl"
        assert Quadrant.BOTTOM_RIGHT.value == "br"


class TestGridStatus:
    def test_status_values(self):
        assert GridStatus.ACTIVE.value == "active"
        assert GridStatus.CLOSED.value == "closed"
