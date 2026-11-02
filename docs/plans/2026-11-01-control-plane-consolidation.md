---
status: draft
role: canonical
kind: plan
date: 2026-11-01
last_reviewed: 2026-11-01
superseded_by: null
topic: control-plane-consolidation
title: "Control-plane consolidation — one registry, one envelope, one workflow lane"
requirements:
  - id: REQ-C01
    title: "Every adapter registered in app.adapters is selectable by the router and named in the MCP tool's adapter list"
    description: "worker, hatchet, and pydantic_ai are reachable through TaskRouter and documented in trigger_workflow, not only prefect/agno/llamaindex."
  - id: REQ-C02
    title: "One task-envelope shape reaches every adapter"
    description: "The MCP tool, the CLI sweep commands, and the router build the same envelope, so an adapter reads the same keys regardless of which entry point dispatched it."
  - id: REQ-C03
    title: "Exactly one adapter registry, one TaskRouter, and one workflow state store exist in production code"
    description: "UnifiedOrchestrator, task_router.AdapterManager, the second TaskRouter, and the duplicate workflow state stores are removed or folded in."
  - id: REQ-C04
    title: "Every execution returns one envelope shape carrying explicit terminal state, exit code, and cost"
    description: "Engine adapters, the worker adapter, and the pool lane all return the same result envelope."
  - id: REQ-C05
    title: "The control plane creates the span; an engine's own tracer is never the source of truth for a mahavishnu workflow span"
    description: "One span tree spans engine and worker legs, created by mahavishnu's observability layer."
  - id: REQ-C06
    title: "A pool dispatch carries a workflow id and participates in the same span tree as an engine dispatch"
    description: "pool_route_execute produces a workflow id and lands in the same workflow state and outcome store as trigger_workflow."
  - id: REQ-C07
    title: "A workflow can run an engine leg and a terminal-worker leg in one execution, with the second leg consuming the first's output"
    description: "A composition demo runs both legs under one workflow id and one span tree."
  - id: REQ-C08
    title: "A one-shot dispatch reports an explicit terminal state that a later poll cannot reverse"
    description: "Settling is final; a stale poll cannot move a settled dispatch back to running."
  - id: REQ-C09
    title: "A one-shot dispatch waits for an explicit readiness signal before it is reported running"
    description: "The dispatch is not running until the CLI demonstrably holds the prompt."
  - id: REQ-C10
    title: "The prompt the CLI read is verified against a digest the worker wrote"
    description: "A truncated or partially-written prompt fails the dispatch rather than running with the wrong bytes. This is a DELIVERY-FIDELITY control, not an authenticity guarantee: it catches truncation, partial writes, and wrong-file mix-up; it does not defend against a malicious caller or a compromised host, and the digest is advisory."
  - id: REQ-C11
    title: "Every demo routes through the workflow lane and produces a workflow id"
    description: "The engine demos stop calling adapter.execute directly, so a demo run exercises the same path an operator gets."
  - id: REQ-C12
    title: "The demo inventory matches the shipped demo set"
    description: "The DEMO SUB-COMMANDS comment, the demo_cli stub tally, the cookbook recipes, the CLI reference, and the wireup invariant tests all move together."
  - id: REQ-C13
    title: "A dispatch's cost is recorded and can be rolled up across legs"
    description: "enable_cost_tracking stops being a dead parameter, and a workflow's total cost spans its engine and worker legs."
  - id: REQ-C14
    title: "The openhands worker speaks the current OpenHands SDK API"
    description: "The worker uses the current conversation, event-stream, and terminal-status contract instead of the deleted V0 shape."
  - id: REQ-C15
    title: "Every workflow demo has a cookbook recipe and every recipe names a command that exists"
    description: "A test parses docs/cookbook/workflows.md and checks both directions, so the cookbook cannot drift silently."
---

# Control-plane consolidation — one registry, one envelope, one workflow lane

> **Status: draft, pending multi-agent review.** This plan supersedes
> `docs/plans/2026-11-01-terminal-cli-harness-demos-and-dispatch-trust.md`
> and `docs/plans/2026-11-01-adapter-composition-executor.md`, both of which
> are marked `superseded_by` this file.
>
> **Why superseding rather than adding:** both predecessor plans were
> written before the code was traced, and both are wrong in ways that
> would have produced expensive work. The dispatch-trust plan prices
> building a worker adapter that already exists, asserts engine-leg cost
> accounting that nothing implements, and would add a third worker state
> machine beside an existing one. The composition plan prices a chain
> executor on the assumption that no composition exists, when a proven
> two-stage composition is already in the demo layer. §4 records the
> corrections with evidence.

## Policy: No backwards compatibility / legacy support

**This plan is forward-only.** Where a shape, a key, a config field, a
module or a stored record changes, it changes — there is **no
deprecation window, no alias, no re-export shim, and no migration of
old data**. Bodai is pre-1.0; no external consumer depends on the
current surface, so defensive scaffolding buys nothing and costs
merge-conflict surface for free.

Concretely, this plan **deletes** rather than deprecates
(`core/routing.py`, `core/workflow_state.py`, `AdapterRegistryConfig`,
`core/unified_orchestrator.py`, the `adapter_registry:` and
`feature_flags:` YAML blocks); **renames** rather than aliases
(`integrations.pydantic_ai_enabled` → `adapters.pydantic_ai_enabled`,
with its one consumer `cli/demo_cli.py:1280` repointed); **prunes**
rather than migrates the 469 stored workflow records (Phase 3 task 6b);
and **bumps** tool versions straight through, with no `DEPRECATED_TOOLS`
entry and no translation shim — the ADR-015 deprecation machinery is
**deliberately not used**. Version numbers stay honest about *what
breaks*, which is the part that matters.

§3 non-goal 10 restates this as a scope boundary.

## 1. Outcome

**Every adapter mahavishnu ships is reachable, returns the same shape,
and produces the same kind of identity.** One workflow id, one span tree,
one cost rollup — whether the work ran on a Prefect flow, a LlamaIndex
query, an Agno agent loop, or a `claude` CLI in a tmux pane.

Success signal:

```bash
# every adapter is selectable, not just the three the router knew about
mahavishnu demo workflow-adapter-swap --engine-a prefect --engine-b worker
# -> one workflow_id, one span tree, both legs settle

# the worker leg participates in the workflow lane
mahavishnu demo terminal-claude
# -> workflow_id: wf_<hex>_terminal
# -> status: completed
# -> answer: DISPATCH-OK

# a composition: engine leg, then worker leg, one identity
mahavishnu demo workflow-engine-and-worker
# -> workflow_id: wf_<hex>_composition
# -> engine leg: completed
# -> worker leg: completed
# -> one span tree covering both legs
```

And the simplification that makes it maintainable: **one dispatch
registry, one router, one task envelope, one result envelope, one
execution lifecycle enum** — instead of two of each.

## 2. Goals

1. Make every registered adapter **reachable** — selectable by the
   router and named in the MCP tool's own documentation — so "built" and
   "usable" stop being different things.
2. Collapse the duplicated machinery (§4.2) into **one** adapter
   registry, one router, one workflow state store, one worker registry,
   one lifecycle enum, and one task envelope.
3. Give every execution **one result envelope** with an explicit terminal
   state and an exit code — so a caller does not have to know which
   substrate ran.
4. Put the **pool lane inside the workflow lane**, so a terminal-worker
   dispatch has a workflow id and lands in the same span tree as an
   engine dispatch. Today it has neither.
5. Make a **composition** — an engine leg and a worker leg in one
   execution — a first-class, demonstrated capability, promoting the
   pattern already proven in `demo workflow-pi-then-local`.
6. Make the one-shot dispatch protocol **trustworthy**: settled is
   final, readiness is explicit, and the prompt's delivery is verified.
7. Bring the **demos up to date** — they are the product's only
   user-facing surface, and today they bypass the workflow lane, one of
   them does not exercise the adapter it is named after, and one of them
   advertises a stage it does not contain.
8. Keep the whole thing **fast enough to be worth using**. Time and
   efficiency are first-class acceptance criteria, not afterthoughts:
   the workflow lane must not make the hot path slower than the pool
   lane it absorbs, and the consolidation must not add a per-dispatch
   cost that shows up as latency for every agent in the fleet.

### 2.1 Time and efficiency criteria

Cost accounting is **deferred** (§3 non-goal 8). What replaces it as the
optimization lens is time and efficiency, measured at three points:

| Criterion | Where it is measured | Budget |
|---|---|---|
| **Dispatch latency** — the added overhead of joining the pool lane to the workflow lane | `mcp__mahavishnu__pool_route_execute` wall time, before vs after | the pool lane's documented **~200–500 ms** routing overhead must not grow (§4.5) |
| **Fan-out cost** — what one dispatch costs in *resources*, not dollars | workers spawned, tmux sessions created, wall-clock seconds per leg | `count` bounded (§4.11); one worker per task, never per repo × task |
| **State-write cost** — the workflow record's write path | `StateManager._persist` (`core/task_router.py:217`) rewrites the **entire** JSON file on every mutation, unlocked | the pool lane must not write a full-file-rewrite record per dispatch; either the record is written once at completion, or the store gets a lock + atomic replace first |

The third row is the one that bites. `StateManager._persist` does
`self._state_file().write_text(json.dumps(data, indent=2))` — a full
file rewrite, no lock. Putting the pool lane's high-volume dispatch path
onto that store turns every dispatch into a full-file rewrite. **That is
a reason to fix the store before joining the lane, not after.**

Efficiency also means **not duplicating work**: the plan's §4.2
duplication table is itself an efficiency inventory — every duplicate
is a place where the same decision is made twice, in two places, that
must then be kept in sync.

## 3. Non-Goals

1. **Not** replacing Prefect, Agno, LlamaIndex, Hatchet, or Pydantic-AI.
   They are the fleet's engines. The engines' own workers stay.
2. **Not** building a daemon, rendezvous socket, or lease manager. Our
   workers are one-shot CLI harnesses — a session per prompt, torn down
   when done. A per-task session *is* the lease. What is worth taking
   from Claude Code's background-worker daemon is the **state machine**,
   not the process architecture.
3. **Not** adopting a third-party orchestrator (Temporal, Airflow,
   Prefect-as-composer) to host the composition. Delegating the
   composition to an engine would hand the observability to that engine
   too, which is the thing the composition is supposed to fix.
4. **Not** making the worker adapter a peer *inside* an engine. Engines
   execute flows the engine defines; our workers execute third-party
   agent CLIs no engine knows about. The worker layer earns its place by
   doing what the engines cannot.
5. **Not** changing the `terminal-crow`, `terminal-shell`,
   `terminal-python`, or other non-one-shot worker types.
6. **Not** adding `demo terminal-deepagents` or `demo terminal-clai`.
   The three CLIs with a working binary and a documented non-interactive
   invocation on this host are the scope; the rest are covered by the
   same registry tests.
7. **Not** changing the version numbers of any Bodai package.
8. **Not** building cost accounting in this plan. `ADAPTER_COSTS`
   (`core/cost_optimizer.py:43`) exists but **nothing consults it
   during a workflow run** — `enable_cost_tracking` is a dead parameter
   and `CostOptimizer` has no production consumer (§4.6). Turning it on
   is a *separate* piece of work with its own risk: it has a background
   budget loop that has never run, and a worker leg's real cost is
   wall-clock, not tokens, so no prior art supplies the model. **Getting
   things working comes first**; the cost rollup lands after the
   workflow lane is sound, and lands on a store that can carry it.
   §2.1 carries the optimization criteria in the meantime.
9. **Not** deciding the Oneiric adapter-bridge migration's shape. That
   is owned by `docs/plans/2026-10-14-decision-adapter-category.md`
   (§4.13); this plan must route *around* it, not duplicate it.
10. **No backwards compatibility.** This plan is **forward-only**
    (the repo's recorded pre-1.0 policy: *replace, not extend*). Where
    a shape, a key, a config field or a module changes, it changes —
    there is **no deprecation window, no alias, no re-export shim, and
    no migration of old data**. Concretely, this plan therefore:
    - **deletes** rather than deprecates (`core/routing.py`,
      `core/workflow_state.py`, `AdapterRegistryConfig`,
      `core/unified_orchestrator.py`, the `adapter_registry:` and
      `feature_flags:` YAML blocks);
    - **renames** rather than aliases
      (`integrations.pydantic_ai_enabled` → `adapters.pydantic_ai_enabled`,
      with its one consumer `cli/demo_cli.py:1280` repointed);
    - **prunes** rather than migrates the 469 stored workflow records
      (Phase 3 task 6b);
    - **bumps** tool versions straight through, with no
      `DEPRECATED_TOOLS` entry and no translation shim — so the
      ADR-015 deprecation machinery the first draft was about to
      inherit is **deliberately not used**. The version numbers stay
      honest about *what breaks*, which is the part that matters.
    This removes the first draft's biggest source of accidental
    complexity: three of round 2's findings were about compatibility
    surfaces that do not need to exist.

## 4. Current Findings

### 4.1 What generates a workflow today

**Nothing declarative.** There is exactly one workflow-record creation
point — `initialize_workflow_state`
(`mahavishnu/core/workflow_execution.py:36`), reached only from
`execute_workflow_parallel` and `dispatch_workflow_async`. The
`workflow_id` is `f"wf_{uuid.uuid4().hex[:8]}_{task.get('type','default')}"`.
The payload is always a raw `dict[str, Any]`, and its content comes from
whichever caller made the request.

There is no workflow DSL in production. The three candidates are all dead
ends:

| Candidate | Verdict |
|---|---|
| `@mahavishnu_workflow` + `WorkflowSpec` (`mahavishnu/distill/decorator.py:46`) | Real, but **zero actual decorator applications** (every grep hit is a docstring or comment) and the spec carries metadata only — `intent`, `schedule`, `work_pool`, `tags`, `repo_filter` — with no steps |
| `examples/workflow_oneiric_examples.yaml` (`workflows:` / `steps:` / `${steps.x}`) | **Nothing loads it** — a dead example |
| `mahavishnu/engines/prefect_schedules.py` | Builds a Prefect schedule dict; creates nothing |

The generation ritual is documented in `docs/cookbook/workflows.md:204`
("How to add a new recipe"): write demo Python, update a CLI comment,
add 4–5 tests, write a cookbook recipe, update `docs/CLI_REFERENCE.md`,
run the gate. **Each "workflow" is hand-written Python plus prose.**

The workflow model's only axis of composition is **repos, not stages**:
`process_single_repo` (`mahavishnu/core/workflow_execution.py:182`) calls
`adapter.execute(task | {"single_repo": repo_path}, [repo_path])` — one
adapter call per repo, gathered in parallel. `execute_workflow_with_fallback`
picks **one** adapter and tries it until one succeeds. Nothing threads
adapter A's output into adapter B.

### 4.2 The duplications

Ten, not eight. The first version of this table named eight; the
multi-agent review (§11) found two more and reversed two of the eight.
Each row names a **winner** — the single place that owns the concept.

| # | Concept | Duplicated in | Winner | Why |
|---|---|---|---|---|
| 1 | **Adapter registry** | **seven** listings: `app.adapters` (`core/app.py:254`), `task_router.AdapterManager.adapters` (`core/task_router.py:127`), `_ENGINE_LOCATIONS` (`engines/__init__.py:104`), `settings.worker_registry.entries`, `AdapterRegistryConfig` (config-only ghost), the **Oneiric entry-point group** `pyproject.toml:140-143` (`[project.entry-points."oneiric.adapters"]` = prefect, agno, worker), and the hardcoded `_import_adapter_class` if/elif chain (`core/bootstrap.py:356-381`) that populates `app.adapters` | `app.adapters` as the single **dispatch** registry | `AdapterManager.register_adapter` is called **only from test modules** — in production that registry is always empty. The other listings have distinct jobs (capability discovery, capability metadata) and are not duplicates of it |
| 2 | **Router** | `core/routing.py:TaskRouter` (chains, live) vs `core/task_router.py:TaskRouter` (registry + stats + `CapabilityRouter`) | **`core/task_router.py` survives**; `core/routing.py`'s chains fold into it | **reversed from the first draft.** `docs/decisions/2026-10-14-decision-adapter-category.md` rule 3 is a hard sequencing rule: the `task_router.py` migration to Oneiric's `AdapterBridge` must complete, and `core/routing.py`'s router is not part of that migration |
| 3 | **Orchestration entry point** | `workflow_execution.execute_workflow_with_fallback` vs `task_router.execute_with_fallback` vs `UnifiedOrchestrator.execute_workflow` | `workflow_execution`, **porting** what `UnifiedOrchestrator` had | `UnifiedOrchestrator` has zero production callers, but it is the only implementation of *N independent tasks each with its own fallback chain*, and the only implementation of **cancellation** — `workflow_execution` has no cancel path at all. Deleting it is an undeclared scope loss |
| 4 | **Worker registry** | legacy `WORKER_REGISTRY` (`workers/registry.py:178`, **43** entries) vs `settings.worker_registry.entries` (`core/config.py:1890`, **16** entries) | **the legacy dict for dispatch**; the settings entries for capability metadata and validation | **reversed from the first draft**, which had it backwards. The YAML is a strict *subset* — 27 types exist only in code, including `shepherd` (the pool's default worker type) and `openhands`. `MahavishnuSettings()` bare does **not** read YAML (`get_settings()` → 16 entries; bare → 0), so the legacy dict is the only unconditionally-populated registry. The two are also **different schemas**: `WorkerEntry` has no `permission_mode`, `category`, `endpoint`, `mcp_server`, or `error_markers`, and has `provides`, which `WorkerConfig` cannot express |
| 5 | **Worker substrate** | `WorkerManager` + `ShellWorker` (one-shot; vocabulary `WorkerStatus`) vs `DurableWorkerManager` + `WorkerLifecycleState` (interactive tmux + settle) vs `SettleState` | decided in Phase 3, as an *execution* vocabulary in `core/status.py` | three vocabularies, not two. `WorkerLifecycleState` has no `TIMEOUT`/`CANCELLED` and legally allows `COMPLETED → READY → RUNNING` — so adopting it unchanged would silently defeat Phase 7's "settled is final" |
| 6 | **Workflow state store** | **two backing stores, five key namespaces** — not four trails. *Store A:* file JSON `data/workflow_state/workflows.json` (`app.workflow_state_manager`, which **is** a `task_router.StateManager` instance, `core/bootstrap.py:620,633`). *Store B:* the **process-local** KV (`core/kv_store.py:87`), holding `workflow-results/{workflow_id}/` (`core/workflow/outcome_writer.py:77`), `workflow/v1/{execution_id}/` (`core/repository_surface.py:72`), `routing/v1/{task_class}/{ts}/` (`core/state_backends/mcp.py:141-145`, written by `core/pools/manager.py:284`), and the approval/webhook/ecosystem namespaces | one store protocol per concern: a `WorkflowStore` for the file store, a per-key `KVBackend` for the substrate; `StateManager` relocates out of `task_router.py` first | **rewritten by round 2.** The first draft called this "four persistence trails" and called one of them "the durable MCP KV". **Both were wrong.** Trails 2 and 4 are the *same* key namespace in the *same* store; trail 3 is the *same process-local dict* — `core/state_backends/mcp.py`'s own docstring says so (*"backed by a process-local thread-safe dict"*; *"All writes are fire-and-forget"*), so it is an HTTP self-call, not a durable store. The trail the inventory **omitted** is the pool lane's own — `routing/v1/`, which Phase 5 touches most. |
| 7 | **Worker wrapper** | `WorkerOrchestratorAdapter` (wraps `WorkerManager`) vs `MahavishnuPool` (wraps the same `WorkerManager`) | the adapter keeps the orchestrator-facing port; the pool keeps its leaf-wrapper rule | `pools/mahavishnu_pool.py:5-12` explicitly warns against inverting the layering ("Do NOT rewrite `execute_task` to call `pool_manager.route_task`"). The fix is a narrow `PoolRouter` port, not the adapter wrapping the pool |
| 8 | **Lifecycle vocabulary** | **14** enum names across **11** modules encode "where is this execution" | one **execution** lifecycle in `core/status.py` — **not** a 14-way superset | `core/status.py` is already the declared home ("Consolidated status enums for Mahavishnu… Issue: MHV-008 - Status Enum Consolidation"). `PoolStatus` (a resource), `PlanStatus` (a document), `WorkerCapabilityState` (a probe), and `SettleState` (a merge run) are **not** execution lifecycles and must stay separate — merging them yields a union where most members are invalid for most subjects |
| 9 | **Adapter/task enums** | `AdapterType` in `core/adapters/base.py:10` (**6** members) vs `AdapterType` in `core/metrics_schema.py:34` (**3**); `TaskType` in `core/metrics_schema.py:42` (**6**) vs `TaskType` in `core/task_router.py:82` (**5**, no `CRITICAL_TASK`) | `core/adapters/base.py:AdapterType` (6 members) for the adapter enum, and `core/metrics_schema.py:TaskType` (6 members) for the task enum — **two different homes, stated separately** | **the most consequential duplication, and the first draft missed it.** `core/routing.py:25`, `core/workflow_execution.py:24` and `core/cost_optimizer.py:31` all import the **3-member** `metrics_schema` enum — so the router literally cannot name `worker`, and the plan's Phase 2 and Phase 4 instructions were `AttributeError`s as written |
| 10 | **`AdapterRegistryConfig`** | `core/config.py:2000-2051` + the `adapter_registry:` YAML block + an untyped `feature_flags:` YAML block | **remove** | a config-only ghost. `HybridAdapterRegistry` was deleted in commit `db06fc87`; the config model outlived its implementation. `settings.adapter_registry` is read by no runtime code, and there is no `core/adapter_registry.py` |
| 11 | **Repository allowlist** | **four** implementations of one concept with **three** different fallbacks, two of them hardcoding a personal path: `core/repository_surface.py:26` `validate_path` (fallback `[cwd, home]`), `core/bootstrap.py:197` `_validate_path` (fallback `[cwd, tmpdir]` — a line-for-line near-duplicate), `core/config.py:3044` `allowed_repo_paths` (default **`["/Users/les/Projects"]`**), and `engines/agno_tools/file_tools.py:120` `DEFAULT_ALLOWED_BASE_DIRS` (**`Path("/Users/les/Projects")`** + tmp + cwd) | `config.allowed_repo_paths`, with a **non-personal default**; `bootstrap._validate_path` deleted in favour of `repository_surface.validate_path`; agno's list derived from the same field | **new in round 2, and it is security-relevant.** `allowed_repo_paths` is set in **no** settings YAML — not `settings/mahavishnu.yaml`, not the gitignored `settings/local.yaml`. So the engine lane's repository boundary is the hardcoded `["/Users/les/Projects"]`: on any other host `validate_path` rejects **every** repository and `execute_workflow_parallel` fails before an adapter runs. Phase 5 task 5 wants to bring the pool lane *inside* this boundary — the boundary must be fixed first, or the pool lane is joined to a placeholder. |
| 12 | **The caller-controlled `task_type`** | one string plays **four** roles: adapter-behaviour selector (`task["type"]`), routing classification (`TaskType`), workflow-id suffix (`core/workflow_execution.py:42`), and Prometheus label (`core/workflow_execution.py:51`) | **split it**: a bounded `routing_type` for routing/labels/ids, and a free-form `operation` for the adapters | **new in round 2.** `trigger_workflow`'s `task_type` is a required, **unvalidated** `str` (`mcp/server_core.py:412`) that reaches a **Prometheus label** and is spliced into the **workflow id** — unbounded metric cardinality from an untrusted input, and an id that can be minted invalid (§4.11). The `TaskType` enum is a *routing* classification (`workflow`/`ai_task`/`rag_query`/…); the adapters branch on `code_sweep`/`quality_check`/`focused_review`/`ingest`/`query` — **zero overlap**. |

**A fourth adapter listing, not a fifth.** `_ENGINE_LOCATIONS`
(`engines/__init__.py:104`) lists the same engines plus `pydantic_ai`.
It feeds the *capability* layer (`mcp/tools/capability_tools.py:117`),
which therefore **advertises `pydantic_ai` while the dispatch layer
cannot run it** — `pydantic_ai` has no branch in
`bootstrap._import_adapter_class` (`core/bootstrap.py:356-381`).
That inconsistency is duplication #9's second half and must be closed
with it.

### 4.3 Three of six adapters are dark

Measured, not asserted:

| adapter | in `app.adapters` | in a routing chain | in router preference orders | named in `trigger_workflow` docs |
|---|---|---|---|---|
| prefect | ✅ | ✅ | ✅ | ✅ |
| agno | ✅ | ✅ | ✅ | ✅ |
| llamaindex | ✅ | ✅ | ✅ | ✅ |
| **worker** | ✅ | ❌ | ❌ | ❌ |
| **hatchet** | ✅ | ❌ | ❌ | ❌ |
| **pydantic_ai** | ❌ | ❌ | ❌ | ❌ |

`worker` is registered by `mahavishnu/core/bootstrap.py:374-377`
(`_import_adapter_class("worker")` → `WorkerOrchestratorAdapter`), gated
on `workers.enabled`, and lands in `app.adapters["worker"]` alongside the
four engines. **The worker adapter already exists and is already
registered.** The predecessor plan priced building it; that was wrong.

`AdapterType.WORKER` appears in **no** chain: `core/routing.py:138`
(`DEFAULT_FALLBACK_CHAINS`) and `core/task_router.py:609`/`:637`
(`TASK_PREFERENCE_ORDERS`, `DEFAULT_PREFERENCE_ORDER`) contain only
prefect, agno, and llamaindex. The router therefore **cannot** select
the worker, and `trigger_workflow`'s docstring advertises only three
adapters.

### 4.4 The payload contract is not uniform

Verified by probe, not by reading:

```
worker adapter reads top-level task keys: ['count', 'prompt', 'task_type', 'timeout', 'worker_type']
trigger_workflow builds task = {"type": task_type, "params": params, "id": ...}
```

**Zero overlap.** Three builders and four expectations coexist:

| Builder | Shape |
|---|---|
| `mcp/server_core.py:477` (`trigger_workflow`) | `{"type", "params", "id"}` |
| `mahavishnu/_main_cli.py:373` and `:638` | `{"task", "id"}` — **wrong key** |
| `core/task_router.py:842` (`execute_with_fallback`) | `{"task_type", "prompt", "repos"}` — and it **silently drops the caller's `params`**, so `agents/mahavishnu_agent.py:283-286` reaches Agno with `params == {}` |
| **`mcp/server_core.py:1554-1562`** (`_dispatch_task_workflow`) | `{"type": "ai_task", "id", "params"}` — **the builder round 1 and round 2 both missed.** It is the only path from a session-buddy task to a running workflow, and the only producer of a value written into another repo's record (`Task.workflow_id`). Its `type` is hard-coded `"ai_task"`, so its id shape does **not** change — but it must still build the envelope |

| Consumer | Reads |
|---|---|
| `core/adapters/worker.py:206-211` | top-level `prompt` / `worker_type` / `count` / `timeout` / `task_type` |
| `engines/llamaindex_adapter_impl.py:1551` | `task["params"]` |
| `engines/agno_adapter_impl.py` | `task["type"]` + `task["params"]` |
| `engines/hatchet_adapter_impl.py:229-233` | top-level `prompt` |

The CLI key bug is live: `_main_cli.py:373` builds
`task = {"task": task_type, "id": ...}` and `:638` builds
`task = {"task": "ai-sweep", "id": ...}`. Because
`initialize_workflow_state` reads `task.get('type', 'default')` and
`execute_workflow_with_fallback` does
`TaskType(task.get("type", "ai_task"))`, both CLI paths mint ids as
`wf_<hex>_default`, route as `ai_task` regardless of the type the
operator asked for, and hand the adapter a dict with no `"type"` key at
all — which Agno reads.

### 4.5 Two more lanes with no workflow identity

- **The pool lane creates no workflow record.**
  `pool_route_execute` → `pool_manager.route_task` →
  `execute_on_pool` → `pool.execute_task` persists a routing-decision
  audit (`pools/manager.py:839`), not a workflow. A terminal-worker
  dispatch therefore has **no workflow id and no span tree** — not a
  different one, none.
- **Workflow outcomes are process-local.**
  `record_workflow_outcome` (`core/workflow/outcome_writer.py:54`)
  writes to `ProcessLocalKV` (`core/kv_store.py`), explicitly
  process-local. "Durable orchestration" is currently aspirational.
- **The workflow state store is not a store.** `StateManager._persist`
  (`core/task_router.py:217`) rewrites the **entire** JSON file on every
  mutation, **unlocked** and **non-atomically**, under a
  **CWD-relative** path (`:189`). Measured on this host:
  `data/workflow_state/workflows.json` is **5.2 MB** holding **469**
  records, of which **77 are stuck in `running`** — 75 of them more than
  an hour old. A server started from a different working directory
  writes a *different* file.

  **Two corrections round 2 made to this bullet.** First, *"no recovery"*
  was wrong: a reaper exists — `_check_stuck_workflows`
  (`core/resilience.py:969`) marks running workflows stale by >1 h as
  failed, and is reachable today through the `heal_workflows` MCP tool
  (`mcp/server_core.py:1120-1128`). What never runs is its **scheduler**:
  `ResiliencePatterns.start_monitoring_service`
  (`core/resilience.py:1057`) has **zero callers**. So the 77 are
  *unreaped*, not unreapable — and if anyone calls `heal_workflows` today
  it performs up to 75 sequential `update()` calls, each a full 5.2 MB
  rewrite: **~390 MB of writes**.

  Second, the real data-loss vector is **two concurrent _processes_, not
  two concurrent workflows**. The running MCP server and any CLI that
  constructs a `MahavishnuApp()` (`_main_cli.py:362` → `core/app.py:296`
  → `core/bootstrap.py:633`) each hold their own 5.2 MB snapshot and
  rewrite the whole file, dropping each other's records. Phase 1 makes
  the CLI a first-class workflow producer (it fixes the `{"task": …}` key
  bug so CLI sweeps mint correct ids *and write records*), so **this plan
  increases that exposure**.

### 4.14 Requirements index

The requirements are declared in the **frontmatter**, which is what
`scripts/audit_requirements.py` reads (`extract_declarations`,
`:95-121`). The audit drops a plan whose every requirement is
unreferenced (`_filter_dead_plans`, `:208-243`), so this plan is
invisible to the gate until Phase 1 lands its first marker — a known
transient, not a defect. This section is the human-readable index.

| ID | Title | Delivered by |
|---|---|---|
| REQ-C01 | Every registered adapter is selectable and documented | Phase 2 |
| REQ-C02 | One typed task envelope reaches every adapter | Phase 1 |
| REQ-C03 | One dispatch registry, one router, one workflow state store | Phase 3 |
| REQ-C04 | One execution envelope with explicit terminal state and exit code | Phase 4 |
| REQ-C05 | The control plane creates the span | Phase 4 |
| REQ-C06 | A pool dispatch carries a workflow id in the same span tree | Phase 5 |
| REQ-C07 | An engine leg and a worker leg compose in one execution | Phase 6 |
| REQ-C08 | A settled dispatch's terminal state is final | Phase 7 |
| REQ-C09 | A dispatch waits for an explicit readiness signal | Phase 7 |
| REQ-C10 | The prompt the CLI read is verified (delivery fidelity) | Phase 7 |
| REQ-C11 | Every demo routes through the workflow lane | Phase 8 |
| REQ-C12 | The demo inventory matches the shipped demo set | Phase 8 |
| REQ-C13 | A dispatch's cost is recorded and rollable up | **deferred** (§3 non-goal 8) |
| REQ-C14 | The openhands worker speaks the current OpenHands SDK API | Phase 1 |
| REQ-C15 | Every workflow demo has a cookbook recipe, and vice versa | Phase 8 |

### 4.6 Nothing is costed

The predecessor plan asserted that the engine leg is costed and the
worker leg is not. **Both are uncosted.**

- `ADAPTER_COSTS` (`core/cost_optimizer.py:43`) holds prefect, agno, and
  llamaindex — but nothing consults it during a workflow run.
- `enable_cost_tracking` is a **dead parameter**: accepted at
  `core/app.py:1251` and `core/workflow_execution.py:641`, referenced in
  neither body.
- `CostOptimizer` has exactly **one** consumer in the repository —
  `tests/integration/test_metrics_integration.py`.
  `get_cost_optimizer()` and `initialize_cost_optimizer()` have zero
  production call sites.
- `PoolMetrics` (`pools/base.py:65`) carries `tasks_completed`,
  `tasks_failed`, `avg_task_duration`, `memory_usage_mb` — and no cost.

So "unified cost rollup" is **not** a worker-versus-engine gap. It is a
pre-existing hole that no substrate fills. The prior-art research (§4.8)
found that **no** framework in the surveyed set has a cost model for
non-LLM substrates either: the only cost rollups that exist anywhere are
computed from LLM tokens. A CLI worker's real cost — tmux session time,
container seconds — has no home in any prior art. Mahavishnu has to
invent it.

### 4.7 Two verified defects

Both independent of any architectural decision, both worth fixing early:

1. **`mahavishnu/workers/openhands.py` targets the deleted OpenHands V0
   API.** It POSTs `{"task": task}` to `/api/conversations`, reads
   `resp.json()["conversation_id"]` (`workers/openhands.py:45`), connects
   to `/ws?conversation_id={conv_id}` (`:61`), and checks
   `event.get("type") in ("FINISHED", "ERROR")` (`:68`, `:127`). The
   current SDK wants `StartConversationRequest` with an
   `initial_message`, a WebSocket at `/sockets/events/{conversation_id}`,
   events discriminated by a `kind` field, and terminal status
   `finished | error | stuck`. **This code cannot work against the
   current SDK.**
2. **The CLI task-key bug** in §4.4.

### 4.8 What prior art says to converge on

Researched 2026-11-01 against Pydantic AI, OpenAI Agents SDK, LangGraph,
Temporal, Airflow, Dagster, CrewAI, AutoGen, Semantic Kernel, Claude
Code's background-worker daemon and Agent SDK, OpenHands, A2A, MCP, ACP,
and Sortie.

**The load-bearing finding:** every LLM framework surveyed unifies the
**model/provider** layer, not the **execution-substrate** layer. In
Pydantic AI, OpenAI Agents SDK, CrewAI, LangGraph, and Semantic Kernel, a
CLI worker is a *tool the model calls* — subordinate, model-triggered,
model-shaped. Mahavishnu's instinct — worker as a peer adapter — is the
*unusual* position. The proven pattern for it lives in durable workflow
engines: **Temporal's Activity + Task Queue split** (a uniform step
contract, plus a substrate-oblivious dispatch where the worker dials the
service), and **Airflow's `BaseOperator` + pluggable `Executor`**.

**The minimal worker contract that four independent implementations agree
on** (Claude Code's `--bg` record, ACP, A2A, MCP tasks, OpenHands,
Sortie):

1. **Two ids** — a short handle plus a durable session UUID, minted by
   the dispatcher and echoed in every reply. This is what makes results
   attributable across a process boundary.
2. **An explicit terminal-state enum**, never inferred from liveness.
   *Cancelled* is distinct from *failed*; *input-required* is distinct
   from both.
3. **Liveness and blocked-reason as a separate axis** from terminal
   state. A worker blocked on a human is not "running" and not "failed" —
   Claude Code splits `state` (working/blocked/done/failed/stopped) from
   `status` (busy/waiting/idle) and adds `waitingFor`; Prefect splits
   the same way with `PAUSED`/`CANCELLING`.
4. **A schema-validated machine-readable result.** The recurring rule:
   *a success subtype with a missing structured payload is a failure.*
5. **An event channel**, so progress is observed rather than polled.
6. **Version negotiation**, because substrates drift.

**Two contracts worth copying verbatim.** Pydantic AI's
`CommandResult(exit_code, stdout, stderr)` and AutoGen's
`CodeResult(exit_code, output)` both encode *"a non-zero exit is a
normal result, not an exception."* That is exactly the rule mahavishnu's
exit-code protocol already follows, independently validated.

**A free win on the worker path.** The Claude Agent SDK's result message
carries `is_error`, `subtype`, `structured_output`, `total_cost_usd`,
`session_id`, `usage`, and `duration_ms`. The `terminal-claude` worker
currently scrapes `{"type":"result"}` off stdout and **discards all of
it** — including the cost figure. The predecessor plan wanted to invent
a result-envelope parser; the SDK already returns one.

**The wire protocol already exists: ACP** (Agent Client Protocol) — 50+
implementers, with third-party CLI adapters for `claude`, `codex`,
`gemini-cli`, `opencode`, and `qwen-code`, implemented by both Sortie and
OpenHands' `ACPAgent`.

**The gap that is ours to fill:** the common interface must **own** span
creation and cost. OpenAI's Agents SDK ships its own `TracingProcessor`,
not OpenTelemetry, so bridging it into a span tree is work to be done,
not inherited. No framework provides a per-step retry contract either —
the Agents SDK retries per *model request*, and `max_turns` is a turn
cap, not a retry. Mahavishnu already owns step-level retry
(`core/resilience.py`: `RetryPolicy`, `retry_async`), a circuit breaker
(`app.circuit_breaker.call`), and OTel spans
(`app.observability.start_workflow_trace`) — **it just does not unify
them across substrates.**

### 4.9 The demos: what is stale

The demos are the product's only user-facing surface, and they have
drifted from the code:

| Demo | Current behaviour | Problem |
|---|---|---|
| `prefect` | uses Prefect's raw client — `get_client`, `run_deployment`, `flow_func.afrom_source(...).adeploy(...)` | **never exercises `PrefectAdapter.execute`** — `grep -n "PrefectAdapter" cli/demo_cli.py` returns zero hits |
| `agno`, `llamaindex`, `pydantic_ai`, `hatchet` | call `adapter.execute(...)` directly | bypass the workflow lane: no workflow id, no span tree, no state, no QC |
| `workflow-pool-worker-terminal` | docstring advertises "Prefect → pool → worker → terminal" | its implementation is three stages with **no Prefect leg** (REQ-010 in the predecessor plan) |
| `workflow-pi-then-local` | a real two-stage composition — stage one's output is folded into stage two's prompt (`cli/demo_cli.py:4098-4108`) | the pattern is **proven** but lives as demo-local code; it is the reference implementation for Phase 6 |
| `workflow-adapter-swap` | swaps the **terminal** adapter (mock ↔ tmux) | the name collides conceptually with an *engine*-adapter swap, which is what consolidation makes possible |
| `workflow-multi-pool-handoff`, `workflow-pi-cascade` | pool lane | no workflow identity (Phase 5) |
| `pool-*` (5 demos) | pool lane | no workflow identity (Phase 5) |
| `demo_all` | sweeps the fast set | the inventory changes as demos are added |

The inventory that must move with them: `_main_cli.py:1471-1480`
(the `DEMO SUB-COMMANDS` block, currently "16 live implementations … +
1 stub"), the stub tally in `cli/demo_cli.py`,
`docs/cookbook/workflows.md` (recipes 1 and 2), the
`### Workflow demos` block at `docs/CLI_REFERENCE.md:110`, and the
wireup invariant tests in `tests/unit/cli/test_cli_wireup_invariants.py`.

### 4.10 Marker placement

`scripts/audit_requirements.py` reads requirement declarations from plan
**frontmatter** (`requirements:`) and references from code via
`# req: REQ-NNN`, `Implements: REQ-NNN`, or
`@pytest.mark.req([...])`. A plan whose every requirement is unreferenced
is dropped from the audit as dead (`_filter_dead_plans`), so this plan
is invisible to the audit until Phase 1 lands its first marker.

Requirement ids are **global** across the repository. `REQ-001` through
`REQ-008` are already claimed by production code for other plans
(queueing, health, pool routing), and `REQ-201`–`REQ-210` are taken.
This plan therefore uses a **plan-scoped `REQ-C0n` namespace**, following
the precedent of `REQ-M01` in `docs/plans/2026-10-27-otel-metrics-service.md`.

Marker placement:

- REQ-C01 → `mahavishnu/core/routing.py`, `core/task_router.py`, `mcp/server_core.py`
- REQ-C02 → `mahavishnu/core/workflow_execution.py`, `mcp/server_core.py`, `_main_cli.py`
- REQ-C03 → `mahavishnu/core/workflow_execution.py`, `core/bootstrap.py`
- REQ-C04 → `mahavishnu/core/adapters/base.py`
- REQ-C05 → `mahavishnu/core/observability.py`
- REQ-C06 → `mahavishnu/pools/manager.py`
- REQ-C07 → `mahavishnu/cli/demo_cli.py`
- REQ-C08/009/010 → `mahavishnu/pools/mahavishnu_pool.py`, `mahavishnu/workers/shell_backend.py`
- REQ-C11/012 → `mahavishnu/cli/demo_cli.py`, `_main_cli.py`, `docs/cookbook/workflows.md`
- REQ-C13 → `mahavishnu/core/cost_optimizer.py`
- REQ-C14 → `mahavishnu/workers/openhands.py`
- REQ-C15 → `tests/unit/cli/test_cookbook_parity.py`

### 4.11 The envelope is a trust boundary

**Round 2 revised this section twice.** The first draft's prescription —
constrain `task["type"]` to the `TaskType` enum — was itself a defect:
it would have rejected the task types the fleet actually uses (§4.2
row 12). The corrected boundary separates **four** things the plan's
first draft conflated into one string.

The task envelope is where caller input becomes control input. Three
independent review lenses converged on this, and the evidence is
concrete: `core/adapters/worker.py:206-211` reads **top-level**
`worker_type`, `count`, `prompt`, `timeout` and `task_type`, and
`core/workflow_execution.py:203` hands the task dict to the adapter
unchanged. Today the caller **cannot** reach those keys, because
`trigger_workflow` nests the caller's dict under `params`
(`mcp/server_core.py:477-481`) and the worker reads the top level —
the "zero overlap" of §4.4. Today the worker adapter is also
unroutable. **Phase 1 and Phase 2 remove both barriers**, and together
they hand any `trigger_workflow` caller three selectors at once.

| Control | Unbounded today | Becomes |
|---|---|---|
| `worker_type` | `resolve_worker_type` (`workers/registry.py:896`) returns it unchanged; `_create_worker` (`workers/manager.py:483`) rejects *unknown* names, so **every registered type is selectable** — including interactive shells, database clients with credential-shaped command templates (`registry.py:410-425`), and `terminal-qwen`, whose default `permission_mode` is `yolo` (`registry.py:202`) against `terminal-claude`'s `acceptEdits` (`registry.py:238`) | an **allowlist of one-shot agent CLIs only** — `terminal-claude`, `terminal-qwen`, `terminal-codex` |
| `count` | `worker.py:217` checks only `count < 1`; the repo's own precedent at `mcp/tools/worker_tools.py:67` bounds it to **1..50** | `Field(ge=1, le=50)` |
| `timeout` | `_resolve_timeout` (`shell_backend.py:188`) — `float("inf") > 0` passes | `Field(gt=0, le=cap)`, finite `float` |
| `type` | `TaskType(task.get("type", "ai_task"))` is an **unguarded enum cast** (`workflow_execution.py:644`) that raises a bare `ValueError`; the string also lands in a Prometheus label (`workflow_execution.py:48-52`) and a workflow id (`:42`) | **split into two fields** — see below |
| `task_type` (as a *Prometheus label*) | `mahavishnu_workflows_total.labels(task_type=task.get("type", "unknown"))` (`workflow_execution.py:51`) — the caller-supplied string lands **directly in a metric label**, with **no bound on cardinality**. Every distinct value a caller passes creates a permanent new time series, in three label sets (`:381-391`) | the label carries the **bounded** `routing_type` only. The free-form operation never reaches a metric label |
| `task_type` (as a *workflow id*) | the same string is spliced into the id: `workflow_id = f"wf_{uuid.uuid4().hex[:8]}_{task.get('type','default')}"` (`workflow_execution.py:42`). `trigger_workflow`'s `task_type` is a required, **unvalidated** `str` (`mcp/server_core.py:412`), so a caller can mint an id containing `/` or a dot-segment. The **write** path does not validate it (`core/workflow/outcome_writer.py:77`); only the **read** path does (`mcp/tools/workflow_tools.py:36-38`). So the outcome is written and **permanently unreadable** — a silent loss, and a `..` segment in a key path that is inert today only because the backing store is a flat `dict` | the id suffix comes from the **bounded** `routing_type`; and the outcome writer **validates the id before writing it** (`validate_workflow_id`), so write and read agree |
| `params` (the free-form bag) | `params` is `dict[str, Any]` (`mcp/server_core.py:413`) and reaches the adapters **unchanged**. Adapters read eleven live keys from it — `query`, `index_id`, `top_k`, `file_types`, `exclude_patterns`, `id` (llamaindex); `focus`, `standards`, `target` (agno) — plus `scope` (the tool's own docstring) and `param1` (the repo's own test) | `TaskParams` keeps `extra="allow"` and a passthrough map, so **nothing is dropped**; and it is handed to the adapters as a **plain `dict`**, because agno and llamaindex call `.get()` on it |
| `count` (its *default*) | `worker.py:207` — `count = task.get("count", len(repos))`: one worker **per repo**. The plan's first draft defaulted it to **1**, silently changing a worker dispatch over N repos into a single worker | the default is preserved as `len(repos)`, resolved at dispatch time (the envelope cannot know `repos` when it is built) |

There is no command injection from an arbitrary `worker_type` — an
unregistered name fails loudly before a command is built. The exposure
is *which registered substrate*, *which permission mode*, and *how
many*. The envelope therefore must be a **Pydantic model with
separated namespaces**: `TaskEnvelope(type: TaskType, id: str,
params: TaskParams)`, where `type` and `id` are **not** members of
`TaskParams`, so caller data cannot shadow a control field.

**The corrected split.** One string today plays four roles: the
adapter-behaviour selector (`task["type"]`), the routing classification
(`TaskType`), the workflow-id suffix, and the Prometheus label. Round 2
found that the plan's first draft tried to constrain *the wrong one*:
`TaskType` is a **routing** classification (`workflow`, `ai_task`,
`rag_query`, `batch_task`, `critical_task`, `interactive_task`) while the
adapters branch on `code_sweep`, `quality_check`, `focused_review`,
`ingest`, `query` and `ingest_and_query` — **zero overlap**. Three
lenses found this independently, and it would have broken `llamaindex`'s
query path, `agno`'s task-type selection, `prefect`'s `quality_check`
operation, the shipped `mahavishnu workflow quality-check` CLI command,
the `jot_dispatch` lane, and two live tests.

The envelope therefore carries **two** task-type fields:

- **`routing_type: TaskType`** — enum-constrained and bounded. It is the
  router's key, the workflow-id suffix, and the metric label. It is
  *server-derived*, never caller-supplied.
- **`operation: str`** — free-form, length-capped. It is the adapter's
  behaviour selector and lands in `task["type"]` for agno, llamaindex,
  prefect and hatchet. It **never** reaches a metric label and **never**
  enters a workflow id.

`trigger_workflow`'s public `task_type` argument keeps its current
free-form meaning (the operation) — so **the request contract does not
change**, and the plan's "MINOR" classification holds *for the corrected
design*. Implementing the first draft's sketch literally would have been
a MAJOR change, and a breaking one.

The same discipline applies to the composition (Phase 6): stage-one
output is **untrusted data**. The reference implementation already
treats it that way — `cli/demo_cli.py:4098-4108` wraps it in
`shlex.quote` and an allowlisted command, with a comment saying so. A
composition that folds an engine leg's output into a worker leg's
prompt must preserve that discipline: delimited and labelled as quoted
content, size-capped, never concatenated into a command, and the
second leg runs with a reduced permission mode unless the operator
opts in.

And the prompt-integrity check (Phase 7) is a **delivery-fidelity**
control, not a security one: the digest is computed by the launcher,
compared by the worker, and reported through the same pane the
supervised CLI writes to. It catches truncation, partial writes, and
wrong-file mix-ups. It does **not** catch a malicious caller. The
requirement is renamed accordingly and the threat model is stated, so
nobody reads it as an authenticity guarantee.

### 4.12 Cross-plan integration

Seventeen other plans are live. Three of them collide with this plan;
the rest do not. The collision audit is a **prerequisite** — Phase 1
cannot be written correctly without knowing who owns what.

(Round 1 counted nineteen; the plan's own supersession of two
predecessors is what changed the number. The count is a moving target
by construction, so it is stated with its date.)

#### 4.12.1 `2026-10-14-decision-adapter-category.md` — hard collision

**This is the most important integration constraint in the plan.**

`docs/decisions/2026-10-14-decision-adapter-category.md` rule 3 is a
**hard sequencing rule**:

> *"Mahavishnu cannot consume the new category until the
> HybridAdapterRegistry migration in `task_router.py` is complete. The
> decision adapters exist in the substrate; they are unreachable from
> Mahavishnu's routing layer until the 5 references in
> `task_router.py:394, 403, 430, 493, 591` are ported to Oneiric's
> `AdapterBridge.use(...)`."*

That plan's Task 2 (`docs/plans/2026-10-14-decision-adapter-category.md:576`)
owns exactly the `core/task_router.py` surface my Phase 3 wanted to
delete, on branch `feat/task-router-adapter-bridge`.

**Consequences for this plan:**

1. **§4.2 row 2's winner is reversed.** `core/task_router.py`'s router
   survives and becomes the Oneiric-bridged router; `core/routing.py`'s
   `TaskRouter` — the fallback-chain builder — folds **into** it. The
   first draft of this plan had it backwards.
2. **`AdapterRegistryConfig` (§4.2 row 10) is not a ghost to invent a
   disposition for — it is the leftover of a migration another plan is
   finishing.** `HybridAdapterRegistry` was deleted in commit `db06fc87`;
   the config model outlived its implementation. That plan's Task 2
   closes the *code* side; the *config* side (the YAML block, the
   untyped `feature_flags:` block) is this plan's to remove.
3. **`pool_route_execute` is shared.** The decision plan's Phase 1 makes
   it route live through the decision category, **gated on a 7-day
   disagreement test** against a hand-coded baseline. This plan's Phase
   5 adds a `workflow_id` to its response. Those are compatible — but
   this plan must not touch the tool's *routing semantics*, and must not
   schedule Phase 5 before the decision plan's gated Phase 1 has
   settled, or the disagreement test measures a moving target.

#### 4.12.2 `2026-10-03-eval-adapter-phase1.md` — low collision, shared seams

The eval plan adds an `EvalPool` extending `BasePool`, an `EvalStorage`,
a `ScoreModelBackend`, and registers its adapter as a Oneiric entry
point. Measured overlap with this plan's surfaces:

| Surface | Overlap |
|---|---|
| `core/app.py`, `core/bootstrap.py`, `app.adapters`, `adapters/base.py`, `AdapterType` | **none** |
| `core/task_router.py`, `core/routing.py`, `core/workflow_execution.py`, `engines/__init__.py` | **none** |
| `pools/base.py` / `BasePool` | shared — the eval plan adds a pool type; this plan does not modify `pools/base.py` (the predecessor plan's `DispatchState` proposal is withdrawn, §4.2 row 5) |
| `core/config.py` | shared — the eval plan adds a nested `eval` settings field; this plan's Phase 2 adds `adapters.pydantic_ai_enabled` and Phase 3 touches the worker-registry schema. Different fields; no conflict |
| `mahavishnu/pools/manager.py` (`:429` — *Modify: `spawn_pool`*) | **shared, and missed by round 1** — this is Phase 5's file |
| `mahavishnu/mcp/bootstrap.py` (`:425-426`, `:491` — `_register_eval_tools` + a health-feed block) | **shared, and missed by round 1** — this is Phase 5's registration path |
| `mahavishnu/core/observability.py` (`:406` — `@observe(span_name="eval.run_suite")`) | **shared, and missed by round 1** — this is Phase 4's file |
| Oneiric entry-point registration | shared *mechanism* — the eval plan, the decision plan, and this plan's capability layer all register through it. **One registry, one owner** (§4.2 row 1) |

**Verdict: largely orthogonal.** The eval plan can proceed in parallel;
the shared seams are `BasePool` and the Oneiric entry-point surface,
and neither requires either plan to wait for the other.

#### 4.12.3 Landed work that constrains the ordering

Three live plans **edit files this plan edits** and must land first:

| Plan | Touches | Constraint |
|---|---|---|
| `2026-10-29-agno-failover-and-gateway-repairs` | `core/config.py` | lands before consolidation's `core/config.py` work (Phase 2's `pydantic_ai_enabled`, Phase 3's `AdapterRegistryConfig` removal) |
| `2026-10-29-bifrost-bodai-cache-wiring` (Phase 5) | `workers/registry.py`, `pools/manager.py` | lands before consolidation's `workers/registry.py` and `pools/manager.py` work |
| `2026-10-27-otel-metrics-service` (Phase 3) | `core/observability.py`, `core/config.py` | lands immediately before consolidation Phase 4 — same file, disjoint symbols, but a rebase otherwise |

And five plans have **already shipped** but their frontmatter still says
active — status drift the consolidation should not inherit:
`mcp-substrate-rewire`, `substrate-calltime-rewire`,
`bifrost-cache-eviction-and-threshold`, `bifrost-cli-consolidation`,
`bodai-producer-span-reporting`. The last of those is the satisfied
prerequisite for REQ-C05 — spans must actually leave the process before
mahavishnu can own the span tree.

#### 4.12.4 The rest

The remaining live plans — bifrost cache/CLI work, the MCP and
substrate rewires, the otel-metrics service, producer span reporting,
the oneiric resolver plans, the task-workflow backlink, the Agno
failover repairs, ruff/BLE001 cleanup, the zsh modernization — do not
touch this plan's surfaces. Two need a note:

- **`2026-10-30-task-workflow-backlink.md`** binds tasks to workflows.
  **Round 1's sequencing rule for it was unfounded.** The plan is
  **already implemented** — its §8 "Implementation status (2026-10-30)"
  records Phase 1 **DONE**, Phase 2 **DONE**, Phase 3 **DONE**, Phase 4
  **PARTIAL** — and its *own* Phase 2 already moved step 2 off
  `pool_route_execute` and onto `dispatch_workflow_async`
  (`core/workflow_execution.py:574-632`), which returns a
  `workflow_id`. Its remaining blocker is an **operator publish step**
  (publish session-buddy, re-sync mahavishnu's venv), not this plan.
  It binds through a dedicated typed channel (`tasks_link_workflow`),
  not through the workflow task envelope, and its §3 Non-Goal 4
  explicitly excludes *"Changing the pool router's contract or
  `pool_route_execute`."* **No sequencing constraint.**
- **`2026-10-27-bodai-producer-span-reporting.md`** and
  **`2026-10-27-otel-metrics-service.md`** own spans and metrics. Phase
  4 makes mahavishnu the creator of the *workflow* span; those plans
  own the *producer* spans. Phase 4 must not re-home spans those plans
  own.

### 4.13 The state-ownership rule

This is an **invariant**, not a phase task. It was stated inside Phase
6 in the first draft, which was wrong: it is a prerequisite for Phase
3's lifecycle merge and Phase 7's settle-finality, both of which come
earlier.

> **The engine owns *when* a stage is dispatched. The worker owns *how*
> it settles and reports.** One transition, one owner. Two owners of one
> transition is how "a stale poll can assert a completed" happens —
> which is the exact bug Phase 7 exists to close.

A second rule falls out of it, and the review made it explicit:

> **The router selects *within* a stage; it never selects *across*
> stages.** A stage names its adapter. The router's fallback chain is a
> property of the stage, not of the composition.

Naming that rule dissolves most of the ambiguity in the composition
design, and it is the single sentence that makes the peer-adapter
assumption safe.

### 4.15 The composition executor already exists

**Round 2's largest historical finding.** Phase 6 of the first draft
said the sequence executor *"is the piece that does not exist"* and
*"mahavishnu does not need its own DAG engine."* **Both are false.**
The repo **shipped** a DAG composition executor:

| Module | What it does |
|---|---|
| `mahavishnu/core/conductor.py` (317 lines) | `plan()` (`:109`) builds an `ExecutionDAG` with `DAGEdge`s; `emit_node()` (`:165`) dispatches a node to its engine; `_dispatch_dag_waves()` (`:205`) does level-by-level wave dispatch across edges with `asyncio.gather`; `emit_flow()` (`:260`) compiles the DAG into a Prefect flow using `task.submit(..., wait_for=[upstream_future])` — **dependency-ordered data flow across adapters** |
| `mahavishnu/core/capabilities.py` | `CapabilityEnvelope` (`:153`), `DAGNode`, `DAGEdge`, `ExecutionDAG` |
| `mahavishnu/core/conductor_types.py` | `NodeSpec`, `NodeHandle` |
| `mahavishnu/engines/emit_node_dispatch.py` | five per-engine dispatchers |
| `tests/integration/conductor/` | end-to-end DAG tests |

Two shipped plans built it: `docs/plans/.archive/2026-08-29-worker-registry-capability-refactor.md`
(Stage 3a — *"add an engine composition layer where tasks declare required
capabilities and the system picks engines + composes them into a DAG"*)
and `docs/plans/.archive/2026-10-12-per-engine-emit-node-dispatch.md`
(commit `b25876ab`).

**The gap is real, but it is a one-line stub, not a missing capability.**
`mcp/tools/capability_tools.py:362` `execute_capability` still returns
`status="planned"`; its own docstring says *"Actual dispatch lands in
Phase 4 (per-engine dispatch modules) — until then, `status='planned'`
is returned once the DAG compiles."* The conductor's downstream prompt
synthesis is likewise an explicit placeholder (`core/conductor.py:222-227`).

So Phase 6 must **not** build a second executor. It must **extend the
conductor**: add a worker leg to `emit_node`, flip
`execute_capability`'s `status="planned"` to a real dispatch, and give
the DAG the identity and span-tree the control plane owns. The
conductor's DAG is engine-legs-only today, and the *composition* this
plan wants is exactly "a worker leg in the same DAG" — not a new
executor.

**The same history explains the rest of §4.2.** The enum consolidation
was attempted in `docs/plans/.archive/2026-02-20-status-enum-consolidation.md`
(`status: shipped`) — but only **Phase 1** shipped; the 24→4 base-class
design was abandoned, which is why §4.2 row 8 still counts 14 enums
across 11 modules. The prior control-plane convergence program is
`docs/plans/.archive/2026-05-10-bodai-control-plane-convergence-plan.md`
(`status: shipped`), and its C2 "durable operational state" is the
JSON-file `StateManager` this plan calls "not a store". And
`docs/plans/.archive/2026-05-11-remaining-work-execution-order.md`
records the move this plan now **reverses**: *"TaskRouter.StateManager
now owns the live workflow coordination surface"* — which is why Phase 3
task 0 must state its reason explicitly rather than silently undoing a
shipped consolidation.

## 5. Implementation Phases

### Phase 1: One task envelope

**Goal:** every entry point builds the same **typed** envelope, and
every adapter reads the same keys from it — with the envelope acting as
the trust boundary it is now (§4.11).

**Tasks:**

1. **Define the envelope as a Pydantic model** — `core/task_envelope.py`
   — with **separated namespaces**:
   ```python
   class TaskControlParams(BaseModel):
       """Server-side control fields. NEVER sourced from the caller's bag."""
       model_config = ConfigDict(extra="forbid")
       count: int | None = Field(default=None, ge=1, le=50)  # None -> len(repos)
       timeout: float = Field(default=300, gt=0, le=MAX_TIMEOUT)
       worker_type: str | None = None       # allowlist-checked in TaskEnvelope
       preference_order: list[str] | None = None   # router control

   class TaskParams(BaseModel):
       """Caller-supplied parameters. Control fields are NOT members.
       Unknown keys are PRESERVED: adapters read them by name."""
       model_config = ConfigDict(extra="allow")
       prompt: str = ""
       operation: str = "general"           # free-form; adapters' behaviour selector
       repos: list[str] = Field(default_factory=list)

   class TaskEnvelope(BaseModel):
       routing_type: TaskType                # the ROUTING field, constrained
       id: str
       params: TaskParams = Field(default_factory=TaskParams)
       control: TaskControlParams = Field(default_factory=TaskControlParams)
   ```
   **Round 2 rewrote this sketch.** The first draft had one `type`
   field constrained to `TaskType` and a closed six-field `TaskParams`.
   Both were defects — see §4.11 and §4.2 row 12. The corrections:
   - **`routing_type` and `operation` are separate fields** (§4.11).
     `routing_type` is server-derived, enum-constrained, bounded; it is
     the router's key, the workflow-id suffix and the metric label.
     `operation` is free-form and length-capped; it is the adapter's
     behaviour selector and lands in `task["type"]`. `trigger_workflow`'s
     public `task_type` argument keeps its current free-form meaning, so
     **the request contract does not change**.
   - **`TaskParams` keeps `extra="allow"`**, so the eleven live keys
     the adapters read (`query`, `index_id`, `top_k`, `file_types`,
     `exclude_patterns`, `id`, `focus`, `standards`, `target`, `scope`,
     `param1`) are **preserved**. The first draft's closed model would
     have silently dropped them: llamaindex's query path dies with
     *"Query text not provided in task_params"*
     (`engines/llamaindex_adapter_impl.py:1320`) and agno's
     `code_sweep` brief degrades to the generic default
     (`engines/agno_adapter_impl.py:2019-2060`).
   - **The projection hands adapters a plain `dict`**, not the model:
     agno and llamaindex call `.get()` on `params`
     (`agno_adapter_impl.py:2017`, `llamaindex_adapter_impl.py:1548`),
     and a Pydantic instance has no `.get()`.
   - **Control fields live in their own namespace**, so `params` cannot
     shadow them. `preference_order` in particular is a **router
     control** (`core/task_router.py:849`) and must not sit in the
     caller-supplied bag — a caller passing
     `params={"preference_order": ["worker"]}` would otherwise steer
     the router, which §4.11 explicitly forbids.
   - `worker_type` is validated against an **allowlist of one-shot agent
     CLIs only** — `terminal-claude`, `terminal-qwen`, `terminal-codex`.
     Everything else is rejected at the boundary, so the registry
     membership check at `workers/manager.py:483` becomes a backstop
     rather than the only guard. A `None` substitutes the adapter's own
     default (`"terminal-claude"`, `core/adapters/worker.py:206`) — a
     bare `None` reaches `resolve_worker_type` and dies with
     `ValueError("Unknown worker type: None")`.
   - `count` is bounded 1..50, matching the existing precedent at
     `mcp/tools/worker_tools.py:67`. **Its default stays `len(repos)`**
     (`core/adapters/worker.py:207`) — one worker per repo — and is
     resolved at dispatch time, because the envelope cannot know
     `repos` when it is built.
   - `timeout` is a bounded finite `float` — `"inf"` is rejected.
   - `prompt` is length-capped, following the pattern in
     `core/task_models.py`. The cap must be set from the pydantic-ai
     precedent (`MAX_PROMPT_LENGTH = 100000`,
     `adapters/ai/pydantic_ai_adapter.py:55`) rather than invented, and
     must not truncate the repo contents the pool lane legitimately
     carries.

   **The envelope must also carry the keys adapters read today**:
   `workflow_name` (`engines/hatchet_adapter_impl.py:232`), `single_repo`
   (injected by `core/workflow_execution.py:198`), and — **missed by the
   first draft** — `system_prompt`, `output_type` and `tools`
   (`adapters/ai/pydantic_ai_adapter.py:415`, `:972-975`). `output_type`
   is a `type[BaseModel]`, so it is **adapter-owned** and must never be a
   caller-supplied envelope field.

2. **Change `trigger_workflow` (`mcp/server_core.py:477`) to build the
   envelope.** The caller's dict goes into `params` and is validated as
   `TaskParams` — it is **not** flattened into the envelope's top level.
   The first draft of this plan flattened it, which would have put
   caller-controlled values directly into the worker's control namespace
   (§4.11).
   - There are **four** envelope builders, not three (§4.4): the MCP
     tool (`mcp/server_core.py:477`), the CLI (`_main_cli.py:373`,
     `:638`), the router (`core/task_router.py:842`), and **the task →
     workflow handoff** (`mcp/server_core.py:1554-1562`,
     `_dispatch_task_workflow`). The handoff is the only path from a
     session-buddy task to a running workflow and the only writer of a
     cross-repo record; its `type` is hard-coded `"ai_task"`, so its id
     shape does not change, but it must still build the envelope.
     There are additionally **three workflow-record creation points**:
     `initialize_workflow_state` (`core/workflow_execution.py:36`),
     `trigger_workflow`'s timeout branch (`mcp/server_core.py:524`, id
     `wf_timeout_<hex>_<type>`), and its exception branch (`:556`, id
     `wf_error_<hex>_<type>`). All must build the envelope.
   - **The handoff's id shape is pinned**: it must remain
     `^wf_[0-9a-f]{8}_ai_task$`, because that value is written into
     session-buddy's `Task.workflow_id`.
   - `adapter` **stays a `str`** — a static enum would advertise
     adapters the running server may not have registered (`hatchet` is
     off by default; `pydantic_ai` is never registered). The docstring
     is updated to name the full `AdapterType` set and point at
     `list_adapters` for runtime truth, and a pre-flight check returns
     a structured error naming the runtime-available adapters rather
     than letting `prepare_execution` raise deep in the call.
   - Bump `tool_versions.py` `"trigger_workflow"` from `1.1.0` to
     `1.2.0` — **MINOR, because the request contract does not
     change.** Round 2 reclassified this twice. The first draft called
     it MINOR on the grounds that it was *"additive new top-level
     keys"*, which was factually wrong: the envelope's key set is
     identical to today's `task` dict, and the keys the plan called
     *new* (`workflow_name`, `single_repo`, `preference_order`) are
     internal — the MCP caller never sees them. What changed was the
     **semantics** of `params` and `task_type`, which under
     `mcp/tool_versions.py:8-10` ("MAJOR: Breaking change (removed
     field, changed type, different semantics)") is MAJOR — *if the
     first draft's sketch is implemented literally*. With the corrected
     design above (two task-type fields, `extra="allow"` passthrough,
     the caller's `task_type` keeping its meaning) the request is
     unchanged and MINOR is correct.
     **The classification therefore depends on the design, which is why
     this task must state the design.**
   - **The repo's own MAJOR-bump machinery is not optional.** Round 2
     found the precedent the plan never consulted:
     `docs/adr/015-worktree-and-cache-storage-v4.md:487-490` — bump to
     2.0.0, add a `DEPRECATED_TOOLS` entry (v1 callable for 2 minor
     releases), add a translation shim, and update `discover_tools()` to
     return `deprecated: true` + `sunset_version`. Plus
     `docs/reports/deprecation-migration.md:12-13`: *"No tools will be
     removed without a migration path."* **The plan's first draft
     contained the word "deprecat" zero times.** Phase 4 task 6 is
     where that machinery has to appear.

3. **Fix `_main_cli.py:373` and `:638`:** `{"task": task_type, ...}` →
   `{"type": task_type, ...}`. Because
   `initialize_workflow_state` reads `task.get('type', 'default')`
   (`core/workflow_execution.py:42`), both CLI paths currently mint ids
   as `wf_<hex>_default` and hand the adapter a dict with no `"type"`
   key at all — which Agno reads.

4. **Change `core/task_router.py:842` (`execution_context`) to build the
   same envelope.** Note the `TaskType(task.get("type", "ai_task"))`
   coercion at `core/workflow_execution.py:644` is on a **different
   lane** — reached from `agents/mahavishnu_agent.py:289` and
   `execute_workflow_with_routing` (`:699`), not from the CLI, which
   passes an explicit adapter to `execute_workflow_parallel`.

5. **Adapter-side coercion at one seam.** The envelope stays
   single-valued; a single `TaskEnvelope.for_adapter(adapter_type)`
   projection hands each adapter the shape it reads, so no adapter keeps
   a second source of truth. The worker adapter
   (`core/adapters/worker.py:206-211`) reads through that projection.

6. **Fix `mahavishnu/workers/openhands.py` for the current OpenHands
   SDK** (REQ-C14): `StartConversationRequest` with `initial_message`,
   the `/sockets/events/{conversation_id}` WebSocket, the `kind`
   discriminator, and the terminal set `finished | error | stuck`. This
   must land **before** any change to the worker registries —
   `openhands` is a legacy-dict-only worker type, so removing the legacy
   dict first would strand this work (§4.12).

**Exit criteria:** the same typed envelope reaches any adapter from the
MCP tool, the CLI, or the router; the CLI sweep commands mint
correctly-named workflow ids; a caller-supplied `params` cannot shadow
`type` or `id`, cannot select an unlisted `worker_type`, and cannot
exceed 50 workers or a finite timeout; the openhands worker completes a
real conversation against the current SDK.

#### Integration Contract

- **Triggered from:** `mcp__mahavishnu__trigger_workflow`
  (`mcp/server_core.py:410`), `mahavishnu workflow sweep` /
  `quality-check` (`_main_cli.py:373`, `:638`), and
  `core/task_router.py:831` (`execute_with_fallback`).
- **Returns to / updates:** the `task` dict stored in
  `app.workflow_state_manager.create(...)`; the `workflow_id` minted by
  `initialize_workflow_state` (`core/workflow_execution.py:36`) and by
  `trigger_workflow`'s two error branches (`mcp/server_core.py:524`,
  `:556`).
- **Demonstrable by:** `pytest tests/unit/core/test_task_envelope.py` —
  the MCP tool, the CLI, and the router build identical envelopes, and
  a hostile `params` (`{"type": ..., "worker_type": "terminal-shell",
  "count": 100000, "timeout": "inf"}`) is rejected at the boundary;
  and `mahavishnu workflow sweep --tag <tag>` mints
  `wf_<hex>_<task_type>` rather than `wf_<hex>_default`.
- **Rollback signal:** a workflow id ending in `_default` for a CLI sweep
  means the envelope change did not reach `_main_cli.py`; a dispatch
  reaching the worker adapter with an unlisted `worker_type` means the
  allowlist was not applied; the openhands worker's conversation never
  reaching a terminal status means the SDK migration is incomplete.
- **Observability added:** the `task_type` recorded on the
  `mahavishnu.workflows.total` metric (`core/workflow_execution.py:382`)
  becomes meaningful for CLI-originated workflows for the first time,
  and it is now a validated enum member rather than a free-form string.
- **Fulfills:** REQ-C02, REQ-C14.

### Phase 2: Reachability — every adapter selectable

**Goal:** no adapter is shipped dark, and none is shipped *broken*.

**Tasks:**

0. **Unify the duplicated `AdapterType` / `TaskType` enums FIRST**
   (§4.2 row 9). `core/routing.py:25`, `core/workflow_execution.py:24`
   and `core/cost_optimizer.py:31` import the **3-member**
   `metrics_schema.AdapterType`, so the router literally cannot name
   `worker` today — the first draft's Phase 2 instruction was an
   `AttributeError` as written. Make
   `core/adapters/base.py:AdapterType` (6 members) the single enum and
   re-point the three importers at it; `metrics_schema` imports rather
   than redefines. The same for `TaskType`:
   `core/metrics_schema.py:42` (6 members) wins over
   `core/task_router.py:82` (5 members, no `CRITICAL_TASK`).
   `metrics_schema`'s Pydantic models (`ExecutionRecord:64`,
   `AdapterStats:102`, `TaskTypeStats:150`, `CostTracking:172`,
   `RoutingDecision:202`, `ABTest:245`) are typed against the old enum
   and must be re-pointed in the same change.

1. **Register `pydantic_ai` before chaining it.** `PydanticAIAdapter`
   exists (`mahavishnu/adapters/ai/pydantic_ai_adapter.py`) and appears
   in `_ENGINE_LOCATIONS` (`engines/__init__.py:109`), so the
   *capability* layer advertises an adapter the *dispatch* layer cannot
   run. Add a `pydantic_ai` branch to `bootstrap._import_adapter_class`
   (`core/bootstrap.py:356`) and an entry to
   `_collect_adapter_classes` (`:384`), gated on a new
   `adapters.pydantic_ai_enabled` flag, tolerating the optional `ai`
   PEP-735 group being absent. Reconcile the existing
   `integrations.pydantic_ai_enabled` (`core/config.py:2603`) with the
   new flag — **one of them should die. Round 2 named the survivor and
   the alias**: `integrations.pydantic_ai_enabled` is **live** today —
   `cli/demo_cli.py:1280` reads it as the `demo pydantic_ai`
   precondition, and `settings/local.yaml:81` sets it `true` on this
   host. So `adapters.pydantic_ai_enabled` becomes the survivor, and
   `integrations.pydantic_ai_enabled` stays as a **one-release alias**
   the loader resolves. Deleting it outright would silently drop the
   operator's setting (the loader drops unknown sub-keys before
   validation, `core/config.py:3560-3563`) and flip `demo pydantic_ai`
   to "skipped" with **no error anywhere**.
   - **`_instantiate_adapters` must be changed too, or the server will
     not boot.** `core/bootstrap.py:403-407` passes `app.config` to
     every adapter except `hatchet`; `PydanticAIAdapter.__init__` wants
     a `PydanticAISettings`
     (`adapters/ai/pydantic_ai_adapter.py:286-297`, model at `:166`), and
     `core/bootstrap.py:414-424` re-raises the resulting `AttributeError`
     as `ConfigurationError`. `pydantic_ai` must get its own settings
     object, exactly as `hatchet` does.

2. **Add `AdapterType.WORKER` and `AdapterType.HATCHET` to the routing
   chains — in BOTH tables, and the live one is `core/routing.py`.**
   **Round 2 corrected the file.** The first draft said to edit
   `core/task_router.py` and *"not `core/routing.py`"*. That table is
   **dead in production**:
   - `core/task_router.py` has **no chain-building method at all**.
     Its five public methods all live in `core/routing.py`
     (`classify_intent` `:190`, `generate_fallback_chain` `:241`,
     `get_adapter_scores` `:291`, `select_adapter` `:404`,
     `get_routing_info` `:467`). Line `:729` — which the first draft's
     Integration Contract cited — is `def _default_preference_order`.
   - The **live** router is `core/routing.py`'s:
     `core/workflow_execution.py:27` imports it, `:647` calls
     `generate_fallback_chain`, `:707` calls `select_adapter`.
   - `core/task_router.py`'s `TASK_PREFERENCE_ORDERS` *is* consulted by
     its own `route()` (`:793`) and `execute_with_fallback()` (`:859`),
     but both resolve the adapter through
     `self.adapter_registry.get_adapter(...)`, and `AdapterManager`'s
     `register_adapter` is called **only from test modules** — in
     production that registry is always empty, so the loop skips every
     adapter.
   ⇒ Adding WORKER to `core/task_router.py` alone has **zero**
   production effect, and **REQ-C01 would be false the day Phase 2
   lands**. Phase 2 must therefore edit **`core/routing.py`'s
   `DEFAULT_FALLBACK_CHAINS` (`:138-169`)** — which §6 already lists —
   *and* `core/task_router.py`'s preference orders, so Phase 3's fold
   carries the change across. The fold's *direction* is unchanged
   (§4.12.1): `core/routing.py` folds **into** `core/task_router.py`.
   The worker needs a **new `TaskType.CLI_TASK`** (or equivalent). It must **not** be put ahead
   of a model-driven engine for `AI_TASK`: the worker's contract is a
   *command plus a prompt* (`core/adapters/worker.py:206-211`), not a
   model-shaped call, so routing an LLM-shaped task to it removes the
   model from the loop with no signal to the caller — the adapter
   returns `{"status": "completed", ...}` and the loss is invisible.
   That is §4.8 item 4 applied to the routing layer: *a success
   subtype with a missing structured payload is a failure*. If the
   worker is made eligible for `AI_TASK` at all, it goes **after** the
   model engines, and the reachability test asserts **ordering**, not
   just membership.

3. **Update `trigger_workflow`'s docstring** to name every adapter
   `prepare_execution` can resolve, pointing at `list_adapters` for the
   runtime truth (`app.adapters` is config-driven; `hatchet` is opt-in
   via `adapters.hatchet_enabled`).

4. **Add a regression test** asserting that every `AdapterType` member
   that has a registration path is reachable from a chain **and** is in
   `app.adapters` when its enable flag is on. A chain member that is not
   registered is a defect, not a pass — the first draft's exit criterion
   ("every `AdapterType` member is reachable") would have been satisfied
   by a member that could never execute.

5. **Reconcile the four adapter listings** (§4.2 row 1): `app.adapters`
   is the dispatch registry; the capability layer's listings stay (they
   have a different job); `AdapterManager` is deleted in Phase 3; and
   `_ENGINE_LOCATIONS` must not advertise an adapter the dispatch layer
   cannot run.

6. **Extend the `adapters` health feed.**
   `core/health_aggregator.py:153-175` computes
   `any_enabled = prefect_enabled or llamaindex_enabled or agno_enabled`
   and reports `entities_count` as a boolean `0/1`.
   **Round 2 corrected the premise.** The probe builds a **bare**
   `MahavishnuSettings()` (`:162`), and a bare settings has all three
   engine flags at their **defaults** — verified at runtime:
   `prefect_enabled=True, llamaindex_enabled=True, agno_enabled=True`
   (and `hatchet_enabled=False`, against `get_settings()`'s `True` on
   this host). So `any_enabled` is `True` on essentially every host and
   the feed **never** reports degraded. The first draft's claim — *"a
   worker-only deployment would get `errors_total=1` → `/health` returns
   503"* — **cannot occur through the YAML**, and its rollback signal
   (*"/health returning 503 on a worker-only deployment"*) **can never
   fire**. The fix must therefore start with `get_settings()` (or
   `app.config`), not with the flags: read the *resolved* settings, then
   include the worker and hatchet flags, and make `entities_count` the
   **count** of enabled adapters. Until the probe reads resolved
   settings, its rollback signal is unobservable and must be replaced
   with one that is not.

7. **Separate *registration* from *routability*, and give the operator
   a kill-switch.** Round 2 found that the plan conflated two things an
   operator opts into separately.
   - **Registration** is what the operator's flags control.
     `core/bootstrap.py:388-389` builds `app.adapters` from
     `adapters.hatchet_enabled` and `workers.enabled`.
   - **Routability** is what changes production traffic — and the
     chains are **static ClassVars** (`core/task_router.py:609-641`,
     `core/routing.py:138-169`). Nothing filters a chain by what is
     registered at runtime.
   ⇒ On a fleet that has not enabled Hatchet, every WORKFLOW-type
   routing attempt tries Hatchet, `prepare_execution` raises
   `ValidationError("Adapter not found: hatchet")`
   (`core/workflow_execution.py:103-111`), the fallback loop swallows it
   (`:654-672`), and the workflow's `errors` list gains a **permanent
   phantom entry** that `trigger_workflow` returns verbatim. On **this**
   host — where `settings/local.yaml:71` already sets
   `adapters.hatchet_enabled: true` and `:81` sets
   `integrations.pydantic_ai_enabled: true` — Phase 2 makes both
   **routable for real production traffic with no configuration change**.
   The operator opted into an *adapter*; they did not opt into a new
   *production substrate*.
   **The fix:** build the chain from `app.adapters` at runtime
   (filtering unregistered members), and add an explicit routability
   flag so an operator can withdraw a substrate without unregistering
   it. Phase 2 task 4's test must be rewritten accordingly — it
   currently asserts that *an unregistered chain member is a defect*,
   which is the opposite of what the runtime needs.
   **The kill-switch problem:** `workers.enabled: false` is the only
   knob an operator has, and it is **destructive** — it removes the
   worker from `app.adapters`, which makes `app._worker_manager` `None`
   (`core/bootstrap.py:434-437`), which makes `mcp/bootstrap.py` skip
   **`register_worker_tools`** — **nine worker MCP tools silently
   vanish behind one `logger.warning`**. There must be a way to make the
   worker unroutable without removing nine tools from the server.

**Exit criteria:** every registered adapter is selectable and named in
the MCP tool's documentation; no chain member lacks a registration path;
`/health` does not report degraded on a worker-only deployment;
**an operator can withdraw a substrate from the routing chain without
unregistering it and without losing MCP tools.**

#### Integration Contract

- **Triggered from:** `TaskRouter.generate_fallback_chain`
  (`core/task_router.py:729`) and `mcp__mahavishnu__trigger_workflow`.
- **Returns to / updates:** `app.adapters` selection in
  `prepare_execution` (`core/workflow_execution.py:103`) and the
  `adapter_used` field of the fallback result.
- **Demonstrable by:** `pytest tests/unit/core/test_adapter_reachability.py`
  — every registered `AdapterType` appears in ≥1 chain and is in
  `app.adapters` under its enable flag;
  `pytest tests/integration/test_trigger_workflow_e2e.py` — a
  non-empty, adapter-resolving result for each newly reachable adapter
  (the wiring discipline requires an e2e per registered tool).
- **Rollback signal:** a new `AdapterType` member appearing in
  `core/adapters/base.py` without a chain entry fails the reachability
  test; `/health` returning 503 on a worker-only deployment means the
  health feed was not extended.
- **Observability added:** the `adapter` label on
  `mahavishnu.workflows.total` and `mahavishnu.workflow.duration_seconds`
  (`core/workflow_execution.py:382-391`) gains `worker` and `hatchet`
  series, which is how a dark adapter becomes visible in production.
- **Fulfills:** REQ-C01.

### Phase 3: Collapse the duplications

**Goal:** one of each.

**Tasks:**

0. **Relocate `StateManager` before touching `task_router.py`.**
   `app.workflow_state_manager` **is** a `task_router.StateManager`
   instance (`core/bootstrap.py:620,633`), and that class has ~25
   production consumers across `core/workflow_execution.py`,
   `core/monitoring.py`, `core/resilience.py`,
   `core/backup_recovery.py`, `core/repository_surface.py`,
   `core/production_readiness.py` and `shell/shell_commands.py` — plus
   the MCP workflow surface (`trigger_workflow`, `get_workflow_status`,
   `list_workflows`, `cancel_workflow`) that Phase 5 depends on. Move
   the class to `core/workflow/state.py` and update the bootstrap
   import. **Deleting or reshaping `core/task_router.py` before this
   lands breaks the entire MCP workflow surface.**

1. **Adapter registry (§4.2 row 1):** delete
   `core/task_router.py`'s `AdapterManager`; point the surviving router
   at `app.adapters`.

2. **Router (§4.2 row 2) — direction flipped.** `core/task_router.py`'s
   router **survives** and becomes the Oneiric-bridged router, per the
   hard sequencing rule in
   `docs/decisions/2026-10-14-decision-adapter-category.md`. Fold
   `core/routing.py`'s fallback-chain logic **into** it. The first
   draft had this backwards and would have deleted the file another
   plan is actively migrating. `core/routing.py`'s `TaskRouter` also
   has live callers — `agents/mahavishnu_agent.py:190`,
   `webhooks/router.py:188,273` — so the fold must preserve them.
   `core/routing.py`'s `TaskRouter` has **no `route()` method** (only
   `classify_intent` / `generate_fallback_chain` / `get_adapter_scores`
   / `select_adapter` / `get_routing_info`), so the fold is an
   *addition* of five public methods, not a move — and the four other
   production importers of `core/task_router.py` must be repointed.
   **Round 2 added what the first draft left unsaid**, because the fold
   has **name collisions** and §7's own acceptance check
   (`grep -rn "class TaskRouter" mahavishnu/` → *"one production
   class"*) is otherwise unsatisfiable:
   - `TaskRouter` — **both** classes define that name.
   - `TaskType` — `core/routing.py` *imports* it (from
     `core.metrics_schema`); `core/task_router.py` *defines* it
     (5 members, `:82`). A textual merge shadows one with the other.
   - `AdapterType` — imported from two modules (resolved by Phase 2
     task 0).
   - `RoutingStrategy` — imported by `core/app.py:143`,
     `core/workflow_execution.py:27`, `agents/mahavishnu_agent.py:40`.
   - `logger` — both modules define it.
   - Two singletons — `get_task_router()` / `reset_task_router()`.
   **The task must therefore state:** (a) `core/routing.py` is
   **deleted** — no re-export shim (§3 non-goal 10) — with
   `RoutingStrategy` and the five methods moved into
   `core/task_router.py`, and `core/app.py` /
   `core/workflow_execution.py` / `agents/mahavishnu_agent.py` /
   `webhooks/router.py` repointed (all four go in §6); (b) the merged
   `__init__` must accept **both** signatures — routing's
   `(fallback_chains=None, default_strategy=RoutingStrategy.BALANCED)`
   (`:171-183`) and task_router's `(adapter_registry=None,
   state_manager=None, router_mode=…, metrics=None)` (`:643-656`) — and
   `self.default_strategy` must survive, because `select_adapter` reads
   it at `:430`; (c) **which chain table the merged
   `generate_fallback_chain` reads**, because they disagree —
   `core/routing.py:164-169` gives
   `INTERACTIVE_TASK = [AGNO, LLAMAINDEX, PREFECT]` and
   `core/task_router.py:630-634` gives `[AGNO, PREFECT, LLAMAINDEX]`;
   and (d) that `INTENT_PATTERNS` (`core/routing.py:47`) is re-typed
   to the winning `TaskType`.
   `core/task_requirements.py:26` (`TaskType`, live, feeding
   `TASK_CAPABILITY_REQUIREMENTS`), `core/bootstrap.py:620`,
   `_main_cli.py:469` (a dead helper whose import is pinned by
   `tests/unit/test_workflow_cli.py:100`), and
   `core/unified_orchestrator.py:21`. `tests/fixtures/chaos_harness.py:14`
   imports `AdapterManager`, `StateManager` and `TaskRouter` together
   and must be repointed with them.

3. **Orchestration entry point (§4.2 row 3) — port, do not delete.**
   Extract `UnifiedOrchestrator`'s multi-task loop into
   `core/workflow_execution.py` as `execute_workflow_batch(tasks:
   list[TaskEnvelope])` — one fallback chain per task, one shared
   workflow id — reusing `app.adapters` instead of the orphan
   `AdapterManager`. Port `cancel_workflow` too — but **correct the
   justification**. `workflow_execution` has no cancel path, but the
   first draft's reason was wrong: `can_cancel_workflows=True`
   (`core/adapters/worker.py:137`) is a **capability flag, not an
   implementation**. **No adapter implements `cancel_workflow`** —
   `grep -rn "def cancel_workflow" mahavishnu/` returns exactly two
   hits, `core/unified_orchestrator.py:194` and the MCP tool
   `mcp/server_core.py:709`, and the former's loop
   (`if adapter and hasattr(adapter, "cancel_workflow")`) is always
   False. The MCP tool only flips the state record to `"cancelled"`; it
   does not stop running work. So the port must either (a) add a real
   `OrchestratorAdapter.cancel_workflow` — an ABI addition this plan
   does not price — or (b) record cancellation as **not** a preserved
   capability. The plan must say which.
   **Also:** `AdapterManager` is the router's *only* adapter lookup
   (`TaskRouter.route` `:793`, `execute_with_fallback` `:859`), and
   **three of its four construction sites have no `app`**
   (`agents/mahavishnu_agent.py:190`, `webhooks/router.py:188,273`,
   `core/unified_orchestrator.py:56`) — so "point the surviving router
   at `app.adapters`" needs a mechanism (a provider, or a lazily
   supplied adapter mapping). And `get_adapter_health` does **not** come
   free: `UnifiedOrchestrator.get_adapter_health` (`:236-258`) reads the
   orphan registry, and `TaskRouter.get_health` (`:942-953`) reads
   `len(self.adapter_registry.adapters)` — **0** in production.
   **And:** `execute_workflow_batch` must mint **one** id for N tasks
   (the source's behaviour: `core/unified_orchestrator.py:81-93` mints
   one id, one state, and records per-task results under it), or say
   why not — `initialize_workflow_state` mints a new id per call, so a
   batch that calls it N times produces N records and N "started"
   increments.

4. **Worker registry (§4.2 row 4) — winner reversed.** Do **not**
   retire the legacy `WORKER_REGISTRY`. It is the **dispatch** source
   of truth — 43 entries against the settings registry's 16 — and the 27
   legacy-only types include `shepherd` (the pool's default worker
   type) and `openhands`. `MahavishnuSettings()` bare does **not** read
   YAML (`get_settings()` → 16 entries; bare → 0), so the legacy dict
   is the only unconditionally-populated registry: a worker must still
   resolve with no settings object in hand. The two are also different
   schemas — `WorkerEntry` has no `permission_mode`, `category`,
   `endpoint`, `mcp_server` or `error_markers`, and has `provides`,
   which `WorkerConfig` cannot express. The action here is to **record
   the split** (dispatch vs capability-metadata) and fix the
   `command_argv` shape inconsistency at `registry.py:1061` (a
   one-element list holding the whole shell string, against the YAML's
   three-element `["sh", "-lc", "<script>"]`). A single source is a
   larger project, not a Phase-3 task.

5. **Worker substrate + lifecycle vocabulary (§4.2 rows 5, 8).** Put
   **one execution lifecycle** in `core/status.py` — which is already
   the declared home ("Consolidated status enums for Mahavishnu… Issue:
   MHV-008") — carrying the union of `WorkflowStatus`, `WorkerStatus`,
   `ExecutionStatus`, `ProgressState` and `RunStatus`, **plus**
   `TIMEOUT`, `CANCELLED`, `INPUT_REQUIRED` and `BLOCKED` (the
   worker-side members §4.8 item 3 requires and the engine side lacks).
   - **Terminal states must be absorbing.** The repo already has the
     pattern: `mahavishnu/settle/state_machine.py:79` defines
     `_TERMINAL_STATES` as a frozenset with no outbound edges. Adopt it
     — `WorkerLifecycleState`'s table allows `COMPLETED → READY →
     RUNNING`, which would silently defeat Phase 7's "settled is final".
   - `WorkerLifecycleState` keeps its **instance** lifecycle and its
     transition table intact; `DurableWorkerManager._transition`
     **raises** `ValueError` on an illegal edge
     (`workers/contract/manager.py:118`), so widening that enum would
     silently widen the legal graph.
   - `PoolStatus` (a resource), `PlanStatus` (a document),
     `WorkerCapabilityState` (a probe) and `SettleState` (a merge run)
     are **not** execution lifecycles and stay separate.
   - **Round 2 added the value the first draft missed and two it got
     wrong.** The store writes **`partial`** today —
     `core/workflow_execution.py:346`:
     `"completed" if not errors else ("partial" if successful_results
     else "failed")` — and `partial` is in **none** of the five source
     enums. It must be in the superset.
     Worse, a naive *union* would also pull in `success`
     (`ExecutionStatus`) and `failure` alongside `completed` and
     `failed` (`WorkerStatus`) — and the store filters on **exact
     string equality** (`core/task_router.py:315-326`). A record
     written as `"completed"` would then be invisible to a filter for
     `"success"`. The superset must therefore **pin the four
     surviving store strings** (`running`, `pending`, `completed`,
     `failed`) as the *store's* vocabulary, and treat `success` /
     `failure` / `partial` as **outcome-trail** vocabulary that Phase 4
     task 4's mapping table owns.
   - The union also changes the *type* of `list_workflows`'s `status`
     parameter — today `core/status.py:118-129` `WorkflowStatus`, which
     **eight live modules import** (`core/task_router.py:54`,
     `core/monitoring.py:21` and `:506`, `core/repository_surface.py:238`,
     `core/resilience.py:17`, `shell/adapter.py:9`,
     `shell/shell_commands.py:8`, `shell/formatters.py:17`,
     `mcp/server_core.py:653`) — and **none of them is in §6**. The
     deprecated re-export module they import from
     (`core/workflow_state.py:5-8`, documented as *"DEPRECATED … No live
     code path should import this module"*) is **deleted**, and the
     eight importers repointed at `core/status.py`.

6. **Workflow state store (§4.2 row 6).** One store per concern, and a
   **store interface** rather than a file swap. `StateManager._persist`
   (`core/task_router.py:217`) rewrites the **entire** JSON file on
   every mutation, **unlocked**, under a **CWD-relative** path
   (`_DEFAULT_STATE_DIR = Path("data/workflow_state")`, `:189`) — so a
   server started from a different directory writes a different
   `workflows.json`, and two concurrent **processes** can lose each
   other's records (§4.5).
   **Round 2 corrected two claims in the first draft.**
   - **`core/state_backends/mcp.py` is not a durable backend to build
     on.** Its own docstring says the substrate it speaks to is
     *"backed by a process-local thread-safe dict"* and that *"All
     writes are fire-and-forget"* — and it is **mahavishnu's own MCP
     server** (`core/bootstrap.py:892-915`). It is an **HTTP self-call
     into the same in-memory dict**: no durability, plus an event-loop
     HTTP hop on the path §2.1 is trying to make faster.
   - **The durable store the repo already has is `core/event_store.py:317`**
     (`EventStore`, PostgreSQL-backed — `core/database.py:28`
     `import asyncpg`, `:194` `asyncpg.create_pool`), and the pool
     lane's own idempotency path already uses it:
     `core/idempotency.py:81` `class IdempotencyStore: def __init__(self, event_store: EventStore)`.
     So the durability work is **not blocked on another plan**.
   - **The substrate has no backend seam to put anything behind.**
     `core/substrate.py:35` imports the `kv_store` **module-level
     singleton** directly, and `put` (`:67`) is **synchronous by
     contract** (`:70-73`) — *"a sync write cannot be an HTTP
     round-trip without blocking the event loop."* Its caller
     `record_workflow_outcome` is likewise sync
     (`core/workflow/outcome_writer.py:54`), called synchronously from
     the async `finalize_workflow_execution`
     (`core/workflow_execution.py:410`). A network-backed store therefore
     **cannot** go behind that facade without changing the contract:
     either `record_workflow_outcome` becomes async and is awaited, or
     the facade grows a background-flush queue with a durability
     acknowledgement. **The task must specify which.**
   **The `WorkflowStore` protocol must be specified, not just named.**
   The operations are: `create`, `update`, `get`, `list_workflows`,
   `delete`, `update_progress`, `get_completed_count`, `add_result`,
   `add_error`. Two live semantic ambiguities have to be settled:
   - **`update` is a merge in one caller and a whole-record replace in
     another** — `core/workflow_execution.py:349-354` passes four
     fields; `core/backup_recovery.py:311` passes `**workflow`, the
     entire backed-up record. `core/task_router.py:306` does
     `record.update(updates)`. The protocol must say which it is; if it
     is a merge, the restore path must be rewritten, because it relies
     on replace semantics to restore `results` / `errors` /
     `adapter_states`.
   - **`list_workflows` applies `limit` before the caller counts.**
     `core/task_router.py:320-326` returns `workflows[:limit]`, and
     `core/monitoring.py:1012-1020` calls it once per status with
     **`limit=1`** and then does `counts[status.value] = len(workflows)`
     — so **every workflow count in the health feed is 0 or 1**. A
     protocol that freezes that signature freezes the bug.
   **Do NOT move the outcome writer off the substrate.** The
   `2026-10-31-substrate-calltime-rewire` plan deliberately rebound
   `core/workflow/outcome_writer.py` to the substrate facade
   (`core/substrate.py`), so a sibling component reading
   `workflow-results/{workflow_id}/` through the `mahavishnu_kv_*` tools
   sees the record — a cross-component contract, not a private store.
   The gap is that the substrate's current backend is process-local
   (`core/kv_store.py:87`), so outcomes do not survive a restart.

6b. **Prune the store; do not migrate it.** **Round 2 added this task,
   and it is the cheapest fix in the plan.** The store holds **469**
   records (5.2 MB, ten of them ~390 KB each), of which **77** are
   stuck `running` and **56** carry the `_default` suffix from the CLI
   key bug — plus **six** leaked test-fixture ids
   (`test_integration_workflow`, `backup_integration_test`, …) sitting
   in the *production* file. Because this plan is **forward-only**
   (§3 non-goal 10), those records need no migration: **delete them.**
   That takes the file from 5.2 MB to near-empty and removes the store's
   worst pathology — the 10 × 390 KB blobs that make every whole-file
   rewrite expensive. The task must also:
   - **Prune before the store-hardening lands**, because the pruning
     write is itself a full-file rewrite.
   - **Repoint the reaper**, or the 77 stay invisible forever:
     `_check_stuck_workflows` (`core/resilience.py:969`) filters on
     `status=WorkflowStatus.RUNNING` (`:974`) and
     `core/monitoring.py:513` does too, and Phase 3 task 5 changes the
     enum those filters use.
   - **Batch the reaper.** If anyone calls the `heal_workflows` MCP tool
     today it performs up to 75 sequential `update()` calls, each a
     full-file rewrite — **~390 MB of writes**. A batched reaper (one
     persist for N records) is a precondition for enabling it.
   - **Pin the store's canonical path.** The CWD-relative
     `data/workflow_state` is the ground of
     `docs/decisions/2026-08-28-cross-repo-fanout-cwd-isolation.md`
     (CWD inheritance is a recorded failure mode), and the repo has a
     canonical XDG path convention (`core/xdg_paths.py`). The store
     must move to it — this is the only place the plan's own
     "CWD-relative" finding gets fixed rather than merely noted.

7. **Remove the `AdapterRegistryConfig` ghost (§4.2 row 10):** delete
   `core/config.py:2000-2051`, the `adapter_registry` field (`:3337`),
   the `adapter_registry:` YAML block, and the untyped `feature_flags:`
   YAML block. Fix `tests/unit/test_workflow_cli.py:102`, which asserts
   an import of a module that does not exist.

8. **Worker wrapper (§4.2 row 7).** **Do not make the adapter own a
   pool.** Two reasons, both structural:
   - Pool selection, scaling, per-`CallerKind` quota, fitness-aware
     routing and the queueing model all live in **`PoolManager`, above
     the pool** (`pools/manager.py:170`, `:424-425`). A pool constructed
     *inside* the adapter is **invisible to `PoolManager`** — so the
     remedy the first draft proposed would *lose* the cross-pool layer
     rather than recover it.
   - `core/bootstrap.py:434-437` derives `app._worker_manager` from
     `worker_adapter.worker_manager`, and `mcp/bootstrap.py:451` skips
     `register_worker_tools` when that is `None`. If the adapter stops
     exposing a `worker_manager`, **nine worker MCP tools silently
     vanish from the server** behind a `logger.warning`, and the
     `workers_running` gauge (`core/app.py:913`) goes to zero.

   Instead: the adapter keeps wrapping `WorkerManager` (the leaf
   substrate it already is); **pool selection and scaling are recovered
   at the lane level** — a workflow stage dispatches through
   `PoolManager.route_task`; and **workflow identity** comes from Phase
   5, minted in the orchestration layer and passed down as an opaque
   correlation id. This preserves the "pool types wrap substrates"
   invariant (`pools/mahavishnu_pool.py:5-12`,
   `docs/pools/POOL_ARCHITECTURE.md:65-91`) and keeps the nine worker
   tools registered.

9. **Define the execution envelope's *type* here**; Phase 4 migrates
   the adapters to it. This preserves the dependency direction: Phase 3
   owns the vocabulary, Phase 4 owns the migration.

**Exit criteria:** `app.adapters` is the only dispatch registry; one
production router; `StateManager` has moved; `UnifiedOrchestrator`'s
capabilities are preserved in `workflow_execution`; the legacy worker
registry still resolves all 43 types; one execution lifecycle with
absorbing terminals; workflow outcomes survive a process restart.

#### Integration Contract

- **Triggered from:** `mahavishnu/core/bootstrap.py:427`
  (`initialize_adapters`) for the registry; `app.execute_workflow_parallel`
  for the state store.
- **Returns to / updates:** `app.adapters`
  (`core/app.py:254`), `app.workflow_state_manager`, and
  `record_workflow_outcome`'s destination (`core/workflow/outcome_writer.py:54`).
- **Demonstrable by:** `pytest tests/unit/core/test_registry_uniqueness.py`
  — asserts on **imports**, not class names: no module imports
  `AdapterType` from more than one of {`core.adapters.base`,
  `core.metrics_schema`}, exactly one production `TaskRouter`, and one
  workflow state store. `python scripts/audit_orphans.py` reports no
  new orphans.
- **Rollback signal:** `audit_orphans.py` reporting a symbol with zero
  callers after the collapse means a deletion went too far; a workflow
  outcome missing after a restart means the store move is incomplete;
  `get_workflow_status` returning `{"status": "error"}` for every id
  means `StateManager` did not move before `task_router.py` was
  reshaped.
- **Observability added:** workflow outcomes become queryable after a
  restart via the workflow state store — the first durable
  observability signal in the workflow lane.
- **Fulfills:** REQ-C03.

### Phase 4: One execution envelope, owned spans

**Goal:** a caller does not need to know which substrate ran.

**Tasks:**

1. Define the execution envelope next to `OrchestratorAdapter`
   (`core/adapters/base.py:43`), carrying the fields §4.8 says every
   worker-side protocol converges on: two ids, an explicit terminal
   state, an exit code, and a structured result payload. Model the
   exit-code and payload fields on Pydantic AI's
   `CommandResult(exit_code, stdout, stderr)` and AutoGen's
   `CodeResult(exit_code, output)` — *a non-zero exit is a result, not
   an exception.*
   - **Cost is not in this phase** (§3 non-goal 8). The envelope may carry a
     `cost` field, but nothing populates it yet — and when it is
     populated it must be **nested with an explicit basis**
     (`ExecutionCost(basis, usd, duration_seconds, tokens)`), because a
     worker leg's real cost is wall-clock and a flat `cost_usd` would
     force it into a fictitious dollar figure. A rollup sums only legs
     with the same basis; mixed legs report `cost_usd=None` explicitly.
   - State the relationship to the two envelopes already live:
     `McpErrorEnvelope` (`mahavishnu/mcp/error_envelope.py:8`) at the
     MCP layer and `WorkflowOutcome` (`core/models/persistence.py:47`)
     at the substrate layer. The execution envelope composes the error
     envelope; it does not replace either.

2. **Round 2 picks: the boundary converter.** The two options were
   "have all six adapters return it" or "convert at the boundary via
   `ExecutionEnvelope.from_adapter_result(adapter_type, raw)`". The
   first is rejected because it breaks the state store —
   `StateManager.create` does `record["task"] = dict(task)`
   (`core/task_router.py:280`) and `add_result` does `dict(result)`
   (`:342-348`), and **`dict()` on a Pydantic model raises
   `TypeError`**. Changing `OrchestratorAdapter.execute`'s return type
   is an ABI change to a base class with five implementations, and it
   would have to be a *breaking* one.
   **But the converter must be honest, and it cannot be uniform.** The
   six adapters report **six different status vocabularies**
   (`completed` / `failed`; `completed` / `timeout` / `error`;
   `completed`; `completed`; `AgentStatus`; `completed` / `partial`),
   and **five of six have no exit code at all**. The worker adapter
   *has* one (`WorkerResult.exit_code`, `workers/base.py:36`) but
   `core/adapters/worker.py:290-300` **drops it** on the way out — so
   the fix is to carry it through, and to make `exit_code` honestly
   `None` for the five engines that cannot report one. §4.8's rule
   applies: *a success subtype with a missing structured payload is a
   failure* — so the envelope must distinguish "exit code 0" from
   "no exit code", and the plan must **name the adapters the converter
   cannot honestly convert** rather than guessing.

3. **The control plane creates the span — and propagates the context.**
   The first draft said the workflow span is opened "around the repo
   fan-out" — it is not. The `with` block at
   `core/workflow_execution.py:277-280` contains only
   `_ = workflow_span`, so **the span closes at line 280, before the
   `asyncio.gather` at line 299**. The fan-out is covered by **no span
   at all** today; `end_workflow_trace` (`:308`) records the duration
   out-of-band. So per-leg spans are **new coverage**, not
   re-parenting. Open the workflow span around the gather, and create
   one child span per leg carrying `(adapter, terminal_state,
   exit_code)`.

   **Context propagation is the hard part, and it does not exist yet.**
   A repo-wide search for `traceparent` / `TRACEPARENT` /
   `propagate.inject` returns **no hits anywhere in `mahavishnu/`** —
   `core/observability.py:441-461` calls `start_as_current_span` with
   no carrier. Without propagation there is no tree, only adjacent
   spans. So:
   - inject `TRACEPARENT` / `TRACESTATE` into the **worker launch
     environment** — `workers/shell_backend.py:399-404` already passes
     `env_overrides` into `terminal_manager.launch_sessions(...)`, so
     this is free **in Phase 4**. The first draft named the *Phase 7
     launcher* as the injection point, but Phase 4 lands before Phase 7
     and the launcher does not exist yet; the launcher will simply
     inherit the variables it already passes through for the prompt.
     `core/observability.py:441-461` `start_workflow_trace` calls
     `start_as_current_span` with **no carrier and no `context=`
     parameter**, so the signature must gain one;
   - inject the same context into **each engine's submission path**
     (the Prefect deployment run, the Hatchet run, the Agno agent call)
     — per engine, since each owns its own tracer;
   - record the exporter target as `http://127.0.0.1:4318` per
     `docs/decisions/2026-10-21-otel-substrate-port-ownership.md`.

   A fragmented tree — mahavishnu's parent span in one producer's
   stream, the engine's and the worker's in others, with no shared
   trace id — is **worse than no tree**: Akosha's `search_spans` would
   show three unrelated traces.

4. **Reconcile the three live terminal-state vocabularies.** The
   MCP surface speaks **three** today: the state-store status written
   by `finalize_workflow_execution` (`completed`/`partial`/`failed`,
   `core/workflow_execution.py:346`), the `WorkflowOutcome.status`
   `Literal["succeeded","failed","cancelled"]`
   (`core/models/persistence.py:55`, msgspec-validated at
   `core/workflow/outcome_writer.py:70`), and `WorkflowStatus`
   (`core/status.py:118`). A client that dispatches via
   `trigger_workflow`, polls `get_workflow_status`, then reads
   `workflow_get_outcome_tool` gets **two different terminal states for
   the same workflow** — and `"partial"` maps to `"cancelled"`, so a
   partially-successful workflow is persisted as CANCELLED. One mapping
   table, in one place, and the corruption fixed.

5. **Persist the envelope** into the workflow-state record at
   finalization (`core/workflow_execution.py:426-441`) so
   `get_workflow_status` can return it. Today that tool reads the state
   record, which stores `results` (a list of per-repo adapter results),
   not an envelope — and the first draft's Phase 4 did not list the
   change.

6. **Decide the envelope's position** in `trigger_workflow`'s tool
   return. The existing `"result": result` key means the envelope would
   otherwise be duplicated at two depths; removing it is a MAJOR shape
   change. **Round 2 corrected the arithmetic and dropped the
   deprecation machinery.** The first draft said `1.1.0 → 2.0.0`; but
   Phase 1 already moves the version (`1.1.0 → 1.2.0`), so Phase 4's
   bump is `1.2.0 → 2.0.0`. And because this plan is **forward-only**
   (§3 non-goal 10), there is **no** `DEPRECATED_TOOLS` entry, **no**
   translation shim, and **no** deprecation window — the key is
   removed and the version says so.
   **Round 2 also found a cheaper shape that avoids the break
   entirely.** The response already carries `workflow_id`, `status`,
   `repos_processed`, `successful_repos`, `failed_repos`,
   `execution_time` and `errors` at the top level
   (`mcp/server_core.py:507-516`) — and the envelope's fields are
   essentially those. So the envelope's fields can be added **at the
   top level** and the `"result"` key dropped in the same change, with
   **no** duplicated shape at two depths. That is the design this task
   should pick; the alternative (keeping `"result"` as a duplicate) is
   what the first draft was arguing against, and with no
   compatibility window the duplication buys nothing.

**Exit criteria:** every execution reaches the caller as one envelope;
one span tree covers the fan-out; the three terminal-state vocabularies
agree for one workflow id; `partial` is no longer persisted as
`cancelled`.

#### Integration Contract

- **Triggered from:** `OrchestratorAdapter.execute`
  (`core/adapters/base.py:77`) via `process_single_repo`
  (`core/workflow_execution.py:182`).
- **Returns to / updates:** the `results` list in
  `finalize_workflow_execution` (`core/workflow_execution.py:334`, the
  `successful_results` parameter at `:341`), the persisted
  `WorkflowOutcome` (`core/models/persistence.py:55`), and the OTel span
  tree.
- **Demonstrable by:** `pytest tests/unit/core/test_execution_envelope.py`
  — all six adapters produce an envelope with the same required fields,
  and one workflow id yields the same terminal state from
  `get_workflow_status` and `workflow_get_outcome_tool`.
- **Rollback signal:** an adapter returning a dict without the envelope's
  required fields fails the contract test; a workflow whose
  `get_workflow_status` and `workflow_get_outcome_tool` disagree on the
  terminal state means the mapping table is not wired.
- **Observability added:** one child span per leg under the workflow
  span, carrying `(adapter, terminal_state, exit_code)`; the workflow
  span now actually covers the fan-out it was opened for.
- **Fulfills:** REQ-C04, REQ-C05.

### Phase 5: The pool lane joins the workflow lane

**Goal:** a terminal-worker dispatch has a workflow id and the same
observability as an engine dispatch.

**Tasks:**

0. **Put the pool lane's record somewhere that is not the
   whole-document store.** **Round 2 replaced both of the first
   draft's options, because neither satisfies §2.1.** The first draft
   offered *"write the record once at completion"* or *"the store gets
   a lock + atomic replace"*. But `StateManager._persist` rewrites the
   **entire** file on **every** mutation — so "once at completion" is
   still a 5.2 MB rewrite per dispatch, and "lock + atomic replace"
   only makes that *safe*, not *cheap*. **Neither option satisfies the
   criterion the plan itself calls "the one that bites".**
   **The option the first draft missed:** the substrate already
   supports **per-record keys with O(1) writes** —
   `substrate.put(f"<namespace>/{key}/", payload)` is a single dict
   insert (`core/kv_store.py:46-48`). A pool dispatch can write
   `pool-dispatch/v1/{workflow_id}/` — **one dict insert, no file
   rewrite, no lock, no contention** — and `get_workflow_status` gains
   a **fallback read** (state store first, substrate second). That
   single change satisfies §2.1, makes the "lock + atomic replace"
   option unnecessary *for the hot path*, and leaves the file store for
   the engine lane.
   **The store-hardening work is still needed** — for the engine lane,
   and for the two-process data-loss vector (§4.5) — but it is no
   longer on the pool lane's critical path. It must specify: a
   **unique temp name** in the same directory (the repo's own rule: a
   fixed-name `.tmp` is a symlink target), `os.replace`, `fsync` on
   file and directory, and an **inter-process** lock (`fcntl.flock`) —
   a `threading.Lock` is useless when the MCP server and a CLI are the
   two writers.
   `pool_route_execute` is the path `CLAUDE.md` § Tool Preferences tells
   every agent to use; adding a full-file-rewrite write to it would
   regress the documented ~200–500 ms routing overhead.

1. **Mint the workflow id before the selector gate**, so it exists on
   **every** return path. **Round 2 replaced the first draft's
   inventory, which was wrong.** AST enumeration of `pool_route_execute`
   (`mcp/tools/pool_tools.py:737-1115`) yields **14** returns — L783,
   L788, L839, L860, L869, L884, L895, L946, L1049, L1081, L1087,
   L1089, L1100, L1105 — of which **13** are bare status dicts (only
   L1049 returns the dispatch result). The first draft cited
   "790, 797, 846, 862, 884, 900, 955, 1010", of which only **884** is
   a return; 797 is a `try:`, 846 a comment, 900 and 955 `raise`s, and
   1010 a dict key inside a `logger.exception`. It also **missed
   L946** — `{"status": "worktree_conflict", ...}` — the one path where
   the dispatch never ran. The e2e test the plan drives would have been
   written from those numbers and **silently skipped the
   worktree-conflict path**.
   So a client doing `result["workflow_id"]` gets a `KeyError` on the
   rate-limited and invalid-selector paths. The idempotency-duplicate
   path (`{"status": "duplicate", "result": cached}`, `:884`) must
   return the **original** id, surfaced at the top level.
   **And the rejection paths must not write a record.** Minting an id
   is free; *writing* one is the expensive part (Phase 5 task 0). A
   dispatch that was rejected before it started must answer
   `get_workflow_status` with a **terminal, non-`not_found`** status
   (e.g. `{"status": "rejected", "reason": "rate_limited"}`) — not
   `not_found`, which reads as "never existed".

2. **Give the pool workflow record the fields
   `get_workflow_status` reads** (`mcp/server_core.py:609-621`): set
   `task["type"]` (e.g. `"pool_dispatch"`), populate `results`, and set
   a terminal `status` on completion. Otherwise the demonstration
   "passes" while reporting `task_type: "unknown"`,
   `repos_processed: 0`, `results_count: 0` — the surface-health
   illusion.
   **Round 2 found that Phase 5 cannot write a record at all without
   a wiring change the first draft omitted.** `get_workflow_status`
   reads `self.app.workflow_state_manager.get(workflow_id)`
   (`mcp/server_core.py:585`), but the pool tool block has **no path**
   to that store: `register_pool_tools(mcp, pool_manager)`
   (`mcp/tools/pool_tools.py:278-281`) takes only the server and the
   `PoolManager`, and `PoolManager.__init__`
   (`pools/manager.py:146`) takes no app and no store. So the task must
   include threading the store (or the Phase 3 `WorkflowStore`) into
   `register_pool_tools` / `PoolManager` and into `mcp/bootstrap.py`'s
   `_register_pool_block`. **The `workflow_id` must be minted in the
   orchestration layer** — the plan's own §9 Temporal model — and
   passed down as an opaque correlation id for the substrate to echo.
   Also: setting `task["type"] = "pool_dispatch"` changes the
   routing-decision audit's `task_class` from `"unknown"`
   (`pools/manager.py:262-268`) — a behaviour change the first draft
   did not mention.

3. **Persist a redacted summary, not the prompt.** The pool task is
   `{"prompt": prompt, "timeout": timeout}`
   (`mcp/tools/pool_tools.py:804-806`), and the prompt routinely carries
   repo contents, diffs and file bodies. `StateManager.create` stores
   `dict(task)` verbatim (`core/task_router.py:280`).
   **Round 2 removed the first draft's alternative, because it would
   have written the prompt to disk in full.** The fallback was *"or
   pass it through the existing helper"* — but
   `core/task_audit.py`'s `SENSITIVE_FIELDS` (`:79`) is
   `{"description", "metadata", "tags"}` and its `SENSITIVE_KEYS`
   (`:86`) are credential names; **the string `prompt` appears
   nowhere in that file**. Passing `{"prompt": "…"}` through it
   returns the prompt verbatim — the exact outcome the task exists to
   prevent. **Persist a summary — prompt length, digest, task class,
   caller kind — and that is the only option.**

4. **Surface the id in `pool_monitor`.** `pool_monitor` returns
   `pool_manager.aggregate_results(pool_ids)`
   (`mcp/tools/pool_tools.py:613-621`); the settled-is-final rule in
   Phase 7 must be enforced at that aggregate layer, not only at the
   dispatch record.

5. **State whether the pool lane is inside `allowed_repo_paths`.**
   The engine lane validates every repo path
   (`core/workflow_execution.py:116-129`) and enforces
   `Permission.EXECUTE_WORKFLOW` per repo (`:131-147`); the pool lane
   has no equivalent, resolving the worktree from the *prompt text*
   (`mcp/tools/pool_tools.py:925`). Phase 5 elevates the pool lane to a
   first-class workflow producer, so "we did not think about it" is not
   a defensible position. Either state the boundary and why, or add the
   check.

6. **Do not repoint `tasks_handoff_to_workflow` onto the pool lane.**
   The handoff is bound to the **workflow** lane's semantics —
   `mcp/server_core.py:1516` binds
   `workflow_dispatch_fn=self._dispatch_task_workflow`, and the typed
   `MHV-102 / WorkflowNotReturnedError` contract and the
   `task.handoff_orphan` sweeper depend on the repo fan-out, the
   outcome store and the durable state. After Phase 5 the pool lane
   *looks* like a first-class workflow producer, and a maintainer
   "simplifying" the handoff onto it would silently drop all three.
   Fix the stale docstring at `mcp/tools/tasks_handoff.py:13` in the
   same change — it already mis-describes step 2 as
   `pool_route_execute(prompt=task.content)`.

7. **The workflow id must satisfy the shared two-repo pattern.**
   `mcp/tools/_workflow_id_guard.py:21` defines
   `^[A-Za-z0-9._-]{1,128}$`, and session-buddy mirrors it byte-for-byte
   with the comment that *"the two repos must agree on what a workflow
   id is, otherwise a value that one side accepts would be rejected (or,
   worse, used unsafely) by the other."* Both sides forbid `.`/`..`
   segments because the id is spliced into
   `workflow-results/{workflow_id}/`. The proposed ids
   (`wf_<hex>_terminal`, `wf_<hex>_composition`) are pattern-safe —
   but any shape change requires a **coordinated session-buddy change**.

8. **Decide the pool lane's identity vs the existing
   `execution_id`.** `pool_tools.py:919` mints an `execution_id` that
   is not surfaced in the response; the worktree branch is named
   `f"feature/{execution_id}-{uuid4().hex[:8]}"`. State whether
   `workflow_id` replaces or derives from it, and surface it under a
   distinct key if it stays distinct.

9. **Keep the routing semantics untouched.** The decision-adapter
   plan's Phase 1 makes this tool route live through the `decision`
   category, gated on a **7-day disagreement test**
   (§4.12.1). This plan adds identity, not routing — and must not
   schedule against a moving target.

10. **Register `pool_route_execute` in `TOOL_VERSIONS`.** It is
   **absent** (`mcp/tool_versions.py:71-78` registers the other seven
   pool tools but not this one), so it has no version to bump and is
   invisible to `discover_tools` — it appears in neither
   `loaded_tools` nor `not_loaded_tools`. Add it (and `pool_spawn` /
   `pool_bootstrap`, the same class of gap) while here.
   **Round 2 widened the class from three tools to nine.** The
   registered-but-unversioned tools are `pool_route_execute`,
   `pool_spawn`, `pool_bootstrap`, **`tasks_handoff_to_workflow`**,
   `audit_health`, `cross_repo_search`,
   `mahavishnu_dispatch_specialist`, `mahavishnu_list_specialists` and
   `mahavishnu_get_publish_url`. `tasks_handoff_to_workflow` is the
   task system's **only** dispatch edge (CLAUDE.md § "Task System
   (Bodai)") and is invisible to the fleet's discovery tool. Register
   all nine, and add a **registry-parity test** that fails when a
   registered tool has no `TOOL_VERSIONS` entry — so the class cannot
   grow again.
   **The version number:** because the tool has been shipping
   **unversioned** and this plan is forward-only (§3 non-goal 10),
   there is no shipped contract to record — so register it at
   **`1.0.0` in the same change that adds the `workflow_id`**, and
   `2.0.0` if the response shape also loses a field. The first draft
   put this task *last*, after the shape had already changed, which
   would have left the registry describing a shape that never shipped.
   **Two other facts about the tool's surface the first draft
   omitted:** its `"Returns:"` docstring (`pool_tools.py:765-775`)
   documents **5** status values while the wire carries **8** —
   `error`, `duplicate` and `worktree_conflict` are undocumented — and
   the tool is **STANDARD-tier**, not always-on
   (`mcp/tools/profiles.py:102`, `:124`; absent from
   `MINIMAL_REGISTRATIONS` `:78-98`), so a MINIMAL deployment has no
   dispatch lane at all. The docstring must be rewritten to the full
   status set, and the tier stated.

**Exit criteria:** every `pool_route_execute` response carries a
`workflow_id`; `get_workflow_status` resolves it and reports real
fields; the prompt is not persisted verbatim; the pool lane's latency
has not regressed.

#### Integration Contract

- **Triggered from:** `mcp__mahavishnu__pool_route_execute` →
  `pool_manager.route_task` (`mahavishnu/pools/manager.py:663`).
- **Returns to / updates:** `app.workflow_state_manager`,
  `pool_manager.aggregate_results` (`pools/manager.py`), the
  `workflow_id` field of the tool's response, and the OTel span tree.
- **Demonstrable by:** `mahavishnu demo pool-mahavishnu` prints a
  `workflow_id`; `mcp__mahavishnu__get_workflow_status` with that id
  resolves and reports a non-`unknown` task type;
  `pytest tests/integration/test_pool_route_execute_e2e.py` asserts
  every return path carries the id.
- **Rollback signal:** a `pool_route_execute` response with no
  `workflow_id` means the lane was not joined; `pool_route_execute`
  latency regressing past the stated ~200–500 ms routing overhead means
  the workflow id is being created on a hot path it should not be.
- **Observability added:** pool dispatches become countable by
  `mahavishnu.workflows.total{adapter="worker"}`.
- **Fulfills:** REQ-C06.

### Phase 6: Composition — engine leg and worker leg

**Goal:** one workflow, two substrates, one identity.

**Tasks:**

1. **Extend the conductor — do not build a second executor. Round 2
   overturned this task.** The first draft said *"This is the piece
   that does not exist"* and *"mahavishnu does not need its own DAG
   engine."* **Both are false**: the repo **shipped** a DAG composition
   executor (§4.15) — `core/conductor.py`'s `plan()` / `emit_node()` /
   `_dispatch_dag_waves()` / `emit_flow()`, backed by
   `core/capabilities.py`, `core/conductor_types.py`,
   `engines/emit_node_dispatch.py` and
   `tests/integration/conductor/`. `emit_flow()` compiles the DAG into
   a Prefect flow with `task.submit(..., wait_for=[upstream_future])` —
   **dependency-ordered data flow across adapters**, which is exactly
   what the first draft proposed to invent.
   **The real gap is precise:** the conductor's DAG threads **engine
   legs only**, its downstream prompt synthesis is an explicit
   placeholder (`core/conductor.py:222-227`), and its MCP entry point
   is a **one-line stub** — `execute_capability`
   (`mcp/tools/capability_tools.py:362`) returns `status="planned"`,
   with its own docstring saying *"Actual dispatch lands in Phase 4
   (per-engine dispatch modules)"*.
   So the task is: **add a worker leg to `emit_node`, flip
   `execute_capability`'s `status="planned"` to a real dispatch, and
   give the DAG the workflow identity and span tree the control plane
   owns.** The fallback chain is still not data flow — that observation
   stands, and it is why the conductor's DAG is the right home rather
   than the fallback chain.
   This remains **distinct** from the multi-task batch loop ported from
   `UnifiedOrchestrator` in Phase 3: a batch runs N independent tasks,
   each with its own fallback; a DAG threads one into the next.

2. **Each stage names its adapter explicitly; the router is not
   consulted inside a stage.** The router selects *within* a stage
   (a stage may have its own fallback chain); it never selects *across*
   stages (§4.13). Without this rule, "prefect by default" and
   "terminal-claude" are two different selection mechanisms and the
   composition is not the thing the plan describes.

3. **Failure policy:** a failed stage **aborts** the sequence, and the
   workflow reports **which** stage broke. `stage_index` and
   `stage_count` go into the envelope's identity fields.

4. **Reuse the threading** from `demo workflow-pi-then-local`
   (`cli/demo_cli.py:4098-4108`), where stage one's output is folded
   into stage two's prompt — but promote it **with its discipline**.
   The demo's threading is a **string splice, not a data-flow
   contract**: `pi_result.get('output', '')` has a **silent
   empty-string default**, so a stage 1 that produced no output yields
   a *successful but empty* stage 2 — §4.8 item 4's failure mode, in
   the very code the plan wants to promote. **Stage one's output must
   be required**: missing or non-string output ⇒ stage 1 fails ⇒ stage
   2 does not run.

4a. **A sequence is a linear list of stages: no branching, no fan-out,
   no cycles.** State it as an invariant and pin it with a test —
   otherwise "a sequence, not a second DAG" is unenforceable, and the
   executor grows a DAG the moment someone needs a conditional.
   The demo's own code treats stage-one output as untrusted: it wraps
   it in `shlex.quote` and an allowlisted command, with a comment
   saying so. The composition must:
   - treat stage-one output as **untrusted data** — delimited and
     labelled as quoted content, never concatenated into the
     instruction region;
   - **size-cap** what is folded across;
   - deliver it as a **prompt, never as a command** — the executor
     reuses the pool's existing env-var / `shlex.quote` delivery;
   - run stage two with a **reduced permission mode** whenever its
     input is derived, unless the operator opts in — and record the
     opt-in. **Round 2 found that this control is unimplementable as
     written**, so it needs an explicit plumbing task: there is **no
     per-dispatch permission-mode path** today.
     `workers/manager.py:412-433` `_resolve_permission_mode` reads
     **settings only**, and `:500-506` constructs
     `ShellWorker(..., permission_mode=...)` while **ignoring
     `kwargs`**. `submit_workers`' `runtime_kwargs` (`:320-326`,
     `:349`) is forwarded only into the **Shepherd** branch (`:507`) —
     so `submit_workers(..., runtime_kwargs={"permission_mode":
     "plan"})` is **silently dropped** for `terminal-claude`.
     The leaf is ready (`ShellWorker.__init__(permission_mode=…)`,
     `resolve_permission_mode(config, override)`); the plumbing is not.
     The task must therefore add: (a) the SHELL branch of
     `_create_worker` forwards `permission_mode`; (b) the envelope
     carries a per-task `permission_mode`; and (c) the "record the
     opt-in" has a named destination (the Phase 4 envelope and the
     Phase 4 span/metric labels). **Without this, the exit criterion
     below is unmeetable** — and a "reduced permission mode" that
     silently does nothing is worse than no such control, because the
     plan would be claiming it.
   - mark the second leg's input as **derived** in the span and metric
     labels, so an operator can tell an injected leg from a direct one.

5. **Keep the executor *one* DAG, not two.** The first draft said
   *"mahavishnu does not need its own DAG engine"* — but the repo
   already has one, and it is the right one (§4.15). The corrected
   rule is the opposite: **there is exactly one DAG engine
   (`core/conductor.py`), and Phase 6 extends it.** Prefect's presence
   in the stack is a *reason* the conductor should compile to a Prefect
   flow, not a reason to avoid the conductor.

6. Add `demo workflow-engine-and-worker`: an engine leg (prefect by
   default) produces a task, a `terminal-claude` pool executes it, both
   legs narrated as stages under one workflow id.

**Exit criteria:** one execution id, one span tree, one envelope
across both legs; the worker leg's prompt contains the engine leg's
output; a failed stage aborts the sequence and names its index; the
derived input is capped, delimited, and the second leg runs with a
reduced permission mode.

#### Integration Contract

- **Triggered from:** `mahavishnu demo workflow-engine-and-worker`;
  the executor is called from `app.execute_workflow_sequence`.
- **Returns to / updates:** the workflow state record and the outcome
  written by `finalize_workflow_execution`.
- **Demonstrable by:** `pytest tests/unit/core/test_workflow_sequence.py`
  — stage two's input contains stage one's output; the demo prints one
  `workflow_id` and one span tree; a failed stage aborts and reports
  `stage_index`.
- **Rollback signal:** two workflow ids for one composition means the
  legs did not share identity; a stage running before its predecessor
  settled means the sequence is not ordered; a workflow reporting no
  stage index means the envelope's identity fields were not extended.
- **Observability added:** one span per stage under the workflow span,
  with the stage's adapter, index, and input/output byte counts, and a
  `derived_input` marker on stages whose input came from a prior stage.
- **Fulfills:** REQ-C07.

### Phase 7: Dispatch trustworthiness

**Goal:** a one-shot dispatch is *settled* or it is *not done* — never
inferred from a process exit.

**Tasks:**

1. **Introduce a pool-owned dispatch record, then make settled final.**
   **Round 2 split this task, because the first draft's version has
   nothing to enforce on.** `pool_manager.aggregate_results`
   (`pools/manager.py:1343-1399`) returns
   `{pool_id: {"memory_count": int, "status": PoolStatus.value}}` —
   **per pool, not per dispatch**. There is no dispatch id, no dispatch
   state, and nothing persisted: the pool's per-dispatch result is a
   **transient dict** returned by `MahavishnuPool.execute_task`
   (`pools/mahavishnu_pool.py:307-314`), and the only persistent pool
   trace is the routing-decision audit (`pools/manager.py:246-290`),
   which has no dispatch id and no state field. `route_task` is
   **synchronous** (`pools/manager.py:836`) — there is no "dispatched"
   interval at all.
   So the task is two tasks: **(1a)** introduce a pool-owned dispatch
   record (`dispatch_id`, `state`, `terminal_state`, `settled_at`)
   written by the pool, and surface per-dispatch states so the rule is
   enforceable and testable; **(1b)** enforce settled-is-final at the
   aggregate layer.
   The plan also asserts *"the pool is the single writer of a
   dispatch's state"* — **today the worker writes its own status**
   (`workers/shell_backend.py:411` `self._status = WorkerStatus.RUNNING`;
   `:683` `CANCELLED`). Moving that ownership is exactly what §4.13's
   state-ownership rule requires, and it is what (1a) does.

2. **Parse the CLI's own result envelope rather than trusting the exit
   code alone.** Claude's `stream-json` ends with
   `{"type":"result","subtype":"success","is_error":false}`; a non-zero
   `is_error` or a non-`success` subtype is a failure even when the
   process exited 0. §4.8's rule: *a success subtype with a missing
   structured payload is a failure.*

3. **The readiness handshake.** Move the launch protocol out of the
   command string and into a **generated launcher** next to the prompt
   file. The launcher reads the prompt into `MAHAVISHNU_PROMPT`,
   exports it, emits `__MAHAVISHNU_READY__` with the prompt's byte
   count, then `exec`s the registry command. The dispatch stays
   `DISPATCHED` until READY arrives, then becomes `RUNNING`. A
   readiness timeout is a **failure**, not a hang.
   The launcher is a new artifact on the trust path, so it must be
   held to the same standard as the prompt file:
   - created with `tempfile.mkstemp` (**O_EXCL**, mode **0600**) in the
     same private directory as the prompt file, and removed with it —
     the repo already documents why (`workers/shell_backend.py:387-392`:
     *"a fixed pathname in a shared directory is a symlink target"*, and
     the default umask would make it world-readable);
   - invoked as `sh <launcher>`, not executed, so it need not carry the
     execute bit;
   - **the stderr decision must be made against the *registry*
     command, not the rendered string.** Today
     `workers/shell_backend.py:393` checks
     `if STDERR_PATH_ENV_VAR in command:` on the **rendered** command,
     and that is the *only* trigger for creating the per-invocation
     stderr file (`:394-396`). With the launcher, the string handed to
     `terminal_manager.launch_sessions` becomes `sh <launcher>` — which
     does **not** contain `MAHAVISHNU_STDERR_PATH` — so the file would
     never be created, the CLI's stderr would silently go to
     `/dev/null`, and the failure diagnostic at `:591` / `:607-610`
     would be lost. `tests/unit/workers/test_shell_command_safety.py:334-343`
     asserts `STDERR_PATH_ENV_VAR in command` and would fail. The
     check must move to `self.config.command` (the registry entry)
     rather than the rendered string;
   - generated **only** via `render_command()` +
     `resolve_permission_mode()`, never by string-formatting the
     registry command — `render_command` raises if a `{prompt}`
     placeholder reappears (`shell_backend.py:172-179`), and
     `resolve_permission_mode` bounds the substituted mode against the
     per-CLI allowlist (`shell_backend.py:105-133`);
   - containing **no caller-supplied text** — only the prompt file path
     and the validated registry command;
   - with the *"no `;` outside the known separators"* assertion from
     `tests/unit/workers/test_shell_command_safety.py:105-120`
     re-pointed at the launcher's contents. **That test file is
     currently in the plan's blast radius and was missing from its
     Required Code Changes.**
   - an `exec` failure (e.g. `ARG_MAX` on a very large prompt)
     surfacing as a **distinct** failure, not as a readiness timeout —
     a launcher that dies before `exec` produces no READY, and the
     timeout diagnosis would misattribute an argv-size failure to the
     CLI.

4. **Prompt delivery fidelity — not an integrity guarantee.** The
   worker computes the sha256 of the prompt it wrote; the launcher
   computes the sha256 of **what it actually read** and reports it.
   Two specifics:
   - The digest must pin the **exported string**, not the file.
     Command substitution strips trailing newlines
     (`shell_backend.py:180-185`), so the CLI's argv is the file bytes
     *minus* trailing newlines; hashing the file would make the check
     pass while the CLI received different bytes. Record the hashed byte
     length alongside the digest.
   - **State the threat model**: this catches truncation, partial
     writes, and wrong-file mix-ups. It does **not** defend against a
     malicious caller (the caller chooses the prompt), against prompt
     injection through repo content, or against a compromised host. The
     digest rides the same pane the supervised CLI writes to, so it is
     **advisory** — never the basis for "the prompt was authentic".
     Where no portable hashing tool exists, the marker says
     `sha256=unavailable` and the worker records
     `delivery_fidelity: "unverified"` rather than reporting a pass it
     did not perform.

5. Use the **execution vocabulary chosen in Phase 3** — *not* a new
   `DispatchState` in `pools/base.py`. The name is already taken by an
   unrelated concept at `mahavishnu/jot/fold.py:54`, and `pools/base.py`
   carries no dispatch state today.

**Exit criteria:** a CLI that exits 0 with `is_error: true` is reported
FAILED; a settled dispatch stays settled across a later poll and across
`pool_monitor`; a launcher that exits before READY yields FAILED with a
readiness error, not a timeout; a truncated prompt file is detected and
reported as `delivery_fidelity: "mismatch"`.

#### Integration Contract

- **Triggered from:** `mcp__mahavishnu__pool_route_execute` →
  `MahavishnuPool.execute_task` (`pools/mahavishnu_pool.py`);
  `ShellWorker.start` and `ShellWorker._await_completion`
  (`workers/shell_backend.py`).
- **Returns to / updates:** the dispatch's state in the pool's dispatch
  record, the aggregate view in `pool_manager.aggregate_results`
  (`pools/manager.py`), and the `status` field of the
  `pool_route_execute` response.
- **Demonstrable by:**
  `pytest tests/unit/workers/test_shell_launcher.py`,
  `pytest tests/unit/pools/test_dispatch_states.py`, and the re-pointed
  `tests/unit/workers/test_shell_command_safety.py`.
- **Rollback signal:** a `pool.dispatch.settled` for a dispatch that
  never logged `pool.dispatch.ready` means the handshake was bypassed; a
  dispatch reporting `delivery_fidelity: "unverified"` on a host that
  has `shasum` means the check silently stopped running.
- **Observability added:** `pool.dispatch.ready` (carrying `pool_id`,
  `worker_id`, `prompt_bytes`, `ready_latency_seconds`),
  `pool.dispatch.settled` (carrying `state`, `exit_code`,
  `duration_seconds`), and `pool.dispatch.fidelity` (carrying
  `prompt_sha256`, `delivery_fidelity`).
- **Fulfills:** REQ-C08, REQ-C09, REQ-C10.

### Phase 8: Demos and documentation

**Goal:** the demos are the surface, and they must show the consolidated
system rather than bypass it.

**Tasks — update the existing demos:**

1. **Route every engine demo through the workflow lane.** `agno`,
   `llamaindex`, `pydantic_ai`, and `hatchet` currently call
   `adapter.execute(task, repos)` **once** with a repo list; they must
   call `app.execute_workflow_parallel` so a demo run produces a
   workflow id, a span tree, and a state record — the same thing an
   operator gets from `trigger_workflow` (REQ-C11). **This changes the
   demos' semantics, not just their routing**: `execute_workflow_parallel`
   fans out **one adapter call per repo**
   (`core/workflow_execution.py:182`), so a single multi-repo call
   becomes N single-repo calls — a different invocation count, a
   different per-repo result shape, and for `agno`/`pydantic_ai`
   (multi-agent over repos) and `llamaindex` (RAG over repos) a
   different meaning. It also runs `validate_pre_execution_qc` and
   `create_session_checkpoint` (`:551-552`), so **every demo run would
   write a session checkpoint into Session-Buddy** — a cross-ecosystem
   side effect of the demo surface.
   **Round 2 corrected the first draft's remedy.** The first draft
   offered *"accept it explicitly or add a demo-mode flag that skips
   `create_session_checkpoint`"*. **A skip flag is the wrong answer**,
   for two reasons:
   - **The write is not demo-only.** `execute_workflow_parallel` already
     does it for **every** `trigger_workflow` today
     (`core/workflow_execution.py:551-552` → `core/session/checkpoint.py:59-79`).
     A demo-only flag hides a pre-existing per-workflow side effect
     rather than fixing it — and it would make the demo lane
     observably *different* from the operator lane, which REQ-C11
     explicitly wants to eliminate.
   - **The write is unattributable.** `core/session/checkpoint.py:66-72`
     sends only `{"checkpoint_type": "workflow"}` — no `workflow_id`,
     no `task`, no `adapter`, no `repos`. So every workflow (and every
     demo) produces an indistinguishable snapshot of the *operator's
     session context*, and `demo_all` over the demo set adds one per
     demo to session-buddy's searchable corpus.
   **The fix is a two-repo contract change**: session-buddy's
   `store_conversation_checkpoint` accepts a `workflow_id` (and the
   workflow state), and mahavishnu passes it from
   `create_session_checkpoint` / `update_checkpoint`
   (`core/session/checkpoint.py:81-117`). The session-buddy side is an
   **operator-owned publish** (the `session-buddy>=0.38.0` pin is
   bumped by the operator, not by this change).
   **Until that lands, the demo lane keeps the checkpoint.** The demo
   must exercise the operator's path.
2. **Fix the `prefect` demo to exercise the adapter.** It currently uses
   Prefect's raw client (`get_client`, `run_deployment`,
   `flow.from_source(...).deploy()`) and never calls
   `PrefectAdapter.execute`. The demo named after the adapter must
   exercise the adapter.
3. **Correct the `workflow-multi-pool-handoff` docstring**, not the
   `workflow-pool-worker-terminal` one. The misleading text lives at
   `cli/demo_cli.py:3642-3643` — *"For the operator-facing E2E (Prefect ->
   pool -> worker -> terminal), use `mahavishnu demo
   workflow-pool-worker-terminal` instead."* `workflow-pool-worker-terminal`'s
   own docstring (`cli/demo_cli.py:3435-3439`) honestly lists three
   substrates and never mentions Prefect — **do not touch it**. Either
   drop the Prefect mention from the cross-reference or point it at
   Phase 6's `workflow-engine-and-worker`. The first draft of this plan
   targeted the wrong docstring and would have left the lie in place.
4. **Promote `workflow-pi-then-local`** to use the Phase 6 sequence
   executor, keeping its behaviour and its recipe.
5. **Disambiguate `workflow-adapter-swap`.** It swaps the *terminal*
   adapter (mock ↔ tmux). Rename it (e.g.
   `workflow-terminal-adapter-swap`) or add an engine-adapter variant, so
   the two meanings do not collide.
6. **Give the pool-lane demos workflow ids** (Phase 5):
   `workflow-multi-pool-handoff`, `workflow-pi-cascade`, and the five
   `pool-*` demos.

**Tasks — add the new demos:**

7. `demo terminal-claude`, `demo terminal-qwen`, `demo terminal-codex` —
   each drives a real one-shot pool dispatch of a prompt and asserts the
   CLI's answer. Each **skips cleanly** when the CLI is missing,
   unauthenticated, or usage-limited; a demo that fails because the
   operator's codex account is exhausted is noise, not signal.
8. `demo workflow-engine-and-worker` — the Phase 6 composition.

**Tasks — the inventory that must move with them (REQ-C12):**

9. `_main_cli.py:1471-1480` — the `DEMO SUB-COMMANDS` block, currently
   "16 live implementations … + 1 stub". The live count is **17**:
   `pool-runpod-public` (`cli/demo_cli.py:2938`) is registered and in
   the sweep spec (`:4291`) but appears in **no** documentation, and the
   block says "4 pool demos" where there are 5.
10. `cli/demo_cli.py` — the stub-section tally comment.
11. `docs/CLI_REFERENCE.md` — **both** the `### Pool demos` block
    (`:101`, which omits `pool-runpod-public`) **and** the
    `### Workflow demos` block (`:110`).
12. `docs/mcp/MCP_TOOLS_SPECIFICATION.md` — it omits `pool_route_execute`,
    `pool_spawn` and `pool_bootstrap` entirely, including the tool
    `CLAUDE.md` names as the primary entry point; its hand-maintained
    `Source:` line numbers have also drifted (`trigger_workflow` is
    documented at `:273`; the decorator is at `:409`).
13. `tests/unit/cli/test_cli_wireup_invariants.py` — add the
    live-implementation test for `pool-runpod-public`, which the other
    four pool demos have and it does not.
14. `tests/unit/cli/test_cli_wireup_invariants.py` — the flag/help
    assertions for every new demo (the anti-revert test).
15. `tests/unit/cli/test_demo_workflow_preconditions.py` — precondition
    tests for each new demo's skip path.
16. `demo_all` — decide whether the harness demos belong in the sweep.
    The harness leg alone is ~115 s, so it is a nightly/CI job, not a
    per-commit gate.

**Tasks — the cookbook (`docs/cookbook/workflows.md`):**

The cookbook is the *worked-example layer* — the only place a reader
learns what a workflow actually looks like end to end. It is currently
**not** covered by any automated check: `grep -rn "cookbook" tests/`
returns nothing, so a recipe can describe a command that no longer
exists and nothing fails. (That grep becomes non-empty once this plan
lands `tests/unit/cli/test_cookbook_parity.py` — so this sentence is a
statement about the *pre-plan* state, not a permanent claim.) That drift is the same failure mode as the
dark adapters, one layer down, so this phase closes it.

17. **Recipe 1 — PiPool → MahavishnuPool handoff** (`docs/cookbook/workflows.md:27`).
    Its documented output (`{"workflow": "pi-then-local", "pi": {...},
    "local": {...}}`) is a bespoke JSON shape no other demo produces.
    Update:
    - the "What you'll see" block to the new result shape, including
      the `workflow_id` that Phase 5 gives the pool lane and the shared
      envelope fields;
    - the Notes bullet that tells the reader to look for the
      `received from pi pool: …` prefix in `~/.mahavishnu/logs/mcp.log`
      — that prefix is produced by the demo's own prompt assembly
      (`cli/demo_cli.py:4098`), which Phase 6 replaces with the
      executor's threading, so the prefix and the note must be
      re-derived together or both changed;
    - the Prerequisites, if the Shepherd workspace path moves when the
      adapter starts wrapping the pool (Phase 3 task 8).

    **Neither existing recipe builds a workflow task envelope** — both
    are pool-lane demos that dispatch through `PoolManager` — so the
    Phase 1 envelope change does not otherwise touch them. Recipe 1
    changes because its *implementation* is promoted onto the Phase 6
    sequence executor.
18. **Recipe 2 — PiPool 2-turn cascade** (`:122`). Same treatment: it
    gains the `workflow_id` from Phase 5. This recipe is *already* a
    sequence — two ordered turns on one pool — so it is a second
    candidate for the Phase 6 executor alongside Recipe 1. Its closing
    cross-reference ("For a true multi-pool handoff (source → target),
    use `workflow-multi-pool-handoff` instead") must also point at the
    new `workflow-engine-and-worker` recipe.
19. **Add a recipe for each new demo** (task 7 and 8 above), following
    the file's existing structure (Goal, Substrates exercised,
    Prerequisites, The command, What you'll see, Troubleshooting, Notes)
    and adding a row to the recipe index with its flavor:
    - **`terminal-claude`** — the one-shot CLI harness: what
      "the prompt rides the launch, not the TUI" looks like from the
      outside; the skip path when the CLI is absent or
      usage-limited; and how to read the completion marker.
    - **`workflow-engine-and-worker`** — the composition: one
      `workflow_id`, two legs, one span tree, and the stage narration.
20. **Add a recipe for the newly-reachable adapters.** Phase 2 makes
    `worker`, `hatchet`, and `pydantic_ai` selectable through
    `trigger_workflow`. The cookbook is where a reader would look for
    "how do I actually run a workflow on a terminal worker", and today
    there is no worked example for it. A recipe showing
    `mcp__mahavishnu__trigger_workflow(adapter="worker", …)` end to end
    — including the repositories to scope to, and what the result
    envelope looks like — is the missing worked example.
21. **Update the "How to add a new recipe" procedure itself.** It is
    the mechanism by which workflows are generated today (§4.1), so it
    must describe the consolidated system:
    - step 1 currently says to build `_run_workflow_<name>_demo` that
      "constructs `PoolConfig` and the substrate, dispatches, returns
      structured result dict" — it must now say to return the **standard
      result envelope** and to run through the workflow lane, so the
      recipe's output matches every other demo's;
    - step 2 says to update the `=== DEMO SUB-COMMANDS ===` comment in
      `_main_cli.py`. That exact string **does not exist** in the code —
      the real marker is `=== DEMO SUB-COMMANDS (mahavishnu demo
      <engine|adapter>) ===` at `_main_cli.py:1471`, and the code's own
      anti-revert grep is `git grep -n 'DEMO SUB-COMMANDS'`. The
      cookbook's instruction must name the marker that is actually
      there, or the anti-revert grep it teaches will fail;
    - the recipe structure list must gain the `workflow_id` / result
      envelope, so a recipe written from the template cannot document
      a pre-consolidation shape;
    - it must also require a cookbook recipe for every new workflow
      demo — that is the parity rule in task 22.
22. **Add a cookbook↔demo parity test** (REQ-C15). A new test in
    `tests/unit/cli/test_demo_workflow_preconditions.py` (or a sibling)
    that parses `docs/cookbook/workflows.md` and asserts:
    - every `mahavishnu demo <name>` command appearing in a recipe
      resolves to a real registered demo command, and
    - every workflow demo in `demo_cli.py` has a recipe.

    This is the check whose absence let the cookbook drift silently
    until now. It is small, deterministic, and it is the difference
    between a cookbook that is maintained and a cookbook that is
    archaeology.
23. **Fix the demo docstring that points at the cookbook.**
    `cli/demo_cli.py:4056` says "Demo-recipe flavor (paired with
    `docs/cookbook/workflows.md`)" — if a recipe is renamed, this
    cross-reference must move with it.

**Tasks — the agent-facing surfaces (round 2 added these):**

24. **Fix the published skill that contradicts Phase 5.**
    `mahavishnu/mcp/skills_catalog/workflow-status.md:66-68` says:
    *"For a synchronous single-task dispatch that has already returned,
    use `mcp__mahavishnu__pool_route_execute` directly — **there is no
    workflow_id to poll.**"* After Phase 5 that is **false**, and the
    file is served to agents over MCP
    (`mcp/tools/skill_tools.py:66`) and materialized into
    `~/.claude/skills/` by the `ecosystem-skill-loader`. Its sibling
    `mahavishnu/mcp/skills_catalog/pool-route.md:94-95` already
    promises a workflow id — Phase 5 makes that true. Both must move
    together.
25. **Fix the published specialist agent body.**
    `mahavishnu/mcp/agents/mahavishnu-specialist.md` names a tool that
    **does not exist** (`mcp__mahavishnu__dispatch_to_pool` — the only
    hits are docstrings) and gives `trigger_workflow`'s second
    parameter as `name` when it is `task_type`
    (`mcp/server_core.py:410-417`). It is also the natural home for
    Phase 5's new `workflow_id` field — and the file the
    `ecosystem-agent-loader` materializes into `~/.claude/agents/`.
26. **Fix the second MCP-tools inventory.** `docs/mcp/MCP_TOOLS_REFERENCE.md`
    documents `trigger_workflow` with the same signature and omits the
    same three pool tools — and `README.md:514` names it as *"the
    detailed inventory"*. Fixing `MCP_TOOLS_SPECIFICATION.md` and not
    this one leaves the fleet with two half-drifted inventories. **Phase 4
    has no documentation task at all for `trigger_workflow`'s response
    shape**; that gap closes here.
27. **Fix `docs/CONFIGURATION.md`.** `:456-470` documents the
    `feature_flags.*` block Phase 3 deletes
    (`use_hybrid_registry`, `use_capability_routing`,
    `fallback_to_legacy`). Operators will keep setting three flags that
    do nothing. (The *typed* `FeatureFlagsConfig` model and its
    `goal_teams.feature_flags` block are a different thing and stay.)

**Exit criteria:** every demo produces a workflow id; `demo --help`
lists every demo; the `DEMO SUB-COMMANDS` count matches the shipped set;
the cookbook and CLI reference describe what the demos actually do; the
cookbook↔demo parity test passes in both directions; **and no published
skill or agent body contradicts the tool's actual surface.**

#### Integration Contract

- **Triggered from:** `mahavishnu demo <name>` (`cli/demo_cli.py`),
  registered at `_main_cli.py:1481-1483`.
- **Returns to / updates:** the workflow state store (every demo now
  writes one), `docs/cookbook/workflows.md`, `docs/CLI_REFERENCE.md`,
  and the `DEMO SUB-COMMANDS` block.
- **Demonstrable by:** `pytest tests/unit/cli/test_cli_wireup_invariants.py`,
  `pytest tests/unit/cli/test_demo_workflow_preconditions.py`, and the
  new cookbook↔demo parity test; `mahavishnu demo --help` lists every
  demo exactly once.
- **Rollback signal:** the `DEMO SUB-COMMANDS` count disagreeing with
  `demo --help` means the inventory drifted — the anti-revert test
  catches this; the cookbook parity test failing means a recipe names a
  command that no longer exists, or a demo has no recipe; a demo that
  fails instead of skipping when its CLI is absent means the skip logic
  regressed.
- **Observability added:** demo runs appear in the workflow state store
  and the span tree, so a demo run is observable like any other
  workflow.
- **Fulfills:** REQ-C11, REQ-C12, REQ-C15.

## 6. Required Code Changes

- [ ] `mahavishnu/core/workflow_execution.py` — envelope construction; sequence executor; `enable_cost_tracking` wired
- [ ] `mahavishnu/core/adapters/base.py` — the result envelope
- [ ] `mahavishnu/core/adapters/worker.py` — envelope reads; wrap the pool
- [ ] `mahavishnu/core/routing.py` — `AdapterType.WORKER`/`HATCHET`/`PYDANTIC_AI` in the chains
- [ ] `mahavishnu/core/task_router.py` — collapse or delete; envelope
- [ ] `mahavishnu/core/unified_orchestrator.py` — **delete**
- [ ] `mahavishnu/core/bootstrap.py` — registry consolidation
- [ ] `mahavishnu/core/app.py` — envelope; `enable_cost_tracking`
- [ ] `mahavishnu/core/cost_optimizer.py` — worker/hatchet cost bases (**deferred**, §3 non-goal 8)
- [ ] `mahavishnu/core/task_envelope.py` — **new**: the typed envelope (§4.11)
- [ ] `mahavishnu/core/metrics_schema.py` — re-point at the unified enums (§4.2 row 9)
- [ ] `mahavishnu/core/workflow/state.py` — **new**: `StateManager` relocated out of `core/task_router.py`
- [ ] `mahavishnu/core/workflow/outcome_writer.py` — the substrate contract (Phase 3 task 6)
- [ ] `mahavishnu/core/substrate.py`, `mahavishnu/core/kv_store.py` — the durable-backend seam
- [ ] `mahavishnu/core/health_aggregator.py` — the `adapters` feed (§4.5, Phase 2 task 6)
- [ ] `mahavishnu/core/models/persistence.py` — `WorkflowOutcome.status` literal (§4.11, Phase 4 task 4)
- [ ] `mahavishnu/core/config.py` — `adapters.pydantic_ai_enabled`; the `AdapterRegistryConfig` removal
- [ ] `mahavishnu/core/oneiric_client.py` — reconcile the two `OneiricMCPConfig` classes
- [ ] `mahavishnu/engines/__init__.py` — `_ENGINE_LOCATIONS` vs `app.adapters`
- [ ] `mahavishnu/mcp/tool_versions.py` — `trigger_workflow` bump; register `pool_route_execute`
- [ ] `mahavishnu/mcp/tools/capability_tools.py` — the duplicate worker registration
- [ ] `mahavishnu/workers/manager.py` — `worker_type` allowlist enforcement
- [ ] `mahavishnu/workers/shell_backend.py` — the launcher, `resolve_permission_mode`
- [ ] `docs/mcp/MCP_TOOLS_SPECIFICATION.md` — the three missing pool tools
- [ ] `settings/mahavishnu.yaml` — `adapter_registry` / `feature_flags` removal
- [ ] `tests/unit/workers/test_shell_command_safety.py` — re-point at the launcher
- [ ] `mahavishnu/core/observability.py` — per-leg span creation
- [ ] `mahavishnu/core/status.py` — the superset lifecycle enum
- [ ] `mahavishnu/workers/contract/state.py` — the chosen vocabulary's home
- [ ] `mahavishnu/workers/shell_backend.py` — launcher, readiness, integrity
- [ ] `mahavishnu/workers/openhands.py` — current SDK contract
- [ ] `mahavishnu/workers/registry.py` — legacy registry retired
- [ ] `mahavishnu/pools/mahavishnu_pool.py` — dispatch state ownership
- [ ] `mahavishnu/pools/manager.py` — workflow identity for pool dispatches
- [ ] `mahavishnu/mcp/server_core.py` — envelope; adapter documentation
- [ ] `mahavishnu/mcp/tools/pool_tools.py` — workflow id in the response
- [ ] `mahavishnu/cli/demo_cli.py` — the demo changes above
- [ ] `mahavishnu/_main_cli.py` — the CLI task-key fix; the demo inventory
- [ ] `docs/cookbook/workflows.md` — recipes 1 and 2, the new recipes,
      and the "How to add a new recipe" procedure
- [ ] `docs/CLI_REFERENCE.md` — the workflow-demos block
- [ ] `docs/plans/PLAN_INDEX.md` — regenerated
- [ ] `docs/adr/011-two-router-composition.md` — **amendment** (it names `core/task_router.py` as the Task Router's home and `UnifiedOrchestrator` as a caller; Phase 3 changes both)
- [ ] `CLAUDE.md` § "Pool and Terminal Architecture" — **amendment** (Phase 5 gives the pool lane workflow identity, against "these modules share no imports or state")
- [ ] `docs/pools/POOL_ARCHITECTURE.md` — **amendment** (the leaf-substrate rule, if Phase 3 task 8's shape changes)
- [ ] `docs/decisions/2026-10-14-decision-adapter-category.md` — **sequencing note**
- [ ] `docs/decisions/2026-08-29-settle-vs-langgraph.md` — cite the "avoid hard-coding primitives to a single engine" precedent in Phase 4
- [ ] `mahavishnu/core/task_requirements.py` — the `TaskType` importer
- [ ] `mahavishnu/mcp/bootstrap.py` — the worker-tool registration gate
- [ ] `tests/fixtures/chaos_harness.py` — the three-import fixture
- [ ] `tests/unit/test_workflow_cli.py` — the source-text import pin
- [ ] `tests/unit/core/test_task_envelope.py` — **new**
- [ ] `tests/unit/core/test_adapter_reachability.py` — **new**
- [ ] `tests/unit/core/test_registry_uniqueness.py` — **new**
- [ ] `tests/unit/core/test_execution_envelope.py` — **new**
- [ ] `tests/unit/core/test_workflow_sequence.py` — **new**
- [ ] `tests/unit/workers/test_shell_launcher.py` — **new**
- [ ] `tests/unit/pools/test_dispatch_states.py` — **new**
- [ ] `tests/unit/cli/test_cli_wireup_invariants.py` — extended
- [ ] `tests/unit/cli/test_demo_workflow_preconditions.py` — extended
- [ ] `tests/unit/cli/test_cookbook_parity.py` — **new** (REQ-C15)
- [ ] `mahavishnu/core/conductor.py` — the **existing** DAG executor: add a worker leg (Phase 6)
- [ ] `mahavishnu/core/capabilities.py` — `CapabilityEnvelope`, `DAGNode`, `DAGEdge`, `ExecutionDAG`
- [ ] `mahavishnu/core/conductor_types.py` — `NodeSpec`, `NodeHandle`
- [ ] `mahavishnu/engines/emit_node_dispatch.py` — the per-engine dispatch tables
- [ ] `mahavishnu/mcp/tools/capability_tools.py` — flip `execute_capability` from `status="planned"` to a real dispatch (Phase 6); the duplicate worker registration
- [ ] `mahavishnu/core/workflow_state.py` — **delete** (the deprecated re-export; 8 live modules import it against its own docstring)
- [ ] `mahavishnu/core/app.py` — repoint `from .routing import RoutingStrategy` (`:143`)
- [ ] `mahavishnu/agents/mahavishnu_agent.py` — repoint `from .routing import ...` (`:40`)
- [ ] `mahavishnu/webhooks/router.py` — repoint `from .routing import ...` (`:27`)
- [ ] `mahavishnu/core/task_audit.py` — the redaction field set (Phase 5 task 3)
- [ ] `mahavishnu/engines/agno_tools/file_tools.py` — derive the allowlist from `config.allowed_repo_paths` (§4.2 row 11)
- [ ] `mahavishnu/mcp/skills_catalog/workflow-status.md` — *"there is no workflow_id to poll"* is **false** after Phase 5
- [ ] `mahavishnu/mcp/skills_catalog/pool-route.md` — the workflow-id promise it already makes
- [ ] `mahavishnu/mcp/agents/mahavishnu-specialist.md` — names a nonexistent `dispatch_to_pool` and the wrong parameter name
- [ ] `docs/mcp/MCP_TOOLS_REFERENCE.md` — the **second** MCP-tools inventory (README names it canonical); also omits the three pool tools
- [ ] `docs/CONFIGURATION.md` — documents the `feature_flags.*` block Phase 3 deletes
- [ ] `docs/adr/017-oneiric-shared-persistence-substrate.md` — **amendment** (Phase 3 task 6 introduces a repo-local state path, the shape ADR 017 supersedes)
- [ ] `docs/adr/009-hybrid-adapter-registry.md` — **amendment** (its supersession chain makes the Oneiric entry-point group canonical, which §4.2 row 1 now counts)
- [ ] `docs/decisions/2026-09-25-langgraph-as-engine-adapter.md` — **the successor** to the settle-vs-langgraph decision Phase 4 currently cites; it records the pool-lane workflow-id failure
- [ ] `docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md` — the **prior failure** of exactly Phase 5's shape (a pool workflow_id that could not be read back)
- [ ] `docs/plans/.archive/2026-08-29-worker-registry-capability-refactor.md`, `docs/plans/.archive/2026-10-12-per-engine-emit-node-dispatch.md` — **cite** in §4.2/Phase 6; they built the conductor
- [ ] `docs/plans/.archive/2026-02-20-status-enum-consolidation.md` — **cite** in §4.2 row 8; the enum consolidation's prior, partial attempt
- [ ] `docs/plans/.archive/2026-05-10-bodai-control-plane-convergence-plan.md`, `docs/plans/.archive/2026-05-11-remaining-work-execution-order.md` — **cite**; the prior convergence program and the `StateManager` move Phase 3 task 0 reverses
- [ ] `tests/unit/test_utility_modules.py` — pins `get_tool_version("trigger_workflow") == "1.1.0"`
- [ ] `tests/unit/mcp/test_server_core.py` — asserts `result["result"]["error"]` (`:257`) and `result["workflow_id"].endswith("_review")` (`:235`)
- [ ] `tests/unit/test_workflow_execution.py` — asserts `"code_review" in workflow_id` (`:140`)
- [ ] `tests/unit/test_mcp_server.py` — the `params={"param1": ...}` (`:337`) and `params={"focus": ...}` (`:424`) calls
- [ ] `tests/unit/test_mahavishnu_config.py` — `:926-933` (the typed `FeatureFlagsConfig`), `:993`, `:1009-1011`, `:1093`
- [ ] `tests/unit/test_config_source_resolution.py` — `:63` (`adapter_registry`), `:74` (`integrations.pydantic_ai_enabled`)
- [ ] `tests/unit/test_config.py` — `:626` (`cfg.pydantic_ai_enabled is False`)
- [ ] `tests/unit/workers/test_shell_command_safety.py` — the `STDERR_PATH_ENV_VAR in command` assertion (`:334-343`) moves to the registry command
- [ ] `tests/unit/workers/test_registry_lookup.py` — extended (key-set assertion)
- [ ] `tests/integration/test_trigger_workflow_e2e.py` — **new** (wiring discipline §4)
- [ ] `tests/integration/test_pool_route_execute_e2e.py` — **new** (wiring discipline §4)

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `mahavishnu demo --help` | every demo listed exactly once | terminal output |
| `pytest tests/unit/cli/test_cookbook_parity.py` | every recipe names a real command; every workflow demo has a recipe | test output |
| `grep -c "DEMO SUB-COMMANDS" mahavishnu/_main_cli.py` | 1 — the marker the cookbook tells implementers to update | command output |
| `mahavishnu demo terminal-claude` | `workflow_id`, `status: completed`, answer echoed | terminal output |
| `mahavishnu demo terminal-codex` | `status: skipped` with a reason, not a failure | terminal output |
| `mahavishnu demo workflow-engine-and-worker` | one `workflow_id`, one span tree, both legs settle | terminal output |
| `mahavishnu workflow sweep --tag <tag>` | workflow id names the task type | terminal output |
| `grep -rn "class TaskRouter" mahavishnu/` | **one** production class — `core/routing.py` is deleted in Phase 3, so this is satisfiable | command output |
| `grep -rn "AdapterType.WORKER" mahavishnu/core/routing.py` | **non-zero after Phase 2** — this is the *live* chain table; the first draft pointed at the dead one | command output |
| `pytest tests/unit/core/test_execution_envelope.py` | the converter's `exit_code` is honestly `None` for the five engines that cannot report one | test output |
| `grep -rn "class TaskRouter" mahavishnu/` **after** Phase 3 | exactly one; `core/routing.py` is gone | command output |
| a boot-time count of registered worker tools | **9** | test output |
| `grep -rn "UnifiedOrchestrator" mahavishnu/` | no production caller | command output |
| `python scripts/audit_orphans.py` | no new orphans | command output |
| `crackerjack run -v -f` | all fast hooks pass | command output |
| `grep -rn "workflow-results/" mahavishnu/core/workflow/outcome_writer.py` | the write path **validates** the id before splicing it | command output |
| `grep -rn "MAX_TIMEOUT" mahavishnu/` | non-zero — the first draft used a constant that does not exist | command output |
| `pytest tests/unit/workers/test_registry_lookup.py` | the YAML registry stays a subset of the code registry | test output |
| `pytest tests/integration/test_trigger_workflow_e2e.py` | each newly reachable adapter resolves and returns non-empty | test output |
| `pytest tests/integration/test_pool_route_execute_e2e.py` | every return path carries a `workflow_id` that resolves | test output |
| the two-leg composition demo, asserting **one `trace_id`** | the engine span and the worker span share a trace — the only check that makes REQ-C05 real | demo output |
| `pytest tests/integration/test_pool_route_execute_e2e.py` | **every one of the 14 return paths** carries a `workflow_id` — including the `worktree_conflict` path at `pool_tools.py:946`, which the first draft's inventory missed | test output |
| `pytest tests/unit/cli/test_cli_wireup_invariants.py` | the boot-time count of registered worker tools is **9** | test output |
| a registry-parity test | every registered MCP tool has a `TOOL_VERSIONS` entry — **9** were missing, including `tasks_handoff_to_workflow` | test output |
| a boot-time count of registered worker tools | **9** — the regression that would catch Phase 3 task 8 silently dropping them | test output |
| `grep -rn "traceparent" mahavishnu/` | non-zero after Phase 4 — context propagation exists | command output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The consolidation touches the executor, the registry, the state store, and the demos at once — a regression in the workflow lane breaks production routing | high | sequence the phases so each lands independently; Phase 1 and Phase 2 change no execution semantics and are the safest first cuts |
| Deleting `UnifiedOrchestrator` removes a capability someone intended to finish | medium | the file has had zero production callers since introduction; its behaviour is recoverable from git; Phase 3 requires the decision be recorded, not assumed |
| One lifecycle enum must serve two substrates with different vocabularies | medium | the superset must include the worker-only members (`input_required`, `blocked`) — §4.8 item 3; the engine-only members are the ones that can be dropped |
| Moving workflow outcomes off `ProcessLocalKV` changes what `get_workflow_status` can find | medium | the file-backed store is a superset of what is kept in memory today; verify the read path before the write path moves |
| The demos grow past a usable length — the harness leg alone is ~115 s | medium | keep the harness demos out of `demo_all`; they are a nightly/CI job |
| Consolidating makes the plan XL and it never ships | medium | §9's decision rule exists to cut scope, not to justify delay; the cut order is documented below |
| `enable_cost_tracking` proves harder to wire than it looks — the cost model has never run | medium | Phase 4 makes it live for one adapter first and measures before extending |
| **Phase 2 makes a substrate routable that an operator only enabled as an *adapter*** — Hatchet and Pydantic-AI are already enabled on this host, and the chains are static | **high** | Phase 2 task 7: build the chain from `app.adapters` at runtime, add an explicit routability flag, and give the operator a kill-switch that does **not** unregister the adapter (unregistering the worker silently drops nine MCP tools) |
| **Two processes write the workflow-state file** — the running server and any CLI that constructs a `MahavishnuApp()` — each holding its own snapshot and rewriting the whole file | **high** | Phase 3 task 6b prunes the file to near-empty and Phase 3 task 6 specifies an **inter-process** lock (`fcntl.flock`), a unique temp name, `os.replace` and `fsync`. Phase 1 *increases* this exposure by making the CLI a first-class workflow producer |
| **Phase 6 collides with the conductor that already exists** — a second composition executor, a second envelope contract, a second data-flow model | **high** | Phase 6 task 1 was rewritten: extend `core/conductor.py`, don't build a second one. Phase 3 deletes `core/unified_orchestrator.py`, which was the *other* orphan in that space |
| **The plan's own §7 acceptance checks were unsatisfiable** — "one production `TaskRouter`" while §6 listed `core/routing.py` for editing; Phase 4 injecting into a Phase 7 artifact | medium | fixed in this revision: `core/routing.py` is deleted in Phase 3, and Phase 4 injects into the worker launch environment that already exists |
| **Every phase carried a "Rollback signal" but no "Rollback action"** — and three of the eight signals described behaviour that was already true, or impossible to observe, before the phase landed | medium | each phase's Integration Contract now needs an actionable signal: a commit to revert, a flag to flip, or a surface to disable — not a symptom description |

### Cut order

If scope has to shrink, cut in this order — the later phases depend on
the earlier ones, not the reverse:

1. **Phase 8's *new* demos and the engine-demo rewiring** — but keep
   the **inventory** edits, and keep the count consistent with the
   shipped set. Cutting the demos while keeping the inventory
   contradicts the plan's own rollback signal.
2. **Phase 7's prompt delivery fidelity** — it is the **cheapest** of
   the three, not the most deferrable: the plumbing already exists
   (`_write_prompt_file` writes an `mkstemp` 0600 file; `render_command`
   already reads it back with the injection property preserved). Only
   the digest handshake is missing. The *readiness* marker is a
   strengthening of an existing mechanism (`_await_ready` already waits
   for the pane to draw — an 8-second heuristic, not an explicit
   marker). Settle-finality is the genuinely new work.
3. **Phase 6's composition** — the demo is the demand signal, and
   nothing else depends on it.
4. **Phase 3's lifecycle-enum merge** — keep the deletion of the
   orphans; the enum merge can follow. **But Phase 7 cannot land before
   the Phase 3 vocabulary exists** — cutting one requires cutting the
   other, or naming Phase 7's vocabulary independently.

**Do not cut:** Phase 1 (the payload trap is live, and it is the trust
boundary), Phase 2 (a dark adapter is worse than an absent one), Phase
3 task 0 (`StateManager` must move before `task_router.py` is
reshaped, or the MCP workflow surface breaks), or Phase 5's workflow
identity (without it the pool lane stays invisible).

**Do not start Phase 2 or Phase 3 until the decision-adapter plan's
`task_router.py` migration has landed** (§4.12.1) — that plan is
mid-flight on the same file, under a hard sequencing rule.

## 9. Decision Rule

**This plan is done when every adapter in `app.adapters` is reachable
from the router and the MCP tool, every execution returns the same
envelope, every demo produces a workflow id, and the ten duplications
in §4.2 have each been resolved to a named winner.**

It is **not** done while a plan says "the adapter exists but the router
cannot select it," or "the demos exercise a path an operator never
takes."

**The model, stated once.** The first draft applied three
incompatible models across Phases 2, 3 and 5 — peer-in-one-registry
(Phase 2), nested-under-the-adapter (Phase 3 task 8), and
owner-of-workflow-identity (Phase 5). Neither prior art the plan
itself cites matches "peer in the same registry": **Temporal** separates
the workflow owner from the activity, and **Airflow** separates the DAG
scheduler from the operator. This plan adopts **Temporal's shape**:

> **Mahavishnu is the Temporal-shaped side. The control plane owns
> workflow identity. A substrate adapter is an Activity — a uniform
> contract — dispatched substrate-obliviously. The substrate never
> owns workflow state.**

Applied uniformly: Phase 2 makes the worker *reachable* (an Activity in
the registry); Phase 3 task 8 keeps the substrate as a leaf the adapter
wraps; Phase 5 mints the pool lane's id **in the orchestration layer**
and passes it down as an opaque correlation id for the substrate to
echo — Temporal's "worker dials the service" shape, and the shape that
satisfies the plan's own §4.8 prior art.

**The decisions this plan does not make for the operator:**

1. **Whether the terminal-worker substrate stays a first-class peer in
   the same registry as the engines**, or becomes a distinct kind of
   step the engines can also call. Both are defensible. This plan
   assumes the first (peer), because it is the smaller change and
   because the engines have no substrate abstraction of their own to be
   unified with (§4.8).
2. **Whether the worker registry is ever consolidated.** The first
   draft said "retire the legacy dict"; the review showed that is a
   schema-union project, not a Phase-3 task (§4.2 row 4). This plan
   records the split and fixes the `command_argv` shape, and leaves the
   union for a separate plan.
3. **How the Oneiric adapter-bridge migration should shape the
   router.** That is owned by the decision-adapter plan (§4.12.1);
   this plan routes around it.

**And two decisions this plan makes, which the reviews forced:**

**Cost accounting is out of scope** (§3 non-goal 8). The plan's goal is a
working control plane, and the cost model has never run — turning it on
is a separate piece of work with its own risk. Time and efficiency carry
the optimization load for now (§2.1).

**This plan is forward-only** (§3 non-goal 10). No deprecation window, no
alias, no re-export shim, no migration of old data. Where a shape, key,
config field or module changes, it changes. This is the repo's recorded
pre-1.0 policy (*replace, not extend*), and it is what makes several
of round 2's corrections cheap rather than expensive: pruning the
469 stored workflow records instead of migrating them, deleting
`core/routing.py` instead of keeping a shim, and renaming
`integrations.pydantic_ai_enabled` instead of aliasing it.

**And the one this plan still does not decide:** whether the Oneiric
adapter-bridge migration should shape the router. That is owned by the
decision-adapter plan (§4.12.1); this plan routes around it.

## 10. Supersedes

This plan replaces:

- `docs/plans/2026-11-01-terminal-cli-harness-demos-and-dispatch-trust.md`
  — its Phases 1 (the three CLI demos) and 3-4 (readiness, integrity)
  become Phase 7 and Phase 8; its Phase 2 (a new `DispatchState` in
  `pools/base.py`) is replaced by Phase 3's reuse of
  `WorkerLifecycleState`; its REQ-009 (engine+worker composition)
  becomes Phase 6; its REQ-010 (the docstring correction) becomes
  Phase 8 task 3.
- `docs/plans/2026-11-01-adapter-composition-executor.md` — its
  Option 3 ("worker as a first-class adapter plus a sequence executor")
  becomes Phase 2 (reachability) plus Phase 6 (sequence), because the
  adapter already exists; its Option 2 (the interop primitive) becomes
  Phase 4's result envelope; its Option 1 ("do not build B, ship the
  demo") is what Phase 6 delivers.

## 11. Multi-agent review record

The plan was reviewed by nine agents on non-overlapping lenses, per the
repo's review protocol (`memory/multi-agent-review-catches-blind-spots`):
seven domain lenses plus two random lenses, with a code-grounding pass
run first and every BLOCKING claim verified against the live code before
acceptance.

| Lens | Agent | Verdict |
|---|---|---|
| Code grounding | `feature-dev:code-explorer` | 2 BLOCKER, 9 IMPORTANT, 10 MINOR |
| Design patterns | `mycelium-core:architect-reviewer` | 3 BLOCKER, 8 IMPORTANT, 5 MINOR |
| Mahavishnu domain | `mahavishnu-specialist` | 1 BLOCKER, 8 IMPORTANT, 8 MINOR |
| Security (random) | `security-auditor` | 1 BLOCKER, 4 IMPORTANT, 3 MINOR |
| MCP surface | `mcp-integration-expert` | 2 BLOCKER, 9 IMPORTANT, 3 MINOR |
| Python implementation (random) | `mycelium-core:python-pro` | 1 BLOCKER + envelope typing |
| Configuration & integration | `oneiric-specialist` | 3 BLOCKER, 8 IMPORTANT, 2 MINOR |
| Cross-ecosystem architecture | `architecture-council` | 5 BLOCKER, 10 IMPORTANT, 5 MINOR — *conditional approve* |
| Reliability / SRE | `mycelium-core:sre-engineer` | 1 BLOCKER + per-phase premise corrections |
| Cross-plan collision audit | `general-purpose` | 19 plans audited; 3 collide, 4 must land first, 5 have shipped but still say active |

### 11.0 The council's model correction

The architecture council's most useful finding was not a bug but a
**model inconsistency**: the plan applied three incompatible models to
the same question — peer-in-one-registry (Phase 2),
nested-under-the-adapter (Phase 3 task 8), and
owner-of-workflow-identity (Phase 5). Neither prior art the plan cites
matches "peer in the same registry": **Temporal** separates the workflow
owner from the activity, **Airflow** separates the DAG scheduler from
the operator. §9 now states **Temporal's shape** once and applies it
uniformly.

It also caught two things that would have been expensive:

- **Phase 3 task 8 would have silently dropped nine MCP tools.**
  `core/bootstrap.py:434-437` derives `app._worker_manager` from
  `worker_adapter.worker_manager`; `mcp/bootstrap.py:451` skips
  `register_worker_tools` when that is `None`. If the adapter stopped
  exposing a `worker_manager` — which is exactly what "the adapter
  wraps the pool" does — **nine worker tools vanish behind a
  `logger.warning`**. It would also have *lost* pool selection rather
  than recovered it, because selection lives in `PoolManager`, above the
  pool.
- **Governance amendments are co-delivered, not follow-up.**
  `docs/decisions/wire-up-contract.md` rule 3 requires that a REQ
  changing a recorded decision amends it **in the same change**. The
  plan changes four: ADR 011 (two-router composition), `CLAUDE.md` §
  "Pool and Terminal Architecture", `docs/pools/POOL_ARCHITECTURE.md`,
  and the 2026-10-14 decision-category plan's sequencing. All four are
  now in §6.

### 11.5 The operability finding

The reliability lens measured the live workflow-state store and found
it is **not a store**: `StateManager._persist` rewrites the entire file
on every mutation, unlocked and non-atomically, under a CWD-relative
path. On this host `data/workflow_state/workflows.json` is **5.2 MB**
with **469** records, of which **77 are permanently stuck in `running`**
— no pruning, no recovery. Phases 4, 5, 6 and 7 each move load onto
it. The plan now states the condition in §4.5, adds the store-hardening
prerequisite to Phase 5, and adds a "one `trace_id` across both legs"
assertion to §7 — the only check that makes REQ-C05 real.

The lens also found that mahavishnu has **zero** OpenTelemetry context
propagation (no `traceparent` anywhere in the package), so "one span
tree" needs explicit `TRACEPARENT`/`TRACESTATE` injection into the
Phase 7 launcher environment and into each engine's submission path.
Phase 4 now says so, and says why a fragmented tree is worse than none.

### 11.6 The cross-plan audit

Nineteen live plans were audited against this one. Three collide:

| Plan | Collision | Resolution |
|---|---|---|
| `2026-10-14-decision-adapter-category` | **hard sequencing rule 3** — the `task_router.py` migration must complete before the `decision/` category is consumable | §4.2 row 2's winner reversed; this plan routes around it |
| `2026-10-03-eval-adapter-phase1` | `core/config.py` allowlist lives inside the `AdapterRegistryConfig` this plan deletes; two of its task anchors point at a module that no longer exists | lands **after** consolidation Phases 1–3, re-anchored. It adds a *fourth* adapter listing, so it does not pre-solve any of this plan's work |
| `2026-10-30-task-workflow-backlink` | none — the id format is compatible with session-buddy's shared `WORKFLOW_ID_PATTERN` | this plan's Phase 5 **unblocks** its live verification (its finding B5 is exactly the missing `workflow_id`) |

Four more must land first, or the consolidation rebases against them:
`agno-failover` (`core/config.py`), `bifrost-bodai-cache-wiring` Phase 5
(`workers/registry.py`, `pools/manager.py`), `otel-metrics-service`
Phase 3 (`core/observability.py`), and the decision-adapter plan.
Five plans have **already shipped** but their frontmatter still says
active — status drift this plan does not inherit.

### 11.1 Cross-reviewer BLOCKERs (3+ lenses agreed)

**B1 — The duplicated enums.** The design-patterns, domain,
code-grounding, and Python-implementation lenses all independently found
that `core/routing.py:25`, `core/workflow_execution.py:24` and
`core/cost_optimizer.py:31` import the **3-member**
`metrics_schema.AdapterType`, while `core/adapters/base.py:10` defines
a **6-member** one. The plan's Phase 2 and Phase 4 instructions were
`AttributeError`s as written. Verified by runtime probe:
`metrics_schema.AdapterType.WORKER` → `AttributeError`. **Fix:** §4.2
row 9, Phase 2 task 0.

**B2 — `StateManager` must move before `task_router.py` is reshaped.**
The domain, MCP-surface, and code-grounding lenses all found that
`app.workflow_state_manager` **is** a `task_router.StateManager`
instance (`core/bootstrap.py:620,633`) with ~25 production consumers,
including the MCP workflow surface Phase 5 depends on. The first draft
called this "two duplicate stores" and would have deleted the class.
**Fix:** §4.2 row 6, Phase 3 task 0.

**B3 — The worker-registry winner was inverted.** The domain and
configuration lenses both found that the legacy `WORKER_REGISTRY` (43
entries) is the **dispatch** source of truth and the settings registry
(16 entries) a capability overlay with a **different schema** — and
that `MahavishnuSettings()` bare does not read YAML (0 entries), so the
legacy dict is the only unconditionally-populated registry. The first
draft had it backwards and quoted the docstring backwards too.
**Fix:** §4.2 row 4, Phase 3 task 4.

### 11.2 Single-lens BLOCKERs

**B4 — the envelope is a trust boundary.** The security lens found that
the first draft's "flatten caller `params` into the top level" plus
Phase 2's reachability would hand any `trigger_workflow` caller the
substrate selector, the permission-mode selector, and the fan-out
count — with `count` unbounded (`worker.py:217` checks only `< 1`),
`timeout` accepting `"inf"` (`shell_backend.py:188`), and
`worker_type` selecting any registered type including
`permission_mode="yolo"` ones. **Fix:** §4.11, Phase 1 task 1.

**B5 — the wrong docstring was targeted.** The code-grounding lens
found that the misleading *"Prefect → pool → worker → terminal"*
cross-reference lives in `demo_workflow_multi_pool_handoff`
(`cli/demo_cli.py:3642-3643`), not in `workflow-pool-worker-terminal`,
whose own docstring is honest. **Fix:** Phase 8 task 3.

**B6 — three live terminal-state vocabularies.** The MCP-surface lens
found that `get_workflow_status` and `workflow_get_outcome_tool` report
**different terminal states for the same workflow**, and that
`"partial"` is persisted as `"cancelled"`
(`core/workflow_execution.py:346,405` vs
`core/models/persistence.py:55`). **Fix:** Phase 4 task 4.

**B7 — `AdapterRegistryConfig` is a config-only ghost.** The
configuration lens found no implementation anywhere: no
`core/adapter_registry.py`, `settings.adapter_registry` read by no
runtime code, and `tests/unit/test_workflow_cli.py:102` asserting an
import of a module that does not exist — in a `main()`-based script
that never runs in CI, so the failure is invisible. **Fix:** §4.2
row 10, Phase 3 task 7.

### 11.3 What the review did *not* overturn

Every lens that checked the plan's **findings** confirmed them: the
"zero overlap" payload probe, the CLI `{"task": ...}` key bug, the
OpenHands V0 defect, the three-of-six dark adapters, the dead
`enable_cost_tracking` parameter, the zero-caller
`UnifiedOrchestrator`, the unenforced `enable_cost_tracking`, the
no-dsl finding, the 14-enum count, and the missing
`hatchet_enabled` default. The code-grounding lens independently
checked **34** `file:line` citations and all resolved.

The review's consistent verdict was that the plan's **diagnostics** were
sound and its **prescriptions** were not. That is what §4.2, §4.11,
§4.12 and §4.13 now carry.

### 11.4 Round 2

Round 1 ran **ten** lenses (the table above lists ten rows; the
cross-plan collision audit was the tenth). Round 2 ran **six** lenses
chosen to be *different in kind* from round 1's: persistence and store
semantics, deployment and operational safety, ecosystem-consumer impact,
platform API surface, a "does this actually work" implementation pass,
and a historical-patterns sweep.

**Round 2's own audit corrected its scope claim.** The first draft of
this section asserted that all six were "the lenses round 1 did not
cover". That is **wrong for five of six** — round 1's reliability lens
already produced §2.1's third criterion and §4.5's store findings;
round 1's architecture council was the cross-ecosystem lens; round 1's
MCP lens was the platform-API lens; round 1's code-grounding and
Python lenses were the implementation lenses. **Only the
historical-patterns sweep was genuinely uncovered.** Round 2's value was
therefore not *new ground* but **depth and adversarial intent**: the same
concerns, re-asked against a materially revised plan, by lenses that
knew what round 1 had already found and were told to look past it.
That intent is visible in the results — round 2 found the plan's
*corrections* were themselves wrong in eight places, which round 1,
checking the first draft's findings, could not have done.

Round 2's findings are recorded in §11.7.

### 11.7 Round 2 — six lenses, and what they overturned

Round 2 ran six lenses against this revision. Every BLOCKING claim was
verified against the live code before acceptance — several were
re-verified by hand after the lens reported them, and the lens's own
citations were checked line by line.

| Lens | Agent | Verdict |
|---|---|---|
| Persistence and store semantics | `database-operations-specialist` | 8 BLOCKING, 9 IMPORTANT, 3 MINOR — measured the live store (5,222,377 bytes / 469 records / 77 stuck / 10 × 390 KB blobs) |
| Deployment and operational safety | `deployment-engineer` | 5 BLOCKING, 7 IMPORTANT, 6 MINOR — *conditional approve* |
| Ecosystem-consumer impact | `general-purpose` | 2 BLOCKING, 5 IMPORTANT, 4 MINOR — read session-buddy, crackerjack, mcp-common and `~/.claude` |
| Platform API surface | `mycelium-core:platform-engineer` | 5 BLOCKING, 7 IMPORTANT, 5 MINOR |
| "Does this actually work" (implementation) | `feature-dev:code-architect` | 12 BLOCKING, 11 IMPORTANT, 9 MINOR — *revise before executing* |
| Historical patterns | `Explore` | 4 BLOCKING, 6 IMPORTANT, 8 MINOR — swept 47 decisions, 24 ADRs, 30 live plans, ~250 archived plans |

**Round 2's cross-reviewer BLOCKERs (3+ lenses agreed):**

**R-B1 — the envelope conflated two `type` semantics.** Lenses 2, 3, 4
and 5 found it independently, and it is the load-bearing error of the
whole plan: `TaskType` is a *routing* classification
(`workflow`/`ai_task`/`rag_query`/…) while the adapters branch on
`code_sweep`/`quality_check`/`focused_review`/`ingest`/`query` —
**zero overlap**. Constraining `task["type"]` to the enum would have
broken llamaindex's query path, agno's task-type selection, prefect's
`quality_check` operation, the shipped `mahavishnu workflow
quality-check` command, the `jot_dispatch` lane, the tool's own
documented example, and two live tests. **Fix:** §4.11, §4.2 row 12,
Phase 1 task 1 — the envelope carries `routing_type` (bounded,
server-derived) and `operation` (free-form, adapter-facing).

**R-B2 — `TaskParams` as a closed model silently dropped eleven live
adapter keys.** Lenses 2, 4 and 5 agreed, with lens 5 adding that the
adapters call `.get()` on `params`, so it must also be handed over as a
**plain dict**. **Fix:** Phase 1 task 1 — `extra="allow"` plus an
explicit passthrough, and the projection emits a dict.

**R-B3 — both version classifications were wrong.** Lenses 2 and 4
agreed, against the repo's own policy at `mcp/tool_versions.py:8-10`.
Phase 1's request change is not "additive new top-level keys" — the
envelope's key set is unchanged and what changed is the *semantics* of
`params` and `task_type`. Phase 4's arithmetic was also internally
contradictory (`1.1.0 → 2.0.0` while Phase 1 sets `1.2.0`). **Fix:**
Phase 1 task 2 and Phase 4 task 6 — and with the corrected envelope
design the Phase 1 change really is MINOR, so the classification now
follows from the design rather than being asserted.

**R-B4 — Phase 2 pointed at a chain table that is dead in production.**
Lens 5 found it; it is the finding that would have made **REQ-C01 false
on the day Phase 2 landed**. `core/task_router.py` has no
`generate_fallback_chain` at all — the live table is
`core/routing.py:DEFAULT_FALLBACK_CHAINS`, and `task_router.py`'s own
preference orders resolve adapters through an `AdapterManager` that is
**always empty in production**. **Fix:** Phase 2 task 2 — both tables,
with the live one named; and §6's `core/routing.py` line reconciled with
it.

**R-B5 — Phase 6 would have built a second composition executor.** Lens
6 found it against the repo's own history: `core/conductor.py` **is** a
shipped DAG composition executor with dependency-ordered data flow
across adapters, built by two shipped plans, with integration tests —
and the plan asserted twice that "the piece does not exist". The real
gap is a **one-line stub** (`execute_capability` returns
`status="planned"`). **Fix:** §4.15, Phase 6 task 1 — extend the
conductor.

**R-B6 — the store inventory was wrong in a way that drove everything
downstream.** Lens 1 found that the plan's "four persistence trails" are
**two backing stores and five key namespaces**, that the trail the plan
called "the durable MCP KV" is the same process-local dict
(`core/state_backends/mcp.py`'s own docstring says so), and that the
trail the inventory omitted is the pool lane's own (`routing/v1/`). The
durable store the repo already has is `core/event_store.py` (PostgreSQL),
already used by the pool lane's idempotency path. **Fix:** §4.2 row 6,
Phase 3 tasks 6 and 6b.

**R-B7 — the pool lane's workflow record had nowhere to live.** Lens 1
found that Phase 5 task 0's two options both violate §2.1 (even one
write to the whole-document store is a 5.2 MB rewrite) and that the
missed option — per-key substrate records with a `get_workflow_status`
fallback — is the only one that satisfies it. Lens 5 separately found
that `register_pool_tools(mcp, pool_manager)` has **no store access at
all**, so Phase 5 could not write a record as written. **Fix:** Phase 5
tasks 0 and 2.

**R-B8 — Phase 5 repeats a documented 2026-08 failure.** Lens 6 found
`docs/feature-tracking/2026-09-25-pool-worker-mcp-audit.md`: a
pool-lane `workflow_id` that could not be read back, with the cause
recorded as *"durable key-value persistence not configured for
`workflow-results/{workflow_id}/`"*, and
`docs/decisions/2026-09-25-langgraph-as-engine-adapter.md` calling that
prerequisite *"more load-bearing than it appeared"*. **Fix:** Phase 5
depends on the store landing, and the read-back assertion is added to
its Integration Contract.

**Round 2's single-lens BLOCKERs** — the remaining findings are recorded
in the phases they affect: the repository allowlist's four
implementations and hardcoded `/Users/les/Projects` (§4.2 row 11,
Phase 5 task 5); the caller-controlled `task_type` reaching a Prometheus
label and the workflow id (§4.11); the write/read validation asymmetry
in the outcome writer (§4.11, Phase 3 task 6); `cancel_workflow` being
a no-op in every adapter (Phase 3 task 3); the missing `PARTIAL` in the
lifecycle superset (Phase 3 task 5); the health feed's bare-settings
probe making its own rollback signal unreachable (Phase 2 task 6); the
missing routability kill-switch (Phase 2 task 7); `pydantic_ai`'s boot
failure (Phase 2 task 1); the unenforced reduced-permission-mode
control (Phase 6 task 4); the launcher's stderr loss (Phase 7 task 3);
the absent dispatch record (Phase 7 task 1); the fourth envelope
builder (§4.4); the unversioned-tool class being nine wide, not three
(Phase 5 task 8); the false cross-plan claims about the backlink plan
(§4.12.4, §11.6); and the task-numbering ambiguities (Phases 5, 6, 8).

**What round 2 did *not* overturn.** The §4.2 duplication table's
*diagnoses* — all ten original rows still name the right duplications,
and two more were added. The §4.11 trust-boundary analysis. The §9
Temporal-shaped model. The §4.5 store measurement. The §4.8 prior-art
convergence. The decision that cost accounting is deferred. And the
core claim of the plan — that the control plane should own workflow
identity and dispatch substrate-obliviously — which no lens disputed.

**Round 2's own caution, recorded for the next reviewer.** Two of the
six lenses re-raised `except TypeError, ValueError:` as a Python 2
syntax error across ~45 files. It is **not** a defect: **PEP 758**
allows unparenthesized multi-exception `except` in **Python 3.14**,
which is this repo's target. Verified by import. No action.

## References

- `mahavishnu/core/adapters/base.py:43` — `OrchestratorAdapter`, the
  interface every engine and the worker adapter already share.
- `mahavishnu/core/adapters/worker.py:33` — `WorkerOrchestratorAdapter`.
- `mahavishnu/core/bootstrap.py:374-377` — the worker adapter's
  registration.
- `mahavishnu/core/workflow_execution.py:36` —
  `initialize_workflow_state`, the one workflow-record creation point.
- `mahavishnu/core/workflow_execution.py:182` — `process_single_repo`,
  the one-adapter-per-repo fan-out.
- `mahavishnu/core/workflow_execution.py:635` —
  `execute_workflow_with_fallback`, the fallback-not-sequence executor.
- `mahavishnu/core/routing.py:138` — `TaskRouter.DEFAULT_FALLBACK_CHAINS`.
- `mahavishnu/core/cost_optimizer.py:43` — `ADAPTER_COSTS`.
- `mahavishnu/workers/contract/state.py:6` — `WorkerLifecycleState` and
  its transition table.
- `mahavishnu/cli/demo_cli.py:4098-4108` — the proven two-stage
  composition.
- `docs/cookbook/workflows.md:204` — how a workflow is "generated" today.
- `docs/decisions/wire-up-contract.md` — the policy this plan implements.
- `scripts/audit_orphans.py`, `scripts/audit_requirements.py` — the
  gates.
