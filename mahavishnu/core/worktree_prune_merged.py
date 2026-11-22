"""Identify and remove merged worktrees across the configured repos.

Companion to docs/decisions/worktree-autoremove-policy.md. The
``WorktreePruner`` here is the *engine*; the CLI in ``worktree_cli.py``
is the *trigger*.

Public API:
  - ``WorktreePruneCandidate``: a dataclass describing a candidate worktree
  - ``classify_merge_status``: multi-signal merge classifier (returns tri-state)
  - ``find_merged_worktrees``: identify candidates across repos
  - ``WorktreePruner``: remove candidates via the existing coordinator
  - ``WorktreePruneResult``: per-worktree outcome

The multi-signal merge classifier uses:
  1. ``git merge-base --is-ancestor HEAD <branch>`` (handles linear FF + true merge commits)
  2. If ancestry check fails, scan ``main..HEAD`` for merge commits; if any exist,
     return ``undetermined`` (because git cherry excludes merge commits)
  3. ``git merge-tree --write-tree <branch> HEAD`` (handles a squash of ANY
     number of commits -- see ``_content_already_in_branch``)
  4. Otherwise, ``git cherry <branch>`` (handles squash, rebase, cherry-pick)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import subprocess  # nosec B404 — argv-list only, no shell
from typing import TYPE_CHECKING

from mahavishnu.core.worktree_audit import WorktreeAuditLogger

if TYPE_CHECKING:
    from collections.abc import Callable

    from mahavishnu.core.worktree_coordination import WorktreeCoordinator


class WorktreeScanError(RuntimeError):
    """Raised when git cannot report a repository's worktrees.

    This is an UNKNOWN answer, not an empty one. The enumeration step
    used to swallow the failure and return no paths, which is
    indistinguishable from "this repository has no worktrees" -- so
    the sweep reported nothing to do, and the merge cycle read that as
    a cleanup that had happened. A git failure has to travel up to the
    caller, which can then decide what to do with it: the fleet-wide
    sweep skips the repository and says so, and a scoped sweep fails.
    """


@dataclass(frozen=True)
class WorktreePruneCandidate:
    """A worktree that is a candidate for removal."""

    repo_path: Path
    repo_nickname: str
    worktree_path: Path
    branch: str
    head_sha: str
    merge_status: str
    dirty_status: str
    behind: int
    last_touched_at: str | None = None

    @property
    def is_merged(self) -> bool:
        return self.merge_status == "merged"

    @property
    def is_clean(self) -> bool:
        return self.dirty_status == "clean"

    @property
    def age_days(self) -> int | None:
        if not self.last_touched_at:
            return None
        try:
            ts = datetime.fromisoformat(self.last_touched_at)
        except ValueError:
            return None
        return (datetime.now(UTC) - ts).days


@dataclass(frozen=True)
class WorktreePruneResult:
    """Outcome of attempting to remove a single worktree."""

    candidate: WorktreePruneCandidate
    success: bool
    backup_path: str | None
    error: str | None
    escalated: bool = False


def _run_git(
    path: Path, *args: str, text: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=text,
        timeout=5,
        check=False,
    )


def _content_already_in_branch(worktree_path: Path, branch: str) -> bool:
    """Return True when the worktree's HEAD adds nothing to ``branch``.

    ``git cherry`` answers "is this commit's patch-id present
    upstream?". Patch-ids are computed per commit, so they cannot see a
    squash: merging N commits produces ONE commit whose diff is the
    union of the N diffs, and that union matches none of the
    individual patch-ids. Every one of the N commits therefore shows
    ``+`` and a squash-merged branch reads as ``not_merged``. (A squash
    of a SINGLE commit happens to work, because then the squash
    commit's diff IS that commit's diff -- which is why the
    single-commit case was covered and the multi-commit case was
    not.)

    ``git merge-tree --write-tree <branch> HEAD`` asks the question
    that actually matters: "would merging HEAD into ``branch`` change
    anything?". It computes the merge without touching the index or
    the working tree, exits 0 when the merge is clean, and prints the
    resulting tree on its first line. When that tree equals
    ``branch``'s tree, the merge is a no-op -- every change HEAD
    carries is already present in ``branch`` -- and the branch is
    merged, whatever produced it.

    Exit 0 alone is NOT enough. A branch with genuinely new content
    also merges cleanly, and its resulting tree differs from
    ``branch``'s. Both conditions are required.

    Returns False on any failure (a conflicting merge, an unknown
    revision, an old git without ``--write-tree``), leaving the
    caller's remaining signals to decide.

    # Implements: REQ-PRUNE-001
    """
    try:
        merged = _run_git(
            worktree_path, "merge-tree", "--write-tree", branch, "HEAD", text=True
        )
    except subprocess.TimeoutExpired, OSError:
        return False
    if merged.returncode != 0:
        # A conflict (exit 1), or an unknown option/revision. Either
        # way there is no clean merge to reason about, so this signal
        # carries no verdict.
        return False
    result_tree = merged.stdout.splitlines()[0].strip() if merged.stdout.strip() else ""
    if not result_tree:
        return False
    branch_tree = _git_output(worktree_path, "rev-parse", f"{branch}^{{tree}}")
    if branch_tree is None:
        return False
    return result_tree == branch_tree


def classify_merge_status(
    worktree_path: Path,
    *,
    main_branch: str = "main",
    master_fallback: bool = True,
) -> str:
    """Return the tri-state merge status for the worktree's HEAD."""
    branches = [main_branch]
    if master_fallback and main_branch != "master":
        branches.append("master")

    for branch in branches:
        try:
            exists = _run_git(worktree_path, "rev-parse", "--verify", "--quiet", branch)
            if exists.returncode != 0:
                continue
            ancestor = _run_git(
                worktree_path, "merge-base", "--is-ancestor", "HEAD", branch
            )
            if ancestor.returncode == 0:
                return "merged"
            if ancestor.returncode != 1:
                return "undetermined"
            merges = _run_git(
                worktree_path,
                "log",
                f"{branch}..HEAD",
                "--merges",
                "--oneline",
                text=True,
            )
            if merges.returncode != 0:
                return "undetermined"
            if merges.stdout.strip():
                return "undetermined"
            # Content equivalence, BEFORE the cherry fallback: the
            # cherry signal cannot see a multi-commit squash, so it
            # must not get the last word on one. This only ever
            # upgrades a branch to "merged"; every earlier
            # "undetermined" is left alone.
            if _content_already_in_branch(worktree_path, branch):
                return "merged"
            cherry = _run_git(worktree_path, "cherry", branch, text=True)
            if cherry.returncode != 0:
                return "undetermined"
            return (
                "not_merged"
                if any(line.startswith("+") for line in cherry.stdout.splitlines())
                else "merged"
            )
        except subprocess.TimeoutExpired, OSError:
            return "undetermined"
    return "undetermined"


def _git_dirty_count(worktree_path: Path) -> str:
    """Return ``clean``, ``dirty``, or ``undetermined`` for a worktree."""
    try:
        result = _run_git(worktree_path, "status", "--short", text=True)
    except subprocess.TimeoutExpired, OSError:
        return "undetermined"
    if result.returncode != 0:
        return "undetermined"
    return "dirty" if result.stdout.strip() else "clean"


def _git_output(worktree_path: Path, *args: str) -> str | None:
    try:
        result = _run_git(worktree_path, *args, text=True)
    except subprocess.TimeoutExpired, OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _git_current_branch(worktree_path: Path) -> str | None:
    return _git_output(worktree_path, "branch", "--show-current") or None


def _git_head_sha(worktree_path: Path) -> str | None:
    return _git_output(worktree_path, "rev-parse", "HEAD")


def _git_behind(worktree_path: Path, main_branch: str) -> int:
    output = _git_output(worktree_path, "rev-list", "--count", f"HEAD..{main_branch}")
    try:
        return int(output) if output is not None else 0
    except ValueError:
        return 0


def _worktree_listing(repo_path: Path) -> tuple[list[Path], set[Path]]:
    """Return the worktree paths and the locked subset, from ONE call.

    ``git worktree list --porcelain`` was run twice per repository per
    sweep -- once for the paths, once for the lock state -- and the
    sweep runs over every configured repository. One call answers both
    questions.

    Paths are RESOLVED on the way out, and that matters for three
    reasons: the lock check compares the resolved path against the
    candidate's path, and a path spelled differently (``/var/...``
    against ``/private/var/...``) would otherwise slip past the guard;
    the coordinator's registry paths are resolved the same way, so the
    de-duplication holds; and the TTL lookup matches the registry's
    spelling, so the TTL guard does not silently degrade to a no-op.

    **The locked subset** is the fleet's existing "do not touch this"
    marker. ``git worktree lock`` is what the agent-scoped worktrees
    carry from creation (git records the reason as ``initializing``),
    and an operator locks one to keep it out of a sweep. A lock is not
    a recency signal -- locked worktrees are up to a fortnight old --
    it is a statement that removal was refused, and the sweep honours
    it unconditionally.

    The merge cycle's OWN worktree is not locked, so the guard does not
    stop stage 6 from cleaning up after itself -- and it does stop it
    from touching anyone else's.

    # Implements: REQ-PRUNE-003

    Raises :class:`WorktreeScanError` when git cannot be run or fails.
    """
    try:
        result = _run_git(repo_path, "worktree", "list", "--porcelain", text=True)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise WorktreeScanError(
            f"cannot list the worktrees of {repo_path}: {exc}"
        ) from exc
    if result.returncode != 0:
        raise WorktreeScanError(
            f"git worktree list failed for {repo_path}: {result.stderr.strip()}"
        )

    paths: list[Path] = []
    locked: set[Path] = set()
    current: Path | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current = Path(line.removeprefix("worktree ")).resolve()
            paths.append(current)
        elif line.startswith("locked") and current is not None:
            locked.add(current)
    return paths, locked


def _direct_worktree_paths(repo_path: Path) -> list[Path]:
    return _worktree_listing(repo_path)[0]


def owning_repo_path(worktree_path: Path) -> Path | None:
    """Return the main checkout that owns a worktree.

    A worktree usually lives OUTSIDE its repository's directory -- the
    fleet's are under ``~/.local/state/mahavishnu/worktrees/`` -- so
    the owning repository cannot be found by looking at the path's
    parents. ``git rev-parse --git-common-dir`` answers it: from any
    worktree it reports the MAIN checkout's ``.git``, whose parent is
    the repository.

    Returns None when the path is not a worktree of a repository, or
    when git cannot be run.
    """
    common_dir = _git_output(
        worktree_path, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    if not common_dir:
        return None
    # RESOLVED, so it matches the repository paths it is compared
    # against: git reports the main checkout's path as recorded, and a
    # symlinked checkout (``/tmp`` against ``/private/tmp``) would
    # otherwise read as "no repository owns this".
    git_dir = Path(common_dir).resolve()
    if git_dir.name != ".git":
        # A bare repository's common dir IS the repository.
        return git_dir
    return git_dir.parent


async def _candidate_worktree_paths(
    repo_path: Path,
    repo_nickname: str | None,
    coordinator: WorktreeCoordinator | None,
    git_paths: list[Path] | None = None,
) -> list[Path]:
    """Enumerate the worktree paths to inspect for this repository.

    Git is the ground truth for which worktrees exist on disk, so the
    direct listing is ALWAYS consulted. The coordinator's registry is
    unioned in on top of it: it knows about worktrees created through
    Session-Buddy that a local listing may not carry yet.

    Consulting only the coordinator -- as this did -- made the sweep
    blind. The coordinator's provider registry reports Session-Buddy
    as unhealthy and falls back to the local provider, and the local
    provider's porcelain parser matched NOTHING git emits: it kept a
    line only when the line had four or more space-separated fields,
    and every line of ``git worktree list --porcelain`` has exactly
    two. The provider therefore returned an empty list for EVERY
    repository, so the sweep found nothing to prune while merged
    worktrees sat on disk. (The parser is fixed alongside this change
    -- ``_parse_worktree_porcelain`` in the local provider -- but the
    pruner does not depend on that fix: git is consulted directly.)

    Worse, a coordinator failure returned an EMPTY list -- the direct
    fallback below was unreachable, so a transient registry outage
    silently pruned nothing.

    A path the coordinator reports but git does not know is harmless:
    ``classify_merge_status`` and ``_git_dirty_count`` both return
    ``undetermined`` for a path git cannot resolve, and an
    ``undetermined`` candidate is never removed.

    ``git_paths`` lets the caller pass a listing it already has, so
    the porcelain command runs once per repository rather than twice.

    # Implements: REQ-PRUNE-002
    """
    paths = (
        list(git_paths) if git_paths is not None else _direct_worktree_paths(repo_path)
    )
    if coordinator is None:
        return paths
    try:
        listed = await coordinator.list_worktrees(repo_nickname=repo_nickname)
    except Exception:  # candidate enumeration — broad catch to fall back to the git listing when the coordinator is unavailable  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
        return paths
    if not listed.get("success"):
        return paths
    for entry in listed.get("worktrees", []):
        if isinstance(entry, dict) and entry.get("path"):
            # RESOLVED, like the git listing above. The de-duplication
            # compares against resolved paths, so an unresolved registry
            # path would register the same worktree twice -- classified
            # twice, and reported twice. The TTL guard reads the
            # registry by path, so the two sides must agree on the
            # spelling too.
            candidate = Path(entry["path"]).resolve()
            if candidate not in paths:
                paths.append(candidate)
    return paths


def _within_ttl(last_touched_at: str | None, ttl_days: int) -> bool:
    """Return True when the worktree is still inside its TTL window."""
    if ttl_days <= 0 or not last_touched_at:
        return False
    try:
        touched = datetime.fromisoformat(last_touched_at)
    except ValueError:
        return True
    return (datetime.now(UTC) - touched).days < ttl_days


def _prune_candidate_for(
    worktree_path: Path,
    *,
    repo_path: Path,
    repo_nickname: str,
    main_branch: str,
    include_dirty: bool,
    ttl_days: int,
    registry_lookup: Callable[[str], str | None] | None,
    locked_paths: set[Path] | None = None,
) -> WorktreePruneCandidate | None:
    """Return the prune candidate for one worktree, or None when filtered out."""
    if worktree_path.resolve() == repo_path.resolve():
        return None
    if locked_paths and worktree_path.resolve() in locked_paths:
        # A locked worktree is one removal was refused for. Skipping it
        # is unconditional -- there is no ``--include-locked`` escape
        # hatch, because the lock IS the refusal.
        #
        # Both sides are resolved: the locked set is built from
        # resolved paths, and a candidate's path may arrive spelled
        # differently (``/var/...`` against ``/private/var/...``).
        return None
    branch = _git_current_branch(worktree_path)
    if branch is None or branch in {main_branch, "master"}:
        return None
    merge_status = classify_merge_status(worktree_path, main_branch=main_branch)
    if merge_status != "merged":
        return None
    dirty_status = _git_dirty_count(worktree_path)
    if dirty_status == "undetermined" or (
        dirty_status == "dirty" and not include_dirty
    ):
        return None
    head_sha = _git_head_sha(worktree_path)
    if head_sha is None:
        return None
    last_touched_at = registry_lookup(str(worktree_path)) if registry_lookup else None
    if _within_ttl(last_touched_at, ttl_days):
        return None
    return WorktreePruneCandidate(
        repo_path=repo_path,
        repo_nickname=repo_nickname,
        worktree_path=worktree_path,
        branch=branch,
        head_sha=head_sha,
        merge_status=merge_status,
        dirty_status=dirty_status,
        behind=_git_behind(worktree_path, main_branch),
        last_touched_at=last_touched_at,
    )


async def find_merged_worktrees(
    repo_path: Path,
    *,
    repo_nickname: str | None = None,
    main_branch: str = "main",
    include_dirty: bool = False,
    ttl_days: int = 0,
    registry_lookup: Callable[[str], str | None] | None = None,
    coordinator: WorktreeCoordinator | None = None,
    only_path: Path | None = None,
) -> list[WorktreePruneCandidate]:
    """Identify fail-closed merged-worktree removal candidates.

    ``only_path`` narrows the sweep to ONE worktree, and it does so
    BEFORE the classification, not after it. Classifying a worktree
    costs a handful of git subprocesses (``git status`` alone measured
    0.26 s), so filtering after the fact still pays for every
    worktree in the repository. The merge cycle's cleanup uses this:
    it must clean up the worktree it just merged, and nothing else.
    """
    paths, locked_paths = _worktree_listing(repo_path)
    paths = await _candidate_worktree_paths(
        repo_path, repo_nickname, coordinator, git_paths=paths
    )

    resolved_nickname = repo_nickname or repo_path.name
    if only_path is not None:
        wanted = only_path.resolve()
        paths = [p for p in paths if p.resolve() == wanted]
    candidates: list[WorktreePruneCandidate] = []
    for worktree_path in paths:
        candidate = _prune_candidate_for(
            worktree_path,
            repo_path=repo_path,
            repo_nickname=resolved_nickname,
            main_branch=main_branch,
            include_dirty=include_dirty,
            ttl_days=ttl_days,
            registry_lookup=registry_lookup,
            locked_paths=locked_paths,
        )
        if candidate is not None:
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: str(item.worktree_path))


_FORCEABLE_SAFETY_CHECKS = frozenset({"uncommitted_changes", "dependency_block"})


def _requires_force(result: dict[str, object]) -> bool:
    return (
        bool(result.get("force_required"))
        or (result.get("safety_check") in _FORCEABLE_SAFETY_CHECKS)
        or result.get("error") == "force-required"
    )


class WorktreePruner:
    """Safely remove previously identified merged worktrees."""

    def __init__(
        self,
        coordinator: WorktreeCoordinator,
        audit_logger: WorktreeAuditLogger | None = None,
    ) -> None:
        self._coordinator = coordinator
        self._audit_logger = audit_logger or WorktreeAuditLogger()

    async def remove(
        self,
        candidates: list[WorktreePruneCandidate],
        *,
        force_reason: str | None = None,
        user_id: str | None = None,
        ttl_days: int = 0,
        include_dirty: bool = False,
        trigger: str = "cli",
    ) -> list[WorktreePruneResult]:
        """Remove candidates, escalating force only for recognized safety blocks."""
        self._validate_candidates(candidates, force_reason)
        self._audit_logger.log_prune_merged_attempt(
            user_id, len(candidates), ttl_days, include_dirty, trigger
        )
        results: list[WorktreePruneResult] = []
        for candidate in candidates:
            results.append(
                await self._apply_candidate(candidate, force_reason, user_id)
            )
        self._log_audit_outcome(user_id, results, trigger)
        return results

    @staticmethod
    def _validate_candidates(
        candidates: list[WorktreePruneCandidate], force_reason: str | None
    ) -> None:
        """Reject candidate lists that violate the pruner's safety invariants.

        Centralising these checks keeps ``remove`` at a single
        cyclomatic-complexity budget and gives callers a precise error
        for each failure mode.
        """
        if any(candidate.merge_status != "merged" for candidate in candidates):
            raise ValueError("All candidates must have merge_status='merged'")
        if any(candidate.dirty_status == "undetermined" for candidate in candidates):
            raise ValueError(
                "Candidates with undetermined dirty status cannot be removed"
            )
        if (
            any(candidate.dirty_status == "dirty" for candidate in candidates)
            and not force_reason
        ):
            raise ValueError("force_reason is required for dirty candidates")

    async def _apply_candidate(
        self,
        candidate: WorktreePruneCandidate,
        force_reason: str | None,
        user_id: str | None,
    ) -> WorktreePruneResult:
        """Run the per-candidate removal flow: re-validate, attempt, escalate."""
        if not self._candidate_unchanged(candidate):
            return WorktreePruneResult(
                candidate, False, None, "candidate changed since discovery"
            )
        try:
            return await self._remove_with_escalation(candidate, force_reason, user_id)
        except Exception as exc:  # per-candidate removal wrapper — broad catch to convert any failure into a structured PruneResult  # background task — broad catch is the documented contract  # noqa: BLE001, RUF100
            return WorktreePruneResult(candidate, False, None, str(exc))

    @staticmethod
    def _candidate_unchanged(candidate: WorktreePruneCandidate) -> bool:
        """Confirm the candidate still matches its discovery-time state.

        Race guard: a worktree may have been touched between discovery and
        prune. Re-running git status / dirty checks here means a stale
        ``WorktreePruneCandidate`` is rejected with a precise error.
        """
        current_sha = _git_head_sha(candidate.worktree_path)
        current_merge = classify_merge_status(candidate.worktree_path)
        current_dirty = _git_dirty_count(candidate.worktree_path)
        return (
            current_sha == candidate.head_sha
            and current_merge == "merged"
            and current_dirty == candidate.dirty_status
        )

    async def _remove_with_escalation(
        self,
        candidate: WorktreePruneCandidate,
        force_reason: str | None,
        user_id: str | None,
    ) -> WorktreePruneResult:
        """Call ``coordinator.remove_worktree`` once, escalating to force on safety blocks."""
        first = await self._coordinator.remove_worktree(
            repo_nickname=candidate.repo_nickname,
            worktree_path=str(candidate.worktree_path),
            force=False,
            force_reason=None,
            user_id=user_id,
        )
        escalated = _requires_force(first)
        final = first
        if escalated:
            final = await self._coordinator.remove_worktree(
                repo_nickname=candidate.repo_nickname,
                worktree_path=str(candidate.worktree_path),
                force=True,
                force_reason=force_reason or "merged worktree dependency cleanup",
                user_id=user_id,
            )
        return WorktreePruneResult(
            candidate=candidate,
            success=bool(final.get("success")),
            backup_path=str(final["backup_path"]) if final.get("backup_path") else None,
            error=str(final["error"]) if final.get("error") else None,
            escalated=escalated,
        )

    @staticmethod
    def _summarize_results(
        results: list[WorktreePruneResult],
    ) -> tuple[
        list[WorktreePruneResult], list[WorktreePruneResult], list[str], list[str]
    ]:
        """Partition results into (successful, failed, backup_paths, failed_paths).

        Pulled out so the audit-logging branch in ``remove`` reads top-down
        without inlining list comprehensions.
        """
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        backup_paths = [r.backup_path for r in successful if r.backup_path]
        failed_paths = [str(r.candidate.worktree_path) for r in failed]
        return successful, failed, backup_paths, failed_paths

    def _log_audit_outcome(
        self,
        user_id: str | None,
        results: list[WorktreePruneResult],
        trigger: str,
    ) -> None:
        """Emit the appropriate audit-log line for the batch outcome."""
        successful, failed, backup_paths, failed_paths = self._summarize_results(
            results
        )
        if failed and successful:
            self._audit_logger.log_prune_merged_partial(
                user_id,
                len(successful),
                len(failed),
                failed_paths,
                backup_paths,
                trigger,
            )
            return
        if failed:
            self._audit_logger.log_prune_merged_failure(
                user_id,
                "; ".join(r.error or "unknown error" for r in failed),
                trigger,
            )
            return
        self._audit_logger.log_prune_merged_success(
            user_id, len(successful), backup_paths, trigger, failed_paths
        )


__all__ = [
    "WorktreePruneCandidate",
    "WorktreePruneResult",
    "WorktreePruner",
    "WorktreeScanError",
    "classify_merge_status",
    "find_merged_worktrees",
    "owning_repo_path",
]
