"""Unit tests for the tasks_handoff_to_workflow feature-flag gate.

The gate answers one question: may mahavishnu register the handoff
edge against the INSTALLED session-buddy? It checks importability AND
that the two repos' shared envelopes still match field-for-field.

The shape check exists because mahavishnu keeps inline copies of
``HandoffParams`` / ``HandoffResult``. Those copies drifted before the
gate compared anything, and the drift was invisible until a task was
handed off.
"""

from __future__ import annotations

import pytest

from mahavishnu.mcp.tools.tasks_handoff_gate import (
    _envelope_mismatches,
    tasks_handoff_to_workflow_available,
)


@pytest.mark.unit
def test_tasks_handoff_to_workflow_available_returns_bool() -> None:
    """The gate returns a bool.

    ``True`` when the installed session-buddy exposes the contract AND
    the two repos' envelopes agree; ``False`` otherwise. Both outcomes
    are valid — we just need a deterministic bool contract.
    """
    result = tasks_handoff_to_workflow_available()
    assert isinstance(result, bool)


@pytest.mark.unit
def test_the_gate_reports_a_shape_mismatch() -> None:
    """A drifted envelope is detected, not accepted.

    This is the case the gate used to miss entirely: both copies were
    importable, so the gate said "available" even when the fields no
    longer lined up.
    """
    from pydantic import BaseModel

    class Upstream(BaseModel):
        a: str
        b: int = 3

    class SameLocal(BaseModel):
        a: str
        b: int = 3

    class DriftedLocal(BaseModel):
        a: str
        b: int = 4
        c: str = "extra"

    assert _envelope_mismatches(Upstream, SameLocal) == []

    problems = _envelope_mismatches(Upstream, DriftedLocal)
    assert problems, "a drifted envelope must be reported"
    assert any("unknown locally" in p for p in problems)
    assert any("default differs" in p for p in problems)


@pytest.mark.unit
def test_the_gate_is_false_when_the_installed_session_buddy_is_drifted() -> None:
    """The gate is False when the installed session-buddy is behind.

    mahavishnu depends on the PUBLISHED session-buddy, so until
    session-buddy ships the new contract the installed wheel still has
    the old ``HandoffParams`` and the gate must say so.

    The consequence is that the handoff edge is SKIPPED, not that the
    mahavishnu MCP server fails to start.
    """
    import session_buddy

    from mahavishnu.mcp.tools.tasks_handoff import HandoffParams as Local

    try:
        from session_buddy.mcp.tools.tasks_models import (
            HandoffParams as Upstream,
        )
    except ImportError:
        pytest.skip("session-buddy does not expose the task-system models")

    drifted = _envelope_mismatches(Upstream, Local)
    if drifted:
        assert tasks_handoff_to_workflow_available() is False, (
            "a drifted contract must not report available"
        )
    else:
        assert tasks_handoff_to_workflow_available() is True

    assert isinstance(session_buddy.__version__, str)
