"""Tests for ``mahavishnu.core.worktree_providers.remote.RemoteWorktreeProvider``.

Covers the v4 WorktreeHandle-based interface per ADR 015 v4 §13 and §18
Phase 2. Uses fake storage + cache + Dhara clients so no real cloud or
Redis connections are required.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from mahavishnu.auth import Principal
from mahavishnu.core.errors import WorktreeIntegrityError
from mahavishnu.core.worktree_providers.cache import WorktreeCache
from mahavishnu.core.worktree_providers.remote import RemoteWorktreeProvider
from mahavishnu.core.worktree_providers.storage_io import compute_sha256
from mahavishnu.core.worktree_providers.types import (
    RemoteWorktreeRef,
    WorktreeHandle,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fakes — recording doubles for storage / cache / dhara / local_provider
# ---------------------------------------------------------------------------


class _FakeStorageAdapter:
    """In-memory fake mirroring the Oneiric S3 storage adapter surface.

    Supports the v4 extensions (``upload(metadata=...)`` and ``exists``)
    that Oneiric PR-A adds. ``upload_calls`` / ``download_calls`` /
    ``exists_calls`` record every method invocation so tests can assert
    the provider dispatched through the expected API surface (and not,
    for example, called ``download`` when it should have called
    ``exists``).
    """

    def __init__(self, *, health: bool = True, backend_kind: str = "s3") -> None:
        self._blobs: dict[str, bytes] = {}
        self._health = health
        self.backend_kind = backend_kind
        self.upload_calls: list[dict[str, Any]] = []
        self.download_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.exists_calls: list[str] = []
        self.health_calls = 0

    async def upload(
        self, key: str, data: bytes, *, metadata: dict[str, str] | None = None
    ) -> None:
        self.upload_calls.append({"key": key, "len": len(data), "metadata": metadata})
        self._blobs[key] = data

    async def download(self, key: str) -> bytes | None:
        self.download_calls.append(key)
        return self._blobs.get(key)

    async def delete(self, key: str) -> None:
        self.delete_calls.append(key)
        self._blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        self.exists_calls.append(key)
        return key in self._blobs

    async def health(self) -> bool:
        self.health_calls += 1
        return self._health


class _FakeCache:
    """WorktreeCache-shaped fake with the four ops we exercise.

    Uses an in-memory dict; ``invalidate_handle`` scans by prefix to
    mirror the real ``WorktreeCache.invalidate_handle`` semantics (and
    returns the count).
    """

    PREFIX = "mahavishnu:worktree-cache:"

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self.invalidate_calls: list[str] = []
        self.set_calls: list[tuple[str, Any]] = []
        self.get_calls: list[str] = []

    @property
    def key_prefix(self) -> str:
        return self.PREFIX

    def _full(self, key: str) -> str:
        return key if key.startswith(self.PREFIX) else f"{self.PREFIX}{key}"

    async def get(self, key: str) -> Any:
        self.get_calls.append(key)
        return self._store.get(self._full(key))

    async def set(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        self.set_calls.append((key, value))
        self._store[self._full(key)] = value

    async def delete(self, key: str) -> None:
        self._store.pop(self._full(key), None)

    async def invalidate_handle(self, handle_id: str) -> int:
        self.invalidate_calls.append(handle_id)
        prefix = f"{self.PREFIX}{handle_id}:"
        victims = [k for k in self._store if k.startswith(prefix)]
        for k in victims:
            self._store.pop(k, None)
        return len(victims)

    async def health(self) -> bool:
        return True


class FakeDharaClient:
    """In-memory DharaThinClient fake (mirrors ``test_dhara_registry``)."""

    def __init__(self) -> None:
        self._registry: dict[str, dict[str, Any]] = {}
        self._idx_principal: dict[str, set[str]] = {}
        self._idx_repo: dict[str, set[str]] = {}
        self._sql_log: list[tuple[str, dict[str, Any]]] = []
        self._schema_ready = False

    async def execute(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._sql_log.append((sql, params or {}))
        s = " ".join(sql.split()).lower()
        if s.startswith("create table"):
            self._schema_ready = True
            return {"rowcount": 0, "status": "ok"}
        if s.startswith("insert or replace into mahavishnu_worktree_registry_idx_principal"):
            p = params or {}
            self._idx_principal.setdefault(p["principal"], set()).add(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}
        if s.startswith("insert or replace into mahavishnu_worktree_registry_idx_repo"):
            p = params or {}
            self._idx_repo.setdefault(p["repo"], set()).add(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}
        if s.startswith("insert or replace into mahavishnu_worktree_registry"):
            p = params or {}
            self._registry[p["handle_id"]] = dict(p)
            return {"rowcount": 1, "status": "ok"}
        if s.startswith("delete from mahavishnu_worktree_registry"):
            p = params or {}
            removed = self._registry.pop(p["handle_id"], None)
            return {"rowcount": 1 if removed else 0, "status": "ok"}
        if s.startswith("delete from mahavishnu_worktree_registry_idx_principal"):
            p = params or {}
            for s_set in self._idx_principal.values():
                s_set.discard(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}
        if s.startswith("delete from mahavishnu_worktree_registry_idx_repo"):
            p = params or {}
            for s_set in self._idx_repo.values():
                s_set.discard(p["handle_id"])
            return {"rowcount": 1, "status": "ok"}
        raise ValueError(f"Unhandled SQL in fake: {sql[:80]}")

    async def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        s = " ".join(sql.split()).lower()
        if s.startswith("select principal, repo from mahavishnu_worktree_registry"):
            p = params or {}
            row = self._registry.get(p["handle_id"])
            return [row] if row else []
        if "idx_principal" in s and params and "principal" in params:
            ids = self._idx_principal.get(params["principal"], set())
            return [self._registry[i] for i in ids if i in self._registry]
        if "idx_repo" in s and params and "repo" in params:
            ids = self._idx_repo.get(params["repo"], set())
            return [self._registry[i] for i in ids if i in self._registry]
        if s.startswith("select * from mahavishnu_worktree_registry"):
            return list(self._registry.values())
        raise ValueError(f"Unhandled SELECT in fake: {sql[:80]}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _principal(
    *,
    uid: int = 1000,
    name: str = "uid:1000",
    scopes: tuple[str, ...] = ("worktree:register",),
) -> Principal:
    """Build a Principal with the scopes needed by Dhara ops.

    ``register_handles`` requires ``worktree:register``; ``remove_handle``
    requires ``worktree:remove``; ``list_handles`` admin path requires
    ``worktree:list-all``. We start with the union of register + remove
    by default; per-test overrides add ``list-all`` as needed.
    """
    return Principal(uid=uid, name=name, scopes=frozenset(scopes))


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a real git repo under tmp_path so ``git bundle create`` works.

    ``create_worktree_handle`` shells out to ``git bundle create`` against
    ``base_ref``; if the path isn't a real repo, the subprocess raises
    ``WorktreeCreationError``. Tests that exercise create_worktree_handle
    use this fixture.
    """
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    # Skip if git is unavailable in the test env
    try:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)
        (repo / "README.md").write_text("hello")
        subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True, capture_output=True)
    except Exception:
        pytest.skip(f"git unavailable or repo init failed: {subprocess.run(['git', '--version'], capture_output=True).stderr}")
    return repo


def _handle(
    *,
    handle_id: str = "h-abc",
    repo: str = "mahavishnu",
    branch: str = "feature/auth",
    sha: str = "",
    size: int = 0,
    principal: Principal | None = None,
    backend_kind: str = "s3",
    bucket: str = "b",
    key: str | None = None,
) -> WorktreeHandle:
    """Build a WorktreeHandle wired to a RemoteWorktreeRef."""
    p = principal or _principal()
    return WorktreeHandle(
        handle_id=handle_id,
        principal=p,
        repo=repo,
        branch=branch,
        base_ref="main",
        created_at=datetime.now(UTC),
        storage_ref=RemoteWorktreeRef(
            bucket=bucket,
            key=key or f"worktrees/{repo}/{branch}/{handle_id}.tar.gz",
            worktree_id=handle_id,
            backend_kind=backend_kind,  # type: ignore[arg-type]
        ),
        sha256=sha,
        bytes_size=size,
        cleanup_policy=None,
        provenance="v4",
    )


# ---------------------------------------------------------------------------
# health / health_check
# ---------------------------------------------------------------------------


def test_health_check_returns_storage_health() -> None:
    """``health()`` returns storage AND cache health AND-ed together."""
    storage_healthy = _FakeStorageAdapter(health=True)
    storage_unhealthy = _FakeStorageAdapter(health=False)
    cache = _FakeCache()

    p_ok = RemoteWorktreeProvider(storage=storage_healthy, cache=cache)
    p_bad = RemoteWorktreeProvider(storage=storage_unhealthy, cache=cache)

    async def run() -> None:
        assert await p_ok.health() is True
        assert await p_bad.health() is False

    asyncio.run(run())


# ---------------------------------------------------------------------------
# create_worktree_handle
# ---------------------------------------------------------------------------


def test_create_worktree_handle_uploads_with_metadata(git_repo: Path) -> None:
    """create_worktree_handle uploads with x-amz-meta-sha256 + principal metadata."""
    storage = _FakeStorageAdapter()
    cache = _FakeCache()
    dhara = FakeDharaClient()
    repo_path = git_repo

    provider = RemoteWorktreeProvider(
        storage=storage,
        cache=cache,
        dhara_client=dhara,
    )
    principal = _principal()

    async def run() -> None:
        handle = await provider.create_worktree_handle(
            repo=str(repo_path),
            branch="feature/x",
            base_ref="HEAD",
            principal=principal,
        )
        assert handle.handle_id
        assert handle.bytes_size > 0
        assert handle.sha256
        # One upload call; metadata carries sha256 + principal.
        assert len(storage.upload_calls) == 1
        call = storage.upload_calls[0]
        md = call["metadata"] or {}
        assert md.get("x-amz-meta-sha256") == handle.sha256
        assert md.get("x-amz-meta-principal") == principal.name
        assert call["key"].endswith(f"{handle.handle_id}.tar.gz")

    asyncio.run(run())


def test_create_worktree_handle_emits_worktree_metric(git_repo: Path) -> None:
    """``create_worktree_handle`` records a ``worktree_create_duration_seconds`` sample."""
    from mahavishnu.observability import metrics as metrics_mod

    storage = _FakeStorageAdapter()
    cache = _FakeCache()
    dhara = FakeDharaClient()
    repo_path = git_repo

    provider = RemoteWorktreeProvider(
        storage=storage,
        cache=cache,
        dhara_client=dhara,
    )

    async def run() -> None:
        # Patch the histogram bound at import time so we can observe a record() call.
        original_record = metrics_mod._worktree_create_histogram.record

        seen: list[dict[str, Any]] = []

        def spy(value: float, attributes: dict[str, Any] | None = None) -> None:
            seen.append({"value": value, "attributes": dict(attributes or {})})
            original_record(value, attributes=attributes)

        metrics_mod._worktree_create_histogram.record = spy  # type: ignore[method-assign]
        try:
            await provider.create_worktree_handle(
                repo=str(repo_path),
                branch="main",
                base_ref="HEAD",
                principal=_principal(),
            )
        finally:
            metrics_mod._worktree_create_histogram.record = original_record  # type: ignore[method-assign]

        assert seen, "expected record_worktree_op to emit at least one sample"
        attrs = seen[-1]["attributes"]
        assert attrs["backend"] == "s3"
        assert attrs["status"] == "ok"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# fetch — cache hit / miss / integrity
# ---------------------------------------------------------------------------


def test_fetch_cache_hit_returns_materialized_ref(tmp_path: Path) -> None:
    """Cache hit skips download and returns the cached path."""
    storage = _FakeStorageAdapter()
    cache = _FakeCache()
    provider = RemoteWorktreeProvider(storage=storage, cache=cache)

    cached_dir = tmp_path / "cached"
    cached_dir.mkdir()
    (cached_dir / "a.txt").write_text("hit")

    handle = _handle(handle_id="h-hit", sha="ignored-on-hit")
    cache_key = f"{handle.handle_id}:materialized"
    asyncio.run(cache.set(cache_key, str(cached_dir)))

    async def run() -> None:
        ref = await provider.fetch(handle)
        assert ref.path == cached_dir
        # Cache hit means NO download should be attempted.
        assert storage.download_calls == []

    asyncio.run(run())


def test_fetch_cache_miss_downloads_and_caches(tmp_path: Path) -> None:
    """Cache miss → download → cache.set → return new materialized ref."""
    storage = _FakeStorageAdapter()
    cache = _FakeCache()
    provider = RemoteWorktreeProvider(storage=storage, cache=cache)

    blob = _make_tar_blob(tmp_path, "hello")
    sha = compute_sha256(blob)
    handle = _handle(handle_id="h-miss", sha=sha, size=len(blob))

    async def run() -> None:
        # Pre-seed storage so download() returns the expected blob.
        await storage.upload(handle.storage_ref.key, blob)

        ref = await provider.fetch(handle)
        assert ref.path.exists()
        assert (ref.path / "f.txt").read_text() == "hello"
        # Download was called once, cache.set was called once.
        assert storage.download_calls == [handle.storage_ref.key]
        # Cache should now hold the materialized path for next time.
        cached = await cache.get(f"{handle.handle_id}:materialized")
        assert cached == str(ref.path)

    asyncio.run(run())


def test_fetch_sha_mismatch_raises_integrity_error(tmp_path: Path) -> None:
    """SHA-256 mismatch → WorktreeIntegrityError; integrity metric emitted."""
    from mahavishnu.observability import metrics as metrics_mod

    storage = _FakeStorageAdapter()
    cache = _FakeCache()
    provider = RemoteWorktreeProvider(storage=storage, cache=cache)

    blob = _make_tar_blob(tmp_path, "tampered")
    handle = _handle(handle_id="h-bad", sha="0" * 64)  # wrong sha

    async def run() -> None:
        # Seed storage with the blob so download returns bytes.
        await storage.upload(handle.storage_ref.key, blob)

        original_add = metrics_mod._bundle_integrity_failure_counter.add
        seen: list[dict[str, Any]] = []

        def spy(amount: int, attributes: dict[str, Any] | None = None) -> None:
            seen.append({"amount": amount, "attributes": dict(attributes or {})})
            original_add(amount, attributes=attributes)

        metrics_mod._bundle_integrity_failure_counter.add = spy  # type: ignore[method-assign]
        try:
            with pytest.raises(WorktreeIntegrityError):
                await provider.fetch(handle)
        finally:
            metrics_mod._bundle_integrity_failure_counter.add = original_add  # type: ignore[method-assign]

        assert seen, "expected bundle_integrity_failure_total counter increment"
        assert seen[-1]["attributes"]["backend"] == "s3"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# remove_handle
# ---------------------------------------------------------------------------


def test_remove_handle_invalidates_cache_and_storage_and_dhara(tmp_path: Path) -> None:
    """remove_handle touches storage, cache, and Dhara in that order."""
    storage = _FakeStorageAdapter()
    cache = _FakeCache()
    dhara = FakeDharaClient()
    provider = RemoteWorktreeProvider(
        storage=storage,
        cache=cache,
        dhara_client=dhara,
    )

    blob = b"some bytes"
    sha = compute_sha256(blob)
    principal = _principal()
    # Need the register AND remove scopes so register_handles succeeds
    # AND dhara_remove_handle can authorize the delete.
    principal_full = replace(
        principal,
        scopes=frozenset({"worktree:register", "worktree:remove"}),
    )
    handle = _handle(
        handle_id="h-rem",
        sha=sha,
        size=len(blob),
        principal=principal_full,
    )

    async def run() -> None:
        # Pre-seed storage + Dhara so all three subsystems have a row.
        await storage.upload(handle.storage_ref.key, blob)
        await cache.set(f"{handle.handle_id}:materialized", "/some/path")
        # Register the handle in Dhara via the registry helper so the
        # delete can find the principal/repo for index cleanup.
        from mahavishnu.core.worktree_providers.dhara_registry import (
            register_handles as dhara_register,
        )

        await dhara_register(dhara, [handle], caller=principal_full)

        removed = await provider.remove_handle(handle)
        assert removed is True

        # Storage: deleted.
        assert handle.storage_ref.key in storage.delete_calls
        assert handle.storage_ref.key not in storage._blobs
        # Cache: invalidate called for this handle.
        assert cache.invalidate_calls == [handle.handle_id]
        # Dhara: primary row removed.
        rows = await dhara.query(
            "SELECT * FROM mahavishnu_worktree_registry WHERE handle_id = :h",
            {"h": handle.handle_id},
        )
        assert rows == []

    asyncio.run(run())


# ---------------------------------------------------------------------------
# list_handles
# ---------------------------------------------------------------------------


def test_list_handles_delegates_to_dhara() -> None:
    """list_handles forwards principal/repo/caller to dhara_registry."""
    storage = _FakeStorageAdapter()
    cache = _FakeCache()
    dhara = FakeDharaClient()
    provider = RemoteWorktreeProvider(
        storage=storage,
        cache=cache,
        dhara_client=dhara,
    )

    caller = _principal(
        uid=2000,
        name="uid:2000",
        scopes=("worktree:read",),
    )

    async def run() -> None:
        handles = await provider.list_handles(repo="mahavishnu", caller=caller)
        assert handles == []

    asyncio.run(run())


def test_list_handles_raises_when_caller_none() -> None:
    """list_handles refuses to dispatch without a caller (privacy)."""
    provider = RemoteWorktreeProvider(storage=_FakeStorageAdapter(), cache=_FakeCache())

    async def run() -> None:
        with pytest.raises(PermissionError):
            await provider.list_handles()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------


def test_exists_uses_storage_not_download(tmp_path: Path) -> None:
    """exists() must hit storage.exists — not download."""
    storage = _FakeStorageAdapter()
    provider = RemoteWorktreeProvider(storage=storage, cache=_FakeCache())
    handle = _handle(handle_id="h-ex", key="worktrees/mahavishnu/main/h-ex.tar.gz")

    async def run() -> None:
        # Empty storage → exists=False, no download.
        assert await provider.exists(handle) is False
        assert storage.exists_calls == [handle.storage_ref.key]
        assert storage.download_calls == []

        # Now seed and re-check — exists=True, still no download.
        await storage.upload(handle.storage_ref.key, b"x")
        assert await provider.exists(handle) is True
        # Only one new exists call was made; download never invoked.
        assert storage.download_calls == []

    asyncio.run(run())


# ---------------------------------------------------------------------------
# lock delegation
# ---------------------------------------------------------------------------


def test_lock_delegates_to_local_provider() -> None:
    """lock() forwards to the injected LocalWorktreeProvider."""
    storage = _FakeStorageAdapter()
    cache = _FakeCache()
    sentinel = object()
    seen: dict[str, Any] = {}

    class _FakeLocal:
        async def lock(self, repo, branch, *, acquire_timeout, lease_ttl, redis_client):
            seen["repo"] = repo
            seen["branch"] = branch
            seen["acquire_timeout"] = acquire_timeout
            seen["lease_ttl"] = lease_ttl
            seen["redis_client"] = redis_client
            return sentinel

    provider = RemoteWorktreeProvider(
        storage=storage,
        cache=cache,
        local_provider=_FakeLocal(),  # type: ignore[arg-type]
    )

    async def run() -> object:
        result = await provider.lock(
            "mahavishnu", "feature/x", acquire_timeout=2.5, lease_ttl=15.0
        )
        assert seen == {
            "repo": "mahavishnu",
            "branch": "feature/x",
            "acquire_timeout": 2.5,
            "lease_ttl": 15.0,
            "redis_client": None,
        }
        return result

    assert asyncio.run(run()) is sentinel


def test_lock_raises_when_no_local_provider() -> None:
    """lock() refuses without a LocalWorktreeProvider."""
    provider = RemoteWorktreeProvider(storage=_FakeStorageAdapter(), cache=_FakeCache())

    async def run() -> None:
        with pytest.raises(NotImplementedError):
            await provider.lock("mahavishnu", "feature/x")

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_tar_blob(tmp_path: Path, content: str) -> bytes:
    """Build a tiny tar.gz blob containing a single ``f.txt`` file."""
    import io
    import tarfile

    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text(content)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(str(src / "f.txt"), arcname="f.txt")
    return buf.getvalue()
