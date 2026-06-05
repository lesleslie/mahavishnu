"""Unit tests for mahavishnu.factories.

The factories module exposes singletons for ``PoolManager``,
``MahavishnuWebSocketServer``, and ``TerminalManager`` so that expensive
re-initialization is avoided. These tests mock the heavy constructors at the
``mahavishnu.factories`` namespace boundary (and the lazy import site for
``TerminalManager``) so the suite stays fast and isolated.

Each factory is exercised for:

- callable / correct return type
- parameter forwarding
- singleton / cache reuse
- ``reset_all_factories`` interaction
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mahavishnu import factories

# ============================================================================
# Shared fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    """Ensure each test sees a clean singleton slate and leaves it clean."""
    factories.reset_all_factories()
    yield
    factories.reset_all_factories()


@pytest.fixture
def mock_pool_manager_cls(monkeypatch: pytest.MonkeyPatch):
    """Replace ``PoolManager`` inside ``mahavishnu.factories`` with a mock class.

    Returns a ``(cls_mock, instance_mock)`` tuple so tests can assert on
    constructor calls and the singleton instance independently.
    """
    cls_mock = MagicMock(name="PoolManagerCls")
    instance = MagicMock(name="PoolManagerInstance")
    cls_mock.return_value = instance
    monkeypatch.setattr(factories, "PoolManager", cls_mock)
    return cls_mock, instance


@pytest.fixture
def mock_websocket_server_cls(monkeypatch: pytest.MonkeyPatch):
    """Replace ``MahavishnuWebSocketServer`` inside ``mahavishnu.factories``."""
    cls_mock = MagicMock(name="MahavishnuWebSocketServerCls")
    instance = MagicMock(name="MahavishnuWebSocketServerInstance")
    cls_mock.return_value = instance
    monkeypatch.setattr(factories, "MahavishnuWebSocketServer", cls_mock)
    return cls_mock, instance


@pytest.fixture
def mock_terminal_manager_cls(monkeypatch: pytest.MonkeyPatch):
    """Replace the ``TerminalManager`` import target.

    ``get_terminal_manager`` performs a lazy
    ``from mahavishnu.terminal import TerminalManager`` inside the function
    body, so the import resolves through the source module. Patching at the
    source keeps the factory's lazy-import contract intact while still
    avoiding real construction.
    """
    cls_mock = MagicMock(name="TerminalManagerCls")
    instance = MagicMock(name="TerminalManagerInstance")
    cls_mock.return_value = instance
    monkeypatch.setattr("mahavishnu.terminal.TerminalManager", cls_mock)
    return cls_mock, instance


# ============================================================================
# get_pool_manager
# ============================================================================


class TestGetPoolManager:
    """Tests for the ``get_pool_manager`` singleton factory."""

    def test_returns_pool_manager_instance(
        self,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """Factory returns the constructed (mocked) PoolManager instance."""
        _, instance = mock_pool_manager_cls
        result = factories.get_pool_manager()
        assert result is instance

    def test_singleton_returns_same_instance(
        self,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """Repeated calls return the cached object, not a new one."""
        _, instance = mock_pool_manager_cls
        first = factories.get_pool_manager()
        second = factories.get_pool_manager()
        third = factories.get_pool_manager()
        assert first is second is third is instance
        # Constructor invoked exactly once across all three calls.
        mock_pool_manager_cls.assert_called_once()

    def test_passes_explicit_dependencies(
        self,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """All forwarded dependencies land on the PoolManager constructor."""
        tm = MagicMock(name="ExplicitTM")
        sb = MagicMock(name="SessionBuddyClient")
        mb = MagicMock(name="MessageBus")
        ep = MagicMock(name="EventPublisher")
        ds = MagicMock(name="DharaState")

        factories.get_pool_manager(
            terminal_manager=tm,
            session_buddy_client=sb,
            message_bus=mb,
            event_publisher=ep,
            dhara_state=ds,
        )

        mock_pool_manager_cls.assert_called_once_with(
            terminal_manager=tm,
            session_buddy_client=sb,
            message_bus=mb,
            event_publisher=ep,
            dhara_state=ds,
        )

    def test_uses_terminal_manager_singleton_when_omitted(
        self,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """When terminal_manager is not provided, the singleton is used."""
        _, tm_instance = mock_terminal_manager_cls
        factories.get_pool_manager()

        _, kwargs = mock_pool_manager_cls.call_args
        assert kwargs["terminal_manager"] is tm_instance

    def test_explicit_terminal_manager_overrides_singleton(
        self,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """An explicit terminal_manager is honored over the singleton."""
        _, tm_singleton = mock_terminal_manager_cls
        tm_explicit = MagicMock(name="ExplicitTMOverride")

        factories.get_pool_manager(terminal_manager=tm_explicit)

        _, kwargs = mock_pool_manager_cls.call_args
        assert kwargs["terminal_manager"] is tm_explicit
        assert kwargs["terminal_manager"] is not tm_singleton

    def test_reset_then_call_yields_new_instance(
        self,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """After ``reset_all_factories`` a fresh instance is constructed."""
        first = factories.get_pool_manager()
        factories.reset_all_factories()
        second = factories.get_pool_manager()
        assert first is not second
        assert mock_pool_manager_cls.call_count == 2


# ============================================================================
# get_websocket_server
# ============================================================================


class TestGetWebSocketServer:
    """Tests for the ``get_websocket_server`` singleton factory."""

    def test_returns_websocket_server_instance(
        self,
        mock_websocket_server_cls,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """Factory returns the constructed (mocked) WS server instance."""
        _, instance = mock_websocket_server_cls
        result = factories.get_websocket_server()
        assert result is instance

    def test_singleton_returns_same_instance(
        self,
        mock_websocket_server_cls,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """Repeated calls share the cached instance."""
        _, instance = mock_websocket_server_cls
        first = factories.get_websocket_server()
        second = factories.get_websocket_server()
        assert first is second is instance
        mock_websocket_server_cls.assert_called_once()

    def test_passes_all_config_kwargs(
        self,
        mock_websocket_server_cls,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """host/port/TLS/auth options are forwarded verbatim."""
        pm = MagicMock(name="PoolManager")
        factories.get_websocket_server(
            pool_manager=pm,
            host="0.0.0.0",
            port=9999,
            max_connections=50,
            message_rate_limit=10,
            require_auth=True,
            tls_enabled=True,
            cert_file="/tmp/cert.pem",
            key_file="/tmp/key.pem",
        )

        mock_websocket_server_cls.assert_called_once_with(
            pool_manager=pm,
            host="0.0.0.0",
            port=9999,
            max_connections=50,
            message_rate_limit=10,
            require_auth=True,
            tls_enabled=True,
            cert_file="/tmp/cert.pem",
            key_file="/tmp/key.pem",
        )

    def test_uses_pool_manager_singleton_when_omitted(
        self,
        mock_websocket_server_cls,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """When pool_manager is None, the PoolManager singleton is used."""
        _, pm_instance = mock_pool_manager_cls
        factories.get_websocket_server()

        _, kwargs = mock_websocket_server_cls.call_args
        assert kwargs["pool_manager"] is pm_instance

    def test_explicit_pool_manager_overrides_singleton(
        self,
        mock_websocket_server_cls,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """An explicit pool_manager is honored over the singleton."""
        _, pm_singleton = mock_pool_manager_cls
        pm_explicit = MagicMock(name="ExplicitPMOverride")

        factories.get_websocket_server(pool_manager=pm_explicit)

        _, kwargs = mock_websocket_server_cls.call_args
        assert kwargs["pool_manager"] is pm_explicit
        assert kwargs["pool_manager"] is not pm_singleton


# ============================================================================
# get_terminal_manager
# ============================================================================


class TestGetTerminalManager:
    """Tests for the ``get_terminal_manager`` singleton factory."""

    def test_returns_terminal_manager_instance(
        self,
        mock_terminal_manager_cls,
    ) -> None:
        """Factory returns the constructed (mocked) TerminalManager."""
        _, instance = mock_terminal_manager_cls
        result = factories.get_terminal_manager()
        assert result is instance

    def test_singleton_returns_same_instance(
        self,
        mock_terminal_manager_cls,
    ) -> None:
        """Repeated calls share the cached instance."""
        _, instance = mock_terminal_manager_cls
        first = factories.get_terminal_manager()
        second = factories.get_terminal_manager()
        assert first is second is instance
        mock_terminal_manager_cls.assert_called_once()

    def test_passes_adapter_and_config(
        self,
        mock_terminal_manager_cls,
    ) -> None:
        """Adapter and config kwargs land on the constructor."""
        adapter = MagicMock(name="Adapter")
        config = MagicMock(name="Config")
        factories.get_terminal_manager(adapter=adapter, config=config)

        mock_terminal_manager_cls.assert_called_once_with(
            adapter=adapter,
            config=config,
        )


# ============================================================================
# initialize_websocket_server
# ============================================================================


class TestInitializeWebSocketServer:
    """Tests for the ``initialize_websocket_server`` convenience helper."""

    def test_initializes_singleton(
        self,
        mock_websocket_server_cls,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """The convenience helper populates the cached WS server slot."""
        _, instance = mock_websocket_server_cls
        factories.initialize_websocket_server()
        assert factories._websocket_server is instance

    def test_forwards_config_to_constructor(
        self,
        mock_websocket_server_cls,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """All config kwargs reach the underlying WS server constructor."""
        factories.initialize_websocket_server(
            host="10.0.0.1",
            port=7000,
            max_connections=25,
            message_rate_limit=42,
            require_auth=True,
            tls_enabled=False,
            cert_file=None,
            key_file=None,
        )

        mock_websocket_server_cls.assert_called_once()
        _, kwargs = mock_websocket_server_cls.call_args
        assert kwargs["host"] == "10.0.0.1"
        assert kwargs["port"] == 7000
        assert kwargs["max_connections"] == 25
        assert kwargs["message_rate_limit"] == 42
        assert kwargs["require_auth"] is True
        assert kwargs["tls_enabled"] is False
        assert kwargs["cert_file"] is None
        assert kwargs["key_file"] is None


# ============================================================================
# reset_all_factories
# ============================================================================


class TestResetAllFactories:
    """Tests for the ``reset_all_factories`` cleanup helper."""

    def test_clears_pool_manager_slot(
        self,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """Slot is set after construction and cleared after reset."""
        factories.get_pool_manager()
        assert factories._pool_manager is not None
        factories.reset_all_factories()
        assert factories._pool_manager is None

    def test_clears_websocket_server_slot(
        self,
        mock_websocket_server_cls,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """Slot is set after construction and cleared after reset."""
        factories.get_websocket_server()
        assert factories._websocket_server is not None
        factories.reset_all_factories()
        assert factories._websocket_server is None

    def test_clears_terminal_manager_slot(
        self,
        mock_terminal_manager_cls,
    ) -> None:
        """Slot is set after construction and cleared after reset."""
        factories.get_terminal_manager()
        assert factories._terminal_manager is not None
        factories.reset_all_factories()
        assert factories._terminal_manager is None

    def test_reset_then_call_rebuilds_singletons(
        self,
        mock_pool_manager_cls,
        mock_terminal_manager_cls,
    ) -> None:
        """All factories construct fresh instances after a reset."""
        first_pool = factories.get_pool_manager()
        first_tm = factories.get_terminal_manager()

        factories.reset_all_factories()

        second_pool = factories.get_pool_manager()
        second_tm = factories.get_terminal_manager()
        assert first_pool is not second_pool
        assert first_tm is not second_tm
        assert mock_pool_manager_cls.call_count == 2
        assert mock_terminal_manager_cls.call_count == 2


# ============================================================================
# Public API
# ============================================================================


class TestPublicAPI:
    """Smoke tests for the module's exported surface."""

    def test_all_exports_are_callable(self) -> None:
        """Every name in ``__all__`` is importable and callable."""
        for name in factories.__all__:
            symbol = getattr(factories, name)
            assert callable(symbol), f"{name} is not callable"
        # And the documented public surface is complete.
        assert set(factories.__all__) == {
            "get_pool_manager",
            "get_websocket_server",
            "get_terminal_manager",
            "initialize_websocket_server",
            "reset_all_factories",
        }
