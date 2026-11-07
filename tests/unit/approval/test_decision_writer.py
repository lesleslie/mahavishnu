"""Verify record_approval_decision validates and persists ApprovalLog."""

from __future__ import annotations

import datetime as _dt
import json
from types import SimpleNamespace
from typing import Any

import msgspec
import pytest
from structlog.testing import capture_logs

from mahavishnu.core._producer_metrics import COUNTERS
from mahavishnu.core.approval.decision_writer import record_approval_decision
from mahavishnu.core.kv_store import kv_store
from mahavishnu.core.models.persistence import ApprovalLog

# Producer name used for Prometheus label cardinality (mirrors the writer).
_PRODUCER = "decision_writer"


def _stored(prefix: str) -> list[dict[str, Any]]:
    """Return every decoded payload the producer wrote under ``prefix``.

    The substrate store holds strings; the facade JSON-encodes structs on
    write. The lookup is by *prefix* because each decision is written
    under its own key inside the approval's namespace — the history is
    append-only, so a namespace can hold many records.
    """
    return [json.loads(value) for _key, value in kv_store.list_prefix(prefix)]


def test_record_approval_decision_persists_validated_struct() -> None:
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

    stored = _stored("approval-history/apr-001/")
    assert len(stored) == 1
    assert stored[0]["approval_id"] == "apr-001"
    assert stored[0]["action"] == "approved"
    assert stored[0]["actor"] == "alice"
    assert stored[0]["metadata"]["rationale"] == "All checks pass"


def test_record_approval_decision_rejects_invalid_decision() -> None:
    """Literal['approved','denied','requested'] enforced by the substrate."""
    with pytest.raises(msgspec.ValidationError):
        record_approval_decision(
            approval_id="apr-002",
            decision="invalid_value",
            rationale="Test",
            decided_by="alice",
        )
    assert _stored("approval-history/apr-002/") == []  # invalid never persisted


def test_record_approval_decision_passes_through_metadata() -> None:
    record = record_approval_decision(
        approval_id="apr-003",
        decision="denied",
        rationale="Workflow failed",
        decided_by="bob",
        metadata={"ticket": "OPS-42"},
    )
    assert record.metadata["ticket"] == "OPS-42"
    assert record.metadata["rationale"] == "Workflow failed"
    assert _stored("approval-history/apr-003/") != []


def test_record_approval_decision_counts_write_as_succeeded() -> None:
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
        record_approval_decision(
            approval_id="apr-counters",
            decision="approved",
            rationale="Counters land",
            decided_by="alice",
        )

    assert _stored("approval-history/apr-counters/") != []
    assert (
        COUNTERS.attempted.labels(producer=_PRODUCER)._value.get()
        == attempted_before + 1
    )
    assert (
        COUNTERS.succeeded.labels(producer=_PRODUCER)._value.get()
        == succeeded_before + 1
    )
    assert COUNTERS.skipped.labels(producer=_PRODUCER)._value.get() == skipped_before
    # The "substrate unbound" branch is gone — no skip event is emitted.
    assert [
        entry for entry in logs if entry["event"] == "approval_log_persistence_skipped"
    ] == []


def test_record_approval_decision_reports_a_failed_write_as_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write that did not land is reported as skipped, never as succeeded.

    The substrate swallows its own write failures so the producer keeps
    running. That is only safe if the producer *reports* the failure: an
    approval log that silently lost a decision is an audit gap, so the
    ``skipped`` counter and the ``approval_log_persistence_skipped``
    warning are what make it detectable.
    """
    import mahavishnu.core.approval.decision_writer as dw_mod

    monkeypatch.setattr(
        dw_mod, "substrate", SimpleNamespace(put=lambda *_a, **_k: False)
    )

    attempted_before = COUNTERS.attempted.labels(producer=_PRODUCER)._value.get()
    succeeded_before = COUNTERS.succeeded.labels(producer=_PRODUCER)._value.get()
    skipped_before = COUNTERS.skipped.labels(producer=_PRODUCER)._value.get()

    with capture_logs() as logs:
        record_approval_decision(
            approval_id="apr-write-fail",
            decision="approved",
            rationale="Write is going to fail",
            decided_by="alice",
        )

    assert (
        COUNTERS.attempted.labels(producer=_PRODUCER)._value.get()
        == attempted_before + 1
    )
    assert (
        COUNTERS.succeeded.labels(producer=_PRODUCER)._value.get() == succeeded_before
    )
    assert (
        COUNTERS.skipped.labels(producer=_PRODUCER)._value.get() == skipped_before + 1
    )
    skipped = [
        entry for entry in logs if entry["event"] == "approval_log_persistence_skipped"
    ]
    assert len(skipped) == 1, logs
    assert skipped[0]["extra"]["reason"] == "substrate_write_failed"
    assert _stored("approval-history/apr-write-fail/") == []


def test_record_approval_decision_emits_log_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision writer emits a structlog INFO event named approval_log_recorded.

    Oneiric configures structlog with its own handlers, so pytest's caplog
    (stdlib logging) does not capture its output. Patch the module-level
    logger.info directly to record the event the same way
    tests/unit/test_confidence_ceiling.py does.
    """
    import mahavishnu.core.approval.decision_writer as dw_mod

    captured: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        dw_mod.logger,
        "info",
        lambda event, **kw: captured.append((event, kw)),
    )

    record = record_approval_decision(
        approval_id="apr-004",
        decision="requested",
        rationale="Need operator review",
        decided_by="system",
    )

    matching = [event for event, _ in captured if event == "approval_log_recorded"]
    assert matching, (
        f"expected an approval_log_recorded structlog event; got: {captured}"
    )
    payload = captured[-1][1]
    extra = payload.get("extra", payload)
    assert extra.get("approval_id") == "apr-004"
    assert extra.get("action") == "requested"
    assert extra.get("actor") == "system"
    assert _stored("approval-history/apr-004/") != []
    assert record.approval_id == "apr-004"


def test_record_approval_decision_appends_rather_than_overwrites() -> None:
    """The approval history is append-only: a second decision is kept.

    The store holds one value per key, so a shared key would let the
    second decision overwrite the first. Each decision therefore gets its
    own key inside the approval's namespace, and the namespace listing
    returns both.
    """
    record_approval_decision(
        approval_id="apr-append",
        decision="requested",
        rationale="Awaiting review",
        decided_by="alice",
    )
    record_approval_decision(
        approval_id="apr-append",
        decision="approved",
        rationale="Approved after review",
        decided_by="bob",
    )

    stored = _stored("approval-history/apr-append/")
    assert len(stored) == 2
    assert {entry["action"] for entry in stored} == {"requested", "approved"}
    assert {entry["actor"] for entry in stored} == {"alice", "bob"}
