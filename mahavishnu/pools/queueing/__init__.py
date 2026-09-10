"""Queueing-theory primitives for Mahavishnu pool routing (Tier 1 Phase 1 + 2).

# Implements: REQ-001

Exposes :class:`MmcQueue` — a stateless M/M/c queueing model that fits
its parameters from observed inter-arrival and service times and
produces expected-wait-time estimates using either the Kingman
heavy-traffic approximation or the exact M/M/c Erlang-C formula.

The library is pure-Python with no third-party dependencies and is
consumed by the :class:`~mahavishnu.pools.queueing.scorer.QueueingScorer`
wrapper (Phase 2) which composes the queueing estimate with an
existing :class:`~mahavishnu.pools.manager.PoolSelector` strategy.
"""
from __future__ import annotations

from mahavishnu.pools.queueing.mmc import MmcQueue
from mahavishnu.pools.queueing.scorer import (
    DEFAULT_WARMUP_MIN_OBSERVATIONS,
    DEFAULT_WARMUP_MIN_SECONDS,
    QueueingObservationBuffer,
    QueueingScorer,
)

__all__ = [
    "DEFAULT_WARMUP_MIN_OBSERVATIONS",
    "DEFAULT_WARMUP_MIN_SECONDS",
    "MmcQueue",
    "QueueingObservationBuffer",
    "QueueingScorer",
]
