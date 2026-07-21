---
status: active
role: implementation
topic: mcp-design
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Mahavishnu ACP Server — Design Spec

**Status:** Approved (design phase complete, awaiting plan) <!-- legacy status: Approved — see YAML frontmatter -->
**Date:** 2026-07-15
**Scope:** New `mahavishnu/acp/` subpackage exposing Mahavishnu as an **ACP server** (stdio JSON-RPC 2.0), alongside the existing A2A HTTP+SSE server.
**Track:** Toad/ACP integration (deferred per user direction; spec committed for future implementation).
**Brainstorm companion:** `.superpowers/brainstorm/85729-1784161289/` (v8 Constellation visual companion is unrelated; this spec is its own thread).

## Context

Toad ([batrachianai/toad](https://github.com/batrachianai/toad)) is a Textual-based TUI that drives coding agents via the **Agent Client Protocol (ACP)** — a JSON-RPC 2.0 protocol jointly governed by [Zed and JetBrains](https://agentclientprotocol.com/community/governance). As of 2026-07-15 the [ACP adopters list](https://agentclientprotocol.com/ecosystem) includes **Claude Code**, plus 14+ IDE clients (Zed, JetBrains, VS Code, Neovim, Vim, etc.). Toad has **no public roadmap item** for A2A support (4 open issues, 0 GitHub hits for "A2A").

Mahavishnu today exposes itself as an **A2A server** (HTTP+SSE, well-known agent card, task lifecycle) at `mahavishnu/a2a/server.py` (242 lines). It does **not** implement ACP. To use Toad directly against Mahavishnu — without the Claude Code layer between — Mahavishnu must speak ACP.

Path A (this spec) is the user's chosen direction: **add an ACP server transport to Mahavishnu**, alongside the existing A2A server, so any ACP client (Toad, Zed's experimental ACP support, future ACP tooling) can drive Mahavishnu directly.

Two recent developments make this path more attractive than it was a year ago:

1. **MCP-over-ACP RFD** ([agentclientprotocol.com/rfds/mcp-over-acp](https://agentclientprotocol.com/rfds/mcp-over-acp)) — agents will be able to advertise `mcpCapabilities.acp: true`, letting ACP sessions tunnel MCP tool calls. Mahavishnu's existing 174 MCP tools could ride on ACP sessions without re-implementation.
1. **A2A v1.0 GA** (January 15, 2026, [Linux Foundation announcement](https://linuxfoundation.org/announcing-a2a-v1-0)) — proves the A2A surface is canonical and stable; we are not replacing it, just adding a second protocol.

## Decision

Add an **ACP server** to Mahavishnu at `mahavishnu/acp/`:

- **Transport:** stdio JSON-RPC 2.0 (newline-delimited; no embedded newlines). One ACP session per Mahavishnu process invocation. Matches the local-agent transport from ACP §transports; remote (Streamable HTTP) deferred until the upstream draft stabilizes.
- **Lifecycle methods implemented:** `initialize`, `authenticate` (optional), `session/new`, `session/load` (gated on `loadSession` capability), `session/prompt`, `session/cancel`, plus `session/update` notifications outbound.
- **Session body:** A single ACP `session/prompt` call maps to `execute_fn({"prompt": prompt})` (the same entry point that powers A2A's `POST /tasks/send` and `pool_route_execute`). The `session_id` is a uuid; Mahavishnu state per session is held in-process for the session's lifetime.
- **Streaming:** Every line of `execute_fn` output becomes a `session/update` notification with `{type: "agent_message_chunk", content: {type: "text", text: "..."}}` — same shape as the A2A SSE events that already flow from `mahavishnu/a2a/server.py:160-198`. EventBridge events are synthesized into ACP `session/update` types where they fit (see "Event synthesis" below).
- **Cancel:** ACP `session/cancel` maps to a Mahavishnu-side `asyncio.CancelledError` injected into the running `execute_fn` task. New in this codebase (A2A has no cancel today).
- **Auth:** Mahavishnu exposes a Bearer token in the AgentCard's `_meta.acp.authMethods` (or via an out-of-band negotiation), which the ACP client passes to `authenticate`. Reuses the same Bearer middleware pattern from `mahavishnu/a2a/server.py:33-56`.

This is the smallest change that:

- Lets Toad drive Mahavishnu directly via ACP, no Claude Code between them.
- Surfaces Mahavishnu's full pool/routing/EventBridge affordance to ACP clients.
- Positions Mahavishnu for the MCP-over-ACP RFD when it lands.
- Does not modify the existing A2A server (which is canonical for inter-agent federation).

## Out of scope

- **A2A changes.** No modifications to `mahavishnu/a2a/`. We are adding a second protocol, not replacing the first.
- **Remote ACP (Streamable HTTP).** ACP remote transport is a draft upstream. Stdio only for v1.
- **MCP-over-ACP** (the RFD). Mahavishnu's existing MCP tools can be re-exposed through ACP later as a follow-on; not part of this spec.
- **A2A-spec compliance fix.** `mahavishnu/a2a/server.py` serves the AgentCard at `/.well-known/agent.json`; the v1.0 spec uses `/.well-known/agent-card.json`. Trivial fix but out of scope here.
- **Toad-side changes.** Toad is upstream. We don't fork or PR Toad.
- **Editor-side changes.** Zed, JetBrains, VS Code ACP support is upstream; we don't ship IDE plugins.
- **Multi-tenant identity.** ACP sessions are per-process; we don't build a multi-user concurrent ACP server (stdio precludes this anyway — one ACP client = one Mahavishnu process).

## Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│ ACP Client (Toad, Zed, JetBrains, VS Code, ...)                            │
└────────────────────────────────────────────────────────────────────────────┘
                              ▲ stdio JSON-RPC 2.0
                              │ newline-delimited messages
                              ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ mahavishnu acp-server  (new entry point: `mahavishnu acp serve`)           │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ ACP JSON-RPC dispatcher (mahavishnu/acp/server.py)                   │  │
│  │  - initialize, authenticate, session/new, session/load                │  │
│  │  - session/prompt → execute_fn({"prompt": prompt})                   │  │
│  │  - session/cancel → asyncio.CancelledError into running task          │  │
│  │  - session/update (outbound) → synthesized from EventBridge + execute │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ ACP session state (in-process dict)                                  │  │
│  │  - session_id → {task, cancellation_token, started_at, ...}          │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                              │                                             │
│                              ▼                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Event synthesis adapter (mahavishnu/acp/events.py)                   │  │
│  │  - EventBridge envelope → ACP session/update notification             │  │
│  │  - working → status update                                            │  │
│  │  - completed/failed → status update + final stopReason               │  │
│  │  - stage_completed → agent_message_chunk                             │  │
│  │  - worker.completed → tool_call update (if known)                    │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
                              │ (existing — no change)
                              ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ Mahavishnu core: execute_fn / pool_route_execute / EventBridge             │
│ mahavishnu/a2a/server.py (existing — unchanged)                             │
│ Mahavishnu CLI: `mahavishnu acp serve` (new)                                │
└────────────────────────────────────────────────────────────────────────────┘
```

## Components

### `mahavishnu/acp/__init__.py` (NEW)

Package marker. Re-exports the public API: `serve()`, `ACPError`, `ACPSession`.

### `mahavishnu/acp/server.py` (NEW)

The stdio JSON-RPC 2.0 dispatcher. Listens on stdin, writes to stdout, logs to stderr. ~200 lines.

```python
"""ACP server for Mahavishnu — stdio JSON-RPC 2.0 transport."""
from __future__ import annotations
import asyncio
import json
import sys
from typing import Any
from collections.abc import Awaitable, Callable

class ACPError(Exception):
    """Raised on protocol-level errors; serialized to JSON-RPC error response."""

class ACPSession:
    session_id: str
    task: asyncio.Task | None
    cancellation_token: asyncio.Event

async def serve(execute_fn: Callable[[dict[str, Any]], Awaitable[Any]]) -> None:
    """Main loop: read JSON-RPC from stdin, dispatch, write responses/notifications."""
```

Handlers:

| Method | Behavior |
|---|---|
| `initialize` | Returns server capabilities: `{protocolVersion, agentCapabilities: {loadSession: true, mcp: {http: false, sse: false}}, authMethods: [{id: "bearer"}]}` |
| `authenticate` | Validates Bearer token against `MAHAVISHNU_ACP_BEARER_TOKEN` env var; sets session auth state |
| `session/new` | Generates uuid; creates `ACPSession`; returns `{sessionId}` |
| `session/load` | Returns 404 unless the client supplies a known checkpoint (deferred — see Open Questions) |
| `session/prompt` | Spawns `execute_fn({"prompt": content})`; emits `session/update` notifications for every line/chunk; final response carries `stopReason: "end_turn"` |
| `session/cancel` | Sets `cancellation_token`; awaits task completion with timeout; returns ack |

### `mahavishnu/acp/events.py` (NEW)

EventBridge envelope → ACP `session/update` notification synthesizer. ~150 lines.

Maps Mahavishnu EventBridge events (channel `bodai:events`, per `mahavishnu/core/events/bodai_subscriber.py`) to ACP shapes:

| EventBridge envelope `type` | ACP `session/update` notification |
|---|---|
| `workflow_started` | `{type: "status", status: "working"}` |
| `stage_completed` | `{type: "agent_message_chunk", content: {type: "text", text: "stage <name> complete"}}` |
| `worker.completed` | `{type: "tool_call_update", toolCallId: <task_id>, status: "completed"}` |
| `completed` | `{type: "status", status: "completed"}` |
| `failed` | `{type: "status", status: "failed"}` + error message chunk |
| `crackerjack.gate_raised` | `{type: "agent_message_chunk", content: {type: "text", text: "crackerjack warning: <msg>"}}` |

Unknown event types pass through as `{type: "agent_message_chunk", content: {type: "text", text: <serialized>}}` so ACP clients see everything. Subscribe via `mahavishnu.core.events.bodai_subscriber.subscribe_to_bodai_events` with a queue_path in `~/.mahavishnu/` and forward envelopes synchronously.

### `mahavishnu/acp/protocol.py` (NEW)

Pydantic models for the ACP wire format (the messages we send and receive). Generated by hand from the ACP spec rather than via codegen — ACP's schema is small enough (~20 message types). Keeps a typed surface for the dispatcher.

### `mahavishnu/cli/acp_cli.py` (NEW) — registers in `mahavishnu/_main_cli.py`

```python
import typer
from mahavishnu.acp.server import serve
from mahavishnu.settings import load_settings

app = typer.Typer(help="ACP (Agent Client Protocol) server.")

@app.command("serve")
def serve_cmd() -> None:
    """Start the ACP server on stdio. Wire-protocol listener for ACP clients."""
    settings = load_settings()
    execute_fn = _build_execute_fn(settings)
    asyncio.run(serve(execute_fn))
```

Registered as `mahavishnu acp serve`. The existing `mahavishnu acp` namespace has no current command; this lands cleanly.

### `mahavishnu/cli/acp_cli.py` private helper: `_build_execute_fn(settings)`

Reuses the existing A2A handler's `execute_fn` construction pattern from `mahavishnu/a2a/server.py`. Same prompt-extraction logic; same call into the Mahavishnu task pipeline. Single source of truth for "given a prompt string, run a Mahavishnu task" — both A2A and ACP call it.

## Data flow

End-to-end: Toad sends `session/prompt` with a prompt; Mahavishnu executes it; ACP client sees streamed updates.

1. ACP client writes JSON-RPC line to Mahavishnu's stdin: `{"jsonrpc":"2.0","id":1,"method":"session/prompt","params":{"sessionId":"...","content":"..."}}`.
1. `mahavishnu/acp/server.py` reads the line, dispatches to `session_prompt_handler`.
1. Handler spawns `asyncio.create_task(execute_fn({"prompt": content}))`. The task body emits chunks (lines of stdout, EventBridge envelopes) via the in-process bridge in `mahavishnu/acp/events.py`.
1. Each chunk is serialized as a `session/update` JSON-RPC notification (no `id`, just `method`) and written to Mahavishnu's stdout.
1. When `execute_fn` finishes, handler emits a final `session/update` with `{type: "status", status: "completed"}` (or `failed`) and returns `{"stopReason": "end_turn"}` as the JSON-RPC response to the original `id`.
1. If the ACP client sends `session/cancel` mid-flight: handler sets `cancellation_token.set()`, the running `execute_fn` raises `asyncio.CancelledError`, handler returns ack.

## Error handling

| Failure | Detection | Behavior |
|---|---|---|
| Stdin pipe closed (ACP client died) | `EOF` on `sys.stdin.read()` | Server exits 0 cleanly. No log spam. |
| Invalid JSON-RPC | `json.JSONDecodeError` | Return JSON-RPC `-32700 Parse error`; continue loop. |
| Unknown method | dispatcher lookup miss | Return JSON-RPC `-32601 Method not found`; continue loop. |
| `session/prompt` with no auth | auth state check | Return JSON-RPC `-32001 Auth required`; do not execute. |
| `execute_fn` raises | `except` in task wrapper | Emit `session/update` with `{type: "status", status: "failed", message}`; return response with `stopReason: "error"`. |
| `session/cancel` race | task already done | Return ack immediately; idempotent. |
| EventBridge unreachable | `subscribe_to_bodai_events` raises | Log warning; ACP server continues with stdout-only streaming (the chunks from `execute_fn` still flow); `session/update` synthesis for EventBridge events is best-effort. |
| Bearer token mismatch | string compare | Return JSON-RPC `-32002 Auth invalid`. |

No silent fallbacks. Each error path emits a structured log line and a structured JSON-RPC error response.

## File layout

| File | Status | Purpose |
|---|---|---|
| `mahavishnu/acp/__init__.py` | NEW | Package marker |
| `mahavishnu/acp/server.py` | NEW | JSON-RPC dispatcher; ~200 lines |
| `mahavishnu/acp/events.py` | NEW | EventBridge → ACP session/update synthesizer; ~150 lines |
| `mahavishnu/acp/protocol.py` | NEW | Pydantic wire-format models; ~300 lines |
| `mahavishnu/cli/acp_cli.py` | NEW | `mahavishnu acp serve` command |
| `mahavishnu/_main_cli.py` | MODIFY | Register `acp_cli` as `app.add_typer(acp_app, name="acp")` |
| `tests/unit/acp/test_server.py` | NEW | Dispatcher unit tests |
| `tests/unit/acp/test_events.py` | NEW | EventBridge → ACP mapping tests |
| `tests/unit/acp/test_protocol.py` | NEW | Pydantic round-trip tests |
| `tests/integration/acp/test_acp_stdio_e2e.py` | NEW | Gated: spawn `mahavishnu acp serve`, feed JSON-RPC lines on stdin, assert responses on stdout |
| `docs/acp/USAGE.md` | NEW | Operator doc: how to point Toad at Mahavishnu |

## Integration Contracts

Per `.claude/decisions/wire-up-contract.md`, every deliverable carries an Integration Contract. Three deliverables (server core, event synthesis, CLI surface) each get one.

### Deliverable 1: ACP server core (`mahavishnu/acp/server.py` + `protocol.py`)

- **Triggered from:** `mahavishnu acp serve` (new CLI command). Toad launches this as a subprocess and pipes its stdio.
- **Returns to / updates:** stdout (JSON-RPC responses and `session/update` notifications). Logs structured events to `~/.mahavishnu/logs/mcp.log`.
- **Demonstrable by:** `echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"<current ACP version>","clientInfo":{"name":"test","version":"0.0.1"}}}' | uv run mahavishnu acp serve`. Asserts: stdout contains a JSON-RPC response with `result.protocolVersion` echoing the requested version and `result.agentCapabilities.loadSession: true`.
- **Rollback signal:** If the server crashes 3x in 60s, log `level=error` and refuse to restart. Operator disables the CLI command by removing the registered sub-app from `_main_cli.py`.
- **Observability added:** Structured log lines per JSON-RPC message: `acp.request_received`, `acp.response_sent`, `acp.session_started`, `acp.session_completed`, `acp.session_cancelled`. OTel span `mahavishnu.acp.session` with attributes `session.id`, `session.stop_reason`, `session.duration_ms`.

### Deliverable 2: Event synthesis adapter (`mahavishnu/acp/events.py`)

- **Triggered from:** `subscribe_to_bodai_events` callback (existing) writes envelopes to the ACP session's outbound queue when the session is active.
- **Returns to / updates:** Writes `session/update` notifications to the ACP server's outbound writer; no persistent state.
- **Demonstrable by:** Unit test publishes a synthetic EventBridge envelope (e.g., `{"type": "stage_completed", ...}`), asserts the synthesizer produces the correct ACP `session/update` shape per the mapping table.
- **Rollback signal:** If `subscribe_to_bodai_events` raises or the session's outbound queue fills (back-pressure), the synthesizer drops the envelope and logs `level=warning`. ACP server continues with execute_fn-direct chunks only.
- **Observability added:** Structured log lines: `acp.event_synthesized type=<event_type> shape=<update_kind>`. Counter for dropped envelopes.

### Deliverable 3: CLI surface (`mahavishnu/cli/acp_cli.py` + `_main_cli.py` registration)

- **Triggered from:** Operator runs `mahavishnu acp serve`, OR Toad's ACP-client config invokes `mahavishnu acp serve` as the agent subprocess.
- **Returns to / updates:** Process stays alive; exits 0 when stdin EOFs.
- **Demonstrable by:** `uv run mahavishnu acp --help` prints usage including the `serve` subcommand. `uv run mahavishnu --help` lists `acp` alongside the existing subcommands.
- **Rollback signal:** N/A (registration is at startup; failure to import raises ImportError before serve runs).
- **Observability added:** Process-start log line `acp.cli.serve_started pid=<n>`. Existing Mahavishnu CLI startup logs apply.

## Testing

Four layers:

### Layer 1: Unit tests — `tests/unit/acp/test_protocol.py`

- Pydantic round-trip for each ACP wire message type we send or receive (`initialize`, `session/new`, `session/prompt`, `session/update`, `session/cancel`, error responses).
- JSON serialization matches the ACP spec's snake_case fields.

### Layer 2: Unit tests — `tests/unit/acp/test_server.py`

- Dispatcher round-trips a synthetic JSON-RPC request to a stub handler and emits the right response shape.
- Unknown method returns `-32601 Method not found`.
- Invalid JSON returns `-32700 Parse error`.
- Bearer auth gate: `session/prompt` without prior `authenticate` returns `-32001 Auth required`.
- Cancel idempotency: calling `session/cancel` twice or after task completion both ack.

### Layer 3: Unit tests — `tests/unit/acp/test_events.py`

- EventBridge envelope → ACP `session/update` mapping per the table above.
- Unknown envelope type passes through as a generic text chunk (no silent drop).
- Drop-on-full-queue path: simulator fills outbound queue, asserts next envelope is dropped with `level=warning`.

### Layer 4: Integration test — `tests/integration/acp/test_acp_stdio_e2e.py` (gated)

Gated by `MAHAVISHNU_ACP_INTEGRATION=1`. Skipped in fast CI.

- Spawn `uv run mahavishnu acp serve` as a subprocess; pipe `initialize`, `authenticate`, `session/new`, `session/prompt` lines to stdin; assert matching responses on stdout.
- Send `session/cancel` mid-prompt; assert task cancellation completes within 1s and a `status: failed` `session/update` arrives.
- Exit by closing stdin; assert subprocess exits 0 within 1s.

### Layer 5: Manual smoke test (not in pytest)

- Configure Toad to point at `mahavishnu acp serve` (per Toad's agent-config syntax).
- Type a prompt in Toad; observe streaming chunks.
- Trigger a workflow via Toad; observe `session/update` notifications.
- Send `Ctrl-C` in Toad; observe cancel.

## Implementation order

1. **`mahavishnu/acp/protocol.py`** — Pydantic models. Pure data, no I/O. Independent of everything else. Fastest to land and unlocks typed dispatch.
1. **`mahavishnu/acp/events.py`** — EventBridge → ACP synthesizer. Independent of the dispatcher; depends on `protocol.py`.
1. **`mahavishnu/acp/server.py`** — JSON-RPC dispatcher. Depends on `protocol.py`; uses `events.py` for streaming.
1. **`mahavishnu/cli/acp_cli.py` + `_main_cli.py` registration** — wires the entry point. Depends on `server.py`.
1. **Tests** — Layers 1-4 in order; Layer 5 (manual) deferred to last.
1. **`docs/acp/USAGE.md`** — operator doc with Toad config example.

Each step is independently mergeable. Steps 1-3 can be developed in parallel (they share `protocol.py` as a contract); step 4 is the wiring; step 5 is the quality gate.

## Open questions for the plan phase

- **`session/load` capability**: ACP supports `session/load` for resuming prior sessions. We have no persistence layer for sessions today (the A2A server is also stateless). Should `session/load` return "not implemented" for v1, or should we persist session transcripts to `~/.mahavishnu/acp-sessions/<id>.jsonl` for reload? Plan phase decides.
- **Tool-call visibility**: ACP `session/update` has a `tool_call` subtype that lets clients show "running tool X with Y arguments" in their UI. EventBridge doesn't surface tool calls today (only stage completions). For full Toad fidelity, we'd need to either (a) extend the EventBridge to emit tool-call events, or (b) accept that Toad shows text chunks only. Plan phase picks.
- **MCP-over-ACP**: The RFD is in flight. When it lands, we'd add `mcpCapabilities.acp: true` to `initialize` and tunnel the existing 174 MCP tools through ACP sessions. Out of scope for v1.
- **Remote ACP**: ACP's remote (Streamable HTTP) transport is a draft. When it stabilizes, add a `--transport=http` flag to `mahavishnu acp serve`. Out of scope for v1.

## References

- [.claude/decisions/wire-up-contract.md](../../.claude/decisions/wire-up-contract.md) — Integration Contract policy
- [docs/plans/TEMPLATE.md](../../plans/TEMPLATE.md) — implementation plan template (next phase)
- [docs/feature-tracking/TEMPLATE.md](../../feature-tracking/TEMPLATE.md) — feature-state tracker (`built → wired → adopted`)
- ACP official: [agentclientprotocol.com](https://agentclientprotocol.com/) (governance: [Zed + JetBrains](https://agentclientprotocol.com/community/governance); ecosystem: [clients + agents](https://agentclientprotocol.com/ecosystem); MCP-over-ACP RFD: [rfds/mcp-over-acp](https://agentclientprotocol.com/rfds/mcp-over-acp))
- A2A v1.0 (existing Mahavishnu protocol, unchanged): [Linux Foundation announcement](https://linuxfoundation.org/announcing-a2a-v1-0); [Google blog](https://blog.google/technology/ai/a2a-linux-foundation); [a2a-protocol.org](https://a2a-protocol.org/)
- Toad: [github.com/batrachianai/toad](https://github.com/batrachianai/toad) (ACP-only; no A2A on roadmap)
- Existing Mahavishnu A2A server (unchanged): `mahavishnu/a2a/server.py`
- Existing Mahavishnu EventBridge subscriber (consumed): `mahavishnu/core/events/bodai_subscriber.py`
- WebSocket stage broadcasting reference: `mahavishnu/websocket/server.py:559` (`broadcast_workflow_stage_completed`) — ACP `session/update` follows the same event types
- Spec sibling: [2026-07-15-constellation-tui-design.md](./2026-07-15-constellation-tui-design.md) (Track 1 — same deferred-to-future-implementation pattern)

## Status

Approved 2026-07-15. Ready for the writing-plans phase when implementation is prioritized. Plan/index entries to follow.
