---
status: draft
role: implementation
kind: plan
date: 2026-10-16
last_reviewed: 2026-10-16
superseded_by: null
blocks_on:
  - docs/plans/2026-10-15-bifrost-gateway-wiring.md
related:
  - docs/plans/2026-05-10-minimax27-provider-migration.md
  - docs/plans/2026-10-15-bifrost-gateway-wiring.md
  - docs/plans/2026-09-27-shared-bodai-substrate-design.md
replaces: null
topic: drop-ollama-favor-llama-server
title: "Drop Ollama in favor of llama-server (llama.cpp) across the Bodai stack"

---

# Drop Ollama in favor of llama-server (llama.cpp) across the Bodai stack

## Why this plan exists

A live demo of `mahavishnu demo llamaindex` on 2026-10-16 surfaced a
real footgun: the local Ollama build returns 501 for the embeddings
endpoint because it was compiled without `--embeddings`. The fall-back
code path (in-memory vector store) handled the OpenSearch KNN-plugin
gap cleanly, but the 501 wall at the embedder is a class of failure
that should not exist.

Wider investigation across the 6 core Bodai repos (mahavishnu, akosha,
session-buddy, crackerjack, oneiric, mcp-common) revealed:

1. The **dominant pattern** in production is `mcp_common.llm.OpenAICompatibleProvider`
   pointed at a `base_url`. Ollama and llama-server are *interchangeable
   in that surface*. They differ in only one place: the library classes
   (Agno's `Ollama`, llama-index's `OllamaEmbedding`/`Ollama`) that wrap
   vendor-specific HTTP shapes.
2. llama-server (llama.cpp's HTTP server) exposes the same OpenAI-compat
   API as MiniMax and Ollama does (`/v1/chat/completions`,
   `/v1/embeddings`, `/v1/models`). Embeddings are a runtime flag
   (`--embedding`), not a build-time choice.
3. CLAUDE.md already names llama-server as a local fallback at
   `http://localhost:8081/v1` with `qwen3.5`, and a 3-tier
   `MiniMax → llama_server → Ollama` FallbackChain is wired through
   `mcp_common.llm.fallback.FallbackChain` and used by CloudWorker
   (Agno), LLMManager (session-buddy), and FallbackChainCodeFixer
   (crackerjack).

Ollama is therefore **one more URL in a base_url table** for the
dominant path, with the library-class cases being the only places that
depend on Ollama-native payload shapes. Removing Ollama simplifies the
provider matrix and removes the embedding 501 footgun.

This is a `feedback-no-backwards-compat-pre-1.0`-aligned cleanup:
no deprecation windows, no legacy support, no shim layers. Delete
the surface; trust the tests to catch missed references.

## 1. Outcome

When this plan ships:
- The Bodai stack has **two** local-LLM providers (llama-server, cloud
  MiniMax) instead of three (llama-server, Ollama, cloud MiniMax).
- `mahavishnu demo llamaindex` runs end-to-end against llama-server
  (verified live) and a real LLM completion is returned.
- The Agno engine (`mahavishnu demo agno`) routes to llama-server for
  local inference without going through Agno's Ollama library class.
- All 5 `LLMProvider.OLLAMA` / `ProviderID.OLLAMA` / `EmbeddingProvider.OLLAMA`
  enum values are deleted. All `ollama_base_url` config keys are
  deleted. All `OLLAMA_BASE_URL` / `SESSION_BUDDY_ENABLE_OLLAMA` env
  vars are no longer read.

## 2. Goals

1. **Replace Ollama with llama-server** in every place where the
   codebase currently talks to a local LLM.
2. **Delete the Ollama-specific library classes** in `mahavishnu/engines/`
   and `session_buddy/llm/providers/`. No shim, no deprecation.
3. **Simplify the FallbackChain** in all three call sites
   (mahavishnu CloudWorker, session-buddy LLMManager, crackerjack
   FallbackChainCodeFixer) to `["minimax", "llama_server"]`.
4. **Wire llama-server into a live demo** (PR 3) so the user has a
   one-command path to verify the cleanup actually works.

## 3. Non-Goals

- Drop MiniMax. The cloud LLM provider stays; the FallbackChain still
  prefers it.
- Migrate any non-Ollama local LLM (e.g. a future vLLM) — that is a
  separate decision.
- Operator-facing install docs for llama-server. PR 3's demo only
  assumes the operator has `llama-server` on `$PATH`; how they
  downloaded a GGUF is out of scope (per user direction, no docker).
- The `mahavishnu demo llamaindex` CLI wrapper. PR 3 implements a
  live demo via direct adapter invocation (mirroring how the Agno
  fix in commit `ba832db6` wired the Agno demo). The full CLI wiring
  is a separate cleanup.
- Migration of the Pydantic-AI adapter (`mahavishnu/adapters/ai/pydantic_ai_adapter.py`).
  Pydantic-AI's `ollama:` prefix is library-specific; the adapter is
  secondary and the Ollama mention is a prefix-mapping dict entry
  (no runtime test exercises it). Deferred to a follow-up plan.

## 4. Current Findings

### Inventory (subagent-verified 2026-10-16)

A grep-driven inventory across the 6 core Bodai repos (output saved
in the parent session transcript) found:

- **~50 file-groups** on the B-list (OpenAI-compat surface, removable
  by config/schema/test cleanup alone).
- **5 file-groups** on the A-list (library-class cases that need code
  changes, not just config). The user's 2026-10-16 confirmation
  removes A6 (docker-compose) entirely.
- **Zero A-list usages of an Ollama-specific feature**
  (model auto-download, Modelfile parsing, `/api/tags` registry)
  in the live runtime path of any repo. The Ollama-native code
  exists only in: Agno's library class, llama-index's library
  classes, oneiric's hybrid embedding Ollama branch, and a
  stand-alone offline script.

### Dead-code confirmation: `OllamaProvider` is unused in production

`session_buddy/llm/providers/ollama_provider.py` is dead code. The
agent's grep + `git log` investigation showed:

- Commit `4590e77d` (2026-05-16) "refactor(llm): consolidate LLMManager
  to delegate directly to mcp_common FallbackChain" replaced the
  per-provider iteration loop with a thin wrapper around
  `mcp_common.llm.fallback.FallbackChain`. The `OllamaProvider` class
  has had zero non-test consumers since.
- All non-test references are re-exports in
  `session_buddy/llm/__init__.py:21, 36` and
  `session_buddy/llm/providers/__init__.py:11, 17`.
- The dedicated test files (`tests/unit/test_llm_providers_ollama.py`,
  `tests/unit/test_llm_helper_functions.py:415-565`) are the only
  callers; both go away when the class is deleted.

This collapses A3 (rewrite) to B (delete).

### Three-tier FallbackChain is already wired in three call sites

The pattern at `mahavishnu/workers/cloud_worker.py:78-113`
(`_build_fallback_chain`) is the canonical shape. Same shape in:

- `session_buddy/llm_providers.py:501-577` (`LLMManager._build_chain`)
- `crackerjack/adapters/ai/unified.py:19-72` (`FallbackChainCodeFixer._build_llm_settings`)

All three register Ollama with `base_url=http://localhost:11434/v1`
(i.e. Ollama's OpenAI-compat surface, not Ollama-native). A
`base_url` swap is the entire mechanical change.

### Agno and llama-index use library classes, not bare HTTP

- `mahavishnu/engines/agno_adapter_impl.py:218-238` constructs
  `from agno.models.ollama import Ollama; Ollama(id=..., host=...,
  options={"num_predict": ...})`. The `options.num_predict` and
  `host=` parameters are Ollama-specific. **Fix**: replace with
  `from agno.models.openai import OpenAIChat; OpenAIChat(id=...,
  base_url=llama_server_url, ...)` (Agno already uses `OpenAIChat`
  for the MiniMax path at L240-262 in the same file).
- `mahavishnu/engines/llamaindex_adapter_impl.py:39-40, 383-386` imports
  `OllamaEmbedding` (which posts `{prompt: text}` to Ollama's
  `/api/embeddings`) and `Ollama` (which posts to Ollama's
  `/api/chat`). llama-index has first-class `OpenAIEmbedding` and
  `OpenAILike` classes for OpenAI-compat providers. **Fix**: swap
  the imports and the `Settings.embed_model = ...` /
  `Settings.llm = ...` constructors.

### oneiric embedding probe chain is `llama_cpp → ollama → minimax → model2vec`

`oneiric/adapters/observability/embeddings.py:99-138` probes
backends in order; the Ollama branch (L308-330, L387-425, L445-458)
uses Ollama-native payload shape (`{prompt: text}` per-text POST
to `/api/embeddings`). The llama.cpp branch in the same file
already uses the OpenAI shape. **Fix**: delete the Ollama branch;
the llama.cpp branch covers it.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-OLLAMA-001
    title: "CloudWorker FallbackChain no longer references ollama"
  - id: REQ-OLLAMA-002
    title: "LLMManager FallbackChain no longer references ollama"
  - id: REQ-OLLAMA-003
    title: "FallbackChainCodeFixer FallbackChain no longer references ollama"
  - id: REQ-OLLAMA-004
    title: "mcp_common LLMSettings.fallback_chain default is [minimax, llama_server]"
  - id: REQ-OLLAMA-005
    title: "session_buddy/llm/providers/ollama_provider.py deleted (entire file + re-exports + tests)"
  - id: REQ-OLLAMA-006
    title: "Agno engine uses OpenAIChat (not agno.models.ollama.Ollama) for local inference"
  - id: REQ-OLLAMA-007
    title: "LlamaIndex engine uses OpenAIEmbedding + OpenAILike (not OllamaEmbedding + Ollama) for local inference"
  - id: REQ-OLLAMA-008
    title: "oneiric EmbeddingService Ollama branch deleted; probe order becomes [llama_cpp, minimax, model2vec]"
  - id: REQ-OLLAMA-009
    title: "oneiric EmbeddingSettings.ollama_* fields deleted; LLMProvider.OLLAMA enum entry deleted"
  - id: REQ-OLLAMA-010
    title: "mahavishnu LLMProvider.OLLAMA enum entry deleted; LLMConfig.ollama_base_url field deleted"
  - id: REQ-OLLAMA-011
    title: "mahavishnu scripts/generate_ollama_embeddings.py deleted (offline script, no callers)"
  - id: REQ-OLLAMA-012
    title: "mahavishnu/settings/*.yaml ollama:* and llm.ollama_base_url entries removed"
  - id: REQ-OLLAMA-013
    title: "session_buddy settings.py ollama_base_url/ollama_default_model fields deleted; feature_flags.enable_ollama flag deleted"
  - id: REQ-OLLAMA-014
    title: "session_buddy reflection/embeddings.py _try_ollama deleted; _try_http_embedding_providers becomes llama-server-only"
  - id: REQ-OLLAMA-015
    title: "crackerjack ProviderID.OLLAMA enum + PROVIDER_INFO[ollama] + CLI selector entry deleted"
  - id: REQ-OLLAMA-016
    title: "crackerjack AISettings.ai_providers / ai_provider / ollama_* fields collapsed to llama_server-only"
  - id: REQ-OLLAMA-017
    title: "akosha BACKEND_DEFAULT_DIMS['ollama'] entry deleted (dim identical to llama_cpp)"
  - id: REQ-OLLAMA-018
    title: "Live demo: mahavishnu demo llamaindex runs end-to-end against llama-server and returns a real completion"
  - id: REQ-OLLAMA-019
    title: "Live demo: mahavishnu demo agno runs against llama-server (via OpenAIChat factory branch) and returns a real completion"
```

## 5. Implementation Phases

The three PRs land **in order**, with mcp-common first (it's a
dependency for the others), then the library-class swaps, then
the live demo. Each PR is a separate merge to local `main` per
`bodai-pre-1.0-merge-policy.md` (no PRs, direct merge).

### Phase 1: Drop Ollama from the OpenAI-compat surface (B-list)

**Goal**: Remove every reference to Ollama that lives on the
OpenAI-compat surface (provider table, enum, schema, settings,
feature flags, CLI selector, tests). After this PR, the production
runtime no longer touches Ollama in any code path that uses
`mcp_common.llm.OpenAICompatibleProvider` or its callers.

**Tasks** (in repo order — mcp-common first because the others
import it):

1. **mcp-common**:
   - `mcp_common/llm/config.py`: `fallback_chain` default →
     `["minimax", "llama_server"]` (REQ-OLLAMA-004).
   - `mcp_common/tests/test_llm.py` + `mcp_common/tests/unit/test_llm_additional.py`:
     drop all `ollama` test cases; keep the `llama_server` ones.
2. **mahavishnu**:
   - `mahavishnu/workers/cloud_worker.py`: providers dict (no `ollama`),
     `fallback_chain` (REQ-OLLAMA-001), `_has_local_fallback` probe
     (no `shutil.which("ollama")`).
   - `mahavishnu/core/config.py`: `LLMProvider.OLLAMA` enum entry,
     `AgnoLLMConfig.provider` default, `LLMConfig.ollama_base_url`
     (REQ-OLLAMA-010).
   - `mahavishnu/core/embeddings_oneiric.py`:
     `EmbeddingConfig.ollama_base_url` (REQ-OLLAMA-008 client side).
   - `mahavishnu/core/bootstrap.py:735`: drop the
     `if actual_provider == "ollama"` branch.
   - `mahavishnu/core/errors.py:438-440`: update recovery hint
     strings.
   - `mahavishnu/cli/demo_cli.py:434, 461, 477`: drop
     `LLMProvider.OLLAMA: None` key.
   - `mahavishnu/cli/config_validator.py:147`: drop
     `_ensure_http_url(settings.llm.ollama_base_url, ...)` line.
   - `mahavishnu/core/production_readiness.py:87`: drop
     `"ollama_base_url"` from validated keys.
   - `mahavishnu/core/routing.py:54`: verify the `\bollama\b` regex
     isn't depended on by any test (likely a misspelling of
     `\bolama\b`); if not, drop the line.
   - `mahavishnu/settings/models.yaml:76-97`: drop the `ollama:`
     provider block.
   - `mahavishnu/settings/embeddings.yaml:31-53`: drop the
     ollama-specific config; keep `provider: fastembed` default.
   - `mahavishnu/settings/mahavishnu.yaml:45`: drop
     `llm.ollama_base_url`.
   - `mahavishnu/settings/local.yaml.example:30, 33`,
     `mahavishnu.yaml.example:18, 19`: drop ollama lines.
   - Tests: drop `ollama` test cases from
     `tests/unit/test_adapters/test_llamaindex_adapter.py` (skip
     Agno-specific ones; that's Phase 2),
     `tests/unit/test_core_embeddings_oneiric.py`,
     `tests/unit/test_embeddings.py`,
     `tests/unit/test_core_models.py`,
     `tests/property/test_config_properties.py`,
     `tests/unit/test_config.py`,
     `tests/unit/test_mahavishnu_config.py`,
     `tests/unit/test_config_validator_cli.py`,
     `tests/unit/test_bootstrap.py`,
     `tests/unit/test_content_ingester.py`,
     `tests/unit/test_errors.py`,
     `tests/unit/test_production_readiness.py`,
     `tests/unit/test_task_router.py`,
     `tests/unit/test_task_router_and_auth.py`,
     `tests/unit/test_worker_registry.py`,
     `tests/unit/test_workers_registry_coverage.py`,
     `tests/unit/workers/test_capabilities_observability.py`,
     `tests/unit/pools/test_gpu_handler_pool.py`,
     `tests/unit/test_adapters/README.md`,
     `tests/unit/core/test_context_coverage.py`.
3. **session-buddy**:
   - `session_buddy/llm/security.py:56-58, 132`: drop `"ollama"`
     from the local-service set; the remaining set is
     `{"llama_server"}`.
   - `session_buddy/llm_providers.py:501-577`: `LLMManager._build_chain`
     no longer registers `ollama`; the chain becomes
     `["minimax", "llama_server"]` (REQ-OLLAMA-002).
   - `session_buddy/llm/__init__.py:21, 36` and
     `session_buddy/llm/providers/__init__.py:11, 17`:
     delete the `OllamaProvider` re-exports (REQ-OLLAMA-005).
   - `session_buddy/settings.py:113, 116, 121-127`:
     drop `ollama_base_url`, `ollama_default_model`, drop
     `"ollama"` from `fallback_providers` default.
   - `session_buddy/config/feature_flags.py:30, 101, 122`:
     delete `enable_ollama` flag (REQ-OLLAMA-013).
   - `session_buddy/reflection/embeddings.py:68-97`:
     delete `_try_ollama`; `_try_http_embedding_providers` becomes
     llama-server-only (REQ-OLLAMA-014).
   - `session_buddy/reflection/database.py:29`,
     `session_buddy/adapters/reflection_adapter_oneiric.py:38, 1112, 1121`,
     `session_buddy/mcp/oneiric_runtime.py:54-101`,
     `session_buddy/utils/lazy_imports.py:118, 256`:
     comment updates.
   - `session_buddy/settings/session-buddy.yaml:11-25, 181`:
     drop ollama entries.
   - `session_buddy/tests/unit/test_llm_providers_ollama.py`:
     delete the file.
   - Drop ollama test cases from:
     `tests/unit/test_llm_providers.py`,
     `tests/unit/llm/test_security.py`,
     `tests/unit/test_feature_flags.py`,
     `tests/unit/test_settings.py`,
     `tests/unit/test_settings_core.py`,
     `tests/unit/test_lazy_imports.py`,
     `tests/unit/test_llm_helper_functions.py`,
     `tests/unit/test_llm_security.py`,
     `tests/unit/test_pools_hybrid_d.py`,
     `tests/unit/test_health_checks.py`,
     `tests/unit/test_health_checks_core.py`,
     `tests/unit/mcp/tools/infrastructure/test_feature_flags_tools.py`.
4. **crackerjack**:
   - `crackerjack/adapters/ai/unified.py:19-72`:
     `_build_llm_settings` no longer registers `ollama`
     (REQ-OLLAMA-003).
   - `crackerjack/adapters/ai/registry.py:9-12, 29-57, 78-82`:
     delete `ProviderID.OLLAMA` enum + `PROVIDER_INFO["ollama"]`
     entry (REQ-OLLAMA-015). `get_code_fixer` returns
     `FallbackChainCodeFixer` with the 2-provider chain.
   - `crackerjack/cli/handlers/provider_selection.py:48-51, 190-196`:
     remove the Ollama option from the interactive selector
     (REQ-OLLAMA-015).
   - `crackerjack/cli/options.py:674`: update help text.
   - `crackerjack/config/settings.py:98-115`:
     `ai_providers` Literal collapses to
     `["minimax", "llama_server"]`; `ai_provider` default
     stays `"minimax"`; drop `ollama_base_url`, `ollama_model`,
     `ollama_timeout` (REQ-OLLAMA-016).
   - `crackerjack/models/semantic_models.py:136-146`:
     drop the `ollama` Literal and `ollama_base_url` field
     (verify legacy schema is unused first).
   - `crackerjack/fixers/security.py:168-204`:
     drop `ollama` and `ollama_base_url` from heuristic lists.
   - Tests: drop ollama test cases from
     `tests/adapters/test_ai_registry.py`,
     `tests/adapters/test_provider_chain.py`,
     `tests/models/test_semantic_models.py`,
     `tests/unit/services/test_config_service.py`,
     `tests/unit/test_config_settings.py`.
5. **oneiric**:
   - `oneiric/adapters/observability/embedding_settings.py:17-77`:
     drop `ollama_*` fields.
   - `oneiric/core/substrate_settings.py:198-208, 240-246`:
     drop `ollama` from `embedding__backend` Literal.
   - `oneiric/adapters/llm/llm_interface.py:21`:
     drop `LLMProvider.OLLAMA` enum entry.
   - Tests: drop ollama test cases from
     `oneiric/tests/adapters/test_observability_embeddings.py`.
6. **akosha**:
   - `akosha/processing/embedding_dim.py:45-58, 61-141`:
     drop `BACKEND_DEFAULT_DIMS["ollama"]` entry (REQ-OLLAMA-017).
   - `akosha/storage/hot_store.py:103, 109`: comment update.
   - Tests: drop ollama test cases from
     `akosha/tests/unit/test_embeddings.py`,
     `akosha/tests/unit/processing/test_embedding_dim.py`.
7. **mcp-common** tests already covered in step 1.

**Exit criteria**:
- `git grep -n "ollama\|Ollama" -- ':!*tests' ':!*docs' ':!*CHANGELOG.md'`
  returns zero hits in the production source tree of all 6 repos
  (modulo Pydantic-AI's optional adapter, deferred per §3).
- `crackerjack run -v -f` passes in every repo (per the user's
  `feedback-crackerjack-merge-gate-is-vf`).
- Each repo's pytest suite passes (modulo known pre-existing
  failures from the recent `raise Exception` commit).

#### Integration Contract (Phase 1)

- **Triggered from**: Any code path that imports
  `mcp_common.llm.fallback.FallbackChain` or its callers
  (`mahavishnu.workers.cloud_worker.CloudWorker.__init__`,
  `session_buddy.llm_providers.LLMManager.__init__`,
  `crackerjack.adapters.ai.unified.FallbackChainCodeFixer.__init__`).
  Also: any code path that reads `mahavishnu.settings.models.yaml`
  or any of the per-repo `settings/{repo}.yaml` files.
- **Returns to / updates**:
  - `LLMSettings.fallback_chain` is now `["minimax", "llama_server"]`
    by default. The `providers` dict no longer has an `"ollama"` key.
  - The `LLMProvider` enum (mahavishnu, oneiric), `EmbeddingProvider`
    enum (mahavishnu), `ProviderID` enum (crackerjack) no longer
    have an `OLLAMA` value.
  - No persistent file or DB change; settings YAMLs are the
    source of truth.
- **Demonstrable by**:
  ```bash
  # In each repo:
  grep -rn "ollama\|Ollama\|OLLAMA" .venv/lib/python3.14/site-packages/ 2>/dev/null
  # (this confirms no installed package leaks ollama into runtime imports)
  pytest tests/unit -q  # passes
  crackerjack run -v -f  # passes
  ```
  Plus: `git grep -i ollama -- ':!*.md' ':!*.yaml.example' ':!ARCHIVED' ':!BACKUP'`
  in each repo returns no hits in production code.
- **Rollback signal**: `LLMManager.generate()` or
  `CloudWorker.execute()` raises `ValueError: provider 'ollama' not
  found` if any caller still references the removed `LLMProvider.OLLAMA`
  value. Catch on the first test run; `git revert` if rollout breaks
  a production call site.
- **Observability added**:
  - Existing OTel span `llm.fallback_chain` (in
    `mcp_common/llm/fallback.py`) already logs the chain order;
    no new span needed.
  - Log line at startup: `"LLM FallbackChain initialized: chain=[minimax, llama_server], providers=2"`
    replaces any previous ollama mention.

### Phase 2: Library-class swaps and Ollama-specific deletions (A-list)

**Goal**: Replace every code path that imports a vendor-specific
Ollama library class with the OpenAI-compat equivalent. Delete the
files that are dead code.

**Tasks**:

1. **mahavishnu**:
   - `mahavishnu/engines/agno_adapter_impl.py:218-238`:
     in `LLMProviderFactory._create_ollama_model`, replace
     `from agno.models.ollama import Ollama; Ollama(...)` with
     `from agno.models.openai import OpenAIChat; OpenAIChat(id=..., base_url=llama_server_url, api_key="no-auth")`.
     The factory method's name and signature stay the same; the
     default config flips `provider: LLMProvider.LLAMA_SERVER`
     (or simply remove the LLMProvider.OLLAMA value as in
     Phase 1 and route the "ollama" string through a different
     factory branch keyed on `LLMProvider.LLAMA_SERVER`).
     (REQ-OLLAMA-006)
   - `mahavishnu/engines/llamaindex_adapter_impl.py:39-40, 383-386`:
     swap the imports and the `Settings.embed_model = ...` /
     `Settings.llm = ...` constructors to use
     `llama_index.embeddings.openai.OpenAIEmbedding` and
     `llama_index.llms.openai.OpenAI` (or `llama_index.llms.openai_like.OpenAILike`
     for non-OpenAI-but-OpenAI-compat endpoints — fits llama-server
     and MiniMax identically).
     `ollama_base_url` and `opensearch_index_name` config keys
     stay; the embedder/llm classes are what change.
     `opensearch_endpoint` stays. `llm_model` stays as the model
     name passed to `OpenAILike(model=llm_model)`.
     (REQ-OLLAMA-007)
   - `mahavishnu/scripts/generate_ollama_embeddings.py`:
     delete the entire file (REQ-OLLAMA-011).
2. **session-buddy**:
   - `session_buddy/llm/providers/ollama_provider.py`:
     delete the entire file (305 LOC) (REQ-OLLAMA-005).
3. **oneiric**:
   - `oneiric/adapters/observability/embeddings.py:308-330, 387-425, 445-458`:
     delete the Ollama branch (the `_probe_ollama` method,
     the `ollama=True` branch in `_probe_encode_via`,
     and the `_encode_ollama` method).
     Update the probe order from
     `("llama_cpp", "ollama", "minimax", "model2vec")` to
     `("llama_cpp", "minimax", "model2vec")` (REQ-OLLAMA-008).
4. Tests:
   - `mahavishnu/tests/unit/test_agno_adapter_impl.py`: update
     the Ollama-path tests to expect `OpenAIChat` with the
     llama-server `base_url`; verify the model_id default still
     flows through.
   - `mahavishnu/tests/unit/engines/test_agno_adapter.py`,
     `tests/integration/test_agno_adapter.py`,
     `tests/unit/engines/test_agno_config_imports.py`,
     `tests/unit/engines/test_agno_teams.py`: same.
   - `mahavishnu/tests/unit/test_adapters/test_llamaindex_adapter.py`:
     replace the Ollama-class assertions with OpenAI-compat
     assertions (the test currently constructs
     `LlamaIndexAdapter(api_url="http://localhost:11434")`; flip
     to `api_url="http://localhost:8081/v1"` and verify the
     embedder/llm classes are OpenAIEmbedding/OpenAI).
   - `oneiric/tests/adapters/test_observability_embeddings.py`:
     delete the Ollama probe/encode tests; verify the
     3-backend chain (llama_cpp → minimax → model2vec) initializes
     correctly.

**Exit criteria**:
- `mahavishnu demo agno` runs against llama-server (no Ollama
  library class in the import graph).
- `mahavishnu demo llamaindex` runs against llama-server
  (no Ollama library class in the import graph).
- `git grep -n "from agno.models.ollama\|from llama_index.embeddings.ollama\|from llama_index.llms.ollama"`
  in all 6 repos returns zero hits.
- `git ls-files | xargs grep -l "ollama_provider.py"` returns
  nothing (file is deleted everywhere).
- All repo test suites pass.

#### Integration Contract (Phase 2)

- **Triggered from**: `mahavishnu demo agno` and
  `mahavishnu demo llamaindex` CLI commands; any
  `LLMProviderFactory.execute()` call that selects the local
  provider; `oneiric.adapters.observability.embeddings.EmbeddingService.initialize()`
  in any code path that runs an embedding.
- **Returns to / updates**:
  - The import graph of `mahavishnu.engines` no longer pulls in
    `agno.models.ollama` or `llama_index.embeddings.ollama`. Verify
    with `python -c "import sys; sys.modules"` after
    `LlamaIndexAdapter()` and `AgnoAdapter()` construction.
  - `oneiric.EmbeddingService.backend_name()` will return
    `"llama_cpp"` instead of `"ollama"` for local traffic.
  - `akosha.processing.embedding_dim.resolve_embedding_dim()`
    will return 768 via the `"llama_cpp"` lookup (the
    `nomic-embed-text` dimension is unchanged).
  - No persistent file change.
- **Demonstrable by**:
  ```bash
  # Live demo (requires llama-server running on :8081):
  llama-server -m qwen3.5.Q4_K_M.gguf --port 8081 --embedding &
  ./.venv/bin/mahavishnu demo llamaindex --repos <tmp> --prompt "..."
  # Returns: a real LLM completion, not "not implemented".
  ./.venv/bin/mahavishnu demo agno --repos <tmp> --prompt "..."
  # Returns: a real LLM completion via OpenAIChat.
  ```
  Plus: `python -c "import mahavishnu.engines.agno_adapter_impl"` no
  longer imports `agno.models.ollama`. Verify with
  `python -c "import sys; [print(m) for m in sys.modules if 'ollama' in m.lower()]"`.
- **Rollback signal**: `ModuleNotFoundError: agno.models.openai`
  or `ModuleNotFoundError: llama_index.embeddings.openai`
  in any test run. Catch on the first `pytest`; `git revert` if
  the live demo fails on the new classes.
- **Observability added**:
  - Log line at adapter init:
    `"llamaindex.adapter.initialized provider=openai_compat base_url=<...>"`.
  - Log line at Agno factory:
    `"agno.adapter.factory_selected provider=openai base_url=<...>"`.
  - Existing OTel span `adapter.execute` (in
    `mahavishnu/engines/llamaindex_adapter_impl.py:1125`) and
    `llamaindex.ingest` already exist; no new spans needed.

### Phase 3: Live demo wiring

**Goal**: Make `mahavishnu demo llamaindex` a real CLI command
(not a stub), and verify both demos run end-to-end against a
llama-server endpoint.

**Tasks**:

1. **mahavishnu**:
   - `mahavishnu/cli/demo_cli.py`: follow the existing
     `demo_agno` pattern (added in commit `ba832db6`):
     - Remove `"llamaindex"` from `_STUB_COSTS` (L431).
     - Add `_check_llamaindex_preconditions()`: probe `llama-index`
       is importable, probe `llama_server` is on `$PATH` (or
       `LLAMA_SERVER_URL` is set), probe a writeable working
       directory.
     - Add `@demo_app.command("llamaindex") demo_llamaindex(...)`
       callback with `--repos`, `--prompt`, `--task-type` (default
       `"default"`), `--timeout` (default 120). Body:
       `asyncio.run(asyncio.wait_for(_run_llamaindex_demo(...), timeout=timeout))`,
       exception handling mirrors `demo_prefect:403-407`.
     - Add `_run_llamaindex_demo()` async helper mirroring
       `_run_agno_demo` from the Agno fix.
2. Tests:
   - `tests/unit/cli/test_cli_wireup_invariants.py`: add
     invariant that `_STUB_COSTS` has no `"llamaindex"` key.
3. Live verification (manual, not in CI):
   ```bash
   # Operator runs llama-server separately:
   llama-server -m qwen3.5.Q4_K_M.gguf --port 8081 --embedding &
   # Then:
   ./.venv/bin/mahavishnu demo llamaindex \
     --repos /tmp/llamaindex_demo_repo \
     --prompt "Which three engines are production-ready?"
   # Returns a real completion.
   ./.venv/bin/mahavishnu demo agno \
     --repos /tmp/llamaindex_demo_repo \
     --prompt "Say hello in one short sentence."
   # Returns a real completion via OpenAIChat.
   ```

**Exit criteria**:
- `.venv/bin/mahavishnu demo llamaindex --help` shows the
  options (no longer a stub).
- Both demos produce real LLM completions against a local
  llama-server.

#### Integration Contract (Phase 3)

- **Triggered from**: `./.venv/bin/mahavishnu demo llamaindex`
  CLI invocation; `./.venv/bin/mahavishnu demo agno` CLI
  invocation; any test that imports `demo_cli.demo_llamaindex`.
- **Returns to / updates**:
  - The CLI output: a real LLM completion string.
  - `_STUB_COSTS` dict in `demo_cli.py` no longer has
    `"llamaindex"`.
  - No persistent file change.
- **Demonstrable by**:
  ```bash
  ./.venv/bin/mahavishnu demo llamaindex --help
  # shows the command and its options
  ./.venv/bin/mahavishnu demo llamaindex --repos /tmp/test_repo \
    --prompt "Test prompt"
  # returns a real completion (not "not implemented")
  ```
- **Rollback signal**: `RuntimeError: LlamaIndex dependencies not
  available` from the adapter's import-time check; or
  `RuntimeError: llama-server not reachable at <url>` from the
  preconditions check. Both fail loud and early; no silent
  fallback.
- **Observability added**:
  - OTel span `cli.demo.llamaindex.execute` with attributes
    `prompt.length`, `repos.count`, `adapter.llama_server_url`.
  - Log line `"demo.llamaindex.completed elapsed=<s> model=<id>"`.

## 6. Required Code Changes

### Production code

- [ ] `mcp_common/llm/config.py` (REQ-OLLAMA-004)
- [ ] `mahavishnu/workers/cloud_worker.py` (REQ-OLLAMA-001)
- [ ] `mahavishnu/engines/agno_adapter_impl.py` (REQ-OLLAMA-006)
- [ ] `mahavishnu/engines/llamaindex_adapter_impl.py` (REQ-OLLAMA-007)
- [ ] `mahavishnu/scripts/generate_ollama_embeddings.py` (REQ-OLLAMA-011) — DELETE
- [ ] `mahavishnu/core/config.py` (REQ-OLLAMA-010)
- [ ] `mahavishnu/core/embeddings_oneiric.py` (REQ-OLLAMA-008 client)
- [ ] `mahavishnu/core/bootstrap.py:735`
- [ ] `mahavishnu/core/errors.py:438-440`
- [ ] `mahavishnu/cli/demo_cli.py` (REQ-OLLAMA-019 — live demo)
- [ ] `mahavishnu/cli/config_validator.py:147`
- [ ] `mahavishnu/core/production_readiness.py:87`
- [ ] `mahavishnu/core/routing.py:54` (verify no test depends)
- [ ] `mahavishnu/settings/models.yaml` (REQ-OLLAMA-012)
- [ ] `mahavishnu/settings/embeddings.yaml` (REQ-OLLAMA-012)
- [ ] `mahavishnu/settings/mahavishnu.yaml` (REQ-OLLAMA-012)
- [ ] `mahavishnu/settings/local.yaml.example` (REQ-OLLAMA-012)
- [ ] `mahavishnu/settings/mahavishnu.yaml.example` (REQ-OLLAMA-012)
- [ ] `session_buddy/llm/providers/ollama_provider.py` (REQ-OLLAMA-005) — DELETE
- [ ] `session_buddy/llm/providers/__init__.py` (REQ-OLLAMA-005)
- [ ] `session_buddy/llm/__init__.py` (REQ-OLLAMA-005)
- [ ] `session_buddy/llm/security.py` (REQ-OLLAMA-002)
- [ ] `session_buddy/llm_providers.py` (REQ-OLLAMA-002)
- [ ] `session_buddy/settings.py` (REQ-OLLAMA-013)
- [ ] `session_buddy/config/feature_flags.py` (REQ-OLLAMA-013)
- [ ] `session_buddy/reflection/embeddings.py` (REQ-OLLAMA-014)
- [ ] `session_buddy/reflection/database.py:29`
- [ ] `session_buddy/adapters/reflection_adapter_oneiric.py`
- [ ] `session_buddy/mcp/oneiric_runtime.py`
- [ ] `session_buddy/utils/lazy_imports.py`
- [ ] `session_buddy/settings/session-buddy.yaml` (REQ-OLLAMA-013)
- [ ] `crackerjack/adapters/ai/unified.py` (REQ-OLLAMA-003)
- [ ] `crackerjack/adapters/ai/registry.py` (REQ-OLLAMA-015)
- [ ] `crackerjack/cli/handlers/provider_selection.py` (REQ-OLLAMA-015)
- [ ] `crackerjack/cli/options.py:674`
- [ ] `crackerjack/config/settings.py` (REQ-OLLAMA-016)
- [ ] `crackerjack/models/semantic_models.py` (REQ-OLLAMA-016)
- [ ] `crackerjack/fixers/security.py`
- [ ] `oneiric/adapters/observability/embeddings.py` (REQ-OLLAMA-008)
- [ ] `oneiric/adapters/observability/embedding_settings.py` (REQ-OLLAMA-009)
- [ ] `oneiric/core/substrate_settings.py` (REQ-OLLAMA-009)
- [ ] `oneiric/adapters/llm/llm_interface.py` (REQ-OLLAMA-009)
- [ ] `akosha/processing/embedding_dim.py` (REQ-OLLAMA-017)
- [ ] `akosha/storage/hot_store.py`

### Tests

- [ ] All 6 repos: drop ollama test cases per the Phase 1 / Phase 2
  per-repo task lists (see inventory report, B-list test files).
- [ ] `session_buddy/tests/unit/test_llm_providers_ollama.py` — DELETE
- [ ] `mahavishnu/tests/unit/test_adapters/test_llamaindex_adapter.py` —
  flip to llama-server base_url
- [ ] `mahavishnu/tests/unit/engines/test_agno_adapter.py` and siblings —
  flip factory expectations to `OpenAIChat`
- [ ] `mahavishnu/tests/unit/cli/test_cli_wireup_invariants.py` —
  add `_STUB_COSTS` has no `"llamaindex"` invariant
- [ ] `oneiric/tests/adapters/test_observability_embeddings.py` —
  drop Ollama probe/encode cases; verify 3-backend chain

## 7. Validation Matrix

| Check | Command | Expected outcome | Evidence |
|---|---|---|---|
| No Ollama in production source | `git grep -in ollama -- ':!*docs' ':!*CHANGELOG.md' ':!*ARCHIVED' ':!*BACKUP' ':!*tests' ':!*.md' ':!*.yaml.example'` | Zero hits in `*.py` and `*.yaml` | Test log |
| LLMManager chain | `python -c "from session_buddy.llm_providers import LLMManager; m = LLMManager(); print(m._chain._providers)"` | `["minimax", "llama_server"]` | Test log |
| CloudWorker chain | `python -c "from mahavishnu.workers.cloud_worker import _build_fallback_chain, CloudWorkerConfig; print(_build_fallback_chain(CloudWorkerConfig())._providers)"` | `["minimax", "llama_server"]` | Test log |
| FallbackChainCodeFixer chain | `python -c "from crackerjack.adapters.ai.unified import FallbackChainCodeFixer; ..."` | 2-provider chain | Test log |
| Agno factory uses OpenAIChat | `python -c "import mahavishnu.engines.agno_adapter_impl; import inspect; src = inspect.getsource(...)"` | String contains `from agno.models.openai import OpenAIChat`; does not contain `from agno.models.ollama import Ollama` | Source inspection |
| LlamaIndex adapter uses OpenAIEmbedding | Same as above for `llamaindex_adapter_impl` | String contains `from llama_index.embeddings.openai import OpenAIEmbedding`; does not contain `from llama_index.embeddings.ollama import OllamaEmbedding` | Source inspection |
| `OllamaProvider` is gone | `git ls-files | xargs grep -l "OllamaProvider" 2>/dev/null` | Zero output (file deleted) | Test log |
| Live demo: llamaindex | `./.venv/bin/mahavishnu demo llamaindex --repos <tmp> --prompt "..."` | Real LLM completion | Screenshot / captured stdout |
| Live demo: agno | `./.venv/bin/mahavishnu demo agno --repos <tmp> --prompt "..."` | Real LLM completion | Screenshot / captured stdout |
| Crackerjack merge gate | `crackerjack run -v -f` | Pass | Test log |
| pytest | `pytest tests/unit -q` | Pass (modulo known pre-existing failures) | Test log |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Operator currently runs Ollama in production; we delete the support | Medium | `feedback-no-backwards-compat-pre-1.0.md` says no deprecation. Operator migrates by switching to llama-server (one binary, one config). |
| llama-server not available on the operator's machine | Low | Document the install in the demo's preconditions; the preconditions check fails loud. |
| Pydantic-AI adapter breaks (Pydantic-AI's `ollama:` prefix is library-specific) | Low | Adapter is secondary/optional; the demo path doesn't use it. The reference is left in place (deleted in a follow-up). |
| OpenSearch KNN plugin still missing on the operator's machine | Medium | Phase 2's LlamaIndex adapter still works via the in-memory vector store fallback (already exercised in the 2026-10-16 demo). Phase 3's live demo uses the same fallback. |
| Hidden call sites referencing `OllamaProvider` or `LLMProvider.OLLAMA` we didn't find | Low | Phase 1's "Rollback signal" + the git grep validation matrix catches these on the first test run. |
| Cookie-cutter `crackerjack` URLs (e.g. typo `http://localhost: 11434` with extra space) hide the cleanup | Low | The inventory found one such typo in `crackerjack/adapters/ai/unified.py:44-54`. Phase 1 fixes the typo as part of the chain rewrite. |
| Cross-repo coordination cost (6 repos, 3 PRs) | Medium | Each PR is a separate merge; crackerjack gates per repo. Sequence: mcp-common → mahavishnu → session-buddy → crackerjack → oneiric → akosha. |

## 9. Decision Rule

This plan is "done" when:
- A user can run `./.venv/bin/mahavishnu demo llamaindex --prompt "..."` against a local llama-server and get a real LLM completion.
- The Phase 1 + Phase 2 + Phase 3 exit criteria all pass.
- The git grep validation matrix returns zero ollama hits in production code across all 6 repos.
- Each repo's `crackerjack run -v -f` passes.
- Each repo's pytest suite passes (modulo known pre-existing failures).

If scope pressure forces a cut: **drop Phase 3** (the live demo).
The library-class swaps in Phase 2 are the load-bearing changes;
the demo is a one-command verification surface that can be added
later as a follow-up plan.

## References

- `mahavishnu/docs/specs/2026-09-27-shared-bodai-substrate-design.md` —
  oneiric substrate (embedding service, LLM provider surface)
- `mahavishnu/docs/plans/2026-10-15-bifrost-gateway-wiring.md` —
  blocks on this plan; the gateway plan must land first (it
  re-shapes how `LLMProvider` is consumed)
- `mahavishnu/docs/plans/2026-05-10-minimax27-provider-migration.md` —
  the precedent for a major LLM-provider migration; the migration
  playbook in that plan is the template for the per-repo merges here
- `mahavishnu/.claude/decisions/` — relevant governance decisions
  (none directly contradict this plan)
- `mahavishnu/CLAUDE.md` § "Crackerjack-Compliant Code" — gate and
  conventions
- `mcp_common/mcp_common/llm/fallback.py` — the canonical
  FallbackChain implementation
- `mahavishnu/workers/cloud_worker.py:78-113` — the canonical
  three-tier chain pattern
- `feedback-no-backwards-compat-pre-1.0.md` — no deprecation windows
- `feedback-crackerjack-merge-gate-is-vf.md` — gate is
  `crackerjack run -v -f`
- `bodai-pre-1.0-merge-policy.md` — direct merge to `main`,
  no PRs
- `git-author-email-correct-domain.md` — author email must be
  `les@wedgwoodwebworks.com` (not `.local`)
