"""Unit tests for mahavishnu.core.events.worker_topics."""

from __future__ import annotations

from mahavishnu.core.events.worker_topics import (
    WORKER_ATTACHED,
    WORKER_AVAILABILITY_CHANGED,
    WORKER_DETACHED,
    WORKER_REAPED,
    WORKER_SPAWNED,
    WORKER_STATUS_CHANGED,
    is_worker_topic,
)


def test_topic_constants() -> None:
    """All six worker topic constants have the expected string values."""
    assert WORKER_SPAWNED == "worker.spawned"
    assert WORKER_ATTACHED == "worker.attached"
    assert WORKER_DETACHED == "worker.detached"
    assert WORKER_STATUS_CHANGED == "worker.status_changed"
    assert WORKER_AVAILABILITY_CHANGED == "worker.availability_changed"
    assert WORKER_REAPED == "worker.reaped"


def test_is_worker_topic() -> None:
    """is_worker_topic returns True for worker.* topics and False otherwise."""
    assert is_worker_topic("worker.spawned")
    assert is_worker_topic("worker.status_changed")
    assert not is_worker_topic("workflow.started")
    assert not is_worker_topic("pool.scaled")
    assert not is_worker_topic("adapter.health_changed")