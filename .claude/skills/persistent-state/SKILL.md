---
name: persistent-state
description: >
  Proactive durable storage skill. Use automatically when state needs to survive beyond the
  current session. Persists configuration via key-value store, tracks metrics over time via
  time-series, manages adapters via the registry, and records service lifecycle events using
  Dhara's ACID storage. NOT user-invoked — Claude activates this autonomously at "durability
  moments."
---

# Persistent State

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| dhara | 8683 | grep | mcp__dhara__put, mcp__dhara__get, mcp__dhara__record_event | 30s |
| session-buddy | 8678 | grep | mcp__session-buddy__store_reflection | 30s |

State that should survive session restarts deserves durable storage, not in-memory variables or temp files. This skill teaches Claude to use Dhara's ACID storage whenever it encounters a "durability moment" — any point where ephemeral state would be more valuable if persisted.

**Core principle:** Will I need this after the session ends? If yes, use Dhara. If no, in-memory is fine.

Dhara provides four storage capabilities, each suited to different types of state:

| Capability | Best For | Example |
|---|---|---|
| Key-value store | Config, cached results, shared state | Pool size calculation, adapter preferences |
| Time-series | Metrics that change over time | Adapter latency, quality scores, uptime |
| Adapter registry | Adapter discovery, validation, health | Which adapters exist, are they healthy |
| Service lifecycle | Service events, status tracking | Service start/stop, deployments, health changes |

## Activation

**Reactive** — triggers automatically when Claude is about to:
- Store configuration or settings that should survive session restart
- Track a metric or value that changes over time (time-series)
- Discover, validate, or manage an adapter in the ecosystem
- Record a service lifecycle event (startup, shutdown, health change)
- Cache a computation result with an expiration time (TTL)

**Not a slash command.** Claude uses this autonomously.

**Trigger pattern:** The skill fires at "durability moments" — any point where Claude is about to create ephemeral state that would be more valuable if persisted.

## Quick Reference

```
# Key-value storage
put(key, value, ttl=TTL)     # Store with optional expiration
get(key)                     # Retrieve

# Time-series tracking
record_time_series(metric_type, entity_id, record={value, unit, source})
query_time_series(metric_type, entity_id, start_date)
aggregate_patterns(start_date)

# Adapter registry
list_adapters(domain, category)
get_adapter(domain, key, provider)
validate_adapter(domain, key, provider)
get_adapter_health(domain, key, provider)

# Service lifecycle
upsert_service(service_id, service_type, status, capabilities)
record_event(event_type, source_service, payload)
list_services(status, capability)
get_service(service_id)
```

## Implementation

### Flow 1: Key-Value Storage

**When to use:** Persisting config, caching computation results, sharing state across sessions.

**Step 1: Decide on TTL**

| Data Type | TTL | Rationale |
|---|---|---|
| Cached computation | 1-24 hours (`3600`-`86400`) | Results become stale |
| Configuration value | 7-30 days (`604800`-`2592000`) | Config changes infrequently |
| Long-lived state | `null` (permanent) | Until explicitly overwritten |

**Step 2: Store the value**

```
Call mcp__dhara__put with:
  - key: "{domain}:{entity}:{identifier}:{field}"
  - value: the data to persist (string, number, object, array, or null)
  - ttl: seconds until expiration (null for permanent)
```

**Step 3: Retrieve later**

```
Call mcp__dhara__get with:
  - key: "{domain}:{entity}:{identifier}:{field}"
```

If the key is not found or TTL expired → recompute and re-store.

### Flow 2: Time-Series Tracking

**When to use:** Observing a metric that changes over time — adapter latency, quality scores, task duration, service uptime.

**Step 1: Record a data point**

```
Call mcp__dhara__record_time_series with:
  - metric_type: what kind of metric (e.g., "adapter_latency")
  - entity_id: what entity it applies to (e.g., "crackerjack:adapter:ruff")
  - record: {
      "value": <number>,
      "unit": "<unit string>",
      "source": "<where this came from>"
    }
```

**Step 2: Query historical data**

```
Call mcp__dhara__query_time_series with:
  - metric_type: the metric to query
  - entity_id: the entity to query
  - start_date: "YYYY-MM-DD" format (optional, defaults to recent)
  - limit: max records to return (optional)
```

**Step 3: Detect cross-metric patterns**

```
Call mcp__dhara__aggregate_patterns with:
  - start_date: "YYYY-MM-DD" format
  - min_occurrences: 2 (default, filter noise)
```

If patterns found → tell the user about interesting correlations or trends.

### Flow 3: Adapter Registry

**When to use:** Before relying on an adapter for critical work, when exploring what adapters are available, or when registering a new adapter.

**Step 1: Discover available adapters**

```
Call mcp__dhara__list_adapters with:
  - domain: "adapter" | "service" | "task" (optional, null for all)
  - category: "storage" | "cache" | "database" (optional, null for all)
```

**Step 2: Get specific adapter details**

```
Call mcp__dhara__get_adapter with:
  - domain: the adapter domain (e.g., "adapter")
  - key: the adapter key (e.g., "redis")
  - provider: the provider name (e.g., "redis")
  - version: specific version (optional, defaults to latest)
```

**Step 3: Validate before critical use**

```
Call mcp__dhara__validate_adapter with:
  - domain: the adapter domain
  - key: the adapter key
  - provider: the provider name
```

This checks: factory path importable, dependencies available, configuration valid, capabilities declared.

**Step 4: Check adapter health**

```
Call mcp__dhara__get_adapter_health with:
  - domain: the adapter domain
  - key: the adapter key
  - provider: the provider name
```

Returns healthy/unhealthy status. Use this before relying on an adapter for critical work.

**Step 5: View version history (diagnostic)**

```
Call mcp__dhara__list_adapter_versions with:
  - domain: the adapter domain
  - key: the adapter key
  - provider: the provider name
```

Shows version history with timestamps and changelogs. Useful for debugging adapter issues.

**Step 6: Register new adapter (rare)**

Only when adding a genuinely new adapter — not for normal workflow.

```
Call mcp__dhara__store_adapter with:
  - domain: "adapter" | "service" | "task"
  - key: adapter key
  - provider: provider name
  - version: semantic version (e.g., "1.0.0")
  - factory_path: Python import path for adapter factory
  - config: configuration dict (optional)
  - dependencies: list of required adapter keys (optional)
  - capabilities: list of capability strings (optional)
  - metadata: additional metadata dict (optional)
```

### Flow 4: Service Lifecycle

**When to use:** A service starts, stops, deploys, or changes health status. Building a living map of the ecosystem.

**Step 1: Record a lifecycle event**

```
Call mcp__dhara__record_event with:
  - event_type: "startup" | "shutdown" | "deployment" | "health_change" | "configuration_change"
  - source_service: the service that generated the event
  - payload: event details dict (optional)
  - related_service: affected service (optional)
  - timestamp: ISO timestamp (optional, defaults to now)
```

**Step 2: Update service record**

```
Call mcp__dhara__upsert_service with:
  - service_id: unique service identifier
  - service_type: "mcp_server" | "adapter" | "worker" | "orchestrator"
  - status: "unknown" | "healthy" | "degraded" | "unhealthy" | "maintenance"
  - capabilities: list of capability strings (optional)
  - metadata: additional metadata dict (optional)
  - heartbeat_at: ISO timestamp of last heartbeat (optional)
```

**Step 3: Discover services**

```
Call mcp__dhara__list_services with:
  - status: filter by status (optional)
  - capability: filter by capability (optional)
  - service_type: filter by type (optional)
```

**Step 4: Get service details**

```
Call mcp__dhara__get_service with:
  - service_id: the service to retrieve
```

**Step 5: Query event history (diagnostic)**

```
Call mcp__dhara__list_events with:
  - source_service: filter by source (optional)
  - event_type: filter by type (optional)
  - related_service: filter by related service (optional)
  - limit: max events to return (optional, default 100)
```

## Key Naming Conventions

### Key-Value Keys

Use structured keys: `{domain}:{entity}:{identifier}:{field}`

Examples: `mahavishnu:pool:default:status`, `crackerjack:adapter:ruff:effectiveness`, `ecosystem:service:mahavishnu:heartbeat`

### Time-Series Identifiers

Use consistent `metric_type` and `entity_id` values across sessions:

| metric_type | entity_id Pattern | When to Record |
|---|---|---|
| `adapter_latency` | `crackerjack:adapter:{name}` | After observing adapter execution time |
| `adapter_success_rate` | `crackerjack:adapter:{name}` | After adapter completes (success or failure) |
| `pool_task_duration` | `mahavishnu:pool:{pool_id}` | After pool task completes |
| `service_uptime` | `ecosystem:service:{service_id}` | During health checks |
| `quality_score` | `crackerjack:repo:{repo_path}` | After quality gate runs |

### Service Identifiers

Use lowercase, hyphenated names. Standard Bodai services:

| Service | service_id | service_type |
|---|---|---|
| Mahavishnu | `mahavishnu` | `orchestrator` |
| Session-Buddy | `session-buddy` | `manager` |
| Crackerjack | `crackerjack` | `inspector` |
| Akosha | `akosha` | `soothsayer` |
| Dhara | `dhara` | `curator` |

Standard event types: `startup`, `shutdown`, `deployment`, `health_change`, `configuration_change`, `performance_degradation`.

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| **Persisting everything** | Storage bloat, noise in queries | Apply the durability test — only persist what has future value |
| **No TTL on cached data** | Stale cache entries served indefinitely | Always set TTL on cached computations (1-24h) |
| **Inconsistent key names** | Can't retrieve stored values | Follow the `{domain}:{entity}:{id}:{field}` convention |
| **Recording time-series without entity_id** | Can't query by entity later | Always include a structured entity_id |
| **Validating adapter after critical failure** | Too late — work already failed | Validate BEFORE relying on adapter for critical work |
| **Missing heartbeat in upsert_service** | Stale service status | Always include `heartbeat_at` with current timestamp |
| **Recording events for trivia** | Event log noise | Only record events that indicate meaningful state changes |

## When NOT to Activate

- **Scratch calculations:** Temporary variables, intermediate computations
- **One-time lookups:** Values with no reuse potential
- **Already persisted:** Data stored in Session-Buddy, git, or other durable systems
- **User preferences:** Use Claude Code memory system for user-level preferences
- **Auto-generated data:** Boilerplate, scaffolding, generated code
- **Sensitive data:** Don't persist secrets, API keys, or credentials in Dhara

## Related Skills

- `learn-from-errors` — Error learning that may produce time-series data (error frequency)
- `code-knowledge-builder` — Code graph enrichment that may identify adapter relationships
- `ecosystem-awareness` — Repo discovery that complements service lifecycle tracking
- `run-quality-checks` — Quality gate results worth tracking as time-series
- `capture-insights` — Broader insight capture (use Session-Buddy for knowledge, Dhara for state)

## Complementary Relationship

```
learn-from-errors          persistent-state          code-knowledge-builder
      |                          |                          |
   Reactive                   Reactive                   Reactive
      |                          |                          |
 Error fixed               State needs              Code explored/
      |                      durability                   edited
      |                          |                          |
 Records error->fix         Persists to:              Records code
 via Session-Buddy          - Key-value store         structure
      |                      - Time-series               |
      |                      - Adapter registry           |
      |                      - Service events             |
      |                          |                          |
      +---- All three feed into the Bodai ecosystem ----+
                                    |
                          Future sessions benefit from:
                          - Faster debugging (seen before)
                          - Durable state (survives restarts)
                          - Code understanding (graph context)
                          - Adapter intelligence (registry)
                          - Service awareness (lifecycle)
```

## MCP Tools Used

| Tool | Cluster | Purpose | Required |
|------|---------|---------|----------|
| `mcp__dhara__put` | Key-Value | Store value with optional TTL | Yes |
| `mcp__dhara__get` | Key-Value | Retrieve value by key | Yes |
| `mcp__dhara__record_time_series` | Time-Series | Record a metric data point | Yes |
| `mcp__dhara__query_time_series` | Time-Series | Query historical metrics | Yes |
| `mcp__dhara__aggregate_patterns` | Time-Series | Find patterns across metrics | Yes |
| `mcp__dhara__list_adapters` | Adapter Registry | List available adapters | Yes |
| `mcp__dhara__get_adapter` | Adapter Registry | Get specific adapter details | Yes |
| `mcp__dhara__validate_adapter` | Adapter Registry | Validate adapter configuration | Yes |
| `mcp__dhara__get_adapter_health` | Adapter Registry | Check adapter health | Yes |
| `mcp__dhara__list_adapter_versions` | Adapter Registry | View version history | No (diagnostic) |
| `mcp__dhara__store_adapter` | Adapter Registry | Register new adapter | No (rare) |
| `mcp__dhara__upsert_service` | Service Lifecycle | Create/update service record | Yes |
| `mcp__dhara__list_services` | Service Lifecycle | List services with filters | Yes |
| `mcp__dhara__get_service` | Service Lifecycle | Get service details | Yes |
| `mcp__dhara__record_event` | Service Lifecycle | Record lifecycle event | Yes |
| `mcp__dhara__list_events` | Service Lifecycle | Query event history | No (diagnostic) |

**Total: 14 required, 2 diagnostic. Covers 16 of ~20 Dhara MCP tools.**