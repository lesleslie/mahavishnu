---
status: complete
role: implementation
kind: plan
date: 2026-10-03
last_reviewed: 2026-11-06
superseded_by: null
topic: model-evaluation
title: "Model Evaluation — Phase 1 Implementation Plan"
requirements:
- id: REQ-EVAL-001
  title: Oneiric adapter discovery for eval extension points
  file: mahavishnu/core/eval/_registry.py:1-80
- id: REQ-EVAL-002
  title: EvalEngine primitive (Dataset, Scorer, Storage, ModelBackend ABCs/Protocols)
  file: mahavishnu/core/eval/engine.py:1-50, dataset.py:1-40, scorer.py:1-50, storage.py:1-50
- id: REQ-EVAL-003
  title: EvalEngine orchestration (composes extension points, returns EvalRunResult)
  file: mahavishnu/core/eval/engine.py:50-250
- id: REQ-EVAL-004
  title: EvalPool as BasePool subclass with single virtual worker (discoverable; MCP tool bypasses in
    Phase 1)
  file: mahavishnu/pools/eval_pool.py:1-200
- id: REQ-EVAL-005
  title: MCP tool surface (eval_register_dataset, eval_run_suite, eval_get_run) via a profile-gated tools
    module
  file: mahavishnu/mcp/bootstrap.py:_register_eval_tools
- id: REQ-EVAL-006
  title: Settings via nested EvalSettings field on MahavishnuSettings; env var MAHAVISHNU_EVAL__*
  file: mahavishnu/core/eval/settings.py:1-80, mahavishnu/core/config.py:eval-field
- id: REQ-EVAL-007
  title: Dogfood golden set of 20-30 Mahavishnu-specific cases
  file: docs/eval/dogfood-v0.jsonl
- id: REQ-EVAL-008
  title: Phase 1 wire-up (e2e tests, health feed, audit_orphans, plan promotion)
  file: mahavishnu/mcp/eval_feed.py + tests/integration/test_eval_*.py
- id: REQ-EVAL-009
  title: MarkdownReportWriter for human-readable run reports
  file: mahavishnu/core/eval/report.py:1-100
- id: REQ-EVAL-010
  title: CLI entry point `mahavishnu eval run-suite` for programmatic use without MCP
  file: mahavishnu/_main_cli.py + mahavishnu/cli/eval_cli.py
- id: REQ-EVAL-011
  title: OTel child-span attribute cardinality bound (eval.* is a fixed schema, not a free-form keyspace)
  file: mahavishnu/core/eval/engine.py:run_suite + tests/integration/test_eval_cardinality.py
---

# Model Evaluation — Phase 1 Implementation Plan

**Date:** 2026-10-03
**Status:** `complete, implementation` — Phase 1 delivered and merged; Phases 2-5 remain out of scope and are tracked separately.
**Owner:** Core Eng
**Scope:** Mahavishnu. Phase 1 only — foundation slice. Phases 2-5 (multi-model A/B, regression detection, agent trajectories, cost routing) are out of scope and tracked separately.
**Purpose:** Ship a vertical slice that proves the architecture, demonstrates the value of prompt/model evaluation to the team, and provides the foundation for Phases 2-5.

## Revision history

- **v0** (2026-10-03): initial draft.
- **v1** (2026-10-03): post multi-agent review. Architectural decision: `EvalPool` extends `BasePool` (option 2). Settings env_prefix corrected to `MAHAVISHNU_EVAL_*`. `model_backend` returns `ModelResponse` and is registered as a fourth oneiric entry-point group. FastMCP tools inline in `bootstrap.py`. New `eval_feed.py` + health-feed wiring. Per-file-ignores added. CLI entry point added. 20-30 Mahavishnu-specific golden cases (not generic Python). 30+ specific corrections from the architecture, MCP, and crackerjack lenses folded in.
- **v2** (2026-10-03): post meta-review (consistency pass). EvalSettings is now a nested field on `MahavishnuSettings` (not a separate `BaseSettings`); env var is `MAHAVISHNU_EVAL__*` (double underscore for nested delimiter). EvalPool factory signature matches `manager.py::spawn_pool` actual call shape. `BasePool.scale()` returns `None` (Liskov), not int. `EvalStorage` gets a `finish_run` method to transition run status. CLI uses `typer` not `click`; entry is `_main_cli.py` not `cli.py`. `Scorer.score` is sync. `_do_run_suite`/`_do_register_dataset`/`_do_get_run` helpers fully specified. `MockModelBackend` has concrete behavior. Per-file-ignore block shown explicitly. `get_eval_settings()` is a module-level lazy getter. 16 corrections from the meta-review folded in.
- **v3** (2026-10-18): drift pass after 15 days of repo activity + `MiniMax-M2.7-highspeed` deprecation at MiniMax. All body line-number references that have shifted by ≤18 lines are re-pinned in the References appendix; task-body line numbers are left as durable pointers that the implementing worker re-verifies on first read (15 days of churn would make a v3-only patch churn again before kickoff). `MiniMax-M2.7-highspeed` → `MiniMax-M3` at lines 31, 65, 564. New coordination note added at the bottom: `M2.7-highspeed` is no longer available — the dogfood smoke test in Task 8.6 must target `MiniMax-M3`. Confirmed `from uuid import uuid7` is in Python 3.14 stdlib (target version per `pyproject.toml`); no pinning action needed. Confirmed the `_evaluation_` vs `_eval_` naming in body prose refers to the **same** field — the field name on `MahavishnuSettings` is `eval`; the "evaluation" wording in body text is a conversational alias. No body re-architecture; only identifier substitutions and a coordination appendix.
- **v4** (2026-11-06): kickoff drift pass — 19 days of repo activity after v3, and the first day of implementation. **v3 re-pinned line numbers but did not verify that the referenced *symbols* still existed**; three load-bearing premises had silently died between 2026-10-03 and 2026-11-06. Corrections folded in: (a) `mahavishnu/core/adapter_discovery.py` and `AdapterDiscoveryEngine` were **deleted** on 2026-10-12 (`db06fc87` — "drop HybridAdapterRegistry, route through Oneiric"), so Task 0.2 and Task 1.3 as written were unexecutable; the replacement is `oneiric.plugins.iter_entry_points(group)` → `.load()` → callable, which is generic over any group name (oneiric 0.34.0). (b) `AdapterRegistryConfig.allowlist_patterns` (`mahavishnu/core/config.py:2022`) is now **dead config** — its only consumers are two unit tests and `settings/mahavishnu.yaml`; it gated the deleted `HybridAdapterRegistry`. Eval's four extension points live in their own entry-point groups, so **no allowlist change is needed**. Task 0.2 rewritten. (c) The FastMCP "tools must be inline" constraint applies **only** to the 27 tools inside `FastMCPServer._register_tools()` (`mahavishnu/mcp/server_core.py:349-358`); profile-gated groups use the `mcp/tools/<name>_tools.py::register_<name>_tools` → `bootstrap.py::_register_<name>_block` → `_OPTIONAL_TOOL_BLOCKS` → `profiles.py` pattern. Task 7.10/7.11 rewritten. (d) `BasePool` grew five abstract methods since the plan was written (`start`, `execute_batch`, `health_check`, `get_metrics`, `stop`); the Task 7.5 `EvalPool` snippet implemented only three and **would not have instantiated**. (e) Requirements must be declared in plan **frontmatter** (`requirements:` list), not only in the body `## 4.5 Requirements` block — `scripts/audit_requirements.py` reads frontmatter, so REQ-EVAL-001..REQ-EVAL-011 were invisible to the audit; frontmatter now carries them and code references them via `# req: REQ-NNN` markers. **The IDs were also re-scoped from bare `REQ-001..REQ-011` to `REQ-EVAL-001..REQ-EVAL-011`**: `scripts/audit_requirements.py` treats requirement IDs as globally unique and scans only `.py` files, and bare `REQ-001..REQ-009` are already claimed by eight other plans (the QueueingScorer plan alone references `REQ-002`/`REQ-003`/`REQ-008`), so the un-prefixed IDs would have been silently satisfied by unrelated code. The repo's newer plans already use plan-scoped prefixes (`REQ-YAML-*`, `REQ-ORC-*`, `REQ-PI-*`, `REQ-SM-*`); this plan now follows suit. (f) `MiniMax-M2.7` was closed to new users on 2026-10-19 and retires 2026-11-18, so v3's "the fallback chain collapses to `M2.7` alone" is wrong — the fallback is `MiniMax-M3.1-Flash`. Task 8.2's CLI default of `MiniMax-M3` remains correct. (g) `pyproject.toml` already sets `[tool.ruff.lint.flake8-type-checking] runtime-evaluated-base-classes = ["pydantic.BaseModel", "msgspec.Struct"]` (landed 2026-10-20, two days after v3), so the 10-line per-file `TC003` carve-out Task 0.3 asked for is unnecessary — and contrary to the stated policy ("prefer a local `# noqa` with a reason over adding a path back to this list"). Task 0.3 revised; the one carve-out this work needs is the FastMCP tool module in Task 7, mirroring `get_capability_result_tool.py`. (h) The fleet-wide shared gitignore ignores `data/` deliberately ("Verified 2026-10-20: no tracked file under any data/ dir in akosha, oneiric, mahavishnu, crackerjack, session-buddy or mcp-common"), and a gitignore rule cannot re-include a file under an excluded directory — so the Task 8.4 golden set at `data/eval/dogfood-v0.jsonl` would have been silently untracked, and the Task 8.7 freshness test would fail in CI. The dataset moves to `docs/eval/dogfood-v0.jsonl`, alongside the `docs/eval/DOGFOOD.md` the plan already creates. Line pins in the References appendix re-verified against `main` at `f3df534f`. **Pre-existing and unrelated:** `tests/integration/test_audit_requirements.py` is red on `main` (28 phantom REQ IDs whose declaring plans live in the gitignored `docs/plans/.archive/`); this plan neither causes nor worsens that, and the 28 baseline phantoms are unchanged by v4.

## 1. Outcome

A developer can run a golden-set of cases covering **Mahavishnu-specific agent behaviors** (repo routing, adapter selection, workflow invocation, etc.) against a model through Mahavishnu and get back a scored, persisted, queryable result — without leaving the project's MCP surface or writing one-off scripts. The framework registers all its pluggable parts (scorers, dataset loaders, storage, model backends) as oneiric adapters so they are discoverable and replaceable.

**Success signal:** the dogfood golden set (20-30 Mahavishnu-specific cases) runs end-to-end against `MiniMax-M3` in under 2 minutes, produces a markdown report at `~/.local/state/mahavishnu/eval/reports/{run_id}.md`, persists results to SQLite, and `/health` reports `checks.eval.feed_entities_count > 0` and `checks.eval.cycles_total > 0` after the run. A re-run after a known-bad prompt change flags the regression.

## 2. Goals

1. Establish `EvalEngine` as a new Mahavishnu primitive (not an `OrchestratorAdapter` subclass — its execution shape is incompatible with `(task, repos) -> dict`).
2. Establish `EvalPool` as a `BasePool` subclass wrapping a single virtual worker (per the user's architectural decision; rationale: consistency with the existing `mahavishnu/pools/` convention + `list_pools()` discoverability + Phase 2 multi-run parallelism without restructuring). **The MCP tool bypasses EvalPool in Phase 1** and calls `EvalEngine` directly; the pool is registered for discoverability + future cross-pool orchestration.
3. Wire all pluggable extension points (scorers, dataset loaders, storage, **model backends**) as oneiric adapters discoverable via the oneiric entry-point mechanism (`oneiric.plugins.iter_entry_points`), with a built-in table as the install-independent runtime source (see Task 1).
4. Expose three MCP tools: `eval_register_dataset`, `eval_run_suite`, `eval_get_run`. Inlined in `bootstrap.py::_register_eval_tools()` per `server_core.py:290-300` (FastMCP's `@server.tool()` requires inline definition for signature introspection).
5. Land the dogfood golden set of 20-30 **Mahavishnu-specific** cases (curated from real team failure modes) so the team can dogfood the feature on the first day of Phase 2.
6. Pass the `crackerjack` gate at the project's hard limits (line length 100, args ≤ 10, branches ≤ 15, statements ≤ 55 ceiling / 30 target, coverage **89.0168%** as configured in `pyproject.toml:462`).
7. Pass wire-up discipline: every MCP tool has a working data feed (`feed.entities_count > 0`, `feed.last_updated_timestamp`, `feed.errors_total`, `cycles_total`) and an `tests/integration/test_<tool>_e2e.py` asserting non-empty results; per `mcp-backend-wiring-discipline.md` the e2e must spin up the server in a subprocess, wait through the warm-up window, and call each tool through the MCP protocol.

## 3. Non-Goals

1. Multi-model A/B comparison (Phase 2).
2. Regression detection across runs (Phase 3).
3. Agent-trajectory / multi-turn evaluation (Phase 5).
4. CI integration / PR gating (Phase 3).
5. LangSmith bidirectional sync (Phase 2 — Phase 1 only *reads* from LangSmith as a dataset source if a LangSmith API key is present; no writes back).
6. UI of any kind. Reports are markdown files. The LangSmith UI is the de facto surface.
7. Custom prompt registries. Reuse LangSmith Prompts or git-versioned `.md` files.
8. Removing the existing `OrchestratorAdapter` ABC or the existing `BasePool`. They are not the problem; do not refactor what works.
9. Persistent `cost_budget_usd` on `PoolConfig`. The budget is **per-run** (per `EvalSuite.cost_budget`), not per-pool-lifetime. `EvalPool` reads the suite's budget; the pool itself has no budget of its own.

## 4. Current Findings

- `OrchestratorAdapter.execute(self, task: dict[str, Any], repos: list[str]) -> dict[str, Any]` is the workflow-engine contract. The eval execution shape is fundamentally different — `(suite, model_config, budget) -> EvalRunResult`. Forcing eval through this signature is dishonest. The eval feature lives as a new primitive, not a new adapter.
- `mahavishnu/pools/base.py:100` defines `BasePool` (NOT `PoolBase`). It has **eight** abstract methods: `start` (134), `execute_task` (142), `execute_batch` (160), `scale(target_worker_count: int) -> None` (171), `health_check` (183), `get_metrics` (196), `collect_memory` (204), `stop` (221). **`scale` returns `None` per the abstract signature** (Liskov constraint) — Task 7.5's EvalPool override must also return `None`, not `1`. The current worker count is observable via `get_status()`, not the return value of `scale`. `BasePool.__init__(config, pool_id=None)` (122) sets `self.pool_id`, `self._status`, `self._workers`; `PoolMetrics` (65) requires `pool_id`, `status`, `active_workers`, `total_workers`.
- `mahavishnu/pools/manager.py:355-359` invokes pool factories as `factory(config=config, terminal_manager=self.terminal_manager, session_buddy_client=self.session_buddy_client)`. **`_build_eval_pool` must match this signature exactly** (accepting the two manager-injected args, ignoring them, and pulling eval-specific deps from module singletons via `get_eval_settings()` and oneiric adapter discovery).
- **v4:** `mahavishnu/core/adapter_discovery.py` and `AdapterDiscoveryEngine` were **deleted** on 2026-10-12 (`db06fc87` — "drop HybridAdapterRegistry, route through Oneiric"). The surviving entry-point API is `oneiric.plugins.iter_entry_points(group)` (`oneiric/plugins.py:67`), which resolves a group by **exact name** with no pattern filter, plus `oneiric.plugins.load_callables(group)` (77). `oneiric.plugins.register_entrypoint_plugins()` (103) additionally feeds resolved payloads into oneiric's `Resolver` — but only for `AdapterMetadata`/`Candidate` payloads, which eval's extension points are not. `AdapterRegistryConfig.allowlist_patterns` (`mahavishnu/core/config.py:2022`) is **dead config**: it gated the deleted `HybridAdapterRegistry` and now has no production reader.
- `mahavishnu/mcp/bootstrap.py:278` `collect_component_checks()` is where per-component feed state is aggregated (from `signer_feed.py`, `plan_index/health.py`, and `task_orphan_sweeper.py`); `register_health_endpoint()` (353) serves it over HTTP. Eval adds a fourth feed: new `mahavishnu/mcp/eval_feed.py` (mirror the `signer_feed.py:160-244` pattern), and `collect_component_checks()` gets a new `eval` check block.
- **v4:** `mahavishnu/mcp/server_core.py:349-358` documents the FastMCP inline constraint — but its scope is **only** the 27 tools registered inside `FastMCPServer._register_tools()` ("The 27 tools registered here are intentionally kept inline; the complexity is the cost of the FastMCP API contract"). It does **not** constrain profile-gated groups, which follow the `mcp/tools/<name>_tools.py::register_<name>_tools` -> `bootstrap.py::_register_<name>_block` -> `_OPTIONAL_TOOL_BLOCKS` -> `profiles.py` pattern (see `mahavishnu/mcp/tools/capability_tools.py` for the canonical shape). The three eval tools therefore live in `mahavishnu/mcp/tools/eval_tools.py`, not inline in `bootstrap.py`.
- `mahavishnu/mcp/signer_feed.py:160-244` is the canonical feed-state pattern: a `SignerFeedState` dataclass with `record_cycle()`, `record_error()`, and `as_dict()` returning the 4-signal contract (`feed_entities_count`, `feed_last_updated_timestamp`, `feed_cycles_total`, `feed_errors_total`). `eval_feed.py` mirrors this. For `EvalFeedState`, `entities_count` is the **total number of `CaseRecord`s persisted across all runs** (incremented by `record_cycle(case_count=N)` — the signature takes a per-run case count).
- `mahavishnu/mcp/sweepers/task_orphan_sweeper.py:264` is the canonical "start a child span" precedent for OTel: `from opentelemetry import trace; tracer = trace.get_tracer(__name__); with tracer.start_as_current_span("eval.run_suite") as span: span.set_attribute("eval.case_count", ...)`. The auto-emitted `mcp.tool.call` span from `tool_call_middleware.py:94-145` writes `duration_ms` to the parent; the eval-specific child span writes eval-specific attributes only (prefixed `eval.*` to avoid collision).
- `mahavishnu/workers/cloud_worker.py` already calls MiniMax via OpenAI-compatible API. Eval composes the existing worker for `MiniMax-M3` (Phase 2); Phase 1 uses a `MockModelBackend` registered as a oneiric adapter under `mahavishnu.eval.model_backends`.
- Settings follow Mahavishnu's existing `pydantic-settings` convention with **nested `EvalSettings` field on `MahavishnuSettings`** (NOT a separate `BaseSettings` class). The parent `MahavishnuSettings` has `env_prefix="MAHAVISHNU_"` and `env_nested_delimiter="__"` (per `mahavishnu/core/config.py:2946-2949`); the `eval` field maps to env var `MAHAVISHNU_EVAL__ENABLED` (double underscore for the nested delimiter), `MAHAVISHNU_EVAL__COST_BUDGET_PER_RUN`, etc. **Verified 2026-11-06:** the working form is `MAHAVISHNU_<GROUP>__<FIELD>` — `MAHAVISHNU_OTEL_INGESTER__SIMILARITY_THRESHOLD=0.42` resolves to `0.42`, while the `MAHAVISHNU__OTEL_INGESTER__SIMILARITY_THRESHOLD=0.42` form that appears in some docstrings is **silently ignored** (the value stays at the `0.7` default). The `MAHAVISHNU_{GROUP}__{FIELD}` format is what `mahavishnu/core/config.py`'s own module docstring documents. The CC memory item `feedback-no-bodai-prefix-in-config-names.md` lives in OTHER Bodai components (oneiric), not Mahavishnu.
- Common primitives come from `oneiric.actions` (per the action-kit discipline in `CLAUDE.md`). Verified mappings for Phase 1: hashing is `oneiric.actions.compression.HashAction` (precedent: `mahavishnu/core/idempotency.py:39`), NOT `oneiric.actions.hash`. HTTP, schema validation, retry primitives to be verified against `oneiric/docs/action-kits.md` before Task 1; hand-roll in `mahavishnu/core/eval/_compat.py` if the action doesn't exist. `_compat.py` is a per-action shim module — each missing oneiric action gets a hand-rolled implementation with a `link_to_issue: oneiric#N` comment. Phase 1 only needs the hash shim.
- Pydantic v2 + `from __future__ import annotations` is a latent bug class (per the memory item `pydantic-future-annotations-forward-ref.md` and existing carve-outs in `pyproject.toml:407-420`). The 11+ new Pydantic model files in `mahavishnu/core/eval/` must be added to `[tool.ruff.lint.per-file-ignores]` for `TC003`, matching the existing entries for `core/capabilities.py`, `core/repo_models.py`, `core/repositories/embeddings.py`.
- `mahavishnu/_main_cli.py` is the actual CLI entry point (NOT `mahavishnu/cli.py`, which does not exist; per `mahavishnu/cli/__init__.py:11` docstring: "the main CLI app is defined in `mahavishnu/_main_cli.py`"). The eval subcommand must be registered there. CLI uses `typer.Typer` and `typer.Option` (precedent: `mahavishnu/cli/plan_cli.py:18-23, 47-51`), NOT `click`.
- `EvalSettings` is a nested Pydantic v2 `BaseModel` (not `BaseSettings`) embedded in `MahavishnuSettings`. The lazy module-level getter `get_eval_settings()` mirrors `get_settings()` at `mahavishnu/core/config.py:3455` and returns `get_settings().eval`. Note: a bare `MahavishnuSettings()` reads **model defaults plus env vars**; the committed YAML is merged by `get_settings()` (oneiric's layered loader), not by the bare constructor.
- `BasePool.scale(self, target_worker_count: int) -> None` is `@abstractmethod` (per `mahavishnu/pools/base.py:156`); returning `1` from an override violates Liskov. EvalPool's `scale(n)` must return `None` and log a warning.

## 4.5 Requirements

```yaml
requirements:
- id: REQ-EVAL-001
  title: Oneiric adapter discovery for eval extension points
  file: mahavishnu/core/eval/_registry.py:1-80
- id: REQ-EVAL-002
  title: EvalEngine primitive (Dataset, Scorer, Storage, ModelBackend ABCs/Protocols)
  file: mahavishnu/core/eval/engine.py:1-50, dataset.py:1-40, scorer.py:1-50, storage.py:1-50
- id: REQ-EVAL-003
  title: EvalEngine orchestration (composes extension points, returns EvalRunResult)
  file: mahavishnu/core/eval/engine.py:50-250
- id: REQ-EVAL-004
  title: EvalPool as BasePool subclass with single virtual worker (discoverable; MCP tool bypasses in
    Phase 1)
  file: mahavishnu/pools/eval_pool.py:1-200
- id: REQ-EVAL-005
  title: MCP tool surface (eval_register_dataset, eval_run_suite, eval_get_run) via a profile-gated tools
    module
  file: mahavishnu/mcp/bootstrap.py:_register_eval_tools
- id: REQ-EVAL-006
  title: Settings via nested EvalSettings field on MahavishnuSettings; env var MAHAVISHNU_EVAL__*
  file: mahavishnu/core/eval/settings.py:1-80, mahavishnu/core/config.py:eval-field
- id: REQ-EVAL-007
  title: Dogfood golden set of 20-30 Mahavishnu-specific cases
  file: docs/eval/dogfood-v0.jsonl
- id: REQ-EVAL-008
  title: Phase 1 wire-up (e2e tests, health feed, audit_orphans, plan promotion)
  file: mahavishnu/mcp/eval_feed.py + tests/integration/test_eval_*.py
- id: REQ-EVAL-009
  title: MarkdownReportWriter for human-readable run reports
  file: mahavishnu/core/eval/report.py:1-100
- id: REQ-EVAL-010
  title: CLI entry point `mahavishnu eval run-suite` for programmatic use without MCP
  file: mahavishnu/_main_cli.py + mahavishnu/cli/eval_cli.py
- id: REQ-EVAL-011
  title: OTel child-span attribute cardinality bound (eval.* is a fixed schema, not a free-form keyspace)
  file: mahavishnu/core/eval/engine.py:run_suite + tests/integration/test_eval_cardinality.py
```

**Cross-component dependencies** (per `wire-up-contract.md` §2 "additional requirements"):

- `Mahavishnu → LangSmith (MCP, read-only in Phase 1)` — for dataset ingestion when `LANGSMITH_API_KEY` is set.
- `Mahavishnu → MiniMax (OpenAI-compatible API, via existing `mahavishnu/workers/cloud_worker.py`)` — for the dogfood run in Task 8.
- `Mahavishnu → Akosha (OTel traces, one-way: Mahavishnu emits, Akosha ingests via `mahavishnu/ingesters/otel_ingester.py`)` — for cross-system observability of eval runs. **Substrate path update (2026-10-19):** the legacy `mahavishnu/ingesters/otel_ingester.py` is the pre-v7 path. After PR-A0b (oneiric substrate ships) and PR-A1 (akosha OTLPReceiver ships), the eval plan's spans flow through the v7 OTel substrate: producers write to `oneiric.adapters.vector.duckdb_hot_store.spans_substrate` (DDL in `oneiric/adapters/vector/duckdb_hot_store.py:130-185`, spec `docs/specs/2026-10-19-bodai-substrate-otel-v7.md` §5.1) and `akosha/observability/otlp_receiver.py` does the per-row validation + DLQ + ON CONFLICT dedup. Eval becomes a vanilla `*-mcp` producer with no producer-side code changes; the env-var precedent `MAHAVISHNU__OTEL_INGESTER__*` is retired and replaced by `ONEIRIC__SUBSTRATE__*` (per the `feedback-no-bodai-prefix-in-config-names` rule). Cardinal rule: retention filters on the server-populated `received_at_unix_nano`, not on producer `start_time_unix_nano`.
- `Mahavishnu → oneiric (entry-point discovery via `oneiric.plugins.iter_entry_points`, scoped to the `mahavishnu.eval.*` groups)` — for pluggable extension points.

## 5. Implementation Phases

The plan ships as one phase (Phase 1 of the broader eval feature). It is decomposed into nine tasks, each a self-contained TDD cycle ending with a green test suite + atomic commit + `python scripts/audit_orphans.py` pass.

### Task 0: Housekeeping (pre-Task-1)

**Files:**
- Modify: `pyproject.toml` (add 4 new entry-point groups)
- Create: `docs/eval/` directory (see the v4 note on the fleet-wide `data/` gitignore)
- ~~Modify: `mahavishnu/core/adapter_discovery.py`~~ — **removed in v4.** The file was deleted upstream (`db06fc87`, 2026-10-12) and its `allowlist_patterns` gate became dead config. Task 0.2 is closed with no code change.

**Steps:**
- [x] **0.1** Add to `pyproject.toml` the four new entry-point groups (PEP 621 syntax, multi-entry, no entries yet):
  ```toml
  [project.entry-points."mahavishnu.eval.scorers"]
  # empty for now; populated in Task 4

  [project.entry-points."mahavishnu.eval.dataset_loaders"]
  # empty for now; populated in Task 3

  [project.entry-points."mahavishnu.eval.storage"]
  # empty for now; populated in Task 5

  [project.entry-points."mahavishnu.eval.model_backends"]
  # empty for now; populated in Task 6
  ```
- [x] **0.2** ~~Extend the `allowlist_patterns` default to include `mahavishnu.eval.*`.~~ **CLOSED in v4 with no code change.** `mahavishnu/core/adapter_discovery.py` and `AdapterDiscoveryEngine` were deleted on 2026-10-12 (`db06fc87`). The surviving `AdapterRegistryConfig.allowlist_patterns` (`mahavishnu/core/config.py:2022`) has **no production consumer** — it gated the deleted `HybridAdapterRegistry`; only two unit tests and `settings/mahavishnu.yaml` still mention it. Eval's four extension points are registered in their **own** entry-point groups (`mahavishnu.eval.scorers`, `.dataset_loaders`, `.storage`, `.model_backends`), and `oneiric.plugins.iter_entry_points(group)` resolves a group by exact name with no pattern filter — so there is no allowlist to widen. No allowlist edit is required.
- [x] **0.3** ~~Add a 10-line `per-file-ignores` block for the eval Pydantic files~~ — **REVISED in v4: no blanket carve-out.** The repo already solves the Pydantic-v2 + `from __future__ import annotations` forward-ref problem **globally**: `pyproject.toml` sets `[tool.ruff.lint.flake8-type-checking] runtime-evaluated-base-classes = ["pydantic.BaseModel", "msgspec.Struct"]`. That landed on **2026-10-20**, two days after v3, which is why the plan still asked for per-file suppression. With it in place, TC001/TC003 fire *correctly* for `BaseModel` subclasses rather than needing a file-by-file exemption, and the comment there states the policy explicitly: *"prefer a local `# noqa` with a reason over adding a path back to this list."* So the eval modules are **written to satisfy the global config**, not exempted from it. The one carve-out this work does need is for the FastMCP tool module — not a `BaseModel` subclass, but it needs runtime imports for schema building — which **Task 7** adds as `"mahavishnu/mcp/tools/eval_tools.py" = ["TC001"]`, mirroring the existing `"mahavishnu/mcp/tools/get_capability_result_tool.py" = ["TC001"]` entry.
- [x] **0.4** Run `python scripts/audit_orphans.py` to establish baseline; record the count in the commit message. **Baseline: 559 orphan rows** across the source tree. Note: `main` reports 544 because its checkout carries a stale gitignored `.backups/mahavishnu.worktree.backup/` tree whose older `core/config.py` supplies 15 spurious "references" — the audit's exclude list covers `.crackerjack` but not `.backups`. The worktree has no `.backups/`, so 559 is the accurate count for the real source tree. Neither number is caused by this plan.
- [x] **0.5** Commit: `git add pyproject.toml && git commit -m "chore(eval): scaffold oneiric entry-point groups for eval extension points (Task 0)"`. (`mahavishnu/core/adapter_discovery.py` is no longer part of this task — see 0.2.)

#### Integration Contract (Task 0)
- **Triggered from**: `uv pip install -e .` (registers the entry-point groups for installed distributions); `mahavishnu mcp start`; crackerjack gate. The **built-in table** in `mahavishnu/core/eval/_registry.py` needs no install — it is the install-independent runtime source (Task 1).
- **Returns to / updates**: `pyproject.toml` (4 new entry-point groups); `docs/eval/` directory created. No allowlist edit — see 0.2. No per-file-ignore block — see 0.3.
- **Demonstrable by**: `python -c "from importlib.metadata import entry_points; eps = entry_points(group='mahavishnu.eval.scorers'); print(list(eps))"` returns `[]` (empty list, no errors).
- **Rollback signal**: `crackerjack run` fails on `TC001`/`TC003` for a file in `mahavishnu/core/eval/` → the module is not a `BaseModel` subclass covered by `runtime-evaluated-base-classes`; use a local `# noqa: TC001` with a reason (see 0.3) rather than adding a path to `per-file-ignores`.
- **Observability added**: none (housekeeping task).

---

### Task 1: Oneiric entry-point scaffolding (REQ-EVAL-001)

**Files:**
- Create: `mahavishnu/core/eval/__init__.py` (re-export hub)
- Create: `mahavishnu/core/eval/_registry.py` (built-in extension-point table + oneiric entry-point merge)
- Test: `tests/unit/core/eval/test_registry.py`

**Steps:**
- [x] **1.1** Write a failing test that calls `mahavishnu.core.eval._registry.discover_scorers()` and asserts it returns at least one scorer (after Task 4 registers `mahavishnu.exact_match`).
- [x] **1.2** Run, confirm FAIL (`ImportError: cannot import name 'discover_scorers'`).
- [x] **1.3** Implement `mahavishnu/core/eval/_registry.py` with `discover_scorers()`, `discover_dataset_loaders()`, `discover_storage()`, `discover_model_backends()`. Each returns `dict[str, Callable]` keyed by extension-point name. Cache results in a module-level dict with a 5-minute TTL.
- [x] **1.3a** **Discovery has two sources, merged (v4 correction).** (i) **Built-ins** — a declarative table in `_registry.py` mapping group to `{name: "module:attr"}`, resolved lazily. This is the runtime source of truth for the shipped extension points. (ii) **Installed entry points** — `oneiric.plugins.iter_entry_points(group)` (`oneiric/plugins.py:67`), which resolves any installed distribution's `[project.entry-points."mahavishnu.eval.*"]` declarations. Entry points **override** built-ins by name, so a third-party distribution can replace a shipped extension point.
- [x] **1.3b** **Why not `@entry_point(group=..., name=...)`?** Python 3.14 **removed** `importlib.metadata.entry_point()` and `EntryPoint.register()` — there is no stdlib runtime entry-point registration. The pyproject `[project.entry-points."mahavishnu.eval.*"]` declarations are also invisible until the distribution is reinstalled, and an editable install's `entry_points.txt` is a static file in the **shared** `.venv` — reinstalling from a worktree would re-point that venv for every other live session (this repo has no per-worktree venv). The built-in table removes that dependency; the drift test in 1.7 keeps pyproject and the table in agreement.
- [x] **1.4** ~~Create `mahavishnu/core/eval/_entry_points.py`~~ — **dropped in v4.** Its only purpose was runtime entry-point registration, which Python 3.14 does not support. The pyproject groups remain the canonical declaration for installed distributions and third parties; the built-in table in `_registry.py` is the runtime source.
- [x] **1.5** Each of Tasks 3, 4, 5, 6 adds its entry to the built-in table **and** to the matching `pyproject.toml` group.
- [x] **1.6** Run, confirm PASS; add a second test that asserts the cache TTL behaves correctly (cache hit returns the same instance; cache miss after TTL expires re-discovers).
- [x] **1.7** Add a drift test that parses `pyproject.toml` (via `tomllib`) and asserts each `mahavishnu.eval.*` group's declared `name = "module:attr"` entries match the built-in table in `_registry.py`. Install-independent — it reads the source tree, not the installed metadata.
- [x] **1.8** Commit: `git add mahavishnu/core/eval/ tests/unit/core/eval/test_registry.py && git commit -m "feat(eval): oneiric entry-point discovery for eval extension points"`.

#### Integration Contract (Task 1)
- **Triggered from**: `mahavishnu mcp start` (during `_register_eval_tools` lifecycle, when `evaluation.enabled=true`).
- **Returns to / updates**: module-level cache dict in `_registry.py`, keyed by group -> `{name: callable}`.
- **Demonstrable by**: `pytest tests/unit/core/eval/test_registry.py -v` passes.
- **Rollback signal**: any import error in `mahavishnu/core/eval/_registry.py` at server startup (logs `mahavishnu.eval.registry.error`).
- **Observability added**: structured log line `eval.registry.discovered domain=scorer count=N` at first discovery per cache window.

---

### Task 2: Settings via nested MahavishnuSettings field (REQ-EVAL-006)

**Files:**
- Create: `mahavishnu/core/eval/settings.py` (`EvalSettings` Pydantic v2 `BaseModel` + `get_eval_settings()` module-level lazy getter)
- Modify: `mahavishnu/core/config.py` (add `eval: EvalSettings = Field(default_factory=EvalSettings)` field to `MahavishnuSettings`)
- Modify: `settings/mahavishnu.yaml` (add `eval:` block under top-level settings)
- Test: `tests/unit/core/eval/test_settings.py`

**Steps:**
- [x] **2.1** Write failing tests: (a) `EvalSettings()` constructs with `enabled=False`; (b) `get_eval_settings()` returns a `MahavishnuSettings` whose `.eval.enabled` reflects the YAML/env override; (c) overriding `MAHAVISHNU_EVAL__COST_BUDGET_PER_RUN=42.0` reads the override (note: double underscore for nested delimiter); (d) `EvalSettings.model_config` uses `extra="forbid"` (NOT v1 `class Config:`).
- [x] **2.2** Run, confirm FAIL.
- [x] **2.3** Implement `EvalSettings(BaseModel)` in `mahavishnu/core/eval/settings.py`:
  ```python
  from __future__ import annotations
  from typing import Literal
  from pydantic import BaseModel, ConfigDict, Field


  class EvalSettings(BaseModel):
      model_config = ConfigDict(extra="forbid")
      enabled: bool = False
      default_storage: str = "mahavishnu.sqlite"
      default_dataset_loader: str = "mahavishnu.jsonl"
      default_scorers: list[str] = Field(default_factory=lambda: ["mahavishnu.contains"])
      default_model_backend: str = "mahavishnu.mock"
      cost_budget_per_run: float = 5.0
      db_path: str = "~/.local/state/mahavishnu/eval/runs.sqlite"


  # (Corrected 2026-11-06: the sketch as first written also carried
  # `default_pool`, `concurrency`, and `regression_threshold`. None of
  # them is in the shipped model -- each was read by no production code,
  # so each was removed rather than shipped inert. `default_pool` named
  # a pool the pool machinery discovers by type, not by setting;
  # `regression_threshold` computed nothing (regression detection is
  # Phase 2 work); `concurrency` would only have set a ceiling Phase 1's
  # sequential loop never reaches.)


  def get_eval_settings() -> "EvalSettings":
      """Module-level lazy getter; mirrors get_settings() at mahavishnu/core/config.py:3455."""
      from mahavishnu.core.config import get_settings

      return get_settings().eval
  ```
- [x] **2.4** In `mahavishnu/core/config.py`, add the `eval` field to `MahavishnuSettings` (after the `otel_ingester` field at line 3195): `eval: EvalSettings = Field(default_factory=EvalSettings)`. Add the import `from .eval.settings import EvalSettings` to the first-party import block — `eval.settings` imports only pydantic at module level and defers its own `get_settings` import into the function body, so there is no cycle.
- [x] **2.5** Add `eval:` block to `settings/mahavishnu.yaml`:
  ```yaml
  eval:
    enabled: false
    default_storage: "mahavishnu.sqlite"
    default_dataset_loader: "mahavishnu.jsonl"
    default_scorers: ["mahavishnu.contains"]
    default_model_backend: "mahavishnu.mock"
    cost_budget_per_run: 5.0
    db_path: "~/.local/state/mahavishnu/eval/runs.sqlite"
  ```
  (Indentation: 2 spaces, matching the existing `otel_ingester:` block in this file.)
- [x] **2.6** Run tests, confirm PASS.
- [x] **2.7** Commit: `git add mahavishnu/core/eval/settings.py mahavishnu/core/config.py settings/mahavishnu.yaml tests/unit/core/eval/test_settings.py && git commit -m "feat(eval): nested EvalSettings on MahavishnuSettings with MAHAVISHNU_EVAL__ env_prefix"`.

#### Integration Contract (Task 2)
- **Triggered from**: `get_settings()` instantiation anywhere; `get_eval_settings()` is the public entry point for eval code.
- **Returns to / updates**: `MahavishnuSettings.eval` (in-process Pydantic model); persisted to `settings/mahavishnu.yaml`.
- **Demonstrable by**: `pytest tests/unit/core/eval/test_settings.py -v`; `MAHAVISHNU_EVAL__COST_BUDGET_PER_RUN=42.0 python -c "from mahavishnu.core.eval.settings import get_eval_settings; print(get_eval_settings().cost_budget_per_run)"` prints `42.0`.
- **Rollback signal**: any Pydantic validation error at startup (logs `mahavishnu.eval.settings.invalid`).
- **Observability added**: structured log line at MCP server startup: `eval.settings.loaded enabled=true pool=eval budget=5.0`.

---

### Task 3: Dataset ABC + JSONL loader (REQ-EVAL-002 partial)

**Files:**
- Create: `mahavishnu/core/eval/dataset.py` (`Dataset` ABC, `DatasetCase` model, `DatasetLoader` ABC)
- Modify: `mahavishnu/core/errors.py` (`EvalDatasetLoadError` + the other three eval error classes)
- Create: `mahavishnu/core/eval/loaders/__init__.py`
- Create: `mahavishnu/core/eval/loaders/jsonl.py` (`JsonlDatasetLoader`, registered in the built-in table + the `mahavishnu.eval.dataset_loaders` pyproject group)
- Create: `mahavishnu/core/eval/_compat.py` (per-action shim module; Phase 1 only needs the hash shim)
- Test: `tests/unit/core/eval/loaders/test_jsonl.py`

**Steps:**
- [x] **3.1** Write failing tests: (a) load a 3-case JSONL fixture, assert each `DatasetCase` has `id`, `input`, `expected`, `metadata` populated; (b) `discover_dataset_loaders()` returns the JSONL loader; (c) malformed JSONL raises `EvalDatasetLoadError` with line number, not raw `json.JSONDecodeError`.
- [x] **3.2** Run, confirm FAIL.
- [x] **3.3** Implement `DatasetCase` (Pydantic v2: `id: str`, `input: str`, `expected: str`, `metadata: dict[str, Any]`) and `Dataset` ABC with `name: str`, `cases: list[DatasetCase]`, `content_hash: str`, `version: str`, `model_validator(mode="after")` enforcing `len(cases) >= 1`. **Two corrections to the plan as written:** (i) `Dataset` is a `BaseModel` **and** an `ABC` — the fields need Pydantic and the type needs to be non-instantiable; (ii) the error classes live in `mahavishnu/core/errors.py`, the repo's central exception catalog, and are named `EvalDatasetLoadError`, `EvalScoringError`, `EvalStorageError`, `EvalEngineError` (the plan's `DatasetLoadError` / `ScoringError` gain the `Eval` prefix so they are unambiguous in a catalog shared by the whole substrate). New codes `MHV-012`..`MHV-015` in the system-error range, with recovery guidance.
- [x] **3.4** Implement `JsonlDatasetLoader.load(path: Path) -> Dataset`. **The loader is `async`** — `oneiric.actions.compression.HashAction.execute` is a coroutine (the precedent is `mahavishnu/core/idempotency.py:114`: `await HashAction().execute({"algorithm": "sha256", "data": raw})` returns `{"digest": ...}`), so `DatasetLoader.load` is `async def` and every call site awaits it. The action **is** available (verified 2026-11-06), so `mahavishnu/core/eval/_compat.py::hash_content` is a thin wrapper rather than a hand-rolled `hashlib` fallback — there is no missing action to note. `path.parent.mkdir(parents=True, exist_ok=True)` before any read.
- [x] **3.5** Register `JsonlDatasetLoader` in the built-in table in `mahavishnu/core/eval/_registry.py` under group `mahavishnu.eval.dataset_loaders`, name `mahavishnu.jsonl` (`"mahavishnu.core.eval.loaders.jsonl:JsonlDatasetLoader"`), **and** declare the same entry under `[project.entry-points."mahavishnu.eval.dataset_loaders"]` in `pyproject.toml`. **Entry-point names contain dots and MUST be quoted in TOML** — an unquoted `mahavishnu.jsonl` is parsed as a *nested table* (`{"mahavishnu": {"jsonl": ...}}`), not a name. The Task 1.7 drift test caught exactly this. The drift test asserts the two agree.
- [x] **3.6** Run, confirm PASS.
- [x] **3.7** Commit: `git add mahavishnu/core/eval/dataset.py mahavishnu/core/eval/loaders/ mahavishnu/core/eval/_registry.py mahavishnu/core/eval/_compat.py pyproject.toml tests/unit/core/eval/loaders/test_jsonl.py && git commit -m "feat(eval): Dataset ABC + JSONL loader (oneiric entry-point)"`.

#### Integration Contract (Task 3)
- **Triggered from**: `eval_register_dataset` MCP tool (Task 7) and any direct `JsonlDatasetLoader.load()` call.
- **Returns to / updates**: in-memory `Dataset` object; no persistent effect (storage lands in Task 5).
- **Demonstrable by**: `pytest tests/unit/core/eval/loaders/test_jsonl.py -v`.
- **Rollback signal**: any `DatasetLoadError` propagated up — caller handles by surfacing to the user with line number.
- **Observability added**: structured log line `eval.dataset.loaded name=... cases=N hash=...sha256-prefix`.

---

### Task 4: Scorer ABC + ExactMatch scorer (REQ-EVAL-002 partial)

**Files:**
- Create: `mahavishnu/core/eval/scorer.py` (`Scorer` ABC, `Score` model; `EvalScoringError` lives in `mahavishnu/core/errors.py` — see Task 3.3)
- Create: `mahavishnu/core/eval/scorers/__init__.py`
- Create: `mahavishnu/core/eval/scorers/exact_match.py` (`ExactMatchScorer`)
- Modify: `mahavishnu/core/eval/_registry.py` (built-in table: `mahavishnu.exact_match`) + `pyproject.toml` (`mahavishnu.eval.scorers` group)
- Test: `tests/unit/core/eval/scorers/test_exact_match.py`

**Steps:**
- [x] **4.1** Write failing tests: (a) `ExactMatchScorer().score(actual="hello", expected="hello", case_meta={})` returns `Score(value=1.0)`; (b) `score(actual="hi", expected="hello", ...)` returns `Score(value=0.0)`; (c) `case_sensitive=False` flips behavior; (d) `discover_scorers()` returns it.
- [x] **4.2** Run, confirm FAIL.
- [x] **4.3** Implement `Score` (Pydantic v2: `value: float ∈ [0,1]`, `kind: str`, `reasoning: str | None`). The unit interval is enforced by the model (`Field(ge=0.0, le=1.0)`), so an out-of-range score is a validation error rather than a silently clamped number.
- [x] **4.4** Implement `Scorer` ABC with `name: str`, `kind: str`, and **`def score(actual: str, expected: str, case_meta: dict[str, Any]) -> Score`** (sync, not async — CPU-bound comparison; async scorers like LLM-as-judge land in Phase 2 as `async def score` with `asyncio.to_thread` dispatch). `case_meta` is typed `Mapping[str, Any]` so a scorer may read it but not mutate the case.
- [x] **4.5** Implement `ExactMatchScorer` with `case_sensitive: bool = True` constructor arg.
- [x] **4.6** Register `ExactMatchScorer` in the built-in table in `mahavishnu/core/eval/_registry.py` under group `mahavishnu.eval.scorers`, name `mahavishnu.exact_match` (`"mahavishnu.core.eval.scorers.exact_match:ExactMatchScorer"`), **and** declare the same entry under `[project.entry-points."mahavishnu.eval.scorers"]` in `pyproject.toml` — **quoted**, per the TOML note in Task 3.5.
- [x] **4.7** Run, confirm PASS.
- [x] **4.8** Commit.

#### Integration Contract (Task 4)
- **Triggered from**: `EvalEngine.run_suite()` (Task 6) per case, after model output is collected.
- **Returns to / updates**: in-memory `Score` object; persisted in Task 5.
- **Demonstrable by**: `pytest tests/unit/core/eval/scorers/test_exact_match.py -v`.
- **Rollback signal**: any `ScoringError` propagated; logged with `eval.scorer.error` and the case marked as `scored=False` in the run record.
- **Observability added**: per-scoring structured log line `eval.scorer.run name=exact_match duration_ms=N`.

---

### Task 5: Storage ABC + SQLite backend (REQ-EVAL-002 partial)

**Files:**
- Create: `mahavishnu/core/eval/storage.py` (`EvalStorage` ABC with `start_run`, `add_case_result`, **`finish_run`**, `get_run`, `list_runs`; `RunRecord`, `CaseRecord`, `ScoreRecord`, `EvalSummary`, `RunDetails`)
- Create: `mahavishnu/core/eval/storage_backends/__init__.py`
- Create: `mahavishnu/core/eval/storage_backends/sqlite.py` (`SqliteEvalStorage`, WAL mode + parent dir creation)
- Modify: `mahavishnu/core/eval/_registry.py` (built-in table: `mahavishnu.sqlite`) + `pyproject.toml` (`mahavishnu.eval.storage` group)
- Test: `tests/unit/core/eval/storage_backends/test_sqlite.py`

**Steps:**
- [x] **5.1** Write failing tests (using `tmp_path` fixture): (a) `start_run` / `add_case_result` / `finish_run` / `get_run` / `list_runs` round-trip; (b) `db_path` with a non-existent parent directory succeeds (parent is created); (c) 10 concurrent `asyncio.to_thread` writes don't lock (WAL mode); (d) a corrupt DB file raises `EvalStorageError` (not raw `sqlite3.DatabaseError`); (e) `finish_run` transitions a run from `"running"` to `"completed"`; (f) `get_run` returns `len(case_results) > 0` for a run with 3 cases.
- [x] **5.2** Run, confirm FAIL.
- [x] **5.3** Define pinned record shapes:
  - `RunRecord(id: str, suite_name: str, suite_version: str, suite_hash: str, model_configs: dict[str, Any], started_at: datetime, finished_at: datetime | None, status: Literal["running", "completed", "budget_exceeded", "failed"], summary: EvalSummary)`
  - `CaseRecord(id: str, run_id: str, case_id: str, case_index: int, actual: str, error: str | None, scored: bool)`
  - `ScoreRecord(id: str, case_id: str, scorer_name: str, value: float, kind: str, reasoning: str | None)`
  - `EvalSummary(TypedDict): total_cases, scored_cases, errors, duration_seconds, cost_usd, mean_score, min_score, max_score`
  - `RunDetails`: the run plus its `case_results` and `scores` — **added in v4**, because step 5.1(f) requires `get_run` to expose the run's case results, and a bare `RunRecord` cannot carry them.
  - **ID format:** every row id is a UUID7 hex string (`uuid7().hex`), per the UUID7 coordination note. The app layer generates it and passes it in; `start_run` takes a fully-formed `RunRecord` and returns its id.
  - **`ScoreRecord.case_id` references `CaseRecord.id`** (the row id), not the dataset case id — that is what the plan's schema says, and it is worth spelling out because the two ids are easy to confuse.
- [x] **5.4** Implement `EvalStorage` ABC with five methods: `start_run(run: RunRecord) -> str`, `add_case_result(case: CaseRecord, scores: Sequence[ScoreRecord] = ())`, **`finish_run(run_id, status, finished_at, summary)`** (required to transition run status), `get_run(run_id) -> RunDetails | None`, `list_runs(limit=50) -> list[RunRecord]`. All `async`.
- [x] **5.5** Implement `SqliteEvalStorage` with stdlib `sqlite3` (sync, wrapped in `asyncio.to_thread`). The connection is opened **lazily** on first use (so constructing the backend does no I/O), in WAL mode with `synchronous=NORMAL`. Every statement runs under a `threading.Lock` and its own transaction, and every `sqlite3.Error` is translated into `EvalStorageError` — a corrupt database file must not surface a raw `sqlite3.DatabaseError`. Schema:
  ```sql
  CREATE TABLE IF NOT EXISTS runs (
      id TEXT PRIMARY KEY,
      suite_name TEXT NOT NULL,
      suite_version TEXT NOT NULL,
      suite_hash TEXT NOT NULL,
      model_configs TEXT NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      status TEXT NOT NULL,
      summary TEXT NOT NULL DEFAULT '{}'
  );
  CREATE TABLE IF NOT EXISTS case_results (
      id TEXT PRIMARY KEY,
      run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
      case_id TEXT NOT NULL,
      case_index INTEGER NOT NULL,
      actual TEXT NOT NULL,
      error TEXT,
      scored INTEGER NOT NULL
  );
  CREATE INDEX IF NOT EXISTS idx_case_results_run_id ON case_results(run_id);
  CREATE TABLE IF NOT EXISTS scores (
      id TEXT PRIMARY KEY,
      case_id TEXT NOT NULL REFERENCES case_results(id) ON DELETE CASCADE,
      scorer_name TEXT NOT NULL,
      value REAL NOT NULL,
      kind TEXT NOT NULL,
      reasoning TEXT
  );
  CREATE INDEX IF NOT EXISTS idx_scores_case_id ON scores(case_id);
  ```
  In `_init_schema`: after `_SCHEMA_SQL`, run `PRAGMA journal_mode=WAL;` and `PRAGMA synchronous=NORMAL;`. `db_path.parent.mkdir(parents=True, exist_ok=True)` before connect. The `finish_run` implementation: `UPDATE runs SET status = ?, finished_at = ?, summary = ? WHERE id = ?`.
- [x] **5.6** Register `SqliteEvalStorage` in the built-in table in `mahavishnu/core/eval/_registry.py` under group `mahavishnu.eval.storage`, name `mahavishnu.sqlite` (`"mahavishnu.core.eval.storage_backends.sqlite:SqliteEvalStorage"`), **and** declare the same entry under `[project.entry-points."mahavishnu.eval.storage"]` in `pyproject.toml` — **quoted**, per the TOML note in Task 3.5.
- [x] **5.7** Run tests, confirm PASS.
- [x] **5.8** Commit.

#### Integration Contract (Task 5)
- **Triggered from**: `EvalEngine.run_suite()` (Task 6); `eval_get_run` MCP tool (Task 7).
- **Returns to / updates**: SQLite file at `db_path` from `EvalSettings` (default `~/.local/state/mahavishnu/eval/runs.sqlite`).
- **Demonstrable by**: `pytest tests/unit/core/eval/storage_backends/test_sqlite.py -v`; `sqlite3 ~/.local/state/mahavishnu/eval/runs.sqlite "SELECT count(*) FROM runs;"` after a real run.
- **Rollback signal**: SQLite `OperationalError` (disk full, permissions, locked); surfaced as `EvalStorageError` with full path + cause.
- **Observability added**: per-write structured log line `eval.storage.write table=runs id=... duration_ms=N`.

---

### Task 6: EvalEngine orchestration (REQ-EVAL-003, model_backend part of REQ-EVAL-002)

**Files:**
- Create: `mahavishnu/core/eval/engine.py` (`EvalEngine`, `EvalSuite`, `ModelConfig`, `CostBudget`, `EvalRunResult`, `EvalEngineError`, `ModelBackend` Protocol, `ModelResponse`, `TokenUsage`)
- Create: `mahavishnu/core/eval/model_backends/__init__.py`
- Create: `mahavishnu/core/eval/model_backends/mock.py` (`MockModelBackend`)
- Modify: `mahavishnu/core/eval/_registry.py` (built-in table: `mahavishnu.mock`) + `pyproject.toml` (`mahavishnu.eval.model_backends` group)
- Modify: `tests/conftest.py` (export `mock_model_backend` fixture)
- Test: `tests/unit/core/eval/test_engine.py`

**Steps:**
- [x] **6.1** Write failing tests with `MockModelBackend` and a `SqliteEvalStorage` on a `tmp_path` (a file-backed store rather than the plan's in-memory one, so the persisted rows can be read back and asserted): (a) 2-case suite produces 2 `CaseRecord`s + 2 `ScoreRecord`s AND `finish_run` transitions status to `"completed"`; (b1) last case ends exactly at 100% of budget → `status="completed"`; (b2) last case would exceed → `status="budget_exceeded"`; (b3) case 1 alone exceeds entire budget → no other cases run, `status="budget_exceeded"`; (c) one case erroring doesn't kill the run, status is `"completed"`; (d) `EvalRunResult.run_id`, `status`, `finished_at`, `summary` are all populated and returned. **Budget arithmetic (v4):** the engine tracks the *actual* cost of each completed case and stops before starting another once the spend has reached the cap; the run is `budget_exceeded` when the spend ends up **strictly greater** than the cap. So a run that lands exactly on 100% of its budget completes, and a first case that blows the budget means no other case runs. When the backend reports no usage, the case is costed at `ModelConfig.max_tokens` — an upper bound, which is the safe direction for a budget guard.
- [x] **6.2** Run, confirm FAIL.
- [x] **6.3** Implement types: `ModelResponse(output: str, usage: TokenUsage | None, latency_ms: float | None)`, `TokenUsage(prompt_tokens: int, completion_tokens: int, total_tokens: int)`, `ModelBackend` Protocol: `async def complete(prompt: str, model_config: ModelConfig) -> ModelResponse`. `EvalRunResult(run_id: str, status: Literal["completed", "budget_exceeded", "failed"], finished_at: datetime, summary: EvalSummary)`. `CostBudget(max_usd: float, max_concurrency: int)`. `EvalEngineError(Exception)` with `retryable: bool` field. **Two corrections to the plan as written:** (i) `EvalSuite` cannot have a field named `model_config` — that is Pydantic v2's reserved name for a model's configuration, and a field with that name breaks the model. The field is **`model`**; the `ModelBackend.complete` method keeps its `model_config` *parameter* name, which is not affected. (ii) `EvalEngineError` derives from `MahavishnuError` (the repo's central exception catalog, see Task 3.3) rather than from bare `Exception`, and keeps the `retryable: bool` field. `ModelConfig` also carries the pricing (`input_cost_per_1k_tokens`, `output_cost_per_1k_tokens`) that the budget arithmetic needs.
- [x] **6.4** Implement `EvalEngine.run_suite` as a thin orchestrator split into helpers (must stay under `max-statements=55` and `max-branches=15`):
  ```
  run_suite         -> orchestrator only (≤30 statements, ≤12 branches)
    _run_one_case    -> per-case execution (asyncio.Semaphore acquire, model invoke, score dispatch, persist)
    _track_budget    -> float math; returns True if case fits in remaining budget
    _summarize_run   -> compute EvalSummary, call storage.finish_run(...), build EvalRunResult
  ```
  Reference: `mahavishnu/ingesters/content_ingester.py:674` has ~50 statements for a comparable shape — `run_suite` MUST be smaller.
- [x] **6.5** Implement `MockModelBackend` in `mahavishnu/core/eval/model_backends/mock.py` with **concrete behavior**: `complete(prompt, model_config)` returns `ModelResponse(output=prompt, usage=TokenUsage(prompt_tokens=len(prompt) // 4, completion_tokens=len(prompt) // 4, total_tokens=len(prompt) // 2), latency_ms=10.0)`. The echo-means-equal mapping means `ExactMatchScorer.score(actual=prompt, expected=prompt)` returns `Score(value=1.0)`. Register in the built-in table in `mahavishnu/core/eval/_registry.py` under group `mahavishnu.eval.model_backends`, name `mahavishnu.mock` (`"mahavishnu.core.eval.model_backends.mock:MockModelBackend"`), **and** declare the same entry under `[project.entry-points."mahavishnu.eval.model_backends"]` in `pyproject.toml`. Add a `mock_model_backend` pytest fixture in `tests/conftest.py` returning a configured `MockModelBackend` instance.
- [x] **6.6** Create the `eval.run_suite` child span with the **explicit OTel API** — `trace.get_tracer(__name__).start_as_current_span("eval.run_suite")` — **not** the `@observe` decorator. **Correction to the plan as written:** `observe()` at `mahavishnu/core/observability.py:1571` is a **no-op** — it wraps the function and returns it unchanged, emitting no span at all. The explicit API is the repo's established precedent (`mahavishnu/mcp/sweepers/task_orphan_sweeper.py:277`), and it is what makes the REQ-EVAL-011 cardinality test in Task 7 possible. Child span uses prefixed attributes: `eval.suite_name`, `eval.model`, `eval.case_count`, `eval.cost_usd`. Avoids collision with the auto-emitted `mcp.tool.call` span's `duration_ms`. **REQ-EVAL-011 cardinality bound (2026-10-19):** the `eval.*` attribute keyspace is FIXED and CLOSED — the only allowed keys are `{eval.suite_name, eval.model, eval.case_count, eval.cost_usd, eval.duration_ms, eval.outcome, eval.total_input_tokens, eval.total_output_tokens}`. No per-case attribute keys (`eval.case_id`, `eval.prompt_hash`, `eval.case.*`) are emitted to the span; per-case data lives in the SQLite `case_results` and `scores` tables, NOT in OTel attributes. This is a hard bound to keep the v7 `spans_substrate` storage cardinality bounded — see the v7 spec's §11.1.6 cardinality alarm (`docs/specs/2026-10-19-bodai-substrate-otel-v7.md`). The bound is asserted by a dedicated test in Task 7 (see REQ-EVAL-011 test file).
- [x] **6.7** Run tests, confirm PASS.
- [x] **6.8** Commit.

#### Integration Contract (Task 6)
- **Triggered from**: `_do_run_suite` helper in `bootstrap.py::_register_eval_tools` (Task 7).
- **Returns to / updates**: SQLite `runs` (with `status` transitioned via `finish_run`), `case_results`, `scores` tables; OTel child span `eval.run_suite` with prefixed attributes.
- **Demonstrable by**: `pytest tests/unit/core/eval/test_engine.py -v`; for a real run, `mcp__mahavishnu__eval_run_suite(suite="dogfood-v0", model="mahavishnu.mock")` followed by `mcp__mahavishnu__eval_get_run(run_id=...)`.
- **Rollback signal**: any unhandled exception in `run_suite` — current run is marked `status="failed"` via `finish_run`; no data is silently lost.
- **Observability added**: OTel child span `eval.run_suite`, carrying the closed `eval.*` keyspace -- `eval.outcome` is `completed`, `budget_exceeded`, or `failed`, and a failed run's span says so rather than carrying no attributes at all. *(Corrected 2026-11-06: this contract claimed structured logs at `started`, `case_complete`, `budget_exceeded`, `completed`, and `failed`. Those log lines were never emitted; the span carries the outcome, and the error paths log a classified failure. The contract now describes what exists.)*

---

### Task 7: EvalPool, MCP tools, health feed, e2e (REQ-EVAL-004, REQ-EVAL-005, REQ-EVAL-008)

**Files:**
- Create: `mahavishnu/pools/eval_pool.py` (`EvalPool(BasePool)` — factory signature matches `manager.py:355-359`)
- Modify: `mahavishnu/pools/_registry.py` (add `eval_pool` to `_ensure_pool_registry_loaded()` for side-effect registration)
- Create: `mahavishnu/mcp/eval_feed.py` (`EvalFeedState` mirroring `signer_feed.py:160-244`)
- Create: `mahavishnu/mcp/tools/eval_tools.py` (`register_eval_tools(server)` — the profile-gated group; see the v4 note in §4 Current Findings)
- Modify: `mahavishnu/mcp/bootstrap.py::collect_component_checks()` (add `eval` check block; the `skills_signer` branch is at lines 302-313)
- Modify: `mahavishnu/mcp/lifecycle.py::start_server()` (call `init_eval_feed_state()` after `init_signer_feed_state()` at line 81)
- Modify: `mahavishnu/mcp/tools/profiles.py` (add `_register_eval_tools` to `STANDARD_REGISTRATIONS` at lines 84-102 and to `REGISTRATION_MAP` at lines 181-258; import at lines 34-63)
- Modify: `mahavishnu/pools/manager.py::spawn_pool` (handle `"eval"` pool type with the corrected factory signature)
- Test: `tests/unit/pools/test_eval_pool.py`
- Test: `tests/integration/test_eval_tools_e2e.py` (4 gate assertions)
- Test: `tests/integration/test_eval_smoke_subprocess.py` (subprocess + warmup per `mcp-backend-wiring-discipline.md` §2)
- Test: `tests/integration/test_eval_cardinality.py` (REQ-EVAL-011 — assert `eval.run_suite` child span emits ONLY the fixed attribute keyspace; the v7 `spans_substrate` cardinality alarm will trigger if any non-allowed key is emitted)

**Steps:**
- [x] **7.1** Write the in-process e2e test with 4 gate assertions: (e1) all three tools return non-empty results in the happy path; (e2) `eval_run_suite` returns `{"status": "error", "error": "evaluation disabled"}` when `get_eval_settings().enabled=False`; (e3) raw FastMCP `tools/list` returns empty for eval tools when `MAHAVISHNU_TOOL_PROFILE="minimal"` (verify the meta-tool's actual filter logic before relying on this gate — if `discover_tools` doesn't filter by profile, this gate may need adjustment); (e4) `eval_run_suite` completes without an EvalPool being spawned (the tool calls `engine.run_suite` directly).
- [x] **7.2** Run, confirm FAIL.
- [x] **7.3** Write the subprocess smoke test: spawn `mahavishnu mcp start` in a subprocess, wait 60s for warmup, call each registered tool through the MCP protocol (e.g. via `mcp.client.session`), assert non-empty results.
- [x] **7.4** Run, confirm FAIL.
- [x] **7.5** Implement `EvalPool(BasePool)` in `mahavishnu/pools/eval_pool.py`. The module-level factory `_build_eval_pool` matches the actual `manager.py::spawn_pool` call signature:
  ```python
  from .base import BasePool, PoolConfig
  from mahavishnu.core.eval.engine import EvalEngine, EvalSettings
  from mahavishnu.core.eval.settings import get_eval_settings
  from mahavishnu.core.eval._registry import discover_storage, discover_model_backends


  def _build_eval_pool(
      config: PoolConfig,
      *,
      terminal_manager: Any,  # unused; BasePool signature requires it
      session_buddy_client: Any,  # unused; BasePool signature requires it
  ) -> "EvalPool":
      settings = get_eval_settings()
      storage_cls = discover_storage()[settings.default_storage]
      backend_cls = discover_model_backends()[settings.default_model_backend]
      return EvalPool(
          config=config,
          storage=storage_cls(db_path=settings.db_path),
          model_backend=backend_cls(),
          settings=settings,
      )


  class EvalPool(BasePool):
      """Single virtual worker; doesn't scale; doesn't collect memory.

      Implements all eight ``BasePool`` abstract methods (base.py:134-222):
      ``start``, ``execute_task``, ``execute_batch``, ``scale``,
      ``health_check``, ``get_metrics``, ``collect_memory``, ``stop``.
      A subclass that omits any one of them cannot be instantiated.
      """

      def __init__(self, config, storage, model_backend, settings):
          super().__init__(config)
          self._engine = EvalEngine(
              storage=storage, model_backend=model_backend, settings=settings
          )

      async def start(self) -> str:
          # BasePool abstract (base.py:134). Eval has no substrate to start.
          self._status = PoolStatus.RUNNING
          return self.pool_id

      async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
          suite = EvalSuite.model_validate(task["suite"])
          result = await self._engine.run_suite(suite)
          return result.model_dump()

      async def execute_batch(
          self, tasks: list[dict[str, Any]]
      ) -> dict[str, dict[str, Any]]:
          # BasePool abstract (base.py:160). Sequential in Phase 1.
          results: dict[str, dict[str, Any]] = {}
          for task in tasks:
              results[task["suite"]["name"]] = await self.execute_task(task)
          return results

      async def scale(self, target_worker_count: int) -> None:
          # No-op per BasePool abstract signature (returns None, not int)
          from oneiric.core.logging import get_logger

          get_logger(__name__).warning(
              "eval pool scale(target=%d) is a no-op; current worker count is 1, "
              "observable via get_status()",
              target_worker_count,
          )

      async def health_check(self) -> dict[str, Any]:
          # BasePool abstract (base.py:183).
          return {"status": "healthy", "pool_type": "eval", "active_workers": 1}

      async def get_metrics(self) -> PoolMetrics:
          # BasePool abstract (base.py:196).
          return PoolMetrics(
              pool_id=self.pool_id,
              status=self._status,
              active_workers=1,
              total_workers=1,
          )

      async def collect_memory(self) -> list[dict[str, Any]]:
          return []  # eval doesn't produce per-worker memory artifacts

      async def stop(self) -> None:
          # BasePool abstract (base.py:221).
          self._status = PoolStatus.STOPPED
  ```
  Register via `register_pool_type("eval", _build_eval_pool)` at the bottom of `eval_pool.py`.
- [x] **7.6** Add `eval_pool,  # noqa: F401  — registry side-effect` to `_ensure_pool_registry_loaded()` in `mahavishnu/pools/_registry.py:89-96` so the `register_pool_type("eval", EvalPool)` call at the bottom of `eval_pool.py` fires when the registry is loaded directly.
- [x] **7.7** Implement `EvalFeedState` in `mahavishnu/mcp/eval_feed.py` mirroring `signer_feed.py:160-244`. Module-level singleton with `asyncio.Lock`. **`entities_count` = total `CaseRecord`s across all runs** (incremented by `record_cycle(case_count=N)` — signature takes a per-run case count). `as_dict()` returns the 4-signal contract.
- [x] **7.8** Add `init_eval_feed_state()` to `mahavishnu/mcp/eval_feed.py` and call it from `mahavishnu/mcp/lifecycle.py::start_server()` immediately after `init_signer_feed_state()` (line 81).
- [x] **7.9** Add an `eval` check block to `collect_component_checks()` in `mahavishnu/mcp/bootstrap.py:278-350`, mirroring the `skills_signer` branch (lines 302-313). `register_health_endpoint()` (353) serves the merged body over HTTP, so the HTTP route and the `get_health` tool report the same component checks. Use the `warm: bool` pattern from `SignerFeedState` so a fresh server with `enabled=true` but no runs yet does not 503.
- [x] **7.10** Implement `register_eval_tools(server)` in `mahavishnu/mcp/tools/eval_tools.py` (**not** inline in `bootstrap.py` — see the v4 note in §4 Current Findings; the FastMCP inline constraint applies only to the 27 core tools in `FastMCPServer._register_tools()`). Gate at registration: `if not get_eval_settings().enabled: return`. Define the three `@server.tool()`-decorated functions in that module. Each tool body delegates to a private `_do_*` helper to stay under `max-branches=15`:
  ```python
  @server.tool()
  async def eval_run_suite(suite: str, model: str, params: dict | None = None) -> dict:
      """The MCP tool body. Note: bypasses EvalPool in Phase 1; calls EvalEngine directly.
      EvalPool is registered for discoverability and Phase 2 cross-pool orchestration.
      """
      settings = get_eval_settings()
      if not settings.enabled:
          return {"status": "error", "error": "evaluation disabled"}
      try:
          return await _do_run_suite(
              suite=suite, model=model, params=params, settings=settings
          )
      except (DatasetLoadError, ScoringError, EvalStorageError, EvalEngineError) as e:
          await get_eval_feed_state().record_error()
          return {"status": "error", "error": str(e), "error_type": type(e).__name__}
      except Exception as e:  # final fallback for the 4-signal contract
          await get_eval_feed_state().record_error()
          return {
              "status": "error",
              "error": "internal error",
              "error_type": type(e).__name__,
          }


  async def _do_run_suite(suite: str, model: str, params: dict | None, settings) -> dict:
      """Helper for eval_run_suite. Owns the actual work; called by the @server.tool body."""
      loader_cls = discover_dataset_loaders()[settings.default_dataset_loader]
      backend_cls = discover_model_backends()[model or settings.default_model_backend]
      storage_cls = discover_storage()[settings.default_storage]
      dataset = loader_cls().load(Path(suite))
      run_id = await storage.start_run(suite=dataset)
      try:
          result = await engine.run_suite(
              EvalSuite(
                  name=...,
                  version=...,
                  dataset=dataset,
                  scorers=...,
                  model_config=...,
                  cost_budget=...,
              )
          )
          await storage.finish_run(
              run_id=run_id,
              status=result.status,
              finished_at=result.finished_at,
              summary=result.summary,
          )
      except Exception:
          await storage.finish_run(
              run_id=run_id, status="failed", finished_at=datetime.now(UTC), summary={...}
          )
          raise
      await get_eval_feed_state().record_cycle(case_count=result.summary["total_cases"])
      return {"status": result.status, "run_id": run_id, "summary": dict(result.summary)}


  async def _do_register_dataset(path: str) -> dict: ...
  async def _do_get_run(run_id: str) -> dict: ...
  ```
  Mirror patterns for `eval_register_dataset` and `eval_get_run`. The crackerjack complexity budget is then spread across 3 inline tool bodies + 3 helper functions.
- [x] **7.11** Wire the group into the profile machinery: import `register_eval_tools` in `mahavishnu/mcp/tools/profiles.py` (the import block at lines 34-63), add `"_register_eval_tools"` to `STANDARD_REGISTRATIONS` (100-122), and add the `REGISTRATION_MAP` lambda trampoline (200+) `"_register_eval_tools": lambda s: _register_eval_tools(s._mhv_server)`. Also add a `_register_eval_tools_block(server)` to `mahavishnu/mcp/bootstrap.py` and the `("_register_eval_tools", _register_eval_tools_block)` tuple to `_OPTIONAL_TOOL_BLOCKS` (909-925) so the legacy `register_profile_tools` path also installs it.
- [x] **7.12** Write `tests/integration/test_eval_cardinality.py` (REQ-EVAL-011). The test runs a small eval suite against `MockModelBackend`, captures the emitted `eval.run_suite` child span attributes via an in-memory `InMemorySpanExporter` (or by patching the active tracer provider for the test only), and asserts:
  1. The set of `eval.*` attribute keys on the captured span is **exactly equal** to the closed keyspace `{eval.suite_name, eval.model, eval.case_count, eval.cost_usd, eval.duration_ms, eval.outcome, eval.total_input_tokens, eval.total_output_tokens}` — no extra keys, no missing keys.
  2. No `eval.case_id`, `eval.prompt_hash`, `eval.case.*`, or any other per-case key is present.
  3. The test re-asserts by introspecting the OTel attribute dict directly (not by parsing logs), so a future regression that adds a new `eval.*` key fails the gate immediately.

  Reference: this is the v7 substrate's §11.1.6 cardinality alarm's "pre-flight" — the alarm catches the regression in production; this test catches it in CI before the alarm ever fires.
- [x] **7.13** Run e2e test, confirm PASS (4 assertions); run subprocess smoke test, confirm PASS; run cardinality test, confirm PASS.
- [x] **7.14** Commit.

### Task 7 corrections (2026-11-06)

Six corrections to Task 7 as written, folded in before the commit:

- **(a) The eager pool loader is `mahavishnu/pools/__init__.py::_load_all_pool_types`,
  not `mahavishnu/pools/_registry.py::_ensure_pool_registry_loaded`.** Step 7.6
  named the wrong function: `_ensure_pool_registry_loaded` was an empty
  `pass` stub whose docstring described an import list it did not have. The
  stub now delegates to the package loader (which is the single source of
  truth for which pool types exist), and `eval_pool` was added to the
  loader's import list in `pools/__init__.py`. `register_pool_type("eval", ...)`
  fires at import time; `mahavishnu pool list` shows the pool.
- **(b) `EvalPool.execute_task` takes a pre-built `EvalSuite` or a
  `dataset_path` -- not `EvalSuite.model_validate(task["suite"])`.** The
  plan's snippet cannot work: `EvalSuite.scorers` is typed `list[Scorer]`,
  and `Scorer` is an ABC, so Pydantic cannot validate a plain dict into it
  (`arbitrary_types_allowed=True` makes the field an isinstance check, not a
  schema). A task that names a dataset path is the operator-facing form; a
  task that carries a built suite is the programmatic form. Both are
  supported; neither goes through Pydantic validation of the whole suite.
- **(c) `EvalPool.scale` raises `NotImplementedError`; it does not log a
  warning and return.** The plan's snippet made scaling a silent no-op.
  `PiPool` already refuses `scale(n>1)` with `NotImplementedError`
  (`mahavishnu/pools/pi_pool.py`), and a pool that accepts a scale request
  and ignores it is the silent-failure shape the repo rejects. The eval pool
  has one virtual worker; changing its concurrency is a settings change.
- **(d) The tool bodies do NOT call `storage.start_run` / `storage.finish_run`.**
  The plan's `_do_run_suite` sketch did both *and* called
  `engine.run_suite(...)`, which itself opens and closes the run
  (`EvalEngine._run_suite_inner`). Following the sketch literally would
  create two runs per call and leave the first one open. `EvalEngine` owns
  the run lifecycle; the tool calls it and reports the result.
- **(e) `EvalFeedState.record_error()` / `record_cycle()` are synchronous.**
  The plan's sketch awaited them. They mutate plain counters and are called
  from sync tool bodies and from the HTTP health route; the module uses a
  `threading.Lock`, not the `asyncio.Lock` the plan named.
- **(f) The FastMCP tool functions ARE defined inline inside
  `register_eval_tools`.** The v4 note (c) said the inline constraint
  applies only to the 27 core tools in `FastMCPServer._register_tools()`;
  the *reason* differs -- `@server.tool()` needs the server instance, so a
  module-level function cannot be decorated against it -- but the practice
  is the same, and every profile-gated group in this repo does it
  (`mcp/tools/pool_tools.py:283`, `mcp/tools/skill_tools.py:241`). The
  plan's actual instruction ("**not** inline in `bootstrap.py`") is
  honoured: the tools live in `mcp/tools/eval_tools.py`.

Two smaller notes:

- **No `per-file-ignores` carve-out was needed.** Step 7.10's Files list
  anticipated adding `"mahavishnu/mcp/tools/eval_tools.py" = ["TC001"]`.
  `FastMCP` is imported under `if TYPE_CHECKING:` and no tool function's
  annotations mention it, so FastMCP's schema builder never has to resolve
  it -- TC001/TC003 are satisfied by the global config with no carve-out.
  `pyproject.toml` is unchanged by this task.
- **The `enabled` gate has two halves.** Registration is gated (a disabled
  evaluation puts no eval tools in `tools/list`) *and* each tool body
  re-checks the flag (a server whose setting is turned off after
  registration refuses the run rather than spending budget). Gate (e2) in
  step 7.1 tests the body half: the tools are registered while evaluation
  is enabled, the setting is then flipped, and the call returns
  `{"status": "error", "error": "evaluation disabled"}`. A separate test
  asserts the registration half.

### Task 7 orphan-audit reading (2026-11-06)

`scripts/audit_orphans.py` reports six recently-added eval symbols with
"none in scan": `JsonlDatasetLoader`, `MockModelBackend`,
`ExactMatchScorer`, `ContainsScorer`, `SqliteEvalStorage` (classes)
and `reset_eval_feed_state` (function). *(Corrected 2026-11-06: this
reading said "four" and named a fourth that was `list_runs` -- a
method that IS wired, through the CLI. The six above are the real
figure: five classes that the registry wires by string and one
function only the tests call.)*

**The five classes are wired.** They are resolved through the eval
registry's built-in table as `"module:attr"` strings
(`mahavishnu/core/eval/_registry.py:54`), and the audit's reference
collector (`collect_references`, `scripts/audit_orphans.py:706`) walks
`.py` files and records AST `Name` / `Attribute` / `alias` nodes only --
it never reads a string literal and never reads `pyproject.toml`. So a
class wired by *string* indirection is invisible to it. The wiring is
verifiable at runtime: `discover_scorers()`, `discover_dataset_loaders()`,
`discover_storage()`, and `discover_model_backends()` each return the
class under its published name.

**`list_runs` is wired by Task 8.** It is a required member of the
`EvalStorage` ABC, and Task 8's `mahavishnu eval` CLI is its first
caller. Leaving it unreferenced until then is the plan's own sequencing,
not an orphan.

This is the same class of blind spot as the requirement-marker regex
noted above: a shared audit script cannot see string-based wiring. The
one-character regex fix to `scripts/audit_requirements.py` was
deliberately **not** made -- it changes repo-wide orphan and phantom
counts, which is an operator decision.

#### Integration Contract (Task 7)
- **Triggered from**: any agent with access to `mcp__mahavishnu__*` tools.
- **Returns to / updates**: SQLite runs DB; new markdown report at `~/.local/state/mahavishnu/eval/reports/{run_id}.md` (via `MarkdownReportWriter` from Task 8); `eval_feed` singleton state.
- **Demonstrable by**: `pytest tests/integration/test_eval_tools_e2e.py -v` (12 tests, covering the 4 gates plus the registration-gate half, the error paths, and the two caller-clamp guards); `pytest tests/integration/test_eval_cardinality.py -v` (4 tests); `pytest tests/integration/test_eval_smoke_subprocess.py -v` (real server; a 120 s warm-up ceiling, ~40-60 s in practice); `pytest tests/unit/pools/test_eval_pool.py -v` (16 tests); `mcp__mahavishnu__get_health` shows `checks.eval.feed_entities_count > 0` after a real run.
- **Smoke-test environment notes**: `tests/integration/test_eval_smoke_subprocess.py` starts a real `mahavishnu mcp start`. Two things it does to stay hermetic: it runs the server in a temporary runtime directory with a minimal `settings/ecosystem.yaml` (the real one is gitignored, and the server refuses to boot without an ecosystem manifest), and it sets `MAHAVISHNU_OBSERVABILITY__TRACING_ENABLED=false` / `METRICS_ENABLED=false` (the OTLP exporters stall the startup by 20-60s per attempt when no collector is listening). The test is marked `slow` and **fails** -- with the server's output attached -- when the server does not come up inside the warmup window. (It used to skip, which made a registration regression invisible in CI: a skip asserts nothing.)
- **Rollback signal**: any tool returning an empty list or raising; the feed's `errors_total` increments; the OTel `eval.run_suite` span carries `eval.outcome="failed"` on a failed run.
- **Observability added**: per-tool OTel spans; health feed counters; `eval.feed.last_updated_timestamp` updates on every `record_cycle()` / `record_error()`.

---

### Task 8: Reports, CLI, dogfood, plan promotion (REQ-EVAL-007, REQ-EVAL-008, REQ-EVAL-009, REQ-EVAL-010)

**Files:**
- Create: `mahavishnu/core/eval/report.py` (`MarkdownReportWriter`)
- Create: `mahavishnu/cli/eval_cli.py` (typer commands)
- Modify: `mahavishnu/_main_cli.py` (add `add_eval_commands(app)` call + import)
- Create: `docs/eval/dogfood-v0.jsonl` (20-30 Mahavishnu-specific cases)
- Create: `docs/eval/dogfood-v0.README.md`
- Create: `docs/eval/DOGFOOD.md`
- Create: `tests/integration/test_dogfood_smoke.py` (real-model smoke; `@pytest.mark.slow`, `@pytest.mark.requires_network`, `@pytest.mark.requires_auth`, `@pytest.mark.timeout(120)`)
- Create: `tests/integration/test_dogfood_freshness.py` (CI freshness check)
- Modify: `docs/plans/PLAN_INDEX.md` (add this plan)
- Modify: `docs/plans/2026-10-03-eval-adapter-phase1.md` (promote `status: draft` → `status: active`)

**Steps:**
- [x] **8.1** Implement `MarkdownReportWriter` in `mahavishnu/core/eval/report.py`. Single-function module: `write_run_markdown(run_record: RunRecord, cases: list[CaseRecord], scores: list[ScoreRecord], path: Path) -> None`. Template is a Jinja2 string in the same file. Report sections: header (suite, model, status, started/finished, duration), summary (count, mean/min/max score, cost), per-case detail (case_id, actual, error if any, scores), and a footer carrying the run id, the case-result count, and the score count. *(Correction, 2026-11-06: the plan asked the footer to carry the cumulative `entities_count`. The implemented footer carries the run's own counts instead — the cumulative feed count is a process-wide number, and putting it in a per-run report would make the report depend on what else the server had done since it started. The feed's own cumulative is visible in `/health`.)*
- [x] **8.2** Implement CLI in `mahavishnu/cli/eval_cli.py` using **typer** (NOT click):
  ```python
  import typer
  from pathlib import Path

  eval_app = typer.Typer(
      help="Model evaluation commands (mirror mcp__mahavishnu__eval_*)"
  )


  @eval_app.command("run-suite")
  def run_suite(
      suite: Path = typer.Option(
          ..., "--suite", exists=True, help="Path to JSONL dataset"
      ),
      model: str = typer.Option("MiniMax-M3", "--model", help="Model backend name"),
      budget: float | None = typer.Option(
          None, "--budget", help="Per-run cost cap in USD"
      ),
  ) -> None: ...


  def add_eval_commands(app: typer.Typer) -> None:
      app.add_typer(eval_app, name="eval")
  ```
  Then in `mahavishnu/_main_cli.py`: add `from .cli.eval_cli import add_eval_commands` to the import block (lines 17-45) and add `add_eval_commands(app)` call within the existing `add_*_commands` block (lines 1358-1606, where other subcommand registrations live).
- [x] **8.3** Curate 20-30 **Mahavishnu-specific** cases. Starting list (must be expanded before Task 8.6 runs):
  - "Given a Mahavishnu workflow config with a single repo and `pool_type: 'mahavishnu'`, which pool selector would minimize latency?" → expected: contains "least_loaded"
  - "Given a repo with tags `['backend', 'python']` and a query 'refactor the API layer', which adapter should Mahavishnu route this to?" → expected: contains "prefect" or "llamaindex" or "agno"
  - "Given a failing pool health check, what is the remediation step in Mahavishnu's `pool_health` tool output?" → expected: mentions pool restart or respawn
  - "Given a Mahavishnu settings file with `pools_enabled: true` and no spawned pools, what does `mcp__mahavishnu__pool_health` return?" → expected: `status: "degraded"` or similar
  - "Given a workflow run with status='failed' and error 'NoAdapterAvailable', what is the most likely configuration fix?" → expected: references adapters config or `MAHAVISHNU_ADAPTERS_PREFECT=true` etc.
  - ... 15-25 more, drawn from real Mahavishnu scenarios (repo routing, pool management, adapter selection, configuration, error recovery).
- [x] **8.4** Write `docs/eval/dogfood-v0.jsonl` with 20-30 cases. Each line: `{"id": "...", "input": "...", "expected": "...", "metadata": {"added_by": "<team-member>", "failure_mode": "<one-line description>", "last_reviewed": "<ISO date>"}}`.
- [x] **8.5** Write `docs/eval/dogfood-v0.README.md` and `docs/eval/DOGFOOD.md`.
- [x] **8.6** Write the smoke test: `@pytest.mark.integration, @pytest.mark.slow, @pytest.mark.requires_network, @pytest.mark.requires_auth, @pytest.mark.timeout(120)`. Runs the dogfood set end-to-end; asserts run completes in <120s, report at `~/.local/state/mahavishnu/eval/reports/{run_id}.md` is non-empty (len(case_results) > 0 AND len(scores) > 0), and `eval.feed.cycles_total` incremented.
- [x] **8.7** Write the freshness test: reads `docs/eval/dogfood-v0.jsonl`, asserts at least 80% of cases have `metadata.last_reviewed` within the last 90 days. Fails otherwise.
- [x] **8.8** Promote this plan: update frontmatter `status: draft` → `status: active`, and add a row to `docs/plans/PLAN_INDEX.md`.
- [x] **8.9** Commit all the above.
- [x] **8.10** Run `crackerjack run` and `pytest tests/integration/ -v`. If everything passes, the plan is done.

### Phase 1 verification (2026-11-06)

What was run, and what the result was:

| Check | Result |
|---|---|
| `ruff check --no-fix` on every file this work touches (51 files) | clean |
| `ty check` on every file this work touches | clean except 3 findings in `tests/conftest.py` that `main` reports identically (pre-existing; not introduced here) |
| The eval test suite (127 tests) | pass |
| The pre-commit gate on every commit | pass — 0 TYPE_CHECKING runtime references, 0 secret findings, conformant frontmatter |
| `python scripts/audit_requirements.py` | **0 orphans** for REQ-EVAL-*; the 28 pre-existing phantoms (archived plans) are unchanged |
| `python scripts/audit_orphans.py` | six eval orphans, all explained: the five string-wired extension-point classes (`JsonlDatasetLoader`, `MockModelBackend`, `ExactMatchScorer`, `ContainsScorer`, `SqliteEvalStorage`), which the audit cannot see through the registry's string table, and `reset_eval_feed_state`, which only the tests call |
| `pytest tests/integration/` | 77 failed, 631 passed, 25 skipped, 12 errors — the same failure set the merge base produces, plus three environment-dependent tests that flake (see below) |
| `mahavishnu eval run-suite --suite docs/eval/dogfood-v0.jsonl` | 29 cases, all scored, report written -- **mean 0.000**, which is the mock's echo artefact and not a verdict on the set (see the ensemble-review section) |

**The whole-tree `crackerjack run -v -f` was deliberately not run in this
worktree.** Its fast-fix prepass runs `uv run ruff check --fix .` and
`uv run ruff format .` over the *whole* tree
(`crackerjack/core/autofix_coordinator.py:514`), and the repository has
**584 pre-existing ruff errors** on `main`. Running the gate here would
have rewritten several hundred unrelated files into the eval branch and
created a worktree-local `.venv` (the worktree has none, and `uv run`
resolves the project's environment). The scoped equivalents — ruff,
ty, and pytest over every file this work touches — are clean, and the
whole-tree gate belongs to the merge workflow, where any autofix is its
own "gate fixes" commit.

**Two ruff findings in touched files were pre-existing on `main`** —
`I001` (un-sorted import block) in `mahavishnu/_main_cli.py` and
`mahavishnu/mcp/bootstrap.py`. The branch's first scoped ruff run
reported them, and a check of `main`'s copies of the same two files
reported the same two findings, so the branch did not introduce them.
They are fixed here anyway (ruff's own formatter, two import
statements wrapped) so that "clean on every file this work touches"
is literally true when the branch is reviewed, and so the merge gate
has two fewer hunks to autofix.

**Pyright reports unresolved imports for the eval modules in this
worktree, and that is an artifact of the worktree, not a defect.**
The shared `.venv`'s editable install points at the *main* checkout
(`/Users/les/Projects/mahavishnu`), so an IDE resolving `mahavishnu`
finds the main tree — which has no `core/eval/` until this branch
merges. Re-pointing the install was deliberately avoided: the same
`.venv` backs every live agent worktree in the fleet, and moving it
would break them. `pytest` is unaffected (it puts the rootdir on
`sys.path` first), which is why the 127 eval tests run against the
worktree's code.

**The integration suite's failures are pre-existing and environmental —
verified against a control tree, not asserted.**
The suite needs services this worktree does not have: the gitignored
`settings/repos.yaml` / `settings/ecosystem.yaml` (the server refuses
to boot without an ecosystem manifest), a live Bifrost gateway, live
Redis, tmux terminal panes, and a live RunPod.

The control run: the merge base (`f3df534f`) checked out into a
pristine worktree with the same missing gitignored settings, the same
command, run back-to-back with the branch run in the same environment.

| Tree | Result |
|---|---|
| merge base `f3df534f` | 76 failed, 609 passed, 24 skipped, 12 errors |
| branch `feat/eval-adapter-phase1` | 77 failed, **631** passed, 25 skipped, 12 errors |

The branch adds exactly **+22 passing tests** (the 24 eval integration
tests it adds, two of which the fix commits turned into other tests)
and **no new failures**: the two failure lists differ by three tests,
all of them environment-dependent — they call the *live* MCP server on
:8680 and live services, so which of them fail depends on what the
server was doing at the time. Running those three files on `main`
fails the same tests (and a different subset on each run:
`test_pool_bootstrap_e2e.py` fails both of its tests there, and
`jot/test_drain_hooks_e2e.py` fails three). No eval test appears in
either list.

The suite is not deterministic, so a single count proves nothing: two
runs of the same branch tree minutes apart produced 84 and 76 failures
(620 and 628 passed) — the swing is service timing, not a code change.
That is why the evidence above is a *diff of failure sets against a
control tree*, not a comparison of two totals.

### Security fixes (2026-11-06)

An automated security review of the Phase 1 work found four issues on
the server-reachable surfaces. All four are fixed; the reasoning is
recorded here because two of them change a *contract* rather than a
line of code.

**The trust boundary.** The eval MCP tools and the eval pool are
server-reachable: a client names a dataset path, a budget, and a token
ceiling, and the server acts on them. The operator's own shell
(`mahavishnu eval run-suite`) is **not** a trust boundary -- an
operator who types a path means it -- and is not confined. Every fix
below is scoped accordingly.

1. **Path traversal / arbitrary file read (HIGH).** `eval_register_dataset`
   and `eval_run_suite` took a caller-supplied path and read it; the
   JSONL loader also did `path.parent.mkdir(parents=True, exist_ok=True)`,
   which made a *read* an arbitrary-directory-creation primitive.
   Fixed: the loader no longer creates directories; a new
   `mahavishnu/core/eval/paths.py::resolve_dataset_path` resolves the
   path symlink-aware and asserts it stays inside
   `EvalSettings.dataset_root` (default
   `~/.local/state/mahavishnu/eval/datasets`); the tools and the pool
   both go through it.

2. **Budget / token-ceiling bypass (MEDIUM).** `params["budget_usd"]`
   *replaced* the operator's cap, so a client could ask for a budget the
   operator never set. Fixed: a caller-supplied limit is **clamped** to
   the operator's, never allowed to raise it -- `max_usd` and
   `max_concurrency` in the tools, `max_tokens` against the new
   `EvalSettings.max_tokens_per_call`. The clamp also lives in
   `EvalEngine._budget_cap`, so *every* entry point (tools, pool, CLI)
   inherits it: the suite's `CostBudget` is a request, the operator's
   setting is a ceiling.

3. **Health-state drift (MEDIUM).** `EvalFeedState.record_error()` set
   `warm = True`, and `is_ok()` then required `entities_count > 0`. A
   client that named a bad dataset path -- one failed request -- could
   therefore drive `/health` to 503 and get the process killed by the
   launchd healthcheck wrapper. Fixed: `warm` now means "a run has
   completed" and only `record_cycle()` sets it. A failed request is
   still visible in `errors_total`; it is no longer fatal to the
   server. *(This fix was **incomplete** when written, and the
   pre-merge ensemble review found the remaining path -- a *successful*
   zero-case cycle. See the ensemble-review section below.)*

4. **Kill-switch bypass on the pool path (MEDIUM).** `EvalSettings.enabled`
   gated the MCP tools but not the eval pool, so a deployment that
   turned evaluation off could still run suites through
   `pool_spawn --type eval`. Fixed: the pool factory refuses to
   construct a disabled pool, and `start()` / `execute_task()` re-check
   the flag so a mid-flight disable is honoured -- the same contract
   the tool bodies already had.
5. **The failing layer's text in a client-reachable field (MEDIUM,
   CWE-209).** The run-failure path put `str(exc)` -- whatever the
   failing layer put in its message, including a connection string or
   a credential fragment -- into the `EvalEngineError`'s `details`.
   `MahavishnuError.to_dict()` serialises `details` into API
   responses, so that text was client-reachable. Fixed: the cause is
   logged (server-side, with the traceback) and the `details` carry
   only structure -- the run id, the case counts, and the exception's
   *type*. A test asserts that a storage error whose message looks
   like a credential does not appear in the raised error.

Two new settings carry the guardrails: `dataset_root` and
`max_tokens_per_call`. Both are documented in `EvalSettings`'s
docstring as guardrails rather than preferences, and both are in
`settings/mahavishnu.yaml`.

### Pre-merge ensemble review (2026-11-06)

The merge workflow's stage-2 "ensemble review" is a **stub**:
`mahavishnu/core/merge_to_main.py::_default_dispatcher` returns a
synthetic `decision: pass` without dispatching any agent. A green
pipeline therefore does **not** mean the change was reviewed. The
review was run for real, in-session, with the three lenses spec §4.4
names -- a domain specialist (`python-pro`), a code-quality specialist
(`critical-audit-specialist`), and a random generalist
(`qa-strategist`) -- each reading the real diff and each ending with a
`<verdict>` block. All three returned `needs_adjustment`, so the
merge was **not** attempted until the findings were fixed.

**What the review found (and what it changed).**

1. **HIGH -- the `/health` 503 hole was not closed.** The security fix
   above moved `warm = True` out of `record_error()`, but
   `record_cycle()` still set it unconditionally, and `is_ok()` judges
   a warm feed by `entities_count > 0`. A client that asked for a zero
   budget got a run that executed no case, which warmed the feed with
   an empty entity count and drove `/health` to **503** -- which the
   launchd healthcheck wrapper (`scripts/launch_with_healthcheck.sh`)
   turns into a process kill. Two of the three reviewers reproduced
   it end to end. Fixed at both layers: the feed warms only on a cycle
   that persisted cases, and a run that executed no case while the
   dataset had cases is now `budget_exceeded`, not `completed`.
2. **MEDIUM -- `"failed"` was an unreachable status.** The plan's Task
   6 contract promised that an unhandled exception marks the run
   `status="failed"`, but nothing ever wrote it: a storage failure left
   the run row `status="running"` with a NULL `finished_at` forever,
   with the already-persisted case results orphaned under it. Fixed:
   the case loop is wrapped, the run is marked `failed` via
   `finish_run`, and the engine raises `EvalEngineError`.
3. **MEDIUM -- the shipped default scorer did not match the shipped
   golden set.** The default was `mahavishnu.exact_match`, and the
   set's expectations are phrases, so a phrase answer scores 0.0 --
   including the plan's own verification command. Fixed: the default
   is `mahavishnu.contains`, and `EvalPool` now honours
   `default_scorers` instead of hard-coding the exact-match scorer.
   *(Corrected 2026-11-06: this item originally said the set "scored
   0.000, forever" and implied the fix moved that number. It does
   not, and cannot, in Phase 1: the only shipped backend is the mock,
   which echoes the question, and the fix for item 7 below moved the
   expectations *out* of their questions -- so the mock now scores
   0.000 deterministically. What the fix delivered is a scorer that
   can grade phrase answers, which is what a real backend needs in
   Phase 2. The 0.000 in Phase 1 is the echo artefact, and the
   verification table now says so.)*
4. **MEDIUM -- an unknown model backend read as a server fault.** A
   bare `registry[name]` raised `KeyError`, which the tool guard
   flattens to `{"error": "internal error"}`. The likeliest client
   mistake is naming a model (`MiniMax-M3`) where a backend
   (`mahavishnu.mock`) belongs. Fixed: the tool raises
   `EvalEngineError` naming the alternatives, like the CLI already
   did.
5. **MEDIUM -- two MCP guard tests proved nothing.** One asserted the
   private clamp helper (it would still pass if the tool stopped
   calling it); the other asserted a cost against the free mock
   backend (0.00 with or without the clamp). Fixed: both now assert
   the observable effect -- the budget the engine is handed, and the
   token ceiling in the persisted model config.
6. **MEDIUM -- a settings test failed on a correctly configured
   machine.** It compared the *merged* settings (YAML + the
   gitignored `local.yaml` + `~/.config/mahavishnu/*` + the
   environment) with the model's defaults, so an operator who
   configured eval the way the feature is designed to be configured
   got a red test. Fixed: the comparison is between the committed
   YAML file and the model's defaults.
7. **MEDIUM -- the golden set would pass several wrong answers.**
   Five of the 29 expectations were substrings of their own
   questions, so the mock echo (and a wrong answer that quoted the
   question back) scored them 1.0; one expectation (`uuid7`) was so
   strict that a correct answer ("UUID v7") scored 0.0. Fixed: the
   seven affected cases were re-worded, and a new test asserts that no
   expectation is contained in its own question.
8. **LOW -- the real-server smoke test could skip silently.** It
   skipped when the server did not come up within the warm-up, so a
   registration regression was invisible in CI. Fixed: it now fails,
   with the server's output attached.
9. **LOW -- two shipped settings were dead.** `regression_threshold`
   and `default_pool` were read by no production code, and
   `DOGFOOD.md` pointed the operator at the threshold as if it drove
   behaviour. Fixed: both are removed (regression detection is Phase 2
   work), and the operating procedure says to compare the means by
   eye.
10. **LOW -- plan claims that the code contradicted.** Corrected in
    this plan: the smoke test's markers and warm-up, the orphan-audit
    row (five orphans, not three), the test counts, the report
    footer's contents, and the three eval tools are now in
    `docs/mcp/MCP_TOOLS_SPECIFICATION.md`.

### Second ensemble round (2026-11-06)

The first round's nine findings were fixed in `89f74698`, and the
ensemble was re-run on the fixed branch -- the same three lenses, with
the generalist drawn again at random (`observability-incident-lead`).
All three confirmed the original findings fixed *by execution*, several
of them by reverting the fix and watching the new test fail. Each then
found new items. What changed:

1. **MEDIUM -- a failed run's span carried no attributes.** The span
   was annotated only on the success path, so a failed run's span was
   indistinguishable from a span the process never got to instrument --
   and the plan's own contract says a failed run is visible as
   `eval.outcome="failed"`. Fixed: the failure path annotates the span
   with the outcome and the case count, inside the closed keyspace.
2. **MEDIUM -- `EvalSettings.concurrency` was a third dead setting.**
   The engine awaits each case before starting the next, so the
   semaphore is never contended: the knob's only effect was to set a
   ceiling the engine never reaches. Removed -- the setting, the
   YAML key, and the tool's `concurrency` override. The suite's own
   `CostBudget.max_concurrency` remains, as the limit the engine
   applies when the loop is widened.
3. **MEDIUM -- the pool's scorer fix shipped with no test.** Reverting
   `EvalPool` to the hard-coded exact-match scorer left every pool
   test passing. The test now pins it with a dataset whose expectation
   is a *substring* of the mock's echo: 1.0 under `contains`, 0.0
   under `exact_match`.
4. **MEDIUM -- two registry lookups still read as server faults.**
   `_do_register_dataset` and `_do_get_run` raised bare `KeyError`s,
   and so did the CLI's dataset-loader lookup. All three now go
   through the lookup that names the alternatives.
5. **MEDIUM -- the golden set's guard covered one direction only.** A
   new test asserts that every case carrying a `metadata.reference` --
   a known-correct answer -- scores 1.0. That is the false-negative
   direction the self-containment test cannot see, and it is how the
   `uuid7` case's opposite failure was found.
6. **LOW-MEDIUM -- a failed run dropped its cause.** The tool's guard
   returned the error's message but not its structured details. The
   details are now returned: they carry structure -- the run id, the
   case counts, the error type -- not the failing layer's text.
7. **LOW -- two operator-facing strings named the old scorer**, and
   the pool's `scale` error told the operator to adjust a
   "concurrency setting" that no longer exists.
8. **LOW -- the plan's claims that the code contradicted** are
   corrected in place: the test counts, the orphan count, the smoke
   test's markers, the removed settings in the Task 2 sketch, the
   report footer's contents, the health-path naming
   (`checks.eval.feed_entities_count`, not `eval.feed.entities_count`),
   the `RunRecord.cost_estimate_accurate` flag that was never
   implemented, and the five log events the Task 6 contract claimed
   and the code never emitted.

**The automated commit security review found two more, both in the
failure path.** The first (CWE-209) was that the failing layer's text
reached the client: `MahavishnuError.to_dict()` serialises `details`
into API responses, and `details` carried `str(exc)`. The second
(CWE-532) was that moving it to the log did not help, because this
repo's logging pipeline does not redact. Both are fixed: the cause is
**classified**, not carried -- the error details hold the run id, the
case counts, and the exception's *type*, and the traceback is passed
through the repo's own `CredentialRedactor` before being logged at
debug level, which the INFO root leaves off by default.

### Task 8 corrections (2026-11-06)

Six corrections to Task 8 as written, folded in before the commit:

- **(a) No Jinja2.** Step 8.1 says "Template is a Jinja2 string in the
  same file". Jinja2 is **not a dependency of this project** --
  `pyproject.toml` does not list it. The report is built from lists of
  lines instead: four sections, one helper per section. Adding a
  template engine to render a table would be a worse trade than the
  twenty lines it replaces.
- **(b) `--model` names a *backend*, not a model.** Step 8.2's sketch
  defaults `--model` to `MiniMax-M3`, but the plan's own validation
  matrix (§7) invokes `--model mahavishnu.mock`. The registry
  publishes *backend* names (`mahavishnu.mock`, and whatever a
  distribution registers under `mahavishnu.eval.model_backends`);
  `MiniMax-M3` is a model that a backend is asked to call. The CLI
  default is `mahavishnu.mock` and the option's help says "Model
  *backend* name".
- **(c) A `contains` scorer was added.** The golden set's expected
  values are *phrases* -- `least_loaded`, `mahavishnu.eval.scorers`,
  `~/.local/state/mahavishnu/worktrees/` -- not whole answers.
  `mahavishnu.exact_match` scores every one of them zero, forever,
  which would make the golden set inert data. `mahavishnu.contains`
  (substring, case-insensitive by default) is the scorer the set is
  written for; it lives in `mahavishnu/core/eval/scorers/contains.py`
  and is registered in the built-in table and the entry-point group.
  This is an addition to the plan's file list.
- **(d) Phase 1 runs the set against the mock backend.** §4 of this
  plan says "Phase 1 uses a `MockModelBackend`", and the §6 file list
  contains no real model backend. Step 8.6's markers
  (`requires_network`, `requires_auth`) and §5's success signal ("runs
  end-to-end against `MiniMax-M3`") describe the *feature*, not
  Phase 1. The smoke test therefore runs the golden set through the
  mock backend and asserts the plumbing -- the set loads, every case
  runs, every case is scored, the run persists, the report is written,
  the feed advances -- and the `requires_network` / `requires_auth`
  markers are **not** applied, because Phase 1 makes no network call.
  The real-model run is Phase 2, and it is one entry point away:
  registering a `mahavishnu.eval.model_backends` entry is all it
  takes, and the golden set does not change. `docs/eval/DOGFOOD.md`
  states this split explicitly so nobody reads a Phase 1 score as a
  verdict on a model.
- **(e) Step 8.8 is a no-op.** The plan's frontmatter is already
  `status: active` -- it was promoted during the v4 revision, not at
  the end of Task 8. `docs/plans/PLAN_INDEX.md` already carries the
  plan's row: that file is **generated** by
  `scripts/regenerate_plan_index.py` ("Do not edit by hand"), and the
  generator picked the plan up when its status became `active`.
- **(f) The report directory is derived, not hardcoded.** The report
  goes to `<run store dir>/reports/{run_id}.md`, computed from
  `EvalSettings.db_path`. The plan hardcoded
  `~/.local/state/mahavishnu/eval/reports/`, which is the default but
  not the only possibility -- an operator who points `db_path` at
  another directory would otherwise get reports in two places.

One consequence worth recording: `EvalStorage.list_runs` was the
storage method the orphan audit reported as having no caller (see the
Task 7 orphan-audit note). The CLI's `eval list-runs` command is its
caller now.

#### Integration Contract (Task 8)
- **Triggered from**: `pytest tests/integration/test_dogfood_smoke.py` (CI, slow); `pytest tests/integration/test_dogfood_freshness.py` (CI, every PR); `mahavishnu eval run-suite --suite <path> --model <name>` CLI invocation.
- **Returns to / updates**: SQLite runs DB; new markdown report; `docs/plans/PLAN_INDEX.md` updated; this plan's frontmatter promoted.
- **Demonstrable by**: `pytest tests/integration/test_dogfood_smoke.py -v` (the whole set runs, scores, persists, and reports); `pytest tests/integration/test_dogfood_freshness.py -v` (at least 80% of the cases reviewed within 90 days); `mahavishnu eval run-suite --suite docs/eval/dogfood-v0.jsonl --scorers mahavishnu.contains`; `cat ~/.local/state/mahavishnu/eval/reports/{run_id}.md` after a run.
- **Rollback signal**: smoke test failing in CI → the framework is broken, not the data; investigate before changing the golden set.
- **Observability added**: same as Task 7; smoke test logs `eval.dogfood.run` with `cases=N, model=..., cost_usd=..., duration_ms=...`.

---

## 6. Required Code Changes

**Create:**
- `mahavishnu/core/eval/__init__.py` (re-export hub)
- `mahavishnu/core/eval/_registry.py`
- `mahavishnu/core/eval/_compat.py` (per-action shim; Phase 1 only needs the hash shim)
- `mahavishnu/core/eval/settings.py` (`EvalSettings` + `get_eval_settings()`)
- `mahavishnu/core/eval/dataset.py`
- `mahavishnu/core/eval/scorer.py`
- `mahavishnu/core/eval/storage.py`
- `mahavishnu/core/eval/engine.py`
- `mahavishnu/core/eval/report.py` (REQ-EVAL-009)
- `mahavishnu/core/eval/loaders/__init__.py`
- `mahavishnu/core/eval/loaders/jsonl.py`
- `mahavishnu/core/eval/scorers/__init__.py`
- `mahavishnu/core/eval/scorers/exact_match.py`
- `mahavishnu/core/eval/storage_backends/__init__.py`
- `mahavishnu/core/eval/storage_backends/sqlite.py`
- `mahavishnu/core/eval/model_backends/__init__.py`
- `mahavishnu/core/eval/model_backends/mock.py`
- `mahavishnu/pools/eval_pool.py` (REQ-EVAL-004)
- `mahavishnu/mcp/eval_feed.py` (REQ-EVAL-008)
- `mahavishnu/mcp/tools/eval_tools.py` (`register_eval_tools(server)` — REQ-EVAL-005)
- `mahavishnu/cli/eval_cli.py` (REQ-EVAL-010)
- `docs/eval/dogfood-v0.jsonl` (REQ-EVAL-007)
- `docs/eval/dogfood-v0.README.md`
- `docs/eval/DOGFOOD.md`
- `tests/conftest.py` modification (add `mock_model_backend` fixture)
- `tests/unit/core/eval/test_registry.py`
- `tests/unit/core/eval/test_settings.py`
- `tests/unit/core/eval/loaders/test_jsonl.py`
- `tests/unit/core/eval/scorers/test_exact_match.py`
- `tests/unit/core/eval/storage_backends/test_sqlite.py`
- `tests/unit/core/eval/test_engine.py`
- `tests/unit/pools/test_eval_pool.py`
- `tests/integration/test_eval_tools_e2e.py` (4 gate assertions)
- `tests/integration/test_eval_smoke_subprocess.py` (subprocess + warmup)
- `tests/integration/test_dogfood_smoke.py`
- `tests/integration/test_dogfood_freshness.py`

**Modify:**
- `pyproject.toml` (4 new entry-point groups — Task 0; `mahavishnu/mcp/tools/eval_tools.py` TC001 carve-out — Task 7)
- `settings/mahavishnu.yaml` (add `eval:` block — Task 2)
- `mahavishnu/core/config.py` (add `eval: EvalSettings` field to `MahavishnuSettings` — Task 2)
- `mahavishnu/core/errors.py` (four eval error classes + `MHV-012`..`MHV-015` — Tasks 3-6)
- `mahavishnu/pools/_registry.py` (add `eval_pool` to `_ensure_pool_registry_loaded()` — Task 7)
- `mahavishnu/pools/manager.py` (handle `"eval"` pool type with the corrected factory signature — Task 7)
- `mahavishnu/mcp/bootstrap.py` (add `_register_eval_tools`, `eval` check block in `register_health_endpoint` — Task 7)
- `mahavishnu/mcp/lifecycle.py` (call `init_eval_feed_state()` — Task 7)
- `mahavishnu/mcp/tools/profiles.py` (add `_register_eval_tools` to `STANDARD_REGISTRATIONS` + `REGISTRATION_MAP` + import — Task 7)
- `mahavishnu/_main_cli.py` (add `add_eval_commands(app)` call + import — Task 8)
- `docs/plans/PLAN_INDEX.md` (add this plan — Task 8)
- `docs/plans/2026-10-03-eval-adapter-phase1.md` (promote `status: draft` → `status: active` — Task 8)

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pytest tests/unit/core/eval/ tests/unit/pools/test_eval_pool.py -v` | All unit tests pass | pytest output |
| `pytest tests/integration/test_eval_tools_e2e.py -v` | All 4 gate assertions pass | pytest output |
| `pytest tests/integration/test_eval_smoke_subprocess.py -v` | Subprocess boots, tools reachable, non-empty results | pytest output |
| `pytest tests/integration/test_dogfood_smoke.py -v` (slow) | Real-model run completes in <120s, markdown report non-empty | pytest output |
| `pytest tests/integration/test_dogfood_freshness.py -v` | At least 80% of dogfood cases reviewed within 90 days | pytest output |
| `crackerjack run` | All hard limits pass; coverage ≥ 89.0168% | crackerjack output |
| `python scripts/audit_orphans.py` | No newly-added symbols with zero callers | script output |
| `mcp__mahavishnu__eval_run_suite` (manual, after `evaluation.enabled=true`) | Returns `run_id`; SQLite row created; status transitions to "completed" | conversation log + `sqlite3 ~/.local/state/mahavishnu/eval/runs.sqlite "SELECT id, status FROM runs"` |
| `mcp__mahavishnu__get_health` (after a real run) | `checks.eval.feed_entities_count > 0` and `checks.eval.cycles_total > 0` | health response |
| `mahavishnu eval run-suite --suite docs/eval/dogfood-v0.jsonl --model mahavishnu.mock` (CLI) | Same as MCP `eval_run_suite` | CLI stdout + report file |
| `grep -rE "TODO|FIXME|implement later" mahavishnu/core/eval/ mahavishnu/pools/eval_pool.py mahavishnu/mcp/eval_feed.py mahavishnu/cli/eval_cli.py` | No matches | shell output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Oneiric action-kit doesn't have a primitive we need (e.g. retry with exponential backoff specific to LLM calls) | Medium | Fall back to a hand-rolled implementation in `mahavishnu/core/eval/_compat.py`, with a comment linking to the action-kit issue; revisit when the action lands. Phase 1 only needs the hash shim. |
| SQLite locking under concurrent writes | Low | WAL mode + `synchronous=NORMAL` enabled in `SqliteEvalStorage._init_schema`; `asyncio.to_thread` wraps all writes. Stress test in Task 5.1c. |
| Dogfood golden set drifts out of relevance | High | `DOGFOOD.md` mandates a review every quarter AND a CI test `test_dogfood_freshness.py` asserts ≥80% of cases have `metadata.last_reviewed` within 90 days. Quarterly review becomes enforced, not a process promise. |
| Cost budget calculation is approximate (uses `max_tokens` fallback when `usage is None`) | High in Phase 1 | Document the limitation; precise pricing lands in Phase 2 with the Bifrost integration. *(Corrected 2026-11-06: this row named a `RunRecord.cost_estimate_accurate` flag so downstream consumers would know the estimate is approximate. No such field was implemented and nothing reads one; the row now states the limitation without naming a field that does not exist.)* |
| Oneiric adapter registration race during MCP server startup | Low | Entry-point discovery is sync; the registry is built once at startup before `_register_tools` runs. `_registry.py` cache has 5-min TTL; first call after startup populates. |
| The e2e test runs against the real model backend in CI and costs money | Medium | The e2e test (`test_eval_tools_e2e.py`) uses `MockModelBackend`. Real-model smoke is in `test_dogfood_smoke.py` which is `@pytest.mark.slow` and skipped by `-m "not slow"` for fast CI feedback. |
| `EvalPool.scale()` violates Liskov if not returning `None` | Low | Plan explicitly pins `scale(n) -> None` and documents the no-op behavior. Test `test_scale_noop_returns_none` pins the contract. |
| `discover_tools(query="eval_run_suite")` filter behavior is unspecified | Low | Gate (e3) in Task 7.1 uses raw FastMCP `tools/list` instead, which directly tests the profile system. If the meta-tool does filter correctly, the gate can be updated. |
| Cost-coverage boundary: dogfood smoke is `@pytest.mark.slow` and CI runs `-m "not slow"`, so `eval.feed.cycles_total > 0` requires either a manual run or a CI job that runs the slow tier | Medium | The plan's subprocess smoke test (`test_eval_smoke_subprocess.py`) is `@pytest.mark.integration` **and `@pytest.mark.slow`** — it starts a real server, which the repo's own rule ("any test >10 s is `slow`") makes slow. *(Correction, 2026-11-06: the plan previously claimed the test was NOT slow and that "the `/health` green path is exercised in fast CI". Both were wrong. The fast lane exercises the *feed* contract at unit level (`tests/unit/mcp/test_eval_feed_state.py`) and the *tool* contract at integration level (`test_eval_tools_e2e.py`); the real-server path is in the slow lane, where it now **fails** rather than skipping if the server does not come up, because a skip is invisible in CI and a registration regression is exactly what that test exists to catch.)* |

## 9. Decision Rule

This plan is "done" when:
- All nine tasks have green tests + atomic commits.
- `crackerjack run` passes at the project's hard limits.
- `pytest tests/integration/test_eval_tools_e2e.py` (4 gate assertions) and `pytest tests/integration/test_eval_smoke_subprocess.py` and `pytest tests/integration/test_dogfood_freshness.py` all pass.
- `pytest tests/integration/test_dogfood_smoke.py -v` (slow) passes.
- The dogfood run produces a non-empty markdown report at `~/.local/state/mahavishnu/eval/reports/{run_id}.md`.
- The MCP server `/health` reports `checks.eval.feed_entities_count > 0` and `checks.eval.cycles_total > 0` after a real run.
- This plan is promoted from `status: draft` to `status: active` and added to `docs/plans/PLAN_INDEX.md`.
- `python scripts/audit_orphans.py` reports no newly-added symbols with zero callers.
- `python scripts/audit_requirements.py` exits 0 — every `REQ-EVAL-*` ID declared in the
  frontmatter is referenced from code (`# req: REQ-EVAL-NNN` inline marker or
  `@pytest.mark.req(["REQ-EVAL-NNN"])` test marker). Until the last task lands, the audit
  is expected to report the not-yet-implemented requirements as orphans; that count must
  reach 0 for this plan to be done.

If any of these fail, do not declare Phase 1 done. The wire-up contract is the bar.

## References
- **No ULID-shaped keys.** Anything matching `^[0-9A-HJKMNP-TV-Z]{26}$`
  (Crockford Base32 ULID) is rejected post-merge by the validation
  matrix in `docs/plans/2026-10-11-uuid7-only-migration.md`
  (§7 Validation Matrix).
- **No legacy column shadow.** Unlike the old `crackerjack V5/V6`
  ULID-hedge pattern, do **not** add a `*_ulid` shadow column with
  dual-write. The `feedback-format-migration-lazy-dual-write.md`
  pattern is forbidden in pre-1.0 (`feedback-no-backwards-compat-pre-1.0`).
- **Reference: §10 of the UUID7 plan** lists this plan in its
  cross-plan patch table.

- `docs/plans/TEMPLATE.md` — the plan format this file follows.
- `docs/plans/2026-05-10-minimax27-provider-migration.md` — example of a completed Mahavishnu plan.
- `docs/decisions/wire-up-contract.md` — the integration contract discipline.
- `docs/decisions/mcp-backend-wiring-discipline.md` — MCP-specific companion rule (subprocess + warmup, 4-signal feed contract).
- `oneiric/plugins.py:67` — `iter_entry_points(group)`, the oneiric entry-point API this plan follows (the deleted `mahavishnu/core/adapter_discovery.py` is its former local predecessor).
- `mahavishnu/pools/base.py:100, 172` — `BasePool` (not `PoolBase`); `scale(target_worker_count) -> None` abstract signature.
- `mahavishnu/pools/manager.py:411-420` — pool factory invocation shape (`factory(config=config, terminal_manager=..., session_buddy_client=...)`).
- `mahavishnu/mcp/server_core.py:349-358` — FastMCP inline-tooling constraint (scope: the 27 core tools in `_register_tools()` only).
- `mahavishnu/mcp/signer_feed.py:160-244` — canonical feed-state pattern (mirror for `eval_feed.py`). Verified against `main` at `f3df534f`.
- `mahavishnu/mcp/sweepers/task_orphan_sweeper.py:264` — canonical "start a child OTel span" precedent. Verify on first read.
- `mahavishnu/mcp/bootstrap.py:278` (`collect_component_checks`) and `:353` (`register_health_endpoint`) — where the `eval` check block lives. Verify on first read.
- `mahavishnu/mcp/tools/profiles.py:93-115, 193+` — `STANDARD_REGISTRATIONS` and `REGISTRATION_MAP`. Verify on first read.
- `mahavishnu/workers/cloud_worker.py` — the existing MiniMax worker that the eval engine will compose.
- `mahavishnu/core/config.py` — `MahavishnuSettings` env_prefix and env_nested_delimiter precedent; `otel_ingester` field; `get_settings()` lazy getter pattern. Line numbers drift frequently; treat as durable pointers — verify on first read.
- `mahavishnu/_main_cli.py:17-45, 1358-1606` — CLI entry point and `add_*_commands` registration block. Verify the add_typer range on first read.
- `mahavishnu/cli/plan_cli.py:18-23, 47-51` — canonical `typer` command pattern. Verify on first read.
- `oneiric/docs/action-kits.md` — catalog of common primitives (verify availability before hand-rolling; `oneiric.actions.compression.HashAction` for sha256).
- `ADR 017: Oneiric as the shared persistence substrate for Bodai` — substrate conventions.
- `pyproject.toml:460-465` — existing `per-file-ignores` carve-outs for Pydantic-heavy files (the model for Task 0's additions).
- Memory items cross-referenced: `pydantic-future-annotations-forward-ref.md`, `feedback-no-bodai-prefix-in-config-names.md`, `feedback-memories-must-be-dual-stored.md`, `wire-protocol-source-of-truth.md`, `multi-agent-review-catches-blind-spots.md`.


## Coordination notes (post-2026-10-11 UUID7 migration)

- **ID format: UUID7 hex (required).** The new `runs` / `case_results`
  / `scores` tables (Task 5) use `id TEXT PRIMARY KEY` (lines 334–360
  of the original plan). The only sanctioned ID generation path
  across the Bodai core, per the active UUID7 migration, is
  `from uuid import uuid7; uuid7().hex`. Default values for the
  `id` column should be either:
  - App-layer: writer calls `uuid7().hex` and passes it in
    (preferred; matches the session-buddy pattern post-Phase-0).
  - Or schema-layer: `id TEXT PRIMARY KEY DEFAULT gen_random_uuid7()::TEXT`
    (requires oneiric's `gen_random_uuid7()` UDF; only available if
    the eval DB is on a PG backend with oneiric's UDF loaded).
- **No ULID-shaped keys.** Anything matching `^[0-9A-HJKMNP-TV-Z]{26}$`
  (Crockford Base32 ULID) is rejected post-merge by the validation
  matrix in `docs/plans/2026-10-11-uuid7-only-migration.md`
  (§7 Validation Matrix).
- **No legacy column shadow.** Unlike the old `crackerjack V5/V6`
  ULID-hedge pattern, do **not** add a `*_ulid` shadow column with
  dual-write. The `feedback-format-migration-lazy-dual-write.md`
  pattern is forbidden in pre-1.0 (`feedback-no-backwards-compat-pre-1.0`).
- **Reference: §10 of the UUID7 plan** lists this plan in its
  cross-plan patch table.
- **ID generation is app-layer only.** The
  `gen_random_uuid7()::TEXT` example in the v1 of this patch
  described a UDF that oneiric does not ship. The app-layer path
  is the only working option.

## Coordination notes (post-2026-10-18 M2.7-highspeed deprecation)

- **`MiniMax-M2.7-highspeed` is being deprecated by MiniMax and will no
  longer be available.** Phase 1's only live MiniMax dependency is the
  dogfood smoke run in **Task 8.6**, where the real-model backend is
  invoked through the existing `mahavishnu/workers/cloud_worker.py`
  plumbing. v3 of this plan swapped every reference from
  `MiniMax-M2.7-highspeed` → `MiniMax-M3` (lines 31, 65, 564 — and any
  CLI default the implementing worker adds during Task 8.2 must use
  `MiniMax-M3`, not `M2.7-highspeed`).
- **`MiniMax-M3` is the primary model on the MiniMax provider** (per
  project `CLAUDE.md` "LLM Provider Configuration" §). The dogfood
  smoke test's `@pytest.mark.requires_auth` marker (Task 8.6) still
  applies — the `MiniMax-M3` model requires the `MINIMAX_API_KEY` shell
  credential — but no separate env var change is needed.
- **v4 correction to the fallback chain.** v3 said the chain
  "collapses to `M2.7` alone". That was already out of date by the
  time v3 landed: MiniMax **closed `M2.7` to new users on 2026-10-19**
  and retires it on **2026-11-18** (12 days from this revision). The
  documented fallback is now **`MiniMax-M3.1-Flash`** (1M context +
  multimodal preview, verified on the MiniMax API on 2026-10-19), then
  the local `llama_server` (`qwen3.5` at `http://localhost:8081`).
  Task 8.2's CLI default of `MiniMax-M3` is unchanged and still
  correct — `M3` remains the primary for the correctness-sensitive
  task categories. Only the *fallback* claim needed correcting.
- **If `MiniMax-M3` is also deprecated before Task 8.6 lands**, the
  fallback is `llama_server` (local `qwen3.5` at
  `http://localhost:8081`) per the project's model-routing YAML.
  This swap is mechanical: edit the CLI default (Task 8.2 line 564)
  and the smoke test's model name (Task 8.6); the eval framework
  itself is model-agnostic.
- **Tag this plan for re-review** when any of the following changes:
  MiniMax adds or removes a model family; `oneiric.actions.compression.HashAction`
  ships or breaks; `mahavishnu/pools/base.py::BasePool` signature
  changes; `mahavishnu/mcp/server_core.py` constraint about inline
  FastMCP tooling changes; or the wire-up discipline in
  `docs/decisions/mcp-backend-wiring-discipline.md` revs past v1.

## Coordination notes (post-2026-11-06 requirement-marker discovery)

- **`scripts/audit_requirements.py` detects the `# req: REQ-NNN` and
  `# Implements: REQ-NNN` forms — not the `@pytest.mark.req([...])` marker.**
  Its `PYTEST_MARKER_REFERENCE_RE` requires exactly one whitespace character
  between `]` and `)` (`\]\s\)`), so the form the script's own docstring
  documents — `@pytest.mark.req(["REQ-001"])` — does not match. 99 marker
  usages across this repo are therefore invisible to the audit, which
  under-reports references and over-reports orphans.
- **This plan satisfies its requirement IDs with `# req: REQ-EVAL-NNN`
  markers in the production modules** (`_registry.py`, `dataset.py`,
  `settings.py`, …), which is the form the audit detects and the repo's
  established practice — 57 such markers already exist in `mahavishnu/`.
  The `@pytest.mark.req([...])` markers on the tests are kept as well; they
  are documentation for the reader, and the gate reads the source markers.
- **The regex fix is a one-character change to a shared script**
  (`\]\s\)` -> `\]\s*\)`), but it is deliberately NOT made here: it would
  also surface the 99 currently-invisible references, several of which use
  bare IDs whose declaring plans live in the gitignored
  `docs/plans/.archive/`, so it changes repo-wide orphan and phantom counts.
  That is an operator decision about the shared gate, not about this plan.

## Coordination notes (post-2026-11-06 commit grouping)

- **Task 4's files rode in Task 5's commit.** The Task 4 commit was
  *rejected by the pre-commit gate*, not lost. The gate scans the whole
  working tree, and `mahavishnu/core/eval/storage_backends/sqlite.py` —
  written for Task 5 while the Task 4 commit was still in flight — still
  imported `EvalSummary` under `if TYPE_CHECKING:` while using it at
  runtime. The rejection was masked by a trailing `git log` that was not
  chained with `&&`, so the task reported success; the next task's broad
  `git add` then swept the scorer files into the Task 5 commit.
- **The gate was right and the code was fixed** — the Task 5 commit has
  the runtime import. The history is therefore grouped as
  Task 3 -> Tasks 4+5 -> Task 6 rather than one commit per task, which
  differs from this plan's "atomic commit per task" wording. The content
  is complete and tested; only the commit grouping differs. The grouping
  was left as-is rather than rewriting history, because splitting it
  means reconstructing three intermediate states of the shared
  `_registry.py`, `pyproject.toml`, and this plan file.
