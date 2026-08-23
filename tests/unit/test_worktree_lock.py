"""Tests for the Redis-backed worktree lock (ADR 015 v4 §14)."""

from __future__ import annotations

import asyncio

import pytest

from mahavishnu.core.worktree_providers.lock import RedisLockBackend


class FakeRedis:
    """In-memory Redis fake for testing the lock backend."""

    def __init__(self) -> None:
        self._kv: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None:
        if nx and key in self._kv:
            return None
        self._kv[key] = value
        return True

    async def get(self, key: str) -> bytes | str | None:
        return self._kv.get(key)

    async def delete(self, key: str) -> int:
        if key in self._kv:
            del self._kv[key]
            return 1
        return 0

    async def incr(self, key: str) -> int:
        # Sets NX-style auto-init for keys (like real Redis)
        # But we also need this to work for fence counters; handle both.
        if key in self._kv:
            self._kv[key] = str(int(self._kv[key]) + 1)
            return int(self._kv[key])
        else:
            self._kv[key] = "1"
            return 1


def _make_client() -> FakeRedis:
    return FakeRedis()


# ----- acquire -------------------------------------------------------------


def test_acquire_returns_worktree_lock() -> None:
    async def run() -> None:
        backend = RedisLockBackend(_make_client())
        lock = await backend.acquire("uid:1000", "mahavishnu", "feature/auth")
        assert lock.repo == "mahavishnu"
        assert lock.branch == "feature/auth"
        assert lock.fencing_token >= 1
        assert lock.expires_at > lock.acquire_at

    asyncio.run(run())


def test_acquire_sets_redis_key() -> None:
    client = _make_client()

    async def run() -> None:
        backend = RedisLockBackend(client)
        await backend.acquire("uid:1000", "mahavishnu", "feature/auth")

    asyncio.run(run())

    # Key includes the principal name
    expected_key = "mahavishnu:worktree-registry:lock:uid:1000:mahavishnu:feature/auth"
    assert expected_key in client._kv


def test_acquire_increments_fence_counter() -> None:
    client = _make_client()

    async def run() -> int:
        backend = RedisLockBackend(client)
        await backend.acquire("uid:1", "r", "b")
        return await backend.acquire("uid:2", "r", "b")

    fencing_token = asyncio.run(run())

    # Two acquires on the same (repo, branch) → two different tokens
    assert fencing_token.fencing_token == 2


def test_acquire_includes_principal_in_key() -> None:
    client = _make_client()

    async def run() -> None:
        backend = RedisLockBackend(client)
        await backend.acquire("uid:alice", "r", "b")
        await backend.acquire("uid:bob", "r", "b")
        # Two different principals → two different lock keys held simultaneously

    asyncio.run(run())

    assert "mahavishnu:worktree-registry:lock:uid:alice:r:b" in client._kv
    assert "mahavishnu:worktree-registry:lock:uid:bob:r:b" in client._kv


def test_acquire_times_out_when_lock_held() -> None:
    client = _make_client()

    async def run() -> None:
        backend = RedisLockBackend(client, acquire_timeout=0.1, poll_interval=0.01)
        # Pre-populate to simulate an existing holder
        client._kv["mahavishnu:worktree-registry:lock:uid:1:r:b"] = "someone-else"
        with pytest.raises(TimeoutError):
            await backend.acquire("uid:1", "r", "b")

    asyncio.run(run())


def test_acquire_retry_succeeds_when_existing_lock_released() -> None:
    client = _make_client()

    async def run() -> None:
        # Pre-populate
        client._kv["mahavishnu:worktree-registry:lock:uid:1:r:b"] = "someone-else"

        async def release_after_delay():
            await asyncio.sleep(0.1)
            del client._kv["mahavishnu:worktree-registry:lock:uid:1:r:b"]

        backend = RedisLockBackend(client, acquire_timeout=2.0, poll_interval=0.05)
        release_task = asyncio.create_task(release_after_delay())
        lock = await backend.acquire("uid:1", "r", "b")
        await release_task
        assert lock.fencing_token >= 1

    asyncio.run(run())


def test_acquire_uses_configured_lease_ttl() -> None:
    client = _make_client()

    async def run() -> None:
        backend = RedisLockBackend(client, lease_ttl=120.0)
        lock = await backend.acquire("uid:1", "r", "b")
        # lease_ttl doesn't appear as a Redis SET arg (FakeRedis doesn't track it)
        # but the WorktreeLock.expires_at should reflect 120s
        delta = (lock.expires_at - lock.acquire_at).total_seconds()
        assert 119 < delta < 121

    asyncio.run(run())


# ----- release -------------------------------------------------------------


def test_release_removes_key() -> None:
    client = _make_client()

    async def run() -> bool:
        backend = RedisLockBackend(client)
        lock = await backend.acquire("uid:1", "r", "b")
        return await backend.release(lock)

    assert asyncio.run(run()) is True
    assert "mahavishnu:worktree-registry:lock:uid:1:r:b" not in client._kv


def test_release_returns_false_when_key_already_gone() -> None:
    """If the key expired (TTL elapsed) before release, delete returns 0."""
    client = _make_client()

    async def run() -> bool:
        backend = RedisLockBackend(client)
        lock = await backend.acquire("uid:1", "r", "b")
        # Simulate TTL expiry by removing the key manually
        del client._kv["mahavishnu:worktree-registry:lock:uid:1:r:b"]
        return await backend.release(lock)

    assert asyncio.run(run()) is False


# ----- construction validation --------------------------------------------


def test_construction_validates_arguments() -> None:
    with pytest.raises(ValueError, match="acquire_timeout"):
        RedisLockBackend(_make_client(), acquire_timeout=-1)
    with pytest.raises(ValueError, match="lease_ttl"):
        RedisLockBackend(_make_client(), lease_ttl=0)
    with pytest.raises(ValueError, match="poll_interval"):
        RedisLockBackend(_make_client(), poll_interval=0)
