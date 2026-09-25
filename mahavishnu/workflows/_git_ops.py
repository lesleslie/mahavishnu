"""Subprocess git wrapper for clone_refactor DAG.

Passes diffs via stdin (never argv — avoids injection through malformed diff headers).
Raises typed exceptions per REQ-CLONE-013.

Implements: REQ-CLONE-011, REQ-CLONE-013
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ---- Typed exceptions (REQ-CLONE-013) ------------------------------------

class GitApplyConflictError(Exception):
    """Structured conflict from `git apply --check`. Never retried."""

    def __init__(self, diff_offset: int, conflict_marker: str, stderr: str) -> None:
        super().__init__(f"GitApplyConflictError at diff_offset={diff_offset}")
        self.diff_offset = diff_offset
        self.conflict_marker = conflict_marker
        self.stderr = stderr


class GitCommitFailedError(Exception):
    """Base for both transient and permanent commit failures."""

    def __init__(self, stderr: str, exit_code: int) -> None:
        super().__init__(f"git commit failed (exit_code={exit_code}): {stderr}")
        self.stderr = stderr
        self.exit_code = exit_code


class GitCommitTransientError(GitCommitFailedError):
    """Index lock contention or brief I/O. Retried up to retries=2 times.

    Implements: REQ-CLONE-013
    """

    def __init__(self, reason: str, stderr: str) -> None:
        super().__init__(stderr, exit_code=-1)
        self.reason = reason


class GitCommitPermanentError(GitCommitFailedError):
    """Permission denied, disk full, pre-commit hook failure, malformed
    message, missing user.email/user.name, repo in detached state. NOT
    retried — propagates immediately.

    Implements: REQ-CLONE-013
    """

    def __init__(self, reason: str, stderr: str, exit_code: int) -> None:
        super().__init__(stderr, exit_code=exit_code)
        self.reason = reason


class GitCommandTimeoutError(GitCommitTransientError):
    """Subprocess exceeded timeout. SF-B5: classified as Transient so Prefect
    retries it; the underlying git operation may have been partway through
    and a retry is safer than abandoning.

    Implements: REQ-CLONE-013 (via Transient subclass)
    """

    def __init__(self, timeout_seconds: float, cmd: list[str]) -> None:
        super().__init__(reason="timeout", stderr=f"timeout after {timeout_seconds}s")
        self.timeout_seconds = timeout_seconds
        self.cmd = cmd


class StashPopFailedError(Exception):
    """Plain `git stash pop` failed. SF-B4: must be raised (not swallowed) so
    the @flow caller records a typed error on the RepoCommit.

    Implements: REQ-CLONE-011
    """

    def __init__(self, stderr: str, exit_code: int) -> None:
        super().__init__(f"git stash pop failed (exit_code={exit_code}): {stderr}")
        self.stderr = stderr
        self.exit_code = exit_code


# ---- Stderr classification (REQ-CLONE-013) --------------------------------

# (human_readable_reason, regex)
_TRANSIENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("index.lock contention", re.compile(r"Unable to create \.git/index\.lock")),
    ("resource_lock_failure", re.compile(r"fatal: unable to lock")),
    ("connection_reset", re.compile(r"Connection reset")),
    ("resource_unavailable", re.compile(r"Resource temporarily unavailable")),
)


def _classify_commit_failure(stderr: str, exit_code: int) -> GitCommitFailedError:
    """Match stderr against transient patterns; otherwise permanent.

    SF-m5: negative exit codes mean the process was killed by a signal
    (e.g., SIGKILL=-9, SIGTERM=-15). Classify as Permanent with a
    signal-specific reason so operators can distinguish signal-kills from
    command-level failures.
    """
    if exit_code < 0:
        return GitCommitPermanentError(
            reason=f"signal_{-exit_code}",
            stderr=stderr,
            exit_code=exit_code,
        )
    for reason_label, pattern in _TRANSIENT_PATTERNS:
        if pattern.search(stderr):
            return GitCommitTransientError(reason=reason_label, stderr=stderr)
    return GitCommitPermanentError(reason="see_stderr", stderr=stderr, exit_code=exit_code)


# ---- Subprocess helpers ---------------------------------------------------

# SF-B5: timeout for any git subprocess call. 120s is generous for any
# git operation; tighten to 30s for `apply --check` if needed.
_GIT_SUBPROCESS_TIMEOUT_SECONDS = 120.0


async def _run_git(
    repo_path: Path,
    *args: str,
    stdin_data: str | None = None,
    check: bool = True,
    timeout_seconds: float = _GIT_SUBPROCESS_TIMEOUT_SECONDS,
) -> tuple[str, str, int]:
    """Run `git -C repo_path <args>` with optional stdin. Returns (stdout, stderr, exit_code).

    SF-B5: bounded by timeout_seconds; on timeout, kills the subprocess and
    raises GitCommandTimeoutError (Transient subclass — Prefect retries).
    """
    cmd = ["git", "-C", str(repo_path), *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    # Conditionally pass input= so that when no data is being sent, we call
    # proc.communicate() with no kwargs — matches the test mock signature
    # exactly and is identical to passing input=None (the asyncio default).
    comm_kwargs: dict[str, Any] = {}
    if stdin_data is not None:
        comm_kwargs["input"] = stdin_data.encode()
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(**comm_kwargs),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise GitCommandTimeoutError(timeout_seconds=timeout_seconds, cmd=list(cmd))
    stdout = stdout_b.decode().strip() if stdout_b else ""
    stderr = stderr_b.decode().strip() if stderr_b else ""
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {args} failed (exit={proc.returncode}): {stderr}")
    return stdout, stderr, proc.returncode or 0


# ---- Public API -----------------------------------------------------------

async def git_apply(repo_path: Path, diff: str) -> None:
    """Apply diff via stdin. Raises GitApplyConflictError on conflict."""
    # Validate path
    repo_path = repo_path.resolve()
    if not (repo_path / ".git").exists():
        raise ValueError(f"repo_path {repo_path} is not a git repo")

    # Reject diffs with suspicious patterns (defensive — REQ security note in §6.2)
    for bad in ("Binary files", "rename to /dev/", "rename from /dev/"):
        if bad in diff:
            raise ValueError(f"diff contains disallowed pattern: {bad!r}")

    # First: `git apply --check` to detect conflicts cleanly
    try:
        await _run_git(repo_path, "apply", "--check", stdin_data=diff, timeout_seconds=30.0)
    except RuntimeError as exc:
        msg = str(exc)
        # Extract diff_offset and conflict_marker from stderr
        offset_match = re.search(r"@@ -(\d+)", msg)
        diff_offset = int(offset_match.group(1)) if offset_match else 0
        marker_match = re.search(r"@@[^@]+@@.*", msg)
        if marker_match:
            conflict_marker = marker_match.group(0)
        else:
            # Fall back to first meaningful stderr line (e.g. "error: ...")
            error_lines = [
                ln.strip()
                for ln in msg.split("\n")
                if ln.strip()
                and "git apply" not in ln.lower()
                and "exit=" not in ln
            ]
            conflict_marker = error_lines[0] if error_lines else msg[:200].strip()
        raise GitApplyConflictError(
            diff_offset=diff_offset,
            conflict_marker=conflict_marker,
            stderr=msg,
        ) from exc

    # Apply for real
    await _run_git(repo_path, "apply", stdin_data=diff)


async def git_commit(repo_path: Path, message: str) -> str:
    """Commit and return SHA. Raises GitCommitTransientError or GitCommitPermanentError."""
    repo_path = repo_path.resolve()
    _, stderr, exit_code = await _run_git(
        repo_path,
        "-c",
        "user.email=les@wedgwoodwebworks.com",
        "-c",
        "user.name=les",
        "commit",
        "-F",
        "-",
        stdin_data=message,
        check=False,
    )
    if exit_code != 0:
        raise _classify_commit_failure(stderr=stderr, exit_code=exit_code)
    # Get the new SHA
    sha, _, _ = await _run_git(repo_path, "rev-parse", "HEAD")
    return sha


async def current_head_sha(repo_path: Path) -> str:
    """Return the 40-char hex SHA of HEAD."""
    repo_path = repo_path.resolve()
    sha, _, _ = await _run_git(repo_path, "rev-parse", "HEAD")
    return sha


async def stash_push(repo_path: Path) -> str | None:
    """Plain `git stash` (NOT --keep-index). Returns the stash ref like
    'stash@{0}' when a stash was created, or None when there were no local
    changes to save.

    Implements: REQ-CLONE-011
    SF-m8 note: plain `git stash` does NOT stash staged-only changes. If
    the repo has staged but no unstaged changes, this exits 0 with "No
    local changes to save" — but no stash@{0} entry is created. Callers
    must handle the None return by skipping stash_pop (otherwise pop
    fails with "stash@{0} is not a valid reference").
    """
    repo_path = repo_path.resolve()
    stdout, _, _ = await _run_git(repo_path, "stash", "push", "-m", "clone-refactor-WIP")
    if "No local changes to save" in stdout:
        return None
    return "stash@{0}"  # canonical reference for most-recent stash


async def stash_pop(repo_path: Path, stash_ref: str = "stash@{0}") -> None:
    """Pop the stash. SF-B4: raises StashPopFailedError on non-zero exit
    (previously swallowed with check=False — this was the silent-failure
    bug that left the working tree dirty).

    Implements: REQ-CLONE-011
    """
    repo_path = repo_path.resolve()
    _, stderr, exit_code = await _run_git(
        repo_path, "stash", "pop", stash_ref, check=False
    )
    if exit_code != 0:
        raise StashPopFailedError(stderr=stderr, exit_code=exit_code)


async def diff_files(repo_path: Path) -> list[str]:
    """Files modified by the last commit."""
    repo_path = repo_path.resolve()
    stdout, _, _ = await _run_git(
        repo_path, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    )
    return [f for f in stdout.splitlines() if f]


async def is_working_tree_clean(repo_path: Path) -> bool:
    """`git status --porcelain` empty → True."""
    repo_path = repo_path.resolve()
    stdout, _, _ = await _run_git(repo_path, "status", "--porcelain")
    return stdout == ""
