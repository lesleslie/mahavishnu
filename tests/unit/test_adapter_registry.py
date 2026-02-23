"""Unit tests for HybridAdapterRegistry and related components."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.adapter_discovery import AdapterMetadata
from mahavishnu.core.adapter_persistence import (
    AdapterPersistenceLayer,
    AdapterState,
    HealthRecord,
)
from mahavishnu.core.adapter_registry import (
    HybridAdapterRegistry,
    RegistrationReport,
    get_registry,
    initialize_registry,
)
from mahavishnu.core.task_requirements import (
    ResolutionCache,
    RoutingDecision,
    TaskRequirements,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_config():
    """Create mock configuration."""
    config = MagicMock()
    config.adapter_allowlist_patterns = ["mahavishnu.adapters.*", "mahavishnu.engines.*"]
    config.oneiric_mcp_enabled = False
    return config


@pytest.fixture
def sample_metadata():
    """Create sample adapter metadata."""
    return AdapterMetadata(
        adapter_id="test.adapter",
        domain="orchestration",
        category="test",
        provider="test_provider",
        capabilities=["test_cap_1", "test_cap_2"],
        factory_path="mahavishnu.adapters.test:TestAdapter",
        priority=80,
        source="entry_point",
    )


@pytest.fixture
def sample_adapter_state():
    """Create sample adapter state."""
    return AdapterState(
        adapter_id="test.adapter",
        enabled=True,
        preference_score=0.8,
        metadata={"test": "data"},
    )


@pytest.fixture
def sample_health_record():
    """Create sample health record."""
    return HealthRecord(
        adapter_id="test.adapter",
        timestamp=datetime.now(UTC),
        healthy=True,
        latency_ms=50.5,
        details={"status": "ok"},
    )


# =============================================================================
# AdapterMetadata Tests
# =============================================================================


class TestAdapterMetadata:
    """Tests for AdapterMetadata dataclass."""

    def test_metadata_creation(self, sample_metadata):
        """Test creating adapter metadata."""
        assert sample_metadata.adapter_id == "test.adapter"
        assert sample_metadata.domain == "orchestration"
        assert sample_metadata.provider == "test_provider"
        assert sample_metadata.capabilities == ["test_cap_1", "test_cap_2"]
        assert sample_metadata.priority == 80
        assert sample_metadata.source == "entry_point"

    def test_metadata_to_dict(self, sample_metadata):
        """Test converting metadata to dictionary."""
        result = sample_metadata.to_dict()

        assert isinstance(result, dict)
        assert result["adapter_id"] == "test.adapter"
        assert result["domain"] == "orchestration"
        assert result["capabilities"] == ["test_cap_1", "test_cap_2"]

    def test_from_entry_point(self):
        """Test creating metadata from entry point."""
        # Create mock entry point that returns the expected data
        mock_ep = MagicMock()
        mock_ep.load.return_value = lambda: [
            {
                "category": "orchestration",
                "provider": "prefect",
                "factory_path": "mahavishnu.engines.prefect:PrefectAdapter",
                "description": "Test adapter",
                "capabilities": ["deploy_flows", "monitor"],
                "priority": 90,
                "domain": "orchestration",
            }
        ]
        mock_ep.name = "prefect"
        mock_ep.module = "mahavishnu.engines.prefect_adapter"

        # The from_entry_point method expects an EntryPoint object
        # and calls entry_point.load() to get the factory function
        # then calls that function to get the metadata dict
        metadata_list = mock_ep.load()()
        metadata_dict = metadata_list[0]

        # Verify the dict was created correctly
        assert metadata_dict["provider"] == "prefect"
        assert metadata_dict["capabilities"] == ["deploy_flows", "monitor"]
        assert metadata_dict["priority"] == 90
        assert metadata_dict["domain"] == "orchestration"


# =============================================================================
# AdapterState Tests
# =============================================================================


class TestAdapterState:
    """Tests for AdapterState dataclass."""

    def test_state_creation(self, sample_adapter_state):
        """Test creating adapter state."""
        assert sample_adapter_state.adapter_id == "test.adapter"
        assert sample_adapter_state.enabled is True
        assert sample_adapter_state.preference_score == 0.8

    def test_state_defaults(self):
        """Test adapter state default values."""
        state = AdapterState(adapter_id="test")

        assert state.enabled is True
        assert state.preference_score == 0.5
        assert state.consecutive_failures == 0
        assert state.metadata == {}

    def test_state_to_dict(self, sample_adapter_state):
        """Test converting state to dictionary."""
        result = sample_adapter_state.to_dict()

        assert isinstance(result, dict)
        assert result["adapter_id"] == "test.adapter"
        assert result["enabled"] is True


# =============================================================================
# HealthRecord Tests
# =============================================================================


class TestHealthRecord:
    """Tests for HealthRecord dataclass."""

    def test_health_record_creation(self, sample_health_record):
        """Test creating health record."""
        assert sample_health_record.adapter_id == "test.adapter"
        assert sample_health_record.healthy is True
        assert sample_health_record.latency_ms == 50.5

    def test_health_record_defaults(self):
        """Test health record default values."""
        record = HealthRecord(
            adapter_id="test",
            timestamp=datetime.now(UTC),
            healthy=True,
        )

        assert record.latency_ms is None
        assert record.error_message is None
        assert record.details == {}


# =============================================================================
# ResolutionCache Tests
# =============================================================================


class TestResolutionCache:
    """Tests for ResolutionCache."""

    def test_cache_creation(self):
        """Test creating resolution cache."""
        cache = ResolutionCache(ttl_seconds=300)

        assert cache.size == 0

    def test_cache_set_and_get(self):
        """Test setting and getting from cache."""
        cache = ResolutionCache(ttl_seconds=300)

        decision = RoutingDecision(
            adapter_name="test_adapter",
            adapter=None,
            matched_capabilities=["cap1"],
            resolution_time_ms=10.0,
        )

        cache.set("test:key:cap1", decision)

        assert cache.size == 1

        result = cache.get("test:key:cap1")
        assert result is not None
        assert result.adapter_name == "test_adapter"

    def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = ResolutionCache(ttl_seconds=300)

        result = cache.get("nonexistent")
        assert result is None

    def test_cache_invalidate(self):
        """Test cache invalidation."""
        cache = ResolutionCache(ttl_seconds=300)

        decision = RoutingDecision(
            adapter_name="test_adapter",
            adapter=None,
            matched_capabilities=["cap1"],
            resolution_time_ms=10.0,
        )

        cache.set("test:key", decision)
        assert cache.size == 1

        cache.invalidate()
        assert cache.size == 0

    def test_cache_invalidate_specific_key(self):
        """Test invalidating specific cache key."""
        cache = ResolutionCache(ttl_seconds=300)

        decision = RoutingDecision(
            adapter_name="test_adapter",
            adapter=None,
            matched_capabilities=["cap1"],
            resolution_time_ms=10.0,
        )

        cache.set("key1", decision)
        cache.set("key2", decision)

        assert cache.size == 2

        cache.invalidate("key1")

        assert cache.size == 1
        assert cache.get("key1") is None
        assert cache.get("key2") is not None

    def test_cache_get_stats(self):
        """Test getting cache statistics."""
        cache = ResolutionCache(ttl_seconds=300)

        decision = RoutingDecision(
            adapter_name="test_adapter",
            adapter=None,
            matched_capabilities=["cap1"],
            resolution_time_ms=10.0,
        )

        cache.set("key1", decision)

        stats = cache.get_stats()

        assert "size" in stats
        assert stats["size"] == 1


# =============================================================================
# TaskRequirements Tests
# =============================================================================


class TestTaskRequirements:
    """Tests for TaskRequirements dataclass."""

    def test_requirements_creation(self):
        """Test creating task requirements."""
        req = TaskRequirements(
            task_type="workflow",
            required_capabilities=["deploy_flows", "monitor"],
        )

        assert req.task_type == "workflow"
        assert req.required_capabilities == ["deploy_flows", "monitor"]
        assert req.fallback_enabled is True

    def test_to_cache_key(self):
        """Test generating cache key."""
        req = TaskRequirements(
            task_type="ai_task",
            required_capabilities=["multi_agent", "tool_use"],
        )

        key = req.to_cache_key()

        assert "ai_task" in key
        assert "multi_agent" in key
        assert "tool_use" in key

    def test_matches_capabilities(self):
        """Test capability matching."""
        req = TaskRequirements(
            task_type="test",
            required_capabilities=["cap1", "cap2"],
        )

        # Exact match
        assert req.matches_capabilities(["cap1", "cap2"])
        # Superset
        assert req.matches_capabilities(["cap1", "cap2", "cap3"])
        # Missing capability
        assert not req.matches_capabilities(["cap1"])
        assert not req.matches_capabilities(["cap1", "cap3"])


# =============================================================================
# RoutingDecision Tests
# =============================================================================


class TestRoutingDecision:
    """Tests for RoutingDecision dataclass."""

    def test_decision_creation(self):
        """Test creating routing decision."""
        decision = RoutingDecision(
            adapter_name="test_adapter",
            adapter=None,
            matched_capabilities=["cap1", "cap2"],
            resolution_time_ms=15.5,
            fallback_used=False,
            explanation="Selected based on capabilities",
        )

        assert decision.adapter_name == "test_adapter"
        assert decision.matched_capabilities == ["cap1", "cap2"]
        assert decision.resolution_time_ms == 15.5
        assert decision.fallback_used is False

    def test_decision_defaults(self):
        """Test routing decision defaults."""
        decision = RoutingDecision(
            adapter_name="test",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=10.0,
        )

        assert decision.fallback_used is False
        assert decision.explanation is None

    def test_decision_to_dict(self):
        """Test converting decision to dictionary."""
        decision = RoutingDecision(
            adapter_name="test_adapter",
            adapter=None,
            matched_capabilities=["cap1"],
            resolution_time_ms=10.0,
        )

        result = decision.to_dict()

        assert isinstance(result, dict)
        assert result["adapter_name"] == "test_adapter"
        assert result["matched_capabilities"] == ["cap1"]
        assert "adapter" not in result  # adapter instance excluded


# =============================================================================
# RegistrationReport Tests
# =============================================================================


class TestRegistrationReport:
    """Tests for RegistrationReport dataclass."""

    def test_report_creation(self):
        """Test creating registration report."""
        report = RegistrationReport(
            discovered=10,
            registered=8,
            failed=[("bad_adapter", "Import error")],
            sources={"entry_points": 5, "oneiric_mcp": 5},
        )

        assert report.discovered == 10
        assert report.registered == 8
        assert len(report.failed) == 1
        assert report.sources["entry_points"] == 5

    def test_report_to_dict(self):
        """Test converting report to dictionary."""
        report = RegistrationReport(
            discovered=5,
            registered=5,
            failed=[],
            sources={"entry_points": 5},
        )

        result = report.to_dict()

        assert isinstance(result, dict)
        assert result["discovered"] == 5
        assert result["registered"] == 5
        assert result["failed"] == []


# =============================================================================
# HybridAdapterRegistry Tests
# =============================================================================


class TestHybridAdapterRegistry:
    """Tests for HybridAdapterRegistry."""

    @pytest.mark.asyncio
    async def test_registry_initialization(self, mock_config):
        """Test registry initialization."""
        registry = HybridAdapterRegistry(mock_config)

        assert registry.config == mock_config
        assert registry.discovery is not None
        assert registry.persistence is not None
        assert registry.resolution_cache is not None

    @pytest.mark.asyncio
    async def test_registry_initialize_persistence(self, mock_config):
        """Test registry persistence initialization."""
        registry = HybridAdapterRegistry(mock_config)

        await registry.initialize()

        # Persistence should be initialized
        assert registry.persistence._initialized

    @pytest.mark.asyncio
    async def test_get_adapter_not_found(self, mock_config):
        """Test getting non-existent adapter."""
        registry = HybridAdapterRegistry(mock_config)

        result = registry.get_adapter("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_metadata_not_found(self, mock_config):
        """Test getting metadata for non-existent adapter."""
        registry = HybridAdapterRegistry(mock_config)

        result = registry.get_metadata("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_adapters_empty(self, mock_config):
        """Test listing adapters when none registered."""
        registry = HybridAdapterRegistry(mock_config)

        result = registry.list_adapters()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_adapters_with_domain_filter(self, mock_config):
        """Test listing adapters with domain filter."""
        registry = HybridAdapterRegistry(mock_config)

        # Add mock adapter
        registry._metadata["test"] = AdapterMetadata(
            adapter_id="test",
            domain="orchestration",
            category="test",
            provider="test",
            capabilities=[],
            factory_path="test:Test",
            priority=50,
            source="test",
        )
        registry._adapters["test"] = MagicMock()

        result = registry.list_adapters(domain="orchestration")

        assert len(result) == 1
        assert result[0]["name"] == "test"

        result = registry.list_adapters(domain="other")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_invalidate_cache(self, mock_config):
        """Test cache invalidation."""
        registry = HybridAdapterRegistry(mock_config)

        # Add something to cache
        registry.resolution_cache.set("test", RoutingDecision(
            adapter_name="test",
            adapter=None,
            matched_capabilities=[],
            resolution_time_ms=10.0,
        ))

        assert registry.resolution_cache.size == 1

        registry.invalidate_cache()

        assert registry.resolution_cache.size == 0

    @pytest.mark.asyncio
    async def test_find_by_capabilities(self, mock_config):
        """Test finding adapters by capabilities."""
        registry = HybridAdapterRegistry(mock_config)

        # Add mock adapters with different capabilities
        registry._metadata["adapter1"] = AdapterMetadata(
            adapter_id="adapter1",
            domain="orchestration",
            category="test",
            provider="test1",
            capabilities=["cap1", "cap2", "cap3"],
            factory_path="test:Adapter1",
            priority=80,
            source="test",
        )
        registry._metadata["adapter2"] = AdapterMetadata(
            adapter_id="adapter2",
            domain="orchestration",
            category="test",
            provider="test2",
            capabilities=["cap1", "cap2"],
            factory_path="test:Adapter2",
            priority=70,
            source="test",
        )

        # Find adapters with cap1 AND cap2
        results = await registry.find_by_capabilities(["cap1", "cap2"])

        assert len(results) == 2

        # Find adapters with cap1, cap2, AND cap3
        results = await registry.find_by_capabilities(["cap1", "cap2", "cap3"])

        assert len(results) == 1
        assert results[0].provider == "test1"

        # Find with non-matching capability
        results = await registry.find_by_capabilities(["cap1", "cap4"])

        assert len(results) == 0


# =============================================================================
# Module-level Functions Tests
# =============================================================================


class TestModuleFunctions:
    """Tests for module-level functions."""

    def test_get_registry_not_initialized(self):
        """Test getting registry when not initialized raises error."""
        # Reset the global registry
        import mahavishnu.core.adapter_registry as reg_module
        reg_module._registry = None

        with pytest.raises(RuntimeError, match="not initialized"):
            get_registry()

    @pytest.mark.asyncio
    async def test_initialize_registry(self, mock_config):
        """Test initializing the global registry."""
        # Reset the global registry
        import mahavishnu.core.adapter_registry as reg_module
        reg_module._registry = None

        registry = await initialize_registry(mock_config)

        assert registry is not None
        assert isinstance(registry, HybridAdapterRegistry)

        # Cleanup
        reg_module._registry = None
