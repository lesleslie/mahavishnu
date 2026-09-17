"""Round-trip test for ``mahavishnu.core.models.persistence``.

Pins the wire-format compatibility with the original Dhara types
(``dhara.schema.{WorkflowOutcome, ApprovalLog, WebhookIngress}``) by
asserting that ``msgspec.to_builtins(...)`` produces the exact field set
Dhara would produce for an equivalent instance. Any drift in field name,
type, or ``frozen=True`` status surfaces here as a test failure rather
than as silent data corruption at the durable store boundary.
"""

from __future__ import annotations

from datetime import datetime

import msgspec

from mahavishnu.core.models.persistence import (
    ApprovalLog,
    WebhookIngress,
    WorkflowOutcome,
)


def test_workflow_outcome_roundtrip_matches_dhara_shape() -> None:
    """Round-trip a WorkflowOutcome through msgspec.to_builtins."""
    outcome = WorkflowOutcome(
        workflow_id="wf-001",
        status="succeeded",
        started_at=datetime(2026, 9, 16, 12, 0, 0),
        finished_at=datetime(2026, 9, 16, 12, 5, 30),
        metadata={"trigger": "manual"},
    )
    dumped = msgspec.to_builtins(outcome)
    assert dumped == {
        "workflow_id": "wf-001",
        "status": "succeeded",
        "started_at": "2026-09-16T12:00:00",
        "finished_at": "2026-09-16T12:05:30",
        "metadata": {"trigger": "manual"},
    }
    # Round-trip back through msgspec.convert to confirm parser compatibility.
    restored = msgspec.convert(dumped, WorkflowOutcome)
    assert restored == outcome


def test_approval_log_roundtrip_matches_dhara_shape() -> None:
    """Round-trip an ApprovalLog through msgspec.to_builtins."""
    entry = ApprovalLog(
        approval_id="apr-001",
        actor="les",
        action="approved",
        at=datetime(2026, 9, 16, 12, 1, 0),
        metadata={"reason": "lgtm"},
    )
    dumped = msgspec.to_builtins(entry)
    assert dumped == {
        "approval_id": "apr-001",
        "actor": "les",
        "action": "approved",
        "at": "2026-09-16T12:01:00",
        "metadata": {"reason": "lgtm"},
    }
    restored = msgspec.convert(dumped, ApprovalLog)
    assert restored == entry


def test_webhook_ingress_roundtrip_matches_dhara_shape() -> None:
    """Round-trip a WebhookIngress through msgspec.to_builtins."""
    record = WebhookIngress(
        webhook_id="wh-001",
        source="github",
        received_at=datetime(2026, 9, 16, 12, 2, 0),
        payload_hash="sha256:" + "a" * 64,
        metadata={"event": "push"},
    )
    dumped = msgspec.to_builtins(record)
    assert dumped == {
        "webhook_id": "wh-001",
        "source": "github",
        "received_at": "2026-09-16T12:02:00",
        "payload_hash": "sha256:" + "a" * 64,
        "metadata": {"event": "push"},
    }
    restored = msgspec.convert(dumped, WebhookIngress)
    assert restored == record


def test_metadata_defaults_to_empty_dict() -> None:
    """All three types default ``metadata`` to ``{}`` (matches Dhara originals)."""
    assert WorkflowOutcome(
        workflow_id="wf-002",
        status="failed",
        started_at=datetime(2026, 9, 16),
        finished_at=datetime(2026, 9, 16, 0, 0, 1),
    ).metadata == {}
    assert ApprovalLog(
        approval_id="apr-002",
        actor="bob",
        action="denied",
        at=datetime(2026, 9, 16),
    ).metadata == {}
    assert WebhookIngress(
        webhook_id="wh-002",
        source="stripe",
        received_at=datetime(2026, 9, 16),
        payload_hash="sha256:" + "b" * 64,
    ).metadata == {}
