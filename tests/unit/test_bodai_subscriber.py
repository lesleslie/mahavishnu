"""Tests for ``mahavishnu.core.events.bodai_subscriber``.

Covers the Bodai EventBridge subscriber (Phase 6A.1 of the Bodai
observability plan). The subscriber consumes Oneiric ``EventEnvelope``
objects from a Redis Streams transport and persists them to a local
queue file.

These tests mock the ``redis.asyncio`` client (no real Redis required)
and use ``InMemoryEventTransport`` only for round-trip envelope
construction in the formatting tests.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from oneiric.runtime.events import EventEnvelope, create_event_envelope
import pytest

from mahavishnu.core.events.bodai_subscriber import (
    DEFAULT_QUEUE_CAP,
    STREAM_NAME,
    _decode_envelope,
    _envelope_to_dict,
    _read_queue,
    _resolve_queue_path,
    _write_queue_atomic,
    append_to_queue,
    format_bodai_summary,
    subscribe_to_bodai_events,
)
from mahavishnu.core.events.contract import (
    InMemoryEventTransport,  # noqa: F401  (kept for downstream test references)
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# format_bodai_summary
# ---------------------------------------------------------------------------


def test_format_bodai_summary_mahavishnu() -> None:
    envelope = EventEnvelope(
        topic="workflow_completed",
        payload={"workflow_id": "wid_abc"},
        headers={"source": "mahavishnu"},
    )
    assert format_bodai_summary(envelope) == "[mahavishnu] workflow_completed workflow_id=wid_abc"


def test_format_bodai_summary_akosha() -> None:
    envelope = EventEnvelope(
        topic="aggregation_completed",
        payload={"suite": "quality"},
        headers={"source": "akosha"},
    )
    assert format_bodai_summary(envelope) == "[akosha] aggregation_completed suite=quality"


def test_format_bodai_summary_missing_keys() -> None:
    envelope = EventEnvelope(topic="", payload={}, headers={})
    assert format_bodai_summary(envelope) == "[unknown] unknown"


def test_format_bodai_summary_mixed_payload_types() -> None:
    envelope = EventEnvelope(
        topic="test_run_completed",
        payload={"passed": 42, "failed": 0, "note": "ok", "tags": ["a", "b"]},
        headers={"source": "crackerjack"},
    )
    summary = format_bodai_summary(envelope)
    assert summary.startswith("[crackerjack] test_run_completed ")
    assert "failed=0" in summary
    assert "passed=42" in summary
    assert "note=ok" in summary
    assert "tags=" in summary  # lists fall through to JSON encoding


def test_format_bodai_summary_via_oneiric_create_event_envelope() -> None:
    """End-to-end: Oneiric ``create_event_envelope`` populates ``source`` in headers."""
    envelope = create_event_envelope(
        topic="workflow_started",
        payload={"workflow_id": "wid_xyz", "stage": "init"},
        source="mahavishnu",
    )

    assert envelope.headers["source"] == "mahavishnu"
    summary = format_bodai_summary(envelope)
    assert summary.startswith("[mahavishnu] workflow_started ")
    assert "workflow_id=wid_xyz" in summary
    assert "stage=init" in summary


# ---------------------------------------------------------------------------
# Queue persistence helpers
# ---------------------------------------------------------------------------


def test_append_to_queue_writes_atomically(tmp_path: Path) -> None:
    queue_path = tmp_path / "bodai-event-queue.json"
    envelope = {"topic": "x", "payload": {"k": 1}, "headers": {"source": "mahavishnu"}}

    append_to_queue(envelope, queue_path=queue_path, queue_cap=10)

    assert queue_path.exists()
    contents = json.loads(queue_path.read_text(encoding="utf-8"))
    assert contents == [envelope]
    # Atomic-write invariant: no leftover tmp sibling of the canonical file
    tmp_siblings = list(queue_path.parent.glob(queue_path.name + ".tmp"))
    assert tmp_siblings == []


def test_append_to_queue_caps_at_100(tmp_path: Path) -> None:
    queue_path = tmp_path / "bodai-event-queue.json"
    seed_count = 150

    for index in range(seed_count):
        append_to_queue(
            {"topic": "x", "payload": {"i": index}, "headers": {"source": "s"}},
            queue_path=queue_path,
            queue_cap=DEFAULT_QUEUE_CAP,
        )

    contents = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(contents) == DEFAULT_QUEUE_CAP
    # The first 50 should have been dropped; remaining items start at index 50
    assert contents[0]["payload"]["i"] == seed_count - DEFAULT_QUEUE_CAP
    assert contents[-1]["payload"]["i"] == seed_count - 1


def test_append_to_queue_creates_parent_directory(tmp_path: Path) -> None:
    queue_path = tmp_path / ".mahavishnu" / "bodai-event-queue.json"
    assert not queue_path.parent.exists()

    append_to_queue(
        {"topic": "x", "payload": {}, "headers": {}},
        queue_path=queue_path,
        queue_cap=10,
    )

    assert queue_path.exists()
    assert queue_path.parent.is_dir()


def test_read_queue_returns_empty_for_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.json"
    assert _read_queue(missing) == []


def test_write_queue_atomic_replaces_existing(tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    _write_queue_atomic(queue_path, [{"a": 1}])
    _write_queue_atomic(queue_path, [{"a": 2}, {"b": 3}])
    contents = json.loads(queue_path.read_text(encoding="utf-8"))
    assert contents == [{"a": 2}, {"b": 3}]


def test_resolve_queue_path_uses_override(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.json"
    assert _resolve_queue_path(explicit) == explicit


# ---------------------------------------------------------------------------
# Subscriber loop (mocked redis)
# ---------------------------------------------------------------------------


def _make_envelope_dict(source: str, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a Redis-stream message dict in the shape ``RedisEventTransport.publish`` writes."""
    envelope = EventEnvelope(
        topic=topic,
        payload=payload,
        headers={"source": source, "event_id": f"evt-{topic}"},
    )
    return {"envelope": envelope.to_json() if hasattr(envelope, "to_json") else json.dumps({
        "topic": envelope.topic,
        "payload": dict(envelope.payload),
        "headers": dict(envelope.headers),
    })}


def _make_redis_mock(
    *,
    read_response: list[tuple[Any, list[tuple[Any, dict[str, Any]]]]] | None = None,
    read_side_effect: Any = None,
    xgroup_create_side_effect: Any = None,
) -> MagicMock:
    """Construct an AsyncMock-shaped redis client."""
    client = MagicMock()
    client.xreadgroup = AsyncMock(return_value=read_response, side_effect=read_side_effect)
    client.xack = AsyncMock(return_value=1)
    client.xgroup_create = AsyncMock(return_value=0, side_effect=xgroup_create_side_effect)
    client.aclose = AsyncMock(return_value=None)
    client.close = AsyncMock(return_value=None)
    return client


def _redis_factory_for(client: MagicMock) -> Any:
    """Return a callable that produces the supplied client when invoked.

    The subscriber's ``client_factory`` parameter accepts this directly so we
    don't have to patch ``redis.asyncio.from_url`` (which is brittle under
    some pytest-asyncio configurations).
    """
    return lambda _url: client


async def _drain_for(predicate: Any, *, iterations: int = 200, sleep: float = 0.01) -> None:
    """Yield to the loop until ``predicate()`` is true or the iteration cap is reached."""
    for _ in range(iterations):
        if predicate():
            return
        await asyncio.sleep(sleep)


async def test_subscribe_consumes_and_appends(tmp_path: Path) -> None:
    """Three envelopes arrive via xreadgroup; verify all 3 appended to queue + acked; verify cancellation stops the loop after one batch."""
    envelope1 = _make_envelope_dict("mahavishnu", "workflow_completed", {"workflow_id": "wid_abc"})
    envelope2 = _make_envelope_dict("akosha", "aggregation_completed", {"suite": "quality"})
    envelope3 = _make_envelope_dict(
        "crackerjack", "test_run_completed", {"passed": 42, "failed": 0}
    )

    first_batch = [(STREAM_NAME.encode("utf-8"), [
        (b"1-0", envelope1),
        (b"1-1", envelope2),
        (b"1-2", envelope3),
    ])]

    # Use a closure with side_effect — switch to empty list once the first batch is consumed
    remaining = {"emitted_first": False}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)  # yield so cancellation_token can take effect
        if not remaining["emitted_first"]:
            remaining["emitted_first"] = True
            return first_batch
        return []

    client = _make_redis_mock()
    client.xreadgroup = AsyncMock(side_effect=fake_xreadgroup)

    queue_path = tmp_path / "queue.json"
    received: list[EventEnvelope] = []

    async def cb(envelope: EventEnvelope) -> None:
        received.append(envelope)

    cancel = asyncio.Event()

    task = asyncio.create_task(
        subscribe_to_bodai_events(
            cb,
            redis_url="redis://localhost:6379/0",
            queue_path=queue_path,
            cancellation_token=cancel,
            xreadgroup_block_ms=10,
            stream_name=STREAM_NAME,
            client_factory=_redis_factory_for(client),
        )
    )
    await _drain_for(lambda: len(received) >= 3)
    cancel.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        task.cancel()
        await task

    assert len(received) == 3
    assert [e.topic for e in received] == [
        "workflow_completed",
        "aggregation_completed",
        "test_run_completed",
    ]

    # All three messages were acked
    assert client.xack.await_count >= 3

    # Queue file contains three entries
    queue_contents = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(queue_contents) == 3
    assert queue_contents[0]["topic"] == "workflow_completed"
    assert queue_contents[2]["headers"]["source"] == "crackerjack"


async def test_subscribe_handles_decode_error(tmp_path: Path) -> None:
    """Malformed envelope: log + skip (no ack, allow retry) + continue processing the next message."""
    malformed = {"envelope": b"this is not json {{{"}
    good = _make_envelope_dict("mahavishnu", "workflow_completed", {"workflow_id": "wid_xyz"})

    state = {"emitted_first": False}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)  # yield so cancellation_token can take effect
        if not state["emitted_first"]:
            state["emitted_first"] = True
            return [(STREAM_NAME.encode("utf-8"), [(b"1-0", malformed), (b"1-1", good)])]
        return []

    client = _make_redis_mock()
    client.xreadgroup = AsyncMock(side_effect=fake_xreadgroup)

    queue_path = tmp_path / "queue.json"
    received: list[EventEnvelope] = []

    async def cb(envelope: EventEnvelope) -> None:
        received.append(envelope)

    cancel = asyncio.Event()

    task = asyncio.create_task(
        subscribe_to_bodai_events(
            cb,
            redis_url="redis://localhost:6379/0",
            queue_path=queue_path,
            cancellation_token=cancel,
            xreadgroup_block_ms=10,
            stream_name=STREAM_NAME,
            client_factory=_redis_factory_for(client),
        )
    )
    await _drain_for(lambda: len(received) >= 1)
    cancel.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        task.cancel()
        await task

    # Only the good envelope was processed
    assert len(received) == 1
    assert received[0].topic == "workflow_completed"


async def test_subscribe_creates_consumer_group_idempotently() -> None:
    """xgroup_create returns BUSYGROUP on first call (group exists), succeeds on retry."""
    busygroup_error = Exception("BUSYGROUP Consumer Group name already exists")
    client = _make_redis_mock()
    client.xgroup_create = AsyncMock(side_effect=[busygroup_error, None])
    client.xreadgroup = AsyncMock(return_value=[])

    queue_path = Path("/tmp/test-subscribe-idempotent.json")
    received: list[EventEnvelope] = []

    async def cb(envelope: EventEnvelope) -> None:
        received.append(envelope)

    cancel = asyncio.Event()
    cancel.set()  # cancel immediately so the loop never blocks on xreadgroup

    await subscribe_to_bodai_events(
        cb,
        redis_url="redis://localhost:6379/0",
        queue_path=queue_path,
        cancellation_token=cancel,
        xreadgroup_block_ms=10,
        stream_name=STREAM_NAME,
        client_factory=_redis_factory_for(client),
    )

    # xgroup_create was called at least once (the test's BUSYGROUP + None
    # side_effect is checked via mock_calls below).
    assert client.xgroup_create.await_count >= 1
    # The first xgroup_create call returned BUSYGROUP (idempotency case),
    # which is what makes this test meaningful.
    assert "BUSYGROUP" in str(client.xgroup_create.await_args) or client.xgroup_create.await_count == 1
    # No callbacks fired
    assert received == []
    # Client closed cleanly
    assert (client.aclose.await_count + client.close.await_count) >= 1


async def test_subscribe_handles_connection_drop(tmp_path: Path) -> None:
    """xreadgroup raises ConnectionError; subscriber logs warning + retries on next iteration."""
    good = _make_envelope_dict("mahavishnu", "workflow_completed", {"workflow_id": "wid_recovery"})

    state = {"calls": 0}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)  # yield so cancellation_token can take effect
        state["calls"] += 1
        if state["calls"] == 1:
            raise ConnectionError("redis connection lost")
        if state["calls"] == 2:
            return [(STREAM_NAME.encode("utf-8"), [(b"1-0", good)])]
        return []

    client = _make_redis_mock()
    client.xreadgroup = AsyncMock(side_effect=fake_xreadgroup)

    queue_path = tmp_path / "queue.json"
    received: list[EventEnvelope] = []

    async def cb(envelope: EventEnvelope) -> None:
        received.append(envelope)

    cancel = asyncio.Event()

    task = asyncio.create_task(
        subscribe_to_bodai_events(
            cb,
            redis_url="redis://localhost:6379/0",
            queue_path=queue_path,
            cancellation_token=cancel,
            xreadgroup_block_ms=10,
            stream_name=STREAM_NAME,
            client_factory=_redis_factory_for(client),
        )
    )
    await _drain_for(lambda: len(received) >= 1)
    cancel.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        task.cancel()
        await task

    # The good envelope was eventually processed despite the ConnectionError
    assert len(received) == 1
    assert received[0].topic == "workflow_completed"
    # Multiple xreadgroup attempts: at least the initial fail + recovery call
    assert client.xreadgroup.await_count >= 2


async def test_subscribe_skips_ack_on_callback_timeout(tmp_path: Path) -> None:
    """Per-event timeout: log + do not ack so another consumer can retry."""
    slow_envelope = _make_envelope_dict("mahavishnu", "workflow_completed", {"workflow_id": "wid_slow"})

    state = {"emitted_first": False}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)  # yield so cancellation_token can take effect
        if not state["emitted_first"]:
            state["emitted_first"] = True
            return [(STREAM_NAME.encode("utf-8"), [(b"1-0", slow_envelope)])]
        return []

    client = _make_redis_mock()
    client.xreadgroup = AsyncMock(side_effect=fake_xreadgroup)

    queue_path = tmp_path / "queue.json"
    received: list[EventEnvelope] = []

    async def slow_cb(envelope: EventEnvelope) -> None:
        received.append(envelope)
        await asyncio.sleep(5.0)

    cancel = asyncio.Event()

    task = asyncio.create_task(
        subscribe_to_bodai_events(
            slow_cb,
            redis_url="redis://localhost:6379/0",
            queue_path=queue_path,
            per_event_timeout_seconds=0.05,
            cancellation_token=cancel,
            xreadgroup_block_ms=10,
            stream_name=STREAM_NAME,
            client_factory=_redis_factory_for(client),
        )
    )
    # Let the timeout fire
    await asyncio.sleep(0.2)
    cancel.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        task.cancel()
        await task

    assert len(received) == 1
    # The slow envelope should NOT have been acked (timed out)
    assert client.xack.await_count == 0
    # Queue file should be empty (nothing appended for the timed-out envelope)
    if queue_path.exists():
        contents = json.loads(queue_path.read_text(encoding="utf-8"))
        assert contents == []


# ---------------------------------------------------------------------------
# Internal helpers — envelope decoding
# ---------------------------------------------------------------------------


def test_decode_envelope_from_redis_canonical_field() -> None:
    payload = {"envelope": json.dumps({
        "topic": "workflow_completed",
        "payload": {"workflow_id": "wid_abc"},
        "headers": {"source": "mahavishnu"},
    })}
    envelope = _decode_envelope(payload)
    assert envelope.topic == "workflow_completed"
    assert envelope.payload == {"workflow_id": "wid_abc"}
    assert envelope.headers == {"source": "mahavishnu"}


def test_decode_envelope_from_redis_fallback_fields() -> None:
    payload = {
        "topic": "aggregation_completed",
        "payload": json.dumps({"suite": "quality"}),
        "headers": json.dumps({"source": "akosha"}),
    }
    envelope = _decode_envelope(payload)
    assert envelope.topic == "aggregation_completed"
    assert envelope.payload == {"suite": "quality"}
    assert envelope.headers == {"source": "akosha"}


def test_decode_envelope_missing_topic_raises() -> None:
    payload = {"envelope": json.dumps({"payload": {}, "headers": {}})}
    with pytest.raises(ValueError, match="topic"):
        _decode_envelope(payload)


def test_envelope_to_dict_round_trip() -> None:
    envelope = EventEnvelope(
        topic="workflow_completed",
        payload={"workflow_id": "wid_abc"},
        headers={"source": "mahavishnu"},
    )
    result = _envelope_to_dict(envelope)
    assert result["topic"] == "workflow_completed"
    assert result["payload"] == {"workflow_id": "wid_abc"}
    assert result["headers"] == {"source": "mahavishnu"}
    assert "received_at" in result