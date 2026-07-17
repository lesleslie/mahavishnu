---
status: shipped
role: historical
date: 2026-04-08
last_reviewed: 2026-07-16
superseded_by: null
topic: routing-composition
---

# Bifrost Gateway Plan

**Status:** In progress  <!-- legacy status: In progress — see YAML frontmatter -->
**Date:** 2026-04-08
**Target port:** 8471
**Scope:** Replace LiteLLM and CCR with a single self-hosted Bifrost-based gateway where practical

## Objective

Build a local, self-hosted LLM gateway that:

- exposes an OpenAI-compatible API for all non-Claude clients
- exposes an Anthropic-compatible path for Claude Code if needed
- routes requests across multiple z.ai-backed models/providers
- applies request and token rate limits
- supports exact-match and semantic caching
- can route by request type, headers, model, and cost/capacity signals
- runs as a macOS LaunchAgent and survives reboots

## Decision

Use **Bifrost** as the gateway.

Do **not** use LiteLLM.
Do **not** use CCR as a required component.

CCR-like behavior will be reproduced in Bifrost where it materially matters:

- model routing
- task-tier routing
- long-context routing
- image / multimodal routing
- web-search routing
- fallback chains
- caching
- rate limiting

CCR-specific Claude Code UX, presets, and CLI affordances are out of scope unless they prove necessary later.
If we need CCR-style task buckets, we will recreate only the minimum client-side label shim needed to annotate requests before they reach Bifrost.

## Why Bifrost

Bifrost is the best fit for this environment because it already provides:

- OpenAI-compatible responses
- Anthropic-compatible integration
- governance-based routing via virtual keys
- routing rules with CEL expressions
- automatic fallbacks
- weighted provider selection
- baseline weighted provider selection, with adaptive load balancing treated as an optional enterprise feature
- request/token rate limits
- semantic caching
- provider-level and key-level budgets
- support for multimodal requests

## Operational Constraints

- bind the gateway to `127.0.0.1` only
- do not store API keys in the LaunchAgent plist
- load secrets from `~/.config/opencode/shell-secrets.zsh` through a dedicated launchd-safe env bridge
- keep the gateway process and its logs local-only
- if the gateway is ever exposed beyond localhost, add an auth edge before that happens
- treat this as a single-user trusted-host deployment for the first rollout
- do not assume any local process is trusted if that threat model changes later

## What Replaces CCR

CCR currently gives Claude Code:

- task-based model routing
- `background`, `think`, `longContext`, `webSearch`, `image` routing buckets
- model switching
- subagent model overrides
- request transformers

The Bifrost replacement is:

- route on `request_type`, headers, model, and budget usage
- use a tiny local wrapper or shim only when we need to derive CCR-style task labels from Claude Code context
- encode task tier in headers when the client cannot infer it itself
- use Bifrost Anthropic support directly for Claude Code
- preserve model-specific routing decisions in gateway config, not a separate router

## Feature Comparison

| Capability | CCR + gateway | Bifrost only | Notes |
|---|---|---|---|
| OpenAI-compatible clients | Yes | Yes | Bifrost already covers Codex, Qwen, Nanobot, OpenClaw, and workers |
| Claude Code support | Yes | Yes, via Anthropic integration | CCR is not required if Bifrost Anthropic works cleanly |
| Task-tier routing | Yes | Yes, via routing rules | Use headers or request metadata to encode task tier |
| Long-context routing | Yes | Yes, via model/request rules | Prefer explicit tier headers or model names |
| Web-search routing | Yes | Yes, via routing rules | Route by request type or tool-related metadata |
| Image / multimodal routing | Yes | Yes, via multimodal request type and routing rules | Bifrost supports request_type-based routing |
| Subagent-specific routing | Yes | Mostly yes | Use a `x-bifrost-task` or similar header from the caller |
| Fallback routing | Yes | Yes | Bifrost supports automatic fallbacks and explicit fallbacks |
| Load balancing | Partial | Yes | Bifrost has weighted provider selection; adaptive load balancing is treated as optional/enterprise |
| Token/request limits | Not a core CCR feature | Yes | Bifrost supports request and token limits |
| Caching | Not a core CCR feature | Yes | Bifrost supports exact-match and semantic caching |
| Prompt caching | Limited / provider dependent | Yes, through gateway + provider features | Anthropic prompt caching is still useful |
| Claude Code model picker UI | Yes | No | This is the main thing we lose by removing CCR |
| Preset export/install | Yes | No | Not needed for the gateway goal |
| Claude-specific transformers | Yes | No | Only needed if a provider needs extra translation |

## Routing Design

### Routing Goals

Route requests by intent, not only by model name.

Desired route classes:

- `default`
- `think`
- `background`
- `long_context`
- `web_search`
- `image`
- `high_throughput`
- `cheap`

### Routing Inputs

Use these inputs in Bifrost routing rules:

- `request_type`
- `model`
- request headers
- query params
- budget usage
- token usage
- request-rate usage
- provider health / availability

Trust boundary:

- route-hint headers are only honored from trusted local wrappers or internal callers
- direct third-party callers do not get to choose expensive routes by setting arbitrary headers
- if a caller cannot be trusted, route by model name, request shape, and server-side defaults only

### Recommended Header Contract

Clients that want CCR-like routing should send one or more of:

- `x-bf-route`
- `x-bf-task`
- `x-bf-tier`
- `x-bf-workload`
- `x-bf-context-length`

Example mappings:

- `x-bf-task: think` -> route to stronger reasoning model
- `x-bf-task: background` -> route to cheaper/faster model
- `x-bf-task: long_context` -> route to a long-context model
- `x-bf-task: image` -> route to multimodal provider/model
- `x-bf-task: web_search` -> route to model/provider best suited for browsing/search

### Image and Multimodal Routing

Bifrost should handle this natively enough for our use case:

- it supports multimodal request types
- routing rules can inspect `request_type`
- routing rules can inspect headers and params
- providers can be selected per modality

Practical implication:

- if a request is an image or another non-text modality, route by `request_type` first when that type is server-derived or injected by a trusted wrapper
- if the client cannot emit a reliable type, use a server-side default route or a trusted caller header

This is sufficient to replace the useful parts of CCR's image routing.

## Caching Design

### Caching Layers

Use three caching layers, in this order:

1. provider-native prompt caching where available
1. Bifrost exact-match response cache
1. Bifrost semantic cache

### What Each Layer Does

- provider-native prompt caching

  - best for stable system prompts and repeated long prefixes
  - especially useful for Anthropic-compatible traffic

- exact-match response cache

  - best for repeated identical prompts and deterministic jobs
  - lowest risk and easiest to reason about

- semantic cache

  - best for near-duplicate prompts and repeated coding questions
  - good for token reduction at scale

### Cache Policy

- cache only safe response classes
- do not cache obviously user-specific or ephemeral content by default
- use short TTLs for uncertain workloads
- scope cache keys by caller identity, protocol family, provider, model, route class, and prompt hash
- never let one client's cache entries satisfy another client's request by accident
- only trusted wrappers may request cache bypass or force a cache mode

Recommended cache hints:

- `x-bf-cache-key`
- `x-bf-cache-type: direct|semantic`
- `x-bf-cache-ttl`
- `x-bf-cache-threshold`
- `x-bf-cache-no-store`

Only trusted wrappers may populate these cache headers directly.

## CCR Included vs Not Included

### If CCR Were Kept

Pros:

- Claude Code gets its existing `/model` and preset UX
- image / long-context / think / background routing is already familiar
- subagent routing remains a first-class behavior
- migration risk is lower in the short term

Cons:

- two routing layers instead of one
- more config sprawl
- harder to reason about cache and rate-limit policy
- more moving parts in auth, logging, and launch agents

### If CCR Is Removed

Pros:

- one gateway instead of two
- fewer operational failure modes
- one routing policy source of truth
- one caching policy source of truth
- easier progress tracking and debugging

Cons:

- lose CCR's Claude Code UI affordances
- task tiers must be encoded through Bifrost config or request headers
- any Claude-specific convenience must be recreated elsewhere

### Recommendation

Remove CCR from the required path.

If Claude Code needs special handling later, recreate only the minimal useful behavior in Bifrost or in a tiny client-side wrapper, not in a second router.

## Implementation Phases

### Phase 0: Confirm Primitives

- [x] verify Bifrost can run locally on this Mac without Docker
- [x] verify Bifrost binds to `127.0.0.1:8471` only
- [x] verify OpenAI-compatible `/v1/chat/completions`
- [x] verify Anthropic-compatible request path for Claude Code
- [ ] verify semantic cache works on repeated prompts
- [ ] verify request/token rate limits can be enforced
- [ ] verify multimodal / image routing can be triggered by request type or a caller header

### Phase 1: Client Contract

- [ ] decide which clients may set route hints directly
- [ ] define the minimum task-label shim for Claude Code, if any
- [ ] define the exact mapping from CCR-style buckets to Bifrost route labels
- [ ] decide which route hints are server-derived versus caller-supplied
- [ ] define which headers are trusted and which are ignored on direct calls

### Phase 2: Gateway Skeleton

- [ ] create Bifrost config for z.ai providers
- [ ] define virtual keys and access policy
- [ ] define routing rules for default, think, background, long-context, web-search, and image tasks
- [ ] define fallback chains for primary and secondary providers
- [ ] define cache policy and TTLs
- [ ] define rate-limit policy

### Phase 3: Client Mapping

- [x] map Codex to OpenAI-compatible endpoint
- [x] map Qwen to OpenAI-compatible endpoint
- [x] map Nanobot to OpenAI-compatible endpoint
- [x] map workers to OpenAI-compatible endpoint
- [x] map Claude Code to Anthropic-compatible endpoint
- [ ] decide whether Claude Code still needs a thin wrapper for task labels only

### Phase 4: LaunchAgent and Boot Persistence

- [ ] create or update LaunchAgent for Bifrost
- [ ] define `ProgramArguments`, `WorkingDirectory`, `EnvironmentVariables`, `KeepAlive`, and `ThrottleInterval`
- [ ] ensure secret loading is separate from the plist and from any committed file
- [ ] keep only non-secret environment entries in the plist
- [ ] set stdout/stderr log paths
- [ ] add restart behavior and throttle limits
- [ ] add a log rotation and redaction policy
- [ ] verify restart after reboot or launchd reload
- [ ] run a cold-start smoke test after `launchctl bootstrap`

### Phase 5: Validation

- [ ] `curl` OpenAI chat completion
- [ ] `curl` Anthropic chat completion if enabled
- [ ] verify streaming works for both supported client styles
- [ ] verify tool-use / function-call behavior survives translation
- [ ] verify beta/passthrough headers needed by Claude traffic are preserved or intentionally dropped
- [ ] verify fallback behavior on a simulated upstream failure
- [ ] verify cache hit on identical prompt
- [ ] verify semantic cache hit on near-duplicate prompt
- [ ] verify rate-limit rejection behaves as expected
- [ ] verify logs contain request id, route choice, provider choice, and cache outcome
- [ ] verify at least one multimodal/image request routes to the intended provider
- [ ] verify a post-reboot or relaunch launchd smoke test before client cutover

### Phase 6: Client Cutover

- [ ] point OpenAI-compatible clients at Bifrost
- [ ] point Claude Code at Bifrost or keep CCR only temporarily if needed
- [ ] remove LiteLLM references
- [ ] remove CCR only after Claude Code behavior is covered

## Rollback Plan

If Bifrost fails during cutover:

- unload or disable the LaunchAgent
- restore the previous client base URLs
- revert any cache or routing header changes in local client wrappers
- fall back to direct z.ai endpoints for the affected clients
- keep the last known-good Bifrost config snapshot in a separate backup file

Rollback success criteria:

- clients can talk to their previous endpoint again
- the gateway is no longer on the critical path
- the machine returns to a working state without manual recovery on each app

## Progress Tracker

Update this table as work lands.

| Milestone | Status | Owner | Evidence | Last updated | Notes |
|---|---|---|---|---|---|
| Bifrost choice locked | Done | Codex | Conversation history | 2026-04-08 | CCR removed from the required path |
| Feature comparison drafted | Done | Codex | This document | 2026-04-08 | This document |
| Client contract defined | Done | Codex | `mahavishnu/llm_gateway/contract.py` + `mahavishnu/llm_gateway/client.py` + tests | 2026-04-08 | Task labels, trust boundaries, route/cache headers, endpoint resolution, and provider/model qualification |
| Bifrost config written | Done | Codex | `config/bifrost/config.template.json` | 2026-04-08 | Bootstrap config verified locally against z.ai OpenAI and Anthropic endpoints, then extended with an OpenAI provider for Codex/Responses clients |
| Routing rules defined | In progress | Codex | `config/bifrost/config.template.json` + `curl` verification | 2026-04-08 | Verified `think`, `long_context`, `web_search`, `image`, `background`, and `cheap` bucket behavior on Anthropic-compatible traffic |
| Cache policy defined | In progress | Codex | `config/bifrost/config.template.json` + Redis Stack on `6379` | 2026-04-08 | Dedicated Redis Stack cache backend is active; direct-cache smoke test passed, semantic mode still needs embedding strategy |
| LaunchAgent written | Done | Codex | `config/launchd/ai.bifrost.gateway.plist` + `scripts/bifrost-gateway.zsh` + `scripts/bifrost-ctl` | 2026-04-08 | Wrapper loads secrets, prefers the cached `@maximhq/bifrost` binary, runs from the app dir so `config.db` stays out of the repo root, and `bifrost-ctl` now kills orphan listeners before restart/rebootstrap |
| Validation curl checks pass | In progress | Codex | `curl` to `/v1/chat/completions`, `/anthropic/v1/messages`, and `/v1/responses` | 2026-04-08 | Anthropic path succeeds; route buckets verified; direct-cache smoke test passed; `/v1/models` is healthy after rebootstrap; OpenAI Responses is blocked by upstream OpenAI quota and z.ai chat-completions is blocked by upstream z.ai balance |
| First caller path integrated | In progress | Codex | `mahavishnu/core/app.py` + `mahavishnu/core/adapters/worker.py` + unit tests | 2026-04-08 | Nanobot OpenAI-compatible callers can opt into Bifrost with `BIFROST_BASE_URL` or `MAHAVISHNU_LLM_GATEWAY_BASE_URL` |
| Mahavishnu worker defaults cut over | Paused | Codex | `mahavishnu/workers/registry.py` + worker tests | 2026-04-08 | Worker defaults were temporarily cut to Bifrost, then reverted to each CLI's native direct configuration because subscription-backed traffic does not survive a generic gateway hop |
| Cross-repo provider cutover started | Paused | Codex | `session-buddy` + `crackerjack` local changes and targeted tests | 2026-04-08 | Bifrost-aware codepaths remain available, but active cutover is paused until the ecosystem moves from subscription-backed usage to API-billed usage |
| User-level CLI configs updated | Paused | Codex | `~/.codex/config.toml`, `~/.claude/settings.json`, `~/.qwen/settings.json`, `~/.nanobot/config.json`, `~/.openclaw/openclaw.json` | 2026-04-08 | Live user configs were reverted to direct provider endpoints and native model IDs; Bifrost is intentionally off the critical path for now |
| Codex gateway compatibility proven | In progress | Codex | Bifrost `/v1/models` + `/v1/responses` checks and Codex exec trace | 2026-04-08 | Codex reaches the Bifrost Responses surface; it cannot use `zai-openai/*` because that provider does not support the OpenAI Responses API, so live use still depends on an OpenAI-backed model with quota |
| Client cutover complete | Paused | Codex | Repo changes + user-level CLI configs | 2026-04-08 | Bifrost cutover is paused by design. Subscription-backed clients now bypass the gateway again, and the gateway remains available as a dormant API-billed path for later activation |

## Acceptance Criteria

The plan is complete when:

- Bifrost is the only required gateway component
- OpenAI clients work through `http://127.0.0.1:8471/v1`
- Claude Code works through Bifrost's Anthropic path
- Claude-specific features needed for cutover have been verified: streaming, tool use, prompt-caching semantics, and required passthrough headers
- routing can distinguish at least:
  - default
  - think
  - background
  - long-context
  - image
  - web-search
- exact-match and semantic caching are enabled
- request and token rate limits are enabled
- the gateway survives reboot through LaunchAgent
- the plan document is updated with implementation progress as each milestone lands

## Open Questions

- Which exact Bifrost routing rule shape is best for each client?
- Should Claude Code send task-tier headers directly, or should we infer tiers from model and request type?
- Which providers should be primary and which should be fallback for each route class?
- Which cache TTLs are safe for coding prompts versus general chat?
- Do we need a tiny compatibility wrapper for Claude Code prompt labeling, or is Bifrost routing enough?
- Do we need any local wrapper at all, or can route decisions be made entirely from model names and server-side defaults?
- Should Codex stay on OpenAI-backed `responses` models only, or do we want a separate non-Codex CLI path for z.ai-backed chat-completions models when OpenAI quota is unavailable?

## References

- Bifrost overview: https://docs.getbifrost.ai/
- Bifrost routing rules: https://docs.getbifrost.ai/providers/routing-rules
- Bifrost provider routing: https://docs.getbifrost.ai/providers/provider-routing
- Bifrost request options: https://docs.getbifrost.ai/providers/request-options
- Bifrost supported providers: https://docs.getbifrost.ai/providers/supported-providers
- Bifrost Anthropic integration: https://docs.getbifrost.ai/integrations/anthropic-sdk/overview
- Bifrost OpenAI integration: https://docs.getbifrost.ai/integrations/openai-sdk
- CCR README: https://github.com/musistudio/claude-code-router
