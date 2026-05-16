from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from mahavishnu.core.events.transport import (
    CompositeEventEnvelopeHandler,
    NotificationEventHandler,
    RetryingEventEnvelopeHandler,
)
from mahavishnu.websocket import integration


@dataclass
class _FakeServer:
    pool_manager: Any
    host: str
    port: int
    ssl_context: None = None
    is_running: bool = False
    event_consumer: Any = None

    def __init__(self, **kwargs: Any) -> None:
        self.pool_manager = kwargs["pool_manager"]
        self.host = kwargs["host"]
        self.port = kwargs["port"]
        self.ssl_context = None
        self.is_running = False
        self.event_consumer = None

    async def start(self) -> None:
        self.is_running = True


class _FakeConsumer:
    created: list[_FakeConsumer] = []

    def __init__(self, *, transport: Any, handler: Any) -> None:
        self.transport = transport
        self.handler = handler
        self.started = False
        self.__class__.created.append(self)

    async def start(self) -> None:
        self.started = True


@pytest.mark.asyncio
async def test_start_websocket_server_uses_notification_router_when_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "MahavishnuWebSocketServer", _FakeServer)
    monkeypatch.setattr(integration, "EventBusConsumer", _FakeConsumer)
    monkeypatch.setattr(
        integration,
        "get_websocket_tls_config",
        lambda: {"tls_enabled": False, "cert_file": None, "key_file": None, "ca_file": None},
    )

    settings = SimpleNamespace(
        websocket_enabled=True,
        websocket_host="127.0.0.1",
        websocket_port=9876,
    )
    pool_manager = object()
    event_transport = object()
    notification_router = object()

    server = await integration.start_websocket_server(
        pool_manager=pool_manager,
        settings=settings,
        event_transport=event_transport,
        notification_router=notification_router,
    )

    assert isinstance(server, _FakeServer)
    assert server.is_running is True
    assert _FakeConsumer.created
    consumer = _FakeConsumer.created[-1]
    assert consumer.transport is event_transport
    assert isinstance(consumer.handler, CompositeEventEnvelopeHandler)
    assert any(
        isinstance(handler, RetryingEventEnvelopeHandler) for handler in consumer.handler.handlers
    )
    assert any(
        isinstance(handler.handler, NotificationEventHandler)
        for handler in consumer.handler.handlers
    )
    assert consumer.started is True
    assert server.event_consumer is consumer
