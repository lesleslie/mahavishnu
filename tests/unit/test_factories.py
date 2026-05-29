"""Tests for mahavishnu.factories singleton management."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestResetFactories:
    """Test factory reset clears all singletons."""

    def test_reset_clears_all_singletons(self):
        """reset_all_factories() must null out all three globals."""
        from mahavishnu import factories as factories_module

        # Set the globals directly via the module
        factories_module._pool_manager = MagicMock()
        factories_module._websocket_server = MagicMock()
        factories_module._terminal_manager = MagicMock()

        factories_module.reset_all_factories()

        assert factories_module._pool_manager is None
        assert factories_module._websocket_server is None
        assert factories_module._terminal_manager is None


class TestGetPoolManager:
    """Test PoolManager singleton."""

    def test_returns_same_instance_on_multiple_calls(self):
        """get_pool_manager() must return identical instance."""
        from mahavishnu import factories as factories_module
        from mahavishnu.pools import PoolManager

        factories_module._pool_manager = None
        factories_module._terminal_manager = MagicMock()

        with patch.object(factories_module, "get_terminal_manager", return_value=MagicMock()):
            with patch.object(PoolManager, "__init__", return_value=None):
                instance1 = factories_module.get_pool_manager()
                instance2 = factories_module.get_pool_manager()

        assert instance1 is instance2

    def test_forwards_all_constructor_kwargs(self):
        """All kwargs are passed through to PoolManager."""
        from mahavishnu import factories as factories_module
        from mahavishnu.pools import PoolManager

        factories_module._pool_manager = None
        factories_module._terminal_manager = MagicMock()

        mock_tm = MagicMock()
        mock_client = MagicMock()
        mock_bus = MagicMock()
        mock_pub = MagicMock()
        mock_dhara = MagicMock()

        with patch.object(factories_module, "get_terminal_manager", return_value=mock_tm):
            with patch.object(PoolManager, "__init__", return_value=None) as mock_init:
                factories_module.get_pool_manager(
                    session_buddy_client=mock_client,
                    message_bus=mock_bus,
                    event_publisher=mock_pub,
                    dhara_state=mock_dhara,
                )

        mock_init.assert_called_once()
        call_kwargs = mock_init.call_args.kwargs
        assert call_kwargs["terminal_manager"] is mock_tm
        assert call_kwargs["session_buddy_client"] is mock_client
        assert call_kwargs["message_bus"] is mock_bus
        assert call_kwargs["event_publisher"] is mock_pub
        assert call_kwargs["dhara_state"] is mock_dhara


class TestGetWebSocketServer:
    """Test WebSocket server singleton."""

    def test_returns_same_instance_on_multiple_calls(self):
        """get_websocket_server() must return identical instance."""
        from mahavishnu import factories as factories_module
        from mahavishnu.websocket import MahavishnuWebSocketServer

        factories_module._websocket_server = None
        factories_module._pool_manager = MagicMock()

        with patch.object(MahavishnuWebSocketServer, "__init__", return_value=None):
            instance1 = factories_module.get_websocket_server()
            instance2 = factories_module.get_websocket_server()

        assert instance1 is instance2

    def test_creates_pool_manager_if_not_provided(self):
        """When pool_manager is None, calls get_pool_manager()."""
        from mahavishnu import factories as factories_module
        from mahavishnu.websocket import MahavishnuWebSocketServer

        factories_module._websocket_server = None
        factories_module._pool_manager = None
        factories_module._terminal_manager = MagicMock()

        mock_pm = MagicMock()
        with patch.object(factories_module, "get_pool_manager", return_value=mock_pm):
            with patch.object(MahavishnuWebSocketServer, "__init__", return_value=None):
                factories_module.get_websocket_server(pool_manager=None)

    def test_passes_tls_params_to_server(self):
        """TLS config kwargs flow through to MahavishnuWebSocketServer."""
        from mahavishnu import factories as factories_module
        from mahavishnu.websocket import MahavishnuWebSocketServer

        factories_module._websocket_server = None
        factories_module._pool_manager = MagicMock()

        with patch.object(MahavishnuWebSocketServer, "__init__", return_value=None) as mock_init:
            factories_module.get_websocket_server(
                host="0.0.0.0",
                port=9000,
                max_connections=500,
                message_rate_limit=200,
                require_auth=True,
                tls_enabled=True,
                cert_file="/certs/cert.pem",
                key_file="/certs/key.pem",
            )

        call_kwargs = mock_init.call_args.kwargs
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 9000
        assert call_kwargs["max_connections"] == 500
        assert call_kwargs["message_rate_limit"] == 200
        assert call_kwargs["require_auth"] is True
        assert call_kwargs["tls_enabled"] is True
        assert call_kwargs["cert_file"] == "/certs/cert.pem"
        assert call_kwargs["key_file"] == "/certs/key.pem"


class TestGetTerminalManager:
    """Test TerminalManager singleton."""

    def test_returns_same_instance_on_multiple_calls(self):
        """get_terminal_manager() must return identical instance."""
        import mahavishnu.factories as fm
        from mahavishnu.terminal import TerminalManager

        fm._terminal_manager = None

        mock_instance = MagicMock()
        with patch.object(
            TerminalManager, "__new__", side_effect=lambda cls, *args, **kwargs: mock_instance
        ):
            instance1 = fm.get_terminal_manager()
            instance2 = fm.get_terminal_manager()

        assert instance1 is instance2
        assert instance1 is mock_instance

    def test_passes_adapter_and_config_kwargs(self):
        """adapter and config kwargs flow through to TerminalManager."""
        import mahavishnu.factories as fm
        from mahavishnu.terminal import TerminalManager

        fm._terminal_manager = None

        mock_adapter = MagicMock()
        mock_config = MagicMock()
        mock_instance = MagicMock()

        # Track call args via side_effect
        call_args = []

        def mock_new(cls, *args, **kwargs):
            call_args.append({"args": args, "kwargs": kwargs})
            return mock_instance

        with patch.object(TerminalManager, "__new__", side_effect=mock_new):
            result = fm.get_terminal_manager(adapter=mock_adapter, config=mock_config)

        assert len(call_args) == 1
        assert call_args[0]["kwargs"].get("adapter") is mock_adapter
        assert call_args[0]["kwargs"].get("config") is mock_config
        assert result is mock_instance


class TestInitializeWebSocketServer:
    """Test websocket initialization convenience function."""

    def test_calls_get_websocket_server_with_same_kwargs(self):
        """initialize_websocket_server() forwards all args to get_websocket_server()."""
        from mahavishnu import factories as factories_module

        factories_module._websocket_server = None
        factories_module._pool_manager = MagicMock()

        with patch.object(
            factories_module, "get_websocket_server", return_value=MagicMock()
        ) as mock_get:
            factories_module.initialize_websocket_server(
                host="0.0.0.0",
                port=9000,
                require_auth=True,
            )

        mock_get.assert_called_once_with(
            pool_manager=None,  # initialize passes None; get_websocket_server lazy-inits pool_manager internally
            host="0.0.0.0",
            port=9000,
            max_connections=1000,
            message_rate_limit=100,
            require_auth=True,
            tls_enabled=False,
            cert_file=None,
            key_file=None,
        )
