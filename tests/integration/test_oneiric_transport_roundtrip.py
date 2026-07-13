"""Real Oneiric EventBridge transport integration tests for Mahavishnu.

Mirrors the parallel tests in
``crackerjack/tests/integration/test_oneiric_transport_roundtrip.py``
and ``akosha/tests/integration/test_oneiric_transport_roundtrip.py``.
Exercises the full ``publish_workflow_* -> EventBridgePublisher ->
emit`` path against a real ``oneiric.domains.events.EventBridge``.
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from oneiric.core.config import LayerSettings
from oneiric.core.lifecycle import LifecycleManager
from oneiric.core.resolution import Resolver
from oneiric.domains.events import EventBridge
from oneiric.runtime.events import EventEnvelope, EventHandler, HandlerResult

from mahavishnu.core.events.eventbridge_adapter import EventBridgePublisher
from mahavishnu.core.events.mahavishnu_publisher import (
    publish_workflow_completed,
    publish_workflow_failed,
    publish_workflow_started,
)


pytestmark = [pytest.mark.integration, pytest.mark.timeout(30)]


class _CapturingDispatcher:
    def __init__(self) -> None:
        self.captured: list[EventEnvelope] = []
        self._handlers: list[EventHandler] = []

    async def dispatch(self, envelope: EventEnvelope) -> list[HandlerResult]:
        self.captured.append(envelope)
        results: list[HandlerResult] = []
        for handler in self._handlers:
            if not handler.accepts(envelope):
                continue
            try:
                value = handler.callback(envelope)
                if inspect.isawaitable(value):
                    await value
                results.append(
                    HandlerResult(handler=handler.name, success=True, duration=0.0)
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    HandlerResult(
                        handler=handler.name,
                        success=False,
                        duration=0.0,
                        error=str(exc),
                    )
                )
        return results

    def register(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def handlers(self) -> list[EventHandler]:
        return list(self._handlers)


def _build_real_eventbridge() -> tuple[EventBridge, _CapturingDispatcher]:
    resolver = Resolver()
    lifecycle = LifecycleManager(resolver)
    settings = LayerSettings()
    bridge = EventBridge(resolver, lifecycle, settings)
    dispatcher = _CapturingDispatcher()
    bridge._dispatcher = dispatcher  # noqa: SLF001 -- test-only
    return bridge, dispatcher


@pytest.mark.asyncio
async def test_publish_workflow_started_round_trips_through_real_eventbridge() -> None:
    bridge, dispatcher = _build_real_eventbridge()
    publisher = EventBridgePublisher(bridge)

    await publish_workflow_started(
        "wf_rt",
        {"adapter": "prefect", "tags": ["smoke"]},
        publisher=publisher,
    )

    envelope = dispatcher.captured[0]
    assert envelope.topic == "workflow.started"
    assert envelope.headers.get("source") == "mahavishnu"
    assert envelope.payload.get("workflow_id") == "wf_rt"


@pytest.mark.asyncio
async def test_publish_workflow_completed_round_trips() -> None:
    bridge, dispatcher = _build_real_eventbridge()
    publisher = EventBridgePublisher(bridge)

    await publish_workflow_completed(
        "wf_done",
        {"success": True, "duration": 1.2},
        publisher=publisher,
    )

    envelope = dispatcher.captured[0]
    assert envelope.topic == "workflow.completed"
    assert envelope.payload.get("workflow_id") == "wf_done"


@pytest.mark.asyncio
async def test_publish_workflow_failed_round_trips() -> None:
    bridge, dispatcher = _build_real_eventbridge()
    publisher = EventBridgePublisher(bridge)

    await publish_workflow_failed(
        "wf_boom",
        "boom",
        publisher=publisher,
    )

    envelope = dispatcher.captured[0]
    assert envelope.topic == "workflow.failed"
    assert envelope.payload.get("error") == "boom"


@pytest.mark.asyncio
async def test_publisher_with_none_does_not_invoke_bridge() -> None:
    """publisher=None: publish_workflow_* short-circuits before bridge."""
    bridge, dispatcher = _build_real_eventbridge()
    await publish_workflow_started("wf_none", {"adapter": "prefect"})
    assert dispatcher.captured == []
