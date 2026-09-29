"""Unit tests for the tasks_handoff_to_workflow feature-flag gate."""

from __future__ import annotations

import pytest

from mahavishnu.mcp.tools.tasks_handoff_gate import (
    tasks_handoff_to_workflow_available,
)


@pytest.mark.unit
def test_tasks_handoff_to_workflow_available_returns_bool() -> None:
    """The gate returns a bool.

    ``True`` when PR #1 session-buddy is installed; ``False`` when the
    older version is on disk. Both outcomes are valid — we just need a
    deterministic bool contract.
    """
    result = tasks_handoff_to_workflow_available()
    assert isinstance(result, bool)


@pytest.mark.unit
def test_tasks_handoff_to_workflow_available_via_real_imports() -> None:
    """When session-buddy 0.30+ is installed, the gate returns True.

    Skips on systems where the installed session-buddy is older than
    0.30 (i.e., PR #1 hasn't shipped there yet). The skip keeps the
    test meaningful across venvs at different release points.
    """
    from packaging.version import Version
    import session_buddy

    if Version(session_buddy.__version__) >= Version("0.30.0"):
        assert tasks_handoff_to_workflow_available() is True
    else:
        pytest.skip(f"session-buddy {session_buddy.__version__} < 0.30.0 — pre-PR #1")
