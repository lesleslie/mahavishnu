# Constellation TUI: Three-Surface Dashboard for Claude Code

**Status:** Approved (design phase complete, awaiting plan)
**Date:** 2026-07-15
**Scope:** Claude Code extension surfaces (statusLine, subagentStatusLine, OSC 777) wired to the Mahavishnu EventBridge
**Track:** Track 1 of 2 (Track 2 — Toad/ACP integration — deferred per design)

## Context

Mahavishnu is the control plane for the Bodai ecosystem (Akosha, Dhara, Session-Buddy, Crackerjack, Oneiric). When an operator is running Claude Code inside this ecosystem, there is no in-CLI affordance that surfaces what the orchestrator is doing. The user runs `mahavishnu pool route --prompt "..."` or `mcp__mahavishnu__pool_route_execute` and the work happens out-of-band; from the Claude Code window, the operator sees nothing.

The user already runs a one-off status line script (`~/.claude/scripts/session_progress_real.py`) that renders two progress bars (5-hour token block, context window) and project metadata. It is not wired to anything Mahavishnu-specific; it only knows about the Anthropic billing JSONL files and ZAI/MiniMax plan quotas. The opportunity is to extend this script to also surface Bodai state, and to add two more surfaces that the user's existing setup does not yet use: `subagentStatusLine` and OSC 777 native notifications.

The locked design (v8, three-surface split) was selected after iterating through mockups v1–v7 in the visual companion. Earlier attempts at a single-screen Constellation dashboard were rejected because (a) a 1500px-wide browser mockup cannot fit in any terminal's statusline region, (b) one big always-on render crowds the chat area, and (c) lifecycle events are better as transient toasts than as a scrolling ticker.

## Decision

Render the Constellation dashboard across **three Claude Code extension surfaces**, each owning the slice it can render cleanly:

1. **`statusLine`** — always-on 5-line strip: three progress bars (context window, 5-hour block, weekly all-model cap), a one-line ecosystem summary with OSC 8 clickable links to each component's MCP surface, and a one-line most-recent-event. Replaces/extends the user's existing `session_progress_real.py`.
2. **`subagentStatusLine`** — per-task JSON rows, one row per active Mahavishnu worker / Claude Code subagent. Owns the workflow chain (scout/plan/patch/verify/land stages render as 5 keyed rows).
3. **OSC 777 toasts** — transient native terminal notifications for lifecycle events (workflow_started, stage_completed, completed, failed, pool_scaled, worker.completed, crackerjack_gate_raised). Drained by a `PostToolUse` hook subscribing to the Mahavishnu EventBridge.

This is the smallest change that:

- Reuses the user's existing `session_progress_real.py` (extends it; doesn't replace it).
- Adds one new file (`mahavishnu-activity-stream.py`) for OSC 777 emission.
- Adds one new file (`mahavishnu-subagent-status.py`) for subagent statusline rows.
- Wires all three surfaces to the existing EventBridge transport (channel `bodai:events`) — no new transport.
- Surfaces the workflow-chain data that already exists in `mahavishnu/websocket/server.py:559` (`broadcast_workflow_stage_completed`).

## Out of scope

- **Track 2 — Toad/ACP integration.** The user requested a separate brainstorm for Toad as another optional coding agent via ACP. This is deferred per the user's explicit direction. A future spec will cover ACP server exposure in Mahavishnu and the Toad adapter.
- **Realtime ticker in the statusline.** The statusline renders on idle (~every few hundred ms after a keystroke), not as a continuous stream. A live 10-row ticker is impossible from the statusline alone. Lifecycle events go through OSC 777 instead.
- **Replacing the user's existing `session_progress_real.py`.** This design *extends* that script — preserves its existing two-bar behavior, adds a third bar, ecosystem summary line, and event tail.
- **A full TUI desktop application.** Constellation is a Claude Code extension, not a separate app. Operators who want a deeper Bodai console use `mahavishnu pool health` / `mahavishnu monitoring status` directly.
- **Mahavishnu-side changes to MCP server ports or transport.** We link to existing surfaces (`http://localhost:{8680,8682,8683,8676,8678}/mcp`) using OSC 8 hyperlinks; we don't add any new HTTP routes.
- **Cross-machine operator views.** Constellation surfaces the **local** session's view. Multi-machine fleet views belong in Akosha's Grafana dashboards.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       Claude Code (operator's TUI)                       │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  statusLine (always-on, 5 lines)                                   │  │
│  │  ───────────────────────────────────────────────                   │  │
│  │  🟡 MED │ ████████░░ 78% │ 186k/200k │ context window     93%    │  │
│  │  🟢 OK  │ █████░░░░░ 44% │  442k/1m  │ 5-hour rolling    7pm     │  │
│  │  🔴 HIGH│ ██████████ 92% │ 9.2m/10m  │ weekly all-model  Sun     │  │
│  │  Ecosystem [M]mahavishnu [P]pools [A]akosha [D]dhara [C]cracker… │  │
│  │  07:42:11 ⚡ [info] pools.spin_up mahavishnu complete              │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  subagentStatusLine (per-task rows, adaptive height)               │  │
│  │  ───────────────────────────────────────────────                   │  │
│  │  🟢 w-01 scout       · akosha diffing        · 12.4k tok · 00:41 │  │
│  │  🟢 w-02 plan        · crackerjack running   · 08.1k tok · 00:28 │  │
│  │  🟡 w-03 patch       · waiting on memory      · 04.7k tok · 00:12 │  │
│  │  🔵 w-04 verify      · queued                 ·        —         │  │
│  │  🔵 w-05 land        · queued                 ·        —         │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  OSC 777 native notifications (transient toasts)                   │  │
│  │  ───────────────────────────────────────────────                   │  │
│  │  ⚡ worker w-02 completed · refactor-auth stage=plan · 28s         │  │
│  │  ⚡ pool local scaled 3 → 4                                        │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
                              ▲
                              │ reads from (via stdin JSON)
                              │
┌─────────────────────────────┴────────────────────────────────────────────┐
│  Operator scripts (this design)                                          │
│  ┌─────────────────────────┐  ┌────────────────────────┐  ┌────────────┐  │
│  │  session_progress_real. │  │  mahavishnu-subagent-  │  │ mahavishnu-│  │
│  │  py  (EXTEND, user owns)│  │  status.py  (NEW)      │  │ activity-  │  │
│  │  → 3 bars + ecosystem   │  │  → JSON rows keyed by  │  │ stream.py  │  │
│  │    summary + event tail │  │    task.id             │  │ (NEW)      │  │
│  └─────────────────────────┘  └────────────────────────┘  └────────────┘  │
└──────────────────────────────────────────────────────────────────────────┘
                              ▲                ▲                    ▲
                              │                │                    │ reads queue
                              │                │                    ▼
┌─────────────────────────────┴────────────────┴────────────────────────────┐
│  Mahavishnu EventBridge (Redis Streams, channel `bodai:events`)             │
│  ─────────────────────────────────────────────────────────────────────     │
│  • workflow_started          • stage_completed           • completed       │
│  • worker.completed          • pool.scaled               • failed         │
│  • crackerjack.gate_raised   • dhara.stream.healthcheck  • akosha.index   │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Components

### Surface 1 — `statusLine` (extend `~/.claude/scripts/session_progress_real.py`)

**File:** `~/.claude/scripts/session_progress_real.py` (user's existing script, MODIFY in place)

Five lines rendered top-to-bottom:

1. **Context window** bar (already exists, keep as Line 2 of current script, move to Line 1 of new layout)
2. **5-hour rolling block** bar (already exists, keep as Line 1, move to Line 2)
3. **Weekly all-model cap** bar (NEW — third bar; source: MiniMax `model_remains` for MiniMax provider, ZAI/ZHIPU `limits` array for those providers, Anthropic's `/usage` JSONL aggregation for native)
4. **Ecosystem summary** (NEW — one line; OSC 8 clickable links to each component's MCP surface: `M` → `http://localhost:8680/mcp`, `P` → `http://localhost:8680/mcp`, `A` → `http://localhost:8682/mcp`, `D` → `http://localhost:8683/mcp`, `C` → `http://localhost:8676/mcp`, `S` → `http://localhost:8678/mcp`)
5. **Most-recent event** (NEW — tail of `~/.mahavishnu/last-event.json` written by `mahavishnu-activity-stream.py`; one line: timestamp, severity, message)

The script reads `COLUMNS` and `LINES` env vars (Claude Code 2.1.153+) and adapts:
- If `COLUMNS < 100`: drop the ecosystem summary, keep 4 lines
- If `COLUMNS < 80`: drop the event tail, keep 3 lines (bars only)
- If `LINES < 8`: emit only 2 lines (the existing two-bar behavior, fully backward-compatible)

The user's existing function `format_bar_line()` is reused as-is. Three new helpers are added:

```python
def format_ecosystem_summary(components: list[ComponentHealth]) -> str:
    """Emit one line with OSC 8 clickable glyphs + labels."""

def format_event_tail(event: dict | None) -> str:
    """Emit the most-recent Bodai event from ~/.mahavishnu/last-event.json."""

def format_weekly_cap(provider: Platform) -> str | None:
    """Render the third bar — provider-specific backend."""
```

**Source of data:**
- Three bars: existing backends (`calculate_block_usage`, `calculate_context_usage`, `MiniMaxBackend`, `GLMBackend`) + new `format_weekly_cap` for Anthropic
- Ecosystem summary: lightweight health probe to each component's MCP `/health` endpoint, cached 30s in `~/.mahavishnu/ecosystem-health-cache.json`
- Event tail: read `~/.mahavishnu/last-event.json` (written by `mahavishnu-activity-stream.py` on every EventBridge event)

### Surface 2 — `subagentStatusLine` (NEW)

**File:** `~/.claude/scripts/mahavishnu-subagent-status.py` (NEW)

Receives a JSON blob on stdin:
```json
{
  "session_id": "...",
  "tasks": [
    {"id": "w-01", "name": "scout", "type": "agent", "status": "completed",
     "startTime": "2026-07-15T07:40:00Z", "tokenCount": 12400, "cwd": "/path"},
    ...
  ]
}
```

Per Claude Code spec, output is **one JSON line per row**, keyed by task id:
```
{"id": "w-01", "content": "🟢 scout · akosha diffing · 12.4k tok · 00:41"}
{"id": "w-02", "content": "🟢 plan · crackerjack running · 08.1k tok · 00:28"}
{"id": "w-03", "content": "🟡 patch · waiting on session-buddy · 04.7k tok · 00:12"}
{"id": "w-04", "content": "🔵 verify · queued"}
{"id": "w-05", "content": "🔵 land · queued"}
```

The Python is small (~80 lines): iterate `tasks`, look up progress info from `~/.mahavishnu/worker-status/<task.id>.json` (written by `mahavishnu-activity-stream.py` for each worker event), format and emit one JSON row per task.

### Surface 3 — `mahavishnu-activity-stream.py` (NEW)

**File:** `~/.claude/hooks/mahavishnu-activity-stream.py` (NEW, registered as `PostToolUse` hook)

This is the **single bridge** between the Mahavishnu EventBridge and the two new surfaces (subagent rows + OSC 777 toasts). It runs as a Claude Code `PostToolUse` hook (so it fires after every tool call, draining any queued events) AND as a background subscriber (`xread` on the Redis Stream).

**Two responsibilities:**

1. **Update `~/.mahavishnu/last-event.json`** — atomic write of the most recent event (consumed by Surface 1's event tail).
2. **Update `~/.mahavishnu/worker-status/<task_id>.json`** — one file per active worker/subagent (consumed by Surface 2's row renderer).
3. **Emit OSC 777 toast for `stage_completed`, `completed`, `failed`, `pool.scaled`, `crackerjack.gate_raised`, `worker.completed`** — sequence:
   ```
   \033]777;notify;title=worker w-02 completed;body=refactor-auth stage=plan · 8.1k tokens · 28s\a
   ```
   Written to stderr (which Claude Code pipes back to the terminal in print mode but doesn't capture for the transcript, keeping toast output off the chat scroll).

The hook is registered in `~/.claude/settings.json` as:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {"type": "command", "command": "python3 ~/.claude/hooks/mahavishnu-activity-stream.py"}
        ]
      }
    ]
  }
}
```

## Data flow

End-to-end: a Mahavishnu worker completes a stage.

1. Worker process in `mahavishnu/workers/manager.py` finishes a stage.
2. Worker emits `stage_completed` event on EventBridge channel `bodai:events` (existing transport — no change).
3. `mahavishnu-activity-stream.py` (running as a background subscriber) consumes the event via `xread`.
4. The script:
   - Writes `~/.mahavishnu/last-event.json` (Surface 1 picks this up on next statusline render)
   - Writes `~/.mahavishnu/worker-status/w-NN.json` (Surface 2 picks this up on next subagent statusline render)
   - Emits OSC 777 toast to stderr (terminal renders as native notification)
5. On next statusline render (~few hundred ms later, triggered by user keystroke or tool completion):
   - Surface 1 reads `last-event.json` and shows it on line 5
   - Surface 2 reads `worker-status/*.json` and shows updated token counts and statuses

The minimum-change property holds: the EventBridge transport, the worker code, and the existing statusline script are unchanged in their responsibilities. We only add listeners.

## Error handling

| Failure | Detection | Behavior |
|---|---|---|
| EventBridge unreachable (Redis down) | `xread` raises `ConnectionError` in subscriber | Log structured fields (`subscribed`, `error`), back off 5s, retry. Statusline shows last cached state. No crash, no toast spam. |
| Component health endpoint timeout | `httpx.get(..., timeout=2s)` raises | Surface 1 ecosystem line omits that component's glyph and shows `?` instead. Cache for 30s to avoid retry storms. |
| OSC 777 emit on terminal that doesn't support it | Terminal ignores unknown OSC sequences | No-op (no error surfaced). Operators on iTerm2/WezTerm/Ghostty/Kitty see toasts; others don't. Feature is opportunistic. |
| `~/.mahavishnu/last-event.json` corrupted | `json.load()` raises | Fall back to "no recent events" line. Log a warning. |
| `subagentStatusLine` invoked when `~/.mahavishnu/worker-status/` missing | Directory doesn't exist | Emit zero rows (valid per Claude Code spec — empty task list is fine). |
| `session_progress_real.py` weekly-cap backend call hangs | Existing backends already have 15s timeouts | Same behavior — fall back to "weekly cap: unknown" line. |
| OSC 777 not supported in tmux/screen sessions | Some multiplexers strip unknown OSC | Detected at install time by a one-shot capability probe; if unsupported, the script logs a warning once and skips OSC emission (statusline + subagent still work). |

No silent fallbacks anywhere. A loud failure with a clear message is better than a silent degradation.

## File layout

| File | Status | Purpose |
|---|---|---|
| `~/.claude/scripts/session_progress_real.py` | EXTEND | Surface 1: 5-line statusline (3 bars + ecosystem + event tail) |
| `~/.claude/scripts/mahavishnu-subagent-status.py` | NEW | Surface 2: per-task JSON rows for subagent statusline |
| `~/.claude/hooks/mahavishnu-activity-stream.py` | NEW | Bridge: EventBridge → last-event.json + worker-status/*.json + OSC 777 |
| `~/.claude/settings.json` | MODIFY | Add `subagentStatusLine` config + `PostToolUse` hook for activity-stream |
| `~/.mahavishnu/last-event.json` | NEW (created at runtime) | Tail cache for Surface 1 |
| `~/.mahavishnu/worker-status/*.json` | NEW (created at runtime) | Per-worker cache for Surface 2 |
| `~/.mahavishnu/ecosystem-health-cache.json` | NEW (created at runtime) | 30s health probe cache for Surface 1's ecosystem line |
| `~/.mahavishnu/logs/mcp.log` | EXISTING | Existing structured log destination; activity-stream appends here too |

## Integration Contracts

Per `.claude/decisions/wire-up-contract.md`, every deliverable carries an Integration Contract. The three deliverables each get one.

### Deliverable 1: Surface 1 — `statusLine` extension

- **Triggered from**: Claude Code's statusline render cycle. The user's existing `~/.claude/settings.json` already has `"statusLine": {"type": "command", "command": "python3 ~/.claude/scripts/session_progress_real.py"}`. We modify the script only; the settings entry is unchanged.
- **Returns to / updates**: stdout (consumed by Claude Code TUI). Side-effect: writes `~/.mahavishnu/ecosystem-health-cache.json` (30s TTL cache).
- **Demonstrable by**: `CLAUDE_CONTEXT_WINDOW=500000 python3 ~/.claude/scripts/session_progress_real.py < /dev/stdin` (after seeding stdin with a sample session JSON). Asserts: stdout contains 5 lines on `COLUMNS >= 120`, 3 lines on `COLUMNS < 80`, and the ecosystem line contains OSC 8 escape sequences (`\x1b]8;;`).
- **Rollback signal**: If `~/.mahavishnu/ecosystem-health-cache.json` write fails 3x in a row, fall back to "Ecosystem: probing…" with no links. If the third-bar backend fails, drop that line (3-line fallback). The two existing bars always render — that contract is unchanged from the user's current setup.
- **Observability added**: Structured log line on each render to `~/.mahavishnu/logs/mcp.log` with fields `component=session_progress`, `provider=<platform>`, `bars_rendered=<int>`, `event_tail_age_seconds=<float>`. Failure paths emit `level=error` lines.

### Deliverable 2: Surface 2 — `subagentStatusLine` (NEW)

- **Triggered from**: Claude Code's subagent statusline render cycle. New entry in `~/.claude/settings.json`:
  ```json
  "subagentStatusLine": {"type": "command", "command": "python3 ~/.claude/scripts/mahavishnu-subagent-status.py"}
  ```
- **Returns to / updates**: stdout (consumed by Claude Code TUI). Side-effect: reads from `~/.mahavishnu/worker-status/*.json`. No writes.
- **Demonstrable by**: `echo '{"session_id":"s1","tasks":[{"id":"w-01","name":"scout","status":"completed","tokenCount":12400,"startTime":"2026-07-15T07:40:00Z"}]}' | python3 ~/.claude/scripts/mahavishnu-subagent-status.py`. Asserts: stdout is exactly one JSON line with `{"id": "w-01", "content": "🟢 scout · 12.4k tok · 00:00"}` (or similar). Empty task list → zero lines, exit 0.
- **Rollback signal**: If `worker-status/` doesn't exist or has no entries for the task ids in `tasks[]`, the script emits no rows (Claude Code handles missing rows gracefully). If a `worker-status/<id>.json` is corrupted (`json.load` raises), the row is omitted for that id and a warning is logged.
- **Observability added**: Structured log line per render: `component=subagent_status`, `tasks_total=<int>`, `tasks_with_status=<int>`, `render_ms=<float>`.

### Deliverable 3: Surface 3 — `mahavishnu-activity-stream.py` bridge (NEW)

- **Triggered from**: Two paths: (a) Claude Code `PostToolUse` hook (fires after every tool call — drains queue and writes last-event.json + worker-status/*.json); (b) a persistent background subscriber process (started at login or first Claude Code launch) that consumes the EventBridge via `xread` and emits OSC 777 toasts to stderr.
- **Returns to / updates**: Writes `~/.mahavishnu/last-event.json` (atomic), `~/.mahavishnu/worker-status/<task_id>.json` (atomic), and `~/.mahavishnu/logs/mcp.log` (appended). Emits OSC 777 to stderr.
- **Demonstrable by**: With EventBridge running and a test event published on `bodai:events` (e.g., via `redis-cli xadd bodai:events '*' type stage_completed workflow_id wf_1 stage plan task_id w-02`), within 2s: `cat ~/.mahavishnu/last-event.json` shows the event; `cat ~/.mahavishnu/worker-status/w-02.json` shows the task status update; OSC 777 sequence appears in stderr (verified by capturing stderr to file and `grep`ing for `\033]777;notify`).
- **Rollback signal**: If the EventBridge subscriber loses connection 3x in 60s, it backs off to 30s retry and logs `level=warning`. If `~/.mahavishnu/` is unwritable, the hook exits 0 (success — don't block Claude Code) and logs the failure to stderr. The user's chat is never blocked.
- **Observability added**: Structured log lines: `event_received`, `osc_emitted`, `last_event_written`, `worker_status_updated`. Each carries `event_type`, `task_id` (if applicable), `elapsed_ms`. Plus an OTel span `mahavishnu.event.consumed` with attributes `event.type` and `event.task_id`.

## Testing

Four test layers, in increasing fidelity:

### Layer 1: Unit tests — `tests/unit/scripts/test_session_progress_real.py` (MODIFY existing)

- Backward-compatibility: existing two-bar tests still pass (the new layout layers on top, doesn't replace).
- New: third-bar (weekly cap) renders for each `Platform` enum.
- New: ecosystem line contains OSC 8 escape sequences when `COLUMNS >= 120`.
- New: ecosystem line is omitted when `COLUMNS < 100`.
- New: event tail renders valid JSON; falls back to "no recent events" on missing/corrupt file.
- New: terminal width detection via `COLUMNS` env var overrides `shutil.get_terminal_size` (the existing width probe must defer to env).

### Layer 2: Unit tests — `tests/unit/scripts/test_mahavishnu_subagent_status.py` (NEW)

- Empty task list → zero stdout rows, exit 0.
- One task → one stdout row with correct format.
- Five tasks → five stdout rows, each keyed by task id.
- Corrupt `worker-status/<id>.json` → that id omitted, others emitted.
- Non-existent `worker-status/` dir → zero rows, exit 0.

### Layer 3: Integration tests — `tests/integration/hooks/test_activity_stream_bridge.py` (NEW, gated)

Gated by `MAHAVISHNU_EVENTBRIDGE_INTEGRATION=1`. Skipped in fast CI.

- Setup: local Redis with EventBridge channel seeded.
- Run: `python3 ~/.claude/hooks/mahavishnu-activity-stream.py` as a foreground process.
- Publish: a test `stage_completed` event via `redis-cli xadd`.
- Assert: within 2s, `~/.mahavishnu/last-event.json` reflects the event; `~/.mahavishnu/worker-status/w-test.json` is created; OSC 777 sequence appears on stderr.
- Teardown: kill subscriber, remove temp files.

### Layer 4: Manual smoke test (not in pytest)

- With Mahavishnu running (`mahavishnu mcp start`), open Claude Code in this repo.
- Verify: statusline shows 5 lines including the OSC 8-clickable ecosystem row.
- Verify: dispatch a worker via `mcp__mahavishnu__pool_route_execute` and confirm the workflow chain shows up as rows in the subagent statusline.
- Verify: trigger a workflow completion (`mahavishnu workflows trigger refactor-auth`) and confirm an OSC 777 toast appears in the terminal.
- Verify: `cat ~/.mahavishnu/last-event.json` and confirm recent events.

## Implementation order

1. **Add `~/.claude/scripts/mahavishnu-activity-stream.py`** (Deliverable 3) — pure new code, no integration with anything else. Subscribes to EventBridge, writes the two cache files, emits OSC 777. Independently testable.
2. **Extend `~/.claude/scripts/session_progress_real.py`** (Deliverable 1) — add `format_ecosystem_summary`, `format_event_tail`, `format_weekly_cap` helpers. Wire them into the main render loop with `COLUMNS`-aware adaptation. Backward-compatible: existing two-bar tests still pass.
3. **Add `~/.claude/scripts/mahavishnu-subagent-status.py`** (Deliverable 2) — pure new code, reads from `worker-status/*.json` and emits JSON rows. Independently testable.
4. **Modify `~/.claude/settings.json`** — register `subagentStatusLine` and the `PostToolUse` hook. One file, two new keys.
5. **Tests** — Layer 1 modifications, Layer 2 new, Layer 3 new gated.
6. **Manual smoke test** on a real machine with the full stack running.

Each step is independently mergeable. Steps 1, 2, 3 are independent scripts that can be developed and tested in parallel. Step 4 wires them into Claude Code. Steps 5–6 are quality gates.

## Open questions for the plan phase

- **Background subscriber lifecycle**: should `mahavishnu-activity-stream.py` be a `launchd`/`systemd` service, a tmux session, or a `PostToolUse`-only script that drains the queue on demand? Trade-offs: always-on gives instant toasts but consumes resources; on-demand drains on every tool call but might miss events between keystrokes. The plan phase will pick one based on operator workflow.
- **Multi-machine operators**: if the operator runs Claude Code on machine A but the Mahavishnu workers run on machine B (Session-Buddy pool), the EventBridge is on machine B. The subscriber needs to point at the right Redis. Plan phase will document the `MAHAVISHNU_EVENTBRIDGE_URL` env var override.
- **OSC 777 capability probe**: when is it run, and how does it communicate "unsupported" to the operator? Plan phase will add a `--probe` flag and a clear first-run banner.

## References

- `.claude/decisions/wire-up-contract.md` — Integration Contract policy
- `docs/plans/TEMPLATE.md` — implementation plan template (next phase)
- `docs/feature-tracking/TEMPLATE.md` — feature-state tracker (`built → wired → adopted`)
- `mahavishnu/websocket/server.py:559` — `broadcast_workflow_stage_completed`
- `mahavishnu/websocket/integration.py:227-321` — `stage_completed` event translation
- `~/.claude/scripts/session_progress_real.py` — existing two-bar statusline script
- `~/.claude/settings.json` — user's Claude Code settings
- `.superpowers/brainstorm/85729-1784161289/content/constellation.html` — v8 three-surface mockup (the visual companion render this spec implements)
- Claude Code statusline docs (Context7, retrieved 2026-07-15): multi-line output, ANSI/Unicode, OSC 8 hyperlinks, `COLUMNS`/`LINES` env vars (since 2.1.153)
- Claude Code `subagentStatusLine` spec (Context7, retrieved 2026-07-15): per-task JSON rows keyed by `task.id`

## Status

Approved 2026-07-15. Locked design is v8 (three-surface split) per the visual companion iteration. Ready for the writing-plans phase to produce the implementation plan.