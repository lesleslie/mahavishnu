---
status: active
role: canonical
date: 2026-11-15
last_reviewed: 2026-11-15
superseded_by: null
topic: dispatch-liveness
title: "A long MCP dispatch stays alive by reporting progress, not by raising the timeout"
---

# A long MCP dispatch stays alive by reporting progress, not by raising the timeout

## Context

Claude Code's MCP client has **three** separate timers, and they behave
differently. Confusing them is what makes the obvious fix the wrong one.

| Timer | Reset by progress? | Default | Governs |
|---|---|---|---|
| **idle** | **yes** | `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`, else 300 s for HTTP / 1800 s for stdio | aborts a call that produces neither a response nor a progress notification |
| **wall clock** | no | `MCP_TOOL_TIMEOUT`, else `1e8` ms (~28 h) | hard cap on the whole call |
| startup | no | separate | server connect |

The idle timer is the one that kills healthy work. A pool dispatch can
legitimately run for minutes with nothing to say — a multi-file refactor
sits in a worker while the client waits — and the client aborts the call at
the idle window even though the server is working perfectly. That is exactly
what happened to the pyscn complexity refactor: the dispatch died at 600 s
with the work stranded in the worker.

The decisive detail is the per-server `.mcp.json` `timeout`. It feeds **both**
timers:

```
wall = perServerTimeout ?? MCP_TOOL_TIMEOUT ?? 1e8
idle = min(max(CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT, perServerTimeout, 1000), wall)
```

So a per-server timeout **collapses idle and wall into one value**. Setting
one would have "fixed" the abort by removing the idle window — and removed
the ability to distinguish a slow call from a wedged one. It also would
have made progress reporting pointless: with `idle == wall`, a call that
outlives the idle window outlives the wall clock too, and the client aborts
either way.

The client sends `_meta.progressToken` on every MCP tool call, and passes
`resetTimeoutOnProgress: true` with a no-op `onprogress` callback. The
callback's presence is what makes the bundled MCP SDK client attach the
token; the server's `notifications/progress` responses then reset the idle
clock. The wall clock is not affected, so a wedged dispatch still dies at the
cap.

## Decision rule

**A long-running MCP tool reports liveness while it works. The idle timer is
reset by progress; the wall clock is not.** Never raise a timeout to work
around an idle abort — fix the idleness.

## What this means in this repo

`mahavishnu_pool_route_execute` takes FastMCP's injected `Context` and runs a
20-second heartbeat for the duration of the dispatch. The parameter is
excluded from the tool schema, so the wire contract is unchanged and the
checked-in surface snapshot stays byte-identical.

Two traps are load-bearing and easy to undo by accident:

1. **`Context` must be imported at runtime**, not under `TYPE_CHECKING`.
   FastMCP resolves the injected parameter with `get_type_hints(fn)`; under
   `from __future__ import annotations` that evaluates the annotation string
   against the module globals. A TYPE_CHECKING-only import leaves the name
   absent, `get_type_hints` raises `NameError`, FastMCP falls back to the
   raw string annotation, and the context is never injected — silently, with
   no error anywhere. The feature would pass every direct-call test and
   never fire in production.

2. **The heartbeat's interval must resolve at call time**, not as a default
   argument, so the module constant stays the single source of truth and a
   test can shorten it.

Progress reporting is advisory. A broken progress channel must never turn a
successful dispatch into a failed one.

## Status

Active — implemented 2026-11-15 (`020798b5`, plus the e2e test and plan in
`docs/plans/2026-11-15-pool-dispatch-progress-heartbeat.md`). Covered by
`tests/unit/test_mcp/test_pool_route_progress.py` and
`tests/integration/test_pool_route_progress_e2e.py`.

**Not applied, deliberately:** no per-server `timeout` was added to
`.mcp.json`, and the global `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT` is unchanged.
