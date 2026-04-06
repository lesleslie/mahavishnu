# Event Envelope Specification

## Overview

All inter-component events in Mahavishnu use a typed, versioned envelope
(`EventEnvelope`) to guarantee identity, schema compatibility, causal tracing,
and deterministic serialization.

## Standard Envelope Schema

```
EventEnvelope (Pydantic BaseModel, frozen)
├── event_id: UUID          — UUIDv4, unique per event
├── event_type: str         — domain enum value, e.g. "code.graph.indexed"
├── version: str            — semver "MAJOR.MINOR.PATCH", default "1.0.0"
├── timestamp: datetime     — UTC, auto-set on creation
├── source: str             — producing component, e.g. "code_index_service"
├── correlation_id: UUID?   — for cross-service tracing (optional)
├── payload: dict           — domain-specific data (validated by schema registry)
└── metadata: dict          — tracing, audit, system metadata
```

### Field Constraints

| Field         | Type     | Required | Constraints              |
|---------------|----------|----------|--------------------------|
| event_id      | UUID     | yes      | auto-generated UUIDv4    |
| event_type    | str      | yes      | 1–128 chars, non-blank   |
| version       | str      | yes      | semver, validated by EventVersion |
| timestamp     | datetime | yes      | UTC, auto-generated      |
| source        | str      | yes      | 1–128 chars, non-blank   |
| correlation_id| UUID?    | no       | for distributed tracing  |
| payload       | dict     | yes      | validated per schema     |
| metadata      | dict     | yes      | defaults to empty dict   |

## Versioning Policy

- **Semantic versioning** on `version` field: MAJOR.MINOR.PATCH
- **Same MAJOR** = backward compatible (consumer can safely read)
- **MAJOR bump** = breaking change (requires explicit migration)
- Consumers use `EventVersion.is_compatible_with()` to gate processing
- `CompatibilityPolicy.check_compatibility()` returns PATCH/MINOR/MAJOR level

### Compatibility Rules

| Producer | Consumer | Compatible? | Level  |
|----------|----------|-------------|--------|
| 1.0.0    | 1.0.0    | Yes         | PATCH  |
| 1.1.0    | 1.0.0    | Yes         | MINOR  |
| 1.0.0    | 1.1.0    | No          | —      |
| 2.0.0    | 1.0.0    | No          | MAJOR  |

## Schema Registry

Built-in schemas registered at startup for all Mahavishnu event types:

| Event Type                | Version | Required Fields           |
|---------------------------|---------|---------------------------|
| code.graph.indexed        | 1.0.0   | repo_path, nodes_count    |
| code.graph.index_failed   | —       | —                         |
| code.graph.cache_invalidated | —    | —                         |
| worker.started            | 1.0.0   | worker_id, worker_type    |
| worker.stopped            | 1.0.0   | worker_id                 |
| worker.status_changed     | 1.0.0   | worker_id, status         |
| worker.error              | 1.0.0   | worker_id, error          |
| backup.started            | 1.0.0   | backup_type               |
| backup.completed          | 1.0.0   | backup_id                 |
| backup.failed             | 1.0.0   | error                     |
| backup.restored           | 1.0.0   | backup_id                 |
| pool.spawned              | 1.0.0   | pool_id, pool_type        |
| pool.closed               | 1.0.0   | pool_id                   |
| pool.scaled               | 1.0.0   | pool_id, target_workers   |
| workflow.started          | 1.0.0   | workflow_id               |
| task.created              | 1.0.0   | task_id                   |

## Implementation

- **Module**: `mahavishnu/core/events/envelope.py`
- **Schema Registry**: `mahavishnu/core/events/schema_registry.py`
- **Compatibility**: `mahavishnu/core/events/compatibility.py`
- **Migration**: `mahavishnu/core/events/migration.py`

## Publishing

The `EventBus` provides two paths:

1. `publish(event_type, data, source)` — legacy, auto-wraps in EventEnvelope
2. `publish_envelope(envelope)` — preferred, explicit envelope construction

All persisted events include the envelope JSON in a dedicated `envelope` column.
