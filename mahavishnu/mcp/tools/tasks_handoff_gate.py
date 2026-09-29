"""Feature-flag gate for session-buddy's tasks_handoff_to_workflow tool.

PR #1 of the Bodai task system adds the typed ``tasks_handoff_to_workflow``
tool to session-buddy. Until PR #1 is tagged and the version pin in
``pyproject.toml`` is bumped by the operator (per the
``feedback-mcp-common-version-bump-is-user`` rule — never bump versions
without explicit user direction), this gate lets the rest of mahavishnu
discover the new surface without crashing on an ``ImportError``.

This file exists per Ruling #3 (T16 plan) — feature-flag fallback pattern.
The companion registration in ``mahavishnu/mcp/tools/profiles.py`` is a
T18 deliverable; this module deliberately keeps the gate stateless so it
can be imported from any profile tier without side effects.
"""

from __future__ import annotations


def tasks_handoff_to_workflow_available() -> bool:
    """Return True if session-buddy's ``tasks_handoff_to_workflow`` is importable.

    The check imports :class:`HandoffParams` and :class:`HandoffResult`
    from ``session_buddy.mcp.tools.tasks_models`` — the typed envelopes
    PR #1 ships. ``False`` means the installed session-buddy predates
    PR #1 (or the package is missing entirely).

    T17/T18 consume this flag to decide whether to register the
    ``tasks_handoff_to_workflow`` MCP tool. Pre-PR #1 callers get a
    clear ``ToolError`` instead of an ``ImportError`` bubbling out of
    FastMCP's registration loop.
    """
    try:
        from session_buddy.mcp.tools.tasks_models import (  # noqa: F401
            HandoffParams,
            HandoffResult,
        )

        return True
    except ImportError:
        return False
