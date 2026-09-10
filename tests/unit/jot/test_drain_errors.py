"""Drain sub-plan error hierarchy (TD-D2 / sub-plan 3, Task 1).

All drain errors inherit from JotError so existing capture/read handlers
that catch JotError will not silently swallow them.
"""
from __future__ import annotations

import pytest

from mahavishnu.jot.errors import (
    JotDeferError,
    JotDispatchError,
    JotError,
    JotLogUnwritableError,
    JotRetryError,
    JotSurfaceThrottled,
    JotValidationError,
)


def test_drain_errors_inherit_from_jot_error() -> None:
    """All drain errors must be catchable as JotError so existing
    capture/read handlers don't silently swallow them.
    """
    for cls in (
        JotDispatchError,
        JotRetryError,
        JotDeferError,
        JotValidationError,
        JotLogUnwritableError,
        JotSurfaceThrottled,
    ):
        assert issubclass(cls, JotError)


def test_jot_dispatch_error_carries_error_id() -> None:
    """Tier-2 reconciler matches on .error_id to correlate with Sentry/Dhara."""
    exc = JotDispatchError(
        "trigger_workflow timed out",
        error_id="ERROR_JOT_TRIGGER_WORKFLOW_FAILED",
    )
    assert exc.error_id == "ERROR_JOT_TRIGGER_WORKFLOW_FAILED"
    assert "trigger_workflow timed out" in str(exc)
    assert "ERROR_JOT_TRIGGER_WORKFLOW_FAILED" in str(exc)


def test_jot_validation_error_carries_field() -> None:
    """Caller needs to know WHICH field failed validation."""
    exc = JotValidationError(
        "must be int",
        field="dispatch.attempt",
        error_id="ERROR_JOT_CTX_BAD_TYPE",
    )
    assert exc.field == "dispatch.attempt"
    assert exc.error_id == "ERROR_JOT_CTX_BAD_TYPE"


def test_jot_log_unwritable_error_carries_path() -> None:
    """Diagnostic needs to surface which path was unwritable."""
    exc = JotLogUnwritableError(
        "permission denied",
        path="/home/user/.mahavishnu/jot/log.jsonl",
    )
    assert exc.path == "/home/user/.mahavishnu/jot/log.jsonl"


def test_jot_retry_error_message_includes_current_state() -> None:
    """User-facing retry error must show why retry was rejected."""
    exc = JotRetryError("jot abc123 is not in FAILED state (current: in_flight)")
    assert "not in FAILED state" in str(exc)
    assert "abc123" in str(exc)
