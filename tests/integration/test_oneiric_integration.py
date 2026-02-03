"""Integration tests for Oneiric MCP integration.

Tests require Oneiric MCP server to be running.

Run tests:
    # Start Oneiric MCP server in insecure mode
    cd /Users/les/Projects/oneiric-mcp
    python -m oneiric_mcp --port 8679

    # Run integration tests
    pytest tests/integration/test_oneiric_integration.py -v
"""

import asyncio

import pytest

from mahavishnu.core.oneiric_client import (
    AdapterEntry,
    OneiricMCPClient,
    OneiricMCPConfig,
)

# Skip tests if Oneiric MCP not available
pytest.importorskip("oneiric_mcp.grpc")


@pytest.mark.integration
@pytest.mark.asyncio
class TestOneiricMCPIntegration:
    """Integration tests with real Oneiric MCP server."""

    async def test_connection_to_server(self):
        """Test connection to Oneiric MCP server."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,  # Insecure dev port
            use_tls=False,
        )

        client = OneiricMCPClient(config)

        try:
            # Ensure connected
            await client._ensure_connected()

            # Verify connection
            assert client._connected is True
            assert client._channel is not None
            assert client._stub is not None

        finally:
            await client.close()

    async def test_list_all_adapters(self):
        """Test listing all adapters from registry."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,
            use_tls=False,
        )

        client = OneiricMCPClient(config)

        try:
            # List all adapters
            adapters = await client.list_adapters()

            # Verify response
            assert isinstance(adapters, list)
            # Note: May be empty if no adapters registered

        finally:
            await client.close()

    async def test_list_adapters_with_filters(self):
        """Test listing adapters with category filter."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,
            use_tls=False,
        )

        client = OneiricMCPClient(config)

        try:
            # List storage adapters
            storage_adapters = await client.list_adapters(category="storage")

            # Verify all returned adapters have category="storage"
            for adapter in storage_adapters:
                assert adapter.category == "storage"

        finally:
            await client.close()

    async def test_list_adapters_caching(self):
        """Test adapter list caching behavior."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,
            use_tls=False,
            cache_ttl_sec=60,
        )

        client = OneiricMCPClient(config)

        try:
            # First call (cache miss)
            adapters1 = await client.list_adapters(use_cache=True)
            cache_entries_after_first = len(client._cache)

            # Second call (cache hit)
            adapters2 = await client.list_adapters(use_cache=True)
            cache_entries_after_second = len(client._cache)

            # Verify caching
            assert adapters1 == adapters2
            assert cache_entries_after_first == cache_entries_after_second

            # Invalidate cache
            await client.invalidate_cache()
            assert len(client._cache) == 0

        finally:
            await client.close()

    async def test_health_check(self):
        """Test health check endpoint."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,
            use_tls=False,
        )

        client = OneiricMCPClient(config)

        try:
            # Perform health check
            health = await client.health_check()

            # Verify response structure
            assert "status" in health
            assert "connected" in health
            assert "adapter_count" in health

            # If connected successfully
            if health["status"] == "healthy":
                assert health["connected"] is True
                assert isinstance(health["adapter_count"], int)

        finally:
            await client.close()

    async def test_resolve_adapter(self):
        """Test resolving adapter by domain/category/provider."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,
            use_tls=False,
        )

        client = OneiricMCPClient(config)

        try:
            # Try to resolve a storage adapter
            # Note: This will only work if adapters are registered
            adapter = await client.resolve_adapter(
                domain="adapter",
                category="storage",
                provider="s3",
                healthy_only=False,  # Don't filter by health for testing
            )

            # If adapter found, verify structure
            if adapter:
                assert isinstance(adapter, AdapterEntry)
                assert adapter.domain == "adapter"
                assert adapter.category == "storage"
                assert adapter.provider == "s3"
                assert adapter.adapter_id is not None

        finally:
            await client.close()

    async def test_circuit_breaker(self):
        """Test circuit breaker behavior with failing adapter."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,
            use_tls=False,
        )

        client = OneiricMCPClient(config)

        try:
            # Test with non-existent adapter (will fail)
            fake_adapter_id = "nonexistent.project.adapter.fake"

            # Check health (will fail)
            is_healthy = await client.check_adapter_health(fake_adapter_id)
            assert is_healthy is False

            # Circuit breaker should track failure
            # Note: May not be blocked yet depending on threshold

        finally:
            await client.close()

    async def test_connection_failure(self):
        """Test handling of connection failure."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=9999,  # Wrong port
            use_tls=False,
            timeout_sec=2,  # Short timeout for testing
        )

        client = OneiricMCPClient(config)

        try:
            # Try to list adapters (should fail)
            with pytest.raises(Exception):  # ConnectionError or similar
                await client.list_adapters()

        finally:
            await client.close()

    async def test_concurrent_requests(self):
        """Test handling concurrent requests."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,
            use_tls=False,
        )

        client = OneiricMCPClient(config)

        try:
            # Launch concurrent requests
            tasks = [
                client.list_adapters(),
                client.list_adapters(category="storage"),
                client.health_check(),
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Verify all completed
            assert len(results) == 3

            # Check for exceptions
            exceptions = [r for r in results if isinstance(r, Exception)]
            if exceptions:
                # At least health_check should work
                pass

        finally:
            await client.close()

    async def test_adapter_entry_serialization(self):
        """Test AdapterEntry to_dict conversion."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,
            use_tls=False,
        )

        client = OneiricMCPClient(config)

        try:
            # List adapters
            adapters = await client.list_adapters()

            if adapters:
                # Test serialization of first adapter
                adapter_dict = adapters[0].to_dict()

                # Verify required fields
                assert "adapter_id" in adapter_dict
                assert "project" in adapter_dict
                assert "domain" in adapter_dict
                assert "category" in adapter_dict
                assert "provider" in adapter_dict
                assert "capabilities" in adapter_dict
                assert "factory_path" in adapter_dict
                assert "health_status" in adapter_dict

        finally:
            await client.close()

    async def test_cache_invalidation(self):
        """Test cache invalidation between queries."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="localhost",
            grpc_port=8679,
            use_tls=False,
            cache_ttl_sec=300,
        )

        client = OneiricMCPClient(config)

        try:
            # First query
            adapters1 = await client.list_adapters(use_cache=True)
            cache_size_1 = len(client._cache)

            # Invalidate cache
            await client.invalidate_cache()
            cache_size_2 = len(client._cache)

            # Verify cache cleared
            assert cache_size_1 > 0
            assert cache_size_2 == 0

            # Second query (should fetch fresh)
            adapters2 = await client.list_adapters(use_cache=False)

            # Should have cache entry again
            cache_size_3 = len(client._cache)
            assert cache_size_3 > 0

        finally:
            await client.close()


@pytest.mark.integration
@pytest.mark.asyncio
class TestOneiricMCPTools:
    """Integration tests for Oneiric MCP tools."""

    async def test_oneiric_list_adapters_tool(self):
        """Test oneiric_list_adapters MCP tool."""
        from mahavishnu.mcp.tools.oneiric_tools import oneiric_list_adapters

        # Call tool
        result = await oneiric_list_adapters()

        # Verify structure
        assert "count" in result
        assert "adapters" in result
        assert isinstance(result["adapters"], list)
        assert isinstance(result["count"], int)

    async def test_oneiric_health_check_tool(self):
        """Test oneiric_health_check MCP tool."""
        from mahavishnu.mcp.tools.oneiric_tools import oneiric_health_check

        # Call tool
        result = await oneiric_health_check()

        # Verify structure
        assert "status" in result
        assert "connected" in result
        assert result["status"] in ["healthy", "unhealthy", "disabled"]

    async def test_oneiric_invalidate_cache_tool(self):
        """Test oneiric_invalidate_cache MCP tool."""
        from mahavishnu.mcp.tools.oneiric_tools import (
            oneiric_invalidate_cache,
            oneiric_list_adapters,
        )

        # List adapters to populate cache
        await oneiric_list_adapters()

        # Invalidate cache
        result = await oneiric_invalidate_cache()

        # Verify
        assert "success" in result
        assert isinstance(result["success"], bool)
