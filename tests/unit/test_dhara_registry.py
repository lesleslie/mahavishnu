"""Tests for the Dhara-backed worktree registry (ADR 015 v4 §11)."""

from __future__ import annotations

import asyncio
from datetime import UTC
from typing import Any

import pytest

from mahavishnu.auth import Principal
from mahavishnu.core.worktree_providers.dhara_registry import (
    list_handles,
    register_handles,
)
from mahavishnu.core.worktree_providers.pre_migrate import synthesize_handle


class FakeDharaClient:
    """In-memory fake of the DharaThinClient interface."""

    def __init__(self) -> None:
        self._registry: dict[str, dict[str, Any]] = {}
        self._idx_principal: dict[str, set[str]] = {}
        self._idx_repo: dict[str, set[str]] = {}
        self._sql_log: list[tuple[str, dict[str, Any]]] = []
        self._schema_ready: bool = False

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._sql_log.append((sql, params or {}))
        sql_normalized = " ".join(sql.split()).lower()

        if sql_normalized.startswith("create table"):
            self._schema_ready = True
            return {"rowcount": 0, "status": "ok"}

        # More specific index tables must match BEFORE the primary table
        # (they share the "mahavishnu_worktree_registry" prefix).
        if sql_normalized.startswith(
            "insert or replace into mahavishnu_worktree_registry_idx_principal"
        ):
            p = params or {}
            self._idx_principal.setdefault(p["principal"], set()).add(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}

        if sql_normalized.startswith(
            "insert or replace into mahavishnu_worktree_registry_idx_repo"
        ):
            p = params or {}
            self._idx_repo.setdefault(p["repo"], set()).add(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}

        if sql_normalized.startswith("insert or replace into mahavishnu_worktree_registry"):
            p = params or {}
            self._registry[p["handle_id"]] = dict(p)
            return {"rowcount": 1, "status": "ok"}

        raise ValueError(f"Unhandled SQL in fake: {sql[:80]}")

    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        sql_normalized = " ".join(sql.split()).lower()

        if sql_normalized.startswith("select r.* from mahavishnu_worktree_registry r"):
            if "idx_principal" in sql_normalized and params and "principal" in params:
                ids = self._idx_principal.get(params["principal"], set())
                return [self._registry[i] for i in ids if i in self._registry]
            if "idx_repo" in sql_normalized and params and "repo" in params:
                ids = self._idx_repo.get(params["repo"], set())
                return [self._registry[i] for i in ids if i in self._registry]

        if sql_normalized.startswith("select * from mahavishnu_worktree_registry"):
            return list(self._registry.values())

        raise ValueError(f"Unhandled SELECT in fake: {sql[:80]}")


def _make_handle(name: str = "h-1", repo: str = "mahavishnu") -> Any:
    return synthesize_handle(
        f"/Users/les/Projects/{repo}",
        {
            "worktree": f"/Users/les/worktrees/{name}",
            "HEAD": "abc123",
            "branch": "refs/heads/feature/auth",
        },
        Principal.from_uid(1000),
    )


def _caller_with_scope(*scopes: str, uid: int = 1000, name: str = "uid:1000") -> Principal:
    """A caller Principal with the given scopes (fresh-frozen=True by default)."""
    from dataclasses import replace

    base = Principal.from_uid(uid) if uid else Principal.anonymous()
    new_scopes = frozenset(scopes)
    if base.scopes == new_scopes:
        return base
    return (
        replace(base, scopes=new_scopes)
        if base.uid is not None
        else Principal(uid=base.uid, name=name, scopes=new_scopes)
    )


# ----- register_handles -----------------------------------------------------


def test_register_handles_creates_schema_then_inserts() -> None:
    async def run() -> int:
        client = FakeDharaClient()
        caller = _caller_with_scope("worktree:register")
        h = _make_handle()
        n = await register_handles(client, [h], caller=caller)
        assert n == 1
        assert len(client._sql_log) == 6
        for i in range(3):
            assert client._sql_log[i][0].strip().lower().startswith("create table"), (
                f"call {i} was not CREATE TABLE: {client._sql_log[i][0][:80]}"
            )
        assert (
            client._sql_log[3][0]
            .strip()
            .lower()
            .startswith("insert or replace into mahavishnu_worktree_registry")
        )
        assert (
            client._sql_log[4][0]
            .strip()
            .lower()
            .startswith("insert or replace into mahavishnu_worktree_registry_idx_principal")
        )
        assert (
            client._sql_log[5][0]
            .strip()
            .lower()
            .startswith("insert or replace into mahavishnu_worktree_registry_idx_repo")
        )
        return n

    asyncio.run(run())


async def _ensure_schema(client: FakeDharaClient) -> None:
    await client.execute(
        "CREATE TABLE IF NOT EXISTS mahavishnu_worktree_registry (handle_id TEXT PRIMARY KEY, principal TEXT NOT NULL, principal_uid INTEGER, repo TEXT NOT NULL, branch TEXT NOT NULL, base_ref TEXT, created_at TEXT NOT NULL, sha256 TEXT NOT NULL DEFAULT '', bytes_size INTEGER NOT NULL DEFAULT 0, cleanup_policy TEXT, provenance TEXT NOT NULL, storage_ref_json TEXT NOT NULL, backend_kind TEXT NOT NULL, origin_path TEXT NOT NULL)"
    )
    await client.execute(
        "CREATE TABLE IF NOT EXISTS mahavishnu_worktree_registry_idx_principal (principal TEXT NOT NULL, handle_id TEXT NOT NULL, PRIMARY KEY (principal, handle_id))"
    )
    await client.execute(
        "CREATE TABLE IF NOT EXISTS mahavishnu_worktree_registry_idx_repo (repo TEXT NOT NULL, handle_id TEXT NOT NULL, PRIMARY KEY (repo, handle_id))"
    )


def test_register_handles_inserts_principal_index() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        handle = _make_handle("h-1")
        await register_handles(client, [handle], caller=_caller_with_scope("worktree:register"))
        assert "uid:1000" in client._idx_principal
        assert handle.handle_id in client._idx_principal["uid:1000"]

    asyncio.run(run())


def test_register_handles_inserts_repo_index() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        handle = _make_handle("h-1")
        await register_handles(client, [handle], caller=_caller_with_scope("worktree:register"))
        assert "mahavishnu" in client._idx_repo
        assert handle.handle_id in client._idx_repo["mahavishnu"]

    asyncio.run(run())


def test_register_handles_batch_inserts_all() -> None:
    async def run() -> int:
        client = FakeDharaClient()
        caller = _caller_with_scope("worktree:register")
        handles = [_make_handle(f"h-{i}") for i in range(5)]
        return await register_handles(client, handles, caller=caller)

    assert asyncio.run(run()) == 5


def test_register_handles_ensure_schema_false_skips_creates() -> None:
    async def run() -> int:
        client = FakeDharaClient()
        await _ensure_schema(client)
        client._sql_log.clear()
        await register_handles(
            client,
            [_make_handle()],
            caller=_caller_with_scope("worktree:register"),
            ensure_schema=False,
        )
        return len(client._sql_log)

    assert asyncio.run(run()) == 3


# ----- register_handles authorization ----------------------------------------


def test_register_handles_requires_register_scope() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        # No scope → reject
        caller = Principal.from_uid(1000)
        with pytest.raises(PermissionError, match="worktree:register"):
            await register_handles(client, [_make_handle()], caller=caller)

    asyncio.run(run())


def test_register_handles_non_admin_cannot_register_other_principals() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        # Caller is uid:2000 (no admin scope); handle belongs to uid:1000
        caller = _caller_with_scope("worktree:register", uid=2000, name="uid:2000")
        handle = _make_handle("h-1")  # owned by uid:1000
        with pytest.raises(PermissionError, match="cannot register"):
            await register_handles(client, [handle], caller=caller)

    asyncio.run(run())


def test_register_handles_admin_can_register_any_principal() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        caller = _caller_with_scope(
            "worktree:register",
            "worktree:register-any",
            uid=9999,
            name="uid:9999",
        )
        handle = _make_handle("h-1")  # owned by uid:1000
        # Admin scope bypasses ownership check
        n = await register_handles(client, [handle], caller=caller)
        assert n == 1
        assert handle.handle_id in client._registry

    asyncio.run(run())


# ----- list_handles ---------------------------------------------------------


def test_list_handles_no_filter_returns_all() -> None:
    async def run() -> list:
        client = FakeDharaClient()
        await _ensure_schema(client)
        await register_handles(
            client,
            [_make_handle(f"h-{i}") for i in range(3)],
            caller=_caller_with_scope("worktree:register"),
        )
        admin = _caller_with_scope("worktree:list-all")
        return await list_handles(client, all_tenants=True, caller=admin)

    handles = asyncio.run(run())
    assert len(handles) == 3


def test_list_handles_filter_by_principal() -> None:
    async def run() -> tuple:
        client = FakeDharaClient()
        await _ensure_schema(client)
        h_uid1000_a = _make_handle("h-1")
        h_uid1000_b = _make_handle("h-3")
        from dataclasses import replace

        h_uid2000 = replace(
            _make_handle("h-2"),
            principal=Principal(name="uid:2000", uid=2000),
        )
        # uid:1000 handles need a uid:1000 caller; uid:2000 handle
        # needs an admin caller (different uid, with register-any).
        caller_uid1k = _caller_with_scope("worktree:register")
        caller_admin = _caller_with_scope(
            "worktree:register",
            "worktree:register-any",
            uid=9999,
            name="uid:9999",
        )
        # Listing uid:2000's handles requires worktree:list-all scope
        # (different uid than the caller). Use a separate admin caller.
        caller_list_all = _caller_with_scope(
            "worktree:list-all",
            uid=9999,
            name="uid:9999",
        )
        await register_handles(client, [h_uid1000_a, h_uid1000_b], caller=caller_uid1k)
        await register_handles(client, [h_uid2000], caller=caller_admin)

        uid1000_handles = await list_handles(client, principal="uid:1000", caller=caller_uid1k)
        uid2000_handles = await list_handles(client, principal="uid:2000", caller=caller_list_all)
        return uid1000_handles, uid2000_handles, h_uid1000_a, h_uid1000_b, h_uid2000

    uid1000, uid2000, h_a, h_b, _h_2k = asyncio.run(run())
    assert len(uid1000) == 2
    assert len(uid2000) == 1
    assert uid2000[0].principal.name == "uid:2000"
    uid1000_ids = {h.handle_id for h in uid1000}
    assert h_a.handle_id in uid1000_ids
    assert h_b.handle_id in uid1000_ids


def test_list_handles_non_admin_cannot_query_other_principal() -> None:
    """Non-admin callers are rejected when asking for someone else's handles."""

    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        caller_uid1k = _caller_with_scope("worktree:register", "worktree:read")
        with pytest.raises(PermissionError, match="can only list their own"):
            await list_handles(client, principal="uid:2000", caller=caller_uid1k)

    asyncio.run(run())


def test_list_handles_filter_by_repo() -> None:
    async def run() -> list:
        client = FakeDharaClient()
        await _ensure_schema(client)
        h_mah = _make_handle("h-mah", repo="mahavishnu")
        h_fb = _make_handle("h-fb", repo="fastblocks")
        await register_handles(
            client, [h_mah, h_fb], caller=_caller_with_scope("worktree:register")
        )
        # Repo listing requires worktree:read scope for non-admin callers
        return await list_handles(
            client, repo="mahavishnu", caller=_caller_with_scope("worktree:read")
        )

    handles = asyncio.run(run())
    assert len(handles) == 1
    assert handles[0].repo == "mahavishnu"


def test_list_handles_repo_filter_without_read_scope_rejected() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        # No worktree:read scope → reject
        caller = _caller_with_scope("worktree:register")
        with pytest.raises(PermissionError, match="worktree:read"):
            await list_handles(client, repo="mahavishnu", caller=caller)

    asyncio.run(run())


def test_list_handles_repo_filter_post_filters_to_callers_own() -> None:
    """Repo-scoped listing returns all rows from SQL, then post-filters
    to only handles the non-admin caller owns."""

    async def run() -> tuple:
        client = FakeDharaClient()
        await _ensure_schema(client)
        h_owner = _make_handle("h-owner")  # uid:1000
        from dataclasses import replace

        h_other = replace(
            _make_handle("h-other"),
            principal=Principal(name="uid:2000", uid=2000),
        )
        caller_uid1k = _caller_with_scope(
            "worktree:register",
            "worktree:register-any",
            uid=9999,
            name="uid:9999",
        )
        await register_handles(client, [h_owner, h_other], caller=caller_uid1k)
        # uid:1000 caller asks for repo=mahavishnu → sees only own handle
        caller_uid1k = _caller_with_scope("worktree:read")
        handles = await list_handles(client, repo="mahavishnu", caller=caller_uid1k)
        return handles, h_owner, h_other

    handles, h_owner, _h_other = asyncio.run(run())
    assert len(handles) == 1
    assert handles[0].handle_id == h_owner.handle_id


# ----- list_handles security ------------------------------------------------


def test_list_handles_unfiltered_raises_without_caller() -> None:
    """No caller + no filter → reject (would have nothing to default to)."""

    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        with pytest.raises(PermissionError, match="list_handles requires"):
            await list_handles(client)

    asyncio.run(run())


def test_list_handles_unfiltered_with_caller_returns_own_handles() -> None:
    """Caller + no filter → returns the caller's own handles (their
    default view)."""

    async def run() -> tuple:
        client = FakeDharaClient()
        await _ensure_schema(client)
        h = _make_handle("h-1")
        caller = _caller_with_scope("worktree:register")
        await register_handles(client, [h], caller=caller)
        handles = await list_handles(client, caller=caller)
        return h, handles

    h, handles = asyncio.run(run())
    assert len(handles) == 1
    assert handles[0].handle_id == h.handle_id


def test_list_handles_all_tenants_requires_admin_scope() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        # No scope → reject even with all_tenants=True
        with pytest.raises(PermissionError, match="worktree:list-all"):
            await list_handles(client, caller=Principal.from_uid(1), all_tenants=True)
        # Has list-all scope → succeed
        admin = _caller_with_scope("worktree:list-all")
        result = await list_handles(client, caller=admin, all_tenants=True)
        assert isinstance(result, list)

    asyncio.run(run())


# ----- Roundtrip -------------------------------------------------------------


def test_register_then_list_roundtrip() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        original = _make_handle("h-rt")
        caller = _caller_with_scope("worktree:register")
        await register_handles(client, [original], caller=caller)
        admin = _caller_with_scope("worktree:list-all")
        loaded = (await list_handles(client, principal=original.principal.name, caller=admin))[0]
        return original, loaded

    original, loaded = asyncio.run(run())
    assert original.handle_id == loaded.handle_id
    assert original.repo == loaded.repo
    assert original.branch == loaded.branch
    assert original.base_ref == loaded.base_ref
    assert original.provenance == loaded.provenance
    # principal_uid round-trip via the new principal_uid column
    assert original.principal.uid == loaded.principal.uid
    assert loaded.storage_ref.backend_kind == "local"


# ----- Path validation (security: relative-path injection) --------------------


def test_rejects_relative_storage_path() -> None:
    from dataclasses import replace

    h = _make_handle("h-bad")
    bad_ref = replace(h.storage_ref, path=__import__("pathlib").Path("../etc/passwd"))
    bad_handle = replace(h, storage_ref=bad_ref)

    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        with pytest.raises(ValueError, match="must be absolute"):
            await register_handles(
                client, [bad_handle], caller=_caller_with_scope("worktree:register")
            )

    asyncio.run(run())


def test_rejects_dotdot_storage_path() -> None:
    from dataclasses import replace
    from pathlib import Path

    h = _make_handle("h-bad")
    bad_ref = replace(h.storage_ref, path=Path("/tmp/x/../../../etc/shadow"))
    bad_handle = replace(h, storage_ref=bad_ref)

    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        with pytest.raises(ValueError, match=r"\.\."):
            await register_handles(
                client, [bad_handle], caller=_caller_with_scope("worktree:register")
            )

    asyncio.run(run())


def test_rejects_dash_prefix_storage_path() -> None:
    """A path string starting with '-' could be mis-parsed as a CLI flag
    by downstream tooling (e.g. `rm -rf /tmp` if the path was ever passed
    as an argument)."""
    from dataclasses import replace
    from pathlib import Path

    h = _make_handle("h-bad")
    # Path can't be both absolute and start with '-' on Unix, but the
    # raw string check catches the dash-prefix before the absolute check
    # fires (the path doesn't even need to be absolute for the threat
    # to exist if a consumer ever interpolates it into a shell command).
    bad_ref = replace(h.storage_ref, path=Path("-rf/tmp"))
    bad_handle = replace(h, storage_ref=bad_ref)

    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        with pytest.raises(ValueError, match="dash"):
            await register_handles(
                client, [bad_handle], caller=_caller_with_scope("worktree:register")
            )

    asyncio.run(run())


def test_rejects_path_outside_worktree_base() -> None:
    """Storage paths must resolve to a location inside the configured
    worktree base directory."""
    from dataclasses import replace
    from pathlib import Path

    h = _make_handle("h-bad")
    bad_ref = replace(h.storage_ref, path=Path("/etc/passwd"))
    bad_handle = replace(h, storage_ref=bad_ref)

    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        with pytest.raises(ValueError, match="outside worktree base"):
            await register_handles(
                client, [bad_handle], caller=_caller_with_scope("worktree:register")
            )

    asyncio.run(run())


# ----- backend-kind-loss (security review #6) ------------------------------


def test_remote_worktree_ref_preserves_backend_kind() -> None:
    """Registering a RemoteWorktreeRef should preserve its original
    backend_kind (s3 vs gcs vs azure) in storage_ref_json so round-trip
    doesn't silently downgrade to a generic remote type."""
    from dataclasses import replace

    from mahavishnu.core.worktree_providers.types import (
        RemoteWorktreeRef,
    )

    # Build a new handle with a RemoteWorktreeRef (don't try to mutate
    # the existing LocalWorktreeRef — frozen dataclasses don't support
    # class changes via dataclasses.replace).
    h_local = _make_handle("h-remote")
    s3_storage = RemoteWorktreeRef(
        bucket="my-bucket",
        key="path/to/bundle",
        worktree_id=h_local.handle_id,
        backend_kind="s3",
    )
    h_remote = (
        replace(
            h_local,
            storage_ref=s3_storage,
            backend_kind_handler=None,  # placeholder, see below
        )
        if False
        else h_local
    )  # don't actually replace (frozen conflict)

    # Just create a fresh handle via synthesize_handle with a different
    # approach: directly construct.
    from datetime import datetime as dt

    from mahavishnu.core.worktree_providers.types import WorktreeHandle

    h_remote = WorktreeHandle(
        handle_id="h-remote-s3",
        principal=Principal(name="uid:1000", uid=1000),
        repo="mahavishnu",
        branch="feature/s3",
        base_ref="main",
        created_at=dt.now(UTC),
        storage_ref=s3_storage,
        sha256="",
        bytes_size=0,
        cleanup_policy=None,
        provenance="v4",
    )

    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        await register_handles(client, [h_remote], caller=_caller_with_scope("worktree:register"))
        admin = _caller_with_scope("worktree:list-all")
        loaded = (await list_handles(client, principal=h_remote.principal.name, caller=admin))[0]
        assert loaded.storage_ref.backend_kind == "s3"
        assert isinstance(loaded.storage_ref, RemoteWorktreeRef)
        assert loaded.storage_ref.bucket == "my-bucket"
        assert loaded.storage_ref.key == "path/to/bundle"

    asyncio.run(run())


@pytest.mark.parametrize("backend", ["gcs", "azure", "s3"])
def test_remote_worktree_ref_round_trip_all_backends(backend: str) -> None:
    """Non-default backends (gcs/azure) must round-trip without
    silently downgrading to s3. Bug was: RemoteWorktreeRef.backend_kind
    was a hardcoded property returning 's3' regardless of the actual
    storage backend, so a gcs handle would silently downgrade to s3
    on read."""
    from datetime import datetime as dt

    from mahavishnu.core.worktree_providers.types import (
        RemoteWorktreeRef,
        WorktreeHandle,
    )

    h = WorktreeHandle(
        handle_id=f"h-remote-{backend}",
        principal=Principal(name="uid:1000", uid=1000),
        repo="mahavishnu",
        branch=f"feature/{backend}",
        base_ref="main",
        created_at=dt.now(UTC),
        storage_ref=RemoteWorktreeRef(
            bucket="my-bucket",
            key=f"path/to/{backend}/bundle",
            worktree_id=f"h-remote-{backend}",
            backend_kind=backend,  # type: ignore[arg-type]
        ),
        sha256="",
        bytes_size=0,
        cleanup_policy=None,
        provenance="v4",
    )

    async def run() -> str:
        client = FakeDharaClient()
        await _ensure_schema(client)
        await register_handles(client, [h], caller=_caller_with_scope("worktree:register"))
        admin = _caller_with_scope("worktree:list-all")
        loaded = (await list_handles(client, principal=h.principal.name, caller=admin))[0]
        return loaded.storage_ref.backend_kind

    assert asyncio.run(run()) == backend
