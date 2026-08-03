"""MCP tools for ecosystem clone detection and refactoring — Task 13 Phase B."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from mahavishnu.core.loop_helpers import detect_until_dry as _detect_until_dry
from mahavishnu.core.verification import (
    Consensus,
    Proposal,
    VerificationStore,
    build_default_store,
    is_verification_enabled,
    verify_proposal,
)

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

    Phase 1 (per docs/plans/2026-07-11-ultracode-integration-wiring.md §5 Task 1.3):
    ``clone_refactor_group`` runs a diverse-refuter ``verify_proposal`` BEFORE
    returning the job-id. The serialized ``VerificationResult`` is returned in
    the ``verification`` field so reviewers see refuter disagreement. When
    ``verification_enabled=True`` in settings AND consensus=REJECT, the
    ``decision`` field flips to ``"blocked_by_verification"`` instead of the
    default ``"propose_approve"``.
    """

    def __init__(
        self,
        app: MahavishnuApp,
        store: VerificationStore | None = None,
    ) -> None:
        self.app = app
        # Lazily construct a store wired to the configured Dhara backend if
        # the caller didn't inject one (tests inject a fake; production passes
        # nothing and gets the default-Dhara-backed store).
        self._store: VerificationStore | None = store
        if self._store is None and getattr(app, "settings", None) is not None:
            self._store = build_default_store(app)

    async def _scan_repos_for_clones(
        self,
        repos: list[str] | None,
        min_similarity: float,
    ) -> list[dict[str, Any]]:
        """Stub scan function — returns an empty list of clone findings.

        Phase 2 Task 2.2: this stub will be replaced by the real pyscn
        fan-out when the underlying scan is implemented (per the plan's
        Non-Goal #1). Today it returns an empty list, which means a
        ``detect_until_dry`` loop will converge in ``k_empty_rounds``
        iterations with ``stopped_reason="converged"``. Tests that need a
        non-converging scan monkey-patch this method.

        Returns:
            A list of clone findings. Each finding must be a mapping with
            at least an ``"id"`` key (per the default ``dedup_key`` in
            :func:`mahavishnu.core.loop_helpers.detect_until_dry`).
        """
        logger.debug(
            "_scan_repos_for_clones: stub scan repos=%s min_similarity=%.2f",
            repos or "all",
            min_similarity,
        )
        return []

    async def clone_detect_ecosystem(
        self,
        repos: list[str] | None = None,
        min_similarity: float = 0.70,
        detect_until_dry: bool = False,
        k_empty_rounds: int = 2,
        max_iterations: int = 5,
    ) -> dict[str, Any]:
        """Fan out pyscn clone detection across the ecosystem and aggregate results.

        Returns a job-id immediately. Poll clone_refactor_status for results.

        Phase 2 Task 2.2: when ``detect_until_dry=True``, the (currently
        stubbed) scan function is wrapped with :func:`detect_until_dry` and
        the response carries a ``run_metadata`` field with the loop's
        iteration count, empty-round count, and stop reason. The wrapper
        is testable independently of the underlying scan stub — tests
        monkey-patch :meth:`_scan_repos_for_clones` to drive both the
        converged and max-iterations paths.

        Args:
            repos: Target repo names from catalog. None = all configured repos.
            min_similarity: Minimum clone similarity threshold (0.0–1.0).
            detect_until_dry: When True, run the scan repeatedly via
                ``detect_until_dry`` until ``k_empty_rounds`` consecutive
                rounds surface no new findings (capped at ``max_iterations``).
                When False (default), the scan is queued fire-and-forget
                per C-NEW-5 and the tool returns immediately.
            k_empty_rounds: Number of consecutive empty rounds that signal
                convergence. Forwarded to ``detect_until_dry``.
            max_iterations: Hard iteration cap. Forwarded to
                ``detect_until_dry``.

        Returns:
            When ``detect_until_dry=False``: ``{"detect_job_id": str,
            "status": "queued", "repos": list, "min_similarity": float}``.
            When ``detect_until_dry=True``: the same plus ``"dry_run": True``,
            ``"findings_count": int``, and ``"run_metadata": dict`` with
            ``iterations`` (``int``), ``empty_rounds`` (``int``), and
            ``stopped_reason`` (``str``).
        """
        job_id = str(uuid4())
        resolved_repos = repos or []
        logger.info(
            "clone_detect_ecosystem: queued job=%s repos=%s min_similarity=%.2f "
            "detect_until_dry=%s",
            job_id,
            resolved_repos or "all",
            min_similarity,
            detect_until_dry,
        )

        if not detect_until_dry:
            return {
                "detect_job_id": job_id,
                "status": "queued",
                "repos": resolved_repos,
                "min_similarity": min_similarity,
            }

        async def scan_fn() -> list[dict[str, Any]]:
            return await self._scan_repos_for_clones(resolved_repos, min_similarity)

        findings, run_metadata = await _detect_until_dry(
            scan_fn,
            k_empty_rounds=k_empty_rounds,
            max_iterations=max_iterations,
        )
        return {
            "detect_job_id": job_id,
            "status": "queued",
            "repos": resolved_repos,
            "min_similarity": min_similarity,
            "dry_run": True,
            "findings_count": len(findings),
            "run_metadata": run_metadata,
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

        Phase 1 (Task 1.3): runs ``verify_proposal`` BEFORE returning the
        job-id. The serialized ``VerificationResult`` is included as the
        ``verification`` field of the response so reviewers can see refuter
        disagreement. When ``verification_enabled=True`` AND consensus=REJECT,
        the ``decision`` field flips from ``"propose_approve"`` to
        ``"blocked_by_verification"``.

        Args:
            cluster_id: Clone cluster ID from clone_detect_ecosystem results.
            extraction_target: "oneiric" | "new_package" | None (auto-classify).

        Returns:
            {"refactor_job_id": str, "status": "queued", "cluster_id": str,
             "decision": "propose_approve" | "blocked_by_verification",
             "verification": dict (serialized VerificationResult)}
        """
        job_id = str(uuid4())
        logger.info(
            "clone_refactor_group: queued job=%s cluster=%s target=%s",
            job_id,
            cluster_id,
            extraction_target or "auto",
        )
        proposal = Proposal(
            proposal_id=job_id,
            proposal_type="clone_refactor",
            subject=cluster_id,
            details={
                "extraction_target": extraction_target or "auto",
                "refactor_job_id": job_id,
            },
        )
        verification_result = await verify_proposal(proposal)
        if self._store is not None:
            verification_result = await self._store.persist(verification_result)
        verification_payload = verification_result.model_dump(mode="json")

        decision = "propose_approve"
        if is_verification_enabled(self.app) and verification_result.consensus == Consensus.REJECT:
            decision = "blocked_by_verification"
            logger.info(
                "clone_refactor_group: decision=blocked_by_verification "
                "job=%s cluster=%s consensus=%s",
                job_id,
                cluster_id,
                verification_result.consensus.value,
            )

        return {
            "refactor_job_id": job_id,
            "status": "queued",
            "cluster_id": cluster_id,
            "extraction_target": extraction_target or "auto",
            "decision": decision,
            "verification": verification_payload,
        }

    async def get_verification_result(self, proposal_id: str) -> dict[str, Any]:
        """Return the stored ``VerificationResult`` for a given ``proposal_id``.

        Task 1.5 (per the same plan): the companion read tool for the
        verification record written by ``clone_refactor_group``. Returns
        ``{"status": "not_found"}`` when no record exists or when persistence
        was not configured.

        Args:
            proposal_id: The proposal_id (= refactor_job_id) to look up.

        Returns:
            {"proposal_id": str, "verification": dict} on hit;
            {"status": "not_found"} on miss.
        """
        if self._store is None:
            logger.info(
                "get_verification_result: no store configured; proposal_id=%s",
                proposal_id,
            )
            return {"proposal_id": proposal_id, "status": "not_found"}
        result = await self._store.get(proposal_id)
        if result is None:
            return {"proposal_id": proposal_id, "status": "not_found"}
        return {
            "proposal_id": proposal_id,
            "verification": result.model_dump(mode="json"),
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
            from mahavishnu.core.state_backends.dhara import DharaStateBackend

            client = DharaStateBackend(base_url=dhara_url)
            records = await client.list_prefix("clone-handled/")
            clusters = records[:limit] if records else []
            return {"clusters": clusters, "total": len(records) if records else 0}
        except Exception as exc:
            logger.exception("clone_refactor_status failed")
            return {"clusters": [], "total": 0, "error": str(exc)}


def register_clone_tools(
    mcp: Any,
    app: MahavishnuApp,
    store: VerificationStore | None = None,
) -> None:
    """Register ecosystem clone detection and refactoring MCP tools.

    Added to FULL_REGISTRATIONS only (M-NEW-10) — these are high-privilege tools
    that open PRs and trigger cross-repo DAGs; not appropriate for STANDARD/MINIMAL.

    Args:
        mcp: FastMCP instance.
        app: MahavishnuApp instance.
        store: Optional ``VerificationStore`` to inject into ``CloneTools``.
            When omitted, ``CloneTools`` builds a Dhara-backed store from
            ``app.settings``. Tests inject a fake store here.

    Registers 4 tools:
    - clone_detect_ecosystem: Fan-out pyscn clone detection across all repos
    - clone_refactor_group: Trigger cross-repo refactor DAG for a clone cluster
      (runs ``verify_proposal`` before returning the job-id per Task 1.3)
    - clone_refactor_status: List open clusters, tiers, and PR status
    - get_verification_result: Fetch a stored ``VerificationResult`` by
      proposal_id (per Task 1.5)
    """
    tools = CloneTools(app, store=store)

    @mcp.tool()
    async def clone_detect_ecosystem(
        repos: list[str] | None = None,
        min_similarity: float = 0.70,
        detect_until_dry: bool = False,
        k_empty_rounds: int = 2,
        max_iterations: int = 5,
    ) -> dict[str, Any]:
        """Fan out clone detection across the ecosystem; returns job-id immediately.

        Phase 2 Task 2.2: set ``detect_until_dry=True`` to wrap the
        (currently stubbed) scan with :func:`detect_until_dry`. The
        response then carries a ``run_metadata`` field with the loop's
        ``iterations``, ``empty_rounds``, and ``stopped_reason`` so
        callers can observe convergence behavior without polling.
        """
        return await tools.clone_detect_ecosystem(
            repos=repos,
            min_similarity=min_similarity,
            detect_until_dry=detect_until_dry,
            k_empty_rounds=k_empty_rounds,
            max_iterations=max_iterations,
        )

    @mcp.tool()
    async def clone_refactor_group(
        cluster_id: str,
        extraction_target: str | None = None,
    ) -> dict[str, Any]:
        """Trigger cross-repo clone refactor DAG; returns job-id immediately.

        Cross-repo extractions are always PROPOSE_APPROVE — never AUTO_APPLY (M-NEW-5).
        A diverse-refuter ``verify_proposal`` runs before the job-id is
        returned; the response carries a ``verification`` field with refuter
        verdicts, aggregated consensus, and a ``persisted`` flag.
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

    @mcp.tool()
    async def get_verification_result(
        proposal_id: str,
    ) -> dict[str, Any]:
        """Return the stored ``VerificationResult`` for a given ``proposal_id``.

        Returns ``{"status": "not_found"}`` when no record exists or when the
        VerificationStore was not configured (see Task 1.5). The proposal_id
        is the same UUID as the ``refactor_job_id`` returned by
        ``clone_refactor_group``.
        """
        return await tools.get_verification_result(proposal_id=proposal_id)
