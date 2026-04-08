# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

- Username: les
- **GitHub handle**: `lesleslie` (confirmed via `gh api`)
- Projects home: /Users/les/Projects/
- Primary project: Mahavishnu (/Users/les/Projects/mahavishnu)
- Uses iTerm2 on macOS
- **Intel Mac** — Homebrew binaries at `/usr/local/opt/` (NOT `/opt/homebrew/`)
- **16 GB RAM**
- User has ADHD and sometimes misses information — be proactive with reminders and clear summaries
- Tool call iteration limit is a client-side nanobot runtime parameter — cannot be changed from within the session
- **Preference**: Always prefer simplest solutions over more complicated ones
- **Preference**: Use `uv` over `pip` for Python package management — uv is installed globally
- **Preference**: Kick off independent tasks in parallel — don't serialize unnecessarily
- **Phrase**: "do all" = run all pending tasks in parallel (confirmed preference)
- **Caution**: Always verify subagent diffs before committing — subagents can go on unwanted deletion sprees; revert and re-apply only intended changes
- **Python**: Shell alias `python`/`python3` points to Python 3.12 — can interfere with venv operations; use full path for non-default venvs
- **Style**: Casual check-ins, no urgency ("at your leisure")
- **Go**: v1.26.1 at `/usr/local/bin/go`

## Local Infrastructure

### Currently Running Services (brew services)
- **started**: grafana

### Installed CLI Tools
- `mcp-grafana` at `/usr/local/bin/mcp-grafana` (Homebrew install) — running on port 3035 (MCP proxy, NOT Grafana itself)
- `cmake` at `/usr/local/bin/cmake` — version 4.3.1
- `ccr` (Claude Code Router) at `/usr/local/bin/ccr` — binary installed, **server not currently running**

### Infrastructure
- **Postgres 18**: Running via Homebrew — `tensorzero` database exists with `pg_trgm` and `vector` extensions created
- **Postgres auth**: No password for local deployment; password required when deployed remotely
- **Redis**: Environment uses Redis (not Valkey)
- **Python compatibility**: `onnxruntime<1.24` pin required for macOS x86_64 (affects session-buddy, crackerjack, oneiric)

### ⚠️ IMPORTANT: Port Clarification
- **Grafana server**: port **3030** (configured in `/usr/local/etc/grafana/grafana.ini`)
- **mcp-grafana MCP proxy**: port **3035** (separate service, `com.mcp.grafana.plist`)
- Previous memory incorrectly stated Grafana port as 3035 — this is the MCP proxy

### TensorZero Gateway Plan
- **Plan file**: `/Users/les/Projects/mahavishnu/docs/plans/tensorzero-gateway-plan.md`
- **Status**: v3.0 with Postgres auth + Tempo (Phase 1.6) — 1001 lines — all remaining TODOs addressed
- **Port**: 8471
- **Deployment**: Native binary (NOT Docker) — Python embedded gateway
- **Install location**: `~/.local/share/tensorzero/.venv/bin/tensorzero-gateway`
- **Config**: `~/.config/tensorzero/tensorzero.toml` — 5 occurrences of `type = "openai-compatible"` fixed to `type = "openai"`, invalid `[gateway.export.prometheus]` section removed
- **Python client**: v2026.4.0 installed in `~/.local/share/tensorzero/.venv` (Python 3.13) — client library only, not the gateway
- **z.ai API key**: `Z_AI_API_KEY` env var (not `ZAI_API_KEY`) — not stored in any persistent location (shell profiles, .env files, macOS keychain); must obtain from user before LaunchAgent can work
- **Gateway status**: Not currently running (neither TensorZero gateway nor CCR server is active)
- **LaunchAgent**: `~/Library/LaunchAgents/com.tensorzero.gateway.plist`
- **Postgres**: Dedicated `tensorzero` database on localhost:5432 for auth + observability
- **z.ai**: Two API formats (OpenAI + Anthropic), coding plan has dedicated endpoint

### Phase 1.6: Tempo (Tracing) — All TODOs Complete
- **Decision**: Replace OTelStorageAdapter's Postgres/pgvector trace storage with Grafana Tempo
- **Architecture**: Services → OTLP → Tempo (direct). Alloy skipped for single-user dev.
- **Tempo**: NO macOS binary — must build from source. `go build ./cmd/tempo`
- **Tempo install**: `~/.local/share/tempo/bin/tempo` (built from `~/.local/share/tempo/src/tempo`)
- **Tempo version**: v2.10.3
- **Tempo config**: `~/.config/tempo/tempo.yaml` — localhost-only binding, local filesystem storage, 7-day retention
- **Tempo data**: `~/.local/state/tempo/data/`
- **Tempo LaunchAgent**: `~/Library/LaunchAgents/com.grafana.tempo.plist`
- **Tempo ports**: HTTP 3200, gRPC 3201 (query), OTLP 4317/4318 (receive) — note: query gRPC (3201) and OTLP gRPC (4317) are different services
- **Alloy**: Completely removed from plan — skipped for single-user dev. Install later with `brew install grafana-alloy` if trace enrichment needed.
- **Alloy config/LaunchAgent**: Not created (Alloy skipped)
- **Tempo MCP server**: Embedded in Tempo v2.9+ — enabled via `query_frontend.mcp_server.enabled = true` in tempo.yaml (NOT top-level)
- **Standalone tempo-mcp-server**: ARCHIVED on GitHub — do NOT use
- **MCP access**: mcp-grafana at port 3035 (Homebrew install at `/usr/local/bin/mcp-grafana`) — proxies Tempo + Prometheus + Loki tools. **GRAFANA_URL for mcp-grafana must be `http://localhost:3030`** (Grafana server), not 3035
- **Trace data sensitivity**: Traces may contain LLM prompt/response content — 7-day retention limits exposure
- **Grafana datasource**: Tempo provisioning YAML needs fixing — current path `~/.config/grafana/provisioning/datasources/tempo.yaml` not scanned by Grafana. Use HTTP API or enable provisioning in `grafana.ini`
- **Disk estimate**: ~2GB max with 7-day retention
- **Pending reviews**: Ops review and security review of Phase 1.6 completed but were partially stale (referenced old Docker setup). Valid Phase 1.6 concerns were applied.
- **Log rotation**: Still TODO for Tempo/gateway logs

### Claude Code OTEL Monitoring
- **Claude Code has native OTEL**: metrics (tokens, cost, LoC, commits, tool decisions), logs/events, traces (beta)
- **No CCR-specific monitoring**: CCR is a proxy — all telemetry comes from Claude Code itself
- **Env vars**: `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_METRICS_EXPORTER=otlp`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318`
- **Traces pass through CCR transparently** via `traceparent` header → TensorZero → z.ai

### TensorZero Monitoring
- **Prometheus metrics**: Exposed at `/metrics` on gateway port 8471 (always available, no config needed)
- **OTEL traces**: Exported via OTLP to Tempo at `http://127.0.0.1:4318`
- **Key metrics**: `tensorzero_inferences_total`, `tensorzero_requests_total`, `tensorzero_inference_latency_overhead_seconds`

## Mahavishnu Architecture

### MCP Server
- **Mahavishnu MCP server**: `python -m mahavishnu mcp start` (PID varies, workspace: `/Users/les/Projects/mahavishnu`)
- **Nanobot gateway**: `nanobot gateway --workspace /Users/les/Projects/mahavishnu` — manages MCP stdio pipe to Mahavishnu
- **Known issue**: MCP stdio pipe can break between nanobot gateway and Mahavishnu MCP server, causing `ClosedResourceError` on all tool calls. Fix by restarting nanobot gateway.
- **No workspace nanobot config** — gateway uses `--workspace` flag only

### Adapter Health Status (2026-04-07)
- **Worker adapter**: ✅ Healthy — workers_active: 0, max_concurrent: 10
- **Prefect adapter**: ⚠️ Unhealthy — `'MahavishnuSettings' object has no attribute 'api_url'` (config error)
- **Agno adapter**: ⚠️ Not initialized — using ollama with qwen2.5:7b, agents_cached: 0, teams_count: 0

### Worker Registry (Mahavishnu)
- **Registry file**: `/Users/les/Projects/mahavishnu/mahavishnu/workers/registry.py`
- **Workers enabled**: `workers.enabled: true` in `settings/mahavishnu.yaml`, max_concurrent: 10
- **Worker types** (40+):
  - **AI Assistants**: terminal-qwen, terminal-claude, terminal-codex, terminal-openclaw, terminal-deepagents, terminal-clai, gateway-openclaw
  - **Shells**: terminal-shell, terminal-zsh, terminal-python, terminal-ipython, terminal-node, terminal-ollama, terminal-sqlite
  - **Databases**: terminal-mysql, terminal-psql, terminal-turso, terminal-redis, terminal-mongo
  - **Remote/Infra**: terminal-ssh (`ssh {host}`, category REMOTE), terminal-kubectl, terminal-terraform
  - **Containers**: container, container-executor
  - **WASM**: terminal-wasmtime, terminal-wasmer
  - **Applications**: application-gimp, application-inkscape, application-blender, application-vscode, application-penpot, application-grafana, application-pycharm, application-mdinject, application-porkbun-dns, application-porkbun-domain, application-synxis-crs, application-synxis-pms, application-graphics, application-n8n, application-neo4j
  - **In-process**: in-process-nanobot, in-process-nanobot-loop
- **Worker categories**: AI_ASSISTANT, REMOTE, SHELL, CONTAINER, APPLICATION, etc.

### Session-Buddy Integration
- **Session-Buddy process**: Running on port **8678** (PID 60943, project at `/Users/les/Projects/session-buddy`)
- **Mahavishnu config**: `session_buddy_url: "http://localhost:8678/mcp"`, integration enabled for worker pools and result storage
- **Scope**: Session-Buddy currently tracks **nanobot terminal sessions** only (workspace, shell type, PID, hostname). Does NOT track Slack or Signal sessions yet.
- **Quality score**: 60/100 (as of 2026-04-07) — recommendations: increase test coverage, add docs/tests/CI-CD
- **Skill file**: `/Users/les/Projects/mahavishnu/skills/session-buddy/SKILL.md`
- **Multi-channel spec**: `/Users/les/Projects/mahavishnu/docs/plans/session-buddy-multi-channel-spec.md` (10399 bytes, updated 2026-04-07)
- **SB version**: 0.14.8 (as of pyproject.toml), build system: hatchling, requires-python >=3.13
- **SB HTTP API**: Only `/health`, `/healthz`, `/metrics` custom routes via FastMCP/Starlette. **NO REST endpoints for sessions** — session tracking is MCP-only currently. Adding HTTP routes is trivial via `@mcp.custom_route()`.
- **SB entry_points**: None defined yet — clean slate for nanobot hook registration
- **SB framework**: FastMCP (on Starlette), no Flask/Django

## Nanobot — Version & Source

### Version Status
- **Installed**: **v0.1.5** (upgraded 2026-04-07 via `uv tool install nanobot-ai`)
- **Previous**: v0.1.4.post6
- **Installed path**: `/Users/les/.local/share/uv/tools/nanobot-ai/lib/python3.13/site-packages/`
- **Upstream repo**: `HKUDS/nanobot` (38.3k stars) — https://github.com/HKUDS/nanobot
- **User's fork**: `lesleslie/nanobot` — created 2026-04-07 via `gh repo fork HKUDS/nanobot`
- **Local clone**: `/Users/les/Projects/nanobot` (cloned from fork)
- **GitHub auth**: `lesleslie` account with `repo` scope, HTTPS protocol
- **PATH warning**: `/Users/les/.local/bin` not on PATH — run `export PATH="/Users/les/.local/bin:$PATH"` or `uv tool update-shell`

### v0.1.5 New Features (NOW INSTALLED)
- **`CompositeHook`** — fan-out hook with per-hook error isolation (async methods catch/log exceptions)
- **`_LoopHookChain`** — inject custom hooks into the agent loop alongside core `_LoopHook`
- **`Dream` memory** — two-stage background consolidation (Phase 1: extract, Phase 2: synthesize), configurable via `DreamConfig`
- **`history.jsonl`** — migrated from Markdown `HISTORY.md`, with cursor-based processing
- **Agent SDK** — programmatic agent interface
- **Sandbox** — `bwrap` backend for exec tool
- **Jinja2 response templates**
- **Sturdier long-running tasks** — core runtime hardening
- **`GitStore`** — tracks SOUL.md, USER.md, memory/MEMORY.md in git
- **New deps**: dulwich, jinja2, markupsafe

### ⚠️ CRITICAL: Hook Injection Gap in v0.1.5
- **`hooks=` param exists on `AgentLoop.__init__`** but NO command (gateway, agent, serve) passes it
- **No config field**, no `entry_points` group, no env var for hook discovery
- **`AgentHookContext` lacks routing data** — no channel, chat_id, session_key, sender_id, or message_id. Internal `_LoopHook` has this data but doesn't expose it.
- **Routing data via contextvars**: Confirmed as approach — thread routing info from `loop.py` to `AgentHookContext` without circular imports
- **Channel plugins are NOT viable** for passive message observation across channels — they're I/O adapters that only see their own channel's traffic
- **`MessageBus` is a simple queue** (not pub/sub) — no interceptor pattern
- **Minimal PR needed**: ~40 lines — add `entry_points(group="nanobot.hooks")` discovery (mirroring existing `channels/registry.py`), extend `AgentHookContext` with routing fields, wire into `commands.py` call sites
- **Review document**: `/Users/les/Projects/mahavishnu/docs/reviews/nanobot-hook-review-1.md`
- **Hooks fire on every agent loop execution** (user messages, cron, heartbeat, system/subagent) but NOT on Dream consolidation
- **`CompositeHook` error isolation**: async methods catch/log exceptions, but NOT for `finalize_content` (pipeline — exceptions propagate)
- **contextvars recommended** for routing data (cleaner than modifying AgentRunSpec) — **confirmed as implementation approach**

### Phase 2 Hook Discovery PR — Pushed
- **Branch**: `feat/hook-discovery` (local clone at `/Users/les/Projects/nanobot`)
- **PR**: #2901 — entry_points discovery + 8 unit tests
- **Scope**: `entry_points(group="nanobot.hooks")` discovery + routing data via contextvars
- **Implementation**: 4 files, ~50 lines — mirrors existing `channels/registry.py` pattern
- **Status**: ✅ Committed and pushed to fork

### Session-Buddy Path Validation Bug — Fixed
- **Was**: SB `track_session_start` rejected paths outside `/Users/les/Projects/session-buddy` — path validation too restrictive
- **Fix**: Commit f39e8592 — `_setup_working_directory` uses simple resolve+exists+is_dir instead of restrictive base-dir validation

### Matrix Channel — Build Blocked
- **`nanobot-ai[matrix]` install FAILS** — `python-olm` v3.2.16 won't compile on macOS with newer clang
- **Root cause**: `lib/list.hh:106` — `const` variable assignment rejected by modern clang (C++11 strict)
- **Dependency chain**: `nanobot-ai[matrix]` → `matrix-nio[e2e]` → `python-olm` (C++ crypto for E2EE)
- **cmake is installed** at `/usr/local/bin/cmake` (v4.3.1) — not the problem
- **`python-olm` not available via Homebrew**
- **Options**: (1) Skip E2EE — install matrix-nio without [e2e], basic Matrix works; (2) Wait for upstream fix; (3) Use older compiler
- **Status**: ⛔ SKIPPED — user doesn't use Matrix (decided 2026-04-07)

### Session-Buddy Integration — Revised Plan (2026-04-07)
- **Decision: Skill now, PR soon, plugin after PR merges**
- **Phase 1 (Now)**: Skill-based approach — LLM reads SKILL.md, calls SB MCP tools. Works on v0.1.5 with no fork. One skill covers all channels (terminal, Slack, Signal). **Status: ✅ Working** — SKILL.md at 77 lines, channel-agnostic (fires on agent loop, not per-channel).
- **Phase 2 (Soon)**: PR to nanobot for `entry_points(group="nanobot.hooks")` discovery + `AgentHookContext` routing fields. **Status: ✅ Pushed** — PR #2901, branch `feat/hook-discovery` with 4 files/~50 lines + 8 unit tests. Local clone at `/Users/les/Projects/nanobot`.
- **Phase 3 (After PR)**: Convert skill logic to proper `AgentHook` plugin package — registers via entry_points, guaranteed execution, background asyncio tasks for heartbeats. **Status: ❌ Blocked on Phase 2**
- **SB server-side work needed regardless**: New `ChannelSessionEvent` schema (v2.0), new MCP tools (`track_channel_session()`, `track_channel_heartbeat()`), storage fields
- **One plugin replaces entire skill** — covers terminal + all channels, no reason to keep skill approach once hooks are injectable
- **Plugin packaging**: Include IN session-buddy package (NOT separate PyPI). `pyproject.toml` entry: `[project.entry-points."nanobot.hooks"] session-buddy = "session_buddy.nanobot_hook:SessionTrackingHook"`. Optional dep: `pip install session-buddy[nanobot]`
- **Hybrid approach recommended** (from Review #2): Skill for user-facing features (checkpoints, reminders) + plugin for mechanical bookkeeping (heartbeats, message counting, idle timeout). Both share same `session_id` format — migration is seamless.
- **Skills survive context compaction** — skills are in system prompt, not conversation history. State persists in MEMORY.md via Dream. NOT a reliability concern.
- **Key insight**: SB skill is already channel-agnostic — if user messages from Slack, session tracking works the same as terminal. The missing piece is automatic hook-based tracking (no reliance on LLM reading skill and deciding to call tools).

### Review Documents
- **Hook Architecture Review #1**: `/Users/les/Projects/mahavishnu/docs/reviews/nanobot-hook-review-1.md` (460 lines, 18653 bytes)
- **Skill vs Plugin Comparison Review #2**: `/Users/les/Projects/mahavishnu/docs/reviews/nanobot-skill-vs-plugin-review-2.md`

### Nanobot Channel Architecture (from latest source)
- **`BaseChannel`** (`nanobot/channels/base.py`): ABC with `start()`, `stop()`, `send()`, `send_delta()`, `_handle_message()`, `login()`, `transcribe_audio()`, `is_allowed()`, `supports_streaming`, `default_config()`, `is_running`
- **`ChannelManager`** (`nanobot/channels/manager.py`): Initializes enabled channels, dispatches outbound with retry/exponential backoff, coalesces stream deltas
- **`MessageBus`** (`nanobot/bus/`): `InboundMessage` → `OutboundMessage` via async queue
- **`InboundMessage fields`: `channel`, `sender_id`, `chat_id`, `content`, `timestamp`, `media`, `metadata` (free-form dict), `session_key_override`
  - `session_key` property: `session_key_override or f"{channel}:{chat_id}"`
- **Built-in channels**: slack, discord, telegram, whatsapp, matrix, dingtalk, feishu, mochat, qq, wecom, weixin, email
- **Slack channel** (`slack.py`): Socket Mode, thread-scoped session keys (`slack:{chat_id}:{thread_ts}` for group, no override for DMs), reaction emoji (eyes/check_mark), markdown→mrkdwn conversion, group_policy (open/mention/allowlist), DM policy (open/allowlist)
- **`SessionManager`** (`nanobot/session/manager.py`): Per-session JSONL files in `{workspace}/sessions/`, in-memory cache, legacy session migration, consolidation support
- **`AgentHook`** (`nanobot/agent/hook.py`): Lifecycle hooks: `before_iteration`, `on_stream`, `on_stream_end`, `before_execute_tools`, `after_iteration`, `finalize_content`. `AgentHookContext` includes `tool_events` field.
- **`AgentLoop`** (`nanobot/agent/loop.py`): Dispatches inbound messages as asyncio tasks, per-session serial + cross-session concurrent (via session locks + concurrency gate), streaming support via `_LoopHook`
- **`ChannelsConfig`**: `send_progress: true`, `send_tool_hints: false`, `send_max_retries: 3`, `transcription_provider: "groq"`, `model_config = ConfigDict(extra="allow")` — arbitrary channel config sections allowed without forking
- **Plugin registration**: `[project.entry-points."nanobot.channels"]` in pyproject.toml
- **Discovery**: `discover_all()` merges built-in channels (pkgutil scan) with external plugins (entry_points). Built-ins take priority.

### Nanobot Config Schema — Key Fields
- **`AgentDefaults`**: model, provider ("auto"), max_tokens (8192), context_window_tokens (65536), temperature (0.1), max_tool_iterations (200), reasoning_effort, timezone, dream config
- **`DreamConfig`**: interval_h (2), cron (legacy), model_override, max_batch_size (20), max_iterations (10)
- **`HeartbeatConfig`**: enabled (true), interval_s (30min), keep_recent_messages (8)
- **`ProvidersConfig`**: custom, azure_openai, anthropic, openai, openrouter, deepseek, groq, zhipu, dashscope, vllm, ollama, ovms, gemini, moonshot, minimax, mistral, stepfun, xiaomi_mimo, aihubmix, siliconflow, volcengine, volcengine_coding_plan, byteplus, byteplus_coding_plan, openai_codex (OAuth), github_copilot (OAuth), qianfan
- **`MCPServerConfig`**: type (stdio/sse/streamableHttp), command, args, env, url, headers, tool_timeout (30s), enabled_tools
- **`ToolsConfig`**: web (WebToolsConfig), exec (ExecToolConfig with sandbox: "bwrap"), restrict_to_workspace, mcp_servers, ssrf_whitelist

### Nanobot Memory System (v0.1.5)
- **`MemoryStore`**: Pure file I/O for MEMORY.md, history.jsonl, SOUL.md, USER.md
- **Legacy migration**: HISTORY.md → history.jsonl (automatic, one-time)
- **`Consolidator`**: Lightweight memory consolidation
- **`Dream`**: Two-stage background memory processing (Phase 1: extract, Phase 2: synthesize via agent run)

### Slack Integration
- **No dedicated Vish Slack bot or slash commands** — all Mahavishnu commands route through nanobot gateway's Slack adapter
- To execute Vish commands from Slack, user asks nanobot (in Slack) which calls Mahavishnu MCP tools
- A dedicated Slack bot for direct Vish commands would need to be built

### Slack Progress Indication Gap
- **User prefers progress updates in Slack** for long-running operations
- **Known gap**: Slack adapter goes silent between tool calls until final response — no streaming progress
- **Typing indicator** only covers LLM thinking time, NOT tool execution duration
- **Emoji reactions** (👀 eyes / ✅ check_mark) are supported by nanobot's `slack.py` but not wired up by default in current config
- **`send_progress: true`** exists in `ChannelsConfig` but doesn't solve the tool-execution silence problem

### Mahavishnu Config Structure
- Main config: `settings/mahavishnu.yaml`
- Additional configs: `settings/models.yaml`, `settings/embeddings.yaml`, `settings/repos.yaml`, `settings/ecosystem.yaml`
- Worker pool types: mahavishnu, session-buddy, kubernetes
- Routing strategy: least_loaded
- OpenTelemetry: metrics and tracing enabled
- OTelStorage (Postgres/pgvector): currently disabled (`enabled: false`)

## Projects & Decisions

- **CCR (Claude Code Router)**: Routes Claude Code to z.ai via Anthropic format; will route through TensorZero
- **Oneiric**: Has `OTelStorageAdapter` (Postgres/pgvector) and `PostgresDatabaseAdapter` (asyncpg); OTelStorageAdapter to be replaced with Tempo
- **Vish**: NanobotWorker instances that will route through TensorZero
- **Nanobot**: Will route through TensorZero gateway

## Power Trio Review — TensorZero Plan v3.0 (2026-04-07)

### 8 Must-Fix Errors Found
1. ~~**Config**: `type = "openai-compatible"` → must be `type = "openai"` (5 occurrences, L271/281/291/321/331)~~ ✅ Fixed
2. ~~**Config**: `[gateway.export.prometheus]` section doesn't exist — remove it~~ ✅ Fixed
3. **Config**: `[gateway.export.otlp.traces] endpoint=` field invalid — use `enabled = true` + env var `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
4. **Config**: Missing `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` in TensorZero LaunchAgent env vars
5. **Ops**: Grafana port is 3030, not 3035 — fix all 3 references in plan (L794, 802, 808)
6. **Ops**: Grafana datasource provisioning path not scanned — use HTTP API or enable provisioning in grafana.ini
7. **Security**: Duplicate port 4318 row in port map (L551–552)
8. **Security**: Components table conflates query gRPC (3201) and OTLP gRPC (4317)

### Key Warnings
- Anthropic `api_base` may cause double `/messages` path (needs testing)
- Missing `OTEL_TRACES_EXPORTER=otlp` in Claude Code env vars
- CCR lists GLM-4.5V, GLM-4.6V but no model definitions exist
- Case-sensitive model names (`glm-4.7` vs `GLM-4.7`) — footgun
- API key creation circular dependency between Phase 1 and Phase 4 (UI)
- Tempo build missing `CGO_ENABLED=0`, `-mod vendor`, version ldflags
- LaunchAgents missing `LimitLoadToSessionType`, `ThrottleInterval`, `ProcessType`
- `launchctl load` deprecated — prefer `launchctl bootstrap gui/$(id -u)`
- Tempo build time estimate optimistic (5–15 min more realistic)
- Postgres tensorzero DB will grow monotonically (no pg_cron for cleanup)
- Log rotation still TODO — newsyslog recipe available

## Tools & External Services
- **Context7**: MCP server for fetching up-to-date library documentation (context7.com) — indexes thousands of open-source libraries, serves via MCP. Has Claude Code client docs. Useful for checking latest APIs instead of relying on training data.