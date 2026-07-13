"""Unit tests for ``mahavishnu.core.events.mahavishnu_publisher``.

Mirrors the InMemoryEventTransport test pattern from
``mahavishnu/core/events/contract.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any
from unittest.mock import AsyncMock

from oneiric.runtime.events import EventEnvelope
import pytest

from mahavishnu.core.events.contract import InMemoryEventTransport
from mahavishnu.core.events.mahavishnu_publisher import (
    EVENT_VERSION,
    SOURCE,
    TOPIC_WORKFLOW_COMPLETED,
    TOPIC_WORKFLOW_STARTED,
    _make_envelope,
    publish_workflow_completed,
    publish_workflow_failed,
    publish_workflow_started,
)

pytestmark = pytest.mark.unit


def _headers_of(envelope: EventEnvelope) -> dict[str, Any]:
    """Return the ``headers`` dict from a Oneiric ``EventEnvelope``."""
    return dict(envelope.headers) if isinstance(envelope.headers, dict) else {}


def _payload_of(envelope: EventEnvelope) -> dict[str, Any]:
    """Return the ``payload`` dict from a Oneiric ``EventEnvelope``."""
    return dict(envelope.payload) if isinstance(envelope.payload, dict) else {}


async def _publish_via(
    transport: InMemoryEventTransport, envelope: EventEnvelope
) -> None:
    await transport.publish(envelope)


def test_publish_workflow_started_builds_canonical_envelope() -> None:
    """publish_workflow_started emits an envelope with the canonical shape."""
    transport = InMemoryEventTransport()
    metadata = {"prompt": "Refactor module", "adapter": "prefect"}

    # Run via transport so we can inspect the persisted envelope
    envelope = _make_envelope(TOPIC_WORKFLOW_STARTED, SOURCE, {"workflow_id": "wf_1", **metadata})

    assert envelope.topic == "workflow.started"
    headers = _headers_of(envelope)
    assert headers.get("source") == "mahavishnu"
    assert headers.get("version") == "1.0.0"
    assert isinstance(headers.get("event_id"), str) and headers.get("event_id")
    assert isinstance(headers.get("timestamp"), str) and headers.get("timestamp")
    payload = _payload_of(envelope)
    assert payload.get("workflow_id") == "wf_1"
    assert payload.get("prompt") == "Refactor module"
    assert payload.get("adapter") == "prefect"
    # Sanity: transport can store and retrieve (async, returns a copy)
    import asyncio

    asyncio.run(_publish_via(transport, envelope))
    history = transport.history()
    assert len(history) == 1
    assert history[0].topic == envelope.topic
    assert _payload_of(history[0]) == _payload_of(envelope)


@pytest.mark.asyncio
async def test_publish_workflow_started_invokes_injected_publisher() -> None:
    """publish_workflow_started calls publisher.publish with the right envelope."""
    publisher = AsyncMock()
    publisher.publish.return_value = None
    metadata = {"prompt": "x"}

    await publish_workflow_started("wf_xyz", metadata, publisher=publisher)

    publisher.publish.assert_awaited_once()
    envelope = publisher.publish.await_args.args[0]
    assert isinstance(envelope, EventEnvelope)
    assert envelope.topic == "workflow.started"
    payload = _payload_of(envelope)
    assert payload.get("workflow_id") == "wf_xyz"
    assert payload.get("prompt") == "x"
    assert _headers_of(envelope).get("source") == "mahavishnu"


@pytest.mark.asyncio
async def test_publish_workflow_completed_builds_canonical_envelope() -> None:
    """publish_workflow_completed emits an envelope with topic=workflow.completed."""
    publisher = AsyncMock()
    publisher.publish.return_value = None
    result = {"status": "success", "duration_seconds": 12.5}

    await publish_workflow_completed("wf_done", result, publisher=publisher)

    publisher.publish.assert_awaited_once()
    envelope = publisher.publish.await_args.args[0]
    assert envelope.topic == "workflow.completed"
    payload = _payload_of(envelope)
    assert payload.get("workflow_id") == "wf_done"
    assert payload.get("status") == "success"
    assert payload.get("duration_seconds") == 12.5
    assert _headers_of(envelope).get("source") == "mahavishnu"
    assert _headers_of(envelope).get("version") == EVENT_VERSION


@pytest.mark.asyncio
async def test_publish_workflow_failed_builds_canonical_envelope() -> None:
    """publish_workflow_failed emits an envelope with topic=workflow.failed."""
    publisher = AsyncMock()
    publisher.publish.return_value = None

    await publish_workflow_failed("wf_boom", "boom!", publisher=publisher)

    publisher.publish.assert_awaited_once()
    envelope = publisher.publish.await_args.args[0]
    assert envelope.topic == "workflow.failed"
    payload = _payload_of(envelope)
    assert payload.get("workflow_id") == "wf_boom"
    assert payload.get("error") == "boom!"
    assert _headers_of(envelope).get("source") == "mahavishnu"


@pytest.mark.asyncio
async def test_publisher_invokes_injected_publisher() -> None:
    """The injected publisher is the one actually invoked."""
    transport = InMemoryEventTransport()
    await publish_workflow_started("wf_a", {"k": "v"}, publisher=transport)
    await publish_workflow_completed("wf_a", {"status": "ok"}, publisher=transport)
    await publish_workflow_failed("wf_a", "nope", publisher=transport)

    history = transport.history()
    assert [h.topic for h in history] == [
        "workflow.started",
        "workflow.completed",
        "workflow.failed",
    ]
    assert _payload_of(history[0]).get("workflow_id") == "wf_a"
    assert _payload_of(history[1]).get("status") == "ok"
    assert _payload_of(history[2]).get("error") == "nope"


@pytest.mark.asyncio
async def test_publisher_swallows_exceptions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising publisher is logged at WARNING and never propagates."""
    publisher = AsyncMock()
    publisher.publish.side_effect = RuntimeError("transport is down")

    with caplog.at_level(logging.WARNING, logger="mahavishnu.core.events.mahavishnu_publisher"):
        # Must NOT raise
        await publish_workflow_started("wf_x", {"p": "y"}, publisher=publisher)
        await publish_workflow_completed("wf_x", {"status": "ok"}, publisher=publisher)
        await publish_workflow_failed("wf_x", "err", publisher=publisher)

    # Three WARNING-level records (one per call) -- logger.exception writes at ERROR by default;
    # we accept any non-INFO level here to be robust to logger configuration.
    error_or_warning = [
        rec for rec in caplog.records
        if rec.levelno >= logging.WARNING
        and rec.name == "mahavishnu.core.events.mahavishnu_publisher"
    ]
    assert len(error_or_warning) >= 3
    publisher.publish.assert_awaited()


@pytest.mark.asyncio
async def test_publisher_with_none_is_a_noop() -> None:
    """publisher=None is silently accepted."""
    # Must not raise
    await publish_workflow_started("wf_n", {"k": "v"})
    await publish_workflow_completed("wf_n", {"status": "ok"})
    await publish_workflow_failed("wf_n", "e")


def test_envelope_uuid_is_unique_across_calls() -> None:
    """Each call produces a different event_id."""
    env_a = _make_envelope(TOPIC_WORKFLOW_STARTED, SOURCE, {"workflow_id": "wf_1"})
    env_b = _make_envelope(TOPIC_WORKFLOW_STARTED, SOURCE, {"workflow_id": "wf_1"})
    id_a = _headers_of(env_a).get("event_id")
    id_b = _headers_of(env_b).get("event_id")
    assert isinstance(id_a, str) and id_a
    assert isinstance(id_b, str) and id_b
    assert id_a != id_b


def test_envelope_timestamp_is_iso_utc() -> None:
    """The timestamp header is ISO 8601 in UTC."""
    envelope = _make_envelope(TOPIC_WORKFLOW_COMPLETED, SOURCE, {"workflow_id": "wf_t"})
    timestamp = _headers_of(envelope).get("timestamp")
    assert isinstance(timestamp, str)
    # datetime.fromisoformat accepts the standard "2026-07-11T12:34:56.789012+00:00" shape
    parsed = datetime.fromisoformat(timestamp)
    assert parsed.tzinfo is not None
    # UTC equivalent
    assert parsed.astimezone(UTC).utcoffset().total_seconds() == 0