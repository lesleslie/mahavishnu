# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

- Username: les
- Projects home: /Users/les/Projects/
- Primary project: Mahavishnu (/Users/les/Projects/mahavishnu)
- Uses iTerm2 on macOS

## Mahavishnu Project

- Running as a LaunchAgent on macOS (PID 83236 as of 2025-04-05, port 8680)
- LaunchAgent plist previously had missing `WorkingDirectory` — caused CWD to default to `/`. This was fixed.
- Stale manual processes can hold port 8680 and need to be killed before the LaunchAgent can bind
- Mahavishnu exposes MCP tools for other services (e.g., Nanobot)
- i9 Claude Code sessions are launched via tmux (session name: `i9-mahavishnu`). Known issue: `claude --print` may not flush output to log immediately — output can be empty for 30+ seconds even when working
- Has a `scripts/` directory
- MCP connections frequently go stale (ClosedResourceError) — requires nanobot restart to restore

## I9 — Typed Event Envelope Initiative

- Initiative 09 in docs/plans/initiatives/09-typed-event-envelope-*
- Work packages: I9-1 (Event Envelope spec), I9-2 (Crackerjack CI), I9-3 (migrating existing producers)
- I9-1 partial implementation completed by Claude Code session (killed at 2025-04-05 05:11 after ~20 min):
  - `envelope.py` (243 lines), `schema_registry.py` (297 lines), `compatibility.py` (108 lines), `migration.py` (157 lines), `__init__.py` (30 lines)
  - Unit tests: `tests/unit/test_event_envelope.py` (was run, has `.pyc`)
- I9-2 and I9-3 remain incomplete
- Constraints: Pydantic v2, ruff, uv run pytest, tests in tests/unit/

## Nanobot / MCP

- Nanobot connects to Mahavishnu via MCP
- **Nanobot runs as a LaunchAgent** (`ai.nanobot.gateway`), NOT a brew service
  - Plist location: `~/Library/LaunchAgents/ai.nanobot.gateway.plist`
  - Label: `ai.nanobot.gateway`
  - Comment: `Nanobot Personal AI Gateway (v0.1.4.post6)`
  - Process path: `/Users/les/.local/share/uv/tools/nanobot-ai/bin/nanobot gateway --workspace /Users/les/Projects/mahavishnu`
  - KeepAlive: true, ThrottleInterval: 30, ProcessType: Background, RunAtLoad: true
  - Logs: stdout → `~/.local/state/mcp/logs/nanobot.log`, stderr → `~/.local/state/mcp/logs/nanobot.err`
  - EnvironmentVariables: HOME, PATH (homebrew-first), LANG
  - **Management script**: `/Users/les/Projects/mahavishnu/scripts/nb-ctl`
    - Renamed from `nanobot.sh` to `nb-ctl` to avoid conflict with the `nanobot` CLI installed by `uv tool`
    - Commands: `start`, `stop`, `restart`, `status`, `tail`, `log`
    - Uses `launchctl kickstart -k gui/$(id -u)/ai.nanobot.gateway` for restart
    - Uses `bootout`/`load` for stop/start; waits for process exit on stop
  - Legacy restart command: `launchctl kickstart -k gui/$(id -u)/ai.nanobot.gateway`
- **`nanobot` CLI** (installed via `uv tool`):
  - Path: `/Users/les/.local/share/uv/tools/nanobot-ai/bin/nanobot`
  - Commands: `onboard`, `gateway`, `agent`, `status`, `channels`, `plugins`, `provider`
- MCP connections can go stale; requires nanobot restart to restore (but restart drops Slack sessions)
- Nanobot does NOT auto-reconnect MCP servers after Mahavishnu restart
- **Recurring issue**: ClosedResourceError when Mahavishnu MCP is unreachable — typical remediation is nanobot restart via `nb-ctl restart`
- User communicates via Slack

## Environment Notes

- tmux used for background/long-running sessions
- macOS LaunchAgent for persistent service management (both Mahavishnu and Nanobot)
- Homebrew services NOT used for nanobot (was a misconception)
- Mahavishnu startup warnings (non-blocking): LlamaIndex deps missing, RuntimeWarning about unawaited coroutine `register_worktree_tools` (server_core.py:1444)