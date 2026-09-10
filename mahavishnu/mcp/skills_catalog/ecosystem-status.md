---
name: ecosystem-status
description: Use ONLY when the user explicitly types `/mahavishnu:ecosystem-status` or selects this Skill from the picker to render a cross-component health snapshot of the Bodai ecosystem from Mahavishnu's vantage point. Do not auto-trigger. Routes through `mcp__mahavishnu__ecosystem_status` and explains the `sections` parameter plus the degraded-adapter flag so the user can interpret a partial report correctly.
allowed-tools: mcp__mahavishnu__ecosystem_status, mcp__mahavishnu__get_health, mcp__mahavishnu__list_adapters, Read, Bash(echo:*)
---

# ecosystem-status

## When to use

This Skill is the right entry point when the user wants a cross-
component health snapshot of the Bodai ecosystem — the canonical
"what's the state of the cluster right now?" view that Mahavishnu
publishes. Common cases:

- "Give me the Bodai ecosystem status."
- "Is Akosha reachable from here? Is Dhara responding?"
- "Show only the workflow + pool sections of the ecosystem report."
- "Surface the degraded adapters in the current ecosystem."

The Skill uses `mcp__mahavishnu__ecosystem_status` as the primary entry
point. The tool's `sections` parameter accepts a list of section
names so the user can request a focused slice (`["workflows", "pools"]`)
or the full snapshot (`sections=None`).

## What the tool does

`mcp__mahavishnu__ecosystem_status(sections=None)` aggregates per-
component state across the Bodai fleet:

- **adapters** — Mahavishnu's own adapter health (prefect, llamaindex,
  agno). Includes each adapter's `health.status` and the per-adapter
  `features` list (RAG, Workflow Orchestration, AI Agents, etc.).
- **workflows** — counts of running, queued, completed, and failed
  workflows surfaced from the workflow_state_manager.
- **pools** — per-pool worker counts, health, and capacity. Reflects
  the current `least_loaded` / `round_robin` / `random` / `affinity`
  selectors available for `pool_route_execute`.
- **observability** — Prometheus metrics summary, recent log
  highlights, and any active alerts surfaced via `get_active_alerts`.
- **session_buddy** — Session-Buddy endpoint reachability and the
  most recent in-process state sync.
- **repositories** — count of repos registered in `repos.yaml` and
  per-tag breakdown.

The response includes a `degraded` flag at the top level. When any
section reports `status: degraded` (e.g. an OTel collector is down
or a pool is unreachable), the Skill surfaces the degraded section
names verbatim and explains the impact on the user's downstream calls.

## Sections parameter — focus vs full

The `sections` parameter is a list of section names from the canonical
set. Common focused slices:

- `["adapters"]` — just the adapter health snapshot. Use this when
  the user is debugging a specific adapter (e.g. "is Prefect up?").
- `["workflows", "pools"]` — fleet routing snapshot. Use this when
  the user is planning a dispatch and wants to know capacity.
- `["observability", "session_buddy"]` — observability substrate
  snapshot. Use this when the user is debugging telemetry gaps.
- `None` (the default) — full snapshot. Use this when the user asks
  for "the whole thing" or "the complete status."

When the user specifies an unknown section name, the Skill surfaces
the canonical section list so the user can pick from it.

## When NOT to use

- For a single-component health check (e.g. just Mahavishnu itself),
  use `mcp__mahavishnu__get_health` — it is cheaper than the full
  ecosystem rollup.
- For pool capacity alone, use `mcp__mahavishnu__pool_health`.
- For adapter introspection alone, use
  `mcp__mahavishnu__list_adapters`.

## Degraded-adapter semantics

A degraded adapter does NOT mean the ecosystem is down — it means
that specific adapter's calls will fail or fallback. The Skill
explains the impact in plain language:

- **Prefect degraded** — durable workflows cannot be dispatched;
  call `trigger_workflow(adapter="prefect", ...)` will surface the
  degradation to the caller. Suggest retrying with `adapter="agno"`
  or `adapter="llamaindex"` if the user can shift the workload.
- **LlamaIndex degraded** — RAG pipelines unavailable; ingestion
  workflows will fail mid-flight. Suggest deferring ingestion until
  the substrate recovers.
- **Agno degraded** — agent loops unavailable; multi-step reasoning
  workflows will fail. Suggest switching to a single-shot
  `pool_route_execute` if the workload allows.

## Inputs the Skill expects

- Optional `sections` list — when the user says "just the adapters"
  or "show me pools only", the Skill translates that phrasing into
  the right `sections` value.
- Optional user signal about degraded-handling — "ignore the
  degraded adapters", "explain what they mean", "skip LlamaIndex
  entirely". The Skill honors the explicit instruction.

## Outputs the Skill returns

A bulleted summary of the requested sections with the per-section
status (healthy / degraded / unavailable), the canonical
`degraded` flag, and a one-paragraph recommendation for the next
action (proceed, defer, reroute, or escalate). Long section
payloads (e.g. workflow lists) are summarized to top-three with
counts; the user can re-query with a focused `sections` list to
see more.
