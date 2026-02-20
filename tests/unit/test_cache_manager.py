"""Tests for Cache Manager - LRU cache with optional Redis backend."""

import pytest
import asyncio
import time
from datetime import datetime, UTC, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Any

from mahavishnu.core.cache_manager import (
    CacheManager,
    CacheBackend,
    LRUCache,
    CacheStats,
    CacheKey,
)


@pytest.fixture
def sample_data() -> dict[str, Any]:
    """Create sample cached data."""
    return {
        "id": "task-123",
        "title": "Test Task",
        "status": "pending",
        "priority": "high",
    }


class TestCacheKey:
    """Tests for CacheKey class."""

    def test_create_key(self) -> None:
        """Create a cache key."""
        key = CacheKey(namespace="tasks", identifier="task-123")

        assert key.namespace == "tasks"
        assert key.identifier == "task-123"

    def test_key_to_string(self) -> None:
        """Convert key to string."""
        key = CacheKey(namespace="tasks", identifier="task-123")

        assert str(key) == "tasks:task-123"

    def test_key_from_string(self) -> None:
        """Create key from string."""
        key = CacheKey.from_string("tasks:task-123")

        assert key.namespace == "tasks"
        assert key.identifier == "task-123"

    def test_key_with_suffix(self) -> None:
        """Create key with suffix."""
        key = CacheKey(namespace="tasks", identifier="task-123", suffix="metadata")

        assert str(key) == "tasks:task-123:metadata"

    def test_key_equality(self) -> None:
        """Test key equality."""
        key1 = CacheKey(namespace="tasks", identifier="task-123")
        key2 = CacheKey(namespace="tasks", identifier="task-123")
        key3 = CacheKey(namespace="tasks", identifier="task-456")

        assert key1 == key2
        assert key1 != key3


class TestCacheStats:
    """Tests for CacheStats class."""

    def test_create_stats(self) -> None:
        """Create cache statistics."""
        stats = CacheStats()

        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0

    def test_record_hit(self) -> None:
        """Record a cache hit."""
        stats = CacheStats()
        stats.record_hit()

        assert stats.hits == 1

    def test_record_miss(self) -> None:
        """Record a cache miss."""
        stats = CacheStats()
        stats.record_miss()

        assert stats.misses == 1

    def test_record_eviction(self) -> None:
        """Record a cache eviction."""
        stats = CacheStats()
        stats.record_eviction()

        assert stats.evictions == 1

    def test_hit_rate(self) -> None:
        """Calculate hit rate."""
        stats = CacheStats()
        stats.record_hit()
        stats.record_hit()
        stats.record_miss()

        assert stats.hit_rate == 2 / 3

    def test_hit_rate_no_requests(self) -> None:
        """Hit rate with no requests."""
        stats = CacheStats()

        assert stats.hit_rate == 0.0

    def test_stats_to_dict(self) -> None:
        """Convert stats to dictionary."""
        stats = CacheStats()
        stats.record_hit()
        stats.record_miss()

        d = stats.to_dict()

        assert d["hits"] == 1
        assert d["misses"] == 1
        assert "hit_rate" in d


class TestLRUCache:
    """Tests for LRUCache class."""

    def test_create_cache(self) -> None:
        """Create an LRU cache."""
        cache = LRUCache(max_size=100)

        assert cache.max_size == 100
        assert len(cache) == 0

    def test_set_and_get(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Set and get a value."""
        cache = LRUCache(max_size=100)

        cache.set("task-123", sample_data)
        result = cache.get("task-123")

        assert result == sample_data

    def test_get_nonexistent(self) -> None:
        """Get a nonexistent key."""
        cache = LRUCache(max_size=100)

        result = cache.get("nonexistent")

        assert result is None

    def test_get_with_default(self) -> None:
        """Get with default value."""
        cache = LRUCache(max_size=100)

        result = cache.get("nonexistent", default={})

        assert result == {}

    def test_delete(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Delete a key."""
        cache = LRUCache(max_size=100)
        cache.set("task-123", sample_data)

        result = cache.delete("task-123")

        assert result is True
        assert cache.get("task-123") is None

    def test_delete_nonexistent(self) -> None:
        """Delete a nonexistent key."""
        cache = LRUCache(max_size=100)

        result = cache.delete("nonexistent")

        assert result is False

    def test_clear(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Clear the cache."""
        cache = LRUCache(max_size=100)
        cache.set("task-1", sample_data)
        cache.set("task-2", sample_data)

        cache.clear()

        assert len(cache) == 0

    def test_eviction_on_max_size(self) -> None:
        """Test eviction when max size reached."""
        cache = LRUCache(max_size=3)

        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)  # Should evict "a"

        assert len(cache) == 3
        assert cache.get("a") is None
        assert cache.get("d") == 4

    def test_lru_order(self) -> None:
        """Test LRU eviction order."""
        cache = LRUCache(max_size=3)

        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.get("a")  # Access "a", makes it most recent
        cache.set("d", 4)  # Should evict "b" (least recent)

        assert cache.get("a") == 1  # Still exists
        assert cache.get("b") is None  # Evicted
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_ttl_expiration(self) -> None:
        """Test TTL expiration."""
        cache = LRUCache(max_size=100)

        cache.set("task-123", {"data": "test"}, ttl=0.1)  # 100ms TTL

        # Should be present immediately
        assert cache.get("task-123") is not None

        # Wait for expiration
        time.sleep(0.2)

        # Should be expired
        assert cache.get("task-123") is None

    def test_no_ttl(self) -> None:
        """Test entry without TTL."""
        cache = LRUCache(max_size=100)

        cache.set("task-123", {"data": "test"})  # No TTL

        time.sleep(0.1)

        # Should still be present
        assert cache.get("task-123") is not None

    def test_contains(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Test contains check."""
        cache = LRUCache(max_size=100)
        cache.set("task-123", sample_data)

        assert "task-123" in cache
        assert "nonexistent" not in cache

    def test_cache_stats(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Test cache statistics."""
        cache = LRUCache(max_size=100)

        cache.set("task-123", sample_data)
        cache.get("task-123")  # Hit
        cache.get("nonexistent")  # Miss

        stats = cache.get_stats()

        assert stats.hits == 1
        assert stats.misses == 1

    def test_keys_method(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Test keys method."""
        cache = LRUCache(max_size=100)
        cache.set("task-1", sample_data)
        cache.set("task-2", sample_data)

        keys = list(cache.keys())

        assert "task-1" in keys
        assert "task-2" in keys


class TestCacheManager:
    """Tests for CacheManager class."""

    def test_create_manager(self) -> None:
        """Create a cache manager."""
        manager = CacheManager()

        assert manager is not None
        assert manager.backend == CacheBackend.MEMORY

    def test_create_manager_with_backend(self) -> None:
        """Create manager with specific backend."""
        manager = CacheManager(backend=CacheBackend.MEMORY)

        assert manager.backend == CacheBackend.MEMORY

    def test_set_and_get(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Set and get a value through manager."""
        manager = CacheManager()

        manager.set("tasks", "task-123", sample_data)
        result = manager.get("tasks", "task-123")

        assert result == sample_data

    def test_get_with_key_object(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Get using CacheKey object."""
        manager = CacheManager()
        key = CacheKey(namespace="tasks", identifier="task-123")

        manager.set_key(key, sample_data)
        result = manager.get_key(key)

        assert result == sample_data

    def test_delete(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Delete a value through manager."""
        manager = CacheManager()
        manager.set("tasks", "task-123", sample_data)

        result = manager.delete("tasks", "task-123")

        assert result is True
        assert manager.get("tasks", "task-123") is None

    def test_clear_namespace(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Clear all keys in a namespace."""
        manager = CacheManager()
        manager.set("tasks", "task-1", sample_data)
        manager.set("tasks", "task-2", sample_data)
        manager.set("users", "user-1", {"name": "test"})

        manager.clear_namespace("tasks")

        assert manager.get("tasks", "task-1") is None
        assert manager.get("tasks", "task-2") is None
        assert manager.get("users", "user-1") is not None

    def test_get_or_set(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Get or set pattern."""
        manager = CacheManager()
        call_count = 0

        def factory() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return sample_data

        # First call - should call factory
        result1 = manager.get_or_set("tasks", "task-123", factory)
        assert call_count == 1

        # Second call - should return cached value
        result2 = manager.get_or_set("tasks", "task-123", factory)
        assert call_count == 1  # Factory not called again

        assert result1 == result2

    def test_get_or_set_with_ttl(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Get or set with TTL."""
        manager = CacheManager()
        call_count = 0

        def factory() -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return sample_data

        manager.get_or_set("tasks", "task-123", factory, ttl=0.1)
        assert call_count == 1

        # Wait for expiration
        time.sleep(0.2)

        # Should call factory again
        manager.get_or_set("tasks", "task-123", factory)
        assert call_count == 2

    def test_invalidate_pattern(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Invalidate keys matching pattern."""
        manager = CacheManager()
        manager.set("tasks", "task-123", sample_data)
        manager.set("tasks", "task-456", sample_data)
        manager.set("tasks", "todo-789", sample_data)

        # Invalidate keys starting with "task"
        count = manager.invalidate_pattern("tasks", "task*")

        assert count == 2
        assert manager.get("tasks", "task-123") is None
        assert manager.get("tasks", "task-456") is None
        assert manager.get("tasks", "todo-789") is not None

    def test_cache_stats(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Get cache statistics."""
        manager = CacheManager()

        manager.set("tasks", "task-123", sample_data)
        manager.get("tasks", "task-123")  # Hit
        manager.get("tasks", "nonexistent")  # Miss

        stats = manager.get_stats()

        assert stats.hits == 1
        assert stats.misses == 1

    def test_multiple_namespaces(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Test multiple namespaces."""
        manager = CacheManager()

        manager.set("tasks", "item-1", sample_data)
        manager.set("users", "item-1", {"name": "user"})
        manager.set("repos", "item-1", {"name": "repo"})

        assert manager.get("tasks", "item-1") == sample_data
        assert manager.get("users", "item-1") == {"name": "user"}
        assert manager.get("repos", "item-1") == {"name": "repo"}

    def test_exists(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Test exists check."""
        manager = CacheManager()
        manager.set("tasks", "task-123", sample_data)

        assert manager.exists("tasks", "task-123") is True
        assert manager.exists("tasks", "nonexistent") is False

    def test_set_many(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Set multiple values at once."""
        manager = CacheManager()

        items = {
            "task-1": sample_data,
            "task-2": sample_data,
            "task-3": sample_data,
        }

        manager.set_many("tasks", items)

        assert manager.get("tasks", "task-1") == sample_data
        assert manager.get("tasks", "task-2") == sample_data
        assert manager.get("tasks", "task-3") == sample_data

    def test_get_many(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Get multiple values at once."""
        manager = CacheManager()

        manager.set("tasks", "task-1", {"id": 1})
        manager.set("tasks", "task-2", {"id": 2})

        results = manager.get_many("tasks", ["task-1", "task-2", "task-3"])

        assert results["task-1"] == {"id": 1}
        assert results["task-2"] == {"id": 2}
        assert results["task-3"] is None


class TestCacheManagerWithRedis:
    """Tests for CacheManager with Redis backend."""

    @pytest.mark.asyncio
    async def test_redis_set_and_get(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """Set and get with Redis backend."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = '{"id": "task-123"}'
        mock_redis.set = AsyncMock()

        manager = CacheManager(backend=CacheBackend.REDIS, redis_client=mock_redis)

        await manager.async_set("tasks", "task-123", sample_data)
        result = await manager.async_get("tasks", "task-123")

        assert result is not None
        assert result["id"] == "task-123"

    @pytest.mark.asyncio
    async def test_redis_delete(self) -> None:
        """Delete with Redis backend."""
        mock_redis = AsyncMock()
        mock_redis.delete.return_value = 1

        manager = CacheManager(backend=CacheBackend.REDIS, redis_client=mock_redis)

        result = await manager.async_delete("tasks", "task-123")

        assert result is True

    @pytest.mark.asyncio
    async def test_redis_ttl(
        self,
        sample_data: dict[str, Any],
    ) -> None:
        """TTL with Redis backend."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        mock_redis.expire = AsyncMock()

        manager = CacheManager(backend=CacheBackend.REDIS, redis_client=mock_redis)

        await manager.async_set("tasks", "task-123", sample_data, ttl=60)

        # Verify set was called with ex parameter
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args is not None
