"""Adapter discovery engine for HybridAdapterRegistry.

This module implements the adapter discovery engine that discovers adapters from
multiple sources:

1. **Python Entry Points** - Plugin discovery via `[project.entry-points."mahavishnu.adapters"]`
2. **Oneiric MCP** - Remote adapter discovery via gRPC (uses existing `OneiricMCPClient`)

Features:
- Thread-safe with `threading.RLock`
- Adapter allowlist security (configurable patterns)
- Graceful fallback when Oneiric MCP unavailable
- Cache adapter metadata with TTL

Example usage:
    from mahavishnu.core.adapter_discovery import AdapterDiscoveryEngine

    engine = AdapterDiscoveryEngine(config={
        "allowlist_patterns": ["mahavishnu.adapters.*", "custom.adapters.*"],
        "cache_ttl_seconds": 300,
    })

    adapters = await engine.discover_all()

    # Or discover from specific sources
    entry_point_adapters = await engine.discover_from_entry_points()
    oneiric_adapters = await engine.discover_from_oneiric_mcp()
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from fnmatch import fnmatch
import logging
import threading
from typing import TYPE_CHECKING, Any, cast

from mahavishnu.core.oneiric_client import (
    ONEIRIC_MCP_AVAILABLE,
    OneiricMCPClient,
    OneiricMCPConfig,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from importlib.metadata import EntryPoint

logger = logging.getLogger(__name__)

# Entry point group for Mahavishnu adapters
ENTRY_POINT_GROUP = "mahavishnu.adapters"


@dataclass
class AdapterMetadata:
    """Metadata for a discovered adapter.

    This dataclass captures all relevant information about an adapter
    discovered from either entry points or Oneiric MCP.

    Attributes:
        adapter_id: Unique identifier for the adapter (e.g., "mahavishnu.prefect")
        domain: Domain category (e.g., "orchestration", "storage", "ai")
        category: Sub-category within domain (e.g., "workflow", "vector", "agent")
        provider: Provider/implementation name (e.g., "prefect", "agno", "llamaindex")
        capabilities: List of capability strings this adapter provides
        factory_path: Import path to adapter factory (e.g., "mahavishnu.engines.prefect:PrefectAdapter")
        priority: Priority for adapter selection (higher = preferred, default 0)
        health_check_url: Optional URL for health check endpoint
        metadata: Additional adapter-specific metadata
        source: Discovery source ("entry_point" or "oneiric_mcp")
        discovered_at: Timestamp when adapter was discovered
    """

    adapter_id: str
    domain: str
    category: str
    provider: str
    capabilities: list[str]
    factory_path: str
    priority: int = 0
    health_check_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])
    source: str = "unknown"
    discovered_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert metadata to dictionary representation.

        Returns:
            Dictionary with all adapter metadata fields
        """
        return {
            "adapter_id": self.adapter_id,
            "domain": self.domain,
            "category": self.category,
            "provider": self.provider,
            "capabilities": self.capabilities,
            "factory_path": self.factory_path,
            "priority": self.priority,
            "health_check_url": self.health_check_url,
            "metadata": self.metadata,
            "source": self.source,
            "discovered_at": self.discovered_at.isoformat(),
        }

    @classmethod
    def from_entry_point(cls, entry_point: Any) -> "AdapterMetadata":
        """Create AdapterMetadata from a Python entry point.

        Entry points should return a dict with the following keys:
        - adapter_id (required)
        - domain (required)
        - category (required)
        - provider (required)
        - capabilities (required)
        - factory_path (required)
        - priority (optional, default 0)
        - health_check_url (optional)
        - metadata (optional)

        Args:
            entry_point: importlib.metadata.EntryPoint object

        Returns:
            AdapterMetadata instance

        Raises:
            ValueError: If entry point metadata is invalid
        """
        try:
            # Load the entry point function
            factory = entry_point.load()

            # Call factory to get metadata dict
            meta_dict = cast("dict[str, Any]", factory() if callable(factory) else factory)

            # Validate required fields
            required_fields = [
                "adapter_id",
                "domain",
                "category",
                "provider",
                "capabilities",
                "factory_path",
            ]
            missing = [f for f in required_fields if f not in meta_dict]
            if missing:
                raise ValueError(
                    f"Entry point {entry_point.name} missing required fields: {missing}"
                )

            return cls(
                adapter_id=str(meta_dict["adapter_id"]),
                domain=str(meta_dict["domain"]),
                category=str(meta_dict["category"]),
                provider=str(meta_dict["provider"]),
                capabilities=list(meta_dict["capabilities"]),
                factory_path=str(meta_dict["factory_path"]),
                priority=int(meta_dict.get("priority", 0)),
                health_check_url=meta_dict.get("health_check_url"),
                metadata=dict(meta_dict.get("metadata", {})),
                source="entry_point",
            )

        except Exception as e:
            logger.error(f"Failed to load entry point {entry_point.name}: {e}")
            raise ValueError(f"Invalid entry point {entry_point.name}: {e}") from e

    @classmethod
    def from_adapter_entry(cls, entry: Any) -> "AdapterMetadata":
        """Create AdapterMetadata from Oneiric MCP AdapterEntry.

        Args:
            entry: AdapterEntry from OneiricMCPClient

        Returns:
            AdapterMetadata instance
        """
        # Cast metadata to dict type
        entry_metadata: dict[str, Any] = dict(entry.metadata) if entry.metadata else {}

        return cls(
            adapter_id=entry.adapter_id,
            domain=entry.domain,
            category=entry.category,
            provider=entry.provider,
            capabilities=list(entry.capabilities),
            factory_path=entry.factory_path,
            priority=entry_metadata.get("priority", 0),
            health_check_url=entry.health_check_url,
            metadata=entry_metadata,
            source="oneiric_mcp",
        )


class AdapterDiscoveryEngine:
    """Engine for discovering adapters from multiple sources.

    Discovers adapters from:
    1. Python entry points (`[project.entry-points."mahavishnu.adapters"]`)
    2. Oneiric MCP gRPC registry (if available)

    Features:
    - Thread-safe discovery with RLock
    - Adapter allowlist for security
    - Cache with configurable TTL
    - Graceful fallback when sources unavailable

    Example:
        engine = AdapterDiscoveryEngine()

        # Discover from all sources
        all_adapters = await engine.discover_all()

        # Discover from specific source
        entry_adapters = await engine.discover_from_entry_points()

        # Invalidate cache
        engine.invalidate_cache()
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize the discovery engine.

        Args:
            config: Optional configuration dictionary with keys:
                - allowlist_patterns: List of glob patterns for allowed adapter IDs
                    (default: ["mahavishnu.adapters.*"])
                - cache_ttl_seconds: Cache TTL in seconds (default: 300)
                - oneiric_mcp_config: OneiricMCPConfig or dict for Oneiric MCP client
                - enable_entry_points: Enable entry point discovery (default: True)
                - enable_oneiric_mcp: Enable Oneiric MCP discovery (default: True)
        """
        config = config or {}

        # Configuration
        self._allowlist_patterns: list[str] = config.get(
            "allowlist_patterns",
            ["mahavishnu.adapters.*", "mahavishnu.engines.*"],
        )
        self._cache_ttl_seconds: int = config.get("cache_ttl_seconds", 300)
        self._enable_entry_points: bool = config.get("enable_entry_points", True)
        self._enable_oneiric_mcp: bool = config.get("enable_oneiric_mcp", True)

        # Oneiric MCP client configuration
        oneiric_config = config.get("oneiric_mcp_config")
        if oneiric_config and isinstance(oneiric_config, dict):
            self._oneiric_mcp_config = OneiricMCPConfig(**oneiric_config)
        elif oneiric_config and isinstance(oneiric_config, OneiricMCPConfig):
            self._oneiric_mcp_config = oneiric_config
        else:
            self._oneiric_mcp_config = OneiricMCPConfig()

        # Thread safety
        self._lock = threading.RLock()

        # Cache
        self._cache: dict[str, tuple[list[AdapterMetadata], datetime]] = {}

        # Oneiric MCP client (lazy initialization)
        self._oneiric_client: OneiricMCPClient | None = None

        logger.info(
            f"AdapterDiscoveryEngine initialized "
            f"(entry_points={self._enable_entry_points}, "
            f"oneiric_mcp={self._enable_oneiric_mcp}, "
            f"cache_ttl={self._cache_ttl_seconds}s, "
            f"allowlist_patterns={len(self._allowlist_patterns)})"
        )

    def _get_oneiric_client(self) -> OneiricMCPClient | None:
        """Get or create Oneiric MCP client (lazy initialization).

        Returns:
            OneiricMCPClient instance or None if unavailable
        """
        if not self._enable_oneiric_mcp:
            return None

        if not ONEIRIC_MCP_AVAILABLE:
            logger.debug("Oneiric MCP not available, skipping remote discovery")
            return None

        if self._oneiric_client is None:
            try:
                self._oneiric_client = OneiricMCPClient(self._oneiric_mcp_config)
                logger.info("Oneiric MCP client initialized for adapter discovery")
            except Exception as e:
                logger.warning(f"Failed to initialize Oneiric MCP client: {e}")
                return None

        return self._oneiric_client

    def _is_adapter_allowed(self, adapter_id: str) -> bool:
        """Check if adapter ID matches allowlist patterns.

        Security check to ensure only allowed adapters are discovered.
        Uses glob patterns for matching.

        Args:
            adapter_id: Adapter identifier to check

        Returns:
            True if adapter is allowed, False otherwise
        """
        if not self._allowlist_patterns:
            # No allowlist means all adapters are allowed (not recommended for production)
            logger.warning("No allowlist patterns configured, allowing all adapters")
            return True

        for pattern in self._allowlist_patterns:
            if fnmatch(adapter_id, pattern):
                return True

        logger.debug(f"Adapter {adapter_id} rejected by allowlist")
        return False

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid.

        Args:
            cache_key: Cache key to check

        Returns:
            True if cache is valid, False if expired or missing
        """
        if cache_key not in self._cache:
            return False

        _, cached_at = self._cache[cache_key]
        age = (datetime.now(UTC) - cached_at).total_seconds()
        return age < self._cache_ttl_seconds

    async def discover_all(self) -> list[AdapterMetadata]:
        """Discover adapters from all configured sources.

        Combines results from entry points and Oneiric MCP, deduplicating
        by adapter_id (entry points take precedence).

        Returns:
            List of discovered adapter metadata
        """
        cache_key = "discover_all"

        # Check cache
        with self._lock:
            if self._is_cache_valid(cache_key):
                adapters, _ = self._cache[cache_key]
                logger.debug(f"Returning {len(adapters)} cached adapters")
                return adapters

        # Discover from all sources
        all_adapters: dict[str, AdapterMetadata] = {}

        # Entry points (higher priority - processed first)
        if self._enable_entry_points:
            try:
                entry_adapters = await self.discover_from_entry_points()
                for adapter in entry_adapters:
                    all_adapters[adapter.adapter_id] = adapter
            except Exception as e:
                logger.error(f"Entry point discovery failed: {e}")

        # Oneiric MCP (fills in gaps not covered by entry points)
        if self._enable_oneiric_mcp:
            try:
                oneiric_adapters = await self.discover_from_oneiric_mcp()
                for adapter in oneiric_adapters:
                    # Only add if not already discovered via entry points
                    if adapter.adapter_id not in all_adapters:
                        all_adapters[adapter.adapter_id] = adapter
            except Exception as e:
                logger.warning(f"Oneiric MCP discovery failed (graceful fallback): {e}")

        result = list(all_adapters.values())

        # Update cache
        with self._lock:
            self._cache[cache_key] = (result, datetime.now(UTC))

        logger.info(f"Discovered {len(result)} adapters from all sources")
        return result

    async def discover_from_entry_points(self) -> list[AdapterMetadata]:
        """Discover adapters from Python entry points.

        Scans `[project.entry-points."mahavishnu.adapters"]` for registered
        adapter plugins.

        Returns:
            List of adapter metadata from entry points

        Raises:
            ImportError: If entry point metadata is malformed
        """
        cache_key = "entry_points"

        # Check cache
        with self._lock:
            if self._is_cache_valid(cache_key):
                adapters, _ = self._cache[cache_key]
                return adapters

        adapters: list[AdapterMetadata] = []

        try:
            # Use importlib.metadata for entry point discovery
            import importlib.metadata as metadata

            # Get entry points for our group
            eps: Iterable[EntryPoint]
            try:
                # Python 3.10+ style
                eps = metadata.entry_points(group=ENTRY_POINT_GROUP)
            except TypeError:
                # Python 3.9 style (returns SelectableGroups)
                all_eps = metadata.entry_points()
                eps = all_eps.select(group=ENTRY_POINT_GROUP)  # type: ignore[union-attr]

            for ep in eps:
                try:
                    adapter_meta = AdapterMetadata.from_entry_point(ep)

                    # Check allowlist
                    if not self._is_adapter_allowed(adapter_meta.adapter_id):
                        logger.warning(f"Adapter {adapter_meta.adapter_id} blocked by allowlist")
                        continue

                    adapters.append(adapter_meta)
                    logger.debug(f"Discovered adapter from entry point: {adapter_meta.adapter_id}")

                except ValueError as e:
                    logger.warning(f"Skipping invalid entry point {ep.name}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error loading entry point {ep.name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Failed to discover entry points: {e}")
            raise

        # Update cache
        with self._lock:
            self._cache[cache_key] = (adapters, datetime.now(UTC))

        logger.info(f"Discovered {len(adapters)} adapters from entry points")
        return adapters

    async def discover_from_oneiric_mcp(self) -> list[AdapterMetadata]:
        """Discover adapters from Oneiric MCP gRPC registry.

        Uses the existing OneiricMCPClient to fetch adapter metadata
        from the remote registry.

        Returns:
            List of adapter metadata from Oneiric MCP

        Note:
            Returns empty list if Oneiric MCP is unavailable (graceful fallback)
        """
        cache_key = "oneiric_mcp"

        # Check cache
        with self._lock:
            if self._is_cache_valid(cache_key):
                adapters, _ = self._cache[cache_key]
                return adapters

        adapters: list[AdapterMetadata] = []

        # Get client
        client = self._get_oneiric_client()
        if client is None:
            logger.debug("Oneiric MCP client not available, returning empty list")
            return adapters

        try:
            # List all adapters from Oneiric MCP
            entries = await client.list_adapters(healthy_only=False, use_cache=True)

            for entry in entries:
                # Check allowlist
                if not self._is_adapter_allowed(entry.adapter_id):
                    logger.warning(f"Adapter {entry.adapter_id} blocked by allowlist")
                    continue

                adapter_meta = AdapterMetadata.from_adapter_entry(entry)
                adapters.append(adapter_meta)
                logger.debug(f"Discovered adapter from Oneiric MCP: {adapter_meta.adapter_id}")

        except ConnectionError as e:
            logger.warning(f"Oneiric MCP connection error (graceful fallback): {e}")
            # Return empty list - graceful fallback
        except Exception as e:
            logger.error(f"Oneiric MCP discovery failed: {e}")
            # Still return empty list - graceful fallback

        # Update cache
        with self._lock:
            self._cache[cache_key] = (adapters, datetime.now(UTC))

        logger.info(f"Discovered {len(adapters)} adapters from Oneiric MCP")
        return adapters

    def invalidate_cache(self) -> None:
        """Clear all cached discovery results.

        Thread-safe cache invalidation.
        """
        with self._lock:
            self._cache.clear()
            logger.info("Adapter discovery cache invalidated")

    def invalidate_cache_for_source(self, source: str) -> None:
        """Clear cached discovery results for a specific source.

        Args:
            source: Cache key/source to invalidate ("entry_points", "oneiric_mcp", etc.)
        """
        with self._lock:
            if source in self._cache:
                del self._cache[source]
                logger.debug(f"Cache invalidated for source: {source}")

    async def close(self) -> None:
        """Close the discovery engine and release resources.

        Closes the Oneiric MCP client if initialized.
        """
        with self._lock:
            if self._oneiric_client is not None:
                try:
                    await self._oneiric_client.close()
                    logger.info("Oneiric MCP client closed")
                except Exception as e:
                    logger.warning(f"Error closing Oneiric MCP client: {e}")
                finally:
                    self._oneiric_client = None

            self._cache.clear()

    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache statistics
        """
        with self._lock:
            stats: dict[str, Any] = {
                "entries": len(self._cache),
                "ttl_seconds": self._cache_ttl_seconds,
                "keys": list(self._cache.keys()),
            }

            # Add age info for each cache entry
            entries_detail: dict[str, dict[str, float]] = {}
            for key, (_, cached_at) in self._cache.items():
                age = (datetime.now(UTC) - cached_at).total_seconds()
                entries_detail[key] = {
                    "age_seconds": age,
                    "expires_in_seconds": max(0.0, self._cache_ttl_seconds - age),
                }
            stats["entries_detail"] = entries_detail

            return stats


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AdapterMetadata",
    "AdapterDiscoveryEngine",
    "ENTRY_POINT_GROUP",
]
