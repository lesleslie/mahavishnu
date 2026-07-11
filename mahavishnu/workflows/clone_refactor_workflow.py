# Workflow-ID: 01JCLONEREF2026
# Approved by: les
"""Prefect DAG workflow for cross-repo clone extraction — Task 13 Phase B.

Orchestrates the ordered PR creation sequence for ecosystem clone refactoring:

    Step 1: create_extraction_pr  → open PR in the extraction target repo
                                    (oneiric or a new shared package)
    Step 2: wait_for_merge        → poll PR status until merged (with timeout)
    Step 3: create_consuming_prs  → open PRs in all consuming repos in parallel,
                                    gated on Step 1 merge completion

Cross-repo extractions are ALWAYS PROPOSE_APPROVE per M-NEW-5: no step
here auto-merges — all PRs require human review and approval.

If the extraction PR is closed (not merged), all consuming PRs are
cancelled to prevent a half-migrated ecosystem state (M-NEW-7).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Poll interval and ceiling for wait_for_merge
_POLL_INTERVAL_S = 60
_POLL_TIMEOUT_S = 3600  # 1 hour


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ExtractionPR:
    pr_url: str
    repo: str
    status: str = "open"  # open | merged | closed


@dataclass
class ConsumingPR:
    pr_url: str
    repo: str
    status: str = "open"


@dataclass
class CloneRefactorResult:
    cluster_id: str
    extraction_pr: ExtractionPR | None
    consuming_prs: list[ConsumingPR] = field(default_factory=list)
    cancelled: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Task implementations (pure async functions, importable by Prefect @task)
# ---------------------------------------------------------------------------


async def create_extraction_pr(
    cluster_id: str,
    target_repo: str,
    extracted_symbol: str,
    diff: str,
    gh_client: Any | None = None,
) -> ExtractionPR:
    """Open a PR in the extraction target repo.

    In production, `gh_client` is the GitHub REST client. In tests, it is mocked.
    When `gh_client` is None, this stub records intent without network I/O.

    Args:
        cluster_id: Clone cluster being extracted.
        target_repo: Repo receiving the extracted symbol (e.g. "oneiric").
        extracted_symbol: Function/class name being extracted.
        diff: Unified diff to apply.
        gh_client: Optional GitHub client (None = dry-run stub).

    Returns:
        ExtractionPR with open status.
    """
    logger.info(
        "clone_refactor_workflow: create_extraction_pr cluster=%s target=%s symbol=%s",
        cluster_id,
        target_repo,
        extracted_symbol,
    )

    if gh_client is None:
        stub_url = f"https://github.com/{target_repo}/pulls/stub/{cluster_id[:8]}"
        logger.info("create_extraction_pr: no gh_client — returning stub PR %s", stub_url)
        return ExtractionPR(pr_url=stub_url, repo=target_repo, status="open")

    try:
        result = await gh_client.create_pr(
            repo=target_repo,
            title=f"refactor: extract clone cluster {cluster_id[:8]} → {extracted_symbol}",
            body=(
                f"Clone cluster `{cluster_id}` detected across multiple repos.\n\n"
                f"This PR extracts `{extracted_symbol}` to `{target_repo}` as the canonical "
                f"implementation. Consuming repos will follow in separate PRs once this merges."
            ),
            diff=diff,
        )
        return ExtractionPR(pr_url=result["html_url"], repo=target_repo, status="open")
    except Exception as exc:
        logger.exception("create_extraction_pr: failed for cluster %s", cluster_id)
        raise RuntimeError(f"Failed to create extraction PR: {exc}") from exc


async def wait_for_merge(
    pr: ExtractionPR,
    gh_client: Any | None = None,
    poll_interval: int = _POLL_INTERVAL_S,
    timeout: int = _POLL_TIMEOUT_S,
) -> ExtractionPR:
    """Poll PR status until merged or closed, with timeout.

    Raises RuntimeError on timeout (> timeout seconds waiting).
    Returns with status="merged" on success or status="closed" if the PR was closed.

    Args:
        pr: The extraction PR to watch.
        gh_client: GitHub client (None = stub, immediately returns merged).
        poll_interval: Seconds between status polls.
        timeout: Maximum wait in seconds before raising RuntimeError.

    Returns:
        ExtractionPR updated with current status.
    """
    if gh_client is None:
        logger.info("wait_for_merge: no gh_client — stub returns merged immediately")
        return ExtractionPR(pr_url=pr.pr_url, repo=pr.repo, status="merged")

    elapsed = 0
    while elapsed < timeout:
        try:
            status = await gh_client.get_pr_status(pr.pr_url)
        except Exception as exc:
            logger.warning("wait_for_merge: status poll failed: %s", exc)
            status = "unknown"

        if status == "merged":
            logger.info("wait_for_merge: PR merged — %s", pr.pr_url)
            return ExtractionPR(pr_url=pr.pr_url, repo=pr.repo, status="merged")

        if status == "closed":
            logger.warning("wait_for_merge: PR closed (not merged) — %s", pr.pr_url)
            return ExtractionPR(pr_url=pr.pr_url, repo=pr.repo, status="closed")

        await asyncio.sleep(poll_interval)
        elapsed += poll_interval

    raise RuntimeError(f"wait_for_merge: timed out after {timeout}s waiting for {pr.pr_url}")


async def create_consuming_pr(
    cluster_id: str,
    consumer_repo: str,
    extracted_symbol: str,
    extraction_target_repo: str,
    diff: str,
    gh_client: Any | None = None,
) -> ConsumingPR:
    """Open a single consuming PR to remove the duplicate and import from extraction target.

    Args:
        cluster_id: Clone cluster being resolved.
        consumer_repo: Repo that contains a duplicate and needs updating.
        extracted_symbol: The extracted function/class name.
        extraction_target_repo: The repo now owning the canonical implementation.
        diff: Unified diff removing the duplicate + adding the import.
        gh_client: GitHub client (None = stub).

    Returns:
        ConsumingPR with open status.
    """
    logger.info(
        "clone_refactor_workflow: create_consuming_pr cluster=%s consumer=%s",
        cluster_id,
        consumer_repo,
    )

    if gh_client is None:
        stub_url = f"https://github.com/{consumer_repo}/pulls/stub/{cluster_id[:8]}"
        return ConsumingPR(pr_url=stub_url, repo=consumer_repo, status="open")

    try:
        result = await gh_client.create_pr(
            repo=consumer_repo,
            title=f"refactor: use {extracted_symbol} from {extraction_target_repo}",
            body=(
                f"Clone cluster `{cluster_id}` has been extracted to "
                f"`{extraction_target_repo}.{extracted_symbol}`.\n\n"
                f"This PR removes the local duplicate and imports from the new canonical location."
            ),
            diff=diff,
        )
        return ConsumingPR(pr_url=result["html_url"], repo=consumer_repo, status="open")
    except Exception as exc:
        logger.exception(
            "create_consuming_pr: failed for cluster %s consumer %s", cluster_id, consumer_repo
        )
        raise RuntimeError(f"Failed to create consuming PR in {consumer_repo}: {exc}") from exc


# ---------------------------------------------------------------------------
# Top-level DAG entrypoint
# ---------------------------------------------------------------------------


async def run_clone_refactor_dag(
    cluster_id: str,
    target_repo: str,
    consumer_repos: list[str],
    extracted_symbol: str,
    extraction_diff: str,
    consuming_diffs: dict[str, str] | None = None,
    gh_client: Any | None = None,
) -> CloneRefactorResult:
    """Run the 3-step cross-repo clone refactor DAG.

    Step ordering (M-NEW-7 rollback strategy):
        1. create_extraction_pr → PR in target repo (oneiric / new package)
        2. wait_for_merge       → block until merged (or handle closed)
        3. create_consuming_prs → parallel PRs in all consumer repos

    If Step 2 returns status="closed": cancel all consuming PRs (never open
    them) to keep the ecosystem in a consistent state.

    Args:
        cluster_id: Unique clone cluster ID.
        target_repo: Extraction target (e.g. "oneiric" or "my-shared-pkg").
        consumer_repos: Repos that contain the duplicate and need updating.
        extracted_symbol: Function/class name extracted.
        extraction_diff: Diff for the extraction PR.
        consuming_diffs: Per-repo diffs for consuming PRs (None = same diff for all).
        gh_client: GitHub client (None = stub mode for tests).

    Returns:
        CloneRefactorResult with PR details and status.
    """
    result = CloneRefactorResult(cluster_id=cluster_id, extraction_pr=None)

    # Step 1: create extraction PR
    try:
        extraction_pr = await create_extraction_pr(
            cluster_id=cluster_id,
            target_repo=target_repo,
            extracted_symbol=extracted_symbol,
            diff=extraction_diff,
            gh_client=gh_client,
        )
        result.extraction_pr = extraction_pr
    except Exception as exc:
        result.error = f"create_extraction_pr failed: {exc}"
        logger.exception("run_clone_refactor_dag: Step 1 failed for cluster %s", cluster_id)
        return result

    # Step 2: wait for merge
    try:
        merged_pr = await wait_for_merge(extraction_pr, gh_client=gh_client)
    except RuntimeError as exc:
        result.error = str(exc)
        return result

    if merged_pr.status == "closed":
        logger.warning(
            "run_clone_refactor_dag: extraction PR closed for cluster %s — "
            "cancelling all consuming PRs",
            cluster_id,
        )
        result.extraction_pr = merged_pr
        result.cancelled = True
        return result

    result.extraction_pr = merged_pr

    # Step 3: create consuming PRs in parallel (gated on extraction merge)
    consuming_tasks = [
        create_consuming_pr(
            cluster_id=cluster_id,
            consumer_repo=repo,
            extracted_symbol=extracted_symbol,
            extraction_target_repo=target_repo,
            diff=(consuming_diffs or {}).get(repo, extraction_diff),
            gh_client=gh_client,
        )
        for repo in consumer_repos
    ]
    consuming_results = await asyncio.gather(*consuming_tasks, return_exceptions=True)

    for repo, pr_or_exc in zip(consumer_repos, consuming_results, strict=False):
        if isinstance(pr_or_exc, BaseException):
            logger.warning(
                "run_clone_refactor_dag: consuming PR failed for %s: %s", repo, pr_or_exc
            )
        else:
            result.consuming_prs.append(pr_or_exc)

    logger.info(
        "run_clone_refactor_dag: complete cluster=%s extraction=%s consuming=%d/%d",
        cluster_id,
        merged_pr.status,
        len(result.consuming_prs),
        len(consumer_repos),
    )
    return result
