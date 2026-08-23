"""Dhara-backed worktree registry (ADR 015 v4 §11).

Maps the v4 logical keyspace (``mahavishnu:worktree-registry:*``) onto
Dhara's SQL substrate via the ``sql_proxy_execute`` /
``sql_proxy_query`` MCP tools (see ``mahavishnu/core/dhara_client.py``).

Keyspace layout (v4 §11):

    Primary record:   :mahavishnu:worktree-registry:<handle_id>
        -> JSON(WorktreeHandle)            (no TTL; durable)

    Secondary idx:   :mahavishnu:worktree-registry:idx:principal:<p>
        SET <handle_id>                       (no TTL)

    Secondary idx:   :mahavishnu:worktree-registry:idx:repo:<r>
        SET <handle_id>                       (no TTL)

    Distributed lock: :mahavishnu:worktree-registry:lock:<p>:<r>:<b>
        lease_token                           (TTL = lease_ttl)

    Audit log:       :mahavishnu:audit-log:<YYYY-MM-DD>:<handle_id>:<seq>
        JSON(AuditEvent)                      (no TTL)

The v4 logical keyspace uses SET semantics for the indexes; the SQL
substrate implements these as auxiliary tables with multi-row writes
(since SQL doesn't have native SETs). This module keeps the
keyspace abstraction intact for callers.

Phase 4 migration calls ``register_handles`` with the output of
``pre_migration_discover()``; Phase 2 cache work uses
``list_handles`` / ``get_handle`` for retrieval.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mahavishnu.auth import Principal

from .types import LocalWorktreeRef, RemoteWorktreeRef, WorktreeHandle

if TYPE_CHECKING:
    from collections.abc import Iterable


# SQL schema (executed once via CREATE TABLE IF NOT EXISTS).
# Note: principal_uid is added so we can round-trip the full Principal
# (uid + name) instead of lossy-encoding uid as 0 (see security review).
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS mahavishnu_worktree_registry (
        handle_id       TEXT PRIMARY KEY,
        principal       TEXT NOT NULL,
        principal_uid   INTEGER,
        repo            TEXT NOT NULL,
        branch          TEXT NOT NULL,
        base_ref        TEXT,
        created_at      TEXT NOT NULL,
        sha256          TEXT NOT NULL DEFAULT '',
        bytes_size      INTEGER NOT NULL DEFAULT 0,
        cleanup_policy  TEXT,
        provenance      TEXT NOT NULL,
        storage_ref_json TEXT NOT NULL,
        backend_kind    TEXT NOT NULL,
        origin_path     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mahavishnu_worktree_registry_idx_principal (
        principal  TEXT NOT NULL,
        handle_id  TEXT NOT NULL,
        PRIMARY KEY (principal, handle_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mahavishnu_worktree_registry_idx_repo (
        repo       TEXT NOT NULL,
        handle_id  TEXT NOT NULL,
        PRIMARY KEY (repo, handle_id)
    )
    """,
)


def _ensure_schema(client: Any) -> None:
    """Sync wrapper exists for type documentation; use _ensure_schema_async."""
    raise NotImplementedError(
        "Use the async helper _ensure_schema_async; this sync "
        "wrapper exists only for type documentation."
    )


async def _ensure_schema_async(client: Any) -> None:
    for stmt in SCHEMA_STATEMENTS:
        await client.execute(stmt)


def _handle_to_row(handle: WorktreeHandle) -> dict[str, Any]:
    """Flatten a WorktreeHandle to a SQL parameter dict.

    Validates paths at write time so path-injection attempts are rejected
    before the handle reaches storage.
    """
    storage_ref = handle.storage_ref
    if isinstance(storage_ref, LocalWorktreeRef):
        _validate_storage_path(str(storage_ref.path), "local")

    return {
        "handle_id": handle.handle_id,
        "principal": handle.principal.name,
        "principal_uid": handle.principal.uid,
        "repo": handle.repo,
        "branch": handle.branch,
        "base_ref": handle.base_ref,
        "created_at": handle.created_at.isoformat(),
        "sha256": handle.sha256,
        "bytes_size": handle.bytes_size,
        "cleanup_policy": handle.cleanup_policy,
        "provenance": handle.provenance,
        "storage_ref_json": json.dumps(_storage_ref_to_dict(storage_ref)),
        "backend_kind": storage_ref.backend_kind,
        "origin_path": str(storage_ref.path) if isinstance(storage_ref, LocalWorktreeRef) else "",
    }


def _storage_ref_to_dict(storage_ref: Any) -> dict[str, Any]:
    """Serialize a WorktreeRef to a dict. Works for slotted dataclasses
    (no __dict__) via dataclasses.asdict which reads __slots__ correctly.
    Path objects are converted to str for JSON serialization.
    """

    def _normalize(v: Any) -> Any:
        if isinstance(v, Path):
            return str(v)
        if isinstance(v, dict):
            return {k: _normalize(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_normalize(x) for x in v]
        return v

    if is_dataclass(storage_ref):
        d = asdict(storage_ref)
    else:
        d = dict(storage_ref.__dict__) if hasattr(storage_ref, "__dict__") else {}
    d = _normalize(d)
    # Always include backend_kind at the top level for round-trip
    d["backend_kind"] = getattr(storage_ref, "backend_kind", "local")
    return d


def _validate_storage_path(path_str: str, backend_kind: str) -> str:
    """Validate a path string before using it as a filesystem path.

    Rejects relative paths, parent-traversal (``..``), and dash-prefixed
    arguments (which some CLIs treat as flags).
    """
    if not path_str:
        raise ValueError(f"{backend_kind} storage path is empty")
    p = Path(path_str)
    if not p.is_absolute():
        raise ValueError(f"{backend_kind} storage path must be absolute: {path_str!r}")
    if any(part == ".." for part in p.parts):
        raise ValueError(f"{backend_kind} storage path contains '..': {path_str!r}")
    return path_str


def _row_to_handle(row: dict[str, Any]) -> WorktreeHandle:
    """Build a WorktreeHandle from a SQL row."""
    storage_data = json.loads(row["storage_ref_json"])
    backend_kind = row["backend_kind"]

    if backend_kind == "local" and "path" in storage_data:
        _validate_storage_path(storage_data["path"], backend_kind)
        storage_ref: Any = LocalWorktreeRef(
            path=Path(storage_data["path"]),
            worktree_id=storage_data.get("worktree_id", row["handle_id"]),
        )
    elif backend_kind in ("s3", "gcs", "azure", "bundle"):
        # RemoteWorktreeRef stores the actual backend_kind in
        # storage_data so callers can roundtrip the original
        # cloud backend without losing fidelity.
        storage_ref = RemoteWorktreeRef(
            bucket=storage_data.get("bucket", ""),
            key=storage_data.get("key", ""),
            worktree_id=storage_data.get("worktree_id", row["handle_id"]),
        )
    else:
        # Unknown backend — fail loud rather than silently downgrading
        # (which would mask bugs and silently misroute work).
        raise ValueError(f"Unknown backend_kind: {backend_kind!r}")

    # Preserve principal_uid round-trip; NULL for anonymous
    principal_uid = row.get("principal_uid")
    if principal_uid is None:
        principal = Principal(uid=None, name=row["principal"])
    else:
        principal = Principal(uid=int(principal_uid), name=row["principal"])

    return WorktreeHandle(
        handle_id=row["handle_id"],
        principal=principal,
        repo=row["repo"],
        branch=row["branch"],
        base_ref=row.get("base_ref", "") or "",
        created_at=datetime.fromisoformat(row["created_at"]),
        storage_ref=storage_ref,
        sha256=row.get("sha256", "") or "",
        bytes_size=row.get("bytes_size", 0) or 0,
        cleanup_policy=row.get("cleanup_policy"),
        provenance=row.get("provenance", "v4"),
    )


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------


async def register_handles(
    client: Any,
    handles: Iterable[WorktreeHandle],
    *,
    caller: Principal,
    ensure_schema: bool = True,
) -> int:
    """Register a batch of WorktreeHandles into the Dhara registry.

    Args:
        client: Object exposing ``async execute(sql, params)`` and
            ``async query(sql, params)``. In production this is a
            ``DharaThinClient``; in tests a fake.
        handles: Iterable of ``WorktreeHandle`` to register.
        caller: Principal performing the registration. Must have
            scope ``worktree:register`` and own each handle's principal
            (or have scope ``worktree:register-any``).
        ensure_schema: If True (default), runs the
            ``CREATE TABLE IF NOT EXISTS`` statements first.
            Set False for tests that have already initialized the schema.

    Returns:
        Number of handles registered.

    Note on atomicity: each handle does 3 separate INSERTs (primary +
    two indexes). Without an enclosing transaction, a failure between
    the primary and an index write leaves the registry inconsistent.
    Dhara's sql_proxy MCP doesn't currently expose a ``BEGIN``/``COMMIT``
    tool, so for Phase 4 the migration script should re-run
    ``list_handles`` after the write to verify index consistency. A
    ``tx`` tool addition is tracked separately as follow-up.
    """
    if ensure_schema:
        await _ensure_schema_async(client)

    # Authorization check: caller must have the register scope
    # explicitly. We use "in scopes" rather than has_scope() because
    # Principal.has_scope treats empty scopes as "all" which is wrong
    # for security checks.
    has_register = "worktree:register" in caller.scopes
    has_admin = "worktree:register-any" in caller.scopes
    if not (has_register or has_admin):
        raise PermissionError(f"Principal {caller.name!r} lacks scope 'worktree:register'")

    count = 0
    for handle in handles:
        # Per-handle ownership: non-admin callers can only register
        # handles they own (same uid).
        if not has_admin and handle.principal.uid != caller.uid:
            raise PermissionError(
                f"Caller {caller.name!r} cannot register handle "
                f"{handle.handle_id!r} owned by "
                f"{handle.principal.name!r}"
            )

        row = _handle_to_row(handle)
        # Primary record (idempotent via UPSERT semantics)
        await client.execute(
            """
            INSERT OR REPLACE INTO mahavishnu_worktree_registry
              (handle_id, principal, principal_uid, repo, branch, base_ref,
               created_at, sha256, bytes_size, cleanup_policy,
               provenance, storage_ref_json, backend_kind, origin_path)
            VALUES
              (:handle_id, :principal, :principal_uid, :repo, :branch, :base_ref,
               :created_at, :sha256, :bytes_size, :cleanup_policy,
               :provenance, :storage_ref_json, :backend_kind, :origin_path)
            """,
            row,
        )
        # Secondary indexes (multi-row INSERT with unique constraint)
        await client.execute(
            """
            INSERT OR REPLACE INTO mahavishnu_worktree_registry_idx_principal
              (principal, handle_id)
            VALUES (:principal, :handle_id)
            """,
            {"principal": row["principal"], "handle_id": row["handle_id"]},
        )
        await client.execute(
            """
            INSERT OR REPLACE INTO mahavishnu_worktree_registry_idx_repo
              (repo, handle_id)
            VALUES (:repo, :handle_id)
            """,
            {"repo": row["repo"], "handle_id": row["handle_id"]},
        )
        count += 1
    return count


async def list_handles(
    client: Any,
    *,
    principal: str | None = None,
    repo: str | None = None,
    caller: Principal | None = None,
    all_tenants: bool = False,
) -> list[WorktreeHandle]:
    """List WorktreeHandles, optionally filtered by principal or repo.

    Multi-tenant safety: ``all_tenants=True`` requires ``caller`` to have
    scope ``worktree:list-all``. Without that explicit opt-in, the
    principal-scoped or repo-scoped filter is required.
    """
    if all_tenants:
        if caller is None or "worktree:list-all" not in caller.scopes:
            raise PermissionError(
                "Listing all tenants requires caller with scope 'worktree:list-all'"
            )
        rows = await client.query("SELECT * FROM mahavishnu_worktree_registry ORDER BY created_at")
        return [_row_to_handle(r) for r in rows]

    if principal is not None:
        rows = await client.query(
            """
            SELECT r.* FROM mahavishnu_worktree_registry r
              JOIN mahavishnu_worktree_registry_idx_principal p
                ON r.handle_id = p.handle_id
            WHERE p.principal = :principal
            ORDER BY r.created_at
            """,
            {"principal": principal},
        )
    elif repo is not None:
        rows = await client.query(
            """
            SELECT r.* FROM mahavishnu_worktree_registry r
              JOIN mahavishnu_worktree_registry_idx_repo x
                ON r.handle_id = x.handle_id
            WHERE x.repo = :repo
            ORDER BY r.created_at
            """,
            {"repo": repo},
        )
    else:
        # Refuse unfiltered listing — would leak across principals.
        raise PermissionError(
            "list_handles requires a principal, repo, or explicit all_tenants=True with admin scope"
        )

    return [_row_to_handle(r) for r in rows]


__all__ = [
    "SCHEMA_STATEMENTS",
    "list_handles",
    "register_handles",
]
