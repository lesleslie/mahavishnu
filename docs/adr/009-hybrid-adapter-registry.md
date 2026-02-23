# ADR 009: Hybrid Adapter Registry with Dynamic Discovery

## Status

**Accepted**

## Context

Mahavishnu's adapter architecture was hardcoded with direct imports and manual initialization, limiting extensibility and plugin support. The system needed:

1. **Dynamic Discovery** - Adapters discovered at runtime via Python entry points
2. **Capability-Based Routing** - Task routing based on adapter capabilities, not hardcoded mappings
3. **State Persistence** - Adapter state and health tracked across restarts
4. **Plugin Architecture** - Third-party adapters supported without core modifications
5. **Health Integration** - Adapter health integrated with monitoring and alerting

### Options Considered

#### Option 1: Keep Hardcoded Initialization

- **Pros:** Simple, predictable, no discovery overhead
- **Cons:** No plugin support, manual updates required, no capability-based routing

#### Option 2: Full Oneiric Integration

- **Pros:** Complete resolution system, gRPC discovery
- **Cons:** Heavy dependency, requires Oneiric MCP server running

#### Option 3: Hybrid Approach with Composite Pattern (CHOSEN)

- **Pros:**
  - Local-first with entry point discovery
  - Optional Oneiric MCP for remote discovery
  - Composite pattern avoids God Object
  - Capability-based routing with fallback support
  - Dhruva persistence optional (SQLite fallback)
- **Cons:**
  - More complex architecture
  - Multiple components to maintain

## Decision

Implement `HybridAdapterRegistry` using the Composite pattern with separate components for discovery, persistence, and health monitoring.

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    HybridAdapterRegistry                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │  Discovery      │  │  Persistence    │  │  Health         │ │
│  │  Engine         │  │  Layer          │  │  Tracker        │ │
│  │                 │  │                 │  │                 │ │
│  │  • Entry Points │  │  • SQLite       │  │  • Prometheus   │ │
│  │  • Oneiric MCP  │  │  • Dhruva MCP   │  │  • Alerts       │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────┐
              │    CapabilityRouter       │
              │    • Task → Capabilities  │
              │    • Resolution Cache     │
              │    • Fallback Chains      │
              └───────────────────────────┘
```

### Core Components

#### 1. AdapterDiscoveryEngine

Discovers adapters from multiple sources:

```python
class AdapterDiscoveryEngine:
    """Discover adapters from entry points and Oneiric MCP."""

    def __init__(self, config: AdapterRegistryConfig):
        self.allowlist_patterns = config.allowlist_patterns
        self._cache: dict[str, list[AdapterMetadata]] = {}

    async def discover_all(self) -> list[AdapterMetadata]:
        """Discover from all sources with caching."""
        adapters = []
        adapters.extend(await self.discover_from_entry_points())
        if self.oneiric_mcp_enabled:
            adapters.extend(await self.discover_from_oneiric_mcp())
        return adapters

    async def discover_from_entry_points(self) -> list[AdapterMetadata]:
        """Load adapters from Python entry points."""
        import importlib.metadata as metadata
        eps = metadata.entry_points(group="mahavishnu.adapters")
        for ep in eps:
            if self._is_allowed(ep.value):
                yield AdapterMetadata.from_entry_point(ep)
```

#### 2. AdapterPersistenceLayer

Persists adapter state with SQLite fallback:

```python
class AdapterPersistenceLayer:
    """Persist adapter state to SQLite with Dhruva MCP sync."""

    async def save_state(self, state: AdapterState) -> None:
        """Save state to SQLite, optionally sync to Dhruva."""
        await self._sqlite_save(state)
        if self.dhruva_enabled:
            await self._dhruva_sync(state)

    async def load_state(self, adapter_id: str) -> AdapterState | None:
        """Load state from SQLite (Dhruva as backup)."""
        state = await self._sqlite_load(adapter_id)
        if not state and self.dhruva_enabled:
            state = await self._dhruva_load(adapter_id)
        return state
```

#### 3. HybridAdapterRegistry

Main registry with composite pattern:

```python
class HybridAdapterRegistry:
    """Hybrid adapter registry with discovery, persistence, and health."""

    def __init__(self, config: MahavishnuSettings):
        self.discovery = AdapterDiscoveryEngine(config.adapter_registry)
        self.persistence = AdapterPersistenceLayer()
        self.resolution_cache = ResolutionCache(ttl_seconds=300)
        self._lock = threading.RLock()
        self._adapters: dict[str, OrchestratorAdapter] = {}
        self._metadata: dict[str, AdapterMetadata] = {}

    async def discover_and_register(self) -> RegistrationReport:
        """Discover and register all adapters."""
        discovered = await self.discovery.discover_all()
        registered = 0
        failed = []

        for metadata in discovered:
            try:
                adapter = await self._create_adapter(metadata)
                with self._lock:
                    self._adapters[metadata.adapter_id] = adapter
                    self._metadata[metadata.adapter_id] = metadata
                registered += 1
            except Exception as e:
                failed.append((metadata.adapter_id, str(e)))

        return RegistrationReport(
            discovered=len(discovered),
            registered=registered,
            failed=failed,
        )

    async def find_by_capabilities(
        self,
        capabilities: list[str],
    ) -> list[AdapterMetadata]:
        """Find adapters matching ALL specified capabilities."""
        matches = []
        for metadata in self._metadata.values():
            if all(cap in metadata.capabilities for cap in capabilities):
                matches.append(metadata)
        return sorted(matches, key=lambda m: m.priority, reverse=True)
```

#### 4. CapabilityRouter

Routes tasks based on capabilities:

```python
class CapabilityRouter:
    """Route tasks based on adapter capabilities."""

    TASK_CAPABILITY_REQUIREMENTS = {
        TaskType.RAG_QUERY: ["rag", "vector_search"],
        TaskType.AI_TASK: ["multi_agent", "tool_use"],
        TaskType.WORKFLOW: ["deploy_flows", "monitor_execution"],
    }

    async def route(self, task_type: TaskType) -> RoutingDecision:
        """Find best adapter for task type."""
        requirements = self.TASK_CAPABILITY_REQUIREMENTS.get(task_type, [])
        candidates = await self.registry.find_by_capabilities(requirements)

        if not candidates:
            raise NoAdapterFoundError(task_type, requirements)

        best = max(candidates, key=lambda m: m.priority)
        return RoutingDecision(
            adapter_name=best.adapter_id,
            matched_capabilities=requirements,
            resolution_time_ms=elapsed_ms,
        )
```

### Entry Point Registration

Adapters register via `pyproject.toml`:

```toml
[project.entry-points."mahavishnu.adapters"]
prefect = "mahavishnu.engines.prefect_adapter:prefect_adapter_entries"
agno = "mahavishnu.engines.agno_adapter:agno_adapter_entries"
worker = "mahavishnu.core.adapters.worker:worker_adapter_entries"
```

Entry point functions return metadata:

```python
def prefect_adapter_entries() -> list[dict[str, Any]]:
    return [{
        "category": "orchestration",
        "provider": "prefect",
        "factory_path": "mahavishnu.engines.prefect_adapter:PrefectAdapter",
        "capabilities": ["deploy_flows", "monitor_execution", "schedule_workflows"],
        "priority": 90,
        "domain": "orchestration",
    }]
```

### Security: Allowlist Patterns

Adapter discovery uses allowlist validation:

```python
def _is_allowed(self, module_path: str) -> bool:
    """Check if module matches allowlist patterns."""
    import fnmatch
    for pattern in self.allowlist_patterns:
        if fnmatch.fnmatch(module_path, pattern):
            return True
    logger.warning(f"Adapter rejected (not in allowlist): {module_path}")
    return False
```

Configuration in `settings/mahavishnu.yaml`:

```yaml
adapter_registry:
  allowlist_patterns:
    - "mahavishnu.adapters.*"
    - "mahavishnu.engines.*"
    - "trusted_org.third_party.*"
  verify_signatures: false  # Enable in production
  reject_unsigned: false    # Dev mode
```

## Consequences

### Positive

- **Plugin Architecture**: Third-party adapters via entry points
- **Capability-Based Routing**: Dynamic routing instead of hardcoded mappings
- **State Persistence**: Adapter state survives restarts
- **Health Integration**: Prometheus metrics and Grafana dashboards
- **Fallback Support**: SQLite fallback when Dhruva unavailable
- **Thread Safety**: RLock protects concurrent access
- **Resolution Caching**: TTL cache for performance

### Negative

- **Complexity**: Multiple components to understand and maintain
- **Discovery Overhead**: Entry point discovery adds startup time
- **Optional Dependencies**: Oneiric MCP and Dhruva are optional but add complexity

### Risks

- **Risk:** Malicious packages could inject adapters
  **Mitigation:** Allowlist patterns required, optional signature verification

- **Risk:** Entry point discovery fails
  **Mitigation:** Cached metadata, fallback to hardcoded initialization

- **Risk:** Dhruva unavailable
  **Mitigation:** SQLite fallback with async sync when available

## Implementation

### Phase 1: Core Registry (Complete)

- [x] `adapter_registry.py` - HybridAdapterRegistry with composite pattern
- [x] `adapter_discovery.py` - Entry point + Oneiric MCP discovery
- [x] `adapter_persistence.py` - SQLite + Dhruva persistence

### Phase 2: Capability Routing (Complete)

- [x] `task_requirements.py` - TaskRequirements, RoutingDecision, ResolutionCache
- [x] `task_router.py` - CapabilityRouter class

### Phase 3: Health Integration (Complete)

- [x] `health_integration.py` - AdapterHealthMonitor with Prometheus
- [x] Grafana dashboard panels for adapter health
- [x] WebSocket broadcasting for adapter events

### Phase 4: MCP Tools (Complete)

- [x] `adapter_registry_tools.py` - 7 MCP tools for adapter management

### Phase 5: Testing (Complete)

- [x] `test_adapter_registry.py` - 32 unit tests
- [x] `test_rollback_integration.py` - 22 integration tests
- [x] `adapter_mocks.py` - Mock infrastructure

## References

- [Python Entry Points](https://packaging.python.org/en/latest/specifications/entry-points/)
- [Oneiric Resolution System](https://github.com/lesleslie/oneiric)
- [Dhruva Persistence Layer](https://github.com/lesleslie/dhruva)
- ADR 004: Adapter Architecture and Engine Integration
