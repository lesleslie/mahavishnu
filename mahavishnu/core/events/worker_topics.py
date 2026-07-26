"""Canonical worker event topic constants.

These constants define the public topic strings used by the durable local
workers envelope publisher (Task 7) and consumed by the statusline and
Constellation dashboard.
"""

from __future__ import annotations

WORKER_SPAWNED = "worker.spawned"
WORKER_ATTACHED = "worker.attached"
WORKER_DETACHED = "worker.detached"
WORKER_STATUS_CHANGED = "worker.status_changed"
WORKER_AVAILABILITY_CHANGED = "worker.availability_changed"
WORKER_REAPED = "worker.reaped"

WORKER_TOPICS: frozenset[str] = frozenset(
    {
        WORKER_SPAWNED,
        WORKER_ATTACHED,
        WORKER_DETACHED,
        WORKER_STATUS_CHANGED,
        WORKER_AVAILABILITY_CHANGED,
        WORKER_REAPED,
    }
)


def is_worker_topic(topic: str) -> bool:
    """Return True when *topic* is one of the canonical worker topics."""
    return topic in WORKER_TOPICS