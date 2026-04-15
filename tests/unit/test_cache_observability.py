"""Regression tests for cache hit/miss observability across all cache implementations.

Covers:
- ResolutionCache (mahavishnu.core.task_requirements)
- AdapterDiscoveryEngine (mahavishnu.core.adapter_discovery)
- CrossRepoBlockerTracker (mahavishnu.core.cross_repo_blocker)
- aggregate_cache_health (mahavishnu.core.cache_manager)
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import time
from typing import Any
from unittest.mock import MagicMock

from mahavishnu.core.cache_manager import aggregate_cache_health
from mahavishnu.core.task_requirements import ResolutionCache, RoutingDecision

# ---------------------------------------------------------------------------
# ResolutionCache tests
# ---------------------------------------------------------------------------


class TestResolutionCacheStats:
    """Hit/miss counters and stats for ResolutionCache."""

    def test_miss_increments_on_empty_get(self) -> None:
        cache = ResolutionCache(ttl_seconds=60)
        assert cache.get("nonexistent") is None
        stats = cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0
        assert stats["hit_rate"] == 0.0

    def test_hit_increments_on_cached_get(self) -> None:
        cache = ResolutionCache(ttl_seconds=60)
        decision = RoutingDecision(
            adapter_name="test",
            adapter=MagicMock(),
            matched_capabilities=["a"],
            resolution_time_ms=1.0,
        )
        cache.set("k1", decision)
        result = cache.get("k1")
        assert result is decision
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 1.0

    def test_ttl_expiry_counts_as_miss(self) -> None:
        cache = ResolutionCache(ttl_seconds=0)  # instant expiry
        decision = RoutingDecision(
            adapter_name="test",
            adapter=MagicMock(),
            matched_capabilities=["a"],
            resolution_time_ms=1.0,
        )
        cache.set("k1", decision)
        time.sleep(0.01)
        assert cache.get("k1") is None
        stats = cache.get_stats()
        assert stats["misses"] >= 1

    def test_reset_stats_clears_counters(self) -> None:
        cache = ResolutionCache(ttl_seconds=60)
        cache.get("miss")
        cache.reset_stats()
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    def test_stats_includes_all_fields(self) -> None:
        cache = ResolutionCache(ttl_seconds=300)
        stats = cache.get_stats()
        for key in ("size", "ttl_seconds", "hits", "misses", "hit_rate"):
            assert key in stats, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# AdapterDiscoveryEngine cache stats tests
# ---------------------------------------------------------------------------


class TestAdapterDiscoveryCacheStats:
    """Hit/miss counters for AdapterDiscoveryEngine.get_cache_stats()."""

    def test_initial_stats(self) -> None:
        from mahavishnu.core.adapter_discovery import AdapterDiscoveryEngine

        engine = AdapterDiscoveryEngine(
            config={"enable_entry_points": False, "enable_oneiric_mcp": False}
        )
        stats = engine.get_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0
        assert "ttl_seconds" in stats

    def test_miss_recorded_on_discover(self) -> None:
        from mahavishnu.core.adapter_discovery import AdapterDiscoveryEngine

        engine = AdapterDiscoveryEngine(
            config={"enable_entry_points": False, "enable_oneiric_mcp": False}
        )

        # discover_all with no sources returns empty list; counts as miss
        result = asyncio.run(engine.discover_all())
        assert result == []
        stats = engine.get_cache_stats()
        assert stats["misses"] == 1

    def test_hit_recorded_on_cached_discover(self) -> None:
        from mahavishnu.core.adapter_discovery import AdapterDiscoveryEngine

        engine = AdapterDiscoveryEngine(
            config={"enable_entry_points": False, "enable_oneiric_mcp": False}
        )

        asyncio.run(engine.discover_all())  # miss
        asyncio.run(engine.discover_all())  # hit
        stats = engine.get_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_invalidate_clears_entries(self) -> None:
        from mahavishnu.core.adapter_discovery import AdapterDiscoveryEngine

        engine = AdapterDiscoveryEngine(
            config={"enable_entry_points": False, "enable_oneiric_mcp": False}
        )

        asyncio.run(engine.discover_all())
        engine.invalidate_cache()
        stats = engine.get_cache_stats()
        assert stats["entries"] == 0


# ---------------------------------------------------------------------------
# CrossRepoBlockerTracker cache stats tests
# ---------------------------------------------------------------------------


class TestCrossRepoBlockerCacheStats:
    """Hit/miss counters for CrossRepoBlockerTracker caches."""

    def _make_tracker(self) -> tuple[Any, MagicMock]:
        from mahavishnu.core.cross_repo_blocker import CrossRepoBlockerTracker

        linker = MagicMock()
        return CrossRepoBlockerTracker(linker), linker

    def test_initial_stats(self) -> None:
        tracker, _ = self._make_tracker()
        stats = tracker.get_stats()
        assert "chain_cache" in stats
        assert "blocker_cache" in stats
        assert stats["chain_cache"]["hits"] == 0
        assert stats["chain_cache"]["misses"] == 0
        assert stats["blocker_cache"]["hits"] == 0

    def test_chain_cache_miss_on_empty(self) -> None:
        tracker, linker = self._make_tracker()
        linker.get_blocking_chain.return_value = []
        tracker.get_blocking_chain("t1")
        stats = tracker.get_stats()
        assert stats["chain_cache"]["misses"] == 1

    def test_chain_cache_hit_on_second_call(self) -> None:
        tracker, linker = self._make_tracker()
        from mahavishnu.core.cross_repo_dependency import (
            CrossRepoDependency,
            DependencyType,
        )

        dep = CrossRepoDependency(
            id="d1",
            source_task_id="t0",
            source_repo="r0",
            target_task_id="t1",
            target_repo="r1",
            dependency_type=DependencyType.BLOCKS,
        )
        linker.get_blocking_chain.return_value = [dep]

        tracker.get_blocking_chain("t1")  # miss + populate
        tracker.get_blocking_chain("t1")  # hit
        stats = tracker.get_stats()
        assert stats["chain_cache"]["hits"] == 1
        assert stats["chain_cache"]["misses"] == 1

    def test_blocker_cache_hit_on_second_call(self) -> None:
        tracker, linker = self._make_tracker()
        from mahavishnu.core.cross_repo_dependency import (
            CrossRepoDependency,
            DependencyType,
        )

        dep = CrossRepoDependency(
            id="d1",
            source_task_id="t0",
            source_repo="r0",
            target_task_id="t1",
            target_repo="r1",
            dependency_type=DependencyType.BLOCKS,
        )
        linker.get_blocked_tasks.return_value = [dep]
        linker.get_blocking_chain.return_value = [dep]

        tracker.get_blocker_impact("t0")  # miss
        tracker.get_blocker_impact("t0")  # hit
        stats = tracker.get_stats()
        assert stats["blocker_cache"]["hits"] == 1
        assert stats["blocker_cache"]["misses"] == 1

    def test_ttl_expiry_counts_as_miss(self) -> None:
        tracker, linker = self._make_tracker()
        from mahavishnu.core.cross_repo_dependency import (
            CrossRepoDependency,
            DependencyType,
        )

        dep = CrossRepoDependency(
            id="d1",
            source_task_id="t0",
            source_repo="r0",
            target_task_id="t1",
            target_repo="r1",
            dependency_type=DependencyType.BLOCKS,
        )
        linker.get_blocking_chain.return_value = [dep]

        # Set TTL to 0 for instant expiry
        tracker._cache_ttl = timedelta(seconds=0)

        tracker.get_blocking_chain("t1")  # miss + populate
        time.sleep(0.01)
        tracker.get_blocking_chain("t1")  # expired -> miss
        stats = tracker.get_stats()
        assert stats["chain_cache"]["misses"] == 2
        assert stats["chain_cache"]["hits"] == 0

    def test_reset_stats_clears_counters(self) -> None:
        tracker, linker = self._make_tracker()
        linker.get_blocking_chain.return_value = []
        tracker.get_blocking_chain("t1")
        tracker.reset_stats()
        stats = tracker.get_stats()
        assert stats["chain_cache"]["hits"] == 0
        assert stats["chain_cache"]["misses"] == 0

    def test_stats_includes_hit_rate(self) -> None:
        tracker, _ = self._make_tracker()
        stats = tracker.get_stats()
        assert "hit_rate" in stats["chain_cache"]
        assert "hit_rate" in stats["blocker_cache"]


# ---------------------------------------------------------------------------
# aggregate_cache_health tests
# ---------------------------------------------------------------------------


class TestAggregateCacheHealth:
    """Tests for the aggregate_cache_health function."""

    def test_empty_input(self) -> None:
        result = aggregate_cache_health({})
        assert result["summary"]["total_hits"] == 0
        assert result["summary"]["total_misses"] == 0
        assert result["summary"]["hit_rate"] == 0.0

    def test_single_cache_dict(self) -> None:
        cache = MagicMock()
        cache.get_stats.return_value = {"hits": 5, "misses": 3, "hit_rate": 5 / 8}
        result = aggregate_cache_health({"rc": cache})
        assert result["caches"]["rc"]["hits"] == 5
        assert result["summary"]["total_hits"] == 5
        assert result["summary"]["total_misses"] == 3

    def test_multiple_caches(self) -> None:
        c1 = MagicMock()
        c1.get_stats.return_value = {"hits": 10, "misses": 2, "hit_rate": 10 / 12}
        c2 = MagicMock()
        c2.get_stats.return_value = {"hits": 4, "misses": 6, "hit_rate": 4 / 10}
        result = aggregate_cache_health({"a": c1, "b": c2})
        assert result["summary"]["total_hits"] == 14
        assert result["summary"]["total_misses"] == 8
        assert result["summary"]["hit_rate"] == 14 / 22

    def test_dataclass_stats_handled(self) -> None:
        """CacheStats dataclass (from CacheManager) has to_dict()."""
        from mahavishnu.core.cache_manager import CacheStats

        stats = CacheStats(hits=3, misses=1)
        cache = MagicMock()
        cache.get_stats.return_value = stats

        result = aggregate_cache_health({"cm": cache})
        assert result["caches"]["cm"]["hits"] == 3
        assert result["summary"]["total_hits"] == 3
