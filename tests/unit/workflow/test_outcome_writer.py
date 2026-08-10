"""Verify record_workflow_outcome validates and persists WorkflowOutcome."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from dhara.schema import SchemaValidationError, WorkflowOutcome
import pytest

from mahavishnu.core.workflow.outcome_writer import record_workflow_outcome


@pytest.fixture
def dhara_storage(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the dhara.put call to capture writes without hitting the real DB."""
    captured: list[tuple[str, object]] = []
    mock_put = MagicMock(side_effect=lambda key, value: captured.append((key, value)))
    monkeypatch.setattr(
        "mahavishnu.core.workflow.outcome_writer.dhara.put",
        mock_put,
    )
    return mock_put


def test_record_workflow_outcome_persists_validated_struct(
    dhara_storage: MagicMock,
) -> None:
    payload = {
        "workflow_id": "wf-123",
        "status": "succeeded",
        "started_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC),
        "metadata": {"ttl_seconds": 300},
    }
    record = record_workflow_outcome(**payload)
    assert isinstance(record, WorkflowOutcome)
    assert record.workflow_id == "wf-123"
    assert record.status == "succeeded"
    assert dhara_storage.call_count == 1


def test_record_workflow_outcome_rejects_invalid_status(
    dhara_storage: MagicMock,
) -> None:
    """Literal['succeeded','failed','cancelled'] enforced by substrate."""
    with pytest.raises(SchemaValidationError):
        record_workflow_outcome(
            workflow_id="wf-123",
            status="unknown",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
    assert dhara_storage.call_count == 0  # invalid never persisted
