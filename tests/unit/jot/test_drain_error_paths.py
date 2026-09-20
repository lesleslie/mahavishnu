"""Coverage lift for drain.py error / edge paths.

Targets the ~60 lines that the §7.6 coverage gate flagged at 85.47%
on 2026-09-19. Each test maps to a specific missed range listed in
the re-review header of `docs/superpowers/plans/2026-09-10-jot-drain.md`:

- _validate_ctx unknown-op raise (line 248)
- _mcp_trigger_workflow exception path (392-406)
- _mcp_get_workflow_status exception path (411-420)
- _auto_retry_after log-unreadable (439-445)
- _auto_retry_after state-not-FAILED return (447-448)
- _auto_retry_after budget-exhausted return (450-451)
- _auto_retry_after log-write-failed on budget-exhausted (474-479)
- _auto_retry_after event-append-failed (494-501)
- _reconcile_if_in_flight timeout log-write-failed (556-562)
- _reconcile_if_in_flight status-fetch exception (577-585)
- _background_reconciler_loop fold/per-jot exceptions (640-664)
- drain_plan log-unreadable path (748-750)
- _propose_action state branches (787, 790, 793, 796-797)
- dispatch_jot already-IN_FLIGHT/SUCCEEDED/done paths (827-841)
- retry_dispatch not-FAILED-state path (886-889)
- defer_jot with reason (915-917)
- _semantic_score degraded paths (1000-1012)
- surface_relevant log-unreadable path (1080-1090)
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.jot.drain import (
    MAX_AUTO_ATTEMPTS,
    DispatchState,
    _auto_retry_after,
    _background_reconciler_loop,
    _mcp_get_workflow_status,
    _mcp_trigger_workflow,
    _propose_action,
    _reconcile_if_in_flight,
    _semantic_score,
    _validate_ctx,
    defer_jot,
    dispatch_jot,
    drain_plan,
    retry_dispatch,
    surface_relevant,
)
from mahavishnu.jot.errors import (
    JotDispatchError,
    JotLogUnwritableError,
    JotRetryError,
    JotValidationError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect log_path() to a tmp file for the duration of one test."""
    p = tmp_path / "log.jsonl"
    monkeypatch.setattr("mahavishnu.jot.drain.log_path", lambda: p)
    monkeypatch.setattr("mahavishnu.jot.paths.log_path", lambda: p)
    return p


def _ev(
    *,
    op: str,
    jot_id: str = "e1",
    text: str = "hello",
    status: str = "active",
    dispatch_state: DispatchState | None = None,
    current_attempt: int | None = None,
    workflow_id: str | None = None,
    ms: int = 0,
    reason: str | None = None,
    until: int | None = None,
) -> dict[str, object]:
    """Build a single event dict suitable for JSONL append."""
    ctx: dict[str, object] = {}
    if workflow_id is not None:
        ctx["workflow_id"] = workflow_id
    if current_attempt is not None:
        ctx["attempt"] = current_attempt
    if reason is not None:
        ctx["reason"] = reason
    if until is not None:
        ctx["until"] = until
    return {
        "id": jot_id,
        "op": op,
        "text": text,
        "ctx": ctx,
        "hlc": {"wall_ms": ms, "ctr": 0, "node": "n1"},
        "node": "n1",
        "created_ms": ms,
    }


def _write(path: Path, *events: dict[str, object]) -> None:
    """Append events to the JSONL log."""
    with path.open("a") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


# ---------------------------------------------------------------------------
# _validate_ctx — line 248
# ---------------------------------------------------------------------------


def test_validate_ctx_unknown_op_raises_jot_validation_error() -> None:
    """Line 248: unknown op must raise JotValidationError, not silently pass."""
    with pytest.raises(JotValidationError) as exc_info:
        _validate_ctx("not_a_real_op", {"x": 1})
    assert "unknown op" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _mcp_trigger_workflow — lines 392-406
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_trigger_workflow_wraps_substrate_exception_as_jot_dispatch_error() -> None:
    """Lines 392-406: trigger_workflow raising → JotDispatchError with cause."""
    fake_trigger = AsyncMock(side_effect=RuntimeError("substrate blew up"))
    with patch("mahavishnu.mcp.server_core.trigger_workflow", fake_trigger, create=True):
        with pytest.raises(JotDispatchError) as exc_info:
            await _mcp_trigger_workflow("prefect", "jot_dispatch", {"prompt": "x"})
    assert "RuntimeError" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------------
# _mcp_get_workflow_status — lines 411-420
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_get_workflow_status_wraps_substrate_exception_as_jot_dispatch_error() -> None:
    """Lines 411-420: get_workflow_status raising → JotDispatchError with cause."""
    fake_status = AsyncMock(side_effect=RuntimeError("status blew up"))
    with patch("mahavishnu.mcp.server_core.get_workflow_status", fake_status, create=True):
        with pytest.raises(JotDispatchError) as exc_info:
            await _mcp_get_workflow_status("wf-123")
    assert "RuntimeError" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------------
# _auto_retry_after — log-unreadable, state-not-FAILED, budget-exhausted,
# log-write-failed, event-append-failed (lines 439-501)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_retry_after_log_unreadable_returns_silently(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 439-445: parse_events failure → log + return, no retry fired."""
    # Make log_path point at a directory so parse_events blows up
    monkeypatch.setattr(
        "mahavishnu.jot.fold.parse_events",
        MagicMock(side_effect=OSError("permission denied")),
    )
    fired = AsyncMock()
    with patch("mahavishnu.mcp.server_core.trigger_workflow", fired, create=True):
        await _auto_retry_after("e1", backoff_s=0)
    fired.assert_not_called()


@pytest.mark.asyncio
async def test_auto_retry_after_state_no_longer_failed_returns(
    isolated_log: Path,
) -> None:
    """Lines 447-448: state changed during sleep → auto-retry exits."""
    _write(
        isolated_log,
        _ev(op="capture", text="x", ms=0),
        # dispatch event but current_attempt high; on refold state != FAILED
        _ev(
            op="dispatch", text="x", ms=10, workflow_id="wf-1",
            current_attempt=1,
        ),
    )
    # Manually mark this as DISPATCHED (not FAILED) by setting state via
    # the in-progress event instead of dispatch_failed.
    fired = AsyncMock()
    with patch("mahavishnu.mcp.server_core.trigger_workflow", fired, create=True):
        await _auto_retry_after("e1", backoff_s=0)
    fired.assert_not_called()


@pytest.mark.asyncio
async def test_auto_retry_after_budget_exhausted_returns(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 450-451: current_attempt already at MAX → exit before retry."""
    _write(
        isolated_log,
        _ev(op="capture", text="x", ms=0),
        _ev(
            op="dispatch_failed", text="x", ms=10, workflow_id="wf-1",
            current_attempt=MAX_AUTO_ATTEMPTS,  # already at budget cap
        ),
    )
    fired = AsyncMock()
    with patch("mahavishnu.mcp.server_core.trigger_workflow", fired, create=True):
        await _auto_retry_after("e1", backoff_s=0)
    fired.assert_not_called()


@pytest.mark.asyncio
async def test_auto_retry_after_log_write_failed_on_budget_exhausted(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 474-479: append_event raises on the budget-exhausted branch.

    Note: this path is normally unreachable from well-formed log events
    (FAILED state implies current_attempt >= MAX, which the guard at
    line 450 catches first). We force the dispatch path by mocking
    resolve_handle to return a synthetic FAILED state with attempt=1.
    """
    from mahavishnu.jot.fold import JotSummary as _JS

    synthetic = _JS(
        id="e1",
        short_id="123456",
        text="hello",
        status="open",
        last_modified_ms=0,
        dispatch_state=DispatchState.FAILED,
        current_attempt=1,
    )
    fake_states = type("R", (), {"states": [synthetic]})()
    monkeypatch.setattr("mahavishnu.jot.handle.resolve_handle", lambda *a, **kw: synthetic)
    monkeypatch.setattr("mahavishnu.jot.fold.build_states", lambda *a, **kw: fake_states)
    fake_trigger = AsyncMock(side_effect=JotDispatchError("substrate down", error_id="E1"))
    failing_append = AsyncMock(side_effect=JotLogUnwritableError("disk full"))
    monkeypatch.setattr("mahavishnu.jot.drain._append_event", failing_append)
    with patch("mahavishnu.mcp.server_core.trigger_workflow", fake_trigger, create=True):
        # Should not raise.
        await _auto_retry_after("e1", backoff_s=0)
    failing_append.assert_called()


@pytest.mark.asyncio
async def test_auto_retry_after_event_append_failed_logs_and_returns(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 494-501: dispatch event append raises → log + return.

    Same forced-state trick as the budget-exhausted test above.
    """
    from mahavishnu.jot.fold import JotSummary as _JS

    synthetic = _JS(
        id="e1",
        short_id="123456",
        text="hello",
        status="open",
        last_modified_ms=0,
        dispatch_state=DispatchState.FAILED,
        current_attempt=1,
    )
    fake_states = type("R", (), {"states": [synthetic]})()
    monkeypatch.setattr("mahavishnu.jot.handle.resolve_handle", lambda *a, **kw: synthetic)
    monkeypatch.setattr("mahavishnu.jot.fold.build_states", lambda *a, **kw: fake_states)
    fake_trigger = AsyncMock(return_value={"workflow_id": "wf-new", "status": "PENDING"})
    failing_append = AsyncMock(side_effect=JotLogUnwritableError("append failed mid-flow"))
    monkeypatch.setattr("mahavishnu.jot.drain._append_event", failing_append)
    with patch("mahavishnu.mcp.server_core.trigger_workflow", fake_trigger, create=True):
        # Must not raise.
        await _auto_retry_after("e1", backoff_s=0)
    fake_trigger.assert_called()


# ---------------------------------------------------------------------------
# _reconcile_if_in_flight — timeout log-write-failed, status-fetch exception
# (lines 556-585)
# ---------------------------------------------------------------------------


def _seed_in_flight(
    isolated_log: Path,
    *,
    workflow_id: str = "wf-1",
    started_at_ms: int = 1,
    current_attempt: int = 1,
) -> None:
    """Seed a JSONL log with a capture + in-flight dispatch."""
    from mahavishnu.jot.drain import log_path as _lp  # noqa: F401

    _write(
        isolated_log,
        _ev(op="capture", text="hello world", ms=0),
        _ev(
            op="dispatch", text="hello world", ms=10,
            workflow_id=workflow_id,
            current_attempt=current_attempt,
        ),
    )


def _make_summary(**overrides: Any) -> Any:
    """Build an in-flight JotSummary directly for reconcile tests."""
    from mahavishnu.jot.fold import JotSummary as _JS

    defaults: dict[str, Any] = dict(
        id="e1",
        short_id="123456",
        text="hello",
        status="open",
        last_modified_ms=0,
        dispatch_state=DispatchState.IN_FLIGHT,
        dispatch_workflow_id="wf-1",
        current_attempt=1,
        dispatch_started_at_ms=1,
    )
    defaults.update(overrides)
    return _JS(**defaults)


@pytest.mark.asyncio
async def test_reconcile_timeout_log_write_failed(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 556-562: append_event raises on timeout path → log, no raise."""
    from mahavishnu.jot.drain import RECONCILER_TIMEOUT_MS

    jot = _make_summary(dispatch_started_at_ms=0)
    monkeypatch.setattr(
        "mahavishnu.jot.drain._now_ms", lambda: RECONCILER_TIMEOUT_MS + 10_000
    )
    failing_append = AsyncMock(side_effect=JotLogUnwritableError("disk full"))
    monkeypatch.setattr("mahavishnu.jot.drain._append_event", failing_append)
    # Patch _auto_retry_after so it doesn't actually run on the success path
    fake_auto_retry = AsyncMock()
    monkeypatch.setattr("mahavishnu.jot.drain._auto_retry_after", fake_auto_retry)
    # Should not raise.
    await _reconcile_if_in_flight(jot)
    failing_append.assert_called()


@pytest.mark.asyncio
async def test_reconcile_status_fetch_raises_logs_and_returns(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 577-585: get_workflow_status raises non-Timeout → log + return."""
    import time as _time

    now_ms = int(_time.time() * 1000)
    jot = _make_summary(dispatch_started_at_ms=now_ms - 1000)  # 1s ago, well under timeout
    fake_status = AsyncMock(side_effect=RuntimeError("substrate error"))
    with patch("mahavishnu.mcp.server_core.get_workflow_status", fake_status, create=True):
        # Must not raise.
        await _reconcile_if_in_flight(jot)
    fake_status.assert_called()


# ---------------------------------------------------------------------------
# _background_reconciler_loop — fold + per-jot exception paths (lines 640-664)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_reconciler_loop_survives_fold_and_per_jot_errors(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 640-664: loop must keep going on fold failure and per-jot failure."""
    calls = {"fold": 0, "per_jot": 0}
    original_sleep = asyncio.sleep

    async def fast_sleep(seconds: float) -> None:
        # Stop the loop after a small number of iterations
        if calls["fold"] >= 2:
            raise asyncio.CancelledError
        await original_sleep(0)

    monkeypatch.setattr("mahavishnu.jot.drain.RECONCILER_INTERVAL_SECONDS", 0)

    def flaky_parse_events(*args: Any, **kwargs: Any) -> Any:
        calls["fold"] += 1
        if calls["fold"] == 1:
            raise OSError("fold fail")
        # Second call returns a jot whose reconcile will raise
        from mahavishnu.jot.events import HLC, JotEvent

        return [
            JotEvent(
                id="e1",
                op="capture",
                text="x",
                ctx={},
                hlc=HLC(wall_ms=0, ctr=0, node="n1"),
                node="n1",
                created_ms=0,
            )
        ]

    async def fake_reconcile(_jot: Any) -> None:
        calls["per_jot"] += 1
        raise RuntimeError("reconcile blew up")

    monkeypatch.setattr("mahavishnu.jot.fold.parse_events", flaky_parse_events)
    monkeypatch.setattr("mahavishnu.jot.drain._reconcile_if_in_flight", fake_reconcile)
    monkeypatch.setattr("mahavishnu.jot.drain.asyncio.sleep", fast_sleep)

    with pytest.raises(asyncio.CancelledError):
        await _background_reconciler_loop()
    assert calls["fold"] >= 2


# ---------------------------------------------------------------------------
# drain_plan log-unreadable path — lines 748-750
# ---------------------------------------------------------------------------


def test_drain_plan_returns_empty_with_error_when_log_unreadable(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 748-750: parse_events raises → empty DrainPlan with error field.

    `drain_plan` is sync (returns DrainPlan directly, not a coroutine).
    """
    monkeypatch.setattr(
        "mahavishnu.jot.fold.parse_events",
        MagicMock(side_effect=OSError("permission denied")),
    )
    plan = drain_plan(query="anything")
    assert plan.candidates == []
    assert plan.error is not None
    assert "permission denied" in plan.error


# ---------------------------------------------------------------------------
# _propose_action — state branches (lines 787, 790, 793, 796-797)
# ---------------------------------------------------------------------------


def _jot_stub(
    short_id: str,
    dispatch_state: DispatchState | None,
) -> Any:
    """Build a JotSummary with just the fields _propose_action reads."""
    from mahavishnu.jot.fold import JotSummary

    return JotSummary(
        id=f"id-{short_id}",
        short_id=short_id,
        text="x",
        status="open",
        last_modified_ms=0,
        dispatch_state=dispatch_state,
    )


def test_propose_action_in_flight_skips() -> None:
    """Line 787: IN_FLIGHT → action='skip'."""
    proposal = _propose_action(_jot_stub("aabbcc", DispatchState.IN_FLIGHT))
    assert proposal["suggested_action"] == "skip"


def test_propose_action_failed_dispatches() -> None:
    """Line 790: FAILED → action='dispatch' (retry)."""
    proposal = _propose_action(_jot_stub("aabbcc", DispatchState.FAILED))
    assert proposal["suggested_action"] == "dispatch"


def test_propose_action_succeeded_done() -> None:
    """Line 793: SUCCEEDED → action='done'."""
    proposal = _propose_action(_jot_stub("aabbcc", DispatchState.SUCCEEDED))
    assert proposal["suggested_action"] == "done"


def test_propose_action_none_dispatches() -> None:
    """Lines 796-797: dispatch_state=None → action='dispatch' (first attempt)."""
    proposal = _propose_action(_jot_stub("aabbcc", None))
    assert proposal["suggested_action"] == "dispatch"


# ---------------------------------------------------------------------------
# dispatch_jot — already-IN_FLIGHT/SUCCEEDED/done paths (lines 827-841)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_jot_already_in_flight_raises(isolated_log: Path) -> None:
    """Line 827-831: dispatch_jot on IN_FLIGHT jot → JotDispatchError."""
    _write(
        isolated_log,
        _ev(op="capture", text="x", ms=0),
        _ev(
            op="dispatch", text="x", ms=10, workflow_id="wf-1",
            current_attempt=1,
        ),
    )
    with pytest.raises(JotDispatchError, match="already IN_FLIGHT"):
        await dispatch_jot("e1")


@pytest.mark.asyncio
async def test_dispatch_jot_already_succeeded_raises(isolated_log: Path) -> None:
    """Lines 832-836: dispatch_jot on SUCCEEDED jot → JotDispatchError."""
    _write(
        isolated_log,
        _ev(op="capture", text="x", ms=0),
        _ev(
            op="dispatch", text="x", ms=10, workflow_id="wf-1",
            current_attempt=1,
        ),
        _ev(
            op="dispatch_done", text="x", ms=20, workflow_id="wf-1",
        ),
    )
    with pytest.raises(JotDispatchError, match="already SUCCEEDED"):
        await dispatch_jot("e1")


@pytest.mark.asyncio
async def test_dispatch_jot_already_done_raises(isolated_log: Path) -> None:
    """Lines 837-841: dispatch_jot on status=done jot → JotDispatchError."""
    _write(
        isolated_log,
        _ev(op="capture", text="x", ms=0),
        _ev(op="done", text="x", ms=10),
    )
    with pytest.raises(JotDispatchError, match="already done"):
        await dispatch_jot("e1")


# ---------------------------------------------------------------------------
# retry_dispatch — not-FAILED-state path (lines 886-889)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_dispatch_non_failed_state_raises_jot_retry_error(
    isolated_log: Path,
) -> None:
    """Lines 886-889: retry on non-FAILED jot → JotRetryError."""
    _write(
        isolated_log,
        _ev(op="capture", text="x", ms=0),
        _ev(
            op="dispatch", text="x", ms=10, workflow_id="wf-1",
            current_attempt=1,
        ),
    )
    with pytest.raises(JotRetryError, match="not in FAILED state"):
        await retry_dispatch("e1")


# ---------------------------------------------------------------------------
# defer_jot — reason in context (lines 915-917)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_defer_jot_records_reason_in_context(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 915-917: defer with reason → ctx['reason'] populated."""
    # Make until_ms far enough in the future to satisfy the gate.
    monkeypatch.setattr(
        "mahavishnu.jot.drain._now_ms", lambda: 0
    )
    _write(
        isolated_log,
        _ev(op="capture", text="x", ms=0),
    )
    await defer_jot("e1", until_ms=10_000, reason="awaiting review")
    events = [
        json.loads(line) for line in isolated_log.read_text().strip().splitlines()
    ]
    defer_events = [e for e in events if e["op"] == "defer"]
    assert defer_events, "expected at least one defer event"
    assert defer_events[0]["ctx"].get("reason") == "awaiting review"


# ---------------------------------------------------------------------------
# _semantic_score — degraded paths (lines 1000-1012)
# ---------------------------------------------------------------------------


def test_semantic_score_degraded_on_timeout() -> None:
    """Line 1000-1002: embeddings service raises → degraded flag set, score 0.0."""
    import mahavishnu.jot.drain as drain_mod

    drain_mod._last_surface_degraded = False

    class FlakyEmbeddings:
        def embed(self, texts: list[str]) -> Any:
            raise TimeoutError("embeddings down")

    score = _semantic_score("hello", "world", FlakyEmbeddings())
    assert score == 0.0
    assert drain_mod._last_surface_degraded is True


def test_semantic_score_degraded_on_malformed_response() -> None:
    """Lines 1010-1012: embed() returns something unlenable → TypeError → degraded."""
    import mahavishnu.jot.drain as drain_mod

    drain_mod._last_surface_degraded = False

    class WeirdEmbeddings:
        def embed(self, texts: list[str]) -> Any:
            # Generator is truthy, but `len(generator)` raises TypeError.
            return (v for v in [[1.0, 2.0], [3.0, 4.0]])

    score = _semantic_score("hello", "world", WeirdEmbeddings())
    assert score == 0.0
    assert drain_mod._last_surface_degraded is True


def test_semantic_score_zero_when_embeddings_empty_or_short() -> None:
    """Line 1007: empty/short embedding tuple → degraded, score 0.0."""
    import mahavishnu.jot.drain as drain_mod

    drain_mod._last_surface_degraded = False

    class ShortEmbeddings:
        def embed(self, texts: list[str]) -> Any:
            return [[0.1]]  # only one vector; len(emb) < 2

    score = _semantic_score("hello", "world", ShortEmbeddings())
    assert score == 0.0
    assert drain_mod._last_surface_degraded is True


# ---------------------------------------------------------------------------
# surface_relevant — log-unreadable path (lines 1080-1090)
# ---------------------------------------------------------------------------


def test_surface_relevant_log_unreadable_returns_degraded_result(
    isolated_log: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lines 1080-1090: parse_events raises → degraded SurfacingResult.

    `surface_relevant(trigger, context_text, limit=3)` is sync.
    """
    monkeypatch.setattr(
        "mahavishnu.jot.fold.parse_events",
        MagicMock(side_effect=OSError("disk gone")),
    )
    result = surface_relevant("hook-trigger", "ctx text")
    assert result.matches == []
    assert result.surface_degraded is True
    assert result.surface_reason == "embeddings_down"
