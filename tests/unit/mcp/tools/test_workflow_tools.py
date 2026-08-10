"""Verify workflow_get_outcome returns a validated WorkflowOutcome struct."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from dhara.schema import WorkflowOutcome
import pytest

from mahavishnu.mcp.tools.workflow_tools import workflow_get_outcome

pytestmark = pytest.mark.unit


def test_workflow_get_outcome_returns_validated_struct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "workflow_id": "wf-abc",
        "status": "failed",
        "started_at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC),
        "metadata": {},
    }
    mock_get = MagicMock(return_value=payload)
    monkeypatch.setattr(
        "mahavishnu.mcp.tools.workflow_tools.dhara.get",
        mock_get,
    )
    result = workflow_get_outcome("wf-abc")
    assert isinstance(result, WorkflowOutcome)
    assert result.workflow_id == "wf-abc"
    assert result.status == "failed"
    assert mock_get.call_count == 1
    assert mock_get.call_args.args[0] == "workflow-results/wf-abc/"


def test_workflow_get_outcome_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Substrate returns None → consumer returns None (no validation attempted)."""
    mock_get = MagicMock(return_value=None)
    monkeypatch.setattr(
        "mahavishnu.mcp.tools.workflow_tools.dhara.get",
        mock_get,
    )
    result = workflow_get_outcome("wf-missing")
    assert result is None
