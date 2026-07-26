"""Identify and remove merged worktrees across the configured repos.

Companion to .claude/decisions/worktree-autoremove-policy.md. The
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
  3. Otherwise, ``git cherry <branch>`` (handles squash, rebase, cherry-pick)
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
            ts = datetime.fromisoformat(self.last_touched_at.replace("Z", "+00:00"))
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


def _run_git(path: Path, *args: str, text: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=text,
        timeout=5,
        check=False,
    )


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
            ancestor = _run_git(worktree_path, "merge-base", "--is-ancestor", "HEAD", branch)
            if ancestor.returncode == 0:
                return "merged"
            if ancestor.returncode != 1:
                return "undetermined"
            merges = _run_git(
                worktree_path, "log", f"{branch}..HEAD", "--merges", "--oneline", text=True
            )
            if merges.returncode != 0:
                return "undetermined"
            if merges.stdout.strip():
                return "undetermined"
            cherry = _run_git(worktree_path, "cherry", branch, text=True)
            if cherry.returncode != 0:
                return "undetermined"
            return (
                "not_merged"
                if any(line.startswith("+") for line in cherry.stdout.splitlines())
                else "merged"
            )
        except (subprocess.TimeoutExpired, OSError):
            return "undetermined"
    return "undetermined"


def _git_dirty_count(worktree_path: Path) -> str:
    """Return ``clean``, ``dirty``, or ``undetermined`` for a worktree."""
    try:
        result = _run_git(worktree_path, "status", "--short", text=True)
    except (subprocess.TimeoutExpired, OSError):
        return "undetermined"
    if result.returncode != 0:
        return "undetermined"
    return "dirty" if result.stdout.strip() else "clean"


def _git_output(worktree_path: Path, *args: str) -> str | None:
    try:
        result = _run_git(worktree_path, *args, text=True)
    except (subprocess.TimeoutExpired, OSError):
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


def _direct_worktree_paths(repo_path: Path) -> list[Path]:
    try:
        result = _run_git(repo_path, "worktree", "list", "--porcelain", text=True)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return [
        Path(line.removeprefix("worktree "))
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    ]


async def find_merged_worktrees(
    repo_path: Path,
    *,
    repo_nickname: str | None = None,
    main_branch: str = "main",
    include_dirty: bool = False,
    ttl_days: int = 0,
    registry_lookup: Callable[[str], str | None] | None = None,
    coordinator: WorktreeCoordinator | None = None,
) -> list[WorktreePruneCandidate]:
    """Identify fail-closed merged-worktree removal candidates."""
    if coordinator is not None:
        try:
            listed = await coordinator.list_worktrees(repo_nickname=repo_nickname)
        except Exception:
            return []
        if not listed.get("success"):
            return []
        paths = [
            Path(entry["path"])
            for entry in listed.get("worktrees", [])
            if isinstance(entry, dict) and entry.get("path")
        ]
    else:
        paths = _direct_worktree_paths(repo_path)

    resolved_nickname = repo_nickname or repo_path.name
    candidates: list[WorktreePruneCandidate] = []
    for worktree_path in paths:
        if worktree_path.resolve() == repo_path.resolve():
            continue
        branch = _git_current_branch(worktree_path)
        if branch is None or branch in {main_branch, "master"}:
            continue
        merge_status = classify_merge_status(worktree_path, main_branch=main_branch)
        if merge_status != "merged":
            continue
        dirty_status = _git_dirty_count(worktree_path)
        if dirty_status == "undetermined" or (dirty_status == "dirty" and not include_dirty):
            continue
        head_sha = _git_head_sha(worktree_path)
        if head_sha is None:
            continue
        last_touched_at = registry_lookup(str(worktree_path)) if registry_lookup else None
        if ttl_days > 0 and last_touched_at:
            try:
                touched = datetime.fromisoformat(last_touched_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if (datetime.now(UTC) - touched).days < ttl_days:
                continue
        candidates.append(
            WorktreePruneCandidate(
                repo_path=repo_path,
                repo_nickname=resolved_nickname,
                worktree_path=worktree_path,
                branch=branch,
                head_sha=head_sha,
                merge_status=merge_status,
                dirty_status=dirty_status,
                behind=_git_behind(worktree_path, main_branch),
                last_touched_at=last_touched_at,
            )
        )
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
        if any(candidate.merge_status != "merged" for candidate in candidates):
            raise ValueError("All candidates must have merge_status='merged'")
        if any(candidate.dirty_status == "undetermined" for candidate in candidates):
            raise ValueError("Candidates with undetermined dirty status cannot be removed")
        if any(candidate.dirty_status == "dirty" for candidate in candidates) and not force_reason:
            raise ValueError("force_reason is required for dirty candidates")

        self._audit_logger.log_prune_merged_attempt(
            user_id, len(candidates), ttl_days, include_dirty, trigger
        )
        results: list[WorktreePruneResult] = []
        for candidate in candidates:
            current_sha = _git_head_sha(candidate.worktree_path)
            current_merge = classify_merge_status(candidate.worktree_path)
            current_dirty = _git_dirty_count(candidate.worktree_path)
            if (
                current_sha != candidate.head_sha
                or current_merge != "merged"
                or current_dirty != candidate.dirty_status
            ):
                results.append(
                    WorktreePruneResult(candidate, False, None, "candidate changed since discovery")
                )
                continue
            try:
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
                results.append(
                    WorktreePruneResult(
                        candidate=candidate,
                        success=bool(final.get("success")),
                        backup_path=(
                            str(final["backup_path"]) if final.get("backup_path") else None
                        ),
                        error=(str(final["error"]) if final.get("error") else None),
                        escalated=escalated,
                    )
                )
            except Exception as exc:
                results.append(WorktreePruneResult(candidate, False, None, str(exc)))

        successful = [result for result in results if result.success]
        failed = [result for result in results if not result.success]
        backup_paths = [result.backup_path for result in successful if result.backup_path]
        failed_paths = [str(result.candidate.worktree_path) for result in failed]
        if failed and successful:
            self._audit_logger.log_prune_merged_partial(
                user_id,
                len(successful),
                len(failed),
                failed_paths,
                backup_paths,
                trigger,
            )
        elif failed:
            self._audit_logger.log_prune_merged_failure(
                user_id, "; ".join(result.error or "unknown error" for result in failed), trigger
            )
        else:
            self._audit_logger.log_prune_merged_success(
                user_id, len(successful), backup_paths, trigger, failed_paths
            )
        return results


__all__ = [
    "WorktreePruneCandidate",
    "WorktreePruneResult",
    "WorktreePruner",
    "classify_merge_status",
    "find_merged_worktrees",
]
