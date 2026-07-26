from mahavishnu.workers.contract.state import (
    WorkerLifecycleState,
    ALLOWED_TRANSITIONS,
    can_transition,
)


def test_state_values():
    assert WorkerLifecycleState.PENDING.value == "pending"
    assert WorkerLifecycleState.READY.value == "ready"
    assert WorkerLifecycleState.DRAINING.value == "draining"
    assert WorkerLifecycleState.REAPED.value == "reaped"


def test_can_transition_ready_to_running():
    assert can_transition(WorkerLifecycleState.READY, WorkerLifecycleState.RUNNING)


def test_can_transition_running_to_completed():
    assert can_transition(WorkerLifecycleState.RUNNING, WorkerLifecycleState.COMPLETED)


def test_cannot_transition_reaped_to_running():
    assert not can_transition(WorkerLifecycleState.REAPED, WorkerLifecycleState.RUNNING)


def test_cannot_transition_completed_to_running():
    assert not can_transition(WorkerLifecycleState.COMPLETED, WorkerLifecycleState.RUNNING)


def test_detached_can_return_to_running():
    assert can_transition(WorkerLifecycleState.DETACHED, WorkerLifecycleState.RUNNING)
