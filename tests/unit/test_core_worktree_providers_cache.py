"""Tests for ``mahavishnu.core.worktree_providers.cache.WorktreeCache`` (PR-C)."""

from __future__ import annotations

import pytest

from mahavishnu.core.worktree_providers.cache import (
    DEFAULT_KEY_PREFIX,
    WorktreeCache,
)


# ---------------------------------------------------------------------------
# Pre-test: install a ``delete_prefix`` shim on MemoryCacheAdapter when the
# installed Oneiric predates Oneiric PR-A (which adds ``delete_prefix`` to
# the cache adapters). Once PR-A ships to the internal index, this shim
# becomes a no-op because the real method already exists.
# ---------------------------------------------------------------------------


def _install_delete_prefix_shim() -> None:
    from oneiric.adapters.cache.memory import MemoryCacheAdapter

    if hasattr(MemoryCacheAdapter, "delete_prefix"):
        return  # PR-A already shipped; nothing to do

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every key whose name starts with ``prefix`` (PR-A-equivalent)."""
        async with self._lock:  # type: ignore[attr-defined]
            victims = [k for k in self._store if k.startswith(prefix)]  # type: ignore[attr-defined]
            for k in victims:
                self._store.pop(k, None)  # type: ignore[attr-defined]
            return len(victims)

    MemoryCacheAdapter.delete_prefix = delete_prefix  # type: ignore[attr-defined]


_install_delete_prefix_shim()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_default_key_prefix_is_canonical() -> None:
    """The default prefix must match ADR §3 exactly."""
    assert DEFAULT_KEY_PREFIX == "mahavishnu:worktree-cache:"


# ---------------------------------------------------------------------------
# In-memory-only path (no Redis dependency)
# ---------------------------------------------------------------------------


def _make_inmemory_cache() -> WorktreeCache:
    """Build a WorktreeCache with L1 only (no L2 connection attempted)."""
    from oneiric.adapters.cache.memory import (
        MemoryCacheAdapter,
        MemoryCacheSettings,
    )
    from oneiric.adapters.cache.multitier import MultiTierCacheAdapter

    l1 = MemoryCacheAdapter(settings=MemoryCacheSettings(max_entries=10))
    multi = MultiTierCacheAdapter(l1_cache=l1, l2_cache=None)
    return WorktreeCache(multi_tier=multi)


@pytest.mark.asyncio
async def test_set_get_round_trip() -> None:
    cache = _make_inmemory_cache()
    await cache.init()
    await cache.set("foo", "bar")
    assert await cache.get("foo") == "bar"
    await cache.cleanup()


@pytest.mark.asyncio
async def test_invalidate_handle_clears_prefix() -> None:
    """invalidate_handle deletes all keys matching ``{prefix}{handle_id}:*``."""
    cache = _make_inmemory_cache()
    await cache.init()

    # Two keys for h1, one for h2.
    await cache.set("h1:materialized", "/tmp/h1")
    await cache.set("h1:sha256", "abc")
    await cache.set("h2:materialized", "/tmp/h2")

    removed = await cache.invalidate_handle("h1")
    assert removed == 2

    assert await cache.get("h1:materialized") is None
    assert await cache.get("h1:sha256") is None
    # h2 untouched
    assert await cache.get("h2:materialized") == "/tmp/h2"
    await cache.cleanup()


@pytest.mark.asyncio
async def test_invalidate_handle_unknown_returns_zero() -> None:
    cache = _make_inmemory_cache()
    await cache.init()
    await cache.set("present", 1)
    removed = await cache.invalidate_handle("nonexistent-handle")
    assert removed == 0
    assert await cache.get("present") == 1
    await cache.cleanup()


@pytest.mark.asyncio
async def test_invalidate_handle_uses_canonical_prefix() -> None:
    """The fully-qualified prefix must equal ``mahavishnu:worktree-cache:{handle_id}:``."""
    cache = _make_inmemory_cache()
    await cache.init()
    assert cache.key_prefix == DEFAULT_KEY_PREFIX
    # Insert a key with the canonical prefix manually
    await cache.set(f"h-abc:foo", "x")
    # invalidate_handle with the same handle id clears it.
    removed = await cache.invalidate_handle("h-abc")
    assert removed == 1
    await cache.cleanup()


# ---------------------------------------------------------------------------
# Key-prefix gotcha — must NOT be the Oneiric hardcoded "l2:"
# ---------------------------------------------------------------------------


def test_key_prefix_is_not_oneiric_hardcoded() -> None:
    """The wrapper's key_prefix must be the canonical Mahavishnu namespace,
    NOT Oneiric's hardcoded ``l2:`` (which only applies when
    MultiTierCacheAdapter builds L2 internally — we bypass that).
    """
    assert DEFAULT_KEY_PREFIX != "l2:"
    assert DEFAULT_KEY_PREFIX.startswith("mahavishnu:")


# ---------------------------------------------------------------------------
# get_metrics re-export
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_metrics_returns_snapshot() -> None:
    cache = _make_inmemory_cache()
    await cache.init()
    await cache.set("a", 1)
    await cache.get("a")  # hit
    snapshot = await cache.get_metrics()
    assert isinstance(snapshot, dict)
    await cache.cleanup()
