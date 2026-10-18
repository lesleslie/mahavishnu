---
status: draft
role: implementation
kind: plan
date: 2026-10-17
last_reviewed: 2026-10-17
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
title: "Bifrost gateway as a oneiric LLM adapter — Bodai LLM call-site consolidation"

---

# Bifrost gateway as a oneiric LLM adapter — Bodai LLM call-site consolidation

## 1. Outcome

When this plan ships:

- **Bifrost is a first-class `oneiric.adapters.llm.bifrost.BifrostLLMAdapter`**, registered with the oneiric adapter catalog alongside the existing `AnthropicLLM` and `OpenAILLMAdapter` at `oneiric/adapters/llm/`. The new adapter is a *routing policy resolver* — it returns gateway URLs (or `None` when disabled), it does **not** do HTTP transport.
- **All surviving Bodai LLM call sites resolve their base URL through oneiric**, then hand the URL to `mcp_common.llm.OpenAICompatibleProvider` (the existing transport primitive — unchanged). The two layers are cleanly separated: **oneiric owns routing policy, mcp-common owns HTTP transport.**
- **The "dead flag" anti-pattern is structurally impossible.** A live investigation on 2026-10-17 found that `settings/mahavishnu.yaml:91` sets `route_qwen_code: true` while the master `bifrost.enabled` defaulted to `False`; the `_resolve_worker_env` function in `mahavishnu/terminal/manager.py:56-57` short-circuits on `enabled=False` so the per-worker flag is dead code with no runtime signal. The new adapter contract returns `None` (not a flag, not a stub) when disabled, so any call site that consults it cannot produce inert wiring.
- **mcp-common's `LLMSettings.fallback_chain` and `OpenAICompatibleProvider` stay where they are.** The substrate rollout umbrella (`2026-10-15-oneiric-substrate-rollout.md`) targets settings classes and embedding/auth substrate, not LLM transport. Keeping transport in mcp-common preserves the clean primitive-vs-policy split.
- **PR #0 of the active ollama plan is already merged** on local main (mahavishnu `77b8bed8`, mcp-common `dd889b4`) — confirmed by `git log --oneline main -3` in each repo. The cross-cutting call-site migration in this plan operates on a substrate that no longer has ollama in its default chain.

## 2. Goals

1. **Add `oneiric.adapters.llm.bifrost.BifrostLLMAdapter`** — a new `LLMBase` subclass following the same shape as `oneiric/adapters/llm/anthropic.py:42-60`. The adapter exposes a `resolve_base_url(protocol_family) -> str | None` method that returns the gateway URL for the given protocol family when `enabled: True`, and `None` otherwise.
2. **Migrate mahavishnu's three Bifrost-aware call sites** to consume the new adapter:
   - `mahavishnu/engines/agno_adapter_impl.py:_resolve_bifrost_base_url` (lines 334-378) → call `oneiric.llm_gateway.resolve(...)` instead of the local helper
   - `mahavishnu/terminal/manager.py:_resolve_worker_env` (lines 32-68) → read `base_url` from the oneiric adapter at spawn time, inject `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` per the resolved value
   - `mahavishnu/workers/capabilities/_probes.py:resolve_probe_endpoint` (lines 132-156) → use oneiric URL when `provider == "minimax"`
3. **Migrate mahavishnu's two direct-from-config call sites** to oneiric-resolved URLs:
   - `mahavishnu/workers/cloud_worker.py:_build_fallback_chain` (lines 73-101) — read both provider URLs from oneiric; pass them to `mcp_common.llm.OpenAICompatibleProvider`
   - `mahavishnu/workers/shepherd_backend.py` and any other `MINIMAX_BASE_URL` / `LLAMA_SERVER_URL` env-var consumers — read from oneiric at startup, fall back to env var for backward compat
4. **Migrate session-buddy's hand-rolled `BifrostClient`** at `session_buddy/bifrost_client.py:32-107` to use oneiric. The two dependents (`session_buddy/worker.py:96`, `session_buddy/memory/entity_extractor.py:132-148`) collapse to "ask oneiric for the URL."
5. **Migrate crackerjack's `FallbackChainCodeFixer`** at `crackerjack/adapters/ai/unified.py:19-72` to oneiric for URL resolution. The `doc_update_service.py:255-273` direct `anthropic.Anthropic` SDK call is **out of scope** (deferred — it's a one-shot direct call, not a router).
6. **Add a `pydantic_ai` adapter** if any Bodai LLM call uses pydantic-ai without going through oneiric. (Audit pending — `mahavishnu/adapters/ai/pydantic_ai_adapter.py:86, 99, 258` has direct `provider_prefixes` that may bypass oneiric.)
7. **Delete the now-orphaned `BifrostConfig` model** in `mahavishnu/core/config.py:855-947` after the migration. The oneiric adapter owns the schema from this point on.
8. **Preserve backward compat for env vars** — `MAHAVISHNU_BIFROST__*` env vars keep working. The Pydantic `BifrostConfig` model in oneiric reads the same env-var prefix (with oneiric as the canonical owner). Operators with `MAHAVISHNU_BIFROST__ENABLED=true` in their `~/.zshenv` don't need to rename.

## 3. Non-Goals

- **Full oneiric substrate migration** (settings classes, embedding, auth, pool) — that's the existing `2026-10-15-oneiric-substrate-rollout.md` umbrella. This plan only touches the LLM-routing slice.
- **Ollama cleanup** — done in PR #0 of `2026-10-16-drop-ollama-favor-llama-server.md`; this plan operates on the post-ollama substrate.
- **Bifrost runtime gateway itself** (the Node.js `@maximhq/bifrost` supervisor at `mahavishnu/scripts/bifrost-gateway.py:1-220` running on `localhost:8471`) — already in place and healthy per the 2026-10-17 audit (`curl http://localhost:8471/health` returns `ok`). The plan does not add new Bifrost routing rules; it routes existing call sites through the existing gateway.
- **PiPool substrate** (`mahavishnu/pools/pi_pool.py`) — the `npx @earendil-works/pi-coding-agent` subprocess uses an env allowlist that explicitly drops `MAHAVISHNU_*` and `MINIMAX_*` keys (`pi_pool.py:139-146` + docstring at lines 13-22). This is a security boundary, not a bug; threading Bifrost config into PiPool would violate the allowlist.
- **crackerjack `doc_update_service.py:255-273` direct Anthropic SDK call** — deferred. It's a one-shot LLM call in a code-fix flow; routing through oneiric is nice-to-have, not load-bearing.
- **Bifrost config schema migrations** — operator-visible field renames. Backward compat with `MAHAVISHNU_BIFROST__*` env vars is preserved; no operator action required.
- **Bifrost cache mode (`cache_mode: off | direct | semantic`)** — the active config has it off; the new adapter does not need to implement cache. Add later if a plan requires it.
- **The pydantic-ai adapter work** if Phase 6's audit reveals all pydantic-ai calls already route through the Agno or cloud worker paths.

## 4. Current Findings

### 4.1 Inventory (2026-10-17 audit)

A grep-driven inventory across the 4 in-scope Bodai repos (mahavishnu, session-buddy, crackerjack, mcp-common) found **24 LLM call sites**. Categorized:

| Category | Count | Currently uses oneiric? | Action |
|---|---:|---:|---|
| Routes through `mcp_common.llm.FallbackChain` (transport, no Bifrost awareness) | 6 | No | Phase 2: add Bifrost resolver above the chain |
| Direct SDK calls (agno `OpenAIChat`, `anthropic.Anthropic`) | 7 | No | Phase 2: replace with oneiric-resolved URLs |
| Hardcoded URLs (Bifrost config template, demo defaults, docstrings) | 4 | n/a | Phase 5: replace with oneiric lookups |
| Env-var injection for terminal workers | 2 | No | Phase 3: read base URL from oneiric |
| Embeddings (post-ollama: fastembed + cloud) | 5 | No | Out of scope for this plan; tracked separately |
| **Total** | **24** | **0** | |

**Zero call sites use oneiric LLM adapters today.** The oneiric adapter infrastructure exists (`oneiric/adapters/llm/anthropic.py:42-60` for `AnthropicLLM`; `oneiric/adapters/bootstrap.py:37, 106-107` registers `AnthropicLLM` and `OpenAILLMAdapter` in the catalog) but no Bodai call site consumes it.

### 4.2 The dead-flag bug

`settings/mahavishnu.yaml:55-71` is a fully-commented-out tutorial block. The live override at `settings/mahavishnu.yaml:90-92` sets only `route_qwen_code: true` + `ssl_show_warn: true` — `enabled` inherits the Pydantic default of `False`. `mahavishnu/terminal/manager.py:56-57` short-circuits on `not bifrost.enabled`, so the per-worker flag is never consulted. Verified at runtime:

```
$ .venv/bin/python -c "from mahavishnu.core.config import get_settings; print(get_settings().bifrost.enabled)"
False
```

The new adapter's `resolve_base_url(protocol_family) -> str | None` returns `None` when `enabled: False`, which means *no consumer can produce inert wiring* — the conditional either resolves to a real URL or `None`, never to a flag that's set but unreachable.

### 4.3 Two parallel Bifrost integrations in the fleet

- **Mahavishnu's**: `BifrostConfig` pydantic model (`mahavishnu/core/config.py:855-947`) + `_resolve_bifrost_base_url` helper (`mahavishnu/engines/agno_adapter_impl.py:334-378`) + `_resolve_worker_env` env injection (`mahavishnu/terminal/manager.py:32-68`).
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

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-BIFROST-001
    title: "oneiric BifrostLLMAdapter catalog entry registered"
  - id: REQ-BIFROST-002
    title: "Adapter resolve_base_url returns None when disabled, URL when enabled"
  - id: REQ-BIFROST-003
    title: "Dead-flag regression test: per-worker opt-ins inert when enabled=False"
  - id: REQ-BIFROST-004
    title: "mahavishnu Agno adapter calls oneiric BifrostLLMAdapter (replaces _resolve_bifrost_base_url)"
  - id: REQ-BIFROST-005
    title: "mahavishnu terminal worker env injection reads URL from oneiric"
  - id: REQ-BIFROST-006
    title: "mahavishnu capability probe uses oneiric URL when provider=minimax"
  - id: REQ-BIFROST-007
    title: "mahavishnu CloudWorker._build_fallback_chain reads URLs from oneiric"
  - id: REQ-BIFROST-008
    title: "session-buddy BifrostClient replaced by oneiric lookup"
  - id: REQ-BIFROST-009
    title: "crackerjack FallbackChainCodeFixer uses oneiric URL resolution"
  - id: REQ-BIFROST-010
    title: "MAHAVISHNU_BIFROST__* env-var backward compat preserved"
  - id: REQ-BIFROST-011
    title: "Orphaned BifrostConfig pydantic model deleted from mahavishnu/core/config.py"
  - id: REQ-BIFROST-012
    title: "Migration verification: every surviving LLM call site resolves through oneiric"
```

## 5. Implementation Phases

Each phase is one squash-merge to local `main` per the trunk-based agent-review workflow. Per `bodai-pre-1.0-merge-policy.md`, no PRs; per `feedback-no-claude-code-coauthor-attribution.md`, no `Co-Authored-By` trailer. Push is user-controlled.

### Phase 1: `oneiric.adapters.llm.bifrost.BifrostLLMAdapter` (additive, oneiric repo)

**Goal**: Land the new adapter in oneiric. No existing call site is touched; this is pure addition.

**Tasks**:
- `oneiric/adapters/llm/bifrost.py` (new): `BifrostLLMSettings(LLMBaseSettings)` with the same fields as the current `BifrostConfig` (enabled, base_url, anthropic_base_url, route_claude_code, route_qwen_code, qwen_env_var, local_provider_enabled, local_provider_url, local_provider_model, auth_env, cache_mode, cache_ttl_seconds, request_timeout_seconds, caller_id).
- `oneiric/adapters/llm/bifrost.py` (continued): `BifrostLLMAdapter(LLMBase)` with `category = "llm"`, `name = "bifrost"`, `factory = "oneiric.adapters.llm.bifrost:BifrostLLMAdapter"`, `settings_model = BifrostLLMSettings`.
- `oneiric/adapters/llm/bifrost.py` (continued): `def resolve_base_url(self, protocol_family: ProtocolFamily) -> str | None` — returns the gateway URL for the given protocol family when `enabled: True` and `route_*_code` is satisfied, else `None`. **Hard rule**: this function never returns a hardcoded URL. It either returns the configured gateway URL or `None`.
- `oneiric/adapters/bootstrap.py`: import `BifrostLLMAdapter` and register in the adapter catalog (after `AnthropicLLM` and `OpenAILLMAdapter`).
- `oneiric/adapters/llm/__init__.py`: re-export `BifrostLLMAdapter` and `BifrostLLMSettings`.
- `oneiric/tests/adapters/llm/test_bifrost.py` (new): unit tests for the contract — `enabled=False` returns `None` regardless of `route_*_code` flags; `enabled=True` + `route_claude_code=True` + Anthropic protocol returns the configured `anthropic_base_url`; `enabled=True` + `route_qwen_code=True` + OpenAI protocol returns `<base_url>/v1`; `enabled=True` + `route_claude_code=True` + OpenAI protocol still returns the OpenAI URL (i.e. `route_*_code` gates the *injection*, not the *resolution*).
- `oneiric/tests/adapters/llm/test_bifrost_dead_flag.py` (new): REQ-BIFROST-003. Asserts that when `enabled=False`, no `route_*_code: True` flag produces a non-`None` resolution. This is the structural regression test that catches the bug we hit on 2026-10-17.

#### Integration Contract (Phase 1)

- **Triggered from**: `oneiric.adapters.bootstrap.load_adapters()` runs on oneiric startup. The new adapter is registered as a side effect of the import.
- **Returns to / updates**: `oneiric.adapters.registry` (the in-memory catalog). Queryable via `oneiric.llm.resolve(protocol_family=...)`.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/oneiric
  .venv/bin/python -c "from oneiric.adapters.llm.bifrost import BifrostLLMAdapter; a = BifrostLLMAdapter(); print(a.resolve_base_url('openai'))"
  # Returns the configured gateway URL or None — both are valid.
  ```
- **Rollback signal**: `BifrostLLMAdapter` not found in `oneiric_report_runtime` MCP output. The new adapter's `cycles_total` counter (incremented per `resolve_base_url` call) is 0 after 1 hour of fleet operation.
- **Observability added**: existing OTel counter `oneiric.adapter.lookup{adapter="bifrost"}` (incremented per resolution attempt) + structured log line `adapter.bifrost.resolved provider=openai resolved=true|false`.

### Phase 2: mahavishnu Agno + CloudWorker + probe migration (3 call sites in one PR)

**Goal**: Three mahavishnu call sites that are Bifrost-aware today stop inlining routing logic and call oneiric instead.

**Tasks**:
- `mahavishnu/engines/agno_adapter_impl.py:198-332`: replace the 4 `_create_*_model` factory methods' use of `_resolve_bifrost_base_url` with a oneiric call. Delete the local `_resolve_bifrost_base_url` helper (lines 334-378) and the `mahavishnu/llm_gateway/client.py` module if no other consumer uses it.
- `mahavishnu/workers/cloud_worker.py:73-101`: `_build_fallback_chain` reads `minimax_url` and `llama_server_url` from oneiric. Pass to `mcp_common.llm.OpenAICompatibleProvider` (no change to the chain).
- `mahavishnu/workers/capabilities/_probes.py:132-156`: `resolve_probe_endpoint` calls oneiric for `provider == "minimax"`.
- Tests:
  - `tests/unit/engines/test_agno_adapter.py`: factory tests now stub `oneiric.adapters.llm.bifrost.BifrostLLMAdapter.resolve_base_url` instead of the local helper.
  - `tests/unit/workers/test_cloud_worker.py`: chain-builder test asserts the URLs come from oneiric (mockable seam).
  - `tests/unit/workers/capabilities/test__probes.py`: probe resolver test asserts the gateway URL is used when `enabled: True` and the direct URL when `enabled: False`.

#### Integration Contract (Phase 2)

- **Triggered from**: any code path that constructs an Agno model, builds a `CloudWorker`, or resolves a `minimax` capability probe.
- **Returns to / updates**: the constructed `OpenAIChat` / `Claude` / `FallbackChain` instances carry the oneiric-resolved `base_url`. No persistent state change.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/mahavishnu
  MAHAVISHNU_BIFROST__ENABLED=true .venv/bin/python -c "
  from mahavishnu.engines.agno_adapter_impl import LLMProviderFactory
  m = LLMProviderFactory.from_settings()
  print(m._create_openai_model('gpt-4o').client.base_url)
  # Prints 'http://127.0.0.1:8471/v1' (or the configured gateway URL).
  "
  ```
- **Rollback signal**: Agno factory raises `LLMGatewayUnavailableError` (or similar) on first model construction. CloudWorker raises on first `execute()`. Probe resolution returns `None` in `/health.bifrost.reachable`.
- **Observability added**: OTel counter `mahavishnu.llm.bifrost_resolved{provider, site, resolved}` + log line `llm.bifrost.resolved site=agno provider=openai url=<redacted>`.

### Phase 3: mahavishnu terminal worker env injection

**Goal**: `mahavishnu/terminal/manager.py:_resolve_worker_env` reads the base URL from oneiric instead of the `BifrostConfig` pydantic model.

**Tasks**:
- `mahavishnu/terminal/manager.py:32-68`: replace the direct `bifrost.anthropic_base_url` / `bifrost.base_url` reads with `oneiric.adapters.llm.bifrost.BifrostLLMAdapter().resolve_base_url(ProtocolFamily.ANTHROPIC)` and `...OPENAI`. The per-worker `route_*_code` flags become inputs to the oneiric adapter (the `route_claude_code` / `route_qwen_code` settings fields on `BifrostLLMSettings`).
- Tests:
  - `tests/unit/terminal/test_manager.py::_resolve_worker_env` (new or extended): three cases — `enabled=False` returns `{}`; `enabled=True` + `route_claude_code=True` + worker_type=claude injects `ANTHROPIC_BASE_URL` from oneiric; `enabled=True` + `route_qwen_code=True` + worker_type=qwen injects `OPENAI_BASE_URL` from oneiric.
  - REQ-BIFROST-003 regression test: `enabled=False` + `route_qwen_code=True` returns `{}` (the dead-flag fix).

#### Integration Contract (Phase 3)

- **Triggered from**: `mahavishnu.terminal.manager._resolve_worker_env(worker_type, ...)` is called by the worker spawn path. Today it's called from `WorkerManager.create_session()`.
- **Returns to / updates**: the dict of env vars injected into the tmux session at spawn. No persistent state.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/mahavishnu
  MAHAVISHNU_BIFROST__ENABLED=true MAHAVISHNU_BIFROST__ROUTE_CLAUDE_CODE=true \
    .venv/bin/python -c "
  from mahavishnu.terminal.manager import _resolve_worker_env
  from oneiric.adapters.llm.bifrost import BifrostLLMAdapter
  a = BifrostLLMAdapter()
  env = _resolve_worker_env('terminal-claude', a)
  print(env.get('ANTHROPIC_BASE_URL'))
  "
  # Prints the configured anthropic gateway URL.
  ```
- **Rollback signal**: terminal worker spawn fails with `RuntimeError: spawn failed: env injection returned empty dict for terminal-claude with bifrost.route_claude_code=true`.
- **Observability added**: log line `terminal.bifrost.env_inject worker_type=<t> injected_keys=[...] url=<redacted>`.

### Phase 4: session-buddy BifrostClient → oneiric

**Goal**: The hand-rolled `BifrostClient` at `session_buddy/bifrost_client.py:32-107` is deleted. All session-buddy call sites resolve their URL through oneiric.

**Tasks**:
- `session_buddy/bifrost_client.py`: delete the file. Re-exports in `session_buddy/__init__.py` (if any) updated.
- `session_buddy/worker.py:14, 96`: replace `BifrostClient` import with a oneiric lookup.
- `session_buddy/memory/entity_extractor.py:132-148`: replace the `BIFROST_OPENAI_BASE_URL` env-var read with a oneiric lookup. The `bifrost_openai_base` field stays as a config override for non-Bifrost deployments.
- `session_buddy/llm_providers.py:383-431, 510-519`: `OpenAIProvider` and `AnthropicProvider` config accept an optional `base_url` (already do); the `_get_provider_api_key_and_env` helper stays for the env-var API-key reads. The `LLMManager` calls oneiric for URL resolution.
- Tests:
  - `session_buddy/tests/unit/test_llm_providers.py`: provider tests now use oneiric-mocked URLs.
  - `session_buddy/tests/unit/llm/test_security.py`: no change (security validator is provider-agnostic).

#### Integration Contract (Phase 4)

- **Triggered from**: `session_buddy.llm_providers.LLMManager.__init__` and any direct `BifrostClient` instantiation in `session_buddy/worker.py`.
- **Returns to / updates**: the constructed `OpenAI` / `AsyncOpenAI` / `Anthropic` clients carry the oneiric-resolved `base_url`.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/session-buddy
  BIFROST_BASE_URL=http://localhost:8471/v1 .venv/bin/python -c "
  from session_buddy.llm_providers import LLMManager
  m = LLMManager()
  print([p.base_url for p in m._chain._providers])
  "
  # Prints the gateway URLs.
  ```
- **Rollback signal**: `LLMManager.__init__` raises on first instantiation. Existing `BifrostClient` callers crash with `ImportError` (the file is deleted — the failure is loud).
- **Observability added**: log line `llm.bifrost.session_buddy_resolved provider=openai url=<redacted>`.

### Phase 5: crackerjack FallbackChainCodeFixer → oneiric

**Goal**: `crackerjack/adapters/ai/unified.py:19-72` uses oneiric for URL resolution.

**Tasks**:
- `crackerjack/adapters/ai/unified.py:19-72`: `_build_llm_settings` reads provider URLs from oneiric.
- `crackerjack/adapters/ai/registry.py:9-12, 29-57`: `ProviderID` enum stays; `PROVIDER_INFO["minimax"]` carries an `uses_bifrost: bool` flag (default false) so the registry reports which providers go through the gateway.
- Tests:
  - `crackerjack/tests/adapters/test_ai_registry.py`: registry tests cover the new `uses_bifrost` field.
  - `crackerjack/tests/adapters/test_provider_chain.py`: chain-builder test asserts the URLs come from oneiric.

#### Integration Contract (Phase 5)

- **Triggered from**: `crackerjack.adapters.ai.unified.FallbackChainCodeFixer.__init__`.
- **Returns to / updates**: the constructed `FallbackChain` carries oneiric-resolved URLs.
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/crackerjack
  BIFROST_BASE_URL=http://localhost:8471/v1 .venv/bin/python -c "
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
- **Conditional migration** (if audit surfaces bypasses): migrate the bypassing call sites to oneiric. If audit shows all paths go through the Agno factory or CloudWorker, Phase 6 is a no-op and the result is a one-line audit note in the PR description.

#### Integration Contract (Phase 6)

- **Triggered from**: pydantic-ai adapter instantiation.
- **Returns to / updates**: the constructed `pydantic_ai.Agent` (or equivalent) carries the oneiric-resolved `base_url`.
- **Demonstrable by**: pydantic-ai adapter test asserts the URL came from oneiric (if migration was needed); otherwise the audit doc is the deliverable.
- **Rollback signal**: pydantic-ai agent construction fails.
- **Observability added**: log line `pydantic_ai.bifrost.resolved provider=openai url=<redacted>` (only if migration happened).

### Phase 7: Mahavishnu BifrostConfig deletion

**Goal**: The orphaned `BifrostConfig` pydantic model in `mahavishnu/core/config.py:855-947` is deleted. The oneiric adapter is the sole owner of the schema.

**Tasks**:
- `mahavishnu/core/config.py:855-947`: delete `BifrostConfig` class.
- `mahavishnu/health.py:178, 457, 494`: rewrite the `/health.bifrost.config` probe to query the oneiric adapter (e.g., `oneiric.adapters.llm.bifrost.BifrostLLMSettings.model_dump()`).
- `mahavishnu/cli/config_validator.py:508, 521`: same.
- `mahavishnu/observability/prometheus_metrics.py:371, 376`: read the bifrost local provider URL from oneiric.
- `mahavishnu/core/health.py:1303-1337`: same.
- `mahavishnu/observability/prometheus_metrics.py:161-381`: same.
- `mahavishnu/scripts/bifrost-gateway.py`: unchanged (it's the runtime gateway, not the schema).
- `mahavishnu/scripts/audit_bifrost_grep.py`: unchanged (it lints for `BIFROST_BASE_URL` env var usage, still relevant).
- Tests:
  - `tests/unit/test_config.py`: assert `BifrostConfig` is no longer importable from `mahavishnu.core.config`. The schema has moved to oneiric.
  - `tests/unit/test_health_bifrost.py`: assert `/health.bifrost.config` returns the oneiric-derived values.

#### Integration Contract (Phase 7)

- **Triggered from**: `mahavishnu health` CLI, `mahavishnu config validate`, and the `/health` HTTP route.
- **Returns to / updates**: `/health.bifrost.config` JSON output. Backward compat: same field names, same env-var override pattern (`MAHAVISHNU_BIFROST__*`).
- **Demonstrable by**:
  ```bash
  cd /Users/les/Projects/mahavishnu
  .venv/bin/python -c "from mahavishnu.core.config import BifrostConfig"
  # ModuleNotFoundError — the class moved to oneiric.

  MAHAVISHNU_BIFROST__ENABLED=true .venv/bin/python -m mahavishnu health
  # /health.bifrost.config now shows the oneiric-resolved values.
  ```
- **Rollback signal**: `/health` returns 503 with `bifrost.config_unreachable: true` (config probe fails).
- **Observability added**: OTel counter `mahavishnu.bifrost.config_probed{resolved=true|false}` + log line `bifrost.config.probed source=oneiric`.

### Phase 8: End-to-end migration verification

**Goal**: Confirm every surviving LLM call site in the Bodai fleet resolves through oneiric (REQ-BIFROST-012).

**Tasks**:
- `scripts/audit_bifrost_callers.py` (new, runs from mahavishnu): a one-shot audit script that walks the 4 in-scope repos and asserts that any `base_url=...` argument to an LLM client construction is either (a) sourced from oneiric via a helper, or (b) a hardcoded local URL (e.g. `http://localhost:8081`) with a `LOCAL_PROVIDER_ALLOWLIST`. Direct base URLs not in either set fail the audit.
- `docs/llm-routing.md` (new): a one-page reference that documents the oneiric ownership and lists the call sites + their routing source.
- `docs/plans/PLAN_INDEX.md`: move this plan from `draft` to `complete` (line 252-260 of the index pattern).

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

### oneiric (Phase 1)

- [ ] `oneiric/adapters/llm/bifrost.py` (new)
- [ ] `oneiric/adapters/llm/__init__.py` (re-export)
- [ ] `oneiric/adapters/bootstrap.py` (register)
- [ ] `oneiric/tests/adapters/llm/test_bifrost.py` (new)
- [ ] `oneiric/tests/adapters/llm/test_bifrost_dead_flag.py` (new — REQ-BIFROST-003 regression)

### mahavishnu (Phases 2, 3, 7)

- [ ] `mahavishnu/engines/agno_adapter_impl.py` (Phase 2 — REQ-BIFROST-004)
- [ ] `mahavishnu/workers/cloud_worker.py` (Phase 2 — REQ-BIFROST-007)
- [ ] `mahavishnu/workers/capabilities/_probes.py` (Phase 2 — REQ-BIFROST-006)
- [ ] `mahavishnu/terminal/manager.py` (Phase 3 — REQ-BIFROST-005)
- [ ] `mahavishnu/llm_gateway/client.py` (Phase 2 — delete if orphaned)
- [ ] `mahavishnu/core/config.py` (Phase 7 — REQ-BIFROST-011)
- [ ] `mahavishnu/health.py` (Phase 7)
- [ ] `mahavishnu/cli/config_validator.py` (Phase 7)
- [ ] `mahavishnu/observability/prometheus_metrics.py` (Phase 7)
- [ ] `mahavishnu/core/health.py:1303-1337` (Phase 7)
- [ ] `tests/unit/engines/test_agno_adapter.py` (Phase 2)
- [ ] `tests/unit/workers/test_cloud_worker.py` (Phase 2)
- [ ] `tests/unit/workers/capabilities/test__probes.py` (Phase 2)
- [ ] `tests/unit/terminal/test_manager.py` (Phase 3)
- [ ] `tests/unit/test_config.py` (Phase 7)
- [ ] `tests/unit/test_health_bifrost.py` (Phase 7)

### session-buddy (Phase 4)

- [ ] `session_buddy/bifrost_client.py` (delete)
- [ ] `session_buddy/worker.py` (Phase 4 — REQ-BIFROST-008)
- [ ] `session_buddy/memory/entity_extractor.py` (Phase 4 — REQ-BIFROST-008)
- [ ] `session_buddy/llm_providers.py` (Phase 4)
- [ ] `session_buddy/tests/unit/test_llm_providers.py` (Phase 4)

### crackerjack (Phase 5)

- [ ] `crackerjack/adapters/ai/unified.py` (Phase 5 — REQ-BIFROST-009)
- [ ] `crackerjack/adapters/ai/registry.py` (Phase 5 — `uses_bifrost` field)
- [ ] `crackerjack/tests/adapters/test_ai_registry.py` (Phase 5)
- [ ] `crackerjack/tests/adapters/test_provider_chain.py` (Phase 5)

### pydantic-ai (Phase 6 — conditional)

- [ ] `mahavishnu/adapters/ai/pydantic_ai_adapter.py` (Phase 6 — only if audit surfaces bypasses)

### cross-repo (Phase 8)

- [ ] `mahavishnu/scripts/audit_bifrost_callers.py` (new)
- [ ] `docs/llm-routing.md` (new)
- [ ] `docs/plans/PLAN_INDEX.md` (move this plan from `draft` to `complete`)

## 7. Validation Matrix

| Check | Command | Expected outcome | Evidence |
|---|---|---|---|
| oneiric adapter registered | `cd /Users/les/Projects/oneiric && .venv/bin/python -c "from oneiric.adapters.llm.bifrost import BifrostLLMAdapter; print(BifrostLLMAdapter.metadata.name)"` | `bifrost` | Test log |
| Dead-flag regression | `cd /Users/les/Projects/oneiric && .venv/bin/python -m pytest tests/adapters/llm/test_bifrost_dead_flag.py -q` | Pass | Test log |
| Mahavishnu Agno routes through oneiric | `cd /Users/les/Projects/mahavishnu && MAHAVISHNU_BIFROST__ENABLED=true .venv/bin/python -c "from mahavishnu.engines.agno_adapter_impl import LLMProviderFactory; m = LLMProviderFactory.from_settings(); print(m._create_openai_model('gpt-4o').client.base_url)"` | Gateway URL | Test log |
| Mahavishnu terminal env injection | `MAHAVISHNU_BIFROST__ENABLED=true MAHAVISHNU_BIFROST__ROUTE_CLAUDE_CODE=true .venv/bin/python -c "from mahavishnu.terminal.manager import _resolve_worker_env; from oneiric.adapters.llm.bifrost import BifrostLLMAdapter; a = BifrostLLMAdapter(); print(_resolve_worker_env('terminal-claude', a))"` | `{'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8471/anthropic'}` | Test log |
| Session-buddy URLs | `cd /Users/les/Projects/session-buddy && BIFROST_BASE_URL=http://localhost:8471/v1 .venv/bin/python -c "from session_buddy.llm_providers import LLMManager; m = LLMManager(); print([p.base_url for p in m._chain._providers])"` | Gateway URLs | Test log |
| Crackerjack URLs | `cd /Users/les/Projects/crackerjack && BIFROST_BASE_URL=http://localhost:8471/v1 .venv/bin/python -c "from crackerjack.adapters.ai.unified import FallbackChainCodeFixer; fc = FallbackChainCodeFixer(); print([p.base_url for p in fc._chain._providers])"` | Gateway URLs | Test log |
| `BifrostConfig` deleted from mahavishnu | `cd /Users/les/Projects/mahavishnu && .venv/bin/python -c "from mahavishnu.core.config import BifrostConfig"` | `ModuleNotFoundError` | Test log |
| All call sites use oneiric | `cd /Users/les/Projects/mahavishnu && python scripts/audit_bifrost_callers.py` | Exits 0 | Audit log |
| Crackerjack merge gate (each repo) | `cd <repo> && crackerjack run -v -f` | Pass | Test log |
| pytest | `pytest tests/unit -q` | Pass (modulo known pre-existing failures) | Test log |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The `MAHAVISHNU_BIFROST__*` env-var prefix breaks in Phase 7 when `BifrostConfig` is deleted | Medium | The oneiric adapter reads the same env-var prefix (`ONEIRIC_BIFROST__*` would be the new canonical, but oneiric can also read `MAHAVISHNU_BIFROST__*` as a deprecated alias — see `feedback-mcp-common-version-bump-is-user.md` for the user-controlled env-var-migration pattern). Phase 7 includes a back-compat shim that maps the old prefix to the new one with a deprecation log line. |
| session-buddy's `BifrostClient` is consumed by external code (not in our tree) | Low | `grep -r "BifrostClient" /Users/les/Projects/` confirms no external consumers in the Bodai fleet. The session-buddy README and CHANGELOG note the class is internal. |
| The oneiric adapter is overkill for the LLM routing concern | Low | oneiric already has `AnthropicLLM` and `OpenAILLMAdapter` at `oneiric/adapters/llm/`. Adding `BifrostLLMAdapter` follows the established shape, not a new pattern. |
| The dead-flag regression test in Phase 1 isn't enough — a future contributor could bypass the adapter with a direct call | Low | The `audit_bifrost_callers.py` script in Phase 8 runs in CI and flags any non-allowlisted `base_url` argument. |
| crackerjack's `doc_update_service.py` direct Anthropic SDK call is a regression vector after the migration | Low | It's out of scope for this plan; deferred to a follow-up. The Phase 8 audit script flags it but doesn't fail the build (allowlist: "out-of-scope: deferred to follow-up"). |
| The Bifrost runtime gateway goes down mid-migration | Low | The existing `bifrost.local_provider_url` field (llama-server) is the documented fallback. Phase 2's chain-builder falls through to llama-server when the gateway is unreachable. |
| oneiric's adapter bootstrap is not yet mature | Medium | The substrate rollout (`2026-10-15-oneiric-substrate-rollout.md`) is still in progress; per its acceptance criteria, "Every Bodai core MCP server calls `oneiric_report_runtime` on startup" is not yet done. The Bifrost adapter registration is independent of this maturity — adapters register at import time, not at runtime-config-publish time. |
| Multi-repo merge coordination cost (8 PRs across 4 repos) | Medium | Per-repo merge via squash-merge. Each repo's `crackerjack run -v -f` gates its own merge. Sequence: oneiric → mahavishnu (3 PRs) → session-buddy → crackerjack → mahavishnu (Phase 7). |

## 9. Decision Rule

This plan is "done" when:

- A user can run `MAHAVISHNU_BIFROST__ENABLED=true .venv/bin/mahavishnu demo agno --prompt "..."` against the local Bifrost gateway and get a real LLM completion routed through the gateway.
- `crackerjack run -v -f` passes in every repo.
- `scripts/audit_bifrost_callers.py` exits 0 (or exits 0 with all bypasses documented in an allowlist comment).
- `/health.bifrost.config` returns the oneiric-derived values.
- The dead-flag regression test in `oneiric/tests/adapters/llm/test_bifrost_dead_flag.py` passes — and any attempt to set `route_*_code: true` while `enabled: false` produces no effect (provable by the test).
- The plan has been promoted from `status: draft` to `status: complete` in `docs/plans/PLAN_INDEX.md` (per `TEMPLATE.md` line 147).

**If scope pressure forces a cut**:

- **Drop Phase 6 (pydantic-ai audit) first.** It's conditional — if the audit shows all pydantic-ai calls go through the Agno factory or CloudWorker, Phase 6 is a one-line note. Don't let a "audit might find something" scope expand the timeline.
- **Drop Phase 7 (BifrostConfig deletion) if back-compat is a real concern.** The orphaned model can stay as a deprecated re-export from `mahavishnu.core.config` for one release cycle. But the migration is *structurally incomplete* without Phase 7 — the dead-flag fix only holds if there's no parallel config model that can independently drift.
- **Phases 1-5 are the load-bearing work.** Without the oneiric adapter, no migration is possible. Without Phases 2-5, the migration is incomplete and the dead-flag bug can re-occur.

**Post-plan discipline**:

- After all per-repo merges land on local `main`, do **NOT** run `git push origin main` — push is user-controlled per `feedback-bodai-push-is-user-controlled.md`.
- The user runs `git push` from their own shell.
- The implementer does **NOT** bump the oneiric version themselves per `feedback-mcp-common-version-bump-is-user.md`; the user runs `crackerjack run -p <level>` from their shell to bump+tag+publish when ready.
- Each per-repo commit is authored as `les@wedgwoodwebworks.com` (not `.local`) with no `Co-Authored-By` trailer per `feedback-no-claude-code-coauthor-attribution.md`.
- The new `oneiric.adapters.llm.bifrost` adapter is *additive* — no existing oneiric call site is changed. Backward compat is automatic for the four repos that don't yet import the new adapter.

## References

- `docs/plans/2026-10-16-drop-ollama-favor-llama-server.md` — the active ollama removal plan; PR #0 already landed in this repo (`77b8bed8`) and mcp-common (`dd889b4`).
- `docs/plans/2026-10-15-bifrost-gateway-wiring.md` — the existing Bifrost wiring plan (Phase D Qwen gate); the wiring this plan consolidates.
- `docs/plans/2026-10-15-oneiric-substrate-rollout.md` — the umbrella oneiric substrate plan; this plan is a slice of it (LLM routing) that doesn't conflict with settings-class or embedding-substrate work.
- `docs/specs/2026-10-15-bifrost-gateway-wiring-design.md` — the v1.5 Bifrost design spec; the schema here is a superset of the spec's Phase A fields.
- `oneiric/adapters/llm/anthropic.py:42-60` — the `LLMBase` subclass shape that the new `BifrostLLMAdapter` follows.
- `mcp_common/llm/provider.py:30-58` — the `OpenAICompatibleProvider` that the new adapter hands URLs to.
- `mahavishnu/core/config.py:855-947` — the current `BifrostConfig` model that Phase 7 deletes.
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
- `feedback-no-backwards-compat-pre-1.0.md` — replace not extend; no deprecation windows (the env-var back-compat shim in Phase 7 is the one exception, and it's clearly labeled as transitional).
- `mahavishnu/CLAUDE.md` § "Crackerjack-Compliant Code" — gate and conventions.
- `mahavishnu/CLAUDE.md` § "Process Discipline" — Integration Contract requirement per phase deliverable.
