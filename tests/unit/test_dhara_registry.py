"""Tests for the Dhara-backed worktree registry (ADR 015 v4 §11)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from mahavishnu.auth import Principal
from mahavishnu.core.worktree_providers.dhara_registry import (
    register_handles,
    list_handles,
)
from mahavishnu.core.worktree_providers.pre_migrate import synthesize_handle
from mahavishnu.core.worktree_providers.types import LocalWorktreeRef, RemoteWorktreeRef


class FakeDharaClient:
    """In-memory fake of the DharaThinClient interface for tests.

    Implements the subset needed for register_handles and list_handles:
    - ``await execute(sql, params)`` for INSERT/CREATE TABLE
    - ``await query(sql, params)`` for SELECT/JOIN

    The fake maintains two indexes (principal, repo) keyed by handle_id
    for fast lookup.
    """

    def __init__(self) -> None:
        self._registry: dict[str, dict[str, Any]] = {}
        self._idx_principal: dict[str, set[str]] = {}
        self._idx_repo: dict[str, set[str]] = {}
        self._sql_log: list[tuple[str, dict[str, Any]]] = []
        self._schema_ready: bool = False

    async def execute(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._sql_log.append((sql, params or {}))
        sql_normalized = " ".join(sql.split()).lower()

        if sql_normalized.startswith("create table"):
            self._schema_ready = True
            return {"rowcount": 0, "status": "ok"}

        # Order matters: check the more specific index tables BEFORE the
        # primary table (otherwise the primary's startswith() matches the
        # idx tables' SQL because they share the "mahavishnu_worktree_registry"
        # prefix).
        if sql_normalized.startswith(
            "insert or replace into mahavishnu_worktree_registry_idx_principal"
        ):
            p = params or {}
            self._idx_principal.setdefault(p["principal"], set()).add(
                p["handle_id"]
            )
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

    async def query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
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


def _make_handle(name: str = "h-1", repo: str = "mahavishnu") -> "Any":
    return synthesize_handle(
        f"/Users/les/Projects/{repo}",
        {
            "worktree": f"/Users/les/worktrees/{name}",
            "HEAD": "abc123",
            "branch": "refs/heads/feature/auth",
        },
        Principal.from_uid(1000),
    )


# ----- register_handles -----------------------------------------------------


def test_register_handles_creates_schema_then_inserts() -> None:
    async def run() -> int:
        client = FakeDharaClient()
        h = _make_handle()
        n = await register_handles(client, [h])
        # 3 CREATE TABLEs + 1 primary INSERT + 2 index INSERTs = 6 calls
        assert n == 1
        assert len(client._sql_log) == 6
        # Confirm the schema comes first (3 CREATE TABLE statements)
        for i in range(3):
            assert client._sql_log[i][0].strip().lower().startswith(
                "create table"
            ), f"call {i} was not CREATE TABLE: {client._sql_log[i][0][:80]}"
        # Then the 3 INSERTs in primary → idx_principal → idx_repo order
        assert client._sql_log[3][0].strip().lower().startswith(
            "insert or replace into mahavishnu_worktree_registry"
        ), f"call 3 was not primary INSERT: {client._sql_log[3][0][:80]}"
        assert client._sql_log[4][0].strip().lower().startswith(
            "insert or replace into mahavishnu_worktree_registry_idx_principal"
        )
        assert client._sql_log[5][0].strip().lower().startswith(
            "insert or replace into mahavishnu_worktree_registry_idx_repo"
        )
        return n

    asyncio.run(run())


async def _ensure_schema(client: FakeDharaClient) -> None:
    """Run schema setup outside of register_handles for testing."""
    await client.execute(
        "CREATE TABLE IF NOT EXISTS mahavishnu_worktree_registry (handle_id TEXT PRIMARY KEY, principal TEXT NOT NULL, repo TEXT NOT NULL, branch TEXT NOT NULL, base_ref TEXT, created_at TEXT NOT NULL, sha256 TEXT NOT NULL DEFAULT '', bytes_size INTEGER NOT NULL DEFAULT 0, cleanup_policy TEXT, provenance TEXT NOT NULL, storage_ref_json TEXT NOT NULL, backend_kind TEXT NOT NULL, origin_path TEXT NOT NULL)"
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
        await register_handles(
            client, [handle], ensure_schema=False
        )
        assert "uid:1000" in client._idx_principal
        assert handle.handle_id in client._idx_principal["uid:1000"]

    asyncio.run(run())


def test_register_handles_inserts_repo_index() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        await _ensure_schema(client)
        handle = _make_handle("h-1")
        await register_handles(
            client, [handle], ensure_schema=False
        )
        assert "mahavishnu" in client._idx_repo
        assert handle.handle_id in client._idx_repo["mahavishnu"]

    asyncio.run(run())


def test_register_handles_batch_inserts_all() -> None:
    async def run() -> int:
        client = FakeDharaClient()
        handles = [_make_handle(f"h-{i}") for i in range(5)]
        return await register_handles(client, handles)

    assert asyncio.run(run()) == 5


def test_register_handles_ensure_schema_false_skips_creates() -> None:
    async def run() -> int:
        client = FakeDharaClient()
        await _ensure_schema(client)  # pre-create
        client._sql_log.clear()
        await register_handles(
            client, [_make_handle()], ensure_schema=False
        )
        return len(client._sql_log)

    # Only the 3 INSERTs, no CREATE TABLE
    assert asyncio.run(run()) == 3


# ----- list_handles ----------------------------------------------------------


def test_list_handles_no_filter_returns_all() -> None:
    async def run() -> list:
        client = FakeDharaClient()
        await _ensure_schema(client)
        await register_handles(
            client,
            [_make_handle(f"h-{i}") for i in range(3)],
            ensure_schema=False,
        )
        return await list_handles(client)

    handles = asyncio.run(run())
    assert len(handles) == 3


def test_list_handles_filter_by_principal() -> None:
    async def run() -> list:
        client = FakeDharaClient()
        await _ensure_schema(client)
        # Three handles — two for uid:1000 (h-1, h-3) and one for uid:2000 (h-2).
        # Each handle has its own unique handle_id (UUID) and is registered
        # only once, so the principal index is clean (no duplicates).
        from dataclasses import replace

        h_uid1000_a = _make_handle("h-1")
        h_uid1000_b = _make_handle("h-3")
        h_uid2000 = replace(
            _make_handle("h-2"),
            principal=Principal(name="uid:2000", uid=2000),
        )
        await register_handles(
            client,
            [h_uid1000_a, h_uid1000_b, h_uid2000],
            ensure_schema=False,
        )

        uid1000_handles = await list_handles(client, principal="uid:1000")
        uid2000_handles = await list_handles(client, principal="uid:2000")
        return uid1000_handles, uid2000_handles

    uid1000, uid2000 = asyncio.run(run())
    assert len(uid1000) == 2
    assert len(uid2000) == 1
    # h1 and h3 are both for uid:1000; h2 is for uid:2000.
    # Compare by handle_id (UUID, not "h-1" string).
    assert uid2000[0].principal.name == "uid:2000"
    assert {h.handle_id for h in uid1000} != {uid2000[0].handle_id}
    assert len({h.handle_id for h in uid1000}.intersection({uid2000[0].handle_id})) == 0


def test_list_handles_filter_by_repo() -> None:
    async def run() -> list:
        client = FakeDharaClient()
        await _ensure_schema(client)
        h_mah = _make_handle("h-mah", repo="mahavishnu")
        h_fb = _make_handle("h-fb", repo="fastblocks")
        await register_handles(client, [h_mah, h_fb], ensure_schema=False)
        return await list_handles(client, repo="mahavishnu")

    handles = asyncio.run(run())
    assert len(handles) == 1
    assert handles[0].repo == "mahavishnu"


# ----- Roundtrip -------------------------------------------------------------


def test_register_then_list_roundtrip() -> None:
    async def run() -> None:
        client = FakeDharaClient()
        original = _make_handle("h-rt")
        await register_handles(client, [original], ensure_schema=True)
        loaded = (await list_handles(client, principal=original.principal.name))[0]
        return original, loaded

    original, loaded = asyncio.run(run())
    assert original.handle_id == loaded.handle_id
    assert original.repo == loaded.repo
    assert original.branch == loaded.branch
    assert original.base_ref == loaded.base_ref
    assert original.provenance == loaded.provenance
    # Storage_ref roundtrip via the fake
    assert loaded.storage_ref.backend_kind == "local"
