"""Unit tests for iTerm2 adapter.

These tests are for the AppleScript-based iTerm2 adapter implementation.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.terminal.adapters.iterm2 import (
    ITERM2_AVAILABLE,
    ITerm2Adapter,
    OSASCRIPT_AVAILABLE,
)


@pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="osascript not available (macOS only)")
class TestITerm2Adapter:
    """Test suite for iTerm2 adapter using AppleScript."""

    @pytest.fixture
    async def adapter(self):
        """Create an iTerm2 adapter."""
        return ITerm2Adapter()

    def test_adapter_name(self):
        """Test adapter name."""
        adapter = ITerm2Adapter()
        assert adapter.adapter_name == "iterm2"

    @pytest.mark.asyncio
    async def test_launch_session(self, adapter):
        """Test launching a new iTerm2 session."""
        mock_result = "session_123"

        with patch.object(adapter, "_run_applescript", return_value=mock_result):
            with patch.object(adapter, "_ensure_iterm2_running"):
                session_id = await adapter.launch_session("echo test", columns=80, rows=24)

        assert session_id is not None
        assert len(session_id) == 8  # UUID[:8]
        assert session_id in adapter._sessions
        assert adapter._sessions[session_id]["command"] == "echo test"

    @pytest.mark.asyncio
    async def test_launch_session_with_profile(self, adapter):
        """Test launching session with custom profile."""
        mock_result = "session_456"

        with patch.object(adapter, "_run_applescript", return_value=mock_result) as mock_run:
            with patch.object(adapter, "_ensure_iterm2_running"):
                await adapter.launch_session(
                    "python -m qwen",
                    profile_name="Work",
                    new_window=True,
                )

        # Verify AppleScript was called
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "profile" in call_args.lower()
        assert "create window" in call_args.lower()

    @pytest.mark.asyncio
    async def test_send_command(self, adapter):
        """Test sending a command to a session."""
        adapter._sessions["test_session"] = {
            "command": "initial",
            "created_at": datetime.now(),
        }

        with patch.object(adapter, "_run_applescript", return_value="") as mock_run:
            await adapter.send_command("test_session", "ls -la")

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "write text" in call_args.lower()
        assert "ls -la" in call_args

    @pytest.mark.asyncio
    async def test_send_command_session_not_found(self, adapter):
        """Test error when sending to non-existent session."""
        with pytest.raises(KeyError, match="Session nonexistent not found"):
            await adapter.send_command("nonexistent", "test")

    @pytest.mark.asyncio
    async def test_capture_output(self, adapter):
        """Test capturing output from a session.

        Note: AppleScript implementation returns placeholder message.
        """
        adapter._sessions["test_session"] = {
            "command": "echo hello",
            "created_at": datetime.now(),
        }

        output = await adapter.capture_output("test_session")

        # AppleScript doesn't support buffer access
        assert "Output capture not available" in output
        assert "test_session" in output

    @pytest.mark.asyncio
    async def test_capture_output_session_not_found(self, adapter):
        """Test error when capturing from non-existent session."""
        with pytest.raises(KeyError, match="Session nonexistent not found"):
            await adapter.capture_output("nonexistent")

    @pytest.mark.asyncio
    async def test_close_session(self, adapter):
        """Test closing a session."""
        adapter._sessions["test_session"] = {
            "command": "test",
            "created_at": datetime.now(),
            "new_window": False,
        }

        with patch.object(adapter, "_run_applescript", return_value="") as mock_run:
            await adapter.close_session("test_session")

        assert "test_session" not in adapter._sessions
        mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_session_not_found(self, adapter):
        """Test closing non-existent session raises error."""
        with pytest.raises(KeyError, match="Session nonexistent not found"):
            await adapter.close_session("nonexistent")

    @pytest.mark.asyncio
    async def test_list_sessions(self, adapter):
        """Test listing all active sessions."""
        adapter._sessions = {
            "session_1": {
                "command": "echo test1",
                "created_at": datetime(2025, 1, 1, 12, 0, 0),
                "profile": None,
                "new_window": False,
            },
            "session_2": {
                "command": "echo test2",
                "created_at": datetime(2025, 1, 1, 12, 1, 0),
                "profile": "Work",
                "new_window": True,
            },
        }

        sessions = await adapter.list_sessions()

        assert len(sessions) == 2
        assert sessions[0]["id"] == "session_1"
        assert sessions[0]["command"] == "echo test1"
        assert sessions[0]["adapter"] == "iterm2"
        assert sessions[1]["profile"] == "Work"
        assert sessions[1]["new_window"] is True

    @pytest.mark.asyncio
    async def test_cleanup(self, adapter):
        """Test cleanup method closes all sessions."""
        adapter._sessions = {
            "session_1": {
                "command": "test",
                "created_at": datetime.now(),
                "new_window": False,
            },
            "session_2": {
                "command": "test2",
                "created_at": datetime.now(),
                "new_window": True,
            },
        }

        with patch.object(adapter, "_run_applescript", return_value=""):
            await adapter.cleanup()

        assert len(adapter._sessions) == 0

    @pytest.mark.asyncio
    async def test_run_applescript_success(self, adapter):
        """Test successful AppleScript execution."""
        expected_output = "test output"

        async def mock_exec(*args, **kwargs):
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(expected_output.encode(), b""))
            proc.returncode = 0
            return proc

        with patch("asyncio.create_subprocess_exec", mock_exec):
            result = await adapter._run_applescript('return "test"')

        assert result == expected_output

    @pytest.mark.asyncio
    async def test_run_applescript_failure(self, adapter):
        """Test AppleScript execution failure."""
        async def mock_exec(*args, **kwargs):
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b"", b"AppleScript error"))
            proc.returncode = 1
            return proc

        with patch("asyncio.create_subprocess_exec", mock_exec):
            with pytest.raises(RuntimeError, match="AppleScript failed"):
                await adapter._run_applescript('invalid script')

    @pytest.mark.asyncio
    async def test_ensure_iterm2_running(self, adapter):
        """Test ensuring iTerm2 is running."""
        with patch.object(adapter, "_run_applescript", return_value="") as mock_run:
            await adapter._ensure_iterm2_running()

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "iTerm2" in call_args


class TestITerm2AdapterNotAvailable:
    """Test suite for when osascript is not available."""

    def test_osascript_available_flag(self):
        """Test OSASCRIPT_AVAILABLE flag."""
        # This just checks the flag exists
        assert isinstance(OSASCRIPT_AVAILABLE, bool)

    def test_init_fails_without_osascript(self):
        """Test that adapter initialization fails without osascript."""
        with patch(
            "mahavishnu.terminal.adapters.iterm2.OSASCRIPT_AVAILABLE", False
        ):
            with pytest.raises(ImportError, match="osascript not available"):
                ITerm2Adapter()


class TestITerm2AdapterEdgeCases:
    """Test edge cases and error handling."""

    @pytest.fixture
    def adapter(self):
        """Create adapter for testing."""
        return ITerm2Adapter()

    @pytest.mark.asyncio
    async def test_send_command_escapes_quotes(self, adapter):
        """Test that commands with quotes are properly escaped."""
        adapter._sessions["test"] = {
            "command": "initial",
            "created_at": datetime.now(),
        }

        with patch.object(adapter, "_run_applescript", return_value="") as mock_run:
            await adapter.send_command("test", 'echo "hello world"')

        call_args = mock_run.call_args[0][0]
        # Should have escaped the quotes
        assert '\\"' in call_args

    @pytest.mark.asyncio
    async def test_close_session_removes_from_tracking_on_error(self, adapter):
        """Test that session is removed from tracking even if close fails."""
        adapter._sessions["test"] = {
            "command": "test",
            "created_at": datetime.now(),
            "new_window": False,
        }

        with patch.object(
            adapter, "_run_applescript", side_effect=RuntimeError("Failed")
        ):
            with pytest.raises(RuntimeError):
                await adapter.close_session("test")

        # Should still be removed from tracking
        assert "test" not in adapter._sessions
