"""Tests for the outbox wiring inside MemoryAggregator.

The outbox (Q2 data-plane durability) is opt-in: two env vars gate the
writer and drainer respectively. These tests verify the env-var contract
by constructing MemoryAggregator directly — no real Session-Buddy required.
"""

from __future__ import annotations

import os

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
