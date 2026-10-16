---
date: 2026-10-15
title: "Bodai EventBus — Wrapper-Layer Adoption of Oneiric EventBridge"
topic: unified-event-bus
status: active
kind: decision
supersedes_plan: 2026-05-09-unified-event-bus-spec.md
decision_date: 2026-10-15
---

# ADR — Bodai EventBus: Wrapper-Layer Adoption of Oneiric EventBridge

**Date:** 2026-10-15
**Status:** `active`, `decision`
**Supersedes:** [`docs/plans/2026-05-09-unified-event-bus-spec.md`](../plans/2026-05-09-unified-event-bus-spec.md)

## Context

The 2026-05-09 unified-event-bus spec called for a **hard-cut migration** of Mahavishnu's four fragmented event systems (`EventBus`, `TaskEventEmitter`, `MessageBus`, `AlertChannel`) onto Oneiric's `EventBridge` + `EventDispatcher` with Redis Streams + Pub/Sub transport, with WebSocket server as an `EventBridge` handler. The spec's intent was "drop and replace" with no compatibility shim.

The hard-cut migration did **not** ship. Instead, Mahavishnu built a wrapper layer that consumes Oneiric's EventBridge through a thin façade rather than directly. The wrapper path covers the same end states (single transport, single envelope shape, WebSocket fan-out) while preserving the per-component event interfaces that downstream code depends on.

## Decision

**Adopt Oneiric's `EventBridge` via wrapper layer, not via hard-cut migration.**

Concretely:
- Oneiric's `EventBridge` is the authoritative transport and envelope shape
- `mahavishnu/core/events/canonical.py` is the canonical envelope dataclass wrapper
- `mahavishnu/core/events/eventbridge_adapter.py` exposes `EventBridgePublisher.emit()` to legacy callers
- `mahavishnu/mahavishnu_publisher.py` is the Mahavishnu-side publisher entrypoint
- `mahavishnu/core/events/bodai_subscriber.py` provides `subscribe_to_bodai_events()` + `read_bodai_events_since()` (one-shot reader is the production consumer pattern)
- `mahavishnu/core/events/transport.py` + `envelope.py` provide Redis Streams transport via `oneiric.adapters.queue.redis_streams`
- The legacy systems (`mahavishnu/core/event_bus.py`, `task_notifications.py`, `mcp/protocols/message_bus.py`) **remain in place** because removing them is a separate, cross-component risk that should be staged not just de-coupled

## Rationale

The hard-cut migration was the correct **end state** but the wrong **migration shape**:

1. **End-state compat preserved** — downstream callers (workers, schedulers, alerting) still see the same `EventEnvelope` and `subscribe_to_bodai_events()` API
3. **Wrapper enables incremental rollout** — Akosha, crackerjack, and Session-Buddy can adopt the wrapper at their own pace without a coordinated cutover
4. **DLQ integration works** via `mahavishnu/core/events/bodai_subscriber.py` and `mahavishnu/core/dead_letter_queue.py`; exhausted handler retries land in the DLQ as the spec required
5. **WebSocket fan-out works** — `mahavishnu/websocket/integration.py` consumes the wrapper envelope directly; the spec's "WebSocketEventHandler" abstraction was implemented as direct integration instead of a separate `WebSocketEventHandler` class

## What did NOT ship (spec items deferred or reworked)

- **Hard-delete of legacy systems** — `event_bus.py` was deleted, but `task_notifications.py`, `mcp/protocols/message_bus.py`, and a few `AlertChannel` references remain
- **`WebSocketEventHandler` class** — replaced with direct integration in `mahavishnu/websocket/integration.py`; both approaches yield the same WebSocket fan-out behavior
- **`mahavishnu-activity-stream.py` deletion** — pending under `2026-07-11-phase-6-bodai-observability.md` Phase 6.4 (separate plan)
- **FailedTask.event_envelope field** — partially applied; some paths use envelope, others use legacy dict shapes (gap being closed incrementally)

## Migration Path Forward

The wrapper is a stable intermediate state. The eventual end state remains "legacy systems deleted, WebSocket consumes EventBridge directly via the `WebSocketEventHandler` interface." Future work to close the gap:

1. Phase 6.4: delete `mahavishnu-activity-stream.py` (tracked by `2026-07-11-phase-6-bodai-observability.md`)
2. Delete `mahavishnu/core/task_notifications.py` once the only caller (`tasks_handoff.py`) is migrated to use `publish_task_event_raw` exclusively
3. Migrate `mcp/protocols/message_bus.py` to wrap on `EventBridge.subscribe()` rather than the legacy in-process queue
4. Add a `WebSocketEventHandler` class to make the swap rule explicit per spec §"WebSocket handler integration"

## Provenance

- 2026-10-15 plan audit (8-batch parallel workflow) flagged the 2026-05-09 spec as `stale-draft`: frontmatter said `draft`, but the wrapper-layer reality was incompatible with the spec's "drop and replace" intent
- Auditor's recommendation: "delete the spec and replace with a short decision document `docs/decisions/unified-event-bus-wrapper.md` that records the wrapper-layer design as the actual outcome"
- This decision document records the actual architecture decision per the audit's recommendation

## Related

- [`docs/plans/2026-05-09-unified-event-bus-spec.md`](../plans/2026-05-09-unified-event-bus-spec.md) — original spec (now superseded; retained for historical reference)
- [`docs/plans/2026-07-11-phase-6-bodai-observability.md`](../plans/2026-07-11-phase-6-bodai-observability.md) — Phase 6.4 cleanup work still pending
- [`docs/specs/2026-09-27-shared-bodai-substrate-design.md`](../specs/2026-09-27-shared-bodai-substrate-design.md) — broader substrate context