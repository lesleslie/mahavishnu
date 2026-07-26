from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from mahavishnu.workers.contract.publisher import CanonicalEnvelopePublisher

if TYPE_CHECKING:
    from mahavishnu.core.events.envelope import EventEnvelope


def test_publisher_emits_canonical_envelope() -> None:
    sink: list[EventEnvelope] = []
    publisher = CanonicalEnvelopePublisher(
        source="mahavishnu.workers.contract",
        sink=sink.append,
        now=lambda: dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.UTC),
    )
    publisher.emit("worker.spawned", {"worker_id": "w-1"})

    assert len(sink) == 1
    env = sink[0]
    assert env.event_type == "worker.spawned"
    assert env.source == "mahavishnu.workers.contract"
    assert env.payload == {"worker_id": "w-1"}
    assert env.timestamp == dt.datetime(
        2026, 7, 26, 10, 0, 0, tzinfo=dt.UTC
    )
    assert env.version == "1.0.0"
    assert env.event_id is not None
