from __future__ import annotations

from enum import Enum


class WorkerLifecycleState(str, Enum):
    PENDING = "pending"
    STARTING = "starting"
    READY = "ready"
    RUNNING = "running"
    DETACHED = "detached"
    DRAINING = "draining"
    COMPLETED = "completed"
    FAILED = "failed"
    REAPED = "reaped"
    DEGRADED = "degraded"


ALLOWED_TRANSITIONS: dict[WorkerLifecycleState, set[WorkerLifecycleState]] = {
    WorkerLifecycleState.PENDING: {
        WorkerLifecycleState.STARTING,
        WorkerLifecycleState.REAPED,
        WorkerLifecycleState.FAILED,
    },
    WorkerLifecycleState.STARTING: {
        WorkerLifecycleState.READY,
        WorkerLifecycleState.REAPED,
        WorkerLifecycleState.FAILED,
        WorkerLifecycleState.DEGRADED,
    },
    WorkerLifecycleState.READY: {
        WorkerLifecycleState.RUNNING,
        WorkerLifecycleState.DETACHED,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
        WorkerLifecycleState.DEGRADED,
    },
    WorkerLifecycleState.RUNNING: {
        WorkerLifecycleState.DETACHED,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.COMPLETED,
        WorkerLifecycleState.FAILED,
        WorkerLifecycleState.DEGRADED,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.DETACHED: {
        WorkerLifecycleState.RUNNING,
        WorkerLifecycleState.READY,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
        WorkerLifecycleState.DEGRADED,
    },
    WorkerLifecycleState.DRAINING: {
        WorkerLifecycleState.COMPLETED,
        WorkerLifecycleState.FAILED,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.COMPLETED: {
        WorkerLifecycleState.READY,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.FAILED: {
        WorkerLifecycleState.READY,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.DEGRADED: {
        WorkerLifecycleState.READY,
        WorkerLifecycleState.DRAINING,
        WorkerLifecycleState.REAPED,
    },
    WorkerLifecycleState.REAPED: set(),
}


def can_transition(
    current: WorkerLifecycleState, target: WorkerLifecycleState
) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())
