"""Task 14: 6 new drain MCP tool wrappers.

Validates that each ``jot_*`` tool wrapper in ``mahavishnu/mcp/tools/jot_tools.py``
calls the correct primitive in ``mahavishnu.jot.drain`` and shapes the result
into the documented TypedDict return. The drain primitives themselves
(``drain_plan``, ``dispatch_jot``, ``defer_jot``, ``delete_jot``,
``retry_dispatch``, ``surface_relevant``) are NOT yet implemented
(Task 9 / Task 8 pending); tests therefore mock the primitives on the
``mahavishnu.jot.drain`` module directly.

See spec §3.3.
"""
from __future__ import annotations

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from mahavishnu.jot.fold import JotSummary

# ---------------------------------------------------------------------------
# Module load: import jot_tools directly (same trick as test_jot_tools.py)
# to bypass mahavishnu/mcp/tools/__init__.py which imports sibling WIP modules.
# ---------------------------------------------------------------------------

_jot_tools_path = (
    Path(__file__).resolve().parents[3] / "mahavishnu" / "mcp" / "tools" / "jot_tools.py"
)
_spec = importlib.util.spec_from_file_location("jot_tools_drain_under_test", _jot_tools_path)
jot_tools = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules[_spec.name] = jot_tools
_spec.loader.exec_module(jot_tools)  # type: ignore[union-attr]


@pytest.fixture(autouse=True)
def _redirect_to_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Sandbox ~/.mahavishnu/jot/ in tmp_path (mirrors test_jot_tools.py)."""
    from mahavishnu.jot import hlc as hlc_module

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    hlc_module._node = None
    jot = tmp_path / ".mahavishnu" / "jot"
    jot.mkdir(parents=True, exist_ok=True)
    (jot / "node").write_text("a" * 8)


def _summary(sid: str = "a3f9c2") -> JotSummary:
    return JotSummary(
        id=sid.ljust(32, "0"),
        short_id=sid,
        text="hello",
        status="open",
        last_modified_ms=1_700_000_000_000,
        dispatch_state=None,
        dispatch_workflow_id=None,
        current_attempt=0,
        dispatch_started_at_ms=None,
        deferred_until=None,
        deleted=False,
    )


# Each wrapper does `from mahavishnu.jot import drain` then calls a
# primitive. Patch the primitive directly on mahavishnu.jot.drain so
# the lazy import resolves to the (already-loaded) module and our mock
# sees the call.

# ---------------------------------------------------------------------------
# jot_drain -> DrainPlanDict
# ---------------------------------------------------------------------------


def test_jot_drain_returns_drain_plan_dict() -> None:
    """jot_drain calls drain.drain_plan() and returns DrainPlanDict shape.

    action_proposals is empty (the wrapper does not synthesize proposals;
    callers request them via drain.execute_action or their own heuristics).
    """
    import mahavishnu.jot.drain as drain_module

    plan = SimpleNamespace(
        query="urgent",
        candidates=[_summary("a3f9c2"), _summary("b4e8d1")],
    )
    with mock.patch.object(drain_module, "drain_plan", return_value=plan) as mp:
        result = jot_tools.jot_drain.fn(
            query="urgent", limit=20, include_in_flight=False,
        )

    assert result["query"] == "urgent"
    assert len(result["candidates"]) == 2
    assert result["candidates"][0]["short_id"] == "a3f9c2"
    assert result["candidates"][1]["short_id"] == "b4e8d1"
    assert result["action_proposals"] == []
    mp.assert_called_once_with(
        query="urgent", limit=20, include_in_flight=False,
    )


def test_jot_drain_default_query_is_none() -> None:
    import mahavishnu.jot.drain as drain_module

    plan = SimpleNamespace(query=None, candidates=[])
    with mock.patch.object(drain_module, "drain_plan", return_value=plan) as mp:
        result = jot_tools.jot_drain.fn()

    assert result["query"] is None
    assert result["candidates"] == []
    mp.assert_called_once_with(
        query=None, limit=20, include_in_flight=False,
    )


# ---------------------------------------------------------------------------
# jot_dispatch -> DispatchResultDict (sets dispatched_from="mcp")
# ---------------------------------------------------------------------------


def test_jot_dispatch_returns_dispatch_result_dict_with_dispatched_from_mcp() -> None:
    import mahavishnu.jot.drain as drain_module

    res = SimpleNamespace(
        handle="a3f9c2",
        workflow_id="wf-123",
        attempt=1,
        status="in_flight",
    )
    with mock.patch.object(drain_module, "dispatch_jot", return_value=res) as mp:
        result = jot_tools.jot_dispatch.fn(handle="a3f9c2")

    assert result == {
        "handle": "a3f9c2",
        "workflow_id": "wf-123",
        "attempt": 1,
        "status": "in_flight",
        "dispatched_from": "mcp",
    }
    mp.assert_called_once_with(handle="a3f9c2")


# ---------------------------------------------------------------------------
# jot_defer -> JotSummaryDict
# ---------------------------------------------------------------------------


def test_jot_defer_returns_jot_summary_dict() -> None:
    import mahavishnu.jot.drain as drain_module

    deferred = replace(_summary("c5f7e0"), deferred_until=1_800_000_000_000)
    with mock.patch.object(drain_module, "defer_jot", return_value=deferred) as mp:
        result = jot_tools.jot_defer.fn(
            handle="c5f7e0", until_ms=1_800_000_000_000, reason="later",
        )

    assert result["short_id"] == "c5f7e0"
    assert result["deferred_until"] == 1_800_000_000_000
    mp.assert_called_once_with(
        handle="c5f7e0", until_ms=1_800_000_000_000, reason="later",
    )


def test_jot_defer_optional_reason() -> None:
    import mahavishnu.jot.drain as drain_module

    deferred = _summary("d6a8f1")
    with mock.patch.object(drain_module, "defer_jot", return_value=deferred) as mp:
        jot_tools.jot_defer.fn(handle="d6a8f1", until_ms=1_800_000_000_000)

    mp.assert_called_once_with(
        handle="d6a8f1", until_ms=1_800_000_000_000, reason=None,
    )


# ---------------------------------------------------------------------------
# jot_delete -> JotSummaryDict
# ---------------------------------------------------------------------------


def test_jot_delete_returns_jot_summary_dict_with_deleted_true() -> None:
    import mahavishnu.jot.drain as drain_module

    deleted = replace(_summary("e7b9a2"), deleted=True)
    with mock.patch.object(drain_module, "delete_jot", return_value=deleted) as mp:
        result = jot_tools.jot_delete.fn(handle="e7b9a2", reason="duplicate")

    assert result["short_id"] == "e7b9a2"
    assert result["deleted"] is True
    mp.assert_called_once_with(handle="e7b9a2", reason="duplicate")


# ---------------------------------------------------------------------------
# jot_retry -> DispatchResultDict
# ---------------------------------------------------------------------------


def test_jot_retry_returns_dispatch_result_dict_with_dispatched_from_mcp() -> None:
    import mahavishnu.jot.drain as drain_module

    res = SimpleNamespace(
        handle="f8c0b3",
        workflow_id="wf-456",
        attempt=2,
        status="queued",
    )
    with mock.patch.object(drain_module, "retry_dispatch", return_value=res) as mp:
        result = jot_tools.jot_retry.fn(handle="f8c0b3")

    assert result == {
        "handle": "f8c0b3",
        "workflow_id": "wf-456",
        "attempt": 2,
        "status": "queued",
        "dispatched_from": "mcp",
    }
    mp.assert_called_once_with(handle="f8c0b3")


# ---------------------------------------------------------------------------
# jot_resurface -> list[JotSummaryDict]
# ---------------------------------------------------------------------------


def test_jot_resurface_returns_list_of_summary_dicts() -> None:
    import mahavishnu.jot.drain as drain_module

    surface = SimpleNamespace(
        matches=[_summary("a1b2c3"), _summary("d4e5f6")],
    )
    with mock.patch.object(
        drain_module, "surface_relevant", return_value=surface,
    ) as mp:
        result = jot_tools.jot_resurface.fn(
            trigger="session_start", context_text="investigating", limit=3,
        )

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["short_id"] == "a1b2c3"
    assert result[1]["short_id"] == "d4e5f6"
    mp.assert_called_once_with(
        trigger="session_start", context_text="investigating", limit=3,
    )


def test_jot_resurface_default_limit_is_three() -> None:
    import mahavishnu.jot.drain as drain_module

    surface = SimpleNamespace(matches=[])
    with mock.patch.object(
        drain_module, "surface_relevant", return_value=surface,
    ) as mp:
        jot_tools.jot_resurface.fn(trigger="tool_result", context_text="x")

    mp.assert_called_once_with(
        trigger="tool_result", context_text="x", limit=3,
    )


# ---------------------------------------------------------------------------
# Module-level registration: every new tool name appears in register() and
# in the wrap-at-import name list (test_jot_tools.py already covers the 8
# pre-existing names).
# ---------------------------------------------------------------------------


def test_new_tool_names_appear_in_register_list() -> None:
    """The 6 new tool names must be in the registration list."""
    src = _jot_tools_path.read_text()
    for name in (
        "jot_drain", "jot_dispatch", "jot_defer",
        "jot_delete", "jot_retry", "jot_resurface",
    ):
        assert name in src, f"{name} missing from jot_tools.py"


def test_new_tools_expose_underlying_callable_via_fn() -> None:
    """Each wrapped FunctionTool exposes the original function via .fn."""
    for name in (
        "jot_drain", "jot_dispatch", "jot_defer",
        "jot_delete", "jot_retry", "jot_resurface",
    ):
        tool = getattr(jot_tools, name)
        assert hasattr(tool, "fn"), f"{name} missing .fn accessor"
        assert callable(tool.fn), f"{name}.fn not callable"