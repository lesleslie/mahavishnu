"""Unit tests for Oneiric MCP client integration.

Tests OneiricMCPClient functionality including:
- gRPC connection management
- Adapter listing and filtering
- Health checking
- Circuit breaker pattern
- Caching behavior
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import grpc.aio

from mahavishnu.core.oneiric_client import (
    AdapterEntry,
    AdapterCircuitBreaker,
    OneiricMCPClient,
    OneiricMCPConfig,
)


# Skip tests if Oneiric MCP not available
pytest.importorskip("oneiric_mcp.grpc")


class TestAdapterEntry:
    """Test AdapterEntry dataclass."""

    def test_from_pb2(self):
        """Test creating AdapterEntry from protobuf."""
        # Create mock protobuf entry
        pb2_entry = MagicMock()
        pb2_entry.adapter_id = "test.adapter.storage.s3"
        pb2_entry.project = "test"
        pb2_entry.domain = "adapter"
        pb2_entry.category = "storage"
        pb2_entry.provider = "s3"
        pb2_entry.capabilities = ["read", "write"]
        pb2_entry.factory_path = "test.adapters.S3Adapter"
        pb2_entry.health_check_url = "http://example.com/health"
        pb2_entry.metadata = {"region": "us-east-1"}
        pb2_entry.registered_at = 1234567890
        pb2_entry.last_heartbeat = 1234567890
        pb2_entry.health_status = "healthy"

        # Convert
        entry = AdapterEntry.from_pb2(pb2_entry)

        # Verify
        assert entry.adapter_id == "test.adapter.storage.s3"
        assert entry.project == "test"
        assert entry.domain == "adapter"
        assert entry.category == "storage"
        assert entry.provider == "s3"
        assert entry.capabilities == ["read", "write"]
        assert entry.factory_path == "test.adapters.S3Adapter"
        assert entry.health_check_url == "http://example.com/health"
        assert entry.metadata == {"region": "us-east-1"}
        assert entry.registered_at == datetime.fromtimestamp(1234567890, tz=UTC)
        assert entry.last_heartbeat == datetime.fromtimestamp(1234567890, tz=UTC)
        assert entry.health_status == "healthy"

    def test_to_dict(self):
        """Test converting AdapterEntry to dictionary."""
        entry = AdapterEntry(
            adapter_id="test.adapter.storage.s3",
            project="test",
            domain="adapter",
            category="storage",
            provider="s3",
            capabilities=["read", "write"],
            factory_path="test.S3Adapter",
            health_check_url="http://example.com/health",
            metadata={"region": "us-east-1"},
            registered_at=datetime.now(UTC),
            last_heartbeat=datetime.now(UTC),
            health_status="healthy",
        )

        result = entry.to_dict()

        assert result["adapter_id"] == "test.adapter.storage.s3"
        assert result["project"] == "test"
        assert result["capabilities"] == ["read", "write"]
        assert result["metadata"] == {"region": "us-east-1"}
        assert "registered_at" in result
        assert "last_heartbeat" in result


class TestAdapterCircuitBreaker:
    """Test AdapterCircuitBreaker functionality."""

    @pytest.mark.asyncio
    async def test_initially_available(self):
        """Test that adapters are initially available."""
        breaker = AdapterCircuitBreaker()

        assert await breaker.is_available("test.adapter")

    @pytest.mark.asyncio
    async def test_failure_threshold(self):
        """Test that adapter is blocked after threshold failures."""
        breaker = AdapterCircuitBreaker(failure_threshold=3)

        # Record failures below threshold
        await breaker.record_failure("test.adapter")
        await breaker.record_failure("test.adapter")

        # Should still be available
        assert await breaker.is_available("test.adapter")

        # Third failure crosses threshold
        await breaker.record_failure("test.adapter")

        # Now should be blocked
        assert not await breaker.is_available("test.adapter")

    @pytest.mark.asyncio
    async def test_success_resets_failures(self):
        """Test that success resets failure count."""
        breaker = AdapterCircuitBreaker(failure_threshold=3)

        # Record some failures
        await breaker.record_failure("test.adapter")
        await breaker.record_failure("test.adapter")

        # Record success
        await breaker.record_success("test.adapter")

        # Should be available
        assert await breaker.is_available("test.adapter")

        # Should need 3 more failures to block
        await breaker.record_failure("test.adapter")
        assert await breaker.is_available("test.adapter")

    @pytest.mark.asyncio
    async def test_block_duration(self):
        """Test that adapter becomes available after block duration."""
        breaker = AdapterCircuitBreaker(
            failure_threshold=1, block_duration_sec=1
        )

        # Block adapter
        await breaker.record_failure("test.adapter")

        # Should be blocked
        assert not await breaker.is_available("test.adapter")

        # Wait for block to expire
        await asyncio.sleep(1.5)

        # Should be available again
        assert await breaker.is_available("test.adapter")


class TestOneiricMCPClient:
    """Test OneiricMCPClient functionality."""

    def test_init_disabled(self):
        """Test initialization with disabled config."""
        config = OneiricMCPConfig(enabled=False)
        client = OneiricMCPClient(config)

        assert client.config.enabled is False

    @pytest.mark.asyncio
    async def test_list_adapters_disabled(self):
        """Test list_adapters returns empty list when disabled."""
        config = OneiricMCPConfig(enabled=False)
        client = OneiricMCPClient(config)

        adapters = await client.list_adapters()

        assert adapters == []

    @pytest.mark.asyncio
    async def test_list_adapters_with_mock(self):
        """Test list_adapters with mocked gRPC stub."""
        config = OneiricMCPConfig(enabled=True, grpc_port=8679)

        with patch("mahavishnu.core.oneiric_client.registry_pb2_grpc"):
            client = OneiricMCPClient(config)

            # Mock the gRPC stub
            mock_stub = AsyncMock()
            client._stub = mock_stub
            client._connected = True

            # Create mock response
            mock_response = MagicMock()
            mock_adapter = MagicMock()
            mock_adapter.adapter_id = "test.adapter.storage.s3"
            mock_adapter.project = "test"
            mock_adapter.domain = "adapter"
            mock_adapter.category = "storage"
            mock_adapter.provider = "s3"
            mock_adapter.capabilities = ["read", "write"]
            mock_adapter.factory_path = "test.S3Adapter"
            mock_adapter.health_check_url = ""
            mock_adapter.metadata = {}
            mock_adapter.registered_at = 1234567890
            mock_adapter.last_heartbeat = 1234567890
            mock_adapter.health_status = "healthy"
            mock_response.adapters = [mock_adapter]

            mock_stub.ListAdapters.return_value = mock_response

            # Call list_adapters
            adapters = await client.list_adapters(category="storage")

            # Verify
            assert len(adapters) == 1
            assert adapters[0].adapter_id == "test.adapter.storage.s3"
            assert adapters[0].category == "storage"

            # Verify gRPC was called
            mock_stub.ListAdapters.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_adapters_caching(self):
        """Test that list_adapters caches results."""
        config = OneiricMCPConfig(enabled=True, grpc_port=8679, cache_ttl_sec=60)

        with patch("mahavishnu.core.oneiric_client.registry_pb2_grpc"):
            client = OneiricMCPClient(config)

            # Mock the gRPC stub
            mock_stub = AsyncMock()
            client._stub = mock_stub
            client._connected = True

            # Create mock response
            mock_response = MagicMock()
            mock_response.adapters = []
            mock_stub.ListAdapters.return_value = mock_response

            # First call (cache miss)
            adapters1 = await client.list_adapters(category="storage", use_cache=True)

            # Second call (cache hit)
            adapters2 = await client.list_adapters(category="storage", use_cache=True)

            # Verify same result
            assert adapters1 == adapters2

            # Verify gRPC called only once (cached)
            assert mock_stub.ListAdapters.call_count == 1

    @pytest.mark.asyncio
    async def test_get_adapter(self):
        """Test get_adapter with mocked stub."""
        config = OneiricMCPConfig(enabled=True, grpc_port=8679)

        with patch("mahavishnu.core.oneiric_client.registry_pb2_grpc"):
            client = OneiricMCPClient(config)

            # Mock the gRPC stub
            mock_stub = AsyncMock()
            client._stub = mock_stub
            client._connected = True

            # Create mock response
            mock_response = MagicMock()
            mock_adapter = MagicMock()
            mock_adapter.adapter_id = "test.adapter.storage.s3"
            mock_adapter.project = "test"
            mock_adapter.domain = "adapter"
            mock_adapter.category = "storage"
            mock_adapter.provider = "s3"
            mock_adapter.capabilities = ["read"]
            mock_adapter.factory_path = "test.S3"
            mock_adapter.health_check_url = ""
            mock_adapter.metadata = {}
            mock_adapter.registered_at = 1234567890
            mock_adapter.last_heartbeat = 1234567890
            mock_adapter.health_status = "healthy"
            mock_response.adapter = mock_adapter

            mock_stub.GetAdapter.return_value = mock_response

            # Call get_adapter
            adapter = await client.get_adapter("test.adapter.storage.s3")

            # Verify
            assert adapter is not None
            assert adapter.adapter_id == "test.adapter.storage.s3"

    @pytest.mark.asyncio
    async def test_get_adapter_not_found(self):
        """Test get_adapter returns None for non-existent adapter."""
        config = OneiricMCPConfig(enabled=True, grpc_port=8679)

        with patch("mahavishnu.core.oneiric_client.registry_pb2_grpc"):
            client = OneiricMCPClient(config)

            # Mock the gRPC stub to raise NOT_FOUND
            mock_stub = AsyncMock()
            client._stub = mock_stub
            client._connected = True

            error = grpc.aio.AioRpcError("test", grpc.StatusCode.NOT_FOUND, "Not found")
            mock_stub.GetAdapter.side_effect = error

            # Call get_adapter
            adapter = await client.get_adapter("nonexistent.adapter")

            # Verify None returned
            assert adapter is None

    @pytest.mark.asyncio
    async def test_check_adapter_health(self):
        """Test check_adapter_health with mocked stub."""
        config = OneiricMCPConfig(enabled=True, grpc_port=8679)

        with patch("mahavishnu.core.oneiric_client.registry_pb2_grpc"):
            client = OneiricMCPClient(config)

            # Mock the gRPC stub
            mock_stub = AsyncMock()
            client._stub = mock_stub
            client._connected = True

            # Create mock response
            mock_response = MagicMock()
            mock_response.healthy = True
            mock_stub.HealthCheck.return_value = mock_response

            # Call check_adapter_health
            is_healthy = await client.check_adapter_health("test.adapter")

            # Verify
            assert is_healthy is True

    @pytest.mark.asyncio
    async def test_resolve_adapter(self):
        """Test resolve_adapter finds matching adapter."""
        config = OneiricMCPConfig(enabled=True, grpc_port=8679)

        with patch("mahavishnu.core.oneiric_client.registry_pb2_grpc"):
            client = OneiricMCPClient(config)

            # Mock list_adapters
            async def mock_list_adapters(**kwargs):
                entry = AdapterEntry(
                    adapter_id="test.adapter.storage.s3",
                    project="test",
                    domain="adapter",
                    category="storage",
                    provider="s3",
                    capabilities=["read"],
                    factory_path="test.S3",
                    registered_at=datetime.now(UTC),
                    last_heartbeat=datetime.now(UTC),
                )
                return [entry]

            client.list_adapters = mock_list_adapters

            # Resolve adapter
            adapter = await client.resolve_adapter(
                domain="adapter",
                category="storage",
                provider="s3",
            )

            # Verify
            assert adapter is not None
            assert adapter.provider == "s3"

    @pytest.mark.asyncio
    async def test_invalidate_cache(self):
        """Test cache invalidation."""
        config = OneiricMCPConfig(enabled=True, grpc_port=8679)

        with patch("mahavishnu.core.oneiric_client.registry_pb2_grpc"):
            client = OneiricMCPClient(config)

            # Mock the gRPC stub
            mock_stub = AsyncMock()
            client._stub = mock_stub
            client._connected = True

            # Create mock response
            mock_response = MagicMock()
            mock_response.adapters = []
            mock_stub.ListAdapters.return_value = mock_response

            # First call
            await client.list_adapters()
            assert len(client._cache) > 0

            # Invalidate cache
            await client.invalidate_cache()
            assert len(client._cache) == 0

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health_check returns status."""
        config = OneiricMCPConfig(enabled=True, grpc_port=8679)

        with patch("mahavishnu.core.oneiric_client.registry_pb2_grpc"):
            client = OneiricMCPClient(config)

            # Mock list_adapters
            async def mock_list(**kwargs):
                return []

            client.list_adapters = mock_list
            client._connected = True

            # Health check
            health = await client.health_check()

            # Verify
            assert health["status"] == "healthy"
            assert health["connected"] is True
            assert "adapter_count" in health

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing client connection."""
        config = OneiricMCPConfig(enabled=True, grpc_port=8679)

        with patch("mahavishnu.core.oneiric_client.grpc.aio"):
            client = OneiricMCPClient(config)

            # Mock channel
            mock_channel = AsyncMock()
            client._channel = mock_channel
            client._connected = True

            # Close
            await client.close()

            # Verify
            mock_channel.close.assert_called_once()
            assert client._connected is False


class TestOneiricMCPConfig:
    """Test OneiricMCPConfig validation."""

    def test_default_config(self):
        """Test default configuration values."""
        config = OneiricMCPConfig()

        assert config.enabled is False
        assert config.grpc_host == "localhost"
        assert config.grpc_port == 8679
        assert config.use_tls is False
        assert config.timeout_sec == 30
        assert config.cache_ttl_sec == 300
        assert config.jwt_enabled is False
        assert config.jwt_project == "mahavishnu"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = OneiricMCPConfig(
            enabled=True,
            grpc_host="oneiric-mcp.example.com",
            grpc_port=8680,
            use_tls=True,
            timeout_sec=60,
            cache_ttl_sec=600,
        )

        assert config.enabled is True
        assert config.grpc_host == "oneiric-mcp.example.com"
        assert config.grpc_port == 8680
        assert config.use_tls is True
        assert config.timeout_sec == 60
        assert config.cache_ttl_sec == 600
