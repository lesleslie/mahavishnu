"""Tests for mahavishnu.pools.outbox (model + writer)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from mahavishnu.pools.outbox.table import MemoryOutboxRow, OutboxStatus
from mahavishnu.pools.outbox.writer import MemoryOutboxWriter

if TYPE_CHECKING:
    from collections.abc import Iterator
    import pathlib

pytestmark = pytest.mark.unit


def test_memory_outbox_row_default_status_is_pending() -> None:
    now = dt.datetime(2026, 7, 29, 12, 0, 0, tzinfo=dt.UTC)
    row = MemoryOutboxRow(
        id=1,
        key="reflection:abc",
        payload={"text": "hello"},
        enqueued_at=now,
    )
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.last_error is None


def test_memory_outbox_row_status_rejects_unknown() -> None:
    now = dt.datetime(2026, 7, 29, 12, 0, 0, tzinfo=dt.UTC)
    with pytest.raises(ValueError):  # Pydantic validation
        MemoryOutboxRow(
            id=1,
            key="reflection:abc",
            payload={"text": "hello"},
            enqueued_at=now,
            status="bogus",  # ty: ignore[invalid-argument-type]
        )


def test_outbox_status_is_literal() -> None:
    # Compile-time assertion; if this doesn't hold the type checker will flag it.
    s: OutboxStatus = "drained"
    assert s in ("pending", "drained", "failed")


@pytest.fixture
def writer(tmp_path: pathlib.Path) -> Iterator[MemoryOutboxWriter]:
    db = tmp_path / "outbox.duckdb"
    w = MemoryOutboxWriter(db)
    yield w
    w.close()


async def test_writer_enqueues_and_round_trips(writer: MemoryOutboxWriter) -> None:
    ids = []
    for i in range(100):
        ids.append(await writer.enqueue(f"reflection:{i}", {"i": i}))
    assert len(ids) == 100
    assert len(set(ids)) == 100  # all distinct BIGSERIAL values
    assert await writer.pending_count() == 100


async def test_writer_pending_count_filters_correctly(writer: MemoryOutboxWriter) -> None:
    id1 = await writer.enqueue("k1", {"a": 1})
    id2 = await writer.enqueue("k2", {"a": 2})
    await writer.enqueue("k3", {"a": 3})  # must remain pending
    await writer.mark_drained([id1, id2])
    assert await writer.pending_count() == 1


async def test_writer_mark_failed_records_error(writer: MemoryOutboxWriter) -> None:
    id1 = await writer.enqueue("k1", {"a": 1})
    await writer.mark_failed([id1], "boom")
    assert await writer.pending_count() == 0
    # Verify the row itself: status flipped to `failed`, attempts bumped,
    # and last_error captured. Uses the public ``get_row`` helper which
    # ignores status filtering (unlike ``pending_batch``).
    row = await writer.get_row(id1)
    assert row is not None
    assert row.status == "failed"
    assert row.attempts == 1
    assert row.last_error == "boom"
