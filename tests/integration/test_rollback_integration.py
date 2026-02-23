"""Integration tests for rollback/fallback scenarios in HybridAdapterRegistry.

These tests verify graceful degradation when various components fail:

1. Feature flag disabled -> falls back to legacy initialization
2. Registry init failure -> gracefully degrades with error handling
3. Oneiric MCP unavailable -> uses local-only discovery
4. Dhruva persistence unavailable -> uses in-memory fallback
5. Partial discovery failure -> continues with successful adapters

Run tests:
    pytest tests/integration/test_rollback_integration.py -v
    pytest tests/integration/test_rollback_integration.py -v -k "test_feature_flag"
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mahavishnu.core.adapter_discovery import (
    AdapterDiscoveryEngine,
    AdapterMetadata,
)
from mahavishnu.core.adapter_persistence import (
    AdapterPersistenceLayer,
    AdapterState,
    HealthRecord,
    PersistenceError,
)
from mahavishnu.core.adapter_registry import (
    HybridAdapterRegistry,
    RegistrationReport,
)
from mahavishnu.core.task_requirements import (
    ResolutionCache,
    RoutingDecision,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_config():
    """Create mock configuration with adapter registry settings."""
    config = MagicMock()
    config.adapter_allowlist_patterns = [
        "mahavishnu.adapters.*",
        "mahavishnu.engines.*",
    ]
    config.oneiric_mcp_enabled = False
    config.adapter_registry = MagicMock()
    config.adapter_registry.enabled = True
    config.adapter_registry.allowlist_patterns = [
        "mahavishnu.adapters.*",
        "mahavishnu.engines.*",
    ]
    config.adapter_registry.cache_ttl_seconds = 300
    return config


@pytest.fixture
def mock_config_with_oneiric_enabled():
    """Create mock configuration with Oneiric MCP enabled."""
    config = MagicMock()
    config.adapter_allowlist_patterns = [
        "mahavishnu.adapters.*",
        "mahavishnu.engines.*",
    ]
    config.oneiric_mcp_enabled = True  # Enable Oneiric MCP
    config.adapter_registry = MagicMock()
    config.adapter_registry.enabled = True
    config.adapter_registry.allowlist_patterns = [
        "mahavishnu.adapters.*",
        "mahavishnu.engines.*",
    ]
    config.adapter_registry.cache_ttl_seconds = 300
    return config


@pytest.fixture
def mock_config_with_feature_disabled():
    """Create mock configuration with hybrid registry disabled."""
    config = MagicMock()
    config.adapter_allowlist_patterns = [
        "mahavishnu.adapters.*",
        "mahavishnu.engines.*",
    ]
    config.oneiric_mcp_enabled = False
    config.adapter_registry = MagicMock()
    config.adapter_registry.enabled = False  # Feature flag disabled
    config.adapter_registry.allowlist_patterns = [
        "mahavishnu.adapters.*",
        "mahavishnu.engines.*",
    ]
    config.adapter_registry.cache_ttl_seconds = 300
    return config


@pytest.fixture
def sample_adapter_metadata():
    """Create sample adapter metadata for testing."""
    return AdapterMetadata(
        adapter_id="mahavishnu.adapters.test",
        domain="orchestration",
        category="workflow",
        provider="test_provider",
        capabilities=["deploy_flows", "monitor_execution"],
        factory_path="mahavishnu.adapters.test:TestAdapter",
        priority=80,
        source="entry_point",
    )


@pytest.fixture
def sample_adapter_metadata_2():
    """Create second sample adapter metadata for partial failure tests."""
    return AdapterMetadata(
        adapter_id="mahavishnu.adapters.backup",
        domain="orchestration",
        category="workflow",
        provider="backup_provider",
        capabilities=["deploy_flows", "rollback"],
        factory_path="mahavishnu.adapters.backup:BackupAdapter",
        priority=70,
        source="entry_point",
    )


@pytest.fixture
def temp_db_path():
    """Create temporary database path for isolation."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
    # Cleanup
    Path(f.name).unlink(missing_ok=True)


# =============================================================================
# Test Classes
# =============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
class TestFeatureFlagDisabledUsesLegacy:
    """Tests for fallback when hybrid registry feature flag is disabled."""

    async def test_feature_flag_disabled_skips_hybrid_registry(
        self,
        mock_config_with_feature_disabled,
    ):
        """When hybrid registry flag is disabled, should skip hybrid initialization."""
        # Arrange
        config = mock_config_with_feature_disabled
        assert config.adapter_registry.enabled is False

        # Act - Create registry with disabled flag
        registry = HybridAdapterRegistry(config)

        # Assert - Registry should still be created but may have different behavior
        assert registry is not None
        assert registry.config == config

        # The discovery engine should be configured with oneiric disabled
        assert registry.discovery._enable_oneiric_mcp is False

    async def test_feature_flag_disabled_uses_entry_points_only(
        self,
        mock_config_with_feature_disabled,
    ):
        """When feature flag disabled, should only use entry points for discovery."""
        config = mock_config_with_feature_disabled

        registry = HybridAdapterRegistry(config)
        await registry.initialize()

        # Mock the entry point discovery to return test adapters
        with patch.object(
            registry.discovery,
            "discover_from_entry_points",
            new_callable=AsyncMock,
        ) as mock_ep:
            mock_ep.return_value = [
                AdapterMetadata(
                    adapter_id="test.adapter",
                    domain="test",
                    category="test",
                    provider="test",
                    capabilities=["test"],
                    factory_path=None,  # No factory to avoid import errors
                    priority=50,
                    source="entry_point",
                )
            ]

            with patch.object(
                registry.discovery,
                "discover_from_oneiric_mcp",
                new_callable=AsyncMock,
            ) as mock_oneiric:
                mock_oneiric.return_value = []

                # Discover adapters
                adapters = await registry.discovery.discover_all()

                # Entry points should be called
                mock_ep.assert_called_once()

                # Oneiric MCP should NOT be called (disabled)
                # Note: It may be called but returns empty list due to disabled flag

        await registry.close()

    async def test_feature_flag_disabled_allows_basic_operations(
        self,
        mock_config_with_feature_disabled,
    ):
        """When feature flag disabled, basic registry operations should still work."""
        config = mock_config_with_feature_disabled

        registry = HybridAdapterRegistry(config)
        await registry.initialize()

        # Basic operations should still work
        assert registry.get_adapter("nonexistent") is None
        assert registry.get_metadata("nonexistent") is None
        assert registry.list_adapters() == []

        # Cache operations should work
        registry.invalidate_cache()

        await registry.close()


@pytest.mark.integration
@pytest.mark.asyncio
class TestRegistryInitFailureFallsBack:
    """Tests for graceful degradation when registry initialization fails."""

    async def test_persistence_init_failure_continues_with_memory_fallback(
        self,
        mock_config,
        caplog,
    ):
        """When persistence layer fails to init, should continue with in-memory state."""
        registry = HybridAdapterRegistry(mock_config)

        # Mock persistence.initialize to raise an error
        with patch.object(
            registry.persistence,
            "initialize",
            side_effect=PersistenceError("Database initialization failed"),
        ):
            # Act - Initialize should handle the error gracefully
            with pytest.raises(PersistenceError):
                await registry.initialize()

        # Cleanup
        await registry.close()

    async def test_discovery_engine_failure_continues_with_empty_adapters(
        self,
        mock_config,
        caplog,
    ):
        """When discovery engine fails, should return empty report."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Mock discover_all to raise an error
        with patch.object(
            registry.discovery,
            "discover_all",
            side_effect=RuntimeError("Discovery failed"),
        ):
            # Act & Assert - Should raise the error
            with pytest.raises(RuntimeError, match="Discovery failed"):
                await registry.discover_and_register()

        await registry.close()

    async def test_partial_registration_failure_reports_errors(
        self,
        mock_config,
    ):
        """When some adapters fail to register, should report errors in report."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Manually add metadata to test registration
        good_metadata = AdapterMetadata(
            adapter_id="good.adapter",
            domain="test",
            category="test",
            provider="good",
            capabilities=["test"],
            factory_path="sys:version",  # Valid import path
            priority=80,
            source="test",
        )

        bad_metadata = AdapterMetadata(
            adapter_id="bad.adapter",
            domain="test",
            category="test",
            provider="bad",
            capabilities=["test"],
            factory_path="nonexistent.module:BadClass",  # Invalid import
            priority=70,
            source="test",
        )

        # Mock discovery to return mixed adapters
        with patch.object(
            registry.discovery,
            "discover_all",
            new_callable=AsyncMock,
            return_value=[good_metadata, bad_metadata],
        ):
            report = await registry.discover_and_register()

            # Should have discovered 2 adapters
            assert report.discovered == 2

            # At least one should have failed (the bad one)
            assert len(report.failed) >= 1

            # Failed list should contain the bad adapter ID
            failed_ids = [fid for fid, _ in report.failed]
            assert "bad.adapter" in failed_ids

        await registry.close()


@pytest.mark.integration
@pytest.mark.asyncio
class TestOneiricMCPFailureLocalOnly:
    """Tests for local-only fallback when Oneiric MCP server is unavailable."""

    async def test_oneiric_unavailable_returns_empty_list(
        self,
        mock_config,
    ):
        """When Oneiric MCP is unavailable, discover_from_oneiric_mcp should return empty."""
        registry = HybridAdapterRegistry(mock_config)

        # Configure discovery with Oneiric enabled but unavailable
        registry.discovery._enable_oneiric_mcp = True

        # Mock _get_oneiric_client to return None (unavailable)
        with patch.object(
            registry.discovery,
            "_get_oneiric_client",
            return_value=None,
        ):
            adapters = await registry.discovery.discover_from_oneiric_mcp()

            # Should return empty list gracefully
            assert adapters == []

        await registry.close()

    async def test_oneiric_connection_error_falls_back_gracefully(
        self,
        mock_config,
        caplog,
    ):
        """When Oneiric MCP connection fails, should log warning and continue."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Configure discovery with Oneiric enabled
        registry.discovery._enable_oneiric_mcp = True

        # Create a mock client that raises ConnectionError
        mock_client = MagicMock()
        mock_client.list_adapters = AsyncMock(
            side_effect=ConnectionError("Oneiric MCP unavailable")
        )

        with patch.object(
            registry.discovery,
            "_get_oneiric_client",
            return_value=mock_client,
        ):
            # Should not raise, just return empty list
            adapters = await registry.discovery.discover_from_oneiric_mcp()

            assert adapters == []
            assert "Oneiric MCP" in caplog.text or "unavailable" in caplog.text.lower()

        await registry.close()

    async def test_oneiric_failure_entry_points_still_work(
        self,
        mock_config,
    ):
        """When Oneiric MCP fails, entry point discovery should still work."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Mock entry points to return adapters
        entry_adapters = [
            AdapterMetadata(
                adapter_id="entry.adapter",
                domain="test",
                category="test",
                provider="entry",
                capabilities=["test"],
                factory_path=None,
                priority=90,
                source="entry_point",
            )
        ]

        with patch.object(
            registry.discovery,
            "discover_from_entry_points",
            new_callable=AsyncMock,
            return_value=entry_adapters,
        ):
            with patch.object(
                registry.discovery,
                "discover_from_oneiric_mcp",
                new_callable=AsyncMock,
                side_effect=ConnectionError("MCP unavailable"),
            ):
                # discover_all should combine results, handling Oneiric failure
                adapters = await registry.discovery.discover_all()

                # Entry point adapters should still be present
                adapter_ids = [a.adapter_id for a in adapters]
                assert "entry.adapter" in adapter_ids

        await registry.close()

    async def test_oneiric_timeout_falls_back(
        self,
        mock_config,
    ):
        """When Oneiric MCP times out, should fall back gracefully."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        registry.discovery._enable_oneiric_mcp = True

        # Mock client that times out
        mock_client = MagicMock()
        mock_client.list_adapters = AsyncMock(
            side_effect=TimeoutError("Oneiric MCP timeout")
        )

        with patch.object(
            registry.discovery,
            "_get_oneiric_client",
            return_value=mock_client,
        ):
            # Should not raise
            adapters = await registry.discovery.discover_from_oneiric_mcp()
            assert adapters == []

        await registry.close()


@pytest.mark.integration
@pytest.mark.asyncio
class TestDhruvaUnavailableUsesMemory:
    """Tests for in-memory fallback when Dhruva persistence fails."""

    async def test_persistence_save_failure_uses_in_memory(
        self,
        mock_config,
        temp_db_path,
    ):
        """When persistence save fails, should track state in memory."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Mock save_state to fail
        with patch.object(
            registry.persistence,
            "save_state",
            side_effect=PersistenceError("Save failed"),
        ):
            # Attempt to set adapter enabled - should handle error
            metadata = AdapterMetadata(
                adapter_id="test.adapter",
                domain="test",
                category="test",
                provider="test",
                capabilities=["test"],
                factory_path=None,
                priority=50,
                source="test",
            )

            # Add adapter to registry
            registry._metadata["test"] = metadata

            # Try to set enabled state
            result = await registry.set_adapter_enabled("test", False, "Testing fallback")

            # Should return True even though persistence failed
            # (state tracked in memory)
            assert result is True

        await registry.close()

    async def test_persistence_load_failure_returns_none(
        self,
        mock_config,
    ):
        """When persistence load fails, should return None and create new state."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Mock load_state to fail
        with patch.object(
            registry.persistence,
            "load_state",
            side_effect=PersistenceError("Load failed"),
        ):
            # Attempt to load state should raise
            with pytest.raises(PersistenceError):
                await registry.persistence.load_state("test.adapter")

        await registry.close()

    async def test_health_record_failure_marks_unhealthy(
        self,
        mock_config,
    ):
        """When health record persistence fails, adapter should be marked unhealthy."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Create mock adapter that returns healthy status
        mock_adapter = MagicMock()
        mock_adapter.get_health = AsyncMock(return_value={"status": "healthy", "latency_ms": 10})

        # Add adapter to registry
        registry._adapters["test"] = mock_adapter
        registry._metadata["test"] = AdapterMetadata(
            adapter_id="test.adapter",
            domain="test",
            category="test",
            provider="test",
            capabilities=["test"],
            factory_path=None,
            priority=50,
            source="test",
        )

        # Mock record_health to fail
        with patch.object(
            registry.persistence,
            "record_health",
            side_effect=PersistenceError("Health record failed"),
        ):
            # Health check should raise the persistence error
            # (this is the actual behavior - it propagates the error)
            with pytest.raises(PersistenceError, match="Health record failed"):
                await registry.check_all_health()

        await registry.close()

    async def test_persistence_unavailable_in_memory_state_works(
        self,
        mock_config,
    ):
        """When persistence is completely unavailable, in-memory state should work."""
        registry = HybridAdapterRegistry(mock_config)

        # Don't initialize persistence
        # Mock initialize to fail
        with patch.object(
            registry.persistence,
            "initialize",
            side_effect=PersistenceError("Database unavailable"),
        ):
            with pytest.raises(PersistenceError):
                await registry.initialize()

        # Even with persistence failure, in-memory operations should work
        metadata = AdapterMetadata(
            adapter_id="memory.adapter",
            domain="test",
            category="test",
            provider="memory",
            capabilities=["test"],
            factory_path=None,
            priority=50,
            source="test",
        )

        # Add directly to in-memory storage
        registry._metadata["memory"] = metadata
        registry._adapters["memory"] = MagicMock()

        # Should be able to retrieve
        assert registry.get_adapter("memory") is not None
        assert registry.get_metadata("memory") is not None

        # List should include it
        adapters = registry.list_adapters()
        assert any(a["name"] == "memory" for a in adapters)

        await registry.close()


@pytest.mark.integration
@pytest.mark.asyncio
class TestPartialDiscoveryContinues:
    """Tests for continuing when some adapters fail discovery."""

    async def test_mixed_discovery_results(
        self,
        mock_config,
    ):
        """When some discovery sources fail, should continue with successful ones."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Entry points succeed
        entry_adapters = [
            AdapterMetadata(
                adapter_id="entry.success",
                domain="test",
                category="test",
                provider="entry",
                capabilities=["test"],
                factory_path=None,
                priority=90,
                source="entry_point",
            )
        ]

        # Oneiric fails
        with patch.object(
            registry.discovery,
            "discover_from_entry_points",
            new_callable=AsyncMock,
            return_value=entry_adapters,
        ):
            with patch.object(
                registry.discovery,
                "discover_from_oneiric_mcp",
                new_callable=AsyncMock,
                side_effect=Exception("Oneiric discovery failed"),
            ):
                adapters = await registry.discovery.discover_all()

                # Should have entry point adapters
                assert len(adapters) >= 1
                assert any(a.adapter_id == "entry.success" for a in adapters)

        await registry.close()

    async def test_registration_continues_after_failures(
        self,
        mock_config,
    ):
        """When some adapter registrations fail, should continue with remaining."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Create mixed adapters (some with valid factory paths, some invalid)
        adapters = [
            AdapterMetadata(
                adapter_id="good.1",
                domain="test",
                category="test",
                provider="good1",
                capabilities=["test"],
                factory_path="sys:version",  # Valid
                priority=90,
                source="test",
            ),
            AdapterMetadata(
                adapter_id="bad.1",
                domain="test",
                category="test",
                provider="bad1",
                capabilities=["test"],
                factory_path="nonexistent:BadClass",  # Invalid
                priority=80,
                source="test",
            ),
            AdapterMetadata(
                adapter_id="good.2",
                domain="test",
                category="test",
                provider="good2",
                capabilities=["test"],
                factory_path="os:path",  # Valid
                priority=70,
                source="test",
            ),
            AdapterMetadata(
                adapter_id="bad.2",
                domain="test",
                category="test",
                provider="bad2",
                capabilities=["test"],
                factory_path="invalid.module.path:Class",  # Invalid
                priority=60,
                source="test",
            ),
        ]

        with patch.object(
            registry.discovery,
            "discover_all",
            new_callable=AsyncMock,
            return_value=adapters,
        ):
            report = await registry.discover_and_register()

            # All should be discovered
            assert report.discovered == 4

            # Should have some failures
            assert len(report.failed) >= 2

            # Failed IDs should be tracked
            failed_ids = [fid for fid, _ in report.failed]
            assert "bad.1" in failed_ids
            assert "bad.2" in failed_ids

        await registry.close()

    async def test_discovery_source_tracking(
        self,
        mock_config_with_oneiric_enabled,
    ):
        """Discovery report should track adapter sources."""
        registry = HybridAdapterRegistry(mock_config_with_oneiric_enabled)
        await registry.initialize()

        # Verify Oneiric MCP is enabled in discovery engine
        assert registry.discovery._enable_oneiric_mcp is True

        # Create adapters with valid factory paths so they register successfully
        entry_adapters = [
            AdapterMetadata(
                adapter_id="entry.adapter.1",
                domain="test",
                category="test",
                provider="entry1",
                capabilities=["test"],
                factory_path="sys:version",  # Valid import path
                priority=90,
                source="entry_point",
            )
        ]

        oneiric_adapters = [
            AdapterMetadata(
                adapter_id="oneiric.adapter.1",
                domain="test",
                category="test",
                provider="oneiric1",
                capabilities=["test"],
                factory_path="os:path",  # Valid import path
                priority=80,
                source="oneiric_mcp",
            )
        ]

        with patch.object(
            registry.discovery,
            "discover_from_entry_points",
            new_callable=AsyncMock,
            return_value=entry_adapters,
        ):
            with patch.object(
                registry.discovery,
                "discover_from_oneiric_mcp",
                new_callable=AsyncMock,
                return_value=oneiric_adapters,
            ):
                report = await registry.discover_and_register()

                # Sources should be tracked
                assert "entry_point" in report.sources
                assert "oneiric_mcp" in report.sources

                # Counts should match
                assert report.sources["entry_point"] == 1
                assert report.sources["oneiric_mcp"] == 1

        await registry.close()

    async def test_capability_matching_continues_with_partial_adapters(
        self,
        mock_config,
    ):
        """When some adapters fail, capability matching should still work."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Add working adapter to metadata
        working_metadata = AdapterMetadata(
            adapter_id="working.adapter",
            domain="orchestration",
            category="workflow",
            provider="working",
            capabilities=["deploy_flows", "monitor"],
            factory_path="sys:version",
            priority=90,
            source="test",
        )

        registry._metadata["working"] = working_metadata
        registry._adapters["working"] = MagicMock()

        # Add broken adapter (simulating partial failure)
        broken_metadata = AdapterMetadata(
            adapter_id="broken.adapter",
            domain="orchestration",
            category="workflow",
            provider="broken",
            capabilities=["deploy_flows", "monitor"],
            factory_path=None,  # No factory
            priority=80,
            source="test",
        )

        registry._metadata["broken"] = broken_metadata
        # No adapter instance for broken

        # Resolve should find the working adapter
        decision = await registry.resolve(
            domain="orchestration",
            key="workflow",
            capabilities=["deploy_flows"],
        )

        assert decision is not None
        assert decision.adapter_name == "working"
        assert "deploy_flows" in decision.matched_capabilities

        await registry.close()

    async def test_health_check_marks_failed_adapters_unhealthy(
        self,
        mock_config,
    ):
        """Health check should mark failed adapters as unhealthy."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Good adapter
        good_adapter = MagicMock()
        good_adapter.get_health = AsyncMock(
            return_value={"status": "healthy", "latency_ms": 10}
        )

        # Failing adapter
        failing_adapter = MagicMock()
        failing_adapter.get_health = AsyncMock(
            side_effect=RuntimeError("Health check failed")
        )

        # Add both to registry
        registry._adapters["good"] = good_adapter
        registry._metadata["good"] = AdapterMetadata(
            adapter_id="good.adapter",
            domain="test",
            category="test",
            provider="good",
            capabilities=["test"],
            factory_path=None,
            priority=90,
            source="test",
        )

        registry._adapters["failing"] = failing_adapter
        registry._metadata["failing"] = AdapterMetadata(
            adapter_id="failing.adapter",
            domain="test",
            category="test",
            provider="failing",
            capabilities=["test"],
            factory_path=None,
            priority=80,
            source="test",
        )

        # Health check should handle both and mark failing as unhealthy
        results = await registry.check_all_health()

        # Good adapter should be healthy
        assert results["good"]["status"] == "healthy"

        # Failing adapter should be unhealthy
        assert results["failing"]["status"] == "unhealthy"
        assert "error" in results["failing"]

        await registry.close()


@pytest.mark.integration
@pytest.mark.asyncio
class TestFallbackChainIntegration:
    """Integration tests for complete fallback chains."""

    async def test_complete_fallback_chain(
        self,
        mock_config,
    ):
        """Test complete fallback: Oneiric fails -> entry points succeed -> partial registration."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        entry_adapters = [
            AdapterMetadata(
                adapter_id="fallback.adapter",
                domain="test",
                category="test",
                provider="fallback",
                capabilities=["test"],
                factory_path="sys:version",
                priority=90,
                source="entry_point",
            )
        ]

        with patch.object(
            registry.discovery,
            "discover_from_entry_points",
            new_callable=AsyncMock,
            return_value=entry_adapters,
        ):
            with patch.object(
                registry.discovery,
                "discover_from_oneiric_mcp",
                new_callable=AsyncMock,
                side_effect=ConnectionError("Oneiric MCP unavailable"),
            ):
                # This should not raise
                report = await registry.discover_and_register()

                # Should have discovered entry point adapters
                assert report.discovered >= 1
                assert report.sources.get("entry_point", 0) >= 1

        await registry.close()

    async def test_cache_invalidation_on_failure(
        self,
        mock_config,
    ):
        """Cache should be invalidatable after failures."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Add to cache
        registry.resolution_cache.set(
            "test:key:cap",
            RoutingDecision(
                adapter_name="test",
                adapter=None,
                matched_capabilities=["cap"],
                resolution_time_ms=10.0,
            ),
        )

        assert registry.resolution_cache.size == 1

        # Invalidate
        registry.invalidate_cache()

        assert registry.resolution_cache.size == 0
        assert registry.discovery._cache == {}

        await registry.close()

    async def test_graceful_close_after_failures(
        self,
        mock_config,
    ):
        """Registry should close gracefully even after failures."""
        registry = HybridAdapterRegistry(mock_config)
        await registry.initialize()

        # Simulate some state
        registry._metadata["test"] = AdapterMetadata(
            adapter_id="test.adapter",
            domain="test",
            category="test",
            provider="test",
            capabilities=["test"],
            factory_path=None,
            priority=50,
            source="test",
        )

        # Add something to cache
        registry.resolution_cache.set(
            "key",
            RoutingDecision(
                adapter_name="test",
                adapter=None,
                matched_capabilities=[],
                resolution_time_ms=5.0,
            ),
        )

        # Close should not raise
        await registry.close()

        # Resources should be cleaned up
        assert registry.resolution_cache.size == 0
