"""Unit tests for the durable-worker contract's canonical publisher.

``CanonicalEnvelopePublisher`` is the single implementation of
:class:`mahavishnu.workers.contract.manager.EventPublisher`. The contract
calls ``emit(payload, topic)`` — payload first — so the publisher's
parameter order must match the protocol exactly.

A mismatched order does not fail loudly at the call site: the publisher
binds ``topic`` to the payload dict and ``payload`` to the topic string,
and the envelope is then built with the two arguments swapped (which
Pydantic rejects, because ``event_type`` is a ``str``).
"""

from __future__ import annotations

import datetime as dt
import inspect
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from mahavishnu.workers.contract.manager import DurableWorkerManager, EventPublisher
from mahavishnu.workers.contract.publisher import CanonicalEnvelopePublisher
from mahavishnu.workers.contract.record import TmuxTarget
from mahavishnu.workers.contract.store import WorkerRecordStore

if TYPE_CHECKING:
    import pathlib

    from mahavishnu.core.events.envelope import EventEnvelope

pytestmark = pytest.mark.unit


def test_publisher_emit_signature_matches_contract_protocol() -> None:
    """The publisher must accept the protocol's parameter order.

    ``DurableWorkerManager._publish`` calls ``publisher.emit(payload,
    topic)``. A publisher declared as ``emit(topic, payload)`` binds the
    two arguments the wrong way round.
    """
    contract_params = list(inspect.signature(EventPublisher.emit).parameters)
    publisher_params = list(
        inspect.signature(CanonicalEnvelopePublisher.emit).parameters
    )

    assert publisher_params == contract_params


def test_publisher_emits_canonical_envelope() -> None:
    sink: list[EventEnvelope] = []
    publisher = CanonicalEnvelopePublisher(
        source="mahavishnu.workers.contract",
        sink=sink.append,
        now=lambda: dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.UTC),
    )
    publisher.emit({"worker_id": "w-1"}, "worker.spawned")

    assert len(sink) == 1
    env = sink[0]
    assert env.event_type == "worker.spawned"
    assert env.source == "mahavishnu.workers.contract"
    assert env.payload == {"worker_id": "w-1"}
    assert env.timestamp == dt.datetime(2026, 7, 26, 10, 0, 0, tzinfo=dt.UTC)
    assert env.version == "1.0.0"
    assert env.event_id is not None


def test_publisher_drops_non_worker_topics() -> None:
    """Only canonical ``worker.*`` topics reach the sink.

    The durable-worker event stream carries worker topics only; any other
    topic is dropped rather than published.
    """
    sink: list[EventEnvelope] = []
    publisher = CanonicalEnvelopePublisher(
        source="mahavishnu.terminal", sink=sink.append
    )

    publisher.emit({"worker_id": "w-1"}, "not.a.worker.topic")

    assert sink == []


def test_publisher_satisfies_durable_manager_contract(tmp_path: pathlib.Path) -> None:
    """A ``CanonicalEnvelopePublisher`` can drive a real ``DurableWorkerManager``.

    The manager publishes through the ``EventPublisher`` protocol; the
    envelopes that reach the sink must carry the topic as ``event_type``
    and the worker's fields as ``payload``.
    """
    envelopes: list[EventEnvelope] = []
    publisher = CanonicalEnvelopePublisher(
        source="mahavishnu.terminal",
        sink=envelopes.append,
    )
    manager = DurableWorkerManager(
        store=WorkerRecordStore(tmp_path),
        publisher=publisher,
        socket_dir=tmp_path / "tmux",
    )
    fake_info = TmuxTarget(
        socket=str(tmp_path / "tmux" / "x.sock"),
        session="mvs",
        window="@0",
        pane="%3",
        attach_command="tmux -S x.sock attach -t mvs",
    )

    with patch(
        "mahavishnu.workers.contract.manager.create_session",
        return_value=fake_info,
    ):
        spawned = manager.spawn(
            worker_type="terminal-claude",
            backend="claude_tui",
            command=["claude"],
        )

    assert envelopes, "spawn must publish at least one envelope"
    by_type = {env.event_type: env for env in envelopes}
    assert "worker.spawned" in by_type
    envelope = by_type["worker.spawned"]
    assert envelope.source == "mahavishnu.terminal"
    assert envelope.payload["worker_id"] == spawned.worker_id
    assert envelope.payload["worker_type"] == "terminal-claude"
