"""3-way merge helper — shells out to ``git merge-file``.

We deliberately do NOT implement our own merge algorithm. The user-facing
contract is "merge conflicts must return a structured error"; the
machine-facing contract is "git's existing 3-way merge is authoritative
for content conflict detection." ``git merge-file`` does both — its
exit code signals clean merge (0), conflict (1), or trunk (>=2), and
its output carries the conflict markers we surface to the caller.

This module is the ONLY place that shells out to git. The MCP tool layer
in :mod:`mahavishnu.mcp.tools.worker_contract_tools` consumes this
helper as ``merge.merge_three_way(base, ours, theirs)``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
import tempfile

logger = logging.getLogger(__name__)


class MergeConflictError(Exception):
    """Raised when ``git merge-file`` exits with code 1 (clean conflict).

    Carries the merged-with-markers content so the caller can inspect
    the conflict regions or stash them for manual resolution.
    """

    def __init__(
        self,
        *,
        path: str,
        merged: str,
        base: str,
        ours: str,
        theirs: str,
    ) -> None:
        super().__init__(f"3-way merge conflict for {path!r}")
        self.path = path
        self.merged = merged
        self.base = base
        self.ours = ours
        self.theirs = theirs


class MergeFailureError(Exception):
    """Raised when ``git merge-file`` exits with code >= 2 (trunk / fatal)."""


@dataclass(frozen=True)
class MergeResult:
    """The successful outcome of a 3-way merge."""

    merged: str
    conflict_count: int


async def merge_three_way(
    *,
    base: str,
    ours: str,
    theirs: str,
    label: str = "<anonymous>",
    git_merge_file: str = "git",
) -> MergeResult:
    """Run ``git merge-file`` over the (base, ours, theirs) triple.

    Returns a :class:`MergeResult` on clean merge (exit code 0). Raises
    :class:`MergeConflictError` on content conflicts (exit code 1) and
    :class:`MergeFailureError` on trunk failures (exit code >= 2).

    The merge runs in ``asyncio.create_subprocess_exec`` so the event
    loop is not blocked. Files are written to a tempdir and deleted on
    completion.
    """
    with tempfile.TemporaryDirectory(prefix="settle-merge-") as tmp_str:
        tmp = Path(tmp_str)
        base_path = tmp / "base"
        ours_path = tmp / "ours"
        theirs_path = tmp / "theirs"
        base_path.write_text(base)
        ours_path.write_text(ours)
        theirs_path.write_text(theirs)

        # ``git merge-file`` exit codes:
        #   0 — clean merge (no conflicts)
        #   1 — conflicts; ``ours`` is now the merged-with-markers file
        # >=2 — fatal error (bad invocation, I/O, etc.)
        proc = await asyncio.create_subprocess_exec(
            git_merge_file,
            "merge-file",
            "-p",  # write merged result to stdout
            "-L",
            "base",
            "-L",
            "ours",
            "-L",
            "theirs",
            str(ours_path),
            str(base_path),
            str(theirs_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        merged = stdout.decode("utf-8", errors="replace")

        if proc.returncode == 0:
            return MergeResult(merged=merged, conflict_count=0)

        if proc.returncode == 1:
            # Count conflict regions by counting "<<<<<<< " markers.
            # git emits three markers per conflict hunk: <<<<<<<,
            # =======, >>>>>>>. Counting the leading ones is the
            # canonical heuristic used by git-merge-file consumers.
            conflict_count = sum(1 for line in merged.splitlines() if line.startswith("<<<<<<< "))
            logger.warning(
                "settle_merge: conflict for label=%r conflict_count=%d",
                label,
                conflict_count,
            )
            raise MergeConflictError(
                path=label,
                merged=merged,
                base=base,
                ours=ours,
                theirs=theirs,
            )

        # Exit >=2 — fatal.
        stderr_text = stderr.decode("utf-8", errors="replace")
        logger.error(
            "settle_merge: git merge-file fatal label=%r stderr=%s",
            label,
            stderr_text.strip(),
        )
        raise MergeFailureError(
            f"git merge-file failed (exit={proc.returncode}) for {label!r}: {stderr_text.strip()}"
        )


def merge_three_way_sync(
    *,
    base: str,
    ours: str,
    theirs: str,
    label: str = "<anonymous>",
    git_merge_file: str = "git",
) -> MergeResult:
    """Synchronous variant for CLI / non-asyncio callers."""
    with tempfile.TemporaryDirectory(prefix="settle-merge-") as tmp_str:
        tmp = Path(tmp_str)
        base_path = tmp / "base"
        ours_path = tmp / "ours"
        theirs_path = tmp / "theirs"
        base_path.write_text(base)
        ours_path.write_text(ours)
        theirs_path.write_text(theirs)

        import subprocess

        result = subprocess.run(
            [
                git_merge_file,
                "merge-file",
                "-p",
                "-L",
                "base",
                "-L",
                "ours",
                "-L",
                "theirs",
                str(ours_path),
                str(base_path),
                str(theirs_path),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        merged = result.stdout
        if result.returncode == 0:
            return MergeResult(merged=merged, conflict_count=0)
        if result.returncode == 1:
            raise MergeConflictError(
                path=label,
                merged=merged,
                base=base,
                ours=ours,
                theirs=theirs,
            )
        raise MergeFailureError(
            f"git merge-file failed (exit={result.returncode}) for {label!r}: "
            f"{result.stderr.strip()}"
        )
