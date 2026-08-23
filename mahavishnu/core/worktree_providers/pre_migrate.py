"""Phase 4 pre-migration discovery (ADR 015 v4 §12).

The 83 misplaced worktrees (audit 2026-08-23) and any other worktrees
on disk pre-date the WorktreeHandle abstraction. This module discovers
them via ``git worktree list --porcelain`` and synthesizes a
``WorktreeHandle`` for each so the v4 Dhara-backed registry has a
starting point.

The synthesized handles carry ``provenance: "pre-v2-migration"``
metadata so consumers (and the eventual Phase 5 deprecation
``DEPRECATED_TOOLS`` entry) can distinguish them from handles
created via the v4 ``WorktreeProvider.create_worktree_handle`` flow.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mahavishnu.auth import Principal

from .types import LocalWorktreeRef, WorktreeHandle


# ----------------------------------------------------------------------------
# Porcelain parser
# ----------------------------------------------------------------------------


def parse_porcelain(output: str) -> list[dict[str, str]]:
    """Parse ``git worktree list --porcelain`` output.

    Each entry is a block of ``key value`` lines separated by blank
    lines. The keys are documented in ``git-worktree(1)``:

      worktree  <absolute path>
      HEAD      <ref>
      branch    <ref>          (only when checked out as a branch)
      detached  (only when HEAD is detached)
      commit    <oid>          (only when HEAD is detached)
      bare      (only when the worktree is bare)

    Returns:
        List of dicts (one per entry). Fields are stripped of the
        trailing key/value delimiter; ``HEAD`` is the full ref name
        (e.g. ``refs/heads/main``); ``branch`` is also a full ref.
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in output.splitlines():
        if not raw_line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = raw_line.partition(" ")
        current[key] = value
    if current:
        entries.append(current)
    return entries


# ----------------------------------------------------------------------------
# Repo inference
# ----------------------------------------------------------------------------


_REPO_NAME_RE = re.compile(r"^.*[/\\](?P<name>[^/\\]+)$")


def infer_repo(worktree_path: str) -> str:
    """Best-effort: return the basename of the worktree path.

    The path is expected to be the worktree directory itself, e.g.
    ``/Users/les/worktrees/agent-abc123`` returns ``agent-abc123``.
    For paths like ``/Users/les/worktrees/mahavishnu/feature-auth``
    this returns ``feature-auth`` (the leaf). For better accuracy,
    pass the result of a ``git -C <path> rev-parse --show-toplevel``
    and look at the basename, or cross-reference with repos.yaml.
    """
    m = _REPO_NAME_RE.match(worktree_path)
    if m:
        return m.group("name")
    return Path(worktree_path).name


# ----------------------------------------------------------------------------
# Synthesis
# ----------------------------------------------------------------------------


def synthesize_handle(
    repo_main_path: str,
    entry: dict[str, str],
    principal: Principal,
) -> WorktreeHandle:
    """Synthesize a WorktreeHandle from a parsed porcelain entry.

    Args:
        repo_main_path: Absolute path to the main repository (used for
            stable repo identification; the worktree's ``branch`` is
            derived from the porcelain ``branch`` field when present).
        entry: One parsed entry from ``parse_porcelain``.
        principal: The Principal under which to record this handle.
            For pre-v2 worktrees the typical choice is
            ``Principal.current()`` (local-host uid) or
            ``Principal.anonymous()`` (serverless).

    Returns:
        A WorktreeHandle with ``provenance="pre-v2-migration"``,
        ``sha256=""`` (computed lazily on first ``fetch()``), and
        ``bytes_size=0`` (computed lazily).
    """
    wt_path = Path(entry["worktree"])
    branch_ref = entry.get("branch", "")
    if branch_ref.startswith("refs/heads/"):
        branch = branch_ref.removeprefix("refs/heads/")
    elif branch_ref:
        branch = branch_ref
    else:
        branch = "detached-HEAD"

    base_ref = entry.get("HEAD", "")  # commit-ish ref or detached marker

    return WorktreeHandle(
        handle_id=uuid.uuid4().hex,
        principal=principal,
        repo=infer_repo(repo_main_path),
        branch=branch,
        base_ref=base_ref,
        created_at=datetime.now(UTC),
        storage_ref=LocalWorktreeRef(
            path=wt_path,
            worktree_id=uuid.uuid4().hex,
        ),
        sha256="",  # computed lazily on first fetch()
        bytes_size=0,  # computed lazily
        cleanup_policy=None,
        provenance="pre-v2-migration",
    )


def pre_migration_discover(
    main_repo: str,
    principal: Principal | None = None,
) -> list[WorktreeHandle]:
    """Discover all worktrees for ``main_repo`` and synthesize WorktreeHandles.

    Runs ``git -C <main_repo> worktree list --porcelain`` and maps each
    entry through :func:`synthesize_handle`. The synthesized handles
    are suitable for registering in the Dhara worktree registry via
    the Phase 4 migration script.

    Args:
        main_repo: Absolute path to the git main repository whose
            worktrees should be discovered.
        principal: Principal under which to record the handles.
            Defaults to ``Principal.current()``.

    Returns:
        List of synthesized WorktreeHandles (one per porcelain entry,
            including the main worktree).

    Raises:
        subprocess.CalledProcessError: If ``git worktree list``
            fails (e.g., main_repo is not a git repository).
    """
    if principal is None:
        principal = Principal.current()

    result = subprocess.run(
        ["git", "-C", main_repo, "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    entries = parse_porcelain(result.stdout)
    return [
        synthesize_handle(main_repo, entry, principal) for entry in entries
    ]


# ----------------------------------------------------------------------------
# JSON serialization helpers
# ----------------------------------------------------------------------------


def handle_to_jsonl_dict(handle: WorktreeHandle) -> dict[str, Any]:
    """Convert a WorktreeHandle to a JSONL-friendly dict.

    The Principal is flattened to a dict; timestamps are ISO 8601.
    Paths are stored as strings (JSON cannot represent ``Path`` directly
    without encoding, and ``asdict`` returns ``Path`` objects unchanged).
    frozensets are converted to lists for the same reason.
    """
    d = asdict(handle)
    d["principal"] = asdict(handle.principal)
    # frozenset (Principal.scopes) → list for JSON
    if isinstance(d["principal"].get("scopes"), frozenset):
        d["principal"]["scopes"] = sorted(d["principal"]["scopes"])
    d["created_at"] = handle.created_at.isoformat()
    d["storage_ref"] = asdict(handle.storage_ref)
    # Convert nested Path objects to strings for JSON serialization.
    if "path" in d["storage_ref"]:
        d["storage_ref"]["path"] = str(d["storage_ref"]["path"])
    return d


__all__ = [
    "handle_to_jsonl_dict",
    "infer_repo",
    "parse_porcelain",
    "pre_migration_discover",
    "synthesize_handle",
]
