# Session-Buddy Multi-Channel Tracking — Concrete Spec

**Status**: Draft v0.2
**Date**: 2026-04-07
**Based on**: nanobot v0.1.4.post6 (installed) + v0.1.5 (latest, not yet installed)

______________________________________________________________________

## 1. Context & Research Findings

### 1.1 Nanobot Architecture (verified via source + upstream)

| Feature | v0.1.4.post6 (ours) | v0.1.5 (latest) |
|---|---|---|
| `BaseChannel` + `_handle_message()` | ✅ | ✅ |
| `session_key` on `InboundMessage` | ✅ `channel:chat_id` | ✅ + thread overrides |
| `SessionManager` (JSONL per session) | ✅ | ✅ |
| Channel plugin system (`entry_points`) | ✅ `nanobot.channels` group | ✅ |
| `AgentHook` (per-iteration lifecycle) | ✅ Basic (6 methods) | ✅ + `CompositeHook`, `_LoopHookChain`, extra hooks |
| `ChannelsConfig` | ✅ `extra="allow"` | ✅ |
| `Dream` memory consolidation | ❌ | ✅ Two-stage background memory |
| History format | Markdown `HISTORY.md` | ✅ Migrated to `history.jsonl` |
| Agent SDK | ❌ | ✅ Programmatic agent interface |
| Sandbox (`bwrap`) | ❌ | ✅ |

**Key insight**: We're one version behind. v0.1.5's `CompositeHook` + extra hooks mechanism would let us inject session tracking as a lifecycle hook without any nanobot modifications. But even on v0.1.4.post6, the skill-based approach works.

### 1.2 Nanobot Plugin System

```python
# nanobot/channels/registry.py — present in both versions
def discover_plugins() -> dict[str, type[BaseChannel]]:
    """Discover external channel plugins registered via entry_points."""
    for ep in entry_points(group="nanobot.channels"):
        cls = ep.load()
        plugins[ep.name] = cls
```

This means we **cannot** fork nanobot. We can:

1. Write a **channel plugin** (separate pip package, registered via `entry_points`)
1. Use the **skill system** (SKILL.md — what we already do)
1. Wait for v0.1.5 and use **extra hooks** (inject `AgentHook` subclass)

### 1.3 Session-Buddy Current State

- `SessionStartEvent` / `SessionEndEvent` — terminal-focused (requires `pid`, `hostname`, `cwd`)
- `SessionTracker` — creates/updates session records
- Auth via JWT (`@require_auth()`)
- **Gap**: No concept of channel_type, thread_id, or idle-timeout sessions

______________________________________________________________________

## 2. Design Decision: Recommended Approach

### 2.1 Why NOT Option A (modify nanobot core)

- **No fork needed** — nanobot has `entry_points` plugin system
- Even without plugins, the skill system provides enough access
- v0.1.5 adds `CompositeHook` + extra hooks which is the ideal injection point

### 2.2 Recommended: Phase-Gated Hybrid (B + C)

```
Phase 1 (skill-based)  → Phase 2 (event bus)  → Phase 3 (nanobot plugin)
    ~2-3 days                  ~1 day                  ~2 days
```

**No nanobot fork required at any phase.**

______________________________________________________________________

## 3. Phase 1: Session-Buddy Channel Adapter + Skill Update

### 3.1 New MCP Tool: `track_channel_session`

Session-Buddy gets a new MCP tool alongside the existing `track_session_start` / `track_session_end`:

```python
class ChannelSessionEvent(BaseModel):
    """Channel-agnostic session event (v2.0)."""
    event_version: str = "2.0"
    event_id: str                          # UUID
    event_type: Literal[
        "channel_session_start",
        "channel_session_end",
        "channel_heartbeat",
    ]

    # Channel identity
    channel_type: str                      # "slack", "signal", "terminal", "discord"
    channel_id: str                        # chat_id / conversation_id
    sender_id: str                         # user identifier

    # Session scoping
    session_scope: str = "conversation"    # "conversation", "thread", "day"
    thread_id: str | None = None           # for thread-scoped sessions

    # Component
    component_name: str = "nanobot"

    # Timing
    timestamp: str                         # ISO 8601 UTC

    # Context (optional, channel-specific)
    workspace: str | None = None
    platform: str | None = None            # "slack-api", "signal-cli", "terminal"

    # Terminal-specific (only for terminal sessions)
    pid: int | None = None
    hostname: str | None = None
    environment: dict[str, str] | None = None

    # Message context
    message_preview: str | None = None     # first 200 chars of triggering message
    message_count: int = 1

    metadata: dict[str, Any] = {}
```

### 3.2 Session Boundary Strategy

| Channel | Session Start | Session End | Heartbeat | Idle Timeout |
|---|---|---|---|---|
| `terminal` | Process spawn | Process exit | N/A | N/A |
| `slack` DM | First msg after 30min idle | 30min idle | Every 10min | 30 min |
| `slack` thread | First msg in thread | 60min idle | Every 10min | 60 min |
| `slack` channel | Bot mention (first in 30min) | 30min idle | Every 10min | 30 min |
| `signal` | First msg after 30min idle | 30min idle | Every 10min | 30 min |

**Implementation**: Idle detection happens on the **nanobot side** (in the skill), not in Session-Buddy. The skill tracks last-activity timestamps and emits `channel_session_end` when the idle timeout is exceeded.

### 3.3 Updated Session-Buddy Skill

The existing `session-buddy/SKILL.md` gets enhanced:

```
On each message:
1. Check if there's an active session (stored in MEMORY.md)
2. If no active session → emit channel_session_start
3. If active session but different channel/scope → end old, start new
4. Send channel_heartbeat (best-effort, async)
5. Check idle timeout → if exceeded, emit channel_session_end

On "end session" / "goodbye":
1. Emit channel_session_end
2. Clear session state from MEMORY.md
```

**Channel detection**: The nanobot skill has access to `channel` and `chat_id` via the agent loop context. It can determine:

- `channel = "slack"` → we're in Slack
- `channel = "cli"` → we're in terminal
- `metadata.slack.thread_ts` → we're in a thread
- `metadata.slack.channel_type` → "im" (DM) vs "channel"

### 3.4 Backward Compatibility

- Existing `track_session_start` / `track_session_end` continue to work for admin shells
- `ChannelSessionEvent` is a **separate** event type (v2.0) — no migration needed
- Terminal sessions can optionally use the new tool (pid/hostname/env still supported)

### 3.5 Session-Buddy Storage

New fields on session records:

```sql
-- existing fields remain
-- new fields added (nullable for backward compat)
channel_type     TEXT,    -- "slack", "signal", "terminal"
channel_id       TEXT,    -- chat_id / conversation_id
sender_id        TEXT,    -- user identifier
session_scope    TEXT,    -- "conversation", "thread", "day"
thread_id        TEXT,    -- for thread-scoped sessions
message_count    INTEGER DEFAULT 1,
idle_timeout_s   INTEGER DEFAULT 1800,
```

______________________________________________________________________

## 4. Phase 2: Event Bus (Dhara-backed)

### 4.1 Approach

Session-Buddy publishes session events to Dhara's time-series storage:

```python
# After handling channel_session_start/end/heartbeat
await dhara.record_time_series(
    metric_type="session_buddy.channel_event",
    entity_id=session_id,
    record={
        "event_type": event.event_type,
        "channel_type": event.channel_type,
        "channel_id": event.channel_id,
        "sender_id": event.sender_id,
        "timestamp": event.timestamp,
    }
)
```

**Overhead**: Zero new infrastructure. Dhara already runs. Just a new metric_type.

### 4.2 Consumers

- **Akosha**: Subscribe to `session_buddy.channel_event` for analytics
- **Tempo/OTEL**: Future — correlate traces with session events
- **Grafana**: Dashboard queries against Dhara time-series

______________________________________________________________________

## 5. Phase 3: Nanobot Plugin (Optional)

### 5.1 After upgrading to v0.1.5

v0.1.5's `_LoopHookChain` + `CompositeHook` allows injecting custom hooks into the agent loop:

```python
# A future nanobot-channel-sessionbuddy plugin package
class SessionTrackingHook(AgentHook):
    """Automatically track sessions via Session-Buddy."""

    async def before_iteration(self, context: AgentHookContext) -> None:
        # Detect session boundary, emit event
        ...

    async def after_iteration(self, context: AgentHookContext) -> None:
        # Send heartbeat, update message count
        ...
```

This plugin would be registered via:

```toml
# pyproject.toml
[project.entry-points."nanobot.channels"]
session-buddy = "nanobot_channel_sessionbuddy:SessionBuddyChannel"
```

Or via extra hooks config (v0.1.5):

```yaml
# nanobot config (hypothetical, depends on v0.1.5 hook config)
hooks:
  - module: nanobot_channel_sessionbuddy
    class: SessionTrackingHook
```

**This is optional** — Phase 1's skill-based approach works without it. Phase 3 just makes it automatic.

______________________________________________________________________

## 6. What We DON'T Need

- ❌ Forking nanobot
- ❌ Modifying nanobot's agent loop
- ❌ New infrastructure (Redis, message queue)
- ❌ Changes to Session-Buddy's existing admin shell tracking
- ❌ Breaking changes to any existing APIs

## 7. Open Questions

1. **Signal integration**: Signal doesn't have a nanobot channel yet. When it does, this spec handles it naturally. Do we want to build the Signal channel adapter too, or wait?

1. **Cross-channel session linking**: Should a Slack thread and a terminal session on the same project be linked? The current design keeps them independent.

1. **Quality scoring for non-terminal sessions**: Current SB quality score is based on test coverage, commits, etc. What should Slack/Signal sessions be scored on? Message count? Resolution rate?

1. **v0.1.5 upgrade timing**: Should we upgrade nanobot to v0.1.5 before starting Phase 1? The `CompositeHook` feature would simplify Phase 3 but isn't needed for Phase 1.

## 8. Effort Estimates

| Phase | Scope | Effort | Dependencies |
|---|---|---|---|
| **Phase 1** | SB channel adapter + skill update | 2-3 days | None |
| **Phase 2** | Dhara event bus | 1 day | Phase 1 |
| **Phase 3** | Nanobot plugin | 2 days | v0.1.5 upgrade, Phase 1 |

**Total**: ~5-6 days for all phases.

## 9. Appendix: Channel Detection in Nanobot

The nanobot agent loop provides these signals to the skill:

```python
# InboundMessage fields available during session:
msg.channel        # "slack", "cli", "telegram", etc.
msg.chat_id        # "D0AR18B4WUU" (Slack DM), "C01234ABCD" (channel)
msg.sender_id      # "U01234ABCD"
msg.session_key    # "slack:D0AR18B4WUU" (DM) or "slack:C01234:1234567890.123456" (thread)
msg.metadata      # {"slack": {"thread_ts": "...", "channel_type": "im", "event": {...}}}
```

The skill can access these via the nanobot runtime context — no API changes needed.
