"""Aggregate memory from pools and sync to Session-Buddy/Akosha."""

import asyncio
import logging
import time
from typing import Any

import httpx


logger = logging.getLogger(__name__)


class MemoryAggregator:
    """Aggregate and sync memory across pools.

    Features:
    - Collect memory from all pools
    - Sync to Session-Buddy via MCP
    - Sync to Akosha for cross-pool analytics
    - Unified search across all pools

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

        logger.info(
            f"MemoryAggregator initialized "
            f"(sync_interval={sync_interval}s)"
        )

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
            while True:
                try:
                    await self.collect_and_sync(pool_manager)
                except Exception as e:
                    logger.error(f"Memory sync error: {e}")

                await asyncio.sleep(self.sync_interval)

        self._sync_task = asyncio.create_task(sync_loop())
        logger.info("Started periodic memory sync")

    async def stop(self) -> None:
        """Stop periodic sync and cleanup.

        Example:
            ```python
            await aggregator.stop()
            ```
        """
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass

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
            print(f"Synced {stats['memory_items_synced']} items")
            ```
        """
        # Collect memory from all pools
        all_memory = []
        pools_info = await pool_manager.list_pools()

        for pool_info in pools_info:
            pool_id = pool_info["pool_id"]
            pool = pool_manager._pools.get(pool_id)

            if pool:
                try:
                    memory_items = await pool.collect_memory()
                    all_memory.extend(memory_items)

                    logger.info(
                        f"Collected {len(memory_items)} memory items "
                        f"from pool {pool_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to collect memory from pool {pool_id}: {e}"
                    )

        # Batch insert to Session-Buddy
        if all_memory:
            await self._sync_to_session_buddy(all_memory)

        # Sync summary to Akosha
        await self._sync_to_akosha({
            "pools_count": len(pools_info),
            "memory_items_count": len(all_memory),
            "timestamp": time.time(),
        })

        return {
            "pools_synced": len(pools_info),
            "memory_items_synced": len(all_memory),
            "timestamp": time.time(),
        }

    async def _sync_to_session_buddy(
        self,
        memory_items: list[dict[str, Any]],
    ) -> None:
        """Sync memory items to Session-Buddy.

        Args:
            memory_items: List of memory dictionaries

        Each memory item should have:
            - content: Text content to store
            - metadata: Dict with metadata
        """
        synced_count = 0

        # Batch store memories
        for memory_item in memory_items:
            try:
                response = await self._mcp_client.post(
                    f"{self.session_buddy_url}/tools/call",
                    json={
                        "name": "store_memory",
                        "arguments": memory_item,
                    },
                )

                if response.status_code == 200:
                    synced_count += 1
                else:
                    logger.warning(
                        f"Failed to store memory: {response.text[:200]}"
                    )

            except httpx.HTTPError as e:
                logger.error(f"Error storing memory: {e}")

        logger.info(f"Synced {synced_count}/{len(memory_items)} items to Session-Buddy")

    async def _sync_to_akosha(
        self,
        summary: dict[str, Any],
    ) -> None:
        """Sync summary to Akosha.

        Args:
            summary: Summary dictionary with:
                - pools_count: Number of pools
                - memory_items_count: Number of memory items
                - timestamp: Sync timestamp
        """
        try:
            response = await self._mcp_client.post(
                f"{self.akosha_url}/tools/call",
                json={
                    "name": "aggregate_metrics",
                    "arguments": summary,
                },
            )

            if response.status_code == 200:
                logger.info("Synced summary to Akosha")
            else:
                logger.warning(
                    f"Failed to sync to Akosha: {response.text[:200]}"
                )

        except httpx.HTTPError as e:
            logger.warning(f"Failed to sync to Akosha: {e}")

    async def cross_pool_search(
        self,
        query: str,
        pool_manager,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Search across all pools via Session-Buddy.

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
                print(f"{result['pool_id']}: {result['content'][:100]}")
            ```
        """
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
                result = response.json()
                conversations = result.get("result", {}).get("conversations", [])
                logger.info(f"Found {len(conversations)} results for query: {query}")
                return conversations
            else:
                logger.warning(f"Search failed: {response.text[:200]}")
                return []

        except httpx.HTTPError as e:
            logger.error(f"Search error: {e}")
            return []

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
                print(f"{pool_id}: {pool_stats['memory_count']} items")
            ```
        """
        pools_info = await pool_manager.list_pools()
        stats = {}

        for pool_info in pools_info:
            pool_id = pool_info["pool_id"]
            pool = pool_manager._pools.get(pool_id)

            if pool:
                try:
                    memory = await pool.collect_memory()
                    stats[pool_id] = {
                        "memory_count": len(memory),
                        "pool_type": pool.config.pool_type,
                        "status": (await pool.status()).value,
                    }
                except Exception as e:
                    stats[pool_id] = {
                        "error": str(e),
                        "memory_count": 0,
                    }

        return stats
