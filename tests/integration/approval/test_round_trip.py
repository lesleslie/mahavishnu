"""Verify approval_log round-trips: write then read returns equal struct.

End-to-end check of the validate-on-write + validate-on-read contract between
``mahavishnu.core.approval.decision_writer.record_approval_decision`` (Task 1
producer) and ``mahavishnu.cli.approval_cli.list_approval_history`` (Task 2
consumer). The Dhara substrate is substituted with an in-memory dict so writes
from ``dhara.put`` are visible to ``dhara.list`` without a real Dhara binding.

Substrate-compat: ``dhara.put`` and ``dhara.list`` are runtime-attached
attributes on the local substrate install; both modules stamp them to ``None``
at import time if absent, so the fixture can safely ``monkeypatch.setattr(...)
with raising=False``.
"""

from __future__ import annotations

from typing import Any

from dhara.schema import ApprovalLog
import pytest

from mahavishnu.cli.approval_cli import list_approval_history
from mahavishnu.core.approval.decision_writer import record_approval_decision


@pytest.fixture
def shared_dhara_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[Any]]:
    """In-memory substrate shared between the producer's ``dhara.put`` and the consumer's ``dhara.list``.

    Keyed by ``approval-history/{approval_id}/`` to mirror the production path
    prefix used by both modules. ``fake_put`` appends to the list; ``fake_list``
    returns the accumulated records (filtered by ``status`` when provided).
    ``since`` is accepted but not enforced — no test in this module exercises
    the lower-bound, and adding fake-time semantics would cloud the contract.

    Both modules resolve their substrate bindings at call time via
    :func:`dhara_calltime` (producer) and ``getattr(dhara, ...)`` (consumer),
    so we patch the live ``dhara`` module (not the consumer/producer
    modules — neither imports ``dhara`` as a name).
    """
    import dhara

    storage: dict[str, list[Any]] = {}

    def fake_put(key: str, value: Any) -> None:
        storage.setdefault(key, []).append(value)

    def fake_list(
        key: str,
        *,
        since: str | None = None,
        status: str | None = None,
    ) -> list[Any]:
        records = list(storage.get(key, []))
        if status is not None:
            records = [r for r in records if getattr(r, "action", None) == status]
        return records

    monkeypatch.setattr(dhara, "put", fake_put, raising=False)
    monkeypatch.setattr(dhara, "list", fake_list, raising=False)
    return storage


def test_approval_log_round_trips_with_struct_equality(
    shared_dhara_storage: dict[str, list[Any]],
) -> None:
    """Producer writes; consumer reads; struct equality holds end-to-end."""
    written = record_approval_decision(
        approval_id="apr-roundtrip",
        decision="approved",
        rationale="All checks pass — round-trip integration test",
        decided_by="alice",
        metadata={"selected_option": 1, "ticket": "OPS-99"},
    )

    assert isinstance(written, ApprovalLog)
    # Producer persisted exactly one struct under the documented path prefix.
    assert shared_dhara_storage["approval-history/apr-roundtrip/"] == [written]

    results = list_approval_history(
        approval_id="apr-roundtrip",
        since=None,
        status=None,
        token="header.payload.signature",
    )

    assert len(results) == 1
    assert isinstance(results[0], ApprovalLog)
    # msgspec.Struct equality is structural: every field matches.
    assert results[0] == written
    # ...and the documented substrate fields round-trip verbatim.
    assert results[0].approval_id == "apr-roundtrip"
    assert results[0].action == "approved"
    assert results[0].actor == "alice"
    assert results[0].metadata["selected_option"] == 1
    assert results[0].metadata["ticket"] == "OPS-99"
    assert results[0].metadata["rationale"] == ("All checks pass — round-trip integration test")


def test_approval_log_round_trip_with_status_filter(
    shared_dhara_storage: dict[str, list[Any]],
) -> None:
    """``status`` filter narrows the read-back to matching action values."""
    record_approval_decision(
        approval_id="apr-filter",
        decision="approved",
        rationale="First decision",
        decided_by="alice",
    )
    record_approval_decision(
        approval_id="apr-filter",
        decision="denied",
        rationale="Second decision",
        decided_by="bob",
    )

    approved = list_approval_history(
        approval_id="apr-filter",
        since=None,
        status="approved",
        token="header.payload.signature",
    )
    denied = list_approval_history(
        approval_id="apr-filter",
        since=None,
        status="denied",
        token="header.payload.signature",
    )
    all_records = list_approval_history(
        approval_id="apr-filter",
        since=None,
        status=None,
        token="header.payload.signature",
    )

    assert len(approved) == 1
    assert approved[0].action == "approved"
    assert approved[0].actor == "alice"
    assert len(denied) == 1
    assert denied[0].action == "denied"
    assert denied[0].actor == "bob"
    # Status=None returns every record; status="approved/denied" partitions them.
    assert len(all_records) == 2
    assert {r.action for r in all_records} == {"approved", "denied"}


def test_approval_log_round_trip_isolates_per_approval_id(
    shared_dhara_storage: dict[str, list[Any]],
) -> None:
    """Each ``approval_id`` has its own substrate prefix — read-back is scoped to the requested ID."""
    record_approval_decision(
        approval_id="apr-100",
        decision="approved",
        rationale="One",
        decided_by="alice",
    )
    record_approval_decision(
        approval_id="apr-200",
        decision="approved",
        rationale="Two",
        decided_by="alice",
    )

    first = list_approval_history(
        approval_id="apr-100", since=None, status=None, token="header.payload.signature"
    )
    second = list_approval_history(
        approval_id="apr-200", since=None, status=None, token="header.payload.signature"
    )

    assert len(first) == 1
    assert first[0].approval_id == "apr-100"
    assert first[0].metadata["rationale"] == "One"
    assert len(second) == 1
    assert second[0].approval_id == "apr-200"
    assert second[0].metadata["rationale"] == "Two"
    # Cross-check the substrate-level invariant: two distinct keys exist.
    assert set(shared_dhara_storage.keys()) == {
        "approval-history/apr-100/",
        "approval-history/apr-200/",
    }


def test_approval_log_round_trip_default_metadata_round_trips(
    shared_dhara_storage: dict[str, list[Any]],
) -> None:
    """When the caller omits ``metadata``, the producer defaults to an empty dict and the round-trip preserves it."""
    written = record_approval_decision(
        approval_id="apr-default-meta",
        decision="requested",
        rationale="Needs operator review",
        decided_by="system",
    )

    assert written.metadata == {"rationale": "Needs operator review"}

    results = list_approval_history(
        approval_id="apr-default-meta",
        since=None,
        status=None,
        token="header.payload.signature",
    )

    assert len(results) == 1
    assert results[0] == written
    assert results[0].metadata == {"rationale": "Needs operator review"}
