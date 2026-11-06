"""Tests for the durable-worker envelope sink in ``mahavishnu.terminal.manager``.

The sink used to log ``getattr(envelope, "topic", "?")``. ``EventEnvelope``
declares no ``topic`` field, so that expression could only ever render
``topic=?`` — the debug line could never report the worker topic.

``CanonicalEnvelopePublisher.emit`` maps the topic onto the envelope's
``event_type`` field, so ``event_type`` is the field that actually carries
the topic. These tests pin that the sink reports ``event_type`` and that
``topic=?`` never appears again.

``mahavishnu.terminal.manager`` uses the stdlib logger
(``from logging import getLogger``), so pytest's ``caplog`` captures the
record here. That is *not* true of the structlog-based modules elsewhere
in this repo, where ``caplog`` is void.
"""

from __future__ import annotations

import logging
import pathlib

import pytest

from mahavishnu.core.events.envelope import EventEnvelope
from mahavishnu.core.events.worker_topics import WORKER_SPAWNED
from mahavishnu.terminal.manager import _enqueue_to_eventbridge
from mahavishnu.workers.contract.publisher import CanonicalEnvelopePublisher

pytestmark = pytest.mark.unit

_SINK_LOGGER = "mahavishnu.terminal.manager"


def _envelope() -> EventEnvelope:
    """Build a canonical envelope carrying a worker topic."""
    return EventEnvelope(
        event_type=WORKER_SPAWNED,
        version="1.0.0",
        source="mahavishnu.terminal",
        payload={"worker_id": "w-1"},
    )


def _sink_output(caplog: pytest.LogCaptureFixture) -> str:
    """Return every message the sink logged during the capture window."""
    return "\n".join(record.getMessage() for record in caplog.records)


def test_sink_debug_line_reports_event_type_instead_of_topic(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The debug line must carry ``event_type`` and never ``topic=?``.

    Regression test for F18: the old sink read a non-existent ``topic``
    attribute, so the line could only ever render the ``?`` placeholder.
    """
    envelope = _envelope()

    with caplog.at_level(logging.DEBUG, logger=_SINK_LOGGER):
        _enqueue_to_eventbridge(envelope)

    output = _sink_output(caplog)

    assert output, "the sink must still log the envelope it drops"
    assert "event_type=" in output
    assert WORKER_SPAWNED in output
    assert "topic=?" not in output
    assert "topic=" not in output


def test_published_worker_topic_survives_the_round_trip(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The topic a worker publishes must reach the sink's debug line.

    ``CanonicalEnvelopePublisher.emit(payload, topic)`` builds the
    envelope with ``event_type=topic`` and hands it to the sink. The
    topic is therefore recoverable from ``event_type`` — which is what
    the sink logs.
    """
    publisher = CanonicalEnvelopePublisher(
        source="mahavishnu.terminal",
        sink=_enqueue_to_eventbridge,
    )

    with caplog.at_level(logging.DEBUG, logger=_SINK_LOGGER):
        publisher.emit({"worker_id": "w-1"}, WORKER_SPAWNED)

    output = _sink_output(caplog)

    assert "event_type=" in output
    assert WORKER_SPAWNED in output
    assert "topic=?" not in output


def test_sink_publishes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tripwire: the sink stays a no-op.

    Publishing to the EventBridge is separate, still-unowned work. If a
    future change wires this sink to the real publisher, this test
    fails and forces the module comment and the docstring to be
    updated in the same change.
    """
    import mahavishnu.core.events.publisher as publisher_module

    async def _forbidden(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("the durable envelope sink must not publish yet")

    monkeypatch.setattr(publisher_module, "safe_publish", _forbidden)

    assert _enqueue_to_eventbridge(_envelope()) is None


def test_all_three_wiring_sites_use_the_same_sink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """Every wiring site must keep handing the same sink to the publisher.

    Three sites construct the durable-worker publisher:

    - ``mahavishnu/mcp/bootstrap.py::_build_tmux_adapter``
    - ``mahavishnu/mcp/bootstrap.py::_try_build_durable_worker_manager``
    - ``mahavishnu/terminal/adapters/__init__.py::_build_tmux_adapter``

    All three pass ``_enqueue_to_eventbridge`` as ``sink``. A site that
    drifted to a different callable would stop dropping envelopes in the
    same place, so the identity of the sink is pinned here.
    """
    from mahavishnu.mcp import bootstrap
    from mahavishnu.terminal import adapters as terminal_adapters

    captured: list[object] = []

    class _FakePublisher:
        def __init__(self, *, source: str, sink: object) -> None:
            captured.append(sink)

    class _FakeStore:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    class _FakeManager:
        def __init__(self, **_kwargs: object) -> None:
            pass

    class _FakeAdapter:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(pathlib.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        "mahavishnu.workers.contract.publisher.CanonicalEnvelopePublisher",
        _FakePublisher,
    )
    monkeypatch.setattr(
        "mahavishnu.workers.contract.store.WorkerRecordStore",
        _FakeStore,
    )
    monkeypatch.setattr(
        "mahavishnu.workers.contract.manager.DurableWorkerManager",
        _FakeManager,
    )
    monkeypatch.setattr(
        "mahavishnu.terminal.adapters.tmux.TmuxTerminalAdapter",
        _FakeAdapter,
    )
    monkeypatch.setattr(bootstrap.shutil, "which", lambda binary: "/usr/bin/tmux")

    bootstrap._build_tmux_adapter()
    bootstrap._try_build_durable_worker_manager()
    terminal_adapters._build_tmux_adapter()

    assert len(captured) == 3
    assert all(sink is _enqueue_to_eventbridge for sink in captured)
