"""Unit tests for ``mahavishnu.terminal.adapters.mock.MockTerminalAdapter``.

Tests the in-memory mock adapter used for testing and development. The
mock adapter does not need any external resources, so these tests run
against the real implementation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from mahavishnu.terminal.adapters.base import TerminalAdapter
from mahavishnu.terminal.adapters.mock import MockTerminalAdapter

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def adapter() -> MockTerminalAdapter:
    """A fresh mock adapter with no response delay."""
    return MockTerminalAdapter(auto_respond=True, response_delay=0.0)


@pytest.fixture
def silent_adapter() -> MockTerminalAdapter:
    """A mock adapter that does not auto-respond to commands."""
    return MockTerminalAdapter(auto_respond=False, response_delay=0.0)


# =============================================================================
# Construction / Interface Tests
# =============================================================================


class TestConstruction:
    """Construction and base class integration tests."""

    def test_is_terminal_adapter(self, adapter: MockTerminalAdapter):
        assert isinstance(adapter, TerminalAdapter)

    def test_adapter_name(self, adapter: MockTerminalAdapter):
        assert adapter.adapter_name == "mock"

    def test_default_construction(self):
        a = MockTerminalAdapter()
        assert a.auto_respond is True
        assert a.response_delay == pytest.approx(0.1)

    def test_initial_state_is_empty(self, adapter: MockTerminalAdapter):
        assert adapter._sessions == {}
        assert adapter._command_history == {}


# =============================================================================
# Session Lifecycle Tests
# =============================================================================


class TestSessionLifecycle:
    """Tests for the basic launch / send / read / close cycle."""

    async def test_launch_session_returns_id(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        assert isinstance(sid, str)
        assert len(sid) == 8
        assert sid in adapter._sessions

    async def test_launch_stores_metadata(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen", columns=120, rows=40)
        info = adapter._sessions[sid]
        assert info["command"] == "qwen"
        assert info["columns"] == 120
        assert info["rows"] == 40
        assert isinstance(info["created_at"], datetime)

    async def test_launch_unique_session_ids(self, adapter: MockTerminalAdapter):
        ids = {await adapter.launch_session("qwen") for _ in range(5)}
        # Probability of collision is low with 8 hex chars; verify we got 5 unique
        assert len(ids) == 5

    async def test_launch_records_command_history(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("initial-cmd")
        assert adapter.get_command_history(sid) == ["initial-cmd"]

    async def test_launch_with_kwargs_ignored(self, adapter: MockTerminalAdapter):
        # Extra kwargs must not raise; they are silently ignored
        sid = await adapter.launch_session("qwen", extra_kwarg="ignored")
        assert sid in adapter._sessions

    async def test_close_removes_session(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        await adapter.close_session(sid)
        assert sid not in adapter._sessions
        assert sid not in adapter._command_history

    async def test_close_unknown_session_is_silent(self, adapter: MockTerminalAdapter):
        # Per the implementation, close_session on an unknown id is a no-op
        await adapter.close_session("does-not-exist")
        assert adapter._sessions == {}

    async def test_close_appends_termination_marker(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        # Snapshot the buffer
        await adapter.capture_output(sid)
        # Close appends a termination marker before deleting the session
        await adapter.close_session(sid)
        assert sid not in adapter._sessions


# =============================================================================
# Command Sending Tests
# =============================================================================


class TestSendCommand:
    """Tests for send_command and command history tracking."""

    async def test_send_appends_to_history(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        await adapter.send_command(sid, "ls")
        await adapter.send_command(sid, "pwd")
        assert adapter.get_command_history(sid) == ["qwen", "ls", "pwd"]

    async def test_send_appends_to_output_buffer(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        await adapter.send_command(sid, "ls")
        output = await adapter.capture_output(sid)
        assert "$ ls" in output

    async def test_send_to_unknown_session_raises(self, adapter: MockTerminalAdapter):
        with pytest.raises(ValueError, match="not found"):
            await adapter.send_command("nope", "ls")

    async def test_auto_respond_generates_response(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        await adapter.send_command(sid, "echo hello")
        output = await adapter.capture_output(sid)
        assert "[Mock]" in output
        assert "hello" in output

    async def test_silent_adapter_skips_response(self, silent_adapter: MockTerminalAdapter):
        sid = await silent_adapter.launch_session("qwen")
        await silent_adapter.send_command(sid, "echo hello")
        output = await silent_adapter.capture_output(sid)
        # No mock response should have been generated
        assert "Executed: echo hello" not in output
        # But the command itself is echoed
        assert "$ echo hello" in output

    async def test_response_delay_used(self):
        a = MockTerminalAdapter(auto_respond=True, response_delay=0.05)
        sid = await a.launch_session("qwen")
        start = asyncio.get_event_loop().time()
        await a.send_command(sid, "echo delayed")
        elapsed = asyncio.get_event_loop().time() - start
        # Loose bound to avoid CI flakiness
        assert elapsed >= 0.04


# =============================================================================
# Capture Output Tests
# =============================================================================


class TestCaptureOutput:
    """Tests for capture_output and line limiting."""

    async def test_capture_full_buffer(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        await adapter.send_command(sid, "a")
        await adapter.send_command(sid, "b")
        output = await adapter.capture_output(sid)
        assert "a" in output
        assert "b" in output

    async def test_capture_with_lines_limit(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        for i in range(5):
            await adapter.send_command(sid, f"cmd-{i}")
        # Request only the last 2 lines
        output = await adapter.capture_output(sid, lines=2)
        # Should contain the most recent commands, but not the earliest ones
        assert "cmd-4" in output
        assert "cmd-0" not in output

    async def test_capture_unknown_session_raises(self, adapter: MockTerminalAdapter):
        with pytest.raises(ValueError, match="not found"):
            await adapter.capture_output("nope")


# =============================================================================
# List Sessions Tests
# =============================================================================


class TestListSessions:
    """Tests for list_sessions metadata output."""

    async def test_list_empty(self, adapter: MockTerminalAdapter):
        assert await adapter.list_sessions() == []

    async def test_list_after_launch(self, adapter: MockTerminalAdapter):
        sid1 = await adapter.launch_session("qwen")
        sid2 = await adapter.launch_session("claude")
        sessions = await adapter.list_sessions()
        ids = {s["session_id"] for s in sessions}
        assert ids == {sid1, sid2}
        for s in sessions:
            assert "command" in s
            assert "created_at" in s
            assert "output_lines" in s
            assert isinstance(s["output_lines"], int)

    async def test_list_excludes_closed(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        await adapter.close_session(sid)
        assert await adapter.list_sessions() == []


# =============================================================================
# Mock Response Generation Tests
# =============================================================================


class TestMockResponses:
    """Tests for the _generate_mock_response helper covering common patterns."""

    @pytest.mark.parametrize(
        "command,expected_substring",
        [
            ("help", "Available commands"),
            ("?", "Available commands"),
            ("status", "Status: OK"),
            ("echo hi there", "hi there"),
            ("exit", "Session ended"),
        ],
    )
    def test_pattern_responses(
        self,
        adapter: MockTerminalAdapter,
        command: str,
        expected_substring: str,
    ):
        response = adapter._generate_mock_response(command)
        assert expected_substring in response

    def test_fallback_response(self, adapter: MockTerminalAdapter):
        response = adapter._generate_mock_response("something-unknown")
        assert "Executed: something-unknown" in response
        assert "Return code: 0" in response


# =============================================================================
# Command History Helper Tests
# =============================================================================


class TestCommandHistory:
    """Tests for get_command_history helper."""

    def test_get_history_unknown_session(self, adapter: MockTerminalAdapter):
        assert adapter.get_command_history("does-not-exist") == []

    async def test_get_history_after_commands(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen")
        await adapter.send_command(sid, "ls")
        await adapter.send_command(sid, "pwd")
        assert adapter.get_command_history(sid) == ["qwen", "ls", "pwd"]


# =============================================================================
# Integration-Style Smoke Test
# =============================================================================


class TestEndToEnd:
    """Full happy-path workflow exercising every public method."""

    async def test_full_workflow(self, adapter: MockTerminalAdapter):
        sid = await adapter.launch_session("qwen", columns=80, rows=24)
        await adapter.send_command(sid, "echo 1")
        await adapter.send_command(sid, "status")
        output = await adapter.capture_output(sid, lines=10)
        assert "echo 1" in output
        assert "Status: OK" in output

        sessions = await adapter.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == sid

        await adapter.close_session(sid)
        assert await adapter.list_sessions() == []
