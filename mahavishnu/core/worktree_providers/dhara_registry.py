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
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mahavishnu.auth import Principal

from .types import LocalWorktreeRef, RemoteWorktreeRef, WorktreeHandle

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


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

    Rejects:

    - empty strings
    - relative paths (must be absolute)
    - parent-traversal (``..``)
    - dash-prefixed paths (some CLIs treat these as flags, e.g. ``-rf /tmp``)
    - paths outside the configured worktree base directory

    The base-directory allowlist pins every registered path inside
    ``get_worktree_base_path()`` so the registry can't accumulate
    off-base entries. Symlink safety is enforced at consumer time
    (when the worktree is actually used), not here.
    """
    if not path_str:
        raise ValueError(f"{backend_kind} storage path is empty")
    p = Path(path_str)
    # Dash-prefix: a path string starting with `-` could be mis-parsed as
    # a CLI flag by downstream tooling (e.g. `rm -rf /tmp` if the path
    # was ever passed as an argument). Check the raw string rather than
    # ``p.parts[0]`` since absolute Unix paths always have ``/`` as
    # parts[0].
    if path_str.startswith("-"):
        raise ValueError(f"{backend_kind} storage path starts with dash (flag-like): {path_str!r}")
    if not p.is_absolute():
        raise ValueError(f"{backend_kind} storage path must be absolute: {path_str!r}")
    if any(part == ".." for part in p.parts):
        raise ValueError(f"{backend_kind} storage path contains '..': {path_str!r}")
    # Base-directory allowlist: the path must resolve to a location
    # under the configured worktree base.
    base = _worktree_base_resolved()
    try:
        candidate = p.resolve()
    except OSError as e:
        raise ValueError(
            f"{backend_kind} storage path cannot be resolved: {path_str!r} ({e})"
        ) from e
    if not _is_within(candidate, base):
        raise ValueError(f"{backend_kind} storage path {candidate} is outside worktree base {base}")
    return path_str


def _worktree_base_resolved() -> Path:
    """Resolve the worktree base directory. Lazy import to avoid a hard
    import cycle (``paths.py`` does not depend on dhara_registry, but
    ``dhara_registry`` is consumed by adapters that load oneiric config
    which in turn pulls ``paths.py``).
    """
    from mahavishnu.core.paths import get_worktree_base_path

    return get_worktree_base_path().resolve()


def _is_within(candidate: Path, base: Path) -> bool:
    """Return True iff ``candidate`` resolves to a path under ``base``.

    Uses ``Path.is_relative_to`` (Python 3.9+) which handles the
    trailing-separator edge case correctly. Both inputs are expected
    to be resolved absolute paths.
    """
    return candidate.is_relative_to(base)


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
        # ``backend_kind`` is required at construction (no default).
        # The column value is authoritative — it was written by
        # ``_handle_to_row`` from ``storage_ref.backend_kind`` and
        # reflects the actual backend identity (not a silent default).
        storage_ref = RemoteWorktreeRef(
            bucket=storage_data.get("bucket", ""),
            key=storage_data.get("key", ""),
            worktree_id=storage_data.get("worktree_id", row["handle_id"]),
            backend_kind=backend_kind,  # type: ignore[arg-type]
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


async def remove_handle(
    client: Any,
    handle_id: str,
    *,
    caller: Principal,
) -> bool:
    """Remove a single ``WorktreeHandle`` from the Dhara registry.

    Authorizes via:
      - Scope: caller must have ``worktree:remove`` OR admin override
        (``worktree:register-any``).
      - Ownership: non-admin callers can only remove handles they own
        (caller.uid == handle's principal_uid). Mirrors the per-handle
        ownership check in ``register_handles``.

    **Atomicity caveat (CONFIRMED):** Dhara's
    ``dhara/mcp/worktree_registry.py`` does NOT expose a
    ``multi_set`` / ``BEGIN`` / ``COMMIT`` transaction primitive.
    ``remove_handle`` is best-effort: delete primary first, then
    indexes. If a step fails mid-sequence, log a warning identifying
    the orphan state and continue (the next call will detect + report
    drift via ``worktree_registry_drift_total``).

    Atomic-remove is deferred to a separate Dhara-side PR.

    Returns ``True`` if the primary row was deleted, ``False`` if it
    was not found.
    """
    has_remove = "worktree:remove" in caller.scopes
    has_admin = "worktree:register-any" in caller.scopes
    if not (has_remove or has_admin):
        raise PermissionError(f"Principal {caller.name!r} lacks scope 'worktree:remove'")

    # Look up the primary to discover principal + uid + repo BEFORE
    # we delete the primary. If absent, return False without touching
    # indexes (no drift to report).
    rows = await client.query(
        "SELECT principal, principal_uid, repo FROM mahavishnu_worktree_registry "
        "WHERE handle_id = :handle_id",
        {"handle_id": handle_id},
    )
    if not rows:
        return False

    principal_name = rows[0]["principal"]
    owner_uid = rows[0].get("principal_uid")

    # Per-handle ownership check: non-admin callers can only remove
    # their own handles. owner_uid may be None for pre-v2 migrated
    # handles (anonymous in pre-migration world); in that case only
    # admin can remove (since we can't verify ownership).
    if not has_admin:
        if owner_uid is None or owner_uid != caller.uid:
            raise PermissionError(
                f"Principal {caller.name!r} cannot remove handle "
                f"{handle_id!r} owned by {principal_name!r}"
            )

    # Delete primary first.
    await client.execute(
        "DELETE FROM mahavishnu_worktree_registry WHERE handle_id = :handle_id",
        {"handle_id": handle_id},
    )

    # Best-effort index cleanup. Each failure is logged + counted as
    # drift (handled in the wrapper layer via record_registry_drift).
    index_drift = 0
    try:
        await client.execute(
            "DELETE FROM mahavishnu_worktree_registry_idx_principal WHERE handle_id = :handle_id",
            {"handle_id": handle_id},
        )
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup; logged + drift counted
        logger.warning(
            "worktree-registry-index-cleanup-failed",
            extra={
                "index": "principal",
                "handle_id": handle_id,
                "error": str(exc),
            },
        )
        index_drift += 1

    try:
        await client.execute(
            "DELETE FROM mahavishnu_worktree_registry_idx_repo WHERE handle_id = :handle_id",
            {"handle_id": handle_id},
        )
    except Exception as exc:  # noqa: BLE001 — best-effort cleanup; logged + drift counted
        logger.warning(
            "worktree-registry-index-cleanup-failed",
            extra={
                "index": "repo",
                "handle_id": handle_id,
                "error": str(exc),
            },
        )
        index_drift += 1

    # Surface drift via metric (best-effort — never raises out of remove).
    if index_drift:
        try:
            from mahavishnu.observability.metrics import record_registry_drift

            record_registry_drift(missing_in_dhara=index_drift)
        except (ImportError, AttributeError):  # pragma: no cover - observability optional
            pass

    return True


async def list_handles(
    client: Any,
    *,
    principal: str | None = None,
    repo: str | None = None,
    caller: Principal | None = None,
    all_tenants: bool = False,
) -> list[WorktreeHandle]:
    """List WorktreeHandles, optionally filtered by principal or repo.

    Authorization model (mirrors ``register_handles``):

    * ``all_tenants=True`` requires scope ``worktree:list-all`` on
      ``caller`` (admin / SRE).
    * ``principal=<name>`` requires ``caller.name == principal`` unless
      the caller has ``worktree:list-all``.
    * ``repo=<name>`` requires scope ``worktree:read`` on ``caller``
      unless they have ``worktree:list-all``; results are
      post-filtered to handles the caller owns.
    * With no filter and no ``all_tenants`` flag, defaults to
      ``caller.name`` if ``caller`` is provided (the typical "show me
      my handles" call), or refuses if ``caller`` is None.
    """
    is_admin = caller is not None and "worktree:list-all" in caller.scopes

    if all_tenants:
        if not is_admin:
            raise PermissionError(
                "Listing all tenants requires caller with scope 'worktree:list-all'"
            )
        rows = await client.query("SELECT * FROM mahavishnu_worktree_registry ORDER BY created_at")
        return [_row_to_handle(r) for r in rows]

    if principal is not None:
        if not is_admin and (caller is None or caller.name != principal):
            raise PermissionError(
                f"Non-admin callers can only list their own handles; "
                f"caller {caller.name if caller else 'None'!r} asked for {principal!r}"
            )
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
        return [_row_to_handle(r) for r in rows]

    if repo is not None:
        if not is_admin:
            if caller is None:
                raise PermissionError(
                    "Repo-scoped listing requires a caller with scope 'worktree:read'"
                )
            if "worktree:read" not in caller.scopes:
                raise PermissionError(
                    f"Caller {caller.name!r} lacks scope 'worktree:read' for repo listing"
                )
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
        handles = [_row_to_handle(r) for r in rows]
        # Post-filter: non-admin callers only see their own handles.
        if not is_admin and caller is not None:
            handles = [h for h in handles if h.principal.name == caller.name]
        return handles

    # No filter provided — default to caller's own handles, or refuse
    # if there's no caller at all.
    if caller is None:
        raise PermissionError(
            "list_handles requires a principal, repo, caller, or explicit "
            "all_tenants=True with admin scope"
        )
    rows = await client.query(
        """
        SELECT r.* FROM mahavishnu_worktree_registry r
          JOIN mahavishnu_worktree_registry_idx_principal p
            ON r.handle_id = p.handle_id
          WHERE p.principal = :principal
          ORDER BY r.created_at
        """,
        {"principal": caller.name},
    )
    return [_row_to_handle(r) for r in rows]


__all__ = [
    "SCHEMA_STATEMENTS",
    "list_handles",
    "register_handles",
]
