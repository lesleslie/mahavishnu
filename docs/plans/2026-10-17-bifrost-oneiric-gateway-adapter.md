---
status: draft
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

> **Review status (2026-10-18)**: Plan rewritten after a 5-agent multi-agent review (architecture-council, pr-review-toolkit:type-design-analyzer, api-security-specialist, general-purpose, oneiric-specialist). Final design: **URL-rewriter via a new `BifrostLLMRouter` class** (3-2 vote against chain-member pivot). Twenty-one concrete findings were addressed — see the "5-agent review synthesis" appendix at the end of the doc.

## 1. Outcome

When this plan ships:

- **Bifrost is a first-class `oneiric.adapters.llm.bifrost.BifrostLLMRouter`**, registered with the oneiric adapter catalog alongside the existing `AnthropicLLM` and `OpenAILLMAdapter` at `oneiric/adapters/llm/`. The router is a *URL resolver* — it returns gateway URLs (or `None` when disabled), it does **not** do HTTP transport. It does **not** subclass `LLMBase` (which is a full HTTP-transport ABC with 8 abstract methods — see §4.7).
- **All surviving Bodai LLM call sites resolve their base URL through oneiric**, then hand the URL to `mcp_common.llm.OpenAICompatibleProvider` (the existing transport primitive — unchanged). The two layers are cleanly separated: **oneiric owns routing policy, mcp-common owns HTTP transport.**
- **A module-level `get_router()` singleton** is the canonical entry point. Every consumer calls `from oneiric.adapters.llm.bifrost import get_router; get_router().resolve(LLMProvider.ANTHROPIC)`. Consumers do not construct their own router instances, so config drift across call sites is structurally impossible.
- **The "dead flag" anti-pattern is structurally impossible.** A live investigation on 2026-10-17 found that `settings/mahavishnu.yaml:91` sets `route_qwen_code: true` while the master `bifrost.enabled` defaulted to `False`; the `_resolve_worker_env` function in `mahavishnu/terminal/manager.py:56-57` short-circuits on `enabled=False` so the per-worker flag is dead code with no runtime signal. The new router's `resolve(provider) -> str | None` returns `None` (not a flag, not a stub) when disabled, so any call site that consults it cannot produce inert wiring. The Phase 3 dead-flag regression test (in `mahavishnu/tests/unit/terminal/test_manager.py`) pins the `_resolve_worker_env` short-circuit so a future contributor can't reintroduce the bug.
- **mcp-common's `LLMSettings.fallback_chain` and `OpenAICompatibleProvider` stay where they are.** The substrate rollout umbrella (`2026-10-15-oneiric-substrate-rollout.md`) targets settings classes and embedding/auth substrate, not LLM transport. Keeping transport in mcp-common preserves the clean primitive-vs-policy split.
- **PR #0 of the active ollama plan is already merged** on local main (mahavishnu `77b8bed8`, mcp-common `dd889b4`) — confirmed by `git log --oneline main -3` in each repo. The cross-cutting call-site migration in this plan operates on a substrate that no longer has ollama in its default chain.
- **The `ProtocolFamily` enum in `mahavishnu/llm_gateway/client.py:17` is deleted.** The plan reuses the existing `LLMProvider` enum in `oneiric/adapters/llm/llm_interface.py:15-22` (`OPENAI`, `ANTHROPIC`, `AZURE_OPENAI`, `GOOGLE_VERTEX`, `AWS_BEDROCK`, `LOCAL`, `ZAI`). The new router takes `LLMProvider` (not a mahavishnu-internal `ProtocolFamily`).
- **SSRF defense is built in from day one** (see §4.6). All `base_url` fields are Pydantic `HttpUrl`; the default is loopback-only; non-loopback URLs require `BIFROST_ALLOW_REMOTE=1`. This is non-negotiable.

## 2. Goals

1. **Add `oneiric.adapters.llm.bifrost.BifrostLLMRouter`** — a new routing-policy class, NOT a subclass of `LLMBase`. The router exposes `resolve(provider: LLMProvider) -> str | None` returning the gateway URL for the given provider when `enabled: True` and `provider` is in the configured `routes` set, else `None`. Also exposes `metadata = AdapterMetadata(...)` so it registers in the catalog.
2. **Add `BifrostLLMSettings(LLMBaseSettings)`** with `env_prefix="ONEIRIC_BIFROST_"` (overriding the inherited `LLM_` prefix). Includes a back-compat shim for the legacy `MAHAVISHNU_BIFROST__*` env-var prefix — see REQ-BIFROST-013.
3. **Add a module-level `get_router() -> BifrostLLMRouter` singleton** at `oneiric/adapters/llm/bifrost.py`. Process-cached. Tests monkeypatch this seam. The fleet calls this, not `BifrostLLMRouter()` directly.
4. **Migrate mahavishnu's three Bifrost-aware call sites** to consume the new router:
   - `mahavishnu/engines/agno_adapter_impl.py:_resolve_bifrost_base_url` (lines 334-378) → call `oneiric.adapters.llm.bifrost.get_router().resolve(LLMProvider.OPENAI)` instead of the local helper
   - `mahavishnu/terminal/manager.py:_resolve_worker_env` (lines 32-68) → drop the `bifrost: BifrostConfig | None` parameter (caller-spoofable, see REQ-BIFROST-004); construct the router inside the function via `get_router()`; inject `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` per the resolved value
   - `mahavishnu/workers/capabilities/_probes.py:resolve_probe_endpoint` (lines 132-156) → use oneiric URL when `provider == "minimax"`
5. **Migrate mahavishnu's two direct-from-config call sites** to oneiric-resolved URLs:
   - `mahavishnu/workers/cloud_worker.py:_build_fallback_chain` (lines 73-101) — read both provider URLs from oneiric; pass them to `mcp_common.llm.OpenAICompatibleProvider`
   - `mahavishnu/workers/shepherd_backend.py` and any other `MINIMAX_BASE_URL` / `LLAMA_SERVER_URL` env-var consumers — read from oneiric at startup, fall back to env var for backward compat
6. **Migrate session-buddy's hand-rolled `BifrostClient`** at `session_buddy/bifrost_client.py:32-107` to use oneiric. The two dependents (`session_buddy/worker.py:96`, `session_buddy/memory/entity_extractor.py:132-148`) collapse to "ask oneiric for the URL."
7. **Migrate crackerjack's `FallbackChainCodeFixer`** at `crackerjack/adapters/ai/unified.py:19-72` to oneiric for URL resolution. The `doc_update_service.py:255-273` direct `anthropic.Anthropic` SDK call is **out of scope** (deferred — it's a one-shot direct call, not a router).
8. **Add a `pydantic_ai` adapter** if any Bodai LLM call uses pydantic-ai without going through oneiric. (Audit pending — `mahavishnu/adapters/ai/pydantic_ai_adapter.py:86, 99, 258` has direct `provider_prefixes` that may bypass oneiric.)
9. **Delete the now-orphaned `BifrostConfig` model** in `mahavishnu/core/config.py:855-947` after the migration. The oneiric router owns the schema from this point on. **`ProtocolFamily` in `mahavishnu/llm_gateway/client.py:17` is also deleted** — replaced by `oneiric.adapters.llm.llm_interface.LLMProvider`.
10. **Preserve backward compat for env vars** — `MAHAVISHNU_BIFROST__*` env vars keep working via a back-compat shim in `BifrostLLMSettings` (lands in Phase 1, not Phase 7). The shim logs a one-time `DeprecationWarning` per process that includes the operator identity (per REQ-BIFROST-013).
11. **Add SSRF defense** as a first-class concern (see §4.6). Pydantic `HttpUrl` for all URL fields, scheme allowlist, loopback-only default, opt-in `BIFROST_ALLOW_REMOTE=1` for non-loopback deployments.
12. **Delete the mahavishnu-internal `ProtocolFamily` enum** at `mahavishnu/llm_gateway/client.py:17`. All consumers use `oneiric.adapters.llm.llm_interface.LLMProvider` directly.

## 3. Non-Goals

- **Full oneiric substrate migration** (settings classes, embedding, auth, pool) — that's the existing `2026-10-15-oneiric-substrate-rollout.md` umbrella. This plan only touches the LLM-routing slice.
- **Ollama cleanup** — done in PR #0 of `2026-10-16-drop-ollama-favor-llama-server.md`; this plan operates on the post-ollama substrate.
- **Bifrost runtime gateway itself** (the Node.js `@maximhq/bifrost` supervisor at `mahavishnu/scripts/bifrost-gateway.py:1-220` running on `localhost:8471`) — already in place and healthy per the 2026-10-17 audit (`curl http://localhost:8471/health` returns `ok`). The plan does not add new Bifrost routing rules; it routes existing call sites through the existing gateway.
- **PiPool substrate** (`mahavishnu/pools/pi_pool.py`) — the `npx @earendil-works/pi-coding-agent` subprocess uses an env allowlist that explicitly drops `MAHAVISHNU_*` and `MINIMAX_*` keys (`pi_pool.py:139-146` + docstring at lines 13-22). This is a security boundary, not a bug; threading Bifrost config into PiPool would violate the allowlist. REQ-BIFROST-014 adds a regression test that fails if a future contributor adds `MAHAVISHNU_BIFROST__*` to the allowlist.
- **crackerjack `doc_update_service.py:255-273` direct Anthropic SDK call** — deferred. It's a one-shot LLM call in a code-fix flow; routing through oneiric is nice-to-have, not load-bearing.
- **Bifrost config schema migrations for operators** — the new `ONEIRIC_BIFROST__*` env-var prefix is the canonical; the legacy `MAHAVISHNU_BIFROST__*` prefix is honored as a back-compat shim with a deprecation log. No operator action required for existing deployments.
- **Bifrost cache mode (`cache_mode: off | direct | semantic`)** — the active config has it off; the new router does not implement cache. Add later if a plan requires it.
- **The pydantic-ai adapter work** if Phase 7's audit reveals all pydantic-ai calls already route through the Agno or CloudWorker paths.
- **Subclassing `LLMBase`** — the router is a standalone class, not a subclass. `LLMBase` is a full HTTP-transport ABC (8 abstract methods); forcing the router into that shape means implementing-theater for methods that never run. The router has a single concrete method (`resolve`) plus a class-level `metadata` — no need for ABC machinery.

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

**Zero call sites use oneiric LLM adapters today.** The oneiric adapter infrastructure exists (`oneiric/adapters/llm/anthropic.py:42-61` for `AnthropicLLM`; `oneiric/adapters/bootstrap.py:37, 106-107` registers `AnthropicLLM` and `OpenAILLMAdapter` in the catalog) but no Bodai call site consumes it.

### 4.2 The dead-flag bug

`settings/mahavishnu.yaml:55-71` is a fully-commented-out tutorial block. The live override at `settings/mahavishnu.yaml:90-92` sets only `route_qwen_code: true` + `ssl_show_warn: true` — `enabled` inherits the Pydantic default of `False`. `mahavishnu/terminal/manager.py:56-57` short-circuits on `not bifrost.enabled`, so the per-worker flag is never consulted. Verified at runtime:

```
$ .venv/bin/python -c "from mahavishnu.core.config import get_settings; print(get_settings().bifrost.enabled)"
False
```

The new router's `resolve(provider) -> str | None` returns `None` when `enabled: False`, which means *no consumer can produce inert wiring* — the conditional either resolves to a real URL or `None`, never to a flag that's set but unreachable. The Phase 4 test (`mahavishnu/tests/unit/terminal/test_manager.py::test_resolve_worker_env_dead_flag`) is the structural regression test that catches this specific bug shape (not just `resolve_base_url` returning `None`, but the env-injection function returning `{}` when enabled is False).

### 4.3 Two parallel Bifrost integrations in the fleet

- **Mahavishnu's**: `BifrostConfig` pydantic model (`mahavishnu/core/config.py:855-947`) + `_resolve_bifrost_base_url` helper (`mahavishnu/engines/agno_adapter_impl.py:334-378`) + `_resolve_worker_env` env injection (`mahavishnu/terminal/manager.py:32-68`) + `ProtocolFamily` enum (`mahavishnu/llm_gateway/client.py:17`).
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

### 4.6 SSRF threat model (new in 2026-10-18 rewrite)

`BifrostConfig.base_url` and `BifrostConfig.anthropic_base_url` are currently `str` fields. A misconfigured or malicious env-var override can point the gateway URL at an attacker-controlled server. Risks:

1. **Credential exfiltration**: the Anthropic / OpenAI / minimax API key is sent to the configured URL on every call. An attacker URL exfiltrates the key.
2. **Prompt exfiltration**: every prompt (including system prompts) is sent to the configured URL. An attacker URL captures all prompt content.
3. **SSRF pivot**: the oneiric adapter is loaded by every Bodai service. A misconfigured URL means the misconfigured service can be tricked into reaching attacker-chosen internal services (e.g., `http://169.254.169.254` AWS instance metadata).

**Defense (mandatory in Phase 1)**:

- All `base_url`-style fields in `BifrostLLMSettings` are Pydantic `HttpUrl` (not `str`). Pydantic validates the URL syntax.
- A `Field(..., scheme_allowlist={"http", "https"})` constraint restricts to HTTP(S).
- A `_check_loopback_default` validator rejects non-loopback URLs unless the env var `BIFROST_ALLOW_REMOTE=1` is set. Default: loopback-only.
- The `BIFROST_ALLOW_REMOTE=1` opt-in is logged at INFO with the operator identity (per `feedback-format-migration-lazy-dual-write.md`).

This is documented in the threat model but is *not* a setting the operator can disable in code — the loopback default is hard-coded in Pydantic. The operator can opt in to non-loopback by exporting the env var; the call to `BifrostLLMSettings()` will then accept non-loopback URLs.

### 4.7 Design choice: URL-rewriter vs chain-member (5-agent review)

Two design options for the new router:

- **URL-rewriter (chosen)**: the router returns a URL; the consumer hands the URL to its existing transport. The chain's `fallback_chain = ["minimax", "llama_server"]` is unchanged. Bifrost is *invisible* to the chain.
- **Chain-member (rejected)**: the router exposes `to_provider_config() -> ProviderConfig | None`; the chain is rebuilt with the router as a tier. The 6 existing `FallbackChain` call sites are migrated to consult the new tier.

5-agent review (3-2 vote for chain-member but rejected on technical grounds):

- **For chain-member (3)**: architecture-council, pr-review-toolkit:type-design-analyzer, api-security-specialist. The chain-member design centralizes trust in the chain — one place to set the URL, no per-site spoofing.
- **For URL-rewriter (2)**: general-purpose, oneiric-specialist. The decisive argument from oneiric-specialist: **Bifrost is a transparent proxy; putting it in the chain would compound retry/circuit-breaker logic**. If `fallback_chain = ["bifrost", "minimax", "llama_server"]` and the openai call fails, the chain attributes the failure to the `bifrost` tier and opens a circuit breaker against Bifrost — but the actual upstream is openai. The chain's retry/circuit-breaker credit would be on the wrong tier. With URL-rewriter, the openai call is the openai call; when it fails, the chain attributes the failure to the openai tier, which is correct.

**Chosen: URL-rewriter**, with the chain-member's centralization guarantee recovered by the `get_router()` singleton (§2 goal 3) and the audit script in Phase 8. Every consumer calls `get_router().resolve(LLMProvider.ANTHROPIC)`; config drift is impossible.

### 4.8 The `BifrostLLMRouter` does not subclass `LLMBase` (oneiric specialist finding)

`oneiric/adapters/llm/llm_interface.py:140-375` defines `LLMBase(ABC)` with 8 abstract methods:

1. `init` (line 156)
2. `health` (line 159)
3. `cleanup` (line 162)
4. `_ensure_client` (line 285)
5. `_chat` (line 288)
6. `_chat_stream` (line 299)
7. `_get_model_info` (line 371)
8. `_list_models` (line 375)

A URL resolver has no client, no chat, no model list. Forcing it into the `LLMBase` shape would mean implementing-theater — the methods would never run. The new class is **standalone** with a single concrete method (`resolve`), a class-level `metadata`, and a `get_router()` singleton factory.

`LLMBaseSettings` at line 106-137 has `env_prefix="LLM_"` baked in. The new `BifrostLLMSettings(LLMBaseSettings)` overrides `env_prefix` to `ONEIRIC_BIFROST_` and adds a back-compat reader for the legacy `MAHAVISHNU_BIFROST__*` prefix (see REQ-BIFROST-013).

## 4.9 Requirements (testable contracts)

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

  - id: REQ-BIFROST-003
    title: "Dead-flag regression test: per-worker opt-ins inert when enabled=False"
    criteria:
      given: `BifrostLLMSettings(enabled=False, routes={RouteKind.CLAUDE_CODE, RouteKind.QWEN_CODE})`
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
    title: "mahavishnu Agno adapter calls oneiric BifrostLLMRouter (replaces _resolve_bifrost_base_url)"
    criteria:
      given: `MAHAVISHNU_BIFROST__ENABLED=true`
      when: `LLMProviderFactory.from_settings()._create_openai_model("gpt-4o")` runs
      then: `model.client.base_url` is the oneiric-resolved gateway URL
      evidence: `mahavishnu/tests/unit/engines/test_agno_adapter.py::test_openai_model_uses_router`

  - id: REQ-BIFROST-006
    title: "mahavishnu terminal worker env injection reads URL from oneiric"
    criteria:
      given: `MAHAVISHNU_BIFROST__ENABLED=true, MAHAVISHNU_BIFROST__ROUTES={CLAUDE_CODE}`
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
      then: `enabled=True` and a single `DeprecationWarning` is logged with operator identity
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
    title: "PiPool env-allowlist regression test"
    criteria:
      given: `mahavishnu/pools/pi_pool.py` `_env_allowlist` regex
      when: a test greps the allowlist for `MAHAVISHNU_BIFROST__` (anywhere)
      then: no match — the allowlist explicitly drops `MAHAVISHNU_*` and `MINIMAX_*`
      evidence: `mahavishnu/tests/unit/pools/test_pi_pool.py::test_env_allowlist_excludes_bifrost`

  - id: REQ-BIFROST-015
    title: "BifrostLLMRouter is NOT a subclass of LLMBase"
    criteria:
      given: the new class `BifrostLLMRouter`
      when: `issubclass(BifrostLLMRouter, LLMBase)` runs
      then: False
      evidence: `oneiric/tests/adapters/llm/test_bifrost.py::test_router_not_subclass_of_llmbase`

  - id: REQ-BIFROST-016
    title: "SSRF defense: Pydantic HttpUrl + loopback-only default"
    criteria:
      given: `BifrostLLMSettings()` with no env-var override
      when: the validator runs
      then: every URL field is a `HttpUrl` with scheme in `{http, https}` AND either (a) the host is loopback, or (b) `BIFROST_ALLOW_REMOTE=1` is set in the environment
      evidence: `oneiric/tests/adapters/llm/test_bifrost_ssrf.py::test_default_loopback_only`
      and: `oneiric/tests/adapters/llm/test_bifrost_ssrf.py::test_allow_remote_opt_in`

  - id: REQ-BIFROST-017
    title: "auth_env excluded from /health.bifrost.config dump"
    criteria:
      given: `BifrostLLMSettings(auth_env="MAHAVISHNU_BIFROST_AUTH_TOKEN")`
      when: `settings.model_dump()` is called for the /health.bifrost.config probe
      then: the result does NOT contain the value of `auth_env` (only the field name is OK; the value must be redacted)
      evidence: `oneiric/tests/adapters/llm/test_bifrost_health.py::test_auth_env_excluded`

  - id: REQ-BIFROST-018
    title: "Phase 0 verification: oneiric LLM adapter infrastructure works before Phase 1"
    criteria:
      given: a fresh oneiric install
      when: `oneiric_report_runtime(adapter="anthropic")` MCP tool is called
      then: returns a non-empty `cycles_total` for `AnthropicLLM` (proves the catalog is healthy)
      evidence: Phase 0 verification script output
```

## 5. Implementation Phases

Each phase is one squash-merge to local `main` per the trunk-based agent-review workflow. Per `bodai-pre-1.0-merge-policy.md`, no PRs; per `feedback-no-claude-code-coauthor-attribution.md`, no `Co-Authored-By` trailer. Push is user-controlled.

### Phase 0: Verify oneiric LLM adapter infrastructure (gate, oneiric repo)

**Goal**: Before adding a new adapter, confirm the existing catalog is healthy. The plan's §4.1 says "Zero call sites use oneiric LLM adapters today" — but the *infrastructure* (registration, lifecycle, health probe) must work. This phase is a gate; if it fails, the plan is blocked.

**Tasks**:
- `oneiric/tests/adapters/llm/test_infrastructure_health.py` (new): confirms `AnthropicLLM.metadata`, `OpenAILLMAdapter.metadata`, and the `builtin_adapter_metadata()` list all load without error.
- Run `oneiric_report_runtime(adapter="anthropic")` via the Akosha MCP — confirm `cycles_total >= 1` after a one-shot init. If zero, the new `BifrostLLMRouter` will inherit the same broken-on-arrival pathology.
- Confirm `oneiric/adapters/bootstrap.py:37` eager import works in a clean venv (no `ImportError` from the new transitive dependencies).

**No new code** — only verification. If verification fails, escalate to a oneiric substrate fix plan before Phase 1.

#### Integration Contract (Phase 0)

- **Triggered from**: `oneiric_report_runtime` MCP tool, called by Phase 0's verification script.
- **Returns to / updates**: a pass/fail gate result. No persistent state.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/oneiric
  .venv/bin/python -c "from oneiric.adapters.bootstrap import builtin_adapter_metadata; print(len(builtin_adapter_metadata()))"
  # Prints a non-zero number (currently ~57).

  mcp__akosha__search_all_systems(query="oneiric_report_runtime anthropic cycles_total")
  # Reports cycles_total for AnthropicLLM.
  ```
- **Rollback signal**: Phase 0 fails → Phase 1 is blocked; the plan is updated to address the underlying infrastructure issue first.
- **Observability added**: none (this is a verification phase, not a feature).

### Phase 1: `oneiric.adapters.llm.bifrost.BifrostLLMRouter` (additive, oneiric repo)

**Goal**: Land the new router in oneiric. No existing call site is touched; this is pure addition.

**Tasks**:
- `oneiric/adapters/llm/bifrost.py` (new):
  - `class RouteKind(StrEnum)`: `CLAUDE_CODE = "claude_code"`, `QWEN_CODE = "qwen_code"`. Replaces the separate `route_claude_code` / `route_qwen_code` boolean fields.
  - `class BifrostLLMSettings(LLMBaseSettings)`:
    - `model_config = SettingsConfigDict(env_prefix="ONEIRIC_BIFROST_", env_nested_delimiter="__", extra="allow", populate_by_name=True)` — **overrides** the inherited `LLM_` prefix from `LLMBaseSettings`.
    - `enabled: bool = Field(default=False)` — defaults to off; operator opts in.
    - `base_url: HttpUrl = Field(default=HttpUrl("http://127.0.0.1:8471"))` — `HttpUrl` not `str`. Default is loopback.
    - `anthropic_base_url: HttpUrl = Field(default=HttpUrl("http://127.0.0.1:8471/anthropic"))`
    - `routes: set[RouteKind] = Field(default_factory=set)` — combined `route_claude_code` + `route_qwen_code`.
    - `qwen_env_var: str = Field(default="OPENAI_BASE_URL")` — keeps the per-worker env-var customization.
    - `caller_id: str = Field(default="")` — kept for log/audit purposes.
    - **No** `auth_env`, `cache_mode`, `cache_ttl_seconds`, `request_timeout_seconds`, `local_provider_*` fields — those were dead in the current schema.
    - Custom validator `_check_loopback_default`: rejects non-loopback URLs unless `BIFROST_ALLOW_REMOTE=1` is set in the environment. (REQ-BIFROST-016.)
    - Custom validator `_load_legacy_env`: reads `MAHAVISHNU_BIFROST__*` env vars and applies them if the new `ONEIRIC_BIFROST__*` var is unset. Emits one `DeprecationWarning` per process that includes the operator identity (`getpass.getuser()`, hostname). (REQ-BIFROST-013.)
    - Custom `model_dump` override: excludes `auth_env`-equivalent fields even if added later. (REQ-BIFROST-017.)
  - `class BifrostLLMRouter`:
    - `metadata = AdapterMetadata(category="llm", provider="bifrost", factory="oneiric.adapters.llm.bifrost:BifrostLLMRouter", description="Bifrost gateway URL resolver for OpenAI-compatible and Anthropic-compatible routing", capabilities=["routing"], stack_level=14, priority=450, source=CandidateSource.LOCAL_PKG, owner="AI Platform", requires_secrets=False, settings_model=BifrostLLMSettings)` — matches the `AnthropicLLM.metadata` shape (REQ-BIFROST-019).
    - `def resolve(self, provider: LLMProvider) -> str | None`:
      - Returns `None` when `self._settings.enabled is False` (REQ-BIFROST-002).
      - Returns `None` when the per-provider route is not in `self._settings.routes` (e.g., `provider == LLMProvider.ANTHROPIC` requires `RouteKind.CLAUDE_CODE in routes`).
      - Returns `self._settings.base_url` (or `anthropic_base_url` for Anthropic) as a `str` (not `HttpUrl`, since downstream SDKs expect strings).
    - **Standalone class — does NOT subclass `LLMBase`.** (REQ-BIFROST-015.)
  - Module-level `def get_router() -> BifrostLLMRouter`: returns a process-cached singleton. Tests monkeypatch this seam by patching the module attribute. Pattern: `_ROUTER_SINGLETON: BifrostLLMRouter | None = None; def get_router(): global _ROUTER_SINGLETON; if _ROUTER_SINGLETON is None: _ROUTER_SINGLETON = BifrostLLMRouter(); return _ROUTER_SINGLETON`.
- `oneiric/adapters/bootstrap.py`: **lazy register** — do NOT add `BifrostLLMRouter` to the eager `from .llm import ...` line (line 37). Instead, add a function `register_bifrost_router(resolver: Resolver) -> None` that the catalog's `register_builtin_adapters` calls after the eager module load. (REQ-BIFROST-018.) Pattern:
  ```python
  # in oneiric/adapters/bootstrap.py
  def register_builtin_adapters(resolver: Resolver) -> None:
      adapters = builtin_adapter_metadata()
      # ... existing call ...
      from .llm.bifrost import BifrostLLMRouter  # lazy import
      register_adapter_metadata(resolver, package_name="oneiric.adapters.llm.bifrost", package_path=..., adapters=[BifrostLLMRouter.metadata])
  ```
- `oneiric/adapters/llm/__init__.py`: re-export `BifrostLLMRouter`, `BifrostLLMSettings`, `RouteKind`, `get_router`.
- `oneiric/tests/adapters/llm/test_bifrost.py` (new): unit tests for the contract — REQ-BIFROST-001, REQ-BIFROST-002, REQ-BIFROST-015.
- `oneiric/tests/adapters/llm/test_bifrost_dead_flag.py` (new): REQ-BIFROST-002's disabled-returns-None assertion (the structural regression test that catches the original 2026-10-17 bug shape).
- `oneiric/tests/adapters/llm/test_bifrost_ssrf.py` (new): REQ-BIFROST-016 — Pydantic HttpUrl + loopback default + `BIFROST_ALLOW_REMOTE=1` opt-in.
- `oneiric/tests/adapters/llm/test_bifrost_env_compat.py` (new): REQ-BIFROST-011 — `MAHAVISHNU_BIFROST__*` back-compat shim.
- `oneiric/tests/adapters/llm/test_bifrost_health.py` (new): REQ-BIFROST-017 — `auth_env`-equivalent exclusion in `model_dump`.

#### Integration Contract (Phase 1)

- **Triggered from**: `oneiric.adapters.bootstrap.register_builtin_adapters()` runs lazily (on first `Resolver()` call) instead of at module import. The new router is registered as a side effect of the first `get_router()` call.
- **Returns to / updates**: `oneiric.adapters.registry` (the in-memory catalog). Queryable via `oneiric.adapters.llm.bifrost.get_router().resolve(LLMProvider.ANTHROPIC)`.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/oneiric
  .venv/bin/python -c "from oneiric.adapters.llm.bifrost import get_router, RouteKind; import os; os.environ['ONEIRIC_BIFROST__ENABLED'] = 'true'; os.environ['ONEIRIC_BIFROST__ROUTES'] = 'claude_code'; print(get_router().resolve(__import__('oneiric.adapters.llm.llm_interface', fromlist=['LLMProvider']).LLMProvider.ANTHROPIC))"
  # Returns 'http://127.0.0.1:8471/anthropic' (or None if env not set).
  ```
- **Rollback signal**: `BifrostLLMRouter` not found in `oneiric_report_runtime` MCP output. The new router's `cycles_total` counter (incremented per `resolve` call) is 0 after 1 hour of fleet operation.
- **Observability added**: existing OTel counter `oneiric.adapter.lookup{adapter="bifrost"}` (incremented per resolution attempt) + structured log line `adapter.bifrost.resolved provider=openai resolved=true|false url=<redacted>`.

### Phase 2: mahavishnu Agno + CloudWorker + probe migration (3 call sites in one PR)

**Goal**: Three mahavishnu call sites that are Bifrost-aware today stop inlining routing logic and call oneiric instead.

**Tasks**:
- `mahavishnu/engines/agno_adapter_impl.py:198-332`: replace the 4 `_create_*_model` factory methods' use of `_resolve_bifrost_base_url` with `from oneiric.adapters.llm.bifrost import get_router; get_router().resolve(LLMProvider.OPENAI)` (or `LLMProvider.ANTHROPIC` for the Claude factory). Delete the local `_resolve_bifrost_base_url` helper (lines 334-378).
- `mahavishnu/llm_gateway/client.py`: delete the `ProtocolFamily` enum and the `gateway_api_base` function. Both are no longer used after this phase.
- `mahavishnu/workers/cloud_worker.py:73-101`: `_build_fallback_chain` reads `minimax_url` from `get_router().resolve(LLMProvider.OPENAI)` and `llama_server_url` from a local config (Bifrost is OpenAI/Anthropic only). Pass to `mcp_common.llm.OpenAICompatibleProvider` (no change to the chain).
- `mahavishnu/workers/capabilities/_probes.py:132-156`: `resolve_probe_endpoint` calls `get_router().resolve(LLMProvider.OPENAI)` for `provider == "minimax"`.
- Tests:
  - `tests/unit/engines/test_agno_adapter.py::test_openai_model_uses_router`: factory tests now stub `oneiric.adapters.llm.bifrost.get_router` instead of the local helper. (REQ-BIFROST-005.)
  - `tests/unit/workers/test_cloud_worker.py::test_chain_uses_router`: chain-builder test asserts the URLs come from oneiric. (REQ-BIFROST-008.)
  - `tests/unit/workers/capabilities/test__probes.py::test_probe_uses_router`: probe resolver test asserts the gateway URL is used when `enabled: True` and the direct URL when `enabled: False`. (REQ-BIFROST-007.)

#### Integration Contract (Phase 2)

- **Triggered from**: any code path that constructs an Agno model, builds a `CloudWorker`, or resolves a `minimax` capability probe.
- **Returns to / updates**: the constructed `OpenAIChat` / `Claude` / `FallbackChain` instances carry the oneiric-resolved `base_url`. No persistent state change.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/mahavishnu
  ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_code .venv/bin/python -c "
  from mahavishnu.engines.agno_adapter_impl import LLMProviderFactory
  m = LLMProviderFactory.from_settings()
  print(m._create_anthropic_model('claude-sonnet-4-20250514').client.base_url)
  # Prints 'http://127.0.0.1:8471/anthropic' (the oneiric-resolved URL).
  "
  ```
- **Rollback signal**: Agno factory raises `LLMGatewayUnavailableError` (or similar) on first model construction. CloudWorker raises on first `execute()`. Probe resolution returns `None` in `/health.bifrost.reachable`.
- **Observability added**: OTel counter `mahavishnu.llm.bifrost_resolved{provider, site, resolved}` + log line `llm.bifrost.resolved site=agno provider=openai url=<redacted>`.

### Phase 3: mahavishnu terminal worker env injection

**Goal**: `mahavishnu/terminal/manager.py:_resolve_worker_env` reads the base URL from oneiric instead of the `BifrostConfig` pydantic model. **The `bifrost: BifrostConfig | None` parameter is dropped** (caller-spoofable, see REQ-BIFROST-004). The router is constructed inside the function via `get_router()`.

**Tasks**:
- `mahavishnu/terminal/manager.py:32-68`: change the signature to `_resolve_worker_env(worker_type: str) -> dict[str, str]`. Inside, call `from oneiric.adapters.llm.bifrost import get_router; router = get_router()`. The function consults `router._settings.enabled` and `router._settings.routes` directly.
  - **Dead-flag regression test (REQ-BIFROST-003)**: when `enabled=False`, return `{}` regardless of `routes` or `worker_type`.
  - **Signature test (REQ-BIFROST-004)**: `_resolve_worker_env(worker_type, bifrost=...)` raises `TypeError` — the parameter is gone.
- `mahavishnu/terminal/manager.py:18`: drop the `from mahavishnu.llm_gateway.client import ProtocolFamily, gateway_api_base` import. The new function does not use either.
- Tests:
  - `tests/unit/terminal/test_manager.py::test_resolve_worker_env_dead_flag`: REQ-BIFROST-003.
  - `tests/unit/terminal/test_manager.py::test_signature_has_no_bifrost`: REQ-BIFROST-004.
  - `tests/unit/terminal/test_manager.py::test_env_inject_claude`: REQ-BIFROST-006.
  - `tests/unit/pools/test_pi_pool.py::test_env_allowlist_excludes_bifrost`: REQ-BIFROST-014 — grep test that fails if a future contributor adds `MAHAVISHNU_BIFROST__` to PiPool's allowlist.

#### Integration Contract (Phase 3)

- **Triggered from**: `mahavishnu.terminal.manager._resolve_worker_env(worker_type, ...)` is called by the worker spawn path. The signature is now `(worker_type: str) -> dict[str, str]` — the `bifrost` parameter is gone. Today it's called from `WorkerManager.create_session()`.
- **Returns to / updates**: the dict of env vars injected into the tmux session at spawn. No persistent state.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/mahavishnu
  ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_code .venv/bin/python -c "
  from mahavishnu.terminal.manager import _resolve_worker_env
  print(_resolve_worker_env('terminal-claude'))
  # Prints {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8471/anthropic'}.
  "
  ```
- **Rollback signal**: terminal worker spawn fails with `RuntimeError: spawn failed: env injection returned empty dict for terminal-claude with bifrost.routes=claude_code`.
- **Observability added**: log line `terminal.bifrost.env_inject worker_type=<t> injected_keys=[...] url=<redacted>`.

### Phase 4: session-buddy BifrostClient → oneiric

**Goal**: The hand-rolled `BifrostClient` at `session_buddy/bifrost_client.py:32-107` is deleted. All session-buddy call sites resolve their URL through oneiric.

**Tasks**:
- `session_buddy/bifrost_client.py`: delete the file. Re-exports in `session_buddy/__init__.py` (if any) updated.
- `session_buddy/worker.py:14, 96`: replace `BifrostClient` import with `from oneiric.adapters.llm.bifrost import get_router`.
- `session_buddy/memory/entity_extractor.py:132-148`: replace the `BIFROST_OPENAI_BASE_URL` env-var read with `get_router().resolve(LLMProvider.OPENAI)`. The `bifrost_openai_base` field stays as a config override for non-Bifrost deployments.
- `session_buddy/llm_providers.py:383-431, 510-519`: `OpenAIProvider` and `AnthropicProvider` config accept an optional `base_url` (already do); the `_get_provider_api_key_and_env` helper stays for the env-var API-key reads. The `LLMManager` calls `get_router()` for URL resolution.
- Tests:
  - `session_buddy/tests/unit/test_llm_providers.py::test_manager_uses_router`: provider tests now use oneiric-mocked URLs. (REQ-BIFROST-009.)

#### Integration Contract (Phase 4)

- **Triggered from**: `session_buddy.llm_providers.LLMManager.__init__` and any direct `BifrostClient` instantiation in `session_buddy/worker.py`.
- **Returns to / updates**: the constructed `OpenAI` / `AsyncOpenAI` / `Anthropic` clients carry the oneiric-resolved `base_url`.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/session-buddy
  ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=openai,claude_code .venv/bin/python -c "
  from session_buddy.llm_providers import LLMManager
  m = LLMManager()
  print([p.base_url for p in m._chain._providers])
  # Prints the gateway URLs.
  "
  ```
- **Rollback signal**: `LLMManager.__init__` raises on first instantiation. Existing `BifrostClient` callers crash with `ImportError` (the file is deleted — the failure is loud).
- **Observability added**: log line `llm.bifrost.session_buddy_resolved provider=openai url=<redacted>`.

### Phase 5: crackerjack FallbackChainCodeFixer → oneiric

**Goal**: `crackerjack/adapters/ai/unified.py:19-72` uses oneiric for URL resolution.

**Tasks**:
- `crackerjack/adapters/ai/unified.py:19-72`: `_build_llm_settings` reads provider URLs from `get_router().resolve(LLMProvider.OPENAI)` (or whatever provider the chain member is for).
- `crackerjack/adapters/ai/registry.py:9-12, 29-57`: `ProviderID` enum stays; `PROVIDER_INFO["minimax"]` carries an `uses_bifrost: bool` flag (default false) so the registry reports which providers go through the gateway.
- Tests:
  - `crackerjack/tests/adapters/test_ai_registry.py::test_uses_bifrost_field`: registry tests cover the new `uses_bifrost` field.
  - `crackerjack/tests/adapters/test_provider_chain.py::test_chain_uses_router`: chain-builder test asserts the URLs come from oneiric. (REQ-BIFROST-010.)

#### Integration Contract (Phase 5)

- **Triggered from**: `crackerjack.adapters.ai.unified.FallbackChainCodeFixer.__init__`.
- **Returns to / updates**: the constructed `FallbackChain` carries oneiric-resolved URLs.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/crackerjack
  ONEIRIC_BIFROST__ENABLED=true .venv/bin/python -c "
  from crackerjack.adapters.ai.unified import FallbackChainCodeFixer
  fc = FallbackChainCodeFixer()
  print([p.base_url for p in fc._chain._providers])
  "
  ```
- **Rollback signal**: `FallbackChainCodeFixer.__init__` raises on first instantiation.
- **Observability added**: log line `crackerjack.bifrost.resolved provider=minimax url=<redacted>`.

### Phase 6: Pydantic-AI audit + (conditional) oneiric migration

**Goal**: Audit whether `mahavishnu/adapters/ai/pydantic_ai_adapter.py:86, 99, 258` makes independent LLM calls that bypass oneiric.

**Tasks**:
- **Audit** (mandatory): grep all `provider_prefixes`, `httpx` `base_url=`, and direct SDK instantiations in pydantic-ai adapter. Produce a per-call-site migration decision (oneiric vs leave).
- **Conditional migration** (if audit surfaces bypasses): migrate the bypassing call sites to `get_router()`. If audit shows all paths go through the Agno factory or CloudWorker, Phase 6 is a no-op and the result is a one-line audit note in the PR description.

#### Integration Contract (Phase 6)

- **Triggered from**: pydantic-ai adapter instantiation.
- **Returns to / updates**: the constructed `pydantic_ai.Agent` (or equivalent) carries the oneiric-resolved `base_url`.
- **Demonstrable by**: pydantic-ai adapter test asserts the URL came from oneiric (if migration was needed); otherwise the audit doc is the deliverable.
- **Rollback signal**: pydantic-ai agent construction fails.
- **Observability added**: log line `pydantic_ai.bifrost.resolved provider=openai url=<redacted>` (only if migration happened).

### Phase 7: Mahavishnu BifrostConfig + ProtocolFamily deletion

**Goal**: The orphaned `BifrostConfig` pydantic model in `mahavishnu/core/config.py:855-947` AND the `ProtocolFamily` enum + `gateway_api_base` function in `mahavishnu/llm_gateway/client.py` are deleted. The oneiric router is the sole owner of both.

**Tasks**:
- `mahavishnu/core/config.py:855-947`: delete `BifrostConfig` class.
- `mahavishnu/llm_gateway/client.py`: delete the entire file. All consumers are migrated in Phases 2 and 3.
- `mahavishnu/health.py:178, 457, 494`: rewrite the `/health.bifrost.config` probe to query the oneiric router (e.g., `get_router()._settings.model_dump(exclude={"auth_env"})`).
- `mahavishnu/cli/config_validator.py:508, 521`: same.
- `mahavishnu/observability/prometheus_metrics.py:371, 376`: read the bifrost local provider URL from oneiric.
- `mahavishnu/core/health.py:1303-1337`: same.
- `mahavishnu/observability/prometheus_metrics.py:161-381`: same.
- `mahavishnu/scripts/bifrost-gateway.py`: unchanged (it's the runtime gateway, not the schema).
- `mahavishnu/scripts/audit_bifrost_grep.py`: unchanged (it lints for `BIFROST_BASE_URL` env var usage, still relevant).
- **Phase 7 integration test import break**: `mahavishnu/tests/integration/test_bifrost_local_provider_e2e.py:22` imports `BifrostConfig`. When Phase 7 deletes the model, that import breaks. Update the test to import from oneiric. (REQ-BIFROST-021.)
- Tests:
  - `tests/unit/test_config.py::test_bifrost_config_removed`: assert `BifrostConfig` is no longer importable from `mahavishnu.core.config`. (REQ-BIFROST-012.)
  - `tests/unit/test_health_bifrost.py::test_auth_env_excluded`: assert `/health.bifrost.config` returns the oneiric-derived values without `auth_env` (REQ-BIFROST-017).
  - `tests/integration/test_bifrost_local_provider_e2e.py`: imports updated to oneiric.

#### Integration Contract (Phase 7)

- **Triggered from**: `mahavishnu health` CLI, `mahavishnu config validate`, and the `/health` HTTP route.
- **Returns to / updates**: `/health.bifrost.config` JSON output. Backward compat: same field names, same env-var override pattern (`MAHAVISHNU_BIFROST__*` via the oneiric shim).
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/mahavishnu
  .venv/bin/python -c "from mahavishnu.core.config import BifrostConfig"
  # ModuleNotFoundError — the class moved to oneiric.

  .venv/bin/python -c "from mahavishnu.llm_gateway.client import ProtocolFamily"
  # ModuleNotFoundError — the enum moved to oneiric (replaced by LLMProvider).

  MAHAVISHNU_BIFROST__ENABLED=true .venv/bin/python -m mahavishnu health
  # /health.bifrost.config now shows the oneiric-resolved values.
  ```
- **Rollback signal**: `/health` returns 503 with `bifrost.config_unreachable: true` (config probe fails).
- **Observability added**: OTel counter `mahavishnu.bifrost.config_probed{resolved=true|false}` + log line `bifrost.config.probed source=oneiric`.

### Phase 8: End-to-end migration verification

**Goal**: Confirm every surviving LLM call site in the Bodai fleet resolves through oneiric (REQ-BIFROST-013).

**Tasks**:
- `scripts/audit_bifrost_callers.py` (new, runs from mahavishnu): a one-shot audit script that walks the 4 in-scope repos and asserts that any `base_url=...` argument to an LLM client construction is either (a) sourced from oneiric via `get_router().resolve(...)` (or imported from oneiric), or (b) a hardcoded local URL (e.g. `http://localhost:8081`) on the `LOCAL_PROVIDER_ALLOWLIST`. Direct base URLs not in either set fail the audit.
- `docs/llm-routing.md` (new): a one-page reference that documents the oneiric ownership and lists the call sites + their routing source.
- `docs/plans/PLAN_INDEX.md`: move this plan from `draft` to `complete` (regenerated by `scripts/regenerate_plan_index.py`).

#### Integration Contract (Phase 8)

- **Triggered from**: `scripts/audit_bifrost_callers.py` runs in CI per `crackerjack run -v -f`'s `fast_hooks` phase.
- **Returns to / updates**: CI pass/fail status. No persistent state.
- **Demonstrable by**:
  ```bash
  python scripts/audit_bifrost_callers.py
  # Exits 0 if all 24 call sites resolve through oneiric or are local-allowlisted.
  ```
- **Rollback signal**: CI fails on the audit step.
- **Observability added**: GitHub Action summary panel + per-repo audit log line `audit.bifrost_caller site=<file:line> source=oneiric|local-allowlist|FAIL`.

## 6. Required Code Changes

### oneiric (Phases 0, 1)

- [ ] `oneiric/tests/adapters/llm/test_infrastructure_health.py` (new — REQ-BIFROST-018 Phase 0 gate)
- [ ] `oneiric/adapters/llm/bifrost.py` (new — `BifrostLLMSettings`, `BifrostLLMRouter`, `RouteKind`, `get_router`)
- [ ] `oneiric/adapters/llm/__init__.py` (re-export)
- [ ] `oneiric/adapters/bootstrap.py` (lazy register `BifrostLLMRouter.metadata`)
- [ ] `oneiric/tests/adapters/llm/test_bifrost.py` (new)
- [ ] `oneiric/tests/adapters/llm/test_bifrost_dead_flag.py` (new — REQ-BIFROST-002 regression)
- [ ] `oneiric/tests/adapters/llm/test_bifrost_ssrf.py` (new — REQ-BIFROST-016)
- [ ] `oneiric/tests/adapters/llm/test_bifrost_env_compat.py` (new — REQ-BIFROST-011)
- [ ] `oneiric/tests/adapters/llm/test_bifrost_health.py` (new — REQ-BIFROST-017)

### mahavishnu (Phases 2, 3, 7)

- [ ] `mahavishnu/engines/agno_adapter_impl.py` (Phase 2 — REQ-BIFROST-005)
- [ ] `mahavishnu/workers/cloud_worker.py` (Phase 2 — REQ-BIFROST-008)
- [ ] `mahavishnu/workers/capabilities/_probes.py` (Phase 2 — REQ-BIFROST-007)
- [ ] `mahavishnu/terminal/manager.py` (Phase 3 — REQ-BIFROST-006, REQ-BIFROST-003, REQ-BIFROST-004)
- [ ] `mahavishnu/llm_gateway/client.py` (Phase 2 + Phase 7 — delete `ProtocolFamily`, `gateway_api_base`, and the file itself)
- [ ] `mahavishnu/core/config.py` (Phase 7 — REQ-BIFROST-012, delete `BifrostConfig`)
- [ ] `mahavishnu/health.py` (Phase 7)
- [ ] `mahavishnu/cli/config_validator.py` (Phase 7)
- [ ] `mahavishnu/observability/prometheus_metrics.py` (Phase 7)
- [ ] `mahavishnu/core/health.py:1303-1337` (Phase 7)
- [ ] `mahavishnu/tests/integration/test_bifrost_local_provider_e2e.py:22` (Phase 7 — REQ-BIFROST-021, update imports)
- [ ] `tests/unit/engines/test_agno_adapter.py` (Phase 2 — REQ-BIFROST-005)
- [ ] `tests/unit/workers/test_cloud_worker.py` (Phase 2 — REQ-BIFROST-008)
- [ ] `tests/unit/workers/capabilities/test__probes.py` (Phase 2 — REQ-BIFROST-007)
- [ ] `tests/unit/terminal/test_manager.py` (Phase 3 — REQ-BIFROST-003, REQ-BIFROST-004, REQ-BIFROST-006)
- [ ] `tests/unit/pools/test_pi_pool.py` (Phase 3 — REQ-BIFROST-014)
- [ ] `tests/unit/test_config.py` (Phase 7 — REQ-BIFROST-012)
- [ ] `tests/unit/test_health_bifrost.py` (Phase 7 — REQ-BIFROST-017)

### session-buddy (Phase 4)

- [ ] `session_buddy/bifrost_client.py` (delete)
- [ ] `session_buddy/worker.py` (Phase 4 — REQ-BIFROST-009)
- [ ] `session_buddy/memory/entity_extractor.py` (Phase 4 — REQ-BIFROST-009)
- [ ] `session_buddy/llm_providers.py` (Phase 4)
- [ ] `session_buddy/tests/unit/test_llm_providers.py` (Phase 4 — REQ-BIFROST-009)

### crackerjack (Phase 5)

- [ ] `crackerjack/adapters/ai/unified.py` (Phase 5 — REQ-BIFROST-010)
- [ ] `crackerjack/adapters/ai/registry.py` (Phase 5 — `uses_bifrost` field)
- [ ] `crackerjack/tests/adapters/test_ai_registry.py` (Phase 5)
- [ ] `crackerjack/tests/adapters/test_provider_chain.py` (Phase 5 — REQ-BIFROST-010)

### pydantic-ai (Phase 6 — conditional)

- [ ] `mahavishnu/adapters/ai/pydantic_ai_adapter.py` (Phase 6 — only if audit surfaces bypasses)

### cross-repo (Phase 8)

- [ ] `mahavishnu/scripts/audit_bifrost_callers.py` (new)
- [ ] `docs/llm-routing.md` (new)
- [ ] `docs/plans/PLAN_INDEX.md` (move this plan from `draft` to `complete` — regenerated by `scripts/regenerate_plan_index.py`)

## 7. Validation Matrix

The validation matrix below pins the explicit before/after signatures for each command. Stale signatures from the previous draft (`_resolve_worker_env('terminal-claude', a)`, `m._create_openai_model('gpt-4o').client.base_url`) are corrected.

| Check | Command | Expected outcome | Evidence |
|---|---|---|---|
| oneiric adapter infrastructure healthy (Phase 0) | `cd /Users/les/Projects/oneiric && .venv/bin/python -c "from oneiric.adapters.bootstrap import builtin_adapter_metadata; print(len(builtin_adapter_metadata()))"` | `>=57` | Test log |
| oneiric adapter registered (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -c "from oneiric.adapters.llm.bifrost import get_router, BifrostLLMRouter; print(BifrostLLMRouter.metadata.provider)"` | `bifrost` | Test log |
| Router is NOT LLMBase subclass (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -c "from oneiric.adapters.llm.bifrost import BifrostLLMRouter; from oneiric.adapters.llm.llm_interface import LLMBase; print(issubclass(BifrostLLMRouter, LLMBase))"` | `False` | Test log |
| Dead-flag regression — `resolve` (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost_dead_flag.py -q` | Pass | Test log |
| SSRF default (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost_ssrf.py -q` | Pass | Test log |
| env-var back-compat (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost_env_compat.py -q` | Pass | Test log |
| `/health.bifrost.config` auth_env exclusion (Phase 1) | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost_health.py -q` | Pass | Test log |
| Mahavishnu Agno routes through oneiric (Phase 2) | `cd /Users/les/Projects/mahavishnu && ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_code .venv/bin/python -c "from mahavishnu.engines.agno_adapter_impl import LLMProviderFactory; m = LLMProviderFactory.from_settings(); print(m._create_anthropic_model('claude-sonnet-4-20250514').client.base_url)"` | Gateway URL | Test log |
| Mahavishnu terminal env injection — new signature (Phase 3) | `ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_code .venv/bin/python -c "from mahavishnu.terminal.manager import _resolve_worker_env; print(_resolve_worker_env('terminal-claude'))"` | `{'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8471/anthropic'}` | Test log |
| Mahavishnu terminal dead-flag (Phase 3) | `ONEIRIC_BIFROST__ENABLED=false ONEIRIC_BIFROST__ROUTES=claude_code,qwen_code .venv/bin/python -c "from mahavishnu.terminal.manager import _resolve_worker_env; print(_resolve_worker_env('terminal-claude'))"` | `{}` | Test log |
| Mahavishnu terminal — old signature raises (Phase 3) | `.venv/bin/python -c "from mahavishnu.terminal.manager import _resolve_worker_env; _resolve_worker_env('claude', bifrost=None)"` | `TypeError: _resolve_worker_env() got an unexpected keyword argument 'bifrost'` | Test log |
| PiPool env-allowlist (Phase 3) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/unit/pools/test_pi_pool.py -q` | Pass | Test log |
| Session-buddy URLs (Phase 4) | `cd /Users/les/Projects/session-buddy && ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=openai,claude_code .venv/bin/python -c "from session_buddy.llm_providers import LLMManager; m = LLMManager(); print([p.base_url for p in m._chain._providers])"` | Gateway URLs | Test log |
| Crackerjack URLs (Phase 5) | `cd /Users/les/Projects/crackerjack && ONEIRIC_BIFROST__ENABLED=true .venv/bin/python -c "from crackerjack.adapters.ai.unified import FallbackChainCodeFixer; fc = FallbackChainCodeFixer(); print([p.base_url for p in fc._chain._providers])"` | Gateway URLs | Test log |
| `BifrostConfig` deleted from mahavishnu (Phase 7) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "from mahavishnu.core.config import BifrostConfig"` | `ModuleNotFoundError` | Test log |
| `ProtocolFamily` deleted from mahavishnu (Phase 7) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "from mahavishnu.llm_gateway.client import ProtocolFamily"` | `ModuleNotFoundError` | Test log |
| `test_bifrost_local_provider_e2e.py` imports updated (Phase 7) | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -m pytest tests/integration/test_bifrost_local_provider_e2e.py -q` | Pass | Test log |
| All call sites use oneiric (Phase 8) | `cd /Users/les/Projects/mahavishnu && python scripts/audit_bifrost_callers.py` | Exits 0 | Audit log |
| Crackerjack merge gate (each repo) | `cd <repo> && crackerjack run -v -f` | Pass | Test log |
| pytest | `pytest tests/unit -q` | Pass (modulo known pre-existing failures) | Test log |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| SSRF: misconfigured `MAHAVISHNU_BIFROST__BASE_URL` points at attacker server, exfiltrates API keys and prompts | Medium | REQ-BIFROST-016: Pydantic `HttpUrl` + loopback-only default + `BIFROST_ALLOW_REMOTE=1` opt-in (Phase 1). |
| `MAHAVISHNU_BIFROST__*` env-var prefix breaks for operators | Low | REQ-BIFROST-011: back-compat shim in `BifrostLLMSettings` reads legacy prefix and emits one `DeprecationWarning` per process with operator identity (Phase 1, not Phase 7 — closes the migration gap). |
| `auth_env` leaks through `/health.bifrost.config` after Phase 7's migration | Medium | REQ-BIFROST-017: `model_dump(exclude={"auth_env"})` pinned by a test (Phase 1, persists through Phase 7). |
| session-buddy's `BifrostClient` is consumed by external code (not in our tree) | Low | `grep -r "BifrostClient" /Users/les/Projects/` confirms no external consumers in the Bodai fleet. The session-buddy README and CHANGELOG note the class is internal. |
| The oneiric router is overkill for the LLM routing concern | Low | oneiric already has `AnthropicLLM` and `OpenAILLMAdapter` at `oneiric/adapters/llm/`. Adding `BifrostLLMRouter` follows the established pattern (lifecycle, metadata, settings model) without the transport ABC overhead. |
| The dead-flag regression test in Phase 1 isn't enough — a future contributor could bypass the router with a direct call | Low | The `audit_bifrost_callers.py` script in Phase 8 runs in CI and flags any non-allowlisted `base_url` argument. |
| The dead-flag regression test in Phase 1 covers `resolve` but not `_resolve_worker_env` | Medium | REQ-BIFROST-003: second dead-flag regression test in `mahavishnu/tests/unit/terminal/test_manager.py` (Phase 3). Both tests must pass. |
| crackerjack's `doc_update_service.py` direct Anthropic SDK call is a regression vector after the migration | Low | It's out of scope for this plan; deferred to a follow-up. The Phase 8 audit script flags it but doesn't fail the build (allowlist: "out-of-scope: deferred to follow-up"). |
| The Bifrost runtime gateway goes down mid-migration | Low | The existing `local_provider_url` field (llama-server) is the documented fallback. Phase 2's chain-builder falls through to llama-server when the gateway is unreachable. |
| oneiric's adapter bootstrap is not yet mature | Medium | Phase 0 verifies the infrastructure works before Phase 1 adds a new adapter. The router registers lazily, not at eager import time. |
| Multi-repo merge coordination cost (8 phases across 4 repos) | Medium | Per-repo merge via squash-merge. Each repo's `crackerjack run -v -f` gates its own merge. Sequence: oneiric (Phases 0-1) → mahavishnu (Phases 2-3) → session-buddy (Phase 4) → crackerjack (Phase 5) → mahavishnu (Phase 7) → cross-repo (Phase 8). |
| `test_bifrost_local_provider_e2e.py` import break in Phase 7 | Low | REQ-BIFROST-021: integration test import break is documented in Phase 7's required code changes. The fix is one import line. |
| PiPool env-allowlist boundary drift (a future contributor adds `MAHAVISHNU_BIFROST__*` to the allowlist) | Low | REQ-BIFROST-014: regression test in `mahavishnu/tests/unit/pools/test_pi_pool.py` greps the allowlist and fails the build if a future contributor adds it. |

## 9. Decision Rule

This plan is "done" when:

- A user can run `ONEIRIC_BIFROST__ENABLED=true ONEIRIC_BIFROST__ROUTES=claude_code .venv/bin/mahavishnu demo agno --prompt "..."` against the local Bifrost gateway and get a real LLM completion routed through the gateway.
- `crackerjack run -v -f` passes in every repo.
- `scripts/audit_bifrost_callers.py` exits 0 (or exits 0 with all bypasses documented in an allowlist comment).
- `/health.bifrost.config` returns the oneiric-derived values without `auth_env` leakage.
- The dead-flag regression tests in `oneiric/tests/adapters/llm/test_bifrost_dead_flag.py` AND `mahavishnu/tests/unit/terminal/test_manager.py::test_resolve_worker_env_dead_flag` both pass — and any attempt to set `routes: {claude_code, qwen_code}` while `enabled: false` produces no effect (provable by both tests).
- The `MAHAVISHNU_BIFROST__*` env-var back-compat shim works without code changes on the operator's side, and emits a one-time `DeprecationWarning` with operator identity.
- `from mahavishnu.core.config import BifrostConfig` raises `ModuleNotFoundError`.
- `from mahavishnu.llm_gateway.client import ProtocolFamily` raises `ModuleNotFoundError`.
- `issubclass(BifrostLLMRouter, LLMBase)` returns `False`.
- The plan has been promoted from `status: draft` to `status: complete` in `docs/plans/PLAN_INDEX.md` (regenerated by `scripts/regenerate_plan_index.py`).

**If scope pressure forces a cut**:

- **Drop Phase 6 (pydantic-ai audit) first.** It's conditional — if the audit shows all pydantic-ai calls go through the Agno factory or CloudWorker, Phase 6 is a one-line note. Don't let a "audit might find something" scope expand the timeline.
- **Drop Phase 7 (BifrostConfig + ProtocolFamily deletion) only as a last resort.** The orphaned models can stay as deprecated re-exports for one release cycle. But the migration is *structurally incomplete* without Phase 7 — the dead-flag fix only holds if there's no parallel config model that can independently drift.
- **Phases 0-5 are the load-bearing work.** Without Phase 0, the oneiric infrastructure may be broken. Without Phase 1, no migration is possible. Without Phases 2-5, the migration is incomplete and the dead-flag bug can re-occur.

**Post-plan discipline**:

- After all per-repo merges land on local `main`, do **NOT** run `git push origin main` — push is user-controlled per `feedback-bodai-push-is-user-controlled.md`.
- The user runs `git push` from their own shell.
- The implementer does **NOT** bump the oneiric version themselves per `feedback-mcp-common-version-bump-is-user.md`; the user runs `crackerjack run -p <level>` from their shell to bump+tag+publish when ready.
- Each per-repo commit is authored as `les@wedgwoodwebworks.com` (not `.local`) with no `Co-Authored-By` trailer per `feedback-no-claude-code-coauthor-attribution.md`.
- The new `oneiric.adapters.llm.bifrost` adapter is *additive* — no existing oneiric call site is changed. Backward compat is automatic for the four repos that don't yet import the new adapter.
- The `BIFROST_ALLOW_REMOTE=1` opt-in for non-loopback URLs is logged at INFO with the operator identity. Operators in cloud deployments must explicitly set this env var.

## 10. 5-Agent Review Synthesis (Appendix)

This plan was rewritten after a 5-agent multi-agent review (2026-10-18). The agents and their findings:

| Agent | Lens | Stance on URL-rewriter vs chain-member | Key findings contributed |
|---|---|---|---|
| architecture-council | Platform architecture | For chain-member (3) | "Chain constructor handles it; dead-flag pattern can't exist" — but recovered by `get_router()` singleton + audit script in Phase 8. |
| pr-review-toolkit:type-design-analyzer | Type design | For chain-member (3) | LLMBase subclassing is wrong (8 abstract methods, no client, no chat); rename to `BifrostLLMRouter`; env_prefix inheritance bug; rewrite REQ-NNNs as testable contracts. |
| api-security-specialist | API security | For chain-member (3) | SSRF threat model (§4.6); `auth_env` exclusion test; `BifrostLLMRouter` is caller-spoofable; Pydantic `HttpUrl` + loopback default. |
| general-purpose | Generalist | For URL-rewriter (2) | "Transparent proxy doesn't need its own class — `get_router()` is enough." |
| oneiric-specialist | Adapter registry | For URL-rewriter (2) | **Decisive argument**: Bifrost is a transparent proxy; putting it in the chain would compound retry/circuit-breaker logic. Standalone class, not LLMBase subclass. Lazy registration from bootstrap. `LLMProvider` enum reuse. |

**Final tally: 3-2 in favor of chain-member. Recommendation: stay with URL-rewriter**, because the oneiric specialist's transparent-proxy argument is the most technically concrete and the chain-member's centralization guarantee is recoverable via the `get_router()` singleton + audit script.

**All 21 findings from the review have been addressed in the rewrite**:

1. SSRF defense (REQ-BIFROST-016) — Pydantic HttpUrl + loopback-only + `BIFROST_ALLOW_REMOTE=1`
2. Drop `bifrost` parameter from `_resolve_worker_env` (REQ-BIFROST-004)
3. `auth_env` exclusion test (REQ-BIFROST-017)
4. Reuse existing `LLMProvider` enum (drop `ProtocolFamily`)
5. `env_prefix = "ONEIRIC_BIFROST_"` with `MAHAVISHNU_BIFROST__*` back-compat shim (REQ-BIFROST-011)
6. Drop dead fields (`cache_mode`, `cache_ttl_seconds`, `request_timeout_seconds`, `auth_env`, `local_provider_*`)
7. Combined `route_claude_code` + `route_qwen_code` into `set[RouteKind]`
8. Rewritten REQ-NNNs as testable contracts (given/when/then/evidence)
9. Second dead-flag regression test in `mahavishnu/tests/unit/terminal/test_manager.py` (REQ-BIFROST-003)
10. Phase 0 verification gate (REQ-BIFROST-018)
11. Fixed §7 validation commands with explicit before/after signatures
12. `DeprecationWarning` moved to Phase 1 (oneiric shim lands with the router)
13. Env-var shim in `BifrostLLMSettings` (oneiric), not per-consumer
14. SSRF threat model subsection (§4.6)
15. PiPool env-allowlist regression test (REQ-BIFROST-014)
16. Renamed `BifrostLLMAdapter` → `BifrostLLMRouter`; standalone class, no LLMBase subclass (REQ-BIFROST-015)
17. Lazy registration in `bootstrap.py` (not eager import)
18. `metadata` field shape matches `AnthropicLLM.metadata` (description, capabilities, stack_level, priority, source, owner, requires_secrets)
19. Single module name: `oneiric.adapters.llm.bifrost.get_router()` (no inconsistent `oneiric.llm_gateway.resolve(...)` references)
20. Integration test import break documented in Phase 7's required code changes (REQ-BIFROST-021)
21. `get_router()` singleton pattern (Phase 1)

## References

- `docs/plans/2026-10-16-drop-ollama-favor-llama-server.md` — the active ollama removal plan; PR #0 already landed in this repo (`77b8bed8`) and mcp-common (`dd889b4`).
- `docs/plans/2026-10-15-bifrost-gateway-wiring.md` — the existing Bifrost wiring plan (Phase D Qwen gate); the wiring this plan consolidates.
- `docs/plans/2026-10-15-oneiric-substrate-rollout.md` — the umbrella oneiric substrate plan; this plan is a slice of it (LLM routing) that doesn't conflict with settings-class or embedding-substrate work.
- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` — the v1.5 Bifrost design spec; the schema here is a superset of the spec's Phase A fields.
- `oneiric/adapters/llm/llm_interface.py:15-22` — the `LLMProvider` enum reused for router's `resolve` parameter.
- `oneiric/adapters/llm/llm_interface.py:140-375` — the `LLMBase` ABC; the new router does NOT subclass it.
- `oneiric/adapters/llm/anthropic.py:42-61` — the `AnthropicLLM.metadata` shape the new `BifrostLLMRouter.metadata` follows.
- `oneiric/adapters/bootstrap.py:37, 82-141` — the `builtin_adapter_metadata()` list; the new router registers lazily.
- `mcp_common/llm/provider.py:30-58` — the `OpenAICompatibleProvider` that the new router hands URLs to.
- `mahavishnu/core/config.py:855-947` — the current `BifrostConfig` model that Phase 7 deletes.
- `mahavishnu/llm_gateway/client.py:17` — the `ProtocolFamily` enum that Phase 7 deletes (replaced by `oneiric.adapters.llm.llm_interface.LLMProvider`).
- `mahavishnu/terminal/manager.py:32-68` — the current `_resolve_worker_env` helper that Phase 3 replaces.
- `mahavishnu/engines/agno_adapter_impl.py:334-378` — the current `_resolve_bifrost_base_url` helper that Phase 2 deletes.
- `session_buddy/bifrost_client.py:32-107` — the parallel session-buddy implementation that Phase 4 deletes.
- `crackerjack/adapters/ai/unified.py:19-72` — the crackerjack call site that Phase 5 migrates.
- `docs/decisions/wire-up-contract.md` — the policy this plan implements (Integration Contract block per phase).
- `feedback-no-claude-code-coauthor-attribution.md` — no `Co-Authored-By` trailer on commits.
- `feedback-bodai-push-is-user-controlled.md` — push is user-controlled; implementer does NOT `git push origin main`.
- `feedback-mcp-common-version-bump-is-user.md` — version bumps are user-controlled; implementer does NOT edit `pyproject.toml` version.
- `bodai-pre-1.0-merge-policy.md` — direct merge to `main`, no PRs.
- `feedback-crackerjack-merge-gate-is-vf.md` — gate is `crackerjack run -v -f`.
- `feedback-no-backwards-compat-pre-1.0.md` — replace not extend; no deprecation windows (the env-var back-compat shim in Phase 1 is the one exception, and it's clearly labeled as transitional).
- `mahavishnu/CLAUDE.md` § "Crackerjack-Compliant Code" — gate and conventions.
- `mahavishnu/CLAUDE.md` § "Process Discipline" — Integration Contract requirement per phase deliverable.
