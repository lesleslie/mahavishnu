---
status: active
role: canonical
kind: decision
date: 2026-11-08
last_reviewed: 2026-11-13
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

2. **The client does not pin the lookup path.** `cache_mode: semantic`
   sends no `x-bf-cache-type`, leaving the gateway's default order —
   direct first, semantic as the fallback. `cache_mode: direct` still pins
   the exact path for an operator who wants zero embedding cost. The
   operator setting is oneiric's `Literal["off", "direct", "semantic"]` and
   was not widened; a fourth mode would be a cross-repo change to a pinned
   dependency for no operational gain.

3. **The plugin's own settings stay.** `exclude_system_prompt: false` is
   upstream's default and the safe one: the system prompt carries the
   persona, the working directory, the date and the project instructions,
   and dropping it lets two sessions collide. `threshold: 0.95` stays
   stricter than upstream's `0.8` — on a shared bucket a looser floor buys
   false positives faster than hits, and upstream's own guidance is that
   tighter thresholds reduce false positives where similar phrasing carries
   different intent. `conversation_history_threshold: 16` stays, and
   `cache_tool_call_responses: false` is now pinned explicitly in the
   template rather than left to the default, so an upgrade cannot widen it.

4. **A per-session cache key is the shape of a future reversal.** If the
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

**Applied 2026-11-08:** the operator-facing change — removing
`x-bf-cache-key` from `~/.claude/settings.json` — was run with
`mahavishnu bifrost cc-url bifrost`, which reported *"applied x-bf-cache-key:
removed"*. It takes effect for **new** Claude Code sessions only, because
`ANTHROPIC_CUSTOM_HEADERS` is read at session start. Verified 2026-11-12:
the live settings file carries `x-bf-vk` and `x-bf-route` and no cache key,
and a request without it returns no `X-Bifrost-Cache-*` headers at all.

**Closed 2026-11-12 — the provider's prompt-cache TTL, and the lever was
the wrong one.** Three findings, in order of how much they changed the
plan:

1. **Bifrost's `prompt_cache` block cannot reach Claude Code at all.** Its
   upstream schema (`https://www.getbifrost.ai/schema`, the `prompt_cache`
   definition in Bifrost v2.5.1) reads: *"Synthesize prompt-cache
   breakpoints for requests that carry none. Off by default. Agentic clients
   such as Codex send no cache markers…"* and *"Requests that already carry
   their own cache_control or prompt_cache_breakpoint are never
   modified."* Claude Code always carries its own markers, so configuring
   `prompt_cache` on a provider would have done nothing for this traffic.
   The block is for Codex-style clients, and no Codex traffic appears in
   this gateway's logs. The earlier reasoning here — that `auto_inject` is
   "a no-op while" Claude Code sends its markers — understated it: the
   injection is skipped, not merely overridden.

2. **The real lever is on the client, and it is already on the short
   default.** Claude Code v2.1.323 exposes `promptCacheTtl` /
   `CLAUDE_CODE_PROMPT_CACHE_TTL` for the main conversation and
   `subagentPromptCacheTtl` / `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` for
   everything else, both `"5m"` or `"1h"`. Its own description of the
   default is the finding: *"Unset = automatic: 1 hour on a Claude
   subscription within its usage limits, **5 minutes on an API key**,
   Bedrock, Vertex or Foundry."* This gateway authenticates with a virtual
   key — the API-key branch — so the effective TTL was always 5 minutes.
   (Anthropic prices a 1-hour cache write at 2× base against 1.25× for a
   5-minute write; MiniMax's cache-write rate is $0.375/M against $0.30/M
   uncached, so a re-written prefix must be read twice inside the window to
   pay for itself.)

3. **The population the lever was sized against no longer exists.** The
   original estimate — ~146 requests a day past the cliff, ~15.3M tokens,
   ~$70/month — was measured against the 11-06…11-08 traffic. That traffic
   has gone:

   | day | requests | prompt tokens |
   |---|---|---|
   | 11-06 | 12,620 | 1,781M |
   | 11-07 | 12,662 | 2,480M |
   | 11-08 | 14,094 | 2,275M |
   | 11-09 | 880 | 143.6M |
   | 11-12 | 329 | 60.2M |
   | 11-13 | 54 | 8.6M |

   Re-running the gap analysis on the current two days: **309 requests
   inside a 5-minute gap, one request past 30 minutes.** At this traffic
   the TTL lever addresses roughly one request a day, so it is worth
   approximately **$0/month**. The lever is *correct* and *unused*; it is
   simply not worth using at this volume.

**The decision is therefore: leave the TTL alone.** No `prompt_cache`
block on any provider, and no `CLAUDE_CODE_PROMPT_CACHE_TTL` in the
harness settings. Re-open it when either condition returns — (a) traffic
goes back to fleet scale, or (b) the prefix-mutation fault below is
explained and turns out to be a TTL problem.

### What the live probe established

A controlled probe (`/tmp/bifrost_prompt_cache_ttl_probe2.py`, seven arms:
prefix size × marker placement × requested TTL × direct-vs-gateway) ran
against MiniMax's own endpoint and through the gateway, with reads at
+90s (inside the 5-minute window) and +9min (past it). Four facts came
out of it, and one non-fact:

- **Bifrost passes `cache_control` through faithfully.** Matching arms
  returned identical usage direct and through the gateway, at every
  round. The gateway is not mangling the markers, and it is not the
  cause of anything below.
- **MiniMax caches Claude Code's shape of request reliably.** A repeat of
  an identical 27k-token request read **27,535 tokens back** at +90s on
  every arm. There is no minimum prefix size either — a 4,540-token
  prefix cached fine (4,608 read).
- **MiniMax never reports the write.** `cache_creation_input_tokens` is
  `0` and `cache_creation` is `null` on the direct leg even when a write
  plainly happened. Only `cache_read_input_tokens` is trustworthy; a
  "created = 0" in any probe is not evidence that nothing was cached.
- **The TTL comparison is inconclusive, and the reason matters.** The
  same nominal 5-minute arm survived 9 minutes in one variant
  (`direct/sys-20k/5m` → 27,392 read at +9min) and expired in another
  (`direct/msg-20k/5m` → 189). The two 1-hour arms disagreed with each
  other too: the direct one expired and the gateway one survived. So
  **MiniMax's cache lifetime is not deterministic under this load** —
  provider-side eviction or replica routing dominates the outcome — and
  a TTL A/B cannot separate the requested TTL from that variance. This
  also means the "5-minute cliff" this investigation started from is not
  a fixed property of MiniMax here; it is one observation of a
  distribution.

That last point is the reason the TTL lever is not merely "not worth it
at current traffic" but **not measurable with the tooling available**.
Even at fleet scale, an A/B would have to control for eviction to mean
anything.

**Closed 2026-11-13 — the provider-cache misses have two causes: Claude
Code's tool set changing inside a session (now fixed, in the harness),
and the auto-mode classifier's own request shape (still open).** The
mechanism was proved by capturing real request bodies through a loopback
proxy in front of the gateway, so no gateway configuration was changed and
no other session's traffic was recorded.

**The mechanism.** The Anthropic cacheable prefix is built in the order
**tools → system → messages**, and the `tools` array is at its front.
Captured consecutive requests from one scratch session show Claude Code
**adding tools mid-session**:

| request | tool count | tool characters | tool added |
|---|---|---|---|
| 002 | 12 | 30,339 | — |
| 003 | 13 | 33,494 | `mcp__bodai__wake` |
| 006 | 14 | 41,233 | `Monitor` |
| 007 | 15 | 42,067 | `mcp__bodai__telepathy_receive` |

Two sources: an MCP server connecting after the session began
(`mcp__bodai__*`), and Claude Code materialising a **deferred tool** on
demand (`Monitor`, behind `ToolSearch`). Because the tools sit at the
front of the prefix, either change invalidates the *entire* cached
prefix — which is why the failures are **whole-request misses** rather
than partial ones, and why the cached read lands on 128–600 tokens:
that is MiniMax's own fixed server-side prefix, and nothing of Claude
Code's content was cached.

With a stable tool set the cache is effectively perfect: one captured
request read **81,083 of 81,084 tokens** back (99.99%).

**What the fault looks like in aggregate.** The whole-request miss rate
falls as sessions get longer, which is the signature of a per-session
re-warm amortised over more turns.

The gateway's log carries two distinct request families from Claude
Code, and they cache very differently. They separate by `object_type`
(streamed vs not) and are confirmed by their output profile: the
conversation averages 721 output tokens and stops with `tool_calls`; the
other averages 46 and stops with `length` — a verdict truncated at a
capped budget. Over seven days on the MiniMax path:

| family | requests | input tokens | cache read | whole-request misses | re-read | cost |
|---|---|---|---|---|---|---|
| conversation (streamed) | 23,914 | 5.03B | **97.7%** | 1,655 | 57.3M | $17.18 |
| auxiliary (non-streamed) | 7,320 | 584M | **35.1%** | 3,041 | 218M | $65.37 |
| all MiniMax | 31,234 | 5.61B | 91.1% | 4,696 | 280M | $83.97 |

Total re-processed input: **280M tokens over 7 days — $83.97, about
$360/month** at $0.30/M.

The auxiliary family is the **auto-mode safety classifier**: a per-turn
request carrying the security-review prompt and the pending tool call,
with no tools of its own. Its dynamic content sits *inside* its own
cacheable region, so it can only ever cache its stable head — 35.1%
against 97.7% for the conversation. It can never share a cache entry
with the conversation, and no tool-set change reaches it.

**The tool-set churn is real, and it is the smaller half.** Of the
conversation family's whole-request misses, 1,383 are *churn-shaped* —
the previous request in the same session was under five minutes earlier,
so the provider had no reason to have evicted — and 120 are
eviction-shaped. The churn-shaped misses re-read 30.3M tokens.

| | conversation cache read rate | churn re-read | cost |
|---|---|---|---|
| before | 97.66% | 30.3M tokens / 7d | $9.08 / 7d |
| after | **98.26%** | ~0 | ~$0 |

**$38.92 a month** — against $280 a month in the auxiliary family that
the same fix cannot reach.

**What this rules out, with evidence:**

- **Not the gateway.** A seven-arm controlled probe (prefix size ×
  marker placement × requested TTL × direct-vs-gateway, read at +90s and
  +9min) returned *identical* usage on matching direct and gateway arms
  at every round. Bifrost passes `cache_control` through faithfully.
- **Not the TTL.** The same nominal 5-minute arm survived 9 minutes in
  one variant and expired in another, and the two 1-hour arms disagreed
  with each other. The cache lifetime is not deterministic under this
  load, so a TTL A/B cannot separate the requested TTL from
  provider-side eviction — and the "5-minute cliff" was one observation
  of a distribution, not a fixed property.
- **Not an unreliable lookup.** Sixteen byte-identical requests hit
  16/16.
- **Not the model alias.** The alias substitutes before the provider
  call, so MiniMax sees the same resolved model either way, and the
  `model` field is not part of the cacheable prefix.

**Also settled:** the cached amount *is* the shared-prefix boundary. A
synthetic mutation ladder moved it in lockstep with the mutation
(0 → 3,584 → 5,888 → 7,168 → 8,192 → 8,704), which is what made the
counter a ruler rather than a boolean. And MiniMax never reports the
write: `cache_creation_input_tokens` is `0` and `cache_creation` is
`null` even when a write plainly happened, so only
`cache_read_input_tokens` is trustworthy.

**Where the fix lives — the client, not the gateway.** Two levers, both
in the harness rather than in Bifrost, and **both landed on 2026-11-13**:

1. **Connect the MCP servers before the first turn**, so the tool set is
   stable from request one. Claude Code chooses its MCP startup mode from
   `CLAUDE_CODE_MCP_STARTUP_WAIT_MS`: unset, the mode is `"lifted"` — *do
   not wait for MCP servers before the first turn* — and a positive value
   makes it `"host_wait"`, waiting up to that many milliseconds for the
   MCP hosts to connect. **`CLAUDE_CODE_MCP_STARTUP_WAIT_MS=10000`** is
   now set in `~/.claude/settings.json`.
2. **Stop deferring a server's tools behind tool search.** An MCP server
   entry in `~/.claude.json` accepts `"alwaysLoad": true`, which Claude
   Code describes as: *"all tools from this server are always included
   in the prompt and never deferred behind tool search … As a side
   effect, true also blocks startup until the server is connected."* It
   is set for `bodai`, whose tools (`mcp__bodai__wake`,
   `mcp__bodai__telepathy_receive`) demonstrably arrived late in the
   capture above.

> **A correction to this record's earlier reasoning.**
> `CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS` is *not* the connect-timing
> lever. It bounds how long a running MCP **tool call** may take before
> Claude Code moves it to a background task. It says nothing about when
> the server connects, and the harness's existing `1000` is about call
> backgrounding. The connect-timing levers are
> `CLAUDE_CODE_MCP_STARTUP_WAIT_MS`, `CLAUDE_CODE_MCP_PREWAIT_SERVERS`
> and per-server `alwaysLoad`.

Neither is a Bifrost setting, and Bifrost's `prompt_cache` block cannot
help: it is skipped for any request that already carries its own
`cache_control` markers, which every Claude Code request does.

**What the fix does not reach.** The auxiliary family's 218M re-read
tokens — **$280 a month**, seven times the churn prize — are untouched
by it. That family carries no tool set of its own; its prefix changes
because its *own* dynamic content moves. The only lever on it is not
running the classifier at all, which is a security-posture decision
rather than a cache decision. It is the next open question, not a
closed one.

## Related

- `config/bifrost/README.md` — "The two caches", `cache_mode`, "Complexity
  Router"
- `docs/decisions/2026-11-07-bifrost-complexity-router.md` — the routing
  rules that share this gateway's request path
- `docs/plans/2026-10-29-bifrost-bodai-cache-wiring.md` — the original
  empirical header mapping (§4.4)
