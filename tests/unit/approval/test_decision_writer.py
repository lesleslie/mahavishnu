"""Verify record_approval_decision validates and persists ApprovalLog."""

from __future__ import annotations

import datetime as _dt
from typing import Any
from unittest.mock import MagicMock

from dhara.schema import ApprovalLog, SchemaValidationError
import pytest

from mahavishnu.core.approval.decision_writer import record_approval_decision


@pytest.fixture
def dhara_storage(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub dhara.put after module import so the substrate-compat guard sees it."""
    # Ensure the writer module is importable for the substrate-compat guard to run.
    import mahavishnu.core.approval.decision_writer as writer

    captured: list[tuple[str, Any]] = []
    mock_put = MagicMock(side_effect=lambda key, value: captured.append((key, value)))
    monkeypatch.setattr(writer.dhara, "put", mock_put, raising=False)
    return mock_put


def test_record_approval_decision_persists_validated_struct(
    dhara_storage: MagicMock,
) -> None:
    record = record_approval_decision(
        approval_id="apr-001",
        decision="approved",
        rationale="All checks pass",
        decided_by="alice",
    )
    assert isinstance(record, ApprovalLog)
    assert record.action == "approved"
    assert record.actor == "alice"
    assert record.approval_id == "apr-001"
    assert isinstance(record.at, _dt.datetime)
    assert record.metadata.get("rationale") == "All checks pass"
    assert dhara_storage.call_count == 1
    call_args = dhara_storage.call_args
    assert call_args.args[0] == "approval-history/apr-001/"
    persisted = call_args.args[1]
    assert isinstance(persisted, ApprovalLog)
    assert persisted.action == "approved"


def test_record_approval_decision_rejects_invalid_decision(
    dhara_storage: MagicMock,
) -> None:
    """Literal['approved','denied','requested'] enforced by substrate."""
    with pytest.raises(SchemaValidationError):
        record_approval_decision(
            approval_id="apr-002",
            decision="invalid_value",
            rationale="Test",
            decided_by="alice",
        )
    assert dhara_storage.call_count == 0


def test_record_approval_decision_passes_through_metadata(
    dhara_storage: MagicMock,
) -> None:
    record = record_approval_decision(
        approval_id="apr-003",
        decision="denied",
        rationale="Workflow failed",
        decided_by="bob",
        metadata={"ticket": "OPS-42"},
    )
    assert record.metadata["ticket"] == "OPS-42"
    assert record.metadata["rationale"] == "Workflow failed"
    assert dhara_storage.call_count == 1


def test_record_approval_decision_emits_log_event(
    dhara_storage: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with caplog.at_level(logging.INFO, logger="mahavishnu.core.approval.decision_writer"):
        record_approval_decision(
            approval_id="apr-004",
            decision="requested",
            rationale="Need operator review",
            decided_by="system",
        )
    assert any("approval_log_recorded" in rec.message for rec in caplog.records), [
        rec.message for rec in caplog.records
    ]
    assert dhara_storage.call_count == 1
