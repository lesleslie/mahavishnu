"""Multi-pool orchestration and management."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, StrEnum
import heapq
import logging
import random
from typing import TYPE_CHECKING, Any, cast

from monitoring.metrics import pool_workers_active

from ..core.errors import RateLimitError
from ..mcp.protocols.message_bus import MessageBus
from .mahavishnu_pool import MahavishnuPool
from .peer_routing import DEFAULT_ACL_PROVIDER, PeerRouteResolver
from .routing_fitness import RoutingFitnessReader
from .runpod_pool import RunPodPool
from .session_buddy_pool import SessionBuddyPool

if TYPE_CHECKING:
    from .base import BasePool, PoolConfig

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
        PEER_AFFINITY: Route to the pool the peer's model recommends
            (Session-Buddy ``user_models`` ``pool: <id>`` hint). Falls
            back to LEAST_LOADED when the peer has no model row, no
            pool hint, or no ``peer_models:read`` ACL grant (A3:
            peer model is a hint, ACL is authoritative).
    """

    ROUND_ROBIN = "round_robin"
    LEAST_LOADED = "least_loaded"
    RANDOM = "random"
    AFFINITY = "affinity"
    PEER_AFFINITY = "peer_affinity"


class CallerKind(StrEnum):
    ULTRA_CODE = "ultracode"
    CLAUDE_CODE = "claude_code"
    WORKFLOW = "workflow"
    CLI = "cli"
    UNKNOWN = "unknown"  # Coerced target for any unrecognized value at the MCP wire boundary


def coerce_caller_kind(value: Any) -> CallerKind:
    """Coerce an arbitrary stringy caller-kind value to a canonical ``CallerKind``.

    Quota-bypass fix: any unrecognized string maps to
    ``CallerKind.UNKNOWN`` (not a fresh bucket) so callers cannot
    inflate quota by sending novel strings at the MCP wire
    boundary. ``None`` and ``CallerKind`` instances pass through
    unchanged (None -> UNKNOWN, CallerKind -> identity).
    """
    if isinstance(value, CallerKind):
        return value
    if value is None:
        return CallerKind.UNKNOWN
    try:
        return CallerKind(value)
    except ValueError:
        return CallerKind.UNKNOWN


@dataclass(slots=True)
class _QuotaState:
    """Per-caller_kind fixed-window quota state.

    Fixed window: counter resets at the boundary of each window_start +
    window_size_seconds period, not based on the time of the most recent
    request. Simpler and more predictable than a sliding window at the
    cost of burst-allowed-at-boundary behavior.

    Mutable counter state - do NOT make this Pydantic.

    Attributes:
        window_start: UTC datetime marking the start of the current
            fixed-window measurement period.
        request_count: Number of requests admitted in the current
            window (mutated in place by ``PoolManager._enforce_caller_quota``).
        window_size_seconds: Length of the fixed window in seconds.
        max_per_window: Maximum requests admitted per window.
    """

    window_start: datetime
    request_count: int = 0
    window_size_seconds: int = 60
    max_per_window: int = 60


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

        # Phase 1.5 Item 2: PEER_AFFINITY resolver. Lazily constructed
        # on first use so existing call sites that never use peer
        # affinity pay no Session-Buddy import cost. The resolver
        # is duck-typed on session_buddy_client; an explicit
        # ``_peer_resolver`` attribute (set by tests or by a future
        # initializer) wins over the lazy default.
        #
        # Security: when the manager is constructed with a
        # session_buddy_client and the resolver is auto-built with
        # the default (deny) ACL provider, that's a smell — the
        # operator probably forgot to pass an explicit ACL. The
        # runtime check below logs a warning so the misconfiguration
        # is visible in production. The deny default still applies
        # (secure-by-default); the warning is a nudge, not a fail.
        self._peer_resolver: PeerRouteResolver | None = None
        if session_buddy_client is not None:
            self._peer_resolver = PeerRouteResolver(
                session_buddy_client=session_buddy_client,
            )
            if self._peer_resolver._acl_provider is DEFAULT_ACL_PROVIDER:
                logger.warning(
                    "PoolManager constructed with session_buddy_client but no "
                    "explicit acl_provider — PEER_AFFINITY routing will be denied "
                    "for all peers. Pass an acl_provider to PeerRouteResolver "
                    "or to PoolManager (see ADR-014 / Item 2 in bodai-adoption-phase-1.5.md)."
                )

        # Track current worker counts for validation (lazy deletion)
        self._pool_worker_counts: dict[str, int] = {}

        # Thread-safe access to heap and worker counts
        self._heap_lock = asyncio.Lock()

        # Phase 3 Task 3.2: per-caller_kind fixed-window quota state.
        # Populated lazily on first request for each ``CallerKind`` to
        # avoid paying for buckets callers never touch. Defaults (60
        # requests per 60-second window) match the plan's recommended
        # baseline; T3.4 wires operator-configurable overrides from
        # ``settings/mahavishnu.yaml``.
        self._caller_quota: dict[CallerKind, _QuotaState] = {}

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
        caller_kind: CallerKind = CallerKind.UNKNOWN,
        parent_session_id: str | None = None,
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
                    "caller_kind": caller_kind.value,
                    "parent_session_id": parent_session_id,
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
            pool = self._pools.get(pool_id)
            if pool is not None:
                worker_counts.setdefault(pool.config.pool_type, 0)

        known_types = {"mahavishnu", "session-buddy", "runpod"} | set(worker_counts.keys())
        for pool_type in known_types:
            pool_workers_active.labels(pool_type=pool_type).set(worker_counts.get(pool_type, 0))

    async def spawn_pool(
        self,
        pool_type: str,
        config: PoolConfig,
    ) -> str:
        """Spawn a new pool of specified type.

        Args:
            pool_type: Type of pool ("mahavishnu", "session-buddy", "runpod")
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
                    session_buddy_url=config.get("session_buddy_url", "http://localhost:8678/mcp"),
                )
            elif pool_type == "runpod":
                pool = RunPodPool(config=config)
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

    async def _select_least_loaded_in_allowlist(
        self,
        allowlist: set[str],
    ) -> str | None:
        """Pick the least-loaded pool whose id is in ``allowlist``.

        Used when PEER_AFFINITY (or AFFINITY) falls back due to
        ADR-014 caller-side authorization: the allowlist is the
        security boundary, so the fallback candidate must come
        from inside the allowlist. Returns ``None`` when no
        registered pool is in the allowlist.

        The ``"*"`` wildcard in the allowlist is treated as
        "every currently-registered pool" — the result is the
        intersection of the allowlist with the live pool
        registry. The wildcard is a documented escape hatch for
        deployments that want to opt into PEER_AFFINITY for
        every pool.
        """
        if "*" in allowlist:
            candidates = list(self._pools.keys())
        else:
            candidates = [pid for pid in self._pools if pid in allowlist]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda pid: self._pool_worker_counts.get(pid, 0),
        )

    def _is_pool_in_allowlist(
        self,
        pool_id: str,
        allowlist: set[str],
    ) -> bool:
        """Test whether ``pool_id`` is authorized by ``allowlist``.

        Honors the ``"*"`` wildcard as "every currently-registered
        pool". A pool not in the live registry is NEVER
        authorized by the wildcard — the wildcard is a per-call
        gate against the current registry, not a blanket bypass.
        """
        if "*" in allowlist:
            return pool_id in self._pools
        return pool_id in allowlist

    async def execute_on_pool(
        self,
        pool_id: str,
        task: dict[str, Any],
        *,
        caller_kind: CallerKind | str = CallerKind.UNKNOWN,
        parent_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute task on specific pool.

        Args:
            pool_id: Target pool ID
            task: Task specification
            caller_kind: Caller identity for quota attribution. Coerced via
                :func:`coerce_caller_kind` so any unrecognized string maps
                to ``CallerKind.UNKNOWN`` (quota-bypass fix).
            parent_session_id: Optional session ID for cross-system correlation.

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
        # Quota enforcement is the first gate — same rule as route_task
        # so a caller cannot bypass it by switching from pool_route_execute
        # to pool_execute. Coercion happens here so any wire-string input
        # lands in the canonical bucket before _enforce_caller_quota runs.
        caller_kind = coerce_caller_kind(caller_kind)
        self._enforce_caller_quota(caller_kind)

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
        caller_pool_allowlist: set[str] | None = None,
        caller_kind: CallerKind | str = CallerKind.UNKNOWN,
        parent_session_id: str | None = None,
    ) -> dict[str, Any]:
        """Route task to best pool based on selector strategy.

        Args:
            task: Task specification
            pool_selector: Selection strategy (default: PoolManager default)
            pool_affinity: Specific pool ID if using AFFINITY strategy
            caller_pool_allowlist: Caller-side authorization contract
                (ADR-014). The set of pool IDs the CALLER is
                authorized to dispatch into. When ``None`` and the
                selector resolves to a specific pool (AFFINITY or
                PEER_AFFINITY), the router refuses to honor that
                specific-pool path and falls back to LEAST_LOADED —
                the caller has not declared which pools it may use.
                When a non-empty set is supplied, only pools in
                the intersection of the allowlist and the registered
                pools are valid candidates. When the intersection
                is empty, the router falls back to LEAST_LOADED
                within the allowlist (or raises if no allowlist
                pools are registered).
            caller_kind: Who is calling (used for quota + audit).
                Accepts a ``CallerKind`` enum or the underlying
                string value. Any unrecognized string is coerced to
                ``CallerKind.UNKNOWN`` so callers cannot inflate
                quota buckets by sending novel strings.
            parent_session_id: Optional Session-Buddy session ID
                that originated this routing request. Forwarded to
                ``_persist_routing_decision`` for audit trails.

        Returns:
            Execution result

        Raises:
            RuntimeError: If no pools available
            ValueError: If a required selector-specific argument is
                missing (e.g. ``pool_affinity`` for AFFINITY, or
                ``peer_id``/``project_id`` for PEER_AFFINITY)

        Example:
            ```python
            # ultracode call (declared kind, parent session for audit)
            result = await pool_mgr.route_task(
                {"prompt": "Refactor module"},
                caller_kind=CallerKind.ULTRA_CODE,
                parent_session_id="sb_session_xyz",
            )
            ```
        """
        if not self._pools:
            raise RuntimeError("No pools available for routing")

        caller_kind = coerce_caller_kind(caller_kind)

        # Phase 3 Task 3.2: per-caller_kind fixed-window quota. This
        # is the FIRST gate inside route_task — it must run before any
        # routing work so a saturated bucket short-circuits cheaply
        # rather than spending cycles on pool selection only to
        # reject the call later. ``RateLimitError`` propagates
        # through the MCP boundary as
        # ``{"status": "rate_limited", "retry_after_seconds": ...}``.
        self._enforce_caller_quota(caller_kind)

        logger.debug(
            "route_task: caller_kind=%s parent_session_id=%s",
            caller_kind,
            parent_session_id,
        )

        selector = pool_selector or self._pool_selector
        task_class = task.get("task_class") or task.get("category", "")
        selector = await self._apply_fitness_aware_routing(selector, task_class)

        if selector == PoolSelector.AFFINITY:
            pool_id, reason = await self._route_by_affinity(pool_affinity, caller_pool_allowlist)
        elif selector == PoolSelector.PEER_AFFINITY:
            pool_id, reason = await self._route_by_peer_affinity(task, caller_pool_allowlist)
        elif selector == PoolSelector.LEAST_LOADED:
            pool_id = await self._get_least_loaded_pool()
            if pool_id is None:
                raise RuntimeError("No pools available for routing")
            logger.debug(f"Least loaded pool: {pool_id}")
            reason = "least_loaded"
        elif selector == PoolSelector.ROUND_ROBIN:
            pool_ids = list(self._pools.keys())
            pool_id = pool_ids[self._round_robin_index % len(pool_ids)]
            self._round_robin_index += 1
            logger.debug(f"Round-robin pool: {pool_id}")
            reason = "round_robin"
        else:  # RANDOM
            pool_id = random.choice(list(self._pools.keys()))
            logger.debug(f"Random pool: {pool_id}")
            reason = "random"

        pool_id, reason = self._apply_gpu_category_override(pool_id, reason, task)
        await self._persist_routing_decision(
            task,
            pool_id,
            selector,
            pool_affinity,
            reason,
            caller_kind=caller_kind,
            parent_session_id=parent_session_id,
        )
        return await self.execute_on_pool(pool_id, task)

    async def _apply_fitness_aware_routing(
        self,
        selector: PoolSelector,
        task_class: str,
    ) -> PoolSelector:
        """Phase 4: override selector from Dhara fitness signals when available."""
        if not task_class:
            return selector
        try:
            signals = await self._routing_fitness_reader.get_fitness_signals(task_class)
            if signals:
                best = await self._routing_fitness_reader.get_best_selector(task_class)
                if best:
                    try:
                        override = PoolSelector(best)
                        logger.debug(
                            "Fitness-aware routing for task_class=%r: selector=%s (score=%.3f)",
                            task_class,
                            best,
                            signals[best].score,
                        )
                        return override
                    except ValueError:
                        pass  # Unknown selector string — keep current selector
        except Exception:
            pass  # Dhara unavailable — use selector as-is
        return selector

    async def _route_by_affinity(
        self,
        pool_affinity: str | None,
        caller_pool_allowlist: set[str] | None,
    ) -> tuple[str, str]:
        """ADR-014 caller-side authorization for AFFINITY selector."""
        if not pool_affinity:
            raise ValueError("pool_affinity required for AFFINITY strategy")
        if caller_pool_allowlist is None:
            logger.debug(
                "affinity_no_caller_allowlist: pool_affinity=%r — "
                "refusing to honor affinity, falling back to LEAST_LOADED",
                pool_affinity,
            )
            pool_id = await self._get_least_loaded_pool()
            if pool_id is None:
                raise RuntimeError("No pools available for routing")
            return pool_id, "affinity_no_caller_allowlist_fallback"
        if not self._is_pool_in_allowlist(pool_affinity, caller_pool_allowlist):
            logger.debug(
                "affinity_not_in_allowlist: pool_affinity=%r allowlist=%r — "
                "falling back to LEAST_LOADED within allowlist",
                pool_affinity,
                sorted(caller_pool_allowlist),
            )
            pool_id = await self._select_least_loaded_in_allowlist(caller_pool_allowlist)
            if pool_id is None:
                raise RuntimeError("No pools available for routing within caller_pool_allowlist")
            return pool_id, "affinity_allowlist_filtered_fallback"
        return pool_affinity, "affinity"

    async def _route_by_peer_affinity(
        self,
        task: dict[str, Any],
        caller_pool_allowlist: set[str] | None,
    ) -> tuple[str, str]:
        """ADR-014 caller-side authorization for PEER_AFFINITY selector.

        The peer model is a routing hint; the caller's declared allowlist is the gate.
        Falls back to LEAST_LOADED within the allowlist whenever the hint is absent,
        stale, or unauthorized.
        """
        peer_id = task.get("peer_id")
        project_id = task.get("project_id")
        if not peer_id or not project_id:
            raise ValueError(
                "PEER_AFFINITY selector requires task['peer_id'] and task['project_id'] to be set"
            )
        if self._peer_resolver is None:
            raise RuntimeError(
                "PEER_AFFINITY selector requires PoolManager to be "
                "constructed with session_buddy_client or a manually set _peer_resolver"
            )
        if caller_pool_allowlist is None:
            logger.debug(
                "peer_affinity_no_caller_allowlist: peer_id=%r project_id=%r — "
                "refusing to route via peer hint, falling back to LEAST_LOADED",
                peer_id,
                project_id,
            )
            pool_id = await self._get_least_loaded_pool()
            if pool_id is None:
                raise RuntimeError("No pools available for routing")
            return pool_id, "peer_affinity_no_caller_allowlist_fallback"

        resolved_pool_id = await self._peer_resolver.resolve_pool(
            peer_id=peer_id,
            project_id=project_id,
        )
        return await self._resolve_peer_affinity_pool(
            peer_id, resolved_pool_id, caller_pool_allowlist, project_id
        )

    async def _resolve_peer_affinity_pool(
        self,
        peer_id: str,
        resolved_pool_id: str | None,
        caller_pool_allowlist: set[str],
        project_id: str,
    ) -> tuple[str, str]:
        """Select final pool_id from a peer resolver result, applying allowlist + staleness checks."""
        if resolved_pool_id is None:
            logger.debug(
                "peer_affinity_no_hint: peer_id=%r project_id=%r — "
                "falling back to LEAST_LOADED within allowlist",
                peer_id,
                project_id,
            )
            pool_id = await self._select_least_loaded_in_allowlist(caller_pool_allowlist)
            if pool_id is None:
                raise RuntimeError("No pools available for routing within caller_pool_allowlist")
            return pool_id, "peer_affinity_fallback_least_loaded"
        if resolved_pool_id not in self._pools:
            # Normal during pool respawns — log and fall back rather than crash.
            logger.debug(
                "peer_affinity_pool_unknown: peer_id=%r recommended=%r "
                "— falling back to LEAST_LOADED within allowlist",
                peer_id,
                resolved_pool_id,
            )
            pool_id = await self._select_least_loaded_in_allowlist(caller_pool_allowlist)
            if pool_id is None:
                raise RuntimeError("No pools available for routing within caller_pool_allowlist")
            return pool_id, "peer_affinity_pool_unknown_fallback"
        if not self._is_pool_in_allowlist(resolved_pool_id, caller_pool_allowlist):
            # Allowlist is authoritative — discard the hint and fall back within it.
            logger.debug(
                "peer_affinity_hint_not_in_allowlist: peer_id=%r "
                "recommended=%r allowlist=%r — falling back to LEAST_LOADED within allowlist",
                peer_id,
                resolved_pool_id,
                sorted(caller_pool_allowlist),
            )
            pool_id = await self._select_least_loaded_in_allowlist(caller_pool_allowlist)
            if pool_id is None:
                raise RuntimeError("No pools available for routing within caller_pool_allowlist")
            return pool_id, "peer_affinity_allowlist_filtered_fallback"
        return resolved_pool_id, "peer_affinity"

    def _apply_gpu_category_override(
        self,
        pool_id: str,
        reason: str,
        task: dict[str, Any],
    ) -> tuple[str, str]:
        """Prefer a RunPod pool for GPU-bound task categories; no-op otherwise."""
        task_category = task.get("category", "")
        if task_category not in {"vision", "ml_inference", "embedding"}:
            return pool_id, reason
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
            return runpod_pool_id, "gpu_override"
        return pool_id, reason

    def _enforce_caller_quota(
        self,
        caller_kind: CallerKind,
        *,
        now: datetime | None = None,
    ) -> None:
        """Enforce the per-``CallerKind`` fixed-window quota.

        Fixed window: counter resets at the boundary of each
        ``window_start + window_size_seconds`` period, not based on the
        time of the most recent request. This is simpler and more
        predictable than a sliding window, at the cost of allowing bursts
        at window boundaries.

        Behavior:
            - Lazy-allocates a ``_QuotaState`` for unknown ``caller_kind``
              buckets on first request, anchored at ``now``.
            - Resets ``window_start`` and ``request_count`` when the
              current window has elapsed.
            - Raises the existing ``RateLimitError`` (MHV-006) from
              ``mahavishnu/core/errors.py`` when the bucket is saturated.
              The wait time is surfaced via
              ``exc.details["retry_after_seconds"]`` (computed as
              ``max(0, window_size_seconds - elapsed)``); MCP callers
              consume that value to back off. ``RateLimitError`` is the
              one canonical quota error per project convention — do not
              introduce a parallel exception class.

        Args:
            caller_kind: Bucket identifier (already coerced through
                ``coerce_caller_kind`` so unrecognized strings land in
                ``CallerKind.UNKNOWN`` rather than spawning novel buckets).
            now: Override for the current time. Defaults to
                ``datetime.now(UTC)``. Useful for tests that need to
                simulate window expiry deterministically.

        Raises:
            RateLimitError: When ``request_count >= max_per_window`` for
                ``caller_kind``. ``exc.details["limit"]`` carries
                ``"caller_kind=<kind>"`` and ``exc.details["retry_after_seconds"]``
                carries the seconds until the next window opens.
        """
        if now is None:
            now = datetime.now(UTC)
        state = self._caller_quota.get(caller_kind)
        if state is None:
            state = _QuotaState(window_start=now)
            self._caller_quota[caller_kind] = state

        elapsed = (now - state.window_start).total_seconds()
        if elapsed >= state.window_size_seconds:
            state.window_start = now
            state.request_count = 0

        if state.request_count >= state.max_per_window:
            retry_after = max(0, int(state.window_size_seconds - elapsed))
            logger.debug(
                "caller_quota_exceeded: caller_kind=%s request_count=%s "
                "max_per_window=%s retry_after_seconds=%s",
                caller_kind,
                state.request_count,
                state.max_per_window,
                retry_after,
            )
            raise RateLimitError(
                limit=f"caller_kind={caller_kind.value}",
                retry_after=retry_after,
            )

        state.request_count += 1

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

            pool_id, data = cast("tuple[str, dict[str, Any]]", result)
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
        return [cast("dict[str, Any]", p) for p in pools_info if not isinstance(p, Exception)]

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
