"""Tests for the outbox wiring inside MemoryAggregator.

The outbox (Q2 data-plane durability) is opt-in: two env vars gate the
writer and drainer respectively. These tests verify the env-var contract
by constructing MemoryAggregator directly — no real Session-Buddy required.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration


def _fresh_aggregator() -> object:
    """Build a MemoryAggregator in the current process.

    A fresh import is required because `os.environ` is captured at module
    import time (see `_OUTBOX_ENABLED` / `_OUTBOX_DRAIN` in
    memory_aggregator.py). Each test sets env vars BEFORE the import.
    """
    import importlib

    import mahavishnu.pools.memory_aggregator as mod

    importlib.reload(mod)
    return mod.MemoryAggregator()


def test_aggregator_with_outbox_disabled_unchanged() -> None:
    os.environ["MAHAVISHNU_OUTBOX_ENABLED"] = "false"
    os.environ["MAHAVISHNU_OUTBOX_DRAIN"] = "false"
    agg = _fresh_aggregator()
    assert agg._outbox_writer is None
    assert agg._outbox_drainer is None


def test_aggregator_with_outbox_enabled_creates_writer() -> None:
    os.environ["MAHAVISHNU_OUTBOX_ENABLED"] = "true"
    os.environ["MAHAVISHNU_OUTBOX_DRAIN"] = "false"
    agg = _fresh_aggregator()
    try:
        assert agg._outbox_writer is not None
        # Drain flag is off, so the drainer must NOT be constructed.
        assert agg._outbox_drainer is None
    finally:
        if agg._outbox_writer is not None:
            agg._outbox_writer.close()


def test_aggregator_with_outbox_enabled_and_drain_creates_both() -> None:
    os.environ["MAHAVISHNU_OUTBOX_ENABLED"] = "true"
    os.environ["MAHAVISHNU_OUTBOX_DRAIN"] = "true"
    agg = _fresh_aggregator()
    try:
        assert agg._outbox_writer is not None
        assert agg._outbox_drainer is not None
    finally:
        if agg._outbox_writer is not None:
            agg._outbox_writer.close()


def test_collect_and_sync_fires_drainer_when_outbox_enabled() -> None:
    """When MAHAVISHNU_OUTBOX_DRAIN is on, ``collect_and_sync`` must invoke
    the drainer's ``drain_once`` so the WAL actually moves rows. This is
    the wiring that closes the loop between PHASE 2 (batch insert) and
    the outbox sink: without it, rows enqueued during this cycle sit
    ``pending`` until the next process restart.
    """
    os.environ["MAHAVISHNU_OUTBOX_ENABLED"] = "true"
    os.environ["MAHAVISHNU_OUTBOX_DRAIN"] = "true"
    agg = _fresh_aggregator()
    try:
        # Swap in a mock drainer so we can assert the wiring without hitting
        # the real Session-Buddy sink. The aggregator's own writer/drainer
        # already point at the live ~/.mahavishnu/outbox.duckdb — we don't
        # need to touch the WAL for this test.
        drainer_mock = MagicMock()
        drainer_mock.drain_once = AsyncMock()
        agg._outbox_drainer = drainer_mock

        pool_manager = MagicMock()
        pool_manager.list_pools = AsyncMock(return_value=[])

        with (
            patch.object(
                agg,
                "_batch_insert_to_session_buddy",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                agg,
                "flush_local_buffer",
                new_callable=AsyncMock,
                return_value={"flushed": 0, "remaining": 0},
            ),
            patch.object(agg, "_sync_to_akosha", new_callable=AsyncMock),
        ):
            import asyncio

            asyncio.run(agg.collect_and_sync(pool_manager))

        drainer_mock.drain_once.assert_awaited_once()
    finally:
        if agg._outbox_writer is not None:
            agg._outbox_writer.close()


def test_collect_and_sync_skips_drainer_when_outbox_disabled() -> None:
    """Sanity check: when no drainer is constructed (env-var default),
    ``collect_and_sync`` must not raise or attempt to await ``None``.
    """
    os.environ["MAHAVISHNU_OUTBOX_ENABLED"] = "false"
    os.environ["MAHAVISHNU_OUTBOX_DRAIN"] = "false"
    agg = _fresh_aggregator()
    try:
        assert agg._outbox_drainer is None

        pool_manager = MagicMock()
        pool_manager.list_pools = AsyncMock(return_value=[])

        with (
            patch.object(
                agg,
                "_batch_insert_to_session_buddy",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch.object(
                agg,
                "flush_local_buffer",
                new_callable=AsyncMock,
                return_value={"flushed": 0, "remaining": 0},
            ),
            patch.object(agg, "_sync_to_akosha", new_callable=AsyncMock),
        ):
            import asyncio

            asyncio.run(agg.collect_and_sync(pool_manager))
    finally:
        if agg._outbox_writer is not None:
            agg._outbox_writer.close()
