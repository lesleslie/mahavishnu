"""Queueing-theory primitives for Mahavishnu pool routing (Tier 1 Phase 1 + 2).

# Implements: REQ-001

Exposes :class:`MmcQueue` — a stateless M/M/c queueing model that fits
its parameters from observed inter-arrival and service times and
produces expected-wait-time estimates using either the Kingman
heavy-traffic approximation or the exact M/M/c Erlang-C formula.

The library is pure-Python with no third-party dependencies. The
queueing estimate is consumed directly by
:class:`~mahavishnu.pools.manager.PoolManager._apply_queueing_penalty`
(Phase 2 onward); the per-pool observation buffer is filled by the
route path and read by the re-ranking logic.

Round-4 general/safety (HIGH-1): the previous ``QueueingScorer``
wrapper was an additive-penalty pattern that was never instantiated
in production. It was removed in round-4 to avoid the orphan
abstraction trap (built-but-not-wired).
"""

from __future__ import annotations

from mahavishnu.pools.queueing.mmc import MmcQueue
from mahavishnu.pools.queueing.scorer import (
    DEFAULT_WARMUP_MIN_OBSERVATIONS,
    DEFAULT_WARMUP_MIN_SECONDS,
    QueueingObservationBuffer,
)

__all__ = [
    "DEFAULT_WARMUP_MIN_OBSERVATIONS",
    "DEFAULT_WARMUP_MIN_SECONDS",
    "MmcQueue",
    "QueueingObservationBuffer",
]
