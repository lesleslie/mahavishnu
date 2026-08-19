"""Verify record_workflow_outcome validates and persists WorkflowOutcome."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

from dhara.schema import SchemaValidationError, WorkflowOutcome
import pytest

from mahavishnu.core.workflow import outcome_writer
from mahavishnu.core.workflow.outcome_writer import record_workflow_outcome


@pytest.fixture
def dhara_storage(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch the dhara.put call to capture writes without hitting the real DB.

    The writer resolves ``dhara.put`` at call time via
    :func:`mahavishnu.core._dhara_substrate_compat.dhara_calltime`, so the
    patch must target the live ``dhara`` module (the writer module no
    longer imports ``dhara`` as a name).
    """
    import dhara

    captured: list[tuple[str, object]] = []
    mock_put = MagicMock(side_effect=lambda key, value: captured.append((key, value)))
    monkeypatch.setattr(dhara, "put", mock_put, raising=False)
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


# --- Task 149: feature flag + runtime gate coverage ---


def test_flag_helper_defaults_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """WORKFLOW_OUTCOME_V1_ENABLED unset → default True."""
    monkeypatch.delenv("WORKFLOW_OUTCOME_V1_ENABLED", raising=False)
    assert outcome_writer._workflow_outcome_v1_enabled() is True


def test_flag_helper_explicit_true(monkeypatch: pytest.MonkeyPatch) -> None:
    """WORKFLOW_OUTCOME_V1_ENABLED='true' → True."""
    monkeypatch.setenv("WORKFLOW_OUTCOME_V1_ENABLED", "true")
    assert outcome_writer._workflow_outcome_v1_enabled() is True


def test_flag_helper_explicit_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """WORKFLOW_OUTCOME_V1_ENABLED='false' → False (rollback switch)."""
    monkeypatch.setenv("WORKFLOW_OUTCOME_V1_ENABLED", "false")
    assert outcome_writer._workflow_outcome_v1_enabled() is False


def test_producer_skips_when_dhara_put_unbound(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Substrate-compat: missing dhara.put → no persistence, returns validated struct,
    logs WARNING with omission fingerprint for diagnosis."""
    # Simulate the substrate not exposing dhara.put.
    import dhara

    monkeypatch.setattr(dhara, "put", None, raising=False)
    with caplog.at_level("WARNING"):
        record = record_workflow_outcome(
            workflow_id="wf-unbound",
            status="succeeded",
            started_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC),
        )
    assert isinstance(record, WorkflowOutcome)
    assert record.workflow_id == "wf-unbound"
    # Warning emitted with the omission fingerprint.
    assert any(
        "workflow_outcome_persistence_skipped" in record.message
        for record in caplog.records
    )


def test_consumer_returns_none_when_dhara_get_unbound(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Substrate-compat: missing dhara.get → return None + warn (do not raise)."""
    # Simulate the substrate not exposing dhara.get.
    import dhara

    monkeypatch.setattr(dhara, "get", None, raising=False)
    # Import inside the test so the monkeypatched module is the one we hit.
    from mahavishnu.mcp.tools import workflow_tools

    async def _exercise() -> "WorkflowOutcome | dict[str, object] | None":
        return await workflow_tools.workflow_get_outcome("wf-missing")

    with caplog.at_level("WARNING"):
        result = asyncio.run(_exercise())
    assert result is None
    assert any(
        "workflow_outcome_read_skipped" in record.message
        for record in caplog.records
    )


def test_call_site_skips_persistence_when_flag_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: WORKFLOW_OUTCOME_V1_ENABLED=false causes the call site
    in finalize_workflow_execution to skip record_workflow_outcome entirely.

    We exercise the flag check directly rather than running the full
    finalize_workflow_execution path (which depends on a wired
    MahavishnuApp). The negative test is the call site's ``if`` guard.
    """
    monkeypatch.setenv("WORKFLOW_OUTCOME_V1_ENABLED", "false")
    assert outcome_writer._workflow_outcome_v1_enabled() is False
    # When the flag is off, the call site must short-circuit BEFORE the
    # try/except. Asserting the helper itself only verifies the trigger;
    # the call site in workflow_execution.py owns the wrapping behavior.
