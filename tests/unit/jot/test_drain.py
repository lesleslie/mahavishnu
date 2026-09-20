"""Task 4: _append_event central write path.

Appended — Task 9 smoke tests for the high-level drain primitives
(drain_plan, dispatch_jot, retry_dispatch, defer_jot, delete_jot). The
primitives exercise the single write path with mocked workflow triggers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mahavishnu.jot.drain import (
    DispatchResult,
    DrainPlan,
    _append_event,
    defer_jot,
    delete_jot,
    dispatch_jot,
    drain_plan,
    retry_dispatch,
)
from mahavishnu.jot.errors import (
    JotDeferError,
    JotLogUnwritableError,
    JotRetryError,
    JotValidationError,
)
from mahavishnu.jot.events import HLC, JotEvent, serialize
from mahavishnu.jot.fold import JotSummary


@pytest.fixture
def isolated_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "log.jsonl"
    monkeypatch.setattr("mahavishnu.jot.drain.log_path", lambda: p)
    return p


@pytest.mark.asyncio
async def test_append_event_dispatch_autofills_started_at_ms(isolated_log: Path) -> None:
    await _append_event("dispatch", {
        "workflow_id": "wf-1", "attempt": 1,
        "pool_selector": "least_loaded", "dispatched_from": "mcp",
    }, jot_id="e1")
    lines = isolated_log.read_text().strip().split("\n")
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert "started_at_ms" in parsed["ctx"]
    assert isinstance(parsed["ctx"]["started_at_ms"], int)


@pytest.mark.asyncio
async def test_append_event_does_not_overwrite_caller_started_at(isolated_log: Path) -> None:
    await _append_event("dispatch", {
        "workflow_id": "wf-1", "attempt": 1,
        "pool_selector": "least_loaded", "dispatched_from": "mcp",
        "started_at_ms": 1234567890,
    }, jot_id="e1")
    parsed = json.loads(isolated_log.read_text().strip())
    assert parsed["ctx"]["started_at_ms"] == 1234567890


@pytest.mark.asyncio
async def test_append_event_validates_typeddict_rejects_missing_required(isolated_log: Path) -> None:
    with pytest.raises(JotValidationError):
        await _append_event("dispatch", {
            "attempt": 1, "pool_selector": "least_loaded", "dispatched_from": "mcp",
        }, jot_id="e1")
    assert isolated_log.exists() is False or isolated_log.read_text() == ""


@pytest.mark.asyncio
async def test_append_event_validates_typeddict_rejects_wrong_type(isolated_log: Path) -> None:
    with pytest.raises(JotValidationError):
        await _append_event("dispatch", {
            "workflow_id": "wf-1", "attempt": "1",  # str instead of int
            "pool_selector": "least_loaded", "dispatched_from": "mcp",
        }, jot_id="e1")
    assert isolated_log.exists() is False or isolated_log.read_text() == ""


@pytest.mark.asyncio
async def test_append_event_validates_retry_budget_exhausted_must_be_bool(
    isolated_log: Path,
) -> None:
    with pytest.raises(JotValidationError):
        await _append_event("dispatch_failed", {
            "workflow_id": "wf-1", "attempt": 1,
            "error": "x", "error_id": "E",
            "retry_budget_exhausted": "true",  # string, not bool
        }, jot_id="e1")


@pytest.mark.asyncio
async def test_append_event_accepts_all_op_types(isolated_log: Path) -> None:
    valid: list[tuple[str, dict]] = [
        ("dispatch_done", {"workflow_id": "wf-1", "summary": "ok"}),
        ("dispatch_failed", {
            "workflow_id": "wf-1", "attempt": 1,
            "error": "x", "error_id": "ERROR_JOT_WORKFLOW_FAILED",
            "retry_budget_exhausted": False,
        }),
        ("defer", {"until": 9999999999999}),
        ("defer_expired", {}),
        ("delete", {"reason": "user cleanup"}),
    ]
    for op, ctx in valid:
        await _append_event(op, ctx, jot_id="e1")
    assert len(isolated_log.read_text().strip().split("\n")) == 5


@pytest.mark.asyncio
async def test_append_event_raises_log_unwritable_on_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "mahavishnu.jot.drain.log_path",
        lambda: Path("/nonexistent/readonly/log.jsonl"),
    )
    with pytest.raises(JotLogUnwritableError) as excinfo:
        await _append_event("defer", {"until": 9999999999999}, jot_id="e1")
    assert excinfo.value.path  # carries path


@pytest.mark.asyncio
async def test_append_event_validates_literal_triggered_by(isolated_log: Path) -> None:
    with pytest.raises(JotValidationError):
        await _append_event("dispatch", {
            "workflow_id": "wf-1", "attempt": 1,
            "pool_selector": "least_loaded", "dispatched_from": "mcp",
            "triggered_by": "scheduler",  # not in {first, auto, manual}
        }, jot_id="e1")


@pytest.mark.asyncio
async def test_append_event_validates_literal_dispatched_from(isolated_log: Path) -> None:
    with pytest.raises(JotValidationError):
        await _append_event("dispatch", {
            "workflow_id": "wf-1", "attempt": 1,
            "pool_selector": "least_loaded", "dispatched_from": "bogus",
        }, jot_id="e1")


# =============================================================================
# Task 9 — High-level drain primitives (DrainPlan / DispatchResult)
# =============================================================================


@pytest.fixture
def seeded_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Seed a log with one capture + a 6-hex short_id of 'aaaaaaaa'."""
    p = tmp_path / "log.jsonl"
    monkeypatch.setattr("mahavishnu.jot.drain.log_path", lambda: p)
    # fold and handle import log_path from .paths; both modules must see
    # the patched value. patch the canonical source.
    monkeypatch.setattr("mahavishnu.jot.paths.log_path", lambda: p)
    p.parent.mkdir(parents=True, exist_ok=True)
    capture = JotEvent(
        id="aaaaaaaa" * 4,
        op="capture",
        hlc=HLC(wall_ms=1_700_000_000_000, ctr=0, node="aaaaaaaa"),
        text="hello world",
        ctx={"cwd": "/x", "session_id": "s"},
        created_ms=1_700_000_000_000,
    )
    p.write_text(serialize(capture) + "\n")
    return p


def test_drain_plan_returns_dataclass(seeded_log: Path) -> None:
    """drain_plan returns a DrainPlan with `candidates` as JotSummary list."""
    plan = drain_plan(query=None, limit=10)
    assert isinstance(plan, DrainPlan)
    assert plan.query is None
    assert plan.error is None
    assert len(plan.candidates) == 1
    assert isinstance(plan.candidates[0], JotSummary)
    assert plan.candidates[0].text == "hello world"


def test_drain_plan_lexical_filter_drops_unmatched(seeded_log: Path) -> None:
    """Lexical score < 0.20 removes the candidate."""
    plan = drain_plan(query="zzz_gibberish_xxx")
    assert plan.candidates == []


def test_dispatch_jot_appends_event_and_returns_dispatch_result(
    seeded_log: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke: dispatch_jot calls _mcp_trigger_workflow with the jot's text
    prompt, returns a DispatchResult, and emits a dispatch event with
    the `dispatched_from` kwarg surfaced in ctx."""

    async def _fake_trigger(
        adapter: str, task_type: str, params: dict[str, object],
    ) -> dict[str, object]:
        if params.get("prompt") != "hello world":
            return {"workflow_id": ""}
        return {"workflow_id": "wf-77"}

    monkeypatch.setattr(
        "mahavishnu.jot.drain._mcp_trigger_workflow", _fake_trigger,
    )

    import asyncio
    res = asyncio.run(dispatch_jot("aaaaaaaa", dispatched_from="mcp"))
    assert isinstance(res, DispatchResult)
    assert res.handle == "aaaaaa"  # brief returns short_id, not full id
    assert res.workflow_id == "wf-77"
    assert res.status == "in_flight"
    events = [
        json.loads(line)
        for line in seeded_log.read_text().splitlines()
        if line.strip()
    ]
    dispatch_evts = [e for e in events if e["op"] == "dispatch"]
    assert len(dispatch_evts) == 1
    assert dispatch_evts[0]["ctx"]["dispatched_from"] == "mcp"


def test_retry_dispatch_rejects_non_failed(seeded_log: Path) -> None:
    """retry_dispatch on a non-FAILED jot raises JotRetryError."""
    import asyncio
    with pytest.raises(JotRetryError) as exc_info:
        asyncio.run(retry_dispatch("aaaaaaaa"))
    assert "not in FAILED state" in str(exc_info.value)


def test_defer_jot_rejects_past_timestamp(seeded_log: Path) -> None:
    """until_ms <= now_ms raises JotDeferError."""
    import asyncio
    with pytest.raises(JotDeferError):
        asyncio.run(defer_jot("aaaaaaaa", until_ms=1))


def test_delete_jot_writes_event(
    seeded_log: Path,
) -> None:
    """delete_jot appends a delete event to the log and surfaces the
    updated JotSummary. Linkage contract (event id == jot id) is out of
    scope for Task 9 — fold-level `deleted=True` requires threading the
    parent jot id through the delete event payload."""
    import asyncio

    summary = asyncio.run(delete_jot("aaaaaaaa", reason="stale"))
    assert isinstance(summary, JotSummary)
    # parse_events tolerates blank lines; replicate that defensive parse
    events = [
        json.loads(line)
        for line in seeded_log.read_text().splitlines()
        if line.strip()
    ]
    delete_evts = [e for e in events if e["op"] == "delete"]
    assert len(delete_evts) == 1
    assert delete_evts[0]["ctx"]["reason"] == "stale"


def test_validate_ctx_rejects_unknown_key_on_dispatch() -> None:
    from mahavishnu.jot.drain import _validate_ctx
    from mahavishnu.jot.errors import JotValidationError
    with pytest.raises(JotValidationError) as excinfo:
        _validate_ctx(
            "dispatch",
            {
                "workflow_id": "wf-1",
                "attempt": 1,
                "pool_selector": "least_loaded",
                "dispatched_from": "mcp",
                "mistyped_key": "typo",  # NOT a known key
            },
        )
    assert "mistyped_key" in str(excinfo.value)
    assert "unknown keys" in str(excinfo.value)


def test_validate_ctx_rejects_unknown_key_on_dispatch_failed() -> None:
    from mahavishnu.jot.drain import _validate_ctx
    from mahavishnu.jot.errors import JotValidationError
    with pytest.raises(JotValidationError) as excinfo:
        _validate_ctx(
            "dispatch_failed",
            {
                "workflow_id": "wf-1",
                "attempt": 1,
                "error": "boom",
                "error_id": "ERROR_TEST",
                "retry_budget_exhausted": False,
                "extra_key": "should be rejected",
            },
        )
    assert "extra_key" in str(excinfo.value)


def test_validate_ctx_rejects_unknown_key_on_defer() -> None:
    from mahavishnu.jot.drain import _validate_ctx
    from mahavishnu.jot.errors import JotValidationError
    with pytest.raises(JotValidationError) as excinfo:
        _validate_ctx("defer", {"until": 100, "extra": "x"})
    assert "extra" in str(excinfo.value)


def test_validate_ctx_accepts_started_at_ms_on_dispatch() -> None:
    """Regression guard: started_at_ms is auto-filled by _append_event;
    it MUST be in the whitelist or dispatch breaks at runtime.
    """
    from mahavishnu.jot.drain import _validate_ctx
    # Should NOT raise. (started_at_ms is auto-filled before _validate_ctx.)
    _validate_ctx(
        "dispatch",
        {
            "workflow_id": "wf-1",
            "attempt": 1,
            "pool_selector": "least_loaded",
            "dispatched_from": "mcp",
            "started_at_ms": 1700000000000,
        },
    )
