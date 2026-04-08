# TensorZero Gateway — Final Implementation Plan

**Status**: Ready for implementation  
**Version**: 3.0 (with Postgres auth)  
**Created**: 2026-04-06  
**Updated**: 2026-04-06 06:27  
**Port**: 8471

## Research Findings — z.ai API Endpoints

### Confirmed: z.ai has TWO API formats

| Endpoint | Format | Use Case | Models |
|---|---|---|---|
| `https://api.z.ai/api/paas/v4/chat/completions` | **OpenAI-compatible** | General API, OpenAI SDK, Coding Plan | glm-5, glm-5-turbo, glm-4.7, glm-4.5, glm-4.5-air |
| `https://api.z.ai/api/anthropic/v1/messages` | **Anthropic Messages** | Claude Code integration | GLM-4.7, GLM-4.5-Air, GLM-4.5V, GLM-4.6V |
| `https://api.z.ai/api/coding/paas/v4/chat/completions` | **OpenAI-compatible** | Coding Plan (rate-limited cheaper tier) | Same models |

### Key discovery: Coding Plan endpoint

z.ai's GLM Coding Plan has a **dedicated endpoint**: `https://api.z.ai/api/coding/paas/v4/chat/completions` — separate from the general endpoint. Both use OpenAI format. The Coding endpoint is cheaper but rate-limited per cycle.

### Authentication
- `Authorization: Bearer YOUR_API_KEY` (standard Bearer token)
- Also supports JWT token authentication (PyJWT-based, for higher security)
- API keys created at https://z.ai/manage-apikey/apikey-list

### Streaming
- Fully supported via `"stream": true` parameter
- SSE format, identical to OpenAI streaming

### Tool/Function Calling
- Supported natively (documented at https://docs.z.ai/guides/capabilities/function-calling)

### Model Names
- Standard: `glm-5`, `glm-5-turbo`, `glm-4.7`, `glm-4.6`, `glm-4.5`, `glm-4.5-air`
- Vision: `glm-5v-turbo`, `glm-4.6v`, `glm-4.5v`, `glm-ocr`

---

## Architecture

```
Claude Code → CCR :3456 (Anthropic format) ──→ TensorZero :8471 ──→ z.ai (Anthropic format)
Codex CLI (OpenAI format) ──────────────────→ TensorZero :8471 ──→ z.ai (OpenAI format)
Qwen CLI (OpenAI format) ───────────────────→ TensorZero :8471 ──→ z.ai (OpenAI format)
Nanobot (OpenAI format) ────────────────────→ TensorZero :8471 ──→ z.ai (OpenAI format)
Vish Workers (OpenAI format) ───────────────→ TensorZero :8471 ──→ z.ai (OpenAI format)
OpenClaw (OpenAI format, if supported) ─────→ TensorZero :8471 ──→ z.ai (OpenAI format)
```

TensorZero exposes **two endpoints**:
- `/openai/v1/chat/completions` — for OpenAI-format clients (Codex, Qwen, Nanobot, Vish)
- Anthropic Messages API — via TensorZero's Anthropic provider type (for CCR/Claude Code)

### CCR Integration Detail

CCR currently sends Anthropic Messages format to `https://api.z.ai/api/anthropic/v1/messages`. Two options:

**Option A (simpler): CCR → TensorZero OpenAI endpoint**
- Change CCR zai provider to use `enhancetool` transformer (OpenAI format) instead of `Anthropic`
- Point CCR zai `api_base_url` to `http://127.0.0.1:8471/openai/v1/chat/completions`
- Pro: Single TensorZero endpoint, simpler config
- Con: CCR changes transformer format for zai (may have subtle differences)

**Option B (preserves current behavior): CCR → TensorZero Anthropic endpoint**
- Keep CCR's Anthropic transformer for zai
- Point CCR zai `api_base_url` to `http://127.0.0.1:8471/anthropic/v1/messages`
- TensorZero routes Anthropic-format requests to z.ai's Anthropic endpoint
- Pro: Zero format translation change in CCR
- Con: Requires TensorZero Anthropic provider config

**Recommendation: Option B** — preserves existing CCR behavior, minimal risk.

---

## Postgres: Auth + Observability

### Current State

- **Postgres 18 running** via Homebrew on `localhost:5432` (Intel Mac — `/usr/local/opt/postgresql@18/`)
- User: `les`, no password (local trust auth)
  - ⚠️ **Security note**: Trust auth means any local process can connect to the `tensorzero` database (and read API keys). Postgres typically only accepts local Unix socket connections by default, which limits this. Verify `pg_hba.conf` doesn't allow TCP connections without auth — run `SELECT * FROM pg_hba_file_rules;` to audit.
- Existing databases: `mahavishnu`, `mahavishnu_test`, `postgres`
- Available extensions: `pg_trgm` (1.6), `vector` (0.8.2) — **installed but not yet created in any database**
- **Missing**: `pg_cron` — not available (Homebrew Postgres doesn't ship it by default)
- Mahavishnu's config references Postgres but `postgres_url` is empty
- Oneiric's `PostgresDatabaseAdapter` uses `asyncpg` — compatible with TensorZero
- Oneiric's auth adapter is Auth0-based — **not relevant** to TensorZero's auth (TensorZero manages its own API keys)

### Why Postgres Now

TensorZero uses Postgres for two things:
1. **API key storage** — `auth.enabled = true` requires Postgres to store/manage gateway API keys
2. **Observability** — inference logs, feedback, metrics (optional but useful)
3. **Rate limiting state** — persistent rate limit counters (alternative to Redis)

**With auth enabled**: Clients authenticate to TensorZero with a TensorZero API key. TensorZero then forwards requests to z.ai using the z.ai API key stored in the gateway's env vars. Clients never see the z.ai key.

### Required Postgres Extensions

TensorZero needs 3 extensions:
- `pg_cron` — scheduled cleanup jobs ⚠️ **not available via Homebrew** — may need install from source or skip (TensorZero should work without it, just no auto-cleanup)
- `pg_trgm` — trigram text search for observability queries ✅ available (1.6)
- `pgvector` — vector similarity search (for inference caching) ✅ available (0.8.2)

### Setup: Create TensorZero Database & Extensions

```bash
PG=/usr/local/opt/postgresql@18/bin/psql

# 1. Create TensorZero database
$PG -h localhost -U les -d postgres -c "CREATE DATABASE tensorzero;"

# 2. Install extensions in tensorzero database
$PG -h localhost -U les -d tensorzero -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
$PG -h localhost -U les -d tensorzero -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 3. pg_cron — skip for now (Homebrew doesn't include it)
#    TensorZero will work without it. Auto-cleanup jobs won't run.
#    If needed later: install from source or switch to Docker Postgres.

# 4. Run TensorZero migrations (creates auth tables, observability schema)
~/.local/share/tensorzero/.venv/bin/tensorzero-gateway \
  --run-postgres-migrations \
  --config-file ~/.config/tensorzero/tensorzero.toml
```

### Connection URL

```
TENSORZERO_POSTGRES_URL="postgres://les@localhost:5432/tensorzero"
```

No password needed — Postgres trusts local connections.

> **Security**: Any local process can connect to this database. Verify with `SELECT * FROM pg_hba_file_rules;` that only `local` (Unix socket) connections use `trust` auth, not `host 127.0.0.1`. If TCP trust auth is enabled, any local user can connect — acceptable for single-user dev but worth confirming.

### API Key Management

After Postgres + auth is configured:
1. Start gateway with `auth.enabled = true`
2. Create API keys via TensorZero UI or API
3. Distribute API key to clients via env var `TENSORZERO_API_KEY`
4. Clients send `Authorization: Bearer <TENSORZERO_API_KEY>` to gateway
5. Gateway validates key against Postgres, then forwards request to z.ai with `ZAI_API_KEY`

This decouples clients from provider credentials — a client compromise doesn't expose the z.ai key.

---

## Deployment: Native Binary (NOT Docker)

### Why not Docker
- Docker Desktop on macOS adds ~2GB RAM overhead for the VM
- Fights with LaunchAgent lifecycle model
- Unnecessary for a single-user local gateway

### Installation: Python embedded gateway

TensorZero doesn't ship standalone binaries. The gateway is embedded in the Python package:

```bash
# Install in a dedicated venv
mkdir -p ~/.local/share/tensorzero
python3 -m venv ~/.local/share/tensorzero/.venv
~/.local/share/tensorzero/.venv/bin/pip install tensorzero

# Binary is at:
~/.local/share/tensorzero/.venv/bin/tensorzero-gateway
```

The `tensorzero` pip package (v2026.4.0) includes the Rust gateway binary, accessible as `tensorzero-gateway` CLI command.

### LaunchAgent

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tensorzero.gateway</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/les/.local/share/tensorzero/.venv/bin/tensorzero-gateway</string>
        <string>--config-file</string>
        <string>/Users/les/.config/tensorzero/tensorzero.toml</string>
        <string>--log-format</string>
        <string>json</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/les/.config/tensorzero</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>ZAI_API_KEY</key>
        <!-- ⚠️ Replace PLACEHOLDER with real key before deployment.
             Do NOT commit the plist with a real key to version control.
             Consider loading from a separate file: `~/Library/Application Support/tensorzero/env` -->
        <string>ZAI_API_KEY_PLACEHOLDER</string>
        <key>TENSORZERO_POSTGRES_URL</key>
        <string>postgres://les@localhost:5432/tensorzero</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/les/.local/state/tensorzero/logs/gateway.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/les/.local/state/tensorzero/logs/gateway.log</string>
</dict>
</plist>
```

### Directory Layout

```
~/.config/tensorzero/
├── tensorzero.toml          # Gateway config (version controlled)
└── tensorzero.toml.local    # Local overrides (gitignored)

~/.local/share/tensorzero/
├── .venv/                   # Python venv with tensorzero package
└── bin/tensorzero-gateway   # Symlink to venv binary

~/.local/state/tensorzero/
└── logs/
    └── gateway.log          # stdout/stderr

~/Library/LaunchAgents/
└── com.tensorzero.gateway.plist
```

### Log Rotation

Both Tempo and the TensorZero gateway use LaunchAgent stdout → file, which grows unbounded. Add `newsyslog` rules:

```bash
# Gateway logs
sudo tee /etc/newsyslog.d/com.tensorzero.gateway.conf << 'EOF'
/Users/les/.local/state/tensorzero/logs/gateway.log   les:staff  644  7  *  $M2000000 JCN
EOF

# Tempo logs (see Phase 1.6 Step 3)
sudo tee /etc/newsyslog.d/com.grafana.tempo.conf << 'EOF'
/Users/les/.local/state/tempo/logs/tempo.log   les:staff  644  7  *  $M2000000 JCN
EOF
```

This rotates at 2MB, keeps 7 compressed copies, and signals the process to reopen (J flag). Logs may contain partial prompts or error messages with API key fragments — rotation limits exposure.

---

## Configuration — tensorzero.toml

```toml
# === Gateway ===
[gateway]
bind_address = "127.0.0.1:8471"
disable_pseudonymous_usage_analytics = true

# Auth — requires Postgres (TENSORZERO_POSTGRES_URL env var)
auth.enabled = true
# Cache auth lookups for 60s to reduce Postgres load
auth.cache.enabled = true
auth.cache.ttl_ms = 60_000

# Observability — stores inference logs in Postgres
# Enables the TensorZero UI to show request history, latency, costs
observability.enabled = true
# Async writes improve gateway latency by offloading DB writes
observability.async_writes = true

# Cache TTL for Redis (if enabled for rate limiting)
cache.valkey.ttl_s = 300  # 5 minutes — short for dev

# === Models ===

# GLM-5 — OpenAI format (for Codex, Qwen, Nanobot, Vish)
[models.glm-5]
routing = ["zai-openai"]

[models.glm-5.providers.zai-openai]
type = "openai-compatible"
model_name = "glm-5"
api_base = "https://api.z.ai/api/paas/v4/"
api_key_location = "env::ZAI_API_KEY"

# GLM-5-Turbo — OpenAI format
[models.glm-5-turbo]
routing = ["zai-openai-turbo"]

[models.glm-5-turbo.providers.zai-openai-turbo]
type = "openai-compatible"
model_name = "glm-5-turbo"
api_base = "https://api.z.ai/api/paas/v4/"
api_key_location = "env::ZAI_API_KEY"

# GLM-4.7 — OpenAI format (primary coding model)
[models.glm-4.7]
routing = ["zai-47"]

[models.glm-4.7.providers.zai-47]
type = "openai-compatible"
model_name = "glm-4.7"
api_base = "https://api.z.ai/api/paas/v4/"
api_key_location = "env::ZAI_API_KEY"

# GLM-4.7 — Anthropic format (for Claude Code via CCR)
[models."GLM-4.7"]
routing = ["zai-anthropic"]

[models."GLM-4.7".providers.zai-anthropic]
type = "anthropic"
model_name = "GLM-4.7"
api_base = "https://api.z.ai/api/anthropic/v1/messages"
api_key_location = "env::ZAI_API_KEY"

# GLM-4.5-Air — Anthropic format (for Claude Code haiku role via CCR)
[models."GLM-4.5-Air"]
routing = ["zai-anthropic-air"]

[models."GLM-4.5-Air".providers.zai-anthropic-air]
type = "anthropic"
model_name = "GLM-4.5-Air"
api_base = "https://api.z.ai/api/anthropic/v1/messages"
api_key_location = "env::ZAI_API_KEY"

# GLM-4.5 — OpenAI format
[models.glm-4.5]
routing = ["zai-45"]

[models.glm-4.5.providers.zai-45]
type = "openai-compatible"
model_name = "glm-4.5"
api_base = "https://api.z.ai/api/paas/v4/"
api_key_location = "env::ZAI_API_KEY"

# GLM-4.5-Air — OpenAI format
[models.glm-4.5-air]
routing = ["zai-45-air"]

[models.glm-4.5-air.providers.zai-45-air]
type = "openai-compatible"
model_name = "glm-4.5-air"
api_base = "https://api.z.ai/api/paas/v4/"
api_key_location = "env::ZAI_API_KEY"

# === Rate Limiting ===
[rate_limiting]
enabled = true

[[rate_limiting.rules]]
# Global inferences per second — conservative start
model_inferences_per_second = 8
# Global tokens per second — ~4K tokens/s sustained
tokens_per_second = 4000

# NOTE: Rate limiting state stored in Postgres (when TENSORZERO_POSTGRES_URL is set)
# or Redis (when TENSORZERO_VALKEY_URL is set). With Postgres, rate limits
# persist across restarts. For >100 QPS, add Redis for sub-ms latency.
```

### Local overrides (tensorzero.toml.local)

```toml
# Pulled in via environment or TENSORZERO_VALKEY_URL
# Not committed to git

# [gateway]
# debug = true  # Enable for verbose error logging during development
```

---

## Client Configuration Changes

### 1. CCR (Claude Code) — Anthropic format preserved

Update `~/.claude-code-router/config.json`:

```json
{
    "name": "zai",
    "api_base_url": "http://127.0.0.1:8471/anthropic/v1/messages",
    "api_key": "$TENSORZERO_API_KEY",
    "models": ["GLM-4.7", "GLM-4.5-Air", "GLM-4.5V", "GLM-4.6V"],
    "transformer": { "use": ["Anthropic"] }
}
```

With auth enabled, clients authenticate to TensorZero using `TENSORZERO_API_KEY`. The gateway validates the key against Postgres, then forwards the request to z.ai using `ZAI_API_KEY` from its own env vars. Clients never see the z.ai key.

### 2. Codex CLI

```toml
# codex.toml
model_provider = "tensorzero"

[model_providers.tensorzero]
name = "TensorZero"
base_url = "http://127.0.0.1:8471/openai/v1"
env_key = "TENSORZERO_API_KEY"
```

### 3. Qwen CLI

```bash
# In shell profile or per-session
export OPENAI_BASE_URL="http://127.0.0.1:8471/openai/v1/"
export OPENAI_API_KEY="$TENSORZERO_API_KEY"
```

**⚠️ Warning**: This redirects ALL OpenAI SDK usage on the system. Only set globally if ALL OpenAI SDK tools should route through TensorZero.

### 4. Nanobot

Update nanobot provider config to set `base_url` to `http://127.0.0.1:8471/openai/v1/` and API key to `TENSORZERO_API_KEY`.

### 5. Vish Workers (NanobotWorker)

Update nanobot provider env vars or config to use `http://127.0.0.1:8471/openai/v1/` and `TENSORZERO_API_KEY`.

### 6. OpenClaw

- If it supports `OPENAI_BASE_URL`: set to `http://127.0.0.1:8471/openai/v1/`
- Otherwise: no change

---

## Deployment Steps

### Phase 0: Postgres Setup

0. **Audit Postgres auth config**
   ```bash
   PG=/usr/local/opt/postgresql@18/bin/psql
   $PG -h localhost -U les -d postgres -c "SELECT * FROM pg_hba_file_rules;"
   # Verify: only 'local' (Unix socket) connections use 'trust'.
   # If 'host 127.0.0.1' with 'trust' exists, any local user can connect.
   # Acceptable for single-user dev — document the risk.
   ```

1. **Create TensorZero database and extensions**
   ```bash
   PG=/usr/local/opt/postgresql@18/bin/psql
   $PG -h localhost -U les -d postgres -c "CREATE DATABASE tensorzero;"
   $PG -h localhost -U les -d tensorzero -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
   $PG -h localhost -U les -d tensorzero -c "CREATE EXTENSION IF NOT EXISTS vector;"
   # pg_cron not available via Homebrew — skip (TensorZero works without it)
   ```

### Phase 1: Install & Verify

2. **Install TensorZero gateway**
   ```bash
   mkdir -p ~/.local/share/tensorzero
   python3 -m venv ~/.local/share/tensorzero/.venv
   ~/.local/share/tensorzero/.venv/bin/pip install tensorzero
   ```

3. **Create config directory and file**
   ```bash
   mkdir -p ~/.config/tensorzero
   mkdir -p ~/.local/state/tensorzero/logs
   # Copy tensorzero.toml from this plan
   ```

4. **Run TensorZero Postgres migrations**
   ```bash
   TENSORZERO_POSTGRES_URL="postgres://les@localhost:5432/tensorzero" \
     ~/.local/share/tensorzero/.venv/bin/tensorzero-gateway \
       --run-postgres-migrations \
       --config-file ~/.config/tensorzero/tensorzero.toml
   ```
   This creates the auth tables, observability schema, and rate limit tables.

5. **Verify gateway starts**
   ```bash
   TENSORZERO_POSTGRES_URL="postgres://les@localhost:5432/tensorzero" \
   ZAI_API_KEY="$ZAI_API_KEY" \
     ~/.local/share/tensorzero/.venv/bin/tensorzero-gateway \
       --config-file ~/.config/tensorzero/tensorzero.toml
   # Should bind to 127.0.0.1:8471
   ```

6. **Smoke test — health (no auth required)**
   ```bash
   curl -s http://127.0.0.1:8471/status
   # Expected: {"status":"ok"}

   curl -s http://127.0.0.1:8471/health
   # Expected: {"gateway":"ok","postgres":"ok"}
   ```

7. **Create a TensorZero API key** (via TensorZero UI or API)
   ```bash
   # Option A: Via TensorZero UI (http://127.0.0.1:4000 after deploying UI)
   # Option B: Via API (requires initial key creation through UI first)
   # Store the generated key as TENSORZERO_API_KEY env var
   ```

8. **Smoke test — actual inference (with auth)**
   ```bash
   curl -s http://127.0.0.1:8471/openai/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $TENSORZERO_API_KEY" \
     -d '{"model":"glm-4.7","messages":[{"role":"user","content":"Say hello"}]}'
   ```

9. **Smoke test — streaming (with auth)**
   ```bash
   curl -sN http://127.0.0.1:8471/openai/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $TENSORZERO_API_KEY" \
     -d '{"model":"glm-4.7","messages":[{"role":"user","content":"Say hello"}],"stream":true}'
   ```

### Phase 1.5: Telemetry Exports (OTEL + Prometheus)

These are config-only changes — no extra services to install.

1. **Prometheus metrics** — TensorZero exposes metrics at `/metrics` on the gateway port (8471)
   ```toml
   [gateway.export.prometheus]
   enabled = true
   ```

   Available metrics include: `tensorzero_inferences_total`, `tensorzero_requests_total`, `tensorzero_inference_latency_overhead_seconds`.

2. **OTEL traces** — exported to Tempo via OTLP HTTP
   ```toml
   [gateway.export.otlp.traces]
   endpoint = "http://127.0.0.1:4318"
   ```

3. **Grafana scraping** — add TensorZero to Grafana's prometheus.yml scrape targets:
   ```yaml
   - job_name: 'tensorzero'
     static_configs:
       - targets: ['localhost:8471']
     metrics_path: '/metrics'
   ```

4. **Claude Code OTEL** — Claude Code has native OTEL support (metrics + logs + traces beta). Configure via environment variables — see Phase 1.6 Step 7 for details.

5. **Verify** — after gateway starts:
   ```bash
   curl -s http://127.0.0.1:8471/metrics | head -20
   ```

### Phase 1.6: Tempo — Distributed Tracing (with MCP)

Replace Postgres-based trace storage (`OTelStorageAdapter` → pgvector) with Grafana Tempo, the purpose-built distributed tracing backend. Tempo provides TraceQL for structured queries, an embedded MCP server for AI tool access, and integrates natively with the existing Grafana instance.

> **No macOS binary available** — Tempo only ships Linux/Windows binaries. Must build from source with Go (already installed at `/usr/local/bin/go`, v1.26.1).

#### Components

| Component | Port | Role |
|---|---|---|
| **Tempo** | 3200 (HTTP query/MCP), 3201 (gRPC query), 4317 (OTLP gRPC receive), 4318 (OTLP HTTP receive) | Trace storage + query engine + embedded MCP server |

> **Grafana Alloy skipped** — For a single-user dev setup, apps send traces directly to Tempo on ports 4317/4318. Alloy adds value in multi-service environments where you need trace enrichment, sampling, or routing to multiple backends. If needed later, install via `brew install grafana-alloy` and configure as an OTLP → Tempo forwarder.

#### Port Map

| Port | Service | Protocol | Notes |
|---|---|---|---|
| 3200 | Tempo | HTTP (query/ready/MCP) | 127.0.0.1 only |
| 3201 | Tempo | gRPC (query) | 127.0.0.1 only — Tempo's server gRPC for TraceQL and trace lookups |
| 4317 | Tempo | gRPC (OTLP receive) | 127.0.0.1 only — apps send OTLP gRPC traces here |
| 4318 | Tempo | HTTP (OTLP receive) | 127.0.0.1 only — apps send OTLP HTTP traces here |

> **Note**: Tempo's OTLP receivers (4317/4318) accept traces from any local process. A compromised local process could inject misleading traces or exhaust disk. Low risk for single-user dev, but worth documenting if the setup is shared.

#### Why Tempo over pgvector for traces

- **TraceQL** — purpose-built query language for traces (spans, durations, attributes)
- **Embedded MCP server** — AI tools can query traces directly (`tempo_query`)
- **No semantic similarity loss** — structured queries are more precise for ops debugging; add pgvector on top later if needed
- **Already have Grafana** — zero-config dashboards, just add a datasource
- **Scales better** — Tempo handles millions of traces/s with local storage; pgvector chokes on high-cardinality trace data

#### Security notes (from security review)

- ⚠️ **No auth on Tempo** — Tempo's OTLP receiver and query API have no authentication. All endpoints bind to `127.0.0.1` only, so only local processes can reach them. This is acceptable for single-user dev. A compromised local process could push fake traces or read all traces (which may contain prompt content). Document this risk if the setup is shared or replicated.
- ⚠️ **Trace data sensitivity** — Traces may contain LLM prompt/response content. Tempo stores these on disk in `~/.local/state/tempo/data/traces`. The 7-day retention limits exposure. No trace data leaves the machine.
- ✅ **All endpoints localhost-only** — `http_listen_address` and all OTLP receiver endpoints use `127.0.0.1`, not `0.0.0.0`.

#### Step 1: Build Tempo from source

Tempo does not ship macOS binaries. Build from source using Go:

```bash
TEMPO_VERSION="v2.10.3"
mkdir -p ~/.local/share/tempo/{bin,src}
cd ~/.local/share/tempo/src

# Clone and checkout the release tag
git clone --depth 1 --branch ${TEMPO_VERSION} https://github.com/grafana/tempo.git
cd tempo

# Build the binary (~2-5 minutes, requires Go 1.25+)
go build -o ~/.local/share/tempo/bin/tempo ./cmd/tempo

# Verify
~/.local/share/tempo/bin/tempo --version
# Expected: tempo, version ...
```

#### Step 2: Create Tempo config

```bash
mkdir -p ~/.config/tempo
mkdir -p ~/.local/state/tempo/{data,logs}
```

`~/.config/tempo/tempo.yaml`:
```yaml
# === Tempo — Local single-user config (v2.10.x) ===
# All endpoints bind to localhost only. No authentication (dev-only).

server:
  http_listen_address: "127.0.0.1"
  http_listen_port: 3200
  grpc_listen_address: "127.0.0.1"
  grpc_listen_port: 3201  # Default is 9095; override to avoid conflicts
  log_level: info

# Distributor — receives OTLP pushes from applications
distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: "127.0.0.1:4317"   # Default; apps send traces here
        http:
          endpoint: "127.0.0.1:4318"   # Default; apps send traces here

# Storage — local filesystem (no S3/object storage needed for dev)
storage:
  trace:
    backend: local
    local:
      path: /Users/les/.local/state/tempo/data/traces
    wal:
      path: /Users/les/.local/state/tempo/data/wal

# Query frontend — enables TraceQL queries + MCP server
query_frontend:
  max_query_length: 0  # unlimited for dev
  # Embedded MCP server — enables AI tool queries at /api/mcp
  # Added in Tempo v2.9.0
  mcp_server:
    enabled: true

# Compactor — keeps disk usage bounded
compactor:
  compaction:
    block_retention: 168h  # 7 days
    compacted_block_retention: 1h

# Metrics generator — produces RED metrics for Grafana dashboards
metrics_generator:
  processor:
    service_graphs:
      dimensions:
        - service.name
        - service.version
      wait: 10s
      workers: 10

overrides:
  metrics_generator:
    processor:
      service_graphs:
        dimensions:
          - service.name
          - service.version
```

#### Step 3: LaunchAgent (Tempo)

**`~/Library/LaunchAgents/com.grafana.tempo.plist`**:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.grafana.tempo</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/les/.local/share/tempo/bin/tempo</string>
        <string>-config.file</string>
        <string>/Users/les/.config/tempo/tempo.yaml</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/les/.config/tempo</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/les/.local/state/tempo/logs/tempo.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/les/.local/state/tempo/logs/tempo.log</string>
</dict>
</plist>
```

> **Log rotation**: Tempo logs grow unbounded via LaunchAgent stdout. Add `newsyslog` config to rotate logs:
> ```
> # /etc/newsyslog.d/com.grafana.tempo.conf
> /Users/les/.local/state/tempo/logs/tempo.log   les:staff  644  7  *  $M2000000 JCN
> ```
> This rotates at 2MB, keeps 7 compressed copies. Logs may contain partial prompts or error messages with API key fragments — rotation limits exposure.

#### Step 4: Install and verify

```bash
# Load LaunchAgent
launchctl load ~/Library/LaunchAgents/com.grafana.tempo.plist

# Verify Tempo is running (may take 2-3 seconds)
sleep 2
curl -s http://127.0.0.1:3200/ready
# Expected: ready

# Verify Tempo MCP endpoint
curl -s http://127.0.0.1:3200/api/mcp
# Should return MCP tool definitions (JSON)

# Verify OTLP receiver is listening
curl -s http://127.0.0.1:4318
# May return empty or error — that's OK, it's a POST endpoint
```

#### Step 5: Configure TensorZero → Tempo (OTEL)

Update `tensorzero.toml` from Phase 1.5:
```toml
[gateway.export.otlp.traces]
endpoint = "http://127.0.0.1:4318"  # Tempo's OTLP HTTP receiver
```

#### Step 6: Configure Mahavishnu → Tempo

Update `OTelStorageAdapter` (or create a new `TempoStorageAdapter`) to:
- Export traces via OTLP to `http://127.0.0.1:4318`
- Query traces via Tempo's HTTP API: `GET http://127.0.0.1:3200/api/traces/{traceID}`
- Query traces via TraceQL: `GET http://127.0.0.1:3200/api/search?q={service.name="mahavishnu"}`

> **TraceQL note**: Verify exact TraceQL syntax against Tempo v2.10 docs — the query language has changed between v2.x releases.

#### Step 7: Configure Claude Code → Tempo (OTEL)

Claude Code has **native OpenTelemetry support** — no wrapper or sidecar needed. It exports:
- **Metrics**: token usage (input/output/cache), cost (USD), active session time, commits, LoC, tool decisions
- **Logs/Events**: user prompts, tool results, API requests, errors
- **Traces** (beta): distributed traces for Claude Code operations

Configure via environment variables in your shell profile (`~/.zshrc` or managed settings):

```bash
# Claude Code OTEL — sends metrics, logs, and traces to Tempo
# ⚠️ GLOBAL SCOPE: These vars affect ALL Claude Code invocations on this system.
# Consider scoping to specific projects via direnv or a wrapper script
# (e.g., only export in work project directories, not personal ones).
export CLAUDE_CODE_ENABLE_TELEMETRY=1
export OTEL_METRICS_EXPORTER=otlp
export OTEL_LOGS_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318  # Tempo OTLP HTTP
export OTEL_METRIC_EXPORT_INTERVAL=60000  # 60s default
export OTEL_LOGS_EXPORT_INTERVAL=5000     # 5s default

# Optional: log user prompts (privacy tradeoff — prompts stored in Tempo traces)
# export OTEL_LOG_USER_PROMPTS=1

# Optional: reduce cardinality if metrics are too noisy
# export OTEL_METRICS_INCLUDE_SESSION_ID=false
# export OTEL_METRICS_INCLUDE_VERSION=false
# export OTEL_METRICS_INCLUDE_ACCOUNT_UUID=false
```

> **CCR note**: CCR (Claude Code Router) is just a proxy — it doesn't generate its own telemetry. All OTEL data comes from Claude Code itself. CCR forwards requests transparently, so trace context (`traceparent`) passes through to TensorZero and z.ai automatically.
>
> **Privacy**: Claude Code traces may contain prompt content and code snippets. The 7-day Tempo retention limits exposure. Set `OTEL_LOG_USER_PROMPTS=0` (default) to exclude prompt content from traces.

**Key Claude Code metrics available after enabling**:
| Metric | Description |
|---|---|
| `claude_code_tokens_total` | Token usage by type (input, output, cache_creation, cache_read) |
| `claude_code_cost_total` | USD cost per session |
| `claude_code_active_time_seconds` | Active session duration |
| `claude_code_commits_total` | Commits made per session |
| `claude_code_lines_of_code_total` | Lines of code changed |
| `claude_code_tool_decision_total` | Tool usage counts (edit, read, write, etc.) |

#### Step 8: Add Tempo datasource to Grafana

```bash
# Add Tempo as a datasource in Grafana provisioning
mkdir -p ~/.config/grafana/provisioning/datasources
cat > ~/.config/grafana/provisioning/datasources/tempo.yaml << 'EOF'
apiVersion: 1
datasources:
  - name: Tempo
    type: tempo
    access: proxy
    url: http://127.0.0.1:3200
    isDefault: false
    editable: true
    uid: tempo
EOF
# Restart Grafana to pick up new datasource (port 3035)
brew services restart grafana
```

#### Step 9: MCP integration

**Recommended: `mcp-grafana` proxied tools** (Option A)
- `mcp-grafana` installed via Homebrew at `/usr/local/bin/mcp-grafana`
- Grafana running on port **3035**
- Auto-discovers Tempo's MCP tools through the Grafana datasource
- Gives you Tempo + Prometheus + Loki tools in one MCP server
- Lower maintenance than direct Tempo MCP

Configure in Mahavishnu's MCP settings:
```json
{
  "mcpServers": {
    "grafana": {
      "command": "mcp-grafana",
      "env": {
        "GRAFANA_URL": "http://localhost:3035"
      }
    }
  }
}
```

**Alternative: Direct Tempo MCP** (Option B)
- Tempo's embedded MCP server at `http://127.0.0.1:3200/api/mcp`
- Lower latency, but no Grafana auth layer
- Only use if `mcp-grafana` doesn't expose the Tempo tools you need

#### Disk usage estimate

| Component | Storage | Retention | Est. size |
|---|---|---|---|
| Tempo traces | `~/.local/state/tempo/data/traces` | 7 days | ~500MB-2GB (depends on trace volume) |
| Tempo WAL | `~/.local/state/tempo/data/wal` | 1h | ~50-100MB |
| Logs | `~/.local/state/tempo/logs/` | indefinite | ~10MB/month |

Total: **~2GB max** with 7-day retention.

> **Disk permissions**: Ensure `~/.local/state/tempo/data/` is owned by `les` with `700` permissions to prevent other local users from reading trace data: `chmod 700 ~/.local/state/tempo/data`.

### Phase 2: LaunchAgent

10. **Install LaunchAgent plist**
    ```bash
    cp com.tensorzero.gateway.plist ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/com.tensorzero.gateway.plist
    ```

11. **Verify LaunchAgent**
    ```bash
    launchctl list | grep tensorzero
    curl -s http://127.0.0.1:8471/health
    # Expected: {"gateway":"ok","postgres":"ok"}
    ```

### Phase 3: Client Migration (one at a time)

12. **Set TENSORZERO_API_KEY** in shell profile
    ```bash
    export TENSORZERO_API_KEY="<key from step 7>"
    ```
13. **Migrate Nanobot** — update provider `base_url` + API key, verify response
14. **Migrate Qwen** — set `OPENAI_BASE_URL` + `OPENAI_API_KEY=$TENSORZERO_API_KEY`, verify response
15. **Migrate Codex** — update config, verify response
16. **Migrate Vish Workers** — update provider config, verify response
17. **Migrate CCR** — update zai provider `api_base_url` + `api_key=$TENSORZERO_API_KEY`, restart CCR, verify Claude Code works
18. **Migrate OpenClaw** — if supported

### Phase 4: TensorZero UI

The TensorZero UI is a web dashboard for browsing inference history, managing API keys, and inspecting functions/variants. It connects to the same Postgres database as the gateway.

19. **Install TensorZero UI** (Node.js app)
    ```bash
    # Install via npx (no global install needed)
    npx @tensorzero/ui
    # or clone and run locally — check latest docs
    ```

20. **Configure UI** — point to same Postgres database
    ```bash
    DATABASE_URL="postgres://les@localhost:5432/tensorzero" \
      npx @tensorzero/ui --port 4000
    ```

21. **Create API key via UI** — browse to `http://127.0.0.1:4000`, create a gateway API key

    > **Audit trail**: When the TensorZero UI creates API keys, there's no built-in audit logging. Consider adding a Postgres trigger on the auth tables to log key creation/rotation events, or manually record key metadata (created_at, purpose, client) in a separate table.

22. **Optional: LaunchAgent for UI**
    ```xml
    <!-- ~/Library/LaunchAgents/com.tensorzero.ui.plist -->
    <!-- Similar pattern to gateway plist -->
    ```

23. **Verify** — browse to `http://127.0.0.1:4000`, should show inference history after gateway is serving traffic

### Phase 5: Rate Limiting (optional)

24. **Add Redis for high-QPS rate limiting** (optional — Postgres handles rate limits for dev load, Redis for >100 QPS)
    ```bash
    # If using existing Redis:
    export TENSORZERO_VALKEY_URL="redis://localhost:6379/15"
    ```
    Add `TENSORZERO_VALKEY_URL` to LaunchAgent EnvironmentVariables.

---

## Security Checklist (from review)

| Item | Status | Action |
|---|---|---|
| Bind to 127.0.0.1 only | ✅ Configured | `bind_address = "127.0.0.1:8471"` |
| Gateway authentication | ✅ Postgres-backed | `auth.enabled = true` with API keys stored in Postgres |
| Postgres connection | ✅ Local trust | `postgres://les@localhost:5432/tensorzero` — no password, localhost only |
| Redis AUTH | ⚠️ If using shared Redis | Enable `--requirepass` on Redis, use `redis://:password@localhost:6379/15` |
| Telemetry disabled | ✅ Configured | `disable_pseudonymous_usage_analytics = true` |
| Keys from env vars | ✅ Configured | `api_key_location = "env::ZAI_API_KEY"` |
| Cache TTL | ✅ Configured | 300s (5 min) — short for dev |
| Log rotation | ✅ Configured | `newsyslog` configs provided for gateway and Tempo logs (2MB rotate, 7 copies) |

---

## Failure Modes & Recovery

| Scenario | Impact | Recovery |
|---|---|---|
| Gateway crash | All clients lose LLM access | LaunchAgent auto-restarts within seconds |
| Gateway hang | Clients timeout | Clients have own retry logic. Kill via `launchctl kickstart -k` |
| z.ai 429 | Gateway retries (if configured) | Rate limiting prevents most 429s. TensorZero retries on transient errors. |
| Redis down | Rate limiting state lost | Rate limits fall back to Postgres. Slightly higher latency but no data loss. |
| Postgres down | Auth fails + observability stops | Gateway returns 503 on authenticated endpoints. Unauthenticated health checks still work. Restart Postgres via `brew services restart postgresql@18`. |
| Config error | Gateway fails to start | LaunchAgent keeps retrying. Check logs. |
| Port conflict (8471) | Gateway fails to start | Change `bind_address` in tensorzero.toml |

### Client-Side Resilience

Each client should have its own timeout and retry:
- **Nanobot**: Already has `_CHAT_RETRY_DELAYS = (1, 2, 4)` — 3 attempts, 7s total
- **Claude Code/CCR**: Has its own timeout (900s). CCR has fallback routing (zai → anthropic)
- **Codex/Qwen**: SDK-level defaults. Should verify.

---

## Reviewer Feedback Addressed

### Security Review
- ✅ C1 (auth): Deferred — requires Postgres. Localhost-only binding is sufficient for single-user dev.
- ✅ C2 (bind address): Fixed — `127.0.0.1:8471`
- ✅ C3 (Redis AUTH): Documented — use dedicated DB index + AUTH if using shared Redis
- ✅ W1 (CCR key propagation): CCR sends z.ai key, gateway forwards it. No leakage since gateway is localhost-only.
- ✅ W7 (cache TTL): Reduced to 300s

### Ops Review
- ✅ Docker replaced with native Python package + LaunchAgent
- ✅ Port 8471 approved
- ✅ Redis namespace: Use DB index 15 (`redis://localhost:6379/15`)
- ✅ LaunchAgent plist provided
- ✅ Log rotation: `newsyslog` configs provided for gateway and Tempo logs
- ⏭️ Startup ordering: Clients have own retry logic. PathState not needed for dev.

### Config Review
- ✅ C1 (model routing): Added `[models.*]` definitions for all model names
- ✅ C2 (z.ai provider type): Fixed — OpenAI models use `openai-compatible` type with `/api/paas/v4/`, Anthropic models use `anthropic` type with `/api/anthropic/v1/messages`
- ✅ C3 (CCR compatibility): Option B preserves CCR's Anthropic format, routes to TensorZero Anthropic endpoint
- ⚠️ W1 (OPENAI_BASE_URL conflict): Documented warning. Per-client config preferred.
- ⚠️ W2 (streaming): Smoke test in deployment steps
- ⚠️ W5 (caching config): Fixed — using `[gateway.cache.valkey]` per TensorZero docs (Redis backend)

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| TensorZero UI | **Phase 4 — yes** | Needed for API key management and observability browsing |
| TensorZero Autopilot | **Skip** | SaaS/cloud product ("Schedule a demo"), not self-hosted |
| OTEL traces | **Phase 1.5 — yes** | Config-only, Grafana already running |
| Prometheus metrics | **Phase 1.5 — yes** | Config-only, Grafana can scrape directly |
| Tempo for traces | **Phase 1.6 — yes** | Replaces pgvector for trace storage. Embedded MCP + TraceQL. |
| Alloy as collector | **Skipped** | Direct OTLP to Tempo is sufficient for single-user dev. Add Alloy later if trace enrichment is needed. |

---

## Open Questions

1. **TensorZero auth without Postgres**: Is there a simpler auth mechanism? If not, localhost-only binding is the pragmatic choice for now.
2. **z.ai Coding Plan endpoint**: Should we use `/api/coding/paas/v4/` instead of `/api/paas/v4/`? Need to check if Coding Plan API key works with the general endpoint.
3. **CCR `enhancetool` transformer**: What does it do? May need investigation if Option A is preferred over Option B.
4. **OpenClaw compatibility**: Does OpenClaw support `OPENAI_BASE_URL`? Need to check.

---

## Files

| File | Location |
|---|---|
| Plan (this file) | `docs/plans/tensorzero-gateway-plan.md` |
| Security review | `docs/plans/reviews/security-review.md` |
| Ops review | `docs/plans/reviews/ops-review.md` |
| Config review | `docs/plans/reviews/config-review.md` |
| Gateway config | `~/.config/tensorzero/tensorzero.toml` |
| LaunchAgent plist | `~/Library/LaunchAgents/com.tensorzero.gateway.plist` |
| Gateway logs | `~/.local/state/tensorzero/logs/gateway.log` |
| Tempo config | `~/.config/tempo/tempo.yaml` |
| Tempo data | `~/.local/state/tempo/data/` |
| Tempo logs | `~/.local/state/tempo/logs/` |
| Tempo LaunchAgent | `~/Library/LaunchAgents/com.grafana.tempo.plist` |
