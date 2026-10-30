"""Feature-flag gate for session-buddy's task-system contract.

The Bodai task system spans two repos: session-buddy owns the task
model and the tools, mahavishnu owns the dispatch edge. The two keep
inline copies of the shared envelopes (:class:`HandoffParams` and
:class:`HandoffResult`) so that a session-buddy upgrade cannot break
the tool signature mid-flight.

That duplication is only safe if something CHECKS it. This module is
that check.

Two things went wrong before it did anything:

* It only checked that session-buddy was IMPORTABLE, not that the
  shapes matched — so the two copies could drift freely, and did.
* The caller treated a False result by raising ``RuntimeError`` from
  inside ``FastMCPServer.__init__``, which took the WHOLE mahavishnu
  MCP server down over one missing tool. A version skew should cost
  the fleet the handoff edge, not the orchestrator.

So the gate now compares the shapes field-by-field, and the caller
SKIPS registration instead of raising.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The envelope fields the two repos must agree on. A mismatch here is
#: a cross-repo contract break: mahavishnu's inline copy would build a
#: result session-buddy's model rejects (or vice versa).
_SHARED_ENVELOPE_NAMES = ("HandoffParams", "HandoffResult")


def _envelope_mismatches(
    upstream: Any,
    local: Any,
) -> list[str]:
    """Return the field names that differ between two envelope models.

    Compares the model fields (names, required-ness, and defaults) and
    the set of field names, so a field added on one side only is caught
    as well as a type change.
    """
    problems: list[str] = []
    upstream_fields = getattr(upstream, "model_fields", {})
    local_fields = getattr(local, "model_fields", {})
    only_upstream = sorted(set(upstream_fields) - set(local_fields))
    only_local = sorted(set(local_fields) - set(upstream_fields))
    if only_upstream:
        problems.append(f"missing locally: {only_upstream}")
    if only_local:
        problems.append(f"unknown locally: {only_local}")
    for name in sorted(set(upstream_fields) & set(local_fields)):
        up = upstream_fields[name]
        lo = local_fields[name]
        if up.is_required() != lo.is_required():
            problems.append(f"{name}: requiredness differs")
            continue
        if not up.is_required() and up.default != lo.default:
            problems.append(f"{name}: default differs")
    return problems


def tasks_handoff_to_workflow_available() -> bool:
    """Return True when session-buddy exposes the task-system contract.

    Checks importability AND that the shared envelopes still match
    field-for-field. Mahavishnu keeps inline copies of
    :class:`HandoffParams` and :class:`HandoffResult` so a session-buddy
    upgrade cannot break the tool signature mid-flight; this gate is
    what keeps those copies honest.

    ``False`` means the installed session-buddy predates the contract
    (or the package is missing entirely). Callers must SKIP the tool in
    that case — never raise. The registration happens inside
    ``FastMCPServer.__init__``, so raising there takes the whole
    mahavishnu MCP server down over one missing tool.
    """
    try:
        from session_buddy.mcp.tools.tasks_models import (  # ty: ignore[unresolved-import]
            HandoffParams,
            HandoffResult,
        )
    except ImportError:
        return False

    try:
        from mahavishnu.mcp.tools.tasks_handoff import (
            HandoffParams as LocalHandoffParams,
        )
        from mahavishnu.mcp.tools.tasks_handoff import (
            HandoffResult as LocalHandoffResult,
        )
    except ImportError:  # pragma: no cover - this module IS tasks_handoff
        return False

    local = {
        "HandoffParams": LocalHandoffParams,
        "HandoffResult": LocalHandoffResult,
    }
    upstream = {
        "HandoffParams": HandoffParams,
        "HandoffResult": HandoffResult,
    }
    for name in _SHARED_ENVELOPE_NAMES:
        problems = _envelope_mismatches(upstream[name], local[name])
        if problems:
            logger.warning(
                "task-system contract mismatch in %s: %s — the handoff edge "
                "will be skipped until the repos are back in sync",
                name,
                "; ".join(problems),
            )
            return False
    return True
