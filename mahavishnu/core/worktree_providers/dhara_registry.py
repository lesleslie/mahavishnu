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


def _validate_storage_path_shape(path_str: str, backend_kind: str) -> None:
    """Reject empty / dash-prefixed / non-absolute / parent-traversal paths.

    Pure-string checks; no filesystem I/O. Splitting the shape checks
    out of ``_validate_storage_path`` keeps each helper under the
    complexity gate (4 branches here vs the previous 7 inside the
    combined function) and lets tests exercise the shape rules without
    mocking the filesystem.

    Dash-prefix rationale: a path starting with ``-`` could be
    mis-parsed as a CLI flag by downstream tooling (e.g. ``rm -rf /tmp``
    if the path was ever passed as an argument). Check the raw
    string rather than ``p.parts[0]`` since absolute Unix paths always
    have ``/`` as parts[0].
    """
    if not path_str:
        raise ValueError(f"{backend_kind} storage path is empty")
    if path_str.startswith("-"):
        raise ValueError(f"{backend_kind} storage path starts with dash (flag-like): {path_str!r}")
    p = Path(path_str)
    if not p.is_absolute():
        raise ValueError(f"{backend_kind} storage path must be absolute: {path_str!r}")
    if any(part == ".." for part in p.parts):
        raise ValueError(f"{backend_kind} storage path contains '..': {path_str!r}")


def _validate_storage_path_within_base(path_str: str, backend_kind: str) -> None:
    """Resolve ``path_str`` and confirm it falls under the worktree base.

    Performs filesystem I/O (``.resolve()``) which is expensive and
    side-effect-bearing; kept separate from the shape checks so tests
    can mock either half in isolation.
    """
    base = _worktree_base_resolved()
    try:
        candidate = Path(path_str).resolve()
    except OSError as exc:
        raise ValueError(
            f"{backend_kind} storage path cannot be resolved: {path_str!r} ({exc})"
        ) from exc
    if not _is_within(candidate, base):
        raise ValueError(f"{backend_kind} storage path {candidate} is outside worktree base {base}")


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

    Returns ``path_str`` unchanged on success for chaining at call sites.
    """
    _validate_storage_path_shape(path_str, backend_kind)
    _validate_storage_path_within_base(path_str, backend_kind)
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


def _assert_can_remove_handle(
    caller: Principal,
    *,
    handle_id: str,
    principal_name: str,
    owner_uid: Any,
    has_admin: bool,
) -> None:
    """Enforce per-handle ownership: non-admin callers may only remove their own.

    ``owner_uid`` may be ``None`` for pre-v2 migrated (anonymous) handles;
    in that case only admins may remove them since we cannot verify
    ownership. Admins (``worktree:register-any``) bypass this check.
    """
    if has_admin:
        return
    if owner_uid is None or owner_uid != caller.uid:
        raise PermissionError(
            f"Principal {caller.name!r} cannot remove handle "
            f"{handle_id!r} owned by {principal_name!r}"
        )


async def _cleanup_principal_index(client: Any, handle_id: str) -> int:
    """Best-effort delete of the principal index row; return 1 on drift, 0 otherwise."""
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
        return 1
    return 0


async def _cleanup_repo_index(client: Any, handle_id: str) -> int:
    """Best-effort delete of the repo index row; return 1 on drift, 0 otherwise."""
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
        return 1
    return 0


async def _surface_index_drift(index_drift: int) -> None:
    """Best-effort metric surface for index drift; never raises out of remove."""
    if not index_drift:
        return
    try:
        from mahavishnu.observability.metrics import record_registry_drift

        record_registry_drift(missing_in_dhara=index_drift)
    except ImportError, AttributeError:  # pragma: no cover - observability optional
        pass


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

    # Look up the primary to discover principal + uid BEFORE we delete
    # the primary. If absent, return False without touching indexes
    # (no drift to report).
    rows = await client.query(
        "SELECT principal, principal_uid FROM mahavishnu_worktree_registry "
        "WHERE handle_id = :handle_id",
        {"handle_id": handle_id},
    )
    if not rows:
        return False

    principal_name = rows[0]["principal"]
    owner_uid = rows[0].get("principal_uid")
    _assert_can_remove_handle(
        caller,
        handle_id=handle_id,
        principal_name=principal_name,
        owner_uid=owner_uid,
        has_admin=has_admin,
    )

    # Delete primary first.
    await client.execute(
        "DELETE FROM mahavishnu_worktree_registry WHERE handle_id = :handle_id",
        {"handle_id": handle_id},
    )

    # Best-effort index cleanup. Each failure is logged + counted as
    # drift (handled in the wrapper layer via record_registry_drift).
    index_drift = await _cleanup_principal_index(client, handle_id)
    index_drift += await _cleanup_repo_index(client, handle_id)
    await _surface_index_drift(index_drift)

    return True


def _assert_admin_scope(caller: Principal | None, *, action: str) -> None:
    """Raise PermissionError unless caller has the worktree:list-all scope."""
    if caller is None or "worktree:list-all" not in caller.scopes:
        raise PermissionError(f"Action {action!r} requires scope 'worktree:list-all' on the caller")


def _assert_principal_match(caller: Principal | None, principal: str, is_admin: bool) -> None:
    """Raise unless caller is admin or asking for their own principal."""
    if is_admin:
        return
    if caller is None or caller.name != principal:
        raise PermissionError(
            "Non-admin callers can only list their own handles; "
            f"caller {caller.name if caller else 'None'!r} asked for {principal!r}"
        )


def _assert_repo_read_scope(caller: Principal | None, is_admin: bool) -> None:
    """Raise unless caller is admin or has the worktree:read scope."""
    if is_admin:
        return
    if caller is None:
        raise PermissionError("Repo-scoped listing requires a caller with scope 'worktree:read'")
    if "worktree:read" not in caller.scopes:
        raise PermissionError(
            f"Caller {caller.name!r} lacks scope 'worktree:read' for repo listing"
        )


async def _fetch_all_handles(client: Any) -> list[WorktreeHandle]:
    """Return every handle in the registry (admin-only caller gate above)."""
    rows = await client.query("SELECT * FROM mahavishnu_worktree_registry ORDER BY created_at")
    return [_row_to_handle(r) for r in rows]


async def _fetch_handles_for_principal(client: Any, principal: str) -> list[WorktreeHandle]:
    """Run the principal-filtered JOIN query and materialize handles."""
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


async def _fetch_handles_for_repo(client: Any, repo: str) -> list[WorktreeHandle]:
    """Run the repo-filtered JOIN query and materialize handles."""
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
    return [_row_to_handle(r) for r in rows]


def _filter_handles_to_caller(
    handles: list[WorktreeHandle],
    caller: Principal | None,
    is_admin: bool,
) -> list[WorktreeHandle]:
    """Post-filter handles so non-admin callers only see their own."""
    if is_admin or caller is None:
        return handles
    return [h for h in handles if h.principal.name == caller.name]


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
        _assert_admin_scope(caller, action="list all tenants")
        return await _fetch_all_handles(client)

    if principal is not None:
        _assert_principal_match(caller, principal, is_admin)
        return await _fetch_handles_for_principal(client, principal)

    if repo is not None:
        _assert_repo_read_scope(caller, is_admin)
        handles = await _fetch_handles_for_repo(client, repo)
        return _filter_handles_to_caller(handles, caller, is_admin)

    # No filter provided — default to caller's own handles, or refuse
    # if there's no caller at all.
    if caller is None:
        raise PermissionError(
            "list_handles requires a principal, repo, caller, or explicit "
            "all_tenants=True with admin scope"
        )
    return await _fetch_handles_for_principal(client, caller.name)


__all__ = [
    "SCHEMA_STATEMENTS",
    "list_handles",
    "register_handles",
]
