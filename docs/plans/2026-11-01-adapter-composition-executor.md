---
status: superseded
role: historical
kind: plan
date: 2026-11-01
last_reviewed: 2026-11-01
superseded_by: docs/plans/2026-11-01-control-plane-consolidation.md
topic: adapter-composition
title: "Adapter composition — making engine and worker substrates compose as one workflow"
---

> **SUPERSEDED (2026-11-01)** by
> `docs/plans/2026-11-01-control-plane-consolidation.md`. Retained for
> traceability only. Its Option 3 ("worker as a first-class adapter plus
> a sequence executor") becomes that plan's Phase 2 (reachability) plus
> Phase 6 (sequence) — the adapter already existed and was already
> registered in `app.adapters`, so the build it priced was mostly done.
> Its Option 2 (the interop primitive) becomes that plan's Phase 4's
> result envelope. Its Option 1 ("do not build B, ship the demo") is
> what Phase 6 delivers. One of its claims is corrected: the engine leg
> is not costed either — `enable_cost_tracking` is a dead parameter and
> `CostOptimizer` has no production caller.

# Adapter composition — making engine and worker substrates compose as one workflow

> **Status: option analysis, not an implementation mandate.** This plan
> exists to price option B and to record the evidence behind the
> recommendation. It deliberately has **no implementation phases** until
> the decision rule in §8 is met.

## 1. Outcome

**If** this plan is promoted, **then** a single mahavishnu workflow can
run an **engine adapter** (Prefect, Agno, LlamaIndex, Hatchet) and a
**terminal worker** (a CLI harness such as `claude`) in one execution,
with one execution id, one span tree, and one cost rollup.

Success signal:

```bash
# a composition of an engine leg and a worker leg, one execution id
mcp__mahavishnu__compose_workflow(
    stages=[{"engine": "prefect"}, {"worker_type": "terminal-claude"}],
    task={...},
)
# -> one execution_id
# -> one cost_usd covering both legs
# -> one span tree
```

## 2. Goals

1. Give a **single decision** — build a composition executor, delegate
   it, or not — backed by evidence rather than momentum.
2. Price the options honestly: what each buys, what it costs, and how
   likely it is to land.
3. Establish the **demand signal** that would justify the work.

## 3. Non-Goals

1. **Not** a plan to implement composition. §5 prices the options; §8
   says what has to be true before any of them is built.
2. **Not** changing the worker dispatch protocol. That is
   `docs/plans/2026-11-01-terminal-cli-harness-demos-and-dispatch-trust.md`
   and it lands first.
3. **Not** replacing Prefect, Agno, LlamaIndex, or Hatchet with a
   mahavishnu-native engine. The engines are the fleet's engines.

## 4. Current Findings

### 4.1 The composition is not expressible today

`TaskRouter`'s chains are AGNO / LLAMAINDEX / PREFECT.
`AdapterType.WORKER` is in **no** chain. The executor,
`execute_workflow_with_fallback` (`mahavishnu/core/workflow_execution.py:647`),
tries each adapter **until one succeeds** — a *fallback*, not a
*sequence*. Nothing in the codebase executes adapters in order,
threading one result into the next.

The two substrates meet only at the MCP tool surface:
`pool_route_execute` (worker) and an engine's `execute` (engine).

### 4.2 The cost of the gap, concretely

- **Engine leg**: costed. `mahavishnu/core/cost_optimizer.py` holds
  `ADAPTER_COSTS` per adapter and calls `record_cost`.
- **Worker leg**: **not costed at all**. `PoolMetrics` carries
  `tasks_completed`, `tasks_failed`, `avg_task_duration`,
  `memory_usage_mb`, `wait_time_estimate` — and no cost.
- **Both legs**: separate execution ids, separate span trees. There is
  no "what did this workflow cost, end to end" today, because there is
  no end-to-end workflow object.

### 4.3 The pieces are already the same shape

`PrefectAdapter`, `LlamaIndexAdapter`, `AgnoAdapter`,
`HatchetAdapterImpl` and `WorkerOrchestratorAdapter` all implement
`OrchestratorAdapter` (`mahavishnu/core/adapters/base.py`). The
composition is *representable*; only the *executor* is missing.

`WorkerOrchestratorAdapter` is instantiated in exactly one place
(`mahavishnu/_main_cli.py:1687`) — a standalone CLI surface, not part
of an engine flow.

### 4.4 The demand signal is the demo, not an argument

No demo composes an engine adapter with a terminal worker today (the
full table is in the dispatch-trust plan, §4.3). Nothing in the fleet
is currently *blocked* on the composition — the engine demos and the
pool demos work independently.

That is the most important finding in this document: **B is a
capability argument, not a pain argument.** The honest reading is that
nobody has yet needed "one workflow across both substrates" enough to
build it.

## 5. Options

Five options. The probabilities are **judgment estimates**, not
measurements — stated as such so they can be argued with.

### Option 1 — Do not build B (ship the demo only)

Deliver `demo workflow-engine-and-worker` from the dispatch-trust plan
and stop there. The composition stays in the caller's hands (an agent,
a script, a demo).

| | |
|---|---|
| **P(right target)** | **0.40** |
| **P(successful delivery)** | 0.95 |
| Effort | S (already scoped in the other plan) |
| Buys | a working composition, plus **the demand signal** |
| Costs | no product capability; every caller writes its own sequencing |

### Option 2 — B5: a thin cross-substrate interop primitive

No chain executor. Instead a single primitive that routes a task to a
named substrate and returns a **normalized result envelope**
(execution id, status, output, cost, span ids) regardless of which
substrate ran it.

| | |
|---|---|
| **P(right target)** | **0.15** as a *destination*, **0.75** as a *prerequisite* |
| **P(successful delivery)** | 0.85 |
| Effort | M |
| Buys | the unified cost rollup and one execution id — the two concrete gaps in §4.2 — without committing to an executor |
| Costs | does not deliver "one workflow across substrates"; the caller still sequences |

This is not really an alternative to Options 3–5 — it is the piece
they all need. Its risk is that it gets built and then nothing uses it.

### Option 3 — B3+B1: the worker as a first-class adapter, plus a sequence executor

1. Expose the pool as an `OrchestratorAdapter` so `AdapterType.WORKER`
   is a peer of the engines and `app.adapters` holds it.
2. Add `execute_workflow_as_pipeline(app, stages, task, repos)` beside
   `execute_workflow_with_fallback`: stages run **in order**, each
   consuming the previous one's output.

| | |
|---|---|
| **P(right target)** | **0.25** |
| **P(successful delivery)** | 0.55 |
| Effort | **XL** |
| Buys | a composition that generalizes across all five engines; observability stays inside mahavishnu (one execution id, one span tree, one cost rollup); `AdapterType.WORKER` stops being a special case |
| Costs | touches the executor, the adapter registry, the cost model, and the pool's dispatch contract. **It collides with the dispatch-trust plan**: that plan gives the worker layer its own state machine (Phase 2), and an engine-owned executor that drives it would need to own the transition too |

The collision is the real problem, not the size. Two owners of one
state transition is how "a stale poll can assert a completed" happens
in the first place. If this option is chosen, the ownership rule must
be written down *first*: the engine owns *when* a stage is dispatched;
the worker owns *how* it settles and reports. That is a design
decision, not an implementation detail.

### Option 4 — B4: delegate the composition to Prefect

Prefect is already a DAG orchestrator in the stack. The composition
becomes a Prefect flow whose task calls back into mahavishnu's MCP
(`pool_route_execute`). Mahavishnu builds no executor.

| | |
|---|---|
| **P(right target)** | **0.20** |
| **P(successful delivery)** | 0.7 |
| Effort | M |
| Buys | retries, DAG semantics, state, and a UI for free; the composition is expressible today in a few lines of Prefect |
| Costs | **inverts the dependency** — the control plane's worker substrate becomes a remote dependency of an engine the control plane also drives; adds a cross-process failure mode (the MCP server must be up); the composition's observability lives in Prefect, which **undercuts the unified-observability argument that motivates B in the first place**; and it only generalizes to Prefect — not to Agno, Hatchet, or LlamaIndex |

The observability inversion is what makes this weaker than it first
looks. If the reason to want B is one cost rollup and one span tree,
handing the composition to Prefect hands the observability to Prefect
too.

### Option 5 — B2: make the existing fallback chain dual-mode

Keep one chain structure and add a `mode: "fallback" | "sequence"`
flag.

| | |
|---|---|
| **P(right target)** | **0.02** |
| **P(successful delivery)** | 0.9 (it is easy) |
| Effort | S |
| Buys | nothing that the other options do not, more cheaply |
| Costs | conflates **priority order** with **data flow** in one data structure. They look alike — both are ordered lists — and they are not the same thing. Cheap to build, permanently expensive to reason about |

Rejected on semantics, not effort.

### Summary

| # | Option | P(right target) | P(delivered) | Effort | Decision |
|---|---|---|---|---|---|
| 1 | Do not build B | **0.40** | 0.95 | S | **recommended for now** |
| 2 | B5 interop primitive | 0.15 (0.75 as prerequisite) | 0.85 | M | **do this next, if the demand signal appears** |
| 3 | B3+B1 worker-as-adapter + sequence executor | 0.25 | 0.55 | XL | the right *destination* if B is ever built |
| 4 | B4 delegate to Prefect | 0.20 | 0.70 | M | plausible, but inverts the observability |
| 5 | B2 dual-mode chain | 0.02 | 0.90 | S | rejected on semantics |

The ordering is not "pick the highest probability". Option 1 has the
highest probability of being right **today** because nothing is
blocked. Option 3 is the highest-probability **destination** among the
build options (0.25 vs 0.20 / 0.02) — but it is XL, has a 0.55
delivery probability, and collides with the dispatch-trust plan.

## 6. Is B genuinely useful?

**Yes, eventually — for one concrete reason: cost and observability
have no common model today.** An engine run is costed per second; a
worker dispatch is not costed at all; the two legs have separate
execution ids. That is not a gap that shows up in a demo. It shows up
the moment anyone asks "what did this workflow cost" for a workflow
that used both.

**But not now, for one equally concrete reason: nobody is blocked.**
The engine demos and the pool demos work independently. The fleet has
no consumer for a chain executor. Building an architectural capability
in a control plane with zero consumers is the exact failure mode the
repo's own Process Discipline warns about — features that get *built*
but never reach *adopted*.

## 7. Is B the type of work the Bodai core components do?

**Yes in remit, no in evidence.**

- **Remit: yes.** Mahavishnu's charter is orchestration and routing.
  An engine→worker composition executor is orchestration, squarely
  inside this repo's mandate — not a new component, a deepening of the
  control plane's existing job.
- **Evidence: no.** The Bodai core repos (mahavishnu, akosha,
  session-buddy, crackerjack, oneiric) build capabilities that other
  components consume. A chain executor with one demo consumer is not
  that. It would be the first capability in the fleet built on
  speculation.

The distinction that resolves it: **B is not a new component, so it
does not need new-component justification — but it does need the same
adoption evidence any capability needs.** The demo *is* that evidence,
which is why Option 1 is not "do nothing" — it is "build the
instrument that decides".

## 8. Decision Rule

**Build nothing until the demo has been used.**

1. Ship `demo workflow-engine-and-worker` (the dispatch-trust plan,
   Phase 1). It is the demand signal.
2. Wait for **one** of:
   - an operator runs the composition demo and asks for it as a
     product capability;
   - a second caller appears that needs the same composition;
   - a cost or observability question comes up that needs the unified
     rollup.
3. When one happens, build **Option 2 (B5)** first — the interop
   primitive is the piece every other option needs, and it is M rather
   than XL. Reprice Options 3–5 against the new evidence.
4. Build **Option 3** only if the demand is *cross-engine* (Prefect
   today, Agno tomorrow). If the demand is Prefect-shaped, Option 4 is
   cheaper and the observability inversion is worth paying.
5. If Option 3 is chosen, the **state-ownership rule** is written
   before any code: the engine owns *when* a stage is dispatched; the
   worker owns *how* it settles and reports. This plan and the
   dispatch-trust plan must agree on it, and the dispatch-trust plan
   lands first.

**The cut:** if no demand signal appears within two quarters, Option 1
stands and this plan stays a decision record. That is a legitimate
outcome, not a failure.

## 9. Required Code Changes

None. This plan authorizes no code. The demo lands in
`docs/plans/2026-11-01-terminal-cli-harness-demos-and-dispatch-trust.md`.

## 10. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `mahavishnu demo workflow-engine-and-worker` | both legs settle in one run | terminal output |
| `grep -c "AdapterType.WORKER" mahavishnu/core/routing.py` | `0` today — the finding this plan rests on | command output |
| `grep -n "ADAPTER_COSTS" mahavishnu/core/cost_optimizer.py` | engine costs exist; pool costs do not | command output |

## 11. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The demo gets built and never used — B proceeds on momentum | medium | §8 requires a named demand signal before any executor work |
| The dispatch-trust plan and an executor fight over who owns the worker's state transition | medium if Option 3 | §8 step 5 writes the ownership rule before code; the dispatch-trust plan lands first |
| Delegating to Prefect inverts the observability we wanted B for | high if Option 4 | §5 Option 4 names the inversion explicitly; Option 2 is the observability-safe middle |
| A chain executor becomes a second orchestration layer beside Prefect | medium | §5 Option 5's rejection is the warning; the executor must stay a *sequence*, not a second DAG |

## 12. Decision Rule (this plan's own fate)

This plan is **done** when §8's decision has been taken and recorded
here — whether that is "Option 1 stands" or "Option 2 is funded". It
is not done while it remains an option analysis.

## References

- `docs/plans/2026-11-01-terminal-cli-harness-demos-and-dispatch-trust.md`
  — the dispatch-trust plan; lands first, and owns the worker's state
  machine.
- `mahavishnu/core/workflow_execution.py:647` —
  `execute_workflow_with_fallback`, the fallback-not-sequence executor.
- `mahavishnu/core/routing.py:140` — `TaskRouter.DEFAULT_FALLBACK_CHAINS`.
- `mahavishnu/core/cost_optimizer.py:44` — `ADAPTER_COSTS`, the engine
  cost model the pool has no counterpart to.
- `mahavishnu/core/adapters/base.py:43` — `OrchestratorAdapter`, the
  interface every engine and the worker adapter already share.
- `docs/decisions/wire-up-contract.md` — the policy that makes
  "built but not adopted" a failure.
