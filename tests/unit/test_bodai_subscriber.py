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
import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from oneiric.runtime.events import EventEnvelope, create_event_envelope
import pytest

from mahavishnu.core.events.bodai_subscriber import (
    DEFAULT_QUEUE_CAP,
    STREAM_NAME,
    _accept_legacy_wire,
    _decode_envelope,
    _envelope_to_dict,
    _read_queue,
    _resolve_queue_path,
    _write_queue_atomic,
    append_to_queue,
    format_bodai_summary,
    subscribe_to_bodai_events,
)
from mahavishnu.core.events.canonical import create_oneiric_envelope
from mahavishnu.core.events.contract import (
    InMemoryEventTransport,  # noqa: F401  (kept for downstream test references)
)
from mahavishnu.core.events.envelope import EventEnvelope as MahavishnuEventEnvelope
from mahavishnu.core.errors import EventEnvelopeConversionError

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
# Step 1: legacy environment parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_legacy_wire_environment_enables_reads(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE", value)
    assert _accept_legacy_wire() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_legacy_wire_environment_disables_reads(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE", value)
    assert _accept_legacy_wire() is False


def test_legacy_wire_environment_defaults_to_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE", raising=False)
    assert _accept_legacy_wire() is True


# ---------------------------------------------------------------------------
# Step 3: canonical and malformed decode
# ---------------------------------------------------------------------------


def _canonical_envelope_json(topic: str, payload: dict[str, Any], source: str) -> str:
    """Build a valid canonical Oneiric envelope JSON for tests."""
    envelope = create_event_envelope(topic=topic, payload=payload, source=source)
    return json.dumps(
        {
            "topic": envelope.topic,
            "payload": dict(envelope.payload),
            "headers": dict(envelope.headers),
        },
        sort_keys=True,
    )


def _legacy_pydantic_json(topic: str, payload: dict[str, Any], source: str) -> str:
    """Build a Pydantic ``EventEnvelope`` JSON (legacy wire format)."""
    pydantic_env = MahavishnuEventEnvelope(
        event_type=topic,
        source=source,
        payload=payload,
    )
    return pydantic_env.to_json()


def test_decode_envelope_canonical_json() -> None:
    """Canonical ``envelope=<JSON>`` field: decoded via canonical decoder."""
    raw = _canonical_envelope_json(
        "workflow_completed", {"workflow_id": "wid_abc"}, "mahavishnu",
    )
    envelope = _decode_envelope({"envelope": raw})
    assert isinstance(envelope, EventEnvelope)
    assert envelope.topic == "workflow_completed"
    assert envelope.payload == {"workflow_id": "wid_abc"}
    assert envelope.headers["source"] == "mahavishnu"


def test_decode_envelope_canonical_precedence_over_direct_triplet() -> None:
    """When both ``envelope`` and direct triplet are present, canonical wins."""
    canonical_raw = _canonical_envelope_json(
        "canonical_topic", {"from": "canonical"}, "mahavishnu",
    )
    direct_payload = {"from": "direct"}
    direct_headers = {"source": "akosha"}
    envelope = _decode_envelope(
        {
            "envelope": canonical_raw,
            "topic": "direct_topic",
            "payload": json.dumps(direct_payload),
            "headers": json.dumps(direct_headers),
        },
    )
    assert envelope.topic == "canonical_topic"
    assert envelope.payload == {"from": "canonical"}
    assert envelope.headers["source"] == "mahavishnu"


def test_decode_envelope_direct_triplet() -> None:
    """Direct ``topic/payload/headers`` triplet builds a canonical envelope."""
    envelope = _decode_envelope(
        {
            "topic": "aggregation_completed",
            "payload": json.dumps({"suite": "quality"}),
            "headers": json.dumps({"source": "akosha"}),
        },
    )
    assert envelope.topic == "aggregation_completed"
    assert envelope.payload == {"suite": "quality"}
    assert envelope.headers["source"] == "akosha"


def test_decode_envelope_direct_triplet_bytes_payload_and_headers() -> None:
    """Bytes payload and headers are decoded as UTF-8 before JSON parse."""
    envelope = _decode_envelope(
        {
            "topic": "test_run_completed",
            "payload": b'{"passed": 7}',
            "headers": b'{"source": "crackerjack"}',
        },
    )
    assert envelope.topic == "test_run_completed"
    assert envelope.payload == {"passed": 7}
    assert envelope.headers["source"] == "crackerjack"


def test_decode_envelope_legacy_allowed_falls_back_to_pydantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy wire path: canonical fails, legacy Pydantic envelope decoded."""
    monkeypatch.setenv("MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE", "true")
    legacy_raw = _legacy_pydantic_json(
        "legacy_topic", {"k": "v"}, "mahavishnu",
    )
    envelope = _decode_envelope({"envelope": legacy_raw})
    assert isinstance(envelope, MahavishnuEventEnvelope)
    assert envelope.event_type == "legacy_topic"
    assert envelope.source == "mahavishnu"


def test_decode_envelope_legacy_denied_skips_malformed_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy disabled: malformed envelope is rejected (raises)."""
    monkeypatch.setenv("MAHAVISHNU_BODAI_ACCEPT_LEGACY_WIRE", "false")
    legacy_raw = _legacy_pydantic_json("t", {}, "s")
    with pytest.raises(EventEnvelopeConversionError):
        _decode_envelope({"envelope": legacy_raw})


def test_decode_envelope_non_utf8_json_payload() -> None:
    """Non-UTF-8 bytes under ``envelope`` field raises canonical decode error."""
    bad = b"\xff\xfe\xfdnot-utf8"
    with pytest.raises(EventEnvelopeConversionError):
        _decode_envelope({"envelope": bad})


def test_decode_envelope_non_object_json() -> None:
    """JSON array is not an envelope object → canonical decoder rejects."""
    with pytest.raises(EventEnvelopeConversionError):
        _decode_envelope({"envelope": json.dumps([1, 2, 3])})


def test_decode_envelope_missing_topic_in_direct_triplet() -> None:
    """Direct triplet missing topic → canonical decoder rejects."""
    with pytest.raises(EventEnvelopeConversionError):
        _decode_envelope(
            {
                "topic": "",
                "payload": "{}",
                "headers": json.dumps({"source": "akosha"}),
            },
        )


def test_decode_envelope_no_envelope_no_topic_raises() -> None:
    """Empty payload with no envelope or topic fields → canonical rejects."""
    with pytest.raises(EventEnvelopeConversionError):
        _decode_envelope({})


# ---------------------------------------------------------------------------
# Subscriber loop helpers (mocked redis)
# ---------------------------------------------------------------------------


def _make_envelope_dict(source: str, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a Redis-stream message dict with a canonical envelope JSON."""
    return {"envelope": _canonical_envelope_json(topic, payload, source)}


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
    """Return a callable that produces the supplied client when invoked."""
    return lambda _url: client


async def _drain_for(predicate: Any, *, iterations: int = 200, sleep: float = 0.01) -> None:
    """Yield to the loop until ``predicate()`` is true or the iteration cap is reached."""
    for _ in range(iterations):
        if predicate():
            return
        await asyncio.sleep(sleep)


async def _run_until(predicate: Any, *, cancel: asyncio.Event, task: asyncio.Task[Any]) -> None:
    """Drain until ``predicate()`` is true, then cancel and await task."""
    await _drain_for(predicate)
    cancel.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        task.cancel()
        await task


# ---------------------------------------------------------------------------
# Step 2: subscriber acknowledgement matrix
# ---------------------------------------------------------------------------


async def test_subscriber_decode_failure_does_not_append_or_ack(
    tmp_path: Path,
) -> None:
    """Malformed envelope: log + skip (no append, no ack) + continue."""
    malformed = {"envelope": b"this is not json {{{"}
    good = _make_envelope_dict(
        "mahavishnu", "workflow_completed", {"workflow_id": "wid_xyz"},
    )

    state = {"emitted_first": False}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)
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
        ),
    )
    await _run_until(lambda: len(received) >= 1, cancel=cancel, task=task)

    # Only the good envelope was processed
    assert len(received) == 1
    assert received[0].topic == "workflow_completed"

    # Exactly one xack (for the good envelope only)
    assert client.xack.await_count == 1
    # Queue file contains only the good envelope
    contents = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(contents) == 1
    assert contents[0]["topic"] == "workflow_completed"


async def test_subscriber_callback_timeout_does_not_append_or_ack(
    tmp_path: Path,
) -> None:
    """Per-event timeout: do not append, do not ack (allow retry)."""
    slow_envelope = _make_envelope_dict(
        "mahavishnu", "workflow_completed", {"workflow_id": "wid_slow"},
    )

    state = {"emitted_first": False}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)
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
        ),
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
    # Timed-out envelope is NOT acked
    assert client.xack.await_count == 0
    # Queue file is empty for the timed-out envelope
    if queue_path.exists():
        contents = json.loads(queue_path.read_text(encoding="utf-8"))
        assert contents == []


async def test_subscriber_callback_cancelled_error_propagates(
    tmp_path: Path,
) -> None:
    """``asyncio.CancelledError`` inside the callback propagates and stops the loop."""
    cancel_event = {"fired": False}
    good = _make_envelope_dict("mahavishnu", "workflow_completed", {"workflow_id": "wid"})

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)
        if not cancel_event["fired"]:
            cancel_event["fired"] = True
            return [(STREAM_NAME.encode("utf-8"), [(b"1-0", good)])]
        return []

    client = _make_redis_mock()
    client.xreadgroup = AsyncMock(side_effect=fake_xreadgroup)

    queue_path = tmp_path / "queue.json"

    async def cancelling_cb(envelope: EventEnvelope) -> None:
        raise asyncio.CancelledError()

    cancel = asyncio.Event()

    task = asyncio.create_task(
        subscribe_to_bodai_events(
            cancelling_cb,
            redis_url="redis://localhost:6379/0",
            queue_path=queue_path,
            cancellation_token=cancel,
            xreadgroup_block_ms=10,
            stream_name=STREAM_NAME,
            client_factory=_redis_factory_for(client),
        ),
    )
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)

    # Loop exited via cancellation, client closed cleanly
    assert (client.aclose.await_count + client.close.await_count) >= 1


async def test_subscriber_callback_exception_appends_and_acks(
    tmp_path: Path,
) -> None:
    """Callback raises Exception: log + proceed to append + ack."""
    envelope = _make_envelope_dict(
        "mahavishnu", "workflow_completed", {"workflow_id": "wid_err"},
    )

    state = {"emitted_first": False}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)
        if not state["emitted_first"]:
            state["emitted_first"] = True
            return [(STREAM_NAME.encode("utf-8"), [(b"1-0", envelope)])]
        return []

    client = _make_redis_mock()
    client.xreadgroup = AsyncMock(side_effect=fake_xreadgroup)

    queue_path = tmp_path / "queue.json"

    async def bad_cb(_envelope: EventEnvelope) -> None:
        raise RuntimeError("intentional callback failure")

    cancel = asyncio.Event()

    task = asyncio.create_task(
        subscribe_to_bodai_events(
            bad_cb,
            redis_url="redis://localhost:6379/0",
            queue_path=queue_path,
            cancellation_token=cancel,
            xreadgroup_block_ms=10,
            stream_name=STREAM_NAME,
            client_factory=_redis_factory_for(client),
        ),
    )
    await _drain_for(lambda: client.xack.await_count >= 1)
    cancel.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        task.cancel()
        await task

    # Even though callback raised, the envelope was appended + acked
    assert client.xack.await_count == 1
    contents = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(contents) == 1
    assert contents[0]["topic"] == "workflow_completed"


async def test_subscriber_queue_append_failure_still_acks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``append_to_queue`` raises, the message is still acked."""
    envelope = _make_envelope_dict(
        "mahavishnu", "workflow_completed", {"workflow_id": "wid_qfail"},
    )

    state = {"emitted_first": False}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)
        if not state["emitted_first"]:
            state["emitted_first"] = True
            return [(STREAM_NAME.encode("utf-8"), [(b"1-0", envelope)])]
        return []

    client = _make_redis_mock()
    client.xreadgroup = AsyncMock(side_effect=fake_xreadgroup)

    queue_path = tmp_path / "queue.json"

    async def cb(envelope: EventEnvelope) -> None:
        return None

    cancel = asyncio.Event()

    def _explode(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("intentional queue append failure")

    monkeypatch.setattr(
        "mahavishnu.core.events.bodai_subscriber.append_to_queue", _explode,
    )

    task = asyncio.create_task(
        subscribe_to_bodai_events(
            cb,
            redis_url="redis://localhost:6379/0",
            queue_path=queue_path,
            cancellation_token=cancel,
            xreadgroup_block_ms=10,
            stream_name=STREAM_NAME,
            client_factory=_redis_factory_for(client),
        ),
    )
    await _drain_for(lambda: client.xack.await_count >= 1)
    cancel.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        task.cancel()
        await task

    # Message was acked despite append failure
    assert client.xack.await_count == 1


async def test_subscriber_redis_read_failure_backs_off_and_retries(
    tmp_path: Path,
) -> None:
    """xreadgroup raises → loop backs off, retries, processes the next batch."""
    good = _make_envelope_dict(
        "mahavishnu", "workflow_completed", {"workflow_id": "wid_recovery"},
    )

    state = {"calls": 0}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)
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
        ),
    )
    await _run_until(lambda: len(received) >= 1, cancel=cancel, task=task)

    assert len(received) == 1
    assert received[0].topic == "workflow_completed"
    assert client.xreadgroup.await_count >= 2


async def test_subscriber_cancellation_token_stops_cleanly(
    tmp_path: Path,
) -> None:
    """Cancellation token set before any messages → loop exits + client closed."""
    client = _make_redis_mock()
    client.xreadgroup = AsyncMock(return_value=[])

    queue_path = tmp_path / "queue.json"
    received: list[EventEnvelope] = []

    async def cb(envelope: EventEnvelope) -> None:
        received.append(envelope)

    cancel = asyncio.Event()
    cancel.set()  # pre-set; loop must exit on first iteration check

    await subscribe_to_bodai_events(
        cb,
        redis_url="redis://localhost:6379/0",
        queue_path=queue_path,
        cancellation_token=cancel,
        xreadgroup_block_ms=10,
        stream_name=STREAM_NAME,
        client_factory=_redis_factory_for(client),
    )

    assert received == []
    # Client closed cleanly via the finally branch
    assert (client.aclose.await_count + client.close.await_count) >= 1


async def test_subscriber_all_exit_paths_close_client(
    tmp_path: Path,
) -> None:
    """Every exit path (normal, cancel, exception) closes the redis client."""
    envelope = _make_envelope_dict(
        "mahavishnu", "workflow_completed", {"workflow_id": "wid"},
    )

    state = {"emitted_first": False}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)
        if not state["emitted_first"]:
            state["emitted_first"] = True
            return [(STREAM_NAME.encode("utf-8"), [(b"1-0", envelope)])]
        return []

    client = _make_redis_mock()
    client.xreadgroup = AsyncMock(side_effect=fake_xreadgroup)

    queue_path = tmp_path / "queue.json"

    async def cb(envelope: EventEnvelope) -> None:
        return None

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
        ),
    )
    await _drain_for(lambda: client.xack.await_count >= 1)
    cancel.set()
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except TimeoutError:
        task.cancel()
        await task

    # Client was closed in the finally block
    assert (client.aclose.await_count + client.close.await_count) >= 1


async def test_subscribe_creates_consumer_group_idempotently() -> None:
    """``xgroup_create`` BUSYGROUP branch is hit; only one await occurs."""
    busygroup_error = Exception("BUSYGROUP Consumer Group name already exists")
    client = _make_redis_mock()
    client.xgroup_create = AsyncMock(side_effect=[busygroup_error, None])
    client.xreadgroup = AsyncMock(return_value=[])

    queue_path = Path("/tmp/test-subscribe-idempotent.json")
    received: list[EventEnvelope] = []

    async def cb(envelope: EventEnvelope) -> None:
        received.append(envelope)

    cancel = asyncio.Event()
    cancel.set()

    with patch("mahavishnu.core.events.bodai_subscriber._logger.debug") as debug_mock:
        await subscribe_to_bodai_events(
            cb,
            redis_url="redis://localhost:6379/0",
            queue_path=queue_path,
            cancellation_token=cancel,
            xreadgroup_block_ms=10,
            stream_name=STREAM_NAME,
            client_factory=_redis_factory_for(client),
        )

    # Exactly one xgroup_create attempt; the BUSYGROUP debug branch was logged
    assert client.xgroup_create.await_count == 1
    debug_calls = [
        call.args[0] for call in debug_mock.call_args_list if call.args
    ]
    assert any("consumer group already exists" in str(arg) for arg in debug_calls)
    # No callbacks fired
    assert received == []
    # Client closed cleanly
    assert (client.aclose.await_count + client.close.await_count) >= 1


async def test_subscribe_consumes_and_appends(tmp_path: Path) -> None:
    """Three envelopes arrive via xreadgroup; verify all 3 appended + acked."""
    envelope1 = _make_envelope_dict(
        "mahavishnu", "workflow_completed", {"workflow_id": "wid_abc"},
    )
    envelope2 = _make_envelope_dict(
        "akosha", "aggregation_completed", {"suite": "quality"},
    )
    envelope3 = _make_envelope_dict(
        "crackerjack", "test_run_completed", {"passed": 42, "failed": 0},
    )

    first_batch = [(STREAM_NAME.encode("utf-8"), [
        (b"1-0", envelope1),
        (b"1-1", envelope2),
        (b"1-2", envelope3),
    ])]

    remaining = {"emitted_first": False}

    async def fake_xreadgroup(**_kwargs: Any) -> list[Any]:
        await asyncio.sleep(0.01)
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
        ),
    )
    await _run_until(lambda: len(received) >= 3, cancel=cancel, task=task)

    assert len(received) == 3
    assert [e.topic for e in received] == [
        "workflow_completed",
        "aggregation_completed",
        "test_run_completed",
    ]

    # All three messages were acked exactly once
    assert client.xack.await_count == 3

    # Queue file contains three entries
    queue_contents = json.loads(queue_path.read_text(encoding="utf-8"))
    assert len(queue_contents) == 3
    assert queue_contents[0]["topic"] == "workflow_completed"
    assert queue_contents[2]["headers"]["source"] == "crackerjack"


# ---------------------------------------------------------------------------
# Internal helpers — envelope conversion
# ---------------------------------------------------------------------------


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


def test_create_oneiric_envelope_helper_in_canonical_path() -> None:
    """Sanity check: ``create_oneiric_envelope`` produces required headers."""
    envelope = create_oneiric_envelope(
        topic="sanity_check",
        payload={"k": "v"},
        source="mahavishnu",
    )
    for key in ("event_id", "source", "version", "timestamp"):
        assert key in envelope.headers
    assert envelope.headers["source"] == "mahavishnu"
    assert envelope.topic == "sanity_check"