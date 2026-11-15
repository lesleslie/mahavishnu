---
status: complete
role: implementation
kind: plan
date: 2026-11-15
last_reviewed: 2026-11-15
superseded_by: null
topic: mcp-dispatch-liveness
title: "Report pool dispatch liveness so long calls survive the client idle timeout"
requirements:
  - id: REQ-DSPROG-001
    title: "Pool dispatch emits progress notifications while in flight"
  - id: REQ-DSPROG-002
    title: "The injected context stays out of the MCP tool schema"
  - id: REQ-DSPROG-003
    title: "A dispatch without a client progress token runs unchanged"
---

# Report pool dispatch liveness so long calls survive the client idle timeout

## 1. Outcome

A pool dispatch that runs longer than the MCP client's idle window no longer
dies at that window. `mahavishnu_pool_route_execute` reports liveness while
the dispatch is in flight, and the client's idle timer is reset by those
reports.

Success signal: a dispatch that takes longer than
`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` completes, and the client observes
`notifications/progress` frames during the call.

## 2. Goals

1. Keep the client's idle timer alive across a long, healthy dispatch.
2. Leave the wire contract untouched — the injected context must not appear
   in the tool schema.
3. Leave every other dispatch path byte-identical in behaviour.

## 3. Non-Goals

1. Extending the client's wall-clock cap. Progress deliberately does not
   touch it; a wedged dispatch still dies at the cap.
2. Changing `.mcp.json` or any client-side timeout setting. A per-server
   `timeout` collapses the idle timer and the wall clock into one value
   (`Math.min(Math.max(idle, perServer), wall)`), which would make progress
   reporting pointless.
3. Progress for any tool other than `mahavishnu_pool_route_execute`.

## 4. Current Findings

- The client aborts a tool call that produces neither a response nor a
  progress notification for its idle window. Claude Code 2.1.325 passes
  `resetTimeoutOnProgress: true` and a no-op `onprogress` callback on MCP
  tool calls; the presence of that callback is what makes the bundled MCP
  client attach `_meta.progressToken` to the request.
- The idle timer is `Math.min(Math.max(CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT,
  perServerTimeout, 1000), wallClockTimeout)`. With no per-server timeout
  and this repo's global `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT = 600000`, the
  idle window is **10 minutes** while the wall clock defaults to `1e8` ms
  (~28 hours). The idle timer was the binding constraint, not the wall
  clock.
- The concrete failure: the pyscn complexity refactor dispatched through
  `pool_route_execute` and was killed at 600 s with the work stranded in the
  worker.
- FastMCP resolves the injected-context parameter with `get_type_hints(fn)`
  and falls back to the raw string annotation if that raises. Under
  `from __future__ import annotations` the annotation is a string, so a
  TYPE_CHECKING-only import of `Context` would make injection fail
  *silently* — no error anywhere, and no heartbeat.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-DSPROG-001
    title: "Pool dispatch emits progress notifications while in flight"
  - id: REQ-DSPROG-002
    title: "The injected context stays out of the MCP tool schema"
  - id: REQ-DSPROG-003
    title: "A dispatch without a client progress token runs unchanged"
```

## 5. Implementation Phases

### Phase 1: The heartbeat

**Goal:** report liveness for the duration of a dispatch.

**Tasks:** add the runtime `Context` import; add `ctx: Context | None = None`
to `mahavishnu_pool_route_execute`; add `_dispatch_with_progress`; route the
dispatch through it.

**Exit criteria:** a real MCP client observes progress notifications during a
slow dispatch, and the dispatch result is returned unchanged.

#### Integration Contract

- **Triggered from**: `mcp__mahavishnu__mahavishnu_pool_route_execute` →
  `register_pool_tools` → `mahavishnu_pool_route_execute` in
  `mahavishnu/mcp/tools/pool_tools.py`.
- **Returns to / updates**: the client receives `notifications/progress`
  frames carrying the elapsed-seconds counter; the dispatch result dict is
  returned to the caller unchanged. No persistent state is written.
- **Demonstrable by**:
  `pytest tests/integration/test_pool_route_progress_e2e.py -k reports_progress`.
- **Rollback signal**: a dispatch that ends with `status="failed"` and no
  progress frames after the first heartbeat tick — the client-side heartbeat
  would keep firing while the server's own report path is broken.
- **Observability added**: the progress message text itself —
  `"pool dispatch in progress (Ns elapsed)"` — plus the debug line
  `"dispatch progress report failed"` when the progress channel breaks.

### Phase 2: Contract and regression safety

**Goal:** prove the wire contract and the non-progress paths are unchanged.

**Tasks:** assert the schema excludes `ctx`; assert a dispatch with no
context runs untouched; assert the heartbeat is cancelled on success and on
failure; assert a broken progress channel cannot fail a dispatch.

**Exit criteria:** the live server's `tools/list` signature for
`mahavishnu_pool_route_execute` matches the checked-in surface snapshot byte
for byte.

#### Integration Contract

- **Triggered from**: `scripts/check_mcp_tool_surface.py` and
  `tests/unit/test_mcp_tool_surface.py`, which compare the live tool surface
  against `tests/fixtures/mcp_surface/tools_list.json`.
- **Returns to / updates**: the checked-in surface snapshot
  (`tests/fixtures/mcp_surface/tools_list.json`) — unchanged by this work, and
  that is the point.
- **Demonstrable by**: `pytest tests/unit/test_mcp/test_pool_route_progress.py
  tests/integration/test_pool_route_progress_e2e.py`.
- **Rollback signal**: a signature-drift finding from
  `scripts/check_mcp_tool_surface.py` naming
  `mahavishnu_pool_route_execute`.
- **Observability added**: the surface checker's own signature-drift finding.

## 6. Required Code Changes

- [x] `mahavishnu/mcp/tools/pool_tools.py` — runtime `Context` import,
      `_ProgressReporter` protocol, `_dispatch_with_progress` heartbeat,
      `ctx` parameter on `mahavishnu_pool_route_execute`.
- [x] `tests/unit/test_mcp/test_pool_route_progress.py` — heartbeat unit
      tests and the schema assertion.
- [x] `tests/integration/test_pool_route_progress_e2e.py` — end-to-end
      delivery through a real FastMCP client.
- [x] `tests/unit/test_mcp/test_pool_tools.py` — drop the stale
      `mahavishnu_budget_enforce` expectation (that tool moved to
      `budget_tools`) and fix a pre-existing unsorted import block.

## 7. Validation Matrix

| tool/command | expected outcome | evidence location |
|---|---|---|
| `pytest tests/unit/test_mcp/test_pool_route_progress.py` | 7 passed | test output |
| `pytest tests/integration/test_pool_route_progress_e2e.py` | 2 passed | test output |
| `pytest tests/unit/test_mcp/test_pool_tools.py` | 20 passed | test output |
| `ruff check` on changed files | clean | gate output |
| `ty check` on changed files | clean | gate output |
| `pyscn` on `pool_tools.py` | 0 functions over complexity 15 | `.pyscn/reports/` |
| live `tools/list` signature | byte-identical to the checked-in snapshot | probe output |
| live `tools/list` description | contains the new "Liveness:" paragraph | probe output |

## 8. Risks

| risk | likelihood | mitigation |
|---|---|---|
| `Context` imported under `TYPE_CHECKING` → injection fails silently | medium | the import is runtime, with a comment explaining exactly why; the e2e test fails loudly if it regresses |
| The heartbeat task leaks past the dispatch | low | `finally` cancels it and awaits the cancellation; two unit tests assert the task count returns to baseline |
| A broken progress channel fails a good dispatch | low | the report is wrapped; a failing report is logged at debug and swallowed |
| The heartbeat keeps a wedged dispatch alive forever | low | progress does not extend the wall-clock cap, so the cap still ends the call |
| The schema gains a `ctx` property | low | `ctx` is excluded by FastMCP; asserted in a unit test and against the live server |

## 9. Decision Rule

This work is done when a real MCP client observes progress notifications
during a dispatch that outlives the client's idle window, the tool schema is
unchanged, and every pre-existing dispatch path behaves identically. It is
**not** done on the strength of the unit tests alone: the e2e test through a
real FastMCP client is the gate.
