---
name: pool-route
description: Use ONLY when the user explicitly types `/mahavishnu:pool-route` or selects this Skill from the picker to dispatch a single ad-hoc task through the Mahavishnu pool router. Do not auto-trigger. Routes through `mcp__mahavishnu__pool_route_execute` with the `least_loaded` selector so the call lands on the worker pool with the most available capacity. Use for tasks that do not need durable Prefect workflows or scheduled execution.
allowed-tools: mcp__mahavishnu__pool_route_execute, mcp__mahavishnu__pool_health, Read, Bash(echo:*)
---

# pool-route

## When to use

This Skill is the right entry point when the user wants a single ad-hoc
task executed against the worker pool — without the overhead of a durable
Prefect flow, an Agno agent loop, or cross-repo orchestration. Common
cases:

- "Run a one-shot code-review on a single repo and return the result."
- "Execute this prompt against whichever worker has the most capacity."
- "Pool-dispatch a quality check and stream the response back inline."

The Skill uses `mcp__mahavishnu__pool_route_execute` as the primary entry
point with the `least_loaded` selector so the call lands on the worker
pool with the most available capacity at dispatch time. If health
degradation makes a fallback preferable, the Skill surfaces the
appropriate alternative routing strategy and explains the choice to the
user before dispatching.

## What the tool does

`mcp__mahavishnu__pool_route_execute(prompt, pool_selector, timeout)`
performs **load-balanced single-task dispatch**:

- **Selector `least_loaded`** — picks the pool with the most free
  workers; the default and the right choice for ad-hoc tasks.
- **Selector `round_robin`** — distributes evenly; better for high-
  volume batch fan-out where each task is roughly the same weight.
- **Selector `random`** — picks any healthy pool; useful for stochastic
  probing during capacity tests.
- **Selector `affinity`** — pins to a pool by tag affinity; reserved
  for users who have configured a tag-aware affinity map.

The `timeout` parameter bounds the wait for a worker to accept the
task. When the timeout expires before a worker picks up the call, the
tool returns a `not_found` envelope so callers can re-route or surface
the failure to the user.

The Skill also queries `mcp__mahavishnu__pool_health` first when the
user signals concern about pool capacity. A degraded health surface
(every pool reporting `degraded`) is surfaced to the user with three
candidate fallback paths: retry with `round_robin`, dispatch via
`trigger_workflow(adapter="prefect", ...)` for durable retry, or hold
the call until health recovers.

## When NOT to use

- For multi-step orchestrations spanning repos or that need to survive
  hours or days, use `trigger_workflow(adapter="prefect", ...)` so the
  durable Prefect flow persists state.
- For agent-loop reasoning with multi-turn tool use, use
  `trigger_workflow(adapter="agno", ...)`.
- For RAG pipelines and document ingestion, use
  `trigger_workflow(adapter="llamaindex", ...)`.
- For a quick, fully local execution without observability, fall back
  to direct Bash invocations.

## Failure modes and how to handle them

- **All pools degraded**: surface the health snapshot, ask whether the
  user wants to retry against a degraded pool, retry with a different
  selector, or escalate to `trigger_workflow` for durable retry.
- **Timeout before worker pickup**: return a structured note and
  recommend a longer timeout or a different selector.
- **Worker reports a task failure**: surface the worker error verbatim,
  include the worker_id and pool_id from the response, and suggest a
  retry once the pool recovers.
- **Skill invoked but pool routing is disabled in settings**: surface
  the configuration gate (`pools_enabled: false`) and propose enabling
  it via `settings/mahavishnu.yaml`.

## Inputs the Skill expects

- `prompt` (string, required) — natural-language description of the
  task the user wants executed. The Skill passes the user's wording
  verbatim; rewrites happen only when the user explicitly asks.
- A user signal about whether to query pool health first. If the user
  mentions "is the pool healthy?", "which pool should I use?", or
  "will this time out?", the Skill calls `pool_health` before
  dispatching.

## Outputs the Skill returns

A short prose summary of what was dispatched, the pool_id that won the
selector, the worker_id that picked up the call, and the inline result
if the dispatch was synchronous. For async dispatches, the Skill
returns the workflow_id so the user can poll
`mcp__mahavishnu__get_workflow_status` for results.
