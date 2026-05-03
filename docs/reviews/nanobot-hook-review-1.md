# Nanobot v0.1.5 Hook Architecture Review

**Date:** 2026-04-07
**Version:** nanobot-ai 0.1.5
**Goal:** Evaluate hook injection points for Session-Buddy integration
**Reviewer:** Subagent (automated code review)

______________________________________________________________________

## Executive Summary

**Verdict: There is NO mechanism in v0.1.5 to inject hooks without modifying nanobot source code.** The `AgentHook` ABC and `AgentLoop.__init__(hooks=...)` parameter exist, but no entry point discovery, config field, or env var wires external hooks into the loop. The gateway/agent/serve commands never pass `hooks=` when constructing `AgentLoop`.

This review covers six questions in detail, identifies gotchas, and proposes a minimal PR path.

______________________________________________________________________

## 1. Hook Injection Mechanisms — Is There Any Way In?

### Current entry_points

```
# nanobot_ai-0.1.5.dist-info/entry_points.txt
[console_scripts]
nanobot = nanobot.cli.commands:app
```

Only one entry point group exists: `console_scripts`. There is **no** `nanobot.hooks` entry point group, no `nanobot.plugins`, no hook auto-discovery of any kind.

### Config schema

`Config` in `schema.py` has no `hooks` field. The top-level fields are:

```python
agents, channels, providers, api, gateway, tools
```

No `hooks`, `plugins`, or `extensions` section exists.

### Environment variables

The config uses `env_prefix="NANOBOT_"` with `env_nested_delimiter="__"`, but there is no hook-related config field for env vars to map to.

### Constructor parameter exists but is unused

```python
# loop.py:164-184
class AgentLoop:
    def __init__(self, ..., hooks: list[AgentHook] | None = None):
        ...
        self._extra_hooks: list[AgentHook] = hooks or []
```

The parameter exists. But all three call sites (`gateway()`, `agent()`, `serve()` in `commands.py`) construct `AgentLoop` **without** `hooks=`:

```python
# commands.py:653-671 (gateway), 563-580 (serve), 885-902 (agent)
agent = AgentLoop(
    bus=bus,
    provider=provider,
    ...
    # NO hooks= parameter
)
```

### Channel plugin entry_points — only for channels

```python
# channels/registry.py:40-51
def discover_plugins() -> dict[str, type[BaseChannel]]:
    for ep in entry_points(group="nanobot.channels"):
        ...
```

Entry point discovery exists but is **exclusively** for `BaseChannel` subclasses in the `nanobot.channels` group. There is no analogous `nanobot.hooks` group.

### Answer: **No external hook injection is possible in v0.1.5.**

Workarounds require either:

- A monkey-patch (fragile, breaks on updates)
- Source modification (lose `uv` managed install)
- A PR to add hook discovery

______________________________________________________________________

## 2. AgentHookContext — What Data Is Available?

### Dataclass fields

```python
# hook.py:14-26
@dataclass(slots=True)
class AgentHookContext:
    iteration: int                          # Current loop iteration (0-indexed)
    messages: list[dict[str, Any]]          # Full message history for this run
    response: LLMResponse | None = None     # Latest LLM response (set after _request_model)
    usage: dict[str, int] = ...             # Token usage from latest response
    tool_calls: list[ToolCallRequest] = ... # Tool calls from latest response
    tool_results: list[Any] = ...           # Results from executed tools
    tool_events: list[dict[str, str]] = ... # Tool event summaries
    final_content: str | None = None        # Final response text
    stop_reason: str | None = None          # "completed", "max_iterations", "error", "tool_error"
    error: str | None = None                # Error message if any
```

### What's MISSING for Session-Buddy

| Need | Available? | Notes |
|------|-----------|-------|
| Channel name | ❌ | Not in `AgentHookContext` |
| Chat ID | ❌ | Not in `AgentHookContext` |
| Session key | ❌ | Not in `AgentHookContext` |
| Message content | ⚠️ Partial | `messages` list has full history but no convenient "current message" field |
| Sender ID | ❌ | Not in `AgentHookContext` |
| Timestamps | ❌ | Not in `AgentHookContext` |
| Tool names/results | ✅ | `tool_calls`, `tool_results`, `tool_events` |
| Token usage | ✅ | `usage` dict |
| Iteration count | ✅ | `iteration` int |
| Final response | ✅ | `final_content`, `stop_reason` |

### Where the routing data lives

The `_LoopHook` (internal, per-run) has the data we need:

```python
# loop.py:47-64
class _LoopHook(AgentHook):
    def __init__(self, ..., channel="cli", chat_id="direct", message_id=None):
        self._channel = channel
        self._chat_id = chat_id
        self._message_id = message_id
```

But this is constructed inside `_run_agent_loop()` and not exposed to extra hooks. The `_LoopHookChain` runs `_primary` (which has the data) then `_extras` (which don't), but the extra hooks receive the same `AgentHookContext` which lacks channel/chat routing.

### Answer: **AgentHookContext is LLM-loop-scoped, not message-scoped.** It has no channel, chat_id, session_key, or sender_id. For Session-Buddy tracking, we need either:

1. Extend `AgentHookContext` with routing fields, or
1. Pass routing data through a separate mechanism (e.g., contextvars)

______________________________________________________________________

## 3. Lifecycle — When Do Hooks Fire?

### The full iteration cycle in `AgentRunner.run()` (runner.py:79-269):

```
for iteration in range(max_iterations):
    1. context = AgentHookContext(iteration, messages)
    2. await hook.before_iteration(context)          ← BEFORE LLM call
    3. response = await _request_model(...)          ← LLM call
    4. context.response = response

    if response.has_tool_calls:
        5. await hook.on_stream_end(context, resuming=True)  ← if streaming
        6. await hook.before_execute_tools(context)          ← BEFORE tool execution
        7. results = await _execute_tools(...)
        8. await hook.after_iteration(context)               ← AFTER tool execution
        continue  ← loop back to step 1

    # No tool calls — final response
    9. await hook.on_stream_end(context, resuming=False)
    10. await hook.after_iteration(context)                  ← AFTER final response
    break
```

### Hook method call order per message:

| Method | When | Notes |
|--------|------|-------|
| `before_iteration` | Start of every iteration | Fires even on tool-call loops |
| `on_stream` | Each streaming delta | Only if `wants_streaming() == True` |
| `on_stream_end` | End of streaming segment | `resuming=True` if tools follow |
| `before_execute_tools` | Before tool execution | After LLM returns tool_calls |
| `after_iteration` | End of every iteration | Fires on both tool and final iterations |
| `finalize_content` | Synchronous, during finalization | Pipeline — no error isolation |

### Does it fire on EVERY message including cron/heartbeat?

**Yes, but with caveats:**

- **Cron jobs**: Route through `agent.process_direct()` → `_process_message()` → `_run_agent_loop()`. Hook fires.
- **Heartbeat**: Routes through `agent.process_direct()` with `session_key="heartbeat"`. Hook fires.
- **Dream jobs**: These run directly via `agent.dream.run()` — they use the `Dream` class, NOT `AgentRunner`. **Hooks do NOT fire on dream consolidation.**
- **System messages** (subagents, etc.): Route through `_process_message()` with `channel="system"`. Hook fires.

### Answer: **Hooks fire on every agent loop execution** (user messages, cron, heartbeat, system/subagent). They do NOT fire on Dream consolidation. A single message may trigger multiple iterations (tool call loops), so `before_iteration`/`after_iteration` fire multiple times per message.

______________________________________________________________________

## 4. Is a Channel Plugin (BaseChannel) a Viable Alternative?

### How channel plugins work

```python
# registry.py:40-51
entry_points(group="nanobot.channels")  # discovers external channels
```

Channel plugins register via `nanobot.channels` entry point group and implement:

```python
class BaseChannel(ABC):
    async def start(self) -> None        # Long-running listener
    async def stop(self) -> None
    async def send(self, msg: OutboundMessage) -> None
    async def send_delta(self, chat_id, delta, metadata) -> None
```

### Can a channel plugin observe all messages?

**No, not passively.** Channel plugins are **inbound producers and outbound consumers**. They:

1. Receive messages from external platforms (Telegram, etc.)
1. Publish `InboundMessage` to the bus
1. Receive `OutboundMessage` from the bus

A channel plugin can observe **outbound** messages via `_dispatch_outbound()` in `ChannelManager`, but:

- It only sees outbound for its own channel name
- It doesn't see messages routed to other channels
- It doesn't see the agent's internal iterations, tool calls, or timing
- It can't intercept inbound messages from other channels

### Could we abuse the channel system?

Theoretically, a "spy channel" could:

- Subscribe to outbound messages by being in the dispatch loop
- But it would need to be enabled in config, and `_dispatch_outbound()` only delivers to the matching `msg.channel`

**Not viable for cross-channel passive observation.**

### Answer: **Channel plugins are not a viable alternative.** They're I/O adapters, not middleware. They can't observe the agent loop internals or cross-channel traffic.

______________________________________________________________________

## 5. Minimal PR to Add Hook Discovery via entry_points

### Design

Follow the existing pattern from `channels/registry.py`:

```python
# New file: nanobot/agent/hooks_registry.py

from __future__ import annotations
from importlib.metadata import entry_points
from loguru import logger
from nanobot.agent.hook import AgentHook

def discover_hooks() -> list[AgentHook]:
    """Discover AgentHook plugins registered via entry_points."""
    hooks: list[AgentHook] = []
    for ep in entry_points(group="nanobot.hooks"):
        try:
            cls = ep.load()
            if isinstance(cls, type) and issubclass(cls, AgentHook):
                hooks.append(cls())
                logger.info("Loaded hook plugin: {}", ep.name)
            elif callable(cls):
                instance = cls()
                if isinstance(instance, AgentHook):
                    hooks.append(instance)
            else:
                logger.warning("Hook entry point '{}' is not an AgentHook subclass", ep.name)
        except Exception:
            logger.exception("Failed to load hook plugin '{}'", ep.name)
    return hooks
```

### Changes to AgentLoop

```python
# loop.py — add to __init__
from nanobot.agent.hooks_registry import discover_hooks

class AgentLoop:
    def __init__(self, ..., hooks: list[AgentHook] | None = None):
        discovered = discover_hooks()
        self._extra_hooks: list[AgentHook] = (hooks or []) + discovered
```

### Changes to AgentHookContext (add routing data)

```python
# hook.py — extend AgentHookContext
@dataclass(slots=True)
class AgentHookContext:
    iteration: int
    messages: list[dict[str, Any]]
    # NEW routing fields
    channel: str = "cli"
    chat_id: str = "direct"
    session_key: str | None = None
    message_id: str | None = None
    # existing fields...
    response: LLMResponse | None = None
    ...
```

### Changes to \_run_agent_loop (pass routing to context)

```python
# loop.py — in _run_agent_loop, before runner.run()
# The runner needs to set routing on the context it creates
# Option A: pass routing through AgentRunSpec
# Option B: use contextvars (cleaner, no runner changes)
```

**Recommended: contextvars approach** — avoids changing `AgentRunSpec`:

```python
# loop.py
import contextvars

_current_channel: contextvars.ContextVar[str] = contextvars.ContextVar("channel", default="cli")
_current_chat_id: contextvars.ContextVar[str] = contextvars.ContextVar("chat_id", default="direct")
_current_session_key: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_key", default=None)

# In _run_agent_loop, before runner.run():
_current_channel.set(channel)
_current_chat_id.set(chat_id)
_current_session_key.set(session.key if session else None)
```

### Changes to commands.py (pass hooks from config)

```python
# commands.py — in gateway(), agent(), serve()
from nanobot.agent.hooks_registry import discover_hooks

hooks = discover_hooks()  # auto-discovered
# Optional: also load from config if we add a hooks section
agent = AgentLoop(..., hooks=hooks)
```

### Plugin package setup

```toml
# pyproject.toml for session-buddy-hook package
[project.entry-points."nanobot.hooks"]
session-buddy = "session_buddy_hook:SessionBuddyHook"
```

### Estimated PR size

| File | Change |
|------|--------|
| `nanobot/agent/hooks_registry.py` | +25 lines (new file) |
| `nanobot/agent/hook.py` | +4 lines (add routing fields to context) |
| `nanobot/agent/loop.py` | +8 lines (import + wire discovery) |
| `nanobot/cli/commands.py` | +3 lines (pass hooks in 3 call sites) |
| `nanobot_ai-0.1.5.dist-info/entry_points.txt` | No change needed |

**Total: ~40 lines of core changes.**

______________________________________________________________________

## 6. Gotchas

### Thread Safety

**Good news:** nanobot is fully async (single-threaded event loop). No thread safety concerns for hook execution. However:

- **Per-session locks** (`_session_locks`) serialize messages within a session but allow concurrent cross-session processing.
- **Concurrency gate** (`_concurrency_gate`, default `Semaphore(3)`) limits concurrent agent runs.
- **`CompositeHook._for_each_hook_safe()`** catches and logs exceptions per hook — a faulty hook **cannot crash the loop**. This is excellent for plugin reliability.

### Error Isolation

```python
# hook.py:70-75
async def _for_each_hook_safe(self, method_name, *args, **kwargs):
    for h in self._hooks:
        try:
            await getattr(h, method_name)(*args, **kwargs)
        except Exception:
            logger.exception("AgentHook.{} error in {}", method_name, type(h).__name__)
```

**BUT** `finalize_content` is a pipeline with NO isolation:

```python
# hook.py:92-94
def finalize_content(self, context, content):
    for h in self._hooks:
        content = h.finalize_content(context, content)
    return content
```

A buggy `finalize_content` **will** propagate. Session-Buddy hook should NOT override `finalize_content` unless it's purely additive.

### Heartbeat / Dream Jobs

- **Heartbeat**: Runs through `process_direct()` with `session_key="heartbeat"`, `channel=<picked from enabled channels>`. Hook fires. **Caveat:** Heartbeat runs every 30 minutes (default) and creates a persistent session that grows. Our hook must distinguish heartbeat from real user sessions.
- **Dream**: Runs through `Dream.run()`, which uses `AgentRunner` directly with a fresh `AgentRunSpec(hook=AgentHook())` — **no extra hooks fire**. This is actually correct behavior (Dream is internal consolidation), but worth noting.
- **Cron**: Routes through `process_direct()` with `session_key=f"cron:{job.id}"`. Hook fires. **Caveat:** Multiple cron jobs could fire concurrently.

### Context Compaction

The `Consolidator` runs `maybe_consolidate_by_tokens()` before each message. This is a **pre-processing step** that modifies session history but does NOT trigger hooks. Our hook won't see compaction events unless we add a separate hook point or listen to session save events.

### Session Checkpoint/Restore

The agent persists in-flight state via `_set_runtime_checkpoint()` / `_restore_runtime_checkpoint()`. On restart, partial turns are restored. Our hook would see the restored turn as a continuation, not a new session. We need to handle this gracefully.

### Multiple Iterations Per Message

A single user message can trigger many iterations (tool call loops). `before_iteration`/`after_iteration` fire on EACH iteration, not just once per message. For Session-Buddy:

- `before_iteration` on iteration 0 = message start
- `after_iteration` with `stop_reason="completed"` = message end
- Intermediate iterations = tool processing

### Streaming Interactions

If `wants_streaming()` returns `True`, the hook receives `on_stream` (delta) and `on_stream_end` (segment boundary). Session-Buddy probably doesn't need streaming, but must NOT return `True` from `wants_streaming()` unless it actually processes deltas — otherwise `_LoopHookChain.wants_streaming()` returns `True` and streaming infrastructure activates unnecessarily.

### The `_LoopHookChain` Ordering

```python
# Primary (internal) runs FIRST, then extras (plugins)
async def before_iteration(self, context):
    await self._primary.before_iteration(context)   # Internal setup
    await self._extras.before_iteration(context)     # Plugin hooks
```

This is correct — internal bookkeeping happens before plugin hooks see the context.

______________________________________________________________________

## Recommendations for Session-Buddy Integration

### Option A: Minimal PR (Recommended)

1. Add `nanobot/agent/hooks_registry.py` with `discover_hooks()` using `entry_points(group="nanobot.hooks")`
1. Extend `AgentHookContext` with `channel`, `chat_id`, `session_key` fields
1. Wire `discover_hooks()` into `AgentLoop.__init__()` and the three `commands.py` call sites
1. Build `session-buddy-hook` as a separate package with `nanobot.hooks` entry point
1. The hook calls Session-Buddy's HTTP API at `localhost:8678` in `before_iteration` (iteration 0) and `after_iteration` (final)

### Option B: Bus Interceptor (No PR needed, more hacky)

Subscribe to the `MessageBus` inbound/outbound queues as a side effect. This gives message-level visibility but no iteration/tool/usage data. Not sufficient for the stated requirements.

### Option C: Config-based Hook Loading (Slightly larger PR)

Add a `hooks` section to `Config` schema that references hook classes by dotted path, then instantiate them. More explicit than entry_points but requires config changes per installation.

______________________________________________________________________

## Files Reviewed

| File | Lines | Key Findings |
|------|-------|-------------|
| `agent/hook.py` | 95 | `AgentHook` ABC (6 methods), `AgentHookContext` (12 fields), `CompositeHook` (error-isolated fan-out) |
| `agent/loop.py` | 783 | `AgentLoop.__init__(hooks=)`, `_LoopHookChain`, `_run_agent_loop` — full lifecycle |
| `agent/runner.py` | 605 | `AgentRunner.run()` — iteration loop, hook call sites |
| `cli/commands.py` | 1389 | `gateway()`, `agent()`, `serve()` — no `hooks=` passed |
| `config/schema.py` | 312 | No `hooks` field in `Config` |
| `channels/manager.py` | 295 | Channel dispatch, outbound routing — not useful for hooks |
| `channels/registry.py` | 71 | `entry_points(group="nanobot.channels")` — template for hook discovery |
| `channels/base.py` | 181 | `BaseChannel` ABC — not a viable hook alternative |
| `bus/events.py` | 38 | `InboundMessage` (channel, sender_id, chat_id, session_key) |
| `entry_points.txt` | 2 | Only `nanobot = nanobot.cli.commands:app` |
