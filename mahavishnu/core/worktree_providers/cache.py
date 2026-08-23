"""Worktree cache wrapper (ADR 015 v4 §3).

Wraps Oneiric's ``MultiTierCacheAdapter`` (L1 memory + L2 Redis) with
a domain-specific ``invalidate_handle`` API and the canonical
``mahavishnu:worktree-cache:`` key prefix.

**L2 key_prefix gotcha:** ``MultiTierCacheAdapter.__init__`` hardcodes
``key_prefix="l2:"`` on internally-constructed L2 (Redis) adapters.
By pre-building ``RedisCacheAdapter(settings=RedisCacheSettings(key_prefix=...))``
and passing it as the ``l2_cache=`` argument, we bypass that
hardcode and apply our own ``mahavishnu:worktree-cache:`` prefix.

This is the **only** place where the prefix lives — keep it here so
PR-D's providers can call ``await cache.invalidate_handle(handle_id)``
without knowing about the L2 prefix mechanics.
"""

from __future__ import annotations

from typing import Any

from oneiric.adapters.cache.memory import (
    MemoryCacheAdapter,
    MemoryCacheSettings,
)
from oneiric.adapters.cache.multitier import MultiTierCacheAdapter
from oneiric.adapters.cache.redis import (
    RedisCacheAdapter,
    RedisCacheSettings,
)

# Canonical namespace prefix for all worktree-cache entries. Used by
# WorktreeProvider.fetch (set/get) and WorktreeCache.invalidate_handle
# (delete_prefix).
DEFAULT_KEY_PREFIX = "mahavishnu:worktree-cache:"


class WorktreeCache:
    """Thin wrapper around MultiTierCacheAdapter for worktree cache entries.

    Methods:
        get/set/delete: vanilla passthroughs.
        invalidate_handle(handle_id): delete every key matching
            ``f"{key_prefix}{handle_id}:"`` from both L1 and L2.
            Returns the combined count (the "invalidation effort"
            metric — same key may live in both layers).

    Re-exports get_metrics() so dashboards can scrape L1/L2 hit
    ratios without reimplementing the snapshot logic.
    """

    def __init__(
        self,
        *,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        l1_max_entries: int = 1024,
        l1_ttl_seconds: float = 600.0,
        redis_url: str | None = None,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 1,
        redis_password: str | None = None,
        redis_ssl: bool = False,
        redis_ttl_seconds: int = 86400,
        default_ttl_seconds: int = 3600,
        multi_tier: MultiTierCacheAdapter | None = None,
    ) -> None:
        if multi_tier is not None:
            self._multi = multi_tier
            self._key_prefix = key_prefix
            self._default_ttl = default_ttl_seconds
            return

        self._key_prefix = key_prefix

        # L1: in-process memory cache (LRU via max_entries).
        l1 = MemoryCacheAdapter(
            settings=MemoryCacheSettings(
                max_entries=l1_max_entries,
                default_ttl=l1_ttl_seconds,
            )
        )

        # L2: Redis with our prefix. Pre-building is required because
        # MultiTierCacheAdapter hardcodes ``l2:`` on internally-built
        # L2 (oneiric/oneiric/adapters/cache/multitier.py:259).
        l2_settings = RedisCacheSettings(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            ssl=redis_ssl,
            key_prefix=key_prefix,  # bypasses MultiTierCacheAdapter hardcode
        )
        if redis_url:
            l2_settings = RedisCacheSettings(url=redis_url, key_prefix=key_prefix)
        l2 = RedisCacheAdapter(settings=l2_settings)

        self._multi = MultiTierCacheAdapter(l1_cache=l1, l2_cache=l2)
        self._default_ttl = default_ttl_seconds

    @property
    def key_prefix(self) -> str:
        """The full prefix applied to every cache key (default
        ``mahavishnu:worktree-cache:``). Used by callers building keys."""
        return self._key_prefix

    async def init(self) -> None:
        await self._multi.init()

    async def cleanup(self) -> None:
        await self._multi.cleanup()

    async def get(self, key: str) -> Any:
        return await self._multi.get(self._prefix(key))

    async def set(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        effective_ttl = ttl if ttl is not None else self._default_ttl
        await self._multi.set(self._prefix(key), value, ttl=effective_ttl)

    async def delete(self, key: str) -> None:
        await self._multi.delete(self._prefix(key))

    def _prefix(self, key: str) -> str:
        """Apply the canonical ``mahavishnu:worktree-cache:`` prefix.

        Idempotent: if the caller already supplied a fully-qualified
        key (starts with ``key_prefix``), pass it through unchanged.
        """
        if key.startswith(self._key_prefix):
            return key
        return f"{self._key_prefix}{key}"

    async def invalidate_handle(self, handle_id: str) -> int:
        """Delete every cache entry for ``handle_id`` from both layers.

        Builds the fully-qualified prefix ``f"{self._key_prefix}{handle_id}:"``
        and dispatches to L1 + L2 ``delete_prefix``. Returns the combined
        count (the "invalidation effort" metric).

        Implementation note: we call L1/L2 directly rather than via
        ``MultiTierCacheAdapter.delete_prefix`` so this code works even
        if the installed Oneiric version predates the multitier
        ``delete_prefix`` method (added in Oneiric PR-A). Once that PR
        ships to the internal index, both paths are equivalent.
        """
        full_prefix = f"{self._key_prefix}{handle_id}:"
        l1_count = 0
        l2_count = 0
        # MultiTierCacheAdapter exposes _l1/_l2 as private. Reach in
        # for the delete_prefix method (Oneiric MemoryCacheAdapter and
        # RedisCacheAdapter both have it post-Oneiric-PR-A).
        l1 = self._multi._l1  # type: ignore[attr-defined]
        l2 = self._multi._l2  # type: ignore[attr-defined]
        if l1 is not None:
            l1_count = await l1.delete_prefix(full_prefix)
        if l2 is not None:
            l2_count = await l2.delete_prefix(full_prefix)
        return l1_count + l2_count

    async def health(self) -> bool:
        return await self._multi.health()

    async def get_metrics(self) -> dict[str, Any]:
        """Re-export ``MultiTierCacheAdapter.get_metrics`` snapshot."""
        return await self._multi.get_metrics()
