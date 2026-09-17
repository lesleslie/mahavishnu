"""Verify precommit CLI wraps async HypothesisLock in asyncio.run."""

from __future__ import annotations

import asyncio
from datetime import datetime

from mahavishnu.core._lock_sentinel import Lock
from mahavishnu.core.precommitment import Hypothesis, HypothesisLock


def test_cli_helpers_work_via_local_lock_backend() -> None:
    """Smoke test: a local-Lock-backed HypothesisLock exercises the async path."""
    lock = HypothesisLock(lock=Lock())
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
