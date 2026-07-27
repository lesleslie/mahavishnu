# Durable Local Workers — Design Spec

- **Status:** draft (awaiting user review)
- **Date:** 2026-07-26
- **Author:** Mahavishnu design session
- **Scope:** local Mahavishnu pools only. Session-Buddy and cloud-pool extensions are captured in §11 and §12 as deferred design sections.

## 1. Problem

Claude Code's use of Mahavishnu workers is currently limited by five adoption
bottlenecks:

1. `worker_execute` truncates output to 500 characters; `worker_execute_batch`
   truncates to 200. Long refactors come back clipped.
1. `dispatch_to_pool(async_callback=True)` returns a `workflow_id` but Claude
   Code has no first-class tool to retrieve the result.
1. Synchronous pool calls block the MCP request for the full `timeout` window.
1. Raw `terminal_launch` / `terminal_send` is fire-and-forget with no
   completion state.
1. The interactive `terminal-claude` worker relies on platform-dependent
   completion markers that often do not match the actual stream-JSON output.

The current iTerm2-windowed worker transport also produces an opaque window
per spawn that Claude Code cannot drive from the same terminal. tmux was
identified as a better substrate because tmux is a client/server system; a
controller can create, target, and read panes from outside any client.

## 2. Goal

Make orchestrated local workers:

- durable across Mahavishnu controller restarts;
- reachable from the same terminal context as Claude Code, without
  requiring Claude Code to run inside tmux;
- observable to the Claude Code statusline and Constellation dashboard
  through canonical events;
- reattachable by a human operator;
- not coupled to a specific terminal emulator (iTerm2, Ghostty, WezTerm,
  SSH, headless CI).

## 3. Non-goals

- Removing iTerm2 immediately. iTerm2 stays available as a deprecated,
  opt-in macOS desktop adapter.
- Cross-host Session-Buddy and RunPod/cloud worker support. The deferred
  extensions in §11 and §12 record the direction; they are out of scope
  for this design's implementation plan.
- Streaming push to Claude Code. v1 uses polling at 250–500 ms.
- Streaming subscription to tmux output via control mode. v1 uses
  `capture-pane -p -S -<offset>`.
- Replacing the existing `WorkerConfig` and `WorkerManager` machinery. This
  design extends them.

## 4. Transport decision

- **Default local worker transport:** tmux.
- **Secondary candidate (not yet implemented):** Zellij, behind a feature
  flag and a version pin.
- **iTerm2:** retained as an explicit macOS desktop adapter, deprecated.
- **WezTerm, mprocs, shpool, abduco, dtach, GNU Screen, Byobu:** not used
  as worker transport. (See §10 for the evaluation rationale.)

tmux is preferred because:

- it is a client/server system; the controller can address panes from
  outside any client;
- private sockets (`tmux -L` / `tmux -S`) provide clean isolation;
- it works headlessly on macOS and Linux;
- the command surface is stable, documented, and scriptable;
- it does not bind Mahavishnu to any particular terminal emulator.

## 5. Stable identities

Each local worker carries separate identities for separate concerns:

| Field | Lifetime | Purpose |
|---|---|---|
| `worker_id` | persistent | Mahavishnu logical worker identity |
| `task_id` | per execution | One execution on a worker |
| `tmux_socket` | persistent or per-run | Path of the tmux server socket |
| `tmux_session` | persistent or per-run | tmux session name |
| `tmux_window` | persistent or per-run | tmux window name/index |
| `tmux_pane` | recoverable | tmux pane id (e.g. `%7`); updated on reattach |
| `claude_session` | per task | Claude Code / Agent SDK session id, when available |
| `workflow_id` | per execution | Oneiric canonical `correlation_id` for the run |

The crucial rule: `worker_id` survives Mahavishnu restarts. `tmux_pane` is
transport metadata and may change after reattachment or pane recreation.
On pane death, the controller either reattaches the same pane or creates
a sibling pane in the same session/window; the record's `tmux_pane` is
updated and a `worker.status_changed` event is emitted so the dashboard
and operators see the new pane id.

**v1 constraint:** one logical worker per tmux pane. Concurrent tasks do
not share a pane.

## 6. Worker state machine

```
pending
  worker record created, no tmux pane yet

starting
  tmux server and pane creation in progress

ready
  pane exists, command launched, capability report AVAILABLE,
  no task running, accepting a new task

running
  task actively executing in the pane; output buffer active

detached
  pane is alive, but the controller's stream to it is unavailable
  (tmux socket file missing, MCP transport down, controller restart)

draining
  cancellation in progress, soft signal sent, grace window open

completed
  task finished successfully, pane still alive

failed
  task finished with an error, pane still alive

reaped
  pane confirmed dead, local record reconciled, EventBridge notified

degraded
  pane exists but capability report is no longer AVAILABLE;
  recovery may require operator intervention
```

Transitions are validated, idempotent, and recoverable. Restarting the
controller does not reset state; it only reattaches the stream and
reconciles the pane's actual status.

This complements rather than replaces the existing
`WorkerCapabilityState` (REGISTERED / CONFIGURED / READY / AVAILABLE) from
the worker-readiness plan. Capability answers "can this worker type be
used?" Lifecycle answers "what is this particular worker doing?"

## 7. Worker contract

### 7.1 Launch

```json
launch_worker(
  prompt: str,
  *,
  worker_id: str | None = None,         // auto-generated if omitted
  worker_type: str = "terminal-claude",
  backend: "claude_tui" | "claude_print" | "agent_sdk" = "claude_tui",
  pty: bool = True,
  session_mode: "current_tmux" | "managed_tmux" | "no_tmux" = "managed_tmux",
  max_wait_ms: int = 30_000,
  model: str | None = None,             // override only when explicit
  metadata: dict = {}
) -> {
  worker_id: str,
  status: "starting" | "ready" | "exited",
  tmux?: {
    socket: str,
    session: str,
    window: str,
    pane: str,                          // raw tmux pane id (e.g. "%7")
    attach_command: str
  },
  claude_session?: str,
  exit_code?: int
}
```

Launch is bounded-sync: returns when the worker reaches `ready` or `exited`,
or after `max_wait_ms`. Callers who want fire-and-forget pass
`max_wait_ms=0` and immediately poll `worker_status`.

`session_mode` is evaluated as:

```
if TMUX is set and session_mode == "current_tmux":
    reuse the current tmux session; create a sibling worker pane/window
else if session_mode == "managed_tmux":
    create a private Mahavishnu-owned tmux server/session
    with socket under ~/.mahavishnu/tmux/<worker_id>.sock
else:  // no_tmux
    fall back to the existing PTY/backend path
```

### 7.2 Send input

```json
send_input(
  worker_id: str,
  input: str,
  *,
  submit: bool = True,
  timeout_ms: int = 5_000
) -> { accepted: bool, byte_offset: int }
```

For interactive backends. No-op with `accepted: true` if the worker is in
a state that cannot accept input.

### 7.3 Capture output

```json
capture_output(
  worker_id: str,
  *,
  since_offset: int = 0,
  max_bytes: int = 65_536,
  strip_ansi: bool = True
) -> {
  worker_id: str,
  text: str,
  next_offset: int,
  truncated: bool,
  pane_alive: bool
}
```

Byte-offset pagination, not line-based. Survives tmux's `-S -<offset>`
semantics and ANSI-heavy streams. `since_offset` is an inclusive
read cursor; the response carries the new cursor.

### 7.4 Status

```json
worker_status(worker_id) -> {
  worker_id: str,
  state: "pending" | "starting" | "ready" | "running" | "detached"
        | "draining" | "completed" | "failed" | "reaped" | "degraded",
  exit_code?: int,
  uptime_seconds: int,
  last_activity_iso: str,
  pane_command: str,                // raw #{pane_current_command}
  tmux?: {...},                     // see §7.1
  claude_session?: str,
  error?: { code: str, message: str }
}
```

### 7.5 Wait

```json
wait_for_state(
  worker_id: str,
  until_state: "ready" | "exited" | "completed" | "failed" | "reaped",
  timeout_ms: int,
  poll_interval_ms: int = 250
) -> { state: ..., elapsed_ms: int, output_during_wait?: str }
```

### 7.6 Cancel

```json
cancel_worker(
  worker_id: str,
  *,
  signal: "soft" | "SIGTERM" | "SIGKILL" = "soft",
  grace_ms: int = 5_000
) -> { killed: bool, exit_code?: int }
```

Two-phase: `soft` sends `\x03` (SIGINT equivalent in Claude Code TUI) then
waits `grace_ms`, then `SIGTERM`, then `SIGKILL`. Idempotent.

### 7.7 Workflow-result retrieval

```json
workflow_result(workflow_id) -> {
  workflow_id: str,
  status: "queued" | "running" | "completed" | "failed" | "rate_limited"
         | "result_write_failed",
  result?: dict,                     // WorkerResult.to_dict()
  error?: str,
  rate_limited: bool,
  retry_after_seconds?: int
}
```

This is the missing retrieval half for `dispatch_to_pool(async_callback=True)`.
Without it, Claude Code has no first-class path to a queued async result.

## 8. Failure handling

### 8.1 Startup reconciliation

On Mahavishnu startup:

1. Load durable worker records from `~/.mahavishnu/worker-sessions/`.
1. For each record, derive the actual tmux target and try to reach it
   through its recorded socket.
1. Classify:
   - `reaped` if the tmux server or pane is gone,
   - `detached` if the server is reachable but the pane is not owned by
     this controller,
   - `ready` / `completed` / `failed` / `degraded` if the pane is alive
     and reachable.
1. Emit one canonical `worker.status_changed` event per record.
1. Persist a `worker-status/<worker_id>.json` snapshot for the dashboard.
1. Open the EventBridge consumer from the persisted cursor if available;
   otherwise start at the current stream position.

### 8.2 Controller disconnect

`detached` is a first-class state, not a failure. Tasks are paused, not
lost. Reconnect resumes state from the durable record plus the new tmux
capture, with output continuation via the offset cursor.

### 8.3 tmux/pane death

If the tmux server or pane disappears:

1. The next poll reclassifies the record as `reaped`.
1. The last captured output is retained until the user explicitly closes
   the record, with a clear `reaped` label.
1. A `worker.status_changed` event is emitted.
1. A new worker can be spawned by re-issuing a launch; the record can be
   archived or deleted.

### 8.4 Cancellation

1. The controller sends a soft signal (`\x03` for CLI tools or a defined
   marker for SDKs).
1. The grace period starts (default 5 seconds).
1. If the worker has not exited, the controller escalates to `SIGTERM` on
   the tmux pane, then `SIGKILL` after another grace period.
1. Final state is `reaped` with the last exit code or `killed` reason
   recorded.
1. The local record is reconciled; the dashboard is notified.

A second `cancel_worker` call observes the existing `draining` or terminal
state and does not start a new cancellation sequence.

### 8.5 Shutdown and restart

Graceful shutdown:

1. Mark all in-flight workers as `detached` in the local record.
1. Emit `worker.status_changed` events.
1. Do not kill panes; they may belong to the operator.

Restart:

1. Reload the durable records.
1. Resume the EventBridge consumer from the persisted cursor.
1. Reattach to the panes that are still alive.

This is the core difference from a per-call worker: workers outlive the
controller.

## 9. Security

- Private tmux sockets live in `~/.mahavishnu/tmux/` with `0600`
  permissions on the directory and socket files.
- Mahavishnu-owned sockets are isolated from the user's default tmux
  server.
- Worker commands are quoted; prompts are passed through `shlex.quote`.
- The attach command is constructed in code, never concatenated from
  user input.
- Output capture is truncated to a per-poll maximum (`max_bytes`) to
  prevent memory blowup; consumers request pagination via offset.
- Pane snapshots are not embedded in event envelopes; the bridge writes
  the snapshot to a separate file referenced by the envelope.
- Operators can revoke access to any worker via `worker_revoke(worker_id)`,
  which removes the local record, marks the pane as `reaped`, and does
  not attempt to kill the underlying process unless `force=true`.
- The worker contract is consumed only by authenticated MCP clients;
  the `attach_command` is a convenience for a local human operator and
  is not auto-executed by Mahavishnu.

## 10. Existing MCP surface: retain and repair

| Tool | Status | Change |
|---|---|---|
| `worker_spawn` | retain | Use the new contract under the hood; keep tool description stable |
| `worker_execute` | retain | Return the full structured result, not 500-char truncated text; add explicit cursor/reference when truncated |
| `worker_execute_batch` | retain | Same fix; raise truncation cap or remove it |
| `worker_list` | retain | Filter by `worker_id` and state |
| `worker_monitor` | retain | Return authoritative state, not only snapshots |
| `worker_collect_results` | retain | Support incremental output with offset |
| `worker_close` | retain | Two-phase graceful shutdown |
| `worker_close_all` | retain | Same |
| `worker_health` | retain | Aggregate state from local records |
| `pool_route_execute` | retain | Use the new contract for shell workers |
| `dispatch_to_pool` | retain | Same; downstream `workflow_result` closes the async loop |

`worker_execute` repair is the highest-priority change: it removes the
primary reason Claude Code avoids the worker tool.

## 11. Deferred extension: Session-Buddy and cross-host workers

This section is deferred. The design is the same worker/session record
shape, with these adaptations:

- `tmux_socket` is a remote tmux endpoint over SSH, or a Mahavishnu-owned
  tmux server on the Session-Buddy host.
- The controller uses a remote tmux shell or a relay protocol over MCP.
- Status polling becomes a remote MCP call; output pagination is still
  byte-offset based.
- Each Session-Buddy instance owns exactly three workers (current
  model); one pane per worker remains the v1 rule.
- The EventBridge consumer must tolerate cross-host envelope routing
  and Redis Streams replication.

Open questions for the Session-Buddy extension:

- Do we need a Mahavishnu-controlled SSH bastion, or do we use the host's
  existing tmux server?
- Should the relay be Mahavishnu-native or built on `mosquitto`-style
  pubsub?
- How does recovery work when the Session-Buddy host restarts?

These do not block the local design.

## 12. Deferred extension: cloud pools (RunPod / OpenHands / A2A)

Cloud pools are serverless or remote-agent systems. The durable-worker
contract is reusable in shape, but the transport metadata changes:

- `tmux_socket`, `tmux_session`, `tmux_window`, `tmux_pane` are absent.
  Cloud workers use container or job IDs as transport metadata.
- The state machine is identical.
- The recovery path is host-driven (RunPod Flash API, OpenHands REST,
  A2A SSE) rather than tmux-driven.
- `capture_output` is replaced by the worker's structured event stream
  (RunPod logs, OpenHands `/acp/status/{conv_id}`, A2A SSE).

Open questions:

- Should the cloud path reuse `capture_output` as an abstract
  `stream_output`, or expose a separate `cloud_output`?
- How does the dashboard render cloud workers with the same state
  machine but different transport metadata?
- Should `claude_session` be carried into cloud workers, or stay
  local-only?

## 13. Out of scope

- A `terminal-tmux` worker type. The new design uses the existing
  `WorkerConfig` and `WorkerManager` machinery; transport is a property
  of the runtime, not a new worker kind.
- A new `WorkerResult` shape. The new contract is an additive MCP
  surface; `WorkerResult.to_dict()` continues to be the wire format.
- Streaming push to Claude Code. v1 polls.
- A Constellation plan rewrite. The new design emits canonical events;
  the bridge consumes them; the dashboard renders them. The Constellation
  plan/spec should be patched in a follow-up to fix its `task_id` keys
  and frozen allowlist, but that is out of scope for this design's
  implementation plan.
- ~~Removing iTerm2. Demoted, not removed.~~ **Updated 2026-07-27**:
  iTerm2 is removed in this plan (per user direction — the cautious
  Phase C / Phase C.1 split is collapsed into one). See §15 for the
  updated rollout.

## 14. Success criteria

- `worker_execute` returns the full structured result for a 100 KB
  refactor without silent truncation.
- `workflow_result(workflow_id)` resolves ≥80% of `dispatch_to_pool`
  async workflows without operator intervention.
- Pool tool-call share (`pool_route_execute` and the new contract tools
  vs. `terminal_launch`) reaches ≥45% on Claude Code sessions that opt in
  to the new contract.
- Workers survive a Mahavishnu controller restart with no operator
  intervention; the controller reattaches within 5 seconds.
- tmux-attached operator action is logged (`tmux attach -t mahavishnu-*`); at least one such attach per active power user per
  week.
- Crackerjack quality score remains ≥75 after the rollout.

## 15. Rollout

1. **Phase A — contract repair.** Fix `worker_execute` truncation, add
   `workflow_result`, fix `terminal-claude` completion detection, add
   `worker_status`, `worker_wait`, `worker_output`, `worker_cancel`.
   Ship behind a feature flag; legacy path remains default.
1. **Phase B — tmux as default local transport.** Add a direct
   `TmuxTerminalAdapter`, use private sockets, reuse the current tmux
   session when `TMUX` is present, otherwise create a managed session.
   Keep iTerm2 available via explicit configuration.
1. **Phase C — deprecate AND remove iTerm2 (collapsed).** Add
   `DeprecationWarning` + `MockTerminalAdapter` fallback for
   `adapter_preference="iterm2"`; then immediately delete the iTerm2
   adapter module, the iTerm2-only test files, the `pyproject.toml`
   `iterm2` extra, and the `mahavishnu/terminal/pool.py` module if
   its only purpose was iTerm2. Refactor the terminal grid manager to
   depend on a generic `TerminalAdapter` (the existing ABC) so it
   compiles after the iTerm2 class is gone. **Updated 2026-07-27**
   per user direction ("ok, can we just go ahead and remove the
   iterm2 worker too from this plan?"); Phase C.1 (the previously
   planned future breaking release) is folded into Phase C.
1. **Phase D — extension to Session-Buddy and cloud.** See §11 and §12.

## 16. Open questions for the user before implementation

1. Default `backend` for `launch_worker` — `claude_tui` (PTY + Claude
   Code TUI) or `claude_print` (PTY + `--print`)? Suggest
   `claude_tui` default, override per-call.
1. Confirm that 500-character `worker_execute` output truncation can be
   removed outright in Phase A, or whether some operators rely on it
   being a short summary.
1. Confirm the `~/.mahavishnu/tmux/` private-socket directory layout.
1. Confirm that we may add `worker_revoke` and that it is allowed to
   leave the underlying process running unless `force=true`.

## 17. References

- tmux manual: https://man.openbsd.org/tmux
- tmux control mode: https://github.com/tmux/tmux/wiki/Control-Mode
- tmux on Homebrew: https://formulae.brew.sh/formula/tmux
- Zellij project: https://github.com/zellij-org/zellij
- Zellij programmatic control: https://zellij.dev/documentation/programmatic-control.html
- WezTerm multiplexing: https://wezterm.org/multiplexing.html
- iTerm2 tmux integration: https://iterm2.com/documentation-tmux-integration.html
- iTerm2 Python API: https://iterm2.com/python-api
- Constellation design spec: `docs/superpowers/specs/2026-07-15-constellation-tui-design.md`
- Constellation implementation plan: `docs/superpowers/plans/2026-07-15-constellation-tui.md`
- Oneiric canonical event envelope: `mahavishnu/core/events/canonical.py`
- Worker readiness observability: `mahavishnu/workers/capabilities/_observability.py`
- Worker manager execution path: `mahavishnu/workers/manager.py`
- Pool route and async dispatch: `mahavishnu/pools/manager.py`,
  `mahavishnu/mcp/tools/pool_tools.py`
- Multi-backend PTY design: `docs/superpowers/specs/2026-07-14-multi-backend-pty-design.md`
- Worker-readiness design: `docs/superpowers/specs/2026-07-21-worker-readiness-design.md`
- Unified iTerm2 AppleScript design (legacy): `docs/superpowers/specs/2026-05-23-unified-iterm2-applescript-design.md`
- Terminal grid design: `docs/superpowers/specs/2026-05-22-terminal-grid-design.md`
