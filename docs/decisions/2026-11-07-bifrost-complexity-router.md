---
status: active
role: canonical
kind: decision
date: 2026-11-07
last_reviewed: 2026-11-07
topic: bifrost-complexity-router
---

# 2026-11-07-bifrost-complexity-router.md

## Context

Bifrost's routing plugin can classify each request as `SIMPLE`, `MEDIUM`, or
`COMPLEX` and publish the tier to the CEL engine as `complexity_tier`. Two
classifiers are available: a **decision model** (Typesafe Jev by default) and
**semantic** (an embedding match against reference phrases). A
`session.enabled` flag retains the highest tier a session has reached for 24
hours of inactivity, keyed on `x-bf-session-id` or the harness-native
`x-claude-code-session-id` / `x-codex-turn-metadata.session_id`.

This repo had no complexity routing. `governance.routing_rules` was
header-driven, and five of its seven rules were keyed on `x-bf-task` —
`think`, `long_context`, `web_search`, `image`, `background`/`classify` —
which is exactly a complexity taxonomy. **All five were unreachable**: no
production code emits `x-bf-task`, because the package that used to
(`mahavishnu/llm_gateway/`) was deleted in `03146be0`. Only
`route-anthropic-native` could fire.

The header-driven shape has a hard ceiling on the Claude Code path. Claude
Code's `ANTHROPIC_CUSTOM_HEADERS` is written once per session, so a caller
cannot express a per-request complexity signal there at all — and the header
is the only thing a CEL rule can match on. `complexity_tier` is computed
*inside* the gateway, so it is the only mechanism that can classify per
request on that path.

Two constraints shape what a tier may route to:

- The Anthropic ingress bridges every request to Bifrost's `responses` request
  type, and only `minimax-anthropic` allows it. `minimax-openai` and
  `llama-server` allow `chat_completion` only. **The cheap tier reachable from
  Claude Code is `minimax-anthropic/MiniMax-M3.1-Flash`** — there is no
  zero-marginal-cost tier on that path.
- Claude Code picks the model per request class — `MiniMax-M3` for the opus and
  sonnet slots, `MiniMax-M3.1-Flash` for the haiku slot — and the
  security-review plugin asks for `claude-opus-5-5` directly, falling back to
  `claude-sonnet-4-6` when the primary yields no verdict. That fallback
  exists because M3's adaptive thinking consumes the entire 16k output budget
  on a review-sized diff and returns thinking-only with `stop_reason:
  max_tokens`. A pinned model that overrides the caller's choice destroys it.

And the credential: `env.X` provider keys resolve from the gateway's own
process environment, and the gateway provisions those from
`~/.config/secrets.env` through an explicit allowlist
(`mahavishnu/bifrost/gateway.py::NEEDED_KEYS`). A key outside the allowlist is
never resolved, Bifrost drops it at startup, and every request for that
provider fails with `no_key_supports_model`.

## Decision rule

1. **The complexity router is configured in the repo template**, at
   `governance.complexity_analyzer_config`, with the **decision** classifier
   on `typesafe` / `jev-latest` — the hosted model the repo's decision-adapter
   work already standardized on. The `keywords` reference lists are carried
   (48 curated phrases across the three tiers) because the saved config
   requires all three lists even though the decision classifier does not read
   them; a later switch to the semantic classifier needs no config change.

1. **`session.enabled: true`.** The reason is coherence, not cost. Without
   session state, a turn's first request — the one carrying the human text —
   is classified and routed by tier, while the turn's continuation requests
   carry only tool results, get no tier, and fall through to the caller's
   model. One turn would then run on two models: the model that decides the
   next action and the model that reads the tool result. The provider's prompt
   cache also misses at that seam. With session state the tier holds for the
   session. Session state stores only the tier, under a hashed session id — no
   prompts, no scores, no history.

1. **The tier policy is downward-only. `SIMPLE` is the only tier with a model
   target.** `MEDIUM` and `COMPLEX` keep the caller's model through
   `route-anthropic-native`. This is what keeps the policy safe:
   - Nothing is ever moved *onto* the heavier model, so the haiku slot is
     never escalated.
   - The security-review plugin's Sonnet fallback is never overridden back
     onto M3, so the "no verdict from the model" failure stays fixed.
   - The session ratchet is harmless **for the tier**: an escalated session
     stops being classified. It is *not* harmless for the model — see
     "Session affinity" below. A session bound to the cheaper model on a
     SIMPLE turn stays on it after it escalates.

1. **One rule: `route-complexity-simple`, priority 3.** Routing rules are
   first-match-wins with the lower priority number evaluated first, and
   `route-anthropic-native` (priority 5) matches every Claude Code request
   because the harness always sends `x-bf-route` — so a tier rule at priority
   5 or above is dead code on that path. The rule is guarded by
   `headers["x-bf-route"] == "anthropic_native"`, which also keeps it off
   direct-SDK callers such as the security-review plugin, that reach the
   gateway without the harness headers.

1. **Jev is reached through Bifrost, not through a second transport.** Bifrost
   already proxies `typesafe` / `jev-latest` via `/v1/decisions`, using the
   provider's own credential. Routing the decision model through Bifrost means
   one credential path, one config site, and unified logs and cost counters —
   and it makes the model swappable by configuration: `jev-latest` →
   `~typesafe/jev-latest` (OpenRouter) → `@cf/cloudflare/clef-flash` →
   a locally pulled Ollama System One model (`nimble`, `tev1`, `clef`,
   `clef-flash`, `laya`). That last option is what closes the hosted-only risk
   the decision-adapter plan records as its own Risk 1, with no code at all.
   It also keeps the fleet at one gateway, per the same principle the
   tool-output-compaction plan states as REQ-COMP-06.

1. **`TYPESAFE_API_KEY` joins `NEEDED_KEYS`.** Without it the gateway never
   resolves the variable, Bifrost drops the key at startup, and every
   classification fails with `no_key_supports_model` — which surfaces as *the
   router never produces a tier*, not as a credential error. The failure is
   silent in the same way as the other three traps the config template's
   docstring lists, which is why it earns an allowlist entry and a contract
   test rather than a comment.
   `tests/unit/test_bifrost_gateway_secrets.py::test_every_configured_provider_key_is_resolved_by_the_gateway`
   derives the requirement from the template, so a provider key cannot be
   added to the config without also being resolvable.

1. **The five `x-bf-task` task-keyed rules are left alone.** They remain
   unreachable and harmless. `complexity_tier` supersedes them as the
   mechanism; it does not require deleting them, and their removal is a
   separate change with its own risk.

1. **The decision-adapter plan is rescoped, not cancelled.** See the
   amendment in `docs/plans/2026-10-14-decision-adapter-category.md`: Task 1
   cuts to one Bifrost-backed adapter, Task 2's sequencing gate is already
   satisfied, Task 3's three `task_router` selectors are dropped, and Task 4
   becomes an independent PR.

## Measured behaviour (2026-11-07)

Verified against the gateway's own request log (`~/.config/bifrost/logs.db`)
after the rebootstrap, and with controlled probes against the Anthropic
ingress. The figures below are for one closed hour — **04:52 to 05:52
local** (`timestamp > '2026-11-07 12:52' AND timestamp <= '2026-11-07
13:52'` in the log's UTC timestamps) — and exclude the probe sessions, so
they are reproducible.

**The classifier works.** 762 requests on the Claude Code path
(`responses_stream`) carried a tier, with 100% coverage from two minutes
after the restart onwards. The distribution was `MEDIUM` 504, `SIMPLE` 236,
`COMPLEX` 22, over 14 sessions. The tier reaches the CEL engine:
`route-complexity-simple` matched 236 times, `route-anthropic-native` took
the rest.

**Session mode works, and it is what makes the classifier affordable.** 741
of the 762 tiered requests reused a stored tier (`complexity_mechanism:
session`); only 21 called the decision model — **97% of tiered requests pay
nothing for classification**.

**The decision model is reached through Bifrost's `/v1/decisions`**, as
designed. The routing metadata records `provider_used: typesafe,
model_used: jev-1.14.0` on every classification.

**The classifier is not free, and session mode is what bounds it.** On the
Claude Code path the 25 decision calls cost 88,229 input tokens and 1,177
output tokens in the hour — about 3,500 input tokens per call, and the
input scales with the turn being classified. Session mode holds that at 3%
of tiered requests; with `session.enabled: false` all 762 would pay it.

The other 11 calls in the window came from **requests with no session id**
(direct SDK clients — `python-urllib`, i.e. this repo's own probes and
integration tests). They cost 125,421 input tokens on their own, about
11,400 per call, because there is no session to cache a tier against and
every one of them is classified from scratch. A caller that cannot send a
session id pays the full price per request.

### Session affinity

Bifrost runs a second routing engine, `session-affinity`, *after* the
routing rules. It binds `(session id, requested model)` to the provider and
model the session was first served, and it wins over a rule's proposed
model. Its own log says so:

```text
[routing-rule] Rule 'Simple Tasks → Concise Model' → matched, selected target
    (weight=1.00): provider=minimax-anthropic, model=MiniMax-M3.1-Flash
[session-affinity] Session stays on minimax-anthropic/MiniMax-M3 for
    MiniMax-M3; routing proposed minimax-anthropic/MiniMax-M3.1-Flash
```

Two consequences, both measured:

1. **The downgrade reaches almost nothing on live traffic.** Of 236
   SIMPLE-tier requests, 230 stayed on `MiniMax-M3`. The six served by
   `MiniMax-M3.1-Flash` were the `MiniMax-M3.1-Flash` request class of one
   session, not downgrades. The sessions in the window were bound to
   `MiniMax-M3` before the router was live, and affinity kept them there. A
   *new* session whose first request for that model class classifies as
   SIMPLE **is** downgraded — a controlled probe asked for `MiniMax-M3` and
   was served `MiniMax-M3.1-Flash`, streaming and non-streaming alike.

2. **An escalation does not restore the caller's model.** A session whose
   first request was SIMPLE stays on `MiniMax-M3.1-Flash` after it
   escalates. With a COMPLEX tier the routing rules correctly propose
   `MiniMax-M3` — the caller's model — and affinity discards it:

   ```text
   [routing-rule] Session complexity escalated: effective=COMPLEX previous=SIMPLE
   [routing-rule] Rule 'Anthropic-Native Claude Code Route' → matched, selected target
       (weight=1.00): provider=minimax-anthropic, model=MiniMax-M3
   [session-affinity] Session stays on minimax-anthropic/MiniMax-M3.1-Flash for
       MiniMax-M3; routing proposed minimax-anthropic/MiniMax-M3
   ```

   So a complex turn can be served by the cheaper model. That is the
   inverse of the property rule 3 claimed, and it is a quality risk rather
   than a cost one.

3. **The "SIMPLE discount" is a session-wide downgrade, not a per-turn
   one.** The binding is `(session id, requested model)` and it persists for
   the session, so a single SIMPLE turn does not discount that turn — it
   **rebinds the whole session's model class** to the cheap model, and every
   later request in that class is served by it, whatever the tier says.
   Measured on the live gateway: one session's first SIMPLE turn was followed
   by **266 MEDIUM requests that asked for `MiniMax-M3` and were served
   `MiniMax-M3.1-Flash`**, each with the routing rules correctly proposing
   the caller's model and affinity discarding it.

   This is larger than rule 3 assumed, and it inverts what the policy
   actually does. The per-tier rule — SIMPLE downgrades, MEDIUM and COMPLEX
   keep the caller's model — is not what decides the model. The session's
   first binding is. The rule only decides whether the session *starts* on
   the cheap model.

`session-affinity` is a built-in routing engine in the pinned v2.5.0
transport. It is not a provider setting, not a plugin, and not a
`governance_config` key — the store exposes no switch for it.

### The accounting

Because the per-request outcome cannot be read from the tier alone, it is
measured per request by
`mahavishnu bifrost complexity-report` (see
`docs/plans/2026-11-07-bifrost-complexity-accounting.md`). The command
reads the gateway's own request log and separates the three outcomes — the
rule's intent carried out, the tier's instruction overruled, and the
classification paid for and not acted on — using the affinity line the
routing engine writes for each request.

## Status

Active. The configuration landed in `config/bifrost/config.template.json` on
2026-11-07 and was applied with `mahavishnu bifrost rebootstrap` (store
backed up to `~/.config/bifrost/.bak/20261107-044811-presync`; the store is
authoritative and the template is only its seed). The gateway came back
healthy (`/health` → `{"components":{"db_pings":"ok"},"status":"ok"}`) and the
transport exposes the analyzer route (`GET /api/routing/complexity-analyzer-config`
answers 401, not 404 — the route exists in the pinned v2.4.0 binary and is
admin-auth-gated). 30/30 config-contract tests pass, and the merge gate
(`crackerjack run -v -f`) passes 18/18 fast hooks.

**Verified against the live store on 2026-11-07** — read from
`~/.config/bifrost/config.db`, not from the template:

- **The analyzer config landed.** It reconciles into the store's
  `complexity_semantic_config` entity: `classifier=decision`,
  `decision={provider: typesafe, model: jev-latest, previous_message_count: 1,
  timeout: 1.5s}`, `session.enabled=true`. Bifrost hashed each of those six
  template fields into that entity's `_config_hashes`, which is the proof
  that the reconcile read this template and not a stale one.
- **The store's other complexity entity is a different thing.**
  `complexity_analyzer_config` holds the retired lexical scorer's state
  (`tier_boundaries` + `keywords.code_keywords`) and was left alone. An
  operator reading the store should not read it as the router's config.
- **The rule landed ahead of the catch-all.** `route-complexity-simple` is at
  priority 3 with the exact CEL; `route-anthropic-native` is at 5.
- **The credential resolves.** `TYPESAFE_API_KEY` is present in the live
  gateway process environment, and the store's env-backed `typesafe-primary`
  key carries `status=success` — a real validation result, not a default,
  because the other providers' keys (`llama-server`, `minimax-anthropic`,
  `minimax-openai`) sit at `status=unknown`. The `no_key_supports_model`
  failure the record warns about last occurred on 2026-10-29, and for the
  embedding model, not for the decision path.

**Still open — the measurements, not the design:**

- **The session-id arrival is now measured, and it works.** Claude Code does
  send a session id: 452 of the 487 tiered requests reused a stored tier
  (`complexity_mechanism: session`). The intra-turn split this record set out
  to prevent does not happen.
- **The decision (2026-11-07): keep the router, price it as observability,
  and watch the risk.** The alternative — removing the model target from the
  rule — was rejected: it removes the risk but leaves the operator with
  neither the tier data nor any saving, and the classifier is cheap enough
  (session mode holds it at 5% of classified requests) to be worth paying
  for. The watch is `mahavishnu bifrost complexity-report`, which prices the
  classifier and attributes every classified request to the outcome it
  actually had.
- **The realised saving is measured, and it is not the shape the policy
  assumed.** In the measured hour the classifier cost 89,406 tokens on the
  Claude Code path (plus 125,421 more from session-less direct clients).
  The rule's per-turn intent almost never fired: 230 of 236 SIMPLE-tier
  requests stayed on `MiniMax-M3`. What actually moved the model was the
  session binding, and it moved it the *other* way — 279 MEDIUM and
  COMPLEX requests were served the cheap model against their tier's
  instruction. So the volume the router moved is large, but it is the
  volume the policy did not intend to move, and it is bought with a
  classifier that costs about as many tokens as the output it moved.

**Two operational notes that are not defects:**

- Bifrost **merges** the `keywords` lists on reconcile rather than replacing
  them, so the live store holds the union of this template's 18/16/14 phrases
  and the 50 reference phrases per tier the store already carried (68/66/64).
  The decision classifier does not read them; a later switch to the semantic
  classifier would read the union.
- The `typesafe` provider carries two enabled keys of equal weight — `Jev`
  (a literal value in the store) and `typesafe-primary` (env-backed). Both
  validate, so classification splits across them rather than failing. The
  literal one is a plaintext credential in `config.db`; retiring it is a
  separate change.

## Related

- `docs/plans/2026-10-14-decision-adapter-category.md` — rescoped by this
  record
- `docs/decisions/2026-10-14-decision-adapter-category.md` — the decision
  category this record narrows
- `docs/plans/2026-11-01-bifrost-cache-eviction-and-threshold.md` — the
  sibling plan that established measure-before-you-tune for this gateway
- `config/bifrost/README.md` — "Complexity Router" and "Bootstrap Routing
  Contract"
