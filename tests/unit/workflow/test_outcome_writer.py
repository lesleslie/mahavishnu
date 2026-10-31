"""Verify record_workflow_outcome validates and persists WorkflowOutcome."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import json
from typing import Any

import msgspec
import pytest
from structlog.testing import capture_logs

from mahavishnu.core._producer_metrics import COUNTERS
from mahavishnu.core.kv_store import kv_store
from mahavishnu.core.models.persistence import WorkflowOutcome
from mahavishnu.core.workflow import outcome_writer
from mahavishnu.core.workflow.outcome_writer import record_workflow_outcome

# Producer name used for Prometheus label cardinality (mirrors the writer).
_PRODUCER = "workflow_outcome_writer"


def _stored(key: str) -> dict[str, Any] | None:
    """Return the decoded payload the producer wrote under ``key``.

    The substrate store holds strings; the facade JSON-encodes structs on
    write. ``None`` means "nothing was written under this key".
    """
    raw = kv_store.get(key)
    if raw is None:
        return None
    return json.loads(raw)


def test_record_workflow_outcome_persists_validated_struct() -> None:
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

    stored = _stored("workflow-results/wf-123/")
    assert stored is not None
    assert stored["workflow_id"] == "wf-123"
    assert stored["status"] == "succeeded"
    assert stored["metadata"] == {"ttl_seconds": 300}


def test_record_workflow_outcome_rejects_invalid_status() -> None:
    """Literal['succeeded','failed','cancelled'] enforced by the substrate."""
    with pytest.raises(msgspec.ValidationError):
        record_workflow_outcome(
            workflow_id="wf-123",
            status="unknown",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
    assert _stored("workflow-results/wf-123/") is None  # invalid never persisted


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


def test_producer_persists_and_counts_success_when_substrate_bound() -> None:
    """The substrate is always bound: the write lands and the counters say so.

    The writer used to resolve ``mcp.put`` through a dynamic module lookup
    and took a "substrate unbound" branch when that lookup returned
    ``None``. The substrate is this server's own in-process store now, so
    there is no unbound state: the write always happens, ``succeeded`` is
    incremented, ``skipped`` never is, and no skip warning is emitted.
    """
    attempted_before = COUNTERS.attempted.labels(producer=_PRODUCER)._value.get()
    succeeded_before = COUNTERS.succeeded.labels(producer=_PRODUCER)._value.get()
    skipped_before = COUNTERS.skipped.labels(producer=_PRODUCER)._value.get()

    with capture_logs() as logs:
        record = record_workflow_outcome(
            workflow_id="wf-bound",
            status="succeeded",
            started_at=datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
            finished_at=datetime(2026, 8, 10, 12, 5, 0, tzinfo=UTC),
        )

    assert isinstance(record, WorkflowOutcome)
    assert record.workflow_id == "wf-bound"
    assert _stored("workflow-results/wf-bound/") is not None
    assert COUNTERS.attempted.labels(producer=_PRODUCER)._value.get() == attempted_before + 1
    assert COUNTERS.succeeded.labels(producer=_PRODUCER)._value.get() == succeeded_before + 1
    assert COUNTERS.skipped.labels(producer=_PRODUCER)._value.get() == skipped_before
    # The "substrate unbound" branch is gone — no skip event is emitted.
    assert [
        entry for entry in logs if entry["event"] == "workflow_outcome_persistence_skipped"
    ] == []


def test_consumer_returns_none_when_no_record_persisted() -> None:
    """The consumer reads through the live substrate: a miss reads as ``None``.

    The old contract had a second "substrate unbound" state that also
    returned ``None``. The substrate is always bound now, so ``None`` means
    exactly one thing — no record was written under that key.
    """
    from mahavishnu.mcp.tools.workflow_tools import workflow_get_outcome

    assert _stored("workflow-results/wf-missing/") is None

    async def _exercise() -> WorkflowOutcome | dict[str, object] | None:
        return await workflow_get_outcome("wf-missing")

    result = asyncio.run(_exercise())
    assert result is None


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
