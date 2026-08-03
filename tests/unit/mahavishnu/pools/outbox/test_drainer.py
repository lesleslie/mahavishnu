"""Tests for mahavishnu.pools.outbox.drainer (drain_once behavior)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mahavishnu.pools.outbox.drainer import DrainResult, MemoryOutboxDrainer
from mahavishnu.pools.outbox.writer import MemoryOutboxWriter

if TYPE_CHECKING:
    import pathlib


pytestmark = pytest.mark.unit


class _StubBreaker:
    """Stand-in for the aggregator's _CircuitBreaker.

    The drainer only reads `is_open()`; success/failure are tracked
    by the aggregator's existing write path. This stub keeps tests
    independent of breaker internals.
    """

    def __init__(self, is_open: bool = False) -> None:
        self._is_open = is_open

    def is_open(self) -> bool:
        return self._is_open


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

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(is_open=False), sink)
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

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(is_open=True), sink)
    result = await drainer.drain_once()
    assert result == DrainResult(drained=0, deferred=50, failed=0)
    assert seen == []
    assert await writer.pending_count() == 50


async def test_drainer_marks_failed_after_max_attempts(writer: MemoryOutboxWriter) -> None:
    await writer.enqueue("k1", {"i": 1})

    async def sink(key: str, payload: dict[str, object]) -> None:
        raise RuntimeError("simulated 5xx")

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(is_open=False), sink, max_attempts=5)
    # Five cycles; row stays pending until attempts >= max, then flips to failed.
    for _ in range(5):
        await drainer.drain_once()
    # Row should be in `failed` status (not `pending`); pending_count filters status='pending'.
    assert await writer.pending_count() == 0
