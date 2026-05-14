# Shared Foundation Adoption Matrix

**Date:** 2026-05-11
**Status:** `draft`, `matrix`
**Owner:** Core Eng
**Purpose:** Define the adoption boundaries needed before C6a deletion batches can start.

This matrix is the C6a companion artifact for the deletion/adoption ledger. It establishes event roles, WebSocket boundaries, and the minimal migration-task framing for active repos.

## 1. Event Adoption Roles

| Repo | Role | Notes |
|---|---|---|
| `mahavishnu` | `producer`, `consumer` | Primary control plane; emits canonical envelopes and consumes shared bus events, recovery state, and notification fan-out. |
| `oneiric` | `producer`, `consumer` | Owns EventBridge, EventDispatcher, NotificationRouter, and transport adapters. |
| `mcp-common` | `none` | Shared MCP primitives only; does not own Bodai event topics. |
| `crackerjack` | `consumer` | Consumes validation and quality-gate results; publishes validation artifacts only through its own provider/validation pipeline. |
| `session-buddy` | `consumer` | Consumes fix/session context and checkpoint recovery; does not own the shared event spine. |
| `akosha` | `consumer` | Consumes derived memory/search inputs with correlation IDs; does not own primary state. |
| `dhara` | `consumer` | Stores operational state/recovery checkpoints only. |
| `mdinject` | `none` | Client surface only unless audits prove an active direct dependency. |

## 2. WebSocket / Event Boundary Tests

| Boundary | Test focus | Expected outcome |
|---|---|---|
| `oneiric` EventBridge vs Mahavishnu WebSocket handler | EventBridge emits canonical envelopes; WebSocket handler maps topic patterns to rooms | Rooms receive the same topic/correlation metadata that the envelope carried |
| `mcp-common` protocol helpers vs service-specific event code | Shared protocol stays transport-agnostic | Service repos own domain mapping only; no local copy of shared protocol logic remains |
| NotificationRouter vs alert adapters | Notification fan-out is routed through the canonical notification path | Oneiric owns routing, service repos only register adapters/topics |
| DLQ vs replay consumer | Exhausted handlers land in the Mahavishnu DLQ and are replayable on recovery | Failed deliveries are retained and visible in recovery surfaces |

## 3. Migration Task Template

Each consumer repo should have one migration task entry per active replacement:

- repo
- candidate module or command
- canonical replacement
- behavior to preserve
- parity test file
- validation command
- release note requirement
- rollback note

## 4. Current C6a-Ready Consumers

| Repo | Candidate batch | Canonical replacement | Status |
|---|---|---|---|
| `mahavishnu` | learning/team-learning surface consolidation | `core/skill_governance.py`, `core/learning_pipeline.py`, `core/skill_registry.py` | ledger seeded |
| `mahavishnu` | composition-root split | smaller service wiring modules | ledger seeded |
| `crackerjack` | CLI alias/service-root cleanup | canonical validation pipeline and provider registry | ledger seeded |
| `session-buddy` | monitoring/fan-out cleanup | EventBridge subscriptions and shared MCP primitives | ledger seeded |
| `mcp-common` | local shared primitive copies | shared MCP server/session primitives | ledger seeded |
| `akosha` | storage-assumption cleanup | derived search/intelligence only | ledger seeded |
| `dhara` | storage entry-point consolidation | one operational-state contract and one object/blob contract | ledger seeded |
| `mdinject` | direct dependency audit | Bodai MCP APIs | audit-only |

## 5. Concrete Adoption Task Packets

### Oneiric

| Candidate | Current anchor | Canonical replacement | Validation hook | Notes |
|---|---|---|---|---|
| EventBridge / EventDispatcher promotion | `oneiric/runtime/events.py` | stable library contract consumed by Mahavishnu | `tests/runtime/test_parity_prototypes.py` and Oneiric runtime contract tests | Event envelope metadata and handler fan-out are the canonical event spine boundary. |
| NotificationRouter adoption | `oneiric/runtime/notifications.py` | shared notification routing contract | notification adapter contract tests | Service repos should stop duplicating direct notification dispatch paths. |
| Redis transport extension | `oneiric/adapters/queue/redis_streams.py` | dual-mode queue/pubsub transport | queue adapter tests | Pub/Sub and stream replay are the transport primitive for C1b/C6a. |
| WebSocket handler integration | `oneiric/adapters/bridge.py`, `oneiric/runtime/events.py` | event handler interface | runtime bridge tests | WebSocket remains a consumer-side handler, not the authority for routing. |

### mcp-common

| Candidate | Current anchor | Canonical replacement | Validation hook | Notes |
|---|---|---|---|---|
| WebSocket server/protocol helpers | `mcp_common/websocket/server.py`, `mcp_common/websocket/protocol.py` | shared WebSocket protocol/server primitives | websocket server tests | Keep transport-agnostic helpers only. |
| Health primitives | `mcp_common/health.py`, `mcp_common/cli/health.py` | shared health contract | health contract tests | Service repos should consume the shared contract rather than maintain local variants. |
| Auth primitives | `mcp_common/auth/core.py`, `mcp_common/auth/config.py` | shared auth contract | auth contract tests | Preserve the JWT/auth boundary already shared across Bodai repos. |
| Server runtime helpers | `mcp_common/server/base.py`, `mcp_common/server/runtime.py`, `mcp_common/server/telemetry.py` | shared server lifecycle primitives | server runtime tests | Remove duplicated lifecycle glue from service repos after adoption. |

### Crackerjack

| Candidate | Current anchor | Canonical replacement | Validation hook | Notes |
|---|---|---|---|---|
| MCP/server root and tool registration | `crackerjack/mcp/server_core.py`, `crackerjack/mcp/tools/*` | canonical validation pipeline and provider registry | MCP server tests | Keep only the validation surfaces the consumer repos need. |
| CLI provider-selection and health options | `crackerjack/cli/handlers/provider_selection.py`, `crackerjack/cli/handlers/health.py` | canonical provider/config pipeline | CLI regression tests | Retain user-facing compatibility until provider registry adoption is complete. |
| Legacy service roots | `crackerjack/services/*` | focused `services/*` replacements and shared foundation contracts | service contract tests | Deletion waits on the adoption ledger for each specific service cluster. |
| WebSocket/auth helpers | `crackerjack/websocket/server.py`, `crackerjack/websocket/auth.py` | mcp-common and Oneiric shared primitives | websocket/auth contract tests | Delegate shared protocol code before removing local copies. |

### Session-Buddy

| Candidate | Current anchor | Canonical replacement | Validation hook | Notes |
|---|---|---|---|---|
| Session context checkpoint path | session-buddy repo-local checkpointing modules | Dhara + shared recovery contract | session/recovery contract tests | Keep local session persistence; remove only duplicate operational-checkpoint adapters. |
| Monitoring / MCP fan-out helpers | session-buddy repo-local monitoring and MCP modules | EventBridge subscriptions plus mcp-common primitives | MCP registration tests | Event fan-out should become a consumer-side subscription pattern. |

## 6. Migration Task Entries

| Task ID | Repo | Entry | Audit command | Validation | Status |
|---|---|---|---|---|---|
| `C6a-O1` | `oneiric` | Promote `EventBridge` / `EventDispatcher` as library contracts and freeze the event-envelope metadata boundary | `rg -n "EventBridge|EventDispatcher|EventEnvelope|NotificationRouter" /Users/les/Projects/oneiric` | Oneiric runtime contract tests | complete |
| `C6a-O2` | `oneiric` | Lock the Redis dual-mode transport (`pubsub_publish`, `pubsub_subscribe`) and WebSocket handler bridge as the canonical fan-out surface | `rg -n "pubsub_publish|pubsub_subscribe|WebSocketEventHandler|RedisStreamsQueueAdapter" /Users/les/Projects/oneiric` | queue adapter and runtime bridge tests | complete |
| `C6a-M1` | `mcp-common` | Track websocket/server/auth/health/runtime helper adoption into shared primitives and remove local copies only after parity | `rg -n "websocket|health|auth|server|telemetry" /Users/les/Projects/mcp-common` | websocket/auth/health/server tests | complete |
| `C6a-C1` | `crackerjack` | Record provider-selection and CLI/service-root cleanup tasks against the canonical validation pipeline | `rg -n "provider_selection|services/|health|websocket|mcp" /Users/les/Projects/crackerjack` | provider-chain and CLI regression tests | planned |
| `C6a-S1` | `session-buddy` | Keep session context persistence while moving realtime fan-out to EventBridge-style subscription callbacks | `rg -n "health|mcp|websocket|event|fan[- ]?out|checkpoint|subscriber" /Users/les/Projects/session-buddy` | session/recovery and MCP registration tests | in progress |
| `C6a-A1` | `akosha` | Audit derived-intelligence/search-only boundaries and preserve correlation IDs on writes | `rg -n "storage|primary|health|websocket|auth|correlation" /Users/les/Projects/akosha` | search/index contract tests | in progress |
| `C6a-D1` | `dhara` | Consolidate storage entry points under one operational-state contract and one object/blob contract | `rg -n "file_storage|file_storage2|storage_server|backup|mcp storage" /Users/les/Projects/dhara` | durable-state contract tests | in progress |
| `C6a-MD1` | `mdinject` | Audit for direct event/session/memory/orchestration/storage dependencies and keep as no-op unless a live dependency exists | `rg -n "event|session|memory|orchestration|storage" /Users/les/Projects/mdinject` | audit-only regression checks | complete |
