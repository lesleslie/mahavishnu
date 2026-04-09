# Bifrost Reactivation Runbook

Date: 2026-04-09

## Purpose

This runbook brings the local Bifrost gateway back from dormant state into a usable localhost-only deployment.

Use it when:

- you switch from subscription-backed coding tools to API-billed usage
- you want routing, exact-match cache, and optional semantic cache
- you want a reproducible way to reinstall the macOS LaunchAgents

Do not use it while your main traffic still depends on subscription-only endpoints.

## Current Dormant State

As of 2026-04-09:

- source launchd plists still exist in the repo:
  - `config/launchd/ai.bifrost.gateway.plist`
  - `config/launchd/ai.bifrost.redis-stack.plist`
- installed copies were removed from `~/Library/LaunchAgents`
- live user configs for Codex, Claude Code, Qwen, Nanobot, and OpenClaw were reverted to direct provider endpoints
- Bifrost and the dedicated Redis Stack cache are not expected to auto-start on reboot

## Prerequisites

- API-backed provider credentials are available and funded
- `~/.zshrc` contains the required keys
- `redis-stack-server` is installed
- the repo contains the Bifrost bootstrap files under `config/bifrost/` and `config/launchd/`

Expected key material:

- `OPENAI_API_KEY`
- `ZAI_API_KEY` or `Z_AI_API_KEY`

Optional later:

- an embedding-provider key for semantic cache if you choose to enable it

## Reactivation Order

Bring the stack back in this order:

1. verify secrets
2. install and start Redis Stack cache backend
3. install and start Bifrost
4. rebootstrap config if needed
5. validate direct cache and routing
6. only then repoint clients

## 1. Verify Secrets

Check that the current shell sees the keys:

```zsh
source ~/.zshrc
env | rg 'OPENAI_API_KEY|ZAI_API_KEY|Z_AI_API_KEY'
```

If you changed `.zshrc` in another shell, restart the terminal or re-source it first.

## 2. Reinstall and Start Redis Stack

Redis Stack is the dedicated cache backend on port `6380`.

```zsh
cd /Users/les/Projects/mahavishnu
./scripts/redis-stack-ctl install
./scripts/redis-stack-ctl start
./scripts/redis-stack-ctl status
```

Healthy outcome:

- LaunchAgent is loaded
- a listener exists on `127.0.0.1:6380`
- ready file exists at `~/.local/state/mcp/ready/redis-stack-bifrost.ready`

## 3. Reinstall and Start Bifrost

```zsh
cd /Users/les/Projects/mahavishnu
./scripts/bifrost-ctl install
./scripts/bifrost-ctl start
./scripts/bifrost-ctl status
```

Healthy outcome:

- LaunchAgent is loaded
- a listener exists on `127.0.0.1:8471`
- ready file exists at `~/.local/state/mcp/ready/bifrost.ready`

## 4. Rebootstrap When Config Changed

Because `config_store` is enabled, Bifrost imports the file config into SQLite and then prefers the database copy.

Use `rebootstrap` when:

- `config/bifrost/config.template.json` changed
- provider keys or model definitions changed materially
- routing rules changed materially
- you want to discard a stale `config.db`

Command:

```zsh
cd /Users/les/Projects/mahavishnu
./scripts/bifrost-ctl rebootstrap
./scripts/bifrost-ctl status
```

## 5. Validate the Gateway Before Client Cutover

### Model listing

```zsh
curl -sS http://127.0.0.1:8471/v1/models
```

### Anthropic path

```zsh
curl -sS http://127.0.0.1:8471/anthropic/v1/messages \
  -H 'content-type: application/json' \
  -H "x-api-key: ${ZAI_API_KEY:-$Z_AI_API_KEY}" \
  -d '{
    "model": "anthropic/GLM-4.5-Air",
    "max_tokens": 32,
    "messages": [{"role":"user","content":"Reply with exactly pong"}]
  }'
```

### OpenAI chat path

```zsh
curl -sS http://127.0.0.1:8471/v1/chat/completions \
  -H 'content-type: application/json' \
  -H "authorization: Bearer ${ZAI_API_KEY:-$Z_AI_API_KEY}" \
  -d '{
    "model": "zai-openai/glm-5-turbo",
    "messages": [{"role":"user","content":"Reply with exactly pong"}]
  }'
```

### OpenAI Responses path

```zsh
curl -sS http://127.0.0.1:8471/v1/responses \
  -H 'content-type: application/json' \
  -H "authorization: Bearer ${OPENAI_API_KEY}" \
  -d '{
    "model": "openai/gpt-5.4-mini",
    "input": "Reply with exactly pong"
  }'
```

Interpretation:

- upstream `429 insufficient_quota` means the gateway path is fine and the provider account needs quota
- z.ai `1113` means the gateway path is fine and the z.ai account needs balance/package

## 6. Validate Exact-Match Cache

The current cache plugin is proven in direct-only mode.

Use a fixed key:

```zsh
curl -sS http://127.0.0.1:8471/anthropic/v1/messages \
  -H 'content-type: application/json' \
  -H "x-api-key: ${ZAI_API_KEY:-$Z_AI_API_KEY}" \
  -H 'x-bf-cache-type: direct' \
  -H 'x-bf-cache-key: smoke-test-ping' \
  -d '{
    "model": "anthropic/GLM-4.5-Air",
    "max_tokens": 32,
    "messages": [{"role":"user","content":"Reply with exactly pong"}]
  }'
```

Repeat the same request immediately.

Healthy outcome:

- the second request is materially faster
- the second request reuses the same cached response identity

## 7. Repoint Clients

Only after the previous checks pass.

Suggested order:

1. Claude Code
2. one OpenAI-compatible client
3. one internal service
4. the rest of the fleet

Recommended first cutover:

- Claude Code -> Bifrost Anthropic path
- one OpenAI-compatible chat client -> Bifrost `/v1/chat/completions`
- keep Codex direct until you intentionally want API-billed OpenAI Responses traffic

## Semantic Cache Next Step

### What is already done

- Redis Stack backend is working
- exact-match direct cache is working
- route buckets were verified

### What is not done

- semantic similarity matching is not meaningfully active yet
- the plugin still needs an embedding strategy/provider to justify semantic mode

### Recommended next step

When the gateway becomes active again, enable semantic mode in a second phase:

1. keep exact-match cache on
2. keep Redis Stack as the vector backend
3. add an embedding-capable provider for semantic cache
4. start with a conservative similarity threshold
5. evaluate hit quality before widening scope

Recommended first-pass settings:

- embedding model: low-cost embedding model such as OpenAI `text-embedding-3-small`
- threshold: `0.8`
- short TTL for semantic entries at first
- keep `cache_by_model: true`
- keep `cache_by_provider: true`

### Why this is the right next step

- semantic cache adds operational complexity
- it pays off only once you have meaningful API traffic to reduce
- exact-match cache already gives the safest savings with the least risk

### Stop point

If you want a stable intermediate state, stop after:

- Redis Stack is healthy
- Bifrost is healthy
- routing rules validate
- exact-match cache validates

That is already a production-usable first phase.

## Rollback

To pause the stack again:

```zsh
cd /Users/les/Projects/mahavishnu
./scripts/bifrost-ctl stop
./scripts/redis-stack-ctl stop
rm -f ~/Library/LaunchAgents/ai.bifrost.gateway.plist
rm -f ~/Library/LaunchAgents/ai.bifrost.redis-stack.plist
```

Then revert any user-level client configs back to direct provider endpoints.

## Notes

- `config_store` means file config changes do not take effect automatically after first bootstrap
- use `rebootstrap` when file config is the intended source of truth again
- do not mix subscription-backed client traffic with a generic API gateway and expect subscription billing to carry through
