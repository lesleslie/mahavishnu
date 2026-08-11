"""Verify list_approval_history reads Dhara payloads and returns typed ApprovalLog structs."""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any
from unittest.mock import MagicMock

from dhara.schema import ApprovalLog
import pytest

from mahavishnu.cli.approval_cli import list_approval_history


@pytest.fixture
def substrate_list(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub dhara.list after module import so the substrate-compat guard sees it."""
    import mahavishnu.cli.approval_cli as cli

    mock_list = MagicMock(return_value=[])
    monkeypatch.setattr(cli.dhara, "list", mock_list, raising=False)
    return mock_list


def _make_payload(
    approval_id: str,
    *,
    action: str = "approved",
    actor: str = "alice",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "approval_id": approval_id,
        "action": action,
        "actor": actor,
        "at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
        "metadata": metadata or {"rationale": f"reason for {approval_id}"},
    }


def test_list_approval_history_returns_validated_structs(
    substrate_list: MagicMock,
) -> None:
    substrate_list.return_value = [
        _make_payload("apr-001", action="approved", actor="alice"),
        _make_payload("apr-002", action="denied", actor="bob"),
    ]

    results = list_approval_history(
        approval_id="apr-stream",
        since=None,
        status=None,
    )

    assert isinstance(results, list)
    assert len(results) == 2
    for record in results:
        assert isinstance(record, ApprovalLog)
    assert [r.approval_id for r in results] == ["apr-001", "apr-002"]
    assert results[0].action == "approved"
    assert results[0].actor == "alice"
    assert results[1].action == "denied"
    assert results[1].actor == "bob"

    substrate_list.assert_called_once_with(
        "approval-history/apr-stream/",
        since=None,
        status=None,
    )


def test_list_approval_history_passes_since_and_status(
    substrate_list: MagicMock,
) -> None:
    substrate_list.return_value = [_make_payload("apr-003")]

    list_approval_history(
        approval_id="apr-stream",
        since="2026-08-01",
        status="approved",
    )

    substrate_list.assert_called_once_with(
        "approval-history/apr-stream/",
        since="2026-08-01",
        status="approved",
    )


def test_list_approval_history_returns_empty_when_dhara_unbound(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the local substrate install does not expose dhara.list, return [] and warn."""
    import mahavishnu.cli.approval_cli as cli

    # Force the substrate-unbound path even if a prior test monkeypatched it.
    monkeypatch.setattr(cli.dhara, "list", None, raising=False)

    with caplog.at_level(logging.WARNING, logger="mahavishnu.cli.approval_cli"):
        results = list_approval_history(
            approval_id="apr-stream",
            since=None,
            status=None,
        )

    assert results == []
    skip_records = [rec for rec in caplog.records if "approval_list_skipped" in rec.message]
    assert len(skip_records) == 1, [rec.message for rec in caplog.records]
    rec = skip_records[0]
    assert rec.levelno == logging.WARNING
    # Structured extras: Oneiric renders `extra={...}` into the formatted
    # message rather than attaching attributes. Parse for the expected keys
    # and values to confirm the structured payload is correct (and that no
    # exception text leaked into the WARNING per observability rule).
    msg = rec.message
    assert "'approval_id': 'apr-stream'" in msg, msg
    assert "'reason': 'dhara.list_unbound'" in msg, msg
    # Sanity: the WARNING must NOT carry exception text in the extras payload.
    assert "Traceback" not in msg
    assert "SchemaValidationError" not in msg.split("extra=", 1)[-1]


def test_list_approval_history_skips_invalid_payloads(
    substrate_list: MagicMock,
) -> None:
    """One valid + one invalid payload -> returns only the valid struct (partial-failure resilience)."""
    substrate_list.return_value = [
        _make_payload("apr-good", action="approved", actor="alice"),
        {
            "approval_id": "apr-bad",
            "action": "not_a_real_action",  # fails Literal validation
            "actor": "carol",
            "at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
            "metadata": {},
        },
    ]

    results = list_approval_history(
        approval_id="apr-stream",
        since=None,
        status=None,
    )

    assert len(results) == 1
    assert isinstance(results[0], ApprovalLog)
    assert results[0].approval_id == "apr-good"


def test_list_entry_skipped_log_carries_bound_exception_type(
    substrate_list: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`approval_list_entry_skipped` log carries the bound exc type, not a constant string.

    Regression guard for the constant-string bug:
    `type(SchemaValidationError).__name__` evaluates to the literal string
    "SchemaValidationError" because the surrounding `except` already
    narrowed the type. The fix binds the exception as ``exc`` and logs
    ``type(exc).__name__``. We trigger a real `SchemaValidationError`
    via an invalid `action` Literal (same shape as
    `test_list_approval_history_skips_invalid_payloads`) and assert the
    structured log carries the bound-exception class name.
    """
    substrate_list.return_value = [
        {
            "approval_id": "apr-bad",
            "action": "not_a_real_action",  # fails Literal validation
            "actor": "carol",
            "at": datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC),
            "metadata": {},
        },
    ]

    with caplog.at_level(logging.WARNING, logger="mahavishnu.cli.approval_cli"):
        results = list_approval_history(
            approval_id="apr-stream",
            since=None,
            status=None,
        )

    # Partial-failure resilience still holds.
    assert results == []

    # Find the structured skip log. Use substring match (the existing
    # `_list_skipped` test at line 109 follows the same pattern) so we
    # don't trip over trailing ANSI escapes or formatter padding.
    skip_records = [
        rec
        for rec in caplog.records
        if "approval_list_entry_skipped" in rec.message
    ]
    assert len(skip_records) == 1, [rec.message for rec in caplog.records]
    rec = skip_records[0]

    # Oneiric renders `extra={...}` into the formatted message; parse for
    # the `reason` field and assert it's the bound-exception class name.
    msg = rec.message
    assert "'reason': 'SchemaValidationError'" in msg, (
        f"Expected bound-exception type name, got: {msg!r}"
    )
    # No exception text leaked into the structured payload.
    assert "Traceback" not in msg
