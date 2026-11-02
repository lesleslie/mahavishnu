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
| 1 | **Adapter registry** | five listings: `app.adapters` (`core/app.py:254`), `task_router.AdapterManager.adapters` (`core/task_router.py:127`), `_ENGINE_LOCATIONS` (`engines/__init__.py:104`), `settings.worker_registry.entries`, and `AdapterRegistryConfig` (config-only ghost) | `app.adapters` as the single **dispatch** registry | `AdapterManager.register_adapter` is called **only from test modules** — in production that registry is always empty. The other listings have distinct jobs (capability discovery, capability metadata) and are not duplicates of it |
| 2 | **Router** | `core/routing.py:TaskRouter` (chains, live) vs `core/task_router.py:TaskRouter` (registry + stats + `CapabilityRouter`) | **`core/task_router.py` survives**; `core/routing.py`'s chains fold into it | **reversed from the first draft.** `docs/decisions/2026-10-14-decision-adapter-category.md` rule 3 is a hard sequencing rule: the `task_router.py` migration to Oneiric's `AdapterBridge` must complete, and `core/routing.py`'s router is not part of that migration |
| 3 | **Orchestration entry point** | `workflow_execution.execute_workflow_with_fallback` vs `task_router.execute_with_fallback` vs `UnifiedOrchestrator.execute_workflow` | `workflow_execution`, **porting** what `UnifiedOrchestrator` had | `UnifiedOrchestrator` has zero production callers, but it is the only implementation of *N independent tasks each with its own fallback chain*, and the only implementation of **cancellation** — `workflow_execution` has no cancel path at all. Deleting it is an undeclared scope loss |
| 4 | **Worker registry** | legacy `WORKER_REGISTRY` (`workers/registry.py:178`, **43** entries) vs `settings.worker_registry.entries` (`core/config.py:1890`, **16** entries) | **the legacy dict for dispatch**; the settings entries for capability metadata and validation | **reversed from the first draft**, which had it backwards. The YAML is a strict *subset* — 27 types exist only in code, including `shepherd` (the pool's default worker type) and `openhands`. `MahavishnuSettings()` bare does **not** read YAML (`get_settings()` → 16 entries; bare → 0), so the legacy dict is the only unconditionally-populated registry. The two are also **different schemas**: `WorkerEntry` has no `permission_mode`, `category`, `endpoint`, `mcp_server`, or `error_markers`, and has `provides`, which `WorkerConfig` cannot express |
| 5 | **Worker substrate** | `WorkerManager` + `ShellWorker` (one-shot; vocabulary `WorkerStatus`) vs `DurableWorkerManager` + `WorkerLifecycleState` (interactive tmux + settle) vs `SettleState` | decided in Phase 3, as an *execution* vocabulary in `core/status.py` | three vocabularies, not two. `WorkerLifecycleState` has no `TIMEOUT`/`CANCELLED` and legally allows `COMPLETED → READY → RUNNING` — so adopting it unchanged would silently defeat Phase 7's "settled is final" |
| 6 | **Workflow state store** | **four** persistence trails: `app.workflow_state_manager` — which **is** a `task_router.StateManager` instance (`core/bootstrap.py:620,633`), file JSON at `data/workflow_state/workflows.json`; `WorkflowOutcome` → `ProcessLocalKV` (`core/kv_store.py:27`); `workflow/v1/{execution_id}` → the durable MCP KV (`core/repository_surface.py:72`, a **disjoint id namespace** — a bare uuid4, not `wf_*`); and `workflow-results/{workflow_id}/` (the KV path the shared id-guard was written for, `mcp/tools/_workflow_id_guard.py:4`) | one durable store; `StateManager` relocates out of `task_router.py` first | **the first draft counted these as three stores; they are four.** The two `StateManager` instances are the same class writing the same file; `ProcessLocalKV` is **process-local**; and the `workflow/v1/` trail uses a **different id shape** — `get_workflow_status` reads only `app.workflow_state_manager` (`mcp/server_core.py:583`), so a `workflow/v1/`-only record is invisible to it |
| 7 | **Worker wrapper** | `WorkerOrchestratorAdapter` (wraps `WorkerManager`) vs `MahavishnuPool` (wraps the same `WorkerManager`) | the adapter keeps the orchestrator-facing port; the pool keeps its leaf-wrapper rule | `pools/mahavishnu_pool.py:5-12` explicitly warns against inverting the layering ("Do NOT rewrite `execute_task` to call `pool_manager.route_task`"). The fix is a narrow `PoolRouter` port, not the adapter wrapping the pool |
| 8 | **Lifecycle vocabulary** | **14** enum names across **11** modules encode "where is this execution" | one **execution** lifecycle in `core/status.py` — **not** a 14-way superset | `core/status.py` is already the declared home ("Consolidated status enums for Mahavishnu… Issue: MHV-008 - Status Enum Consolidation"). `PoolStatus` (a resource), `PlanStatus` (a document), `WorkerCapabilityState` (a probe), and `SettleState` (a merge run) are **not** execution lifecycles and must stay separate — merging them yields a union where most members are invalid for most subjects |
| 9 | **Adapter/task enums** | `AdapterType` in `core/adapters/base.py:10` (**6** members) vs `AdapterType` in `core/metrics_schema.py:34` (**3**); `TaskType` in `core/metrics_schema.py:42` (**6**) vs `TaskType` in `core/task_router.py:82` (**5**, no `CRITICAL_TASK`) | the `core/adapters/base.py` pair | **the most consequential duplication, and the first draft missed it.** `core/routing.py:25`, `core/workflow_execution.py:24` and `core/cost_optimizer.py:31` all import the **3-member** `metrics_schema` enum — so the router literally cannot name `worker`, and the plan's Phase 2 and Phase 4 instructions were `AttributeError`s as written |
| 10 | **`AdapterRegistryConfig`** | `core/config.py:2000-2051` + the `adapter_registry:` YAML block + an untyped `feature_flags:` YAML block | **remove** | a config-only ghost. `HybridAdapterRegistry` was deleted in commit `db06fc87`; the config model outlived its implementation. `settings.adapter_registry` is read by no runtime code, and there is no `core/adapter_registry.py` |

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
| `core/task_router.py:842` (`execute_with_fallback`) | `{"task_type", "prompt", "repos"}` |

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
  records, of which **77 are permanently stuck in `running`** — no
  pruning, no recovery. Two concurrent workflows can lose each other's
  records, and a server started from a different working directory
  writes a *different* file.

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
implementors, with third-party CLI adapters for `claude`, `codex`,
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
| `type` | `TaskType(task.get("type", "ai_task"))` is an **unguarded enum cast** (`workflow_execution.py:644`) that raises a bare `ValueError`; the string also lands in a Prometheus label (`workflow_execution.py:48-52`) and a workflow id (`:42`) | constrained to `TaskType` members; the **validated** value used for both |

There is no command injection from an arbitrary `worker_type` — an
unregistered name fails loudly before a command is built. The exposure
is *which registered substrate*, *which permission mode*, and *how
many*. The envelope therefore must be a **Pydantic model with
separated namespaces**: `TaskEnvelope(type: TaskType, id: str,
params: TaskParams)`, where `type` and `id` are **not** members of
`TaskParams`, so caller data cannot shadow a control field.

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

Nineteen other plans are live. Three of them collide with this plan;
the rest do not. The collision audit is a **prerequisite** — Phase 1
cannot be written correctly without knowing who owns what.

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
  It touches workflow-id semantics and the task dict — the same surface
  as §4.1 and §4.4. It must be sequenced **after** Phase 1's envelope
  lands, or it will bind to a task shape that no longer exists.
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

## 5. Implementation Phases

### Phase 1: One task envelope

**Goal:** every entry point builds the same **typed** envelope, and
every adapter reads the same keys from it — with the envelope acting as
the trust boundary it is now (§4.11).

**Tasks:**

1. **Define the envelope as a Pydantic model** — `core/task_envelope.py`
   — with **separated namespaces**:
   ```python
   class TaskParams(BaseModel):
       """Caller-supplied parameters. Control fields are NOT members."""
       prompt: str = ""
       count: int = Field(default=1, ge=1, le=50)
       timeout: float = Field(default=300, gt=0, le=MAX_TIMEOUT)
       worker_type: str | None = None      # allowlist-checked in TaskEnvelope
       task_type: str = "general"
       repos: list[str] = Field(default_factory=list)

   class TaskEnvelope(BaseModel):
       type: TaskType                       # the ROUTING field, constrained
       id: str
       params: TaskParams = Field(default_factory=TaskParams)
   ```
   `type` and `id` are **not** members of `TaskParams`, so caller data
   cannot shadow a control field (§4.11).
   - `type` is constrained to the `TaskType` members, replacing the
     unguarded `TaskType(task.get("type", "ai_task"))` cast at
     `core/workflow_execution.py:644` with a `ValidationError`.
   - `worker_type` is validated against an **allowlist of one-shot agent
     CLIs only** — `terminal-claude`, `terminal-qwen`, `terminal-codex`.
     Everything else is rejected at the boundary, so the registry
     membership check at `workers/manager.py:483` becomes a backstop
     rather than the only guard.
   - `count` is bounded 1..50, matching the existing precedent at
     `mcp/tools/worker_tools.py:67`.
   - `timeout` is a bounded finite `float` — `"inf"` is rejected.
   - `prompt` is length-capped, following the pattern in
     `core/task_models.py`.

   **The envelope must also carry the keys adapters read today**:
   `workflow_name` (`engines/hatchet_adapter_impl.py:232`), `single_repo`
   (injected by `core/workflow_execution.py:198`), and `preference_order`
   (`core/task_router.py:849`).

2. **Change `trigger_workflow` (`mcp/server_core.py:477`) to build the
   envelope.** The caller's dict goes into `params` and is validated as
   `TaskParams` — it is **not** flattened into the envelope's top level.
   The first draft of this plan flattened it, which would have put
   caller-controlled values directly into the worker's control namespace
   (§4.11).
   - There are **three** workflow-record creation points, not one:
     `initialize_workflow_state` (`core/workflow_execution.py:36`),
     `trigger_workflow`'s timeout branch (`mcp/server_core.py:524`, id
     `wf_timeout_<hex>_<type>`), and its exception branch (`:556`, id
     `wf_error_<hex>_<type>`). All three must build the envelope.
   - `adapter` **stays a `str`** — a static enum would advertise
     adapters the running server may not have registered (`hatchet` is
     off by default; `pydantic_ai` is never registered). The docstring
     is updated to name the full `AdapterType` set and point at
     `list_adapters` for runtime truth, and a pre-flight check returns
     a structured error naming the runtime-available adapters rather
     than letting `prepare_execution` raise deep in the call.
   - Bump `tool_versions.py` `"trigger_workflow"` from `1.1.0` to
     `1.2.0` (MINOR — additive new top-level keys).

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
   new flag — one of them should die.

2. **Add `AdapterType.WORKER` and `AdapterType.HATCHET` to the
   routing chains** — in `core/task_router.py`, which survives per
   §4.12.1, not `core/routing.py`. The worker needs a **new
   `TaskType.CLI_TASK`** (or equivalent). It must **not** be put ahead
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
   and reports `entities_count` as a boolean `0/1`. A **worker-only**
   deployment (engines off, `workers.enabled: true`) would get
   `errors_total=1` → `/health` returns **503 degraded** even though the
   worker adapter is healthy. Include the worker flag and
   `hatchet_enabled`, and make `entities_count` the **count** of enabled
   adapters.

**Exit criteria:** every registered adapter is selectable and named in
the MCP tool's documentation; no chain member lacks a registration path;
`/health` does not report degraded on a worker-only deployment.

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
   production importers of `core/task_router.py` must be repointed:
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
   `AdapterManager`. Port `cancel_workflow` too: `workflow_execution`
   has **no cancel path at all**, and the adapters already declare
   `can_cancel_workflows=True`. `get_adapter_health` comes free from
   `app.adapters`. `UnifiedOrchestrator` then dies as a *module* with
   its capability preserved.

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

6. **Workflow state store (§4.2 row 6).** One durable store, and a
   **store interface** rather than a file swap. `StateManager._persist`
   (`core/task_router.py:217`) rewrites the **entire** JSON file on
   every mutation, **unlocked**, under a **CWD-relative** path
   (`_DEFAULT_STATE_DIR = Path("data/workflow_state")`, `:189`) — so a
   server started from a different directory writes a different
   `workflows.json`, and two concurrent workflows can lose each other's
   records. Introduce a `WorkflowStore` protocol with the file-JSON
   implementation behind it; the repo already has
   `core/state_backends/mcp.py` to build on.
   **Do NOT move the outcome writer off the substrate.** The
   `2026-10-31-substrate-calltime-rewire` plan deliberately rebound
   `core/workflow/outcome_writer.py` to the substrate facade
   (`core/substrate.py`), so a sibling component reading
   `workflow-results/{workflow_id}/` through the `mahavishnu_kv_*` tools
   sees the record — a cross-component contract, not a private store.
   The gap is that the substrate's current backend is process-local
   (`core/kv_store.py:27`), so outcomes do not survive a restart. The
   fix is a **durable backend behind the substrate facade**, not a
   relocation; and it belongs to the substrate plan's owners.

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

2. Have all six adapters return it — or, lower-risk, have the control
   plane convert at the boundary via
   `ExecutionEnvelope.from_adapter_result(adapter_type, raw)`. Pick
   one and say so; the first draft's "wrap rather than rewrite" left
   REQ-C04 false at the type level, since
   `OrchestratorAdapter.execute` is declared `-> dict[str, Any]`.

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
   - inject `TRACEPARENT` / `TRACESTATE` into the **Phase 7 launcher's
     environment** — that launcher already "reads the prompt into
     `MAHAVISHNU_PROMPT` and exports it", so this is free;
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
   change (`1.1.0 → 2.0.0` per `mcp/tool_versions.py:8-10`).

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

0. **Make the state store safe for the hot path first** (§2.1).
   `StateManager._persist` rewrites the whole JSON file on every
   mutation, unlocked. Either the pool lane writes its workflow record
   **once at completion** (as `finalize_workflow_execution` does today),
   or the store gets a lock + atomic replace before the lane joins it.
   `pool_route_execute` is the path `CLAUDE.md` § Tool Preferences tells
   every agent to use; adding a full-file-rewrite write to it would
   regress the documented ~200–500 ms routing overhead.

1. **Mint the workflow id before the selector gate**, so it exists on
   **every** return path. `pool_route_execute` has ~10 distinct return
   paths (`mcp/tools/pool_tools.py:790, 797, 846, 862, 884, 900, 955,
   1010` and the outer handler); nine return a bare status dict, so a
   client doing `result["workflow_id"]` gets a `KeyError` on the
   rate-limited and invalid-selector paths. The idempotency-duplicate
   path (`{"status": "duplicate", "result": cached}`) must return the
   **original** id, surfaced at the top level.

2. **Give the pool workflow record the fields
   `get_workflow_status` reads** (`mcp/server_core.py:609-621`): set
   `task["type"]` (e.g. `"pool_dispatch"`), populate `results`, and set
   a terminal `status` on completion. Otherwise the demonstration
   "passes" while reporting `task_type: "unknown"`,
   `repos_processed: 0`, `results_count: 0` — the surface-health
   illusion.

3. **Persist a redacted summary, not the prompt.** The pool task is
   `{"prompt": prompt, "timeout": timeout}`
   (`mcp/tools/pool_tools.py:804-806`), and the prompt routinely carries
   repo contents, diffs and file bodies. `StateManager.create` stores
   `dict(task)` verbatim (`core/task_router.py:273`) and
   `core/task_audit.py` has a redaction helper the store does not use.
   Persist a summary — prompt length, digest, task class, caller kind —
   or pass it through the existing helper.

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

5. **Do not repoint `tasks_handoff_to_workflow` onto the pool lane.**
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

5a. **The workflow id must satisfy the shared two-repo pattern.**
   `mcp/tools/_workflow_id_guard.py:21` defines
   `^[A-Za-z0-9._-]{1,128}$`, and session-buddy mirrors it byte-for-byte
   with the comment that *"the two repos must agree on what a workflow
   id is, otherwise a value that one side accepts would be rejected (or,
   worse, used unsafely) by the other."* Both sides forbid `.`/`..`
   segments because the id is spliced into
   `workflow-results/{workflow_id}/`. The proposed ids
   (`wf_<hex>_terminal`, `wf_<hex>_composition`) are pattern-safe —
   but any shape change requires a **coordinated session-buddy change**.

5b. **Decide the pool lane's identity vs the existing
   `execution_id`.** `pool_tools.py:919` mints an `execution_id` that
   is not surfaced in the response; the worktree branch is named
   `f"feature/{execution_id}-{uuid4().hex[:8]}"`. State whether
   `workflow_id` replaces or derives from it, and surface it under a
   distinct key if it stays distinct.

7. **Keep the routing semantics untouched.** The decision-adapter
   plan's Phase 1 makes this tool route live through the `decision`
   category, gated on a **7-day disagreement test**
   (§4.12.1). This plan adds identity, not routing — and must not
   schedule against a moving target.

8. **Register `pool_route_execute` in `TOOL_VERSIONS`.** It is
   **absent** (`mcp/tool_versions.py:71-78` registers the other seven
   pool tools but not this one), so it has no version to bump and is
   invisible to `discover_tools` — it appears in neither
   `loaded_tools` nor `not_loaded_tools`. Add it (and `pool_spawn` /
   `pool_bootstrap`, the same class of gap) while here.

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

1. Add a **sequence** entry point beside
   `execute_workflow_with_fallback` (`core/workflow_execution.py:635`):
   stages run **in order**, each consuming the previous one's output.
   This is the piece that does not exist — the fallback chain is
   priority order, not data flow, and conflating them is a rejected
   design. This is **distinct** from the multi-task batch loop ported
   from `UnifiedOrchestrator` in Phase 3: a batch runs N independent
   tasks, each with its own fallback; a sequence threads one into the
   next.

2. **Each stage names its adapter explicitly; the router is not
   consulted inside a stage.** The router selects *within* a stage
   (a stage may have its own fallback chain); it never selects *across*
   stages (§4.13). Without this rule, "prefect by default" and
   "terminal-claude" are two different selection mechanisms and the
   composition is not the thing the plan describes.

3. **Failure policy:** a failed stage **aborts** the sequence, and the
   workflow reports **which** stage broke. `stage_index` and
   `stage_count` go into the envelope's identity fields.

2. **Reuse the threading** from `demo workflow-pi-then-local`
   (`cli/demo_cli.py:4098-4108`), where stage one's output is folded
   into stage two's prompt — but promote it **with its discipline**.
   The demo's threading is a **string splice, not a data-flow
   contract**: `pi_result.get('output', '')` has a **silent
   empty-string default**, so a stage 1 that produced no output yields
   a *successful but empty* stage 2 — §4.8 item 4's failure mode, in
   the very code the plan wants to promote. **Stage one's output must
   be required**: missing or non-string output ⇒ stage 1 fails ⇒ stage
   2 does not run.

2a. **A sequence is a linear list of stages: no branching, no fan-out,
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
     opt-in;
   - mark the second leg's input as **derived** in the span and metric
     labels, so an operator can tell an injected leg from a direct one.

5. **Keep the executor a *sequence*, not a second DAG.** Prefect is
   already in the stack; mahavishnu does not need its own DAG engine.

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

1. **Settled is final.** The pool is the single writer of a dispatch's
   state; a worker reports an *outcome* and the pool decides the
   *state*. A later poll — the worker's progress callback, a
   `pool_monitor` read — may not move a settled dispatch back to
   running. The rule is enforced at the **aggregate layer**
   (`pool_manager.aggregate_results`, `pools/manager.py`), not only at
   the dispatch record. This is the "a stale poll can assert a
   completed" hole.

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
   side effect of the demo surface. Accept it explicitly or add a
   demo-mode flag that skips `create_session_checkpoint`.
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
exists and nothing fails. That drift is the same failure mode as the
dark adapters, one layer down, so this phase closes it.

15. **Recipe 1 — PiPool → MahavishnuPool handoff** (`docs/cookbook/workflows.md:27`).
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
16. **Recipe 2 — PiPool 2-turn cascade** (`:122`). Same treatment: it
    gains the `workflow_id` from Phase 5. This recipe is *already* a
    sequence — two ordered turns on one pool — so it is a second
    candidate for the Phase 6 executor alongside Recipe 1. Its closing
    cross-reference ("For a true multi-pool handoff (source → target),
    use `workflow-multi-pool-handoff` instead") must also point at the
    new `workflow-engine-and-worker` recipe.
17. **Add a recipe for each new demo** (task 7 and 8 above), following
    the file's existing structure (Goal, Substrates exercised,
    Prerequisites, The command, What you'll see, Troubleshooting, Notes)
    and adding a row to the recipe index with its flavor:
    - **`terminal-claude`** — the one-shot CLI harness: what
      "the prompt rides the launch, not the TUI" looks like from the
      outside; the skip path when the CLI is absent or
      usage-limited; and how to read the completion marker.
    - **`workflow-engine-and-worker`** — the composition: one
      `workflow_id`, two legs, one span tree, and the stage narration.
18. **Add a recipe for the newly-reachable adapters.** Phase 2 makes
    `worker`, `hatchet`, and `pydantic_ai` selectable through
    `trigger_workflow`. The cookbook is where a reader would look for
    "how do I actually run a workflow on a terminal worker", and today
    there is no worked example for it. A recipe showing
    `mcp__mahavishnu__trigger_workflow(adapter="worker", …)` end to end
    — including the repositories to scope to, and what the result
    envelope looks like — is the missing worked example.
19. **Update the "How to add a new recipe" procedure itself.** It is
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
      demo — that is the parity rule in task 20.
20. **Add a cookbook↔demo parity test** (REQ-C15). A new test in
    `tests/unit/cli/test_demo_workflow_preconditions.py` (or a sibling)
    that parses `docs/cookbook/workflows.md` and asserts:
    - every `mahavishnu demo <name>` command appearing in a recipe
      resolves to a real registered demo command, and
    - every workflow demo in `demo_cli.py` has a recipe.

    This is the check whose absence let the cookbook drift silently
    until now. It is small, deterministic, and it is the difference
    between a cookbook that is maintained and a cookbook that is
    archaeology.
21. **Fix the demo docstring that points at the cookbook.**
    `cli/demo_cli.py:4056` says "Demo-recipe flavor (paired with
    `docs/cookbook/workflows.md`)" — if a recipe is renamed, this
    cross-reference must move with it.

**Exit criteria:** every demo produces a workflow id; `demo --help`
lists every demo; the `DEMO SUB-COMMANDS` count matches the shipped set;
the cookbook and CLI reference describe what the demos actually do; and
the cookbook↔demo parity test passes in both directions.

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
- [ ] `mahavishnu/core/health_aggregator.py` — the `adapters` feed (§4.12, Phase 2 task 6)
- [ ] `mahavishnu/core/models/persistence.py` — `WorkflowOutcome.status` literal (§4.12, Phase 4 task 4)
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
| `grep -rn "class TaskRouter" mahavishnu/` | one production class | command output |
| `grep -rn "UnifiedOrchestrator" mahavishnu/` | no production caller | command output |
| `python scripts/audit_orphans.py` | no new orphans | command output |
| `python scripts/audit_requirements.py` | orphans 0, phantoms 0 once markers land | command output |
| `crackerjack run -v -f` | all fast hooks pass | command output |
| `python scripts/audit_requirements.py` | orphans 0, phantoms 0 once markers land | command output |
| `pytest tests/unit/workers/test_registry_lookup.py` | the YAML registry stays a subset of the code registry | test output |
| `pytest tests/integration/test_trigger_workflow_e2e.py` | each newly reachable adapter resolves and returns non-empty | test output |
| `pytest tests/integration/test_pool_route_execute_e2e.py` | every return path carries a `workflow_id` that resolves | test output |
| the two-leg composition demo, asserting **one `trace_id`** | the engine span and the worker span share a trace — the only check that makes REQ-C05 real | demo output |
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

**And one decision this plan makes, which the review forced:** cost
accounting is **out of scope** (§3 non-goal 8). The plan's goal is a working
control plane, and the cost model has never run — turning it on is a
separate piece of work with its own risk. Time and efficiency carry the
optimization load for now (§2.1).

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

Round 1 ran nine lenses; round 2 runs the lenses round 1 did not
cover: persistence and store semantics, deployment and operational
safety, ecosystem-consumer impact, platform API surface, a
"does this actually work" implementation pass, and a historical-patterns
sweep over prior decisions and plans. Round 2 runs against this
revision.

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
