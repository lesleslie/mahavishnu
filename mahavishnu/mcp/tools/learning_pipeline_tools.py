"""MCP tools for the governed learning pipeline (read-only).

All tools are observation-only: no approve/reject/promote/rollback
operations are exposed via MCP.  Human review is mandatory.

Security notes (post-wiring hardening, 2026-10-14):

* Each tool is gated by :func:`mahavishnu.mcp.auth.require_mcp_auth`
  against the ``Permission.READ`` namespace (4 tools) and
  ``Permission.WRITE`` for ``trigger_synthesis`` (which kicks off a
  cycle that writes evidence to Session-Buddy). The gates are
  fail-closed: a missing ``rbac_manager`` denies with
  ``error_code == "AUTH_NOT_CONFIGURED"``.
* Error responses return the exception class name (not the full
  message) to avoid leaking internal details (Session-Buddy URLs,
  Pydantic payloads, query plans). The full trace stays in
  ``mahavishnu.*`` logs via ``logger.warning(..., exc_info=True)``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp_common.auth.permissions import Permission as MCPPermission

from ...mcp.auth import require_mcp_auth

if TYPE_CHECKING:
    from mcp_common.fastmcp import FastMCP

logger = logging.getLogger(__name__)


def _safe_error(exc: BaseException) -> str:
    """Return the exception class name only (no message).

    Keeps internal exception details (URLs, payloads, stack
    fragments) out of the MCP response. The full exception is still
    in the application log via ``logger.warning(..., exc_info=True)``.
    """
    return type(exc).__name__


def register_learning_tools(
    mcp: FastMCP,
    pipeline_service: Any | None = None,
    evidence_store: Any | None = None,
    skill_registry: Any | None = None,
    rbac_manager: Any | None = None,
) -> None:
    """Register read-only learning pipeline tools.

    Structural C901 suppression: FastMCP's ``@mcp.tool()`` decorator
    requires each tool function to be defined inline so it can introspect
    the function name and signature for the MCP tool schema. The tools
    registered here are intentionally kept inline; the complexity is the
    cost of the FastMCP API contract, not bad code.

    Args:
        mcp: FastMCP instance.
        pipeline_service: LearningPipelineService, if initialized.
        evidence_store: EvidenceStore, if initialized.
        skill_registry: SkillRegistry, if initialized.
        rbac_manager: Optional RBACManager. When ``None`` the auth gates
            fail closed with ``error_code == "AUTH_NOT_CONFIGURED"``;
            production wiring MUST inject a real manager (mirrors the
            contract documented in ``mahavishnu/mcp/auth.py``).
    """

    def _pipeline_status() -> dict[str, Any]:
        if pipeline_service is None:
            return {"available": False, "error": "Learning pipeline service not initialized"}
        return {
            "available": True,
            "is_running": pipeline_service.is_running,
            "cycle_count": pipeline_service.cycle_count,
            "total_drafts": pipeline_service.total_drafts,
            "last_cycle": pipeline_service.last_result.model_dump(mode="json")
            if pipeline_service.last_result
            else None,
        }

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=MCPPermission.READ,
    )
    async def get_pipeline_status(user_id: str | None = None) -> dict[str, Any]:
        """Get current learning pipeline status including running state, cycle count, and last result."""
        return _pipeline_status()

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=MCPPermission.READ,
    )
    async def list_evidence(
        query: str = "",
        limit: int = 20,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """List stored learning evidence, optionally filtered by a search query."""
        if evidence_store is None:
            return {"available": False, "error": "Evidence store not initialized"}
        try:
            results = await evidence_store.query_evidence(query, limit)
            return {
                "available": True,
                "count": len(results),
                "evidence": [e.model_dump(mode="json") for e in results],
            }
        except Exception as exc:
            logger.warning("list_evidence_failed", exc_info=True)
            return {
                "available": True,
                "error": _safe_error(exc),
                "count": 0,
                "evidence": [],
            }

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=MCPPermission.WRITE,
    )
    async def trigger_synthesis(user_id: str | None = None) -> dict[str, Any]:
        """Trigger a single learning pipeline cycle manually. Returns cycle result.

        Requires ``Permission.WRITE`` because the cycle writes evidence
        to Session-Buddy and synthesizes drafts into the in-memory
        registry. Activation of any synthesized skill remains
        human-gated (see ADR 012).
        """
        if pipeline_service is None:
            return {"available": False, "error": "Learning pipeline service not initialized"}
        try:
            result = await pipeline_service.run_once()
            return {
                "available": True,
                "cycle_result": result.model_dump(mode="json"),
            }
        except Exception as exc:
            logger.warning("trigger_synthesis_failed", exc_info=True)
            return {"available": True, "error": _safe_error(exc)}

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=MCPPermission.READ,
    )
    async def list_pending_drafts(user_id: str | None = None) -> dict[str, Any]:
        """List all active skill drafts in the registry."""
        if skill_registry is None:
            return {"available": False, "error": "Skill registry not initialized"}
        try:
            active = skill_registry.list_active()
            return {
                "available": True,
                "count": len(active),
                "drafts": [
                    {
                        "skill_id": r.skill_id,
                        "version": r.version,
                        "state": r.state,
                        "body": r.body[:500] if r.body else None,
                    }
                    for r in active
                ],
            }
        except Exception as exc:
            logger.warning("list_pending_drafts_failed", exc_info=True)
            return {
                "available": True,
                "error": _safe_error(exc),
                "count": 0,
                "drafts": [],
            }

    @mcp.tool()
    @require_mcp_auth(
        rbac_manager=rbac_manager,
        required_permission=MCPPermission.READ,
    )
    async def get_promotion_history(
        skill_id: str, user_id: str | None = None
    ) -> dict[str, Any]:
        """Get version and promotion history for a specific skill."""
        if skill_registry is None:
            return {"available": False, "error": "Skill registry not initialized"}
        try:
            history = skill_registry.list_history(skill_id)
            return {
                "available": True,
                "skill_id": skill_id,
                "count": len(history),
                "history": [
                    {
                        "version": r.version,
                        "state": r.state,
                        "body": r.body[:500] if r.body else None,
                        "has_rollback": r.rollback is not None,
                    }
                    for r in history
                ],
            }
        except Exception as exc:
            logger.warning("get_promotion_history_failed", exc_info=True)
            return {
                "available": True,
                "error": _safe_error(exc),
                "skill_id": skill_id,
                "count": 0,
                "history": [],
            }
