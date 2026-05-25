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
