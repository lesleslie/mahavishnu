# WebSocket Consumer Guide

This guide documents the contract that subscribers of Mahavishnu's
WebSocket channels MUST honour. It applies to all channels: the
existing `workflow:`, `pool:`, `worker:`, and `goal-teams` channels
plus the new `settle:` and `run:` channels introduced in Phase 2
(`worker_run_with_settle` / `worker_settle` MCP tools).

The canonical idempotency / out-of-order / reconnect rules live in the
next section. Channels that do not follow these rules are out of
contract and may be retired without notice.

## Idempotency contract

**Every WebSocket event carries a deterministic `(channel, payload identifier)` tuple that the consumer MUST treat as idempotent.**

A consumer that processes the same tuple twice MUST NOT change its
post-state (i.e. two replays of the same event are observably
indistinguishable from a single delivery). This is required because:

1. **At-least-once delivery.** The WebSocket layer can re-deliver an
   event on transient network errors. Re-deliveries are indistinguishable
   from original deliveries.
1. **Out-of-order delivery.** Events can arrive in any order. In
   particular, a `phase=completed` event may arrive before a sibling
   `phase=started` event after a reconnect.
1. **Reconnect / catch-up via `since_offset`.** Reconnecting clients
   resume from a captured offset. The same event may be re-delivered
   during the catch-up window.

The payload identifier is the `run_ref` (for `settle:` and `run:`
channels) or the `workflow_id` / `pool_id` / `worker_id` for the
other channels. Subscribers MUST key their idempotency table by this
identifier plus the `phase` field.

### Settle channel payloads (Phase 2)

`settle:{run_ref}` and `run:{worker_id}` carry the same event payload:

```json
{
  "event": "settle.transition",
  "run_ref": "settle-abcd1234",
  "worker_id": "w-xyz",
  "from_state": "selected",
  "to_state": "applied",
  "phase": "applied",
  "action": "apply",
  "timestamp": "2026-08-29T20:30:00Z",
  "merge": {"merged": {"hello.txt": "hello world\n"}, "conflict_count": 0}
}
```

The `phase` field is set to `to_state` so the canonical
idempotency rule applies: `phase=applied` is terminal. A consumer
that sees `phase=applied` for a given `run_ref` MUST NOT act on
any subsequent transition for that `run_ref` (there are none —
terminal states are absorbing).

### Required consumer behaviour

| Scenario | Required behaviour |
|-----------------------------------------|-------------------------------------------------------------------------------|
| Same event delivered twice | Idempotency table keyed on `run_ref` (or equivalent) absorbs the duplicate. |
| `phase=applied` then `phase=proposed` later | Ignore the second event. `applied` is absorbing. |
| `phase=proposed` then `phase=applied` skipped | Treat the run as completed. The gap is a delivery loss, not a state change. |
| Event arrives before the consumer is connected | Catch up via `since_offset` on reconnect. The catch-up window replays events. |
| Connection drops mid-stream | Reconnect with the last captured `since_offset`. Replays are safe. |

## Reconnect / catch-up protocol

Every WebSocket event carries a monotonically increasing
`since_offset` field. Subscribers MUST persist the last-seen offset
for each channel they consume and re-supply it on reconnect via the
`since_offset` query parameter.

The server replays all events with `since_offset > captured_offset`
in order. Replay is bounded by a configurable retention window
(default: 24 hours). Beyond the retention window, subscribers MUST
treat the run as orphaned and consult the durable Dhara record
(via the `get_settle_record(run_ref)` MCP helper) to recover the
canonical state.

## Out-of-order delivery

Subscribers MUST NOT assume that `phase=started` arrives before
`phase=completed`. The WebSocket layer does not guarantee global
ordering across reconnect windows. The state machine in
`mahavishnu.settle.state_machine` enforces ordering at the
producer side; consumers see whatever order the transport hands
them.

A safe consumer pattern is:

1. Maintain a per-`run_ref` state machine mirror locally.
1. On each event, advance the mirror via the same transition rules.
1. If a transition is illegal locally (e.g. `applied` after
   `proposed`), log and skip — the event is stale or out-of-order
   and must NOT be re-applied.

## When to consult Dhara

WebSocket events are best-effort. Subscribers that need durable state
should consult the Dhara-backed settle record directly:

```
mcp__mahavishnu__get_settle_record(run_ref="settle-abcd1234")
```

This bypasses WebSocket delivery entirely and returns the canonical
record (state + transition log). Use this whenever:

- The retention window has expired and the consumer is reconnecting.
- The consumer suspects it has missed events (e.g. gap in offsets).
- The consumer is starting fresh and needs to backfill state for
  existing runs.

## Channel-specific notes

### `settle:{run_ref}`

Per-run channel. Carries one `settle.transition` event per state
change for that run. Subscribers on `settle:settle-abcd1234` see
exactly the events for `run_ref=settle-abcd1234`. Channel may go
silent after `phase=applied` — that is the terminal signal.

### `run:{worker_id}`

Per-worker alias for the same events. Use this channel when your
consumer is keyed on the underlying worker rather than the settle
handle. Same payload, same idempotency rules.

### `workflow:{workflow_id}`, `pool:{pool_id}`, `worker:{worker_id}`

Unchanged from pre-Phase 2 behaviour. The same idempotency contract
applies — key by `workflow_id` / `pool_id` / `worker_id` plus
the event `phase`.

## Phase 2 migrations

| Channel | Phase 2 change |
|---------|-------------------------------------------------------------------------------|
| `settle:` | New. Carries settle-run transitions. Idempotency table keyed on `run_ref`. |
| `run:` | New. Per-worker alias for the same payloads. |
| `workflow:` | No change. |
| `pool:` | No change. |
| `worker:` | No change. |
| `goal-teams` | No change. |

The new channels are gated on `worker:read` permission in
`MahavishnuWebSocketServer._can_subscribe_to_channel` (line 451
of `mahavishnu/websocket/server.py`). No new permission tier is
introduced — callers with worker visibility automatically get
settle visibility.
