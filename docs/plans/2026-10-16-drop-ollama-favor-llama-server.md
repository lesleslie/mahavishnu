---
status: draft
role: implementation
kind: plan
date: 2026-10-16
last_reviewed: 2026-10-16
superseded_by: null
blocks_on: []
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
- All `LLMProvider.OLLAMA` / `ProviderID.OLLAMA` / `EmbeddingProvider.OLLAMA`
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
4. **Wire llama-server into a live demo** (Phase 2) so the user has a
   one-command path to verify the cleanup actually works.

## 3. Non-Goals

- Drop MiniMax. The cloud LLM provider stays; the FallbackChain still
  prefers it.
- Migrate any non-Ollama local LLM (e.g. a future vLLM) — that is a
  separate decision.
- Operator-facing install docs for llama-server. Phase 2's demo only
  assumes the operator has `llama-server` on `$PATH`; how they
  downloaded a GGUF is out of scope (per user direction, no docker).
- Docker / docker-compose changes (per user direction).
- Operator runbook / migration guide for users currently running
  Ollama. Operators switch to llama-server (one binary, one config);
  the user direction is "no backwards compat" so no migration guide.
- The full `mahavishnu demo llamaindex` CLI wrapper in this plan —
  Phase 2 implements a live demo via direct adapter invocation
  (mirroring how the Agno fix in commit `ba832db6` wired the Agno
  demo). The full CLI Typer wiring is the Phase 2 deliverable
  itself, not a separate follow-up.

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
  base_url=llama_server_url, api_key="no-auth")` (Agno already uses
  `OpenAIChat` for the MiniMax path at L240-262 in the same file).
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

### Streaming-usage accounting gap (pre-existing, not a regression)

llama-server does not emit usage in streaming responses. This is a
known OpenAI-compat gap shared with Ollama — neither is a
regression introduced by this plan. Non-streaming usage accounting
works. Documented as a known limitation; no fix in this plan.

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
    title: "mahavishnu settings/*.yaml ollama:* and llm.ollama_base_url entries removed"
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
  - id: REQ-OLLAMA-020
    title: "pyproject.toml adds llama-index-embeddings-openai and llama-index-llms-openai-like as dependencies or extras"
  - id: REQ-OLLAMA-021
    title: "LLMProvider.LLAMA_SERVER enum value added to mahavishnu.core.config.LLMProvider"
  - id: REQ-OLLAMA-022
    title: "_PROVIDER_FACTORY_METHODS rekeyed from LLMProvider.OLLAMA to LLMProvider.LLAMA_SERVER; AgnoLLMConfig.provider default updated consistently"
  - id: REQ-OLLAMA-023
    title: "Pydantic-AI adapter ollama: provider_prefix entry removed (5-line change, folded into Phase 1 per wire-up-contract)"
  - id: REQ-OLLAMA-024
    title: "Core config.py parents[2] loader anchor (from commit 8580fe76) preserved untouched"
```

## 5. Implementation Phases

The plan lands in **2 phases**, each with **per-repo merge cycles**,
in dependency order. Per `bodai-pre-1.0-merge-policy.md` and
`MAHAVISHNU_AUTO_MERGE=1` default, each per-repo merge is a direct
squash-merge to local `main` via the SessionEnd hook. There are no
GitHub PRs.

**Why 2 phases, not 3**: a 3-phase plan (cleanup → swap library classes
→ live demo) leaves `mahavishnu` broken between Phase 1 and Phase 2
because `LLMProvider.OLLAMA` is used in the
`_PROVIDER_FACTORY_METHODS` dict literal at
`mahavishnu/engines/agno_adapter_impl.py:127`. Deleting the enum
value in Phase 1 causes `AttributeError` at class-definition time
before Phase 2 can land. Collapsing Phase 1 + Phase 2 into a single
"Drop Ollama in source" phase eliminates the broken-tree window.

The other 5 repos split cleanly (Phase 1 is config/schema cleanup
with no library-class swap), so for those repos the per-repo
merge-cycle is one. For mahavishnu, it's also one — but the merge
combines the B-list cleanup with the A-list library-class swap.

**Per-repo merge order** (driven by dependency on mcp-common's
`fallback_chain` default change):

1. **mcp-common** — changes the default `fallback_chain` first;
   downstream repos pick up the new default via their existing
   `mcp-common>=X` pin (no coordinated version bump needed; per
   `feedback-mcp-common-version-bump-is-user.md`, the user runs
   `crackerjack run -p <level>` from their shell to bump+tag+publish
   when ready).
2. **session-buddy** — drops `ollama_provider.py` + re-exports + the
   `LLMManager` chain entry. Independent of mahavishnu.
3. **oneiric** — drops the Ollama branch of the embedding probe chain
   and the `ollama_*` settings fields. Independent of mahavishnu.
4. **crackerjack** — drops `ProviderID.OLLAMA` and the chain entry.
   Independent of mahavishnu.
5. **akosha** — drops the `BACKEND_DEFAULT_DIMS["ollama"]` entry.
   Smallest scope; no library-class case.
6. **mahavishnu** — drops the B-list + A-list (Agno + LlamaIndex +
   script deletion). Heaviest scope; lands last so the other 5 repos
   don't transiently consume the old `LLMProvider.OLLAMA` value.

### Phase 1: Drop Ollama in source (per-repo merge cycles)

**Goal**: Remove every reference to Ollama in production source across
all 6 repos. After this phase, the production runtime no longer
touches Ollama in any code path.

**Phase 0 (preflight, lands first in any order):**
- **Ecosystem-wide grep**: `rg -i "ollama" /Users/les/Projects/` —
  search beyond the 6 core repos for any Bodai ecosystem member
  (web_reader, bifrost, mahavishnu-web, bodai-crow, etc.) that
  references Ollama. Document any finding in a follow-up plan if
  it falls outside the 6 core repos' scope. (Catches anything the
  6-repo inventory missed.)

**Tasks** (per-repo, in the merge order above):

#### 1a. mcp-common (REQ-OLLAMA-004)

- `mcp_common/llm/config.py`: `fallback_chain` default →
  `["minimax", "llama_server"]` (REQ-OLLAMA-004).
- `mcp_common/tests/test_llm.py` + `mcp_common/tests/unit/test_llm_additional.py`:
  drop all `ollama` test cases; keep the `llama_server` ones.

#### 1b. session-buddy (REQ-OLLAMA-002, REQ-OLLAMA-005, REQ-OLLAMA-013, REQ-OLLAMA-014)

- `session_buddy/llm/providers/ollama_provider.py`:
  delete the entire file (304 LOC) (REQ-OLLAMA-005).
- `session_buddy/llm/providers/__init__.py:11, 17` and
  `session_buddy/llm/__init__.py:21, 36`:
  delete the `OllamaProvider` re-exports (REQ-OLLAMA-005).
- `session_buddy/llm/security.py:56-58, 132`:
  drop `"ollama"` from the local-service set; the remaining set is
  `{"llama_server"}` (REQ-OLLAMA-002).
- `session_buddy/llm_providers.py:501-577`:
  `LLMManager._build_chain` no longer registers `ollama`; the chain
  becomes `["minimax", "llama_server"]` (REQ-OLLAMA-002).
- `session_buddy/settings.py:113, 116, 121-127`:
  drop `ollama_base_url`, `ollama_default_model`, drop `"ollama"` from
  `fallback_providers` default (REQ-OLLAMA-013).
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

#### 1c. oneiric (REQ-OLLAMA-008, REQ-OLLAMA-009)

- `oneiric/adapters/observability/embeddings.py:308-330, 387-425, 445-458`:
  delete the Ollama branch (the `_probe_ollama` method,
  the `ollama=True` branch in `_probe_encode_via`,
  and the `_encode_ollama` method).
  Update the probe order from
  `("llama_cpp", "ollama", "minimax", "model2vec")` to
  `("llama_cpp", "minimax", "model2vec")` (REQ-OLLAMA-008).
- `oneiric/adapters/observability/embedding_settings.py:17-77`:
  drop `ollama_*` fields (REQ-OLLAMA-009).
- `oneiric/core/substrate_settings.py:198-208, 240-246`:
  drop `ollama` from `embedding__backend` Literal (REQ-OLLAMA-009).
- `oneiric/adapters/llm/llm_interface.py:21`:
  drop `LLMProvider.OLLAMA` enum entry (REQ-OLLAMA-009).
- Tests: drop ollama test cases from
  `oneiric/tests/adapters/test_observability_embeddings.py`.

#### 1d. crackerjack (REQ-OLLAMA-003, REQ-OLLAMA-015, REQ-OLLAMA-016)

- `crackerjack/adapters/ai/unified.py:19-72`:
  `_build_llm_settings` no longer registers `ollama`
  (REQ-OLLAMA-003). Also fix the `http://localhost: 11434` cookie-cutter
  typo (extra space) in the process.
- `crackerjack/adapters/ai/registry.py:9-12, 29-57, 78-82`:
  delete `ProviderID.OLLAMA` enum + `PROVIDER_INFO["ollama"]` entry
  (REQ-OLLAMA-015). `get_code_fixer` returns
  `FallbackChainCodeFixer` with the 2-provider chain.
- `crackerjack/cli/handlers/provider_selection.py:48-51, 190-196`:
  remove the Ollama option from the interactive selector
  (REQ-OLLAMA-015).
- `crackerjack/cli/options.py:674`: update help text.
- `crackerjack/config/settings.py:98-115`:
  `ai_providers` Literal collapses to `["minimax", "llama_server"]`;
  `ai_provider` default stays `"minimax"`;
  drop `ollama_base_url`, `ollama_model`, `ollama_timeout`
  (REQ-OLLAMA-016).
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

#### 1e. akosha (REQ-OLLAMA-017)

- `akosha/processing/embedding_dim.py:45-58, 61-141`:
  drop `BACKEND_DEFAULT_DIMS["ollama"]` entry (REQ-OLLAMA-017).
- `akosha/storage/hot_store.py:103, 109`: comment update.
- Tests: drop ollama test cases from
  `akosha/tests/unit/test_embeddings.py`,
  `akosha/tests/unit/processing/test_embedding_dim.py`.

#### 1f. mahavishnu (REQ-OLLAMA-001, REQ-OLLAMA-006, REQ-OLLAMA-007, REQ-OLLAMA-010, REQ-OLLAMA-011, REQ-OLLAMA-012, REQ-OLLAMA-021, REQ-OLLAMA-022, REQ-OLLAMA-023, REQ-OLLAMA-024)

This is the heaviest merge. It combines the B-list (config/schema
cleanup) with the A-list (Agno + LlamaIndex library-class swaps +
factory rekey + script deletion + new enum value). The Phase 1 / 2
split from earlier drafts is collapsed here to avoid a broken tree
between merges (see "Why 2 phases, not 3" above).

**B-list (config / schema / settings cleanup):**

- `mahavishnu/workers/cloud_worker.py`:
  providers dict (no `ollama`), `fallback_chain` (REQ-OLLAMA-001),
  `_has_local_fallback` probe (no `shutil.which("ollama")`).
- `mahavishnu/core/config.py`:
  - `LLMProvider.OLLAMA` enum entry deleted (REQ-OLLAMA-010).
  - `LLMProvider.LLAMA_SERVER` enum value added (REQ-OLLAMA-021).
  - `LLMProvider.OLLAMA: None` (key handling in `AgnoLLMConfig`
    validator at L202) deleted.
  - `AgnoLLMConfig.provider` default updated to
    `LLMProvider.LLAMA_SERVER` (REQ-OLLAMA-022).
  - `LLMConfig.ollama_base_url` field deleted (REQ-OLLAMA-010).
  - **Preserve the `parents[2]` loader anchor at L3319** from
    commit `8580fe76` — do not touch (REQ-OLLAMA-024).
- `mahavishnu/core/embeddings_oneiric.py`:
  `EmbeddingConfig.ollama_base_url` deleted.
- `mahavishnu/core/bootstrap.py:735`:
  drop the `if actual_provider == "ollama"` branch.
- `mahavishnu/core/errors.py:438-440`:
  update recovery hint strings.
- `mahavishnu/cli/config_validator.py:147`:
  drop the `_ensure_http_url(settings.llm.ollama_base_url, ...)` line.
- `mahavishnu/core/production_readiness.py:87`:
  drop `"ollama_base_url"` from validated keys.
- `mahavishnu/core/routing.py:54`:
  drop the `\bollama\b` line (the project name "ollama" is
  correctly spelled; the line is removed because the project is
  being dropped, not because it was a typo).
- `mahavishnu/settings/models.yaml:76-97`:
  drop the `ollama:` provider block (REQ-OLLAMA-012).
- `mahavishnu/settings/embeddings.yaml:31-53`:
  drop the ollama-specific config; keep `provider: fastembed` default
  (REQ-OLLAMA-012).
- `mahavishnu/settings/mahavishnu.yaml:45`:
  drop `llm.ollama_base_url` (REQ-OLLAMA-012).
- `mahavishnu/settings/local.yaml.example:30, 33`,
  `mahavishnu/settings/mahavishnu.yaml.example:18, 19`:
  drop ollama lines (REQ-OLLAMA-012).
- Tests: drop `ollama` test cases from
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

**A-list (library-class swap + dead-code deletion):**

- `mahavishnu/engines/agno_adapter_impl.py:218-238`:
  replace `from agno.models.ollama import Ollama; Ollama(...)` with
  `from agno.models.openai import OpenAIChat; OpenAIChat(id=...,
  base_url=llama_server_url, api_key=None)`. Verify `api_key=None`
  is accepted by llama-server (some builds reject any bearer
  token; the verification step is a one-line `curl` against
  `http://localhost:8081/v1/chat/completions` with
  `Authorization: Bearer no-auth` — if rejected, fall back to
  `api_key="no-auth"`). (REQ-OLLAMA-006)
- `mahavishnu/engines/agno_adapter_impl.py:127` and
  `_PROVIDER_FACTORY_METHODS`: rekey from `LLMProvider.OLLAMA` to
  `LLMProvider.LLAMA_SERVER` (REQ-OLLAMA-022).
  Also verify the second construction site at
  `mahavishnu/engines/agno_adapter_impl.py:1032` (via
  `_resolve_legacy_llm_config()`) — rekey consistently.
- `mahavishnu/engines/llamaindex_adapter_impl.py`:
  - Add `llama-index-embeddings-openai` and
    `llama-index-llms-openai-like` to `pyproject.toml` (REQ-OLLAMA-020)
    **before** swapping imports. The Phase 2 implementer must NOT
    commit the import swap without the deps landing — `ModuleNotFoundError`
    would break the production runtime.
  - Replace `from llama_index.embeddings.ollama import OllamaEmbedding`
    with `from llama_index.embeddings.openai import OpenAIEmbedding`
    (lines 39, 49).
  - Replace `from llama_index.llms.ollama import Ollama` with
    `from llama_index.llms.openai_like import OpenAILike` (line 40, 50).
  - Replace `Settings.embed_model = OllamaEmbedding(model_name=..., base_url=...)`
    with `Settings.embed_model = OpenAIEmbedding(model_name=...,
    api_base=..., api_key=None)` (lines 383-384).
    **Constructor parameter renames** (a naive copy-paste swap
    fails with `TypeError`):
    | OllamaEmbedding param | OpenAIEmbedding param |
    |---|---|
    | `model_name` | `model_name` (unchanged) |
    | `base_url` | `api_base` |
    | (none) | `api_key=None` |
    | `keep_alive` | no equivalent (drop) |
    | `format="json"` | `additional_kwargs={"response_format": {"type": "json_object"}}` (only if needed) |
  - Replace `Settings.llm = Ollama(model=..., base_url=...)` with
    `Settings.llm = OpenAILike(model=llm_model, api_base=...,
    api_key=None, is_chat_model=True, context_window=32768,
    is_function_calling_model=False)` (lines 385-386).
    **OpenAILike-specific kwargs** (the defaults are wrong for our
    use case — `is_chat_model=False` posts to `/v1/completions`
    not `/v1/chat/completions`; `context_window=3900` truncates a
    32k-context Qwen3.5 silently):
    | OpenAILike kwarg | Default | Required for our use case |
    |---|---|---|
    | `is_chat_model` | `False` | `True` |
    | `context_window` | `3900` | `32768` (matches Qwen3.5) |
    | `is_function_calling_model` | `False` | `False` (LlamaIndex adapter doesn't use tools) |
  - Update the `LLAMAINDEX_AVAILABLE` `try/except ImportError` block
    (lines 34-56) to also handle the new dependencies in the
    `MagicMock` fallback (`OpenAIEmbedding = MagicMock(name="OpenAIEmbedding")`,
    etc.) so import-block symmetry is preserved.
  - Update `get_health` (lines 1230-1237) to report the new
    provider class names.
  - (REQ-OLLAMA-007)
- `mahavishnu/scripts/generate_ollama_embeddings.py`:
  delete the entire file (REQ-OLLAMA-011).
- `mahavishnu/adapters/ai/pydantic_ai_adapter.py:86, 99, 258`:
  remove the `"ollama" → "ollama"` mapping in `provider_prefixes`
  and the corresponding ASCII-diagram reference (5-line change,
  folded into Phase 1 per the wire-up-contract —
  REQ-OLLAMA-023).

**Doc updates** (across all 6 repos, in this same per-repo merge):

- `mahavishnu/CLAUDE.md` "LLM Provider Configuration" section:
  rewrite to describe MiniMax → llama-server (no Ollama tier).
- `mahavishnu/docs/ROUTING_GUIDE.md`, `docs/CONFIGURATION.md`,
  `docs/CLI_REFERENCE.md`: same.
- `mahavishnu/docs/specs/`, `docs/adr/`, `docs/runbooks/`,
  `docs/architecture/`, `docs/ingestion/`, `docs/grafana/`,
  `docs/guides/`, `docs/followups/`, `docs/reviews/`,
  `docs/src/adapters/llamaindex.md`, `docs/src/adapters/agno.md`:
  remove "Ollama" references (the plan author reviewed the
  inventory; ~15 doc files contain Ollama mentions).
- `mahavishnu/examples/goal_driven_team_tutorial.py`,
  `examples/cli_ingestion_examples.sh`,
  `examples/pydantic_ai_adapter_example.py`: same.
- Same doc sweep in session-buddy, crackerjack, oneiric, akosha,
  mcp-common (`session_buddy/README.md`, `ARCHITECTURE.md`,
  `CLAUDE.md`, `docs/architecture/`, `docs/API_KEY_SETUP.md`, etc.).

**Exit criteria** (Phase 1):
- `git grep -in "ollama\|Ollama\|OLLAMA" -- ':!*docs' ':!*CHANGELOG.md' ':!*ARCHIVED' ':!*BACKUP' ':!*tests' ':!*.md' ':!*.yaml.example'`
  returns zero hits in the production source tree of all 6 repos.
- `mahavishnu/engines/agno_adapter_impl.py` imports
  `from agno.models.openai import OpenAIChat` and not
  `from agno.models.ollama import Ollama`.
- `mahavishnu/engines/llamaindex_adapter_impl.py` imports
  `from llama_index.embeddings.openai import OpenAIEmbedding`
  and `from llama_index.llms.openai_like import OpenAILike`,
  not the ollama classes.
- `session_buddy/llm/providers/ollama_provider.py` is deleted
  (no entry in `git ls-files`).
- `crackerjack run -v -f` passes in every repo (per the user's
  `feedback-crackerjack-merge-gate-is-vf`).
- Each repo's pytest suite passes (modulo known pre-existing
  failures from the recent `raise Exception` commit).
- The `parents[2]` loader anchor at `mahavishnu/core/config.py:3319`
  is unchanged (verified via `git diff HEAD~1 -- mahavishnu/core/config.py`).

#### Integration Contract (Phase 1)

- **Triggered from**: Any code path that imports
  `mcp_common.llm.fallback.FallbackChain` or its callers
  (`mahavishnu.workers.cloud_worker.CloudWorker.__init__`,
  `session_buddy.llm_providers.LLMManager.__init__`,
  `crackerjack.adapters.ai.unified.FallbackChainCodeFixer.__init__`).
  Also: any code path that reads `mahavishnu.settings.models.yaml`
  or any of the per-repo `settings/{repo}.yaml` files. Also:
  `LLMProviderFactory._create_llama_server_model` (new factory
  branch) at `mahavishnu/engines/agno_adapter_impl.py:218-238` (renamed
  from `_create_ollama_model`).
- **Returns to / updates**:
  - `LLMSettings.fallback_chain` is now `["minimax", "llama_server"]`
    by default. The `providers` dict no longer has an `"ollama"` key.
  - `LLMProvider` enum (mahavishnu, oneiric), `EmbeddingProvider`
    enum (mahavishnu), `ProviderID` enum (crackerjack) no longer
    have an `OLLAMA` value. `LLMProvider.LLAMA_SERVER` is added.
  - `AgnoLLMConfig.provider` defaults to `LLMProvider.LLAMA_SERVER`.
  - `_PROVIDER_FACTORY_METHODS` keys on `LLMProvider.LLAMA_SERVER`.
  - No persistent file or DB change; settings YAMLs are the
    source of truth.
- **Demonstrable by**:
  ```bash
  # In each repo:
  grep -rin "ollama\|Ollama\|OLLAMA" \
    --include="*.py" --include="*.yaml" \
    --exclude-dir=.venv --exclude-dir=node_modules \
    --exclude-dir=__pycache__ --exclude-dir=.git
  # Returns: zero hits.

  # In mahavishnu:
  python -c "import mahavishnu.engines.llamaindex_adapter_impl; import sys; assert not any('ollama' in m.lower() for m in sys.modules); print('OK')"
  # Returns: OK (verifies no Ollama library is imported transitively)

  # In session-buddy:
  git ls-files | grep ollama_provider.py
  # Returns: zero hits (file deleted)

  # In each repo:
  pytest tests/unit -q  # passes
  crackerjack run -v -f  # passes
  ```
- **Rollback signal**: `LLMManager.generate()` or
  `CloudWorker.execute()` raises `ValueError: provider 'ollama' not
  found` if any caller still references the removed
  `LLMProvider.OLLAMA` value. Catch on the first test run;
  `git revert` if rollout breaks a production call site.
  Separately, `ModuleNotFoundError: llama_index.embeddings.openai`
  or `ModuleNotFoundError: llama_index.llms.openai_like` if the
  `pyproject.toml` deps weren't added before the import swap.
- **Observability added**:
  - Existing OTel span `llm.fallback_chain` (in
    `mcp_common/llm/fallback.py`) already logs the chain order;
    no new span needed.
  - **New log line** at startup:
    `"LLM FallbackChain initialized: chain=[minimax, llama_server], providers=2"`
    (replaces any previous ollama mention).
  - **New log line** at Agno factory:
    `"agno.adapter.factory_selected provider=llama_server base_url=<...>"`
    (replaces the ollama-keyed log).

### Phase 2: Live demo wiring

**Goal**: Make `mahavishnu demo llamaindex` a real CLI command
(not a stub), and verify the Phase 1 swap works end-to-end against
a llama-server endpoint.

**Tasks**:

1. `mahavishnu/cli/demo_cli.py`:
   - Follow the existing `demo_agno` pattern (added in commit
     `ba832db6`):
     - Remove `"llamaindex"` from `_STUB_COSTS` (the dict lives at
       `demo_cli.py:654-655`, not L431 as the inventory report
       said; the implementer must verify the actual line number
       in the current file).
     - Add `_check_llamaindex_preconditions()`: probe
       `llama-index-embeddings-openai` and `llama-index-llms-openai-like`
       are importable, probe `llama-server` is on `$PATH` (or
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
   - `tests/unit/cli/test_cli_wireup_invariants.py`:
     add invariant that `_STUB_COSTS` has no `"llamaindex"` key.
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

**Embedding-quality caveat for the demo**: the demo uses a single
Qwen3.5 GGUF for both chat and embeddings. This is for
one-GGUF convenience only; production embeddings should use a
dedicated embedding model (e.g. `nomic-embed-text-v1.5.Q8_0.gguf`).
Documented as a known limitation; no fix in this plan.

**Vector store caveat**: LlamaIndex's `SimpleVectorStore` (the
fallback when OpenSearch KNN plugin is missing) is **not
persistent across restarts**. Pre-existing condition; documented
here for clarity.

**Degraded-mode note** (2-tier FallbackChain): if both MiniMax and
llama-server are unreachable, `CloudWorker.execute()` and the
Agno/LlamaIndex adapters raise `RuntimeError` after retry
exhaustion. The oneiric embedding chain still has 3 tiers
(llama_cpp → minimax → model2vec) — `model2vec` is
static-embeddings only; no inconsistency.

**Exit criteria** (Phase 2):
- `.venv/bin/mahavishnu demo llamaindex --help` shows the
  options (no longer a stub).
- Both demos produce real LLM completions against a local
  llama-server.
- `git grep -n "llamaindex" -- 'mahavishnu/cli/demo_cli.py'` shows
  the new command is registered.

#### Integration Contract (Phase 2)

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

## 5.5 Per-repo commit discipline

Each per-repo merge is a **separate squash-merge to local `main`**
per the trunk-based agent-review workflow. Per
`feedback-no-claude-code-coauthor-attribution.md`, no
`Co-Authored-By` trailer. Per `git-author-email-correct-domain.md`,
author email is `les@wedgwoodwebworks.com` (not `.local`). Per
`feedback-bodai-push-is-user-controlled.md`, the user runs
`git push` and `crackerjack run -p <level>` from their own shell —
**the implementer does not push to origin**. mcp-common is a
dependency for the other 5 repos, so the user may also run
`crackerjack run -p <level>` to bump+tag+publish a new mcp-common
version after Phase 1 lands; the implementer does NOT bump the
mcp-common version themselves.

## 6. Required Code Changes

### Production code (mahavishnu)

- [ ] `mahavishnu/workers/cloud_worker.py` (REQ-OLLAMA-001)
- [ ] `mahavishnu/engines/agno_adapter_impl.py` (REQ-OLLAMA-006, REQ-OLLAMA-022)
- [ ] `mahavishnu/engines/llamaindex_adapter_impl.py` (REQ-OLLAMA-007)
- [ ] `mahavishnu/pyproject.toml` (REQ-OLLAMA-020 — add deps)
- [ ] `scripts/generate_ollama_embeddings.py` (REQ-OLLAMA-011) — DELETE
- [ ] `mahavishnu/core/config.py` (REQ-OLLAMA-010, REQ-OLLAMA-021, REQ-OLLAMA-022, REQ-OLLAMA-024)
- [ ] `mahavishnu/core/embeddings_oneiric.py`
- [ ] `mahavishnu/core/bootstrap.py:735`
- [ ] `mahavishnu/core/errors.py:438-440`
- [ ] `mahavishnu/cli/demo_cli.py` (REQ-OLLAMA-018, REQ-OLLAMA-019 — live demo)
- [ ] `mahavishnu/cli/config_validator.py:147`
- [ ] `mahavishnu/core/production_readiness.py:87`
- [ ] `mahavishnu/core/routing.py:54`
- [ ] `mahavishnu/adapters/ai/pydantic_ai_adapter.py` (REQ-OLLAMA-023)
- [ ] `settings/models.yaml` (REQ-OLLAMA-012)
- [ ] `settings/embeddings.yaml` (REQ-OLLAMA-012)
- [ ] `settings/mahavishnu.yaml` (REQ-OLLAMA-012)
- [ ] `settings/local.yaml.example` (REQ-OLLAMA-012)
- [ ] `settings/mahavishnu.yaml.example` (REQ-OLLAMA-012)

### Production code (session-buddy)

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
- [ ] `settings/session-buddy.yaml` (REQ-OLLAMA-013)

### Production code (crackerjack)

- [ ] `crackerjack/adapters/ai/unified.py` (REQ-OLLAMA-003)
- [ ] `crackerjack/adapters/ai/registry.py` (REQ-OLLAMA-015)
- [ ] `crackerjack/cli/handlers/provider_selection.py` (REQ-OLLAMA-015)
- [ ] `crackerjack/cli/options.py:674`
- [ ] `crackerjack/config/settings.py` (REQ-OLLAMA-016)
- [ ] `crackerjack/models/semantic_models.py` (REQ-OLLAMA-016)
- [ ] `crackerjack/fixers/security.py`

### Production code (oneiric)

- [ ] `oneiric/adapters/observability/embeddings.py` (REQ-OLLAMA-008)
- [ ] `oneiric/adapters/observability/embedding_settings.py` (REQ-OLLAMA-009)
- [ ] `oneiric/core/substrate_settings.py` (REQ-OLLAMA-009)
- [ ] `oneiric/adapters/llm/llm_interface.py` (REQ-OLLAMA-009)

### Production code (akosha)

- [ ] `akosha/processing/embedding_dim.py` (REQ-OLLAMA-017)
- [ ] `akosha/storage/hot_store.py`

### Production code (mcp-common)

- [ ] `mcp_common/llm/config.py` (REQ-OLLAMA-004)

### Tests (all 6 repos)

- [ ] Drop ollama test cases per the per-repo task lists above.
- [ ] `session_buddy/tests/unit/test_llm_providers_ollama.py` — DELETE
- [ ] `tests/unit/test_adapters/test_llamaindex_adapter.py` —
  flip to llama-server base_url
- [ ] `tests/unit/engines/test_agno_adapter.py` and siblings —
  flip factory expectations to `OpenAIChat`
- [ ] `tests/unit/cli/test_cli_wireup_invariants.py` —
  add `_STUB_COSTS` has no `"llamaindex"` invariant
- [ ] `oneiric/tests/adapters/test_observability_embeddings.py` —
  drop Ollama probe/encode cases; verify 3-backend chain
- [ ] Add a runtime class-identity test:
  `assert isinstance(LlamaIndexAdapter()._embed_model, OpenAIEmbedding)`
  and `assert isinstance(LlamaIndexAdapter()._llm, OpenAILike)`
  after the swap.

### Docs (all 6 repos)

- [ ] `mahavishnu/CLAUDE.md` "LLM Provider Configuration" section
- [ ] `mahavishnu/docs/ROUTING_GUIDE.md`, `docs/CONFIGURATION.md`, `docs/CLI_REFERENCE.md`
- [ ] `mahavishnu/docs/specs/`, `docs/adr/`, `docs/runbooks/`, `docs/architecture/`, `docs/ingestion/`, `docs/grafana/`, `docs/guides/`, `docs/followups/`, `docs/reviews/`, `docs/src/adapters/`
- [ ] `mahavishnu/examples/`
- [ ] `session_buddy/README.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `docs/`
- [ ] `crackerjack/docs/`, `CHANGELOG.md`
- [ ] `oneiric/docs/`
- [ ] `akosha/README.md`, `docs/`
- [ ] `mcp-common/docs/`

## 7. Validation Matrix

| Check | Command | Expected outcome | Evidence |
|---|---|---|---|
| No Ollama in production source | `rg -in ollama -- ':!docs' ':!CHANGELOG.md' ':!ARCHIVED' ':!BACKUP' ':!tests' ':!*.md' ':!*.yaml.example' --type py --type yaml` | Zero hits in `*.py` and `*.yaml` | Test log |
| LLMManager chain | `python -c "from session_buddy.llm_providers import LLMManager; m = LLMManager(); print(m._chain._providers)"` | `["minimax", "llama_server"]` | Test log |
| CloudWorker chain | `python -c "from mahavishnu.workers.cloud_worker import _build_fallback_chain, CloudWorkerConfig; print(_build_fallback_chain(CloudWorkerConfig())._providers)"` | `["minimax", "llama_server"]` | Test log |
| FallbackChainCodeFixer chain | `python -c "from crackerjack.adapters.ai.unified import FallbackChainCodeFixer; fc = FallbackChainCodeFixer(); print(fc._chain._providers)"` | `["minimax", "llama_server"]` | Test log |
| Agno factory uses OpenAIChat | `python -c "import mahavishnu.engines.agno_adapter_impl; import inspect; src = inspect.getsource(mahavishnu.engines.agno_adapter_impl); assert 'from agno.models.openai import OpenAIChat' in src; assert 'from agno.models.ollama import Ollama' not in src"` | Passes silently | Test log |
| LlamaIndex adapter uses OpenAIEmbedding | `python -c "import mahavishnu.engines.llamaindex_adapter_impl; import inspect; src = inspect.getsource(mahavishnu.engines.llamaindex_adapter_impl); assert 'from llama_index.embeddings.openai import OpenAIEmbedding' in src; assert 'from llama_index.embeddings.ollama import OllamaEmbedding' not in src"` | Passes silently | Test log |
| `OllamaProvider` is gone | `git ls-files | xargs grep -l "OllamaProvider" 2>/dev/null` | Zero output (file deleted) | Test log |
| Phase 1 module imports succeed | `python -c "import mahavishnu.engines.llamaindex_adapter_impl, mahavishnu.engines.agno_adapter_impl, session_buddy.llm_providers; print('OK')"` | `OK` | Test log |
| No Ollama library transitively imported | `python -c "import mahavishnu.engines.llamaindex_adapter_impl; import sys; assert not any('ollama' in m.lower() for m in sys.modules), f'stale imports: {[m for m in sys.modules if 'ollama' in m.lower()]}'; print('OK')"` | `OK` | Test log |
| Live demo: llamaindex | `./.venv/bin/mahavishnu demo llamaindex --repos <tmp> --prompt "..."` | Real LLM completion | Screenshot / captured stdout |
| Live demo: agno | `./.venv/bin/mahavishnu demo agno --repos <tmp> --prompt "..."` | Real LLM completion | Screenshot / captured stdout |
| Crackerjack merge gate | `crackerjack run -v -f` | Pass | Test log |
| pytest | `pytest tests/unit -q` | Pass (modulo known pre-existing failures) | Test log |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Operator currently runs Ollama in production; we delete the support | Medium | Per `feedback-no-backwards-compat-pre-1.0.md`, no deprecation. Operator migrates by switching to llama-server (one binary, one config). |
| llama-server not available on the operator's machine | Low | Document the install in the demo's preconditions; the preconditions check fails loud. |
| `llama-index-embeddings-openai` / `llama-index-llms-openai-like` not installed at runtime | Medium | REQ-OLLAMA-020 adds the deps **before** the import swap. Phase 0 (ecosystem grep) catches any unflagged reference. If still missing, the `LLAMAINDEX_AVAILABLE` try/except block falls back to `MagicMock`, which fails the first LLM call with a clear error. |
| `LLMProvider.OLLAMA` deletion racing factory class definition (Phase 1 split into two merges) | Eliminated | The plan collapses Phase 1 and Phase 2 into a single per-repo merge. No race window. |
| `LLMProvider.OLLAMA: None` key handling at `mahavishnu/core/config.py:202` not yet deleted when other call sites still reference the enum | Eliminated | Single per-repo merge handles the enum deletion and the key-handling deletion together. |
| `mahavishnu/cli/demo_cli.py:477` `LLMProvider.OLLAMA: None` is a separate call site from `core/config.py:202` | Medium | The plan calls out `demo_cli.py:477` explicitly in the B-list tasks; verify with grep on `LLMProvider.OLLAMA` in the new line. |
| Pydantic-AI adapter breaks (Pydantic-AI's `ollama:` prefix is library-specific) | Low | REQ-OLLAMA-023 folds the 5-line change into Phase 1. Adapter is secondary/optional; the demo path doesn't use it. |
| OpenSearch KNN plugin still missing on the operator's machine | Medium | Phase 1's LlamaIndex adapter still works via the in-memory vector store fallback. Phase 2's live demo uses the same fallback. Documented in Phase 2. |
| Hidden call sites referencing `OllamaProvider` or `LLMProvider.OLLAMA` we didn't find | Low | Phase 0 ecosystem-wide grep + the git grep validation matrix catches these on the first test run. |
| Cookie-cutter `crackerjack` URLs (e.g. typo `http://localhost: 11434` with extra space) hide the cleanup | Low | The inventory found one such typo in `crackerjack/adapters/ai/unified.py:44-54`. Phase 1 fixes the typo as part of the chain rewrite. |
| Cross-repo coordination cost (6 repos, 7 merge cycles) | Medium | Per-repo merge via SessionEnd hook. Each repo's `crackerjack run -v -f` gates its own merge. Sequence: mcp-common → session-buddy → oneiric → crackerjack → akosha → mahavishnu. |
| llama-server auth header rejection (sends `Authorization: Bearer <key>`; some builds reject any bearer token without `--api-key`) | Low | Phase 1 verification step: `curl -H "Authorization: Bearer no-auth" http://localhost:8081/v1/chat/completions`. If rejected, fall back to omitting the header. Document in the demo's preconditions. |
| Vector store non-persistence (`SimpleVectorStore` fallback) | Pre-existing | Documented in Phase 2. Production deployments should install OpenSearch KNN plugin. |
| Streaming-usage accounting gap in llama-server | Pre-existing | Documented in §4. Not a regression (shared with Ollama). Non-streaming usage works. |
| 2-tier FallbackChain reduced to 2 providers (no tertiary) | Acceptable | Per `feedback-no-backwards-compat-pre-1.0.md`. If both MiniMax and llama-server unreachable, `CloudWorker.execute()` raises `RuntimeError` after retry exhaustion. The oneiric embedding chain still has 3 tiers. |

## 9. Decision Rule

This plan is "done" when:
- A user can run `./.venv/bin/mahavishnu demo llamaindex --prompt "..."` against a local llama-server and get a real LLM completion.
- The Phase 1 + Phase 2 exit criteria all pass.
- The git grep validation matrix returns zero ollama hits in production code across all 6 repos.
- Each repo's `crackerjack run -v -f` passes.
- Each repo's pytest suite passes (modulo known pre-existing failures).
- The plan has been promoted from `status: draft` to `status: active`
  in `docs/plans/PLAN_INDEX.md` (per `TEMPLATE.md` line 147). Run
  `python -m crackerjack.tools.plan_index_sync` (or equivalent)
  to verify the index entry passes CI.

**If scope pressure forces a cut**:
- **Drop Phase 1's B-list sweep first**, not Phase 2. Phase 1's B-list
  is mechanical grep-and-delete across ~50 file-groups; the actual
  fix is the library-class swap (Agno + LlamaIndex + the new
  `LLMProvider.LLAMA_SERVER` enum value), which is Phase 2's A-list.
  A minimal "Phase 1-essential" would be just the A-list + the
  `_STUB_COSTS` removal.
- Phase 2 is the only end-to-end verification surface (the live
  demo). Without it, we have no way to confirm the swap actually
  works at runtime — only that the test suite still passes.
  Test-suite-passing-after-deletion is exactly the regime that
  produced the original Ollama 501 bug. Dropping Phase 2 loses the
  only signal that catches a runtime-only failure.

**Post-plan discipline**:
- After all per-repo merges land on local `main`, do **NOT** run
  `git push origin main` — push is user-controlled per
  `feedback-bodai-push-is-user-controlled.md`.
- The user runs `git push` and `crackerjack run -p <level>` from
  their own shell to bump+tag+publish the mcp-common version.
- The implementer does not bump the mcp-common version themselves
  per `feedback-mcp-common-version-bump-is-user.md`.
- Each per-repo commit is authored as
  `les@wedgwoodwebworks.com` (not `.local`) with no
  `Co-Authored-By` trailer per `feedback-no-claude-code-coauthor-attribution.md`.

## References

- `mahavishnu/docs/specs/2026-09-27-shared-bodai-substrate-design.md` —
  oneiric substrate (embedding service, LLM provider surface)
- `mahavishnu/docs/plans/2026-05-10-minimax27-provider-migration.md` —
  the precedent for a major LLM-provider migration; the migration
  playbook in that plan is the template for the per-repo merges here
- `mahavishnu/docs/plans/2026-10-15-bifrost-gateway-wiring.md` —
  related but independent (Bifrost does not consume or reshape the
  LLM provider surface)
- `mcp_common/mcp_common/llm/fallback.py` — the canonical
  FallbackChain implementation
- `mahavishnu/workers/cloud_worker.py:78-113` — the canonical
  three-tier chain pattern (now collapsing to two)
- `feedback-no-backwards-compat-pre-1.0.md` — no deprecation windows
- `feedback-crackerjack-merge-gate-is-vf.md` — gate is
  `crackerjack run -v -f`
- `feedback-crackerjack-run-vf-not-f.md` — use `-v -f`, not bare `-f`
- `bodai-pre-1.0-merge-policy.md` — direct merge to `main`,
  no PRs
- `feedback-bodai-push-is-user-controlled.md` — push is
  user-controlled; implementer does NOT `git push origin main`
- `feedback-mcp-common-version-bump-is-user.md` — mcp-common
  version bump is user-controlled; implementer does NOT edit
  `pyproject.toml` version
- `feedback-no-claude-code-coauthor-attribution.md` — no
  `Co-Authored-By` trailer on commits
- `git-author-email-correct-domain.md` — author email must be
  `les@wedgwoodwebworks.com` (not `.local`)
- `mahavishnu/CLAUDE.md` § "Crackerjack-Compliant Code" — gate and
  conventions
- `mahavishnu/docs/decisions/wire-up-contract.md` — Pydantic-AI
  cleanup is folded into Phase 1 (not deferred as a follow-up)
