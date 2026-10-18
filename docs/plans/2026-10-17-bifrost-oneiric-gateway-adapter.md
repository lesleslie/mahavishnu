---
status: active
role: implementation
kind: plan
date: 2026-10-17
last_reviewed: 2026-10-18
superseded_by: null
blocks_on: []
related:
  - docs/plans/2026-10-16-drop-ollama-favor-llama-server.md
  - docs/plans/2026-10-15-bifrost-gateway-wiring.md
  - docs/plans/2026-10-15-oneiric-substrate-rollout.md
  - docs/plans/2026-09-27-shared-bodai-substrate-design.md
  - docs/specs/2026-10-15-bifrost-gateway-wiring-design.md
  - docs/decisions/wire-up-contract.md
replaces: null
topic: bifrost-oneiric-gateway-adapter
title: "Bifrost gateway as a oneiric LLM router — Bodai LLM call-site consolidation"

---

# Bifrost gateway as a oneiric LLM router — Bodai LLM call-site consolidation

> **Review status (2026-10-18)**: Plan rewritten twice after agent reviews.
> - **First rewrite** (commit `91331689`): 5-agent multi-agent review (architecture-council, pr-review-toolkit:type-design-analyzer, api-security-specialist, general-purpose, oneiric-specialist). Final design: URL-rewriter via `BifrostLLMRouter` (3-2 vote against chain-member pivot, decided on oneiric specialist's transparent-proxy argument).
> - **Second rewrite** (this document): 3-agent final review pass (2 proper + 1 random). 33 findings addressed. See the §11 3-Agent Final Review Findings appendix.
> - The generalist's B-1 (blocker) caught a real bug: the prior "drop dead fields" decision was based on a wrong audit. Live consumers in `mahavishnu/llm_gateway/contract.py`, `mahavishnu/health.py`, and `mahavishnu/core/health.py` need the fields. Re-declared on `BifrostLLMSettings`.

## 1. Outcome

When this plan ships:

- **Bifrost is a first-class `oneiric.adapters.llm.bifrost.BifrostLLMRouter`**, registered with the oneiric adapter catalog alongside the existing `AnthropicLLM` and `OpenAILLMAdapter` at `oneiric/adapters/llm/`. The router is a *URL resolver* — it returns gateway URLs (or `None` when disabled), it does **not** do HTTP transport. It does **not** subclass `LLMBase` (which is a full HTTP-transport ABC with 8 abstract methods) and it does **not** subclass `LLMBaseSettings` (which carries 21 dead fields including a silent-accept `api_key: SecretStr`). The router extends `pydantic_settings.BaseSettings` directly.
- **All surviving Bodai LLM call sites resolve their base URL through oneiric**, then hand the URL to `mcp_common.llm.OpenAICompatibleProvider` (the existing transport primitive — unchanged). The two layers are cleanly separated: **oneiric owns routing policy, mcp-common owns HTTP transport.**
- **A module-level `get_router()` singleton** is the canonical entry point. Every consumer calls `from oneiric.adapters.llm.bifrost import get_router; get_router().resolve(LLMProvider.ANTHROPIC)`. Consumers do not construct their own router instances, so config drift across call sites is structurally impossible. `reset_router_for_tests()` is the test seam.
- **The "dead flag" anti-pattern is structurally impossible.** A live investigation on 2026-10-17 found that `settings/mahavishnu.yaml:91` sets `route_qwen_code: true` while the master `bifrost.enabled` defaulted to `False`; the `_resolve_worker_env` function in `mahavishnu/terminal/manager.py:56-57` short-circuits on `enabled=False` so the per-worker flag is dead code with no runtime signal. The new router's `resolve(provider) -> str | None` returns `None` (not a flag, not a stub) when disabled, so any call site that consults it cannot produce inert wiring. The Phase 3 dead-flag regression test (in `mahavishnu/tests/unit/terminal/test_manager.py`) pins the `_resolve_worker_env` short-circuit so a future contributor can't reintroduce the bug.
- **mcp-common's `LLMSettings.fallback_chain` and `OpenAICompatibleProvider` stay where they are.** The substrate rollout umbrella (`2026-10-15-oneiric-substrate-rollout.md`) targets settings classes and embedding/auth substrate, not LLM transport. Keeping transport in mcp-common preserves the clean primitive-vs-policy split.
- **PR #0 of the active ollama plan is already merged** on local main (mahavishnu `77b8bed8`, mcp-common `dd889b4`) — confirmed by `git log --oneline main -3` in each repo. The cross-cutting call-site migration in this plan operates on a substrate that no longer has ollama in its default chain.
- **The `ProtocolFamily` enum in `mahavishnu/llm_gateway/client.py:17` is deleted.** The plan reuses the existing `LLMProvider` enum in `oneiric/adapters/llm/llm_interface.py:15-22` (`OPENAI`, `ANTHROPIC`, `AZURE_OPENAI`, `GOOGLE_VERTEX`, `AWS_BEDROCK`, `LOCAL`, `ZAI`). The new router takes `LLMProvider` (not a mahavishnu-internal `ProtocolFamily`).
- **SSRF defense is built in from day one** (see §4.6). All `base_url`-style fields are Pydantic `HttpUrl`; the default is loopback-only; non-loopback URLs require `BIFROST_ALLOW_REMOTE=1`; the opt-in path also blocks AWS/GCP/Azure IMDS IPs and RFC1918 ranges (`169.254.169.254`, `100.100.100.200`, `metadata.google.internal`, `metadata.azure.com`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`). This is non-negotiable.
- **`BifrostLLMSettings` carries the fields live consumers need.** A previous version of this plan claimed `auth_env`, `cache_mode`, `cache_ttl_seconds`, `local_provider_enabled`, `local_provider_url` were "dead in the current schema." The 3-agent final review's B-1 audit (generalist) proved the opposite: each field has live consumers (`auth_env` at `mahavishnu/health.py:176,456,494` and `mahavishnu/core/health.py:99`; `local_provider_*` at `mahavishnu/core/health.py:1326,1334,1337`; `cache_*` at `mahavishnu/llm_gateway/contract.py:147,148,197,202,204,205,232` and `client.py:74,127,128,137,152,153` — the last two files are themselves deleted in Phase 7). All are re-declared on `BifrostLLMSettings` and migrated in Phase 7. Only `request_timeout_seconds` is genuinely dead and is dropped.

## 2. Goals

1. **Add `oneiric.adapters.llm.bifrost.BifrostLLMRouter`** — a new routing-policy class, NOT a subclass of `LLMBase`. The router exposes `resolve(provider: LLMProvider) -> str | None` returning the gateway URL for the given provider when `enabled: True` and `provider` is in the configured `routes` set, else `None`. Also exposes `metadata = AdapterMetadata(...)` so it registers in the catalog.
2. **Add `BifrostLLMSettings(pydantic_settings.BaseSettings)`** with `env_prefix="ONEIRIC_BIFROST_"` (set directly on `SettingsConfigDict`, no inheritance). Includes a back-compat shim for the legacy `MAHAVISHNU_BIFROST__*` env-var prefix (see REQ-BIFROST-011). **Re-declares** the fields live consumers need (`auth_env`, `cache_mode`, `cache_ttl_seconds`, `local_provider_enabled`, `local_provider_url`) so the deletion in Phase 7 doesn't break them. Defines `_SENSITIVE_FIELDS: frozenset[str] = frozenset({"auth_env"})` and overrides `model_dump` / `model_dump_json` so `auth_env` is excluded by default. Only `request_timeout_seconds` is dropped (genuinely dead).
3. **Add a module-level `get_router() -> BifrostLLMRouter` singleton** at `oneiric/adapters/llm/bifrost.py`. Process-cached. **Plus a `reset_router_for_tests()` module-level helper** that clears the cache (the test seam — without it, test pollution is a real risk per REQ-BIFROST-018).
4. **Declare the `LLMProvider → RouteKind` mapping explicitly** as a class-level `_PROVIDER_ROUTE: ClassVar[Mapping[LLMProvider, RouteKind]]`. The 7-value `LLMProvider` enum (`OPENAI`, `ANTHROPIC`, `AZURE_OPENAI`, `GOOGLE_VERTEX`, `AWS_BEDROCK`, `LOCAL`, `ZAI`) maps to a 2-value `RouteKind` enum (`CLAUDE_ROUTE`, `QWEN_ROUTE`) renamed from `CLAUDE_CODE`/`QWEN_CODE` to avoid the value-collision footgun with `worker_type == "terminal-claude"` (REQ-BIFROST-020).
5. **Migrate mahavishnu's three Bifrost-aware call sites** to consume the new router:
   - `mahavishnu/engines/agno_adapter_impl.py:_resolve_bifrost_base_url` (lines 334-378) → call `oneiric.adapters.llm.bifrost.get_router().resolve(LLMProvider.OPENAI)` instead of the local helper
   - `mahavishnu/terminal/manager.py:_resolve_worker_env` (lines 32-68) → drop the `bifrost: BifrostConfig | None` parameter (caller-spoofable, see REQ-BIFROST-004); construct the router inside the function via `get_router()`; inject `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` per the resolved value
   - `mahavishnu/terminal/manager.py:TerminalManager.__init__` (lines 138-169) → **also drop the `bifrost` parameter from the constructor** so the spoofable attack class is fully closed (REQ-BIFROST-023 — surfaces a gap in the previous plan; the constructor still accepted `bifrost` and stored `self.bifrost` even after `_resolve_worker_env` stopped using it)
   - `mahavishnu/workers/capabilities/_probes.py:resolve_probe_endpoint` (lines 132-156) → use oneiric URL when `provider == "minimax"`
6. **Migrate mahavishnu's two direct-from-config call sites** to oneiric-resolved URLs:
   - `mahavishnu/workers/cloud_worker.py:_build_fallback_chain` (lines 73-101) — read both provider URLs from oneiric; pass them to `mcp_common.llm.OpenAICompatibleProvider`
   - `mahavishnu/workers/shepherd_backend.py` and any other `MINIMAX_BASE_URL` / `LLAMA_SERVER_URL` env-var consumers — read from oneiric at startup, fall back to env var for backward compat
7. **Migrate session-buddy's hand-rolled `BifrostClient`** at `session_buddy/bifrost_client.py:32-107` to use oneiric. The two dependents (`session_buddy/worker.py:96`, `session_buddy/memory/entity_extractor.py:132-148`) collapse to "ask oneiric for the URL."
8. **Migrate crackerjack's `FallbackChainCodeFixer`** at `crackerjack/adapters/ai/unified.py:53-72` (per the generalist's M-1 citation correction; the old `:19-72` cite was 34 lines off) to oneiric for URL resolution. The `uses_bifrost: bool` field on `PROVIDER_INFO["minimax"]` is **dropped** (generalist H-3: it had no consumer and structurally mirrored the original `route_qwen_code: True while enabled: False` bug). The `doc_update_service.py:255-273` direct `anthropic.Anthropic` SDK call is **out of scope** (deferred).
9. **Add a `pydantic_ai` adapter** if any Bodai LLM call uses pydantic-ai without going through oneiric. (Audit pending — `mahavishnu/adapters/ai/pydantic_ai_adapter.py:86, 99, 258` has direct `provider_prefixes` that may bypass oneiric. A regression test `tests/unit/adapters/test_pydantic_ai_no_bypass.py` pins the conclusion — the audit cannot degenerate to a PR comment.)
10. **Delete the now-orphaned `BifrostConfig` model** in `mahavishnu/core/config.py:854-989` (per the generalist's H-2 citation correction; the old `:855-947` cite was 42 lines off — the class extends to line 989 where `HNSWIndexConfig` starts at 992). The oneiric router owns the schema from this point on. **`ProtocolFamily` in `mahavishnu/llm_gateway/client.py:17` is also deleted** — replaced by `oneiric.adapters.llm.llm_interface.LLMProvider`.
11. **Preserve backward compat for env vars** — `MAHAVISHNU_BIFROST__*` env vars keep working via a back-compat shim in `BifrostLLMSettings` (lands in Phase 1, not Phase 7). The shim logs a `DeprecationWarning` AND mirrors to a structured INFO log line `legacy_env_prefix_in_use` with operator identity (`getpass.getuser()`, hostname) — `DeprecationWarning` is silent in production per the security agent's F-06. The structured log is the operator-visible surface. (REQ-BIFROST-011.)
12. **Add SSRF defense** as a first-class concern (see §4.6). Pydantic `HttpUrl` for all URL fields, scheme allowlist, loopback-only default, opt-in `BIFROST_ALLOW_REMOTE=1` for non-loopback deployments, **and a metadata-IP + RFC1918 blocklist in the opt-in path** so an attacker who convinces an operator to set `BIFROST_ALLOW_REMOTE=1` still can't pivot to AWS/GCP/Azure IMDS endpoints.
13. **Pin the PiPool security boundary correctly** in REQ-BIFROST-014. The plan previously tested `mahavishnu/pools/pi_pool.py:_env_allowlist`; the actual boundary is the `_FORBIDDEN_ENV_PREFIXES` denylist at `mahavishnu/core/json_rpc_stdio.py:76-83`. The test pins the denylist (and the allowlist as defense-in-depth).
14. **Pin the oneiric PyPI publication step as a precondition** for Phases 2-7. The implementer does NOT run `crackerjack run -p <level>` per `feedback-mcp-common-version-bump-is-user.md`; Phases 2-7 each declare "Triggered from: oneiric PyPI version ≥X.Y.Z (user runs `crackerjack run -p`)" in their Integration Contract.
15. **Make Phase 7 non-deferrable.** The migration is structurally incomplete without it (the dead-field-leak fix only holds if there's no parallel config model that can independently drift). The §9 "done" criteria are unconditional; the §9 cut-rule no longer lists Phase 7 as deferrable.

## 3. Non-Goals

- **Full oneiric substrate migration** (settings classes, embedding, auth, pool) — that's the existing `2026-10-15-oneiric-substrate-rollout.md` umbrella. This plan only touches the LLM-routing slice.
- **Ollama cleanup** — done in PR #0 of `2026-10-16-drop-ollama-favor-llama-server.md`; this plan operates on the post-ollama substrate.
- **Bifrost runtime gateway itself** (the Node.js `@maximhq/bifrost` supervisor at `mahavishnu/scripts/bifrost-gateway.py:1-226` running on `localhost:8471`) — already in place and healthy per the 2026-10-17 audit. The plan does not add new Bifrost routing rules; it routes existing call sites through the existing gateway.
- **PiPool substrate** (`mahavishnu/pools/pi_pool.py`) — the `npx @earendil-works/pi-coding-agent` subprocess uses an env allowlist that explicitly drops `MAHAVISHNU_*` and `MINIMAX_*` keys (`pi_pool.py:139-146` + docstring at lines 13-22). This is a security boundary, not a bug; threading Bifrost config into PiPool would violate the allowlist. The actual enforcement is the `_FORBIDDEN_ENV_PREFIXES` denylist at `mahavishnu/core/json_rpc_stdio.py:76-83`; REQ-BIFROST-014 pins the denylist.
- **crackerjack `doc_update_service.py:255-273` direct Anthropic SDK call** — deferred.
- **Bifrost cache implementation** — `cache_mode` and `cache_ttl_seconds` are carried for consumer compatibility but the router does not implement cache. The fields are read by the health probe; a future plan can add cache behavior.
- **The pydantic-ai adapter work** if Phase 6's audit (pinned by `test_pydantic_ai_no_bypass.py`) reveals all pydantic-ai calls already route through the Agno or CloudWorker paths.
- **Subclassing `LLMBase`** — the router is a standalone class, not a subclass. `LLMBase` is a full HTTP-transport ABC (8 abstract methods); forcing the router into that shape means implementing-theater.
- **Subclassing `LLMBaseSettings`** — the settings class extends `pydantic_settings.BaseSettings` directly. `LLMBaseSettings` carries 21 LLM-client fields the router doesn't need, including `api_key: SecretStr` which silently accepts operator misconfiguration.
- **Subclassing the inherited `LLM_` env_prefix** — `BifrostLLMSettings` overrides `env_prefix` directly on its own `SettingsConfigDict`.

## 4. Current Findings

### 4.1 Inventory (2026-10-17 audit)

A grep-driven inventory across the 4 in-scope Bodai repos (mahavishnu, session-buddy, crackerjack, mcp-common) found **24 LLM call sites**. Categorized:

| Category | Count | Currently uses oneiric? | Action |
|---|---:|---:|---|
| Routes through `mcp_common.llm.FallbackChain` (transport, no Bifrost awareness) | 6 | No | Phase 3: read URL from oneiric, hand to chain |
| Direct SDK calls (agno `OpenAIChat`, `anthropic.Anthropic`) | 7 | No | Phase 2: replace with oneiric-resolved URLs |
| Hardcoded URLs (Bifrost config template, demo defaults, docstrings) | 4 | n/a | Phase 6: replace with oneiric lookups |
| Env-var injection for terminal workers | 2 | No | Phase 4: read base URL from oneiric |
| Embeddings (post-ollama: fastembed + cloud) | 5 | No | Out of scope for this plan; tracked separately |
| **Total** | **24** | **0** | |

**Zero call sites use oneiric LLM adapters today.** The oneiric adapter infrastructure exists (`oneiric/adapters/llm/anthropic.py:42-61` for `AnthropicLLM`; `oneiric/adapters/bootstrap.py:37, 82-141` registers `AnthropicLLM` and `OpenAILLMAdapter` in the catalog) but no Bodai call site consumes it.

### 4.2 The dead-flag bug

`settings/mahavishnu.yaml:55-88` is a fully-commented-out tutorial block (generalist's M-3 citation correction; the old `:55-71` cite was 17 lines off). The live override at `settings/mahavishnu.yaml:90-92` sets only `route_qwen_code: true` + `ssl_show_warn: true` — `enabled` inherits the Pydantic default of `False`. `mahavishnu/terminal/manager.py:56-57` short-circuits on `not bifrost.enabled`, so the per-worker flag is never consulted. Verified at runtime:

```
$ .venv/bin/python -c "from mahavishnu.core.config import get_settings; print(get_settings().bifrost.enabled)"
False
```

The new router's `resolve(provider) -> str | None` returns `None` when `enabled: False`, which means *no consumer can produce inert wiring* — the conditional either resolves to a real URL or `None`, never to a flag that's set but unreachable. The Phase 4 test (`mahavishnu/tests/unit/terminal/test_manager.py::test_resolve_worker_env_dead_flag`) is the structural regression test that catches this specific bug shape.

### 4.3 Two parallel Bifrost integrations in the fleet

- **Mahavishnu's**: `BifrostConfig` pydantic model (`mahavishnu/core/config.py:854-989`) + `_resolve_bifrost_base_url` helper (`mahavishnu/engines/agno_adapter_impl.py:334-378`) + `_resolve_worker_env` env injection (`mahavishnu/terminal/manager.py:32-68`) + `ProtocolFamily` enum (`mahavishnu/llm_gateway/client.py:17`).
- **Session-buddy's**: `BifrostClient` class (`session_buddy/bifrost_client.py:32-107`) + a separate `BIFROST_BASE_URL` env-var contract + `entity_extractor.py:132-148` reading `BIFROST_OPENAI_BASE_URL` directly.

These are **parallel**, not hierarchical. They happen to point at the same `localhost:8471` default URL but they don't share code or config. This plan collapses both into a single oneiric-owned routing surface.

### 4.4 mcp-common substrate compatibility

The active `2026-10-15-oneiric-substrate-rollout.md` umbrella plan (status: active, role: umbrella) covers:
- oneiric runtime-config registry (`oneiric_report_runtime` MCP tool)
- SessionBuddySettings oneiric-shape reshape
- Pgvector warm-tier migration (supplanted)

**None of these touch LLM transport primitives.** The acceptance criteria at line 57 is "Every Bodai core settings class extends OneiricSettings" — settings, not transport. `mcp_common.llm.OpenAICompatibleProvider` and `FallbackChain` are unaffected by this plan.

### 4.5 PR #0 of the active ollama plan already landed

```
mahavishnu:  77b8bed8 chore(ollama): PR #0 — config comments + dict literal + docs
mcp-common:  dd889b4 chore(ollama): PR #0 — fallback_chain default + docstrings
```

`LLMSettings.fallback_chain` default is now `["minimax", "llama_server"]` end-to-end. The `_PYDANTIC_AI_PROVIDER_KEY_ENV` dict in `mahavishnu/cli/demo_cli.py:851` no longer has the `ollama` entry. This plan's call-site migration operates on the post-ollama substrate.

### 4.6 SSRF threat model (extended in second rewrite)

`BifrostConfig.base_url` and `BifrostConfig.anthropic_base_url` are currently `str` fields. A misconfigured or malicious env-var override can point the gateway URL at an attacker-controlled server. Risks:

1. **Credential exfiltration**: the Anthropic / OpenAI / minimax API key is sent to the configured URL on every call. An attacker URL exfiltrates the key.
2. **Prompt exfiltration**: every prompt (including system prompts) is sent to the configured URL. An attacker URL captures all prompt content.
3. **SSRF pivot**: the oneiric adapter is loaded by every Bodai service. A misconfigured URL means the misconfigured service can be tricked into reaching attacker-chosen internal services.

**Defense (mandatory in Phase 1)**:

- All `base_url`-style fields in `BifrostLLMSettings` are Pydantic `HttpUrl` (not `str`). Pydantic validates the URL syntax.
- Scheme allowlist: only `http` and `https` are accepted. Implemented via `@field_validator(mode="after")` on each URL field, or via `Annotated[HttpUrl, AfterValidator(_check_scheme)]`.
- **Default: loopback-only.** A `@model_validator(mode="after")` on `BifrostLLMSettings` rejects non-loopback URLs unless `BIFROST_ALLOW_REMOTE=1` is set in the environment.
- **Opt-in path blocks IMDS and RFC1918.** Even when `BIFROST_ALLOW_REMOTE=1` is set, the validator rejects:
  - **AWS IMDS**: `169.254.169.254`, `169.254.169.253`, `fd00:ec2::254`
  - **GCP IMDS**: `100.100.100.200`, `metadata.google.internal`
  - **Azure IMDS**: `169.254.169.254`, `metadata.azure.com`
  - **RFC1918 ranges**: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
  - **Loopback IPv6**: `::1`
  - **Link-local IPv6**: `fe80::/10`
- The `BIFROST_ALLOW_REMOTE=1` opt-in is logged at INFO with the operator identity (`getpass.getuser()`, `socket.gethostname()`) as structured log fields (not f-string — log injection avoidance). The operator can also disable this with `BIFROST_LOG_OPERATOR_IDENTITY=0` for PII-sensitive environments.

This is documented in the threat model but is *not* a setting the operator can disable in code — the loopback default is hard-coded in Pydantic. The operator can opt in to non-loopback by exporting the env var; the call to `BifrostLLMSettings()` will then accept non-loopback URLs that aren't on the metadata/RFC1918 blocklist.

### 4.7 Design choice: URL-rewriter vs chain-member (5-agent review)

Two design options for the new router:

- **URL-rewriter (chosen)**: the router returns a URL; the consumer hands the URL to its existing transport. The chain's `fallback_chain = ["minimax", "llama_server"]` is unchanged. Bifrost is *invisible* to the chain.
- **Chain-member (rejected)**: the router exposes `to_provider_config() -> ProviderConfig | None`; the chain is rebuilt with the router as a tier.

The oneiric specialist's decisive argument against chain-member: **Bifrost is a transparent proxy; putting it in the chain would compound retry/circuit-breaker logic**. If `fallback_chain = ["bifrost", "minimax", "llama_server"]` and the openai call fails, the chain attributes the failure to the `bifrost` tier and opens a circuit breaker against Bifrost — but the actual upstream is openai. The chain's retry/circuit-breaker credit would be on the wrong tier.

**Chosen: URL-rewriter**, with the chain-member's centralization guarantee recovered by the `get_router()` singleton (§2 goal 3) and the audit script in Phase 8.

### 4.8 The `BifrostLLMRouter` does not subclass `LLMBase` or `LLMBaseSettings` (consolidated)

`oneiric/adapters/llm/llm_interface.py:140-375` defines `LLMBase(ABC)` with 8 abstract methods. `LLMBaseSettings` at line 106-137 has 21 fields tuned for LLM client construction: `model`, `max_tokens`, `temperature`, `top_p`, `frequency_penalty`, `presence_penalty`, `n`, `api_key`, `base_url`, `organization`, `timeout`, `max_retries`, `stream`, `response_format`, `seed`, `stop`, `logit_bias`, `functions`, `function_call`, `tools`, `tool_choice`. The router needs 6 of these (`enabled`, `base_url`, `anthropic_base_url`, `routes`, `qwen_env_var`, `caller_id`) plus 5 re-declared fields for consumer compatibility (`auth_env`, `cache_mode`, `cache_ttl_seconds`, `local_provider_enabled`, `local_provider_url`).

The new `BifrostLLMRouter` and `BifrostLLMSettings` extend `BaseSettings` directly (not `LLMBaseSettings`) — this avoids the silent-accept `api_key: SecretStr` confusion (an operator setting `ONEIRIC_BIFROST__API_KEY=sk-...` would see no error and no effect, since the router doesn't consume it). It also avoids the Pydantic v2 field-type override conflict (`HttpUrl` cannot override `str | None` in a subclass).

### 4.9 Requirements (testable contracts)

Each requirement is testable: a unit test in the appropriate repo pins the contract.

```yaml
requirements:
  - id: REQ-BIFROST-001
    title: "oneiric BifrostLLMRouter catalog entry registered"
    criteria:
      given: a fresh oneiric install
      when: `oneiric.adapters.bootstrap.load_adapters()` runs
      then: `BifrostLLMRouter.metadata` appears in the registered adapters list
      evidence: `oneiric/tests/adapters/llm/test_bifrost.py::test_metadata_registered`

  - id: REQ-BIFROST-002
    title: "Router resolve returns None when disabled, URL when enabled"
    criteria:
      given: `BifrostLLMSettings(enabled=False)` (any value of `routes`)
      when: `router.resolve(LLMProvider.ANTHROPIC)` is called
      then: returns None
      evidence: `oneiric/tests/adapters/llm/test_bifrost.py::test_resolve_disabled`
      and: parametrized over all 7 `LLMProvider` values to make the contract unmissable

  - id: REQ-BIFROST-003
    title: "Dead-flag regression test: per-worker opt-ins inert when enabled=False"
    criteria:
      given: `BifrostLLMSettings(enabled=False, routes={RouteKind.CLAUDE_ROUTE, RouteKind.QWEN_ROUTE})`
      when: `mahavishnu.terminal.manager._resolve_worker_env("terminal-claude")` is called
      then: returns `{}` — no env-var injection
      evidence: `mahavishnu/tests/unit/terminal/test_manager.py::test_resolve_worker_env_dead_flag`

  - id: REQ-BIFROST-004
    title: "_resolve_worker_env drops the bifrost parameter (caller-spoofable)"
    criteria:
      given: the new function signature `_resolve_worker_env(worker_type: str) -> dict[str, str]`
      when: a caller tries to pass `bifrost=BifrostConfig(...)`
      then: TypeError — the parameter no longer exists
      evidence: `mahavishnu/tests/unit/terminal/test_manager.py::test_signature_has_no_bifrost`

  - id: REQ-BIFROST-005
    title: "mahavishnu Agno adapter calls oneiric BifrostLLMRouter"
    criteria:
      given: `ONEIRIC_BIFROST__ENABLED=true`
      when: `LLMProviderFactory.from_settings()._create_anthropic_model("claude-sonnet-4-20250514")` runs
      then: `model.client.base_url` is the oneiric-resolved gateway URL
      evidence: `mahavishnu/tests/unit/engines/test_agno_adapter.py::test_anthropic_model_uses_router`

  - id: REQ-BIFROST-006
    title: "mahavishnu terminal worker env injection reads URL from oneiric"
    criteria:
      given: `ONEIRIC_BIFROST__ENABLED=true, ONEIRIC_BIFROST__ROUTES={CLAUDE_ROUTE}`
      when: `_resolve_worker_env("terminal-claude")` runs
      then: `env["ANTHROPIC_BASE_URL"]` is the oneiric-resolved anthropic URL
      evidence: `mahavishnu/tests/unit/terminal/test_manager.py::test_env_inject_claude`

  - id: REQ-BIFROST-007
    title: "mahavishnu capability probe uses oneiric URL when provider=minimax"
    criteria:
      given: `BifrostLLMSettings(enabled=True, routes={...})`
      when: `resolve_probe_endpoint(provider="minimax")` runs
      then: returns the oneiric-resolved URL for `LLMProvider.OPENAI`
      evidence: `mahavishnu/tests/unit/workers/capabilities/test__probes.py::test_probe_uses_router`

  - id: REQ-BIFROST-008
    title: "mahavishnu CloudWorker._build_fallback_chain reads URLs from oneiric"
    criteria:
      given: `BifrostLLMSettings(enabled=True)`
      when: `CloudWorker._build_fallback_chain()` runs
      then: every chain member's `base_url` is the oneiric-resolved URL for its provider
      evidence: `mahavishnu/tests/unit/workers/test_cloud_worker.py::test_chain_uses_router`

  - id: REQ-BIFROST-009
    title: "session-buddy BifrostClient replaced by oneiric lookup"
    criteria:
      given: `BifrostLLMSettings(enabled=True)`
      when: `LLMManager()` initializes
      then: every chain member's `base_url` is the oneiric-resolved URL
      evidence: `session_buddy/tests/unit/test_llm_providers.py::test_manager_uses_router`

  - id: REQ-BIFROST-010
    title: "crackerjack FallbackChainCodeFixer uses oneiric URL resolution"
    criteria:
      given: `BifrostLLMSettings(enabled=True)`
      when: `FallbackChainCodeFixer()` initializes
      then: every chain member's `base_url` is the oneiric-resolved URL
      evidence: `crackerjack/tests/adapters/test_provider_chain.py::test_chain_uses_router`

  - id: REQ-BIFROST-011
    title: "MAHAVISHNU_BIFROST__* env-var backward compat preserved via oneiric shim"
    criteria:
      given: only `MAHAVISHNU_BIFROST__ENABLED=true` is set (no `ONEIRIC_BIFROST__*`)
      when: `BifrostLLMSettings()` is constructed
      then: `enabled=True` AND a single `DeprecationWarning` is emitted AND a single structured INFO log line `legacy_env_prefix_in_use` is emitted with `prefix="MAHAVISHNU_BIFROST__"` and `operator=<getpass.getuser()>` fields
      evidence: `oneiric/tests/adapters/llm/test_bifrost_env_compat.py::test_legacy_prefix`

  - id: REQ-BIFROST-012
    title: "Orphaned BifrostConfig pydantic model + ProtocolFamily enum deleted from mahavishnu"
    criteria:
      given: mahavishnu after Phase 7
      when: `from mahavishnu.core.config import BifrostConfig` runs
      then: ModuleNotFoundError
      and: `from mahavishnu.llm_gateway.client import ProtocolFamily` also raises ModuleNotFoundError
      evidence: `mahavishnu/tests/unit/test_config.py::test_bifrost_config_removed`

  - id: REQ-BIFROST-013
    title: "Migration verification: every surviving LLM call site resolves through oneiric"
    criteria:
      given: a fresh checkout of all 4 in-scope repos
      when: `python scripts/audit_bifrost_callers.py` runs in CI
      then: exits 0 — every `base_url=...` argument to an LLM client is either (a) sourced from oneiric, or (b) a hardcoded local URL on the `LOCAL_PROVIDER_ALLOWLIST`
      evidence: `scripts/audit_bifrost_callers.py` exit code

  - id: REQ-BIFROST-014
    title: "PiPool env-allowlist security boundary: `_FORBIDDEN_ENV_PREFIXES` denylist includes `MAHAVISHNU_*` and `BIFROST_*`"
    criteria:
      given: the denylist at `mahavishnu/core/json_rpc_stdio.py:76-83`
      when: a test asserts `"MAHAVISHNU_" in _FORBIDDEN_ENV_PREFIXES` and `"BIFROST_" in _FORBIDDEN_ENV_PREFIXES`
      then: both pass — any contributor who loosens the denylist trips the test
      evidence: `mahavishnu/tests/unit/core/test_json_rpc_stdio.py::test_forbidden_env_prefixes_includes_mahavishnu_and_bifrost`
      and: defense-in-depth: the PiPool allowlist at `pi_pool.py:139-146` also has a test that greps for `MAHAVISHNU_BIFROST__` and fails the build if a future contributor adds it

  - id: REQ-BIFROST-015
    title: "BifrostLLMRouter is NOT a subclass of LLMBase"
    criteria:
      given: the new class `BifrostLLMRouter`
      when: `issubclass(BifrostLLMRouter, LLMBase)` runs
      then: False
      evidence: `oneiric/tests/adapters/llm/test_bifrost.py::test_router_not_subclass_of_llmbase`

  - id: REQ-BIFROST-016
    title: "SSRF defense: Pydantic HttpUrl + loopback-only default + IMDS/RFC1918 blocklist in opt-in path"
    criteria:
      given: `BifrostLLMSettings()` with no env-var override
      when: the validator runs
      then: every URL field is a `HttpUrl` with scheme in `{http, https}` AND either (a) the host is loopback, or (b) `BIFROST_ALLOW_REMOTE=1` is set AND the host is not on the metadata/RFC1918 blocklist
      evidence: `oneiric/tests/adapters/llm/test_bifrost_ssrf.py::test_default_loopback_only`
      and: `oneiric/tests/adapters/llm/test_bifrost_ssrf.py::test_allow_remote_blocks_imds`
      and: `oneiric/tests/adapters/llm/test_bifrost_ssrf.py::test_allow_remote_blocks_rfc1918`

  - id: REQ-BIFROST-017
    title: "auth_env excluded from /health.bifrost.config dump via centralized _SENSITIVE_FIELDS"
    criteria:
      given: `BifrostLLMSettings(auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN")`
      when: `settings.model_dump()` is called (no explicit exclude)
      then: the result does NOT contain the field `auth_env`
      and: the field `auth_env` is the env-var *name*, not a secret value — the actual key never enters settings
      evidence: `oneiric/tests/adapters/llm/test_bifrost_health.py::test_auth_env_excluded_default`
      and: `oneiric/tests/adapters/llm/test_bifrost_health.py::test_model_dump_json_also_excludes_auth_env`
      and: the override applies to `model_dump_json` and `dict()` paths too

  - id: REQ-BIFROST-018
    title: "Phase 0 verification: oneiric LLM adapter infrastructure works before Phase 1"
    criteria:
      given: a fresh oneiric install
      when: `oneiric_report_runtime(adapter="anthropic")` MCP tool is called
      then: returns a non-empty `cycles_total` for `AnthropicLLM` (proves the catalog is healthy)
      evidence: Phase 0 verification script output
      and: `reset_router_for_tests()` exists in `oneiric/adapters/llm/bifrost.py` and is exported in `__init__.py` (test seam)

  - id: REQ-BIFROST-019
    title: "AdapterMetadata fields match the AnthropicLLM shape"
    criteria:
      given: `BifrostLLMRouter.metadata`
      when: introspected
      then: it has `category`, `provider`, `factory` (with space after `:`), `description`, `capabilities` (list of strings), `stack_level` (int < 20), `priority` (int < 500), `source` (CandidateSource value), `owner` (string), `requires_secrets` (False), `settings_model` (BifrostLLMSettings)
      evidence: `oneiric/tests/adapters/llm/test_bifrost.py::test_metadata_shape`

  - id: REQ-BIFROST-020
    title: "LLMProvider → RouteKind mapping is explicit"
    criteria:
      given: `BifrostLLMRouter._PROVIDER_ROUTE`
      when: consulted for any of the 7 `LLMProvider` values
      then: returns the corresponding `RouteKind` for `ANTHROPIC` and `OPENAI`; raises `ValueError` (or returns a documented default) for the other 5 values
      evidence: `oneiric/tests/adapters/llm/test_bifrost.py::test_provider_route_mapping_explicit`
      and: parametrized over all 7 LLMProvider values

  - id: REQ-BIFROST-021
    title: "Phase 7 integration test import break is documented and updated"
    criteria:
      given: `mahavishnu/tests/integration/test_bifrost_local_provider_e2e.py:22` imports `BifrostConfig`
      when: Phase 7 deletes the model
      then: the test file is updated to import from `oneiric.adapters.llm.bifrost` instead
      evidence: `mahavishnu/tests/integration/test_bifrost_local_provider_e2e.py` passes

  - id: REQ-BIFROST-022
    title: "Phase 0→1→2→3→4→5→7→8 ordering depends on the oneiric PyPI publication step"
    criteria:
      given: Phase 1 lands the router on oneiric's local `main`
      when: Phases 2-7 import `from oneiric.adapters.llm.bifrost import get_router`
      then: those phases block on the user running `crackerjack run -p <level>` to publish oneiric to PyPI per `feedback-mcp-common-version-bump-is-user.md`
      evidence: each Phase 2-7 Integration Contract declares this precondition in its `Triggered from` block

  - id: REQ-BIFROST-023
    title: "TerminalManager.__init__ drops the bifrost parameter"
    criteria:
      given: the new constructor signature `TerminalManager.__init__(self, adapter, config=None)`
      when: a caller tries to pass `bifrost=BifrostConfig(...)`
      then: TypeError — the parameter no longer exists
      evidence: `mahavishnu/tests/unit/terminal/test_manager.py::test_terminal_manager_constructor_has_no_bifrost`
      and: `mahavishnu/terminal/manager.py:138-169` no longer has the `bifrost` parameter or `self.bifrost` assignment

## 5. Implementation Phases

Each phase is one squash-merge to local `main` per the trunk-based agent-review workflow. **Each phase that depends on oneiric (Phases 2-7) blocks on the user running `crackerjack run -p <level>` after Phase 1 lands** to publish oneiric to PyPI per `feedback-mcp-common-version-bump-is-user.md` (REQ-BIFROST-022). The implementer does NOT do this.

### Phase 0: Verify oneiric LLM adapter infrastructure (gate, oneiric repo)

**Goal**: Before adding a new adapter, confirm the existing catalog is healthy. The plan's §4.1 says "Zero call sites use oneiric LLM adapters today" — but the *infrastructure* (registration, lifecycle, health probe) must work.

**Tasks**:
- `oneiric/tests/adapters/llm/test_infrastructure_health.py` (new): confirms `AnthropicLLM.metadata`, `OpenAILLMAdapter.metadata`, and the `builtin_adapter_metadata()` list all load without error.
- Run `oneiric_report_runtime(adapter="anthropic")` via the Akosha MCP — confirm `cycles_total >= 1` after a one-shot init.
- Confirm `oneiric/adapters/bootstrap.py:37` eager import works in a clean venv.

**No new code** — only verification. If verification fails, escalate to a oneiric substrate fix plan before Phase 1.

#### Integration Contract (Phase 0)

- **Triggered from**: `oneiric_report_runtime` MCP tool.
- **Returns to / updates**: a pass/fail gate result. No persistent state.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/oneiric
  .venv/bin/python -c "from oneiric.adapters.bootstrap import builtin_adapter_metadata; print(len(builtin_adapter_metadata()))"
  # Prints a non-zero number (currently ~57).
  ```
- **Rollback signal**: Phase 0 fails → Phase 1 is blocked.
- **Observability added**: none.

### Phase 1: `oneiric.adapters.llm.bifrost.BifrostLLMRouter` (additive, oneiric repo)

**Goal**: Land the new router in oneiric. No existing call site is touched; this is pure addition.

**Tasks**:
- `oneiric/adapters/llm/bifrost.py` (new):
  - `class RouteKind(StrEnum)`: `CLAUDE_ROUTE = "claude_route"`, `QWEN_ROUTE = "qwen_route"`. Renamed from `CLAUDE_CODE`/`QWEN_CODE` to avoid the value-collision footgun with `worker_type == "terminal-claude"` (type F5).
  - `class BifrostLLMSettings(pydantic_settings.BaseSettings)`:
    - `model_config = SettingsConfigDict(env_prefix="ONEIRIC_BIFROST_", env_nested_delimiter="__", extra="allow", populate_by_name=True)` — set directly on `SettingsConfigDict`, no inheritance.
    - `enabled: bool = Field(default=False)`.
    - `base_url: HttpUrl = Field(default=HttpUrl("http://127.0.0.1:8471"))`.
    - `anthropic_base_url: HttpUrl = Field(default=HttpUrl("http://127.0.0.1:8471/anthropic"))`.
    - `routes: set[RouteKind] = Field(default_factory=set)`.
    - `qwen_env_var: str = Field(default="OPENAI_BASE_URL")`.
    - `caller_id: str = Field(default="")`.
    - **Re-declared fields for consumer compatibility** (B-1 fix):
      - `auth_env: str = Field(default="MAHAVISHNU_BIFROST_AUTH_TOKEN")` — the env-var *name*, not the secret value.
      - `cache_mode: Literal["off", "direct", "semantic"] = "off"`.
      - `cache_ttl_seconds: int = 0`.
      - `local_provider_enabled: bool = False`.
      - `local_provider_url: HttpUrl | None = None`.
    - `_SENSITIVE_FIELDS: ClassVar[frozenset[str]] = frozenset({"auth_env"})` (security F-02 fix; centralized exclusion list).
    - `@model_validator(mode="before") def _load_legacy_env(cls, data: Any) -> Any` (type F12): reads `MAHAVISHNU_BIFROST__*` env vars and applies them if the new `ONEIRIC_BIFROST__*` var is unset. Emits one `DeprecationWarning` (REQ-BIFROST-011) AND logs one INFO line `legacy_env_prefix_in_use` (security F-06 fix) with `prefix` and `operator` fields.
    - `@model_validator(mode="after") def _check_loopback_and_imds(self) -> "BifrostLLMSettings"` (type F12, security F-01): validates every `HttpUrl` field:
      - Scheme must be `http` or `https` (security F-10 fix; `scheme_allowlist` is not a Pydantic v2 feature).
      - Default: loopback-only. Rejects non-loopback hosts unless `BIFROST_ALLOW_REMOTE=1` is set.
      - Opt-in path: blocks AWS IMDS (`169.254.169.254`, `169.254.169.253`), GCP IMDS (`100.100.100.200`, `metadata.google.internal`), Azure IMDS (`metadata.azure.com`), RFC1918 ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback IPv6 (`::1`), link-local IPv6 (`fe80::/10`).
      - The opt-in is logged at INFO with structured fields `allow_remote_opt_in=true`, `operator=getpass.getuser()`, `hostname=socket.gethostname()`. `BIFROST_LOG_OPERATOR_IDENTITY=0` disables the operator/hostname fields for PII-sensitive environments.
    - `def model_dump(self, *, exclude: set[str] | None = None, **kwargs: Any) -> dict[str, Any]`: overrides Pydantic's default to apply `_SENSITIVE_FIELDS` as a default exclusion (security F-02 fix). The override makes `model_dump(exclude={"auth_env"})` redundant in callers — but keeps the parameter, so explicit `exclude=set()` opts in to inclusion.
    - `def model_dump_json(self, *, exclude: set[str] | None = None, **kwargs: Any) -> str`: same exclusion override (security F-02 fix).
  - `class BifrostLLMRouter`:
    - `_PROVIDER_ROUTE: ClassVar[Mapping[LLMProvider, RouteKind]] = {LLMProvider.ANTHROPIC: RouteKind.CLAUDE_ROUTE, LLMProvider.OPENAI: RouteKind.QWEN_ROUTE}` (type F1 fix; explicit 7→2 mapping).
    - `metadata = AdapterMetadata(category="llm", provider="bifrost", factory="oneiric.adapters.llm.bifrost: BifrostLLMRouter", description="Bifrost gateway URL resolver for OpenAI-compatible and Anthropic-compatible routing", capabilities=["routing"], stack_level=14, priority=450, source=CandidateSource.LOCAL_PKG, owner="AI Platform", requires_secrets=False, settings_model=BifrostLLMSettings)` (type F7 + F9 fixes: factory string with space after `:`; comment explaining the priority rationale — "Bifrost is a transparent proxy; clients should pick the real provider and have it routed through Bifrost").
    - `def __init__(self, settings: BifrostLLMSettings | None = None) -> None`: shows the constructor (type F13 fix). Default `settings = settings or BifrostLLMSettings()`.
    - `def resolve(self, provider: LLMProvider) -> str | None` (type F1 fix):
      - Returns `None` when `self._settings.enabled is False` (REQ-BIFROST-002).
      - Returns `None` when the required route for the provider is not in `self._settings.routes`. The required route is `_PROVIDER_ROUTE[provider]`; raises `KeyError` if the provider has no mapping (caller bug).
      - Returns `str(self._settings.base_url)` (or `anthropic_base_url` for Anthropic).
    - **Standalone class — does NOT subclass `LLMBase` or `LLMBaseSettings`.** (REQ-BIFROST-015.)
  - Module-level:
    - `_ROUTER_SINGLETON: BifrostLLMRouter | None = None`.
    - `def get_router() -> BifrostLLMRouter`: process-cached. Tests monkeypatch this seam.
    - `def reset_router_for_tests() -> None` (type F6 + security F-11 fix): clears `_ROUTER_SINGLETON`. Called from a `pytest.fixture` in `oneiric/tests/adapters/llm/conftest.py`. Documented as test-only.
- `oneiric/adapters/bootstrap.py`: **lazy register** — modify `builtin_adapter_metadata()` (line 82) to import `BifrostLLMRouter` lazily inside the function and add its `metadata` to the list (type F8 fix; single `package_name="oneiric.adapters"` namespace preserved). The eager `from .llm import AnthropicLLM, OpenAILLMAdapter` at line 37 stays unchanged.
  ```python
  def builtin_adapter_metadata() -> list[AdapterMetadata]:
      adapters = [
          # ... existing list (unchanged) ...
      ]
      from .llm.bifrost import BifrostLLMRouter  # lazy import
      adapters.append(BifrostLLMRouter.metadata)
      return adapters
  ```
- `oneiric/adapters/llm/__init__.py`: re-export `BifrostLLMRouter`, `BifrostLLMSettings`, `RouteKind`, `get_router`, `reset_router_for_tests`.
- `oneiric/tests/adapters/llm/test_bifrost.py` (new): REQ-BIFROST-001, REQ-BIFROST-002, REQ-BIFROST-015, REQ-BIFROST-019, REQ-BIFROST-020 (parametrized over all 7 LLMProvider values).
- `oneiric/tests/adapters/llm/test_bifrost_dead_flag.py` (new): REQ-BIFROST-002's disabled-returns-None assertion.
- `oneiric/tests/adapters/llm/test_bifrost_ssrf.py` (new): REQ-BIFROST-016 — Pydantic HttpUrl + loopback default + IMDS/RFC1918 blocklist in opt-in path.
- `oneiric/tests/adapters/llm/test_bifrost_env_compat.py` (new): REQ-BIFROST-011 — `MAHAVISHNU_BIFROST__*` back-compat shim, both DeprecationWarning and structured INFO log.
- `oneiric/tests/adapters/llm/test_bifrost_health.py` (new): REQ-BIFROST-017 — `auth_env` exclusion in `model_dump` AND `model_dump_json` defaults.
- `oneiric/tests/adapters/llm/conftest.py` (new): `reset_router_for_tests()` fixture.

#### Integration Contract (Phase 1)

- **Triggered from**: `oneiric.adapters.bootstrap.register_builtin_adapters()` (which calls `builtin_adapter_metadata()`) runs lazily (on first `Resolver()` call). The new router is registered as a side effect of the first `get_router()` call.
- **Returns to / updates**: `oneiric.adapters.registry` (the in-memory catalog). Queryable via `oneiric.adapters.llm.bifrost.get_router().resolve(LLMProvider.ANTHROPIC)`.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/oneiric
  ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_route .venv/bin/python -c "
  from oneiric.adapters.llm.bifrost import get_router
  from oneiric.adapters.llm.llm_interface import LLMProvider
  print(get_router().resolve(LLMProvider.ANTHROPIC))
  # Prints 'http://127.0.0.1:8471/anthropic'.
  "
  ```
- **Rollback signal**: `BifrostLLMRouter` not found in `oneiric_report_runtime` MCP output.
- **Observability added**: OTel counter `oneiric.adapter.lookup{adapter="bifrost"}` + structured log line `adapter.bifrost.resolved provider=<p> resolved=true|false url=<redacted>`.

### Phase 2: mahavishnu Agno + CloudWorker + probe migration (3 call sites in one PR)

**Goal**: Three mahavishnu call sites that are Bifrost-aware today stop inlining routing logic and call oneiric instead.

**Triggered from**: `oneiric PyPI version ≥X.Y.Z` (the user runs `crackerjack run -p <level>` to publish after Phase 1 lands on oneiric's local main). The implementer does NOT do this.

**Tasks**:
- `mahavishnu/engines/agno_adapter_impl.py:198-332`: replace the 4 `_create_*_model` factory methods' use of `_resolve_bifrost_base_url` with `from oneiric.adapters.llm.bifrost import get_router; get_router().resolve(LLMProvider.OPENAI)` (or `LLMProvider.ANTHROPIC` for the Claude factory). Delete the local `_resolve_bifrost_base_url` helper (lines 334-378).
- `mahavishnu/llm_gateway/client.py`: delete the `ProtocolFamily` enum and the `gateway_api_base` function. Both are no longer used after this phase.
- `mahavishnu/workers/cloud_worker.py:73-101`: `_build_fallback_chain` reads `minimax_url` from `get_router().resolve(LLMProvider.OPENAI)` and `llama_server_url` from a local config. Pass to `mcp_common.llm.OpenAICompatibleProvider`.
- `mahavishnu/workers/capabilities/_probes.py:132-156`: `resolve_probe_endpoint` calls `get_router().resolve(LLMProvider.OPENAI)` for `provider == "minimax"`.
- Tests:
  - `tests/unit/engines/test_agno_adapter.py::test_anthropic_model_uses_router`: REQ-BIFROST-005.
  - `tests/unit/workers/test_cloud_worker.py::test_chain_uses_router`: REQ-BIFROST-008.
  - `tests/unit/workers/capabilities/test__probes.py::test_probe_uses_router`: REQ-BIFROST-007.

#### Integration Contract (Phase 2)

- **Triggered from**: any code path that constructs an Agno model, builds a `CloudWorker`, or resolves a `minimax` capability probe. **Precondition**: oneiric PyPI version ≥ the Phase 1 version (REQ-BIFROST-022).
- **Returns to / updates**: the constructed `OpenAIChat` / `Claude` / `FallbackChain` instances carry the oneiric-resolved `base_url`. No persistent state change.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/mahavishnu
  ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_route .venv/bin/python -c "
  from mahavishnu.engines.agno_adapter_impl import LLMProviderFactory
  m = LLMProviderFactory.from_settings()
  print(m._create_anthropic_model('claude-sonnet-4-20250514').client.base_url)
  "
  ```
- **Rollback signal**: Agno factory raises on first model construction. CloudWorker raises on first `execute()`. Probe resolution returns `None` in `/health.bifrost.reachable`.
- **Observability added**: OTel counter `mahavishnu.llm.bifrost_resolved{provider, site, resolved}` + log line `llm.bifrost.resolved site=agno provider=openai url=<redacted>`.

### Phase 3: mahavishnu terminal worker env injection (broader scope)

**Goal**: `mahavishnu/terminal/manager.py:_resolve_worker_env` reads the base URL from oneiric. **The `bifrost` parameter is dropped from BOTH `_resolve_worker_env` and `TerminalManager.__init__`** — the previous plan only dropped it from the inner helper, leaving the constructor's `bifrost` parameter as a caller-spoofable attack class (security F-03).

**Triggered from**: oneiric PyPI publication (REQ-BIFROST-022).

**Tasks**:
- `mahavishnu/terminal/manager.py:32-68`: change `_resolve_worker_env(worker_type, bifrost)` to `_resolve_worker_env(worker_type: str) -> dict[str, str]`. Inside, call `from oneiric.adapters.llm.bifrost import get_router; router = get_router()`. The function consults `router._settings.enabled` and `router._settings.routes` directly.
- `mahavishnu/terminal/manager.py:138-169`: **also change** `TerminalManager.__init__(self, adapter, config=None, bifrost: BifrostConfig | None = None)` to `TerminalManager.__init__(self, adapter, config=None)`. Remove the `self.bifrost = bifrost` assignment at line 159. Update the docstring at lines 148-156 (REQ-BIFROST-023).
- `mahavishnu/terminal/manager.py:18`: drop the `from mahavishnu.llm_gateway.client import ProtocolFamily, gateway_api_base` import.
- Tests:
  - `tests/unit/terminal/test_manager.py::test_resolve_worker_env_dead_flag`: REQ-BIFROST-003.
  - `tests/unit/terminal/test_manager.py::test_signature_has_no_bifrost`: REQ-BIFROST-004.
  - `tests/unit/terminal/test_manager.py::test_env_inject_claude`: REQ-BIFROST-006.
  - `tests/unit/terminal/test_manager.py::test_terminal_manager_constructor_has_no_bifrost`: REQ-BIFROST-023.
  - `tests/unit/core/test_json_rpc_stdio.py::test_forbidden_env_prefixes_includes_mahavishnu_and_bifrost`: REQ-BIFROST-014 — pins the actual PiPool security boundary (the `_FORBIDDEN_ENV_PREFIXES` denylist at `json_rpc_stdio.py:76-83`).
  - `tests/unit/pools/test_pi_pool.py::test_env_allowlist_excludes_bifrost_prefixes`: REQ-BIFROST-014 (defense-in-depth) — re-derived from the actual allowlist source (not a string grep).

#### Integration Contract (Phase 3)

- **Triggered from**: `mahavishnu.terminal.manager._resolve_worker_env(worker_type)` and `TerminalManager(adapter, config=None)`. **Precondition**: oneiric PyPI version (REQ-BIFROST-022).
- **Returns to / updates**: the dict of env vars injected into the tmux session at spawn. No persistent state.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/mahavishnu
  ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_route .venv/bin/python -c "
  from mahavishnu.terminal.manager import _resolve_worker_env
  print(_resolve_worker_env('terminal-claude'))
  # Prints {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8471/anthropic'}.
  "

  # Old constructor signature raises TypeError
  .venv/bin/python -c "
  from mahavishnu.terminal.manager import TerminalManager
  TerminalManager(None, bifrost=None)
  # TypeError: TerminalManager.__init__() got an unexpected keyword argument 'bifrost'.
  "
  ```
- **Rollback signal**: terminal worker spawn fails. Constructor call fails.
- **Observability added**: log line `terminal.bifrost.env_inject worker_type=<t> injected_keys=[...] url=<redacted>`.

### Phase 4: session-buddy BifrostClient → oneiric

**Triggered from**: oneiric PyPI publication (REQ-BIFROST-022).

**Tasks**:
- `session_buddy/bifrost_client.py`: delete the file.
- `session_buddy/worker.py:14, 96`: replace `BifrostClient` import with `from oneiric.adapters.llm.bifrost import get_router`.
- `session_buddy/memory/entity_extractor.py:132-148`: replace the `BIFROST_OPENAI_BASE_URL` env-var read with `get_router().resolve(LLMProvider.OPENAI)`.
- `session_buddy/llm_providers.py:383-431, 510-519`: `LLMManager` calls `get_router()` for URL resolution.
- Tests: `session_buddy/tests/unit/test_llm_providers.py::test_manager_uses_router`: REQ-BIFROST-009.

### Phase 5: crackerjack FallbackChainCodeFixer → oneiric (broader scope)

**Triggered from**: oneiric PyPI publication (REQ-BIFROST-022).

**Tasks**:
- `crackerjack/adapters/ai/unified.py:53-72`: `_build_llm_settings` reads provider URLs from `get_router().resolve(LLMProvider.OPENAI)` (generalist M-1 citation correction; the old `:19-72` cite was 34 lines off).
- `crackerjack/adapters/ai/registry.py:9-12, 29-57`: **drop the `uses_bifrost: bool` field** from `PROVIDER_INFO["minimax"]` (generalist H-3 fix). The field had no consumer and structurally mirrored the original `route_qwen_code: True while enabled: False` bug. The audit script in Phase 8 catches any provider that bypasses oneiric.
- Tests:
  - `crackerjack/tests/adapters/test_ai_registry.py::test_uses_bifrost_field_removed`: asserts the field is gone.
  - `crackerjack/tests/adapters/test_provider_chain.py::test_chain_uses_router`: REQ-BIFROST-010.

### Phase 6: Pydantic-AI audit + (conditional) oneiric migration

**Triggered from**: oneiric PyPI publication (REQ-BIFROST-022).

**Tasks**:
- **Audit** (mandatory): grep all `provider_prefixes`, `httpx` `base_url=`, and direct SDK instantiations in pydantic-ai adapter.
- **Conditional migration** (if audit surfaces bypasses): migrate the bypassing call sites to `get_router()`.
- **Pinned test** (L-1 fix): `tests/unit/adapters/test_pydantic_ai_no_bypass.py` asserts the audit grep result. The audit cannot degenerate to a one-line PR comment.

### Phase 7: Mahavishnu BifrostConfig + ProtocolFamily deletion (non-deferrable)

**Triggered from**: oneiric PyPI publication (REQ-BIFROST-022). **Phase 7 is NOT deferrable** (generalist M-4 fix); the migration is structurally incomplete without it.

**Tasks**:
- `mahavishnu/core/config.py:854-989` (generalist H-2 citation correction; the old `:855-947` cite was 42 lines off): delete `BifrostConfig` class. Migrate the live consumers to read from the oneiric router:
  - `mahavishnu/health.py:176, 456, 494` — replace `BifrostConfig.auth_env` reads with `get_router()._settings.auth_env`. Add the centralized-exclusion test that pins `_SENSITIVE_FIELDS` (REQ-BIFROST-017).
  - `mahavishnu/core/health.py:99, 1326, 1334, 1337` — replace `BifrostConfig.auth_env` and `BifrostConfig.local_provider_*` reads with `get_router()._settings.<field>`. The `local_provider_*` reads use the centralized `get_router()._settings` to avoid the dead-field-leak that the previous plan had.
- `mahavishnu/llm_gateway/client.py`: delete the entire file. `ProtocolFamily` and `gateway_api_base` are no longer used.
- `mahavishnu/health.py:178, 457, 494`: rewrite the `/health.bifrost.config` probe to query the oneiric router: `get_router()._settings.model_dump()`. The model_dump override (from `BifrostLLMSettings`) excludes `auth_env` by default (security F-02 fix). Non-loopback URLs are also excluded if `/health.bifrost.config` is auth-gated to non-trusted callers (security F-07 fix).
- `mahavishnu/cli/config_validator.py:508, 521`: same.
- `mahavishnu/observability/prometheus_metrics.py:371, 376`: read `local_provider_url` from `get_router()._settings`.
- `mahavishnu/core/health.py:1303-1337`: same.
- `mahavishnu/observability/prometheus_metrics.py:161-381`: same.
- `mahavishnu/scripts/bifrost-gateway.py`: unchanged.
- `mahavishnu/scripts/audit_bifrost_grep.py`: unchanged.
- **Phase 7 urljoin note** (security F-12): the plan notes that future URL composition in oneiric should use `urllib.parse.urlunparse((scheme, netloc, path, params, query, fragment))` rather than `urljoin`, because `urljoin` discards the host when given an absolute path. The original `gateway_api_base` used `urljoin` and is being deleted.
- **Phase 7 integration test import break** (REQ-BIFROST-021): `mahavishnu/tests/integration/test_bifrost_local_provider_e2e.py:22` imports `BifrostConfig`. Update the import to `from oneiric.adapters.llm.bifrost import get_router`.
- Tests:
  - `tests/unit/test_config.py::test_bifrost_config_removed`: REQ-BIFROST-012.
  - `tests/unit/test_health_bifrost.py::test_auth_env_excluded`: REQ-BIFROST-017.
  - `tests/integration/test_bifrost_local_provider_e2e.py`: imports updated, passes (REQ-BIFROST-021).
  - `tests/unit/test_health_bifrost.py::test_non_loopback_url_redacted_when_unauth`: REQ-BIFROST-017 (F-07 fix); asserts that when `/health` is unauthenticated, non-loopback `base_url` is also excluded.

### Phase 8: End-to-end migration verification

**Triggered from**: oneiric PyPI publication (REQ-BIFROST-022).

**Tasks**:
- `scripts/audit_bifrost_callers.py` (new): a one-shot audit script that walks the 4 in-scope repos and asserts that any `base_url=...` argument to an LLM client construction is either (a) sourced from oneiric via `get_router().resolve(...)`, or (b) a hardcoded local URL on the `LOCAL_PROVIDER_ALLOWLIST`. Direct base URLs not in either set fail the audit.
- `docs/llm-routing.md` (new): a one-page reference that documents the oneiric ownership and lists the call sites + their routing source.
- `docs/plans/PLAN_INDEX.md`: move this plan from `draft` to `complete` (regenerated by `scripts/regenerate_plan_index.py`).

## 6. Required Code Changes

### oneiric (Phases 0, 1)

- [ ] `oneiric/tests/adapters/llm/test_infrastructure_health.py` (new — REQ-BIFROST-018 Phase 0 gate)
- [ ] `oneiric/adapters/llm/bifrost.py` (new — `BifrostLLMSettings`, `BifrostLLMRouter`, `RouteKind`, `_PROVIDER_ROUTE`, `_SENSITIVE_FIELDS`, `get_router`, `reset_router_for_tests`)
- [ ] `oneiric/adapters/llm/__init__.py` (re-export including `reset_router_for_tests`)
- [ ] `oneiric/adapters/bootstrap.py` (lazy register `BifrostLLMRouter.metadata` inside `builtin_adapter_metadata()`)
- [ ] `oneiric/tests/adapters/llm/test_bifrost.py` (new — REQ-BIFROST-001, 002, 015, 019, 020)
- [ ] `oneiric/tests/adapters/llm/test_bifrost_dead_flag.py` (new — REQ-BIFROST-002 regression)
- [ ] `oneiric/tests/adapters/llm/test_bifrost_ssrf.py` (new — REQ-BIFROST-016)
- [ ] `oneiric/tests/adapters/llm/test_bifrost_env_compat.py` (new — REQ-BIFROST-011)
- [ ] `oneiric/tests/adapters/llm/test_bifrost_health.py` (new — REQ-BIFROST-017, F-07 fix)
- [ ] `oneiric/tests/adapters/llm/conftest.py` (new — `reset_router_for_tests` fixture)

### mahavishnu (Phases 2, 3, 7)

- [ ] `mahavishnu/engines/agno_adapter_impl.py` (Phase 2 — REQ-BIFROST-005)
- [ ] `mahavishnu/workers/cloud_worker.py` (Phase 2 — REQ-BIFROST-008)
- [ ] `mahavishnu/workers/capabilities/_probes.py` (Phase 2 — REQ-BIFROST-007)
- [ ] `mahavishnu/terminal/manager.py` (Phase 3 — REQ-BIFROST-003, 004, 006, 023; F-03 fix; both `_resolve_worker_env` and `TerminalManager.__init__`)
- [ ] `mahavishnu/llm_gateway/client.py` (Phase 2 + Phase 7 — delete `ProtocolFamily`, `gateway_api_base`, and the file itself)
- [ ] `mahavishnu/core/config.py:854-989` (Phase 7 — REQ-BIFROST-012, delete `BifrostConfig`; B-1 fix is the consumer migration in `health.py` and `core/health.py`)
- [ ] `mahavishnu/health.py` (Phase 7 — B-1 fix: read `auth_env` from router; REQ-BIFROST-017; F-07 fix)
- [ ] `mahavishnu/cli/config_validator.py` (Phase 7)
- [ ] `mahavishnu/observability/prometheus_metrics.py` (Phase 7)
- [ ] `mahavishnu/core/health.py:99, 1303-1337, 1326, 1334, 1337` (Phase 7 — B-1 fix: read `auth_env` and `local_provider_*` from router)
- [ ] `mahavishnu/tests/integration/test_bifrost_local_provider_e2e.py:22` (Phase 7 — REQ-BIFROST-021)
- [ ] `tests/unit/engines/test_agno_adapter.py` (Phase 2 — REQ-BIFROST-005)
- [ ] `tests/unit/workers/test_cloud_worker.py` (Phase 2 — REQ-BIFROST-008)
- [ ] `tests/unit/workers/capabilities/test__probes.py` (Phase 2 — REQ-BIFROST-007)
- [ ] `tests/unit/terminal/test_manager.py` (Phase 3 — REQ-BIFROST-003, 004, 006, 023)
- [ ] `tests/unit/core/test_json_rpc_stdio.py` (Phase 3 — REQ-BIFROST-014)
- [ ] `tests/unit/pools/test_pi_pool.py` (Phase 3 — REQ-BIFROST-014 defense-in-depth)
- [ ] `tests/unit/test_config.py` (Phase 7 — REQ-BIFROST-012)
- [ ] `tests/unit/test_health_bifrost.py` (Phase 7 — REQ-BIFROST-017 + F-07 fix)

### session-buddy (Phase 4)

- [ ] `session_buddy/bifrost_client.py` (delete)
- [ ] `session_buddy/worker.py` (Phase 4 — REQ-BIFROST-009)
- [ ] `session_buddy/memory/entity_extractor.py` (Phase 4 — REQ-BIFROST-009)
- [ ] `session_buddy/llm_providers.py` (Phase 4)
- [ ] `session_buddy/tests/unit/test_llm_providers.py` (Phase 4 — REQ-BIFROST-009)

### crackerjack (Phase 5)

- [ ] `crackerjack/adapters/ai/unified.py:53-72` (Phase 5 — REQ-BIFROST-010; M-1 citation correction)
- [ ] `crackerjack/adapters/ai/registry.py:9-12, 29-57` (Phase 5 — H-3 fix: drop `uses_bifrost` field)
- [ ] `crackerjack/tests/adapters/test_ai_registry.py` (Phase 5)
- [ ] `crackerjack/tests/adapters/test_provider_chain.py` (Phase 5 — REQ-BIFROST-010)

### pydantic-ai (Phase 6 — conditional)

- [ ] `mahavishnu/adapters/ai/pydantic_ai_adapter.py` (Phase 6 — only if audit surfaces bypasses)
- [ ] `mahavishnu/tests/unit/adapters/test_pydantic_ai_no_bypass.py` (Phase 6 — L-1 fix; pins the audit conclusion)

### cross-repo (Phase 8)

- [ ] `mahavishnu/scripts/audit_bifrost_callers.py` (new)
- [ ] `docs/llm-routing.md` (new)
- [ ] `docs/plans/PLAN_INDEX.md` (move this plan from `draft` to `complete` — regenerated by `scripts/regenerate_plan_index.py`)

## 7. Validation Matrix

The validation matrix below pins the explicit before/after signatures for each command.

| Check | Command | Expected outcome | Evidence |
|---|---|---|---|
| oneiric adapter infrastructure healthy (Phase 0) | `cd /Users/les/Projects/oneiric && .venv/bin/python -c "from oneiric.adapters.bootstrap import builtin_adapter_metadata; print(len(builtin_adapter_metadata()))"` | `>=58` (was 57 + 1 new) | Test log |
| oneiric adapter registered (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -c "from oneiric.adapters.llm.bifrost import get_router, BifrostLLMRouter; print(BifrostLLMRouter.metadata.provider)"` | `bifrost` | Test log |
| Router is NOT LLMBase subclass (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -c "from oneiric.adapters.llm.bifrost import BifrostLLMRouter; from oneiric.adapters.llm.llm_interface import LLMBase; print(issubclass(BifrostLLMRouter, LLMBase))"` | `False` | Test log |
| Dead-flag regression — `resolve` (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost_dead_flag.py -q` | Pass | Test log |
| SSRF default (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost_ssrf.py -q` | Pass | Test log |
| env-var back-compat (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost_env_compat.py -q` | Pass (warning + log line) | Test log |
| `/health.bifrost.config` auth_env exclusion (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost_health.py -q` | Pass | Test log |
| Provider mapping is explicit (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost.py -q -k "test_provider_route_mapping"` | Pass (parametrized over 7 LLMProvider values) | Test log |
| `reset_router_for_tests` exists (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -c "from oneiric.adapters.llm.bifrost import reset_router_for_tests; print('ok')"` | `ok` | Test log |
| Mahavishnu Agno routes through oneiric (Phase 2) | `cd /Users/les/Projects/mahavishnu && ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_route .venv/bin/python -c "from mahavishnu.engines.agno_adapter_impl import LLMProviderFactory; m = LLMProviderFactory.from_settings(); print(m._create_anthropic_model('claude-sonnet-4-20250514').client.base_url)"` | Gateway URL | Test log |
| Mahavishnu terminal env injection — new signature (Phase 3) | `ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_route .venv/bin/python -c "from mahavishnu.terminal.manager import _resolve_worker_env; print(_resolve_worker_env('terminal-claude'))"` | `{'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8471/anthropic'}` | Test log |
| Mahavishnu terminal dead-flag (Phase 3) | `ONEIRIC_BIFROST__ENABLED=false ONEIRIC_BIFROST__ROUTES=claude_route,qwen_route .venv/bin/python -c "from mahavishnu.terminal.manager import _resolve_worker_env; print(_resolve_worker_env('terminal-claude'))"` | `{}` | Test log |
| Mahavishnu terminal — old signature raises (Phase 3) | `.venv/bin/python -c "from mahavishnu.terminal.manager import _resolve_worker_env; _resolve_worker_env('claude', bifrost=None)"` | `TypeError: _resolve_worker_env() got an unexpected keyword argument 'bifrost'` | Test log |
| Mahavishnu TerminalManager constructor — old signature raises (Phase 3, REQ-BIFROST-023) | `.venv/bin/python -c "from mahavishnu.terminal.manager import TerminalManager; TerminalManager(None, bifrost=None)"` | `TypeError: TerminalManager.__init__() got an unexpected keyword argument 'bifrost'` | Test log |
| PiPool denylist (Phase 3) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/core/test_json_rpc_stdio.py -q -k "test_forbidden_env_prefixes"` | Pass | Test log |
| PiPool allowlist defense-in-depth (Phase 3) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/pools/test_pi_pool.py -q -k "test_env_allowlist"` | Pass | Test log |
| Session-buddy URLs (Phase 4) | `cd /Users/les/Projects/session-buddy && ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=openai,claude_route .venv/bin/python -c "from session_buddy.llm_providers import LLMManager; m = LLMManager(); print([p.base_url for p in m._chain._providers])"` | Gateway URLs | Test log |
| Crackerjack URLs (Phase 5) | `cd /Users/les/Projects/crackerjack && ONEIRIC_BIFROST__ENABLED=true .venv/bin/python -c "from crackerjack.adapters.ai.unified import FallbackChainCodeFixer; fc = FallbackChainCodeFixer(); print([p.base_url for p in fc._chain._providers])"` | Gateway URLs | Test log |
| Crackerjack `uses_bifrost` field removed (Phase 5) | `cd /Users/les/Projects/crackerjack && .venv/bin/python -c "from crackerjack.adapters.ai.registry import PROVIDER_INFO; assert 'uses_bifrost' not in PROVIDER_INFO['minimax']"` | No `AssertionError` | Test log |
| Pydantic-AI audit pinned (Phase 6) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/adapters/test_pydantic_ai_no_bypass.py -q` | Pass | Test log |
| `BifrostConfig` deleted from mahavishnu (Phase 7) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "from mahavishnu.core.config import BifrostConfig"` | `ModuleNotFoundError` | Test log |
| `ProtocolFamily` deleted from mahavishnu (Phase 7) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "from mahavishnu.llm_gateway.client import ProtocolFamily"` | `ModuleNotFoundError` | Test log |
| `/health.bifrost.config` reads from router (Phase 7) | `cd /Users/les/Projects/mahavishnu && ONEIRIC_BIFROST__ENABLED=true .venv/bin/python -m mahavishnu health` | Output includes `auth_env` excluded | Test log |
| `test_bifrost_local_provider_e2e.py` imports updated (Phase 7) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/integration/test_bifrost_local_provider_e2e.py -q` | Pass | Test log |
| All call sites use oneiric (Phase 8) | `cd /Users/les/Projects/mahavishnu && python scripts/audit_bifrost_callers.py` | Exits 0 | Audit log |
| Crackerjack merge gate (each repo) | `cd <repo> && crackerjack run -v -f` | Pass | Test log |
| pytest | `pytest tests/unit -q` | Pass (modulo known pre-existing failures) | Test log |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| **IMDS pivot**: `BIFROST_ALLOW_REMOTE=1` allows non-loopback; attacker convinces operator to set it, then exfiltrates to `169.254.169.254` | Medium | REQ-BIFROST-016: opt-in path also blocks AWS/GCP/Azure IMDS IPs and RFC1918 ranges. The opt-in is logged at INFO with operator identity. |
| **The oneiric publication step blocks Phases 2-7** until the user runs `crackerjack run -p <level>` per `feedback-mcp-common-version-bump-is-user.md` | High (deterministic) | REQ-BIFROST-022: each Phase 2-7 Integration Contract declares the publication precondition in its `Triggered from` block. The implementer does NOT do this; the user runs `crackerjack run -p` from their shell. |
| **Dead-field leak via `BifrostLLMRouter` settings migration**: `BifrostConfig` consumers don't migrate and break in Phase 7 | Medium | B-1 fix: `BifrostLLMSettings` re-declares `auth_env`, `cache_mode`, `cache_ttl_seconds`, `local_provider_enabled`, `local_provider_url`. Phase 7 migrates the consumers to read from `get_router()._settings`. |
| **`MAHAVISHNU_BIFROST__*` env-var prefix breaks for operators** | Low | REQ-BIFROST-011: back-compat shim in `BifrostLLMSettings` reads legacy prefix and emits one `DeprecationWarning` AND one structured INFO log `legacy_env_prefix_in_use` with operator identity (closes the migration gap). |
| **`TerminalManager.__init__` still accepts caller-spoofable `bifrost`** | Low (after Phase 3 fix) | REQ-BIFROST-023: Phase 3 drops the `bifrost` parameter from both `_resolve_worker_env` AND `TerminalManager.__init__`. The previous plan only fixed the inner helper. |
| **`api_key: SecretStr` silently accepted as `ONEIRIC_BIFROST__API_KEY`** | Low (now) | `BifrostLLMSettings` extends `pydantic_settings.BaseSettings` directly, not `LLMBaseSettings`. The 21 dead LLM-client fields (including the silent-accept `api_key`) are not inherited. |
| **`auth_env` leaks through `/health.bifrost.config`** | Low (now) | REQ-BIFROST-017: centralized `_SENSITIVE_FIELDS: frozenset[str]` + `model_dump`/`model_dump_json` override so `auth_env` is excluded by default. Tested with `model_dump_json` and `dict()` paths too. |
| **Pydantic v2 `HttpUrl` field-override conflict with `LLMBaseSettings.base_url: str \| None`** | Eliminated (now) | `BifrostLLMSettings` extends `pydantic_settings.BaseSettings` directly. |
| **Test pollution from `get_router()` singleton** | Low (now) | REQ-BIFROST-018: `reset_router_for_tests()` module-level helper + `conftest.py` pytest fixture. |
| **PiPool env-allowlist regression test pins the wrong boundary** | Low (now) | REQ-BIFROST-014: the test pins `_FORBIDDEN_ENV_PREFIXES` denylist at `json_rpc_stdio.py:76-83` (the actual security boundary), with the PiPool allowlist as defense-in-depth. |
| **Operator-identity PII in logs** | Low (now) | `BIFROST_LOG_OPERATOR_IDENTITY=0` env var disables the operator/hostname fields for PII-sensitive environments. |
| **Plan citation drift on `BifrostConfig` (855-947 vs 854-989)** | Low (now) | All citations re-cite to 854-989. |
| **Phase 6 audit degenerates to a one-line PR comment** | Low (now) | L-1 fix: `tests/unit/adapters/test_pydantic_ai_no_bypass.py` pins the audit conclusion. |
| **Phase 7 deferral leaves the migration structurally incomplete** | Low (now) | M-4 fix: Phase 7 is non-deferrable. §9's "done" criteria are unconditional. |
| `uses_bifrost` field on `PROVIDER_INFO["minimax"]` is a dead-flag repeat | Low (now) | H-3 fix: drop the field. The audit script in Phase 8 catches any provider that bypasses oneiric. |
| session-buddy's `BifrostClient` is consumed by external code | Low | `grep -r "BifrostClient" /Users/les/Projects/` confirms no external consumers. |
| Multi-repo merge coordination cost (8 phases across 4 repos) | Medium | Per-repo merge via squash-merge. Each repo's `crackerjack run -v -f` gates its own merge. Sequence: oneiric (Phases 0-1) → mahavishnu (Phases 2-3) → session-buddy (Phase 4) → crackerjack (Phase 5) → mahavishnu (Phases 6-7) → cross-repo (Phase 8). With the oneiric publication block between Phase 1 and Phase 2. |
| `test_bifrost_local_provider_e2e.py` import break in Phase 7 | Low | REQ-BIFROST-021: documented in Phase 7's required code changes. |

## 9. Decision Rule

This plan is "done" when:

- A user can run `ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_route .venv/bin/mahavishnu demo agno --prompt "..."` against the local Bifrost gateway and get a real LLM completion routed through the gateway.
- `crackerjack run -v -f` passes in every repo.
- `scripts/audit_bifrost_callers.py` exits 0.
- `/health.bifrost.config` returns the oneiric-derived values without `auth_env` leakage.
- The dead-flag regression tests in `oneiric/tests/adapters/llm/test_bifrost_dead_flag.py` AND `mahavishnu/tests/unit/terminal/test_manager.py::test_resolve_worker_env_dead_flag` both pass.
- The `MAHAVISHNU_BIFROST__*` env-var back-compat shim works without code changes on the operator's side, and emits both a `DeprecationWarning` AND a structured INFO log `legacy_env_prefix_in_use` with operator identity.
- `from mahavishnu.core.config import BifrostConfig` raises `ModuleNotFoundError`.
- `from mahavishnu.llm_gateway.client import ProtocolFamily` raises `ModuleNotFoundError`.
- `issubclass(BifrostLLMRouter, LLMBase)` returns `False`.
- The `_FORBIDDEN_ENV_PREFIXES` denylist test passes (`test_forbidden_env_prefixes_includes_mahavishnu_and_bifrost`).
- The `reset_router_for_tests` test passes.
- The non-loopback URL redaction test passes (when `/health` is unauthenticated).
- The plan has been promoted from `status: draft` to `status: complete` in `docs/plans/PLAN_INDEX.md` (regenerated by `scripts/regenerate_plan_index.py`).

**Phase 7 is non-deferrable.** The migration is structurally incomplete without it (the dead-field-leak fix only holds if there's no parallel config model that can independently drift).

**If scope pressure forces a cut**:

- **Drop Phase 6 (pydantic-ai audit) first.** It's conditional — if the audit (pinned by `test_pydantic_ai_no_bypass.py`) shows all pydantic-ai calls go through the Agno factory or CloudWorker, Phase 6 is a one-line audit note.

**Post-plan discipline**:

- After all per-repo merges land on local `main`, do **NOT** run `git push origin main` — push is user-controlled per `feedback-bodai-push-is-user-controlled.md`.
- The user runs `git push` from their own shell.
- The implementer does **NOT** bump the oneiric version themselves per `feedback-mcp-common-version-bump-is-user.md`; the user runs `crackerjack run -p <level>` from their shell to bump+tag+publish when ready. This is the publication step Phases 2-7 depend on.
- Each per-repo commit is authored as `les@wedgwoodwebworks.com` (not `.local`) with no `Co-Authored-By` trailer per `feedback-no-claude-code-coauthor-attribution.md`.
- The new `oneiric.adapters.llm.bifrost` adapter is *additive* — no existing oneiric call site is changed. Backward compat is automatic for the four repos that don't yet import the new adapter.
- The `BIFROST_ALLOW_REMOTE=1` opt-in for non-loopback URLs is logged at INFO with the operator identity. Operators in cloud deployments must explicitly set this env var.
- The `BIFROST_LOG_OPERATOR_IDENTITY=0` opt-out disables the operator/hostname fields in INFO logs for PII-sensitive environments.

## 10. 5-Agent Review Synthesis (Appendix — historical)

This plan was rewritten after a 5-agent multi-agent review (2026-10-18). The agents and their findings:

| Agent | Lens | Stance on URL-rewriter vs chain-member | Key findings contributed |
|---|---|---|---|
| architecture-council | Platform architecture | For chain-member (3) | "Chain constructor handles it; dead-flag pattern can't exist" — but recovered by `get_router()` singleton + audit script. |
| pr-review-toolkit:type-design-analyzer | Type design | For chain-member (3) | LLMBase subclassing is wrong; rename to `BifrostLLMRouter`; env_prefix inheritance bug; rewrite REQ-NNNs as testable contracts. |
| api-security-specialist | API security | For chain-member (3) | SSRF threat model; `auth_env` exclusion test; `BifrostLLMRouter` is caller-spoofable; Pydantic `HttpUrl` + loopback default. |
| general-purpose | Generalist | For URL-rewriter (2) | "Transparent proxy doesn't need its own class — `get_router()` is enough." |
| oneiric-specialist | Adapter registry | For URL-rewriter (2) | **Decisive argument**: Bifrost is a transparent proxy; putting it in the chain would compound retry/circuit-breaker logic. Standalone class, not LLMBase subclass. Lazy registration from bootstrap. `LLMProvider` enum reuse. |

Final tally: 3-2 in favor of chain-member. **Chosen: URL-rewriter**, because the oneiric specialist's transparent-proxy argument is the most technically concrete and the chain-member's centralization guarantee is recoverable via the `get_router()` singleton + audit script.

## 11. 3-Agent Final Review Findings (Appendix)

This plan was rewritten a second time after a 3-agent final review (2026-10-18). The 2 proper agents + 1 random were:

- **pr-review-toolkit:type-design-analyzer** (proper)
- **api-security-specialist** (proper)
- **general-purpose** (random)

**33 findings, 1 blocker**: all addressed in this document.

### Cross-cutting findings (2+ agents agreed)

| Finding | From | Fix in this rewrite |
|---|---|---|
| Pydantic v2 `HttpUrl` override of `LLMBaseSettings.base_url: str \| None` fails; `scheme_allowlist` is not a Pydantic v2 feature | type F3, security F-10 | Extend `pydantic_settings.BaseSettings` directly, not `LLMBaseSettings` (§2 goal 2, §4.8). |
| `get_router()` test pollution | type F6, security F-11 | `reset_router_for_tests()` + `conftest.py` fixture (REQ-BIFROST-018). |
| `auth_env` field semantics / exclusion coverage | type F2, security F-02, F-09 | `_SENSITIVE_FIELDS: frozenset[str]` + `model_dump`/`model_dump_json` overrides (REQ-BIFROST-017). |

### Blocker

- **B-1** (generalist): The plan claimed `auth_env`, `cache_mode`, `cache_ttl_seconds`, `local_provider_*` were "dead in the current schema" — but each has live consumers (`auth_env` at `mahavishnu/health.py:176,456,494` and `mahavishnu/core/health.py:99`; `local_provider_*` at `mahavishnu/core/health.py:1326,1334,1337`; `cache_*` at `mahavishnu/llm_gateway/contract.py:147,148,197,202,204,205,232` and `client.py:74,127,128,137,152,153`). Phase 7 would break these. **Fix**: re-declare the fields on `BifrostLLMSettings`; migrate consumers in Phase 7 to read from `get_router()._settings` (§1, §2 goal 2, §5 Phase 7). Only `request_timeout_seconds` is dropped (genuinely dead).

### High

- **H-1** (generalist): REQ-BIFROST-019, 020, 021 referenced in §5/§6/§10 but undefined in §4.9. **Fix**: added to §4.9.
- **H-2** (generalist): `BifrostConfig` cited as 855-947, actually 854-989. **Fix**: re-cite everywhere.
- **H-3** (generalist): `uses_bifrost: bool` field on `PROVIDER_INFO["minimax"]` with no consumer. **Fix**: drop the field in Phase 5.
- **F1** (type): 7-value `LLMProvider` → 2-value `RouteKind` mapping is implicit. **Fix**: explicit `_PROVIDER_ROUTE: ClassVar[Mapping[LLMProvider, RouteKind]]` (REQ-BIFROST-020).

### Medium

- **F-01** (security): `BIFROST_ALLOW_REMOTE=1` doesn't block IMDS / RFC1918. **Fix**: extended SSRF defense with metadata-IP and RFC1918 blocklists (REQ-BIFROST-016).
- **F-03** (security): `TerminalManager.__init__` still accepts caller-spoofable `bifrost`. **Fix**: drop in Phase 3, add REQ-BIFROST-023.
- **F-04** (security): REQ-BIFROST-014 tested the wrong boundary. **Fix**: pin the `_FORBIDDEN_ENV_PREFIXES` denylist as the actual boundary.
- **M-1** (generalist): `crackerjack/adapters/ai/unified.py:19-72` cite was 34 lines off. **Fix**: re-cite to 53-72.
- **M-2** (generalist): Cross-repo merge order omitted the user-driven oneiric publication step. **Fix**: each Phase 2-7 Integration Contract declares this precondition (REQ-BIFROST-022).
- **M-3** (generalist): `settings/mahavishnu.yaml:55-71` cite was 17 lines off. **Fix**: re-cite to 55-88.
- **M-4** (generalist): §9 hard "done" criterion contradicted §9 cut-rule that defers Phase 7. **Fix**: Phase 7 is non-deferrable; §9 unconditional.

### Low

- **F-02** (security): Centralized `_SENSITIVE_FIELDS` — covered above.
- **F5** (type): `RouteKind.CLAUDE_CODE` value collided with `worker_type == "terminal-claude"` semantics. **Fix**: renamed to `CLAUDE_ROUTE`/`QWEN_ROUTE` with values `"claude_route"`/`"qwen_route"`.
- **F-05** (security): PII in operator identity logs. **Fix**: `BIFROST_LOG_OPERATOR_IDENTITY=0` opt-out.
- **F-06** (security): `DeprecationWarning` silent in production. **Fix**: mirror to structured INFO log `legacy_env_prefix_in_use`.
- **F-07** (security): `/health.bifrost.config` exposes non-loopback URLs. **Fix**: redact non-loopback URLs in unauthenticated `/health`.
- **F-08** (security): `url=<redacted>` underspecified. **Fix**: future URL composition uses `urllib.parse.urlunparse` (urljoin pitfall noted).
- **F-10** (security): `Field(..., scheme_allowlist=...)` not a Pydantic v2 feature. **Fix**: covered by F3 cross-cutting fix.
- **F-12** (type): Specify Pydantic v2 validator decorators. **Fix**: spelled out (`@model_validator(mode="before")` for legacy env, `@model_validator(mode="after")` for loopback+IMDS).
- **F-13** (type): `BifrostLLMRouter.__init__` not shown. **Fix**: shown in §5 Phase 1.
- **F7** (type): `metadata.factory` missing space after `:`. **Fix**: `factory="oneiric.adapters.llm.bifrost: BifrostLLMRouter"`.
- **F8** (type): Lazy-registration snippet created separate package namespace. **Fix**: lazy import inside `builtin_adapter_metadata()`.
- **F9** (type): `stack_level=14` / `priority=450` rationale not documented. **Fix**: comment added.
- **F10** (type): Removing dead fields needs call-site audit. **Fix**: audit done — see B-1 above.
- **F11** (type): `test_env_allowlist_excludes_bifrost` is a string-grep. **Fix**: covered by F-04 cross-cutting fix.
- **L-1** (generalist): Phase 6 audit needs a test pinning. **Fix**: `tests/unit/adapters/test_pydantic_ai_no_bypass.py` added.
- **L-2** (generalist): `auth_env` leak risk restates REQ-BIFROST-017. **Fix**: dropped.
- **L-3** (generalist): `scripts/bifrost-gateway.py:1-220` is 226 lines. **Fix**: re-cite to 1-226.
- **F-12** (security): `urljoin` absolute-path-override pitfall. **Fix**: noted in Phase 7.
- **F-13** (security): `_FORBIDDEN_ENV_PREFIXES` denylist has no regression test. **Fix**: REQ-BIFROST-014 pins the denylist.

### What the agents say is sound (no change needed)

- Standalone class, not LLMBase subclass
- `set[RouteKind]` over two booleans
- `HttpUrl` + loopback validator (extended per F-01)
- Reuse `LLMProvider`, delete `ProtocolFamily`
- `get_router()` singleton (with F-11 fix)
- `BIFROST_ALLOW_REMOTE=1` opt-in (extended per F-01)
- Phase 0 verification gate
- `audit_bifrost_callers.py` allowlist
- No API keys in plan log lines
- §10 5-agent review attribution is correct
- §3 Non-Goals correctly carve out the substrate, ollama, bifrost runtime, PiPool, doc_update_service, settings/embedding/auth
- §5 Phase 0→1→2→3→4→5→7→8 ordering is sound (with M-2 publication acknowledgement)

## References

- `docs/plans/2026-10-16-drop-ollama-favor-llama-server.md` — the active ollama removal plan; PR #0 already landed in this repo (`77b8bed8`) and mcp-common (`dd889b4`).
- `docs/plans/2026-10-15-bifrost-gateway-wiring.md` — the existing Bifrost wiring plan (Phase D Qwen gate); the wiring this plan consolidates.
- `docs/plans/2026-10-15-oneiric-substrate-rollout.md` — the umbrella oneiric substrate plan; this plan is a slice of it (LLM routing) that doesn't conflict with settings-class or embedding-substrate work.
- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` — the v1.5 Bifrost design spec; the schema here is a superset of the spec's Phase A fields.
- `oneiric/adapters/llm/llm_interface.py:15-22` — the `LLMProvider` enum reused for router's `resolve` parameter.
- `oneiric/adapters/llm/llm_interface.py:140-375` — the `LLMBase` ABC; the new router does NOT subclass it.
- `oneiric/adapters/llm/anthropic.py:42-61` — the `AnthropicLLM.metadata` shape the new `BifrostLLMRouter.metadata` follows.
- `oneiric/adapters/bootstrap.py:37, 82-141` — the `builtin_adapter_metadata()` list; the new router registers lazily inside this function.
- `mcp_common/llm/provider.py:30-58` — the `OpenAICompatibleProvider` that the new router hands URLs to.
- `mahavishnu/core/config.py:854-989` — the current `BifrostConfig` model that Phase 7 deletes.
- `mahavishnu/llm_gateway/client.py:17` — the `ProtocolFamily` enum that Phase 7 deletes.
- `mahavishnu/terminal/manager.py:32-68` — the current `_resolve_worker_env` helper that Phase 3 replaces.
- `mahavishnu/terminal/manager.py:138-169` — the `TerminalManager.__init__` that Phase 3 also updates (REQ-BIFROST-023).
- `mahavishnu/engines/agno_adapter_impl.py:334-378` — the current `_resolve_bifrost_base_url` helper that Phase 2 deletes.
- `mahavishnu/core/json_rpc_stdio.py:76-83` — the `_FORBIDDEN_ENV_PREFIXES` denylist that REQ-BIFROST-014 pins.
- `session_buddy/bifrost_client.py:32-107` — the parallel session-buddy implementation that Phase 4 deletes.
- `crackerjack/adapters/ai/unified.py:53-72` — the crackerjack call site that Phase 5 migrates.
- `docs/decisions/wire-up-contract.md` — the policy this plan implements (Integration Contract block per phase).
- `feedback-no-claude-code-coauthor-attribution.md` — no `Co-Authored-By` trailer on commits.
- `feedback-bodai-push-is-user-controlled.md` — push is user-controlled; implementer does NOT `git push origin main`.
- `feedback-mcp-common-version-bump-is-user.md` — version bumps are user-controlled; implementer does NOT edit `pyproject.toml` version. The user runs `crackerjack run -p <level>` to publish oneiric to PyPI. Phases 2-7 depend on this.
- `bodai-pre-1.0-merge-policy.md` — direct merge to `main`, no PRs.
- `feedback-crackerjack-merge-gate-is-vf.md` — gate is `crackerjack run -v -f`.
- `feedback-no-backwards-compat-pre-1.0.md` — replace not extend; no deprecation windows (the env-var back-compat shim in Phase 1 is the one exception, and it's clearly labeled as transitional).
- `mahavishnu/CLAUDE.md` § "Crackerjack-Compliant Code" — gate and conventions.
- `mahavishnu/CLAUDE.md` § "Process Discipline" — Integration Contract requirement per phase deliverable.
