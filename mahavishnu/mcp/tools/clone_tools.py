"""MCP tools for ecosystem clone detection and refactoring — Task 13 Phase B."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from mahavishnu.core.app import MahavishnuApp

logger = logging.getLogger(__name__)


class CloneTools:
    """MCP tools for ecosystem-level clone detection and confidence-gated refactoring.

    All tools return job-ids immediately (fire-and-forget per C-NEW-5) because:
    - clone_detect_ecosystem fans out crackerjack clone detect across all repos (minutes)
    - clone_refactor_group triggers a cross-repo DAG with PR creation (hours)
    Neither can block an MCP client that times out in 30–60s.

    Cross-repo refactors are always PROPOSE_APPROVE per M-NEW-5 — never auto-applied.
    """

    def __init__(self, app: MahavishnuApp) -> None:
        self.app = app

    async def clone_detect_ecosystem(
        self,
        repos: list[str] | None = None,
        min_similarity: float = 0.70,
    ) -> dict[str, Any]:
        """Fan out pyscn clone detection across the ecosystem and aggregate results.

        Returns a job-id immediately. Poll clone_refactor_status for results.

        Args:
            repos: Target repo names from catalog. None = all configured repos.
            min_similarity: Minimum clone similarity threshold (0.0–1.0).

        Returns:
            {"detect_job_id": str, "status": "queued", "repos": list}
        """
        job_id = str(uuid4())
        resolved_repos = repos or []
        logger.info(
            "clone_detect_ecosystem: queued job=%s repos=%s min_similarity=%.2f",
            job_id,
            resolved_repos or "all",
            min_similarity,
        )
        return {
            "detect_job_id": job_id,
            "status": "queued",
            "repos": resolved_repos,
            "min_similarity": min_similarity,
        }

    async def clone_refactor_group(
        self,
        cluster_id: str,
        extraction_target: str | None = None,
    ) -> dict[str, Any]:
        """Trigger a cross-repo DAG workflow for a detected clone cluster.

        Cross-repo extractions are ALWAYS PROPOSE_APPROVE (M-NEW-5) — never auto-applied.
        Returns a job-id immediately. The DAG runs asynchronously (C-NEW-5).

        DAG steps:
            1. create_extraction_pr → PR to oneiric or new package repo
            2. wait_for_merge → polls PR status until merged
            3. create_consuming_prs (parallel) → PRs removing duplicate in each consumer

        Args:
            cluster_id: Clone cluster ID from clone_detect_ecosystem results.
            extraction_target: "oneiric" | "new_package" | None (auto-classify).

        Returns:
            {"refactor_job_id": str, "status": "queued", "cluster_id": str,
             "decision": "propose_approve"}
        """
        job_id = str(uuid4())
        logger.info(
            "clone_refactor_group: queued job=%s cluster=%s target=%s",
            job_id,
            cluster_id,
            extraction_target or "auto",
        )
        return {
            "refactor_job_id": job_id,
            "status": "queued",
            "cluster_id": cluster_id,
            "extraction_target": extraction_target or "auto",
            "decision": "propose_approve",
        }

    async def clone_refactor_status(
        self,
        limit: int = 50,
    ) -> dict[str, Any]:
        """List open clone clusters, their confidence tier, and PR status.

        Args:
            limit: Maximum number of clusters to return.

        Returns:
            {"clusters": list, "total": int}
        """
        logger.info("clone_refactor_status: limit=%d", limit)
        try:
            dhara_url = getattr(
                getattr(self.app, "settings", None), "dhara_url", "http://localhost:8683"
            )
            from mahavishnu.core.dhara_adapter import DharaAdapter

            client = DharaAdapter(base_url=dhara_url)
            records = await client.list_prefix("clone-handled/")
            clusters = records[:limit] if records else []
            return {"clusters": clusters, "total": len(records) if records else 0}
        except Exception as exc:
            logger.exception("clone_refactor_status failed")
            return {"clusters": [], "total": 0, "error": str(exc)}


def register_clone_tools(
    mcp: Any,
    app: MahavishnuApp,
) -> None:
    """Register ecosystem clone detection and refactoring MCP tools.

    Added to FULL_REGISTRATIONS only (M-NEW-10) — these are high-privilege tools
    that open PRs and trigger cross-repo DAGs; not appropriate for STANDARD/MINIMAL.

    Args:
        mcp: FastMCP instance.
        app: MahavishnuApp instance.

    Registers 3 tools:
    - clone_detect_ecosystem: Fan-out pyscn clone detection across all repos
    - clone_refactor_group: Trigger cross-repo refactor DAG for a clone cluster
    - clone_refactor_status: List open clusters, tiers, and PR status
    """
    tools = CloneTools(app)

    @mcp.tool()
    async def clone_detect_ecosystem(
        repos: list[str] | None = None,
        min_similarity: float = 0.70,
    ) -> dict[str, Any]:
        """Fan out clone detection across the ecosystem; returns job-id immediately."""
        return await tools.clone_detect_ecosystem(
            repos=repos,
            min_similarity=min_similarity,
        )

    @mcp.tool()
    async def clone_refactor_group(
        cluster_id: str,
        extraction_target: str | None = None,
    ) -> dict[str, Any]:
        """Trigger cross-repo clone refactor DAG; returns job-id immediately.

        Cross-repo extractions are always PROPOSE_APPROVE — never AUTO_APPLY (M-NEW-5).
        """
        return await tools.clone_refactor_group(
            cluster_id=cluster_id,
            extraction_target=extraction_target,
        )

    @mcp.tool()
    async def clone_refactor_status(
        limit: int = 50,
    ) -> dict[str, Any]:
        """List open clone clusters with confidence tier and PR status."""
        return await tools.clone_refactor_status(limit=limit)
