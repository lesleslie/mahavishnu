"""Hybrid adapter registry combining Oneiric resolution + Dhruva persistence.

This module implements the HybridAdapterRegistry using the composite pattern,
combining three specialized components:

1. **AdapterDiscoveryEngine** - Entry points + Oneiric MCP discovery
2. **AdapterPersistenceLayer** - Dhruva/SQLite state and health storage
3. **HealthIntegration** - Health monitoring, metrics, and alerts

Architecture:
    ┌───────────────────────────────────────────────────────────────────┐
    │                     HybridAdapterRegistry                          │
    │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐   │
    │  │  Discovery      │  │  Persistence    │  │  Health         │   │
    │  │  Engine         │  │  Layer          │  │  Integration    │   │
    │  │  (entry points, │  │  (Dhruva/SQLite)│  │  (metrics,      │   │
    │  │   Oneiric MCP)  │  │                 │  │   alerts)       │   │
    │  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘   │
    │           │                    │                    │            │
    │           └────────────────────┼────────────────────┘            │
    │                                ▼                                  │
    │                    ┌─────────────────────┐                       │
    │                    │  AdapterInstance[]  │                       │
    │                    └─────────────────────┘                       │
    └───────────────────────────────────────────────────────────────────┘

Thread Safety:
    Uses RLock for thread-safe adapter registration and resolution.

Created: 2026-02-22
Version: 1.0
Related: Hybrid Adapter Integration Plan Phases 1-5
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from mahavishnu.core.adapter_discovery import (
    AdapterDiscoveryEngine,
    AdapterMetadata,
)
from mahavishnu.core.adapter_persistence import (
    AdapterPersistenceLayer,
    AdapterState,
    HealthRecord,
)
from mahavishnu.core.task_requirements import (
    ResolutionCache,
    RoutingDecision,
    TaskRequirements,
)

if TYPE_CHECKING:
    from mahavishnu.core.adapters.base import OrchestratorAdapter
    from mahavishnu.core.routing_metrics import RoutingMetrics
    from mahavishnu.websocket.server import MahavishnuWebSocketServer

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class RegistrationReport:
    """Report of adapter registration results.

    Attributes:
        discovered: Total adapters discovered from all sources
        registered: Adapters successfully registered
        failed: List of (adapter_id, error_message) for failed registrations
        sources: Count of adapters discovered per source
    """

    discovered: int
    registered: int
    failed: list[tuple[str, str]] = field(default_factory=list)
    sources: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "discovered": self.discovered,
            "registered": self.registered,
            "failed": self.failed,
            "sources": self.sources,
        }


# =============================================================================
# Hybrid Adapter Registry
# =============================================================================


class HybridAdapterRegistry:
    """Hybrid adapter registry with Oneiric discovery + Dhruva persistence.

    This registry implements the composite pattern, delegating to specialized
    components for discovery, persistence, and health monitoring.

    Features:
    - Entry point plugin discovery
    - Oneiric MCP remote discovery
    - Dhruva/SQLite state persistence
    - Capability-based routing with caching
    - Health monitoring integration
    - Thread-safe operations

    Example:
        >>> from mahavishnu.core.adapter_registry import HybridAdapterRegistry
        >>> from mahavishnu.core.config import MahavishnuSettings
        >>>
        >>> settings = MahavishnuSettings()
        >>> registry = HybridAdapterRegistry(settings)
        >>> report = await registry.discover_and_register()
        >>>
        >>> # Resolve adapter by capabilities
        >>> decision = await registry.resolve(
        ...     domain="orchestration",
        ...     key="workflow",
        ...     capabilities=["deploy_flows", "monitor_execution"]
        ... )
        >>>
        >>> # Or get adapter by name
        >>> adapter = registry.get_adapter("prefect")
    """

    def __init__(
        self,
        config: Any,  # MahavishnuSettings
        metrics: "RoutingMetrics | None" = None,
        websocket_server: "MahavishnuWebSocketServer | None" = None,
    ) -> None:
        """Initialize the hybrid adapter registry.

        Args:
            config: MahavishnuSettings instance
            metrics: Optional RoutingMetrics for Prometheus integration
            websocket_server: Optional WebSocket server for real-time broadcasts
        """
        self.config = config
        self.metrics = metrics
        self.websocket_server = websocket_server

        # Thread safety
        self._lock = threading.RLock()

        # Composite components
        self.discovery = AdapterDiscoveryEngine(
            config={
                "allowlist_patterns": getattr(config, "adapter_allowlist_patterns", None)
                or ["mahavishnu.adapters.*", "mahavishnu.engines.*"],
                "cache_ttl_seconds": 300,
                "enable_oneiric_mcp": getattr(config, "oneiric_mcp_enabled", False),
            }
        )
        self.persistence = AdapterPersistenceLayer()
        self.resolution_cache = ResolutionCache(ttl_seconds=300)

        # Registered adapters (name -> instance)
        self._adapters: dict[str, OrchestratorAdapter] = {}

        # Adapter metadata (name -> metadata)
        self._metadata: dict[str, AdapterMetadata] = {}

        # Health state (name -> health dict)
        self._health_state: dict[str, dict[str, Any]] = {}

        logger.info("HybridAdapterRegistry initialized")

    async def initialize(self) -> None:
        """Initialize persistence layer.

        Must be called before using the registry.
        """
        await self.persistence.initialize()
        logger.debug("HybridAdapterRegistry persistence initialized")

    async def discover_and_register(self) -> RegistrationReport:
        """Discover and register adapters from all sources.

        This is the main entry point for adapter registration. It:
        1. Discovers adapters from entry points
        2. Discovers adapters from Oneiric MCP
        3. Loads persisted state for known adapters
        4. Instantiates and registers adapters

        Returns:
            RegistrationReport with discovery and registration results
        """
        report = RegistrationReport(discovered=0, registered=0)

        # Discover from all sources
        discovered = await self.discovery.discover_all()
        report.discovered = len(discovered)

        # Track sources
        for adapter in discovered:
            source = adapter.source
            report.sources[source] = report.sources.get(source, 0) + 1

        # Register each discovered adapter
        for metadata in discovered:
            try:
                success = await self._register_adapter_from_metadata(metadata)
                if success:
                    report.registered += 1
                else:
                    report.failed.append((metadata.adapter_id, "Registration failed"))
            except Exception as e:
                error_msg = str(e)
                report.failed.append((metadata.adapter_id, error_msg))
                logger.error(f"Failed to register adapter {metadata.adapter_id}: {error_msg}")

        logger.info(
            f"Registration complete: {report.registered}/{report.discovered} adapters "
            f"from sources: {report.sources}"
        )

        return report

    async def _register_adapter_from_metadata(self, metadata: AdapterMetadata) -> bool:
        """Register an adapter from its metadata.

        Args:
            metadata: Adapter metadata from discovery

        Returns:
            True if registration successful, False otherwise
        """
        # Load factory path
        factory_path = metadata.factory_path
        if not factory_path:
            logger.warning(f"Adapter {metadata.adapter_id} has no factory_path, skipping")
            return False

        try:
            # Parse factory path (module:class or module.function)
            if ":" in factory_path:
                module_path, class_name = factory_path.rsplit(":", 1)
            else:
                module_path = factory_path
                class_name = None

            # Import module
            module = importlib.import_module(module_path)

            # Get class/function
            if class_name:
                factory = getattr(module, class_name)
            else:
                factory = module

            # Instantiate adapter
            if callable(factory):
                # Check if it's a class or factory function
                adapter = factory(config=self.config)
            else:
                adapter = factory

            # Store in registry
            with self._lock:
                # Use provider as the key for simpler access
                adapter_name = metadata.provider
                self._adapters[adapter_name] = adapter
                self._metadata[adapter_name] = metadata

            # Load persisted state
            state = await self.persistence.load_state(metadata.adapter_id)
            if state is None:
                # Create default state
                state = AdapterState(
                    adapter_id=metadata.adapter_id,
                    enabled=True,
                    preference_score=metadata.priority / 100.0,  # Normalize to 0-1
                )
                await self.persistence.save_state(state)

            # Broadcast registration via WebSocket
            if self.websocket_server:
                await self.websocket_server.broadcast_adapter_registered(
                    adapter_id=metadata.adapter_id,
                    adapter_name=adapter_name,
                    capabilities=metadata.capabilities,
                    provider=metadata.provider,
                    source=metadata.source,
                )

            logger.info(
                f"Registered adapter: {adapter_name} "
                f"(capabilities: {metadata.capabilities}, source: {metadata.source})"
            )
            return True

        except Exception as e:
            logger.error(
                f"Failed to instantiate adapter {metadata.adapter_id} from {factory_path}: {e}"
            )
            return False

    async def resolve(
        self,
        domain: str,
        key: str,
        capabilities: list[str] | None = None,
    ) -> RoutingDecision | None:
        """Resolve the best adapter for the given requirements.

        Uses capability matching and cached resolutions for performance.

        Args:
            domain: Domain category (e.g., "orchestration")
            key: Lookup key (e.g., "workflow", "ai_task")
            capabilities: Required capabilities

        Returns:
            RoutingDecision with selected adapter, or None if no match
        """
        start_time = time.time()

        # Build cache key
        cache_key = f"{domain}:{key}:{','.join(sorted(capabilities or []))}"

        # Check cache
        cached = self.resolution_cache.get(cache_key)
        if cached:
            logger.debug(f"Cache hit for resolution: {cache_key}")
            return cached

        # Find matching adapters
        with self._lock:
            matching: list[tuple[str, OrchestratorAdapter, AdapterMetadata]] = []

            for name, metadata in self._metadata.items():
                # Check domain
                if metadata.domain != domain:
                    continue

                # Check capabilities
                if capabilities:
                    available = set(metadata.capabilities)
                    required = set(capabilities)
                    if not required.issubset(available):
                        continue

                adapter = self._adapters.get(name)
                if adapter:
                    matching.append((name, adapter, metadata))

        if not matching:
            logger.warning(
                f"No adapter found for domain={domain}, key={key}, capabilities={capabilities}"
            )
            return None

        # Sort by priority (higher first)
        matching.sort(key=lambda x: x[2].priority, reverse=True)

        # Select best match
        selected_name, selected_adapter, selected_meta = matching[0]

        resolution_time_ms = (time.time() - start_time) * 1000

        # Build matched capabilities list
        matched_caps = []
        if capabilities:
            matched_caps = [cap for cap in capabilities if cap in selected_meta.capabilities]

        decision = RoutingDecision(
            adapter_name=selected_name,
            adapter=selected_adapter,
            matched_capabilities=matched_caps,
            resolution_time_ms=resolution_time_ms,
            fallback_used=False,
            explanation=f"Selected {selected_name} based on capability match and priority",
        )

        # Cache the decision
        self.resolution_cache.set(cache_key, decision)

        logger.info(
            f"Resolved {domain}/{key} to {selected_name} "
            f"(capabilities: {matched_caps}, time: {resolution_time_ms:.2f}ms)"
        )

        return decision

    async def find_by_capabilities(
        self,
        capabilities: list[str],
    ) -> list[AdapterMetadata]:
        """Find all adapters matching ALL specified capabilities.

        Args:
            capabilities: Required capabilities (ALL must be present)

        Returns:
            List of matching adapter metadata
        """
        required = set(capabilities)
        matches: list[AdapterMetadata] = []

        with self._lock:
            for metadata in self._metadata.values():
                available = set(metadata.capabilities)
                if required.issubset(available):
                    matches.append(metadata)

        # Sort by priority
        matches.sort(key=lambda m: m.priority, reverse=True)

        return matches

    def get_adapter(self, name: str) -> "OrchestratorAdapter | None":
        """Get a registered adapter by name.

        Thread-safe lookup.

        Args:
            name: Adapter name (e.g., "prefect", "agno", "llamaindex")

        Returns:
            Adapter instance if found, None otherwise
        """
        with self._lock:
            return self._adapters.get(name)

    def get_metadata(self, name: str) -> AdapterMetadata | None:
        """Get adapter metadata by name.

        Args:
            name: Adapter name

        Returns:
            AdapterMetadata if found, None otherwise
        """
        with self._lock:
            return self._metadata.get(name)

    def list_adapters(
        self,
        domain: str | None = None,
        capabilities: list[str] | None = None,
        healthy_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List all registered adapters with optional filters.

        Args:
            domain: Filter by domain category
            capabilities: Filter by required capabilities
            healthy_only: Only return healthy adapters

        Returns:
            List of adapter info dictionaries
        """
        with self._lock:
            results: list[dict[str, Any]] = []

            for name, metadata in self._metadata.items():
                # Domain filter
                if domain and metadata.domain != domain:
                    continue

                # Capability filter
                if capabilities:
                    available = set(metadata.capabilities)
                    required = set(capabilities)
                    if not required.issubset(available):
                        continue

                # Health filter
                if healthy_only:
                    health = self._health_state.get(name, {})
                    if health.get("status") != "healthy":
                        continue

                adapter = self._adapters.get(name)
                results.append(
                    {
                        "name": name,
                        "adapter_id": metadata.adapter_id,
                        "domain": metadata.domain,
                        "category": metadata.category,
                        "provider": metadata.provider,
                        "capabilities": metadata.capabilities,
                        "priority": metadata.priority,
                        "source": metadata.source,
                        "healthy": self._health_state.get(name, {}).get("status", "unknown"),
                        "has_instance": adapter is not None,
                    }
                )

            return results

    async def check_all_health(self) -> dict[str, dict[str, Any]]:
        """Check health of all registered adapters.

        Updates internal health state and persists records.

        Returns:
            Dictionary mapping adapter names to health status
        """
        results: dict[str, dict[str, Any]] = {}

        for name, adapter in self._adapters.items():
            try:
                health = await adapter.get_health()

                # Normalize health status
                status = health.get("status", "unknown")
                if status not in ("healthy", "degraded", "unhealthy"):
                    status = "healthy" if health.get("healthy", True) else "unhealthy"

                results[name] = {
                    "status": status,
                    "latency_ms": health.get("latency_ms"),
                    "error": health.get("error"),
                    "details": health,
                }

                # Record health history
                await self.persistence.record_health(
                    HealthRecord(
                        adapter_id=self._metadata[name].adapter_id,
                        timestamp=datetime.now(UTC),
                        healthy=(status == "healthy"),
                        latency_ms=health.get("latency_ms"),
                        error_message=health.get("error"),
                        details=health,
                    )
                )

            except Exception as e:
                results[name] = {
                    "status": "unhealthy",
                    "error": str(e),
                }

                # Record failure
                await self.persistence.record_health(
                    HealthRecord(
                        adapter_id=self._metadata[name].adapter_id,
                        timestamp=datetime.now(UTC),
                        healthy=False,
                        error_message=str(e),
                    )
                )

        # Update internal state
        with self._lock:
            old_state = self._health_state.copy()
            self._health_state = results

        # Broadcast health changes
        if self.websocket_server:
            for name, health in results.items():
                old_health = old_state.get(name, {})
                if old_health.get("status") != health.get("status"):
                    await self.websocket_server.broadcast_adapter_health_changed(
                        adapter_id=self._metadata[name].adapter_id,
                        adapter_name=name,
                        old_status=old_health.get("status", "unknown"),
                        new_status=health.get("status", "unknown"),
                        details=health,
                    )

        return results

    async def set_adapter_enabled(
        self,
        name: str,
        enabled: bool,
        reason: str | None = None,
    ) -> bool:
        """Enable or disable an adapter.

        Args:
            name: Adapter name
            enabled: Whether to enable or disable
            reason: Optional reason for the change

        Returns:
            True if successful, False if adapter not found
        """
        with self._lock:
            metadata = self._metadata.get(name)
            if not metadata:
                return False

        # Load and update state
        state = await self.persistence.load_state(metadata.adapter_id)
        if state:
            state.enabled = enabled
            state.updated_at = datetime.now(UTC)
            await self.persistence.save_state(state)

        # Broadcast change
        if self.websocket_server:
            await self.websocket_server.broadcast_adapter_enabled(
                adapter_id=metadata.adapter_id,
                adapter_name=name,
                enabled=enabled,
                reason=reason,
            )

        logger.info(f"Adapter {name} {'enabled' if enabled else 'disabled'}: {reason}")
        return True

    def invalidate_cache(self) -> None:
        """Invalidate all caches."""
        self.discovery.invalidate_cache()
        self.resolution_cache.invalidate()
        logger.info("Adapter registry caches invalidated")

    async def close(self) -> None:
        """Close the registry and release resources."""
        await self.discovery.close()
        await self.persistence.close()
        self.invalidate_cache()
        logger.info("HybridAdapterRegistry closed")

    # =========================================================================
    # Properties for backward compatibility
    # =========================================================================

    @property
    def adapters(self) -> dict[str, "OrchestratorAdapter"]:
        """Get all registered adapters (backward compatibility).

        Returns:
            Dictionary mapping adapter names to instances
        """
        with self._lock:
            return self._adapters.copy()


# =============================================================================
# Module-level singleton
# =============================================================================

_registry: HybridAdapterRegistry | None = None


def get_registry() -> HybridAdapterRegistry:
    """Get the global adapter registry.

    Raises:
        RuntimeError: If registry has not been initialized

    Returns:
        HybridAdapterRegistry instance
    """
    global _registry
    if _registry is None:
        raise RuntimeError(
            "HybridAdapterRegistry not initialized. Call initialize_registry() first."
        )
    return _registry


async def initialize_registry(
    config: Any,
    metrics: "RoutingMetrics | None" = None,
    websocket_server: "MahavishnuWebSocketServer | None" = None,
) -> HybridAdapterRegistry:
    """Initialize and return the global adapter registry.

    Args:
        config: MahavishnuSettings instance
        metrics: Optional RoutingMetrics
        websocket_server: Optional WebSocket server

    Returns:
        Initialized HybridAdapterRegistry
    """
    global _registry

    if _registry is None:
        _registry = HybridAdapterRegistry(
            config=config,
            metrics=metrics,
            websocket_server=websocket_server,
        )
        await _registry.initialize()
        await _registry.discover_and_register()

    return _registry


__all__ = [
    "HybridAdapterRegistry",
    "RegistrationReport",
    "get_registry",
    "initialize_registry",
]
