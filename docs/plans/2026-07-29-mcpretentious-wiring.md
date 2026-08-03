---
status: active
role: implementation
date: 2026-07-29
last_reviewed: 2026-07-29
superseded_by: null
topic: mcpretentious-runtime-wiring
---

# Mcpretentious Runtime Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `mcpretentious` reachable on `http://127.0.0.1:8699` so `mahavishnu pool_spawn` can resolve a `terminal_id` from the `mcpretentious-open` tool call. Specifically: add a `mcpretentious` entry to `.mcp.json` and a new `com.mcp.mcpretentious.plist` LaunchAgent that supervises the server.

**Architecture:** Two independent surfaces, both rooted in documented convention. The `.mcp.json` entry lets Claude Code spawn the server alongside the existing 17 entries when this project is loaded. The LaunchAgent ensures the server is also available when Claude Code is not running, so Mahavishnu's local-pool model can start workers during CI or from the CLI alone. Both surfaces use `uvx --from mcpretentious mcpretentious` (per `docs/TERMINAL_MANAGEMENT.md:468-471`) and reuse the existing `launch_with_healthcheck.sh` wrapper for crash-visible supervision.

**Tech Stack:** macOS LaunchAgent, Bash, `uvx`, `launchctl`, `curl`, `jq`, FastMCP-style MCP client tools.

## 1. Outcome

- `curl -fsS http://127.0.0.1:8699/health` returns 200.
- `mcpretentious` is listed in `.mcp.json` and starts successfully when Claude Code loads this project.
- `mahavishnu pool_spawn --type mahavishnu --name test --min 1 --max 1` returns a `pool_id` and the spawn no longer fails with `MHV-007`.
- `mahavishnu pool list` shows at least one RUNNING pool.

## 2. Goals

1. Add `mcpretentious` to `.mcp.json` in alphabetical position between `mahavishnu` and `mermaid`.
2. Create `~/Library/LaunchAgents/com.mcp.mcpretentious.plist` that supervises the server on port 8699 and writes logs to `~/.local/state/mcp/logs/mcpretentious.{log,err}`.
3. Verify both surfaces and confirm `pool_spawn` no longer raises `MHV-007`.

## 3. Non-Goals

- Repackaging `mcpretentious` or modifying its upstream source.
- Touching any project source code; this is purely an operational wiring change.
- Removing or replacing the iTerm2 adapter or its documentation.
- Adding Mahavishnu ACL wiring (out of scope; see `PoolManager constructed with session_buddy_client but no explicit acl_provider` warning in the startup log).

## 4. Current Findings

- `pool_spawn` fails with `MHV-007 Failed to launch session: 'terminal_id'` because the `mcpretentious` adapter (`mahavishnu/terminal/adapters/mcpretentious.py:84`) does `result["terminal_id"]` on a `None`/empty response. Root cause: nothing is listening on port 8699 (`curl http://127.0.0.1:8699/health` returns `000`).
- `.mcp.json` lists 17 servers; no `mcpretentious` entry exists.
- `~/Library/LaunchAgents/` contains only `com.mcp.mahavishnu.plist` (plus a backup). It runs `scripts/launch_mcp_with_secrets.py` on port 8680. No `mcpretentious` plist exists.
- `~/.local/state/mcp/scripts/launch_with_healthcheck.sh` is the existing healthcheck wrapper; it accepts `<health-url> [--timeout SECONDS] -- <command> [args...]`, polls every 0.5s, and exits non-zero on timeout so `KeepAlive.Crashed=true` triggers a restart.
- `docs/TERMINAL_MANAGEMENT.md:468-471` documents the entrypoint as `uvx --from mcpretentious mcpretentious`; `docs/terminal/backends.md:12-31` documents `npx mcpretentious`. The user chose `uvx` for this plan.
- `mahavishnu/terminal/mcp_client.py:321` and `mahavishnu/terminal/adapters/mcpretentious.py:93` both consume the `terminal_id` key from the `mcpretentious-open` response. The contract is documented and unchanged.

## 5. Implementation Phases

### Phase 1: Add mcpretentious to .mcp.json

**Goal:** Make Claude Code spawn the mcpretentious server when this project loads.

**Tasks:**
- Insert a new `mcpretentious` key in `mcpServers`, alphabetically between `mahavishnu` and `mermaid`, with the same `command`/`args` shape as the `minimax-coding-plan` entry that already uses `uvx`.
- Sort: rely on the existing `mcpServers` object — JSON object key order is preserved by the parser; alphabetical insertion is mandatory.
- Do **not** add `env`, `headers`, `transport`, or `type` fields; the existing uvx pattern does not need them and adding extras would be premature.

**Exit criteria:** `jq -r '.mcpServers | keys | .[]' .mcp.json | sort -C` reports no out-of-order key; the new key is present.

#### Integration Contract

- **Triggered from:** Claude Code project load.
- **Returns to / updates:** `mcpServers.mcpretentious` in `.mcp.json`; no runtime effect until Claude Code is restarted in this project.
- **Demonstrable by:** `jq '.mcpServers | has("mcpretentious")' .mcp.json` returns `true` and `jq '.mcpServers.mcpretentious.command' .mcp.json` returns `"uvx"`.
- **Rollback signal:** the server fails to start when Claude Code loads the project (then the user manually removes the entry).
- **Observability added:** none directly; the new server's own `mcpretentious` log is its own signal.

### Phase 2: Create the LaunchAgent plist

**Goal:** Supervise `mcpretentious` independently of Claude Code so Mahavishnu's local pool can run when Claude Code is not running.

**Tasks:**
- Create `~/Library/LaunchAgents/com.mcp.mcpretentious.plist` with the same shape as `com.mcp.mahavishnu.plist` (Label, KeepAlive, ThrottleInterval, RunAtLoad, ProgramArguments, EnvironmentVariables, log paths).
- Set `MCP_PORT=8699` in `EnvironmentVariables`.
- Set `ProgramArguments` to: `launch_with_healthcheck.sh http://127.0.0.1:8699/health --timeout 60 -- uvx --from mcpretentious mcpretentious`.
- Set `StandardOutPath` to `~/.local/state/mcp/logs/mcpretentious.log` and `StandardErrorPath` to `~/.local/state/mcp/logs/mcpretentious.err`.
- Set `WorkingDirectory` to `/Users/les/Projects/mahavishnu` (matches the existing plist).
- Validate the plist with `plutil -lint ~/Library/LaunchAgents/com.mcp.mcpretentious.plist`.

**Exit criteria:** `plutil -lint` reports `OK` and the plist is syntactically valid.

#### Integration Contract

- **Triggered from:** `launchctl load -w ~/Library/LaunchAgents/com.mcp.mcpretentious.plist` (or system login + `RunAtLoad=true`).
- **Returns to / updates:** A persistent process on `127.0.0.1:8699`; writes stdout/stderr to `~/.local/state/mcp/logs/mcpretentious.{log,err}`.
- **Demonstrable by:** `launchctl list | grep mcpretent` shows a running PID; `curl -fsS http://127.0.0.1:8699/health` returns 200.
- **Rollback signal:** `launchctl list` exits the agent; the wrapper script exits non-zero on a stuck start, surfacing as a restart in `launchctl list`.
- **Observability added:** Log lines for each start/restart cycle land in `mcpretentious.log`; the healthcheck script writes its own diagnostic lines to `mcpretentious.err`.

### Phase 3: Load the agent and verify end-to-end

**Goal:** Confirm Mahavishnu can spawn a pool after the wiring is complete.

**Tasks:**
- Load the new agent: `launchctl load -w ~/Library/LaunchAgents/com.mcp.mcpretentious.plist`.
- Wait for `curl -fsS http://127.0.0.1:8699/health` to return 200 (timeout 60s).
- Run `mahavishnu pool spawn --type mahavishnu --name test --min 1 --max 1` and assert that the response contains a `pool_id` and `status: created` (not the previous `MHV-007` failure).
- Run `mahavishnu pool list` and assert that the test pool is present.
- Run `mahavishnu pool close test` to clean up the test pool.

**Exit criteria:** The three `mahavishnu pool` commands exit 0; the test pool is created and then closed.

#### Integration Contract

- **Triggered from:** `launchctl load` and `mahavishnu pool` CLI.
- **Returns to / updates:** A running pool backed by a `mcpretentious` terminal adapter.
- **Demonstrable by:** `mahavishnu pool list` shows the test pool as RUNNING and `pool_route_execute` can dispatch work to it.
- **Rollback signal:** The plist's `KeepAlive.Crashed=true` causes a restart storm visible in `mcpretentious.err`; the user unloads the agent with `launchctl bootout`.
- **Observability added:** `mcpretentious.log` records each `mcpretentious-open` call from the test spawn; the Mahavishnu pool's own audit logger records the worker creation.

## 6. Required Code Changes

- Modify `/Users/les/Projects/mahavishnu/.mcp.json`: insert `mcpretentious` entry (no other fields touched).
- Create `~/Library/LaunchAgents/com.mcp.mcpretentious.plist` (new file).
- Optionally add a one-line note to `docs/TERMINAL_MANAGEMENT.md` pointing to the new plist (skip if not required).

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
| --- | --- | --- |
| `jq '.mcpServers | has("mcpretentious")' .mcp.json` | `true` | Conversation log |
| `jq '.mcpServers.mcpretentious.command' .mcp.json` | `"uvx"` | Conversation log |
| `plutil -lint ~/Library/LaunchAgents/com.mcp.mcpretentious.plist` | `OK` | Conversation log |
| `launchctl list \| grep mcpretent` | non-empty PID | Conversation log |
| `curl -fsS http://127.0.0.1:8699/health` | 200 | Conversation log |
| `mahavishnu pool spawn --type mahavishnu --name test --min 1 --max 1` | `pool_id` returned | Conversation log |
| `mahavishnu pool list` | test pool RUNNING | Conversation log |
| `mahavishnu pool close test` | exit 0 | Conversation log |

## 8. Risks

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| `uvx` is not on PATH in the LaunchAgent environment | Low | The existing plist uses `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin`; add `/Users/les/.local/bin` if `which uvx` requires it. |
| `mcpretentious` listens on a different default port | Low | The plan pins port 8699 explicitly; if the upstream default differs, set `MCP_PORT` to match. |
| The agent and `.mcp.json` race for the same port | Low | Both use `127.0.0.1:8699`; whichever starts first wins, the other observes `EADDRINUSE` and fails fast. In practice only one path is active at a time. |
| `mahavishnu pool spawn` still fails for an unrelated reason | Low | The previous symptom (KeyError on `terminal_id`) is fully addressed; any new failure will surface with a different message and require re-investigation. |

## 9. Decision Rule

Plan is done when `mcpretentious` is configured in both `.mcp.json` and the new LaunchAgent, the plist is valid, the agent is loaded, port 8699 responds to `/health`, and `mahavishnu pool spawn` returns a `pool_id` without raising `MHV-007`.
