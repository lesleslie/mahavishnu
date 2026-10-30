# Bifrost Bootstrap Notes

This directory contains the bootstrap artifacts for the local Bifrost gateway.

Current status (verified live, 2026-10-30):

- **Bifrost is live on `127.0.0.1:8471`.** Verified by
  `curl -fsS http://127.0.0.1:8471/health` returning `{"status":"ok",...}`
  (HTTP 200) and the launchd ready file at `~/.local/state/mcp/ready/bifrost.ready`.
- The earlier "paused indefinitely" state from 2026-06-26 (macOS Gatekeeper on
  `@maximhq/bifrost`'s native binary) has been resolved or worked around. The
  launchd job (`ai.bifrost.gateway`) and the Oneiric-secret-resolving
  `mahavishnu bifrost status` are healthy.
- The transport binary is pinned to **v2.4.0** (upgraded from v2.3.2 on
  2026-10-29) — see "Transport Version Pin" below. Verify with
  `curl -s http://127.0.0.1:8471/api/version`.
- Live providers: `minimax-anthropic` (MiniMax's Anthropic-native
  `/anthropic/v1/messages` — the path Claude Code needs), `minimax-openai`
  (MiniMax's OpenAI-compatible `/v1/chat/completions` — the path the
  Mahavishnu worker uses), `llama-server` (`qwen3-8b-q4_k_m` local), `openai`
  (`gpt-5.4` family).
- **The live store still carries the first version of the
  `route-anthropic-native` rule** (model pinned to `MiniMax-M3`, fallback
  `minimax-openai/MiniMax-M3`, no `count_tokens` permission). The template in
  this directory carries the corrected rule — see "Custom Providers: Three
  Silent Traps" — but the store is a separate artifact and is only re-seeded
  from the template when it is explicitly synced. Until that happens the live
  gateway still downgrades the 1M-context model, refuses the token-count
  call, and has an inert fallback.
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

## Transport Version Pin

The npm package `@maximhq/bifrost` is **only a launcher**. It downloads the
native `bifrost-http` binary from `downloads.getmaxim.ai` and resolves
`latest` on every boot. The npm version number (1.6.x) is unrelated to the
transport version that actually runs.

The transport version is pinned to **v2.4.0** in two places that a CI guard
test keeps in sync:

- `mahavishnu/bifrost/paths.py` → `BIFROST_TRANSPORT_VERSION`
- `config/launchd/ai.bifrost.gateway.plist` → `BIFROST_TRANSPORT_VERSION`

The launcher receives `--transport-version=v2.4.0` and strips the flag before
exec'ing the binary.

**To roll back on the launchd path**, edit `BIFROST_TRANSPORT_VERSION` in
`config/launchd/ai.bifrost.gateway.plist` and restart the gateway.
launchd's `EnvironmentVariables` *replace* the inherited environment, so an
export in your shell never reaches the gateway, and `install_plist()`
re-copies the repo plist over the installed one on every
start/restart/rebootstrap — editing the installed plist directly is undone.
The `BIFROST_TRANSPORT_VERSION` environment variable only affects a
foreground run (`mahavishnu bifrost foreground`).

Two traps this pin avoids:

- **A silent upstream swap.** Unpinned, the next upstream release replaces the
  binary on the next restart, with no change on this side.
- **A launcher too old to parse the flag.** The flag is stripped by the
  launcher's own argument parser; a launcher that does not know it forwards
  the flag to the binary, which rejects unknown flags and refuses to boot.
  `gateway.launcher_supports_transport_version()` checks the cached launcher
  and falls back to `npx` when it is too old.

**Which cached launcher gets used.** `find_cached_bifrost_bin()` picks the
**newest** cached `@maximhq/bifrost`, by the version in its `package.json` —
not by path. npm's `_npx` cache directories are named by an opaque hash, so
path order is arbitrary: it selected the *older* launcher (1.6.2 rather than
1.6.3) on this host. The newer launcher validates the arguments it forwards
to the transport binary against a known-flag list; the older one forwards
them verbatim, and the binary refuses to boot on a flag it does not know.

Verify what is actually running:

```bash
curl -s http://127.0.0.1:8471/api/version   # e.g. "v2.4.0"
```

**Architecture matters.** The launcher picks the build from `node -p process.arch` (`x64` → `darwin/amd64`, `arm64` → `darwin/arm64`). Downloading
a binary by hand with the wrong architecture fails at exec with
`spawnSync ... Unknown system error -86` (EBADARCH). This host is Intel
(x86_64).

## Custom Providers: Three Silent Traps

Adding a provider to `config.template.json` looks like it should just work.
It often does not, and when it does not, **the gateway starts cleanly, health
is green, and the request simply does not work**. All three traps below cost
a Claude Code route that had been silently falling through to the wrong
provider.

**1. A custom provider may not be named after a standard provider.** Upstream
refuses such a name outright — the providers API answers HTTP 400, *"Custom
provider cannot be same as a standard provider"* — and the config-file import
on this deployment did not register the provider either: the store held no
`anthropic` row and every Claude Code request failed with `failed to get config for provider anthropic: not found`. Name custom providers distinctly:
`minimax-anthropic`, not `anthropic`. The key name is a good hint — a key
called `minimax-anthropic-primary` implies a provider called
`minimax-anthropic`.

**2. `allowed_requests` and `request_path_overrides` are keyed by request
type, and `messages` is not one of them.** Bifrost's Anthropic HTTP route
(`/anthropic/v1/messages`) bridges to the generic `responses` request type.
So:

```json
"custom_provider_config": {
  "allowed_requests": {
    "count_tokens": true,
    "responses": true,
    "responses_stream": true
  },
  "base_provider_type": "anthropic",
  "request_path_overrides": {
    "count_tokens": "/anthropic/v1/messages/count_tokens",
    "responses": "/anthropic/v1/messages",
    "responses_stream": "/anthropic/v1/messages"
  }
}
```

An unknown key is ignored, and because unspecified `allowed_requests` fields
default to `false`, a single wrong key leaves the provider allowing
*nothing*.

`count_tokens` is its own request type and its own HTTP route
(`POST /v1/messages/count_tokens`). It needs both the permission *and* the
path override: the default Anthropic path does not exist on MiniMax, whose
Anthropic surface lives under `/anthropic/`. Claude Code sends the
token-count call with the same `x-bf-route` header as everything else, so
the provider has to allow it or the call fails with an operation-not-allowed
error.

**3. A routing-rule target that names a `model` overwrites the caller's
model.** Upstream keeps the incoming model when the target omits it:

> `model` — *Target model (omit or empty to use the incoming request model)*

So a target that pins `MiniMax-M3` rewrites every request that asked for
something else. Claude Code picks the model per request class — the
`MiniMax-M3` slots (opus and sonnet) and `MiniMax-M3.1-Flash` (haiku) — so
a pinned model silently moved the fast slot onto the heavy model: no
error, no log line, and a different price. Pin the **provider**; let the
model through. The provider's key must then list every model id the caller
actually sends.

> **The `[1m]` suffix never reaches the gateway.** It is a Claude Code-side
> convention: *"Claude Code strips the suffix before sending the model ID to
> your provider"* (code.claude.com/docs/en/model-config). The shipped
> binary carries the same logic (`strip1mTag`, `toProviderWireModelId`), and
> a control probe with a deliberately bogus id returned MiniMax's error
> naming the id *without* the suffix. `MiniMax-M3[1m]` is therefore not a
> model id at all — MiniMax has no 1M-suffixed variant, and
> `MiniMax-M3` already has a 1M-token window with a guaranteed 512K floor.
> Sending the literal string to MiniMax is a 400
> (`invalid params, unknown model 'MiniMax-M3[1m]' (2013)`).
>
> The suffix still matters *inside* Claude Code: it is how Claude Code
> learns the model has a 1M window, and it suppresses proactive compaction
> for that model alias. The key's model list carries the `[1m]` spelling so
> that a client which does forward it still resolves a key and falls
> through to the fallback, rather than failing at key resolution.

**How to tell whether a provider actually landed:** the config store is
authoritative, so compare it against the template rather than trusting the
file:

```bash
python3 -c "
import pathlib, sqlite3
db = pathlib.Path.home()/'.config'/'bifrost'/'config.db'
con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
print([r[0] for r in con.execute('SELECT name FROM config_providers')])
"
```

`tests/unit/test_bifrost_config_template.py` pins all three against the
template. It cannot see the live store — a store that was never re-seeded
keeps serving the old configuration no matter what the template says.

## The Anthropic-Native Path and the Thinking Budget

The `minimax-anthropic` provider serves MiniMax's Anthropic-native
`/anthropic/v1/messages`, which returns genuine Anthropic responses —
reasoning as a **signed `thinking` block**, not inline in the assistant text.

It also enforces Anthropic's thinking floor: with `thinking` enabled, the
budget must be **at least 1024 tokens**. A request below that is rejected
with `400 invalid_request_error: reasoning.max_tokens must be >= 1024 for anthropic`.

**The `route-anthropic-native` rule's fallback is
`minimax-anthropic/MiniMax-M3.1-Flash`** — the same provider on a different
model. It has to be: the Anthropic ingress bridges every request to the
`responses` request type, and the OpenAI-compatible `minimax-openai` provider
only allows `chat_completion`, so it cannot serve this request at all. A
chat-completions fallback there is inert, and the request fails hard instead
of degrading.

A fallback on the same provider also means a below-1024 thinking budget
still fails, rather than silently degrading to inline reasoning: both models
speak the Anthropic protocol and enforce the same floor. Claude Code's own
thinking budgets are 1024 and above, so it does not hit this.

If reasoning appears inline in the assistant text, check the gateway's
request log for the request's provider attribution before assuming the route
is misconfigured:

```bash
python3 -c "
import pathlib, sqlite3
l = sqlite3.connect(f\"file:{pathlib.Path.home()/'.config'/'bifrost'/'logs.db'}?mode=ro\", uri=True)
l.execute('PRAGMA query_only = ON')
for ts, prov, rule, key, status in l.execute(
    'SELECT timestamp, provider, routing_rule_id, selected_key_name, status '
    'FROM logs ORDER BY timestamp DESC LIMIT 5'):
    print(f'{ts[:23]} {prov!r:20} rule={rule!r} key={key!r} status={status!r}')
"
```

### The route is a bridge, not a wire

`minimax-anthropic` is a *custom* provider, and upstream's Anthropic raw
passthrough only fires for the standard provider name `anthropic` — a custom
name falls through to the typed conversion path. So the request is
re-serialised into Bifrost's internal Responses shape and re-encoded on the
way back. The **shape** is what Claude Code needs (a signed `thinking`
block, real Anthropic content blocks), but it is not byte-for-byte
forwarding: Anthropic fields with no representation in the Responses schema
are dropped by the bridge rather than passed through, and raw request/response
capture is not populated. That trade-off is unavoidable while the provider
must carry a non-standard name — see trap 1 above.

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

> **Callers within a traffic class still share a bucket.** The bucket
> is derived — `<traffic-class>:<hash of the gateway virtual key>` — so it
> is never the fleet-wide `default`, and a second virtual key would split
> it again with no code change. But this deployment issues exactly one
> `BIFROST_VIRTUAL_KEY`, so the hash is the same for every caller: the
> namespace is split by protocol surface (`worker`, `agno-openai`,
> `agno-anthropic`, `claude-code`), not by tenant. Within a class, two
> agents with different personas but the same user turn can collide — the
> semantic cache's `exclude_system_prompt: true` drops the system prompt
> from the key — and one can be served the other's cached response.
>
> Real per-tenant isolation means a distinct virtual key per tenant:
> Bifrost issues keys per key, so giving each tenant its own
> `BIFROST_VIRTUAL_KEY` separates the buckets without a code change.
> Recorded as an open risk in the plan.

**The harnesses' buckets.** `mahavishnu bifrost cc-url bifrost` writes
`x-bf-cache-key: claude-code:<hash>` into Claude Code's
`ANTHROPIC_CUSTOM_HEADERS`, and `mahavishnu bifrost qwen-url bifrost`
writes `x-bf-cache-key: qwen-code:<hash>` into the matching Qwen provider
entry's `generationConfig.customHeaders`. Both sit alongside `x-bf-vk` and
`x-bf-route`. Without them, a harness's requests carry no bucket header and
the gateway resolves the plugin's shared `default_cache_key` — the same
namespace the rest of the fleet falls back into, and one in which a
harness's own sessions share entries.

That last part is the reason it exists. Reproduced live on 2026-10-30: two
requests with the *same* user turn and *different* system prompts — the
shape of two Claude Code sessions in two directories — came back
`cache_hit: true`, `hit_type: "direct"`, the same `cache_id`, served in
1–47 ms instead of ~700 ms. The system prompt carries the date, working
directory and environment, and the cache is configured to exclude it, so
without a bucket of its own one session can be served another's cached
response.

Two limits worth stating plainly:

- **It separates Claude Code from the fleet, not from itself.** The bucket
  is written once into `~/.claude/settings.json`, so every Claude Code
  session on the host shares it. What keeps two sessions apart in practice
  is the conversation history the cache key also carries — and the
  gateway's `conversation_history_threshold: 8`, which stops caching
  entirely past eight messages, so a long session is not cached at all.
- **A bucket is not an authorisation boundary.** The gateway does not check
  that the presented credential owns the bucket it names; the derivation is
  a convention that keeps this deployment honest, not an enforcement.

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
- `x-bf-route: anthropic_native` -> provider `minimax-anthropic`, model as sent by the caller (fallback `minimax-anthropic/MiniMax-M3.1-Flash`)

The `anthropic_native` route is the **only one that can currently fire**.
No production code in this repo emits `x-bf-task` — the package that used to
(`mahavishnu/llm_gateway/`) has been deleted — so the five task-keyed rules
above are unreachable in production. `x-bf-route` is sent by the Claude Code
harness: `mahavishnu bifrost cc-url bifrost` writes
`x-bf-route: anthropic_native` into Claude Code's `ANTHROPIC_CUSTOM_HEADERS`,
and `cc-url direct` removes it again. `cc-url status` reports whether it is
present.

Two providers claim `MiniMax-M3`, so the route is what makes the choice
unambiguous: `minimax-anthropic` reaches MiniMax over its Anthropic-native
`/anthropic/v1/messages` (genuine Anthropic responses, signed `thinking`
blocks), while `minimax-openai` reaches it over the OpenAI-compatible
`/v1/chat/completions` (reasoning inline in the assistant text).

Notes:

- these rules are intentionally header-driven for now
- they are meant to reproduce the useful routing buckets from CCR without introducing a second router
- all M3 fallbacks are M3.1-Flash (same generation); the M2.x line is retired upstream (2026-11-18) and no longer referenced
- the `image` route is currently disabled in the template until the gateway has a supported multimodal adapter
- **prerequisite for routing Claude Code through the gateway**: Claude Code
  must not share the semantic cache's shared `default` bucket. Its system
  prompt carries the date, working directory and environment, and the plugin
  excludes the system prompt from the cache key, so two agents with the same
  user turn would collide. **Done** — `cc-url bifrost` now sends
  `x-bf-cache-key: claude-code:<hash>`; see "Semantic Cache" above for what
  that does and does not separate. Qwen Code gets the same treatment
  (`qwen-code:<hash>`).
- **Qwen Code goes to the Anthropic surface, not the OpenAI one.** Its active
  model resolves to the `anthropic` provider entry, and that entry is what
  the toggle points at `http://127.0.0.1:8471/anthropic` — so Qwen reaches
  MiniMax's Anthropic-native endpoint and gets signed thinking blocks, the
  same as Claude Code. It also gets `x-bf-route: anthropic_native`, so the
  provider choice is explicit rather than left to bare model-name
  resolution. The `openai` provider entry (DashScope) is left alone.

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
