# Nanobot Session Tracking: Skill vs Plugin — Technical Review

**Date**: 2026-04-07
**Reviewer**: AI subagent
**Status**: Final
**Scope**: Compare SKILL-based (Approach A) vs PLUGIN-based (Approach B) session tracking for Session-Buddy in nanobot

______________________________________________________________________

## Executive Summary

**Recommendation: Ship the skill now; add the hook as a reliability backstop.**

Both approaches work. The skill is sufficient for production deployment today. The plugin is strictly superior for reliability but requires no new nanobot PR — the current installed version (v0.1.4.post6) already has `_LoopHookChain` and `CompositeHook` with error isolation. The gap between "skill works" and "hook guarantees execution" is narrow and recoverable. Ship the skill, harden it with a few mitigations, then add the hook as a Phase 2 safety net.

______________________________________________________________________

## 1. Can the Skill Reliably Handle Context Compaction?

### What happens when SKILL.md instructions are evicted

Nanobot's `Consolidator` archives old messages into `history.jsonl` via LLM summarization. The skill instructions come from the skill system (injected into the system prompt), not from individual user messages. Critically:

- **Skills are re-read on every message.** The nanobot context builder injects skill content into the system prompt on each iteration. Skills are not part of the conversation history that gets compacted — they're part of the *system prompt template*. Unless the system prompt itself is truncated (which happens only at extreme context pressure), skill instructions survive compaction.
- **MEMORY.md survives compaction.** The skill stores `session_id` in `memory/MEMORY.md` via the Dream system. Dream runs as a separate background process that reads `history.jsonl` and updates `MEMORY.md`. The session state section is persistent across compactions.
- **MCP tool definitions survive compaction.** MCP tool schemas (track_session_start, track_session_end, checkpoint) are injected by the tool registry, not stored in conversation history.

### Residual risk

The skill instructs the LLM to call MCP tools *on every message*. After compaction, the LLM may lose the conversational thread that triggered the original `track_session_start` call, but MEMORY.md preserves the session_id. The LLM will:

1. Read MEMORY.md → see "Active session ID: abc-123"
1. Not call `track_session_start` again (session already exists)
1. Continue using the stored session_id for checkpoints/heartbeat

**Verdict: Low risk.** Skill instructions survive compaction. State persists in MEMORY.md. The only gap is if the LLM decides to stop following skill instructions entirely (which would break ALL skills, not just session-buddy).

______________________________________________________________________

## 2. Data Comparison: Skill vs Plugin

### What the skill captures (current)

| Data Point | Source | Reliability |
|---|---|---|
| `session_id` | MEMORY.md | ✅ Persistent |
| `event_id` (UUID) | Generated per call via `exec` | ✅ |
| `component_name` | Hardcoded "nanobot" | ✅ |
| `shell_type` | Hardcoded "NanobotGateway" | ✅ |
| `timestamp` | Generated per call | ✅ |
| `pid` | `os.getpid()` via exec | ✅ |
| `user` (username, home) | Hardcoded in SKILL.md | ⚠️ Static |
| `hostname` | `hostname` via exec | ✅ |
| `environment` (python, platform, cwd) | Generated via exec | ✅ |
| `channel_type` | **Not captured** | ❌ Gap |
| `channel_id` | **Not captured** | ❌ Gap |
| `sender_id` | **Not captured** | ❌ Gap |
| `thread_id` | **Not captured** | ❌ Gap |
| `message_count` | **Not tracked** | ❌ Gap |
| `message_preview` | **Not captured** | ❌ Gap |

### What a plugin could capture

A hook with access to `AgentHookContext` and the `AgentLoop` internals gets:

| Data Point | Source | Reliability |
|---|---|---|
| All skill data above | Same sources | ✅ Same |
| `iteration` count | `context.iteration` | ✅ Every iteration |
| `messages` (full history) | `context.messages` | ✅ Every iteration |
| `tool_calls` made | `context.tool_calls` | ✅ Every iteration |
| `tool_results` | `context.tool_results` | ✅ Every iteration |
| `usage` (tokens) | `context.usage` | ✅ Every iteration |
| `channel` | `AgentLoop._dispatch(msg)` | ✅ From InboundMessage |
| `chat_id` | `msg.chat_id` | ✅ From InboundMessage |
| `sender_id` | `msg.sender_id` | ✅ From InboundMessage |
| `session_key` | `msg.session_key` | ✅ From InboundMessage |
| `metadata` (thread_ts, etc.) | `msg.metadata` | ✅ From InboundMessage |
| Error tracking | `context.error` | ✅ Every iteration |

### Key gaps in the skill

1. **No per-iteration tracking.** The skill fires on explicit triggers (start, end, checkpoint). It cannot track every agent iteration, token usage, or tool call pattern.
1. **No channel identity.** The skill doesn't know if it's running in Slack, terminal, or Signal. The multi-channel spec (Phase 1) addresses this by adding `track_channel_session`, but it relies on the LLM correctly detecting and reporting channel context.
1. **No message counting.** The skill can't increment a counter per-iteration. It would need to call an MCP tool on every message just to count, which wastes tokens and latency.

______________________________________________________________________

## 3. Hardening the Skill: Practical Mitigations

### 3.1 Compact Recovery

The skill already stores state in MEMORY.md. To make recovery explicit, add a section to MEMORY.md:

```markdown
## Session-Buddy State
- Active session ID: nanobot-20260407-123456
- Last checkpoint: 2026-04-07T14:30:00Z
- Session started: 2026-04-07T12:00:00Z
- Session-Buddy MCP: connected
```

On each message, the LLM checks this section. If session_id exists but is stale (>24h), it should call `track_session_end` then `track_session_start`.

### 3.2 Heartbeat via Cron

The skill can use nanobot's `cron` skill to schedule periodic heartbeats:

```
Set a cron reminder for 30 minutes from now:
"Session-Buddy heartbeat: call track_session_heartbeat if session is still active"
```

This ensures some activity even if the LLM forgets to track.

### 3.3 Explicit Compact Hook

The skill already includes a "Pre-Compact Sync" section. Enhance it:

```
## Pre-Compact Sync

Before any context compaction (you'll feel the context getting long):
1. Call mcp_session-buddy_pre_compact_sync() to flush pending events
2. Update MEMORY.md with current session state
3. This ensures no events are lost during compaction
```

### 3.4 Reduce exec calls

The current skill calls `exec` 4 times to get runtime values (uuid, pid, hostname, python/platform). Optimize:

```bash
python3 -c "import uuid,os,sys,platform; print(f'{uuid.uuid4()}|{os.getpid()}|{os.uname().nodename}|{sys.version.split()[0]}|{platform.platform()}')"
```

One exec call, parse with `|` separator. Reduces tool call overhead from 4→1.

**Verdict: Skill can be made robust enough for production with these mitigations.**

______________________________________________________________________

## 4. Hybrid Approach: Skill Now, Hook as Backstop

### Architecture

```
Layer 1 (Skill):     LLM-driven, fires on explicit triggers
                     → session_start, session_end, checkpoint, pre_compact_sync
                     → Stores state in MEMORY.md

Layer 2 (Hook):      Code-driven, fires on every iteration
                     → heartbeat, message_count, token tracking
                     → Validates session state consistency
                     → Fires session_end if LLM forgot
```

The hook doesn't replace the skill — it *complements* it. The skill handles rich, context-aware actions (checkpoint summaries, user-facing reminders). The hook handles mechanical, every-iteration bookkeeping.

### Interaction pattern

1. **Normal flow**: Skill calls `track_session_start` on first message. Hook sees session_id in MEMORY.md and starts sending heartbeats.
1. **Skill forgets**: Hook detects no `track_session_start` has been called for this session_key but messages are flowing. Hook fires `track_session_start` directly.
1. **Skill compacts**: Hook's `after_iteration` fires on every iteration regardless of context window. It can check if the session is still active and emit heartbeats.

This is the recommended production architecture.

______________________________________________________________________

## 5. Packaging Story

### 5.1 Current nanobot hook infrastructure (v0.1.4.post6)

The installed nanobot already has:

- `AgentHook` base class with 6 lifecycle methods
- `CompositeHook` with **error isolation** (catches + logs per-hook exceptions)
- `_LoopHookChain` that chains primary hook → extra hooks
- `AgentLoop.__init__(hooks=...)` parameter
- `Nanobot.run(hooks=[...])` for SDK usage

**No PR needed.** Hooks can be passed programmatically.

### 5.2 Discovery gap

There is **no `nanobot.hooks` entry_points group** in the current nanobot. Hooks must be passed explicitly via:

- `AgentLoop(hooks=[my_hook])` — for CLI usage
- `Nanobot.run(hooks=[my_hook])` — for SDK usage

The CLI doesn't have a config option for extra hooks. This means:

- For **terminal usage**: We'd need to either (a) monkey-patch AgentLoop, (b) add a config option to nanobot, or (c) use the SDK interface.
- For **Slack/Signal usage**: The channel manager creates AgentLoop internally. We'd need a config option or entry_points.

### 5.3 Recommended packaging

**Option A: Standalone package `nanobot-sessionbuddy`**

```toml
# pyproject.toml
[project]
name = "nanobot-sessionbuddy"
dependencies = [
    "nanobot-ai>=0.1.4",
    "httpx>=0.28",
]

[project.optional-dependencies]
dev = ["session-buddy>=0.14"]

[project.entry-points."nanobot.channels"]
# Not applicable — we're not a channel, we're a hook
```

The hook would be a Python class that users import and pass:

```python
from nanobot_sessionbuddy import SessionTrackingHook

# In config or startup
hooks = [SessionTrackingHook(sb_url="http://localhost:8678")]
```

**Option B: Add hook to session-buddy package**

```toml
# session-buddy/pyproject.toml
[project.optional-dependencies]
nanobot = ["nanobot-ai>=0.1.4", "httpx>=0.28"]
```

```python
# session_buddy/integrations/nanobot_hook.py
from nanobot.agent.hook import AgentHook, AgentHookContext

class SessionBuddyHook(AgentHook):
    async def before_iteration(self, context: AgentHookContext) -> None:
        # Call Session-Buddy HTTP API directly
        async with httpx.AsyncClient() as client:
            await client.post("http://localhost:8678/api/v1/heartbeat", json={...})
```

**Recommendation: Option B.** Keep it in the session-buddy package as an optional extra. Users who want automatic tracking install `session-buddy[nanobot]`.

______________________________________________________________________

## 6. Risk Assessment: Plugin Exception Handling

### CompositeHook error isolation (verified in source)

```python
# nanobot/agent/hook.py:70-75
async def _for_each_hook_safe(self, method_name: str, *args, **kwargs) -> None:
    for h in self._hooks:
        try:
            await getattr(h, method_name)(*args, **kwargs)
        except Exception:
            logger.exception("AgentHook.{} error in {}", method_name, type(h).__name__)
```

**This is bulletproof.** If SessionBuddyHook throws:

1. The exception is caught and logged
1. The agent loop continues normally
1. Other hooks still fire
1. No data loss — only session tracking is affected

### Risk matrix

| Failure Mode | Impact | Mitigation |
|---|---|---|
| Session-Buddy server down | Heartbeats fail, sessions appear "active" forever | Timeout sessions server-side (30min idle) |
| Network timeout (httpx) | One heartbeat dropped | Use short timeout (2s), fire-and-forget |
| Malformed response | Exception caught by CompositeHook | Validate response in hook, catch locally too |
| Session-Buddy returns 500 | Session not tracked | Log warning, retry next iteration |
| Hook raises in `finalize_content` | **NOT isolated** (pipeline, not fan-out) | Don't use `finalize_content` for tracking |
| Memory leak in hook | Accumulated state | Keep hook stateless (read MEMORY.md each iteration) |

### One critical note

`finalize_content` is a **pipeline**, not fan-out. It does NOT have error isolation. The hook must NOT override `finalize_content` with anything that can throw. Our hook should only use `before_iteration` and `after_iteration`, which are both isolated.

______________________________________________________________________

## 7. Migration Path: Skill → Plugin Without Losing Sessions

### Phase 1: Skill Only (now)

1. Deploy the SKILL.md as-is with hardening mitigations
1. Session data flows through MCP tools → Session-Buddy server
1. Sessions are stored with `session_id = nanobot-{timestamp}`

### Phase 2: Add Hook (after validation)

1. Add `SessionBuddyHook` to session-buddy package
1. Hook reads MEMORY.md to find active session_id
1. If no session exists but messages are flowing → hook calls `track_session_start` via HTTP
1. If session exists → hook sends heartbeat every N iterations
1. Hook does NOT interfere with skill's session_start/end calls (both can coexist)

### Session continuity

The critical invariant is: **session_id format must match between skill and hook.**

```python
# Both use the same format:
session_id = f"nanobot-{timestamp}"  # e.g., "nanobot-20260407-123456"
```

The hook can read the session_id from MEMORY.md (written by the skill) and continue using it. No migration needed — the hook simply picks up where the skill left off.

### Phase 3: Deprecate Skill (optional)

Once the hook is proven reliable:

1. Set `always: false` → keep skill as fallback
1. Hook handles all tracking automatically
1. Skill still exists for manual checkpoint/end-session commands

______________________________________________________________________

## 8. Session-Buddy HTTP API: Direct vs MCP

### Current HTTP endpoints

Session-Buddy exposes via FastMCP's `custom_route`:

- `GET /health` — health check
- `GET /healthz` — k8s health check
- `GET /metrics` — Prometheus metrics
- `POST /mcp` — MCP streamable-http transport

**There is no direct HTTP API for session tracking.** All session operations go through MCP tools (`track_session_start`, `track_session_end`, `checkpoint`).

### For the plugin, add a thin HTTP endpoint

```python
@mcp.custom_route("/api/v1/sessions/heartbeat", methods=["POST"])
async def api_heartbeat(request):
    """Lightweight heartbeat endpoint for nanobot hook."""
    # No MCP overhead, no JWT auth needed for localhost
    # Validate source IP is localhost
    ...
```

This gives the hook a fast, lightweight path that doesn't require MCP protocol negotiation. MCP tool calls have significant overhead (JSON-RPC framing, tool discovery, response parsing). A direct HTTP POST is ~10x faster for fire-and-forget heartbeats.

### Recommendation

Add `/api/v1/sessions/start`, `/api/v1/sessions/end`, `/api/v1/sessions/heartbeat` as HTTP endpoints on Session-Buddy. The hook uses these. The skill continues to use MCP tools (richer validation, structured responses). Both write to the same `SessionTracker` backend.

______________________________________________________________________

## 9. Decision Matrix

| Criterion | Skill (A) | Plugin (B) | Hybrid (A+B) |
|---|---|---|---|
| **Time to deploy** | ✅ Now | ⚠️ 1-2 days | ✅ Now + 2 days |
| **Reliability** | ⚠️ LLM-dependent | ✅ Guaranteed | ✅ Guaranteed |
| **Channel awareness** | ❌ Requires LLM detection | ✅ Direct from InboundMessage | ✅ |
| **Per-iteration data** | ❌ Cannot track | ✅ Every iteration | ✅ |
| **Context window impact** | ⚠️ Uses tokens for instructions | ✅ Zero token overhead | ✅ Minimal |
| **Error isolation** | N/A (LLM decides) | ✅ CompositeHook | ✅ |
| **No nanobot changes** | ✅ | ✅ (hooks param exists) | ✅ |
| **Multi-channel support** | ⚠️ Partial | ✅ Full | ✅ Full |
| **User-facing features** | ✅ Checkpoint, reminders | ❌ Silent | ✅ Both |
| **Maintenance burden** | ⚠️ LLM prompt drift | ✅ Stable Python code | ⚠️ Both |

______________________________________________________________________

## 10. Final Recommendation

### Ship order

1. **Today**: Deploy hardened SKILL.md (with compact recovery, reduced exec calls, heartbeat cron)
1. **This week**: Add `/api/v1/sessions/*` HTTP endpoints to Session-Buddy (for future hook use)
1. **Next week**: Add `SessionBuddyHook` class to session-buddy package as `session-buddy[nanobot]` optional extra
1. **Validate**: Run hook alongside skill for 1 week, compare session coverage
1. **Stabilize**: If hook proves reliable, make it the primary; skill becomes fallback for manual operations

### Why not wait for the plugin?

The skill works today. Waiting for the plugin means losing session data for every nanobot session that runs in the meantime. The hybrid approach captures data from day one and incrementally improves reliability.

### Why the plugin matters long-term

The skill cannot track:

- Every agent iteration (token usage patterns)
- Channel identity without LLM cooperation
- Silent failures (when the LLM doesn't call MCP tools)
- Automatic idle-timeout session ends

The plugin guarantees all of these. It's not a replacement for the skill — it's the operational backbone that makes session tracking production-grade.

______________________________________________________________________

## Appendix A: Verified Source Locations

| Component | Path |
|---|---|
| SKILL.md | `/Users/les/Projects/mahavishnu/skills/session-buddy/SKILL.md` |
| Multi-channel spec | `/Users/les/Projects/mahavishnu/docs/plans/session-buddy-multi-channel-spec.md` |
| AgentHook base | `nanobot/agent/hook.py` |
| CompositeHook | `nanobot/agent/hook.py:54-95` |
| \_LoopHookChain | `nanobot/agent/loop.py:113-147` |
| AgentLoop hooks param | `nanobot/agent/loop.py:183,214` |
| Nanobot.run(hooks=) | `nanobot/nanobot.py:87-110` |
| MemoryStore (MEMORY.md) | `nanobot/agent/memory.py:31-337` |
| Consolidator | `nanobot/agent/memory.py:346-512` |
| Dream | `nanobot/agent/memory.py:519-671` |
| Session-Buddy server | `session_buddy/server_optimized.py` |
| Session-Buddy event models | `session_buddy/mcp/event_models.py` |
| Session-Buddy tracker | `session_buddy/mcp/session_tracker.py` |
| Admin shell MCP tools | `session_buddy/mcp/tools/session/admin_shell_tracking_tools.py` |
| Channel registry | `nanobot/channels/registry.py` |
| SB HTTP endpoints | `/health`, `/healthz`, `/metrics` only |

## Appendix B: No `nanobot.hooks` Entry Points Group

Confirmed: there is no `nanobot.hooks` entry_points group in the installed nanobot (v0.1.4.post6). The only entry point is:

```
[console_scripts]
nanobot = nanobot.cli.commands:app
```

Channel plugins use `nanobot.channels` group, but that's for `BaseChannel` subclasses, not hooks. Hook injection is currently only via the `hooks` parameter to `AgentLoop` or `Nanobot.run()`. A future PR could add hook discovery via entry_points, but it's not needed for our approach — we pass hooks explicitly.
