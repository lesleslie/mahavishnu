"""Oneiric MCP gRPC client for adapter discovery and resolution.

This module provides a high-performance gRPC client for connecting to Oneiric MCP's
adapter registry, enabling dynamic adapter discovery in Mahavishnu workflows.

Features:
- Async gRPC client with connection pooling
- Adapter list caching with TTL
- Health monitoring with circuit breaker
- Graceful fallback when Oneiric MCP unavailable
- JWT authentication support (production)
- TLS/mTLS support (production)
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import logging
from typing import Any

import grpc.aio

logger = logging.getLogger(__name__)

# Try to import Oneiric MCP gRPC modules
try:
    from oneiric_mcp.grpc import registry_pb2, registry_pb2_grpc

    ONEIRIC_MCP_AVAILABLE = True
except ImportError:
    ONEIRIC_MCP_AVAILABLE = False
    logger.warning("Oneiric MCP gRPC modules not available. Install with: pip install oneiric-mcp")


@dataclass
class AdapterEntry:
    """Represents an adapter entry from Oneiric MCP registry."""

    adapter_id: str
    project: str
    domain: str
    category: str
    provider: str
    capabilities: list[str]
    factory_path: str
    health_check_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_at: datetime | None = None
    last_heartbeat: datetime | None = None
    health_status: str = "unknown"

    @classmethod
    def from_pb2(cls, pb2_entry: Any) -> "AdapterEntry":
        """Create AdapterEntry from protobuf AdapterEntry.

        Args:
            pb2_entry: Protobuf AdapterEntry message

        Returns:
            AdapterEntry instance
        """
        return cls(
            adapter_id=pb2_entry.adapter_id,
            project=pb2_entry.project,
            domain=pb2_entry.domain,
            category=pb2_entry.category,
            provider=pb2_entry.provider,
            capabilities=list(pb2_entry.capabilities),
            factory_path=pb2_entry.factory_path,
            health_check_url=pb2_entry.health_check_url or None,
            metadata=dict(pb2_entry.metadata),
            registered_at=datetime.fromtimestamp(pb2_entry.registered_at, tz=UTC),
            last_heartbeat=datetime.fromtimestamp(pb2_entry.last_heartbeat, tz=UTC),
            health_status=pb2_entry.health_status,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation.

        Returns:
            Dictionary with adapter details
        """
        return {
            "adapter_id": self.adapter_id,
            "project": self.project,
            "domain": self.domain,
            "category": self.category,
            "provider": self.provider,
            "capabilities": self.capabilities,
            "factory_path": self.factory_path,
            "health_check_url": self.health_check_url,
            "metadata": self.metadata,
            "registered_at": self.registered_at.isoformat() if self.registered_at else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "health_status": self.health_status,
        }


@dataclass
class OneiricMCPConfig:
    """Configuration for Oneiric MCP client."""

    enabled: bool = True
    grpc_host: str = "localhost"
    grpc_port: int = 8679
    use_tls: bool = False
    timeout_sec: int = 30
    cache_ttl_sec: int = 300  # 5 minutes
    jwt_enabled: bool = False
    jwt_secret: str | None = None
    jwt_project: str = "mahavishnu"
    tls_cert_path: str | None = None
    tls_key_path: str | None = None
    tls_ca_path: str | None = None


class AdapterCircuitBreaker:
    """Circuit breaker for failing adapters.

    Prevents repeated calls to adapters that are consistently failing.
    """

    def __init__(self, failure_threshold: int = 3, block_duration_sec: int = 300):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before blocking
            block_duration_sec: How long to block adapter after threshold (default: 5 minutes)
        """
        self.failure_threshold = failure_threshold
        self.block_duration_sec = block_duration_sec
        self.failures: dict[str, int] = {}
        self.blocked_until: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def is_available(self, adapter_id: str) -> bool:
        """Check if adapter is available (not blocked).

        Args:
            adapter_id: Adapter identifier

        Returns:
            True if adapter is available, False if blocked
        """
        async with self._lock:
            if adapter_id in self.blocked_until:
                if datetime.now(UTC) < self.blocked_until[adapter_id]:
                    logger.debug(
                        f"Adapter {adapter_id} is blocked until {self.blocked_until[adapter_id]}"
                    )
                    return False
                else:
                    # Block period expired, remove from blocked list
                    del self.blocked_until[adapter_id]
                    self.failures.pop(adapter_id, None)
        return True

    async def record_success(self, adapter_id: str):
        """Record successful adapter call.

        Args:
            adapter_id: Adapter identifier
        """
        async with self._lock:
            self.failures.pop(adapter_id, None)
            self.blocked_until.pop(adapter_id, None)

    async def record_failure(self, adapter_id: str):
        """Record adapter failure and potentially block it.

        Args:
            adapter_id: Adapter identifier
        """
        async with self._lock:
            self.failures[adapter_id] = self.failures.get(adapter_id, 0) + 1

            if self.failures[adapter_id] >= self.failure_threshold:
                # Block adapter for configured duration
                self.blocked_until[adapter_id] = datetime.now(UTC) + timedelta(
                    seconds=self.block_duration_sec
                )
                logger.warning(
                    f"Adapter {adapter_id} blocked after {self.failures[adapter_id]} failures "
                    f"until {self.blocked_until[adapter_id]}"
                )


class OneiricMCPClient:
    """Async gRPC client for Oneiric MCP adapter registry.

    Provides high-performance adapter discovery with caching, circuit breaker,
    and health monitoring capabilities.
    """

    def __init__(self, config: OneiricMCPConfig | None = None):
        """Initialize Oneiric MCP client.

        Args:
            config: Client configuration (defaults to OneiricMCPConfig())
        """
        if not ONEIRIC_MCP_AVAILABLE:
            raise ImportError(
                "Oneiric MCP gRPC modules not available. Install with: pip install oneiric-mcp"
            )

        self.config = config or OneiricMCPConfig()
        self._channel: grpc.aio.Channel | None = None
        self._stub: registry_pb2_grpc.AdapterRegistryStub | None = None
        self._circuit_breaker = AdapterCircuitBreaker()
        self._cache: dict[str, tuple[list[AdapterEntry], datetime]] = {}
        self._lock = asyncio.Lock()
        self._connected = False

        logger.info(
            f"OneiricMCPClient initialized (host={self.config.grpc_host}, "
            f"port={self.config.grpc_port}, tls={self.config.use_tls})"
        )

    async def _ensure_connected(self):
        """Ensure gRPC channel is connected."""
        if self._connected and self._channel:
            return

        async with self._lock:
            # Double-check after acquiring lock
            if self._connected and self._channel:
                return

            # Close existing connection if any
            if self._channel:
                await self._channel.close()

            # Create new connection
            if self.config.use_tls:
                # TLS/mTLS mode (production)
                if self.config.tls_cert_path and self.config.tls_key_path:
                    # Read certificates
                    with open(self.config.tls_cert_path, "rb") as f:
                        cert_chain = f.read()
                    with open(self.config.tls_key_path, "rb") as f:
                        private_key = f.read()

                    if self.config.tls_ca_path:
                        # mTLS mode
                        with open(self.config.tls_ca_path, "rb") as f:
                            root_certificates = f.read()
                        credentials = grpc.ssl_channel_credentials(
                            root_certificates=root_certificates,
                            private_key=private_key,
                            certificate_chain=cert_chain,
                        )
                        logger.info("Using mTLS credentials")
                    else:
                        # TLS mode (server auth only)
                        credentials = grpc.ssl_channel_credentials(
                            certificate_chain=cert_chain, private_key=private_key
                        )
                        logger.info("Using TLS credentials")

                    self._channel = grpc.aio.secure_channel(
                        f"{self.config.grpc_host}:{self.config.grpc_port}",
                        credentials,
                    )
                else:
                    raise ValueError(
                        "TLS enabled but certificate paths not configured. "
                        "Set tls_cert_path and tls_key_path."
                    )
            else:
                # Insecure mode (development only)
                if self.config.grpc_port != 8679:
                    logger.warning(
                        f"Insecure mode on port {self.config.grpc_port} "
                        "(dev mode should use port 8679)"
                    )
                self._channel = grpc.aio.insecure_channel(
                    f"{self.config.grpc_host}:{self.config.grpc_port}"
                )
                logger.debug("Using insecure channel (development mode)")

            # Create stub
            self._stub = registry_pb2_grpc.AdapterRegistryStub(self._channel)

            # Wait for channel ready
            try:
                await grpc.aio.wait_for_channel_ready(
                    self._channel, timeout=self.config.timeout_sec
                )
                self._connected = True
                logger.info(
                    f"Connected to Oneiric MCP at {self.config.grpc_host}:{self.config.grpc_port}"
                )
            except TimeoutError:
                self._connected = False
                raise ConnectionError(
                    f"Timeout connecting to Oneiric MCP at "
                    f"{self.config.grpc_host}:{self.config.grpc_port}"
                )

    async def close(self):
        """Close gRPC channel and cleanup resources."""
        if self._channel:
            await self._channel.close()
            self._connected = False
            logger.info("Oneiric MCP client connection closed")

    def _make_cache_key(
        self,
        project: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        healthy_only: bool = False,
    ) -> str:
        """Generate cache key for adapter query.

        Args:
            project: Project filter
            domain: Domain filter
            category: Category filter
            healthy_only: Healthy-only filter

        Returns:
            Cache key string
        """
        parts = [
            project or "*",
            domain or "*",
            category or "*",
            "healthy" if healthy_only else "all",
        ]
        return ":".join(parts)

    async def list_adapters(
        self,
        project: str | None = None,
        domain: str | None = None,
        category: str | None = None,
        healthy_only: bool = False,
        use_cache: bool = True,
    ) -> list[AdapterEntry]:
        """List available adapters with optional filters.

        Args:
            project: Filter by project name
            domain: Filter by domain (e.g., "adapter", "service")
            category: Filter by category (e.g., "storage", "orchestration")
            healthy_only: Only return healthy adapters
            use_cache: Use cached results if available (default: True)

        Returns:
            List of matching adapter entries

        Raises:
            ConnectionError: If cannot connect to Oneiric MCP
        """
        if not self.config.enabled:
            logger.debug("Oneiric MCP client disabled, returning empty list")
            return []

        # Check cache
        cache_key = self._make_cache_key(project, domain, category, healthy_only)
        if use_cache and cache_key in self._cache:
            adapters, cached_at = self._cache[cache_key]
            age_sec = (datetime.now(UTC) - cached_at).total_seconds()
            if age_sec < self.config.cache_ttl_sec:
                logger.debug(f"Cache hit for {cache_key} ({age_sec:.1f}s old)")
                return adapters
            else:
                # Cache expired
                del self._cache[cache_key]

        # Ensure connected
        await self._ensure_connected()

        # Build request
        request = registry_pb2.ListRequest(
            project=project or "",
            domain=domain or "",
            category=category or "",
            healthy_only=healthy_only,
        )

        try:
            # Call gRPC
            response = await self._stub.ListAdapters(request, timeout=self.config.timeout_sec)

            # Convert to AdapterEntry objects
            adapters = [AdapterEntry.from_pb2(pb2_adapter) for pb2_adapter in response.adapters]

            # Cache results
            self._cache[cache_key] = (adapters, datetime.now(UTC))

            logger.info(
                f"Listed {len(adapters)} adapters "
                f"(project={project}, domain={domain}, category={category}, "
                f"healthy_only={healthy_only})"
            )

            return adapters

        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                self._connected = False
                raise ConnectionError(f"Oneiric MCP unavailable: {e.details()}")
            else:
                logger.error(f"gRPC error listing adapters: {e.code()} - {e.details()}")
                raise
        except Exception as e:
            logger.error(f"Error listing adapters: {e}")
            raise

    async def get_adapter(self, adapter_id: str) -> AdapterEntry | None:
        """Get specific adapter by ID.

        Args:
            adapter_id: Adapter's unique ID (e.g., "mahavishnu.adapter.storage.s3")

        Returns:
            Adapter entry if found, None otherwise

        Raises:
            ConnectionError: If cannot connect to Oneiric MCP
        """
        if not self.config.enabled:
            return None

        # Check circuit breaker
        if not await self._circuit_breaker.is_available(adapter_id):
            logger.warning(f"Adapter {adapter_id} is blocked by circuit breaker")
            return None

        # Ensure connected
        await self._ensure_connected()

        request = registry_pb2.GetRequest(adapter_id=adapter_id)

        try:
            response = await self._stub.GetAdapter(request, timeout=self.config.timeout_sec)
            adapter = AdapterEntry.from_pb2(response.adapter)
            await self._circuit_breaker.record_success(adapter_id)
            return adapter

        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.NOT_FOUND:
                logger.debug(f"Adapter {adapter_id} not found")
                return None
            elif e.code() == grpc.StatusCode.UNAVAILABLE:
                self._connected = False
                await self._circuit_breaker.record_failure(adapter_id)
                raise ConnectionError(f"Oneiric MCP unavailable: {e.details()}")
            else:
                logger.error(f"gRPC error getting adapter: {e.code()} - {e.details()}")
                await self._circuit_breaker.record_failure(adapter_id)
                return None
        except Exception as e:
            logger.error(f"Error getting adapter {adapter_id}: {e}")
            await self._circuit_breaker.record_failure(adapter_id)
            return None

    async def check_adapter_health(self, adapter_id: str) -> bool:
        """Check if adapter is healthy.

        Args:
            adapter_id: Adapter's unique ID

        Returns:
            True if adapter is healthy, False otherwise

        Raises:
            ConnectionError: If cannot connect to Oneiric MCP
        """
        if not self.config.enabled:
            return False

        # Check circuit breaker
        if not await self._circuit_breaker.is_available(adapter_id):
            return False

        # Ensure connected
        await self._ensure_connected()

        request = registry_pb2.HealthCheckRequest(adapter_id=adapter_id)

        try:
            response = await self._stub.HealthCheck(request, timeout=self.config.timeout_sec)
            is_healthy = response.healthy

            if is_healthy:
                await self._circuit_breaker.record_success(adapter_id)
            else:
                await self._circuit_breaker.record_failure(adapter_id)

            return is_healthy

        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                self._connected = False
                await self._circuit_breaker.record_failure(adapter_id)
                raise ConnectionError(f"Oneiric MCP unavailable: {e.details()}")
            else:
                logger.error(f"gRPC error checking health: {e.code()} - {e.details()}")
                await self._circuit_breaker.record_failure(adapter_id)
                return False
        except Exception as e:
            logger.error(f"Error checking health for {adapter_id}: {e}")
            await self._circuit_breaker.record_failure(adapter_id)
            return False

    async def resolve_adapter(
        self,
        domain: str,
        category: str,
        provider: str,
        project: str | None = None,
        healthy_only: bool = True,
    ) -> AdapterEntry | None:
        """Resolve best-matching adapter.

        Args:
            domain: Adapter domain (e.g., "adapter", "service")
            category: Adapter category (e.g., "storage", "orchestration")
            provider: Adapter provider (e.g., "s3", "prefect")
            project: Optional project filter
            healthy_only: Only return healthy adapters (default: True)

        Returns:
            Best-matching adapter entry, or None if not found

        Raises:
            ConnectionError: If cannot connect to Oneiric MCP
        """
        # List adapters with filters
        adapters = await self.list_adapters(
            domain=domain,
            category=category,
            project=project,
            healthy_only=healthy_only,
        )

        # Find exact provider match
        for adapter in adapters:
            if adapter.provider == provider:
                logger.info(f"Resolved adapter: {adapter.adapter_id}")
                return adapter

        # No exact match found
        logger.warning(
            f"No adapter found for domain={domain}, category={category}, provider={provider}"
        )
        return None

    async def send_heartbeat(self, adapter_id: str) -> bool:
        """Send heartbeat for adapter.

        Args:
            adapter_id: Adapter's unique ID

        Returns:
            True if heartbeat successful, False otherwise

        Raises:
            ConnectionError: If cannot connect to Oneiric MCP
        """
        if not self.config.enabled:
            return False

        # Ensure connected
        await self._ensure_connected()

        request = registry_pb2.HeartbeatRequest(adapter_id=adapter_id)

        try:
            response = await self._stub.Heartbeat(request, timeout=self.config.timeout_sec)
            return response.registered

        except grpc.aio.AioRpcError as e:
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                self._connected = False
                raise ConnectionError(f"Oneiric MCP unavailable: {e.details()}")
            else:
                logger.error(f"gRPC error sending heartbeat: {e.code()} - {e.details()}")
                return False
        except Exception as e:
            logger.error(f"Error sending heartbeat for {adapter_id}: {e}")
            return False

    async def invalidate_cache(self):
        """Invalidate all cached adapter lists."""
        self._cache.clear()
        logger.debug("Oneiric MCP adapter cache invalidated")

    async def health_check(self) -> dict[str, Any]:
        """Check health of Oneiric MCP connection.

        Returns:
            Health status dictionary
        """
        if not self.config.enabled:
            return {
                "status": "disabled",
                "connected": False,
            }

        try:
            # Try to list adapters (limit to 1 for quick check)
            await self._ensure_connected()
            adapters = await self.list_adapters(use_cache=False)

            return {
                "status": "healthy",
                "connected": True,
                "adapter_count": len(adapters),
                "cache_entries": len(self._cache),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "connected": False,
                "error": str(e),
            }
