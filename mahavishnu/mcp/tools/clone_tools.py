"""MCP tools for ecosystem clone detection and refactoring — Task 13 Phase B."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from mahavishnu.core.loop_helpers import detect_until_dry as _detect_until_dry
from mahavishnu.core.state_backends.mcp import MCPStateBackend, MCPStateConfig
from mahavishnu.core.verification import (
    Consensus,
    Proposal,
    VerificationStore,
    build_default_store,
    is_verification_enabled,
    verify_proposal,
)
from mahavishnu.mcp.tools.clone_claims import (
    ConcurrentDAGError,
    MCPStateBackendUnavailable,
    cluster_state_claim,
    release_cluster_claim,
)
from mahavishnu.workflows.clone_refactor_workflow import run_clone_refactor_dag

if TYPE_CHECKING:
    from mahavishnu.core.app import MahavishnuApp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UUID7 (Change A). pyproject.toml pins >=3.14, so `from uuid import uuid7`
# is unconditional on supported interpreters.
# ---------------------------------------------------------------------------

from uuid import uuid7 as _new_uuid7

# ---------------------------------------------------------------------------
# Module-level MCPStateBackend singleton (Change B).
#
# Contract: every code path in clone_tools.py, clone_claims.py, and the
# run_clone_refactor_dag @flow MUST see the same MCPStateBackend instance so
# circuit-breaker state stays consistent (REQ-CLONE-014 reliability, per
# spec §6.1 v4 MAJOR-fix M2). Tests monkeypatch this module attribute;
# production rebuilds it via register_clone_tools() → _build_mcp_backend().
#
# CE-B2 fix: `app.mcp_url` (resolved at core/app.py:248 from
# health.dependencies.mcp.{host,port}) is the canonical source for the URL.
# `MCPStatePersistenceConfig` has extra="forbid" — only the three timing
# fields are valid in settings.
# ---------------------------------------------------------------------------


def _build_mcp_backend(app: Any | None = None) -> MCPStateBackend:
    """Build the module-level MCPStateBackend singleton.

    Used at module load (with `app=None`) for the default singleton, and
    by register_clone_tools() (with `app`) for production reconfiguration.
    Tests monkeypatch the resulting `mcp_backend` module attribute.
    """
    url = (
        getattr(app, "mcp_url", "http://localhost:8683")
        if app is not None
        else "http://localhost:8683"
    )
    settings = getattr(app, "settings", None) if app is not None else None
    mcp_state_cfg = getattr(settings, "mcp_state", None) if settings is not None else None
    return MCPStateBackend(
        base_url=url,
        config=MCPStateConfig(
            enabled=getattr(mcp_state_cfg, "enabled", True) if mcp_state_cfg else True,
            flush_interval_seconds=getattr(mcp_state_cfg, "flush_interval_seconds", 60)
            if mcp_state_cfg
            else 60,
            max_routing_buffer_age_seconds=(
                getattr(mcp_state_cfg, "max_routing_buffer_age_seconds", 3600)
                if mcp_state_cfg
                else 3600
            ),
        ),
    )


mcp_backend: MCPStateBackend = _build_mcp_backend()


# ---------------------------------------------------------------------------
# cluster_id normalization regex (Change C) — REQ-CLONE-015
# ---------------------------------------------------------------------------

CLUSTER_ID_RE = re.compile(r"^[a-z0-9-]{3,64}$")


# ---------------------------------------------------------------------------
# Strong reference for fire-and-forget tasks (SF-B2).
#
# `asyncio.create_task()` returns a task that the event loop holds a WEAK
# reference to. Without a strong reference held in module scope, the task
# may be garbage-collected mid-execution before the @flow body runs.
# ---------------------------------------------------------------------------

_background_tasks: set[asyncio.Task] = set()


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
        # Lazily construct a store wired to the configured MCP backend if
        # the caller didn't inject one (tests inject a fake; production passes
        # nothing and gets the default-MCP-backed store).
        self._store: VerificationStore | None = store
        if self._store is None and getattr(app, "settings", None) is not None:
            self._store = build_default_store(app)

    @staticmethod
    def _validate_clone_refactor_inputs(
        cluster_id: str,
        target_repo: str,
        extracted_symbol: str,
    ) -> None:
        """Validate ingress args for clone_refactor_group.

        Raises ValueError on invalid_cluster_id or null-byte input
        (REQ-CLONE-015). Pure sync check — extracted from
        ``clone_refactor_group`` to drop its cyclomatic complexity.
        """
        if not CLUSTER_ID_RE.match(cluster_id):
            raise ValueError(f"invalid_cluster_id: {cluster_id!r}")
        for arg_name, arg_val in (
            ("cluster_id", cluster_id),
            ("target_repo", target_repo),
            ("extracted_symbol", extracted_symbol),
        ):
            if "\x00" in arg_val:
                raise ValueError(f"invalid_{arg_name}: contains null byte")

    @staticmethod
    async def _run_verification_gate(
        proposal: Proposal,
        app: Any,
        store: Any | None,
    ) -> tuple[VerificationResult, dict[str, Any], str]:
        """Run verify_proposal and return (result, payload, decision).

        ``decision`` is "propose_approve" or "blocked_by_verification".
        On REJECT, the caller is responsible for releasing the cluster
        claim — this helper does NOT touch the claim (separation of
        concerns; the same caller code path handles REJECT and
        exception-driven cleanup).

        Extracted from ``clone_refactor_group`` to drop its cyclomatic
        complexity; the verification gate has its own decision tree
        (verify → persist → REJECT?) that does not need to live inline.
        """
        verification_result = await verify_proposal(proposal)
        if store is not None:
            verification_result = await store.persist(verification_result)
        verification_payload = verification_result.model_dump(mode="json")
        decision = "propose_approve"
        if (
            is_verification_enabled(app)
            and verification_result.consensus == Consensus.REJECT
        ):
            decision = "blocked_by_verification"
        return verification_result, verification_payload, decision

    @staticmethod
    async def _cleanup_on_failure(
        claim_acquired: bool,
        mcp_backend: MCPStateBackend,
        cluster_id: str,
    ) -> None:
        """Release the cluster claim if we held it.

        Used by every except arm that fires AFTER ``claim_acquired``
        was set, plus the REJECT early-return path. Mirrors the
        post-claim claim-release discipline (REQ-CLONE-001 +
        REQ-CLONE-016 semantics) so the body of ``clone_refactor_group``
        reads as a linear flow.
        """
        if claim_acquired:
            await release_cluster_claim(mcp_backend, cluster_id)

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
        target_repo: str,
        consumer_repos: list[str],
        extracted_symbol: str,
        extraction_diff: str,
        consuming_diffs: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Trigger a cross-repo DAG workflow for a detected clone cluster.

        Cross-repo extractions are ALWAYS PROPOSE_APPROVE (M-NEW-5) — never auto-applied.
        Returns a job-id immediately. The DAG runs asynchronously (C-NEW-5).

        DAG steps:
            1. detect_cluster_members → target repo + consumers
            2. write_canonical_symbol → commit extraction in target repo
            3. write_replacement_diff (parallel) → commit removal in each consumer
            4. persist_dag_state → final workflow/v1/{refactor_job_id} record

        Phase 1 (Task 1.3): runs ``verify_proposal`` BEFORE returning the
        job-id. The serialized ``VerificationResult`` is included as the
        ``verification`` field of the response so reviewers can see refuter
        disagreement. When ``verification_enabled=True`` AND consensus=REJECT,
        the ``decision`` field flips from ``"propose_approve"`` to
        ``"blocked_by_verification"``.

        REQ-CLONE-007: refactor_job_id is UUIDv7 (time-sortable).
        REQ-CLONE-009: cluster_state_claim dedups concurrent invocations.
        REQ-CLONE-015: cluster_id must match ^[a-z0-9-]{3,64}$.
        REQ-CLONE-016: cancellation must mark terminal state.

        Args:
            cluster_id: Clone cluster ID from clone_detect_ecosystem results.
                Validated against ^[a-z0-9-]{3,64}$ (REQ-CLONE-015).
            target_repo: Filesystem path of the repo that owns the canonical symbol.
            consumer_repos: Filesystem paths of repos that import the symbol.
            extracted_symbol: Fully-qualified symbol being extracted.
            extraction_diff: Unified diff to apply to target_repo (canonical write).
            consuming_diffs: Optional per-consumer diffs. Missing entry → consumer
                marked failed with MissingConsumingDiff.

        Returns:
            {"refactor_job_id": str, "status": "queued", "cluster_id": str,
             "decision": "propose_approve" | "blocked_by_verification",
             "verification": dict (serialized VerificationResult)}

        Raises:
            ValueError: invalid_cluster_id or null-byte input (REQ-CLONE-015).
            ConcurrentDAGError: another DAG already holds the cluster claim (REQ-CLONE-009).
            MCPStateBackendUnavailable: substrate circuit is open (REQ-CLONE-014).
            asyncio.CancelledError: client cancelled mid-flight (REQ-CLONE-016).
        """
        # Change C: cluster_id normalization (REQ-CLONE-015) +
        # SF-m4: reject null bytes in ingress args
        self._validate_clone_refactor_inputs(cluster_id, target_repo, extracted_symbol)

        # Change D: UUID7 (REQ-CLONE-007) — time-sortable, lexicographic
        refactor_job_id = str(_new_uuid7())
        logger.info(
            "clone_refactor_group: queued job=%s cluster=%s target=%s",
            refactor_job_id,
            cluster_id,
            target_repo,
        )

        # Change E: claim FIRST, then verify, then either DAG or REJECT-release.
        # Acquiring before verify_proposal ensures REJECT and cancellation
        # both flow through the same claim-release path (REQ-CLONE-001 +
        # REQ-CLONE-016 semantics). The cost is briefly holding the claim
        # while we run the refuter (sub-second), which is acceptable.
        # C-2/SF-B1: wrap the entire post-claim section in one try/except
        # that releases the claim on ANY error/cancellation.
        claim_acquired = False
        try:
            # REQ-CLONE-009: cluster-claim dedup
            await cluster_state_claim(mcp_backend, cluster_id, refactor_job_id)
            claim_acquired = True

            # Phase 1 (Task 1.3): verify_proposal before spawning DAG.
            # See ``_run_verification_gate`` for the REJECT decision tree.
            proposal = Proposal(
                proposal_id=refactor_job_id,
                proposal_type="clone_refactor",
                subject=cluster_id,
                details={
                    "target_repo": target_repo,
                    "extracted_symbol": extracted_symbol,
                    "refactor_job_id": refactor_job_id,
                },
            )
            _, verification_payload, decision = await self._run_verification_gate(
                proposal, self.app, self._store
            )
            if decision == "blocked_by_verification":
                # REQ-CLONE-001: REJECT blocks DAG. Release claim, return early.
                await self._cleanup_on_failure(claim_acquired, mcp_backend, cluster_id)
                claim_acquired = False
                return {
                    "refactor_job_id": refactor_job_id,
                    "status": "queued",
                    "cluster_id": cluster_id,
                    "decision": decision,
                    "verification": verification_payload,
                }

            # REQ-CLONE-007: initial DAG state write
            await mcp_backend.put(
                mcp_backend.dag_key(refactor_job_id),
                {
                    "schema_version": 2,
                    "refactor_job_id": refactor_job_id,
                    "cluster_id": cluster_id,
                    "status": "queued",
                },
            )

            # Fire DAG (SF-B2: strong reference + add_done_callback)
            task_obj = asyncio.create_task(
                run_clone_refactor_dag(
                    refactor_job_id=refactor_job_id,
                    cluster_id=cluster_id,
                    mcp_backend=mcp_backend,
                    target_repo=target_repo,
                    consumer_repos=consumer_repos,
                    extracted_symbol=extracted_symbol,
                    extraction_diff=extraction_diff,
                    consuming_diffs=consuming_diffs,
                ),
                name=f"clone-refactor-{refactor_job_id}",
            )
            _background_tasks.add(task_obj)
            task_obj.add_done_callback(_background_tasks.discard)

            return {
                "refactor_job_id": refactor_job_id,
                "status": "queued",
                "cluster_id": cluster_id,
                "decision": decision,
                "verification": verification_payload,
            }

        except asyncio.CancelledError:
            # SF-B1: cancellation anywhere after claim acquisition; release.
            await self._cleanup_on_failure(claim_acquired, mcp_backend, cluster_id)
            raise
        except (ConcurrentDAGError, MCPStateBackendUnavailable):
            # ConcurrentDAGError: claim rejected by cluster_state_claim (sentinel
            # owned by another job) — we never acquired, no release.
            # MCPStateBackendUnavailable (SF-M6): surface to MCP client as 503;
            # cluster_claim raised before the sentinel was overwritten — no claim.
            # Both paths share "raise without cleanup".
            raise
        except Exception:
            # Any other exception: release claim (if acquired) before re-raising.
            await self._cleanup_on_failure(claim_acquired, mcp_backend, cluster_id)
            raise

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
        limit: int = 10,
    ) -> list[tuple[str, dict[str, Any]]]:
        """List in-flight DAG states for clone-refactor jobs.

        Reads from the canonical ``workflow/v1/*`` prefix via the module-level
        ``mcp_backend`` singleton (consistent circuit-breaker state). Sorted by
        UUIDv7 lexicographic order (UUIDv7 is time-sortable → lexicographic
        equals chronological). Most recent first.

        Args:
            limit: Maximum number of records to return.

        Returns:
            ``list[tuple[str, dict[str, Any]]]`` — list of ``(key, value)``
            pairs. Empty list on substrate failure (silently, since this is
            an operator-status query, not a critical-path write).
        """
        logger.info("clone_refactor_status: limit=%d", limit)
        # CR-B2: list[tuple[str, dict]] (was `list[dict]`). MCPStateBackend
        # .list_prefix() returns list[tuple[str, dict]] per the CR-m6 test
        # in tests/unit/test_mcp_state_backend.py::TestListPrefixReturnShape.
        # CA-B2: list_prefix(self, prefix) does NOT accept a `limit` param;
        # slice in Python.
        try:
            records = await mcp_backend.list_prefix("workflow/v1/")
            # Sort by UUID7 lexicographically (newest first).
            return sorted(records, key=lambda kv: kv[0], reverse=True)[:limit]
        except Exception as exc:  # noqa: BLE001
            logger.warning("clone_refactor_status: list_prefix failed (%s); returning []", exc)
            return []


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
            When omitted, ``CloneTools`` builds a MCP-backed store from
            ``app.settings``. Tests inject a fake store here.

    Registers 4 tools:
    - clone_detect_ecosystem: Fan-out pyscn clone detection across all repos
    - clone_refactor_group: Trigger cross-repo refactor DAG for a clone cluster
      (runs ``verify_proposal`` before returning the job-id per Task 1.3)
    - clone_refactor_status: List in-flight DAG records (sorted by UUID7)
    - get_verification_result: Fetch a stored ``VerificationResult`` by
      proposal_id (per Task 1.5)
    """
    # CE-B2: reconfigure the module-level `mcp_backend` singleton using
    # `app.mcp_url` so the production substrate URL wins over the default.
    # Tests bypass this path (they never call register_clone_tools) and
    # monkeypatch the `mcp_backend` module attribute instead.
    global mcp_backend
    mcp_backend = _build_mcp_backend(app)

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
        target_repo: str,
        consumer_repos: list[str],
        extracted_symbol: str,
        extraction_diff: str,
        consuming_diffs: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Trigger cross-repo clone refactor DAG; returns job-id immediately.

        Cross-repo extractions are always PROPOSE_APPROVE — never AUTO_APPLY (M-NEW-5).
        A diverse-refuter ``verify_proposal`` runs before the job-id is
        returned; the response carries a ``verification`` field with refuter
        verdicts, aggregated consensus, and a ``persisted`` flag.

        REQ-CLONE-007: refactor_job_id is UUIDv7.
        REQ-CLONE-009: cluster_state_claim dedups concurrent calls.
        REQ-CLONE-015: cluster_id must match ^[a-z0-9-]{3,64}$.
        """
        return await tools.clone_refactor_group(
            cluster_id=cluster_id,
            target_repo=target_repo,
            consumer_repos=consumer_repos,
            extracted_symbol=extracted_symbol,
            extraction_diff=extraction_diff,
            consuming_diffs=consuming_diffs,
        )

    @mcp.tool()
    async def clone_refactor_status(
        limit: int = 10,
    ) -> list[tuple[str, dict[str, Any]]]:
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
