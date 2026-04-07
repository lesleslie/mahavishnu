# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

- Username: les
- Projects home: /Users/les/Projects/
- Primary project: Mahavishnu (/Users/les/Projects/mahavishnu)
- Uses iTerm2 on macOS
- **Intel Mac** — Homebrew binaries at `/usr/local/opt/` (NOT `/opt/homebrew/`)
- **16 GB RAM**
- User has ADHD and sometimes misses information — be proactive with reminders and clear summaries
- Tool call iteration limit is a client-side nanobot runtime parameter — cannot be changed from within the session
- **Preference**: Always prefer simplest solutions over more complicated ones
- **Preference**: Use `uv` over `pip` for Python package management — uv is installed globally

## Local Infrastructure

### Currently Running Services (brew services)
- **started**: grafana

### Installed CLI Tools
- `mcp-grafana` at `/usr/local/bin/mcp-grafana` (devel build)

### TensorZero Gateway Plan
- **Plan file**: `/Users/les/Projects/mahavishnu/docs/plans/tensorzero-gateway-plan.md`
- **Status**: v3.0 with Postgres auth + Tempo/Alloy (Phase 1.6)
- **Port**: 8471
- **Deployment**: Native binary (NOT Docker) — Python embedded gateway
- **Install location**: `~/.local/share/tensorzero/.venv/bin/tensorzero-gateway`
- **Config**: `~/.config/tensorzero/tensorzero.toml`
- **LaunchAgent**: `~/Library/LaunchAgents/com.tensorzero.gateway.plist`
- **Postgres**: Dedicated `tensorzero` database on localhost:5432 for auth + observability
- **z.ai**: Two API formats (OpenAI + Anthropic), coding plan has dedicated endpoint

### Phase 1.6: Tempo + Grafana Alloy (Tracing)
- **Decision**: Replace OTelStorageAdapter's Postgres/pgvector trace storage with Grafana Tempo
- **Architecture**: Services → OTLP → Grafana Alloy → Tempo → TraceQL queries
- **Grafana Alloy**: Install via `brew install grafana-alloy`, runs as LaunchAgent
- **Tempo**: Download binary from GitHub releases (NOT Docker), runs as LaunchAgent
- **Tempo MCP**: Embedded in Tempo v2.10+ at `/api/mcp` — no separate process needed
- **Standalone tempo-mcp-server**: ARCHIVED on GitHub — do NOT use
- **MCP access option**: mcp-grafana proxied tools (Option A recommended) — user already has mcp-grafana
- **Trace data sensitivity**: Traces may contain LLM prompt/response content
- **Pending reviews**: Ops review and security review of Phase 1.6 not yet completed (rate limited)

## Projects & Decisions

- **CCR (Claude Code Router)**: Routes Claude Code to z.ai via Anthropic format; will route through TensorZero
- **Oneiric**: Has `OTelStorageAdapter` (Postgres/pgvector) and `PostgresDatabaseAdapter` (asyncpg); OTelStorageAdapter to be replaced with Tempo
- **Vish**: NanobotWorker instances that will route through TensorZero
- **Nanobot**: Will route through TensorZero gateway
