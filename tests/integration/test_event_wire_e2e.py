"""End-to-end integration proof for the canonical Oneiric event wire.

Task 8 of the Oneiric EventEnvelope wire-standardization plan. The test
exercises the full observable chain:

    Pydantic EventEnvelope
        -> RedisEventTransport.publish() (canonical Redis record)
        -> decode_oneiric_envelope round-trip
        -> Bodai subscriber xack after queue persistence
        -> `mahavishnu metrics bodai` CLI render

The test-local ``_RecordingQueueAdapter`` and ``_SingleBatchRedisClient``
fixtures stand in for the production Redis client (Phase 1 deliberately
avoids fakeredis). This proves the application boundaries, not the
server-side Redis pending-entry behavior.

Marker: ``integration`` per ``CLAUDE.md`` Test conventions.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from mahavishnu.core.events.bodai_subscriber import subscribe_to_bodai_events
from mahavishnu.core.events.canonical import decode_oneiric_envelope
from mahavishnu.core.events.contract import create_event_envelope
from mahavishnu.core.events.transport import RedisEventTransport
from mahavishnu.metrics_cli import metrics_app

pytestmark = pytest.mark.integration


@dataclass
class _RecordingQueueAdapter:
    """Capture-only stand-in for the queue adapter used by RedisEventTransport."""

    enqueued: list[dict[str, Any]] = field(default_factory=list)
    published: list[tuple[str, str]] = field(default_factory=list)

    async def enqueue(self, record: dict[str, Any]) -> str:
        self.enqueued.append(record)
        return "1-0"

    async def pubsub_publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


class _SingleBatchRedisClient:
    """One-shot Redis Streams stub that returns a single envelope on first xreadgroup."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record
        self.xgroup_create = AsyncMock()
        self.xack = AsyncMock()
        self.aclose = AsyncMock()
        self._read = False

    async def xreadgroup(self, **_kwargs: Any) -> list[Any]:
        if self._read:
            return []
        self._read = True
        return [(b"bodai:events", [(b"1-0", self.record)])]


async def test_pydantic_event_round_trips_through_wire_and_metrics_cli(
    tmp_path: Path,
) -> None:
    adapter = _RecordingQueueAdapter()
    internal = create_event_envelope(
        "workflow.completed",
        "mahavishnu",
        payload={"workflow_id": "wf-e2e", "status": "success"},
        metadata={"adapter": "prefect"},
    )

    await RedisEventTransport(adapter).publish(internal)
    record = adapter.enqueued[0]
    assert set(record) == {"wire_format", "envelope"}
    assert record["wire_format"] == "oneiric-v1"

    canonical = decode_oneiric_envelope(record["envelope"])
    assert canonical.topic == internal.event_type
    assert canonical.headers["event_id"] == str(internal.event_id)
    assert canonical.headers["source"] == "mahavishnu"
    assert canonical.headers["metadata"] == internal.metadata

    cancel = asyncio.Event()
    client = _SingleBatchRedisClient(
        {
            b"wire_format": b"oneiric-v1",
            b"envelope": record["envelope"].encode("utf-8"),
        }
    )
    queue_path = tmp_path / "queue.json"
    seen: list[Any] = []

    async def callback(envelope) -> None:
        seen.append(envelope)
        cancel.set()

    await subscribe_to_bodai_events(
        callback,
        queue_path=queue_path,
        cancellation_token=cancel,
        client_factory=lambda _url: client,
        xreadgroup_block_ms=1,
    )

    client.xack.assert_awaited_once_with(
        "bodai:events",
        "mahavishnu-claude-observers",
        "1-0",
    )
    result = CliRunner().invoke(
        metrics_app,
        [
            "bodai",
            "--queue-path",
            str(queue_path),
            "--state-path",
            str(tmp_path / "state.json"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "mahavishnu" in result.stdout
    assert "wf-e2e" in result.stdout