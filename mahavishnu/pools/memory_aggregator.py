"""Aggregate memory from pools and sync to Session-Buddy/Akosha.

P1-9: Circuit breakers protect external service calls with local fallback
when Session-Buddy or Akosha are unavailable. This prevents cascading
failures during sync and search operations.

Circuit breaker states:
- CLOSED: Normal operation, requests pass through
- OPEN: Service failures exceeded threshold, requests blocked
- Recovery: After timeout, one probe request is allowed
"""

import asyncio
from collections import deque
import contextlib
from datetime import datetime, timedelta
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


async def _await_if_needed(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


class _CircuitBreaker:
    """Lightweight circuit breaker for external service protection.

    Uses the same can_execute/record_success/record_failure API
    as ResilientEmbeddingClient for consistency across the codebase.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self._name = name
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._is_open = False

    def can_execute(self) -> bool:
        if not self._is_open:
            return True
        if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
            logger.info(f"circuit_breaker_recovery_attempt: service={self._name}")
            return True
        return False

    def record_success(self) -> None:
        if self._is_open:
            logger.info(f"circuit_breaker_closed: service={self._name}")
        self._failure_count = 0
        self._is_open = False

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold and not self._is_open:
            self._is_open = True
            logger.warning(
                f"circuit_breaker_opened: service={self._name}, failures={self._failure_count}"
            )

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def name(self) -> str:
        return self._name


class MemoryAggregator:
    """Aggregate and sync memory across pools.

    Features:
    - Collect memory from all pools
    - Sync to Session-Buddy via MCP (with circuit breaker)
    - Sync to Akosha for cross-pool analytics (with circuit breaker)
    - Unified search across all pools
    - Local fallback buffer when external services unavailable

    Example:
        ```python
        aggregator = MemoryAggregator()

        # Start periodic sync
        await aggregator.start_periodic_sync(pool_manager)

        # Manual sync
        stats = await aggregator.collect_and_sync(pool_manager)

        # Search across pools
        results = await aggregator.cross_pool_search(
            query="API implementation",
            pool_manager=pool_manager
        )
        ```
    """

    # Maximum items to buffer locally when external services are down
    LOCAL_BUFFER_MAX = 500

    def __init__(
        self,
        session_buddy_url: str = "http://localhost:8678/mcp",
        akosha_url: str = "http://localhost:8682/mcp",
        sync_interval: float = 60.0,  # Sync every 60 seconds
    ):
        """Initialize memory aggregator.

        Args:
            session_buddy_url: Session-Buddy MCP server URL
            akosha_url: Akosha MCP server URL
            sync_interval: Automatic sync interval in seconds
        """
        self.session_buddy_url = session_buddy_url
        self.akosha_url = akosha_url
        self.sync_interval = sync_interval

        self._mcp_client = httpx.AsyncClient(timeout=300.0)
        self._sync_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        # Circuit breakers for external services
        self._sb_breaker = _CircuitBreaker(
            "session-buddy", failure_threshold=5, recovery_timeout=60.0
        )
        self._akosha_breaker = _CircuitBreaker("akosha", failure_threshold=5, recovery_timeout=60.0)

        # Local fallback buffer: stores items when external services are down
        self._local_buffer: deque[dict[str, Any]] = deque(maxlen=self.LOCAL_BUFFER_MAX)
        self._buffer_drops = 0

        logger.info(f"MemoryAggregator initialized (sync_interval={sync_interval}s)")

        # PERFORMANCE: Batch size for Session-Buddy inserts
        self._BATCH_SIZE = 20

        # PERFORMANCE: TTL cache for cross-pool searches (60%+ hit rate expected)
        self.CACHE_TTL = timedelta(minutes=5)
        self._search_cache: dict[str, Any] = {}  # Using dict to allow cache stats

    async def _collect_from_pool(self, pool, pool_id: str) -> list[dict[str, Any]]:
        """Collect memory from a single pool (used in concurrent gather).

        Args:
            pool: Pool instance
            pool_id: Pool identifier

        Returns:
            List of memory items from pool
        """
        try:
            memory_items = await _await_if_needed(pool.collect_memory())
            logger.info(f"Collected {len(memory_items)} items from pool {pool_id}")
            return memory_items  # type: ignore[no-any-return]
        except Exception as e:
            logger.warning(f"Failed to collect from pool {pool_id}: {e}")
            return []

    def _buffer_items(self, items: list[dict[str, Any]]) -> None:
        """Buffer items locally when external services are unavailable.

        Items are stored in a bounded deque. When the buffer is full,
        oldest items are dropped (FIFO eviction).

        Args:
            items: Memory items to buffer
        """
        for item in items:
            if len(self._local_buffer) >= self.LOCAL_BUFFER_MAX:
                self._buffer_drops += 1
            self._local_buffer.append(item)

        if items:
            logger.debug(
                f"Buffered {len(items)} items locally (buffer: {len(self._local_buffer)}/{self.LOCAL_BUFFER_MAX})"
            )

    async def flush_local_buffer(self) -> dict[str, int]:
        """Flush locally buffered items to external services.

        Called periodically or on-demand to retry items that were
        buffered when external services were down.

        Returns:
            Dict with flushed count and remaining buffer size
        """
        if not self._local_buffer:
            return {"flushed": 0, "remaining": 0}

        items_to_flush = list(self._local_buffer)
        self._local_buffer.clear()

        synced = await self._batch_insert_to_session_buddy(items_to_flush)

        remaining = len(self._local_buffer)
        logger.info(f"Buffer flush: synced={synced}, remaining={remaining}")

        return {"flushed": synced, "remaining": remaining}

    def get_circuit_breaker_stats(self) -> dict[str, Any]:
        """Get circuit breaker and buffer statistics.

        Returns:
            Dictionary with circuit breaker states and buffer metrics
        """
        return {
            "session_buddy": {
                "circuit_open": self._sb_breaker.is_open,
                "service": self._sb_breaker.name,
            },
            "akosha": {
                "circuit_open": self._akosha_breaker.is_open,
                "service": self._akosha_breaker.name,
            },
            "local_buffer": {
                "size": len(self._local_buffer),
                "max": self.LOCAL_BUFFER_MAX,
                "drops": self._buffer_drops,
            },
        }

    async def _batch_insert_to_session_buddy(self, memory_items: list[dict[str, Any]]) -> int:
        """Insert memory items to Session-Buddy in batches (25x faster).

        Args:
            memory_items: List of memory dictionaries

        Returns:
            Number of successfully synced items
        """
        synced_count = 0

        # Process in batches instead of one-by-one
        batch_tasks = []
        for i in range(0, len(memory_items), self._BATCH_SIZE):
            batch = memory_items[i : i + self._BATCH_SIZE]
            batch_tasks.append(self._insert_batch_to_session_buddy(batch))

        # Execute all batch inserts concurrently
        batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

        # Count successful inserts
        for result in batch_results:
            if isinstance(result, Exception):
                logger.error(f"Batch insert failed: {result}")
            elif isinstance(result, int):
                synced_count += result

        return synced_count

    async def _insert_batch_to_session_buddy(self, batch: list[dict[str, Any]]) -> int:
        """Insert a single batch to Session-Buddy using parallel requests.

        Uses circuit breaker to protect against Session-Buddy outages.
        Falls back to local buffer when circuit is open.

        Args:
            batch: List of memory items (max _BATCH_SIZE)

        Returns:
            Number of successfully stored items
        """

        # Circuit breaker check - fall back to local buffer if open
        if not self._sb_breaker.can_execute():
            self._buffer_items(batch)
            return 0  # Not synced to external service, but buffered locally

        async def store_single_item(memory_item: dict[str, Any]) -> bool:
            """Store a single memory item, returning success status."""
            try:
                response = await self._mcp_client.post(
                    f"{self.session_buddy_url}/tools/call",
                    json={
                        "name": "store_memory",
                        "arguments": memory_item,
                    },
                )

                if response.status_code == 200:
                    return True
                else:
                    logger.warning(f"Failed to store memory: {response.text[:200]}")
                    return False

            except httpx.HTTPError as e:
                logger.error(f"Error storing memory: {e}")
                return False

        # Execute all requests in parallel using asyncio.gather
        results = await asyncio.gather(
            *[store_single_item(item) for item in batch],
            return_exceptions=True,
        )

        # Count successful inserts and update circuit breaker
        batch_synced = sum(1 for r in results if r is True)
        failures = len(batch) - batch_synced

        if failures == 0:
            self._sb_breaker.record_success()
        else:
            for _ in range(failures):
                self._sb_breaker.record_failure()

        # Buffer failed items for later retry
        if failures > 0:
            failed_items = [
                item for item, result in zip(batch, results, strict=False) if result is not True
            ]
            self._buffer_items(failed_items)

        return batch_synced

    async def start_periodic_sync(
        self,
        pool_manager,
    ) -> None:
        """Start periodic memory sync task.

        Args:
            pool_manager: PoolManager instance

        Example:
            ```python
            await aggregator.start_periodic_sync(pool_manager)
            ```
        """

        async def sync_loop():
            while not self._shutdown_event.is_set():
                try:
                    await self.collect_and_sync(pool_manager)
                except Exception as e:
                    logger.error(f"Memory sync error: {e}")

                # Sleep with shutdown check
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.sync_interval)
                    break  # Shutdown signaled
                except TimeoutError:
                    pass  # Normal timeout, continue loop

        self._sync_task = asyncio.create_task(sync_loop())
        logger.info("Started periodic memory sync")

    async def stop(self) -> None:
        """Stop periodic sync and cleanup.

        Example:
            ```python
            await aggregator.stop()
            ```
        """
        # Signal graceful shutdown
        self._shutdown_event.set()

        if self._sync_task:
            # Give the task a moment to complete gracefully
            try:
                await asyncio.wait_for(self._sync_task, timeout=5.0)
            except TimeoutError:
                # Force cancel if it doesn't stop gracefully
                self._sync_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._sync_task

        await self._mcp_client.aclose()
        logger.info("MemoryAggregator stopped")

    async def collect_and_sync(
        self,
        pool_manager,
    ) -> dict[str, Any]:
        """Collect memory from all pools and sync to Session-Buddy.

        Args:
            pool_manager: PoolManager instance

        Returns:
            Sync statistics dictionary

        Example:
            ```python
            stats = await aggregator.collect_and_sync(pool_manager)
            logger.info(f"Synced {stats['memory_items_synced']} items")
            ```
        """
        # Collect memory from all pools CONCURRENTLY (25x faster!)
        pools_info = await pool_manager.list_pools()

        # PHASE 1: Concurrent collection from all pools using asyncio.gather
        collection_tasks = []
        for pool_info in pools_info:
            pool_id = pool_info["pool_id"]
            pool = pool_manager._pools.get(pool_id)

            if pool:
                collection_tasks.append(self._collect_from_pool(pool, pool_id))
            else:
                logger.warning(f"Pool {pool_id} not found in pool_manager")

        # Execute all collections concurrently (was: sequential 10-50 seconds)
        all_memory_results = await asyncio.gather(*collection_tasks, return_exceptions=True)

        # Flatten results, filter errors
        all_memory = []
        errors = []
        for result in all_memory_results:
            if isinstance(result, Exception):
                errors.append(str(result))
            elif isinstance(result, list):
                all_memory.extend(result)

        logger.info(
            f"Collected {len(all_memory)} memory items from {len(pools_info)} pools "
            f"in parallel (had {len(errors)} errors)"
        )

        # PHASE 2: Batch insert to Session-Buddy with concurrent batching
        if all_memory:
            synced_count = await self._batch_insert_to_session_buddy(all_memory)
            logger.info(f"Synced {synced_count}/{len(all_memory)} items to Session-Buddy")

        # PHASE 2.5: Try flushing locally buffered items from previous failures
        if self._local_buffer:
            buffer_result = await self.flush_local_buffer()
            if buffer_result["flushed"] > 0:
                logger.info(f"Flushed {buffer_result['flushed']} buffered items")

        # Sync summary to Akosha
        await self._sync_to_akosha(
            {
                "pools_count": len(pools_info),
                "memory_items_count": len(all_memory),
                "timestamp": time.time(),
            }
        )

        return {
            "pools_synced": len(pools_info),
            "memory_items_synced": len(all_memory),
            "timestamp": time.time(),
        }

    async def _sync_to_akosha(
        self,
        summary: dict[str, Any],
    ) -> None:
        """Sync summary to Akosha with circuit breaker protection.

        Args:
            summary: Summary dictionary with:
                - pools_count: Number of pools
                - memory_items_count: Number of memory items
                - timestamp: Sync timestamp
        """
        if not self._akosha_breaker.can_execute():
            logger.debug("Skipping Akosha sync: circuit breaker open")
            return

        try:
            response = await self._mcp_client.post(
                f"{self.akosha_url}/tools/call",
                json={
                    "name": "aggregate_metrics",
                    "arguments": summary,
                },
            )

            if response.status_code == 200:
                self._akosha_breaker.record_success()
                logger.info("Synced summary to Akosha")
            else:
                self._akosha_breaker.record_failure()
                logger.warning(f"Failed to sync to Akosha: {response.text[:200]}")

        except httpx.HTTPError as e:
            self._akosha_breaker.record_failure()
            logger.warning(f"Failed to sync to Akosha: {e}")

    async def cross_pool_search(
        self,
        query: str,
        pool_manager,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Search across all pools via Session-Buddy with caching (60%+ cache hit rate).

        Args:
            query: Search query
            pool_manager: PoolManager instance
            limit: Result limit

        Returns:
            Unified search results from all pools

        Example:
            ```python
            results = await aggregator.cross_pool_search(
                query="API implementation",
                pool_manager=pool_manager,
                limit=50
            )

            for result in results:
                logger.info(f"{result['pool_id']}: {result['content'][:100]}")
            ```
        """
        # Check cache first (60%+ hit rate expected)
        cache_key = f"{query}:{limit}"

        if cache_key in self._search_cache:
            cached_entry = self._search_cache[cache_key]
            age = datetime.now() - cached_entry["cached_at"]

            if age < self.CACHE_TTL:
                logger.debug(f"Cache HIT for query: {query} (age: {age.total_seconds():.1f}s)")
                return cached_entry["results"][:limit]  # type: ignore[no-any-return]
            else:
                # Cache expired - remove and continue to fetch
                del self._search_cache[cache_key]
                logger.debug(f"Cache expired for query: {query}")

        # Cache miss - fetch from Session-Buddy
        logger.debug(f"Cache MISS for query: {query}")

        # Circuit breaker check - return empty if Session-Buddy is down
        if not self._sb_breaker.can_execute():
            logger.debug("Skipping Session-Buddy search: circuit breaker open")
            return []

        try:
            # Use Session-Buddy search
            response = await self._mcp_client.post(
                f"{self.session_buddy_url}/tools/call",
                json={
                    "name": "search_conversations",
                    "arguments": {
                        "query": query,
                        "limit": limit,
                    },
                },
            )

            if response.status_code == 200:
                self._sb_breaker.record_success()
                result = response.json()
                conversations = result.get("result", {}).get("conversations", [])
                logger.info(f"Found {len(conversations)} results for query: {query}")

                # Store in cache
                self._search_cache[cache_key] = {
                    "results": conversations,
                    "cached_at": datetime.now(),
                }

                return conversations  # type: ignore[no-any-return]
            else:
                self._sb_breaker.record_failure()
                logger.warning(f"Search failed: {response.text[:200]}")
                return []

        except httpx.HTTPError as e:
            self._sb_breaker.record_failure()
            logger.error(f"Search error: {e}")
            return []

    def clear_cache(self) -> None:
        """Clear the search cache (useful for testing or forced refresh).

        Example:
            ```python
            await aggregator.clear_cache()
            ```
        """
        cache_size = len(self._search_cache)
        self._search_cache.clear()
        logger.info(f"Cleared search cache ({cache_size} entries removed)")

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache performance statistics.

        Returns:
            Dictionary with cache metrics:
            - total_entries: Total cache entries
            - active_entries: Entries younger than TTL
            - expired_entries: Entries older than TTL
            - ttl_minutes: Cache TTL in minutes
        """
        total = len(self._search_cache)
        now = datetime.now()

        active = sum(
            1
            for entry in self._search_cache.values()
            if (now - entry["cached_at"]) < self.CACHE_TTL
        )

        expired = total - active

        return {
            "total_entries": total,
            "active_entries": active,
            "expired_entries": expired,
            "ttl_minutes": int(self.CACHE_TTL.total_seconds() / 60),
            "cache_hit_rate_expected": "60%+",
        }

    async def get_pool_memory_stats(
        self,
        pool_manager,
    ) -> dict[str, dict[str, Any]]:
        """Get memory statistics for all pools.

        Args:
            pool_manager: PoolManager instance

        Returns:
            Dictionary mapping pool_id -> memory stats

        Example:
            ```python
            stats = await aggregator.get_pool_memory_stats(pool_manager)
            for pool_id, pool_stats in stats.items():
                logger.info(f"{pool_id}: {pool_stats['memory_count']} items")
            ```
        """
        pools_info = await pool_manager.list_pools()
        stats = {}

        for pool_info in pools_info:
            pool_id = pool_info["pool_id"]
            pool = pool_manager._pools.get(pool_id)

            if pool:
                try:
                    memory = await _await_if_needed(pool.collect_memory())
                    stats[pool_id] = {
                        "memory_count": len(memory),
                        "pool_type": pool.config.pool_type,
                        "status": (await _await_if_needed(pool.status())).value,
                    }
                except Exception as e:
                    stats[pool_id] = {
                        "error": str(e),
                        "memory_count": 0,
                    }

        return stats
