"""MCP tools for the governed learning pipeline (read-only).

All tools are observation-only: no approve/reject/promote/rollback
operations are exposed via MCP.  Human review is mandatory.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

logger = logging.getLogger(__name__)


def register_learning_tools(
    mcp: FastMCP,
    pipeline_service: Any | None = None,
    evidence_store: Any | None = None,
    skill_registry: Any | None = None,
) -> None:
    """Register read-only learning pipeline tools.

    Args:
        mcp: FastMCP instance.
        pipeline_service: LearningPipelineService, if initialized.
        evidence_store: EvidenceStore, if initialized.
        skill_registry: SkillRegistry, if initialized.
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
    async def get_pipeline_status() -> dict[str, Any]:
        """Get current learning pipeline status including running state, cycle count, and last result."""
        return _pipeline_status()

    @mcp.tool()
    async def list_evidence(query: str = "", limit: int = 20) -> dict[str, Any]:
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
            return {"available": True, "error": str(exc), "count": 0, "evidence": []}

    @mcp.tool()
    async def trigger_synthesis() -> dict[str, Any]:
        """Trigger a single learning pipeline cycle manually. Returns cycle result."""
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
            return {"available": True, "error": str(exc)}

    @mcp.tool()
    async def list_pending_drafts() -> dict[str, Any]:
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
            return {"available": True, "error": str(exc), "count": 0, "drafts": []}

    @mcp.tool()
    async def get_promotion_history(skill_id: str) -> dict[str, Any]:
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
            return {"available": True, "error": str(exc), "skill_id": skill_id, "count": 0, "history": []}
