"""Redis-backed distributed lock for v4 worktree operations.

ADR 015 v4 §14: ``WorktreeProvider.lock()`` returns a
``WorktreeLock`` with acquire semantics, lease TTL, and fencing
token. This module provides the Redis SETNX + INCR implementation
that ``LocalWorktreeProvider.lock`` and ``RemoteWorktreeProvider.lock``
both delegate to.

Why a shared module: the lock primitive is backend-agnostic
(every ``WorktreeProvider`` issue acquires it the same way), and
keeping the Redis-specific logic in one place avoids two copies of
the SETNX + fencing dance.

Implementation notes:

  - ``SET key token NX EX lease_ttl`` gives us atomic acquire-with-lease.
  - ``INCR mahavishnu:worktree-fence:<repo>:<branch>`` gives us the
    monotonic fencing token. Callers pass the token to all subsequent
    writes; writes reject tokens older than the highest-seen token
    (not implemented here; the lock itself just emits the token).
  - The lock key includes the principal so two principals locking
    the same ``(repo, branch)`` don't share state.
  - Release is a best-effort delete. A compare-and-delete (Lua) variant
    is a tracked follow-up: ``WorktreeLock`` would need to carry the
    original acquire token, and ``release()`` would ``client.eval()``
    the script so we don't delete a still-held lock whose TTL hasn't
    expired yet.

Caller contract (returned ``WorktreeLock``):

  >>> lock.acquire_at
  datetime(2026, 8, 23, ...)
  >>> lock.expires_at
  datetime(2026, 8, 23, ..., +30s)
  >>> lock.fencing_token
  42
  >>> lock.owner_principal
  Principal(uid=1000, name='uid:1000', ...)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import secrets
import time
from typing import Protocol

from mahavishnu.auth import Principal

from .types import WorktreeLock


class RedisLike(Protocol):
    """Subset of redis.asyncio.Redis we depend on (for Protocol typing)."""

    async def set(
        self,
        key: str,
        value: str,
        *,
        nx: bool = False,
        ex: int | None = None,
    ) -> bool | None: ...

    async def get(self, key: str) -> bytes | str | None: ...

    async def delete(self, key: str) -> int: ...

    async def incr(self, key: str) -> int: ...


def _principal_with_name(name: str) -> Principal:
    """Build a Principal from just the principal name (lock carries just a name).

    The full Principal (with uid, scopes, etc.) lives in the registry;
    the lock only needs the discriminator name for the key.
    """
    return Principal(uid=None, name=name)


class RedisLockBackend:
    """Redis-backed implementation of v4 §14 distributed worktree lock.

    Caller passes a Redis client (any object with the ``RedisLike``
    shape). The backend does NOT manage the client's lifecycle — the
    caller constructs and closes the client (typical: a process-wide
    ``redis.asyncio.Redis`` connection pool).
    """

    KEY_PREFIX = "mahavishnu:worktree-registry:lock"
    FENCE_PREFIX = "mahavishnu:worktree-fence"

    def __init__(
        self,
        client: RedisLike,
        *,
        acquire_timeout: float = 10.0,
        lease_ttl: float = 30.0,
        poll_interval: float = 0.05,
    ) -> None:
        if acquire_timeout < 0:
            raise ValueError("acquire_timeout must be non-negative")
        if lease_ttl <= 0:
            raise ValueError("lease_ttl must be positive")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self._client = client
        self._acquire_timeout = acquire_timeout
        self._lease_ttl = lease_ttl
        self._poll_interval = poll_interval

    @staticmethod
    def _lock_key(principal_name: str, repo: str, branch: str) -> str:
        return f"{RedisLockBackend.KEY_PREFIX}:{principal_name}:{repo}:{branch}"

    @staticmethod
    def _fence_key(repo: str, branch: str) -> str:
        return f"{RedisLockBackend.FENCE_PREFIX}:{repo}:{branch}"

    async def acquire(
        self,
        principal_name: str,
        repo: str,
        branch: str,
    ) -> WorktreeLock:
        """Acquire the distributed lock for ``(principal_name, repo, branch)``.

        Polls Redis SETNX with the configured ``acquire_timeout`` /
        ``lease_ttl``. Returns a ``WorktreeLock`` with a freshly
        issued fencing token on success; raises ``TimeoutError``
        on timeout.
        """
        key = self._lock_key(principal_name, repo, branch)
        token = secrets.token_urlsafe(16)
        deadline = time.monotonic() + self._acquire_timeout

        while True:
            ok = await self._client.set(key, token, nx=True, ex=int(self._lease_ttl))
            if ok:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Could not acquire lock {key} within {self._acquire_timeout}s")
            await asyncio.sleep(self._poll_interval)

        # Now we hold the lock. Issue a monotonic fencing token.
        fencing_token = await self._client.incr(self._fence_key(repo, branch))

        now = datetime.now(UTC)
        return WorktreeLock(
            acquire_at=now,
            expires_at=now + timedelta(seconds=self._lease_ttl),
            owner_principal=_principal_with_name(principal_name),
            fencing_token=int(fencing_token),
            repo=repo,
            branch=branch,
        )

    async def release(self, lock: WorktreeLock) -> bool:
        """Release the lock via best-effort delete.

        Returns True if the lock key existed and was deleted; False if
        the key was already gone (TTL expired, or never held by this
        caller). Tracked follow-up: a compare-and-delete Lua script
        that only deletes when the stored token matches the lock's
        original acquire token, so we never release a lock that has
        since been re-acquired by another principal.
        """
        key = self._lock_key(lock.owner_principal.name, lock.repo, lock.branch)
        return bool(await self._client.delete(key))


__all__ = [
    "RedisLike",
    "RedisLockBackend",
]
