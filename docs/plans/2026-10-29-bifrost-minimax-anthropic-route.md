---
status: complete
role: implementation
kind: plan
date: 2026-10-29
last_reviewed: 2026-10-30
superseded_by: null
topic: bifrost-minimax-routing
title: "Route Claude Code through Bifrost to MiniMax with genuine Anthropic responses"
---

# Route Claude Code through Bifrost to MiniMax with genuine Anthropic responses

## 1. Outcome

When Claude Code is routed through the Bifrost gateway, its requests reach
MiniMax over MiniMax's **Anthropic-native** endpoint and the gateway returns
genuine Anthropic-shaped responses — reasoning delivered as Anthropic
`thinking` blocks, never inline in the assistant text.

**Success signal**: a `POST http://127.0.0.1:8471/anthropic/v1/messages`
from a Claude Code session returns a `content` array containing a `thinking`
block, and the assistant text contains no `<think>` tags.

## 2. Goals

1. Make Bifrost's model→provider resolution **deterministic for Claude Code
   traffic**, so it cannot land on the OpenAI-compatible MiniMax path by
   accident.
2. Ensure reasoning is delivered as Anthropic `thinking` blocks.
3. Leave the Mahavishnu **worker's** OpenAI-compatible path (`minimax-openai`)
   untouched — workers do not consume `thinking` blocks.
4. Make every step reversible from one place.

## 3. Non-Goals

- Migrating the fleet off MiniMax's Anthropic-native endpoint.
- Adopting Bifrost's native `minimax` provider as the Claude Code path
  (evaluated — see §4.2; deferred pending a thinking-signature test).
- Changing the semantic-cache plugin configuration.
- Touching the `llama-server` or `openai` providers.

## 4. Current Findings

### 4.1 The symptom and its cause — the provider never existed

**Corrected 2026-10-30 after live verification.** The first draft of this
section blamed provider ambiguity. That was wrong, and the live gateway
proved it: the Anthropic-native MiniMax provider **was never in the config
store at all**. Every Claude Code request through Bifrost was served by
`minimax-openai` — MiniMax's OpenAI-compatible endpoint — which returns
reasoning **inline** inside `content`. That is the symptom.

The template's provider entry had **three** independent defects, each of
which silently discards it:

1. **Name collision.** The provider was named `anthropic`, which is
   Bifrost's *standard* provider name. The config-store import drops a
   custom provider whose name collides with a standard one. Verified: the
   store held `llama-server`, `minimax-openai` and `openai` — no
   `anthropic` — and a request for `model=anthropic/MiniMax-M3` returned
   `failed to get config for provider anthropic: not found`.
2. **Invalid `allowed_requests` key.** The entry said
   `{"messages": true}`. Bifrost's `schemas.AllowedRequests` has **no**
   `messages` field, and unspecified fields default to `false` — so the
   provider allowed *nothing*.
3. **Invalid `request_path_overrides` key.** `request_path_overrides` is
   `map[RequestType]string`, and there is no `messages` request type. The
   Anthropic HTTP route bridges to Bifrost's generic `responses` type, so the
   override must be keyed `responses`.

The key was already named `minimax-anthropic-primary`, mirroring
`minimax-openai` / `minimax-openai-primary` — the provider name was simply
wrong. Fixed by renaming the provider to `minimax-anthropic` and correcting
both key sets.

**After the fix**, a Claude Code-shaped request through the gateway returns
`content: [thinking, text]`, with a **signed** thinking block and no inline
`<think>` tags — the same shape the fleet gets when talking to
`https://api.minimax.io/anthropic` directly. The worker's
`/v1/chat/completions` path still resolves to `minimax-openai`
(`allowed_requests.chat_completion`), so it is unaffected.

v2.4.0's native `minimax` provider remains a valid *alternative* for a
non-Claude-Code fleet — see §4.2 — but it is not what was missing here.

### 4.2 v2.4.0's native `minimax` provider — evaluated, not adopted

v2.4.0 ships a native `minimax` provider (chat, Responses, image, async
video, TTS, STT). It **would** fix the inline-thinking symptom: the native
provider sends `reasoning_split: true` on every chat request, so MiniMax
returns reasoning in `reasoning_content` and Bifrost renders it as Anthropic
`thinking` blocks.

It is nonetheless the wrong choice for the stated goal:

- The upstream becomes MiniMax's **OpenAI-compatible** endpoint, not the
  Anthropic-native one — the wire format changes.
- Bridged thinking blocks carry **no `signature`**. Anthropic's API expects
  one when thinking blocks are replayed, and Claude Code replays them.
  v2.4.0's "Bridged Thinking Signatures" fix removed the *synthetic*
  signature; it does not add a real one.

It remains the right answer for a *non-Claude-Code* fleet that wants native
MiniMax features (video, TTS, STT) — a separate plan.

### 4.3 `config.db` is authoritative — the template is not the live config

`config_store.enabled: true` (`config.template.json` L6-11). With the config
store enabled, the SQLite store holds providers, keys, governance rules,
virtual keys and the dashboard admin account. **Editing
`config.template.json` does not change the running gateway.**

`bifrost rebootstrap` re-seeds `config.json` and *keeps* `config.db`; its
`--drop-db` path destroys the virtual key and the admin account (see
`tests/unit/test_bifrost_lifecycle.py::test_sync_config_keeps_the_config_store`).

**The management API is not usable for this on this deployment.**
`POST /api/governance/routing-rules` requires `ManagementBearerAuth` or
`BasicAuth`, and dashboard auth is active
(`GET /api/session/is-auth-enabled` → `{"auth_type":"password",
"is_auth_enabled":true,"setup_required":false}`). The OSS setup-token
header stops working once dashboard auth is enabled, so the token in
`~/.config/secrets.env` is rejected with 401. That path needs the admin
password, which lives in the config store.

**The store syncs routing rules from `config.json` instead.** Every rule in
`config.db` has a non-empty `config_hash` — the hash of the `config.json`
entry it was last synced from — and the targets live in a sibling
`routing_targets` table. So writing the rule into `~/.config/bifrost/config.json`
and restarting the gateway is what actually lands it in the store. This also
explains why the provider defect in §4.1 was invisible: the `anthropic`
provider was in `config.json` the whole time and simply never made it into
the store.

### 4.4 The repo-side lever already exists

`mahavishnu/bifrost/toggles.py` writes Claude Code's
`ANTHROPIC_CUSTOM_HEADERS` as newline-separated `Name: Value` lines
(`_upsert_header_line`). That is the same header channel Bifrost's CEL
routing rules match on — the existing rules already read `headers["x-bf-task"]`
and `headers["x-bf-route"]`.

The `x-bf-task` header is emitted by the **worker contract layer**
(`mahavishnu/workers/contract/`), which is how the worker path reaches the
`background` / `classify` rules today. Claude Code does not go through the
contract layer, so it carries no `x-bf-task` — and therefore matches no
governance rule at all, falling through to bare model-name resolution. That
is the gap.

> **Correction (2026-10-30, from the ensemble review).** The paragraph
> above is wrong about `x-bf-task`. **No production code in this repo
> emits `x-bf-task` at all** — the only occurrences are a test file and the
> gateway's own config. `mahavishnu/llm_gateway/`, the package that used
> to emit it, has been deleted, leaving only a `__pycache__`.
>
> The consequence is wider than this plan: the `think`, `long_context`,
> `web_search`, `image`, `background` and `classify` rules are all
> **unreachable in production**, because nothing sends the header they
> match on. `x-bf-route` is the only header any repo code emits, which
> makes it the right lever here — and it means the new rule is the only
> one that can actually fire. The gap this plan closes is therefore larger
> than "Claude Code is ambiguous": five of the six rules are dead, and the
> sixth (the new one) is the first to be reachable.

### 4.5 Routing-rule API (verified against the v2.4.0 OpenAPI)

- `POST /api/governance/routing-rules` — create
- `GET  /api/governance/routing-rules` — list
- `PUT|DELETE /api/governance/routing-rules/{rule_id}`
- `priority`: *"lower number = higher priority"*, unique within a scope.
- `scope` evaluation order: `virtual_key`, `user`, `team`, `customer`,
  `global`.
- `targets[].weights` must sum to 1; `fallbacks` is the ordered chain tried
  after the selected target fails.

**Not usable on this deployment** — see §4.3. The endpoints and the schema
are as documented, but every management endpoint requires admin credentials
that an automated run does not have.

### 4.6 Ensemble review — upstream-verified corrections (2026-10-30)

A second review lens checked the change against the v2.4.0 upstream source
rather than against the repo's own assumptions. It confirmed the mechanism
(the standard-provider name collision, the invalid `messages` request type,
the governance-rule override, the header reaching CEL) and found three
defects in the first version of the rule. All three are corrected in
`config/bifrost/config.template.json`.

**a. The rule pinned the model, which overrode Claude Code's own choice.**
Upstream's routing target schema is explicit: *"Target model (omit or empty
to use the incoming request model)"*. A target that names a model **overwrites**
the caller's model outright (`plugins/routing/rules/engine.go:288-294`, applied
by `req.SetModel(...)`). Claude Code selects the model per request class —
`MiniMax-M3` for the opus and sonnet slots, `MiniMax-M3.1-Flash` for the
haiku slot — so a pinned `MiniMax-M3` silently moved the fast slot onto the
heavy model, with no error and no log line.

> **Corrected 2026-10-30.** This originally read that the pin "downgraded the
> 1M-context variant". It did not: Claude Code strips the `[1m]` suffix
> before the request leaves the client (see below), so the gateway never
> saw a 1M-spelled model to downgrade. The pin's real effect was on the
> *fast* slot.

> **The plan's earlier claim was wrong.** It said a provider-only target
> "leaves the model identifier unresolved and the provider is then re-derived
> from the bare model name". Upstream keeps the incoming model when the
> target omits it. The target now pins the **provider only**, and the
> provider's key lists every model id Claude Code actually sends.

**b. `count_tokens` was missing.** `POST /v1/messages/count_tokens` is a
first-class request type with its own Anthropic route, and the provider gates
it with `CheckOperationAllowed`. The route header travels on *every* request,
so the token-count call matches the rule too — and with `count_tokens` unset
it is refused with an operation-not-allowed error. It needs the permission
*and* a path override, because MiniMax's Anthropic surface lives under
`/anthropic/` and the default Anthropic path would 404.

**c. The fallback could not serve the request.** The Anthropic ingress
bridges every request to the `responses` request type, and `minimax-openai`
allows only `chat_completion` / `chat_completion_stream`. Bifrost v2.4.0 has
no `responses` → `chat_completion` conversion — the conversion flags are
`convert_chat_to_responses`, `convert_text_to_chat`,
`convert_decision_to_responses` and `force_reasoning_only_models_to_responses`,
all the other way round. A fallback on `minimax-openai` was therefore inert:
it could not serve the request, so the request failed hard rather than
degrading. The fallback now names the same provider on a different model
(`minimax-anthropic/MiniMax-M3.1-Flash`), which speaks the same Anthropic
protocol and can actually serve the request.

**The `[1m]` suffix is Claude Code-side, and never reaches the gateway.**
Claude Code documents that it *"strips the suffix before sending the model
ID to your provider"*; the shipped binary carries the same logic
(`strip1mTag`, `toProviderWireModelId`), and a control probe with a
deliberately bogus id returned MiniMax's error naming the id *without* the
suffix. `MiniMax-M3[1m]` is not a MiniMax model id -- MiniMax has no
1M-suffixed variant, and `MiniMax-M3` already has a 1M-token window with a
guaranteed 512K floor -- so sending the literal string is a 400. The suffix
still matters inside Claude Code: it is how Claude Code learns the model has
a 1M window and suppresses proactive compaction for that alias. **This
retires the planned `[1m]` -> `MiniMax-M3` routing rule** -- the gateway
never sees a model the rule would have to catch.

**Also recorded, not changed:**

- **Priority 5 is unique in the live store.** The store enforces uniqueness
  per scope and answers 409 on a duplicate; the live global-scope rules use
  5, 10, 20, 30, 40, 50, 60, so `route-anthropic-native` holds the
  highest-priority slot with no collision.
- **The route is a bridge, not a wire.** Upstream's Anthropic raw passthrough
  fires only for the standard provider name `anthropic`
  (`isClaudeModel` switches on the *provider*); a custom provider name falls
  through to the typed conversion path. The request is re-serialised into
  Bifrost's internal Responses shape and re-encoded on the way back, so
  Anthropic fields with no Responses representation are dropped rather than
  forwarded. The **shape** is what Claude Code needs — a signed `thinking`
  block — but it is not byte-for-byte forwarding, and the trade-off is forced
  by trap 1 (the provider cannot be named `anthropic`).
- **"Silently dropped" was softened.** Upstream's providers API refuses a
  standard provider name loudly (HTTP 400, *"Custom provider cannot be same
  as a standard provider"*). The config-file import's behaviour was not read
  from source, so the docs now say what is verifiable: the API refuses the
  name, and the import did not register the provider on this deployment.

### 4.7 Python-correctness lens — the toggle's own claims

A second review lens read the Python the branch touches and compared it
against what its own docstrings claim. No blocker; four behavioural gaps
and four nits, all in `mahavishnu/bifrost/`. All are fixed.

**The route header was not actually independent of the virtual key.**
`_set_route_header`'s docstring — and Phase 1 below — say the route header
is "a routing *signal*, not a credential", installed independently of the
key. The implementation wrote it as a *side effect* of writing the
credential, so a host whose settings carried a stale key and whose operator
had no `BIFROST_VIRTUAL_KEY` exported never received it: the gateway rule
never fired, and the provider choice stayed ambiguous — the exact problem
the route exists to solve. The route header is now installed on every path
that leaves the harness pointed at Bifrost, credential or no credential.

**`--force` recorded the Bifrost URL as the endpoint to restore.** The
backup holds the pre-toggle upstream that `direct` restores. On a host
already pointed at Bifrost the current URL *is* the Bifrost URL, so
recording it made `direct` put the harness **back on the gateway** while
the operator believed they had left. The backup now keeps whatever the
first toggle recorded.

**The cached launcher was chosen by npm's cache hash, not by version.**
`find_cached_bifrost_bin()` sorted the candidates by path. npm's `_npx`
cache directories are named by an opaque hash, so that ordering has nothing
to do with the version — and on this host it selected the *older* launcher
(1.6.2 rather than 1.6.3). That is not cosmetic: the newer launcher
validates the arguments it forwards to the transport binary against a
known-flag list, while the older one forwards them verbatim, and the binary
refuses to boot on a flag it does not know. The candidates are now ordered
by the version in the cached `package.json`.

**The readiness budget was below the gateway's own bind timeout.**
`lifecycle.READY_BUDGET_SECONDS` was 60s while `gateway.READY_TIMEOUT_SECONDS`
is 180s, and the supervisor writes the ready file only *after* the child
binds. Bifrost ≥ 2.3.0 syncs its MCP catalog at startup and a cold cache
takes 60–180s, so a budget at the low end of that window made the gate give
up on a gateway that was about to come up. The failure was safe — the
client is left alone rather than aimed at a dead port — but it reported a
healthy gateway as missing. The budget now outlives the bind timeout.

Also fixed: `direct` now removes a route header stranded on a hand-set
(non-Bifrost) endpoint, and removes it from the model sink as well as the
env sink; the route-only install path says plainly that a missing virtual
key will 401; and `CLAUDE.md`'s link to the M2.7 migration plan pointed at
a path that only exists under `docs/plans/.archive/`.

One test-coverage gap was closed rather than a defect fixed: the ready file
was asserted to be retracted for `start` only, so deleting the call from
`restart` or `rebootstrap` would have left the suite green. The assertion
is now table-driven over all three.

## 4.8 Requirements

```yaml
requirements:
  - id: REQ-BIFROST-038
    title: "Claude Code requests resolve to the Anthropic-native MiniMax provider"
  - id: REQ-BIFROST-039
    title: "Reasoning returns as Anthropic thinking blocks, never inline"
  - id: REQ-BIFROST-040
    title: "Worker OpenAI-compatible path is unaffected by the Claude Code route"
  - id: REQ-BIFROST-041
    title: "Routing rule is applied to the authoritative config store"
```

## 5. Implementation Phases

### Phase 1: Route Claude Code explicitly (repo-side, reversible)

**Goal:** give Claude Code traffic a routing signal the gateway can match.

**Tasks:**
1. Add `CC_ROUTE_HEADER = "x-bf-route"` and a value constant
   (`anthropic_native`) to `mahavishnu/bifrost/models.py`.
2. Extend `toggles.py` so the **Claude Code** harness writes
   `x-bf-route: anthropic_native` alongside `x-bf-vk` in
   `ANTHROPIC_CUSTOM_HEADERS`. The Qwen harness is untouched — it wants the
   OpenAI-compatible route.
3. Extend the template with the matching governance rule
   (`config/bifrost/config.template.json`):
   `cel_expression: headers["x-bf-route"] == "anthropic_native"`, target
   provider `minimax-anthropic` / model `MiniMax-M3`, fallback
   `minimax-openai/MiniMax-M3`, global scope, priority `5` (lower number =
   higher priority; the existing rules use 10–60).
   **The target must name the *custom* provider** — `minimax-anthropic`,
   not `anthropic` (§4.1).
4. Pin with tests: the header is written for `cc` and not for `qwen`; the
   template's rule matches the constant.

**Exit criteria:** `mahavishnu bifrost cc-url bifrost` writes both header
lines; the template parses and the rule is present.

**Note (from the ensemble review).** The route header is a routing signal,
not a credential, so it is installed **independently of the virtual key**.
The no-op check used to short-circuit on "the URL matches and the key
matches", which meant a host that was already pointed at Bifrost — every
host that ran the toggle before this change — never received the route
header. Installing it independently also means the pre-toggle upstream URL
in the backup is left intact, so `cc-url direct` still restores it.

#### Integration Contract

- **Triggered from**: `mahavishnu bifrost cc-url bifrost`
  (`mahavishnu/cli/bifrost_cli.py:cc_url` → `toggles.apply`).
- **Returns to / updates**: `~/.claude/settings.json` —
  `env.ANTHROPIC_CUSTOM_HEADERS` gains an `x-bf-route:` line.
- **Demonstrable by**: `tests/unit/test_bifrost_toggles.py` asserting the
  header line exists for `cc`; `python -c "import json,plistlib; ..."`
  asserting the rule is in the template.
- **Rollback signal**: `mahavishnu bifrost cc-url direct` restores the
  prior URL and drops the routing header.
- **Observability added**: none new — the `x-bf-route` value is recorded in
  Bifrost's request log (`~/.config/bifrost/logs.db`) as the routing rule
  that matched the request.

### Phase 2: Apply the rule to the live config store

**Goal:** make the gateway actually honour the route.

**Tasks:**
1. Write the rule into `~/.config/bifrost/config.json` — the store syncs
   rules from there (§4.3). The management API needs admin credentials that
   are not available to an automated run.
2. Restart the gateway so the store re-syncs. **This is the only step that
   changes gateway behaviour** — the template edit in Phase 1 does not.
3. Confirm it landed: `routing_rules` and `routing_targets` in `config.db`
   show the rule, with a non-empty `config_hash`.

**Exit criteria:** the rule is present in the store with a non-empty
`config_hash`, and its target row names `minimax-anthropic`.

#### Integration Contract

- **Triggered from**: the rule is written into
  `~/.config/bifrost/config.json` and the gateway is restarted
  (`launchctl kickstart -k gui/$(id -u)/ai.bifrost.gateway`).
- **Returns to / updates**: `~/.config/bifrost/config.db` — the
  `routing_rules` and `routing_targets` tables.
- **Demonstrable by**: reading `config.db` shows the rule with a
  non-empty `config_hash` and a target row of
  `provider='minimax-anthropic', model='MiniMax-M3'`.
- **Rollback signal**: remove the rule from
  `~/.config/bifrost/config.json` and restart the gateway.
- **Observability added**: Bifrost's request log attributes Claude Code
  requests to provider `minimax-anthropic` and to the
  `route-anthropic-native` rule.

### Phase 3: Verify the thinking blocks

**Goal:** prove the symptom is gone end-to-end.

**Tasks:**
1. Send a Claude Code-shaped request through the gateway: a `claude-cli`
   User-Agent (Bifrost's `IsClaudeCodeRequest` matches `claude-cli` /
   `claude-code` / `claude-vscode` as substrings), the `x-bf-vk` virtual key,
   and the `x-bf-route` header.
2. Inspect the response `content` array: a `thinking` block must be present
   and the assistant text must contain no `<think>` tags.
3. Exercise a **tool-calling turn** and a **multi-turn replay** — the
   signature question (§4.2) only bites on replay, so a single-turn probe is
   not sufficient evidence.
4. Confirm the worker's `/v1/chat/completions` route still resolves to the
   OpenAI-compatible provider.
5. Restore: `mahavishnu bifrost cc-url direct`.

**Exit criteria:** thinking arrives as a block; the assistant text is clean.

**Verified 2026-10-30** against the live gateway:

| Probe | Result |
|---|---|
| Anthropic route, `x-bf-route` header | HTTP 200, `content: [thinking, text]`, thinking block **signed**, no inline `<think>` |
| Anthropic route, no route header | same shape — the provider now exists, so default resolution lands on it too |
| Provider-qualified `model=anthropic/MiniMax-M3` | HTTP 400 `failed to get config for provider anthropic: not found` (before the rename) |
| Tool-calling turn + replay (thinking block replayed with its signature, then `tool_result`) | turn 1 HTTP 200 `tool_use`; turn 2 HTTP 200 with clean text, no inline `<think>` |
| Worker route `/v1/chat/completions` | HTTP 200; request log attributes it to the OpenAI-compatible provider |
| Request log attribution (routed probe) | `provider=minimax-anthropic`, `key=minimax-anthropic-primary`, `rule=route-anthropic-native` |

#### Integration Contract

- **Triggered from**: a Claude Code session with
  `ANTHROPIC_BASE_URL=http://127.0.0.1:8471/anthropic`.
- **Returns to / updates**: nothing persistent — this phase is a measurement.
- **Demonstrable by**: the captured `content` array, plus
  `curl -s http://127.0.0.1:8471/api/version` still reporting `v2.4.0`.
- **Rollback signal**: inline `<think>` text reappearing in the assistant
  turn, or a 4xx on the replayed turn.
- **Observability added**: the request-log provider attribution for
  Claude Code traffic.

## 6. Required Code Changes

- [x] `config/bifrost/config.template.json` — rename the provider to
      `minimax-anthropic`; correct `allowed_requests` and
      `request_path_overrides` to real request types; add the
      `anthropic_native` rule
- [x] `config/bifrost/config.template.json` (review pass) — allow
      `count_tokens` with its MiniMax path override; list
      `MiniMax-M3[1m]` in the provider's key; pin the **provider only** in the
      rule's target so Claude Code's model choice survives; point the
      fallback at a provider that can serve the `responses` request type
- [x] `mahavishnu/bifrost/models.py` — `ROUTE_HEADER`, route value, the
      `HarnessDescriptor.route_header` field
- [x] `mahavishnu/bifrost/toggles.py` — write and remove the route header for
      the `cc` harness
- [x] `tests/unit/test_bifrost_config_template.py` — guard the three silent
      provider traps
- [x] `tests/unit/test_bifrost_toggles.py` — pin the header behaviour, the
      rule's provider-only target, the route header's independence from the
      credential, and the backup's restore point
- [x] `mahavishnu/bifrost/gateway.py` — choose the cached launcher by package
      version, not by npm's cache-hash directory name
- [x] `mahavishnu/bifrost/lifecycle.py` — the readiness budget must outlive
      the gateway's own bind timeout
- [x] `config/bifrost/README.md` — document the route and the three traps

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence |
|---|---|---|
| `mahavishnu bifrost cc-url status` | route header present for `cc` | `~/.claude/settings.json` |
| `config.db` → `routing_rules` / `routing_targets` | one rule matching `anthropic_native`, target `minimax-anthropic` | store query |
| `POST /anthropic/v1/messages` via Bifrost | `content[]` has a `thinking` block | captured response |
| `pytest tests/unit/test_bifrost_toggles.py` | green | pytest output |
| `pytest tests/unit/test_bifrost_config_template.py` | green | pytest output |
| `mahavishnu bifrost verify-gate` | green | CLI exit code |
| `config.db` → `routing_rules.priority` (global scope) | no duplicate priority | store query — **verified 2026-10-30** |

## 8. Risks

**Resolved during execution (2026-10-30).** The first two rows were the
open questions; both were measured, not assumed.

| Risk | Outcome |
|---|---|
| Governance rules do not evaluate on the Anthropic route | **Not a risk.** The rule fired — the request log shows `routing_rule_id=route-anthropic-native` with `provider=minimax-anthropic` and `key=minimax-anthropic-primary` |
| The provider's typed path (non-passthrough) loses thinking fidelity | **Not a risk.** The response carries a **signed** thinking block, and a replayed turn (thinking block replayed with its signature, then a `tool_result`) returns HTTP 200 with clean text |
| A provider entry that looks right in `config.json` but is not in the store | **This is what happened** (§4.1). The `anthropic` provider was in the template the whole time and never reached the store. Guarded now by `tests/unit/test_bifrost_config_template.py` |
| Editing the template does not change the running gateway | **Certain** — Phase 2 exists precisely because of this. The store syncs from `config.json`, and `bifrost rebootstrap` seeds `config.json` from the template; a template edit alone changes nothing |

**Resolved by the ensemble review (2026-10-30)** — see §4.6:

| Risk | Outcome |
|---|---|
| The rule pins the model, so Claude Code's own model choice is overridden | **Fixed.** Upstream keeps the incoming model when the target omits it, so the target now pins the provider only. The provider's key lists `MiniMax-M3`, `MiniMax-M3[1m]` and `MiniMax-M3.1-Flash` |
| Rule priority collides with an existing rule | **Not a risk.** The live global-scope priorities are 5, 10, 20, 30, 40, 50, 60 — `route-anthropic-native` holds slot 5 with no duplicate |
| The rule's fallback cannot serve the request | **Fixed.** The fallback moved from `minimax-openai` (chat-completions only, cannot serve the `responses` request type the Anthropic ingress produces) to `minimax-anthropic/MiniMax-M3.1-Flash` |
| The provider refuses Claude Code's token-count call | **Fixed.** `count_tokens` is now allowed, with the `/anthropic/v1/messages/count_tokens` path override |

**Closed on 2026-10-30.** The store was re-seeded from the template and now
carries every correction from §4.6: the routing target pins the provider
only (its `model` column is empty), the rule's `fallbacks` reads
`["minimax-anthropic/MiniMax-M3.1-Flash"]`, and the `minimax-anthropic`
provider has `count_tokens: true` with the
`/anthropic/v1/messages/count_tokens` path override.

**Still open (a recurring failure mode, not a current one):**

| Risk | Likelihood | Mitigation |
|---|---|---|
| The config store and the template drift apart again | **High — the mode is recurring, but it is not happening now.** The template is the seed and the store is authoritative; a provider or rule that fails to import is invisible until a request misses it. The guard test checks the template's *shape*; it cannot see the store. Worth a runtime check that every template provider exists in `config.db` |

## 9. Decision Rule

Ship when: a Claude Code session routed through Bifrost returns reasoning as
Anthropic `thinking` blocks across a **tool-calling replay turn**, and the
worker path still resolves to `minimax-openai`. If the Anthropic route turns
out not to evaluate governance rules, fall back to making the model claim
unambiguous rather than adding a second mechanism.

**Met on 2026-10-30** — see the Phase 3 table: a signed `thinking` block, a
tool-calling turn and its replay both served by `minimax-anthropic` with no
fallback, and the worker route still attributed to `minimax-openai`. The
fallback branch was not needed: the rules do evaluate on the Anthropic
route.

**Both are now closed** (2026-10-30). The cutover is done: Claude Code and
Qwen Code are both pointed at the gateway, and both were verified live —
`verify-gate` passes for Qwen Code (`provider=minimax-anthropic`,
`status=success`, `via claude-cli/0.26.1`), and a Claude Code-shaped
request returns a **signed** `thinking` block with `route-anthropic-native`
firing. The cache buckets are in place for both harnesses. The toggles
remain reversible (`cc-url direct`, `qwen-url direct`).

**The cache bucket is now wired** (2026-10-30). `cc-url bifrost` writes
`x-bf-cache-key: claude-code:<hash>` alongside the credential and the route
header, derived from the traffic class and the credential the request will
present — never the shared `default` namespace. `qwen-url bifrost` does the
same for Qwen Code (`qwen-code:<hash>`), and gives Qwen the
`x-bf-route: anthropic_native` header too: its active model resolves to the
`anthropic` provider entry, which the toggle points at the gateway's
Anthropic surface — so Qwen reaches MiniMax's Anthropic-native endpoint and
gets signed thinking blocks rather than inline reasoning. The route header
makes that choice explicit instead of leaving it to bare model-name
resolution, which is how Qwen's historical route ended up on
`minimax-openai` (the OpenAI-compatible surface) rather than the
Anthropic-native one. The collision it prevents
was reproduced live first: two requests with the same user turn and
different system prompts (the shape of two Claude Code sessions in two
directories) both came back `cache_hit: true` on the same `cache_id`, in
1–47 ms instead of ~700 ms.

What the bucket does **not** do is separate two Claude Code sessions from
each other: it is written once into `~/.claude/settings.json`, so every
session on the host shares it. What keeps them apart in practice is the
conversation history the cache key also carries, plus the gateway's
`conversation_history_threshold: 8`, which stops caching entirely past
eight messages — so a long session is not cached at all.

**The store sync is closed too.** The operator ran the authorised sync and
restart on 2026-10-30, and the live store now carries every correction from
§4.6 — the routing target pins the provider only (`model` is empty), the
rule's `fallbacks` reads `["minimax-anthropic/MiniMax-M3.1-Flash"]`, and the
`minimax-anthropic` provider has `count_tokens: true` with the
`/anthropic/v1/messages/count_tokens` path override. Both the provider row
and the rule row carry the same `updated_at` stamp, which is the store's own
record that a real import ran. The template and the store agree, so this
plan's status is **`complete`**.

## 10. Operator Action — Live-Store Sync (Completed 2026-10-30)

This section is the record of what the operator ran. It is kept because the
sync is a **live-config write** that cannot be folded into a merge: the store
is a separate artifact, it is only re-seeded from the template on an
explicit sync, and a template edit alone changes nothing at runtime.

The steps that were run, in order:

1. Re-seed `~/.config/bifrost/config.json` from
   `config/bifrost/config.template.json` (`mahavishnu.bifrost.lifecycle.sync_config()`;
   it backs up the store first and keeps `config.db`).
2. Restart the gateway so the store re-imported the rule and the provider's
   key — the store syncs from `config.json`, not the other way round. Set
   `BIFROST_CTL_NO_CC_URL_REWRITE=1` for the restart so the harnesses are
   left where they are: `restart()` calls `_after_ready("bifrost")`, which
   repoints them at the gateway, and the gate is currently commented out in
   `~/.zshenv`.
3. Re-run the Phase 3 probes, plus a `count_tokens` probe and a probe
   carrying `model: "MiniMax-M3[1m]"`, to confirm the corrections landed.
4. Check the store's `routing_targets` row for `route-anthropic-native`:
   the target's `model` column must be empty (the caller supplies it) and the
   rule's `fallbacks` must read `["minimax-anthropic/MiniMax-M3.1-Flash"]`.
   A target with no model is new to this config, and the config-file import
   path was not read from upstream source — so the store is the only place
   this can be confirmed.

Steps 1–4 are confirmed against the live store: the rule's `fallbacks` and
the empty target `model` were read back from `routing_rules` and
`routing_targets`, and the provider's `allowed_requests.count_tokens` and
`request_path_overrides` from `config_providers`. The Phase 3 probes pass,
and `mahavishnu bifrost status` reports both harnesses on the gateway with
their route headers and their own cache buckets.

**If the sync ever has to be repeated**, note that
`mahavishnu bifrost rebootstrap` performs steps 1 and 2 in one command, but
it also repoints the Claude Code and Qwen harnesses at the gateway. Once the
cutover is wanted that is the right command; until then, use `sync_config()`
plus a gated restart.

## 11. Security Review Corrections (2026-10-30)

A review of the pushed changes raised three findings. All three were checked
against the upstream Bifrost v2.4.0 source (`plugins/semanticcache/main.go`,
`utils.go`, `search.go`) before being acted on, and all three were real.

### 11.1 The cache key dropped the system prompt

**Finding.** `exclude_system_prompt: true` drops the system messages from
the hashed and embedded input. The system prompt is where a harness puts
the things that distinguish one session from another — persona, working
directory, date, project instructions — so two sessions with the same user
turn hashed to the same key. The per-traffic-class bucket added in §9 does
not fix this: the bucket is derived from the traffic class and the
credential, both constant on the host, so it separates Claude Code from the
fleet but not one Claude Code session from another.

**Upstream.** `ExcludeSystemPrompt` is `*bool` with the documented default
`false` — the system prompt participates in the key unless the config
explicitly opts out. The template was opting out.

**Fix.** `exclude_system_prompt` is back to `false` in the template. The
system prompt now discriminates between sessions, which is what closes the
gap the bucket could not.

The same review pointed at the plugin's `default_cache_key: "default"`, the
fleet-wide namespace that a client with no bucket header fell back into.
`resolveCacheKey` returns `False` when neither a per-request key nor a
default is set, and the plugin's pre-LLM hook then exits before any lookup
or write — so removing `default_cache_key` does not disable the cache for
the callers that name a bucket; it removes the shared namespace for the
ones that do not. The key is now unset in the template.

### 11.2 `off` still served reads

**Finding.** `cache_mode: off` sent `x-bf-cache-no-store`, which upstream
documents as "skip writing the response to cache (still served from cache
on hit)". A mode named `off` that still performs cross-session lookups is a
retention control that reads as a privacy control and is not one. The
module docstring disclosed the asymmetry; the name did not.

**Upstream.** There is no read-suppression header in v2.4.0. The cache key
is, however, encoded into the direct cache ID (`generateDirectCacheID`) and
is an equality filter on the semantic search (`cache_key`), so a bucket
nothing was ever written to cannot be hit on either path.

**Fix.** `off` now points at a bucket of its own that is never written,
plus the no-store header. Two `off` requests never share a bucket, and an
`off` request cannot be answered out of a bucket another caller wrote to.
The setting name is unchanged — the vocabulary belongs to Oneiric's
`BifrostLLMSettings`, not to this repo.

### 11.3 Two agent-reachable paths skipped the traversal guard

**Finding.** `mahavishnu/engines/agno_tools/code_tools.py` ran
`_search_code_impl`'s path through `_validate_path` (traversal detection,
symlink resolution, allowed-base-directory check, blocked-path check), but
`_analyze_code_impl` and `_get_function_signature_impl` resolved whatever
path the agent named. Both read the file: one returns its imports, classes
and functions, the other parses it.

**Fix.** Both now call `_validate_path`, and a test pins the parity for
both tools.

### 11.4 What still needs the operator

The template changes in §11.1 are live-config changes like everything else
in §10. `config.json` has been re-seeded from the template, so the file on
disk carries the corrected plugin config. The **store** does not yet: it
still holds `exclude_system_prompt: true` and `default_cache_key:
"default"`, because the store re-imports from `config.json` when the
gateway starts, not when the file changes.

One restart closes that:

```bash
BIFROST_CTL_NO_CC_URL_REWRITE=1 mahavishnu bifrost restart
```

Until it runs, the live gateway still drops the system prompt from the key
and still carries a shared `default_cache_key`.
