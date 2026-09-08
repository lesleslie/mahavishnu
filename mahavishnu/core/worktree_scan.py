"""Worktree scan: classifier + scan driver (3-pass pipeline) + report formatters.

Spec: docs/superpowers/specs/2026-09-07-worktree-cleanup-design.md
Decision: .claude/decisions/worktree-cleanup-policy.md
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
from typing import Literal

from mahavishnu.core.paths import get_worktree_base_path

# Module-level constants for subprocess safety
_PID_REGEX = re.compile(r"^[0-9]+$")
_GIT_TIMEOUT_DEFAULT = 5  # baseline; scan driver overrides per-call
_PS_TIMEOUT_DEFAULT = 2
_LOCK_FILE_REGEX = re.compile(
    r"^claude agent \S+ \(pid (\d+) start (\d{4}-\d{2}-\d{2})\)$"
)

# Lock-file command identity patterns (per spec A21: PID-reuse identity check).
# Match `claude` or `python` running mahavishnu. A recycled PID running
# something else (e.g. `bash`) is treated as "unknown", not "alive".
_LOCKED_COMMAND_PREFIXES: tuple[str, ...] = (
    "claude",
)


# ---------------------------------------------------------------------------
# Plan-orphan pattern registry
# ---------------------------------------------------------------------------
# Maintained in code; the decision doc § Decision rule enumerates these via
# `tests/unit/test_decision_doc_sync.py::test_doc_lists_current_plan_orphan_patterns`.
PLAN_ORPHAN_PATTERNS: tuple[str, ...] = (
    r"^w4-claude-md-breadcrumb",  # Wave 4 plan (Aug 2026)
    r"^plan7-phase5",  # Plan 7 phase 5 (Aug 2026)
    r"^wave8-diagram-corrections",  # Wave 8 diagram corrections (Aug 2026)
)

# Pre-computed prefix lookup for PLAN_ORPHAN_PATTERNS (used by Tier X check,
# see F46). Strips the optional leading `^` anchor.
_PLAN_ORPHAN_PREFIXES: tuple[str, ...] = tuple(
    p.lstrip("^") for p in PLAN_ORPHAN_PATTERNS
)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
PidLiveness = Literal["alive", "dead", "unknown", "none"]
Tier = Literal[
    "A-merged",
    "A-merged-dirty",
    "A-orphan-detached",
    "A-orphan-detached-dirty",
    "X",
    "B",
    "C",
    "D",
    "unknown",
]

# Canonical tier order used by text/JSON formatters.
_TIER_ORDER: tuple[Tier, ...] = (
    "A-merged",
    "A-merged-dirty",
    "A-orphan-detached",
    "A-orphan-detached-dirty",
    "X",
    "B",
    "C",
    "D",
    "unknown",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run_git_scanned(
    path: Path,
    *args: str,
    timeout: int = _GIT_TIMEOUT_DEFAULT,
    text: bool = False,
) -> subprocess.CompletedProcess:
    """Run `git -C <path> <args>` with explicit timeout.

    Does NOT use _run_git from worktree_prune_merged because that helper
    hard-codes timeout=5 (per spec A55); the scan driver needs up to 30s
    per-repo headroom for slow repos.
    """
    return subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=text,
        timeout=timeout,
        check=False,
        shell=False,  # explicit, even though default is False
    )


def _run_ps(
    pid: str,
    *args: str,
    timeout: int = _PS_TIMEOUT_DEFAULT,
) -> subprocess.CompletedProcess:
    """Run `ps -p <pid> [args]` after strict PID validation.

    PID must match ^[0-9]+$ to prevent flag injection (per spec A8).
    """
    if not _PID_REGEX.match(pid):
        raise ValueError(f"PID must match ^[0-9]+$: {pid!r}")
    return subprocess.run(
        ["ps", "-p", pid, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )


# ---------------------------------------------------------------------------
# WorktreeClassification + classifier
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WorktreeClassification:
    """Pure data: result of classifying a single worktree."""

    tier: Tier
    is_dirty: bool
    is_locked: bool
    pid_liveness: PidLiveness | None  # None when lock absent
    stash_count: int
    modified_count: int
    untracked_count: int
    cross_repo_group_id: str | None
    notes: list[str] = field(default_factory=list)
    # F21 §2 fix: real PID + command (not None) for the locked_live JSON
    # section; preserved here so consumers can re-emit identity-based liveness.
    lock_pid: int | None = None
    lock_command: str | None = None
    # F21 §3 fix: keep `repo` (repo_nickname) and `branch` end-to-end so the
    # nested `entries[]` array inside `tier_x_cross_repo_orphan[]` can carry
    # them per spec JSON schema.
    repo_nickname: str | None = None
    branch: str | None = None
    worktree_path: Path | None = None


def classify_worktree(
    *,
    worktree_path: Path,
    branch: str | None,  # None when detached HEAD
    age_days: float,
    is_dirty: bool,
    is_locked: bool,
    lock_pid_liveness: PidLiveness | None,
    plan_orphan_groups: dict[str, list[tuple[str, Path]]],
    classify_merge_status_fn,  # injected for testability
    age_threshold_a: float = 30.0,
    age_threshold_c: float = 9.0,
    # F21 §2: parsed lock-file PID + command (None when no lock)
    lock_pid: int | None = None,
    lock_command: str | None = None,
    # F21 §3: preserved end-to-end so tier_x JSON entries can carry repo + branch
    repo_nickname: str | None = None,
) -> WorktreeClassification:
    """Classify a worktree into a tier.

    First-match-wins by row order from the Decision rule. The injected
    `classify_merge_status_fn` lets tests skip the real git roundtrip.
    """

    def _mk(
        tier: Tier,
        *,
        notes: list[str] | None = None,
        cross_repo_group_id: str | None = None,
    ) -> WorktreeClassification:
        """Build a WorktreeClassification with all the shared kwargs."""
        return WorktreeClassification(
            tier=tier,
            is_dirty=is_dirty,
            is_locked=is_locked,
            pid_liveness=lock_pid_liveness,
            stash_count=0,
            modified_count=0,
            untracked_count=0,
            cross_repo_group_id=cross_repo_group_id,
            notes=notes or [],
            lock_pid=lock_pid,
            lock_command=lock_command,
            repo_nickname=repo_nickname,
            branch=branch,
            worktree_path=worktree_path,
        )

    merge_status = classify_merge_status_fn(worktree_path)

    # Tier A-merged (clean or dirty): branch is fully merged.
    # NOTE: F22 Tier X exclusivity — early-return for merged takes priority
    # over Tier X. A worktree matching PLAN_ORPHAN_PATTERNS AND merged
    # belongs in tier_a_merged (not tier_x_cross_repo_orphan).
    if merge_status == "merged":
        return _mk("A-merged-dirty" if is_dirty else "A-merged")

    # Tier X (cross-repo plan-orphan): branch matches PLAN_ORPHAN_PATTERNS
    # AND worktree is in plan_orphan_groups (computed in Pass 2 of the scan
    # pipeline). Reported EXCLUSIVELY in tier_x; never under Tier A.
    # is_locked == False guard per spec § Decision rule Tier X row (F14).
    if branch is not None and not is_locked:
        for group_id, entries in plan_orphan_groups.items():
            if worktree_path in [p for _, p in entries] and any(
                branch.startswith(prefix) for prefix in _PLAN_ORPHAN_PREFIXES
            ):
                return _mk("X", cross_repo_group_id=group_id)

    # Tier A-orphan-detached: detached HEAD, not a known `git bisect` pattern,
    # not in plan-orphan groups (already handled above).
    if branch is None:
        return _mk(
            "A-orphan-detached-dirty" if is_dirty else "A-orphan-detached",
            notes=["detached HEAD; verify not bisect/rebase state before deleting"],
        )

    # Tier B (agent-dispatch leftover): path under get_worktree_base_path() with
    # `agent-*` basename, OR under any repo's .claude/worktrees/agent-*.
    # F12: matcher uses basename + path-segments check, not `parent.name == "agent-"`.
    base = get_worktree_base_path()
    in_agent_root = worktree_path.parent == base and worktree_path.name.startswith("agent-")
    in_repo_agent_claude = (
        worktree_path.name.startswith("agent-")
        and len(worktree_path.parts) >= 3
        and worktree_path.parts[-2] == "worktrees"
        and worktree_path.parts[-3].startswith(".claude")
    )
    if in_agent_root or in_repo_agent_claude:
        return _mk("B", notes=["agent-dispatch leftover"])

    # Tier C (mid-age): 9.0 <= age < 30.0 AND is_locked == False (F13)
    if (not is_locked) and age_threshold_c <= age_days < age_threshold_a:
        return _mk("C")

    # Tier D (recent): age < 9.0
    if age_days < age_threshold_c:
        return _mk("D", notes=["recent; manual review"])

    # age >= 30 but not merged/detached/plan-orphan = tier A by age (uncommon)
    if age_days >= age_threshold_a:
        return _mk(
            "A-orphan-detached-dirty" if is_dirty else "A-orphan-detached",
            notes=["age >= 30d but not merged/detached"],
        )

    return _mk("unknown", notes=["unclassified"])


# ---------------------------------------------------------------------------
# 3-pass scan pipeline
# ---------------------------------------------------------------------------
def scan_worktrees(
    *,
    repo_paths: list[Path],
    classify_merge_status_fn,
    output_format: Literal["text", "json"] = "text",
    age_threshold_a: float = 30.0,
    age_threshold_c: float = 9.0,
    get_worktree_base_path_fn=get_worktree_base_path,
) -> str:
    """3-pass pipeline: collect, group cross-repo orphans, classify.

    Returns text or JSON report string. Read-only: no filesystem mutation
    outside of (optional) ps -p <pid> liveness checks.

    Per-repo failures are surfaced via the report (F19):
    - JSON: `scan_metadata.failed_repos` (list of {path, reason})
    - Text: footer `Scan complete: N candidates; M scan failures; ...`
    Task 2.7's CLI exit-code-1 path consumes these.
    """
    # Pass 1: collect (with per-repo failure tracking — F19)
    raw_entries: list[dict] = []
    failed_repos: list[dict] = []
    for repo in repo_paths:
        entries, reason = _collect_repo(repo, age_threshold_a, age_threshold_c)
        if reason is not None:
            failed_repos.append({"path": str(repo), "reason": reason})
            continue
        raw_entries.extend(entries)

    # L4: repos_scanned reflects what was actually scanned (input minus
    # the driver-level failures). Exposed in scan_metadata for callers.
    repos_scanned = len(repo_paths) - len(failed_repos)

    # Pass 2: group cross-repo orphans
    plan_orphan_groups = _group_plan_orphans(raw_entries)

    # Pass 3: classify
    classifications = [
        _classify_entry(
            entry,
            plan_orphan_groups,
            classify_merge_status_fn,
            age_threshold_a,
            age_threshold_c,
            get_worktree_base_path_fn,
        )
        for entry in raw_entries
    ]

    # Format
    if output_format == "json":
        return _format_json(
            classifications, failed_repos=failed_repos, repos_scanned=repos_scanned
        )
    return _format_text(
        classifications, failed_repos=failed_repos, repos_scanned=repos_scanned
    )


def scan_worktrees_with_status(
    *,
    repo_paths: list[Path],
    classify_merge_status_fn,
    output_format: Literal["text", "json"] = "text",
    age_threshold_a: float = 30.0,
    age_threshold_c: float = 9.0,
    get_worktree_base_path_fn=get_worktree_base_path,
) -> tuple[str, list[dict]]:
    """L3 — like `scan_worktrees`, but also returns the driver-failure list.

    Use this when the caller needs exit-code semantics: a non-empty
    `failed_repos` should drive exit 1 alongside any path-existence failures
    the caller already tracks.
    """
    # Pass 1: collect (mirrors scan_worktrees; would be DRY-er if extracted)
    raw_entries: list[dict] = []
    failed_repos: list[dict] = []
    for repo in repo_paths:
        entries, reason = _collect_repo(repo, age_threshold_a, age_threshold_c)
        if reason is not None:
            failed_repos.append({"path": str(repo), "reason": reason})
            continue
        raw_entries.extend(entries)
    repos_scanned = len(repo_paths) - len(failed_repos)

    plan_orphan_groups = _group_plan_orphans(raw_entries)
    classifications = [
        _classify_entry(
            entry,
            plan_orphan_groups,
            classify_merge_status_fn,
            age_threshold_a,
            age_threshold_c,
            get_worktree_base_path_fn,
        )
        for entry in raw_entries
    ]

    if output_format == "json":
        report = _format_json(
            classifications, failed_repos=failed_repos, repos_scanned=repos_scanned
        )
    else:
        report = _format_text(
            classifications, failed_repos=failed_repos, repos_scanned=repos_scanned
        )
    return report, failed_repos


def _collect_repo(
    repo: Path, age_threshold_a: float, age_threshold_c: float
) -> tuple[list[dict], str | None]:
    """Pass 1: parse `git worktree list --porcelain` + age + dirty for each worktree.

    F18 (BLOCKING): each entry gets `repo_nickname` set so Tier X grouping
    in Pass 2 can correctly bucket entries by repository.

    Returns:
        (entries, failure_reason). failure_reason is None on success,
        or a short string (e.g. "git worktree list returned 1") on failure.
        F19: this surfaces per-repo failures so scan_worktrees can emit
        `failed_repos` for Task 2.7's CLI exit-code-1 path.
    """
    result = _run_git_scanned(
        repo, "worktree", "list", "--porcelain", text=True, timeout=30
    )
    if result.returncode != 0:
        # stderr may be str (text=True) or bytes; handle both.
        raw_stderr = result.stderr if result.stderr is not None else ""
        if isinstance(raw_stderr, bytes):
            stderr_text = raw_stderr.decode(errors="replace").strip()
        else:
            stderr_text = str(raw_stderr).strip()
        return (
            [],
            f"git worktree list returned {result.returncode}: {stderr_text or '<no stderr>'}",
        )
    entries: list[dict] = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = Path(line[9:].strip())
        elif line.startswith("branch "):
            current["branch"] = line[7:].strip().replace("refs/heads/", "")
        elif line == "detached":
            current["branch"] = None
    if current:
        entries.append(current)

    # F18: tag each entry with the source repo's nickname so Pass 2 grouping
    # can produce per-repo counts and so Tier X detection works. Falls back
    # to parent name when repo itself has no name (defensive against bad symlinks).
    repo_nickname = repo.name or repo.parent.name
    for entry in entries:
        entry["repo_nickname"] = repo_nickname

    # Enrich with age, dirty, locked status
    for entry in entries:
        path = entry["path"]
        age_result = _run_git_scanned(
            path, "log", "-1", "--format=%ct", text=True, timeout=10
        )
        try:
            entry["age_days"] = (
                datetime.now(UTC).timestamp()
                - int(age_result.stdout.strip())
            ) / 86400
        except (ValueError, AttributeError):
            # F40 fix: a fresh repo (no commits → empty stdout) should default
            # to Tier D (recent), not 99999.0d which forces Tier A or C.
            entry["age_days"] = 0.0
        # Unconditional: dirty classification needed for Tier A predicate
        status_result = _run_git_scanned(
            path, "status", "--short", text=True, timeout=10
        )
        entry["is_dirty"] = bool(status_result.stdout.strip())
        is_locked = _is_worktree_locked(repo, path)
        entry["is_locked"] = is_locked
        if is_locked:
            lock_pid, lock_command, lock_pid_liveness = _get_lock_pid_liveness(
                repo, path
            )
        else:
            lock_pid, lock_command, lock_pid_liveness = None, None, None
        entry["lock_pid"] = lock_pid
        entry["lock_command"] = lock_command
        entry["lock_pid_liveness"] = lock_pid_liveness
    return (entries, None)


def _is_worktree_locked(repo: Path, worktree_path: Path) -> bool:
    """Read .git/worktrees/<basename>/locked; return True if locked."""
    git_dir = _run_git_scanned(
        repo, "rev-parse", "--git-dir", text=True, timeout=5
    ).stdout.strip()
    if not git_dir:
        return False
    git_path = Path(git_dir)
    wt_name = worktree_path.name
    lock_file = git_path / "worktrees" / wt_name / "locked"
    return lock_file.exists()


def _get_lock_pid_liveness(
    repo: Path, worktree_path: Path
) -> tuple[int | None, str | None, PidLiveness | None]:
    """Parse lock file, extract PID + command, return (pid, command, liveness).

    Implements spec A21 PID-reuse identity check: even when `ps -p <pid>`
    returns 0 (process exists), we also call `ps -p <pid> -o command=` and
    verify the command starts with a known pattern (claude / python).
    A recycled PID running something else → "unknown", not "alive".

    Returns:
        (lock_pid, lock_command, pid_liveness). All three are None when the
        worktree is not locked. When locked but the lock parse fails,
        pid_liveness is "unknown" and pid/command are None.
    """
    git_dir = _run_git_scanned(
        repo, "rev-parse", "--git-dir", text=True, timeout=5
    ).stdout.strip()
    if not git_dir:
        return (None, None, None)
    git_path = Path(git_dir)
    wt_name = worktree_path.name
    lock_file = git_path / "worktrees" / wt_name / "locked"
    if not lock_file.exists():
        return (None, None, None)
    try:
        content = lock_file.read_text().strip()
    except OSError:
        return (None, None, "unknown")
    match = _LOCK_FILE_REGEX.match(content)
    if not match:
        return (None, None, "unknown")
    pid_str = match.group(1)
    try:
        pid_int = int(pid_str)
    except ValueError:
        pid_int = None
    try:
        result = _run_ps(pid_str, timeout=2)
    except subprocess.TimeoutExpired:
        return (pid_int, None, "unknown")
    if result.returncode == 0:
        # PID-reuse identity check (A21). Wrap the second _run_ps call
        # because a hung `ps -p <pid> -o command=` would otherwise raise
        # subprocess.TimeoutExpired and abort the whole scan mid-loop
        # (final-review L2). Treat timeout as "unknown" identity.
        try:
            cmd_result = _run_ps(pid_str, "-o", "command=", timeout=2)
        except subprocess.TimeoutExpired:
            return (pid_int, None, "unknown")
        cmd = cmd_result.stdout.strip() if cmd_result.returncode == 0 else ""
        if any(cmd.startswith(prefix) for prefix in _LOCKED_COMMAND_PREFIXES):
            return (pid_int, cmd, "alive")
        return (pid_int, cmd, "unknown")
    return (pid_int, None, "dead")


def _group_plan_orphans(entries: list[dict]) -> dict[str, list[tuple[str, Path]]]:
    """Pass 2: group worktrees by (date, PLAN_ORPHAN_PATTERN) across repos.

    Keeps only groups with ≥ 2 distinct repos (per spec § Decision rule Tier X).
    """
    date_groups: dict[tuple[str, str], list[tuple[str, Path]]] = defaultdict(list)
    for entry in entries:
        branch = entry.get("branch")
        if branch is None:
            continue
        matching_pattern = next(
            (p for p in _PLAN_ORPHAN_PREFIXES if branch.startswith(p)),
            None,
        )
        if matching_pattern is None:
            continue
        # Heuristic: ISO date is the last 10 chars of the branch.
        tail = branch[-10:]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", tail):
            continue
        date_groups[(tail, matching_pattern)].append(
            (entry.get("repo_nickname", "unknown"), entry["path"])
        )
    return {
        f"{date}-{pattern}": entries
        for (date, pattern), entries in date_groups.items()
        if len({repo_n for repo_n, _ in entries}) >= 2
    }


def _classify_entry(
    entry: dict,
    plan_orphan_groups: dict,
    classify_merge_status_fn,
    age_threshold_a: float,
    age_threshold_c: float,
    get_worktree_base_path_fn,
) -> WorktreeClassification:
    """Pass 3: classify a single collected entry."""
    return classify_worktree(
        worktree_path=entry["path"],
        branch=entry.get("branch"),
        age_days=entry["age_days"],
        is_dirty=entry["is_dirty"],
        is_locked=entry["is_locked"],
        lock_pid_liveness=entry["lock_pid_liveness"],
        plan_orphan_groups=plan_orphan_groups,
        classify_merge_status_fn=classify_merge_status_fn,
        age_threshold_a=age_threshold_a,
        age_threshold_c=age_threshold_c,
        lock_pid=entry.get("lock_pid"),
        lock_command=entry.get("lock_command"),
        repo_nickname=entry.get("repo_nickname"),
    )


# ---------------------------------------------------------------------------
# Report formatters (F20 text + F21 JSON)
# ---------------------------------------------------------------------------
def _format_text(
    classifications: list[WorktreeClassification],
    *,
    failed_repos: list[dict] | None = None,
    repos_scanned: int = 0,
) -> str:
    """Group by tier; emit text report.

    Spec § Output (text) requires separate LOCKED-live / LOCKED-orphan /
    LOCKED-unknown / DIRTY sections plus a "Scan complete" footer line
    (F20). All sections are always emitted (possibly empty) so jq-style
    downstream consumers can rely on the section ordering.

    F19: failed_repos surfaces per-repo scan failures (consumed by Task 2.7
    CLI's exit-code-1 path). Footer reads e.g.
    "Scan complete: 5 candidates; 2 scan failures; exit 1."
    """
    failed_repos = failed_repos or []
    by_tier: dict[str, list[WorktreeClassification]] = {tier: [] for tier in _TIER_ORDER}
    for c in classifications:
        by_tier.setdefault(c.tier, []).append(c)

    lines: list[str] = [
        f"[mahavishnu worktree scan] started {datetime.now(UTC).isoformat()}",
        "",
    ]

    # Per-tier sections (always emitted; count 0 if empty).
    for tier in _TIER_ORDER:
        bucket = by_tier.get(tier, [])
        lines.append(f"Tier {tier} ({len(bucket)}):")
        for c in bucket:
            lines.append(f"  {c}")
        lines.append("")

    # LOCKED sections (F20) — only entries with a parsed lock PID are "live".
    live = [
        c for c in classifications
        if c.pid_liveness == "alive" and c.lock_pid is not None
    ]
    orphan = [c for c in classifications if c.pid_liveness == "dead"]
    unknown = [c for c in classifications if c.pid_liveness == "unknown"]
    lines.append(f"LOCKED-live (cannot remove without verification, {len(live)}):")
    for c in live:
        lines.append(
            f"  {c}  pid={c.lock_pid} command={c.lock_command!r}"
        )
    lines.append(f"LOCKED-orphan (PID dead, can unlock+remove, {len(orphan)}):")
    for c in orphan:
        lines.append(f"  {c}")
    lines.append(f"LOCKED-unknown (lock parse failed, manual review, {len(unknown)}):")
    for c in unknown:
        lines.append(f"  {c}")
    lines.append("")

    # DIRTY section (F20): one line per dirty classification.
    dirty = [c for c in classifications if c.is_dirty]
    lines.append(
        f"DIRTY ({sum(c.modified_count for c in dirty)} modified, "
        f"{sum(c.stash_count for c in dirty)} stashes, "
        f"{sum(c.untracked_count for c in dirty)} untracked; "
        f"full detail with --include-dirty, {len(dirty)}):"
    )
    for c in dirty:
        lines.append(f"  {c}")
    lines.append("")

    # F19: per-repo failures before the footer so operators see which repos failed.
    if failed_repos:
        lines.append(f"SCAN-FAILURES ({len(failed_repos)} repo(s) failed):")
        for f in failed_repos:
            lines.append(f"  {f['path']}: {f['reason']}")
        lines.append("")

    # Footer (F20 + F19): exit code reflects whether any repo scan failed.
    exit_code = 1 if failed_repos else 0
    lines.append(
        f"Scan complete: {len(classifications)} candidates; "
        f"{len(failed_repos)} scan failures; exit {exit_code}."
    )
    return "\n".join(lines)


def _format_json(
    classifications: list[WorktreeClassification],
    *,
    failed_repos: list[dict] | None = None,
    repos_scanned: int = 0,
) -> str:
    """Group by tier; emit JSON report per spec § Output (JSON).

    F21 + F19 fixes:
      - tier_x_cross_repo_orphan is grouped by `group_id` with each record
        carrying `date` + `pattern` + `entries[ {repo, path, branch} ]`
      - locked_live[] is filtered to entries where
        `pid_liveness == "alive" AND lock_pid is not None`, and each entry
        carries the real `pid` + `command` instead of `None` placeholders.
      - scan_metadata.failed_repos: list of {path, reason} for per-repo
        scan failures (consumed by Task 2.7's CLI exit-code-1 path).
    """
    failed_repos = failed_repos or []

    def _base_entry(c: WorktreeClassification) -> dict:
        return {
            "tier": c.tier,
            "is_dirty": c.is_dirty,
            "is_locked": c.is_locked,
            "pid_liveness": c.pid_liveness,
            "stash_count": c.stash_count,
            "modified_count": c.modified_count,
            "untracked_count": c.untracked_count,
            "cross_repo_group_id": c.cross_repo_group_id,
            "notes": c.notes,
            "repo_nickname": c.repo_nickname,
            "branch": c.branch,
            "worktree_path": str(c.worktree_path) if c.worktree_path else None,
        }

    by_tier: dict[str, list[dict]] = {tier: [] for tier in _TIER_ORDER}
    for c in classifications:
        by_tier.setdefault(c.tier, []).append(_base_entry(c))

    # F21 §3: tier_x_cross_repo_orphan[] — group by group_id.
    # group_id format is `<YYYY-MM-DD>-<pattern-slug>` (date is 10 chars).
    tier_x_by_group: dict[str, list[WorktreeClassification]] = {}
    for c in classifications:
        if c.tier != "X" or c.cross_repo_group_id is None:
            continue
        tier_x_by_group.setdefault(c.cross_repo_group_id, []).append(c)
    tier_x_cross_repo_orphan: list[dict] = []
    for group_id, classes in sorted(tier_x_by_group.items()):
        # date is the first 10 chars (YYYY-MM-DD); pattern is the rest.
        date = group_id[:10] if len(group_id) >= 10 else ""
        pattern = group_id[11:] if len(group_id) > 11 else group_id
        entries = [
            {
                "repo": cls.repo_nickname,
                "path": str(cls.worktree_path) if cls.worktree_path else None,
                "branch": cls.branch,
            }
            for cls in classes
        ]
        tier_x_cross_repo_orphan.append(
            {
                "group_id": group_id,
                "date": date,
                "pattern": pattern,
                "entries": entries,
            }
        )

    # F21 §2: locked_live[] — only entries with a parsed PID, real values.
    locked_live = [
        {
            **_base_entry(c),
            "pid": c.lock_pid,
            "command": c.lock_command,
            "liveness": c.pid_liveness,
        }
        for c in classifications
        if c.pid_liveness == "alive" and c.lock_pid is not None
    ]

    # F19: scan_metadata carries failed_repos for the Task 2.7 CLI.
    output = {
        "scan_metadata": {
            "started_at": datetime.now(UTC).isoformat(),
            "repos_scanned": repos_scanned,
            "thresholds": {"tier_a_min_days": 30.0, "tier_c_min_days": 9.0},
            "failed_repos": failed_repos,
        },
        "tier_a_merged": by_tier.get("A-merged", []),
        "tier_a_merged_dirty": by_tier.get("A-merged-dirty", []),
        "tier_a_orphan_detached": by_tier.get("A-orphan-detached", []),
        "tier_a_orphan_detached_dirty": by_tier.get("A-orphan-detached-dirty", []),
        "tier_x_cross_repo_orphan": tier_x_cross_repo_orphan,
        "tier_b": by_tier.get("B", []),
        "tier_c": by_tier.get("C", []),
        "tier_d": by_tier.get("D", []),
        "locked_live": locked_live,
        "locked_orphan": [
            _base_entry(c) for c in classifications if c.pid_liveness == "dead"
        ],
        "locked_unknown": [
            _base_entry(c) for c in classifications if c.pid_liveness == "unknown"
        ],
        "dirty": [
            _base_entry(c) for c in classifications if c.is_dirty
        ],
    }
    return json.dumps(output, indent=2)


__all__ = [
    "PLAN_ORPHAN_PATTERNS",
    "PidLiveness",
    "Tier",
    "WorktreeClassification",
    "_collect_repo",
    "_format_json",
    "_format_text",
    "_get_lock_pid_liveness",
    "_group_plan_orphans",
    "_is_worktree_locked",
    "_run_git_scanned",
    "_run_ps",
    "classify_worktree",
    "scan_worktrees",
    "scan_worktrees_with_status",
]
