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

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from mahavishnu.auth import Principal

from .types import WorktreeHandle


# SQL schema (executed once via CREATE TABLE IF NOT EXISTS).
SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS mahavishnu_worktree_registry (
        handle_id       TEXT PRIMARY KEY,
        principal       TEXT NOT NULL,
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
    """Create the worktree-registry tables if they don't exist.

    ``client`` must expose ``async execute(sql, params)``.
    """
    for stmt in SCHEMA_STATEMENTS:
        # The execute() method is async; caller (register_handles or
        # the migration script) is responsible for awaiting it.
        # We can't await here without making this function async, so
        # we yield the coroutines via a small helper. Simpler:
        # callers call ``await _ensure_schema_async(client)`` instead.
        raise NotImplementedError(
            "Use the async helper _ensure_schema_async; this sync "
            "wrapper exists only for type documentation."
        )


async def _ensure_schema_async(client: Any) -> None:
    for stmt in SCHEMA_STATEMENTS:
        await client.execute(stmt)


def _handle_to_row(handle: WorktreeHandle) -> dict[str, Any]:
    """Flatten a WorktreeHandle to a SQL parameter dict."""
    return {
        "handle_id": handle.handle_id,
        "principal": handle.principal.name,
        "repo": handle.repo,
        "branch": handle.branch,
        "base_ref": handle.base_ref,
        "created_at": handle.created_at.isoformat(),
        "sha256": handle.sha256,
        "bytes_size": handle.bytes_size,
        "cleanup_policy": handle.cleanup_policy,
        "provenance": handle.provenance,
        "storage_ref_json": json.dumps(_storage_ref_to_dict(handle.storage_ref)),
        "backend_kind": handle.storage_ref.backend_kind,
        "origin_path": str(handle.storage_ref.path)
        if hasattr(handle.storage_ref, "path")
        else "",
    }


def _storage_ref_to_dict(storage_ref: Any) -> dict[str, Any]:
    """Serialize a WorktreeRef to a dict."""
    if hasattr(storage_ref, "__dict__"):
        d = dict(storage_ref.__dict__)
    else:
        d = {"backend_kind": storage_ref.backend_kind}
    return d


def _row_to_handle(row: dict[str, Any]) -> WorktreeHandle:
    """Build a WorktreeHandle from a SQL row."""
    from .types import LocalWorktreeRef, RemoteWorktreeRef

    storage_data = json.loads(row["storage_ref_json"])
    backend_kind = row["backend_kind"]

    if backend_kind == "local" and "path" in storage_data:
        from pathlib import Path

        storage_ref: Any = LocalWorktreeRef(
            path=Path(storage_data["path"]),
            worktree_id=storage_data.get("worktree_id", row["handle_id"]),
        )
    elif backend_kind in ("s3", "gcs", "azure", "bundle"):
        storage_ref = RemoteWorktreeRef(
            bucket=storage_data.get("bucket", ""),
            key=storage_data.get("key", ""),
            worktree_id=storage_data.get("worktree_id", row["handle_id"]),
        )
    else:
        # Unknown backend — fall back to LocalWorktreeRef
        from pathlib import Path

        storage_ref = LocalWorktreeRef(path=Path(""), worktree_id=row["handle_id"])

    principal = Principal(uid=0, name=row["principal"])

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
    ensure_schema: bool = True,
) -> int:
    """Register a batch of WorktreeHandles into the Dhara registry.

    Args:
        client: Object exposing ``async execute(sql, params)`` and
            ``async query(sql, params)``. In production this is a
            ``DharaThinClient``; in tests a fake.
        handles: Iterable of ``WorktreeHandle`` to register.
        ensure_schema: If True (default), runs the
            ``CREATE TABLE IF NOT EXISTS`` statements first.
            Set False for tests that have already initialized the schema.

    Returns:
        Number of handles registered (== number of INSERT statements
        executed; idempotent on conflict via INSERT OR REPLACE).
    """
    if ensure_schema:
        await _ensure_schema_async(client)

    count = 0
    for handle in handles:
        row = _handle_to_row(handle)
        # Primary record (idempotent via UPSERT semantics)
        await client.execute(
            """
            INSERT OR REPLACE INTO mahavishnu_worktree_registry
              (handle_id, principal, repo, branch, base_ref,
               created_at, sha256, bytes_size, cleanup_policy,
               provenance, storage_ref_json, backend_kind, origin_path)
            VALUES
              (:handle_id, :principal, :repo, :branch, :base_ref,
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
) -> list[WorktreeHandle]:
    """List WorktreeHandles, optionally filtered by principal or repo.

    Uses the secondary indexes when filters are provided. Falls back to
    a full scan otherwise.
    """
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
        rows = await client.query(
            "SELECT * FROM mahavishnu_worktree_registry ORDER BY created_at"
        )
    return [_row_to_handle(r) for r in rows]


__all__ = [
    "SCHEMA_STATEMENTS",
    "list_handles",
    "register_handles",
]
