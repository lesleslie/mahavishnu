---
status: partial
role: canonical
kind: plan
date: 2026-11-01
last_reviewed: 2026-11-08
superseded_by: null
topic: bifrost-cache-eviction-and-threshold
title: "Bifrost cache eviction sweep and cache-tuning retune"
requirements:
- id: REQ-BIFROST-042
  title: Expired Bifrost cache entries are reclaimable without a gateway restart
- id: REQ-BIFROST-043
  title: The eviction sweep never removes a live entry or a non-Bifrost key
- id: REQ-BIFROST-044
  title: The cache tuning thresholds are justified by recorded measurement
---

# Plan — Bifrost cache eviction sweep and cache-tuning retune

> **Status: partial** (verified 2026-11-08). The sweep, the schedule and
> the live config satisfy §9 conditions 1–3. Condition 4 is not met:
> §4.6 is recorded in `config/bifrost/README.md`, but §4.5's band-separation
> analysis — benefit band `0.9545–0.9784` against risk band
> `0.9511/0.9798/0.9842`, and the threshold comparison showing no
> similarity threshold separates the bands — is not.

## 1. Outcome

The Bifrost semantic-cache store stops growing without bound, and the two
cache gates that currently keep ~96% of gateway traffic out of the cache are
retuned against measured data instead of inherited defaults.

**Success signals:**

- The Bifrost Redis store holds no entry whose `expires_at` is in the past
  for longer than one sweep interval.
- `mahavishnu bifrost cache-sweep --dry-run` reports the expired-entry count
  and byte weight of what a real sweep would remove.
- The similarity threshold is raised to `0.95` with every measured legitimate
  paraphrase still hitting, and the similarity threshold and the
  conversation-history threshold are each justified by a recorded measurement
  rather than by a default.

## 2. Goals

1. Add a periodic sweep that removes expired Bifrost cache entries from
   Redis, without touching live entries or any non-Bifrost key.
2. Wire the sweep so it runs without an operator (a launchd timer), and
   expose it as an operator command that reports what it did.
3. Raise the semantic cache's similarity threshold to a value that keeps
   every measured legitimate paraphrase hit while dropping the weakest
   measured same-session collision band.
4. Raise `conversation_history_threshold` from `8` to `16`, with the
   collision exposure of the admitted population quantified.
5. Record the measured band separation — or lack of it — so a future
   change to these knobs is made against data.

## 3. Non-Goals

1. **Not** changing Bifrost itself. The missing turn-identity filter in the
   `semanticcache` plugin is an upstream defect; this plan mitigates it
   from the configuration side and records it for an upstream issue.
2. **Not** changing the embedding model or the Redis vector index dimension.
   `text-embedding-3-small` and `text-embedding-3-large` share the same
   8191-token input ceiling, and the RediSearch `VECTOR` attribute is
   created with a fixed `dim` that RediSearch cannot resize in place.
3. **Not** adding a Redis `maxmemory` eviction policy. LRU eviction would
   discard *live* entries under pressure; the correct rule here is
   "expired means gone".
4. **Not** claiming a semantic-cache hit rate improvement for the
   Mahavishnu worker path. That path has one cache entry in three days of
   logs; there is no data to improve on yet.

## 4. Current Findings

All figures below were measured against the running gateway at
`127.0.0.1:8471` and its Redis store at `localhost:6379`, on 2026-11-01.

### 4.1 The cache is functioning

- Gateway healthy; `semantic_cache` plugin enabled; Redis `vector_store`
  configured at `localhost:6379`.
- Direct (exact-match) path: hits at every prompt size tested, up to ~9000
  tokens.
- Semantic (vector) path: hits at 29 / 1002 / 8002 embedding tokens, with
  similarity `1.000` against a `0.86` threshold.
- Real Claude Code traffic populates the derived bucket
  `claude-code:5c578932e1df` (167 entries).
- Bucket isolation holds: the same prompt in a different bucket misses, then
  caches independently.
- The shared `default` / `Default` buckets hold 1198 entries and **zero**
  live ones — the isolation fix in commit `2b80457f` is effective, and
  `default_cache_key` is unset in the live config.
- `tests/integration/test_bifrost_semantic_cache_e2e.py`: 5/5 passed.

### 4.2 Expiry is enforced in-band, and nothing ever reclaims the space

Every cache entry is a Redis HASH carrying an `expires_at` field (epoch
seconds). The Redis key TTL is `-1` — never expires. Bifrost checks
`expires_at` at read time and skips the entry; it never deletes it.

- `BifrostSemanticCachePlugin:*` — 1504 entries, **16 live, 1488 expired**.
  The expired set holds ~19.3 MB of response payloads.
- `BifrostLocalCachePlugin:*` — 10 entries, all expired (~10.3 days old),
  all in the retired `Default` bucket.
- `BifrostSemanticCachePlugin_d1:*` — 48 entries, all expired, all in the
  retired `Default` bucket, zero growth since ~9.2 days ago. `FT._LIST`
  reports only `BifrostLocalCachePlugin` and `BifrostSemanticCachePlugin` as
  RediSearch indexes, so this namespace is a relic of an older layout.
- Redis: 81.5 MB used, **no `maxmemory` limit** (`maxmemory_human = 0B`).
- The plugin's `cleanup_on_shutdown: true` only fires when the gateway
  exits. The gateway is `KeepAlive`, so it may not exit for weeks.

### 4.3 Two gates, and which one actually binds

| Condition | Direct path | Semantic path |
|---|---|---|
| ≤8 messages, ≤8192 embedding tokens | hit | hit |
| ≤8 messages, >8192 embedding tokens | hit | skipped |
| >8 messages | skipped | skipped |

The message gate flips at **9 total messages** (measured: 8 messages → hit,
9 → no cache headers at all). The token gate is the embedding model's own
8191-token input ceiling; the plugin embeds the *entire* conversation
(system prompt included — confirmed: a 5400-token system prompt produces a
4813-token embedding).

When the semantic search is skipped, Bifrost falls back to the direct path,
so a long prompt still caches on exact repeat. The harness does not send
`x-bf-cache-type`, so this fallback is the default behaviour for Claude Code.

### 4.4 How little reaches the semantic path

Claude Code traffic, 3 days, from the Bifrost request log:

| `cache_debug` state | Requests | Share |
|---|---|---|
| empty (plugin ran, cached nothing) | 15 398 | 96.1% |
| populated (cache engaged) | 622 | 3.9% |

Of the 58 semantic hits in that window, **30 are the e2e test suite**,
27 were measurement probes, and **1** was real Claude Code traffic
(`claude-code:5c578932e1df`, similarity `0.940`).

The intended beneficiary — the Mahavishnu worker path — has **one**
`worker:` bucket entry and **zero** `agno-openai:` / `agno-anthropic:`
entries in three days. The worker path is wired correctly
(`mahavishnu/workers/cloud_worker.py:140` and
`mahavishnu/engines/agno_adapter_impl.py:568`) but has not been exercised.

So: the semantic cache works, and almost nothing is using it.

### 4.5 Benefit band and risk band overlap

Realistic same-intent rewrites (self-contained questions, fresh bucket each
time) versus the same session advancing one turn (alternating user and
assistant messages, realistic sizes):

| Band | Similarities | Hits |
|---|---|---|
| Benefit — same intent, reworded | 0.9545 – 0.9784 | 8/8 |
| Risk — same session, next turn | 0.9511, 0.9798, 0.9842 | 3/3 in-band |

The two bands **overlap**. Bifrost's semantic search filters only by
`cache_key` (the bucket) and then does a pure vector search within it —
there is no turn-identity filter. `params_hash` cannot serve as one: it is
byte-identical across every conversation measured
(`6564897ebb68909c`), because it encodes request *parameters*, not content.

Consequences, measured on the live gateway:

- A longer conversation in the same bucket is served the earlier
  conversation's cached response. Reproducible and deterministic
  (similarity `0.870103240013` on two separate trials).
- Similarity **rises** with conversation length: `0.896` at +1 turn,
  `0.981` at +4 turns.
- Therefore no similarity threshold separates the bands:

| Threshold | Benefit kept | Risk kept |
|---|---|---|
| 0.86 (current) | 100% | 43% |
| 0.95 | 100% | 43% |
| 0.96 | 75% | 29% |
| 0.98 | 0% | 14% |
| 0.99 | 0% | 0% |

This is the upstream defect this plan cannot fix from configuration alone.

### 4.6 The admitted population is 98.6% too large to embed

Of the 15 496 Claude Code requests the 8-message gate currently excludes
(the gate-excluded population is by definition the `>8`-message population):

| Prompt tokens | Requests | Path once admitted |
|---|---|---|
| ≤8192 | 222 (1.4%) | semantic — collision-prone |
| 8k–20k | 113 | direct only — safe |
| 20k–60k | 1242 | direct only — safe |
| >60k | 13 919 | direct only — safe |

Only 1.4% of the admitted population can reach the semantic path; the rest
exceed the embedding ceiling and run the exact-match direct path, which
cannot serve a wrong turn.

The direct path's hit rate on large requests is itself low: 15 direct hits
across 15 274 requests above 8k tokens (0.1%). Direct hits concentrate on
small requests (748 of 763 are ≤8192 tokens) and repeat roughly twice per
cache id.

### 4.7 Historical failures, now resolved

| Failure class | Count | Window | Status |
|---|---|---|---|
| `no_key_supports_model` | 568 | 2026-10-23 → 10-29 | resolved (key allowlist) |
| `insufficient_quota` | 31 | 2026-10-19 → 10-21 | resolved (credit) |
| gateway direct-only fallback | 65 | 2026-04-08 → 10-23 | resolved |
| embedding 8192-token cap | 413+ | 2026-10-30 → present | **live**, mitigated by the direct fallback |

### 4.8 The sweep hung on shutdown — and said nothing

The first version of the sweep drove `coredis` with `asyncio.run`.
`coredis` keeps a reader and a writer task per connection inside an
**anyio** task group, and a plain asyncio runner never cancels that
group on the way out — `asyncio.run`'s shutdown cancels the tasks it can
see, not the ones anyio owns. The process finished the sweep and then
blocked forever on a socket read.

The failure was silent in the worst way:

- `launchctl list` showed a live PID forever, with status `-15`;
- stdout was redirected to a file, so Python's block buffering meant the
  summary line never reached the log — **the log stayed empty**, which
  read as "the sweep never ran";
- every foreground invocation looked fine, because the operator's shell
  saw the output before the process wedged.

The fix is `anyio.run(...)`, which is what `coredis`'s own documentation
prescribes. `anyio` is now declared in the `cache` dependency group
rather than relied on as a transitive dependency.

`tests/integration/test_bifrost_cache_eviction_e2e.py` pins the
*termination*, not the output: a sweep that prints the right numbers and
never exits is a failure.

## 4.5 Requirements

```yaml
requirements:
- id: REQ-BIFROST-042
  title: Expired Bifrost cache entries are reclaimable without a gateway restart
- id: REQ-BIFROST-043
  title: The eviction sweep never removes a live entry or a non-Bifrost key
- id: REQ-BIFROST-044
  title: The cache tuning thresholds are justified by recorded measurement
```

## 5. Implementation Phases

### Phase 1: Eviction sweep

**Goal:** Remove expired Bifrost cache entries from Redis on demand, safely
and idempotently.

**Tasks:**

1. `mahavishnu/bifrost/cache_eviction.py` — the sweep logic.
   - Discover candidate keys with `SCAN` (never `KEYS`), matched against the
     Bifrost cache prefixes only.
   - Decide expiry from the entry's own `expires_at` field.
   - Delete atomically via a Lua script so a write that lands between the
     read and the delete cannot be lost (the script re-reads `expires_at`
     and deletes only if it is still in the past).
   - Never delete an entry that has no `expires_at` field — unknown state is
     kept.
   - Support `--dry-run`.
2. `mahavishnu/cli/bifrost_cli.py` — `mahavishnu bifrost cache-sweep`
   subcommand reporting scanned / live / expired / deleted counts.
3. `tests/unit/test_bifrost_cache_eviction.py` — unit coverage for the
   selection rule and the Lua script's atomicity contract.

**Exit criteria:** the sweep runs against the live store, removes the 1488
expired semantic entries, removes zero live entries, and leaves every
non-Bifrost key untouched.

#### Integration Contract

- **Triggered from**: `mahavishnu bifrost cache-sweep`, and the launchd
  timer in Phase 3 (`config/launchd/ai.bifrost.cache-sweep.plist`).
- **Returns to / updates**: the Redis store at `localhost:6379` — deletes
  HASH keys under the `BifrostSemanticCachePlugin:`,
  `BifrostSemanticCachePlugin_d1:` and `BifrostLocalCachePlugin:` prefixes.
  Deleting a HASH key removes the document from its RediSearch index
  automatically.
- **Demonstrable by**: `mahavishnu bifrost cache-sweep --dry-run` followed by
  `mahavishnu bifrost cache-sweep`, then
  `FT.INFO BifrostSemanticCachePlugin` showing `num_docs` reduced and
  `redis-cli --scan --pattern 'BifrostSemanticCachePlugin:*'` showing only
  live entries.
- **Rollback signal**: the sweep logs `cache_sweep_error` for any key it
  could not read or delete; more than 1% of scanned keys erroring means
  stop the timer. Deleting an expired entry can only cause a cache miss, so
  the blast radius is bounded.
- **Observability added**: one structured log line per sweep
  (`cache_sweep_completed`) carrying scanned / live / expired / deleted
  counts and elapsed time, written to the gateway log directory.

### Phase 2: Retune the two thresholds

**Goal:** Change the live cache configuration to the values justified by
§4.5 and §4.6.

> **Status: applied 2026-11-01.** The authoritative `config_plugins` row,
> the `config.json` seed and the repo template all carry the new values,
> and the gateway was restarted to load them. Verified behaviourally: the
> message-count gate now flips at 17 messages (it flipped at 9 before),
> the e2e suite passes 5/5 against the retuned gateway, and the measured
> 0.870 same-session collision now misses instead of serving the prior
> turn's response.

> **The authoritative store is `config.db`, not `config.json`.**
> `mahavishnu/bifrost/lifecycle.py::sync_config` documents this: with
> `config_store` enabled, the SQLite database is authoritative for
> providers, keys, governance config and plugin configuration;
> `config.json` is only a first-run seed. Editing `config.json` alone
> changes nothing at runtime. The live plugin row reads:
>
> ```sql
> sqlite3 ~/.config/bifrost/config.db \
>   "SELECT config_json FROM config_plugins WHERE name='semantic_cache';"
> ```

**Tasks:**

1. `config/bifrost/config.template.json` and the live
   `~/.config/bifrost/config.json` and `~/.config/bifrost/config.db`:
   - `threshold`: `0.86` → `0.95`. Keeps 8/8 measured legitimate
     paraphrases (minimum observed `0.9545`); drops the `0.870` and `0.896`
     collision classes.
   - `conversation_history_threshold`: `8` → `16`. Of the admitted
     population, 98.6% exceeds the embedding ceiling and therefore runs the
     safe direct path; only 1.4% (222 requests / 3 days) can reach the
     collision-prone semantic path, and that surface is further reduced by
     the threshold above. Sixteen covers a worker or Agno agent-loop shape
     (a task plus tool rounds) without admitting the very long sessions
     whose conversations are dominated by history.
2. `settings/models.yaml` / `mahavishnu/bifrost/models.py` if the operator
   cache mode needs to change — it does not: `cache_mode` stays `semantic`.
3. Record the measurements above in
   `config/bifrost/README.md` next to the existing threshold table, so the
   next operator inherits the reasoning rather than the numbers alone.

**Applying it** — the gateway holds `config.db` open, so the write goes in
while it is stopped:

```bash
mahavishnu bifrost stop
sqlite3 ~/.config/bifrost/config.db \
  "UPDATE config_plugins SET config_json = replace(replace(config_json,
     '\"threshold\":0.86', '\"threshold\":0.95'),
     '\"conversation_history_threshold\":8',
     '\"conversation_history_threshold\":16')
   WHERE name='semantic_cache';"
mahavishnu bifrost start
```

**Exit criteria:** the live config carries the new values, the gateway is
restarted, and `mahavishnu bifrost cache-sweep --dry-run` plus the
`test_bifrost_semantic_cache_e2e.py` suite both pass against the restarted
gateway.

#### Integration Contract

- **Triggered from**: operator edit of the live config store plus
  `mahavishnu bifrost start`.
- **Returns to / updates**: the `config_plugins` row in
  `~/.config/bifrost/config.db` (authoritative), the seed at
  `~/.config/bifrost/config.json`, and the repo template
  `config/bifrost/config.template.json`, so a re-bootstrap does not
  reintroduce the old values.
- **Demonstrable by**: `tests/integration/test_bifrost_semantic_cache_e2e.py`
  passing 5/5 against the restarted gateway — in particular
  `test_paraphrase_is_a_semantic_cache_hit`, which fails if the threshold is
  raised past the paraphrase band.
- **Rollback signal**: the e2e paraphrase test failing, or the production
  semantic-hit count dropping to zero in the request log
  (`json_extract(cache_debug,'$.hit_type')='semantic'`), within one hour
  of the restart.
- **Observability added**: none new — the existing `cache_debug` field
  already carries `similarity`, `threshold` and `hit_type` per request, and
  the sweep log line from Phase 1 reports store growth.

### Phase 3: Schedule the sweep

**Goal:** The store is reclaimed on a schedule, without an operator.

> **Status: applied 2026-11-01.** The agent is installed at
> `~/Library/LaunchAgents/ai.bifrost.cache-sweep.plist` and loaded. Its
> first run reclaimed 108 expired entries and wrote
> `cache_sweep_completed` to
> `~/.local/state/mcp/logs/bifrost-cache-sweep.log`. The install is a CLI
> command rather than a copy-paste step — see task 2.

**Tasks:**

1. `config/launchd/ai.bifrost.cache-sweep.plist` — a launchd agent with
   `StartInterval` (15 minutes), `RunAtLoad`, no `KeepAlive`, logging to
   `~/.local/state/mcp/logs/bifrost-cache-sweep.log`. **Done.**
2. Install and load it through the CLI, following the pattern the
   existing `ai.bifrost.gateway` and `ai.bifrost.redis-stack` plists
   use. **Done** — `mahavishnu/bifrost/lifecycle.py` gained
   `install_cache_sweep_plist()`, `start_cache_sweep()` and
   `stop_cache_sweep()`, exposed as `mahavishnu bifrost
   install-sweep-agent` and `mahavishnu bifrost uninstall-sweep-agent`.

   `launchctl bootstrap` can fail with `EIO` immediately after a
   `bootout`; `start_cache_sweep()` retries once after a short pause.
3. Confirm the sweep does not fight the gateway: the two never hold the
   same key for long, and the Lua delete is atomic against writes.

**Exit criteria:** `launchctl list | grep cache-sweep` shows the agent
loaded, and two consecutive intervals produce a sweep log line.

#### Integration Contract

- **Triggered from**: launchd's `StartInterval`, every 15 minutes.
- **Returns to / updates**: the Redis store at `localhost:6379`, via the
  same sweep implementation as Phase 1.
- **Demonstrable by**: `tail ~/.local/state/mcp/logs/bifrost-cache-sweep.log`
  showing a `cache_sweep_completed` line with a non-zero `expired` count on
  the first run after the backlog is created.
- **Rollback signal**: the sweep log showing repeated
  `cache_sweep_error` entries; the agent is stopped with
  `launchctl bootout`.
- **Observability added**: the `cache_sweep_completed` log line, written
  once per interval.

## 6. Required Code Changes

- [x] `mahavishnu/bifrost/cache_eviction.py` — new: the sweep implementation.
- [x] `mahavishnu/bifrost/__init__.py` — export the sweep entry points.
- [x] `mahavishnu/cli/bifrost_cli.py` — new `cache-sweep` subcommand.
- [x] `mahavishnu/_main_cli.py` — no change (`bifrost_app` is already
      registered; the new command is inside that app).
- [x] `config/launchd/ai.bifrost.cache-sweep.plist` — new: the timer.
- [x] `mahavishnu/bifrost/lifecycle.py` — `install_cache_sweep_plist()`,
      `start_cache_sweep()`, `stop_cache_sweep()`.
- [x] `config/bifrost/config.template.json` — threshold and
      conversation-history-threshold retune.
- [ ] `config/bifrost/README.md` — record the measurements and the reasoning.
- [x] `tests/unit/test_bifrost_cache_eviction.py` — unit coverage.
- [x] `tests/integration/test_bifrost_cache_eviction_e2e.py` — termination
      and non-destructiveness regression coverage.
- [x] `tests/unit/cli/test_cli_wireup_invariants.py` — assert the new
      subcommand is registered.
- [x] `pyproject.toml` — declare `anyio` in the `cache` group.
- [x] `docs/plans/PLAN_INDEX.md` — index this plan.

### What shipped with Phase 1

The sweep ran against the live store on 2026-11-01:

| Metric | Before | After |
|---|---|---|
| Redis keys | 1743 | 144 |
| Semantic-store entries | 1504 (16 live) | 93 (93 live) |
| `BifrostLocalCachePlugin` docs | 10 (all expired) | 0 |
| `BifrostSemanticCachePlugin_d1` keys | 48 (all expired) | 0 |
| Expired entries remaining | 1488 | 0 |
| Redis memory | 249.7 MB | 230.3 MB |
| Non-Bifrost keys (`bodai:events`, `oneiric-queue`) | 52 | **52 — none removed** |

The `BifrostSemanticCachePlugin` RediSearch index followed:
`num_docs` 1533 → 93.

A second run found 0 expired entries and deleted nothing — the sweep is
idempotent.

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pytest tests/unit/test_bifrost_cache_eviction.py` | pass | pytest output |
| `pytest tests/unit/cli/test_cli_wireup_invariants.py` | pass | pytest output |
| `pytest tests/integration/test_bifrost_semantic_cache_e2e.py` | 5/5 pass | pytest output |
| `mahavishnu bifrost cache-sweep --dry-run` | reports expired count, deletes 0 | stdout |
| `mahavishnu bifrost cache-sweep` | deletes the expired entries | stdout + Redis |
| `FT.INFO BifrostSemanticCachePlugin` | `num_docs` reduced | Redis |
| `redis-cli --scan --pattern 'bodai:*'` | unchanged | Redis |
| `crackerjack run -v -f` | gate passes | crackerjack output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The sweep deletes an entry that was just rewritten | Low | Lua script re-reads `expires_at` and deletes only if still expired; atomic per key |
| The sweep deletes a non-Bifrost key | Very low | Only the three Bifrost prefixes are matched; `bodai:events` and `oneiric-queue` use different prefixes and were verified untouched |
| The threshold raise to 0.95 loses legitimate paraphrase hits | Low | All 8 measured realistic paraphrases score ≥ 0.9545; the e2e paraphrase test scores 0.982 |
| The threshold raise to 16 admits collision-prone requests | Low | 1.4% of the admitted population is embeddable; the residual surface is the measured 0.951–0.984 band |
| The similarity bands cannot be separated, so residual stale serves remain | **Certain** | Accepted and recorded. The structural fix is upstream. Until then, `conversation_history_threshold` is kept at a value that bounds the admitted population |
| The worker path still shows no benefit | Medium | Accepted; there is no worker traffic to measure. §4.4 records the baseline so the effect can be measured when workers run |

## 9. Decision Rule

The plan is done when:

1. The sweep removes expired entries and provably leaves live entries and
   non-Bifrost keys untouched.
2. The sweep is scheduled and has run at least twice unattended.
3. The live config carries `threshold: 0.95` and
   `conversation_history_threshold: 16`, and the e2e suite passes 5/5
   against the restarted gateway.
4. The measurements in §4.5 and §4.6 are recorded in
   `config/bifrost/README.md`.

If the e2e paraphrase test fails at `threshold: 0.95`, fall back to `0.94`
and record the failing similarity. If it fails there too, revert the
similarity threshold to `0.86` and keep `conversation_history_threshold`
at `8` — the untuned state — while the upstream turn-identity defect is
raised.
