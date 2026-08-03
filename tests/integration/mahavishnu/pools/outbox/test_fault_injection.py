"""Fault-injection tests for the outbox drainer.

These exercise the drainer's behavior when the sink raises. Two cases:
1. Transient 5xx then recovery — sink fails the first few attempts, then
   succeeds; the drainer should eventually drain everything.
2. Partial-batch failure — sink fails one specific row; the drainer stops
   the batch (preserving order) and a subsequent drain eventually resolves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mahavishnu.pools.outbox.drainer import MemoryOutboxDrainer
from mahavishnu.pools.outbox.writer import MemoryOutboxWriter

if TYPE_CHECKING:
    import pathlib


pytestmark = pytest.mark.integration


class _StubBreaker:
    def __init__(self, can_execute: bool = True) -> None:
        self._can_execute = can_execute

    def can_execute(self) -> bool:
        return self._can_execute


@pytest.fixture
def writer(tmp_path: pathlib.Path) -> MemoryOutboxWriter:
    w = MemoryOutboxWriter(tmp_path / "outbox.duckdb")
    yield w
    w.close()


async def test_session_buddy_5xx_then_recovery(writer: MemoryOutboxWriter) -> None:
    for i in range(10):
        await writer.enqueue(f"k{i}", {"i": i})

    fail_count = {"n": 0}

    async def flaky_sink(key: str, payload: dict[str, object]) -> None:
        if fail_count["n"] < 3:
            fail_count["n"] += 1
            raise RuntimeError("simulated 5xx")

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(can_execute=True), flaky_sink)
    # First drain fails on row 0 (attempts=1); subsequent drains recover.
    for _ in range(10):
        await drainer.drain_once()
        if await writer.pending_count() == 0:
            break
    assert await writer.pending_count() == 0


async def test_partial_drain_failure_continues_batch(writer: MemoryOutboxWriter) -> None:
    """The drainer stops the batch on first sink exception to preserve ordering.
    A subsequent drain picks up where the previous one left off.
    """
    for i in range(10):
        await writer.enqueue(f"k{i}", {"i": i})

    fail_k5 = {"active": True}

    async def sink(key: str, payload: dict[str, object]) -> None:
        if fail_k5["active"] and key == "k5":
            raise RuntimeError("fail k5")

    drainer = MemoryOutboxDrainer(writer, _StubBreaker(can_execute=True), sink)
    # Drive enough drains that k5 hits max_attempts and ends up failed.
    for _ in range(20):
        await drainer.drain_once()
        if await writer.pending_count() == 0:
            break
    # k5 ends up failed; everything else drained.
    assert await writer.pending_count() == 0
