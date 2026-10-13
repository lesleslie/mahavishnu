"""Budget enforcement MCP tool.

Extracted from ``mahavishnu.mcp.tools.pool_tools`` (originally lines
732-800). Carved out as part of the Stage 3b unblocker plan — see
``docs/plans/2026-10-12-pool-tools-debt-and-shepherd-registry.md``.

The ``budget_enforce`` MCP surface declares a per-workflow budget
(tokens / turns / wallclock) that the watchdog subsequently enforces.
Re-calling with the same ``workflow_id`` re-bases the cap — the
"pause at N" semantics on a running run are intentional.

The MCP boundary swallows failures as ``status: "failed"`` rather than
raising — the watchdog polls against whatever state was last persisted,
so a partial write here is acceptable.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

from mcp_common.fastmcp import FastMCP

from mahavishnu.core.budget import BudgetRecord, BudgetSpec, BudgetStateMachine

logger = logging.getLogger(__name__)

# Module-level dependency slot. ``register_budget_tools`` writes the live
# ``BudgetStore`` here so the module-level ``budget_enforce_tool`` callable
# can reach it without a closure. Mirrors the per-tool state pattern used
# elsewhere in the MCP layer (e.g. jot_tools rebinds module attrs at
# registration time). ``None`` means "unconfigured" — tests that don't
# exercise persistence leave it that way.
_budget_store: Any | None = None

__all__ = ["budget_enforce_tool", "register_budget_tools"]


async def budget_enforce_tool(
    workflow_id: str,
    budget_tokens: int | None = None,
    budget_turns: int | None = None,
    budget_wallclock_seconds: float | None = None,
    declared_by: str | None = None,
) -> dict[str, Any]:
    """Declare a per-workflow budget; the watchdog enforces it.

    ``workflow_id`` must be unique per call. Re-calling with the
    same ``workflow_id`` re-bases the cap (intentional "pause at
    N" semantics on a running run). The MCP boundary swallows
    MCP failures as ``status: "failed"`` rather than raising —
    the watchdog polls against whatever state was last persisted,
    so a partial write here is acceptable.
    """
    if _budget_store is None:
        return {
            "workflow_id": workflow_id,
            "status": "unconfigured",
            "error": "budget_store is not configured on this server",
        }
    spec = BudgetSpec(
        budget_tokens=budget_tokens,
        budget_turns=budget_turns,
        budget_wallclock_seconds=budget_wallclock_seconds,
        declared_by=declared_by,
    )
    try:
        existing_raw = await _budget_store.get(
            f"mahavishni://budgets/{workflow_id}.json"
        )
    except Exception as exc:
        logger.warning("budget_enforce: read failed for %s: %s", workflow_id, exc)
        existing_raw = None
    sm = BudgetStateMachine(
        BudgetRecord.from_dict(existing_raw)
        if isinstance(existing_raw, dict) and existing_raw.get("workflow_id")
        else BudgetRecord(workflow_id=workflow_id)
    )
    sm.declare(spec)
    try:
        sm.start(when=datetime.now(UTC))
    except ValueError as exc:
        return {
            "workflow_id": workflow_id,
            "status": "failed",
            "error": str(exc),
        }
    try:
        await _budget_store.put(
            f"mahavishni://budgets/{workflow_id}.json",
            sm.record.to_dict(),
        )
    except Exception as exc:
        logger.warning("budget_enforce: persist failed for %s: %s", workflow_id, exc)
        return {
            "workflow_id": workflow_id,
            "status": "failed",
            "error": f"failed to persist budget: {exc}",
        }
    logger.info(
        "mahavishnu_budget_enforce_invoked",
        extra={"workflow_id": workflow_id, "status": "active"},
    )
    return {
        "workflow_id": workflow_id,
        "status": "active",
        "spec": spec.to_dict(),
        "state": sm.record.state.value,
        "started_at": (
            sm.record.started_at.isoformat() if sm.record.started_at is not None else None
        ),
    }


def register_budget_tools(
    mcp_app: FastMCP,
    *,
    budget_store: Any | None = None,
) -> None:
    """Register the ``mahavishnu_budget_enforce`` tool.

    Stores ``budget_store`` in the module-level slot and decorates
    :func:`budget_enforce_tool` against ``mcp_app`` so it becomes an
    MCP-callable tool. ``pool_manager`` is reserved for future budget
    attribution per-pool and intentionally accepted-but-ignored for
    API parity with the broader tool-registration contract.

    Args:
        mcp_app: FastMCP instance to register against.
        budget_store: Optional :class:`mahavishnu.core.budget.BudgetStore`
            used by ``budget_enforce_tool``. When ``None`` (the default,
            used in tests that don't exercise budgets) the tool returns
            ``{"status": "unconfigured"}`` rather than raising.
    """
    global _budget_store
    _budget_store = budget_store
    mcp_app.tool(name="mahavishnu_budget_enforce")(budget_enforce_tool)
    logger.info("mahavishnu_budget_enforce_registered")