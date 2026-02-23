"""Comprehensive mock infrastructure for testing HybridAdapterRegistry.

This module provides mock implementations of the core components used by
HybridAdapterRegistry, enabling isolated and deterministic testing.

Mocks Provided:
- MockOneiricResolver: Mock for Oneiric resolver with configurable candidates
- MockDhruvaRegistry: Mock for Dhruva persistence layer
- MockAdapterDiscovery: Mock for adapter discovery engine
- MockAdapter: Simple mock adapter implementing OrchestratorAdapter protocol
- MockCandidate: Mock candidate for resolution testing

Usage:
    >>> from tests.fixtures.adapter_mocks import (
    ...     MockAdapter,
    ...     MockAdapterDiscovery,
    ...     MockDhruvaRegistry,
    ... )
    >>> from mahavishnu.core.adapter_registry import HybridAdapterRegistry
    >>>
    >>> # Create mock dependencies
    >>> discovery = MockAdapterDiscovery()
    >>> persistence = MockDhruvaRegistry()
    >>>
    >>> # Configure return values
    >>> discovery.set_adapters([...])
    >>> persistence.set_state("adapter_id", {...})
    >>>
    >>> # Use in tests
    >>> assert discovery.discover_all.called
    >>> assert persistence.save_state.call_count == 1

Created: 2026-02-22
Version: 1.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from collections.abc import Callable


# =============================================================================
# Mock Candidate
# =============================================================================


@dataclass
class MockCandidate:
    """Mock candidate for resolution testing.

    Represents a candidate adapter returned by Oneiric resolution.

    Attributes:
        adapter_id: Unique identifier for the adapter
        provider: Provider name (e.g., "prefect", "llamaindex")
        domain: Domain category (e.g., "orchestration")
        category: Sub-category within domain
        capabilities: List of capability strings
        priority: Priority score for selection (higher = preferred)
        enabled: Whether this candidate is enabled
        score: Resolution score (computed during resolution)

    Usage:
        >>> candidate = MockCandidate(
        ...     adapter_id="test.prefect",
        ...     provider="prefect",
        ...     capabilities=["deploy_flows", "monitor"],
        ... )
        >>> assert candidate.matches(["deploy_flows"])
    """

    adapter_id: str
    provider: str
    domain: str = "orchestration"
    category: str = "workflow"
    capabilities: list[str] = field(default_factory=list)
    priority: int = 50
    enabled: bool = True
    score: float = 0.0

    def matches(self, required_capabilities: list[str]) -> bool:
        """Check if this candidate matches required capabilities.

        Args:
            required_capabilities: List of capabilities that must be present

        Returns:
            True if all required capabilities are present
        """
        required = set(required_capabilities)
        available = set(self.capabilities)
        return required.issubset(available)

    def to_metadata_dict(self) -> dict[str, Any]:
        """Convert to AdapterMetadata-compatible dictionary.

        Returns:
            Dictionary suitable for creating AdapterMetadata
        """
        return {
            "adapter_id": self.adapter_id,
            "domain": self.domain,
            "category": self.category,
            "provider": self.provider,
            "capabilities": self.capabilities,
            "factory_path": f"mock.adapters.{self.provider}:Mock{self.provider.title()}Adapter",
            "priority": self.priority,
            "source": "mock",
        }


# =============================================================================
# Mock Adapter
# =============================================================================


class MockAdapter:
    """Mock adapter implementing OrchestratorAdapter protocol.

    Provides a simple mock that tracks method calls and returns
    configurable responses.

    Attributes:
        name: Adapter name
        adapter_type: Adapter type enum value
        capabilities: AdapterCapabilities instance
        execute: AsyncMock for execute method
        get_health: AsyncMock for get_health method
        call_history: List of all method calls with arguments

    Usage:
        >>> adapter = MockAdapter(
        ...     name="test_adapter",
        ...     capabilities=["deploy_flows", "monitor"],
        ... )
        >>> adapter.execute.return_value = {"status": "success"}
        >>> result = await adapter.execute({"task": "test"}, [])
        >>> assert result["status"] == "success"
        >>> assert adapter.was_called("execute")
    """

    def __init__(
        self,
        name: str = "mock_adapter",
        adapter_type: str = "mock",
        capabilities: list[str] | None = None,
        health_status: str = "healthy",
        health_latency_ms: float = 10.0,
    ) -> None:
        """Initialize mock adapter.

        Args:
            name: Adapter name
            adapter_type: Adapter type string
            capabilities: List of capability strings
            health_status: Default health status to return
            health_latency_ms: Default health check latency
        """
        self._name = name
        self._adapter_type = adapter_type
        self._capability_list = capabilities or []
        self._health_status = health_status
        self._health_latency_ms = health_latency_ms

        # Method mocks
        self.execute = AsyncMock(return_value={"status": "success", "result": {}})
        self.get_health = AsyncMock(
            return_value={
                "status": self._health_status,
                "latency_ms": self._health_latency_ms,
            }
        )

        # Call tracking
        self.call_history: list[dict[str, Any]] = []

        # Wire up call tracking
        self._wrap_mocks()

    def _wrap_mocks(self) -> None:
        """Wrap mock methods to track calls."""

        original_execute = self.execute
        original_get_health = self.get_health

        async def tracked_execute(*args: Any, **kwargs: Any) -> Any:
            self.call_history.append({
                "method": "execute",
                "args": args,
                "kwargs": kwargs,
                "timestamp": datetime.now(UTC),
            })
            return await original_execute(*args, **kwargs)

        async def tracked_get_health(*args: Any, **kwargs: Any) -> Any:
            self.call_history.append({
                "method": "get_health",
                "args": args,
                "kwargs": kwargs,
                "timestamp": datetime.now(UTC),
            })
            return await original_get_health(*args, **kwargs)

        self.execute = tracked_execute  # type: ignore[method-assign]
        self.get_health = tracked_get_health  # type: ignore[method-assign]

    @property
    def name(self) -> str:
        """Return adapter name."""
        return self._name

    @property
    def adapter_type(self) -> Any:
        """Return adapter type enum."""
        # Return a mock enum-like object
        return MagicMock(value=self._adapter_type)

    @property
    def capabilities(self) -> Any:
        """Return adapter capabilities."""
        # Return a mock AdapterCapabilities object
        caps = MagicMock()
        caps.can_deploy_flows = "deploy_flows" in self._capability_list
        caps.can_monitor_execution = "monitor_execution" in self._capability_list
        caps.can_cancel_workflows = "cancel_workflows" in self._capability_list
        caps.can_sync_state = "sync_state" in self._capability_list
        caps.supports_batch_execution = "batch_execution" in self._capability_list
        caps.has_cloud_ui = "cloud_ui" in self._capability_list
        caps.supports_multi_agent = "multi_agent" in self._capability_list
        return caps

    @property
    def capability_list(self) -> list[str]:
        """Return list of capability strings."""
        return self._capability_list

    def was_called(self, method: str) -> bool:
        """Check if a method was called.

        Args:
            method: Method name to check

        Returns:
            True if method was called at least once
        """
        return any(call["method"] == method for call in self.call_history)

    def get_calls(self, method: str) -> list[dict[str, Any]]:
        """Get all calls to a specific method.

        Args:
            method: Method name to filter by

        Returns:
            List of call records
        """
        return [call for call in self.call_history if call["method"] == method]

    def reset_history(self) -> None:
        """Clear call history."""
        self.call_history.clear()

    def set_execute_result(self, result: dict[str, Any]) -> None:
        """Configure the execute method return value.

        Args:
            result: Dictionary to return from execute
        """
        self.execute.return_value = result  # type: ignore[misc]

    def set_execute_side_effect(
        self, side_effect: Exception | Callable[..., Any]
    ) -> None:
        """Configure the execute method to raise or use side effect.

        Args:
            side_effect: Exception to raise or callable to invoke
        """
        self.execute.side_effect = side_effect  # type: ignore[misc]

    def set_health_result(self, result: dict[str, Any]) -> None:
        """Configure the get_health method return value.

        Args:
            result: Dictionary to return from get_health
        """
        self.get_health.return_value = result  # type: ignore[misc]


# =============================================================================
# Mock Oneiric Resolver
# =============================================================================


class MockOneiricResolver:
    """Mock for Oneiric resolver with configurable candidates.

    Simulates the Oneiric MCP resolver for testing adapter resolution
    without requiring an actual Oneiric MCP connection.

    Attributes:
        candidates: List of MockCandidate instances
        resolve: AsyncMock for resolve method
        list_adapters: AsyncMock for list_adapters method
        call_history: List of all method calls

    Usage:
        >>> resolver = MockOneiricResolver()
        >>> resolver.add_candidate(MockCandidate(
        ...     adapter_id="test.prefect",
        ...     provider="prefect",
        ...     capabilities=["deploy_flows"],
        ... ))
        >>> result = await resolver.resolve(
        ...     domain="orchestration",
        ...     capabilities=["deploy_flows"],
        ... )
        >>> assert result.provider == "prefect"
    """

    def __init__(self, candidates: list[MockCandidate] | None = None) -> None:
        """Initialize mock resolver.

        Args:
            candidates: Initial list of candidates
        """
        self._candidates: list[MockCandidate] = candidates or []
        self._default_candidates = list(self._candidates)

        # Method mocks
        self.resolve = AsyncMock(side_effect=self._resolve_impl)
        self.list_adapters = AsyncMock(side_effect=self._list_adapters_impl)
        self.get_adapter = AsyncMock(side_effect=self._get_adapter_impl)
        self.check_health = AsyncMock(return_value=True)
        self.send_heartbeat = AsyncMock(return_value=True)
        self.invalidate_cache = MagicMock()

        # Call tracking
        self.call_history: list[dict[str, Any]] = []

    def _record_call(self, method: str, *args: Any, **kwargs: Any) -> None:
        """Record a method call."""
        self.call_history.append({
            "method": method,
            "args": args,
            "kwargs": kwargs,
            "timestamp": datetime.now(UTC),
        })

    async def _resolve_impl(
        self,
        domain: str,
        category: str | None = None,
        capabilities: list[str] | None = None,
        **kwargs: Any,
    ) -> MockCandidate | None:
        """Implementation of resolve method.

        Args:
            domain: Domain to filter by
            category: Optional category filter
            capabilities: Required capabilities
            **kwargs: Additional filters

        Returns:
            Best matching candidate or None
        """
        self._record_call("resolve", domain, category, capabilities, **kwargs)

        # Filter candidates
        matches = [
            c
            for c in self._candidates
            if c.domain == domain
            and c.enabled
            and (category is None or c.category == category)
            and (capabilities is None or c.matches(capabilities))
        ]

        if not matches:
            return None

        # Sort by priority (higher first), then by score
        matches.sort(key=lambda c: (c.priority, c.score), reverse=True)
        return matches[0]

    async def _list_adapters_impl(
        self,
        domain: str | None = None,
        category: str | None = None,
        healthy_only: bool = True,
        **kwargs: Any,
    ) -> list[MockCandidate]:
        """Implementation of list_adapters method.

        Args:
            domain: Optional domain filter
            category: Optional category filter
            healthy_only: Only return enabled candidates
            **kwargs: Additional filters

        Returns:
            List of matching candidates
        """
        self._record_call("list_adapters", domain, category, healthy_only, **kwargs)

        results = [
            c
            for c in self._candidates
            if (domain is None or c.domain == domain)
            and (category is None or c.category == category)
            and (not healthy_only or c.enabled)
        ]

        return results

    async def _get_adapter_impl(self, adapter_id: str) -> MockCandidate | None:
        """Implementation of get_adapter method.

        Args:
            adapter_id: Adapter ID to look up

        Returns:
            Matching candidate or None
        """
        self._record_call("get_adapter", adapter_id)

        for candidate in self._candidates:
            if candidate.adapter_id == adapter_id:
                return candidate
        return None

    def add_candidate(self, candidate: MockCandidate) -> None:
        """Add a candidate to the resolver.

        Args:
            candidate: MockCandidate to add
        """
        self._candidates.append(candidate)

    def set_candidates(self, candidates: list[MockCandidate]) -> None:
        """Replace all candidates.

        Args:
            candidates: New list of candidates
        """
        self._candidates = list(candidates)

    def reset_candidates(self) -> None:
        """Reset to default candidates."""
        self._candidates = list(self._default_candidates)

    def clear_candidates(self) -> None:
        """Remove all candidates."""
        self._candidates.clear()

    def get_candidate_by_id(self, adapter_id: str) -> MockCandidate | None:
        """Get candidate by ID.

        Args:
            adapter_id: Adapter ID to look up

        Returns:
            Matching candidate or None
        """
        for candidate in self._candidates:
            if candidate.adapter_id == adapter_id:
                return candidate
        return None

    def was_called(self, method: str) -> bool:
        """Check if a method was called."""
        return any(call["method"] == method for call in self.call_history)

    def reset_history(self) -> None:
        """Clear call history."""
        self.call_history.clear()

    async def close(self) -> None:
        """Close the resolver (no-op for mock)."""
        pass


# =============================================================================
# Mock Dhruva Registry
# =============================================================================


class MockDhruvaRegistry:
    """Mock for Dhruva persistence layer.

    Simulates the Dhruva MCP persistence layer for testing adapter
    state storage without requiring an actual Dhruva connection.

    Attributes:
        states: Dictionary of adapter states by adapter_id
        health_records: Dictionary of health records by adapter_id
        call_history: List of all method calls

    Usage:
        >>> registry = MockDhruvaRegistry()
        >>> await registry.save_state("prefect", {"enabled": True, "score": 0.8})
        >>> state = await registry.load_state("prefect")
        >>> assert state["enabled"] is True
        >>> assert registry.was_called("save_state")
    """

    def __init__(self) -> None:
        """Initialize mock registry."""
        # In-memory storage
        self._states: dict[str, dict[str, Any]] = {}
        self._health_records: dict[str, list[dict[str, Any]]] = {}

        # Call tracking
        self.call_history: list[dict[str, Any]] = []

        # Async method mocks (can be configured for side effects)
        self.save_state = AsyncMock(side_effect=self._save_state_impl)
        self.load_state = AsyncMock(side_effect=self._load_state_impl)
        self.load_all_states = AsyncMock(side_effect=self._load_all_states_impl)
        self.record_health = AsyncMock(side_effect=self._record_health_impl)
        self.get_health_history = AsyncMock(side_effect=self._get_health_history_impl)
        self.delete_state = AsyncMock(side_effect=self._delete_state_impl)
        self.cleanup_old_records = AsyncMock(return_value=0)

    def _record_call(self, method: str, *args: Any, **kwargs: Any) -> None:
        """Record a method call."""
        self.call_history.append({
            "method": method,
            "args": args,
            "kwargs": kwargs,
            "timestamp": datetime.now(UTC),
        })

    async def _save_state_impl(self, adapter_id: str, state: dict[str, Any]) -> None:
        """Implementation of save_state."""
        self._record_call("save_state", adapter_id, state)
        self._states[adapter_id] = {
            **state,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    async def _load_state_impl(self, adapter_id: str) -> dict[str, Any] | None:
        """Implementation of load_state."""
        self._record_call("load_state", adapter_id)
        return self._states.get(adapter_id)

    async def _load_all_states_impl(self) -> dict[str, dict[str, Any]]:
        """Implementation of load_all_states."""
        self._record_call("load_all_states")
        return dict(self._states)

    async def _record_health_impl(self, record: dict[str, Any]) -> None:
        """Implementation of record_health."""
        self._record_call("record_health", record)
        adapter_id = record.get("adapter_id", "unknown")
        if adapter_id not in self._health_records:
            self._health_records[adapter_id] = []
        self._health_records[adapter_id].append({
            **record,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    async def _get_health_history_impl(
        self, adapter_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Implementation of get_health_history."""
        self._record_call("get_health_history", adapter_id, limit)
        records = self._health_records.get(adapter_id, [])
        return records[-limit:]

    async def _delete_state_impl(self, adapter_id: str) -> bool:
        """Implementation of delete_state."""
        self._record_call("delete_state", adapter_id)
        if adapter_id in self._states:
            del self._states[adapter_id]
            return True
        return False

    def set_state(self, adapter_id: str, state: dict[str, Any]) -> None:
        """Directly set adapter state (synchronous helper).

        Args:
            adapter_id: Adapter identifier
            state: State dictionary
        """
        self._states[adapter_id] = {
            **state,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    def get_state(self, adapter_id: str) -> dict[str, Any] | None:
        """Directly get adapter state (synchronous helper).

        Args:
            adapter_id: Adapter identifier

        Returns:
            State dictionary or None
        """
        return self._states.get(adapter_id)

    def add_health_record(self, adapter_id: str, record: dict[str, Any]) -> None:
        """Directly add a health record (synchronous helper).

        Args:
            adapter_id: Adapter identifier
            record: Health record dictionary
        """
        if adapter_id not in self._health_records:
            self._health_records[adapter_id] = []
        self._health_records[adapter_id].append({
            **record,
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def clear_all(self) -> None:
        """Clear all stored data."""
        self._states.clear()
        self._health_records.clear()

    def was_called(self, method: str) -> bool:
        """Check if a method was called."""
        return any(call["method"] == method for call in self.call_history)

    def get_calls(self, method: str) -> list[dict[str, Any]]:
        """Get all calls to a specific method."""
        return [call for call in self.call_history if call["method"] == method]

    def reset_history(self) -> None:
        """Clear call history."""
        self.call_history.clear()

    async def close(self) -> None:
        """Close the registry (no-op for mock)."""
        pass

    @property
    def _initialized(self) -> bool:
        """Compatibility property for tests checking initialization."""
        return True


# =============================================================================
# Mock Adapter Discovery
# =============================================================================


class MockAdapterDiscovery:
    """Mock for adapter discovery engine.

    Simulates the AdapterDiscoveryEngine for testing adapter discovery
    without requiring actual entry points or Oneiric MCP connection.

    Attributes:
        adapters: List of AdapterMetadata-compatible dictionaries
        call_history: List of all method calls

    Usage:
        >>> discovery = MockAdapterDiscovery()
        >>> discovery.add_adapter({
        ...     "adapter_id": "test.prefect",
        ...     "provider": "prefect",
        ...     "domain": "orchestration",
        ...     "capabilities": ["deploy_flows"],
        ... })
        >>> adapters = await discovery.discover_all()
        >>> assert len(adapters) == 1
    """

    def __init__(self, adapters: list[dict[str, Any]] | None = None) -> None:
        """Initialize mock discovery.

        Args:
            adapters: Initial list of adapter metadata dictionaries
        """
        self._adapters: list[dict[str, Any]] = adapters or []
        self._default_adapters = list(self._adapters)

        # Call tracking
        self.call_history: list[dict[str, Any]] = []

        # Async method mocks
        self.discover_all = AsyncMock(side_effect=self._discover_all_impl)
        self.discover_from_entry_points = AsyncMock(
            side_effect=self._discover_from_entry_points_impl
        )
        self.discover_from_oneiric_mcp = AsyncMock(
            side_effect=self._discover_from_oneiric_mcp_impl
        )

        # Sync method mocks
        self.invalidate_cache = MagicMock(side_effect=self._invalidate_cache_impl)
        self.get_cache_stats = MagicMock(return_value={"entries": 0, "ttl_seconds": 300})

    def _record_call(self, method: str, *args: Any, **kwargs: Any) -> None:
        """Record a method call."""
        self.call_history.append({
            "method": method,
            "args": args,
            "kwargs": kwargs,
            "timestamp": datetime.now(UTC),
        })

    def _create_metadata_from_dict(self, data: dict[str, Any]) -> MagicMock:
        """Create a mock AdapterMetadata from dictionary.

        Args:
            data: Dictionary with adapter metadata

        Returns:
            MagicMock with AdapterMetadata interface
        """
        metadata = MagicMock()
        metadata.adapter_id = data.get("adapter_id", "unknown")
        metadata.domain = data.get("domain", "orchestration")
        metadata.category = data.get("category", "workflow")
        metadata.provider = data.get("provider", "unknown")
        metadata.capabilities = data.get("capabilities", [])
        metadata.factory_path = data.get(
            "factory_path", f"mock.adapters.{metadata.provider}:MockAdapter"
        )
        metadata.priority = data.get("priority", 50)
        metadata.health_check_url = data.get("health_check_url")
        metadata.metadata = data.get("metadata", {})
        metadata.source = data.get("source", "mock")
        metadata.discovered_at = datetime.now(UTC)

        metadata.to_dict = MagicMock(return_value=data)

        return metadata

    async def _discover_all_impl(self) -> list[MagicMock]:
        """Implementation of discover_all."""
        self._record_call("discover_all")
        return [self._create_metadata_from_dict(a) for a in self._adapters]

    async def _discover_from_entry_points_impl(self) -> list[MagicMock]:
        """Implementation of discover_from_entry_points."""
        self._record_call("discover_from_entry_points")
        entry_point_adapters = [
            a for a in self._adapters if a.get("source") in ("entry_point", "mock")
        ]
        return [self._create_metadata_from_dict(a) for a in entry_point_adapters]

    async def _discover_from_oneiric_mcp_impl(self) -> list[MagicMock]:
        """Implementation of discover_from_oneiric_mcp."""
        self._record_call("discover_from_oneiric_mcp")
        oneiric_adapters = [
            a for a in self._adapters if a.get("source") == "oneiric_mcp"
        ]
        return [self._create_metadata_from_dict(a) for a in oneiric_adapters]

    def _invalidate_cache_impl(self) -> None:
        """Implementation of invalidate_cache."""
        self._record_call("invalidate_cache")

    def add_adapter(self, adapter: dict[str, Any]) -> None:
        """Add an adapter to discovery results.

        Args:
            adapter: Adapter metadata dictionary
        """
        self._adapters.append(adapter)

    def set_adapters(self, adapters: list[dict[str, Any]]) -> None:
        """Replace all adapters.

        Args:
            adapters: New list of adapter metadata
        """
        self._adapters = list(adapters)

    def reset_adapters(self) -> None:
        """Reset to default adapters."""
        self._adapters = list(self._default_adapters)

    def clear_adapters(self) -> None:
        """Remove all adapters."""
        self._adapters.clear()

    def was_called(self, method: str) -> bool:
        """Check if a method was called."""
        return any(call["method"] == method for call in self.call_history)

    def reset_history(self) -> None:
        """Clear call history."""
        self.call_history.clear()

    async def close(self) -> None:
        """Close the discovery engine (no-op for mock)."""
        pass


# =============================================================================
# Factory Functions
# =============================================================================


def create_mock_adapter(
    name: str = "test_adapter",
    capabilities: list[str] | None = None,
    **kwargs: Any,
) -> MockAdapter:
    """Factory function to create a MockAdapter.

    Args:
        name: Adapter name
        capabilities: List of capabilities
        **kwargs: Additional arguments passed to MockAdapter

    Returns:
        Configured MockAdapter instance
    """
    return MockAdapter(name=name, capabilities=capabilities, **kwargs)


def create_mock_candidate(
    adapter_id: str,
    provider: str,
    capabilities: list[str] | None = None,
    **kwargs: Any,
) -> MockCandidate:
    """Factory function to create a MockCandidate.

    Args:
        adapter_id: Unique adapter identifier
        provider: Provider name
        capabilities: List of capabilities
        **kwargs: Additional arguments passed to MockCandidate

    Returns:
        Configured MockCandidate instance
    """
    return MockCandidate(
        adapter_id=adapter_id,
        provider=provider,
        capabilities=capabilities or [],
        **kwargs,
    )


def create_mock_registry_fixtures() -> dict[str, Any]:
    """Create a complete set of mock fixtures for registry testing.

    Returns:
        Dictionary with pre-configured mock instances:
        - discovery: MockAdapterDiscovery
        - persistence: MockDhruvaRegistry
        - resolver: MockOneiricResolver
        - adapters: List of sample MockAdapter instances
    """
    # Create sample adapters
    prefect_adapter = create_mock_adapter(
        name="prefect",
        capabilities=["deploy_flows", "monitor_execution", "cancel_workflows"],
    )
    llamaindex_adapter = create_mock_adapter(
        name="llamaindex",
        capabilities=["rag", "vector_search", "embedding"],
    )
    agno_adapter = create_mock_adapter(
        name="agno",
        capabilities=["multi_agent", "tool_use"],
    )

    # Create sample candidates
    prefect_candidate = create_mock_candidate(
        adapter_id="mahavishnu.engines.prefect",
        provider="prefect",
        capabilities=["deploy_flows", "monitor_execution"],
    )
    llamaindex_candidate = create_mock_candidate(
        adapter_id="mahavishnu.adapters.llamaindex",
        provider="llamaindex",
        capabilities=["rag", "vector_search"],
    )

    return {
        "discovery": MockAdapterDiscovery(),
        "persistence": MockDhruvaRegistry(),
        "resolver": MockOneiricResolver(candidates=[prefect_candidate, llamaindex_candidate]),
        "adapters": [prefect_adapter, llamaindex_adapter, agno_adapter],
        "candidates": [prefect_candidate, llamaindex_candidate],
    }


# =============================================================================
# Module Exports
# =============================================================================


__all__ = [
    # Mock classes
    "MockAdapter",
    "MockCandidate",
    "MockOneiricResolver",
    "MockDhruvaRegistry",
    "MockAdapterDiscovery",
    # Factory functions
    "create_mock_adapter",
    "create_mock_candidate",
    "create_mock_registry_fixtures",
]
