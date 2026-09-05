"""Unit tests for ``mahavishnu.websocket.integration``.

Covers ``start_websocket_server``, ``stop_websocket_server``,
``get_websocket_status``, ``broadcast_workflow_event``,
``broadcast_pool_event`` and the ``WebSocketBroadcaster`` helper class.

The MahavishnuWebSocketServer is replaced with a fake so tests exercise the
production logic in ``integration.py`` without touching real network or TLS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from mahavishnu.core.events.transport import (
    CompositeEventEnvelopeHandler,
    NotificationEventHandler,
    RetryingEventEnvelopeHandler,
)
from mahavishnu.websocket import integration


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeServer:
    """Stand-in for ``MahavishnuWebSocketServer``.

    Only the attributes and methods used by ``integration.py`` are populated.
    """

    pool_manager: Any
    host: str
    port: int
    max_connections: int = 1000
    message_rate_limit: int = 100
    cert_file: str | None = None
    key_file: str | None = None
    ca_file: str | None = None
    tls_enabled: bool = False
    verify_client: bool = False
    auto_cert: bool = False
    ssl_context: Any = None
    is_running: bool = False
    uri: str = ""
    connections: dict = field(default_factory=dict)
    connection_rooms: dict = field(default_factory=dict)
    event_consumer: Any = None

    def __init__(self, **kwargs: Any) -> None:
        # Capture every kwarg verbatim so test assertions can inspect
        # what the production code passed through.
        for key, value in kwargs.items():
            setattr(self, key, value)
        # Defaults that tests should be able to read back
        self.is_running = False
        self.connections = {}
        self.connection_rooms = {}
        self.ssl_context = None
        self.uri = ""
        self.event_consumer = None

    async def start(self) -> None:
        self.is_running = True

    async def stop(self) -> None:
        self.is_running = False

    async def broadcast_workflow_started(self, workflow_id: str, data: dict) -> None:
        self.calls_started.append((workflow_id, data))

    async def broadcast_workflow_stage_completed(
        self, workflow_id: str, stage_name: str, result: dict
    ) -> None:
        self.calls_stage.append((workflow_id, stage_name, result))

    async def broadcast_workflow_completed(self, workflow_id: str, data: dict) -> None:
        self.calls_completed.append((workflow_id, data))

    async def broadcast_workflow_failed(self, workflow_id: str, error: str) -> None:
        self.calls_failed.append((workflow_id, error))

    async def broadcast_pool_status_changed(self, pool_id: str, data: dict) -> None:
        self.calls_pool_status.append((pool_id, data))

    async def broadcast_worker_status_changed(
        self, worker_id: str, status: str, pool_id: str
    ) -> None:
        self.calls_worker_status.append((worker_id, status, pool_id))


def _make_fake_server(**overrides: Any) -> _FakeServer:
    """Build a ``_FakeServer`` with sensible defaults + overrides."""
    base: dict[str, Any] = {
        "pool_manager": object(),
        "host": "127.0.0.1",
        "port": 8690,
    }
    base.update(overrides)
    server = _FakeServer(**base)
    server.calls_started = []
    server.calls_stage = []
    server.calls_completed = []
    server.calls_failed = []
    server.calls_pool_status = []
    server.calls_worker_status = []
    return server


class _FakeConsumer:
    """Stand-in for ``EventBusConsumer``."""

    created: list[_FakeConsumer] = []

    def __init__(self, *, transport: Any, handler: Any) -> None:
        self.transport = transport
        self.handler = handler
        self.started = False
        self.__class__.created.append(self)

    async def start(self) -> None:
        self.started = True


@pytest.fixture
def fake_server_cls(monkeypatch: pytest.MonkeyPatch) -> type[_FakeServer]:
    """Patch ``integration.MahavishnuWebSocketServer`` to return ``_FakeServer``."""
    _FakeServer.calls_started = []  # type: ignore[attr-defined]
    monkeypatch.setattr(integration, "MahavishnuWebSocketServer", _FakeServer)
    return _FakeServer


@pytest.fixture
def fake_consumer_cls(monkeypatch: pytest.MonkeyPatch) -> type[_FakeConsumer]:
    """Patch ``integration.EventBusConsumer`` to return ``_FakeConsumer``."""
    _FakeConsumer.created = []
    monkeypatch.setattr(integration, "EventBusConsumer", _FakeConsumer)
    return _FakeConsumer


@pytest.fixture
def tls_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``get_websocket_tls_config`` to return all defaults off."""
    monkeypatch.setattr(
        integration,
        "get_websocket_tls_config",
        lambda: {
            "tls_enabled": False,
            "cert_file": None,
            "key_file": None,
            "ca_file": None,
            "verify_client": False,
        },
    )


def _enabled_settings(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "websocket_enabled": True,
        "websocket_host": "127.0.0.1",
        "websocket_port": 8690,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# start_websocket_server — disabled branch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStartWebSocketServerDisabled:
    """Cover the early-return when websocket is disabled."""

    @pytest.mark.asyncio
    async def test_websocket_disabled_returns_none(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        settings = _enabled_settings(websocket_enabled=False)
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_default_websocket_enabled_setting_is_false(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        """When ``websocket_enabled`` attribute is missing, default to False (fail-closed).

        Regression test for
        ``docs/followups/2026-09-05-websocket-integration-settings-default-broadcaster-positional.md``.
        The previous default (``True``) silently enabled the WS server when
        settings was malformed; the safe default is off.
        """
        # No ``websocket_enabled`` attribute on settings — getattr now falls back to False.
        settings = SimpleNamespace(websocket_host="127.0.0.1", websocket_port=8690)
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert result is None


# ---------------------------------------------------------------------------
# start_websocket_server — successful start without event transport
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStartWebSocketServerBasic:
    """Cover the no-event-transport happy path."""

    @pytest.mark.asyncio
    async def test_starts_with_minimal_arguments(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        settings = _enabled_settings()
        pool_manager = object()

        result = await integration.start_websocket_server(
            pool_manager=pool_manager, settings=settings
        )

        assert isinstance(result, _FakeServer)
        assert result.is_running is True
        assert result.host == "127.0.0.1"
        assert result.port == 8690
        # No event_transport → no event_consumer attached
        assert result.event_consumer is None
        assert _FakeConsumer.created == []

    @pytest.mark.asyncio
    async def test_custom_host_port_from_args(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(),
            settings=settings,
            host="0.0.0.0",
            port=9999,
        )
        assert isinstance(result, _FakeServer)
        assert result.host == "0.0.0.0"
        assert result.port == 9999

    @pytest.mark.asyncio
    async def test_max_connections_and_rate_limit(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(result, _FakeServer)
        # The production code passes hard-coded 1000 / 100 to MahavishnuWebSocketServer
        assert result.max_connections == 1000
        assert result.message_rate_limit == 100

    @pytest.mark.asyncio
    async def test_auto_cert_passed_through(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(),
            settings=settings,
            auto_cert=True,
        )
        assert isinstance(result, _FakeServer)
        assert result.auto_cert is True

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(**kwargs: Any) -> _FakeServer:
            raise RuntimeError("kaboom")

        monkeypatch.setattr(integration, "MahavishnuWebSocketServer", boom)
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_start_raises(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If ``server.start()`` raises, the boundary handler returns None."""

        class _StartBoom(_FakeServer):
            async def start(self) -> None:
                raise RuntimeError("start failed")

        _StartBoom.calls_started = []  # type: ignore[attr-defined]
        _StartBoom.calls_stage = []  # type: ignore[attr-defined]
        _StartBoom.calls_completed = []  # type: ignore[attr-defined]
        _StartBoom.calls_failed = []  # type: ignore[attr-defined]
        _StartBoom.calls_pool_status = []  # type: ignore[attr-defined]
        _StartBoom.calls_worker_status = []  # type: ignore[attr-defined]
        monkeypatch.setattr(integration, "MahavishnuWebSocketServer", _StartBoom)
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert result is None


# ---------------------------------------------------------------------------
# start_websocket_server — TLS configuration branches
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStartWebSocketServerTLS:
    """Cover every TLS branch in start_websocket_server."""

    @pytest.mark.asyncio
    async def test_explicit_tls_enabled_true(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
    ) -> None:
        """When ``tls_enabled=True`` is passed explicitly, env config is ignored."""
        monkeypatch_get = pytest.MonkeyPatch()
        monkeypatch_get.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": "true",
                "cert_file": "/env/cert.pem",
                "key_file": "/env/key.pem",
                "ca_file": "/env/ca.pem",
                "verify_client": "true",
            },
        )
        try:
            settings = _enabled_settings()
            result = await integration.start_websocket_server(
                pool_manager=object(),
                settings=settings,
                tls_enabled=True,
                cert_file="/my/cert.pem",
                key_file="/my/key.pem",
                ca_file="/my/ca.pem",
                verify_client=True,
            )
            assert isinstance(result, _FakeServer)
            # Explicit args win over env
            assert result.cert_file == "/my/cert.pem"
            assert result.key_file == "/my/key.pem"
            assert result.ca_file == "/my/ca.pem"
            assert result.verify_client is True
            assert result.tls_enabled is True
        finally:
            monkeypatch_get.undo()

    @pytest.mark.asyncio
    async def test_env_tls_enabled_string_true(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``tls_enabled='true'`` (string) is normalised to bool True."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": "TRUE",
                "cert_file": "/env/cert.pem",
                "key_file": "/env/key.pem",
                "ca_file": "/env/ca.pem",
                "verify_client": "yes",
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(result, _FakeServer)
        assert result.tls_enabled is True
        assert result.cert_file == "/env/cert.pem"
        assert result.key_file == "/env/key.pem"
        assert result.ca_file == "/env/ca.pem"
        assert result.verify_client is True

    @pytest.mark.asyncio
    async def test_env_tls_enabled_string_false(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``tls_enabled='false'`` (string) is normalised to bool False."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": "false",
                "cert_file": None,
                "key_file": None,
                "ca_file": None,
                "verify_client": False,
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(result, _FakeServer)
        assert result.tls_enabled is False

    @pytest.mark.asyncio
    async def test_env_tls_enabled_unrecognised_string(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unrecognised string is coerced to ``None`` (tls_enabled becomes False)."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": "maybe",
                "cert_file": None,
                "key_file": None,
                "ca_file": None,
                "verify_client": False,
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(result, _FakeServer)
        # Falls back to False (None branch)
        assert result.tls_enabled is False

    @pytest.mark.asyncio
    async def test_env_tls_enabled_non_string_non_bool(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-str/non-bool TLS value triggers the ``else`` branch (None)."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": 42,  # int — neither bool nor str
                "cert_file": None,
                "key_file": None,
                "ca_file": None,
                "verify_client": False,
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(result, _FakeServer)
        # The ``else`` branch sets tls_enabled = None → server default False
        assert result.tls_enabled is False

    @pytest.mark.asyncio
    async def test_env_cert_files_non_string_kept(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When env cert files are non-str, the explicit kwarg is preserved."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": False,
                "cert_file": 123,
                "key_file": 456,
                "ca_file": 789,
                "verify_client": False,
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(),
            settings=settings,
            cert_file="/explicit/cert.pem",
            key_file="/explicit/key.pem",
            ca_file="/explicit/ca.pem",
        )
        assert isinstance(result, _FakeServer)
        # Explicit arg retained since env value is non-str
        assert result.cert_file == "/explicit/cert.pem"
        assert result.key_file == "/explicit/key.pem"
        assert result.ca_file == "/explicit/ca.pem"

    @pytest.mark.asyncio
    async def test_env_cert_files_string_used(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When env cert files are strings, they win when explicit is None."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": False,
                "cert_file": "/env/cert.pem",
                "key_file": "/env/key.pem",
                "ca_file": "/env/ca.pem",
                "verify_client": False,
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(result, _FakeServer)
        assert result.cert_file == "/env/cert.pem"
        assert result.key_file == "/env/key.pem"
        assert result.ca_file == "/env/ca.pem"

    @pytest.mark.asyncio
    async def test_env_verify_client_string_true(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """verify_client='1' string is parsed and OR-ed with explicit arg."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": False,
                "cert_file": None,
                "key_file": None,
                "ca_file": None,
                "verify_client": "1",
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(result, _FakeServer)
        assert result.verify_client is True

    @pytest.mark.asyncio
    async def test_env_verify_client_string_false(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """verify_client='no' string parses to False, keeps explicit False."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": False,
                "cert_file": None,
                "key_file": None,
                "ca_file": None,
                "verify_client": "no",
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(result, _FakeServer)
        assert result.verify_client is False

    @pytest.mark.asyncio
    async def test_env_verify_client_unrecognised_string(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Unrecognised verify_client string falls back to bool(explicit)."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": False,
                "cert_file": None,
                "key_file": None,
                "ca_file": None,
                "verify_client": "perhaps",
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings, verify_client=True
        )
        assert isinstance(result, _FakeServer)
        # bool(verify_client=True OR "perhaps") -> True
        assert result.verify_client is True

    @pytest.mark.asyncio
    async def test_env_verify_client_non_bool_non_str(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-bool/non-str verify_client falls through to bool(explicit)."""
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": False,
                "cert_file": None,
                "key_file": None,
                "ca_file": None,
                "verify_client": 7,
            },
        )
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(result, _FakeServer)
        # Falls to `bool(verify_client)` -> False
        assert result.verify_client is False

    @pytest.mark.asyncio
    async def test_no_tls_branch_uses_tls_enabled_false(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        """When tls_enabled stays None, server receives False."""
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            integration,
            "get_websocket_tls_config",
            lambda: {
                "tls_enabled": None,
                "cert_file": None,
                "key_file": None,
                "ca_file": None,
                "verify_client": False,
            },
        )
        try:
            settings = _enabled_settings()
            result = await integration.start_websocket_server(
                pool_manager=object(), settings=settings
            )
            assert isinstance(result, _FakeServer)
            assert result.tls_enabled is False
        finally:
            monkeypatch.undo()


# ---------------------------------------------------------------------------
# start_websocket_server — event transport branches
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStartWebSocketServerEventTransport:
    """Cover the event-transport + DLQ + notification router branches."""

    @pytest.mark.asyncio
    async def test_event_transport_without_dlq(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        settings = _enabled_settings()
        event_transport = object()
        result = await integration.start_websocket_server(
            pool_manager=object(),
            settings=settings,
            event_transport=event_transport,
        )
        assert isinstance(result, _FakeServer)
        assert len(_FakeConsumer.created) == 1
        consumer = _FakeConsumer.created[0]
        assert consumer.transport is event_transport
        assert consumer.started is True
        assert result.event_consumer is consumer
        # No DLQ handler at any level
        assert consumer.handler.dead_letter_handler is None  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_event_transport_with_dlq_no_notification(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        settings = _enabled_settings()
        dlq = object()
        result = await integration.start_websocket_server(
            pool_manager=object(),
            settings=settings,
            event_transport=object(),
            dead_letter_queue=dlq,
        )
        assert isinstance(result, _FakeServer)
        consumer = _FakeConsumer.created[0]
        # The handler is a single RetryingEventEnvelopeHandler (no composite)
        assert isinstance(consumer.handler, RetryingEventEnvelopeHandler)
        assert consumer.handler.dead_letter_handler is not None
        assert isinstance(
            consumer.handler.handler,  # type: ignore[attr-defined]
            _FakeServer,  # MahavishnuWebSocketServer substitute
        )

    @pytest.mark.asyncio
    async def test_event_transport_with_notification_router(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(),
            settings=settings,
            event_transport=object(),
            notification_router=object(),
        )
        assert isinstance(result, _FakeServer)
        consumer = _FakeConsumer.created[0]
        # With notification router we get a CompositeEventEnvelopeHandler
        assert isinstance(consumer.handler, CompositeEventEnvelopeHandler)
        # Both sub-handlers are RetryingEventEnvelopeHandler
        for sub in consumer.handler.handlers:
            assert isinstance(sub, RetryingEventEnvelopeHandler)
        # One of them wraps a NotificationEventHandler
        assert any(
            isinstance(sub.handler, NotificationEventHandler)
            for sub in consumer.handler.handlers
        )

    @pytest.mark.asyncio
    async def test_event_transport_with_dlq_and_notification(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        settings = _enabled_settings()
        result = await integration.start_websocket_server(
            pool_manager=object(),
            settings=settings,
            event_transport=object(),
            dead_letter_queue=object(),
            notification_router=object(),
        )
        assert isinstance(result, _FakeServer)
        consumer = _FakeConsumer.created[0]
        assert isinstance(consumer.handler, CompositeEventEnvelopeHandler)
        # Both sub-handlers carry a DLQ handler
        for sub in consumer.handler.handlers:
            assert sub.dead_letter_handler is not None


# ---------------------------------------------------------------------------
# stop_websocket_server
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStopWebSocketServer:
    """Cover ``stop_websocket_server`` happy + error paths."""

    @pytest.mark.asyncio
    async def test_none_server_is_noop(self) -> None:
        # Should not raise
        await integration.stop_websocket_server(None)

    @pytest.mark.asyncio
    async def test_stop_running_server(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        await integration.stop_websocket_server(server)
        assert server.is_running is False

    @pytest.mark.asyncio
    async def test_stop_exception_is_swallowed(self) -> None:
        class _StopBoom(_FakeServer):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.calls_started = []
                self.calls_stage = []
                self.calls_completed = []
                self.calls_failed = []
                self.calls_pool_status = []
                self.calls_worker_status = []

            async def stop(self) -> None:
                raise RuntimeError("stop failed")

        server = _StopBoom(pool_manager=object(), host="127.0.0.1", port=8690)
        # Should not raise
        await integration.stop_websocket_server(server)


# ---------------------------------------------------------------------------
# get_websocket_status
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetWebSocketStatus:
    """Cover ``get_websocket_status`` for both None and live server."""

    def test_status_when_server_is_none(self) -> None:
        status = integration.get_websocket_status(None)
        assert status == {
            "enabled": False,
            "status": "not_initialized",
            "host": "127.0.0.1",
            "port": 8690,
            "secure": False,
        }

    def test_status_when_server_running(self) -> None:
        server = _make_fake_server(host="127.0.0.1", port=9000)
        server.is_running = True
        server.connections = {"c1": object(), "c2": object()}
        server.connection_rooms = {"r1": {"c1"}, "r2": {"c2"}}
        server.uri = "ws://127.0.0.1:9000"

        status = integration.get_websocket_status(server)

        assert status == {
            "enabled": True,
            "status": "running",
            "host": "127.0.0.1",
            "port": 9000,
            "uri": "ws://127.0.0.1:9000",
            "secure": False,
            "connections": 2,
            "rooms": 2,
        }

    def test_status_when_server_stopped(self) -> None:
        server = _make_fake_server()
        server.is_running = False
        # Stopped server reports zero connections / rooms
        status = integration.get_websocket_status(server)
        assert status["status"] == "stopped"
        assert status["connections"] == 0
        assert status["rooms"] == 0

    def test_status_secure_when_ssl_context_present(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        server.ssl_context = object()  # truthy
        status = integration.get_websocket_status(server)
        assert status["secure"] is True


# ---------------------------------------------------------------------------
# broadcast_workflow_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBroadcastWorkflowEvent:
    """Cover ``broadcast_workflow_event`` happy + error paths."""

    @pytest.mark.asyncio
    async def test_returns_false_when_server_is_none(self) -> None:
        result = await integration.broadcast_workflow_event(
            None, "started", "wf-1", {"prompt": "x"}
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_server_not_running(self) -> None:
        server = _make_fake_server()
        server.is_running = False
        result = await integration.broadcast_workflow_event(
            server, "started", "wf-1", {"prompt": "x"}
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_started_event(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_workflow_event(
            server, "started", "wf-1", {"prompt": "x"}
        )
        assert result is True
        assert server.calls_started == [("wf-1", {"prompt": "x"})]

    @pytest.mark.asyncio
    async def test_stage_completed_event(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_workflow_event(
            server,
            "stage_completed",
            "wf-1",
            {"stage_name": "build", "result": {"status": "ok"}},
        )
        assert result is True
        assert server.calls_stage == [("wf-1", "build", {"status": "ok"})]

    @pytest.mark.asyncio
    async def test_stage_completed_uses_defaults(self) -> None:
        """Missing stage_name / result defaults are applied."""
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_workflow_event(
            server, "stage_completed", "wf-1", {}
        )
        assert result is True
        assert server.calls_stage == [("wf-1", "unknown", {})]

    @pytest.mark.asyncio
    async def test_completed_event(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_workflow_event(
            server, "completed", "wf-1", {"status": "ok"}
        )
        assert result is True
        assert server.calls_completed == [("wf-1", {"status": "ok"})]

    @pytest.mark.asyncio
    async def test_failed_event(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_workflow_event(
            server, "failed", "wf-1", {"error": "boom"}
        )
        assert result is True
        assert server.calls_failed == [("wf-1", "boom")]

    @pytest.mark.asyncio
    async def test_failed_event_default_error(self) -> None:
        """Missing error key falls back to ``Unknown error``."""
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_workflow_event(
            server, "failed", "wf-1", {}
        )
        assert result is True
        assert server.calls_failed == [("wf-1", "Unknown error")]

    @pytest.mark.asyncio
    async def test_unknown_event_type_returns_false(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_workflow_event(
            server, "not_a_real_event", "wf-1", {}
        )
        assert result is False
        # No broadcast method should have been called
        assert server.calls_started == []
        assert server.calls_stage == []
        assert server.calls_completed == []
        assert server.calls_failed == []

    @pytest.mark.asyncio
    async def test_broadcast_exception_returns_false(self) -> None:
        """Server raising during broadcast must be swallowed and return False."""
        server = _make_fake_server()
        server.is_running = True
        server.broadcast_workflow_started = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom")
        )
        result = await integration.broadcast_workflow_event(
            server, "started", "wf-1", {}
        )
        assert result is False


# ---------------------------------------------------------------------------
# broadcast_pool_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBroadcastPoolEvent:
    """Cover ``broadcast_pool_event`` happy + error paths."""

    @pytest.mark.asyncio
    async def test_returns_false_when_server_is_none(self) -> None:
        result = await integration.broadcast_pool_event(
            None, "status_changed", "pool-1", {"status": "ok"}
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_server_not_running(self) -> None:
        server = _make_fake_server()
        server.is_running = False
        result = await integration.broadcast_pool_event(
            server, "status_changed", "pool-1", {"status": "ok"}
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_status_changed_event(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_pool_event(
            server, "status_changed", "pool-1", {"workers": 3}
        )
        assert result is True
        assert server.calls_pool_status == [("pool-1", {"workers": 3})]

    @pytest.mark.asyncio
    async def test_worker_status_changed_event(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_pool_event(
            server,
            "worker_status_changed",
            "pool-1",
            {"worker_id": "w-1", "status": "busy"},
        )
        assert result is True
        assert server.calls_worker_status == [("w-1", "busy", "pool-1")]

    @pytest.mark.asyncio
    async def test_worker_status_changed_defaults(self) -> None:
        """Missing worker_id / status use ``unknown`` placeholders."""
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_pool_event(
            server, "worker_status_changed", "pool-1", {}
        )
        assert result is True
        assert server.calls_worker_status == [("unknown", "unknown", "pool-1")]

    @pytest.mark.asyncio
    async def test_unknown_event_type_returns_false(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        result = await integration.broadcast_pool_event(
            server, "mystery_event", "pool-1", {}
        )
        assert result is False
        assert server.calls_pool_status == []
        assert server.calls_worker_status == []

    @pytest.mark.asyncio
    async def test_broadcast_exception_returns_false(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        server.broadcast_pool_status_changed = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("boom")
        )
        result = await integration.broadcast_pool_event(
            server, "status_changed", "pool-1", {}
        )
        assert result is False


# ---------------------------------------------------------------------------
# WebSocketBroadcaster helper class
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWebSocketBroadcasterHelper:
    """Cover the convenience wrapper class in ``integration.py``."""

    def test_init_stores_server(self) -> None:
        server = _make_fake_server()
        b = integration.WebSocketBroadcaster(server)
        assert b.server is server

    def test_init_with_none(self) -> None:
        b = integration.WebSocketBroadcaster(None)
        assert b.server is None

    def test_init_no_args(self) -> None:
        """``WebSocketBroadcaster()`` (no args) constructs cleanly with server=None.

        Regression test for
        ``docs/followups/2026-09-05-websocket-integration-settings-default-broadcaster-positional.md``.
        The previous signature required ``server`` positionally; the new
        default makes deferred wiring possible.
        """
        b = integration.WebSocketBroadcaster()
        assert b.server is None

    @pytest.mark.asyncio
    async def test_workflow_started_delegates(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        b = integration.WebSocketBroadcaster(server)
        result = await b.workflow_started("wf-1", {"prompt": "x"})
        assert result is True
        assert server.calls_started == [("wf-1", {"prompt": "x"})]

    @pytest.mark.asyncio
    async def test_workflow_stage_completed_delegates(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        b = integration.WebSocketBroadcaster(server)
        result = await b.workflow_stage_completed("wf-1", "stage-a", {"r": 1})
        assert result is True
        assert server.calls_stage == [("wf-1", "stage-a", {"r": 1})]

    @pytest.mark.asyncio
    async def test_workflow_completed_delegates(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        b = integration.WebSocketBroadcaster(server)
        result = await b.workflow_completed("wf-1", {"status": "ok"})
        assert result is True
        assert server.calls_completed == [("wf-1", {"status": "ok"})]

    @pytest.mark.asyncio
    async def test_workflow_failed_delegates(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        b = integration.WebSocketBroadcaster(server)
        result = await b.workflow_failed("wf-1", "boom")
        assert result is True
        assert server.calls_failed == [("wf-1", "boom")]

    @pytest.mark.asyncio
    async def test_pool_status_changed_delegates(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        b = integration.WebSocketBroadcaster(server)
        result = await b.pool_status_changed("pool-1", {"state": "active"})
        assert result is True
        assert server.calls_pool_status == [("pool-1", {"state": "active"})]

    @pytest.mark.asyncio
    async def test_worker_status_changed_delegates(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        b = integration.WebSocketBroadcaster(server)
        result = await b.worker_status_changed("w-1", "busy", "pool-1")
        assert result is True
        assert server.calls_worker_status == [("w-1", "busy", "pool-1")]

    @pytest.mark.asyncio
    async def test_workflow_started_returns_false_when_server_none(self) -> None:
        b = integration.WebSocketBroadcaster(None)
        result = await b.workflow_started("wf-1", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_workflow_stage_completed_returns_false_when_server_none(self) -> None:
        b = integration.WebSocketBroadcaster(None)
        result = await b.workflow_stage_completed("wf-1", "stage", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_workflow_completed_returns_false_when_server_none(self) -> None:
        b = integration.WebSocketBroadcaster(None)
        result = await b.workflow_completed("wf-1", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_workflow_failed_returns_false_when_server_none(self) -> None:
        b = integration.WebSocketBroadcaster(None)
        result = await b.workflow_failed("wf-1", "err")
        assert result is False

    @pytest.mark.asyncio
    async def test_pool_status_changed_returns_false_when_server_none(self) -> None:
        b = integration.WebSocketBroadcaster(None)
        result = await b.pool_status_changed("pool-1", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_worker_status_changed_returns_false_when_server_none(self) -> None:
        b = integration.WebSocketBroadcaster(None)
        result = await b.worker_status_changed("w-1", "busy", "pool-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_workflow_started_returns_false_when_server_not_running(self) -> None:
        server = _make_fake_server()
        server.is_running = False
        b = integration.WebSocketBroadcaster(server)
        result = await b.workflow_started("wf-1", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_pool_status_changed_returns_false_when_server_not_running(self) -> None:
        server = _make_fake_server()
        server.is_running = False
        b = integration.WebSocketBroadcaster(server)
        result = await b.pool_status_changed("pool-1", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_broadcaster_propagates_exception_to_false(self) -> None:
        """If the underlying server raises, the wrapper returns False."""
        server = _make_fake_server()
        server.is_running = True
        server.broadcast_workflow_failed = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("kaboom")
        )
        b = integration.WebSocketBroadcaster(server)
        result = await b.workflow_failed("wf-1", "err")
        assert result is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEdgeCases:
    """Cover less common interaction patterns."""

    @pytest.mark.asyncio
    async def test_broadcast_with_no_correlation_id_field(
        self,
    ) -> None:
        """stage_completed dict with empty stage_name still produces broadcast."""
        server = _make_fake_server()
        server.is_running = True
        await integration.broadcast_workflow_event(
            server, "stage_completed", "wf-x", {"stage_name": "", "result": {}}
        )
        assert server.calls_stage == [("wf-x", "", {})]

    @pytest.mark.asyncio
    async def test_broadcast_pool_status_changed_with_no_status_data(self) -> None:
        server = _make_fake_server()
        server.is_running = True
        await integration.broadcast_pool_event(
            server, "status_changed", "pool-x", {}
        )
        assert server.calls_pool_status == [("pool-x", {})]

    @pytest.mark.asyncio
    async def test_lifecycle_start_then_stop(
        self,
        fake_server_cls: type[_FakeServer],
        fake_consumer_cls: type[_FakeConsumer],
        tls_disabled: None,
    ) -> None:
        """Full start → status → stop lifecycle."""
        settings = _enabled_settings()
        server = await integration.start_websocket_server(
            pool_manager=object(), settings=settings
        )
        assert isinstance(server, _FakeServer)
        assert server.is_running is True

        status = integration.get_websocket_status(server)
        assert status["status"] == "running"

        await integration.stop_websocket_server(server)
        assert server.is_running is False

        status_after = integration.get_websocket_status(server)
        assert status_after["status"] == "stopped"