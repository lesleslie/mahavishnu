# Bodai Unified Event Bus — Standardization Plan

## Metadata

- Status: `draft`
- Owner: `Core Eng`
- Target Window: `2026-05-18` to `2026-06-30`
- Prerequisite: Oneiric integration in Mahavishnu (MCP or library mode)

______________________________________________________________________

## 1. Outcome

All Bodai components publish events through a **single unified event bus** backed by Oneiric's `EventBridge` + `EventDispatcher`, with Redis Streams as the transport layer. Mahavishnu adopts Oneiric as a library. Fragmented parallel event systems are removed. The WebSocket server becomes an EventBridge handler. All failed events land in Mahavishnu's existing DLQ. All notification adapters are wired through Oneiric's `NotificationRouter`.

______________________________________________________________________

## 2. Architecture Summary

### After (target state)

```
CODE                          MAHAVISHNU                        ONEIRIC
 ─────                         ────────                         ───────
 EventBridge.emit(topic, payload)
         │
         │              ┌──────────────────────────────────────┐
         │              │         Event Bus Consumer           │
         │              │  (pulls from Redis Streams / Pub/Sub)│
         │              └──────────────┬───────────────────────┘
         │                             │
         │         ┌──────────────────┴──────────────────┐
         │         │              Redis                    │
         │         │  ┌──────────────────────────────┐    │
         │         │  │  Streams (durable log)        │    │
         │         │  │  ← XADD (persist)             │    │
         │         │  │  XREADGROUP (consumer)       │    │
         │         │  └──────────────────────────────┘    │
         │         │  ┌──────────────────────────────┐    │
         │         │  │  Pub/Sub (real-time fan-out)  │    │
         │         │  │  ← SUBSCRIBE (topics)        │    │
         │         │  └──────────────────────────────┘    │
         │         └──────────────────┬───────────────────────┘
         │                            │
         │                            ▼
         │                    EventDispatcher
         │                            │
         │                   ┌────────┼────────┐
         │                   │        │        │
         │               Handler[] Handler[] Handler[]
         │               (domain   (notif-  (webhook)
         │               logic)     ication)
         │                   │        │        │
         │                   │        ▼        ▼
         │                   │  NotificationRouter
         │                   │       │
         │                   │  ┌──┬──┬──┬──┬──┬──┐
         │                   │  │slack│teams│fcm│apns│...│
         │                   │  └──┴──┴──┴──┴──┴──┘
         │
         │         WebSocketEventHandler (subscriber)
         │                   │
         │                   ▼
         │          WebSocket rooms (workflow:*,
         │          pool:*, worker:*, global, ...)
         │
         │         DLQEventHandler (on retry exhaustion)
         │                   │
         │                   ▼
         │         Mahavishnu DeadLetterQueue
```

### Before (current state)

Mahavishnu has four independent event-like systems that never talk to each other or to Oneiric:

- `EventBus` — SQLite-backed, in-process, own `EventType` enum
- `TaskEventEmitter` — in-process pub/sub for task lifecycle
- `MessageBus` — inter-pool async queue (pool-scoped)
- `Monitoring/Alerting` — `AlertChannel.send_notification(Alert)` with email/slack/webhook

Oneiric has:

- `EventBridge` + `EventDispatcher` — topic-based pub/sub with priority, retry, fanout
- `NotificationRouter` — routes to messaging adapters (Slack, Teams, FCM, APNs, WebPush, Webhook)
- Queue adapters (Redis Streams, NATS, Kafka, RabbitMQ, GCP Pub/Sub, CloudTasks) — available but not wired into EventBridge

WebSocket (`MahavishnuWebSocketServer`, ports 8690/8691) operates as a standalone channel — publishing directly via its own broadcast methods, not through any event bus.

______________________________________________________________________

## 3. Key Decisions

### 3.1 Integration Model

**Decision:** Mahavishnu consumes Oneiric as a library (`from oneiric.runtime.orchestrator import RuntimeOrchestrator`, or individual components like `EventBridge`, `EventDispatcher`).

**Rationale:** Tight coupling is appropriate here — event bus is infrastructure, not a remote service. Library mode gives Mahavishnu full access to Oneiric's adapter resolution, lifecycle management, and config layering without network overhead or API versioning concerns.

### 3.2 Event Transport (Redis Dual-Mode via Extended RedisStreamsQueueAdapter)

**Decision:** Redis in dual mode — Pub/Sub for real-time fan-out, Streams for durability — via an extended `RedisStreamsQueueAdapter` (no parallel transport layer needed).

**Rationale:** `RedisStreamsQueueAdapter` already exists in Oneiric with `capabilities=["queue", "pubsub", "fanout"]` but currently only implements queue operations (Streams). Since we own Oneiric, we extend it directly with pub/sub methods rather than building a parallel transport layer.

**Changes to `RedisStreamsQueueAdapter`:**

Add two methods to the adapter:

```python
async def pubsub_publish(self, channel: str, message: str | bytes) -> None:
    """Publish to a pub/sub channel. Fan-out to all subscribers."""
    client = self._ensure_client("redis-streams-client-not-initialized")
    if isinstance(message, str):
        message = message.encode("utf-8")
    await client.publish(channel, message)

async def pubsub_subscribe(
    self,
    channel: str | None = None,
    pattern: str | None = None,
    *,
    callback: Callable[[str, str], Awaitable[None]],
) -> Any:
    """Subscribe to a channel or pattern. Calls callback(channel, message) on each message."""
    # Uses coredis async pubsub (https://redise.readthedocs.io/en/latest/usage/pubsub/)
    subscriber = self._client.pubsub()
    if channel:
        await subscriber.subscribe(channel)
    if pattern:
        await subscriber.psubscribe(pattern)

    async def listener():
        async for message in subscriber.listen():
            channel_name = message["channel"]
            data = message["data"]
            await callback(channel_name, data)

    return asyncio.create_task(listener())
```

Add settings fields to `RedisStreamsQueueSettings`:

```python
pubsub_channel_prefix: str = Field(
    default="bodai:events:",
    description="Prefix for pub/sub channel names. Channels are 'prefix + topic'.",
)
```

**Event transport pattern:**

1. **`RedisEventTransport.publish(envelope)`** (replaces standalone file, becomes a thin wrapper or inline helper):

   - Calls `adapter.pubsub_publish("bodai:events:{topic}", envelope_json)` — real-time fan-out
   - Calls `adapter.enqueue(envelope.to_dict())` — persists to stream

1. **`EventBusConsumer`** (background subscriber):

   - `pubsub_subscribe(pattern="bodai:events:*", callback=on_event)` — pattern subscribe receives all topic channels
   - On each message → dispatch to local `EventDispatcher`
   - On startup: `read()` replays unacknowledged entries from the stream

1. **Reconnection:** `EventBusConsumer` handles reconnection; coredis pub/sub subscriber auto-reconnects at the protocol level.

**Redis channel naming:**

- Pub/Sub: `bodai:events:{topic}` (e.g., `bodai:events:pool.spawned`)
- Stream: `bodai:events` (single stream for all events)

### 3.3 Event Envelope

**Decision:** Extend Oneiric's `EventEnvelope` with Bodai-standard fields.

**Rationale:** Oneiric's envelope is minimal (`topic + payload + headers`). Mahavishnu's envelope has `event_id`, `version`, `timestamp`, `source`, `correlation_id` — all valuable. Rather than lose them, extend Oneiric's schema. After extension, drop `mahavishnu/core/events/envelope.py` entirely.

**Extended `EventEnvelope` (Oneiric):**

```python
class EventEnvelope(msgspec.Struct):
    topic: str                          # e.g. "pool.spawned"
    payload: dict[str, Any]             # event-specific data
    headers: dict[str, Any] = {}       # ext: event_id, source, correlation_id, version, timestamp

# Headers convention:
#   headers["event_id"]: str          — UUID4, unique per event
#   headers["source"]: str            — producing component
#   headers["correlation_id"]: str    — UUID for distributed tracing
#   headers["version"]: str            — semver "MAJOR.MINOR.PATCH"
#   headers["timestamp"]: str          — ISO 8601 UTC
```

This keeps Oneiric's msgspec struct clean while adding Bodai metadata via headers. No changes to EventDispatcher logic required.

### 3.4 WebSocket Integration

**Decision:** WebSocket server becomes an EventBridge handler (subscriber).

**Rationale:** WebSocket's value is real-time push to connected clients — not event routing. Making it a handler is the cleanest integration: code publishes events to `EventBridge.emit()` as normal. WebSocket handler subscribes to topics and fans out to rooms.

**Implementation:** `WebSocketEventHandler` implements `EventHandlerProtocol.handle(envelope)`. Maps topic patterns to room names:

| Topic Pattern | WebSocket Room | Fanout |
|---|---|---|
| `workflow.*` | `workflow:{workflow_id}` | to specific workflow room |
| `pool.*` | `pool:{pool_id}` | to specific pool room |
| `worker.*` | `pool:{pool_id}` | to parent pool room |
| `code.*` | `code` | global code events |
| `backup.*` | `global` | system-wide |
| `adapter.*` | `adapters` | adapter registry |
| `symbiotic.*` | `symbiotic:ecosystem` | ecosystem learning |
| `goal-teams.*` | `goal-teams` | team events |

Clients subscribe to rooms via WebSocket protocol (`subscribe` / `unsubscribe` request). No direct coupling between Mahavishnu code and WebSocket — both just use EventBridge.

### 3.5 Correlation and Tracing

**Decision:** `correlation_id` and `causation_id` go into `EventEnvelope.headers`.

**Implementation:** Add a helper in Mahavishnu's event helpers:

```python
def create_event_envelope(
    topic: str,
    payload: dict,
    source: str,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> EventEnvelope:
    """Create a Bodai-standard EventEnvelope with full metadata."""
    envelope_id = str(uuid.uuid4())
    return EventEnvelope(
        topic=topic,
        payload=payload,
        headers={
            "event_id": envelope_id,
            "source": source,
            "correlation_id": correlation_id or ulid_or_uuid(),
            "causation_id": causation_id,
            "version": "1.0.0",
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
```

A new `EventContext` class carries `correlation_id` through a workflow:

```python
@dataclass
class EventContext:
    correlation_id: str
    causation_stack: list[str] = field(default_factory=list)

    def child(self, causation_id: str) -> "EventContext":
        """Create child context with causation chain."""
        return EventContext(
            correlation_id=self.correlation_id,
            causation_stack=[*self.causation_stack, causation_id],
        )
```

`EventContext` is created at workflow start and threaded through all `emit()` calls.

### 3.6 Topic Mapping

**Decision:** Migrate all Mahavishnu `EventType` values to Oneiric topic strings.

No new topics introduced — all existing events map 1:1:

| Mahavishnu `EventType` | Oneiric Topic | Notes |
|---|---|---|
| `CODE_GRAPH_INDEXED` | `code.graph.indexed` | |
| `CODE_GRAPH_INDEX_FAILED` | `code.graph.index_failed` | |
| `CODE_GRAPH_CACHE_INVALIDATED` | `code.graph.cache_invalidated` | |
| `WORKER_STARTED` | `worker.started` | |
| `WORKER_STOPPED` | `worker.stopped` | |
| `WORKER_STATUS_CHANGED` | `worker.status_changed` | |
| `WORKER_ERROR` | `worker.error` | |
| `BACKUP_STARTED` | `backup.started` | |
| `BACKUP_COMPLETED` | `backup.completed` | |
| `BACKUP_FAILED` | `backup.failed` | |
| `BACKUP_RESTORED` | `backup.restored` | |
| `POOL_SPAWNED` | `pool.spawned` | |
| `POOL_CLOSED` | `pool.closed` | |
| `POOL_SCALED` | `pool.scaled` | |

New topics for Mahavishnu monitoring events:

| Topic | Trigger |
|---|---|
| `alert.critical` | Critical severity alert triggered |
| `alert.warning` | Warning/medium alert triggered |
| `alert.resolved` | Previously firing alert resolved |
| `workflow.stage_completed` | Workflow stage finished |
| `workflow.failed` | Workflow failed |

### 3.7 DLQ Integration

**Decision:** Wire exhausted EventDispatcher retries to Mahavishnu's existing `DeadLetterQueue`.

**Implementation:**

- `EventDispatcher._run_handler` already has a retry loop via `run_with_retry`. When retries exhaust, the exception propagates.
- Add a new handler type: `DLQEventHandler` registered on every event topic.
- On `HandlerResult.success == False` after max attempts, the DLQ handler enqueues the failed event:

```python
class DLQEventHandler:
    def __init__(self, dlq: DeadLetterQueue):
        self._dlq = dlq

    async def handle(self, envelope: EventEnvelope) -> None:
        event_id = envelope.headers.get("event_id", "unknown")
        await self._dlq.enqueue(
            task_id=event_id,
            task={"envelope": envelope.payload},
            repos=[],  # no repos for pure event failures
            error=f"Event handler exhausted retries: {envelope.topic}",
            retry_policy=RetryPolicy.EXPONENTIAL,
            max_retries=3,
            event_envelope=envelope.to_dict(),  # store full envelope for replay
        )
```

- `FailedTask` gets a new optional field `event_envelope: dict | None = None` to store the full failed envelope for replay/retry.
- Existing Mahavishnu DLQ workflows (task_id + repos + task payload) are unaffected — they already use a different code path.

### 3.8 Notification Adapters

**Decision:** Wire all available adapters.

| Adapter | Purpose | Configuration |
|---|---|---|
| `SlackAdapter` | Team alerts | `SLACK_TOKEN` env var, `default_channel` |
| `TeamsAdapter` | Team alerts (alternative) | `webhook_url` |
| `FCMAdapter` | Android push | Firebase credentials |
| `APNsAdapter` | iOS push | APNs credentials |
| `WebPushAdapter` | Browser push | VAPID keys |
| `WebhookAdapter` | Generic webhooks | per-route `webhook_url` |

Notification routing via Oneiric's `NotificationRouter` with topic-based rules:

| Topic | Default Adapter | Note |
|---|---|---|
| `alert.critical` | Slack + Teams | high-severity needs both |
| `alert.warning` | Slack | medium alerts |
| `backup.failed` | Slack | backup failures need attention |
| `workflow.failed` | Slack | workflow failures |
| `pool.spawned` | (none — internal only) | |
| `adapter.health_changed` | Slack | degraded adapter alert |

### 3.9 Migration: Drop and Replace

**Decision:** No compatibility shim. All callers migrate to Oneiric directly.

Rationale: This is a deliberate architectural migration, not a side-by-side rollout. Code that calls `mahavishnu.core.event_bus.EventBus` is migrated to `EventBridge.emit()`. Code that uses `mahavishnu.core.task_notifications` is migrated to EventBridge topics. No dual-path maintenance.

______________________________________________________________________

## 4. Work Packages

### Phase 1: Foundation (Week 1-2)

| ID | Task | Owner | Files |
|---|---|---|---|
| P1-1 | Extend Oneiric `EventEnvelope` with Bodai headers schema | Core Eng | `oneiric/runtime/events.py` |
| P1-2 | Add `EventContext` and `create_event_envelope()` helper | Core Eng | New: `mahavishnu/core/events.py` |
| P1-3 | Wire Redis event transport into `MahavishnuApp` initialization | Core Eng | `mahavishnu/core/config.py`, `mahavishnu/core/app.py` |
| P1-4 | Add `DLQEventHandler` integration with Mahavishnu `DeadLetterQueue` | Core Eng | `oneiric/domains/events.py` (or new handler file) |
| P1-5 | Extend `FailedTask` with `event_envelope` field | Core Eng | `mahavishnu/core/dead_letter_queue.py` |
| P1-6 | Register all Bodai topic schemas in Oneiric schema registry | Core Eng | `oneiric/` or new registry |

| P1-7 | Extend `RedisStreamsQueueAdapter` with `pubsub_publish()` and `pubsub_subscribe()` | Core Eng | `oneiric/adapters/queue/redis_streams.py` |
| P1-8 | Add `RedisEventTransport` (thin wrapper over extended adapter) + `EventBusConsumer` | Core Eng | New: `mahavishnu/core/event_bus_consumer.py` |
| P1-9 | Wire event transport into `MahavishnuApp` initialization | Core Eng | `mahavishnu/core/config.py`, `mahavishnu/core/app.py` |

### Phase 2: Migrate Mahavishnu (Week 2-3)

| ID | Task | Owner | Files |
|---|---|---|---|
| P2-1 | Migrate `EventBus` publishers to `EventBridge.emit()` | Core Eng | All call sites of `event_bus.publish()` |
| P2-2 | Migrate `TaskEventEmitter` to EventBridge topics | Core Eng | `mahavishnu/core/task_notifications.py` call sites |
| P2-3 | Migrate `AlertChannel.send_notification` to `NotificationRouter` | Core Eng | `mahavishnu/core/monitoring.py` |
| P2-4 | Add `WebSocketEventHandler` as EventBridge subscriber | Core Eng | `mahavishnu/websocket/handler.py` (new) |
| P2-5 | Remove `mahavishnu/core/event_bus.py` | Core Eng | Delete |
| P2-6 | Remove `mahavishnu/core/task_notifications.py` (or deprecate to stub) | Core Eng | Delete |
| P2-7 | Wire notification adapters in Mahavishnu config | Core Eng | `settings/mahavishnu.yaml` |

### Phase 3: Verification & Cleanup (Week 3-4)

| ID | Task | Owner | Files |
|---|---|---|---|
| P3-1 | Update all tests: replace `EventBus` with `EventBridge` | Core Eng | `tests/` |
| P3-2 | Add integration test: event published → Redis → handlers → notification | Core Eng | `tests/integration/` |
| P3-3 | Add DLQ test: handler exhausts retries → enqueued in DLQ | Core Eng | `tests/` |
| P3-4 | Add WebSocket test: event published → room broadcasted | Core Eng | `tests/` |
| P3-5 | Update CLAUDE.md / AGENTS.md event bus documentation | Core Eng | docs |
| P3-6 | Run Crackerjack full suite, fix regressions | Core Eng | CI |

### Phase 4: Documentation (Week 4)

| ID | Task | Owner | Files |
|---|---|---|---|
| P4-1 | Write event bus documentation: topics, headers convention, publishing guide | Core Eng | `docs/` |
| P4-2 | Document DLQ integration and event replay workflow | Core Eng | `docs/` |
| P4-3 | Update ADR for Bodai unified event bus (or new ADR) | Core Eng | `docs/adr/` |
| P4-4 | Add event bus to PLAN_INDEX.md as active initiative | Core Eng | `docs/plans/` |

______________________________________________________________________

## 5. File Inventory

### New Files

| File | Purpose |
|---|---|
| `mahavishnu/core/events.py` | `EventContext`, `create_event_envelope()`, topic constants, correlation helpers |
| `mahavishnu/core/event_bus_consumer.py` | `EventBusConsumer` — uses extended `RedisStreamsQueueAdapter` pub/sub methods, dispatches to EventDispatcher, handles startup replay |
| `mahavishnu/websocket/handler.py` | `WebSocketEventHandler` implementing `EventHandlerProtocol` (EventBridge subscriber) |
| `mahavishnu/core/events/dlq_handler.py` | `DLQEventHandler` — EventBridge handler that enqueues exhausted events to Mahavishnu DLQ |

### Deleted Files

| File | Reason |
|---|---|
| `mahavishnu/core/event_bus.py` | Replaced by Oneiric EventBridge |
| `mahavishnu/core/events/envelope.py` | Replaced by extended Oneiric EventEnvelope |
| `mahavishnu/core/events/schema_registry.py` | Schema registry moved to Oneiric |
| `mahavishnu/core/events/compatibility.py` | Compatibility logic moved to Oneiric |
| `mahavishnu/core/events/migration.py` | Migration helpers replaced |
| `mahavishnu/core/task_notifications.py` | Replaced by EventBridge topics |
| `mahavishnu/mcp/protocols/message_bus.py` | Pool messaging uses Redis Streams directly via Oneiric adapter |

### Modified Files

| File | Change |
|---|---|
| `oneiric/adapters/queue/redis_streams.py` | Add `pubsub_publish()` and `pubsub_subscribe()` methods, add `pubsub_channel_prefix` to settings |
| `oneiric/runtime/events.py` | Extend `EventEnvelope` headers schema, add Bodai-standard fields |
| `oneiric/domains/events.py` | Add DLQ integration after retry exhaustion |
| `mahavishnu/core/dead_letter_queue.py` | Add `event_envelope` field to `FailedTask` |
| `mahavishnu/core/monitoring.py` | Replace `AlertChannel` with `NotificationRouter` |
| `mahavishnu/websocket/server.py` | Refactor: extract broadcast logic to handler |
| `mahavishnu/core/app.py` | Initialize Oneiric RuntimeOrchestrator, wire EventBridge |
| `mahavishnu/core/config.py` | Add Oneiric/Redis Streams queue config section |
| `settings/mahavishnu.yaml` | Add notification adapters, Redis Streams transport config |

______________________________________________________________________

## 6. Dependencies

- `oneiric` ≥ latest (extended `EventEnvelope` headers schema, DLQ handler integration)
- `coredis` (Redis — Pub/Sub + Streams, already a dependency)
- `aiosqlite` (existing)
- `msgspec` (Oneiric — already a dependency)

______________________________________________________________________

## 7. Exit Criteria

- [ ] All Mahavishnu event publishing uses `EventBridge.emit()` via `RedisEventTransport` (Pub/Sub + Streams)
- [ ] `EventBusConsumer` subscribes to Redis Pub/Sub, dispatches to `EventDispatcher`
- [ ] `EventBusConsumer` replays missed events from Streams on startup
- [ ] `WebSocketEventHandler` fans out events to correct rooms
- [ ] All 6 notification adapters are configured and routable
- [ ] Failed events after retry exhaustion appear in Mahavishnu DLQ with full envelope
- [ ] `FailedTask.event_envelope` field is populated for event-sourced failures
- [ ] `EventContext` carries `correlation_id` through workflows
- [ ] All existing tests pass after migration (or explicitly skipped with migration-notes)
- [ ] Crackerjack full suite passes
- [ ] CLAUDE.md updated to remove references to old event systems
- [ ] ADR written documenting the unified event bus decision

______________________________________________________________________

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Partial migration leaves mixed event formats | Medium | High | Phase 2 is atomic: all old systems removed together |
| EventDispatcher retry exhaustion silently drops events | Medium | High | P1-4 wires DLQ before any event migration starts |
| WebSocket room mapping becomes stale as topics evolve | Low | Medium | Topic→room mapping in config, not hardcoded |
| Oneiric schema changes break Mahavishnu event schemas | Low | High | Semver on `version` field, compatibility checks |
| Redis Pub/Sub subscriber disconnects during heavy event flow | Low | Medium | Events persisted to Streams; `EventBusConsumer` auto-reconnects with exponential backoff; circuit breaker prevents tight retry loops |
| Redis unavailable during event publish | Low | Medium | Publishes to Streams synchronously (durability); Pub/Sub publish is best-effort; circuit breaker prevents cascading failures |

______________________________________________________________________

## 9. Open Questions

| Question | Decision Needed |
|---|---|
| Event replay from DLQ | Should replay re-publish to EventBridge, or invoke handlers directly? Recommend: re-publish to EventBridge so the full delivery chain runs |
| External event consumers | Is there any external consumer of Mahavishnu events that needs a migration window? |
| Event schema validation | Should `EventEnvelope.headers` be validated against the Bodai schema at publish time, or trust producers? |
