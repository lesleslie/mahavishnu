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
(commit `db06fc87 feat(adapters): Phase 2 — drop HybridAdapterRegistry, route through Oneiric`) — the file is gone but 5 live references in
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

1. **All three pieces of the substrate contract must hold for every decision
   adapter:** (a) class-level `metadata: ClassVar[AdapterMetadata]` slot;
   (b) `DecisionBaseSettings` Pydantic base (with `caller_namespace` per
   REQ-OSUB-B-004, `api_key_env` indirection, `base_url`, `model`,
   `timeout_seconds`, `max_retries`); (c) `init`/`health`/`cleanup` async
   lifecycle with default `health()` being a single-question probe (a Noul
   question by default; subclasses can override for cheaper probes).

1. **Mahavishnu's `task_router.py` migration is sequenced with Task 3's new
   selector tests, but is NOT a hard prerequisite for the substrate-side
   Oneiric PR (Task 1).** The decision adapters exist in the substrate
   once Task 1 lands; they become reachable from Mahavishnu's routing
   layer once the 5 docstring/comment references in
   `task_router.py:394, 403, 430, 493, 591` are updated AND Task 2 Step 18a
   extends `TaskRouter.__init__(adapter_bridge=...)` so the new selectors
   have a bridge to dispatch through.

   The 5 references are all in docstrings or comments — the
   `HybridAdapterRegistry` class was deleted at commit `db06fc87`. The
   only real coupling is Task 3 Step 18a (init signature change)
   depends on Task 2 Step 4 (init signature change), so Task 2 lands in
   the same PR as Task 3's selector work. Task 1 (substrate) is fully
   independent and can ship whenever.

   The original rule ("must land before") overstated the dependency.
   Building the Mahavishnu side without the migration lands Task 3
   Steps 1-15 (router, CLI, MCP tools) cleanly; only the selectors
   (Steps 16-19) and the feed-state probe (Step 26) require Task 2.

1. **The `decision` category name is singular** (matches `vector`, `cache`,
   `llm`, `embedding`, `storage` convention in `oneiric/adapters/`).
   User-facing CLI/MCP tool names are also singular: `mahavishnu decision decide`, `mcp__mahavishnu__decision_decide`.

1. **Adapters that do not support a method fail closed with
   `UnsupportedCapabilityError(RuntimeError)`** (defined in
   `oneiric.core.errors`), not silent stub and not Python's built-in
   `NotImplementedError` — which is reserved for the abstract-method contract.
   Jev raises on `rank()`; BGE/TEI raises on `decide()`; the substrate default
   implementations on `DecisionBase` raise with a message naming the concrete
   adapter class and the missing capability. `AdapterBridge.use("decision",
   capabilities=["noul"])` resolves to Jev; `AdapterBridge.use("decision",
   capabilities=["rank"])` resolves to BGE; `AdapterBridge.use("decision",
   capabilities=["noul", "multimodal"])` resolves to Decision 3.0.

1. **The `mahavishnu/adapters/pgvector_adapter.py:126` fork deletion is
   pulled out of this plan** as a separate drive-by. The premise of the
   original rule was wrong: the fork is **actively used** by
   `mahavishnu/ingesters/otel_ingester.py:619` (`from mahavishnu.adapters.pgvector_adapter
   import PgvectorAdapter, PgvectorSettings`; instantiated at lines 625-626),
   AND Oneiric's `vector/pgvector.py:271-277` only emits IVFFlat indexes
   (`USING ivfflat ... WITH (lists = ...)`), **not HNSW**. The fork's HNSW
   config (`_sql_create_hnsw_index` at `pgvector_adapter.py:601`) is a real,
   non-duplicated feature. The pgvector deletion work must wait until either
   (a) HNSW is backported to Oneiric's `PgvectorAdapter`, or (b) the OTel
   ingester is migrated to use `AdapterBridge.use("vector", provider="pgvector")`
   and verified to lose no functionality. Either is its own PR with its own
   Integration Contract block.

1. **PEP 735 `[dependency-groups].typesafe` covers the Jev SDK.** The BGE/TEI
   adapter uses `httpx2` (already a Oneiric baseline per
   `oneiric.adapters.httpx_base`); the Decision 3.0 adapter uses `httpx2`
   to call vllm-sr's `/v1/systemone` endpoint. Per
   `feedback-mcp-common-version-bump-is-user.md`, no version pin is bumped
   in any Bodai `pyproject.toml` without user approval.

1. **The `decision_3_0` adapter exposes a `quantization: str | None = None`
   field.** Default `None` lets vllm-sr pick. Operators on Apple Silicon
   should pin a HuggingFace repo suffix like `vllm-sr/d3-mini-AWQ` and set
   `quantization="awq"` (or `"gptq"`, `"fp8"`) to fit within the available
   unified memory. The field is optional; the substrate must not require
   it, since Jev and BGE/TEI don't use it.

1. **A `README.md` lands at `oneiric/adapters/decision/`** documenting the
   category's public surface (capability taxonomy, capability-aware routing,
   list of concrete adapters, operator setup, per-adapter env-var contract).
   A sibling `mahavishnu/decision/README.md` covers the consumer-side wiring
   (DecisionRouter, MCP tools, CLI, kill switch). Without these, the operator
   has no canonical entry point for "how do I add a new decision adapter?"
   or "which adapter gives me multimodal + calibrated probability?".

1. **Three typed substrate exceptions ship with the category**, in
   `oneiric.core.errors`:
   - `UnsupportedCapabilityError(RuntimeError)` — replaces Python's
     `NotImplementedError` for "this concrete adapter does not implement this
     primitive" signals. Carries the concrete adapter class name and the
     missing capability in its message. Defined in plan Task 1 Step 0a.
   - `ShadowModeOnlyError(RuntimeError)` — raised by `DecisionRouter` /
     `TaskRouter.decide`/`rank` when `MAHAVISHNU_DECISION_LIVE_ROUTING=true`
     is unset. This is the only machine-checkable Phase 1 gate until Task 5
     (shadow harness) ships.
   - `DecisionToolsDisabledError(RuntimeError)` — raised by the MCP tools
     when `MAHAVISHNU_DECISION_ENABLED=false`. Per-tool kill switch; leaves
     the tool registered (clients see a typed error rather than 404).

1. **Adapter methods MUST NOT call back into `AdapterBridge.use()` from within
   `decide()`, `rank()`, or any subclass-implemented method.** The substrate's
   `LifecycleManager` caches adapter instances by `(domain, key)`
   (`oneiric/domains/base.py:98-107`); a recursive `bridge.use()` would
   return the same instance the call originated from — infinite re-entry.
   Retry / fallback / multi-provider dispatch lives in the orchestrator
   (`DecisionRouter`), not the adapter. Enforced by `test_decision_base.py`
   in plan Task 1 Step 29.

1. **`DecisionRouter` caches `AdapterHandle`s by `frozenset(capabilities)`** and
   is constructed **once on `TaskRouter.__init__`**, not per-call. The
   substrate's `LifecycleManager` caches the adapter instance + `httpx.AsyncClient`,
   but the bridge dispatch path (`resolver.resolve → lifecycle.get_instance →
   _build_handle → _after_handle → new AdapterHandle`) executes per call. The
   `DecisionRouter` cache is the Mahavishnu-side equivalent — it caches the
   handle, not the adapter, since the adapter is already cached one layer down.
   Single source of truth for `cycles_total` is `DecisionRouter.cycles_total`
   (atomic counter, `asyncio.Lock`); the MCP tool wrappers and the feed-state
   aggregator probe both read from this same counter. NEVER
   `getattr(adapter, "_cycles", 0)`.

1. **`DecisionBaseSettings.health_probe: Literal["capability_probe", "head_get",
   "skip"]`** selects the strategy used by `_probe_decision_state` and any
   direct `adapter.health()` call. Default `"capability_probe"` (full
   decide()/rank() probe); `"head_get"` issues `GET {base_url}/health`
   (TEI exposes `/health`; vllm-sr does too in Engine mode); `"skip"` returns
   `False` without network. Operators with expensive upstream services can
   select `"head_get"` to cut the feed-state aggregator's 60s tick cost.

1. **Per-tool kill switch via `MAHAVISHNU_DECISION_ENABLED`** (default
   truthy — case-insensitive match against `frozenset({"true", "1", "yes", "on"})`
   per `_parse_enabled` in `decision_tools.py`). When unset / non-truthy,
   `decision_decide` and `decision_rank` raise `DecisionToolsDisabledError` from
   each tool, leaving the tool registered so clients see a typed error rather
   than 404. This avoids the blunt `MAHAVISHNU_TOOL_PROFILE=minimal` (which
   flips off 33 other tools). Same truthy set applies to
   `MAHAVISHNU_DECISION_LIVE_ROUTING`.

1. **Cross-repo rollback contract for Task 1 substrate PR.** Task 1's PR MUST
   NOT auto-merge to `main` until `crackerjack run -v` runs locally against
   all 4 downstream test suites (Mahavishnu, Akosha, Session-Buddy, Crackerjack)
   and reports green — via the trunk-based agent-review workflow (per
   `memory/feedback-bodai-merge-workflow`), not via remote CI. Operator
   workflow: gate the auto-merge session-wide via `MAHAVISHNU_AUTO_MERGE=0`,
   run downstream CIs, manually merge. **No mechanical cross-repo enforcement
   exists** — this rule is policy-only. If Task 1 is reverted, Task 3's
   selectors MUST be reverted in the same change window (otherwise Task 3
   references undefined symbols). The `try/except ImportError` fallback in
   `mahavishnu/decision/__init__.py` (plan Step 33) prevents the 175-tool MCP
   server from crashing during the revert window — the kill switch surface
   stays intact. Per `feedback-substrate-compat-shim-rot.md`, substrate
   extensions rot when the named substrate changes shape; a substrate PR
   deployed without consumer verification amplifies the rot.

1. **Pre-Task 3 user action: bump the Oneiric pin in `mahavishnu/pyproject.toml`
   from `oneiric>=0.28.0` to `oneiric>=0.30.0` (or whatever Task 1 ships as).**
   `mahavishnu/decision/router.py` and `mahavishnu/mcp/tools/decision_tools.py`
   import `oneiric.adapters.decision.types` at module top; CI's
   `pip install -e ".[dev]"` resolves Oneiric from the PyPI index, so
   `ModuleNotFoundError` is guaranteed until the operator bumps the Mahavishnu
   pin to a version that has the new category. Per
   `feedback-mcp-common-version-bump-is-user`, this is operator-controlled —
   surface it, pause, wait for the operator. Local dev can
   `uv pip install -e /Users/les/Projects/oneiric` in the Mahavishnu venv to
   consume the new category from the local checkout.

## Status

Phase 0 plan in `docs/plans/2026-10-14-decision-adapter-category.md`. Phase 0
spec in `docs/specs/2026-10-14-decision-adapter-category-design.md`. Hard
sequencing on the `task_router.py` migration. Phase 1 (live routing
in `mcp__mahavishnu__pool_route_execute`) gated on a 7-day disagreement
test vs. hand-coded baseline, per `feedback-bodai-merge-workflow` rules
plus the precision/calibration drift checks from the spec. Three Phase 0
adapters means three substrate-side PRs (one per adapter) plus the
existing migration + consumption + pgvector PRs.

## Tool count delta (consumer side)

Mahavishnu's MCP server ships 175 tools after Task 3 lands (was 173):
two new `mcp__mahavishnu__decision_*` tools (`decision_decide` + `decision_rank`)
registered via `STANDARD_REGISTRATIONS` + `REGISTRATION_MAP` (NOT inline
`_register_tools()` — that would put them under `minimal` profile too).
Per `feedback-docs-audit-mcp-tool-hallucination`, hand-maintained tool
counts drift; the count above is authoritative for this PR cycle only.
A future PR that adds or removes tools must update the count inline and
preferably add a `tests/integration/test_tool_count.py` self-count check
that fails the build if `mcp__mahavishnu__discover_tools` reports a
different number than the docs claim.
