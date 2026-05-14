# Bifrost Bootstrap Notes

This directory contains the bootstrap artifacts for the local Bifrost gateway.

Current status:

- bootstrap artifacts are preserved in-repo
- live client cutover is paused
- installed LaunchAgent copies were removed from `~/Library/LaunchAgents` on 2026-04-09
- Bifrost is not on the critical path right now
- subscription-backed tools are routed directly to their native providers again

## Files

- `config.template.json`
  - seed configuration copied into `~/.config/bifrost/config.json` by `scripts/bifrost-gateway.zsh`
- `../launchd/ai.bifrost.gateway.plist`
  - LaunchAgent template
- `../launchd/ai.bifrost.redis-stack.plist`
  - LaunchAgent template for the dedicated Redis Stack cache backend
- `../../docs/bifrost-reactivation-runbook.md`
  - reactivation and validation steps for bringing the gateway back later

## Current Bootstrap Mode

The template is intentionally conservative:

- OpenAI provider configured for Codex/OpenAI Responses clients
- OpenAI-compatible MiniMax provider configured for chat/completions traffic
- dedicated Redis Stack cache backend configured on `127.0.0.1:6380`
- semantic cache plugin enabled in direct-only mode

This means:

- routing works without a second router like CCR
- `x-bf-cache-*` headers are active for trusted callers
- direct-cache hits work now; semantic similarity cache still needs an embedding provider if we want near-duplicate matches
- OpenAI-style callers can target `/v1/chat/completions` with explicit `minimax-openai/<model>` names
- OpenAI Responses clients such as Codex can target `/v1/responses` with explicit `openai/<model>` names
- CCR-style task routing is bootstrapped through header-driven global routing rules
- user-level configs were previously cut over for validation and then reverted to direct provider endpoints when subscription-backed usage resumed

The current cache backend is Redis Stack because the plain Homebrew Redis build on `6379`
does not provide RediSearch `FT.*`, which Bifrost requires.

## Provider Names

The current bootstrap config uses:

- `openai/<model>` for OpenAI-backed Responses clients
- `minimax-openai/<model>` for MiniMax OpenAI-compatible chat models

Example:

- `openai/gpt-5.4`
- `minimax-openai/MiniMax-M2.7`

## Client Opt-In

In-repo callers can opt into Bifrost for OpenAI-compatible traffic by setting either:

- `BIFROST_BASE_URL=http://127.0.0.1:8471`
- `MAHAVISHNU_LLM_GATEWAY_BASE_URL=http://127.0.0.1:8471`

Current in-repo wiring:

- `mahavishnu/core/app.py`
- `mahavishnu/core/adapters/worker.py`

Both use the nanobot `OpenAICompatProvider` and switch its `base_url` from the direct
Anthropic-compatible endpoint to Bifrost's OpenAI-compatible `/v1` surface when one of
those environment variables is present.

## Mahavishnu Worker Defaults

Mahavishnu's worker registry previously defaulted these local CLIs to Bifrost-backed
surfaces during cutover work:

- `terminal-claude`
  - previously exported `ANTHROPIC_BASE_URL=${BIFROST_ANTHROPIC_BASE_URL:-http://127.0.0.1:8471/anthropic}`
- `terminal-qwen`
  - previously used `--auth-type openai`
  - previously used `--openai-base-url ${BIFROST_OPENAI_BASE_URL:-http://127.0.0.1:8471/v1}`
  - previously defaulted model to `${QWEN_MODEL:-zai-openai/glm-5-turbo}`

Current note:

- those worker defaults were reverted
- `terminal-claude` and `terminal-qwen` now defer to their native CLI configuration again
- `terminal-codex` is also direct/native again

## Bootstrap Routing Contract

The current bootstrap config includes global routing rules keyed off trusted caller headers.

Supported route headers:

- `x-bf-task`
- `x-bf-route`

Current task mappings:

- `think` -> `minimax-openai/MiniMax-M2.7`
- `long_context` or `longContext` -> `minimax-openai/MiniMax-M2.7`
- `web_search` or `webSearch` -> `minimax-openai/MiniMax-M2.7`
- `image` -> deferred until a supported MiniMax multimodal route exists
- `background`, `cheap`, or `high_throughput` -> `minimax-openai/MiniMax-M2.7-highspeed`

Notes:

- these rules are intentionally header-driven for now
- they are meant to reproduce the useful routing buckets from CCR without introducing a second router
- the `image` route is currently disabled in the template until the gateway has a supported multimodal adapter

## Verified Bootstrap State

As of 2026-04-08:

- the LaunchAgent starts Bifrost on `127.0.0.1:8471`
- the Redis Stack LaunchAgent starts a dedicated cache backend on `127.0.0.1:6380`
- OpenAI-compatible requests reach the MiniMax provider through `http://127.0.0.1:8471/v1/chat/completions`
- `/v1/models` now advertises `openai/gpt-5.3-codex`, `openai/gpt-5.4`, and `openai/gpt-5.4-mini`
- `/v1/responses` is reachable through Bifrost and fails with upstream `429 insufficient_quota` when the OpenAI account has no quota
- `/v1/chat/completions` reaches `minimax-openai/MiniMax-M2.7` through Bifrost when the MiniMax provider is healthy
- Codex reaches Bifrost on the OpenAI Responses path and is therefore protocol-compatible with the gateway
- `minimax-openai/*` does not currently support the OpenAI Responses API, so Codex cannot be switched to MiniMax through `/v1/responses` as a quota workaround
- after rebootstrap, Bifrost now stores `config.db` under `~/.config/bifrost` instead of the repo root and the launchd job writes the expected ready file
- after the config-store cleanup, `/v1/models` reports only healthy OpenAI and Anthropic key statuses; the old misleading invalid-key status was caused by the previous stale/orphaned startup state
- `x-bf-task: think` routes to the stronger reasoning model
- `x-bf-task: long_context` routes to the long-context model
- `x-bf-task: web_search` routes to the search-oriented model
- `x-bf-task: image` routes to the vision model(s)
- `x-bf-task: background` routes to the cheaper background model
- `x-bf-task: cheap` routes to the cheaper background model
- the OpenAI MiniMax custom provider still does not support `list_models`, so Bifrost falls back to static datasheets for `minimax-openai/*`
- plain Homebrew Redis 8.6.2 on `6379` still lacks RediSearch `FT.*`, so Bifrost cache uses the dedicated Redis Stack instance on `6380`
- Bifrost now reports `semantic_cache - active`
- repeated requests with `x-bf-cache-type: direct` and a fixed `x-bf-cache-key` return the same message id on the second request and complete much faster, confirming direct cache hits
- the launch wrapper now prefers the cached Bifrost `bin.js` under `~/.npm/_npx` and falls back to `npx` only when the cache is missing

## Important Bifrost Behavior

The template enables `config_store` with SQLite.

After first bootstrap:

- Bifrost imports the file config into `config.db`
- later changes in `config.json` are ignored while `config_store` is enabled
- routing rules, virtual keys, and governance settings should be managed through the Bifrost UI or public config APIs

If you need to re-bootstrap from file config, stop the gateway and remove the existing `config.db`.

## Semantic Cache Next Step

The current plugin is working in direct-only mode:

- exact-match cache hits work
- semantic similarity mode is not active yet

The next meaningful step is to configure an embedding provider for the plugin.

Recommended first pass:

- keep Redis Stack as the vector store backend
- add an embedding-capable provider to the semantic cache plugin
- start with OpenAI `text-embedding-3-small` if API billing is acceptable
- keep `cache_by_model` and `cache_by_provider` enabled
- begin with `threshold: 0.8`
- keep `conversation_history_threshold` low, around `3`

Reason:

- Redis Stack is already proven locally for the cache backend
- Bifrost supports dual-layer cache with exact hash matching plus semantic similarity
- semantic mode is only worth enabling once you are on API-billed traffic where repeated prompts can actually save money

Do not enable semantic mode while you remain primarily on subscription-backed clients. The operational complexity is not justified until the gateway becomes an active API path again.

## Local Control

Use [`scripts/bifrost-ctl`](/Users/les/Projects/mahavishnu/scripts/bifrost-ctl) for local management:

- `scripts/bifrost-ctl install`
- `scripts/bifrost-ctl sync-config`
- `scripts/bifrost-ctl start`
- `scripts/bifrost-ctl rebootstrap`
- `scripts/bifrost-ctl status`
- `scripts/bifrost-ctl tail`

Use [`scripts/redis-stack-ctl`](/Users/les/Projects/mahavishnu/scripts/redis-stack-ctl) for the dedicated cache backend:

- `scripts/redis-stack-ctl install`
- `scripts/redis-stack-ctl start`
- `scripts/redis-stack-ctl stop`
- `scripts/redis-stack-ctl restart`
- `scripts/redis-stack-ctl status`

Operational note:

- after repeated rapid restarts, launchd may report `spawn scheduled` before the job becomes healthy again
- in that state, wait roughly one `ThrottleInterval` window before assuming startup failed
- if you need a predictable recovery path, prefer `scripts/bifrost-ctl stop` followed by `scripts/bifrost-ctl start`
- `scripts/bifrost-ctl` now force-kills any orphan listener on `127.0.0.1:8471` before restart/rebootstrap so stale child processes do not hold the port open
- when validating the OpenAI provider, distinguish protocol failures from account-state failures:
  `429 insufficient_quota` from `/v1/responses` means the gateway path is working and the backing OpenAI account needs billing/quota attention
