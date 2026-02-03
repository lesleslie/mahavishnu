"""Multi-pool orchestration and management."""

import asyncio
import logging
from typing import Any
from enum import Enum

from .base import BasePool, PoolConfig, PoolStatus
from .mahavishnu_pool import MahavishnuPool
from .session_buddy_pool import SessionBuddyPool
from .kubernetes_pool import KubernetesPool
from ..mcp.protocols.message_bus import MessageBus, MessageType


logger = logging.getLogger(__name__)


class PoolSelector(Enum):
    """Pool selection strategies.

    Attributes:
        ROUND_ROBIN: Distribute tasks evenly across pools
        LEAST_LOADED: Route to pool with fewest active workers
        RANDOM: Random pool selection
        AFFINITY: Route to same pool for related tasks
    """
    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    RANDOM = "random"
    AFFINITY = "affinity"


class PoolManager:
    """Manage multiple pools of different types.

    Features:
    - Spawn pools by type and configuration
    - Route tasks to appropriate pools
    - Handle inter-pool communication
    - Aggregate results across pools
    - Monitor pool health

    Example:
        ```python
        # Create pool manager
        pool_mgr = PoolManager(terminal_manager=tm)

        # Spawn pools
        config = PoolConfig(name="local", pool_type="mahavishnu")
        pool_id = await pool_mgr.spawn_pool("mahavishnu", config)

        # Execute task
        result = await pool_mgr.execute_on_pool(pool_id, {"prompt": "Hello"})

        # Route task automatically
        result = await pool_mgr.route_task(
            {"prompt": "Hello"},
            pool_selector=PoolSelector.LEAST_LOADED
        )
        ```
    """

    def __init__(
        self,
        terminal_manager,
        session_buddy_client: Any = None,
        message_bus: MessageBus | None = None,
    ):
        """Initialize pool manager.

        Args:
            terminal_manager: TerminalManager for terminal control
            session_buddy_client: Optional Session-Buddy MCP client
            message_bus: Optional MessageBus for inter-pool communication
        """
        self.terminal_manager = terminal_manager
        self.session_buddy_client = session_buddy_client
        self.message_bus = message_bus or MessageBus()

        self._pools: dict[str, BasePool] = {}
        self._pool_selector = PoolSelector.LEAST_LOADED
        self._round_robin_index = 0

        logger.info("PoolManager initialized")

    async def spawn_pool(
        self,
        pool_type: str,
        config: PoolConfig,
    ) -> str:
        """Spawn a new pool of specified type.

        Args:
            pool_type: Type of pool ("mahavishnu", "session-buddy", "kubernetes")
            config: Pool configuration

        Returns:
            pool_id: Unique pool identifier

        Raises:
            ValueError: If pool_type is unknown
            Exception: If pool fails to start

        Example:
            ```python
            config = PoolConfig(
                name="local-pool",
                pool_type="mahavishnu",
                min_workers=2,
                max_workers=5,
            )
            pool_id = await pool_mgr.spawn_pool("mahavishnu", config)
            ```
        """
        logger.info(f"Spawning {pool_type} pool: {config.name}")

        try:
            if pool_type == "mahavishnu":
                pool = MahavishnuPool(
                    config=config,
                    terminal_manager=self.terminal_manager,
                    session_buddy_client=self.session_buddy_client,
                )
            elif pool_type == "session-buddy":
                pool = SessionBuddyPool(
                    config=config,
                    session_buddy_url=config.get(
                        "session_buddy_url",
                        "http://localhost:8678/mcp"
                    ),
                )
            elif pool_type == "kubernetes":
                pool = KubernetesPool(
                    config=config,
                    namespace=config.get("namespace", "mahavishnu"),
                    kubeconfig_path=config.get("kubeconfig_path"),
                    container_image=config.get(
                        "container_image",
                        "python:3.13-slim"
                    ),
                )
            else:
                raise ValueError(f"Unknown pool type: {pool_type}")

            # Start the pool
            pool_id = await pool.start()
            self._pools[pool_id] = pool

            # Announce pool creation via message bus
            await self.message_bus.publish({
                "type": "pool_created",
                "source_pool_id": pool_id,
                "payload": {
                    "pool_id": pool_id,
                    "pool_type": pool_type,
                    "config": {
                        "name": config.name,
                        "min_workers": config.min_workers,
                        "max_workers": config.max_workers,
                    },
                },
            })

            logger.info(f"Pool {pool_id} spawned successfully (type: {pool_type})")

            return pool_id

        except Exception as e:
            logger.error(f"Failed to spawn pool: {e}")
            raise

    async def execute_on_pool(
        self,
        pool_id: str,
        task: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute task on specific pool.

        Args:
            pool_id: Target pool ID
            task: Task specification

        Returns:
            Execution result

        Raises:
            ValueError: If pool not found

        Example:
            ```python
            result = await pool_mgr.execute_on_pool(
                "pool_abc",
                {"prompt": "Write code", "timeout": 300}
            )
            ```
        """
        pool = self._pools.get(pool_id)
        if not pool:
            raise ValueError(f"Pool not found: {pool_id}")

        logger.info(f"Executing task on pool {pool_id}")

        result = await pool.execute_task(task)

        # Announce task completion
        await self.message_bus.publish({
            "type": "task_completed",
            "source_pool_id": pool_id,
            "payload": {
                "pool_id": pool_id,
                "result": result,
            },
        })

        return result

    async def route_task(
        self,
        task: dict[str, Any],
        pool_selector: PoolSelector | None = None,
        pool_affinity: str | None = None,
    ) -> dict[str, Any]:
        """Route task to best pool based on selector strategy.

        Args:
            task: Task specification
            pool_selector: Selection strategy (default: PoolManager default)
            pool_affinity: Specific pool ID if using AFFINITY strategy

        Returns:
            Execution result

        Raises:
            RuntimeError: If no pools available

        Example:
            ```python
            # Route to least loaded pool
            result = await pool_mgr.route_task(
                {"prompt": "Hello"},
                pool_selector=PoolSelector.LEAST_LOADED
            )

            # Route to specific pool (affinity)
            result = await pool_mgr.route_task(
                {"prompt": "Hello"},
                pool_selector=PoolSelector.AFFINITY,
                pool_affinity="pool_abc"
            )
            ```
        """
        if not self._pools:
            raise RuntimeError("No pools available for routing")

        selector = pool_selector or self._pool_selector

        # Select pool
        if selector == PoolSelector.AFFINITY:
            if not pool_affinity:
                raise ValueError("pool_affinity required for AFFINITY strategy")
            pool_id = pool_affinity
        elif selector == PoolSelector.LEAST_LOADED:
            # Find pool with fewest active workers
            pool_id = min(
                self._pools.keys(),
                key=lambda pid: len(self._pools[pid]._workers),
            )
            logger.debug(f"Least loaded pool: {pool_id}")
        elif selector == PoolSelector.ROUND_ROBIN:
            # Round-robin through pools
            pool_ids = list(self._pools.keys())
            pool_id = pool_ids[self._round_robin_index % len(pool_ids)]
            self._round_robin_index += 1
            logger.debug(f"Round-robin pool: {pool_id}")
        else:  # RANDOM
            import random
            pool_id = random.choice(list(self._pools.keys()))
            logger.debug(f"Random pool: {pool_id}")

        return await self.execute_on_pool(pool_id, task)

    async def aggregate_results(
        self,
        pool_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Aggregate results from multiple pools.

        Args:
            pool_ids: List of pool IDs (None = all pools)

        Returns:
            Dictionary mapping pool_id -> aggregated results

        Example:
            ```python
            # Aggregate results from all pools
            results = await pool_mgr.aggregate_results()

            # Aggregate from specific pools
            results = await pool_mgr.aggregate_results(
                pool_ids=["pool_abc", "pool_def"]
            )
            ```
        """
        if pool_ids is None:
            pool_ids = list(self._pools.keys())

        aggregated = {}

        for pool_id in pool_ids:
            pool = self._pools.get(pool_id)
            if pool:
                memory = await pool.collect_memory()
                aggregated[pool_id] = {
                    "memory_count": len(memory),
                    "status": (await pool.status()).value,
                }

        return aggregated

    async def close_pool(self, pool_id: str) -> None:
        """Close a specific pool.

        Args:
            pool_id: Pool ID to close

        Example:
            ```python
            await pool_mgr.close_pool("pool_abc")
            ```
        """
        pool = self._pools.get(pool_id)
        if pool:
            await pool.stop()
            del self._pools[pool_id]

            # Announce pool closure
            await self.message_bus.publish({
                "type": "pool_closed",
                "source_pool_id": pool_id,
                "payload": {"pool_id": pool_id},
            })

            logger.info(f"Pool {pool_id} closed")

    async def close_all(self) -> None:
        """Close all pools.

        Example:
            ```python
            await pool_mgr.close_all()
            ```
        """
        pool_ids = list(self._pools.keys())
        logger.info(f"Closing {len(pool_ids)} pools...")

        for pool_id in pool_ids:
            await self.close_pool(pool_id)

        logger.info("All pools closed")

    async def list_pools(self) -> list[dict[str, Any]]:
        """List all active pools.

        Returns:
            List of pool information dictionaries

        Example:
            ```python
            pools = await pool_mgr.list_pools()
            for pool in pools:
                print(f"{pool['pool_id']}: {pool['pool_type']} - {pool['status']}")
            ```
        """
        pools_info = []

        for pool_id, pool in self._pools.items():
            status = await pool.status()
            pools_info.append({
                "pool_id": pool_id,
                "pool_type": pool.config.pool_type,
                "name": pool.config.name,
                "status": status.value,
                "workers": len(pool._workers),
                "min_workers": pool.config.min_workers,
                "max_workers": pool.config.max_workers,
            })

        return pools_info

    async def health_check(self) -> dict[str, Any]:
        """Get health status of all pools.

        Returns:
            Health status dictionary

        Example:
            ```python
            health = await pool_mgr.health_check()
            print(f"Status: {health['status']}")
            print(f"Active pools: {health['pools_active']}")
            ```
        """
        pools_info = await self.list_pools()

        # Check if any pool is unhealthy
        unhealthy_pools = [p for p in pools_info if p["status"] in ("failed", "unhealthy")]

        overall_status = "healthy"
        if unhealthy_pools:
            overall_status = "degraded" if len(unhealthy_pools) < len(pools_info) else "unhealthy"

        return {
            "status": overall_status,
            "pools_active": len(self._pools),
            "pools": pools_info,
        }

    def set_pool_selector(self, selector: PoolSelector) -> None:
        """Set default pool selection strategy.

        Args:
            selector: Selection strategy

        Example:
            ```python
            pool_mgr.set_pool_selector(PoolSelector.LEAST_LOADED)
            ```
        """
        self._pool_selector = selector
        logger.info(f"Pool selector set to: {selector.value}")

    def get_message_bus_stats(self) -> dict[str, Any]:
        """Get message bus statistics.

        Returns:
            Message bus statistics
        """
        return self.message_bus.get_stats()
