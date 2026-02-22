"""Task requirements and routing decisions for capability-based routing.

This module defines data structures for Phase 2 of the routing plan,
enabling intelligent capability-based task routing across adapters.

Architecture:
    TaskRequirements --> ResolutionCache --> RoutingDecision
           |                  |                   |
           v                  v                   v
    TaskType mapping    TTL-based caching    Adapter selection
                                               with explanation
"""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time
from typing import Any

from mahavishnu.core.task_router import TaskType


@dataclass
class TaskRequirements:
    """Requirements for task routing and execution.

    Defines what a task needs from an adapter, including mandatory
    capabilities, preferred capabilities, budget constraints, and
    latency requirements.

    Attributes:
        task_type: Type of task (workflow, AI task, RAG query)
        required_capabilities: Capabilities that MUST be present (ALL required)
        preferred_capabilities: Nice-to-have capabilities that improve selection
        budget_constraints: Cost limits (e.g., {"max_cost_usd": 0.10})
        latency_sla_ms: Maximum acceptable latency in milliseconds
        fallback_enabled: Whether to allow fallback to other adapters
    """

    task_type: str
    required_capabilities: list[str]
    preferred_capabilities: list[str] = field(default_factory=list[str])
    budget_constraints: dict[str, float] | None = None
    latency_sla_ms: int | None = None
    fallback_enabled: bool = True

    def __post_init__(self) -> None:
        """Validate requirements after initialization."""
        if not self.task_type:
            raise ValueError("task_type cannot be empty")
        if not self.required_capabilities:
            raise ValueError("required_capabilities cannot be empty")

    def to_cache_key(self) -> str:
        """Generate a cache key for this set of requirements.

        Returns:
            String key suitable for cache lookup
        """
        # Sort capabilities for consistent keys
        required = ",".join(sorted(self.required_capabilities))
        preferred = ",".join(sorted(self.preferred_capabilities))
        budget = ""
        if self.budget_constraints:
            budget = ",".join(f"{k}={v}" for k, v in sorted(self.budget_constraints.items()))

        return f"{self.task_type}|{required}|{preferred}|{budget}|{self.latency_sla_ms}|{self.fallback_enabled}"

    def matches_capabilities(self, available: set[str]) -> bool:
        """Check if available capabilities satisfy all required capabilities.

        Args:
            available: Set of capabilities an adapter provides

        Returns:
            True if all required capabilities are available
        """
        required_set = set(self.required_capabilities)
        return required_set.issubset(available)

    def count_preferred_matches(self, available: set[str]) -> int:
        """Count how many preferred capabilities are available.

        Args:
            available: Set of capabilities an adapter provides

        Returns:
            Number of preferred capabilities that match
        """
        preferred_set = set(self.preferred_capabilities)
        return len(preferred_set.intersection(available))


@dataclass
class RoutingDecision:
    """Result of a routing decision for a task.

    Captures which adapter was selected, why it was chosen, and
    metadata about the resolution process.

    Attributes:
        adapter_name: Name of the selected adapter
        adapter: Instance of the selected OrchestratorAdapter
        matched_capabilities: List of capabilities that matched requirements
        resolution_time_ms: Time taken to make the routing decision
        fallback_used: Whether this decision used a fallback adapter
        explanation: Human-readable explanation of why this adapter was chosen
    """

    adapter_name: str
    adapter: Any  # OrchestratorAdapter instance
    matched_capabilities: list[str]
    resolution_time_ms: float
    fallback_used: bool = False
    explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert routing decision to dictionary for serialization.

        Returns:
            Dictionary representation (excludes adapter instance)
        """
        return {
            "adapter_name": self.adapter_name,
            "matched_capabilities": self.matched_capabilities,
            "resolution_time_ms": self.resolution_time_ms,
            "fallback_used": self.fallback_used,
            "explanation": self.explanation,
        }


# Mapping of task types to their required capabilities
TASK_CAPABILITY_REQUIREMENTS: dict[TaskType, list[str]] = {
    TaskType.WORKFLOW: ["deploy_flows", "monitor_execution"],
    TaskType.AI_TASK: ["multi_agent", "tool_use"],
    TaskType.RAG_QUERY: ["rag", "vector_search"],
}


class ResolutionCache:
    """Thread-safe cache for routing decisions with TTL support.

    Caches RoutingDecision objects to avoid repeated resolution for
    identical task requirements. Automatically expires entries after
    the configured TTL.

    Thread Safety:
        Uses RLock for thread-safe operations on the cache.

    Attributes:
        ttl_seconds: Time-to-live for cached entries in seconds

    Example:
        >>> cache = ResolutionCache(ttl_seconds=300)
        >>> decision = RoutingDecision(...)
        >>> cache.set("task_key", decision)
        >>> cached = cache.get("task_key")
        >>> assert cached == decision
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        """Initialize the resolution cache.

        Args:
            ttl_seconds: Time-to-live for cached entries (default: 5 minutes)
        """
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[RoutingDecision, float]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> RoutingDecision | None:
        """Get a cached routing decision if not expired.

        Args:
            key: Cache key (typically from TaskRequirements.to_cache_key())

        Returns:
            Cached RoutingDecision if valid, None if not found or expired
        """
        with self._lock:
            self._cleanup_expired()

            entry = self._cache.get(key)
            if entry is None:
                return None

            decision, timestamp = entry
            current_time = time.time()

            if current_time - timestamp > self._ttl_seconds:
                # Entry expired, remove it
                del self._cache[key]
                return None

            return decision

    def set(self, key: str, decision: RoutingDecision) -> None:
        """Cache a routing decision.

        Args:
            key: Cache key (typically from TaskRequirements.to_cache_key())
            decision: RoutingDecision to cache
        """
        with self._lock:
            self._cache[key] = (decision, time.time())

    def invalidate(self, key: str | None = None) -> None:
        """Invalidate cached entries.

        Args:
            key: Specific key to invalidate, or None to clear all entries
        """
        with self._lock:
            if key is None:
                self._cache.clear()
            elif key in self._cache:
                del self._cache[key]

    def _cleanup_expired(self) -> None:
        """Remove expired entries from the cache.

        Called internally during get operations to maintain cache hygiene.
        Must be called while holding the lock.
        """
        current_time = time.time()
        expired_keys = [
            key
            for key, (_, timestamp) in self._cache.items()
            if current_time - timestamp > self._ttl_seconds
        ]

        for key in expired_keys:
            del self._cache[key]

    @property
    def size(self) -> int:
        """Get the current number of cached entries.

        Returns:
            Number of entries in the cache (including expired)
        """
        with self._lock:
            return len(self._cache)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache size, TTL, and entry ages
        """
        with self._lock:
            self._cleanup_expired()
            current_time = time.time()

            ages = [current_time - timestamp for _, timestamp in self._cache.values()]

            return {
                "size": len(self._cache),
                "ttl_seconds": self._ttl_seconds,
                "oldest_entry_age_seconds": max(ages) if ages else 0,
                "newest_entry_age_seconds": min(ages) if ages else 0,
            }


__all__ = [
    "TaskRequirements",
    "RoutingDecision",
    "TASK_CAPABILITY_REQUIREMENTS",
    "ResolutionCache",
]
