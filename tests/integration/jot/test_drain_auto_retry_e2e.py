"""End-to-end adversarial tests for the reconciler auto-retry path.

Verifies that the reconciler fires auto-retry as background tasks
(fire-and-forget via asyncio.create_task) and does NOT block on the
30s RETRY_BACKOFF_SECONDS — even with multiple FAILED-but-retriable
jots to process.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import time

import pytest

from mahavishnu.jot import drain as drain_module
from mahavishnu.jot.drain import (
    DispatchState,
    _reconcile_if_in_flight,
)


def _make_summary(**overrides):  # type: ignore[no-untyped-def]
    """Build a JotSummary directly (no log needed for adversarial timing test)."""
    from mahavishnu.jot.fold import JotSummary

    defaults = dict(
        id="e1", short_id="123456", text="hello",
        status="open", last_modified_ms=0,
        dispatch_state=DispatchState.IN_FLIGHT,
        dispatch_workflow_id="wf-1",
        current_attempt=1,
        dispatch_started_at_ms=int(time.time() * 1000) - 700_000,  # past Tier-2 timeout
        deferred_until=None, deleted=False,
    )
    defaults.update(overrides)
    return JotSummary(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_reconciler_does_not_block_on_auto_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    fake_workflow_substrate: dict, fast_backoff: None,
) -> None:
    """Adversarial: reconciler picks up FAILED dispatch, schedules
    auto-retry via _retry_waiters, and moves on to next jot WITHOUT
    waiting for RETRY_BACKOFF_SECONDS (30s).

    Pre-fix: ``await _auto_retry_after(jot.short_id, backoff_s=30)``
    blocked the reconciler for 30s per FAILED-but-retriable jot.
    Post-fix: ``asyncio.create_task`` fires-and-forgets; the test
    observes via ``_retry_waiters[handle]``.

    Constructs jots inline (no ``create_failed_dispatch_jot`` helper on
    ``fake_workflow_substrate``).

    Note: only ``fast_backoff`` is used (no ``no_async_sleep``) so the
    test's own ``await asyncio.sleep(0)`` actually yields to the loop.
    """
    # Redirect log to a per-test tmp file so _auto_retry_after's fold
    # call doesn't read whatever leftover state.
    log_p = tmp_path / "log.jsonl"
    monkeypatch.setattr("mahavishnu.jot.drain.log_path", lambda: log_p)
    monkeypatch.setattr("mahavishnu.jot.paths.log_path", lambda: log_p)

    # Force the Tier-2 timeout gate to fire by setting now_ms far in
    # the future relative to dispatch_started_at_ms.
    future_ms = int(time.time() * 1000) + 10_000
    monkeypatch.setattr("mahavishnu.jot.drain._now_ms", lambda: future_ms)

    # Set up: 3 jots, all FAILED-but-retriable (attempt=1, budget=2).
    jots = [_make_summary(short_id=f"id{i:06d}") for i in range(3)]

    start = time.monotonic()
    # The reconciler normally runs in Tier-2 (background). For the
    # test we invoke it directly per jot, mimicking the per-jot path.
    for jot in jots:
        await _reconcile_if_in_flight(jot)
    elapsed = time.monotonic() - start

    # Pre-fix: elapsed would be ~90s (3 jots × 30s backoff).
    # Post-fix: elapsed should be << 1s. This is the core adversarial
    # proof: the reconciler does NOT block on the auto-retry backoff.
    assert elapsed < 1.0, (
        f"reconciler blocked on auto-retry: elapsed={elapsed:.2f}s "
        f"(expected <1s post-revert)"
    )

    # Yield to the event loop so the fire-and-forget tasks can start.
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    # All 3 jots have a waiter entry (auto-retry was scheduled).
    assert len(drain_module._retry_waiters) == 3
    for jot in jots:
        assert jot.short_id in drain_module._retry_waiters

    # Wait for all retries to complete (cleanup).
    await asyncio.gather(
        *[drain_module._retry_waiters[j.short_id].wait() for j in jots],
        return_exceptions=True,
    )
    for j in jots:
        drain_module._retry_waiters.pop(j.short_id, None)
