from __future__ import annotations

from types import SimpleNamespace

from mahavishnu.core.control_surface import (
    get_correlation_status,
    get_event_activity,
    get_fix_trace,
    get_recovered_routing_decisions,
    get_recovery_summary,
    list_pending_approvals,
    record_event_activity,
    record_fix_trace,
    request_approval,
    respond_to_approval,
)


class _Envelope:
    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": "evt-1",
            "event_type": "task.created",
            "source": "tests",
            "timestamp": "2026-05-16T00:00:00Z",
            "correlation_id": "corr-1",
            "causation_id": "cause-1",
            "payload": {"name": "demo"},
            "metadata": {"priority": "high"},
        }


class _Request:
    def __init__(self, request_id: str = "req-1") -> None:
        self.request_id = request_id

    def to_dict(self) -> dict[str, object]:
        return {"request_id": self.request_id, "status": "pending"}


class _ApprovalResult:
    def __init__(self) -> None:
        self.approved = True
        self.selected_option = 2
        self.rejection_reason = None


def test_recovery_summary_without_dhara_state() -> None:
    app = SimpleNamespace(
        active_workflows=[1, 2],
        approval_manager=SimpleNamespace(pending_requests=[1]),
        pool_manager=SimpleNamespace(_pools={"pool": object()}),
        _dhara_state=None,
    )

    import asyncio

    summary = asyncio.run(get_recovery_summary(app))

    assert summary["recovered_workflows"] == 2
    assert summary["recovered_approvals"] == 1
    assert summary["recovered_pools"] == 1
    assert summary["dhara_available"] is False
    assert summary["last_recovered_at"] is None


def test_recovery_summary_with_dhara_state() -> None:
    async def recover_workflows() -> list[dict[str, str]]:
        return [{"status": "running"}, {"status": "done"}]

    async def recover_approvals() -> list[int]:
        return [1, 2, 3]

    async def recover_pools() -> list[str]:
        return ["pool-a"]

    async def recover_routing_decisions() -> list[dict[str, int]]:
        return [{"decision": 1}, {"decision": 2}]

    dhara_state = SimpleNamespace(
        available=True,
        recover_workflows=recover_workflows,
        recover_approvals=recover_approvals,
        recover_pools=recover_pools,
        recover_routing_decisions=recover_routing_decisions,
    )
    app = SimpleNamespace(
        active_workflows=[],
        approval_manager=SimpleNamespace(pending_requests=[]),
        pool_manager=None,
        _dhara_state=dhara_state,
    )

    import asyncio

    summary = asyncio.run(get_recovery_summary(app))

    assert summary["recovered_workflows"] == 1
    assert summary["recovered_approvals"] == 3
    assert summary["recovered_pools"] == 1
    assert summary["recovered_routing_decisions"] == 2
    assert summary["dhara_available"] is True
    assert summary["last_recovered_at"] is not None


def test_get_recovered_routing_decisions_filters_and_handles_missing_state() -> None:
    import asyncio

    app = SimpleNamespace(_dhara_state=None)
    assert asyncio.run(get_recovered_routing_decisions(app)) == []

    async def recover_routing_decisions() -> list[dict[str, str]]:
        return [
            {"task_class": "build", "decision": "keep"},
            {"task_class": "deploy", "decision": "drop"},
            {"decision": "ignore"},
        ]

    dhara_state = SimpleNamespace(recover_routing_decisions=recover_routing_decisions)
    app = SimpleNamespace(_dhara_state=dhara_state)
    assert asyncio.run(get_recovered_routing_decisions(app, task_class="build")) == [
        {"task_class": "build", "decision": "keep"}
    ]


def test_event_activity_and_fix_traces() -> None:
    app = SimpleNamespace(event_activity=[], fix_activity=[])

    record_event_activity(app, _Envelope())
    record_event_activity(app, {"event_id": "evt-2", "payload": "not-a-dict", "metadata": 1})
    assert get_event_activity(app, limit=0) == []
    assert len(get_event_activity(app, limit=10)) == 2

    record_fix_trace(app, "corr-1", "start", "message-1", {"step": 1})
    record_fix_trace(app, "corr-2", "finish", "message-2", None)
    assert get_fix_trace(app, correlation_id="corr-1", limit=10)[0]["stage"] == "start"
    assert get_fix_trace(app, limit=0) == []

    status = get_correlation_status(
        SimpleNamespace(_dhara_state=None, fix_activity=app.fix_activity)
    )
    assert status["trace_count"] == 2
    assert status["latest_stage"] == "finish"
    assert status["dhara_available"] is False


def test_approval_helpers_delegate_to_manager() -> None:
    approval_manager = SimpleNamespace(
        pending_requests=[_Request("req-1")],
        create_request=lambda **kwargs: _Request(kwargs["approval_type"]),
        respond=lambda **kwargs: _ApprovalResult(),
    )
    app = SimpleNamespace(approval_manager=approval_manager)

    assert list_pending_approvals(app) == [{"request_id": "req-1", "status": "pending"}]
    assert request_approval(
        app, "deploy", {"repo": "demo"}, options=["yes"], timeout_minutes=5
    ) == {
        "request_id": "deploy",
        "status": "pending",
    }
    assert respond_to_approval(app, "req-1", True, selected_option=2) == {
        "request_id": "req-1",
        "approved": True,
        "selected_option": 2,
        "rejection_reason": None,
    }
