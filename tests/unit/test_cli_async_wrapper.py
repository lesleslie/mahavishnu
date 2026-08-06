"""Verify precommit CLI wraps async HypothesisLock in asyncio.run."""

from __future__ import annotations

import asyncio
from datetime import datetime

from dhara.lock.in_memory import InMemoryDharaLock

from mahavishnu.core.precommitment import Hypothesis, HypothesisLock


def test_cli_helpers_work_via_in_memory_backend() -> None:
    """Smoke test: an InMemoryDharaLock-backed HypothesisLock exercises the async path."""
    lock = HypothesisLock(dhara_lock=InMemoryDharaLock())
    h = Hypothesis(
        claim="x",
        falsification_criteria=("a",),
        success_criteria=("b",),
        confidence=80,
        locked_at=datetime.now(),
    )
    result = asyncio.run(lock.lock(h))
    assert result.lock_id.startswith("L-")
    assert asyncio.run(lock.verify_lock(result.lock_id)) is True
