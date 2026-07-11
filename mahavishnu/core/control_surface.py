"""Runtime control-surface helpers for MahavishnuApp.

These helpers keep the application class focused on wiring while preserving
the public app-level API used by the TUI, MCP tools, and ecosystem status
collectors.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


async def get_recovery_summary(app: Any) -> dict[str, Any]:
    """Return a durable-state recovery summary for operator surfaces."""
    summary = {
        "recovered_workflows": len(app.active_workflows),
        "recovered_approvals": len(app.approval_manager.pending_requests),
        "recovered_pools": len(app.pool_manager._pools) if app.pool_manager else 0,
        "recovered_routing_decisions": 0,
        "dhara_available": False,
        "last_recovered_at": None,
    }
    if app._dhara_state is None:
        return summary

    try:
        workflows = await app._dhara_state.recover_workflows()
        approvals = await app._dhara_state.recover_approvals()
        pools = await app._dhara_state.recover_pools()
        routing = await app._dhara_state.recover_routing_decisions()
        summary.update(
            {
                "recovered_workflows": sum(
                    1 for value in workflows if value.get("status") == "running"
                ),
                "recovered_approvals": len(approvals),
                "recovered_pools": len(pools),
                "recovered_routing_decisions": len(routing),
                "dhara_available": bool(app._dhara_state.available),
                "last_recovered_at": datetime.now().isoformat(),
            }
        )
    except Exception as exc:
        from logging import getLogger

        getLogger(__name__).debug("Dhara recovery summary skipped: %s", exc)
    return summary


async def get_recovered_routing_decisions(
    app: Any,
    task_class: str | None = None,
) -> list[dict[str, Any]]:
    """Return recovered routing decisions from Dhara."""
    if app._dhara_state is None:
        return []

    try:
        decisions = await app._dhara_state.recover_routing_decisions()
        if task_class is None:
            return decisions  # type: ignore[no-any-return]
        return [
            decision
            for decision in decisions
            if isinstance(decision, dict) and decision.get("task_class") == task_class
        ]
    except Exception as exc:
        from logging import getLogger

        getLogger(__name__).debug("Dhara routing recovery skipped: %s", exc)
        return []


def record_event_activity(app: Any, envelope: Any) -> None:
    """Record a canonical envelope for cockpit activity views."""
    payload = envelope.to_dict() if hasattr(envelope, "to_dict") else dict(envelope)
    app.event_activity.append(
        {
            "event_id": payload.get("event_id"),
            "event_type": payload.get("event_type"),
            "source": payload.get("source"),
            "timestamp": payload.get("timestamp"),
            "correlation_id": payload.get("correlation_id"),
            "causation_id": payload.get("causation_id"),
            "payload": payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            "metadata": payload.get("metadata")
            if isinstance(payload.get("metadata"), dict)
            else {},
        }
    )


def get_event_activity(app: Any, limit: int = 25) -> list[dict[str, Any]]:
    """Return the most recent canonical events for cockpit display."""
    if limit <= 0:
        return []
    return list(app.event_activity)[-limit:]


def record_fix_trace(
    app: Any,
    correlation_id: str,
    stage: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record a correlation-aware fix trace entry for the cockpit."""
    app.fix_activity.append(
        {
            "correlation_id": correlation_id,
            "stage": stage,
            "message": message,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(),
        }
    )


def get_fix_trace(
    app: Any,
    correlation_id: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Return recent fix trace entries, optionally filtered by correlation."""
    if limit <= 0:
        return []
    entries = list(app.fix_activity)
    if correlation_id is not None:
        entries = [entry for entry in entries if entry.get("correlation_id") == correlation_id]
    return entries[-limit:]


def get_correlation_status(app: Any, correlation_id: str | None = None) -> dict[str, Any]:
    """Return a correlation-aware status snapshot for operator surfaces."""
    trace = get_fix_trace(app, correlation_id=correlation_id, limit=25)
    return {
        "correlation_id": correlation_id,
        "trace_count": len(trace),
        "latest_stage": trace[-1]["stage"] if trace else None,
        "latest_message": trace[-1]["message"] if trace else None,
        "session_checkpoints": len(trace),
        "dhara_available": bool(app._dhara_state.available) if app._dhara_state else False,
    }


def list_pending_approvals(app: Any) -> list[dict[str, Any]]:
    """Return pending approvals as dictionaries for cockpit surfaces."""
    return [request.to_dict() for request in app.approval_manager.pending_requests]


def request_approval(
    app: Any,
    approval_type: str,
    context: dict[str, Any],
    options: list[Any] | None = None,
    timeout_minutes: int | None = None,
) -> dict[str, Any]:
    """Forward an approval request through the durable approval manager."""
    request = app.approval_manager.create_request(
        approval_type=approval_type,
        context=context,
        options=options,
        timeout_minutes=timeout_minutes,
    )
    return request.to_dict()  # type: ignore[no-any-return]


def respond_to_approval(
    app: Any,
    request_id: str,
    approved: bool,
    selected_option: int | None = None,
    rejection_reason: str | None = None,
) -> dict[str, Any]:
    """Forward an approval response through the durable approval manager."""
    result = app.approval_manager.respond(
        request_id=request_id,
        approved=approved,
        selected_option=selected_option,
        rejection_reason=rejection_reason,
    )
    return {
        "request_id": request_id,
        "approved": result.approved,
        "selected_option": result.selected_option,
        "rejection_reason": result.rejection_reason,
    }
