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
- The transport binary is pinned to **v2.5.0** (upgraded from v2.4.0 on
  2026-11-07) — see "Transport Version Pin" below. Verify with
  `curl -s http://127.0.0.1:8471/api/version`.
- Live providers: `minimax-anthropic` (MiniMax's Anthropic-native
  `/anthropic/v1/messages` — the path Claude Code needs), `minimax-openai`
  (MiniMax's OpenAI-compatible `/v1/chat/completions` — the path the
  Mahavishnu worker uses), `llama-server` (`qwen3-8b-q4_k_m` local), `openai`
  (`gpt-5.4` family), `typesafe` (the decision model behind the complexity
  router — see "Complexity Router" below).
- **The `route-anthropic-native` rule is live and corrected.** The store's
  target names the provider only (`model` is NULL, so the caller's model
  passes through), the fallback is `minimax-anthropic/MiniMax-M3.1-Flash`
  (the same protocol, so it can actually serve the request), `count_tokens`
  is allowed with its own path override, and the key lists `MiniMax-M3` and
  `MiniMax-M3.1-Flash`. The store is authoritative and
  the template is only its seed — see "Custom Providers: Three Silent Traps".
- **Both harnesses route through the gateway, and both are verified.**
  `mahavishnu bifrost verify-gate` passes for Qwen Code
  (`provider=minimax-anthropic status=success via claude-cli/0.26.1`), and a
  Claude Code-shaped request returns a **signed** `thinking` block with the
  route rule firing on both.
- Claude Code's `ANTHROPIC_BASE_URL` in `~/.claude/settings.json` is now
  `http://127.0.0.1:8471/anthropic` (via Bifrost), with `x-bf-vk`,
  `x-bf-route: anthropic_native` and `x-bf-cache-key: claude-code:<hash>` in
  `ANTHROPIC_CUSTOM_HEADERS`. Qwen Code's `modelProviders.anthropic` entry
  carries the same three, with `qwen-code:<hash>` as its bucket.
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

The transport version is pinned to **v2.5.0** in two places that a CI guard
test keeps in sync:

- `mahavishnu/bifrost/paths.py` → `BIFROST_TRANSPORT_VERSION`
- `config/launchd/ai.bifrost.gateway.plist` → `BIFROST_TRANSPORT_VERSION`

The launcher receives `--transport-version=v2.5.0` and strips the flag before
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
curl -s http://127.0.0.1:8471/api/version   # e.g. "v2.5.0"
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

> **The `[1m]` suffix was retired on 2026-11-07.** It was never a model id.
> It is a Claude Code-side convention: *"Claude Code strips the suffix before
> sending the model ID to your provider"*
> (code.claude.com/docs/en/model-config). The shipped binary carries the same
> logic (`strip1mTag`, `toProviderWireModelId`), and a control probe with a
> deliberately bogus id returned MiniMax's error naming the id *without* the
> suffix. MiniMax has no 1M-suffixed variant, and `MiniMax-M3` already has a
> 1M-token window with a guaranteed 512K floor — the suffix bought a
> *client-side claim*, not a larger window.
>
> `ANTHROPIC_DEFAULT_OPUS_MODEL` is now plain `MiniMax-M3`, and the key's
> model list no longer carries the `[1m]` spelling. Two reasons:
> `CLAUDE_CODE_MAX_CONTEXT_TOKENS` already caps the session at 512K, so the
> 1M claim bought nothing; and the inner `claude` CLI that the
> security-review plugin spawns does not recognise `MiniMax-M3[1m]` as a
> model id at all (`[claude-code:unrecognized_model]`), which is one of the
> reasons its reviews kept failing.
>
> A client that forwards the literal suffix no longer reaches MiniMax's
> `2013`. With the spelling gone from the key's allowlist, key selection does
> not match it, and the request falls through to the rule's fallback —
> `minimax-anthropic/MiniMax-M3.1-Flash` — which serves it normally. Verified
> live 2026-11-07: `MiniMax-M3[1m]` comes back with
> `response.model == "MiniMax-M3.1-Flash"` and the answer intact.
>
> That is *better* than the allowlist entry it replaced. With the entry
> present, key selection matched the key and Bifrost then handed MiniMax an
> id the provider rejects (`invalid params, unknown model 'MiniMax-M3[1m]'`).
> Without it, the request is served by a model that exists.

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

`BifrostLLMSettings.cache_mode` (`off` | `direct` | `semantic`) is consumed by
`mahavishnu/bifrost/cache_headers.py`, which turns it into the gateway's
`x-bf-cache-*` request headers. It was advisory-only for a while — the
`mahavishnu/llm_gateway` package that consumed it was deleted in commit
`03146be0`, and nothing read the setting again until REQ-BIFROST-037
restored the wiring.

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
- **Claude Code** and **Qwen Code** are both pointed at the gateway
  (`http://127.0.0.1:8471/anthropic`) by `mahavishnu bifrost cc-url bifrost`
  and `mahavishnu bifrost qwen-url bifrost`. Both carry the gateway virtual
  key, the `anthropic_native` route header, and a cache bucket of their own.
  `qwen-url direct` / `cc-url direct` put them back.

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
| `off` | `x-bf-cache-no-store: true` | The response is **not written** to the cache, and the request points at a bucket nothing was ever written to, so it cannot be served from one either. |
| `direct` | `x-bf-cache-type: direct` | Only the exact-match path is searched. No embedding is generated, so this mode costs nothing beyond a vector-store lookup. |
| `semantic` | *no type header* | The gateway's own default order: the exact-match path first, vector similarity as the fallback. Similarity caching is on — it is the fallback path. |

Every mode also sends `x-bf-cache-key` to scope entries to a bucket
(`default` unless a caller names another).

> **Why `semantic` sends no type header.** Sending `x-bf-cache-type` *limits*
> the lookup to a single path; omitting it is Bifrost's documented default,
> which tries the direct path first and falls back to the semantic one. That
> order is the economically correct one — a direct match is a hash of the
> input and costs nothing beyond a vector-store lookup, while a semantic match
> pays one embedding call — and it is the only order in which a request whose
> text exceeds the embedding model's 8192-token input ceiling still gets a
> lookup at all. The direct path hashes rather than embeds, so it has no
> ceiling.
>
> Measured against this gateway: pinning a request to the semantic path gave
> 514 of 869 consulted requests no lookup whatsoever (the embedding was
> rejected outright) and forfeited every exact repeat. See
> [The two caches](#the-two-caches).

> **Callers within a traffic class still share a bucket.** The bucket
> is derived — `<traffic-class>:<hash of the gateway virtual key>` — so it
> is never the fleet-wide `default`, and a second virtual key would split
> it again with no code change. But this deployment issues exactly one
> `BIFROST_VIRTUAL_KEY`, so the hash is the same for every caller: the
> namespace is split by protocol surface (`worker`, `agno-openai`,
> `agno-anthropic`, `claude-code`), not by tenant.
>
> Real per-tenant isolation means a distinct virtual key per tenant:
> Bifrost issues keys per key, so giving each tenant its own
> `BIFROST_VIRTUAL_KEY` separates the buckets without a code change.
> Recorded as an open risk in the plan.

**The harnesses' buckets.** `mahavishnu bifrost qwen-url bifrost` writes
`x-bf-cache-key: qwen-code:<hash>` into the matching Qwen provider entry's
`generationConfig.customHeaders`, alongside `x-bf-vk` and `x-bf-route`.
Without it, a harness's requests carry no bucket header and the plugin has no
key to resolve — so with `default_cache_key` unset (upstream's default) the
request does not reach the cache at all.

**Claude Code carries no bucket at all**, and that is deliberate. The bucket
was introduced to stop two Claude Code sessions colliding — the shape was
reproduced live on 2026-10-30: two requests with the *same* user turn and
*different* system prompts came back `cache_hit: true`, `hit_type: "direct"`,
the same `cache_id`, served in 1–47 ms instead of ~700 ms. But a bucket does
not close that hole: it is one static string, so every Claude Code session on
the host shares it, and Bifrost scopes cache entries by virtual key and
*user* — and Claude Code sends no user id, so all of its sessions land in one
scope. Two cross-session cache hits were measured in 24h on 2026-11-07: one
session served another's response.

Taking Claude Code out of the response cache closes that hole for good and
costs almost nothing: over 48h the cache served 43 of Claude Code's 11,077
requests — worth **$2.60 a month** against a **$4,832** monthly bill. The
provider's prompt cache is a different layer, is unaffected by any header the
toggle writes, and is already serving 91–92% of input tokens from cache on
this path. See [The two caches](#the-two-caches).

> **The exclusion depends on `default_cache_key` staying unset.** A request
> that names no bucket reaches the cache only if the plugin's
> `default_cache_key` names one — upstream's rule is that with neither set,
> `resolveCacheKey` returns false and the plugin exits before any lookup or
> write. Set a default and Claude Code would fall into it, with every session
> on the host in one namespace. The two facts are coupled, so they are
> asserted together in
> `tests/unit/test_bifrost_semantic_cache_config.py::test_claude_codes_exclusion_from_the_cache_holds`.
> The live store was checked on 2026-11-08: `config_plugins.config` carries no
> `default_cache_key`.

Two limits worth stating plainly:

- **It separates a harness from the fleet, not from itself.** The bucket is
  written once into the harness's settings, so every session of that harness
  on the host shares it. What keeps two sessions apart is the system prompt,
  which the cache key carries: it holds the working directory, the date and
  the project instructions, so two sessions in two directories hash to two
  different keys. The conversation history the key also carries helps, and the
  gateway's `conversation_history_threshold: 16` stops caching entirely past
  sixteen messages, so a long session is not cached at all.
- **A bucket is not an authorisation boundary.** The gateway does not check
  that the presented credential owns the bucket it names; the derivation is
  a convention that keeps this deployment honest, not an enforcement.

> **`off` means off.** It suppresses the cache *read* as well as the write.
> Bifrost v2.5.0 has no header that suppresses a read —
> `x-bf-cache-no-store` is documented upstream as "skip writing the response
> to cache (still served from cache on hit)" — so the repo's `off` mode
> points at a bucket nothing was ever written to. The cache key is encoded
> into the direct cache ID and is an equality filter on the semantic
> search, so a bucket with no entries cannot be hit on either path.

**The cache headers are sent even when the virtual key is missing.** They
express an operator retention control, and a missing credential must not
invert it: without `x-bf-cache-no-store` the gateway could resolve the
bucket from its own `default_cache_key` and write the prompt and response
into a shared cache — the opposite of `cache_mode: off`. A missing key
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

### The two caches

Bifrost's admin dashboard shows a cache hit rate per provider. That number
and this gateway's own semantic cache measure **different layers**, and
confusing them is what makes the second one look broken.

| | Provider prompt cache | Gateway semantic cache |
|---|---|---|
| Caches | the request's **token prefix** | the whole **response** |
| Key | a hash of a byte-stable prefix | an embedding, compared by cosine similarity |
| Scoped by | the request itself | the operator's `x-bf-cache-key` bucket |
| Saves | input tokens | the whole upstream call |
| On a 250k-token agent request | works — only the tail is recomputed | the embedding is rejected; no lookup happens |
| On an agent loop (the prompt changes every turn) | ~91–92% of input tokens | ~0.4% of requests |

The provider cache is the one that matters on this path, and it needs nothing
from us: Claude Code resends the same system prompt, tool definitions and
transcript every turn, so the *front* of the request is stable by
construction and the provider caches it. Measured over 48h on this gateway:

| model | requests | prompt tokens | read from the provider cache |
|---|---|---|---|
| `MiniMax-M3` | 17,820 | 3,367,102,459 | 91.5% |
| `MiniMax-M3.1-Flash` | 5,336 | 1,008,293,993 | 92.6% |

Per request the steady state is 96–99%: each request's cached read is
*exactly* the previous request's prompt count, so only the newest turn is
recomputed.

The gateway's semantic cache, meanwhile, served 43 requests in 24h — worth
**$2.60 a month** against a **$4,832** monthly bill. Its ceiling, even if it
hit every Claude Code request, is the output tokens alone (~$279/month), and
that would need a 100% hit rate on requests whose prompts are all different.

So a whole-response cache is the wrong tool for an agent loop and the prefix
cache is the right one. The response cache earns its keep on the short,
repetitive traffic the repo's own clients send — the Agno and worker paths —
and is kept off the Claude Code path for that reason.

> **The provider cache has a lever this gateway is not using.** Bifrost
> supports a per-provider `prompt_cache` block whose `ttl` may be `"1h"` —
> upstream's default is 5 minutes, which is the provider's default ephemeral
> cache lifetime — and `cache_control_injection_points` to place breakpoints
> on specific messages. Upstream's rule is "caller markers always win", and
> Claude Code sends its own `cache_control` markers, so `auto_inject` is a
> no-op while it does.
>
> The cliff is measurable here: the uncached fraction runs 8% within five
> minutes of the previous request, 22% after ten, and 99.9% after thirty.
> About 146 requests a day land past the cliff and re-process ~15.3M tokens.
> Extending the TTL would bound that at roughly **$70/month** — but MiniMax
> charges $0.375/M to *write* a cache against $0.30/M for uncached input, so
> a re-written prefix that is read only once costs more than not caching it.
> Whether Bifrost's injection would apply on top of Claude Code's markers, and
> whether MiniMax honours a requested one-hour TTL, is **not yet tested**.

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
- `web_search` or `webSearch` -> `minimax-openai/MiniMax-M3.1-Flash`
- `image` -> `minimax-openai/MiniMax-M3.1-Flash`
- `background`, `cheap`, or `high_throughput` -> `minimax-openai/MiniMax-M3.1-Flash` (fallback `llama-server/qwen3-8b-q4_k_m`)
- `x-bf-route: anthropic_native` -> provider `minimax-anthropic`, model as sent by the caller (fallback `minimax-anthropic/MiniMax-M3.1-Flash`)

The `anthropic_native` route is the only one the **header** rules can fire
on. No production code in this repo emits `x-bf-task` — the package that used
to (`mahavishnu/llm_gateway/`) has been deleted — so the five task-keyed rules
above are unreachable in production. `x-bf-route` is sent by the Claude Code
harness: `mahavishnu bifrost cc-url bifrost` writes
`x-bf-route: anthropic_native` into Claude Code's `ANTHROPIC_CUSTOM_HEADERS`,
and `cc-url direct` removes it again. `cc-url status` reports whether it is
present.

A second route fires on the **complexity tier** rather than on a header:
`route-complexity-simple` (priority 3) matches
`headers["x-bf-route"] == "anthropic_native" && complexity_tier == "SIMPLE"`
and targets `minimax-anthropic/MiniMax-M3.1-Flash`. The tier is computed
inside the gateway, so this rule needs no header the caller does not already
send — see "Complexity Router" below.

Two providers claim `MiniMax-M3`, so the route is what makes the choice
unambiguous: `minimax-anthropic` reaches MiniMax over its Anthropic-native
`/anthropic/v1/messages` (genuine Anthropic responses, signed `thinking`
blocks), while `minimax-openai` reaches it over the OpenAI-compatible
`/v1/chat/completions` (reasoning inline in the assistant text).

Notes:

- these rules are intentionally header-driven for now
- they are meant to reproduce the useful routing buckets from CCR without introducing a second router
- all M3 fallbacks are M3.1-Flash (same generation); the M2.x line is retired upstream (2026-11-18) and no longer referenced
- the `image` route is **enabled**: MiniMax-M3 and M3.1-Flash both accept image
  input on the OpenAI-compatible surface, and both were verified live against
  this gateway on 2026-11-06 (a chart image read correctly, including a
  non-obvious axis value). It was disabled from 2026-05-13 until then with the
  note "Deferred until a supported MiniMax multimodal adapter exists" — a
  deferral written three weeks *before* MiniMax-M3 shipped (2026-06-01), and
  one the gateway never needed: Bifrost's `base_provider_type: openai` passes
  `image_url` blocks straight through to `/v1/chat/completions`
- the `anthropic_native` target must pin the **provider only** — leave `model`
  unset. A pinned model overrides the caller's, which silently moves
  Claude Code's `MiniMax-M3.1-Flash` haiku slot onto `MiniMax-M3`.
  Verified live 2026-11-06
- the `llama-server-local` key allowlists **both** `qwen3-8b-q4_k_m` and the
  repo-wide `qwen3.5` label. The gateway resolves a request against the key's
  allowlist *before* the call, so a label llama.cpp would ignore is still a
  400 at the gateway if the allowlist omits it
- **prerequisite for routing Claude Code through the gateway**: Claude Code
  must not share the semantic cache's shared `default` bucket. Its system
  prompt carries the date, working directory and environment, and it used to
  be excluded from the cache key, so two agents with the same user turn
  would collide. **Done twice over** — `cc-url bifrost` now sends
  `x-bf-cache-key: claude-code:<hash>`, and the plugin keeps the system
  prompt in the key (`exclude_system_prompt: false`, upstream's default).
  See "Semantic Cache" above for what that does and does not separate.
  Qwen Code gets the same treatment (`qwen-code:<hash>`).
- **Qwen Code goes to the Anthropic surface, not the OpenAI one.** Its active
  model resolves to the `anthropic` provider entry, and that entry is what
  the toggle points at `http://127.0.0.1:8471/anthropic` — so Qwen reaches
  MiniMax's Anthropic-native endpoint and gets signed thinking blocks, the
  same as Claude Code. It also gets `x-bf-route: anthropic_native`, so the
  provider choice is explicit rather than left to bare model-name
  resolution. The `openai` provider entry (DashScope) is left alone.

## Complexity Router

Bifrost's routing plugin can classify each request as `SIMPLE`, `MEDIUM`, or
`COMPLEX` and publish the tier to the CEL engine as `complexity_tier`. The
configuration lives at `governance.complexity_analyzer_config` in the template.

**The decision model.** The classifier is `decision`: the request is classified
by a decision model, here TypeSafe's `jev-latest` through the `typesafe`
provider. That provider's key resolves from `env.TYPESAFE_API_KEY`, which the
gateway provisions from `~/.config/secrets.env` — `TYPESAFE_API_KEY` is in
`mahavishnu/bifrost/gateway.py::NEEDED_KEYS` for exactly that reason. Without
it the gateway never resolves the variable, Bifrost drops the key at startup,
and every classification fails with `no_key_supports_model` — which surfaces as
"the router never produces a tier" rather than as a credential error.

**Session-aware routing is on (`session.enabled: true`).** A turn's first
request carries the human text and gets a tier; the turn's continuation
requests carry only tool results and do not. Without session state one turn
would run on two models — the model that decides the next action and the model
that reads the tool result — and the provider's prompt cache would miss at the
seam. With it the tier holds for the session. Session identity comes from
`x-bf-session-id` or the harness-native `x-claude-code-session-id`; a request
without one is classified on its own.

**The tier policy is downward-only.** Only `SIMPLE` carries a model target.
`MEDIUM` and `COMPLEX` keep the caller's model through `route-anthropic-native`,
so nothing is ever moved onto the heavier model: Claude Code picks the model
per request class (`MiniMax-M3` for the opus and sonnet slots,
`MiniMax-M3.1-Flash` for the haiku slot), and a pinned model on a higher tier
would override that — and would override the security-review plugin's
deliberate Sonnet fallback, which `MiniMax-M3`'s adaptive thinking truncates.

**Session affinity overrules the model target.** Bifrost runs a second routing
engine, `session-affinity`, after the routing rules. It binds
`(session id, requested model)` to the provider and model the session was
first served, and it wins over a rule's proposed model. Three consequences:

- The downgrade only reaches a model class whose **first** request in a
  session classified as SIMPLE. A session bound to `MiniMax-M3` before the
  router was live stays on it, so most live traffic is not downgraded.
- An escalation does **not** restore the caller's model. A session that
  started SIMPLE stays on `MiniMax-M3.1-Flash` after it escalates, because
  affinity discards the routing proposal.
- **The discount is session-wide, not per-turn.** The binding persists for
  the session, so one SIMPLE turn rebinds that session's whole model class
  to the cheap model — and every later request in the class is served by
  it, including MEDIUM and COMPLEX turns whose tier said to keep the
  caller's model. Measured on 2026-11-07: one session's first SIMPLE turn
  was followed by 266 MEDIUM requests that asked for `MiniMax-M3` and were
  served `MiniMax-M3.1-Flash`.

Read the engine's own log to see which way it went:

```bash
sqlite3 ~/.config/bifrost/logs.db \
  "SELECT routing_engine_logs FROM logs
    WHERE routing_rule_id='route-complexity-simple' ORDER BY timestamp DESC LIMIT 1"
```

`session-affinity` is a built-in engine in the pinned v2.5.0 transport — not
a provider setting, not a plugin, and not a `governance_config` key. The
store exposes no switch for it.

**Pricing it.** Because the outcome of a request cannot be read from the
tier alone, it is measured per request:

```bash
mahavishnu bifrost complexity-report --hours 24
```

The report separates the classifier's token cost, the traffic the cheap
model actually served, the requests where the session binding overruled
the tier, and the classifications that were paid for and not acted on. Add
`--fail-on-hazard` to make it a monitor. See
`docs/plans/2026-11-07-bifrost-complexity-accounting.md`.

**Observability.** The request log records `complexity_tier`,
`complexity_mechanism` (`semantic`, `decision`, `llm`, `session`, or `skipped`)
and `complexity_score`. The logs API filters on the first two:

```bash
curl 'http://127.0.0.1:8471/api/logs?complexity_tiers=COMPLEX&complexity_mechanisms=decision'
```

The same fields are in the request log database, which needs no admin token:

```bash
sqlite3 ~/.config/bifrost/logs.db \
  "SELECT timestamp, model, complexity_tier, complexity_mechanism,
          routing_rule_id, routing_engines_used
     FROM logs WHERE complexity_tier IS NOT NULL
     ORDER BY timestamp DESC LIMIT 10"
```

`complexity_mechanism: session` means a stored session tier was reused;
`skipped` means no tier was produced.

**Applying it.** The store is authoritative and the template is only its seed,
so the config takes effect after:

```bash
.venv/bin/mahavishnu bifrost rebootstrap
```

Never `--drop-db` — that discards the store, and with it the virtual key and
the dashboard admin account.

**Where it lands in the store.** The reconcile writes the analyzer config into
the store's `complexity_semantic_config` entity — *not* into
`complexity_analyzer_config`, which holds the retired lexical scorer's state
(`tier_boundaries` + `keywords.code_keywords`) and is left alone. Reading the
wrong entity is the easy mistake here, so read the store rather than the
template:

```bash
sqlite3 ~/.config/bifrost/config.db \
  "SELECT json_extract(value,'$.classifier'), \
          json_extract(value,'$.decision.model'), \
          json_extract(value,'$.session.enabled') \
   FROM governance_config WHERE key='complexity_semantic_config'"
```

**Bifrost merges the keyword lists.** The reconcile unions the template's
`keywords` lists with whatever the store already holds instead of replacing
them, so the live counts are the union of the template's 18/16/14 phrases and
the 50 reference phrases per tier the store already carried (68/66/64 on
2026-11-07). The decision classifier does not read them; a later switch to the
semantic classifier would read the union.

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
- later changes in `config.json` are ignored while `config_store` is enabled —
  with one exception observed on 2026-11-07: the complexity analyzer's fields
  were re-imported from `config.json` at startup, and their `keywords` lists
  were merged rather than replaced. Treat `rebootstrap` as the way to land a
  change, and read the store to confirm what landed.
- routing rules, virtual keys, and governance settings should be managed through the Bifrost UI or public config APIs

If you need to re-bootstrap from file config, use `mahavishnu bifrost rebootstrap`.
It re-seeds `config.json` from `config/bifrost/config.template.json` and restarts
the gateway. The config store is **kept** (it is authoritative for providers,
keys, governance config, and virtual keys) and is backed up first, under
`~/.config/bifrost/.bak/`. Pass `--drop-db` only if you deliberately want to
discard it.

## Guard: Anthropic First-Party Tools vs. the Gateway

Claude Code ships bundled skills under
`bundled-skills/<version>/<hash>/`. The `claude-api` skill's
`drop_block_probe.py` probes Anthropic's *preserved thinking* controls
(`thinking-binding-controls-2026-08-01`, `block_binding`). It is stdlib-only,
authenticates with `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN`, and takes its
endpoint from `--base-url` — defaulting to `$ANTHROPIC_BASE_URL`.

When Claude Code is routed through this gateway, the session environment sets
`ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic`. The probe inherits it,
asks a MiniMax-backed provider for a Claude model id, and fails with
`no keys found that support model: claude-opus-5-5` — a 400 that reads like a
gateway fault and is not one. Observed on 2026-11-06: 242 `claude-opus-5-5`
and 30 `claude-sonnet-4-6` requests, all 0% success, from
`user_agent: Python-urllib/3.13` on the `bodai-pi-pool` virtual key.

The probe is **first-party only** by its own documentation ("it authenticates
against `/v1/messages` with `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`").
MiniMax implements none of the controls it measures, so it cannot produce a
meaningful result against this gateway on any model id — it would report
`NOT WIRED` and exit 1 by design.

`.claude/hooks/bifrost-anthropic-probe-guard.py` is a `PreToolUse` guard that
denies the combination: Anthropic's tooling **and** an effective base URL of
this gateway. It never blocks ordinary Bash work, and it never second-guesses
an explicit choice:

| Command shape | Result |
|---|---|
| no `--base-url`, session env points at the gateway | **denied** (exit 2) |
| `--base-url <anything>` | allowed — the operator chose the endpoint |
| `env -u ANTHROPIC_BASE_URL …` / `unset ANTHROPIC_BASE_URL` | allowed — scrubbed |
| inline `ANTHROPIC_BASE_URL=…` | resolved from the command, then judged |

The guard requires the command to **execute** the tooling, not merely name
it — reading or grepping the probe's source cannot reach the network, and
blocking those calls would make the guard a nuisance rather than a safeguard.
A command that runs Python (`python`, `python3`, `python3.13`, an absolute
path, a venv interpreter) while naming the probe or the bundled `claude-api`
skill counts as an invocation; `grep`, `cat`, and `ls` over the same paths do
not. A leading `VAR=value` assignment is an environment prefix, not the
command being run, so `P=/path/probe.py grep …` is not an invocation either.

To run the probe against Anthropic:

```bash
env -u ANTHROPIC_BASE_URL -u ANTHROPIC_AUTH_TOKEN -u ANTHROPIC_CUSTOM_HEADERS \
  ANTHROPIC_API_KEY=sk-ant-... \
  python3 <script> --self-test --model claude-opus-5-5 --yes \
  --base-url https://api.anthropic.com
```

The guard lives in this repo (source of truth, with unit tests in
`tests/unit/hooks/test_bifrost_anthropic_probe_guard.py`). It is registered
per-harness, because the hazard is machine-wide rather than repo-scoped:

```bash
# repo-scoped (this repo's sessions)
#   .claude/settings.json -> hooks.PreToolUse, matcher "Bash"
# user-scoped (every session on this machine)
#   ~/.claude/settings.json -> hooks.PreToolUse, matcher "Bash"
```

## Model Aliases: Claude Ids Onto MiniMax

Some Claude Code **plugins** call the Anthropic API directly, in-process,
rather than through Claude Code's own model selection. They pick their own
model id — Anthropic's — and inherit the session's `ANTHROPIC_BASE_URL`, so
the request lands on this gateway and is answered with

```
400 {"type":"error","error":{"type":"no_key_supports_model",
     "message":"no keys found that support model: claude-opus-5-5"}}
```

The security-review plugin is the confirmed case: it asked for
`claude-opus-5-5` and `claude-sonnet-4-6` on three separate commits and got
no verdict each time, because the request never reached a model. The failure
is silent — the review is simply skipped — and it is logged at
`~/.claude/security/log.txt`.

`ANTHROPIC_DEFAULT_*_MODEL` does not help here: it governs Claude Code's own
model selection, not a plugin's direct SDK call. The lever that does work is
a **key-level alias**, which Bifrost resolves after key selection and before
the provider call.

Both `minimax-anthropic` and `minimax-openai` carry the alias map, so the
behaviour does not depend on which surface a client happens to use:

```json
"aliases": {
  "claude-opus-5-5": "MiniMax-M3",
  "claude-sonnet-4-6": "MiniMax-M3.1-Flash",
  "claude-haiku-5-5": "MiniMax-M3.1-Flash"
}
```

### Aliases Must Be Double-Specified

Bifrost treats alias names as model identifiers for key selection and
allowlists. When a key's `models` list is restricted — and these keys' are —
the alias name must **also** appear in that list, or the gateway cannot
select the key for it and the request fails exactly as it did before the
alias was added. Upstream issue
[maximhq/bifrost#3278](https://github.com/maximhq/bifrost/issues/3278)
documents this. So both the alias map and the allowlist carry the Claude ids:

```json
"models": ["MiniMax-M3", "MiniMax-M3.1-Flash", "claude-opus-5-5", "…"],
"aliases": { "claude-opus-5-5": "MiniMax-M3" }
```

`tests/unit/test_bifrost_config_template.py` pins both halves of that rule,
plus the fact that an alias target must itself be a model the key serves.

### What an Alias Does and Does Not Mean

An alias **substitutes** a model: a caller that asked for `claude-opus-5-5`
is served `MiniMax-M3`. It is a graceful-degradation mechanism for clients
that hardcode Anthropic model ids, not a claim that MiniMax is Claude. The
Opus, Fable and Mythos ids map to `MiniMax-M3`, MiniMax's reasoning-grade
model; the Sonnet and Haiku ids map to `MiniMax-M3.1-Flash`, its concise
counterpart.

### Why Sonnet Is Not MiniMax-M3

The tiering is load-bearing, not cosmetic. The security-review plugin calls
`claude-opus-5-5` first and falls back to `claude-sonnet-4-6` when the
primary yields no verdict. It sends `thinking: {"type": "adaptive"}` with
`max_tokens=16000`.

On a review-sized diff (30 changed files, measured 2026-11-07) MiniMax-M3's
adaptive thinking consumes the *entire* output budget: the response comes
back thinking-only with `stop_reason: max_tokens`, the plugin finds no
`type == "text"` block, and the review ends with "no verdict from the model".
The same payload on `MiniMax-M3.1-Flash` completes in 2193 output tokens with
a usable text block.

So the primary attempt keeps the stronger model — on a diff small enough for
it to finish, the review gets the better analysis — while the fallback id
carries the model that reliably fits inside the budget. That is what makes
the fallback land instead of truncating the same way.

Note the truncation mode is **not** caused by the alias: it also occurred on
2026-11-06 at 12:59 and 13:40, before any alias existed. The alias moved
the failure from "rejected at key selection" (HTTP 400) to "answered but
truncated", and the Sonnet mapping closes the second gap.

The alias map deliberately covers the **current** Claude lineup plus the
immediately previous generation. Adding an id that no client requests costs
nothing but adds to the treadmill; the list is therefore kept to ids that
Anthropic's own bundled skill documents or that were observed failing in the
gateway logs.

### Applying a Change to the Live Store

`config.json` is only a first-run seed — the `config_store` database is
authoritative, and it reconciles against the template per entity by content
hash. To push a template change into the live store:

```bash
.venv/bin/mahavishnu bifrost rebootstrap   # backs up config.db, then restarts
```

Never pass `--drop-db`: it discards the store, and with it the virtual key
and the dashboard admin account.

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
| `threshold` | `0.95` | Cosine floor for a similarity hit. `0.8` is Bifrost's generic default, tuned for single short prompts; here the embedding covers a whole conversation, so it is loose. `resolveCacheThreshold` takes `max(config, per-request)`, so a higher floor can only be raised. Retuned from `0.86` on 2026-11-01: all 8 measured legitimate paraphrases score ≥ `0.9545`, and the `0.870` same-session collision class now misses instead of serving the prior turn's response. |
| `conversation_history_threshold` | `16` | Bifrost skips caching **entirely** — both layers — for requests with more than this many messages. Its default of `3` disables the cache for nearly all agentic traffic, which resends the full transcript every turn. Raised from `8` on 2026-11-01: 98.6% of the admitted population exceeds the embedding ceiling and therefore runs the safe direct path, so only 1.4% can reach the collision-prone semantic path. That last part only holds because the client does **not** pin the lookup with `x-bf-cache-type` — see [`cache_mode`](#cache_mode). **The name reads the wrong way round:** it is the point *past which caching stops*, not a count of messages included in the key. Bifrost's Helm chart docs still carry the older wording, and lowering it skips *more* traffic, not less. |
| `exclude_system_prompt` | `false` | **Upstream's default, and it is the safe one.** The system prompt carries the persona, the working directory, the date and the project instructions — the things that distinguish one session from another. Dropping it from the key lets two requests with identical messages but different system prompts share an entry, and one be served the other's cached response. That collision was reproduced live against this gateway before the setting was reverted. **Cost:** the system prompt now counts against the embedding model's input budget (see the 8192-token limit below), so a long session can fall off the *semantic* path sooner. The *direct* path hashes the input rather than embedding it, so it is unaffected. |
| `default_cache_key` | *unset* | Upstream's default is empty, and it is the safe one: with no per-request `x-bf-cache-key` and no default, `resolveCacheKey` returns false and the plugin's pre-LLM hook exits before any lookup or write. Setting it to a fixed value puts every client that does not name a bucket into one shared namespace. Callers that want the cache name their own. |
| `cache_by_model` / `cache_by_provider` | `true` | Keep model/provider in the filter so a cached response never crosses providers. |
| `cache_tool_call_responses` | `false` | Upstream's default, pinned here so an upgrade cannot widen it. A replayed tool call runs in a later caller's agent loop with arguments chosen for someone else's prompt. Verified against the live store: 0 of the 67 entries in the `BifrostSemanticCachePlugin` Redis namespace carry a client tool call. |

Two upstream requirements that are easy to miss:

1. **The embedding model must be in the provider's key allowlist.** The `openai`
   provider's key declares `models: [...]`, and Bifrost resolves a key *before*
   dispatching upstream. If `text-embedding-3-small` is absent from that list,
   every embedding attempt fails locally with `no_key_supports_model` and the
   request never reaches OpenAI — so no amount of upstream credit fixes it.
1. **The embedding model has an 8192-token input limit.** The plugin embeds
   the request's key material with no truncation, and long agentic turns
   exceed the limit — the embedding request comes back as
   `Invalid 'input': maximum context length is 8192 tokens`. The plugin
   degrades gracefully — it logs the skip and falls through to the upstream
   provider — but those requests are never cached semantically.

   Measured here (24h): 514 of the 869 consulted requests failed this way.
   The embedded text is a *subset* of the request, not the request — a
   request of 127,696 prompt tokens embedded without incident, while one of
   9,047 tokens was rejected. The overflow is in the conversation content that
   gets embedded (a large tool result, a long turn), **not** in the system
   prompt, so `exclude_system_prompt` does not fix it.

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
