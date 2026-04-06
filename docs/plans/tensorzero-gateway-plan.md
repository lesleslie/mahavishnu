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

# Cache TTL for Valkey/Redis (if enabled for rate limiting)
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
# or Valkey/Redis (when TENSORZERO_VALKEY_URL is set). With Postgres, rate limits
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

0. **Create TensorZero database and extensions**
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

### Phase 4: Rate Limiting (optional)

19. **Add Redis for high-QPS rate limiting** (optional — Postgres handles rate limits for dev load, Redis for >100 QPS)
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
| Log rotation | ⚠️ TODO | LaunchAgent stdout grows unbounded. Add newsyslog or log rotation. |

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
- ⏭️ Startup ordering: Clients have own retry logic. PathState not needed for dev.
- ⏭️ Log rotation: TODO — add newsyslog config later

### Config Review
- ✅ C1 (model routing): Added `[models.*]` definitions for all model names
- ✅ C2 (z.ai provider type): Fixed — OpenAI models use `openai-compatible` type with `/api/paas/v4/`, Anthropic models use `anthropic` type with `/api/anthropic/v1/messages`
- ✅ C3 (CCR compatibility): Option B preserves CCR's Anthropic format, routes to TensorZero Anthropic endpoint
- ⚠️ W1 (OPENAI_BASE_URL conflict): Documented warning. Per-client config preferred.
- ⚠️ W2 (streaming): Smoke test in deployment steps
- ⚠️ W5 (caching config): Fixed — using `[gateway.cache.valkey]` per TensorZero docs

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
