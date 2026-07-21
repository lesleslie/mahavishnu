---
status: active
role: canonical
date: 2026-07-16
last_reviewed: 2026-07-16
topic: bodai-observability
---

# Bodai Observability Pattern — One Subscriber, One Bus

One-line summary: Claude Code's "observe Bodai" path reads from
Oneiric EventBridge (the unified event spine from Convergence Plan
C1b), not from raw component WebSockets. Phase 6 of the
ultracode integration wiring plan lands this pattern.

## Context

The Bodai ecosystem has five components with activity surfaces:

| Component | Raw stream | What it publishes |
|---|---|---|
| Mahavishnu | `ws://localhost:8690` (workflow/pool/worker/global channels) | workflow + pool lifecycle |
| Akosha | `akosha/websocket/server.py:431` (metrics channel) | aggregation events |
| Dhara | REST/pull-only | state, on demand |
| Session-Buddy | Slack/Signal/terminal event_models | channel sessions |
| Crackerjack | `crackerjack/websocket/server.py:266-281` | test lifecycle |

A Claude Code session wanting to "see what's happening across
Bodai" could naively subscribe to all five raw streams. The
architecture-council review of the integration plan flagged that
approach: it would create a second control plane duplicating the
Oneiric EventBridge that Convergence Plan C1b already shipped.

The Convergence Plan's Non-Goal #1 explicitly forbids adding a second
event bus. The follow-up Phase 6 must consume EventBridge handlers,
not raw WebSockets.

## Decision rule

The Claude Code observability surface for Bodai reads from
**Oneiric EventBridge** exclusively. Specifically:

1. Components publish activity events to EventBridge using the
   canonical envelope from Oneiric `EventEnvelope`
   (`oneiric.runtime.events.EventEnvelope`):
   - `topic: str` — event type (e.g., `workflow.completed`,
     `aggregation.completed`, `test_run.completed`)
   - `payload: dict[str, Any]` — domain-specific event body
   - `headers: dict[str, Any]` — carries `source` (component name),
     `event_id` (ULID), `version` (semver), `timestamp` (ISO-8601),
     and optional `correlation_id` / `causation_id` for causal tracing
1. A single subscriber — the Bodai activity subscriber — reads from
   EventBridge and surfaces events to Claude Code via the
   `.claude/hooks/` PostToolUse pattern.
1. No component-level WebSocket subscriber exists in `.claude/hooks/`
   for the purpose of Bodai-wide observation. Phase 5's
   Mahavishnu-only hook is the *transition state*, not the pattern
   to copy.

## What this means concretely

- **Today (post-Phase 5)**: `.claude/hooks/mahavishnu-activity-stream.py`
  subscribes to Mahavishnu's WebSocket directly. This is acceptable
  for Mahavishnu because (a) Mahavishnu already runs its own broadcast
  loop, and (b) EventBridge does not yet publish an "activity" event
  category.
- **Phase 6 (when EventBridge adds activity events)**: The
  Mahavishnu-only hook is replaced by a Bodai activity hook that
  subscribes to EventBridge. The Mahavishnu WebSocket subscriber is
  removed.
- **Component-specific WebSocket subscribers are forbidden** for the
  Claude Code observability use case. If you need Akosha's metrics
  channel for a non-Claude-Code consumer (e.g., a Grafana dashboard),
  use Akosha's existing client API — don't add a new
  `.claude/hooks/` subscriber.

## Why not multi-WebSocket?

The five raw streams have:

- **Different envelope schemas.** Mahavishnu broadcasts
  `{"event_type": "workflow_started", "workflow_id": "wid_abc", ...}`;
  Akosha broadcasts `{"kind": "aggregation", "metrics": {...}}`;
  Crackerjack broadcasts `{"test_run_started", "passed": N, "failed": M}`.
  A multi-WebSocket subscriber must normalize on the consumer side.

- **Different reliability characteristics.** Mahavishnu's WebSocket
  has reconnect logic; Crackerjack's has none; Dhara has no
  WebSocket at all (REST-only). A multi-WebSocket subscriber must
  handle each stream's quirks separately.

- **No ordering guarantees across streams.** A workflow_started
  event on Mahavishnu might arrive after a workflow_completed event
  on Akosha if Akosha's aggregation runs first. Multi-stream
  correlation requires a global sequence number that none of the
  raw streams provide.

EventBridge solves all three: canonical envelope, single reliability
contract, global sequence numbers. It is the right layer for
Claude Code to consume.

## How to add a new component's activity events

When Akosha, Crackerjack, Dhara, or Session-Buddy need to surface
activity to Claude Code:

1. **Publish to EventBridge, not to a new WebSocket.** If the
   component already has a WebSocket for non-Claude consumers, leave
   it. The EventBridge publisher is an additional adapter, not a
   replacement.

1. **Use the canonical envelope from Convergence Plan C2.** The
   Phase 6 subscriber assumes the envelope shape agreed there. If
   C2 lands a different shape, the Phase 6 subscriber must be
   updated to match (single source of truth: EventBridge).

1. **Do not add a per-component subscriber in `.claude/hooks/`.**
   The single Bodai activity subscriber is the consumer.

### Concrete envelope examples (from `format_bodai_summary`)

The Mahavishnu-side subscriber (`mahavishnu.core.events.bodai_subscriber`)
produces one-line summaries of the canonical envelope. Operators see
these inline after a tool invocation; the same format is what
`mahavishnu metrics bodai` aggregates.

```
[mahavishnu] workflow.completed workflow_id=wid_abc
[akosha] aggregation.completed suite=quality
[crackerjack] test_run.completed passed=42 failed=0
```

Each line is built from `headers["source"]` (the component prefix),
`envelope.topic` (the event type), and `key=value` pairs sorted out
of `envelope.payload`. Missing fields fall back to `[unknown] unknown` so a malformed envelope never aborts the consumer loop.

## Status <!-- legacy status: In progress — see YAML frontmatter -->

In progress (Mahavishnu side complete). Phase 6A landed the
Mahavishnu-side subscriber at `mahavishnu/core/events/bodai_subscriber.py`
and Phase 6 close shipped the `mahavishnu metrics bodai` CLI. Akosha
and Crackerjack publisher work (Phase 6.2a / 6.2b) is cross-repo and
not started. Phase 5's Mahavishnu-only hook remains as the
operational fallback until all three publishers land.

## References

- `docs/plans/2026-07-11-ultracode-integration-wiring.md` §5 Phase 6
  (deferred; this file is its operational extension)
- `docs/plans/2026-05-10-bodai-control-plane-convergence-plan.md`
  Non-Goal #1 (no second control plane)
- `.claude/hooks/mahavishnu-activity-stream.py` (Phase 5 transition
  state — to be replaced by Phase 6)
- `docs/ROUTING_GUIDE.md` §Bodai observability survey table (gap
  classification for each component)
