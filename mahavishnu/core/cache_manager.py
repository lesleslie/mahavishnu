"""Cache Manager - LRU cache with optional Redis backend.

Provides caching infrastructure for frequent queries:

- In-memory LRU cache with TTL support
- Optional Redis backend for distributed caching
- Cache key namespacing
- Cache invalidation strategies
- Hit/miss statistics

Usage:
    from mahavishnu.core.cache_manager import CacheManager, CacheKey

    manager = CacheManager()

    # Set and get
    manager.set("tasks", "task-123", task_data)
    result = manager.get("tasks", "task-123")

    # Get or set pattern
    result = manager.get_or_set("tasks", "task-123", lambda: fetch_task())
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class CacheBackend(str, Enum):
    """Cache backend types."""

    MEMORY = "memory"
    REDIS = "redis"


@dataclass
class CacheKey:
    """A cache key with namespace.

    Attributes:
        namespace: Cache namespace (e.g., "tasks", "users")
        identifier: Unique identifier within namespace
        suffix: Optional suffix for sub-keys
    """

    namespace: str
    identifier: str
    suffix: str | None = None

    def __str__(self) -> str:
        """Convert to string representation."""
        if self.suffix:
            return f"{self.namespace}:{self.identifier}:{self.suffix}"
        return f"{self.namespace}:{self.identifier}"

    def __eq__(self, other: object) -> bool:
        """Check equality."""
        if isinstance(other, CacheKey):
            return (
                self.namespace == other.namespace
                and self.identifier == other.identifier
                and self.suffix == other.suffix
            )
        return False

    def __hash__(self) -> int:
        """Make hashable."""
        return hash(str(self))

    @classmethod
    def from_string(cls, key: str) -> CacheKey:
        """Create key from string.

        Args:
            key: String in format "namespace:identifier" or "namespace:identifier:suffix"

        Returns:
            CacheKey instance
        """
        parts = key.split(":", 2)
        if len(parts) == 2:
            return cls(namespace=parts[0], identifier=parts[1])
        return cls(namespace=parts[0], identifier=parts[1], suffix=parts[2])


@dataclass
class CacheStats:
    """Cache statistics.

    Attributes:
        hits: Number of cache hits
        misses: Number of cache misses
        evictions: Number of cache evictions
    """

    hits: int = 0
    misses: int = 0
    evictions: int = 0

    def record_hit(self) -> None:
        """Record a cache hit."""
        self.hits += 1

    def record_miss(self) -> None:
        """Record a cache miss."""
        self.misses += 1

    def record_eviction(self) -> None:
        """Record a cache eviction."""
        self.evictions += 1

    @property
    def hit_rate(self) -> float:
        """Calculate hit rate."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": self.hit_rate,
        }


@dataclass
class CacheEntry:
    """A cache entry with optional TTL.

    Attributes:
        value: Cached value
        expires_at: Optional expiration timestamp
    """

    value: Any
    expires_at: float | None = None

    def is_expired(self) -> bool:
        """Check if entry is expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class LRUCache:
    """In-memory LRU cache with TTL support.

    Features:
    - Fixed maximum size with LRU eviction
    - Time-to-live (TTL) support
    - Hit/miss statistics

    Example:
        cache = LRUCache(max_size=100)
        cache.set("key", value, ttl=60)
        result = cache.get("key")
    """

    def __init__(self, max_size: int = 1000) -> None:
        """Initialize LRU cache.

        Args:
            max_size: Maximum number of entries
        """
        self.max_size = max_size
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._stats = CacheStats()

    def __len__(self) -> int:
        """Get cache size."""
        return len(self._cache)

    def __contains__(self, key: str) -> bool:
        """Check if key exists."""
        entry = self._cache.get(key)
        if entry is None:
            return False
        if entry.is_expired():
            del self._cache[key]
            return False
        return True

    def set(
        self,
        key: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """Set a cache value.

        Args:
            key: Cache key
            value: Value to cache
            ttl: Optional time-to-live in seconds
        """
        # Calculate expiration time
        expires_at = None
        if ttl is not None:
            expires_at = time.time() + ttl

        # Remove if exists (to update order)
        if key in self._cache:
            del self._cache[key]

        # Evict if at capacity
        while len(self._cache) >= self.max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
            self._stats.record_eviction()

        # Add entry
        self._cache[key] = CacheEntry(value=value, expires_at=expires_at)

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """Get a cache value.

        Args:
            key: Cache key
            default: Default value if not found

        Returns:
            Cached value or default
        """
        entry = self._cache.get(key)

        if entry is None:
            self._stats.record_miss()
            return default

        if entry.is_expired():
            del self._cache[key]
            self._stats.record_miss()
            return default

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        self._stats.record_hit()

        return entry.value

    def delete(self, key: str) -> bool:
        """Delete a cache entry.

        Args:
            key: Cache key

        Returns:
            True if deleted, False if not found
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all entries."""
        self._cache.clear()

    def keys(self) -> list[str]:
        """Get all keys.

        Returns:
            List of cache keys
        """
        # Filter out expired entries
        valid_keys = []
        expired_keys = []

        for key, entry in self._cache.items():
            if entry.is_expired():
                expired_keys.append(key)
            else:
                valid_keys.append(key)

        # Remove expired entries
        for key in expired_keys:
            del self._cache[key]

        return valid_keys

    def get_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            CacheStats instance
        """
        return self._stats


class CacheManager:
    """Cache manager with pluggable backends.

    Features:
    - In-memory LRU cache (default)
    - Optional Redis backend for distributed caching
    - Namespace support
    - Pattern-based invalidation
    - Statistics tracking

    Example:
        manager = CacheManager()

        # Simple set/get
        manager.set("tasks", "task-123", task_data)
        result = manager.get("tasks", "task-123")

        # Get or set pattern
        result = manager.get_or_set("tasks", "task-123", fetch_task)
    """

    def __init__(
        self,
        backend: CacheBackend = CacheBackend.MEMORY,
        max_size: int = 1000,
        redis_client: Any = None,
    ) -> None:
        """Initialize cache manager.

        Args:
            backend: Cache backend type
            max_size: Maximum entries for memory cache
            redis_client: Optional Redis client for Redis backend
        """
        self.backend = backend
        self._cache = LRUCache(max_size=max_size)
        self._redis = redis_client
        self._stats = CacheStats()

    def _make_key(self, namespace: str, identifier: str) -> str:
        """Create cache key string.

        Args:
            namespace: Cache namespace
            identifier: Key identifier

        Returns:
            Key string
        """
        return f"{namespace}:{identifier}"

    def set(
        self,
        namespace: str,
        identifier: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """Set a cache value.

        Args:
            namespace: Cache namespace
            identifier: Key identifier
            value: Value to cache
            ttl: Optional time-to-live in seconds
        """
        key = self._make_key(namespace, identifier)
        self._cache.set(key, value, ttl=ttl)

    def set_key(
        self,
        key: CacheKey,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """Set using CacheKey object.

        Args:
            key: CacheKey instance
            value: Value to cache
            ttl: Optional time-to-live in seconds
        """
        self._cache.set(str(key), value, ttl=ttl)

    def get(
        self,
        namespace: str,
        identifier: str,
        default: Any = None,
    ) -> Any:
        """Get a cache value.

        Args:
            namespace: Cache namespace
            identifier: Key identifier
            default: Default value if not found

        Returns:
            Cached value or default
        """
        key = self._make_key(namespace, identifier)
        result = self._cache.get(key, default=default)

        # Update stats
        if result is default and default is None:
            self._stats.record_miss()
        else:
            self._stats.record_hit()

        return result

    def get_key(
        self,
        key: CacheKey,
        default: Any = None,
    ) -> Any:
        """Get using CacheKey object.

        Args:
            key: CacheKey instance
            default: Default value if not found

        Returns:
            Cached value or default
        """
        return self._cache.get(str(key), default=default)

    def delete(self, namespace: str, identifier: str) -> bool:
        """Delete a cache entry.

        Args:
            namespace: Cache namespace
            identifier: Key identifier

        Returns:
            True if deleted
        """
        key = self._make_key(namespace, identifier)
        return self._cache.delete(key)

    def exists(self, namespace: str, identifier: str) -> bool:
        """Check if key exists.

        Args:
            namespace: Cache namespace
            identifier: Key identifier

        Returns:
            True if key exists
        """
        key = self._make_key(namespace, identifier)
        return key in self._cache

    def clear_namespace(self, namespace: str) -> int:
        """Clear all keys in a namespace.

        Args:
            namespace: Cache namespace

        Returns:
            Number of keys cleared
        """
        prefix = f"{namespace}:"
        keys_to_delete = [
            key for key in self._cache.keys()
            if key.startswith(prefix)
        ]

        for key in keys_to_delete:
            self._cache.delete(key)

        return len(keys_to_delete)

    def invalidate_pattern(self, namespace: str, pattern: str) -> int:
        """Invalidate keys matching pattern.

        Args:
            namespace: Cache namespace
            pattern: Glob pattern to match

        Returns:
            Number of keys invalidated
        """
        prefix = f"{namespace}:"
        keys_to_delete = []

        for key in self._cache.keys():
            if key.startswith(prefix):
                # Extract identifier part
                identifier = key[len(prefix):]
                if fnmatch.fnmatch(identifier, pattern):
                    keys_to_delete.append(key)

        for key in keys_to_delete:
            self._cache.delete(key)

        return len(keys_to_delete)

    def get_or_set(
        self,
        namespace: str,
        identifier: str,
        factory: Callable[[], Any],
        ttl: float | None = None,
    ) -> Any:
        """Get value or set from factory.

        Args:
            namespace: Cache namespace
            identifier: Key identifier
            factory: Function to create value if not cached
            ttl: Optional time-to-live

        Returns:
            Cached or created value
        """
        result = self.get(namespace, identifier)
        if result is not None:
            return result

        # Create and cache value
        value = factory()
        self.set(namespace, identifier, value, ttl=ttl)
        return value

    def set_many(
        self,
        namespace: str,
        items: dict[str, Any],
        ttl: float | None = None,
    ) -> None:
        """Set multiple values at once.

        Args:
            namespace: Cache namespace
            items: Dictionary of identifier -> value
            ttl: Optional time-to-live
        """
        for identifier, value in items.items():
            self.set(namespace, identifier, value, ttl=ttl)

    def get_many(
        self,
        namespace: str,
        identifiers: list[str],
    ) -> dict[str, Any]:
        """Get multiple values at once.

        Args:
            namespace: Cache namespace
            identifiers: List of identifiers

        Returns:
            Dictionary of identifier -> value
        """
        result = {}
        for identifier in identifiers:
            result[identifier] = self.get(namespace, identifier)
        return result

    def get_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            CacheStats instance
        """
        return self._stats

    # Async methods for Redis backend

    async def async_set(
        self,
        namespace: str,
        identifier: str,
        value: Any,
        ttl: float | None = None,
    ) -> None:
        """Async set for Redis backend.

        Args:
            namespace: Cache namespace
            identifier: Key identifier
            value: Value to cache
            ttl: Optional time-to-live
        """
        if self._redis is None:
            self.set(namespace, identifier, value, ttl)
            return

        key = self._make_key(namespace, identifier)
        json_value = json.dumps(value)

        if ttl:
            await self._redis.set(key, json_value, ex=int(ttl))
        else:
            await self._redis.set(key, json_value)

    async def async_get(
        self,
        namespace: str,
        identifier: str,
        default: Any = None,
    ) -> Any:
        """Async get for Redis backend.

        Args:
            namespace: Cache namespace
            identifier: Key identifier
            default: Default value

        Returns:
            Cached value or default
        """
        if self._redis is None:
            return self.get(namespace, identifier, default)

        key = self._make_key(namespace, identifier)
        result = await self._redis.get(key)

        if result is None:
            return default

        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return result

    async def async_delete(
        self,
        namespace: str,
        identifier: str,
    ) -> bool:
        """Async delete for Redis backend.

        Args:
            namespace: Cache namespace
            identifier: Key identifier

        Returns:
            True if deleted
        """
        if self._redis is None:
            return self.delete(namespace, identifier)

        key = self._make_key(namespace, identifier)
        result = await self._redis.delete(key)
        return result > 0


__all__ = [
    "CacheManager",
    "CacheBackend",
    "LRUCache",
    "CacheStats",
    "CacheKey",
]
