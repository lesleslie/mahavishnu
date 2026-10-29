# Bifrost Bootstrap Notes

This directory contains the bootstrap artifacts for the local Bifrost gateway.

Current status (verified live, 2026-10-20):

- **Bifrost is live on `127.0.0.1:8471`.** Verified by
  `curl -fsS http://127.0.0.1:8471/health` returning `{"status":"ok",...}`
  (HTTP 200) and the launchd ready file at `~/.local/state/mcp/ready/bifrost.ready`.
- The earlier "paused indefinitely" state from 2026-06-26 (macOS Gatekeeper on
  `@maximhq/bifrost`'s native binary) has been resolved or worked around. The
  launchd job (`ai.bifrost.gateway`) and the Oneiric-secret-resolving
  `mahavishnu bifrost status` are healthy.
- Live providers: `minimax-openai` (M3 primary, M2.7 fallback), `llama-server`
  (`qwen3-8b-q4_k_m` local), `anthropic`, `openai` (`gpt-5.4` family).
- Claude Code's `ANTHROPIC_BASE_URL` in `~/.claude/settings.json` is currently
  `https://api.minimax.io/anthropic` (direct-to-MiniMax, not via Bifrost).
- The wired-worker opt-ins (`terminal-claude`, `terminal-qwen`, `terminal-codex`)
  remain in their historical reverted state — see "Mahavishnu Worker Defaults" below.

## Verifying Bifrost is Live

Before any cutover, run these checks in order. Any failure = pause and investigate.

1. `lsof -tiTCP:8471 -sTCP:LISTEN` — non-empty means a listener is bound.
1. `curl -fsS http://127.0.0.1:8471/health` — must return
   `{"components":{"db_pings":"ok"},"status":"ok"}` (or equivalent).
1. `test -f ~/.local/state/mcp/ready/bifrost.ready` — ready file written
   by `mahavishnu bifrost foreground` only after the listener probe succeeds.
1. `tail -5 ~/.local/state/mcp/logs/bifrost.log` — recent JSON lines, not stale.

## Files

- `config.template.json`
  - seed configuration copied into `~/.config/bifrost/config.json` by `mahavishnu/bifrost/gateway.py`
- `../launchd/ai.bifrost.gateway.plist`
  - LaunchAgent template
- `../launchd/ai.bifrost.redis-stack.plist`
  - LaunchAgent template for the dedicated Redis Stack cache backend
- `../../docs/BIFROST_REACTIVATION_RUNBOOK.md`
  - reactivation and validation steps for bringing the gateway back later

## Current Bootstrap Mode

The template is intentionally conservative:

- OpenAI provider configured for Codex/OpenAI Responses clients
- OpenAI-compatible MiniMax provider configured for chat/completions traffic
- dedicated Redis Stack cache backend configured on `127.0.0.1:6379`
- semantic cache plugin enabled in **semantic mode** (embedding provider: OpenAI
  `text-embedding-3-small`, vector dimension 1536)

This means:

- routing works without a second router like CCR
- `x-bf-cache-*` headers are active for trusted callers
- both cache layers work: exact-match hits *and* similarity hits for near-duplicate
  prompts (see "Semantic Cache" below)
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
- `minimax-openai/MiniMax-M3`

## Client Opt-In

In-repo callers reach Bifrost through Oneiric's `BifrostLLMRouter`
(`oneiric.adapters.llm.bifrost.get_router()`), which resolves a gateway URL
per provider. The router is configured by `BifrostLLMSettings`, whose
`env_prefix` is `ONEIRIC_BIFROST_` with `env_nested_delimiter="__"`. Flat
fields use a **single** underscore (`ONEIRIC_BIFROST_ENABLED`,
`ONEIRIC_BIFROST_ROUTES`); only nested models use the double underscore.

The switch is set in `~/.zshenv` and mirrored in `~/.config/oneiric/local.yaml`:

```yaml
bifrost:
  enabled: true
  base_url: http://127.0.0.1:8471/v1
  anthropic_base_url: http://127.0.0.1:8471/anthropic
  routes: [claude_route, qwen_route]
```

> **Note:** `MahavishnuSettings` has no `bifrost` field, and nothing in this
> repo reads `MAHAVISHNU_BIFROST__enabled`. Oneiric's legacy
> `MAHAVISHNU_BIFROST__*` prefix is still honoured by Oneiric as a
> back-compat shim, but `ONEIRIC_BIFROST_*` is the canonical spelling.

`BifrostLLMSettings.cache_mode` (`off` | `direct` | `semantic`) is **advisory
only**: the `mahavishnu/llm_gateway` package that consumed it was deleted in
commit `03146be0`, and no remaining code reads it. Caching is engaged by the
gateway itself, through the plugin's `default_cache_key` and the
`x-bf-cache-*` request headers.

Current in-repo wiring:

- `mahavishnu/core/app.py`
- `mahavishnu/core/adapters/worker.py`

Both use the nanobot `OpenAICompatProvider` and switch its `base_url` from the direct
Anthropic-compatible endpoint to Bifrost's OpenAI-compatible `/v1` surface when one of
those environment variables is present.

## Harness Routing: Claude Code vs. the Bodai Components

The two are routed differently, on purpose:

- **Bodai components** (mahavishnu, akosha, session-buddy, crackerjack,
  oneiric, mcp-common) route their LLM and worker calls through Bifrost via
  `BifrostLLMRouter` — see "Client Opt-In" above.
- **Claude Code** talks to `https://api.minimax.io/anthropic` **directly**,
  bypassing Bifrost. Qwen Code stays pointed at the gateway.

> **Gotcha:** every gateway command that brings the service up re-points
> Claude Code at the gateway — `mahavishnu bifrost start`, `restart`, and
> `rebootstrap` all end in `_after_ready("bifrost")` →
> `repoint_harnesses("bifrost")` (`mahavishnu/bifrost/lifecycle.py`). The
> `restart` docstring says "preserving the client's current routing choice",
> but the code re-points. After any of them, restore the direct endpoint
> with `mahavishnu bifrost cc-url direct`.

Because Claude Code's system prompt carries the current date, working
directory, and environment details, it must not share a cache bucket with
another agent. If Claude Code is ever routed through the gateway, give it a
distinct `x-bf-cache-key` per session.

### Authentication: the virtual key, not the provider key

A request that reaches the gateway must carry the **gateway virtual key** in
`x-bf-vk`. The gateway rejects a provider key with
`401 - virtual key is required` — it resolves upstream credentials from its
own config store, so the caller's provider key is not just unnecessary, it
is a hard failure.

```
Authorization: Bearer <MINIMAX_API_KEY>                        -> 401
Authorization: Bearer <BIFROST_VIRTUAL_KEY>                     -> 200
Authorization: Bearer <MINIMAX_API_KEY> + x-bf-vk: <vk>        -> 200
```

The third form is what the Bodai path uses: the provider key stays in
`Authorization` (it is still correct for a direct-to-MiniMax call), and the
virtual key rides alongside in `x-bf-vk`.

> **The second row is contested.** Two modules in this repo record the
> opposite from an earlier probe — `mahavishnu/bifrost/toggles.py` and
> `mahavishnu/workers/capabilities/_probes.py` both say Bifrost reads the
> virtual key *exclusively* from `x-bf-vk` and that no bearer form is
> honoured. The matrix above comes from a later, purpose-built probe
> (2026-10-29, plan §4.1). Nothing in the Bodai path depends on which is
> right: the virtual key is sent in `x-bf-vk` on every gateway request, and
> the provider key in `Authorization`, which is the form both readings
> accept. Settling the disagreement needs a deliberate live probe; until
> then, treat the bearer-only form as unreliable.

The key is read from `$BIFROST_VIRTUAL_KEY`, falling back to
`~/.config/secrets.env` — a launchd-spawned process inherits no interactive
environment.

**The key is only attached to a trusted transport.** A plain-HTTP request
to a non-loopback host would put the gateway credential on the wire in
cleartext, so `mahavishnu/bifrost/cache_headers.py` withholds it in that
case and logs an error. HTTPS is always trusted; plain HTTP is trusted
only for loopback, which is how the gateway is deployed.

### `cache_mode`

`BifrostLLMSettings.cache_mode` (`off` | `direct` | `semantic`) selects the
cache path a request takes. It is set with `ONEIRIC_BIFROST_CACHE_MODE` and
translated into the request headers by
`mahavishnu/bifrost/cache_headers.py`:

| `cache_mode` | Headers sent | Effect at the gateway |
|---|---|---|
| `off` | `x-bf-cache-no-store: true` | The response is **not written** to the cache. Reads still happen — Bifrost v1.5/v1.6 exposes no header that suppresses the read. |
| `direct` | `x-bf-cache-type: direct` | Only the exact-match path is searched. |
| `semantic` | `x-bf-cache-type: semantic` | Only the vector-similarity path is searched. |

Every mode also sends `x-bf-cache-key` to scope entries to a bucket
(`default` unless a caller names another).

> **`off` is not "no cache".** It means "do not populate the cache". A
> request in `off` mode can still be *served* from a previously cached
> response.

**The cache headers are sent even when the virtual key is missing.** They
express an operator retention control, and a missing credential must not
invert it: without `x-bf-cache-no-store` the gateway resolves the bucket
from its own `default_cache_key` and writes the prompt and response into
the shared cache — the opposite of `cache_mode: off`. A missing key
removes `x-bf-vk` and nothing else.

The setting is read by the **environment**, not by
`~/.config/oneiric/local.yaml` — `BifrostLLMSettings` is a
`pydantic-settings` class whose only source is `ONEIRIC_BIFROST_*` in the
process environment. Verified by probing `caller_id`: a value set in
`local.yaml` does not reach the settings object.

> **launchd does not source `~/.zshenv`.** A long-running Bodai service
> started by launchd sees none of the `ONEIRIC_BIFROST_*` variables, so its
> Bifrost router is disabled and it falls back to calling MiniMax directly.
> Mirror the variables into the service's plist
> (`EnvironmentVariables`) — the same pattern the mahavishnu plist already
> uses for `MAHAVISHNU_OTEL_METRICS_ENABLED`.

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

- `think` -> `minimax-openai/MiniMax-M3`
- `long_context` or `longContext` -> `minimax-openai/MiniMax-M3`
- `web_search` or `webSearch` -> `minimax-openai/MiniMax-M3`
- `image` -> deferred until a supported MiniMax multimodal route exists
- `background`, `cheap`, or `high_throughput` -> `minimax-openai/MiniMax-M3`

Notes:

- these rules are intentionally header-driven for now
- they are meant to reproduce the useful routing buckets from CCR without introducing a second router
- all M3 fallbacks are M3-highspeed (same generation); M2.7 variants are reserved as the documented offline fallback chain
- the `image` route is currently disabled in the template until the gateway has a supported multimodal adapter

## Verified Bootstrap State

As of 2026-04-08:

- the LaunchAgent starts Bifrost on `127.0.0.1:8471`
- the Redis Stack LaunchAgent starts a dedicated cache backend on `127.0.0.1:6379`
- OpenAI-compatible requests reach the MiniMax provider through `http://127.0.0.1:8471/v1/chat/completions`
- `/v1/models` now advertises `openai/gpt-5.3-codex`, `openai/gpt-5.4`, and `openai/gpt-5.4-mini`
- `/v1/responses` is reachable through Bifrost and fails with upstream `429 insufficient_quota` when the OpenAI account has no quota
- `/v1/chat/completions` reaches `minimax-openai/MiniMax-M3` through Bifrost when the MiniMax provider is healthy
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
- plain Homebrew Redis 8.6.2 lacks RediSearch `FT.*`; Redis Stack now binds the conventional `6379` port so it can serve as the default cache backend for any Redis-compatible client (Oneiric, ad-hoc `redis-cli`, etc.)
- Bifrost now reports `semantic_cache - active`
- repeated requests with `x-bf-cache-type: direct` and a fixed `x-bf-cache-key` return the same message id on the second request and complete much faster, confirming direct cache hits
- as of 2026-10-29 the semantic cache is no longer inert: it stores real
  1536-dim vectors, a reworded prompt is served from cache via similarity
  (0.9828 against a 0.86 threshold), and an unrelated prompt is not. See
  "Semantic Cache" below and `tests/integration/test_bifrost_semantic_cache_e2e.py`.
- the launch wrapper now prefers the cached Bifrost `bin.js` under `~/.npm/_npx` and falls back to `npx` only when the cache is missing

## Important Bifrost Behavior

The template enables `config_store` with SQLite.

After first bootstrap:

- Bifrost imports the file config into `config.db`
- later changes in `config.json` are ignored while `config_store` is enabled
- routing rules, virtual keys, and governance settings should be managed through the Bifrost UI or public config APIs

If you need to re-bootstrap from file config, use `mahavishnu bifrost rebootstrap`.
It re-seeds `config.json` from `config/bifrost/config.template.json` and restarts
the gateway. The config store is **kept** (it is authoritative for providers,
keys, governance config, and virtual keys) and is backed up first, under
`~/.config/bifrost/.bak/`. Pass `--drop-db` only if you deliberately want to
discard it.

## Semantic Cache

The plugin runs in **semantic mode** (verified 2026-10-29):

- exact-match cache hits work
- semantic similarity hits work — a reworded prompt is served from the cache via
  vector cosine similarity

Configured values and why each one is what it is:

| Key | Value | Reason |
|---|---|---|
| `provider` | `openai` | The plugin generates embeddings through this provider's keys. |
| `embedding_model` | `text-embedding-3-small` | 1536-dim; matches the Redis index exactly. |
| `dimension` | `1536` | **Must** equal the model's native output size. The Redis `VECTOR` attribute is created with a fixed `dim` and RediSearch cannot resize it in place. |
| `threshold` | `0.86` | Cosine floor for a similarity hit. `0.8` is Bifrost's generic default, tuned for single short prompts; here the embedding covers a whole conversation, so it is loose. `resolveCacheThreshold` takes `max(config, per-request)`, so a higher floor can only be raised. |
| `conversation_history_threshold` | `8` | Bifrost skips caching **entirely** — both layers — for requests with more than this many messages. Its default of `3` disables the cache for nearly all agentic traffic, which resends the full transcript every turn. |
| `exclude_system_prompt` | `true` | Drops the shared system prompt from the embedded text, which otherwise inflates similarity between unrelated tasks (a large common prefix). **Trade-off:** it also drops the system prompt from the *direct* cache key, so two requests with identical messages but different system prompts can share an entry. Set it to `false` if you run multiple agent personas through one cache key. |
| `default_cache_key` | `default` | Without it, `resolveCacheKey` returns false and caching is disabled for every request that does not send an explicit `x-bf-cache-key` header. |
| `cache_by_model` / `cache_by_provider` | `true` | Keep model/provider in the filter so a cached response never crosses providers. |

Two upstream requirements that are easy to miss:

1. **The embedding model must be in the provider's key allowlist.** The `openai`
   provider's key declares `models: [...]`, and Bifrost resolves a key *before*
   dispatching upstream. If `text-embedding-3-small` is absent from that list,
   every embedding attempt fails locally with `no_key_supports_model` and the
   request never reaches OpenAI — so no amount of upstream credit fixes it.
1. **The embedding model has an 8192-token input limit.** The plugin embeds the
   *entire* conversation with no truncation, so long agentic transcripts exceed
   the limit and the embedding request is rejected. The plugin degrades
   gracefully — it logs the skip and falls through to the upstream provider —
   but those requests are never cached semantically.

### Verifying the cache

`tests/integration/test_bifrost_semantic_cache_e2e.py` asserts the behaviour
end to end against the running gateway (direct hit, semantic hit, and no
false positive on an unrelated prompt).
`tests/unit/test_bifrost_semantic_cache_config.py` asserts the config
invariants above without needing the gateway or the network.

A manual check:

```bash
curl -sS -D - -o /dev/null http://127.0.0.1:8471/v1/chat/completions \
  -H "x-bf-vk: $BIFROST_VIRTUAL_KEY" \
  -H "x-bf-cache-key: manual-probe" \
  -H "Content-Type: application/json" \
  -d '{"model":"minimax-openai/MiniMax-M3","messages":[{"role":"user","content":"probe: reply with the single word PONG"}],"max_tokens":16}'
```

A cached response carries `X-Bifrost-Cache-Hit: true` plus
`X-Bifrost-Cache-Hit-Type: direct|semantic`; a similarity hit also carries
`X-Bifrost-Cache-Similarity` and `X-Bifrost-Cache-Threshold`.

## Local Control

Use `mahavishnu bifrost` for local management (the standalone
`scripts/bifrost*` tools were consolidated here in Phase 4 of
`docs/plans/2026-10-21-bifrost-cli-consolidation.md`):

- `mahavishnu bifrost install`
- `mahavishnu bifrost start`
- `mahavishnu bifrost stop`
- `mahavishnu bifrost restart`
- `mahavishnu bifrost rebootstrap`
- `mahavishnu bifrost status`
- `mahavishnu bifrost verify-gate`

Client routing:

- `mahavishnu bifrost cc-url {bifrost|direct|status}`
- `mahavishnu bifrost qwen-url {bifrost|direct|status}`
- `mahavishnu bifrost policy`

Use [`scripts/redis-stack-ctl`](../../scripts/redis-stack-ctl) for the dedicated cache backend:

- `scripts/redis-stack-ctl install`
- `scripts/redis-stack-ctl start`
- `scripts/redis-stack-ctl stop`
- `scripts/redis-stack-ctl restart`
- `scripts/redis-stack-ctl status`

### Claude Code URL toggle

`start`, `restart`, `rebootstrap`, and `stop` invoke
`mahavishnu bifrost cc-url`
so Claude Code's `ANTHROPIC_BASE_URL` in `~/.claude/settings.json` follows
Bifrost's lifecycle automatically:

- `start`/`restart`/`rebootstrap`: flip Claude onto
  `http://127.0.0.1:8471/anthropic` after the gateway writes its ready file.
- `stop`: restore the prior URL *first*, then tear down the gateway.
- `status`: report which URL Claude is currently configured with.

The toggle is idempotent and never overwrites a URL it did not set itself.
The prior URL is saved to `~/.config/bifrost/claude-url-backup.txt` while
Bifrost is up and removed on stop.

**Important:** Claude Code reads `~/.claude/settings.json` once per session.
Restart Claude Code after toggling for the change to take effect.

### Operational notes

- after repeated rapid restarts, launchd may report `spawn scheduled` before the job becomes healthy again
- in that state, wait roughly one `ThrottleInterval` window before assuming startup failed
- if you need a predictable recovery path, prefer `mahavishnu bifrost stop` followed by `mahavishnu bifrost start`
- `mahavishnu bifrost` now force-kills any orphan listener on `127.0.0.1:8471` before restart/rebootstrap so stale child processes do not hold the port open
- when validating the OpenAI provider, distinguish protocol failures from account-state failures:
  `429 insufficient_quota` from `/v1/responses` means the gateway path is working and the backing OpenAI account needs billing/quota attention
- if the launchd job fails to start with `spawnSync .../bifrost-http-0 EACCES`, the npm package's native binary landed without an execute bit.
  Run `chmod +x ~/Library/Caches/bifrost/<version>/bin/bifrost-http-0` for the affected version, then re-run `mahavishnu bifrost start`.
- if the launchd job still fails to start after the chmod (with `Unknown system error -88` from `spawnSync`), macOS Gatekeeper is rejecting the unsigned native binary.
  Run `codesign --force --sign - ~/Library/Caches/bifrost/<version>/bin/bifrost-http-0` to ad-hoc sign it, then re-run `mahavishnu bifrost start`. See `docs/BIFROST_REACTIVATION_RUNBOOK.md` for details.
