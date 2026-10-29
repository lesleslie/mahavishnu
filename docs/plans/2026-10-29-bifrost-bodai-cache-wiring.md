---
status: active
role: canonical
kind: plan
date: 2026-10-29
last_reviewed: 2026-10-29
superseded_by: null
topic: bifrost-cache-wiring
title: "Bifrost — Bodai Routing, Virtual-Key Auth, and cache_mode Wiring"
requirements:
  - id: REQ-BIFROST-035
    title: "Bifrost-routed Bodai calls authenticate with the gateway virtual key"
    description: >-
      A request that reaches the gateway carries the gateway virtual key in
      x-bf-vk. The gateway rejects a provider key with "401 - virtual key is
      required", so without the header every Bodai call fails and silently
      falls through to the local provider.
  - id: REQ-BIFROST-036
    title: "The llama-server provider key resolves so the local provider is servable"
    description: >-
      The Bifrost config declares the local provider key as
      env.LLAMA_SERVER_API_KEY. When that variable cannot be resolved the key
      is dropped and every request for the local model fails with
      no_key_supports_model, pushing the background and classify governance
      rules onto the cloud provider.
  - id: REQ-BIFROST-037
    title: "cache_mode translates into x-bf-cache-* request headers"
    description: >-
      The off, direct and semantic cache modes reach the request as
      x-bf-cache-no-store, x-bf-cache-type direct, and x-bf-cache-type
      semantic respectively. The setting is no longer advisory-only.
---

# Bifrost — Bodai Routing, Virtual-Key Auth, and `cache_mode` Wiring

## 1. Outcome

Bodai component LLM calls reach Bifrost successfully (no `401`), the local
`llama-server` provider is usable again, and the operator-visible
`cache_mode` setting actually controls caching behaviour instead of being
advisory-only.

Success signals:

- `CloudWorker.execute()` completes through the gateway (today: `401 - virtual
  key is required`, then a silent fall-through to `llama_server`).
- `llama-server/qwen3-8b-q4_k_m` is servable through Bifrost (today:
  `no_key_supports_model`).
- A repeated Bodai call returns `X-Bifrost-Cache-Hit: true`.

**Scope correction (added after the ensemble review of Phase 3, 2026-10-29).**
`CloudWorker` has no construction site in production code — it is re-exported
from `mahavishnu/workers/__init__.py` and instantiated only in tests. The
worker factory accepts `shepherd` only, and the pool default is `shepherd`.
The live Bodai → Bifrost path is the **Agno adapter**
(`mahavishnu/engines/agno_adapter_impl.py`), which builds its provider
against the gateway URL but, before this change, attached no headers at all.

So the outcome above is now achieved for the Agno path — which is the path
that actually carries Bodai traffic — and the `CloudWorker` path is fixed
but dormant until it is wired (see §4.10 and Phase 5). The success signals
should be read accordingly: `CloudWorker.execute()` completing is a property
of the code, not yet of a live route.

## 2. Goals

1. Restore the `llama-server` provider by making its key resolvable.
1. Authenticate Bifrost-routed Bodai calls with the gateway virtual key.
1. Give `cache_mode` (`off` | `direct` | `semantic`) a real effect by
   translating it into the `x-bf-cache-*` request headers Bifrost honours.
1. Cover all of the above with tests that fail without the fix.

## 3. Non-Goals

1. Re-pointing Claude Code at Bifrost. Claude Code stays on
   `https://api.minimax.io/anthropic`; Bodai components use the gateway.
1. Replacing `default_cache_key` with per-client opt-in caching. Caching
   stays on by default.
1. Implementing a "no read, no write" cache opt-out — Bifrost v1.5/v1.6 has
   no header for it. `off` means "do not populate the cache".
1. Changing Bifrost's own source or version.

## 4. Current Findings

### 4.1 The Bodai → Bifrost path 401s on every call (verified 2026-10-29)

`mahavishnu/workers/cloud_worker.py:113` builds the MiniMax provider with
`"api_key": "${MINIMAX_API_KEY}"` and a `base_url` that
`_resolve_minimax_base_url()` (same file, line 82) resolves through the
Oneiric Bifrost router to `http://127.0.0.1:8471/v1`.

The gateway rejects a provider key:

```
Provider minimax failed: Error code: 401 - virtual key is required. Provide a virtual key via the x-bf-vk header.
Provider minimax exhausted 3 attempts
Cloud task failed (all providers exhausted)
```

A direct probe confirms the credential boundary — `Authorization: Bearer
<MINIMAX_API_KEY>` → **401**; `Authorization: Bearer <BIFROST_VIRTUAL_KEY>`
→ **200**; `Authorization: Bearer <MINIMAX_API_KEY>` **plus**
`x-bf-vk: <BIFROST_VIRTUAL_KEY>` → **200**.

### 4.2 The `llama-server` provider has no usable key (verified 2026-10-29)

`config/bifrost/config.template.json` declares the provider key with
`"value": "env.LLAMA_SERVER_API_KEY"`. That variable is absent from the
shell, from `~/.config/secrets.env`, and from the gateway's process
environment, so Bifrost drops the key and every request fails with
`no_key_supports_model`. The `background` / `classify` governance rules that
target `llama-server` therefore silently fall back to MiniMax.

The gateway would not have injected the variable even if it existed:
`NEEDED_KEYS` in `mahavishnu/bifrost/gateway.py:43` is
`("MINIMAX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")`, and
`SECRETS_ENV_KEYS` is derived from it.

### 4.3 `cache_mode` has no consumer (verified 2026-10-29)

`BifrostLLMSettings.cache_mode` is declared in
`oneiric/adapters/llm/bifrost.py` and defaults to `"off"`. The
`mahavishnu/llm_gateway` package that read it was deleted in commit
`03146be0`; `rg "cache_mode" mahavishnu/ oneiric/` finds only the
declaration. The setting is advisory-only.

### 4.4 The `x-bf-cache-*` headers the running gateway honours

Empirically determined against Bifrost v1.6.2 (npm `@maximhq/bifrost`
1.6.2), by seeding a cache key and then re-requesting with and without each
header:

| Header | Effect | Evidence |
|---|---|---|
| `x-bf-cache-key` | Selects the cache bucket. Without it and without `default_cache_key`, caching is entirely off. | Cache engaged only when sent. |
| `x-bf-cache-type: direct` | Narrows the lookup to the exact-match path. | Paraphrase request returned `miss` under `direct`, `HIT:semantic` otherwise. |
| `x-bf-cache-type: semantic` | Narrows the lookup to the similarity path. | Exact repeat returned `HIT:semantic`, never `HIT:direct`. |
| `x-bf-cache-no-store: true` | Suppresses the cache **write**. | Seed with the header was not served to the next identical request; without it, it was. |

The mapping is in Bifrost core at
`transports/bifrost-http/lib/ctx.go`, and the plugin-side semantics are in
`plugins/semanticcache/main.go` (`resolveCacheTypes`, `shouldSkipCacheWrite`).

### 4.5 `mcp_common.llm` cannot send custom headers

`mcp_common/llm/provider.py` constructs `openai.AsyncOpenAI` with only
`api_key` / `base_url` / `max_retries` / `timeout`, and `execute()` calls
`chat.completions.create()` without `extra_headers`. `ProviderConfig` is
`extra="forbid"`, so there is no header escape hatch at all today.

### 4.6 The cache write is asynchronous — a test race, not a cache bug

The plugin flushes a cache entry **after** the response is delivered
("the flush of this chunk to the store is async" —
`plugins/semanticcache/main.go`). A request issued immediately after the
seed may therefore still miss.

This became visible once the `llama-server` provider became servable: the
e2e tests' upstream-model fixture prefers the local model, which answers
in ~100 ms against MiniMax's ~1 s, so the repeat request now arrives well
before the write lands. Two cache e2e tests failed intermittently for
exactly this reason.

Fixed by polling for the expected hit instead of assuming the write has
landed. The negative test additionally waits until the seed *is* readable,
so its "no hit" assertion cannot pass vacuously.

Measured similarity for the test prompts (via `text-embedding-3-small`):
seed vs. unrelated **0.147** (threshold 0.86 — safe), seed vs. paraphrase
**0.978** (matches).

### 4.7 `restart` re-points the harnesses too, despite its docstring

`mahavishnu/bifrost/lifecycle.py:251` — `restart()` ends in
`_after_ready("bifrost")` → `repoint_harnesses("bifrost")`, the same as
`rebootstrap`. Its docstring says "preserving the client's current routing
choice", which the code does not do. Anyone following the docstring
believes Claude Code stays on the direct MiniMax endpoint; it does not.

### 4.8 The launchd plist generator would have wiped the whole fix (verified 2026-10-29)

`launchd` gives a service **only** the `EnvironmentVariables` declared in
its plist — it never sources `~/.zshenv`, `~/.zshrc` or `~/.profile`. So
the `ONEIRIC_BIFROST_*` variables had to be written into
`~/Library/LaunchAgents/com.mcp.mahavishnu.plist` by hand.

`mcp-ctl generate` rewrites every `com.mcp.*.plist` from
`~/.claude/scripts/mcp-launchd/mcp-ctl.sh`, whose template emitted four
variables (`PATH`, `LANG`, `LOG_LEVEL`, `MCP_PORT`) and nothing else. A
regeneration would therefore have removed the six `ONEIRIC_BIFROST_*`
variables, the two `OTEL_EXPORTER_*` variables and
`MAHAVISHNU_TOOL_PROFILE` — the service would have silently reverted to
direct MiniMax with metrics off.

The damage was wider than the Bifrost variables. The generator's generic
`-m <module> mcp start` launch form is not what production runs: every
Bodai service was migrated to the `launch_with_healthcheck.sh` wrapper
with a per-repo `WorkingDirectory` (see the launcher-migration decision
note). Regeneration would also have replaced that launch spec, dropped
`WorkingDirectory` (the server would have started in `$HOME`, breaking
`settings/` resolution), and reset the per-service `StartInterval` — the
live values were hand-tuned (`akosha` runs at 60 s, not the
priority-derived 10 s). Three servers in the registry (`dhruva`,
`mermaid`, `n8n`) have neither a checkout nor a running plist, so
generation would have registered three new launchd jobs against programs
that do not exist, each crash-looping every 30 s.

**The fix — two layers.** `generate_plist()` now:

1. **Preserves** an existing plist's `ProgramArguments`,
   `WorkingDirectory`, `StartInterval` and `EnvironmentVariables`. This
   is what keeps the third-party services' credentials
   (`GRAFANA_SERVICE_ACCOUNT_TOKEN`, `LANGSMITH_API_KEY`,
   `MAILGUN_API_KEY`, `RAINDROP_TOKEN`) from being dropped by a
   regeneration. The four built-ins seed a plist that does not exist yet;
   they are not re-added to one that does, so regeneration cannot
   introduce a variable the running service never had.
2. **Declares** the durable configuration in the generator itself
   (`_server_env_lines()`), so `ONEIRIC_BIFROST_*` and the OTel
   variables are re-emitted even if the plist is deleted. The values are
   non-secret; credentials stay in `~/.config/secrets.env`, which
   `mcp_common.server.launcher.load_secrets` reads at process start.

`cmd_generate` additionally skips servers that have neither a checkout
nor an existing plist.

**Verification.** Regenerating all 16 managed plists into a scratch
directory and comparing the full parsed plist against the live one gives
**16 identical, 0 different** — regeneration is now a no-op. A plist
generated from scratch carries all ten durable variables and the
healthcheck-wrapper launch spec. The live plists were left untouched:
the running service never needed to be reloaded for this fix.

### 4.9 The cache e2e tests were hostage to the local model's speed (verified 2026-10-29)

`test_bifrost_semantic_cache_e2e.py` preferred the local `llama-server` as
its upstream because it is free and hermetic, and probed it with the
same 120 s timeout the tests used for everything else.

On a loaded machine the local model degrades badly. Measured on
2026-10-29 with a load average of 21–32 (13 users, several concurrent
Claude Code sessions), `llama-server` was serving **6365 ms per token**
(0.16 tok/s) for an 8B Q4 model that should do 30–60 tok/s:

```
prompt eval time = 22540.86 ms / 15 tokens (1502.72 ms per token)
       eval time = 95480.87 ms / 16 tokens (6365.39 ms per token)
```

A direct request to the llama-server — bypassing Bifrost entirely —
took **162 s**. Through the gateway the same request took 60 s, and one
request ran for 14 minutes before the client gave up (`499` after
865 480 ms). The three cache tests that depend on the `upstream_model`
fixture then failed with `ReadTimeout`.

This is not a cache defect: the gateway, the plugin and the embedding
provider were all healthy throughout. But the test design made the
suite's runtime hostage to a resource the test does not control.

**The fix.** The upstream probe is now time-boxed (`PROBE_TIMEOUT`,
45 s) and independent of the request timeout (300 s). A candidate that
cannot answer the probe is skipped in favour of the next one, so a
starved local model falls through to MiniMax (~1 s) instead of stalling.
The cache-write poll budget (180 s) now covers the upstream's latency as
well as the plugin's asynchronous flush, since one poll iteration is a
full round trip.

The general rule this encodes: **an integration test that only cares
about a header must not hard-depend on a shared, saturable local
resource.** Prefer the fastest *responsive* candidate, and time-box the
selection.

### 4.10 `CloudWorker` is not reachable from production dispatch (verified 2026-10-29)

`CloudWorker` is the provider construction this plan's Phase 3 originally
targeted, and it has no construction site in production code:

- `mahavishnu/workers/manager.py:500-507` — `WorkerManager._create_worker`
  dispatches `RuntimeKind.SHELL` to `ShellWorker` and everything else to
  `_create_isolated_worker`, which accepts only `"shepherd"`
  (`WORKER_SUPPORTED_TYPES = frozenset({"shepherd"})`).
- `mahavishnu/pools/manager.py:340` — the pool default is
  `"worker_type": "shepherd"`.
- `mahavishnu/workers/registry.py` — no cloud worker type is registered.
- `grep -rn "CloudWorker" --include="*.py" mahavishnu/` finds only the
  re-export at `mahavishnu/workers/__init__.py:32`. Every instantiation in
  the repository is in `tests/`.

The comment in `mahavishnu/workers/cloud_worker.py` claiming the class is
"exercised by every `CloudWorker()` literal in production pool-routing
code" is false: the plan it cites
(`docs/plans/2026-05-16-llm-routing-plan2-downstream-migration.md`) is
archived and was a design sketch, never an implemented wiring.

This is the "built but not wired" failure that
`docs/decisions/wire-up-contract.md` exists to prevent, caught by the
ensemble review of Phase 3 rather than by the code.

**The fix, in two parts.** The headers are now attached at *every* gateway
provider construction site, so whichever path is live carries them:

| Consumer | Path | State |
|---|---|---|
| Agno adapter (OpenAI + Anthropic) | `mahavishnu/engines/agno_adapter_impl.py` | **Live.** Headers attached. |
| `CloudWorker` | `mahavishnu/workers/cloud_worker.py` | Correct, but unreachable. Wiring tracked in Phase 5. |
| Pi pool | `mahavishnu/pools/pi_pool.py` | Bearer-only via `~/.pi/agent/models.json`. Needs a Pi-side header facility — Phase 5. |
| Bifrost health probe | `mahavishnu/workers/capabilities/_probes.py` | Already sent `x-bf-vk`; reads the credential from the environment only, so under launchd it reports a missing key that `resolve_virtual_key()` would find in the credential store. |

### 4.11 The accepted auth form is recorded in two contradictory places

§4.1 records a live probe: `Authorization: Bearer <MINIMAX_API_KEY>` →
**401**; `Authorization: Bearer <BIFROST_VIRTUAL_KEY>` → **200**;
`Authorization: Bearer <MINIMAX_API_KEY>` **plus** `x-bf-vk:
<BIFROST_VIRTUAL_KEY>` → **200**.

Two sibling modules in this repository record the opposite, from an earlier
probe:

- `mahavishnu/bifrost/toggles.py:11-13` — "Bifrost reads the virtual key
  *exclusively* from the `x-bf-vk` header, both harnesses reached the
  gateway and were rejected with `401 virtual key is required`".
- `mahavishnu/workers/capabilities/_probes.py:133-137` — "reads virtual
  keys *exclusively* from its own `x-bf-vk` header. **A header-differential
  probe confirmed no `Authorization: Bearer` form is honoured.**"

The two readings disagree about whether a bearer-only request is accepted.
The 2026-10-29 probe in §4.1 is the newer and the more purpose-built, so
it is the one this work relies on — but the older comments are still in the
tree and will mislead the next reader.

This change does not depend on the answer: the virtual key is sent in
`x-bf-vk` on every gateway path, and the provider key in `Authorization`,
which is exactly the combination both readings accept. What the ambiguity
does affect is the **Agno adapter's** pre-existing behaviour, which sends
the virtual key as a bearer with no `x-bf-vk` — under the "exclusively"
reading that path was 401ing. It now carries `x-bf-vk` as well, so it is
correct under either reading.

**Open item:** the two older comments should be reconciled against a
settled measurement rather than left to contradict §4.1. That needs a live
probe run deliberately, not inferred.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-BIFROST-035
    title: "Bifrost-routed Bodai calls authenticate with the gateway virtual key"
  - id: REQ-BIFROST-036
    title: "The llama-server provider key resolves so the local provider is servable"
  - id: REQ-BIFROST-037
    title: "cache_mode translates into x-bf-cache-* request headers"
```

## 5. Implementation Phases

### Phase 1: Make the local provider servable

**Goal:** `llama-server/qwen3-8b-q4_k_m` is servable through Bifrost.

**Tasks:**

1. Declare `LLAMA_SERVER_API_KEY` in `~/.config/secrets.env` (operator
   credential store — the value is a placeholder, not a secret: the local
   llama-server does not verify it).
2. Add `LLAMA_SERVER_API_KEY` to `NEEDED_KEYS` in
   `mahavishnu/bifrost/gateway.py` so the gateway injects it into the
   Bifrost subprocess environment. Without this, step 1 is inert.
1. Restart the gateway and confirm the provider resolves.

**Exit criteria:** a chat completion against `llama-server/qwen3-8b-q4_k_m`
returns 200.

#### Integration Contract

- **Triggered from**: `mahavishnu bifrost rebootstrap` →
  `mahavishnu/bifrost/gateway.py:foreground()` → `load_secrets_env()` →
  `os.environ.setdefault` → `launch_bifrost()`.
- **Returns to / updates**: the Bifrost subprocess environment
  (`~/.config/bifrost/config.json` provider key `env.LLAMA_SERVER_API_KEY`
  resolves) and `~/.config/secrets.env`.
- **Demonstrable by**: `curl -X POST .../v1/chat/completions` with
  `"model":"llama-server/qwen3-8b-q4_k_m"` returns HTTP 200.
- **Rollback signal**: the provider returns `no_key_supports_model` again
  after a gateway restart.
- **Observability added**: the Bifrost gateway log line
  `plugin status: semantic_cache - active` plus the provider's key status
  in `/health`.

### Phase 2: Teach `mcp_common.llm` to send headers

**Goal:** an OpenAI-compatible provider can carry the virtual key and the
cache headers.

**Tasks:**

1. `mcp_common/llm/config.py`: add `default_headers: dict[str, str] = {}` to
   `ProviderConfig` (additive; `extra="forbid"` still holds).
1. `mcp_common/llm/provider.py`: merge `config.default_headers` into the
   `openai.AsyncOpenAI(...)` construction, and forward
   `task.get("extra_headers")` as the SDK's per-call `extra_headers`.
1. Tests in `mcp-common/tests/test_llm.py`.

**Exit criteria:** a provider configured with `default_headers` sends them;
a task carrying `extra_headers` sends them per call.

#### Integration Contract

- **Triggered from**: `mcp_common.llm.OpenAICompatibleProvider.execute()`.
- **Returns to / updates**: the outbound HTTP request headers to the
  OpenAI-compatible endpoint (here: the Bifrost gateway).
- **Demonstrable by**: `pytest mcp-common/tests/test_llm.py -k header`
  passes; the recorded request carries the header.
- **Rollback signal**: the Bifrost gateway logs `401 - virtual key is
  required` for a Bodai-originated request.
- **Observability added**: none at the library level — the effect is
  observable at the gateway as `X-Bifrost-Cache-Hit`.

### Phase 3: Wire the virtual key and `cache_mode` into the Bodai path

**Goal:** `CloudWorker` calls reach Bifrost authenticated, and `cache_mode`
selects the cache path.

**Tasks:**

1. New `mahavishnu/bifrost/cache_headers.py`: resolve `cache_mode` from the
   Oneiric router settings and build the header set.
1. `mahavishnu/workers/cloud_worker.py`: when the MiniMax provider's
   `base_url` resolves to the gateway, attach `x-bf-vk` plus the cache
   headers; when it resolves directly to MiniMax, attach nothing.
1. Set `cache_mode: semantic` in the **environment** —
   `ONEIRIC_BIFROST_CACHE_MODE=semantic` in `~/.zshenv` and in the
   LaunchAgent plist. `BifrostLLMSettings` extends
   `pydantic_settings.BaseSettings` with `env_prefix="ONEIRIC_BIFROST_"`
   and has **no yaml source**, so `~/.config/oneiric/local.yaml` has no
   effect on this setting. (The `~/.zshenv` half is done; see §6.)

**Exit criteria:** a repeated Bodai call returns
`X-Bifrost-Cache-Hit: true`, and `CloudWorker.execute()` succeeds.

#### Integration Contract

- **Triggered from**: `CloudWorker.execute()` →
  `_build_fallback_chain()` → `FallbackChain.execute()` →
  `OpenAICompatibleProvider.execute()`.
- **Returns to / updates**: the outbound request headers, and the Bifrost
  vector store (`BifrostSemanticCachePlugin` namespace in Redis Stack).
- **Demonstrable by**: `pytest tests/integration/test_bifrost_bodai_path_e2e.py`
  passes.
- **Rollback signal**: the gateway logs `401 - virtual key is required`, or
  `no_key_supports_model` for the embedded model.
- **Observability added**: response headers `X-Bifrost-Cache-Hit`,
  `X-Bifrost-Cache-Hit-Type`, `X-Bifrost-Cache-Similarity`.

### Phase 4: Tests and documentation

**Goal:** the regressions are caught by the suite.

**Tasks:**

1. Unit tests for the header builder.
1. An integration test that drives a Bodai-originated call through the
   gateway and asserts the cache hit.
1. Update `config/bifrost/README.md` with the `cache_mode` mapping and the
   virtual-key requirement.

**Exit criteria:** the suite fails when the virtual key or the
`cache_mode` mapping is removed.

#### Integration Contract

- **Triggered from**: `pytest tests/unit tests/integration`.
- **Returns to / updates**: the test suite; `config/bifrost/README.md`.
- **Demonstrable by**: `pytest -m "not slow" -q` is green, and reverting
  the fix makes the new tests fail.
- **Rollback signal**: n/a — tests only.
- **Observability added**: n/a — tests only.

### Phase 5: Close the wiring gap (opened 2026-10-29)

**Goal:** every gateway consumer carries the header set, and the dormant
`CloudWorker` path is either wired or explicitly retired.

**Why this phase exists.** The ensemble review of Phase 3 found that the
headers were attached to a path with no production construction site
(§4.10). Moving the header wiring to every live consumer happened in
Phase 3; what remains are the two reachability questions.

**Tasks:**

1. `mahavishnu/pools/pi_pool.py` — the Pi subprocess resolves the virtual
   key as a bearer from `~/.pi/agent/models.json`
   (`apiKey: "$BODAI_BIFROST_VK"`). Pi's provider schema needs a header
   facility for `x-bf-vk` and the `x-bf-cache-*` set. Until Pi supports
   that, the Pi path cannot carry a cache mode, and the plan should say so
   rather than imply it can.
1. `mahavishnu/workers/capabilities/_probes.py` — the Bifrost health probe
   reads the virtual key from the environment only, so under launchd it
   reports "missing BIFROST_VIRTUAL_KEY" for a credential that
   `resolve_virtual_key()` finds in the credential store. Route it through
   `resolve_virtual_key()` so the two readers agree.
1. `CloudWorker` — decide whether it is a live worker type or a library
   surface. If it is to be live, register it in `workers/registry.py` and
   the pool's `worker_type` allowlist. If not, say so in its module
   docstring so the next reader does not plan against it.

**Exit criteria:** every construction site that targets the gateway URL
either carries the header set or is documented as not doing so, and the
`CloudWorker` docstring matches its reachability.

#### Integration Contract

- **Triggered from**: the worker registry and the pool spawn path.
- **Returns to / updates**: the worker registry and the pool defaults.
- **Demonstrable by**: a pool spawn that resolves a gateway-routed
  provider, and the registry's unit tests.
- **Rollback signal**: a gateway-routed provider built without `x-bf-vk`.
- **Observability added**: none new; the existing `401 - virtual key is
  required` at the gateway is the signal.

## 6. Required Code Changes

- [ ] `~/.config/secrets.env` — declare `LLAMA_SERVER_API_KEY` (operator
      action; requires explicit authorization)
- [ ] `~/.zshenv` — `ONEIRIC_BIFROST_CACHE_MODE=semantic` (operator action;
      requires explicit authorization)
- [x] `~/Library/LaunchAgents/com.mcp.mahavishnu.plist` — mirrors the
      `ONEIRIC_BIFROST_*` variables so the long-running service routes
      through the gateway (verified 2026-10-29: the plist sets
      `ONEIRIC_BIFROST_CACHE_MODE=semantic`)
- [x] `mahavishnu/bifrost/gateway.py` — add `LLAMA_SERVER_API_KEY` to
      `NEEDED_KEYS`
- [x] `mcp-common/mcp_common/llm/config.py` — `ProviderConfig.default_headers`
- [x] `mcp-common/mcp_common/llm/provider.py` — send `default_headers` and
      per-call `extra_headers`
- [x] `mcp-common/tests/test_llm.py` — header tests
- [x] `mahavishnu/bifrost/cache_headers.py` — new module
- [x] `mahavishnu/workers/cloud_worker.py` — attach gateway headers
- [x] `mahavishnu/engines/agno_adapter_impl.py` — attach gateway headers
      to the OpenAI and Anthropic provider constructions (the live path)
- [x] `mahavishnu/bifrost/gateway.py` — withhold the virtual key from a
      target that is neither https nor loopback
- [x] `mahavishnu/tests/unit/test_bifrost_cache_headers.py` — new
- [x] `mahavishnu/tests/unit/test_bifrost_gateway_secrets.py` — derive the
      required provider keys from the shipped template rather than
      iterating `NEEDED_KEYS`
- [x] `mahavishnu/tests/unit/test_bifrost_cache_headers.py` — new
- [x] `mahavishnu/tests/unit/workers/test_cloud_worker.py` — gateway-header
      tests added to the existing class
- [x] `mahavishnu/tests/unit/test_bifrost_gateway_secrets.py` — fixture
      updated for the new `NEEDED_KEYS` entry
- [x] `mahavishnu/tests/integration/test_bifrost_bodai_path_e2e.py` — new
- [x] `config/bifrost/README.md` — document `cache_mode` and the virtual key
- [x] `~/.claude/scripts/mcp-launchd/mcp-ctl.sh` — `generate_plist()` preserves
      an existing plist's launch spec and environment, declares the durable
      variables itself, and `cmd_generate` skips servers that have neither a
      checkout nor an existing plist (see §4.8)

### Cross-repo publish boundary

`mcp_common` is a **published** dependency of mahavishnu
(`mcp-common>=0.33.1`), so the `default_headers` field only exists in
mahavishnu's venv once mcp-common is republished. The mcp-common change is
implemented and green (117 tests); **publishing it is the operator's step**
— the publish stage is never run by Claude.

**Update (2026-10-29):** mcp-common **0.34.0 is published** (PyPI upload
2026-10-29T12:03) and carries the `default_headers` field, and the
mahavishnu venv now resolves the registry wheel rather than an editable
install. The publish boundary above is closed.

One item remains open and is **operator-owned**: the declared floor in
`pyproject.toml` is still `mcp-common>=0.33.1`, but `ProviderConfig` is
`extra="forbid"`, so on 0.33.1 the `default_headers` key raises
`pydantic.ValidationError` inside `get_enabled_providers()` and the
provider fails to start. The floor should be `>=0.34.0`. Version floors
are not changed by Claude — the operator owns them.

## 7. Validation Matrix

| Tool / command | Expected | Evidence |
|---|---|---|
| `pytest tests/unit/test_bifrost_semantic_cache_config.py` | pass | 8 passed |
| `pytest tests/integration/test_bifrost_semantic_cache_e2e.py` | pass | 5 passed |
| `pytest tests/integration/test_bifrost_bodai_path_e2e.py` | pass | new |
| `CloudWorker.execute()` probe | `status=succeeded` | was `failed` / 401 |
| `curl` with `"model":"llama-server/qwen3-8b-q4_k_m"` | HTTP 200 | was 400 |
| `python scripts/audit_requirements.py` | clean | new REQ IDs referenced |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `x-bf-vk` alongside the provider `Authorization` is not honoured by a future Bifrost release | Low | The gateway maps `x-bf-vk` in `ctx.go` unconditionally; the provider-key path is unchanged if the header is dropped. |
| `default_headers` on the OpenAI client silently replaces the SDK's own `Authorization` | Medium | Merge the SDK's headers with ours rather than replacing them; cover with a test. |
| `cache_mode: semantic` makes every Bodai call pay an embedding round-trip | Medium | The embedding is one small request; `threshold` and `conversation_history_threshold` bound the false-positive surface. |
| The `llama-server` placeholder key becomes a real credential requirement | Low | It is the same variable name llama.cpp itself uses (`LLAMA_SERVER_API_KEY`), so promoting it to a real secret needs no config change. |

## 9. Decision Rule

Ship when the Bodai path authenticates through the gateway, the local
provider is servable, `cache_mode` demonstrably changes the cache path, and
the new tests fail when each fix is reverted. Do **not** ship the
`default_cache_key` removal — caching stays on by default.
