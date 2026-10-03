---
status: active
role: implementation
kind: plan
date: 2026-10-03
last_reviewed: 2026-10-03
superseded_by: null
topic: model-evaluation
title: "Model Evaluation — Phase 1 Implementation Plan"

---

# Model Evaluation — Phase 1 Implementation Plan

**Date:** 2026-10-03
**Status:** `draft, implementation`
**Owner:** Core Eng
**Scope:** Mahavishnu. Phase 1 only — foundation slice. Phases 2-5 (multi-model A/B, regression detection, agent trajectories, cost routing) are out of scope and tracked separately.
**Purpose:** Ship a vertical slice that proves the architecture, demonstrates the value of prompt/model evaluation to the team, and provides the foundation for Phases 2-5.

## Revision history

- **v0** (2026-10-03): initial draft.
- **v1** (2026-10-03): post multi-agent review. Architectural decision: `EvalPool` extends `BasePool` (option 2). Settings env_prefix corrected to `MAHAVISHNU_EVAL_*`. `model_backend` returns `ModelResponse` and is registered as a fourth oneiric entry-point group. FastMCP tools inline in `bootstrap.py`. New `eval_feed.py` + health-feed wiring. Per-file-ignores added. CLI entry point added. 20-30 Mahavishnu-specific golden cases (not generic Python). 30+ specific corrections from the architecture, MCP, and crackerjack lenses folded in.
- **v2** (2026-10-03): post meta-review (consistency pass). EvalSettings is now a nested field on `MahavishnuSettings` (not a separate `BaseSettings`); env var is `MAHAVISHNU_EVAL__*` (double underscore for nested delimiter). EvalPool factory signature matches `manager.py::spawn_pool` actual call shape. `BasePool.scale()` returns `None` (Liskov), not int. `EvalStorage` gets a `finish_run` method to transition run status. CLI uses `typer` not `click`; entry is `_main_cli.py` not `cli.py`. `Scorer.score` is sync. `_do_run_suite`/`_do_register_dataset`/`_do_get_run` helpers fully specified. `MockModelBackend` has concrete behavior. Per-file-ignore block shown explicitly. `get_eval_settings()` is a module-level lazy getter. 16 corrections from the meta-review folded in.

## 1. Outcome

A developer can run a golden-set of cases covering **Mahavishnu-specific agent behaviors** (repo routing, adapter selection, workflow invocation, etc.) against a model through Mahavishnu and get back a scored, persisted, queryable result — without leaving the project's MCP surface or writing one-off scripts. The framework registers all its pluggable parts (scorers, dataset loaders, storage, model backends) as oneiric adapters so they are discoverable and replaceable.

**Success signal:** the dogfood golden set (20-30 Mahavishnu-specific cases) runs end-to-end against `MiniMax-M2.7-highspeed` in under 2 minutes, produces a markdown report at `~/.local/state/mahavishnu/eval/reports/{run_id}.md`, persists results to SQLite, and `/health` reports `eval.feed.entities_count > 0` and `eval.feed.cycles_total > 0` after the run. A re-run after a known-bad prompt change flags the regression.

## 2. Goals

1. Establish `EvalEngine` as a new Mahavishnu primitive (not an `OrchestratorAdapter` subclass — its execution shape is incompatible with `(task, repos) -> dict`).
2. Establish `EvalPool` as a `BasePool` subclass wrapping a single virtual worker (per the user's architectural decision; rationale: consistency with the existing `mahavishnu/pools/` convention + `list_pools()` discoverability + Phase 2 multi-run parallelism without restructuring). **The MCP tool bypasses EvalPool in Phase 1** and calls `EvalEngine` directly; the pool is registered for discoverability + future cross-pool orchestration.
3. Wire all pluggable extension points (scorers, dataset loaders, storage, **model backends**) as oneiric adapters discoverable via the existing `AdapterDiscoveryEngine` entry-point mechanism.
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
- `mahavishnu/pools/base.py:84` defines `BasePool` (NOT `PoolBase`) with `execute_task`, `execute_batch`, `collect_memory`, `scale(target_worker_count: int) -> None`, `get_status`. **`scale` returns `None` per the abstract signature** (Liskov constraint) — Task 7.5's EvalPool override must also return `None`, not `1`. The current worker count is observable via `get_status()`, not the return value of `scale`.
- `mahavishnu/pools/manager.py:355-359` invokes pool factories as `factory(config=config, terminal_manager=self.terminal_manager, session_buddy_client=self.session_buddy_client)`. **`_build_eval_pool` must match this signature exactly** (accepting the two manager-injected args, ignoring them, and pulling eval-specific deps from module singletons via `get_eval_settings()` and oneiric adapter discovery).
- `mahavishnu/core/adapter_discovery.py` shows the in-repo oneiric integration pattern: `MCPAdapterRegistryClient` + `AdapterDiscoveryEngine.discover_from_entry_points(group, allowlist_patterns)`. The default allowlist at `AdapterDiscoveryEngine.__init__` is `["mahavishnu.adapters.*", "custom.adapters.*"]`; **must be extended** to `["mahavishnu.adapters.*", "mahavishnu.eval.*", "custom.adapters.*"]` or eval adapters will be silently filtered out at discovery time.
- `mahavishnu/mcp/bootstrap.py:265-345` is where `register_health_endpoint()` aggregates feed state from `signer_feed.py`, `plan_index/health.py`, and `task_orphan_sweeper.py`. Eval adds a fourth feed: new `mahavishnu/mcp/eval_feed.py` (mirror `signer_feed.py:153-249` pattern), and `bootstrap.py` gets a new `eval` check block.
- `mahavishnu/mcp/server_core.py:293-298` documents the constraint: "FastMCP's `@server.tool()` decorator requires each tool function to be defined inline so it can introspect the function name and signature for the MCP tool schema." Therefore the three eval tools live inline in `bootstrap.py::_register_eval_tools()`, not in a separate `eval_tools.py` module.
- `mahavishnu/mcp/signer_feed.py:153-249` is the canonical feed-state pattern: a `SignerFeedState` dataclass with `record_cycle()`, `record_error()`, and `as_dict()` returning the 4-signal contract (`feed_entities_count`, `feed_last_updated_timestamp`, `feed_cycles_total`, `feed_errors_total`). `eval_feed.py` mirrors this. For `EvalFeedState`, `entities_count` is the **total number of `CaseRecord`s persisted across all runs** (incremented by `record_cycle(case_count=N)` — the signature takes a per-run case count).
- `mahavishnu/mcp/sweepers/task_orphan_sweeper.py:264` is the canonical "start a child span" precedent for OTel: `from opentelemetry import trace; tracer = trace.get_tracer(__name__); with tracer.start_as_current_span("eval.run_suite") as span: span.set_attribute("eval.case_count", ...)`. The auto-emitted `mcp.tool.call` span from `tool_call_middleware.py:94-145` writes `duration_ms` to the parent; the eval-specific child span writes eval-specific attributes only (prefixed `eval.*` to avoid collision).
- `mahavishnu/workers/cloud_worker.py` already calls MiniMax via OpenAI-compatible API. Eval composes the existing worker for `MiniMax-M2.7-highspeed` (Phase 2); Phase 1 uses a `MockModelBackend` registered as a oneiric adapter under `mahavishnu.eval.model_backends`.
- Settings follow Mahavishnu's existing `pydantic-settings` convention with **nested `EvalSettings` field on `MahavishnuSettings`** (NOT a separate `BaseSettings` class). The parent `MahavishnuSettings` has `env_prefix="MAHAVISHNU_"` and `env_nested_delimiter="__"` (per `mahavishnu/core/config.py:2663-2664`); the `evaluation` field maps to env var `MAHAVISHNU_EVAL__ENABLED` (double underscore for the nested delimiter), `MAHAVISHNU_EVAL__COST_BUDGET_PER_RUN`, etc. Precedent: `MAHAVISHNU__OTEL_INGESTER__STORAGE__TYPE` at `mahavishnu/core/config.py:903`. The CC memory item `feedback-no-bodai-prefix-in-config-names.md` lives in OTHER Bodai components (Dhara, oneiric), not Mahavishnu.
- Common primitives come from `oneiric.actions` (per the action-kit discipline in `CLAUDE.md`). Verified mappings for Phase 1: hashing is `oneiric.actions.compression.HashAction` (precedent: `mahavishnu/core/idempotency.py:39`), NOT `oneiric.actions.hash`. HTTP, schema validation, retry primitives to be verified against `oneiric/docs/action-kits.md` before Task 1; hand-roll in `mahavishnu/core/eval/_compat.py` if the action doesn't exist. `_compat.py` is a per-action shim module — each missing oneiric action gets a hand-rolled implementation with a `link_to_issue: oneiric#N` comment. Phase 1 only needs the hash shim.
- Pydantic v2 + `from __future__ import annotations` is a latent bug class (per the memory item `pydantic-future-annotations-forward-ref.md` and existing carve-outs in `pyproject.toml:407-420`). The 11+ new Pydantic model files in `mahavishnu/core/eval/` must be added to `[tool.ruff.lint.per-file-ignores]` for `TC003`, matching the existing entries for `core/capabilities.py`, `core/repo_models.py`, `core/repositories/embeddings.py`.
- `mahavishnu/_main_cli.py` is the actual CLI entry point (NOT `mahavishnu/cli.py`, which does not exist; per `mahavishnu/cli/__init__.py:11` docstring: "the main CLI app is defined in `mahavishnu/_main_cli.py`"). The eval subcommand must be registered there. CLI uses `typer.Typer` and `typer.Option` (precedent: `mahavishnu/cli/plan_cli.py:18-23, 47-51`), NOT `click`.
- `EvalSettings` is a nested Pydantic v2 `BaseModel` (not `BaseSettings`) embedded in `MahavishnuSettings`. The lazy module-level getter `get_eval_settings()` mirrors `get_settings()` at `mahavishnu/core/config.py:3046` and returns `get_settings().evaluation`.
- `BasePool.scale(self, target_worker_count: int) -> None` is `@abstractmethod` (per `mahavishnu/pools/base.py:156`); returning `1` from an override violates Liskov. EvalPool's `scale(n)` must return `None` and log a warning.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "Oneiric adapter discovery for eval extension points"
    file: "mahavishnu/core/eval/_registry.py:1-80"
  - id: REQ-002
    title: "EvalEngine primitive (Dataset, Scorer, Storage, ModelBackend ABCs/Protocols)"
    file: "mahavishnu/core/eval/engine.py:1-50, dataset.py:1-40, scorer.py:1-50, storage.py:1-50"
  - id: REQ-003
    title: "EvalEngine orchestration (composes extension points, returns EvalRunResult)"
    file: "mahavishnu/core/eval/engine.py:50-250"
  - id: REQ-004
    title: "EvalPool as BasePool subclass with single virtual worker (discoverable; MCP tool bypasses in Phase 1)"
    file: "mahavishnu/pools/eval_pool.py:1-200"
  - id: REQ-005
    title: "MCP tool surface (eval_register_dataset, eval_run_suite, eval_get_run) inline in bootstrap.py"
    file: "mahavishnu/mcp/bootstrap.py:_register_eval_tools"
  - id: REQ-006
    title: "Settings via nested EvalSettings field on MahavishnuSettings; env var MAHAVISHNU_EVAL__*"
    file: "mahavishnu/core/eval/settings.py:1-80, mahavishnu/core/config.py:eval-field"
  - id: REQ-007
    title: "Dogfood golden set of 20-30 Mahavishnu-specific cases"
    file: "data/eval/dogfood-v0.jsonl"
  - id: REQ-008
    title: "Phase 1 wire-up (e2e tests, health feed, audit_orphans, plan promotion)"
    file: "mahavishnu/mcp/eval_feed.py + tests/integration/test_eval_*.py"
  - id: REQ-009
    title: "MarkdownReportWriter for human-readable run reports"
    file: "mahavishnu/core/eval/report.py:1-100"
  - id: REQ-010
    title: "CLI entry point `mahavishnu eval run-suite` for programmatic use without MCP"
    file: "mahavishnu/_main_cli.py + mahavishnu/cli/eval_cli.py"
```

**Cross-component dependencies** (per `wire-up-contract.md` §2 "additional requirements"):

- `Mahavishnu → LangSmith (MCP, read-only in Phase 1)` — for dataset ingestion when `LANGSMITH_API_KEY` is set.
- `Mahavishnu → MiniMax (OpenAI-compatible API, via existing `mahavishnu/workers/cloud_worker.py`)` — for the dogfood run in Task 8.
- `Mahavishnu → Akosha (OTel traces, one-way: Mahavishnu emits, Akosha ingests via `mahavishnu/ingesters/otel_ingester.py`)` — for cross-system observability of eval runs.
- `Mahavishnu → oneiric (entry-point discovery, scoped to `mahavishnu.eval.*` group via `AdapterDiscoveryEngine`)` — for pluggable extension points.

## 5. Implementation Phases

The plan ships as one phase (Phase 1 of the broader eval feature). It is decomposed into nine tasks, each a self-contained TDD cycle ending with a green test suite + atomic commit + `python scripts/audit_orphans.py` pass.

### Task 0: Housekeeping (pre-Task-1)

**Files:**
- Modify: `pyproject.toml` (add 4 new entry-point groups + per-file-ignore block)
- Modify: `mahavishnu/core/adapter_discovery.py` (extend `allowlist_patterns` default to include `mahavishnu.eval.*`)
- Create: `data/eval/` directory

**Steps:**
- [ ] **0.1** Add to `pyproject.toml` the four new entry-point groups (PEP 621 syntax, multi-entry, no entries yet):
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
- [ ] **0.2** In `mahavishnu/core/adapter_discovery.py`, extend the `allowlist_patterns` default from `["mahavishnu.adapters.*", "custom.adapters.*"]` to `["mahavishnu.adapters.*", "mahavishnu.eval.*", "custom.adapters.*"]`. Without this, the `AdapterDiscoveryEngine` silently filters out every eval adapter it discovers.
- [ ] **0.3** In `pyproject.toml:[tool.ruff.lint.per-file-ignores]`, add the new block (Ruff supports module paths; verify glob support before falling back):
  ```toml
  [tool.ruff.lint.per-file-ignores]
  "mahavishnu/core/eval/engine.py" = ["TC003"]
  "mahavishnu/core/eval/dataset.py" = ["TC003"]
  "mahavishnu/core/eval/scorer.py" = ["TC003"]
  "mahavishnu/core/eval/storage.py" = ["TC003"]
  "mahavishnu/core/eval/settings.py" = ["TC003"]
  "mahavishnu/core/eval/report.py" = ["TC003"]
  "mahavishnu/core/eval/loaders/jsonl.py" = ["TC003"]
  "mahavishnu/core/eval/scorers/exact_match.py" = ["TC003"]
  "mahavishnu/core/eval/storage_backends/sqlite.py" = ["TC003"]
  "mahavishnu/core/eval/model_backends/mock.py" = ["TC003"]
  ```
  Comment above the block: "Pydantic-v2 model files; `__future__ import annotations` required by project convention; `TC003` carve-out for forward-ref resolution (see `pydantic-future-annotations-forward-ref.md`)."
- [ ] **0.4** Run `python scripts/audit_orphans.py` to establish baseline; record the count in the commit message.
- [ ] **0.5** Commit: `git add pyproject.toml mahavishnu/core/adapter_discovery.py && git commit -m "chore(eval): scaffold oneiric entry-point groups and per-file-ignores (Task 0)"`.

#### Integration Contract (Task 0)
- **Triggered from**: `uv pip install -e .` (registers entry-point groups); `mahavishnu mcp start` (loads `AdapterDiscoveryEngine`); crackerjack gate.
- **Returns to / updates**: `pyproject.toml` (4 new entry-point groups, 10-line per-file-ignore block); `mahavishnu/core/adapter_discovery.py` (extended allowlist).
- **Demonstrable by**: `python -c "from importlib.metadata import entry_points; eps = entry_points(group='mahavishnu.eval.scorers'); print(list(eps))"` returns `[]` (empty list, no errors).
- **Rollback signal**: `crackerjack run` fails on `TC003` for any file in `mahavishnu/core/eval/` → check the per-file-ignores block.
- **Observability added**: none (housekeeping task).

---

### Task 1: Oneiric entry-point scaffolding (REQ-001)

**Files:**
- Create: `mahavishnu/core/eval/__init__.py` (re-export hub)
- Create: `mahavishnu/core/eval/_registry.py` (thin wrapper over `AdapterDiscoveryEngine`)
- Create: `mahavishnu/core/eval/_entry_points.py` (single file, registers all four groups)
- Test: `tests/unit/core/eval/test_registry.py`

**Steps:**
- [ ] **1.1** Write a failing test that calls `mahavishnu.core.eval.registry.discover_scorers()` and asserts it returns at least one scorer (after Task 4 registers `mahavishnu.exact_match`).
- [ ] **1.2** Run, confirm FAIL (`ImportError: cannot import name 'discover_scorers'`).
- [ ] **1.3** Implement `mahavishnu/core/eval/_registry.py` with `discover_scorers()`, `discover_dataset_loaders()`, `discover_storage()`, `discover_model_backends()`. Each function wraps `AdapterDiscoveryEngine.discover_from_entry_points(group=...)`. Cache results in a module-level dict with a 5-minute TTL.
- [ ] **1.4** Implement `mahavishnu/core/eval/_entry_points.py` — single file, registers all four groups via `@entry_point(group="...", name="...")`. Empty for now; Tasks 3, 4, 5, 6 will populate.
- [ ] **1.5** Add `mahavishnu/core/eval/_entry_points` import to `mahavishnu/core/eval/_registry.py` so the entry-point side effects fire at first registry call. Add comment: `import mahavishnu.core.eval._entry_points  # noqa: F401  — registry side-effect (mirrors mahavishnu/pools/_registry.py:90-95 pattern)`.
- [ ] **1.6** Run, confirm PASS; add a second test that asserts the cache TTL behaves correctly (cache hit returns the same instance; cache miss after TTL expires re-discovers).
- [ ] **1.7** Commit: `git add mahavishnu/core/eval/ tests/unit/core/eval/test_registry.py && git commit -m "feat(eval): scaffold oneiric entry-point discovery for eval extension points"`.

#### Integration Contract (Task 1)
- **Triggered from**: `mahavishnu mcp start` (during `_register_eval_tools` lifecycle, when `evaluation.enabled=true`).
- **Returns to / updates**: module-level cache dict in `_registry.py`, keyed by domain → list[adapter].
- **Demonstrable by**: `pytest tests/unit/core/eval/test_registry.py -v` passes.
- **Rollback signal**: any import error in `mahavishnu/core/eval/_registry.py` at server startup (logs `mahavishnu.eval.registry.error`).
- **Observability added**: structured log line `eval.registry.discovered domain=scorer count=N` at first discovery per cache window.

---

### Task 2: Settings via nested MahavishnuSettings field (REQ-006)

**Files:**
- Create: `mahavishnu/core/eval/settings.py` (`EvalSettings` Pydantic v2 `BaseModel` + `get_eval_settings()` module-level lazy getter)
- Modify: `mahavishnu/core/config.py` (add `eval: EvalSettings = Field(default_factory=EvalSettings)` field to `MahavishnuSettings`)
- Modify: `settings/mahavishnu.yaml` (add `eval:` block under top-level settings)
- Test: `tests/unit/core/eval/test_settings.py`

**Steps:**
- [ ] **2.1** Write failing tests: (a) `EvalSettings()` constructs with `enabled=False`; (b) `get_eval_settings()` returns a `MahavishnuSettings` whose `.eval.enabled` reflects the YAML/env override; (c) overriding `MAHAVISHNU_EVAL__COST_BUDGET_PER_RUN=42.0` reads the override (note: double underscore for nested delimiter); (d) `EvalSettings.model_config` uses `extra="forbid"` (NOT v1 `class Config:`).
- [ ] **2.2** Run, confirm FAIL.
- [ ] **2.3** Implement `EvalSettings(BaseModel)` in `mahavishnu/core/eval/settings.py`:
  ```python
  from __future__ import annotations
  from typing import Literal
  from pydantic import BaseModel, ConfigDict, Field

  class EvalSettings(BaseModel):
      model_config = ConfigDict(extra="forbid")
      enabled: bool = False
      default_pool: str = "eval"
      default_storage: str = "mahavishnu.sqlite"
      default_dataset_loader: str = "mahavishnu.jsonl"
      default_scorers: list[str] = Field(default_factory=lambda: ["mahavishnu.exact_match"])
      default_model_backend: str = "mahavishnu.mock"
      cost_budget_per_run: float = 5.0
      concurrency: int = 20
      regression_threshold: float = 0.05
      db_path: str = "~/.local/state/mahavishnu/eval/runs.sqlite"

  def get_eval_settings() -> "EvalSettings":
      """Module-level lazy getter; mirrors get_settings() at mahavishnu/core/config.py:3046."""
      from mahavishnu.core.config import get_settings
      return get_settings().eval
  ```
- [ ] **2.4** In `mahavishnu/core/config.py`, add the `eval` field to `MahavishnuSettings` (after the `otel_ingester` field at line 2786): `eval: EvalSettings = Field(default_factory=EvalSettings)`.
- [ ] **2.5** Add `eval:` block to `settings/mahavishnu.yaml`:
  ```yaml
  eval:
    enabled: false
    default_pool: "eval"
    default_storage: "mahavishnu.sqlite"
    default_dataset_loader: "mahavishnu.jsonl"
    default_scorers: ["mahavishnu.exact_match"]
    default_model_backend: "mahavishnu.mock"
    cost_budget_per_run: 5.0
    concurrency: 20
    regression_threshold: 0.05
    db_path: "~/.local/state/mahavishnu/eval/runs.sqlite"
  ```
  (Indentation: 2 spaces, matching the existing `otel_ingester:` block in this file.)
- [ ] **2.6** Run tests, confirm PASS.
- [ ] **2.7** Commit: `git add mahavishnu/core/eval/settings.py mahavishnu/core/config.py settings/mahavishnu.yaml tests/unit/core/eval/test_settings.py && git commit -m "feat(eval): nested EvalSettings on MahavishnuSettings with MAHAVISHNU_EVAL__ env_prefix"`.

#### Integration Contract (Task 2)
- **Triggered from**: `get_settings()` instantiation anywhere; `get_eval_settings()` is the public entry point for eval code.
- **Returns to / updates**: `MahavishnuSettings.eval` (in-process Pydantic model); persisted to `settings/mahavishnu.yaml`.
- **Demonstrable by**: `pytest tests/unit/core/eval/test_settings.py -v`; `MAHAVISHNU_EVAL__COST_BUDGET_PER_RUN=42.0 python -c "from mahavishnu.core.eval.settings import get_eval_settings; print(get_eval_settings().cost_budget_per_run)"` prints `42.0`.
- **Rollback signal**: any Pydantic validation error at startup (logs `mahavishnu.eval.settings.invalid`).
- **Observability added**: structured log line at MCP server startup: `eval.settings.loaded enabled=true pool=eval budget=5.0`.

---

### Task 3: Dataset ABC + JSONL loader (REQ-002 partial)

**Files:**
- Create: `mahavishnu/core/eval/dataset.py` (`Dataset` ABC, `DatasetCase` model, `DatasetLoadError`)
- Create: `mahavishnu/core/eval/loaders/__init__.py`
- Create: `mahavishnu/core/eval/loaders/jsonl.py` (`JsonlDatasetLoader`, registered via `mahavishnu.core.eval._entry_points`)
- Create: `mahavishnu/core/eval/_compat.py` (per-action shim module; Phase 1 only needs the hash shim)
- Test: `tests/unit/core/eval/loaders/test_jsonl.py`

**Steps:**
- [ ] **3.1** Write failing tests: (a) load a 3-case JSONL fixture, assert each `DatasetCase` has `id`, `input`, `expected`, `metadata` populated; (b) `discover_dataset_loaders()` returns the JSONL loader; (c) malformed JSONL raises `DatasetLoadError` with line number, not raw `json.JSONDecodeError`.
- [ ] **3.2** Run, confirm FAIL.
- [ ] **3.3** Implement `DatasetCase` (Pydantic v2: `id: str`, `input: str`, `expected: str`, `metadata: dict[str, Any]`) and `Dataset` ABC with `name: str`, `cases: list[DatasetCase]`, `content_hash: str`, `version: str`, `model_validator(mode="after")` enforcing `len(cases) >= 1`.
- [ ] **3.4** Implement `JsonlDatasetLoader.load(path: Path) -> Dataset`. The `content_hash` uses `oneiric.actions.compression.HashAction` (verified importable as of 2026-10-03; if missing at write time, fall back to `hashlib.sha256` in `mahavishnu/core/eval/_compat.py::hash_content`). `path.parent.mkdir(parents=True, exist_ok=True)` before any read.
- [ ] **3.5** Register `JsonlDatasetLoader` in `mahavishnu/core/eval/_entry_points.py` under `group="mahavishnu.eval.dataset_loaders"`, `name="mahavishnu.jsonl"`.
- [ ] **3.6** Run, confirm PASS.
- [ ] **3.7** Commit: `git add mahavishnu/core/eval/dataset.py mahavishnu/core/eval/loaders/ mahavishnu/core/eval/_entry_points.py mahavishnu/core/eval/_compat.py tests/unit/core/eval/loaders/test_jsonl.py && git commit -m "feat(eval): Dataset ABC + JSONL loader (oneiric entry-point)"`.

#### Integration Contract (Task 3)
- **Triggered from**: `eval_register_dataset` MCP tool (Task 7) and any direct `JsonlDatasetLoader.load()` call.
- **Returns to / updates**: in-memory `Dataset` object; no persistent effect (storage lands in Task 5).
- **Demonstrable by**: `pytest tests/unit/core/eval/loaders/test_jsonl.py -v`.
- **Rollback signal**: any `DatasetLoadError` propagated up — caller handles by surfacing to the user with line number.
- **Observability added**: structured log line `eval.dataset.loaded name=... cases=N hash=...sha256-prefix`.

---

### Task 4: Scorer ABC + ExactMatch scorer (REQ-002 partial)

**Files:**
- Create: `mahavishnu/core/eval/scorer.py` (`Scorer` ABC, `Score` model, `ScoringError`)
- Create: `mahavishnu/core/eval/scorers/__init__.py`
- Create: `mahavishnu/core/eval/scorers/exact_match.py` (`ExactMatchScorer`)
- Modify: `mahavishnu/core/eval/_entry_points.py` (register `mahavishnu.exact_match`)
- Test: `tests/unit/core/eval/scorers/test_exact_match.py`

**Steps:**
- [ ] **4.1** Write failing tests: (a) `ExactMatchScorer().score(actual="hello", expected="hello", case_meta={})` returns `Score(value=1.0)`; (b) `score(actual="hi", expected="hello", ...)` returns `Score(value=0.0)`; (c) `case_sensitive=False` flips behavior; (d) `discover_scorers()` returns it.
- [ ] **4.2** Run, confirm FAIL.
- [ ] **4.3** Implement `Score` (Pydantic v2: `value: float ∈ [0,1]`, `kind: str`, `reasoning: str | None`).
- [ ] **4.4** Implement `Scorer` ABC with `name: str`, `kind: str`, and **`def score(actual: str, expected: str, case_meta: dict[str, Any]) -> Score`** (sync, not async — CPU-bound comparison; async scorers like LLM-as-judge land in Phase 2 as `async def score` with `asyncio.to_thread` dispatch).
- [ ] **4.5** Implement `ExactMatchScorer` with `case_sensitive: bool = True` constructor arg.
- [ ] **4.6** Register in `mahavishnu/core/eval/_entry_points.py` under `group="mahavishnu.eval.scorers"`, `name="mahavishnu.exact_match"`.
- [ ] **4.7** Run, confirm PASS.
- [ ] **4.8** Commit.

#### Integration Contract (Task 4)
- **Triggered from**: `EvalEngine.run_suite()` (Task 6) per case, after model output is collected.
- **Returns to / updates**: in-memory `Score` object; persisted in Task 5.
- **Demonstrable by**: `pytest tests/unit/core/eval/scorers/test_exact_match.py -v`.
- **Rollback signal**: any `ScoringError` propagated; logged with `eval.scorer.error` and the case marked as `scored=False` in the run record.
- **Observability added**: per-scoring structured log line `eval.scorer.run name=exact_match duration_ms=N`.

---

### Task 5: Storage ABC + SQLite backend (REQ-002 partial)

**Files:**
- Create: `mahavishnu/core/eval/storage.py` (`EvalStorage` ABC with `start_run`, `add_case_result`, **`finish_run`**, `get_run`, `list_runs`; `RunRecord`, `CaseRecord`, `ScoreRecord`, `EvalSummary`)
- Create: `mahavishnu/core/eval/storage_backends/__init__.py`
- Create: `mahavishnu/core/eval/storage_backends/sqlite.py` (`SqliteEvalStorage`, WAL mode + parent dir creation)
- Modify: `mahavishnu/core/eval/_entry_points.py` (register `mahavishnu.sqlite`)
- Test: `tests/unit/core/eval/storage_backends/test_sqlite.py`

**Steps:**
- [ ] **5.1** Write failing tests (using `tmp_path` fixture): (a) `start_run` / `add_case_result` / `finish_run` / `get_run` / `list_runs` round-trip; (b) `db_path` with a non-existent parent directory succeeds (parent is created); (c) 10 concurrent `asyncio.to_thread` writes don't lock (WAL mode); (d) a corrupt DB file raises `EvalStorageError` (not raw `sqlite3.DatabaseError`); (e) `finish_run` transitions a run from `"running"` to `"completed"`; (f) `get_run` returns `len(case_results) > 0` for a run with 3 cases.
- [ ] **5.2** Run, confirm FAIL.
- [ ] **5.3** Define pinned record shapes:
  - `RunRecord(id: str, suite_name: str, suite_version: str, suite_hash: str, model_configs: dict[str, Any], started_at: datetime, finished_at: datetime | None, status: Literal["running", "completed", "budget_exceeded", "failed"], summary: EvalSummary)`
  - `CaseRecord(id: str, run_id: str, case_id: str, case_index: int, actual: str, error: str | None, scored: bool)`
  - `ScoreRecord(id: str, case_id: str, scorer_name: str, value: float, kind: str, reasoning: str | None)`
  - `EvalSummary(TypedDict): total_cases, scored_cases, errors, duration_seconds, cost_usd, mean_score, min_score, max_score`
- [ ] **5.4** Implement `EvalStorage` ABC with five methods: `start_run`, `add_case_result`, **`finish_run(run_id, status, finished_at, summary)`** (NEW — required to transition run status), `get_run`, `list_runs`. All `async`.
- [ ] **5.5** Implement `SqliteEvalStorage` with stdlib `sqlite3` (sync, wrapped in `asyncio.to_thread`). Schema:
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
- [ ] **5.6** Register in `mahavishnu/core/eval/_entry_points.py` under `group="mahavishnu.eval.storage"`, `name="mahavishnu.sqlite"`.
- [ ] **5.7** Run tests, confirm PASS.
- [ ] **5.8** Commit.

#### Integration Contract (Task 5)
- **Triggered from**: `EvalEngine.run_suite()` (Task 6); `eval_get_run` MCP tool (Task 7).
- **Returns to / updates**: SQLite file at `db_path` from `EvalSettings` (default `~/.local/state/mahavishnu/eval/runs.sqlite`).
- **Demonstrable by**: `pytest tests/unit/core/eval/storage_backends/test_sqlite.py -v`; `sqlite3 ~/.local/state/mahavishnu/eval/runs.sqlite "SELECT count(*) FROM runs;"` after a real run.
- **Rollback signal**: SQLite `OperationalError` (disk full, permissions, locked); surfaced as `EvalStorageError` with full path + cause.
- **Observability added**: per-write structured log line `eval.storage.write table=runs id=... duration_ms=N`.

---

### Task 6: EvalEngine orchestration (REQ-003, model_backend part of REQ-002)

**Files:**
- Create: `mahavishnu/core/eval/engine.py` (`EvalEngine`, `EvalSuite`, `ModelConfig`, `CostBudget`, `EvalRunResult`, `EvalEngineError`, `ModelBackend` Protocol, `ModelResponse`, `TokenUsage`)
- Create: `mahavishnu/core/eval/model_backends/__init__.py`
- Create: `mahavishnu/core/eval/model_backends/mock.py` (`MockModelBackend`)
- Modify: `mahavishnu/core/eval/_entry_points.py` (register `mahavishnu.mock`)
- Modify: `tests/conftest.py` (export `mock_model_backend` fixture)
- Test: `tests/unit/core/eval/test_engine.py`

**Steps:**
- [ ] **6.1** Write failing tests with `MockModelBackend` and in-memory `SqliteEvalStorage`: (a) 2-case suite produces 2 `CaseRecord`s + 2 `ScoreRecord`s AND `finish_run` transitions status to `"completed"`; (b1) last case ends exactly at 100% of budget → `status="completed"`; (b2) last case would exceed → `status="budget_exceeded"`; (b3) case 1 alone exceeds entire budget → no other cases run, `status="budget_exceeded"`; (c) one case erroring doesn't kill the run, status is `"completed"`; (d) `EvalRunResult.run_id`, `status`, `finished_at`, `summary` are all populated and returned.
- [ ] **6.2** Run, confirm FAIL.
- [ ] **6.3** Implement types: `ModelResponse(output: str, usage: TokenUsage | None, latency_ms: float | None)`, `TokenUsage(prompt_tokens: int, completion_tokens: int, total_tokens: int)`, `ModelBackend` Protocol: `async def complete(prompt: str, model_config: ModelConfig) -> ModelResponse`. `EvalRunResult(run_id: str, status: Literal["completed", "budget_exceeded", "failed"], finished_at: datetime, summary: EvalSummary)`. `CostBudget(max_usd: float, max_concurrency: int)`. `EvalEngineError(Exception)` with `retryable: bool` field.
- [ ] **6.4** Implement `EvalEngine.run_suite` as a thin orchestrator split into helpers (must stay under `max-statements=55` and `max-branches=15`):
  ```
  run_suite         -> orchestrator only (≤30 statements, ≤12 branches)
    _run_one_case    -> per-case execution (asyncio.Semaphore acquire, model invoke, score dispatch, persist)
    _track_budget    -> float math; returns True if case fits in remaining budget
    _summarize_run   -> compute EvalSummary, call storage.finish_run(...), build EvalRunResult
  ```
  Reference: `mahavishnu/ingesters/content_ingester.py:674` has ~50 statements for a comparable shape — `run_suite` MUST be smaller.
- [ ] **6.5** Implement `MockModelBackend` in `mahavishnu/core/eval/model_backends/mock.py` with **concrete behavior**: `complete(prompt, model_config)` returns `ModelResponse(output=prompt, usage=TokenUsage(prompt_tokens=len(prompt) // 4, completion_tokens=len(prompt) // 4, total_tokens=len(prompt) // 2), latency_ms=10.0)`. The echo-means-equal mapping means `ExactMatchScorer.score(actual=prompt, expected=prompt)` returns `Score(value=1.0)`. Register in `_entry_points.py` under `group="mahavishnu.eval.model_backends"`, `name="mahavishnu.mock"`. Add a `mock_model_backend` pytest fixture in `tests/conftest.py` returning a configured `MockModelBackend` instance.
- [ ] **6.6** Add `@observe(span_name="eval.run_suite")` on `run_suite` (from `mahavishnu/core/observability.py`). Child span uses prefixed attributes: `eval.suite_name`, `eval.model`, `eval.case_count`, `eval.cost_usd`. Avoids collision with the auto-emitted `mcp.tool.call` span's `duration_ms`.
- [ ] **6.7** Run tests, confirm PASS.
- [ ] **6.8** Commit.

#### Integration Contract (Task 6)
- **Triggered from**: `_do_run_suite` helper in `bootstrap.py::_register_eval_tools` (Task 7).
- **Returns to / updates**: SQLite `runs` (with `status` transitioned via `finish_run`), `case_results`, `scores` tables; OTel child span `eval.run_suite` with prefixed attributes.
- **Demonstrable by**: `pytest tests/unit/core/eval/test_engine.py -v`; for a real run, `mcp__mahavishnu__eval_run_suite(suite="dogfood-v0", model="mahavishnu.mock")` followed by `mcp__mahavishnu__eval_get_run(run_id=...)`.
- **Rollback signal**: any unhandled exception in `run_suite` — current run is marked `status="failed"` via `finish_run`; no data is silently lost.
- **Observability added**: OTel child span `eval.run_suite`; structured logs at `started`, `case_complete`, `budget_exceeded`, `completed`, `failed`.

---

### Task 7: EvalPool, MCP tools, health feed, e2e (REQ-004, REQ-005, REQ-008)

**Files:**
- Create: `mahavishnu/pools/eval_pool.py` (`EvalPool(BasePool)` — factory signature matches `manager.py:355-359`)
- Modify: `mahavishnu/pools/_registry.py` (add `eval_pool` to `_ensure_pool_registry_loaded()` for side-effect registration)
- Create: `mahavishnu/mcp/eval_feed.py` (`EvalFeedState` mirroring `signer_feed.py:153-249`)
- Create: `mahavishnu/mcp/bootstrap.py::_register_eval_tools` (inline per `server_core.py:293-298`)
- Modify: `mahavishnu/mcp/bootstrap.py::register_health_endpoint()` (add `eval` check block at lines 265-345)
- Modify: `mahavishnu/mcp/lifecycle.py::start_server()` (call `init_eval_feed_state()` after `init_signer_feed_state()` at line 81)
- Modify: `mahavishnu/mcp/tools/profiles.py` (add `_register_eval_tools` to `STANDARD_REGISTRATIONS` at lines 84-102 and to `REGISTRATION_MAP` at lines 181-258; import at lines 34-63)
- Modify: `mahavishnu/pools/manager.py::spawn_pool` (handle `"eval"` pool type with the corrected factory signature)
- Test: `tests/unit/pools/test_eval_pool.py`
- Test: `tests/integration/test_eval_tools_e2e.py` (4 gate assertions)
- Test: `tests/integration/test_eval_smoke_subprocess.py` (subprocess + warmup per `mcp-backend-wiring-discipline.md` §2)

**Steps:**
- [ ] **7.1** Write the in-process e2e test with 4 gate assertions: (e1) all three tools return non-empty results in the happy path; (e2) `eval_run_suite` returns `{"status": "error", "error": "evaluation disabled"}` when `get_eval_settings().enabled=False`; (e3) raw FastMCP `tools/list` returns empty for eval tools when `MAHAVISHNU_TOOL_PROFILE="minimal"` (verify the meta-tool's actual filter logic before relying on this gate — if `discover_tools` doesn't filter by profile, this gate may need adjustment); (e4) `eval_run_suite` completes without an EvalPool being spawned (the tool calls `engine.run_suite` directly).
- [ ] **7.2** Run, confirm FAIL.
- [ ] **7.3** Write the subprocess smoke test: spawn `mahavishnu mcp start` in a subprocess, wait 60s for warmup, call each registered tool through the MCP protocol (e.g. via `mcp.client.session`), assert non-empty results.
- [ ] **7.4** Run, confirm FAIL.
- [ ] **7.5** Implement `EvalPool(BasePool)` in `mahavishnu/pools/eval_pool.py`. The module-level factory `_build_eval_pool` matches the actual `manager.py::spawn_pool` call signature:
  ```python
  from .base import BasePool, PoolConfig
  from mahavishnu.core.eval.engine import EvalEngine, EvalSettings
  from mahavishnu.core.eval.settings import get_eval_settings
  from mahavishnu.core.eval._registry import discover_storage, discover_model_backends

  def _build_eval_pool(
      config: PoolConfig,
      *,
      terminal_manager: Any,       # unused; BasePool signature requires it
      session_buddy_client: Any,   # unused; BasePool signature requires it
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
      """Single virtual worker; doesn't scale; doesn't collect memory."""

      def __init__(self, config, storage, model_backend, settings):
          super().__init__(config)
          self._engine = EvalEngine(storage=storage, model_backend=model_backend, settings=settings)

      async def execute_task(self, task: dict[str, Any]) -> dict[str, Any]:
          suite = EvalSuite.model_validate(task["suite"])
          result = await self._engine.run_suite(suite)
          return result.model_dump()

      async def scale(self, target_worker_count: int) -> None:
          # No-op per BasePool abstract signature (returns None, not int)
          from oneiric.core.logging import get_logger
          get_logger(__name__).warning(
              "eval pool scale(target=%d) is a no-op; current worker count is 1, "
              "observable via get_status()", target_worker_count,
          )

      async def collect_memory(self) -> list[dict[str, Any]]:
          return []  # eval doesn't produce per-worker memory artifacts
  ```
  Register via `register_pool_type("eval", _build_eval_pool)` at the bottom of `eval_pool.py`.
- [ ] **7.6** Add `eval_pool,  # noqa: F401  — registry side-effect` to `_ensure_pool_registry_loaded()` in `mahavishnu/pools/_registry.py:89-96` so the `register_pool_type("eval", EvalPool)` call at the bottom of `eval_pool.py` fires when the registry is loaded directly.
- [ ] **7.7** Implement `EvalFeedState` in `mahavishnu/mcp/eval_feed.py` mirroring `signer_feed.py:153-249`. Module-level singleton with `asyncio.Lock`. **`entities_count` = total `CaseRecord`s across all runs** (incremented by `record_cycle(case_count=N)` — signature takes a per-run case count). `as_dict()` returns the 4-signal contract.
- [ ] **7.8** Add `init_eval_feed_state()` to `mahavishnu/mcp/eval_feed.py` and call it from `mahavishnu/mcp/lifecycle.py::start_server()` immediately after `init_signer_feed_state()` (line 81).
- [ ] **7.9** Add an `eval` check block to `register_health_endpoint()` in `mahavishnu/mcp/bootstrap.py:265-345`, mirroring the `skills_signer` branch (lines 281-294). Use the `warm: bool` pattern from `SignerFeedState` so a fresh server with `enabled=true` but no runs yet does not 503.
- [ ] **7.10** Implement `_register_eval_tools(server)` in `mahavishnu/mcp/bootstrap.py`. Inline per `server_core.py:293-298`. Gate at startup: `if not get_eval_settings().enabled: return`. Define the three `@server.tool()`-decorated functions inline. Each tool body delegates to a private `_do_*` helper to stay under `max-branches=15`:
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
          return await _do_run_suite(suite=suite, model=model, params=params, settings=settings)
      except (DatasetLoadError, ScoringError, EvalStorageError, EvalEngineError) as e:
          await get_eval_feed_state().record_error()
          return {"status": "error", "error": str(e), "error_type": type(e).__name__}
      except Exception as e:  # final fallback for the 4-signal contract
          await get_eval_feed_state().record_error()
          return {"status": "error", "error": "internal error", "error_type": type(e).__name__}

  async def _do_run_suite(suite: str, model: str, params: dict | None, settings) -> dict:
      """Helper for eval_run_suite. Owns the actual work; called by the @server.tool body."""
      loader_cls = discover_dataset_loaders()[settings.default_dataset_loader]
      backend_cls = discover_model_backends()[model or settings.default_model_backend]
      storage_cls = discover_storage()[settings.default_storage]
      dataset = loader_cls().load(Path(suite))
      run_id = await storage.start_run(suite=dataset)
      try:
          result = await engine.run_suite(EvalSuite(name=..., version=..., dataset=dataset, scorers=..., model_config=..., cost_budget=...))
          await storage.finish_run(run_id=run_id, status=result.status, finished_at=result.finished_at, summary=result.summary)
      except Exception:
          await storage.finish_run(run_id=run_id, status="failed", finished_at=datetime.now(UTC), summary={...})
          raise
      await get_eval_feed_state().record_cycle(case_count=result.summary["total_cases"])
      return {"status": result.status, "run_id": run_id, "summary": dict(result.summary)}

  async def _do_register_dataset(path: str) -> dict: ...
  async def _do_get_run(run_id: str) -> dict: ...
  ```
  Mirror patterns for `eval_register_dataset` and `eval_get_run`. The crackerjack complexity budget is then spread across 3 inline tool bodies + 3 helper functions.
- [ ] **7.11** Add `_register_eval_tools` to `STANDARD_REGISTRATIONS` in `mahavishnu/mcp/tools/profiles.py:84-102` and to `REGISTRATION_MAP` at lines 181-258. Import at lines 34-63.
- [ ] **7.12** Run e2e test, confirm PASS (4 assertions); run subprocess smoke test, confirm PASS.
- [ ] **7.13** Commit.

#### Integration Contract (Task 7)
- **Triggered from**: any agent with access to `mcp__mahavishnu__*` tools.
- **Returns to / updates**: SQLite runs DB; new markdown report at `~/.local/state/mahavishnu/eval/reports/{run_id}.md` (via `MarkdownReportWriter` from Task 8); `eval_feed` singleton state.
- **Demonstrable by**: `pytest tests/integration/test_eval_tools_e2e.py -v` (4 assertions); `pytest tests/integration/test_eval_smoke_subprocess.py -v`; `mcp__mahavishnu__get_health` shows `eval.feed.entities_count > 0` after a real run.
- **Rollback signal**: any tool returning an empty list or raising; `eval.feed.errors_total` increments; OTel `eval.run_suite` span attributes carry `outcome="error"`.
- **Observability added**: per-tool OTel spans; health feed counters; `eval.feed.last_updated_timestamp` updates on every `record_cycle()` / `record_error()`.

---

### Task 8: Reports, CLI, dogfood, plan promotion (REQ-007, REQ-008, REQ-009, REQ-010)

**Files:**
- Create: `mahavishnu/core/eval/report.py` (`MarkdownReportWriter`)
- Create: `mahavishnu/cli/eval_cli.py` (typer commands)
- Modify: `mahavishnu/_main_cli.py` (add `add_eval_commands(app)` call + import)
- Create: `data/eval/dogfood-v0.jsonl` (20-30 Mahavishnu-specific cases)
- Create: `data/eval/dogfood-v0.README.md`
- Create: `docs/eval/DOGFOOD.md`
- Create: `tests/integration/test_dogfood_smoke.py` (real-model smoke; `@pytest.mark.slow`, `@pytest.mark.requires_network`, `@pytest.mark.requires_auth`, `@pytest.mark.timeout(120)`)
- Create: `tests/integration/test_dogfood_freshness.py` (CI freshness check)
- Modify: `docs/plans/PLAN_INDEX.md` (add this plan)
- Modify: `docs/plans/2026-10-03-eval-adapter-phase1.md` (promote `status: draft` → `status: active`)

**Steps:**
- [ ] **8.1** Implement `MarkdownReportWriter` in `mahavishnu/core/eval/report.py`. Single-function module: `write_run_markdown(run_record: RunRecord, cases: list[CaseRecord], scores: list[ScoreRecord], path: Path) -> None`. Template is a Jinja2 string in the same file. Report sections: header (suite, model, status, started/finished, duration), summary (count, mean/min/max score, cost), per-case detail (case_id, actual, error if any, scores), and a "footer" with the `entities_count` cumulative.
- [ ] **8.2** Implement CLI in `mahavishnu/cli/eval_cli.py` using **typer** (NOT click):
  ```python
  import typer
  from pathlib import Path

  eval_app = typer.Typer(help="Model evaluation commands (mirror mcp__mahavishnu__eval_*)")

  @eval_app.command("run-suite")
  def run_suite(
      suite: Path = typer.Option(..., "--suite", exists=True, help="Path to JSONL dataset"),
      model: str = typer.Option("MiniMax-M2.7-highspeed", "--model", help="Model backend name"),
      budget: float | None = typer.Option(None, "--budget", help="Per-run cost cap in USD"),
  ) -> None:
      ...

  def add_eval_commands(app: typer.Typer) -> None:
      app.add_typer(eval_app, name="eval")
  ```
  Then in `mahavishnu/_main_cli.py`: add `from .cli.eval_cli import add_eval_commands` to the import block (lines 17-45) and add `add_eval_commands(app)` call within the existing `add_*_commands` block (lines 1358-1606, where other subcommand registrations live).
- [ ] **8.3** Curate 20-30 **Mahavishnu-specific** cases. Starting list (must be expanded before Task 8.6 runs):
  - "Given a Mahavishnu workflow config with a single repo and `pool_type: 'mahavishnu'`, which pool selector would minimize latency?" → expected: contains "least_loaded"
  - "Given a repo with tags `['backend', 'python']` and a query 'refactor the API layer', which adapter should Mahavishnu route this to?" → expected: contains "prefect" or "llamaindex" or "agno"
  - "Given a failing pool health check, what is the remediation step in Mahavishnu's `pool_health` tool output?" → expected: mentions pool restart or respawn
  - "Given a Mahavishnu settings file with `pools_enabled: true` and no spawned pools, what does `mcp__mahavishnu__pool_health` return?" → expected: `status: "degraded"` or similar
  - "Given a workflow run with status='failed' and error 'NoAdapterAvailable', what is the most likely configuration fix?" → expected: references adapters config or `MAHAVISHNU_ADAPTERS_PREFECT=true` etc.
  - ... 15-25 more, drawn from real Mahavishnu scenarios (repo routing, pool management, adapter selection, configuration, error recovery).
- [ ] **8.4** Write `data/eval/dogfood-v0.jsonl` with 20-30 cases. Each line: `{"id": "...", "input": "...", "expected": "...", "metadata": {"added_by": "<team-member>", "failure_mode": "<one-line description>", "last_reviewed": "<ISO date>"}}`.
- [ ] **8.5** Write `data/eval/dogfood-v0.README.md` and `docs/eval/DOGFOOD.md`.
- [ ] **8.6** Write the smoke test: `@pytest.mark.integration, @pytest.mark.slow, @pytest.mark.requires_network, @pytest.mark.requires_auth, @pytest.mark.timeout(120)`. Runs the dogfood set end-to-end; asserts run completes in <120s, report at `~/.local/state/mahavishnu/eval/reports/{run_id}.md` is non-empty (len(case_results) > 0 AND len(scores) > 0), and `eval.feed.cycles_total` incremented.
- [ ] **8.7** Write the freshness test: reads `data/eval/dogfood-v0.jsonl`, asserts at least 80% of cases have `metadata.last_reviewed` within the last 90 days. Fails otherwise.
- [ ] **8.8** Promote this plan: update frontmatter `status: draft` → `status: active`, and add a row to `docs/plans/PLAN_INDEX.md`.
- [ ] **8.9** Commit all the above.
- [ ] **8.10** Run `crackerjack run` and `pytest tests/integration/ -v`. If everything passes, the plan is done.

#### Integration Contract (Task 8)
- **Triggered from**: `pytest tests/integration/test_dogfood_smoke.py` (CI, slow); `pytest tests/integration/test_dogfood_freshness.py` (CI, every PR); `mahavishnu eval run-suite --suite <path> --model <name>` CLI invocation.
- **Returns to / updates**: SQLite runs DB; new markdown report; `docs/plans/PLAN_INDEX.md` updated; this plan's frontmatter promoted.
- **Demonstrable by**: the smoke test itself; `cat ~/.local/state/mahavishnu/eval/reports/{latest}.md` after a real run.
- **Rollback signal**: smoke test failing in CI → the framework is broken, not the data; investigate before changing the golden set.
- **Observability added**: same as Task 7; smoke test logs `eval.dogfood.run` with `cases=N, model=..., cost_usd=..., duration_ms=...`.

---

## 6. Required Code Changes

**Create:**
- `mahavishnu/core/eval/__init__.py` (re-export hub)
- `mahavishnu/core/eval/_registry.py`
- `mahavishnu/core/eval/_entry_points.py` (single file, all four groups)
- `mahavishnu/core/eval/_compat.py` (per-action shim; Phase 1 only needs the hash shim)
- `mahavishnu/core/eval/settings.py` (`EvalSettings` + `get_eval_settings()`)
- `mahavishnu/core/eval/dataset.py`
- `mahavishnu/core/eval/scorer.py`
- `mahavishnu/core/eval/storage.py`
- `mahavishnu/core/eval/engine.py`
- `mahavishnu/core/eval/report.py` (REQ-009)
- `mahavishnu/core/eval/loaders/__init__.py`
- `mahavishnu/core/eval/loaders/jsonl.py`
- `mahavishnu/core/eval/scorers/__init__.py`
- `mahavishnu/core/eval/scorers/exact_match.py`
- `mahavishnu/core/eval/storage_backends/__init__.py`
- `mahavishnu/core/eval/storage_backends/sqlite.py`
- `mahavishnu/core/eval/model_backends/__init__.py`
- `mahavishnu/core/eval/model_backends/mock.py`
- `mahavishnu/pools/eval_pool.py` (REQ-004)
- `mahavishnu/mcp/eval_feed.py` (REQ-008)
- `mahavishnu/cli/eval_cli.py` (REQ-010)
- `data/eval/dogfood-v0.jsonl` (REQ-007)
- `data/eval/dogfood-v0.README.md`
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
- `pyproject.toml` (4 new entry-point groups + 10-line per-file-ignore block — Task 0)
- `mahavishnu/core/adapter_discovery.py` (allowlist — Task 0)
- `settings/mahavishnu.yaml` (add `eval:` block — Task 2)
- `mahavishnu/core/config.py` (add `eval: EvalSettings` field to `MahavishnuSettings` — Task 2)
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
| `mcp__mahavishnu__get_health` (after a real run) | `eval.feed.entities_count > 0` and `eval.feed.cycles_total > 0` | health response |
| `mahavishnu eval run-suite --suite data/eval/dogfood-v0.jsonl --model mahavishnu.mock` (CLI) | Same as MCP `eval_run_suite` | CLI stdout + report file |
| `grep -rE "TODO|FIXME|implement later" mahavishnu/core/eval/ mahavishnu/pools/eval_pool.py mahavishnu/mcp/eval_feed.py mahavishnu/cli/eval_cli.py` | No matches | shell output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Oneiric action-kit doesn't have a primitive we need (e.g. retry with exponential backoff specific to LLM calls) | Medium | Fall back to a hand-rolled implementation in `mahavishnu/core/eval/_compat.py`, with a comment linking to the action-kit issue; revisit when the action lands. Phase 1 only needs the hash shim. |
| SQLite locking under concurrent writes | Low | WAL mode + `synchronous=NORMAL` enabled in `SqliteEvalStorage._init_schema`; `asyncio.to_thread` wraps all writes. Stress test in Task 5.1c. |
| Dogfood golden set drifts out of relevance | High | `DOGFOOD.md` mandates a review every quarter AND a CI test `test_dogfood_freshness.py` asserts ≥80% of cases have `metadata.last_reviewed` within 90 days. Quarterly review becomes enforced, not a process promise. |
| Cost budget calculation is approximate (uses `max_tokens` fallback when `usage is None`) | High in Phase 1 | Document the limitation; precise pricing lands in Phase 2 with the Bifrost integration. `RunRecord` carries `cost_estimate_accurate=False` flag so downstream consumers know. |
| Oneiric adapter registration race during MCP server startup | Low | Entry-point discovery is sync; the registry is built once at startup before `_register_tools` runs. `_registry.py` cache has 5-min TTL; first call after startup populates. |
| The e2e test runs against the real model backend in CI and costs money | Medium | The e2e test (`test_eval_tools_e2e.py`) uses `MockModelBackend`. Real-model smoke is in `test_dogfood_smoke.py` which is `@pytest.mark.slow` and skipped by `-m "not slow"` for fast CI feedback. |
| `EvalPool.scale()` violates Liskov if not returning `None` | Low | Plan explicitly pins `scale(n) -> None` and documents the no-op behavior. Test `test_scale_noop_returns_none` pins the contract. |
| `discover_tools(query="eval_run_suite")` filter behavior is unspecified | Low | Gate (e3) in Task 7.1 uses raw FastMCP `tools/list` instead, which directly tests the profile system. If the meta-tool does filter correctly, the gate can be updated. |
| Cost-coverage boundary: dogfood smoke is `@pytest.mark.slow` and CI runs `-m "not slow"`, so `eval.feed.cycles_total > 0` requires either a manual run or a CI job that runs the slow tier | Medium | The plan's subprocess smoke test (`test_eval_smoke_subprocess.py`) is `@pytest.mark.integration, @pytest.mark.crackerjack` (NOT `slow`); it uses `MockModelBackend` and increments `cycles_total` deterministically. The `/health` green path is exercised in fast CI. The real-model smoke is slow + manual. |

## 9. Decision Rule

This plan is "done" when:
- All nine tasks have green tests + atomic commits.
- `crackerjack run` passes at the project's hard limits.
- `pytest tests/integration/test_eval_tools_e2e.py` (4 gate assertions) and `pytest tests/integration/test_eval_smoke_subprocess.py` and `pytest tests/integration/test_dogfood_freshness.py` all pass.
- `pytest tests/integration/test_dogfood_smoke.py -v` (slow) passes.
- The dogfood run produces a non-empty markdown report at `~/.local/state/mahavishnu/eval/reports/{run_id}.md`.
- The MCP server `/health` reports `eval.feed.entities_count > 0` and `eval.feed.cycles_total > 0` after a real run.
- This plan is promoted from `status: draft` to `status: active` and added to `docs/plans/PLAN_INDEX.md`.
- `python scripts/audit_orphans.py` reports no newly-added symbols with zero callers.

If any of these fail, do not declare Phase 1 done. The wire-up contract is the bar.

## References

- `docs/plans/TEMPLATE.md` — the plan format this file follows.
- `docs/plans/2026-05-10-minimax27-provider-migration.md` — example of a completed Mahavishnu plan.
- `.claude/decisions/wire-up-contract.md` — the integration contract discipline.
- `.claude/decisions/mcp-backend-wiring-discipline.md` — MCP-specific companion rule (subprocess + warmup, 4-signal feed contract).
- `mahavishnu/core/adapter_discovery.py` — the in-repo oneiric integration pattern this plan follows.
- `mahavishnu/pools/base.py:84, 156` — `BasePool` (not `PoolBase`); `scale(target_worker_count) -> None` abstract signature.
- `mahavishnu/pools/manager.py:355-359` — pool factory invocation shape (`factory(config, *, terminal_manager, session_buddy_client)`).
- `mahavishnu/mcp/server_core.py:293-298` — FastMCP inline-tooling constraint.
- `mahavishnu/mcp/signer_feed.py:153-249` — canonical feed-state pattern (mirror for `eval_feed.py`).
- `mahavishnu/mcp/sweepers/task_orphan_sweeper.py:264` — canonical "start a child OTel span" precedent.
- `mahavishnu/mcp/bootstrap.py:265-345` — `register_health_endpoint()` where the `eval` check block lives.
- `mahavishnu/mcp/tools/profiles.py:84-102, 181-258` — `STANDARD_REGISTRATIONS` and `REGISTRATION_MAP`.
- `mahavishnu/workers/cloud_worker.py` — the existing MiniMax worker that the eval engine will compose.
- `mahavishnu/core/config.py:2627-2665, 2786, 3046` — `MahavishnuSettings` env_prefix precedent; `otel_ingester` field; `get_settings()` lazy getter pattern.
- `mahavishnu/_main_cli.py:17-45, 1358-1606` — CLI entry point and `add_*_commands` registration block.
- `mahavishnu/cli/plan_cli.py:18-23, 47-51` — canonical `typer` command pattern.
- `oneiric/docs/action-kits.md` — catalog of common primitives (verify availability before hand-rolling; `oneiric.actions.compression.HashAction` for sha256).
- `ADR 017: Oneiric as the shared persistence substrate for Bodai` — substrate conventions.
- `pyproject.toml:407-420` — existing `per-file-ignores` carve-outs for Pydantic-heavy files (the model for Task 0's additions).
- Memory items cross-referenced: `pydantic-future-annotations-forward-ref.md`, `feedback-no-bodai-prefix-in-config-names.md`, `feedback-memories-must-be-dual-stored.md`, `wire-protocol-source-of-truth.md`, `multi-agent-review-catches-blind-spots.md`.
