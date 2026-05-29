"""Multi-pool orchestration and management."""

import asyncio
from datetime import UTC, datetime
from enum import Enum
import heapq
import logging
import random
from typing import Any

from monitoring.metrics import pool_workers_active

from ..mcp.protocols.message_bus import MessageBus
from .base import BasePool, PoolConfig
from .kubernetes_pool import KubernetesPool
from .mahavishnu_pool import MahavishnuPool
from .routing_fitness import RoutingFitnessReader
from .runpod_pool import RunPodPool
from .session_buddy_pool import SessionBuddyPool

logger = logging.getLogger(__name__)


async def _await_if_needed(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


class PoolSelector(Enum):
    """Pool selection strategies.

    Attributes:
        ROUND_ROBIN: Distribute tasks evenly across pools
        LEAST_LOADED: Route to pool with fewest active workers (O(log n) heap-based)
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
    - Route tasks to appropriate pools (O(log n) least-loaded routing)
    - Handle inter-pool communication
    - Aggregate results across pools (concurrent collection)
    - Monitor pool health (concurrent status checks)

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
        event_publisher: Any = None,
        dhara_state: Any = None,
    ):
        """Initialize pool manager.

        Args:
            terminal_manager: TerminalManager for terminal control
            session_buddy_client: Optional Session-Buddy MCP client
            message_bus: Optional MessageBus for inter-pool communication
        """
        self.terminal_manager = terminal_manager
        self.session_buddy_client = session_buddy_client
        self.message_bus = message_bus or MessageBus(event_publisher=event_publisher)
        self._dhara_state = dhara_state

        self._pools: dict[str, BasePool] = {}
        self._pool_selector = PoolSelector.LEAST_LOADED
        self._round_robin_index = 0

        # O(log n) heap-based routing optimization
        # Heap stores tuples of (worker_count, pool_id) for efficient min lookup
        self._worker_count_heap: list[tuple[int, str]] = []

        # Phase 4: Routing fitness reader — reads signals from Dhara
        self._routing_fitness_reader = RoutingFitnessReader(dhara_state=dhara_state)

        # Track current worker counts for validation (lazy deletion)
        self._pool_worker_counts: dict[str, int] = {}

        # Thread-safe access to heap and worker counts
        self._heap_lock = asyncio.Lock()

        logger.info("PoolManager initialized with O(log n) heap routing and concurrent collection")

    async def _persist_pool_state(self, pool_id: str, pool: BasePool, status: str) -> None:
        if self._dhara_state is None:
            return
        try:
            await self._dhara_state.persist_pool(
                pool_id,
                {
                    "pool_id": pool_id,
                    "pool_type": pool.config.pool_type,
                    "name": pool.config.name,
                    "status": status,
                    "workers": len(pool._workers),
                    "min_workers": pool.config.min_workers,
                    "max_workers": pool.config.max_workers,
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception as exc:
            logger.debug("Failed to persist pool state for %s: %s", pool_id, exc)

    async def _persist_routing_decision(
        self,
        task: dict[str, Any],
        pool_id: str,
        selector: PoolSelector,
        pool_affinity: str | None,
        reason: str,
    ) -> None:
        if self._dhara_state is None:
            return
        try:
            task_class = str(task.get("category") or task.get("type") or "unknown")
            await self._dhara_state.persist_routing_decision(
                task_class,
                {
                    "task_class": task_class,
                    "task_type": task.get("type", "unknown"),
                    "pool_id": pool_id,
                    "selector": selector.value,
                    "pool_affinity": pool_affinity,
                    "reason": reason,
                    "task_category": task.get("category"),
                    "updated_at": datetime.now(UTC).isoformat(),
                },
                timestamp=datetime.now(UTC),
            )
        except Exception as exc:
            logger.debug("Failed to persist routing decision for %s: %s", pool_id, exc)

    def _refresh_pool_worker_metrics(self) -> None:
        """Recompute live worker counts per pool type for shared Prometheus metrics."""
        worker_counts: dict[str, int] = {}
        for pool in self._pools.values():
            pool_type = pool.config.pool_type
            worker_counts[pool_type] = worker_counts.get(pool_type, 0) + len(pool._workers)

        active_pool_types = set(self._pool_worker_counts.keys())
        for pool_id in active_pool_types:
            pool = self._pools.get(pool_id)  # type: ignore[assignment]
            if pool is not None:
                worker_counts.setdefault(pool.config.pool_type, 0)

        known_types = {"mahavishnu", "session-buddy", "kubernetes", "runpod"} | set(
            worker_counts.keys()
        )
        for pool_type in known_types:
            pool_workers_active.labels(pool_type=pool_type).set(worker_counts.get(pool_type, 0))

    async def spawn_pool(
        self,
        pool_type: str,
        config: PoolConfig,
    ) -> str:
        """Spawn a new pool of specified type.

        Args:
            pool_type: Type of pool ("mahavishnu", "session-buddy", "kubernetes", "runpod")
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
                pool = SessionBuddyPool(  # type: ignore[assignment]
                    config=config,
                    session_buddy_url=config.get("session_buddy_url", "http://localhost:8678/mcp"),
                )
            elif pool_type == "kubernetes":
                pool = KubernetesPool(  # type: ignore[assignment]
                    config=config,
                    namespace=config.get("namespace", "mahavishnu"),
                    kubeconfig_path=config.get("kubeconfig_path"),
                    container_image=config.get("container_image", "python:3.13-slim"),
                )
            elif pool_type == "runpod":
                pool = RunPodPool(config=config)  # type: ignore[assignment]
            else:
                raise ValueError(f"Unknown pool type: {pool_type}")

            # Start the pool
            pool_id = await pool.start()
            self._pools[pool_id] = pool

            # Initialize worker count and add to heap
            initial_count = config.min_workers
            self._pool_worker_counts[pool_id] = initial_count
            heapq.heappush(self._worker_count_heap, (initial_count, pool_id))
            await self._persist_pool_state(pool_id, pool, "running")

            # Announce pool creation via message bus
            await self.message_bus.publish(
                {
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
                }
            )

            logger.info(
                f"Pool {pool_id} spawned successfully (type: {pool_type}, "
                f"initial workers: {initial_count})"
            )
            self._refresh_pool_worker_metrics()

            return pool_id

        except Exception as e:
            logger.error(f"Failed to spawn pool: {e}")
            raise

    async def _update_pool_worker_count(self, pool_id: str, new_count: int) -> None:
        """Update pool's worker count in heap.

        Uses lazy deletion strategy: adds new entry to heap without removing old one.
        Old entries are skipped when encountered (stale count detection).

        Thread-safe via asyncio.Lock for concurrent access.

        Args:
            pool_id: Pool identifier
            new_count: New worker count
        """
        if pool_id not in self._pool_worker_counts:
            return

        async with self._heap_lock:
            self._pool_worker_counts[pool_id] = new_count
            heapq.heappush(self._worker_count_heap, (new_count, pool_id))

        # Note: Old (old_count, pool_id) entry still in heap
        # It will be skipped via stale count check in _get_least_loaded_pool()
        # This is lazy deletion - simpler and faster than explicit removal

    async def _get_least_loaded_pool(self) -> str | None:
        """Get least-loaded pool ID using heap (O(log n) amortized).

        Handles stale entries from lazy deletion by checking counts match.
        Thread-safe via asyncio.Lock for concurrent access.

        Returns:
            Pool ID with fewest workers, or None if no pools available
        """
        async with self._heap_lock:
            while self._worker_count_heap:
                worker_count, pool_id = self._worker_count_heap[0]

                # Check if entry is stale (lazy deletion)
                if pool_id not in self._pools:
                    # Pool was closed - remove stale entry
                    heapq.heappop(self._worker_count_heap)
                    continue

                # Check if count matches current tracked count
                current_count = self._pool_worker_counts.get(pool_id)
                if current_count is None or worker_count != current_count:
                    # Stale entry - pool was rescaled
                    heapq.heappop(self._worker_count_heap)
                    continue

                # Valid entry found - return pool_id without popping
                return pool_id

        if self._pools:
            return min(self._pools.items(), key=lambda item: len(item[1]._workers))[0]

        return None

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

        # Update worker count in heap if task changed it
        new_count = len(pool._workers)
        if pool_id in self._pool_worker_counts:
            old_count = self._pool_worker_counts[pool_id]
            if new_count != old_count:
                await self._update_pool_worker_count(pool_id, new_count)
        self._refresh_pool_worker_metrics()
        await self._persist_pool_state(pool_id, pool, "running")

        # Announce task completion
        await self.message_bus.publish(
            {
                "type": "task_completed",
                "source_pool_id": pool_id,
                "payload": {
                    "pool_id": pool_id,
                    "result": result,
                },
            }
        )

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
            # Route to least loaded pool (O(log n) heap-based)
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

        # Phase 4: Consult RoutingFitnessReader for fitness-aware routing.
        # If fitness signals exist for the task's class, override the selector
        # to use the highest-score selector; fall back to configured selector
        # (or least_loaded default) if Dhara is unavailable or no signals exist.
        task_class = task.get("task_class") or task.get("category", "")
        if task_class:
            try:
                signals = await self._routing_fitness_reader.get_fitness_signals(task_class)
                if signals:
                    best = await self._routing_fitness_reader.get_best_selector(task_class)
                    if best:
                        try:
                            selector = PoolSelector(best)
                            logger.debug(
                                "Fitness-aware routing for task_class=%r: selector=%s (score=%.3f)",
                                task_class,
                                best,
                                signals[best].score,
                            )
                        except ValueError:
                            pass  # Unknown selector string — keep current selector
            except Exception:
                pass  # Dhara unavailable — use selector as-is

        # Select pool
        if selector == PoolSelector.AFFINITY:
            if not pool_affinity:
                raise ValueError("pool_affinity required for AFFINITY strategy")
            pool_id = pool_affinity
            reason = "affinity"
        elif selector == PoolSelector.LEAST_LOADED:
            # O(log n) heap-based lookup (thread-safe)
            pool_id = await self._get_least_loaded_pool()  # type: ignore[assignment]
            if pool_id is None:
                raise RuntimeError("No pools available for routing")
            logger.debug(f"Least loaded pool: {pool_id}")
            reason = "least_loaded"
        elif selector == PoolSelector.ROUND_ROBIN:
            # Round-robin through pools
            pool_ids = list(self._pools.keys())
            pool_id = pool_ids[self._round_robin_index % len(pool_ids)]
            self._round_robin_index += 1
            logger.debug(f"Round-robin pool: {pool_id}")
            reason = "round_robin"
        else:  # RANDOM
            pool_id = random.choice(list(self._pools.keys()))
            logger.debug(f"Random pool: {pool_id}")
            reason = "random"

        # GPU category override: prefer a runpod pool for GPU-bound task categories.
        # Falls back to the already-selected pool when no runpod pool is available.
        task_category = task.get("category", "")
        if task_category in {"vision", "ml_inference", "embedding"}:
            runpod_pool_id = next(
                (pid for pid, p in self._pools.items() if p.config.pool_type == "runpod"),
                None,
            )
            if runpod_pool_id:
                logger.debug(
                    "GPU task category=%r — routing to runpod pool %s",
                    task_category,
                    runpod_pool_id,
                )
                pool_id = runpod_pool_id
                reason = "gpu_override"

        await self._persist_routing_decision(task, pool_id, selector, pool_affinity, reason)

        return await self.execute_on_pool(pool_id, task)

    async def aggregate_results(
        self,
        pool_ids: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Aggregate results from multiple pools concurrently.

        Uses asyncio.gather to collect from all pools in parallel (10x performance improvement).

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

        # Collect from all pools concurrently using asyncio.gather
        async def collect_from_pool(pool_id: str) -> tuple[str, dict[str, Any]]:
            """Collect memory and status from a single pool."""
            pool = self._pools.get(pool_id)
            if pool:
                memory = await _await_if_needed(pool.collect_memory())
                status = await _await_if_needed(pool.status())
                return pool_id, {
                    "memory_count": len(memory),
                    "status": status.value,
                }
            return pool_id, {"memory_count": 0, "status": "not_found"}

        # Execute all collection tasks concurrently (10x faster!)
        tasks = [collect_from_pool(pid) for pid in pool_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Reconstruct dictionary, handling errors
        aggregated = {}
        for result in results:
            if isinstance(result, Exception):
                # Log error but don't fail entire aggregation
                logger.warning(f"Pool aggregation failed: {result}")
                continue

            pool_id, data = result  # type: ignore[misc]
            aggregated[pool_id] = data

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
            await self._persist_pool_state(pool_id, pool, "closed")
            del self._pools[pool_id]

            # Remove from tracking structures
            if pool_id in self._pool_worker_counts:
                del self._pool_worker_counts[pool_id]
            # Note: Heap entry will be cleaned up lazily by _get_least_loaded_pool()

            # Announce pool closure
            await self.message_bus.publish(
                {
                    "type": "pool_closed",
                    "source_pool_id": pool_id,
                    "payload": {"pool_id": pool_id},
                }
            )

            logger.info(f"Pool {pool_id} closed")
            self._refresh_pool_worker_metrics()

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

        # Clear heap
        self._worker_count_heap.clear()
        self._pool_worker_counts.clear()
        self._refresh_pool_worker_metrics()

        logger.info("All pools closed")

    async def list_pools(self) -> list[dict[str, Any]]:
        """List all active pools with concurrent status collection.

        Uses asyncio.gather to check all pool statuses in parallel (10x performance improvement).

        Returns:
            List of pool information dictionaries

        Example:
            ```python
            pools = await pool_mgr.list_pools()
            for pool in pools:
                logger.info(f"{pool['pool_id']}: {pool['pool_type']} - {pool['status']}")
            ```
        """

        # Collect pool information concurrently (10x performance improvement!)
        async def get_pool_info(pool_id: str, pool: BasePool) -> dict[str, Any]:
            """Get information for a single pool."""
            status = await pool.status()
            return {
                "pool_id": pool_id,
                "pool_type": pool.config.pool_type,
                "name": pool.config.name,
                "status": status.value,
                "workers": len(pool._workers),
                "min_workers": pool.config.min_workers,
                "max_workers": pool.config.max_workers,
            }

        # Execute all status checks concurrently
        tasks = [get_pool_info(pool_id, pool) for pool_id, pool in self._pools.items()]
        pools_info = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and return valid results
        return [p for p in pools_info if not isinstance(p, Exception)]  # type: ignore[misc]

    async def health_check(self) -> dict[str, Any]:
        """Get health status of all pools.

        Returns:
            Health status dictionary

        Example:
            ```python
            health = await pool_mgr.health_check()
            logger.info(f"Status: {health['status']}")
            logger.info(f"Active pools: {health['pools_active']}")
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
