# Multi-Backend PTY Toolservers for Mahavishnu

**Status:** Approved (design phase complete, awaiting plan)
**Date:** 2026-07-14
**Scope:** Mahavishnu terminal adapter system (`mahavishnu/terminal/`)

## Context

Mahavishnu's `McpretentiousAdapter` (`mahavishnu/terminal/adapters/mcpretentious.py`) hardcodes a launch command in `mahavishnu/terminal/mcp_client.py:248`:

```python
self._client = StdioMCPClient("uvx", ["--from", "mcpretentious", "mcpretentious"])
```

This command is broken. MCPretentious is an **npm** package (`https://github.com/oetiker/MCPretentious`), not a PyPI package, so `uvx` cannot resolve it. Every tool call against a mcpretentious adapter times out at 30s with no useful diagnostic. The adapter is effectively dead code.

The terminal adapter system is also currently single-backend. `terminal/config.py:50` exposes `adapter_preference: str` as a free-form string but `terminal/manager.py:484-499` only knows about `("mcpretentious", "iterm2", "crow", "mock")` with a hardcoded launch path for `mcpretentious`.

## Decision

Make the PTY toolservers **pluggable via a hardcoded built-in list** in a new `mahavishnu/terminal/backends.py` module. The list contains one or more named entries, each defining a launch command and tool-name mapping. Operators select a backend by setting `terminal.adapter_preference` (no new config surface). The pluggability is internal — operators can choose between built-ins but cannot add custom backends through config. New backends = one entry in the registry.

This is the smallest change that:
- Fixes the immediate bug (npm-vs-uvx)
- Adds a second built-in backend (`luqm4nx/pty-mcp-server-python`) for cross-implementation coverage
- Sets up the architecture for future backends without committing to a config-driven plugin system

## Out of scope

- **Oneiric-ification of terminal adapters.** The existing engine adapter system uses Oneiric for distribution/discovery. Terminal adapters stay separate because they have a different lifecycle (per-pool vs. per-workflow) and the Oneiric enum/categories are engine-shaped. Reusable if a future need drives a general adapter system; not preemptive.
- **Per-workflow terminal selection.** Technically possible, but workers are long-lived and the right terminal adapter is an environment decision. A future override feature (workflow requests an adapter, pool falls back to default if not available) is the YAGNI-correct shape if a real need surfaces.
- **Configurable per-backend launch commands.** Operators pick the backend by name; they cannot override the launch command. Reduces YAML surface, prevents misconfiguration, keeps the test matrix small.
- **Discovery of third-party backends via entry points.** Hardcoded list is enough for the foreseeable set.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      PoolManager / route_task                   │
│  (existing — passes task to pool, pool picks worker)            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              TerminalManager.create(config)                     │
│  (existing) — reads config.terminal.adapter_preference,         │
│  instantiates the right adapter. NO CHANGE to signature.         │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
  MockAdapter          ITerm2Adapter         McpretentiousAdapter
  (existing)           (existing)             (existing, but broken)
                                                 │
                                                 ▼
                                       StdioMCPClient
                                       (mcp_client.py — CHANGE HERE)
                                                 │
                                       ┌─────────┴──────────┐
                                       ▼                    ▼
                              MCPretentious          pty-mcp-server-python
                              (npm, npx)             (Python, uvx)
                              [hardcoded list]       [hardcoded list]
```

The change is local to one module: `mcp_client.py` + a new `backends.py`. Nothing else moves.

## Components

### `mahavishnu/terminal/backends.py` (NEW)

Single source of truth for built-in PTY backends.

```python
"""PTY toolserver backend registry.

Built-in backends. Each entry defines:
  - command + args: how to spawn the MCP subprocess
  - tool_map: how Mahavishnu's generic tool names map to backend-specific names
  - requires: prerequisites that must be on PATH

Adding a new backend = one entry here + (if tool surface differs) a thin
adapter shim. Operators pick by name via terminal.adapter_preference.
"""
from dataclasses import dataclass, field

@dataclass(frozen=True)
class PtyBackend:
    name: str
    command: str
    args: tuple[str, ...]
    tool_map: dict[str, str] = field(default_factory=dict)
    requires: tuple[str, ...] = field(default_factory=tuple)

BUILTIN_BACKENDS: dict[str, PtyBackend] = {
    "mcpretentious": PtyBackend(
        name="mcpretentious",
        command="npx",                              # was: "uvx" — BUG
        args=("mcpretentious",),
        tool_map={},                                # uses default names
        requires=("node",),                         # npm package
    ),
    "pty_mcp_python": PtyBackend(
        name="pty_mcp_python",
        command="uvx",
        args=("--from", "luqm4nx-pty-mcp-server-python", "pty-mcp-server-python"),
        tool_map={},                                # see Tool-name mapping note below
        requires=("uvx",),
    ),
}
```

### `mahavishnu/terminal/mcp_client.py` (MODIFY)

Two changes:

1. **Line 248** — replace hardcoded subprocess invocation with registry lookup:
   ```python
   # BEFORE (broken):
   self._client = StdioMCPClient("uvx", ["--from", "mcpretentious", "mcpretentious"])

   # AFTER:
   backend = BUILTIN_BACKENDS[backend_name]
   self._client = StdioMCPClient(backend.command, list(backend.args))
   ```

2. **New helper function** `check_prerequisites()`:
   ```python
   def check_prerequisites(backend: PtyBackend) -> list[str]:
       """Return a list of missing prerequisites (empty = all good)."""
       import shutil
       return [req for req in backend.requires if shutil.which(req) is None]
   ```

   Called from `McpretentiousClient.__init__` so failures surface at construction time with a clear message (e.g., "Backend 'mcpretentious' requires 'node' but it was not found on PATH").

### `mahavishnu/terminal/manager.py` (MINOR MODIFY)

`McpretentiousClient` instantiation gets the backend name from the manager. The manager already knows `preference` (it's the input to its selection logic at `manager.py:443`), so this is a one-line change: pass `preference` through to the client constructor.

### Scope boundaries

- **No changes** to `MockAdapter`, `ITerm2Adapter`, `CrowTerminalAdapter`
- **No changes** to `bootstrap.py`, `health_integration.py`, or any Oneiric code
- **No changes** to settings files — `adapter_preference` is already exposed
- **No new config fields**

## Data flow

Tracing one end-to-end call: operator runs `mahavishnu mcp start` with `adapter_preference: "mcpretentious"`.

1. `main_cli.py` constructs `MahavishnuSettings` → `config.terminal.adapter_preference = "mcpretentious"`
2. `main_cli.py` calls `TerminalManager.create(config, mcp_client=None)`
   - `preference = "mcpretentious"`
   - manager calls `McpretentiousClient(backend_name="mcpretentious")` (NEW)
     - `check_prerequisites(BUILTIN_BACKENDS["mcpretentious"])` → `[]` (node is on PATH)
     - `backend = BUILTIN_BACKENDS["mcpretentious"]`
     - `StdioMCPClient("npx", ["mcpretentious"])` — FIXED (was `uvx` + wrong package)
     - `StdioMCPClient.start()` → `asyncio.create_subprocess_exec("npx", "mcpretentious", ...)`
     - MCPretentious subprocess listens on stdin/stdout for JSON-RPC
   - `adapter = McpretentiousAdapter(mcp_client)`
   - `return TerminalManager(adapter, config)`
3. `pool_route_execute` dispatches a task
   - `TerminalManager.launch_sessions(command=...)`
     - `adapter.launch_session(command)`
       - `self.mcp.call_tool("mcpretentious-open", {columns, rows})`
         - `StdioMCPClient.call_tool(...)` writes JSON-RPC to MCPretentious stdin, reads response from stdout, returns session_id
4. Session is now alive in MCPretentious (and its iTerm2/tmux backend). Pool worker sends commands via the same pipe, captures output, etc.

The minimal-change property holds: step 2 is where the new code lives. Steps 1, 3, 4 are unchanged.

## Error handling

| Failure | Detection | Behavior |
|---------|-----------|----------|
| Prerequisite missing (e.g., `node` not installed) | `check_prerequisites()` at construction | Raise `ConfigurationError`: "Backend 'mcpretentious' requires 'node' (Node.js >= 18) but it was not found on PATH. Install it: brew install node" |
| Subprocess fails to start (e.g., npm registry unreachable) | `StdioMCPClient.start()` — process exits within ~2s or raises `FileNotFoundError` | Raise `ConfigurationError`: "Failed to start PTY tools backend 'mcpretentious': npx mcpretentious exited with code 1. Output: <stderr>" |
| Tool call times out (subprocess hung) | `StdioMCPClient.call_tool()` — 30s default | Cancel pending request, log structured fields (`backend`, `tool`, `request_id`, `elapsed_ms`), raise `ToolCallError`. No silent retry. |
| Tool name mismatch (we call `mcpretentious-read` but package exposes `mcpretentious-screenshot`) | Subprocess returns JSON-RPC method-not-found | Raise `ToolCallError` listing available tools. Recovery: extend adapter or add to `tool_map`. |
| Subprocess crashes mid-session (e.g., user Ctrl-C's iTerm2) | Next `call_tool` gets EOF on stdout | `ToolCallError` (clean, no traceback). Pool worker's existing health check (`KeepAlive.Crashed`) reaps dead worker and spawns fresh. No new code. |

No silent fallbacks anywhere. A loud failure with a clear message is better than a silent degradation.

## Testing

Four test layers:

### 5.1 Unit tests — `tests/unit/terminal/test_backends.py` (NEW)

- `BUILTIN_BACKENDS` has expected keys (`mcpretentious`, `pty_mcp_python`)
- Each entry has non-empty `command`, `args`, `requires`
- `PtyBackend` is frozen (immutability)
- `check_prerequisites()` returns `[]` for empty `requires`
- `check_prerequisites()` returns `["node"]` for backend with `requires=("node",)` when `node` is missing
- `check_prerequisites()` returns `[]` when all required tools are on `PATH`

### 5.2 Unit tests — `mcp_client.py` regression (MODIFY existing)

The existing `tests/unit/terminal/mcp_client.py` tests need updating. New tests should:

- Mock `asyncio.create_subprocess_exec` and assert it's called with `("npx", "mcpretentious")` — **this is the regression test for the original bug**
- Assert `check_prerequisites()` is called before spawn
- Assert a missing prerequisite raises `ConfigurationError` with the right message

## Tool-name mapping (for `pty_mcp_python`)

The `mcpretentious` backend uses tool names that match the existing `McpretentiousAdapter` exactly: `mcpretentious-open`, `-type`, `-read`, `-close`, `-list`. So `tool_map` is empty.

The `pty_mcp_server_python` backend **must be verified before relying on it**: at implementation time, we will install the package locally, list its tool surface (`tools/list` over MCP), and either (a) confirm it exposes the same `mcpretentious-*` shape (then `tool_map` stays empty and the existing `McpretentiousAdapter` works unchanged) or (b) write a thin adapter shim that calls the right tool names. The `tool_map` field is the data-driven escape hatch for the second case; if a future third backend needs remapping, populate the dict instead of writing another adapter.

## Testing

Gated by `MCPRETENTIOUS_INTEGRATION=1` env var. Skipped in fast CI.

- Setup: `npm install -g mcpretentious`
- Spawn Mahavishnu with `adapter_preference: "mcpretentious"`
- Call `pool_route_execute` with `echo hello`
- Assert session is created and output contains `hello`
- Teardown: kill subprocess

### 5.4 Manual smoke test (not in pytest)

- Set `terminal.adapter_preference: "mcpretentious"` in `settings/local.yaml`
- Run `mahavishnu mcp start` — confirm wrapper logs "Using mcpretentious adapter" and subprocess PID
- Run a pool task — confirm completion
- Switch to `adapter_preference: "pty_mcp_python"` and confirm it switches
- Document both backends in `docs/terminal/backends.md` with logs

## Implementation order

1. Add `mahavishnu/terminal/backends.py` with `BUILTIN_BACKENDS` and `check_prerequisites()` — pure code, no side effects
2. Modify `mcp_client.py:248` to use the registry — fixes the original bug
3. Add `check_prerequisites()` call in `McpretentiousClient.__init__` — fail-loud behavior
4. Add `tests/unit/terminal/test_backends.py`
5. Update `tests/unit/terminal/mcp_client.py` to add the regression test
6. Add `tests/integration/terminal/test_mcpretentious_smoke.py` (gated)
7. Update `docs/terminal/backends.md` with both backends documented
8. Manual smoke test on a real machine

Each step is independently mergeable. Steps 1-3 are the core fix; steps 4-8 are quality and documentation.
