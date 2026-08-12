---
status: complete
role: historical
topic: mcpretentious-removed
date: 2026-08-12
last_reviewed: 2026-08-12
superseded_by: null
blocks_on: []
---

# Mcpretentious Terminal Adapter Removed — Bootstrap Followup

**Status:** Resolved (2026-08-12). The mcpretentious terminal adapter and its
`BUILTIN_BACKENDS["mcpretentious"]` entry have been removed from the runtime
path. The default `adapter_preference` is now `tmux`, which routes through
the existing `DurableWorkerManager` (Spec §9.4). Crow remains available as an
opt-in via `adapter_preference: "crow"` + `crow_enabled: true`. No further
action is required from operators on stock installs.

## Root cause

The original [MHV-007] failure (`Failed to launch session: Timeout calling
MCP tool mcpretentious-open`) traced to a dead upstream dependency:

1. `settings/mahavishnu.yaml:191` shipped with `adapter_preference: "crow"`.
2. Stock installs with `crow_enabled: false` (the default) fell through to
   the mock adapter — a no-op that *appeared* healthy in `pool_health` but
   never actually launched a worker.
3. When an operator opted into the durable path by setting
   `adapter_preference: "mcpretentious"`, the factory at
   `mahavishnu/terminal/backends.py:31-36` spawned `npx mcpretentious`. The
   mcpretentious npm package has been removed from the ecosystem, so `npx`
   hung indefinitely trying to resolve the package, the
   `StdioMCPClient.call_tool("mcpretentious-open", ...)` call blocked until
   the asyncio timeout fired, and the failure surfaced as `[MHV-007]`.

The real fix is to remove the dead dependency from the runtime path entirely
and default to the already-wired tmux durable-worker contract.

## Architectural fix

The vishnu-side removal (Group A in the wave-3 plan) consists of:

- **A1.** `mahavishnu/terminal/backends.py:30-43` — remove the
  `"mcpretentious"` entry from `BUILTIN_BACKENDS`. Keep the `"tmux"` entry,
  the `PtyBackend` dataclass, and the `check_prerequisites` helper (the
  `"tmux"` entry's `requires=("tmux",)` is what surfaces a clear
  "install tmux" error when the operator lacks the binary).
- **A2.** `mahavishnu/terminal/manager.py:548-582` — delete the
  `if preference in BUILTIN_BACKENDS:` block, which constructed
  `McpretentiousAdapter(mcp_client, backend_name=preference)`. The block
  becomes unreachable once `BUILTIN_BACKENDS` only contains `"tmux"`,
  which is already handled at the prior branch. Drop the now-unused
  `BUILTIN_BACKENDS` import at `manager.py:13`.
- **A3.** `mahavishnu/terminal/manager.py:12` — drop the
  `from .adapters.mcpretentious import McpretentiousAdapter` import. Delete
  the file `mahavishnu/terminal/adapters/mcpretentious.py` entirely (no
  remaining consumer).
- **A4.** `settings/mahavishnu.yaml:191` — change
  `adapter_preference: "crow"` to `adapter_preference: "tmux"`. Add a YAML
  comment pointing at this followup.
- **A5.** This document.
- **A6.** `mahavishnu/terminal/__init__.py` — pre-flight confirmed the
  lazy-export registry does not re-export `McpretentiousAdapter`, so no
  re-export removal is needed.

## Why tmux

`TmuxTerminalAdapter` (`mahavishnu/terminal/adapters/tmux.py`) already
exists and is wired to the durable-worker contract at
`mahavishnu/workers/contract/manager.py` via
`DurableWorkerManager.spawn(worker_type=..., backend=..., command=...)`.
The contract test at
`tests/unit/mcp/tools/test_pool_route_execute_contract.py:62`
("routes shell type through durable") already passes against this path.
No remote package, no npx, no MCP subprocess — only the `tmux` binary,
which is the standard operator dependency and is already implied by the
prior `requires=("tmux",)` prerequisite check.

Crow remains available as an opt-in: operators set
`adapter_preference: "crow"` and `terminal.crow_enabled: true`. The mock
adapter remains the no-dependency default under `adapter_preference: "auto"`.

## Rollback path

If a future operator needs to bring back the mcpretentious entry:

1. `git log -S "mcpretentious" -- mahavishnu/terminal/backends.py` — find
   the commit that removed the entry.
2. Restore the deleted `mahavishnu/terminal/adapters/mcpretentious.py`
   file from the same commit (`git show <sha>^:mahavishnu/terminal/adapters/mcpretentious.py`).
3. Re-add the `from .adapters.mcpretentious import McpretentiousAdapter`
   import and the `if preference in BUILTIN_BACKENDS:` block in
   `manager.py` (refer to the same commit for the exact text).
4. Revert `settings/mahavishnu.yaml` to `adapter_preference: "crow"`
   (or to `"mcpretentious"` if the operator's intent is to route through
   the npm package).

The deletion is permanent per the user's earlier direction; this rollback
path is documented only for completeness.

## Observability

The tmux durable-worker contract already publishes `worker.spawned` and
`worker.status_changed` events; the existing Mahavishnu WebSocket broadcast
surfaces them on port 8690. No new metrics required.

## References

- `mahavishnu/terminal/backends.py` — `BUILTIN_BACKENDS` registry
- `mahavishnu/terminal/manager.py` — `TerminalManager.create` factory
- `mahavishnu/terminal/adapters/tmux.py` — `TmuxTerminalAdapter` (active)
- `mahavishnu/workers/contract/manager.py` — `DurableWorkerManager` (active)
- `settings/mahavishnu.yaml:191` — `adapter_preference` default
- `tests/unit/mcp/tools/test_pool_route_execute_contract.py:62` — durable
  path contract test (verification)
