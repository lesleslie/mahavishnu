# 2026-10-14-decision-adapter-category.md

## Context

The Bodai orchestrator (Mahavishnu) has a `task_router.py` that classifies tasks
and routes them to the right engine. Today the classification is a deterministic
YAML table (per `feedback-cli-flag-consumer-wiring.md` and the existing
`tests/unit/test_task_router.py::TestYAMLRoutingSync` guard). Several real
decision-classifier products have shipped in 2026 — TypeSafe AI's Jev is the
flagship System One model (TechCrunch / Forbes coverage, $40M DCVC seed,
launched 2026-09-15); vLLM Semantic Router's **Decision 3.0** is the
open-source Apache 2.0 multimodal System One model family (ranked #1 on the
Jev Decision Index for similarly-sized entries, 0.6B to 27B params);
BGE Reranker v2-m3 via HuggingFace TEI is the canonical open-source
self-hostable relevance ranker. The orchestrator needs a *substrate-faithful*
way to consume these without forking its routing layer.

The Oneiric substrate team has added the `OneiricAdapter` Protocol at
`/Users/les/Projects/oneiric/oneiric/adapters/protocol.py:47-117` — a structural,
duck-typed contract (`metadata: ClassVar[AdapterMetadata]` + `init`/`health`/
`cleanup` async methods). Most categories extend a typed base ABC
(`VectorBase[T]`, `LLMBase`, `EmbeddingBase`) layered on top of the Protocol.
The Mahavishnu team is mid-migration from its old `HybridAdapterRegistry`
(commit `db06fc87 feat(adapters): Phase 2 — drop HybridAdapterRegistry, route
through Oneiric`) — the file is gone but 5 live references in
`mahavishnu/core/task_router.py` and 2 in `mahavishnu/core/health_integration.py`
still need cleanup. Per `feedback-substrate-compat-shim-rot.md`, substrate
shims rot; we should NOT add a `decision/` category to Oneiric that Mahavishnu
cannot reach.

## Decision rule

1. **A `decision/` category lands in Oneiric with three initial adapters:**
   - `JevAdapter` — TypeSafe Jev, closed hosted, pointwise Noul/Choice/Score.
   - `Decision3Adapter` — vLLM Semantic Router Decision 3.0, open-source
     self-hostable, pointwise Noul/Choice/Score with multimodal images/videos.
   - `BgeTeiRerankAdapter` — HuggingFace TEI, open-source self-hostable, relevance ranker.
   Cohere Rerank v4 remains Phase 2.

   The substrate default for Decision 3.0 is `vllm-sr/d3-mini` (4.54B params)
   per Apple-Silicon hardware fit (4.54B at Q4_K_M fits in ~3 GB; comfortable
   on M1/M2 base). Operators with M1/M2 Max+ or M3/M4 Pro can override
   `model` to `vllm-sr/d3-flash` (8.39B) for the Jev Decision Index #1 result.

2. **All three pieces of the substrate contract must hold for every decision
   adapter:** (a) class-level `metadata: ClassVar[AdapterMetadata]` slot;
   (b) `DecisionBaseSettings` Pydantic base (with `caller_namespace` per
   REQ-OSUB-B-004, `api_key_env` indirection, `base_url`, `model`,
   `timeout_seconds`, `max_retries`); (c) `init`/`health`/`cleanup` async
   lifecycle with default `health()` being a single-question probe (a Noul
   question by default; subclasses can override for cheaper probes).

3. **Mahavishnu cannot consume the new category until the HybridAdapterRegistry
   migration in `task_router.py` is complete.** The decision adapters exist
   in the substrate; they are unreachable from Mahavishnu's routing layer
   until the 5 references in `task_router.py:394, 403, 430, 493, 591` are
   ported to Oneiric's `AdapterBridge.use(...)`. This is a hard sequencing
   rule — building the Mahavishnu side before the migration is closed
   produces a category-with-no-consumers and must not happen.

4. **The `decision` category name is singular** (matches `vector`, `cache`,
   `llm`, `embedding`, `storage` convention in `oneiric/adapters/`).
   User-facing CLI/MCP tool names are also singular: `mahavishnu decision
   decide`, `mcp__mahavishnu__decision_decide`.

5. **Adapters that do not support a method fail closed with
   `NotImplementedError`**, not silent stub. Jev raises on `rank()`; BGE/TEI
   raises on `decide()`. `AdapterBridge.use("decision", capabilities=["noul"])`
   resolves to Jev; `AdapterBridge.use("decision", capabilities=["rank"])`
   resolves to BGE; `AdapterBridge.use("decision", capabilities=["noul", "multimodal"])`
   resolves to Decision 3.0.

6. **The Mahavishnu `mahavishnu/adapters/pgvector_adapter.py:126` fork is
   deleted in the same change window** as the decision category consumption
   work. `PgvectorAdapter.metadata` is already in `builtin_adapter_metadata()`
   per `oneiric/adapters/bootstrap.py:124`, so `AdapterBridge.use("vector",
   provider="pgvector")` resolves to Oneiric's class. The Mahavishnu fork
   adds nothing Oneiric's class doesn't already provide (per
   `feedback-mcp-test-must-assert-aggregator-verdict.md` — the
   `pgvector_adapter.py` HNSW extension is a candidate for upstreaming to
   Oneiric, not for carrying as a Mahavishnu fork).

7. **PEP 735 `[dependency-groups].typesafe` covers the Jev SDK.** The BGE/TEI
   adapter uses `httpx2` (already a Oneiric baseline per
   `oneiric.adapters.httpx_base`); the Decision 3.0 adapter uses `httpx2`
   to call vllm-sr's `/v1/systemone` endpoint. Per
   `feedback-mcp-common-version-bump-is-user.md`, no version pin is bumped
   in any Bodai `pyproject.toml` without user approval.

8. **The `decision_3_0` adapter exposes a `quantization: str | None = None`
   field.** Default `None` lets vllm-sr pick. Operators on Apple Silicon
   should pin a HuggingFace repo suffix like `vllm-sr/d3-mini-AWQ` and set
   `quantization="awq"` (or `"gptq"`, `"fp8"`) to fit within the available
   unified memory. The field is optional; the substrate must not require
   it, since Jev and BGE/TEI don't use it.

## Status

Phase 0 plan in `docs/plans/2026-10-14-decision-adapter-category.md`. Phase 0
spec in `docs/specs/2026-10-14-decision-adapter-category-design.md`. Hard
sequencing on the `task_router.py` migration. Phase 1 (live routing
in `mcp__mahavishnu__pool_route_execute`) gated on a 7-day disagreement
test vs. hand-coded baseline, per `feedback-bodai-merge-workflow` rules
plus the precision/calibration drift checks from the spec. Three Phase 0
adapters means three substrate-side PRs (one per adapter) plus the
existing migration + consumption + pgvector PRs.
