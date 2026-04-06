# Security Review — TensorZero Gateway Plan

**Reviewer**: Security subagent  
**Date**: 2026-04-06  
**Document reviewed**: `docs/plans/tensorzero-gateway-plan.md`  
**Related files inspected**: `docker-compose.yml`, `~/.claude-code-router/config.json`, environment variables

---

## 🔴 Critical Issues (Must Fix Before Deployment)

### C1. Zero authentication on the TensorZero gateway

**Severity: Critical**  
**Location**: `tensorzero.toml` — no `api_keys` or auth section configured.

The gateway binds on `0.0.0.0:8471` (see C2) with **no authentication whatsoever**. Any process on the machine — or any device on the same network if the firewall allows it — can submit inference requests that consume your **paid** z.ai, Anthropic, and OpenAI API credits. This is equivalent to leaving an open proxy to paid services.

**Evidence**: The plan's client configs confirm the problem:
- Qwen: `OPENAI_API_KEY="none"` — deliberately sends no key.
- Codex: `env_key = "TENSORZERO_API_KEY"` — but TensorZero never validates it.
- CCR: "API key can remain the z.ai key (forwarded through)" — key passed but not checked.

**Fix**: Configure TensorZero's `api_keys` block to require a shared gateway key, and distribute that key to legitimate clients:
```toml
[api_keys]
gateway = ["${TENSORZERO_API_KEY}"]
```
Then have each client send this key. Unauthenticated requests should be rejected with 401.

### C2. Gateway binds 0.0.0.0 — exposes to the network

**Severity: Critical**  
**Location**: `tensorzero.toml` line `gateway_url = "http://0.0.0.0:8471"`

This binds to **all network interfaces**, not just localhost. Combined with C1 (no auth), any device on your LAN or VPN can reach the gateway. This is especially dangerous on a laptop that hops between trusted and untrusted networks (coffee shops, airports, coworking spaces).

Note: the existing `docker-compose.yml` has the same pattern for Redis (0.0.0.0:6379), Postgres (0.0.0.0:5432), and Adminer (0.0.0.0:8080) — those are pre-existing issues that this plan should not replicate.

**Fix**: Change to `gateway_url = "http://127.0.0.1:8471"`. If Docker networking requires 0.0.0.0 internally, bind 0.0.0.0 inside the container but map the Docker port to `127.0.0.1:8471:8471` in the Compose file.

### C3. Unauthenticated Redis accessible to TensorZero cache

**Severity: Critical**  
**Location**: `tensorzero.toml` → `[redis] url = "redis://localhost:6379"`, `docker-compose.yml` Redis service.

The plan enables TensorZero's inference cache (`cache_mode = "on"`) pointing at the shared Redis instance that has **no AUTH** configured (confirmed in `docker-compose.yml` lines 96-97, commented out). This means:

1. **Cached LLM responses** (which contain user prompts, code, and model outputs) are stored in plaintext in an unauthenticated Redis instance.
2. Any process on the machine can `redis-cli GET` and read cached inference data — potentially containing proprietary code, system prompts, or sensitive conversations.
3. Any process can also `redis-cli FLUSHALL` and evict the cache, or `redis-cli SET` to poison it.

**Fix (minimum)**: Enable Redis AUTH (`--requirepass`) and use `redis://:password@localhost:6379` in the TensorZero config.  
**Fix (better)**: Run a separate Redis instance for TensorZero with `appendonly no` (ephemeral, no disk persistence of cached prompts), and isolate it with AUTH + a dedicated password.

---

## 🟡 Warnings (Should Address)

### W1. API key propagation through CCR headers

**Severity: Medium**  
**Location**: Plan § "CCR (Claude Code)" — "API key can remain the z.ai key (forwarded through)."

If CCR forwards the actual `ZAI_API_KEY` in request headers to the TensorZero gateway, the key is visible in:
- TensorZero's access logs (if request logging is enabled)
- Docker container logs (`docker compose logs tensorzero`)
- Any proxy or debugging tool in the path

Even with C1 fixed (gateway auth), having the **upstream provider key** travel alongside requests is unnecessary — TensorZero already has the key from its own environment variable.

**Recommendation**: Have CCR send the TensorZero gateway key instead. The gateway maps requests to its own configured provider keys. CCR should not need to know or send the z.ai key at all.

### W2. CCR logging may capture prompt/response content

**Severity: Medium**  
**Location**: `~/.claude-code-router/config.json` — `"LOG": true`, `"LOG_LEVEL": "info"`.

CCR is configured to log at `info` level. Depending on CCR's implementation, this may log request bodies (containing user prompts and model responses) to stdout/log files. These logs could contain sensitive project code, system prompts, or private conversations.

**Recommendation**: Verify what CCR logs at `info` level. If request/response bodies are included, consider switching to `"LOG_LEVEL": "warn"` or `"error"` in production usage, or ensure log files have restricted permissions.

### W3. Docker containers run without security hardening

**Severity: Medium**  
**Location**: `docker-compose.yml` — all services, and the planned TensorZero service.

No containers in the Compose file use:
- `read_only: true` (immutable filesystem)
- `security_opt: ["no-new-privileges:true"]` (prevent privilege escalation)
- `cap_drop: [ALL]` (drop Linux capabilities)
- Dedicated non-root user

For TensorZero specifically, this means if a vulnerability is found in the gateway, an attacker could potentially escape the container with full root capabilities on the host.

**Recommendation**: Add basic hardening to the TensorZero service definition:
```yaml
tensorzero:
  image: tensorzero/gateway
  read_only: true
  security_opt:
    - no-new-privileges:true
  cap_drop:
    - ALL
  tmpfs:
    - /tmp
```

### W4. Multiple API keys in single container environment

**Severity: Medium**  
**Location**: Plan § "tensorzero.toml" — three providers configured (`zai`, `anthropic`, `openai`).

The TensorZero container will receive **all three** API keys via environment variables (`ZAI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). If any client can reach the gateway (see C1/C2), they can use **all three** provider keys, not just the one they normally need. For example, a Qwen client intended only for z.ai could burn through OpenAI credits.

**Recommendation**: This is mitigated by fixing C1 (gateway auth). Additionally, consider using TensorZero's function/model routing to restrict which clients can access which providers.

### W5. Pre-existing: Adminer exposed without auth on 0.0.0.0:8080

**Severity: Medium** (pre-existing, not introduced by this plan)  
**Location**: `docker-compose.yml` lines 126-137.

Adminer (database management UI) is exposed on all interfaces with no authentication. Anyone who can reach port 8080 gets a web UI pointed at your Postgres instance. The plan doesn't change this, but adding TensorZero increases the attack surface of the overall Compose stack.

**Recommendation**: Bind Adminer to `127.0.0.1:8080:8080` or remove it if not actively used.

### W6. Pre-existing: PostgreSQL with weak credentials on 0.0.0.0:5432

**Severity: Medium** (pre-existing)  
**Location**: `docker-compose.yml` line 25 — `POSTGRES_PASSWORD: mahavishnu_dev`.

The database password is a trivially guessable dev default, and the port is exposed to all interfaces. Same bind-address concern as C2.

**Recommendation**: At minimum, bind to 127.0.0.1 only. Use a stronger password if the port must remain open.

### W7. Cache TTL of 1 hour may retain sensitive data

**Severity: Low**  
**Location**: `tensorzero.toml` — `default_ttl_secs = 3600`

Prompt/response pairs are cached for 1 hour. If these contain proprietary code, credentials discussed in conversation, or other sensitive data, they persist in Redis for the full TTL. A Redis compromise (see C3) within that window exposes recent inference data.

**Recommendation**: Consider a shorter TTL (300s / 5 min) for a dev setup, or disable the cache entirely until Redis is properly secured with AUTH.

---

## 🟢 Good Practices Already in Place

### ✅ G1. Telemetry disabled

```toml
disable_pseudonymous_usage_analytics = true
```

Pseudonymous usage analytics are disabled. This prevents TensorZero from phoning home with usage patterns, which is good for privacy and reduces network attack surface.

### ✅ G2. API keys sourced from environment variables

```toml
api_key_location = "env::ZAI_API_KEY"
```

Keys are not hardcoded in the TOML config. They come from environment variables, which is the standard best practice. Ensure the Docker Compose file uses `env_file` or `environment` to inject them (not baked into the image).

### ✅ G3. Config is version-controlled (GitOps-friendly)

The plan explicitly notes `tensorzero.toml` is "GitOps-friendly, version controlled." This enables change auditing and prevents drift between expected and actual configuration.

### ✅ G4. Rate limiting configured

Token-per-minute (100K bucket, 2K/s refill) and inference-per-second (30 burst, 10/s refill) rate limits are defined. This provides a safety net against both accidental runaway usage and potential abuse if auth is weak.

### ✅ G5. CCR already binds to 127.0.0.1

```json
"HOST": "127.0.0.1"
```

CCR correctly binds to localhost only. This is the right pattern and should be followed by the TensorZero gateway.

### ✅ G6. Independent rollback for each client

Each client configuration change is independent and reversible. There's no big-bang cutover that could leave all clients broken simultaneously.

### ✅ G7. Redis data expires naturally

The plan notes "Redis state expires naturally" for rollback. This means cached data and rate-limit counters have built-in TTLs, preventing unbounded data accumulation.

### ✅ G8. CCR config uses env var references for keys

```json
"api_key": "$ZAI_API_KEY"
```

CCR references environment variables (not literal keys) for API keys. This is the correct approach.

---

## Summary

| Category | Count |
|----------|-------|
| 🔴 Critical | 3 |
| 🟡 Warning | 7 (2 pre-existing) |
| 🟢 Good practice | 8 |

**Deployment recommendation**: **Do not deploy** until C1 (gateway auth), C2 (bind to localhost), and C3 (Redis AUTH) are resolved. These three issues together create a scenario where any network-adjacent attacker can read your cached LLM prompts/responses and make unlimited inference requests using your paid API keys.

The fix is straightforward:
1. Add `api_keys` to `tensorzero.toml` and distribute a gateway key to clients.
2. Change `gateway_url` to `127.0.0.1`.
3. Enable Redis AUTH and update the connection URL.

Total estimated effort: ~30 minutes.
