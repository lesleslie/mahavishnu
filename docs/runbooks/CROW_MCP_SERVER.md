# crow-mcp Runbook

crow-mcp is the built-in MCP toolserver for the Crow agent. It provides PTY terminal
execution, file read/write/edit, web search (SearXNG), and web fetch tools.

**Transport:** stdio (started on-demand by Claude Code — no background daemon needed)
**Package:** `crow-mcp` subpackage of the [crow-cli monorepo](https://github.com/crow-cli/crow-cli)
**MCP config:** `.mcp.json` → `"crow": {"command": "crow-mcp"}`

## Install

crow-mcp is not published to PyPI independently — install directly from the monorepo:

```bash
uv tool install "crow-mcp @ git+https://github.com/crow-cli/crow-cli.git#subdirectory=crow-mcp"
```

Verify:

```bash
crow-mcp --help
# or
which crow-mcp   # → /Users/les/.local/bin/crow-mcp
```

## MCP Tools Provided

| Tool | Description |
|------|-------------|
| `terminal` | Real PTY shell with directory state persistence, C-c/C-z support |
| `read` | File reader with line numbers, binary detection, pagination |
| `write` | File writer with auto mkdir -p |
| `edit` | Fuzzy string replacement (9-level cascade: exact → Levenshtein → context-aware) |
| `web_search` | Web search via SearXNG |
| `web_fetch` | Fetch URL as markdown via readabilipy |

## Architecture

crow-mcp is crow-cli's **toolserver** — crow-cli (ACP agent) connects to it as an MCP
client for tool dispatch. Mahavishnu uses crow-mcp directly via `CrowTerminalAdapter`
(see `mahavishnu/terminal/adapters/crow.py`) for PTY session management.

```
CrowTerminalAdapter → MCP client → crow-mcp (stdio) → pty.openpty()
CrowWorker          → httpx       → crow-cli ACP      → crow-mcp (stdio)
```

## Update

```bash
uv tool upgrade crow-mcp
# or reinstall:
uv tool install --force "crow-mcp @ git+https://github.com/crow-cli/crow-cli.git#subdirectory=crow-mcp"
```

## Logs

crow-mcp writes terminal session logs to:

```
~/.cache/crow-mcp/logs/terminal_YYYYMMDD_HHMMSS.log
```

## Security

- stdio transport: process-local, no network exposure
- No launchd plist needed — Claude Code spawns crow-mcp on demand
- No JWT/TLS required (stdio is inherently local)
