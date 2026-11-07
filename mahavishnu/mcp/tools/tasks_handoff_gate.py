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

Then the gate itself became a third way to take the server down: it
caught only ``ImportError``, so a dependency that failed at import
time for a non-import reason escaped into ``FastMCPServer.__init__``.
On 2026-11-06 the published session-buddy 0.38.0 raised
``pydantic.ValidationError`` while loading its settings, the
mahavishnu MCP server died before binding port 8680, and launchd
restarted it 28 times. Both imports now catch ``Exception``, so the
gate degrades to a skipped tool — with a warning — instead of a dead
orchestrator.
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


def _log_skip(source: str, exc: Exception) -> None:
    """Record that the handoff edge was skipped, and why.

    Only the exception TYPE is logged, never its message. The failure
    this guards against was a ``pydantic.ValidationError`` whose text
    embedded the operator's cloud credential values; logs are not a safe
    place for those.

    The type is logged QUALIFIED (``pydantic_core.ValidationError``,
    not a bare ``ValidationError``) so an operator can tell which
    dependency blew up without the log carrying anything out of the
    exception itself.
    """
    exc_type = type(exc)
    logger.warning(
        "task-system handoff edge skipped: %s is unavailable (%s.%s)",
        source,
        exc_type.__module__,
        exc_type.__qualname__,
    )


def tasks_handoff_to_workflow_available() -> bool:
    """Return True when session-buddy exposes the task-system contract.

    Checks importability AND that the shared envelopes still match
    field-for-field. Mahavishnu keeps inline copies of
    :class:`HandoffParams` and :class:`HandoffResult` so a session-buddy
    upgrade cannot break the tool signature mid-flight; this gate is
    what keeps those copies honest.

    ``False`` means the installed session-buddy does not provide a
    usable task-system contract: it predates the contract, the package
    is missing entirely, or the package raises while importing. Callers
    must SKIP the tool in every one of those cases — never raise. The
    registration happens inside ``FastMCPServer.__init__``, so raising
    there takes the whole mahavishnu MCP server down over one missing
    tool.

    That last sentence is load-bearing, so BOTH imports below catch
    ``Exception`` rather than just ``ImportError``. A dependency that
    fails at import time for a non-import reason — a settings
    ``ValidationError``, a syntax error in a plugin, a bad plugin
    registry — is still "the contract is not available", and it must
    degrade to a skipped tool rather than a dead orchestrator.
    """
    try:
        from session_buddy.mcp.tools.tasks_models import (  # ty: ignore[import-not-found]
            HandoffParams,
            HandoffResult,
        )
    except Exception as exc:  # gate contract — an import-time failure must skip the tool, never kill the server  # best-effort operation — broad catch is the documented contract  # noqa: BLE001, RUF100
        _log_skip("session-buddy's task-system models", exc)
        return False

    try:
        from mahavishnu.mcp.tools.tasks_handoff import (
            HandoffParams as LocalHandoffParams,
        )
        from mahavishnu.mcp.tools.tasks_handoff import (
            HandoffResult as LocalHandoffResult,
        )
    except Exception as exc:  # gate contract — same contract for mahavishnu's own inline copies  # best-effort operation — broad catch is the documented contract  # noqa: BLE001, RUF100
        _log_skip("mahavishnu's inline handoff envelopes", exc)
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
