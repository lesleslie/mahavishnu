"""Unit tests for ``mahavishnu.core.events.mahavishnu_publisher``.

Mirrors the InMemoryEventTransport test pattern from
``mahavishnu/core/events/contract.py`` and verifies the canonical
Oneiric envelope contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any
from unittest.mock import AsyncMock

from oneiric.runtime.events import EventEnvelope
import pytest

from mahavishnu.core.events.canonical import RESERVED_EVENT_HEADERS
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


class _RecordingPublisher:
    """In-process fake that captures every published Oneiric envelope.

    Satisfies the canonical :class:`OneiricEventPublisherProtocol`
    because the protocol accepts either a coroutine return or a
    plain object. The recording implementation is intentionally
    synchronous — the lifecycle functions only need to consume the
    awaitable or non-awaitable result uniformly.
    """

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope] = []

    async def publish(self, envelope: EventEnvelope) -> None:
        self.envelopes.append(envelope)


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
async def test_publish_workflow_started_invokes_recording_publisher() -> None:
    """publish_workflow_started forwards a recorded Oneiric envelope to the publisher."""
    publisher = _RecordingPublisher()
    metadata = {"prompt": "x"}

    await publish_workflow_started("wf_xyz", metadata, publisher=publisher)

    assert len(publisher.envelopes) == 1
    envelope = publisher.envelopes[0]
    assert isinstance(envelope, EventEnvelope)
    assert envelope.topic == "workflow.started"
    payload = _payload_of(envelope)
    assert payload.get("workflow_id") == "wf_xyz"
    assert payload.get("prompt") == "x"
    headers = _headers_of(envelope)
    assert headers.get("source") == "mahavishnu"
    # Reserved headers must appear exactly once each
    for reserved in RESERVED_EVENT_HEADERS & {"event_id", "source", "version", "timestamp"}:
        assert headers.get(reserved), f"missing reserved header {reserved}"


@pytest.mark.asyncio
async def test_publish_workflow_completed_builds_canonical_envelope() -> None:
    """publish_workflow_completed emits a workflow.completed envelope with reserved headers set."""
    publisher = _RecordingPublisher()
    result = {"status": "success", "duration_seconds": 12.5}

    await publish_workflow_completed("wf_done", result, publisher=publisher)

    assert len(publisher.envelopes) == 1
    envelope = publisher.envelopes[0]
    assert envelope.topic == "workflow.completed"
    payload = _payload_of(envelope)
    assert payload.get("workflow_id") == "wf_done"
    assert payload.get("status") == "success"
    assert payload.get("duration_seconds") == 12.5
    headers = _headers_of(envelope)
    assert headers.get("source") == "mahavishnu"
    assert headers.get("version") == EVENT_VERSION


@pytest.mark.asyncio
async def test_publish_workflow_failed_builds_canonical_envelope() -> None:
    """publish_workflow_failed emits a workflow.failed envelope."""
    publisher = _RecordingPublisher()

    await publish_workflow_failed("wf_boom", "boom!", publisher=publisher)

    assert len(publisher.envelopes) == 1
    envelope = publisher.envelopes[0]
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
    """publisher=None is silently accepted (a sibling recorder sees zero envelopes)."""
    # A sibling recording publisher confirms no global state was written when
    # we passed publisher=None to each lifecycle call.
    sibling = _RecordingPublisher()
    # Must not raise
    await publish_workflow_started("wf_n", {"k": "v"}, publisher=None)
    await publish_workflow_completed("wf_n", {"status": "ok"}, publisher=None)
    await publish_workflow_failed("wf_n", "e", publisher=None)

    # And the default (no publisher arg) path stays clean too.
    await publish_workflow_started("wf_default", {"k": "v"})
    await publish_workflow_completed("wf_default", {"status": "ok"})
    await publish_workflow_failed("wf_default", "e")

    # The sibling recorder saw nothing.
    assert sibling.envelopes == []


@pytest.mark.asyncio
async def test_recording_publisher_receives_three_envelopes() -> None:
    """A recording publisher captures the start/complete/failed envelopes in order."""
    publisher = _RecordingPublisher()

    await publish_workflow_started("wf_seq", {"prompt": "p"}, publisher=publisher)
    await publish_workflow_completed("wf_seq", {"status": "ok"}, publisher=publisher)
    await publish_workflow_failed("wf_seq", "boom", publisher=publisher)

    assert [e.topic for e in publisher.envelopes] == [
        "workflow.started",
        "workflow.completed",
        "workflow.failed",
    ]


@pytest.mark.asyncio
async def test_publisher_preserves_payload_identity() -> None:
    """The lifecycle functions pass a payload containing the original kwargs unchanged."""
    publisher = _RecordingPublisher()
    metadata = {"prompt": "Refactor", "tags": ["x", "y"]}

    await publish_workflow_started("wf_payload", metadata, publisher=publisher)

    [envelope] = publisher.envelopes
    payload = envelope.payload
    assert payload["workflow_id"] == "wf_payload"
    assert payload["prompt"] == "Refactor"
    assert payload["tags"] == ["x", "y"]


@pytest.mark.asyncio
async def test_publisher_records_reserved_headers_exactly_once() -> None:
    """Required reserved headers (event_id/source/version/timestamp) appear exactly once."""
    publisher = _RecordingPublisher()

    await publish_workflow_started("wf_unique", {"k": "v"}, publisher=publisher)

    [envelope] = publisher.envelopes
    headers = envelope.headers
    for reserved in ("event_id", "source", "version", "timestamp"):
        # Exactly one occurrence of each reserved header (defensive vs. duplicate-header collisions).
        occurrences = sum(1 for key in headers if key == reserved)
        assert occurrences == 1, f"reserved header {reserved} appeared {occurrences} times"
    assert headers["source"] == SOURCE
    assert headers["version"] == EVENT_VERSION


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
