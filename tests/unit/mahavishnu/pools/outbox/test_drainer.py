"""Tests for mahavishnu.pools.outbox.drainer (drain_once behavior)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from mahavishnu.pools.memory_aggregator import _CircuitBreaker
from mahavishnu.pools.outbox.drainer import DrainResult, MemoryOutboxDrainer
from mahavishnu.pools.outbox.writer import MemoryOutboxWriter

if TYPE_CHECKING:
    import pathlib


pytestmark = pytest.mark.unit


class _StubBreaker:
    """Stand-in for the aggregator's _CircuitBreaker.

    Implements the ``can_execute()`` protocol the drainer actually depends
    on (matches the real ``_CircuitBreaker.can_execute`` semantics for the
    closed / open states we exercise in these tests). The real-breaker
    behavior is verified by ``test_drainer_fires_sink_when_real_breaker_is_half_open``.
    """

    def __init__(self, can_execute: bool = True) -> None:
        self._can_execute = can_execute

    def can_execute(self) -> bool:
        return self._can_execute


@pytest.fixture
def writer(tmp_path: pathlib.Path) -> MemoryOutboxWriter:
    w = MemoryOutboxWriter(tmp_path / "outbox.duckdb")
    yield w
    w.close()


async def test_drainer_drains_pending_when_breaker_closed(writer: MemoryOutboxWriter) -> None:
    for i in range(50):
        await writer.enqueue(f"k{i}", {"i": i})

    seen: list[tuple[str, dict[str, object]]] = []

    async def sink(key: str, payload: dict[str, object]) -> None:
        seen.append((key, payload))

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(can_execute=True), sink)
    result = await drainer.drain_once()
    assert result == DrainResult(drained=50, deferred=0, failed=0)
    assert len(seen) == 50
    assert await writer.pending_count() == 0


async def test_drainer_skips_when_breaker_open(writer: MemoryOutboxWriter) -> None:
    for i in range(50):
        await writer.enqueue(f"k{i}", {"i": i})

    seen: list[tuple[str, dict[str, object]]] = []

    async def sink(key: str, payload: dict[str, object]) -> None:
        seen.append((key, payload))

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(can_execute=False), sink)
    result = await drainer.drain_once()
    assert result == DrainResult(drained=0, deferred=50, failed=0)
    assert seen == []
    assert await writer.pending_count() == 50


async def test_drainer_marks_failed_after_max_attempts(writer: MemoryOutboxWriter) -> None:
    await writer.enqueue("k1", {"i": 1})

    async def sink(key: str, payload: dict[str, object]) -> None:
        raise RuntimeError("simulated 5xx")

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(can_execute=True), sink, max_attempts=5)
    # Five cycles; row stays pending until attempts >= max, then flips to failed.
    for _ in range(5):
        await drainer.drain_once()
    # Row should be in `failed` status (not `pending`); pending_count filters status='pending'.
    assert await writer.pending_count() == 0


async def test_drainer_fires_sink_when_real_breaker_is_half_open(
    writer: MemoryOutboxWriter,
) -> None:
    """Wiring test against the real ``_CircuitBreaker``.

    The drainer must honor ``can_execute()`` (which encapsulates the
    half-open / recovery probe) rather than ``is_open()`` (a static
    snapshot). With the old API, an open breaker that has already passed
    its recovery timeout would block the drainer forever; with the new
    API, the breaker reports ``can_execute() is True`` and the drainer
    actually attempts the sink.
    """
    # Build a real breaker that opens after a single failure and has a
    # zero-second recovery window, then trip it.
    breaker = _CircuitBreaker("session-buddy", failure_threshold=1, recovery_timeout=0.0)
    breaker.record_failure()
    assert breaker.is_open  # the breaker is open right now
    # Let the recovery window elapse.
    time.sleep(0.01)
    assert breaker.can_execute() is True  # half-open probe: allow one attempt

    for i in range(3):
        await writer.enqueue(f"k{i}", {"i": i})

    seen: list[tuple[str, dict[str, object]]] = []

    async def sink(key: str, payload: dict[str, object]) -> None:
        seen.append((key, payload))

    drainer = MemoryOutboxDrainer(writer, breaker, sink)
    result = await drainer.drain_once()
    assert result.drained == 3
    assert seen == [(f"k{i}", {"i": i}) for i in range(3)]
    assert await writer.pending_count() == 0
