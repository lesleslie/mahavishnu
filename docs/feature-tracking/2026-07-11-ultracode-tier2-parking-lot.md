# Tier 2 Parking Lot — Deferred ultracode Integration Ideas

**Owner:** mahavishnu core
**Created:** 2026-07-11
**Last updated:** 2026-07-11
**Repo(s):** /Users/les/Projects/mahavishnu
**Source plan:** `docs/plans/2026-07-11-ultracode-integration-wiring.md`

## Purpose

This file captures the five Tier 2 ultracode-integration ideas that were considered during the planning conversation on 2026-07-11 and **deferred** in favor of the three Tier 1 items in the source plan. Each entry below records the idea, the probability it would meaningfully improve Mahavishnu, the trigger condition that should prompt reconsideration, and the rough effort estimate. When a trigger condition is met, promote the relevant entry into its own feature-tracking file.

## State — pick one

- [ ] **parked** (deferred; not built; revisit when trigger condition met)

## Built (yes/no)

no

## Wired (yes/no)

no

## Trigger path

Each entry's "Reconsider when" field describes its trigger path.

## Integration point

Each entry's "Where it would live" field describes its integration point.

## End-to-end check

Not applicable — these are deferred ideas, not built features.

## Blocker

None — these are deliberately deferred, not blocked.

## Next action

When the trigger condition is met for any entry, copy that entry's content into a new feature-tracking file at `docs/feature-tracking/<slug>.md` and reference this parking lot in its "Related" section.

______________________________________________________________________

## Tier 2 entries

### 2.1 Multi-judge routing for high-stakes pool selection (P=0.55)

**What it is:** Currently `PoolManager.route_task` uses a single model's preference score to pick a pool. For high-stakes decisions (cross-repo refactors, version bumps), spawn 3 judges and use majority vote.

**Where it would live:** `mahavishnu/pools/manager.py::route_task` with a new optional `multi_judge: bool = False` parameter. Gate behind "high-stakes" tag (`cross_repo=true`, `production_impact>threshold`).

**Why it's deferred:** Cost is 3× LLM calls per routing decision. Not worth it on every task — only on rare, high-stakes ones. Need a clear threshold for when to enable.

**Reconsider when:** Mahavishnu ships ≥3 high-stakes routing decisions per week AND operators report ≥1 routing decision that produced a poor outcome (caught by post-hoc review).

**Effort estimate:** ~120 lines + 60 lines of tests. Half a day.

### 2.2 Token-budget caps on self-improvement generation (P=0.60)

**What it is:** `self_improvement_generate` is unbounded today. Add a per-deployment cap (default: 100 calls/week, per the session-buddy doc's "planned" ceiling) tracked in Dhara.

**Where it would live:** New `mahavishnu/core/budget.py` exporting `Budget` (a counter with weekly reset). `self_improvement_generate` reads before queueing.

**Why it's deferred:** The current call volume is low enough that the cap is not urgent. But it's a known footgun — a runaway loop could rack up significant LLM spend.

**Reconsider when:** `mahavishnu metrics self-improvement --calls-per-week` exceeds 50, OR a runaway-incident postmortem identifies this as a contributing factor.

**Effort estimate:** ~80 lines + 40 lines of tests. Quarter day.

### 2.3 Sub-workflow composition (P=0.45)

**What it is:** Mahavishnu workflows are config-driven DAGs in Oneiric. Allow one workflow to embed another as a step. Example: `pr-enhance` workflow contains a `quality-gate` workflow step.

**Where it would live:** `mahavishnu/core/workflow_models.py` gains `parent_workflow_id: str | None` field. Oneiric loader handles recursion with a depth limit (default 3).

**Why it's deferred:** Oneiric's loader doesn't love recursion; nested workflow YAML would need explicit `parent_workflow_id` and a depth limit. Risk: complexity without much operational gain if most workflows are already flat.

**Reconsider when:** A second workflow needs to embed the same DAG pattern AND a refactor to share that pattern via composition would be cleaner than duplication.

**Effort estimate:** ~200 lines + 80 lines of tests. One day.

### 2.4 Diversity in adapter selection (P=0.40)

**What it is:** Currently one adapter wins per task. For ambiguous tasks (e.g., "refactor this Python module"), try 3 adapters (Prefect + LlamaIndex + Agno) in parallel and keep the best output.

**Where it would live:** New `mahavishnu/core/adapter_race.py` exporting `async def race_adapters(task, adapter_names: list[str]) -> AdapterResult`. Called by the workflow engine when `task.ambiguous == True`.

**Why it's deferred:** Cost is 3× execution, latency is 3× wall-clock unless parallel. Probably only worth it for "exploratory" tier tasks, not production.

**Reconsider when:** An empirical study shows adapter-quality variance is >2× on a meaningful workload (currently unknown).

**Effort estimate:** ~150 lines + 80 lines of tests. Half a day.

### 2.5 Self-critique loop on generated fixes (P=0.35)

**What it is:** After `review_and_fix(auto_fix=True)` produces a fix, spawn a critic that checks the diff against the original failure mode. If the critic identifies gaps, revise the fix before finalizing.

**Where it would live:** Modify `mahavishnu/mcp/tools/self_improvement_tools.py:83-174` (`review_and_fix`) to add `self_critique: bool = False` parameter. New `mahavishnu/core/fix_critic.py` for the critique logic.

**Why it's deferred:** Adds latency on a hot path. The CLAUDE.md checker is already partially automated by `crackerjack-compliant-code`. Critique-and-revise loops often get stuck in local optima.

**Reconsider when:** Operators report ≥1 fix-per-week that misses the original failure mode (caught by post-deployment monitoring or rollback).

**Effort estimate:** ~250 lines + 100 lines of tests. One day.

### 2.6 Bodai-wide observability surfacing (deferred from plan Phase 6) (P=0.55)

**What it is:** The originally-planned Phase 6 of `docs/plans/2026-07-11-ultracode-integration-wiring.md` — extending the Phase 5 worker-activity surfacing pattern to the rest of the Bodai ecosystem (Dhara, Session-Buddy, Crackerjack, Akosha). Includes `/bodai-status` slash command and a generalized `bodai-activity-stream.py` hook.

**Where it would live:** New plan at `docs/plans/2026-07-XX-bodai-event-bridge-surfacing.md` (placeholder name). Files: `.claude/commands/bodai-status.md`, `.claude/hooks/bodai-activity-stream.py`, possibly new EventBridge handlers in `mahavishnu/core/events/` (per the unified event spine shipped in Convergence Plan C1b).

**Why it's deferred:** Architecture-council review found that the originally-proposed multi-WebSocket subscriber consumes raw `ws://localhost:8690`, `ws://localhost:8686`, `ws://localhost:8692` streams — duplicating the unified event spine shipped in Convergence Plan C1b (Oneiric EventBridge over Redis Streams). The Convergence Plan's Non-Goal #1 explicitly forbids adding a second control plane / event bus. The follow-up plan must consume EventBridge handlers, not raw WebSocket connections.

**Precondition (hard block):** An EventBridge handler for activity events exists in the Convergence Plan's C1b work. Until that lands, Phase 6 cannot be implemented without violating the Non-Goal.

**Reconsider when:** EventBridge activity handler exists AND `akosha health` / `session-buddy health` CLIs land (cross-referenced as `component-health-cli-gap.md`). Survey table for existing observability surfaces is preserved in the plan's Phase 6 section for reference.

**Effort estimate:** ~250 lines + 100 lines of tests. One to two days. Likely tracked under a separate plan once the precondition is met.

______________________________________________________________________

## Related

- Plan: `docs/plans/2026-07-11-ultracode-integration-wiring.md` (Tier 1 items that *were* selected)
- Feature: `docs/feature-tracking/2026-07-11-verification-gate.md` (Tier 1, probability ~0.70)
- Feature: `docs/feature-tracking/2026-07-11-loop-until-dry.md` (Tier 1, probability ~0.65)
- Feature: `docs/feature-tracking/2026-07-11-dispatch-to-pool.md` (Tier 1 — MCP bridge completion)
- Conversation: 2026-07-11 — Vishnu vs ultracode capabilities comparison

## How to revive a parked idea

When a trigger condition is met:

1. Copy the entry's "What it is" / "Where it would live" / "Effort estimate" sections into a new file at `docs/feature-tracking/<slug>.md`, populating the standard feature-tracking template fields.
1. Update this parking lot file: set state to **promoted** with a date, link to the new file in this entry, and decrement the entry count above.
1. Create a focused plan in `docs/plans/` for the promoted feature, OR add it as a phase to an existing plan if it's a small enough delta.
1. Update `docs/plans/PLAN_INDEX.md`.

## Session-Buddy

Run `mcp__session-buddy__store_reflection` once after creating this file:

```python
mcp__session-buddy__store_reflection(
    content=(
        "Feature ultracode-tier2-parking-lot: state=parked, "
        "built=no, wired=no, "
        "blocker=none (deliberately deferred), "
        "next=monitor trigger conditions for 2.1-2.6 and promote when met"
    ),
    tags=["feature-tracking", "ultracode-tier2-parking-lot", "parking-lot"],
)
```

- Reflection ID: <to be filled after running store_reflection>
- Saved at: \<ISO timestamp from the call's response>
