---
status: active
role: canonical
kind: decision
date: 2026-11-08
last_reviewed: 2026-11-08
topic: bifrost-cache-layers
---

# 2026-11-08-bifrost-cache-layers.md

## Context

Bifrost's admin dashboard reports a cache hit rate per provider. On this
gateway that rate is 91–92% of input tokens, and the gateway's own semantic
cache sits at 0.4% of requests. The two numbers are not in conflict: they
measure **different layers**, and reading them as the same thing is what
makes the second look broken.

| | Provider prompt cache | Gateway semantic cache |
|---|---|---|
| Caches | the request's **token prefix** | the whole **response** |
| Key | a hash of a byte-stable prefix | an embedding, compared by cosine similarity |
| Scoped by | the request itself | the operator's `x-bf-cache-key` bucket |
| Saves | input tokens | the whole upstream call |
| On a 250k-token agent request | works — only the tail is recomputed | the embedding is rejected; no lookup happens |
| On an agent loop (the prompt changes every turn) | ~91–92% of input tokens | ~0.4% of requests |

The provider cache needs nothing from us. Claude Code resends the same
system prompt, tool definitions and transcript every turn, so the *front* of
the request is stable by construction and the provider caches it. Measured
over 48h: each request's cached read is **exactly** the previous request's
prompt count, so only the newest turn is recomputed — 96–99% per request in
steady state.

A whole-response cache is the wrong tool for an agent loop. It hits only on
near-identical prompts, which is an FAQ-bot workload. Over 48h it served 43
of Claude Code's 11,077 requests — worth **$2.60 a month** against a
**$4,832** monthly bill — while every consulted request paid an embedding
round trip (~950 ms, measured in the plugin's own logs) and 59% of them
failed the embedding outright.

The failures are structural, not a tuning problem. `text-embedding-3-small`
rejects inputs over 8192 tokens, and the embedded text is a *subset* of the
request, not the request: a request of 127,696 prompt tokens embedded without
incident while one of 9,047 tokens was rejected. The overflow is in the
conversation content that gets embedded — a large tool result, a long turn —
**not** in the system prompt.

Three further findings shaped the decision:

- **The client was pinning the lookup to the one path that could fail.**
  `x-bf-cache-type` *limits* a Bifrost lookup to a single path. Sending
  `semantic` forfeited the direct path — free, hash-based, and the only one
  with no input-size ceiling — and left every oversized request with no
  lookup at all. Omitting the header is Bifrost's documented default: direct
  first, semantic as the fallback, which is also the economically correct
  order (a direct match costs nothing beyond a vector-store lookup; a
  semantic match pays one embedding call).
- **The bucket did not isolate Claude Code from itself.** The bucket is one
  static string in `~/.claude/settings.json`, so every Claude Code session
  on the host shares it, and Bifrost scopes cache entries by virtual key and
  *user* — and Claude Code sends no user id, so all of its sessions land in
  one scope. Two cross-session cache hits were measured in 24h: one session
  was served another's response. The system prompt in the key is not a
  discriminator when two sessions share a working directory and a date.
- **The provider cache has a lever this gateway was not using.** Its TTL is
  5 minutes, and the cliff is measurable: the uncached fraction runs 8%
  within five minutes of the previous request, 22% after ten, and 99.9%
  after thirty. About 146 requests a day land past the cliff and re-process
  ~15.3M tokens.

## Decision rule

1. **Claude Code does not use the gateway's response cache.** The toggle
   writes no `x-bf-cache-key` for it, and removes a stale one. With the
   plugin's `default_cache_key` unset, a request that names no bucket does
   not reach the cache at all — so the header's absence is what keeps the
   harness out of it. The provider's prompt cache is a different layer, is
   unaffected by any header the toggle writes, and is the cache that
   actually carries this traffic. Qwen Code keeps its bucket; its traffic
   has not been measured.

   > **This exclusion rests on `default_cache_key` staying unset.** Upstream's
   > rule is that with neither a per-request key nor a configured default,
   > `resolveCacheKey` returns false and the plugin exits before any lookup
   > or write. Set a default and Claude Code would fall into it, with every
   > session on the host in one namespace — the exact bleed the exclusion
   > removes. The two facts are coupled, so they are asserted together in
   > `tests/unit/test_bifrost_semantic_cache_config.py::test_claude_codes_exclusion_from_the_cache_holds`.
   > The live store was checked on 2026-11-08: `config_plugins.config`
   > carries no `default_cache_key`.

1. **The client does not pin the lookup path.** `cache_mode: semantic`
   sends no `x-bf-cache-type`, leaving the gateway's default order —
   direct first, semantic as the fallback. `cache_mode: direct` still pins
   the exact path for an operator who wants zero embedding cost. The
   operator setting is oneiric's `Literal["off", "direct", "semantic"]` and
   was not widened; a fourth mode would be a cross-repo change to a pinned
   dependency for no operational gain.

1. **The plugin's own settings stay.** `exclude_system_prompt: false` is
   upstream's default and the safe one: the system prompt carries the
   persona, the working directory, the date and the project instructions,
   and dropping it lets two sessions collide. `threshold: 0.95` stays
   stricter than upstream's `0.8` — on a shared bucket a looser floor buys
   false positives faster than hits, and upstream's own guidance is that
   tighter thresholds reduce false positives where similar phrasing carries
   different intent. `conversation_history_threshold: 16` stays, and
   `cache_tool_call_responses: false` is now pinned explicitly in the
   template rather than left to the default, so an upgrade cannot widen it.

1. **A per-session cache key is the shape of a future reversal.** If the
   response cache is ever wanted back on the Claude Code path, the bucket
   has to be per session — and the gateway, not the client, is the right
   place to derive it: Bifrost's plugin hooks can rewrite a request header
   in place after authentication, so a hook could set
   `x-bf-cache-key` from the `x-claude-code-session-id` the harness already
   sends. The economics would still have to justify it: at 0.4% of requests
   and $2.60 a month, it does not today.

## Status

Active — code landed 2026-11-08. The toggle change is in
`mahavishnu/bifrost/models.py` (`HarnessDescriptor.cache_enabled`) and
`mahavishnu/bifrost/toggles.py`; the header change is in
`mahavishnu/bifrost/cache_headers.py`. `config/bifrost/README.md` carries
the operational detail under "The two caches".

**Not yet applied:** the operator-facing change — removing
`x-bf-cache-key` from `~/.claude/settings.json` — is run by
`mahavishnu bifrost cc-url bifrost`, and takes effect for **new** Claude
Code sessions only, because `ANTHROPIC_CUSTOM_HEADERS` is read at session
start.

**Open, and deliberately so:** the provider's prompt-cache TTL. Bifrost
supports a per-provider `prompt_cache` block with `ttl: "1h"`, and upstream's
rule is "caller markers always win" — Claude Code sends its own
`cache_control` markers, so `auto_inject` is a no-op while it does. Whether
Bifrost's injection would apply on top of those markers, and whether MiniMax
honours a requested one-hour TTL, is **untested**. The ceiling is the ~146
requests a day that re-process 15.3M tokens after a pause, worth roughly
$70/month — but MiniMax charges $0.375/M to *write* a cache against
$0.30/M for uncached input, so a re-written prefix read only once costs more
than not caching it. Measure before changing anything.

## Related

- `config/bifrost/README.md` — "The two caches", `cache_mode`, "Complexity
  Router"
- `docs/decisions/2026-11-07-bifrost-complexity-router.md` — the routing
  rules that share this gateway's request path
- `docs/plans/2026-10-29-bifrost-bodai-cache-wiring.md` — the original
  empirical header mapping (§4.4)
