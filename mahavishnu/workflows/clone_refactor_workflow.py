# Workflow-ID: 01JCLONEREF2026
# Approved by: les
"""Git-tree clone-refactor DAG.

Implements: REQ-CLONE-001, REQ-CLONE-002, REQ-CLONE-003, REQ-CLONE-010,
            REQ-CLONE-011, REQ-CLONE-012, REQ-CLONE-013, REQ-CLONE-016
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from prefect import flow, task

from mahavishnu.mcp.tools.clone_claims import release_cluster_claim
from mahavishnu.workflows import _git_ops

if TYPE_CHECKING:
    from mahavishnu.core.state_backends.mcp import MCPStateBackend


def _git_commit_transient_retry_predicate(task: Any, run: Any, state: Any) -> bool:
    """Prefect retry predicate for transient git commit failures.

    Implements: REQ-CLONE-013 (transient retry only).

    CA-m1: do NOT use tenacity.retry_if_exception_type here. Prefect calls
    retry_condition_fn with 3 positional args (task, run, state) per
    prefect.tasks.RetryConditionCallable; tenacity.retry_if_exception_type
    has __call__(self, retry_state) — 1 arg. Prefect wraps the call in
    `except Exception: return False` (task_engine.py), which silently
    disables ALL retries. The 3-arg form below preserves the retry contract.
    """
    return isinstance(state.data, _git_ops.GitCommitTransient)

logger = logging.getLogger(__name__)


# ---- Dataclasses (REQ-CLONE-002) ------------------------------------------

# TD-m1: status fields are Literal, not str — typos like "Completed" or
# "queued " (trailing space) compile silently and break equality checks.
RepoCommitStatus = Literal["completed", "failed"]
DAGStateStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)  # TD-m4: immutable; slots for memory
class RepoCommit:
    """Per-repo commit result. Fields mirror §7.2 final state record shape.

    TD-m4: frozen=True. SF-M7 partial-fill semantics preserved via
    `dataclasses.replace(base, files_touched=..., working_tree_clean_after_commit=...)`
    in write_canonical_symbol / write_replacement_diff (below).
    """

    repo: str
    sha: str | None
    status: RepoCommitStatus
    files_touched: tuple[str, ...] = ()  # frozen: must be immutable; tuple OK
    working_tree_clean_after_commit: bool = True
    error_type: str | None = None
    error_diff_offset: int | None = None
    error_conflict_marker: str | None = None
    error_stderr: str | None = None
    error_exit_code: int | None = None


@dataclass(frozen=True, slots=True)  # TD-m4
class RepoHit:
    """One row of detect_cluster_members output."""

    repo: str
    match_score: float


@dataclass(frozen=True, slots=True)  # TD-m4
class DAGState:
    """Aggregate DAG lifecycle state — written to workflow/v1/{refactor_job_id}."""

    schema_version: int = 2
    refactor_job_id: str = ""
    cluster_id: str = ""
    target_repo: str = ""
    consumer_repos: tuple[str, ...] = ()  # frozen: immutable
    status: DAGStateStatus = "queued"
    started_at: str = ""
    dag_started_at: str = ""
    dag_completed_at: str = ""
    target_commit: str | None = None
    target_commit_files_touched: tuple[str, ...] = ()  # frozen
    consumer_commits: tuple[RepoCommit, ...] = ()  # frozen
    failed_consumers: tuple[str, ...] = ()  # frozen


@dataclass(frozen=True, slots=True)  # TD-m4
class DAGResult:
    status: RepoCommitStatus
    consumer_commits: tuple[RepoCommit, ...]
    target_commit: RepoCommit | None = None
    error: str | None = None


# ---- Commit-message convention (REQ-CLONE-012) ---------------------------

def commit_message(refactor_job_id: str, repo: str, extracted_symbol: str) -> str:
    """Format the consumer-write commit message. Includes refactor-job header
    so operators can grep `git log --grep="^refactor-job:"` to disambiguate
    DAG-A vs DAG-B commits (REQ-CLONE-012).
    """
    return (
        f"refactor-job: {refactor_job_id}\n"
        f"target: {repo}\n"
        f"extracts: {extracted_symbol}\n"
        f"\n"
        f"Automated commit from clone_refactor_group DAG.\n"
        f"Revert recipe: git reset --hard $(git log --grep='^refactor-job: {refactor_job_id}$' --pretty=%H -n 1)^"
    )


# ---- Step functions (@task) ----------------------------------------------

@task(name="detect_cluster_members", retries=0)
async def detect_cluster_members(cluster_id: str, repos: list[str]) -> list[RepoHit]:
    """Detect cluster members. Stub that returns the input repos."""
    return [RepoHit(repo=r, match_score=1.0) for r in repos]


@task(
    name="write_canonical_symbol",
    retries=2,
    retry_delay_seconds=5,
    retry_condition_fn=_git_commit_transient_retry_predicate,
)
async def write_canonical_symbol(
    refactor_job_id: str,
    target_repo: str,
    extracted_symbol: str,
    extraction_diff: str,
) -> RepoCommit:
    """Write the canonical-symbol change to the target repo's local main.

    Implements: REQ-CLONE-011 (plain git stash wrap),
                REQ-CLONE-012 (commit message convention),
                REQ-CLONE-013 (transient retry only).
    SF-M7: build the RepoCommit immediately after `git_commit` succeeds,
    then fill in optional metadata (`files_touched`, `working_tree_clean`)
    in a try/except. If metadata gathering fails, return the partial
    `RepoCommit` with `working_tree_clean_after_commit=False` rather than
    letting the exception swallow the successful commit record.
    SF-B4: catch `StashPopFailed` and record typed error on the RepoCommit
    (do not propagate — the commit may have already succeeded).
    """
    repo_path = Path(target_repo)
    # REQ-CLONE-011: plain git stash (NOT --keep-index — that's partial-commit workflow).
    # stash_push returns None when there were no local changes to save (working tree
    # clean at function entry); skip stash_pop in that case.
    stash_ref: str | None = await _git_ops.stash_push(repo_path)
    sha: str | None = None
    stash_popped = False
    try:
        await _git_ops.git_apply(repo_path, extraction_diff)
        await _stage_all(repo_path)  # git_commit requires staged changes (Task 4 contract)
        msg = commit_message(refactor_job_id, target_repo, extracted_symbol)
        sha = await _git_ops.git_commit(repo_path, msg)
        # C3 fix: stash_pop runs HERE so a failure propagates as StashPopFailed
        # to the except arm with the captured SHA preserved, rather than being
        # silently swallowed in the finally block.
        if stash_ref is not None:
            await _git_ops.stash_pop(repo_path, stash_ref)
        stash_popped = True
        # SF-M7 + TD-m4: RepoCommit is frozen; build with empty defaults,
        # then use dataclasses.replace() to fill in optional metadata.
        base = RepoCommit(
            repo=target_repo,
            sha=sha,
            status="completed",
            files_touched=(),
            working_tree_clean_after_commit=False,
        )
        try:
            files = await _git_ops.diff_files(repo_path)
            clean = await _git_ops.is_working_tree_clean(repo_path)
            return replace(base, files_touched=tuple(files), working_tree_clean_after_commit=clean)
        except Exception as meta_exc:  # noqa: BLE001 — SF-M7 partial-fill fallback
            logger.warning(
                "write_canonical_symbol: post-commit metadata failed (%s); continuing",
                meta_exc,
            )
            return base
    except _git_ops.StashPopFailed as spf:
        # C3 fix: stash pop failed AFTER commit landed. Record typed error
        # on the result with the captured SHA (was previously discarded).
        logger.warning(
            "write_canonical_symbol: stash pop failed (sha=%s, stderr=%s)",
            sha, spf.stderr,
        )
        return RepoCommit(
            repo=target_repo,
            sha=sha,
            status="failed",
            error_type="StashPopFailed",
            error_stderr=spf.stderr,
            error_exit_code=spf.exit_code,
        )
    finally:
        # C3 fix: only run cleanup if we never reached the inner stash_pop
        # AND there's an actual stash to pop. On commit failure
        # (git_commit or git_apply raised), the inner stash_pop never ran
        # and the worktree still holds the diff — clean it up so the
        # agent's working tree is restored to pre-stash state.
        if not stash_popped and stash_ref is not None:
            try:
                await _git_ops.stash_pop(repo_path, stash_ref)
            except _git_ops.StashPopFailed:
                pass  # best-effort; operator can intervene via `git stash list`


@task(
    name="write_replacement_diff",
    retries=2,
    retry_delay_seconds=5,
    retry_condition_fn=_git_commit_transient_retry_predicate,
)
async def write_replacement_diff(
    refactor_job_id: str,
    consumer_repo: str,
    consuming_diff: str,
) -> RepoCommit:
    """Write the consuming diff to a single consumer repo.

    Same SF-B4/SF-M7 hardening as `write_canonical_symbol`.
    """
    repo_path = Path(consumer_repo)
    # REQ-CLONE-011: stash_push returns None when working tree was clean at
    # function entry; skip stash_pop in that case.
    stash_ref: str | None = await _git_ops.stash_push(repo_path)
    sha: str | None = None
    stash_popped = False
    try:
        await _git_ops.git_apply(repo_path, consuming_diff)
        await _stage_all(repo_path)  # git_commit requires staged changes (Task 4 contract)
        msg = commit_message(refactor_job_id, consumer_repo, "consuming-diff")
        sha = await _git_ops.git_commit(repo_path, msg)
        # C3 fix: stash_pop runs HERE so a failure propagates with the
        # captured SHA rather than being silently swallowed.
        if stash_ref is not None:
            await _git_ops.stash_pop(repo_path, stash_ref)
        stash_popped = True
        # SF-M7 + TD-m4: frozen dataclass via replace()
        base = RepoCommit(
            repo=consumer_repo,
            sha=sha,
            status="completed",
            files_touched=(),
            working_tree_clean_after_commit=False,
        )
        try:
            files = await _git_ops.diff_files(repo_path)
            clean = await _git_ops.is_working_tree_clean(repo_path)
            return replace(base, files_touched=tuple(files), working_tree_clean_after_commit=clean)
        except Exception as meta_exc:  # noqa: BLE001 — SF-M7 partial-fill fallback
            logger.warning(
                "write_replacement_diff: post-commit metadata failed (%s); continuing",
                meta_exc,
            )
            return base
    except _git_ops.StashPopFailed as spf:
        # C3 fix: preserve captured SHA on stash_pop failure.
        logger.warning(
            "write_replacement_diff: stash pop failed (sha=%s, stderr=%s)",
            sha, spf.stderr,
        )
        return RepoCommit(
            repo=consumer_repo,
            sha=sha,
            status="failed",
            error_type="StashPopFailed",
            error_stderr=spf.stderr,
            error_exit_code=spf.exit_code,
        )
    finally:
        # C3 fix: only run cleanup if the inner stash_pop never ran (i.e.,
        # git_commit or git_apply raised). See write_canonical_symbol for
        # rationale. Skip also when stash_ref is None (nothing was stashed).
        if not stash_popped and stash_ref is not None:
            try:
                await _git_ops.stash_pop(repo_path, stash_ref)
            except _git_ops.StashPopFailed:
                pass


@task(name="persist_dag_state", retries=0)
async def persist_dag_state(mcp_backend: MCPStateBackend, state: DAGState) -> None:
    """Best-effort write of aggregate DAG state (REQ-CLONE-003).

    TD-m8: use `_dataclass_to_dict(state)` (which calls asdict) for nested
    serialization instead of `state.__dict__` — the conventional idiom and
    safe with frozen dataclasses.
    """
    await mcp_backend.try_put_with_log_context(
        mcp_backend.dag_key(state.refactor_job_id),
        _dataclass_to_dict(state),
        log_context={"dag_id": state.refactor_job_id, "step_name": "persist_dag_state"},
    )


# ---- Per-step write helpers (REQ-CLONE-010) ------------------------------

async def _stage_all(repo_path: Path) -> None:
    """Stage all working-tree changes for the next commit.

    Brief defect fix: the original brief code called `git_apply` then
    `git_commit` directly, but `git_commit` (per Task 4's `_git_ops.py`)
    requires staged changes. Task 4's own test fixture confirms this
    (`subprocess.run(["git", "-C", str(git_repo), "add", "."], check=True)`
    before `git_commit`). We centralize the staging step here so the
    @task wrappers stay focused on apply→commit orchestration.
    """
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(repo_path), "add", "-A",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_b = await proc.communicate()
    if proc.returncode != 0:
        stderr = stderr_b.decode() if stderr_b else ""
        raise RuntimeError(f"git add -A failed (exit={proc.returncode}): {stderr}")


async def _write_step_outcome(
    mcp_backend: MCPStateBackend,
    refactor_job_id: str,
    step_name: str,
    outcome: dict[str, Any],
) -> None:
    """Per-step durability: every @task writes its outcome before returning."""
    log_context = {
        "dag_id": refactor_job_id,
        "step_name": step_name,
        "files_touched": outcome.get("files_touched", []),
    }
    await mcp_backend.try_put_with_log_context(
        f"workflow/v1/{refactor_job_id}/steps/{step_name}",
        outcome,
        log_context=log_context,
    )


async def _write_terminal_failed(
    mcp_backend: MCPStateBackend,
    refactor_job_id: str,
    exc: BaseException,
) -> None:
    await _write_step_outcome(
        mcp_backend,
        refactor_job_id,
        "failed",
        {
            "error_type": type(exc).__name__,
            "error": str(exc),
            "failed_at": datetime.now(UTC).isoformat(),
        },
    )


async def _write_terminal_cancelled(
    mcp_backend: MCPStateBackend,
    refactor_job_id: str,
) -> None:
    await _write_step_outcome(
        mcp_backend,
        refactor_job_id,
        "cancelled",
        {"cancelled_at": datetime.now(UTC).isoformat()},
    )


def _dataclass_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a (frozen) dataclass to a dict for substrate writes.

    TD-m8: prefer dataclasses.asdict() over obj.__dict__ for nested types.
    Falls back to __dict__ for non-dataclass objects (e.g., BaseException).
    """
    from dataclasses import asdict, is_dataclass
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return obj.__dict__


# ---- @flow orchestrator ---------------------------------------------------

# SF-M5: re-entry guard. Raised if the same refactor_job_id is invoked twice
# (operator re-run, or cross-process race that slipped past cluster_claim).
class DAGAlreadyRunningError(Exception):
    """Raised by run_clone_refactor_dag if the same refactor_job_id is already
    in flight (status in {queued, running}). Prevents duplicate work."""

    def __init__(self, existing_status: str) -> None:
        super().__init__(f"DAG {existing_status} already; refusing re-entry")
        self.existing_status = existing_status


@flow(name="clone-refactor-dag", validate_parameters=False)
async def run_clone_refactor_dag(
    refactor_job_id: str,
    cluster_id: str,
    mcp_backend: MCPStateBackend,
    target_repo: str,
    consumer_repos: list[str],
    extracted_symbol: str,
    extraction_diff: str,
    consuming_diffs: dict[str, str] | None = None,
) -> DAGResult:
    """Run the full DAG. Implements REQ-CLONE-010 (per-step write + try/except/finally
    with explicit CancelledError arm).

    SF-M5 re-entry guard: reads workflow/v1/{refactor_job_id} at entry; raises
    DAGAlreadyRunningError if status in {queued, running}.

    CA-m2 note: `@flow` runs in-process; `DAGState` is a non-Pydantic
    dataclass — Prefect serializes via pickle for in-memory flow, which
    works. Cross-process deployment would break; the spec explicitly
    intends in-process only.

    SF-m1 note: Phase 3 (consume) uses bare `asyncio.gather` (no
    return_exceptions) because each consumer's failure is caught by the
    `_run_consumer` wrapper, which builds a typed `RepoCommit`. Functionally
    equivalent to `return_exceptions=True` for normal `Exception` subclasses;
    the wrapper adds typed fields that bare `return_exceptions` cannot.
    """
    # SF-M5: re-entry guard
    existing_state = await mcp_backend.get(mcp_backend.dag_key(refactor_job_id))
    if existing_state is not None and existing_state.get("status") in ("queued", "running"):
        raise DAGAlreadyRunningError(existing_status=existing_state.get("status", "unknown"))

    consumer_commits: tuple[RepoCommit, ...] = ()
    target_commit: RepoCommit | None = None

    try:
        # Phase 1: detect
        hits = await detect_cluster_members(cluster_id, [target_repo, *consumer_repos])
        await _write_step_outcome(
            mcp_backend, refactor_job_id, "detect", {"hits": len(hits)}
        )

        # Phase 2: propose (target)
        target_commit = await write_canonical_symbol(
            refactor_job_id, target_repo, extracted_symbol, extraction_diff
        )
        await _write_step_outcome(
            mcp_backend,
            refactor_job_id,
            "propose",
            {"target_sha": target_commit.sha, "files_touched": target_commit.files_touched},
        )

        # Phase 3: consume (parallel) — collect success/failure per repo
        async def _run_consumer(repo: str) -> RepoCommit:
            diff = (consuming_diffs or {}).get(repo)
            if diff is None:
                return RepoCommit(
                    repo=repo, sha=None, status="failed",
                    error_type="MissingConsumingDiff",
                    error_stderr=f"No consuming_diffs entry for {repo}",
                )
            try:
                return await write_replacement_diff(refactor_job_id, repo, diff)
            except Exception as exc:  # noqa: BLE001 — REQ-CLONE-010 failure-path: convert unanticipated exception to typed RepoCommit
                return RepoCommit(
                    repo=repo, sha=None, status="failed",
                    error_type=type(exc).__name__,
                    error_stderr=str(exc),
                    error_diff_offset=getattr(exc, "diff_offset", None),
                    error_conflict_marker=getattr(exc, "conflict_marker", None),
                    error_exit_code=getattr(exc, "exit_code", None),
                )

        # TD-m4: consumer_commits is a tuple (RepoCommit is frozen)
        consumer_commits = tuple(
            await asyncio.gather(*(_run_consumer(r) for r in consumer_repos))
        )
        await _write_step_outcome(
            mcp_backend,
            refactor_job_id,
            "consume",
            {"consumer_commits": [_dataclass_to_dict(c) for c in consumer_commits]},
        )

        # Phase 4: finalize
        all_completed = all(c.status == "completed" for c in consumer_commits)
        status: RepoCommitStatus = "completed" if all_completed else "failed"
        final = DAGResult(
            status=status,
            consumer_commits=consumer_commits,
            target_commit=target_commit,
        )
        await persist_dag_state(
            mcp_backend,
            DAGState(
                refactor_job_id=refactor_job_id,
                cluster_id=cluster_id,
                target_repo=target_repo,
                consumer_repos=tuple(consumer_repos),
                status=status,
                dag_completed_at=datetime.now(UTC).isoformat(),
                target_commit=target_commit.sha if target_commit else None,
                target_commit_files_touched=target_commit.files_touched if target_commit else (),
                consumer_commits=consumer_commits,
                failed_consumers=tuple(c.repo for c in consumer_commits if c.status == "failed"),
            ),
        )
        return final

    except asyncio.CancelledError:
        # REQ-CLONE-016: cancellation must persist terminal "cancelled" before re-raising
        await _write_terminal_cancelled(mcp_backend, refactor_job_id)
        raise
    except Exception as exc:
        # REQ-CLONE-010: unhandled exception path. Record transitions to "failed".
        await _write_terminal_failed(mcp_backend, refactor_job_id, exc)
        raise
    finally:
        # REQ-CLONE-009: release cluster claim regardless of outcome.
        # SF-B3: wrap release in try/except so a release failure never
        # shadows the original DAG exception (Python's finally semantics
        # would otherwise replace the traceback).
        try:
            await release_cluster_claim(mcp_backend, cluster_id)
        except Exception as release_exc:  # noqa: BLE001 — best-effort claim release; never shadow original exception per SF-B3
            logger.warning(
                "release_cluster_claim failed for cluster_id=%s (%s); continuing",
                cluster_id, release_exc,
            )