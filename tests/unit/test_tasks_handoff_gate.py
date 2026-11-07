"""Unit tests for the tasks_handoff_to_workflow feature-flag gate.

The gate answers one question: may mahavishnu register the handoff
edge against the INSTALLED session-buddy? It checks importability AND
that the two repos' shared envelopes still match field-for-field.

The shape check exists because mahavishnu keeps inline copies of
``HandoffParams`` / ``HandoffResult``. Those copies drifted before the
gate compared anything, and the drift was invisible until a task was
handed off.

The gate must also NEVER raise. Its result is consumed inside
``FastMCPServer.__init__``, so an escaping exception kills the whole
orchestrator over one skipped tool.
"""

from __future__ import annotations

import builtins
import logging
from typing import Any

import pytest

from mahavishnu.mcp.tools.tasks_handoff_gate import (
    _envelope_mismatches,
    tasks_handoff_to_workflow_available,
)

_GATE_LOGGER = "mahavishnu.mcp.tools.tasks_handoff_gate"


def _raise_on_import(prefix: str, exc: Exception) -> Any:
    """Return an ``__import__`` replacement that fails for ``prefix``.

    Simulates a dependency that blows up at import time. The real
    incident was a ``pydantic.ValidationError`` raised inside
    session-buddy's settings load, which is not an ``ImportError`` and
    therefore escaped the gate's narrow ``except`` clause.
    """
    original_import = builtins.__import__

    def _patched_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name.startswith(prefix):
            raise exc
        return original_import(name, globals, locals, fromlist, level)

    return _patched_import


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


@pytest.mark.unit
@pytest.mark.parametrize(
    "exc_type",
    [RuntimeError, ValueError],
    ids=["runtime-error", "value-error"],
)
def test_the_gate_never_raises_when_the_session_buddy_import_fails(
    monkeypatch: pytest.MonkeyPatch,
    exc_type: type[Exception],
) -> None:
    """A broken session-buddy must not take the MCP server down.

    The gate's contract is "never raise": its result is consumed inside
    ``FastMCPServer.__init__``, so an escaping exception kills the whole
    orchestrator over one skipped tool.

    This is not hypothetical. On 2026-11-06 the published session-buddy
    0.38.0 raised ``pydantic.ValidationError`` at import time (its
    ``cloud_sync`` group rejected operator-supplied credentials), the
    gate caught only ``ImportError``, and the exception escaped into
    ``FastMCPServer.__init__``. The mahavishnu MCP server died before
    binding port 8680 and launchd restarted it 28 times.
    """
    monkeypatch.setattr(
        builtins,
        "__import__",
        _raise_on_import("session_buddy", exc_type("simulated breakage")),
    )

    assert tasks_handoff_to_workflow_available() is False


@pytest.mark.unit
def test_the_gate_warns_when_the_session_buddy_import_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The skip is logged, so an operator can see WHY the edge is off.

    A silently skipped handoff edge looks identical to a working one
    from the outside. The warning names the failure without echoing the
    exception message — that message carried credential values on
    2026-11-06, and logs are not a safe place for those.
    """
    monkeypatch.setattr(
        builtins,
        "__import__",
        _raise_on_import("session_buddy", RuntimeError("simulated breakage")),
    )

    with caplog.at_level(logging.WARNING, logger=_GATE_LOGGER):
        assert tasks_handoff_to_workflow_available() is False

    # Filter to the gate's own logger. ``caplog`` captures every WARNING
    # record the process emits, and unrelated libraries emit their own
    # during import (fastmcp's tool registration does). Asserting on the
    # first captured warning would then depend on which module happened
    # to import first — a different order in a fresh worktree than in the
    # main checkout, which is exactly how this test failed there.
    warnings = [
        r
        for r in caplog.records
        if r.name == _GATE_LOGGER and r.levelno >= logging.WARNING
    ]
    assert warnings, "skipping the handoff edge must be logged"
    message = warnings[0].getMessage()
    assert "session-buddy's task-system models" in message, (
        "the warning must name the import that failed"
    )
    assert "RuntimeError" in message, "the failure type must be named"
    assert "simulated breakage" not in message, (
        "the exception message must not be logged — it can carry secrets"
    )


@pytest.mark.unit
def test_the_gate_never_raises_when_the_local_envelope_import_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A broken mahavishnu-side envelope copy is also survivable.

    The gate reads two sets of envelopes: the upstream ones from
    session-buddy and mahavishnu's own inline copies. Both imports run
    inside ``FastMCPServer.__init__``, so both must degrade to "skip
    the tool" rather than raising.
    """
    monkeypatch.setattr(
        builtins,
        "__import__",
        _raise_on_import(
            "mahavishnu.mcp.tools.tasks_handoff",
            RuntimeError("simulated breakage"),
        ),
    )

    with caplog.at_level(logging.WARNING, logger=_GATE_LOGGER):
        assert tasks_handoff_to_workflow_available() is False

    warnings = [
        r
        for r in caplog.records
        if r.name == _GATE_LOGGER and r.levelno >= logging.WARNING
    ]
    assert warnings, "skipping the handoff edge must be logged"
    assert "RuntimeError" in warnings[0].getMessage()
