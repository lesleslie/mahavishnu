"""Task 4: _append_event central write path."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mahavishnu.jot.drain import _append_event
from mahavishnu.jot.errors import JotLogUnwritableError, JotValidationError


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
    })
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
    })
    parsed = json.loads(isolated_log.read_text().strip())
    assert parsed["ctx"]["started_at_ms"] == 1234567890


@pytest.mark.asyncio
async def test_append_event_validates_typeddict_rejects_missing_required(isolated_log: Path) -> None:
    with pytest.raises(JotValidationError):
        await _append_event("dispatch", {
            "attempt": 1, "pool_selector": "least_loaded", "dispatched_from": "mcp",
        })
    assert isolated_log.exists() is False or isolated_log.read_text() == ""


@pytest.mark.asyncio
async def test_append_event_validates_typeddict_rejects_wrong_type(isolated_log: Path) -> None:
    with pytest.raises(JotValidationError):
        await _append_event("dispatch", {
            "workflow_id": "wf-1", "attempt": "1",  # str instead of int
            "pool_selector": "least_loaded", "dispatched_from": "mcp",
        })
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
        })


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
        await _append_event(op, ctx)
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
        await _append_event("defer", {"until": 9999999999999})
    assert excinfo.value.path  # carries path


@pytest.mark.asyncio
async def test_append_event_validates_literal_triggered_by(isolated_log: Path) -> None:
    with pytest.raises(JotValidationError):
        await _append_event("dispatch", {
            "workflow_id": "wf-1", "attempt": 1,
            "pool_selector": "least_loaded", "dispatched_from": "mcp",
            "triggered_by": "scheduler",  # not in {first, auto, manual}
        })


@pytest.mark.asyncio
async def test_append_event_validates_literal_dispatched_from(isolated_log: Path) -> None:
    with pytest.raises(JotValidationError):
        await _append_event("dispatch", {
            "workflow_id": "wf-1", "attempt": 1,
            "pool_selector": "least_loaded", "dispatched_from": "bogus",
        })
