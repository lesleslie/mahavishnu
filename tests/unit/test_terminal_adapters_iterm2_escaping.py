"""Test that ITerm2Adapter uses canonical bridge escaping.

These tests verify that multi-line commands use the & return & AppleScript
syntax instead of embedded newlines, and that single quotes are properly escaped.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.terminal.adapters.iterm2 import ITerm2Adapter, OSASCRIPT_AVAILABLE


class TestITerm2AdapterEscaping:
    """Test that ITerm2Adapter uses canonical bridge escaping."""

    @pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="osascript not available")
    def test_send_command_with_newline_uses_multiline_syntax(self):
        """Multi-line commands should use & return & for AppleScript, not embedded \\n."""
        adapter = ITerm2Adapter()
        adapter._sessions["test"] = {
            "command": "echo test",
            "created_at": datetime.now(),
            "window": "win_123",
            "tab": "tab_456",
            "new_window": False,
        }

        captured_script = None

        async def capture_script(script):
            nonlocal captured_script
            captured_script = script
            return ""

        adapter._run_applescript = capture_script

        asyncio.get_event_loop().run_until_complete(
            adapter.send_command("test", "echo line1\necho line2")
        )

        # Should use & return & for multi-line, not embedded \n
        assert captured_script is not None, "AppleScript was not captured"
        assert "& return &" in captured_script, (
            f"Expected '& return &' for multi-line command, got: {captured_script}"
        )
        assert "\\n" not in captured_script, (
            f"Should not have embedded \\n in script: {captured_script}"
        )

    @pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="osascript not available")
    def test_send_command_with_single_quote_escaped(self):
        """Single quotes should be escaped per canonical spec (\\')."""
        adapter = ITerm2Adapter()
        adapter._sessions["test"] = {
            "command": "echo test",
            "created_at": datetime.now(),
            "window": "win_123",
            "tab": "tab_456",
            "new_window": False,
        }

        captured_script = None

        async def capture_script(script):
            nonlocal captured_script
            captured_script = script
            return ""

        adapter._run_applescript = capture_script

        asyncio.get_event_loop().run_until_complete(
            adapter.send_command("test", "echo 'single quote")
        )

        assert captured_script is not None, "AppleScript was not captured"
        # Canonical escaping uses \' for single quotes
        assert "\\'" in captured_script, (
            f"Expected \\' for escaped single quote, got: {captured_script}"
        )

    @pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="osascript not available")
    def test_launch_session_with_newline_uses_multiline_syntax(self):
        """launch_session with multi-line command should use & return & syntax."""
        adapter = ITerm2Adapter()

        captured_script = None

        async def capture_script(script):
            nonlocal captured_script
            captured_script = script
            return "win_123,tab_456"

        adapter._run_applescript = capture_script

        asyncio.get_event_loop().run_until_complete(
            adapter.launch_session("echo line1\necho line2", new_window=False)
        )

        assert captured_script is not None, "AppleScript was not captured"
        assert "& return &" in captured_script, (
            f"Expected '& return &' for multi-line command, got: {captured_script}"
        )
        assert "\\n" not in captured_script, (
            f"Should not have embedded \\n in script: {captured_script}"
        )

    @pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="osascript not available")
    def test_launch_session_with_single_quote_escaped(self):
        """launch_session with single quotes should use \\' escaping."""
        adapter = ITerm2Adapter()

        captured_script = None

        async def capture_script(script):
            nonlocal captured_script
            captured_script = script
            return "win_123,tab_456"

        adapter._run_applescript = capture_script

        asyncio.get_event_loop().run_until_complete(
            adapter.launch_session("echo 'hello'", new_window=False)
        )

        assert captured_script is not None, "AppleScript was not captured"
        assert "\\'" in captured_script, (
            f"Expected \\' for escaped single quote, got: {captured_script}"
        )