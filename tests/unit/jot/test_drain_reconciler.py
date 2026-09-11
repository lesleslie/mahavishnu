"""Tasks 6, 7, 10: reconciler + retry orchestration.

Tests use real fold + actual JSONL log via tmp_path, not mocks. Mocks are
used only for the substrate calls (trigger_workflow, get_workflow_status)
which cross process boundaries.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from mahavishnu.jot.drain import (
    DispatchState,
    RECONCILER_TIMEOUT_MS,
    STATUS_CALL_TIMEOUT_SECONDS,
    TERMINAL_STATUSES,
    _auto_retry_after,
    _reconcile_if_in_flight,
)
from mahavishnu.jot.events import serialize
from mahavishnu.jot.fold import JotSummary as RealJotSummary


@pytest.fixture
def isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "log.jsonl"
    monkeypatch.setattr("mahavishnu.jot.drain.log_path", lambda: p)
    monkeypatch.setattr("mahavishnu.jot.paths.log_path", lambda: p)
    return p


def _capture_event(op: str, status: str, *, text: str = "x", workflow_id: str | None = None,
                  attempt: int | None = None, ms: int = 0,
                  dispatch_started_at_ms: int | None = None) -> dict[str, object]:
    from mahavishnu.jot.events import HLC, JotEvent
    ctx: dict[str, object] = {}
    if workflow_id is not None:
        ctx["workflow_id"] = workflow_id
    if attempt is not None:
        ctx["attempt"] = attempt
    if dispatch_started_at_ms is not None:
        ctx["started_at_ms"] = dispatch_started_at_ms
    return {
        "id": "", "op": op, "text": text, "ctx": ctx,
        "hlc": {"wall_ms": ms, "ctr": 0, "node": "n1"},
        "node": "n1",
        "created_ms": ms,
    }


def _write_log(path: Path, *events: dict) -> None:
    """Write a JSONL log containing the given events."""
    from mahavishnu.jot.events import HLC, JotEvent
    with path.open("w") as f:
        for ev in events:
            event = JotEvent(
                id=ev.get("id", ""),
                op=ev["op"],  # type: ignore[arg-type]
                text=ev.get("text", ""),
                ctx=ev.get("ctx", {}),
                hlc=HLC(**ev["hlc"]),  # type: ignore[arg-type]
                created_ms=ev.get("created_ms", 0),
            )
            f.write(serialize(event))


def _make_summary(**overrides) -> RealJotSummary:
    """Build a JotSummary directly (no log needed for reconciler unit tests).

    dispatch_started_at_ms defaults to now() so the Tier-2 timeout gate
    doesn't fire — tests that want the timeout gate can override to 0.
    """
    from time import time
    defaults = dict(
        id="e1", short_id="123456", text="hello",
        status="open", last_modified_ms=0,
        dispatch_state=DispatchState.IN_FLIGHT,
        dispatch_workflow_id="wf-1",
        current_attempt=1,
        dispatch_started_at_ms=int(time() * 1000),  # recent
        deferred_until=None, deleted=False,
    )
    defaults.update(overrides)
    return RealJotSummary(**defaults)  # type: ignore[arg-type]


# ===== Task 7: _reconcile_if_in_flight =====


@pytest.mark.asyncio
async def test_reconcile_skips_non_in_flight(isolated_log: Path) -> None:
    s = _make_summary(dispatch_state=DispatchState.SUCCEEDED)
    await _reconcile_if_in_flight(s)
    assert isolated_log.exists() is False


@pytest.mark.asyncio
async def test_reconcile_warns_when_no_workflow_id(isolated_log: Path) -> None:
    s = _make_summary(dispatch_workflow_id=None)
    await _reconcile_if_in_flight(s)
    assert isolated_log.exists() is False


@pytest.mark.asyncio
async def test_reconcile_tier2_timeout_attempt_one_preserves_budget(
    isolated_log: Path,
) -> None:
    """Timeout on attempt 1 → dispatch_failed + auto-retry scheduled (locked policy)."""
    s = _make_summary(current_attempt=1, dispatch_started_at_ms=0)
    auto_retry_called = []

    async def fake_auto_retry(handle: str, backoff_s: int) -> None:
        auto_retry_called.append((handle, backoff_s))

    with patch("mahavishnu.jot.drain._auto_retry_after", fake_auto_retry), \
         patch("mahavishnu.jot.drain._now_ms", return_value=RECONCILER_TIMEOUT_MS + 1000):
        await _reconcile_if_in_flight(s)
    parsed = json.loads(isolated_log.read_text().strip().split("\n")[0])
    assert parsed["op"] == "dispatch_failed"
    assert parsed["ctx"]["retry_budget_exhausted"] is False
    assert len(auto_retry_called) == 1


@pytest.mark.asyncio
async def test_reconcile_tier2_timeout_attempt_two_exhausts_budget(
    isolated_log: Path,
) -> None:
    """Timeout on attempt 2 → dispatch_failed + retry_budget_exhausted=true."""
    s = _make_summary(current_attempt=2, dispatch_started_at_ms=0)
    auto_retry_called = []

    async def fake_auto_retry(handle: str, backoff_s: int) -> None:
        auto_retry_called.append(1)

    with patch("mahavishnu.jot.drain._auto_retry_after", fake_auto_retry), \
         patch("mahavishnu.jot.drain._now_ms", return_value=RECONCILER_TIMEOUT_MS + 1000):
        await _reconcile_if_in_flight(s)
    parsed = json.loads(isolated_log.read_text().strip().split("\n")[0])
    assert parsed["ctx"]["retry_budget_exhausted"] is True
    assert auto_retry_called == []


@pytest.mark.asyncio
async def test_reconcile_skips_timeout_check_when_started_at_none(
    isolated_log: Path,
) -> None:
    """Legacy entries with started_at_ms=None fall through to status check."""
    s = _make_summary(dispatch_started_at_ms=None)

    async def fake_status(workflow_id: str) -> dict[str, object]:
        return {"status": "COMPLETED"}

    with patch("mahavishnu.jot.drain._mcp_get_workflow_status", fake_status):
        await _reconcile_if_in_flight(s)
    parsed = json.loads(isolated_log.read_text().strip().split("\n")[0])
    assert parsed["op"] == "dispatch_done"


@pytest.mark.asyncio
async def test_reconcile_substrate_timeout_returns_silently(isolated_log: Path) -> None:
    s = _make_summary()

    async def fake_status(workflow_id: str) -> dict[str, object]:
        raise asyncio.TimeoutError()

    with patch("mahavishnu.jot.drain._mcp_get_workflow_status", fake_status):
        await _reconcile_if_in_flight(s)
    assert isolated_log.exists() is False


@pytest.mark.asyncio
async def test_reconcile_writes_dispatch_done_on_completed(isolated_log: Path) -> None:
    s = _make_summary()

    async def fake_status(workflow_id: str) -> dict[str, object]:
        return {"status": "COMPLETED", "results_count": 5}

    with patch("mahavishnu.jot.drain._mcp_get_workflow_status", fake_status):
        await _reconcile_if_in_flight(s)
    parsed = json.loads(isolated_log.read_text().strip().split("\n")[0])
    assert parsed["op"] == "dispatch_done"
    assert parsed["ctx"]["summary"] == "ok"


@pytest.mark.asyncio
async def test_reconcile_writes_dispatch_failed_with_budget_exhausted_false_attempt_one(
    isolated_log: Path,
) -> None:
    s = _make_summary(current_attempt=1)

    async def fake_status(workflow_id: str) -> dict[str, object]:
        return {"status": "FAILED"}

    async def fake_auto_retry(handle: str, backoff_s: int) -> None:
        pass

    with patch("mahavishnu.jot.drain._mcp_get_workflow_status", fake_status), \
         patch("mahavishnu.jot.drain._auto_retry_after", fake_auto_retry):
        await _reconcile_if_in_flight(s)
    parsed = json.loads(isolated_log.read_text().strip().split("\n")[0])
    assert parsed["op"] == "dispatch_failed"
    assert parsed["ctx"]["retry_budget_exhausted"] is False


@pytest.mark.asyncio
async def test_reconcile_writes_dispatch_failed_with_budget_exhausted_true_attempt_two(
    isolated_log: Path,
) -> None:
    s = _make_summary(current_attempt=2)

    async def fake_status(workflow_id: str) -> dict[str, object]:
        return {"status": "FAILED"}

    async def fake_auto_retry(handle: str, backoff_s: int) -> None:
        pytest.fail("auto_retry must NOT be called when budget exhausted")

    with patch("mahavishnu.jot.drain._mcp_get_workflow_status", fake_status), \
         patch("mahavishnu.jot.drain._auto_retry_after", fake_auto_retry):
        await _reconcile_if_in_flight(s)
    parsed = json.loads(isolated_log.read_text().strip().split("\n")[0])
    assert parsed["ctx"]["retry_budget_exhausted"] is True


@pytest.mark.asyncio
async def test_reconcile_non_terminal_status_noop(isolated_log: Path) -> None:
    s = _make_summary()

    async def fake_status(workflow_id: str) -> dict[str, object]:
        return {"status": "RUNNING"}

    with patch("mahavishnu.jot.drain._mcp_get_workflow_status", fake_status):
        await _reconcile_if_in_flight(s)
    assert isolated_log.exists() is False


@pytest.mark.asyncio
async def test_reconcile_catches_validation_error_propagation(
    isolated_log: Path,
) -> None:
    """JotValidationError on write must NOT propagate (fold continues)."""
    s = _make_summary(current_attempt=2)

    async def fake_status(workflow_id: str) -> dict[str, object]:
        return {"status": "FAILED"}

    # Force the append to raise JotValidationError (e.g., bad type for retry_budget_exhausted)
    from mahavishnu.jot.drain import _append_event as real_append
    from mahavishnu.jot.errors import JotValidationError

    async def broken_append(op, ctx):
        raise JotValidationError("test forced", field="ctx.retry_budget_exhausted")

    with patch("mahavishnu.jot.drain._mcp_get_workflow_status", fake_status), \
         patch("mahavishnu.jot.drain._append_event", broken_append):
        # Must not raise
        await _reconcile_if_in_flight(s)


@pytest.mark.asyncio
async def test_reconcile_terminal_statuses_include_cancelled_and_timeout(
    isolated_log: Path,
) -> None:
    """CANCELLED + TIMEOUT are terminal; reconciliation emits dispatch_failed."""
    for term in ("CANCELLED", "TIMEOUT"):
        s = _make_summary()

        async def fake_status(workflow_id: str, _t: str = term) -> dict[str, object]:
            return {"status": _t}

        async def fake_auto_retry(handle: str, backoff_s: int) -> None:
            pass

        with patch("mahavishnu.jot.drain._mcp_get_workflow_status", fake_status), \
             patch("mahavishnu.jot.drain._auto_retry_after", fake_auto_retry):
            await _reconcile_if_in_flight(s)
        lines = isolated_log.read_text().strip().split("\n")
        last = json.loads(lines[-1])
        assert last["op"] == "dispatch_failed"
        assert term in last["ctx"]["error"]
        # Reset for next iteration
        isolated_log.write_text("")


# ===== Task 6: _auto_retry_after =====


@pytest.mark.asyncio
async def test_auto_retry_skips_when_already_succeeded(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Race: manual retry succeeded before backoff completed → auto-retry exits."""
    _write_log(
        isolated_log,
        _capture_event(
            "capture", "ok", text="x", ms=0,
        ),
        _capture_event(
            "dispatch", "ok", workflow_id="wf-1", attempt=1, ms=1000,
            dispatch_started_at_ms=1000,
        ),
        _capture_event(
            "dispatch_done", "ok", workflow_id="wf-1", ms=2000,
        ),
    )
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    triggered = []
    async def fake_trigger(*a, **kw):
        triggered.append(1)
        return {"workflow_id": "wf-new"}
    monkeypatch.setattr("mahavishnu.jot.drain._mcp_trigger_workflow", fake_trigger)

    await _auto_retry_after("x", backoff_s=0)
    assert triggered == []  # no retry fired (state is SUCCEEDED, not FAILED)


@pytest.mark.asyncio
async def test_auto_retry_appends_dispatch_event_when_trigger_succeeds(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful trigger writes dispatch event with attempt=current+1."""
    _write_log(
        isolated_log,
        _capture_event("capture", "ok", text="hello", ms=0),
        _capture_event("dispatch", "ok", workflow_id="wf-old", attempt=1, ms=1000,
                       dispatch_started_at_ms=1000),
        _capture_event(
            "dispatch_failed", "ok", workflow_id="wf-old", attempt=1,
            ms=2000,
        ),
    )
    # Patch ctx to include retry_budget_exhausted=False (so state is FAILED-eligible)
    # Actually dispatch_failed defaults to retry_budget_exhausted=False via defensive parse.
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    async def fake_trigger(adapter, task_type, params):
        return {"workflow_id": "wf-new"}

    monkeypatch.setattr("mahavishnu.jot.drain._mcp_trigger_workflow", fake_trigger)
    await _auto_retry_after("x", backoff_s=0)

    lines = isolated_log.read_text().strip().split("\n")
    # 3 initial events + 1 new dispatch = 4 lines
    assert len(lines) == 4
    parsed = json.loads(lines[3])
    assert parsed["op"] == "dispatch"
    assert parsed["ctx"]["workflow_id"] == "wf-new"
    assert parsed["ctx"]["attempt"] == 2
    assert parsed["ctx"]["triggered_by"] == "auto"


@pytest.mark.asyncio
async def test_auto_retry_writes_failed_event_when_trigger_raises(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mahavishnu.jot.errors import JotDispatchError
    _write_log(
        isolated_log,
        _capture_event("capture", "ok", text="x", ms=0),
        _capture_event("dispatch", "ok", workflow_id="wf-old", attempt=1, ms=1000,
                       dispatch_started_at_ms=1000),
        _capture_event("dispatch_failed", "ok", workflow_id="wf-old", attempt=1, ms=2000),
    )
    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    async def fake_trigger(adapter, task_type, params):
        raise JotDispatchError("auth failed", error_id="ERROR_JOT_AUTH")

    monkeypatch.setattr("mahavishnu.jot.drain._mcp_trigger_workflow", fake_trigger)
    await _auto_retry_after("x", backoff_s=0)

    parsed = json.loads(isolated_log.read_text().strip().split("\n")[-1])
    assert parsed["op"] == "dispatch_failed"
    assert parsed["ctx"]["retry_budget_exhausted"] is True


@pytest.mark.asyncio
async def test_auto_retry_does_nothing_when_attempt_exceeds_max(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """current_attempt=2 (the last) → no retry fires."""
    _write_log(
        isolated_log,
        _capture_event("capture", "ok", text="x", ms=0),
        _capture_event("dispatch", "ok", workflow_id="wf-old", attempt=2, ms=1000,
                       dispatch_started_at_ms=1000),
        _capture_event("dispatch_failed", "ok", workflow_id="wf-old", attempt=2, ms=2000),
    )
    monkeypatch.setattr("asyncio.sleep", AsyncMock())
    triggered = []
    async def fake_trigger(*a, **kw):
        triggered.append(1)
        return {"workflow_id": "wf"}
    monkeypatch.setattr("mahavishnu.jot.drain._mcp_trigger_workflow", fake_trigger)

    await _auto_retry_after("x", backoff_s=0)
    assert triggered == []
