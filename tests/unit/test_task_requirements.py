"""Tests for task requirements and routing decisions.

Tests cover:
- TaskRequirements creation, validation, capability matching
- TaskRequirements cache key generation
- RoutingDecision creation, to_dict
- ResolutionCache operations (get/set/invalidate/TTL/stats)
"""

import threading
import time

import pytest

from mahavishnu.core.task_requirements import (
    TASK_CAPABILITY_REQUIREMENTS,
    ResolutionCache,
    RoutingDecision,
    TaskRequirements,
)

# ============================================================================
# TaskRequirements Tests
# ============================================================================


class TestTaskRequirementsCreation:
    """Test TaskRequirements creation and validation."""

    def test_basic_creation(self):
        req = TaskRequirements(
            task_type="workflow",
            required_capabilities=["deploy_flows"],
        )
        assert req.task_type == "workflow"
        assert req.required_capabilities == ["deploy_flows"]
        assert req.preferred_capabilities == []
        assert req.budget_constraints is None
        assert req.latency_sla_ms is None
        assert req.fallback_enabled is True

    def test_full_creation(self):
        req = TaskRequirements(
            task_type="ai_task",
            required_capabilities=["multi_agent", "tool_use"],
            preferred_capabilities=["streaming", "memory"],
            budget_constraints={"max_cost_usd": 0.50},
            latency_sla_ms=5000,
            fallback_enabled=False,
        )
        assert req.task_type == "ai_task"
        assert len(req.required_capabilities) == 2
        assert len(req.preferred_capabilities) == 2
        assert req.budget_constraints["max_cost_usd"] == 0.50
        assert req.latency_sla_ms == 5000
        assert req.fallback_enabled is False

    def test_empty_task_type_raises(self):
        with pytest.raises(ValueError, match="task_type cannot be empty"):
            TaskRequirements(task_type="", required_capabilities=["cap"])

    def test_empty_required_capabilities_raises(self):
        with pytest.raises(ValueError, match="required_capabilities cannot be empty"):
            TaskRequirements(task_type="workflow", required_capabilities=[])

    def test_default_preferred_capabilities(self):
        req = TaskRequirements(task_type="test", required_capabilities=["a"])
        assert req.preferred_capabilities == []


class TestTaskRequirementsCacheKey:
    """Test cache key generation."""

    def test_deterministic_key(self):
        req1 = TaskRequirements(task_type="test", required_capabilities=["a", "b"])
        req2 = TaskRequirements(task_type="test", required_capabilities=["b", "a"])
        assert req1.to_cache_key() == req2.to_cache_key()

    def test_different_types_different_keys(self):
        req1 = TaskRequirements(task_type="workflow", required_capabilities=["a"])
        req2 = TaskRequirements(task_type="ai_task", required_capabilities=["a"])
        assert req1.to_cache_key() != req2.to_cache_key()

    def test_different_capabilities_different_keys(self):
        req1 = TaskRequirements(task_type="test", required_capabilities=["a"])
        req2 = TaskRequirements(task_type="test", required_capabilities=["b"])
        assert req1.to_cache_key() != req2.to_cache_key()

    def test_budget_included_in_key(self):
        req1 = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            budget_constraints={"max_cost_usd": 1.0},
        )
        req2 = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
        )
        assert req1.to_cache_key() != req2.to_cache_key()

    def test_latency_included_in_key(self):
        req1 = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            latency_sla_ms=100,
        )
        req2 = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            latency_sla_ms=200,
        )
        assert req1.to_cache_key() != req2.to_cache_key()

    def test_fallback_included_in_key(self):
        req1 = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            fallback_enabled=True,
        )
        req2 = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            fallback_enabled=False,
        )
        assert req1.to_cache_key() != req2.to_cache_key()

    def test_preferred_capabilities_included(self):
        req1 = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            preferred_capabilities=["x"],
        )
        req2 = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            preferred_capabilities=["y"],
        )
        assert req1.to_cache_key() != req2.to_cache_key()


class TestTaskRequirementsCapabilityMatching:
    """Test capability matching methods."""

    def test_matches_all_required(self):
        req = TaskRequirements(
            task_type="test",
            required_capabilities=["deploy", "monitor"],
        )
        assert req.matches_capabilities({"deploy", "monitor", "scale"}) is True

    def test_missing_one_required(self):
        req = TaskRequirements(
            task_type="test",
            required_capabilities=["deploy", "monitor"],
        )
        assert req.matches_capabilities({"deploy", "scale"}) is False

    def test_empty_available_fails(self):
        req = TaskRequirements(
            task_type="test",
            required_capabilities=["deploy"],
        )
        assert req.matches_capabilities(set()) is False

    def test_exact_match(self):
        req = TaskRequirements(
            task_type="test",
            required_capabilities=["a", "b"],
        )
        assert req.matches_capabilities({"a", "b"}) is True

    def test_count_preferred_matches_all(self):
        req = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            preferred_capabilities=["x", "y", "z"],
        )
        assert req.count_preferred_matches({"x", "y", "z"}) == 3

    def test_count_preferred_matches_partial(self):
        req = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            preferred_capabilities=["x", "y", "z"],
        )
        assert req.count_preferred_matches({"x", "w"}) == 1

    def test_count_preferred_matches_none(self):
        req = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
            preferred_capabilities=["x", "y"],
        )
        assert req.count_preferred_matches({"w", "q"}) == 0

    def test_count_preferred_matches_empty_preferred(self):
        req = TaskRequirements(
            task_type="test",
            required_capabilities=["a"],
        )
        assert req.count_preferred_matches({"x", "y"}) == 0


class TestTaskCapabilityRequirements:
    """Test TASK_CAPABILITY_REQUIREMENTS mapping."""

    def test_workflow_has_requirements(self):
        assert "WORKFLOW" in TASK_CAPABILITY_REQUIREMENTS or any(
            t.value == "workflow" for t in TASK_CAPABILITY_REQUIREMENTS
        )

    def test_ai_task_has_requirements(self):
        assert any(
            "multi_agent" in caps or "tool_use" in caps
            for caps in TASK_CAPABILITY_REQUIREMENTS.values()
        )

    def test_rag_query_has_requirements(self):
        assert any(
            "rag" in caps or "vector_search" in caps
            for caps in TASK_CAPABILITY_REQUIREMENTS.values()
        )


# ============================================================================
# RoutingDecision Tests
# ============================================================================


class TestRoutingDecision:
    """Test RoutingDecision dataclass."""

    def test_creation(self):
        decision = RoutingDecision(
            adapter_name="prefect",
            adapter=None,  # In real use, this would be an adapter instance
            matched_capabilities=["deploy_flows"],
            resolution_time_ms=42.5,
        )
        assert decision.adapter_name == "prefect"
        assert decision.matched_capabilities == ["deploy_flows"]
        assert decision.resolution_time_ms == 42.5
        assert decision.fallback_used is False
        assert decision.explanation is None

    def test_with_all_fields(self):
        decision = RoutingDecision(
            adapter_name="agno",
            adapter="mock_adapter",
            matched_capabilities=["multi_agent"],
            resolution_time_ms=15.0,
            fallback_used=True,
            explanation="Best match for AI tasks",
        )
        assert decision.fallback_used is True
        assert decision.explanation == "Best match for AI tasks"

    def test_to_dict(self):
        decision = RoutingDecision(
            adapter_name="prefect",
            adapter="adapter_instance",  # Should be excluded from dict
            matched_capabilities=["deploy"],
            resolution_time_ms=10.0,
            fallback_used=False,
            explanation="Test",
        )
        d = decision.to_dict()
        assert d["adapter_name"] == "prefect"
        assert d["matched_capabilities"] == ["deploy"]
        assert d["resolution_time_ms"] == 10.0
        assert d["fallback_used"] is False
        assert d["explanation"] == "Test"
        assert "adapter" not in d  # Adapter instance excluded


# ============================================================================
# ResolutionCache Tests
# ============================================================================


class TestResolutionCache:
    """Test ResolutionCache."""

    def test_creation_defaults(self):
        cache = ResolutionCache()
        assert cache.size == 0
        assert cache._ttl_seconds == 300

    def test_creation_custom_ttl(self):
        cache = ResolutionCache(ttl_seconds=60)
        assert cache._ttl_seconds == 60

    def test_set_and_get(self):
        cache = ResolutionCache()
        decision = RoutingDecision(
            adapter_name="test",
            adapter=None,
            matched_capabilities=["a"],
            resolution_time_ms=5.0,
        )
        cache.set("key1", decision)
        result = cache.get("key1")
        assert result is not None
        assert result.adapter_name == "test"

    def test_get_missing_key(self):
        cache = ResolutionCache()
        result = cache.get("nonexistent")
        assert result is None

    def test_size_tracks_entries(self):
        cache = ResolutionCache()
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        assert cache.size == 0
        cache.set("k1", decision)
        assert cache.size == 1
        cache.set("k2", decision)
        assert cache.size == 2

    def test_invalidate_specific_key(self):
        cache = ResolutionCache()
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        cache.set("k1", decision)
        cache.set("k2", decision)
        cache.invalidate("k1")
        assert cache.get("k1") is None
        assert cache.get("k2") is not None

    def test_invalidate_all(self):
        cache = ResolutionCache()
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        cache.set("k1", decision)
        cache.set("k2", decision)
        cache.invalidate()  # None = clear all
        assert cache.size == 0

    def test_ttl_expiration(self):
        cache = ResolutionCache(ttl_seconds=1)
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        cache.set("key1", decision)
        assert cache.get("key1") is not None
        time.sleep(1.5)
        assert cache.get("key1") is None

    def test_get_expired_entry_removes_stale_value(self, monkeypatch):
        cache = ResolutionCache(ttl_seconds=5)
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )

        times = iter([100.0, 104.0, 106.0])
        monkeypatch.setattr("mahavishnu.core.task_requirements.time.time", lambda: next(times))

        cache.set("key1", decision)
        assert cache.get("key1") is None
        assert cache.size == 0

    def test_overwrite_existing_key(self):
        cache = ResolutionCache()
        d1 = RoutingDecision(
            adapter_name="first",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        d2 = RoutingDecision(
            adapter_name="second",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=2.0,
        )
        cache.set("key1", d1)
        cache.set("key1", d2)
        result = cache.get("key1")
        assert result.adapter_name == "second"

    def test_hit_miss_stats(self):
        cache = ResolutionCache()
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        cache.set("k1", decision)
        cache.get("k1")  # hit
        cache.get("k1")  # hit
        cache.get("missing")  # miss
        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1

    def test_hit_rate_calculation(self):
        cache = ResolutionCache()
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        cache.set("k1", decision)
        cache.get("k1")  # hit
        cache.get("k1")  # hit
        cache.get("missing")  # miss
        cache.get("missing")  # miss
        stats = cache.get_stats()
        assert stats["hit_rate"] == 0.5

    def test_hit_rate_zero_when_no_access(self):
        cache = ResolutionCache()
        stats = cache.get_stats()
        assert stats["hit_rate"] == 0.0

    def test_reset_stats(self):
        cache = ResolutionCache()
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        cache.set("k1", decision)
        cache.get("k1")
        cache.get("missing")
        cache.reset_stats()
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0

    def test_thread_safety(self):
        """Cache should be thread-safe."""
        cache = ResolutionCache()
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        errors = []

        def writer():
            try:
                for i in range(100):
                    cache.set(f"key_{i}", decision)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(100):
                    cache.get(f"key_{i}")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_stats_include_ages(self):
        cache = ResolutionCache()
        decision = RoutingDecision(
            adapter_name="t",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=1.0,
        )
        cache.set("k1", decision)
        time.sleep(0.1)
        stats = cache.get_stats()
        assert stats["oldest_entry_age_seconds"] > 0
        assert stats["newest_entry_age_seconds"] > 0
