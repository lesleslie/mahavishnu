"""Unit tests for TerminalManager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.terminal.config import TerminalSettings
from mahavishnu.terminal.manager import TerminalManager

# ============================================================================
# TerminalManager Tests
# ============================================================================


class TestTerminalManager:
    """Tests for TerminalManager."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock terminal adapter."""
        adapter = MagicMock()
        adapter.adapter_name = "mock"
        adapter.launch_session = AsyncMock(return_value="session_123")
        adapter.send_command = AsyncMock()
        adapter.capture_output = AsyncMock(return_value="test output")
        adapter.close_session = AsyncMock()
        adapter.list_sessions = AsyncMock(return_value=[])
        return adapter

    @pytest.fixture
    def config(self):
        """Create terminal settings."""
        return TerminalSettings(max_concurrent_sessions=10)

    @pytest.fixture
    def manager(self, mock_adapter, config):
        """Create a TerminalManager instance."""
        return TerminalManager(mock_adapter, config)

    def test_current_adapter_returns_name(self, manager, mock_adapter):
        """Test current_adapter returns adapter's adapter_name."""
        assert manager.current_adapter() == "mock"

    def test_initialization_sets_semaphore(self, manager, config):
        """Test initialization creates semaphore with correct limit."""
        assert isinstance(manager._semaphore, asyncio.Semaphore)
        assert manager._semaphore._value == config.max_concurrent_sessions

    def test_adapter_history_initially_empty(self, manager):
        """Test adapter history starts empty."""
        assert manager.get_adapter_history() == []

    @pytest.mark.asyncio
    async def test_switch_adapter_updates_current(self, manager, mock_adapter):
        """Test switch_adapter changes current adapter."""
        new_adapter = MagicMock()
        new_adapter.adapter_name = "new_adapter"

        with patch.object(
            manager,
            "_migrate_sessions",
            new_adapter._migrate_sessions
            if hasattr(new_adapter, "_migrate_sessions")
            else AsyncMock(),
        ):
            await manager.switch_adapter(new_adapter)

        assert manager.current_adapter() == "new_adapter"
        history = manager.get_adapter_history()
        assert len(history) == 1
        assert history[0]["from"] == "mock"
        assert history[0]["to"] == "new_adapter"

    @pytest.mark.asyncio
    async def test_switch_adapter_records_history(self, manager, mock_adapter):
        """Test switch_adapter appends to adapter history."""
        new_adapter = MagicMock()
        new_adapter.adapter_name = "switched"

        with patch.object(manager, "_migrate_sessions", AsyncMock()):
            await manager.switch_adapter(new_adapter)

        history = manager.get_adapter_history()
        assert len(history) == 1
        assert "timestamp" in history[0]

    @pytest.mark.asyncio
    async def test_switch_adapter_with_migration(self, manager, mock_adapter):
        """Test switch_adapter with migrate_sessions=True attempts migration."""
        new_adapter = MagicMock()
        new_adapter.adapter_name = "new_adapter"
        new_adapter.launch_session = AsyncMock(return_value="migrated_session")
        new_adapter.list_sessions = AsyncMock(return_value=[{"id": "old_1", "command": "test"}])

        with patch.object(manager, "_migrate_sessions", AsyncMock()) as mock_migrate:
            await manager.switch_adapter(new_adapter, migrate_sessions=True)
            mock_migrate.assert_called_once()

    def test_set_migration_callback(self, manager):
        """Test set_migration_callback stores callback."""
        callback = AsyncMock()

        manager.set_migration_callback(callback)

        assert manager._session_migration_callback == callback

    @pytest.mark.asyncio
    async def test_set_migration_callback_invoked_on_switch(self, manager, mock_adapter):
        """Test migration callback is called during adapter switch."""
        callback = AsyncMock()
        manager.set_migration_callback(callback)

        new_adapter = MagicMock()
        new_adapter.adapter_name = "new"

        with patch.object(manager, "_migrate_sessions", AsyncMock()):
            await manager.switch_adapter(new_adapter)

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "mock"  # old adapter name
        assert args[1] == "new"  # new adapter name

    @pytest.mark.asyncio
    async def test_launch_sessions_single(self, manager, mock_adapter):
        """Test launch_sessions with count=1 returns single session ID."""
        session_ids = await manager.launch_sessions("echo test", count=1)

        assert len(session_ids) == 1
        assert session_ids[0] == "session_123"
        mock_adapter.launch_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_launch_sessions_multiple_concurrent(self, manager, mock_adapter):
        """Test launch_sessions with count>1 launches concurrently."""
        mock_adapter.launch_session = AsyncMock(side_effect=["s1", "s2", "s3"])

        session_ids = await manager.launch_sessions("echo test", count=3)

        assert len(session_ids) == 3
        assert mock_adapter.launch_session.call_count == 3

    @pytest.mark.asyncio
    async def test_launch_sessions_enforces_semaphore(self, manager, mock_adapter):
        """Test launch_sessions uses semaphore to limit concurrency."""
        manager._semaphore = asyncio.Semaphore(2)  # Only 2 concurrent
        mock_adapter.launch_session = AsyncMock(return_value="session")

        # Launch 5 sessions but only 2 can run concurrently
        session_ids = await manager.launch_sessions("echo test", count=5)

        assert len(session_ids) == 5

    @pytest.mark.asyncio
    async def test_launch_sessions_batch_processes_in_batches(self, manager, mock_adapter):
        """Test launch_sessions_batch processes in batches of _batch_size."""
        manager._batch_size = 2
        mock_adapter.launch_session = AsyncMock(return_value="batch_session")

        session_ids = await manager.launch_sessions_batch("echo test", count=5)

        assert len(session_ids) == 5
        # At least 3 batches: [0,1], [2,3], [4]
        assert mock_adapter.launch_session.call_count == 5

    @pytest.mark.asyncio
    async def test_send_command_delegates_to_adapter(self, manager, mock_adapter):
        """Test send_command calls adapter.send_command."""
        await manager.send_command("session_123", "ls -la")

        mock_adapter.send_command.assert_called_once_with("session_123", "ls -la")

    @pytest.mark.asyncio
    async def test_capture_output_delegates_to_adapter(self, manager, mock_adapter):
        """Test capture_output calls adapter.capture_output."""
        output = await manager.capture_output("session_123", lines=50)

        mock_adapter.capture_output.assert_called_once_with("session_123", 50)
        assert output == "test output"

    @pytest.mark.asyncio
    async def test_capture_all_outputs_concurrent(self, manager, mock_adapter):
        """Test capture_all_outputs captures from multiple sessions concurrently."""
        mock_adapter.capture_output = AsyncMock(side_effect=["output_1", "output_2", "output_3"])

        outputs = await manager.capture_all_outputs(["s1", "s2", "s3"])

        assert len(outputs) == 3
        assert outputs["s1"] == "output_1"
        assert outputs["s2"] == "output_2"
        assert outputs["s3"] == "output_3"

    @pytest.mark.asyncio
    async def test_close_session_delegates_to_adapter(self, manager, mock_adapter):
        """Test close_session calls adapter.close_session."""
        await manager.close_session("session_123")

        mock_adapter.close_session.assert_called_once_with("session_123")

    @pytest.mark.asyncio
    async def test_close_all_closes_multiple_sessions(self, manager, mock_adapter):
        """Test close_all closes multiple sessions concurrently."""
        await manager.close_all(["s1", "s2", "s3"])

        assert mock_adapter.close_session.call_count == 3

    @pytest.mark.asyncio
    async def test_list_sessions_delegates_to_adapter(self, manager, mock_adapter):
        """Test list_sessions calls adapter.list_sessions."""
        mock_adapter.list_sessions = AsyncMock(return_value=[{"id": "s1"}, {"id": "s2"}])

        sessions = await manager.list_sessions()

        mock_adapter.list_sessions.assert_called_once()
        assert len(sessions) == 2


class TestTerminalManagerFactory:
    """Tests for TerminalManager.create factory method."""

    @pytest.mark.asyncio
    async def test_create_with_mock_preference(self):
        """Test create with 'mock' preference returns mock adapter."""
        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference="mock")

        manager = await TerminalManager.create(config, mcp_client=None)

        assert manager.current_adapter() == "mock"

    @pytest.mark.asyncio
    async def test_create_with_auto_preference(self):
        """Test create with 'auto' preference falls back to mock."""
        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference="auto")

        manager = await TerminalManager.create(config, mcp_client=None)

        assert manager.current_adapter() == "mock"

    @pytest.mark.asyncio
    async def test_create_with_iterm2_preference_and_available(self):
        """Test create with 'iterm2' preference when osascript available."""

        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference="iterm2")

        with patch(
            "mahavishnu.terminal.adapters.iterm2.OSASCRIPT_AVAILABLE",
            True,
        ):
            manager = await TerminalManager.create(config, mcp_client=None)

        assert manager.current_adapter() == "iterm2"

    @pytest.mark.asyncio
    async def test_create_with_mcpretentious_preference(self):
        """Test create with 'mcpretentious' preference uses MCP client."""
        config = MagicMock()
        config.terminal = TerminalSettings(adapter_preference="mcpretentious")

        mock_client = MagicMock()

        with patch("mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE", False):
            from mahavishnu.terminal.adapters.mcpretentious import McpretentiousAdapter

            with patch.object(McpretentiousAdapter, "__init__", lambda self, mcp: None):
                manager = await TerminalManager.create(config, mcp_client=mock_client)

        assert manager.current_adapter() == "mcpretentious"

    @pytest.mark.asyncio
    async def test_create_with_crow_preference_and_disabled_uses_mock(self):
        """MHV-001 regression: crow preference + crow_enabled=false -> mock, no crash.

        With the default settings/mahavishnu.yaml setting adapter_preference="crow",
        a stock install must NOT crash with ConfigurationError when the CLI callers
        pass mcp_client=None. The crow_enabled toggle (default false) gates the
        crow adapter and falls through to the mock adapter.
        """
        config = MagicMock()
        config.terminal = TerminalSettings(
            adapter_preference="crow",
            crow_enabled=False,
        )

        manager = await TerminalManager.create(config, mcp_client=None)

        assert manager.current_adapter() == "mock"

    @pytest.mark.asyncio
    async def test_create_with_crow_enabled_and_mcp_client_uses_crow(self):
        """crow preference + crow_enabled=true + mcp_client -> CrowTerminalAdapter."""
        config = MagicMock()
        config.terminal = TerminalSettings(
            adapter_preference="crow",
            crow_enabled=True,
            crow_http_host="127.0.0.1",
            crow_http_port=8675,
        )

        mock_client = MagicMock()

        with patch("mahavishnu.terminal.adapters.iterm2.ITERM2_AVAILABLE", False):
            from mahavishnu.terminal.adapters.crow import CrowTerminalAdapter

            with patch.object(CrowTerminalAdapter, "__init__", lambda self, mcp: None):
                manager = await TerminalManager.create(config, mcp_client=mock_client)

        assert manager.current_adapter() == "crow"

    @pytest.mark.asyncio
    async def test_create_with_crow_enabled_no_mcp_client_raises(self):
        """crow_enabled=true but mcp_client=None -> ConfigurationError with clear msg.

        Once the operator opts in (crow_enabled=true), the wiring failure surfaces
        with an actionable error message instead of the misleading original wording
        "requires mcp_client pointing at the Bodai crow HTTP server".
        """
        from mahavishnu.core.errors import ConfigurationError

        config = MagicMock()
        config.terminal = TerminalSettings(
            adapter_preference="crow",
            crow_enabled=True,
            crow_http_host="127.0.0.1",
            crow_http_port=8675,
        )

        with pytest.raises(ConfigurationError) as exc_info:
            await TerminalManager.create(config, mcp_client=None)

        message = exc_info.value.message
        assert "crow_enabled=true" in message
        assert "mcp_client" in message
        # Endpoint hint should appear in details
        assert exc_info.value.details.get("crow_http_endpoint") == "127.0.0.1:8675"

    def test_terminal_settings_crow_defaults(self):
        """TerminalSettings.crow_* default to disabled, sensible host/port."""
        settings = TerminalSettings()

        assert settings.crow_enabled is False
        assert settings.crow_http_host == "127.0.0.1"
        assert settings.crow_http_port == 8675


# ============================================================================
# TerminalSettings Tests
# ============================================================================


class TestTerminalSettings:
    """Tests for TerminalSettings configuration."""

    def test_default_values(self):
        """Test TerminalSettings default values."""
        settings = TerminalSettings()

        assert settings.enabled is False
        assert settings.default_columns == 120
        assert settings.default_rows == 40
        assert settings.max_concurrent_sessions == 20
        assert settings.adapter_preference == "mock"

    def test_column_bounds(self):
        """Test column bounds validation."""
        with pytest.raises(ValueError):
            TerminalSettings(default_columns=20)  # < 40

        with pytest.raises(ValueError):
            TerminalSettings(default_columns=400)  # > 300

    def test_row_bounds(self):
        """Test row bounds validation."""
        with pytest.raises(ValueError):
            TerminalSettings(default_rows=5)  # < 10

        with pytest.raises(ValueError):
            TerminalSettings(default_rows=300)  # > 200

    def test_max_concurrent_bounds(self):
        """Test max_concurrent_sessions bounds validation."""
        with pytest.raises(ValueError):
            TerminalSettings(max_concurrent_sessions=0)  # < 1

        with pytest.raises(ValueError):
            TerminalSettings(max_concurrent_sessions=200)  # > 100
