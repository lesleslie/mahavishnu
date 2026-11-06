---
name: ecosystem-status
description: Use ONLY when the user explicitly types `/mahavishnu:ecosystem-status` or selects this Skill from the picker to render a cross-component health snapshot of the Bodai ecosystem from Mahavishnu's vantage point. Do not auto-trigger. Routes through `mcp__mahavishnu__ecosystem_status` and explains the `sections` parameter plus the aggregate status so the user can interpret a partial report correctly.
allowed-tools: mcp__mahavishnu__ecosystem_status, mcp__mahavishnu__get_health, mcp__mahavishnu__list_adapters, Read, Bash(echo:*)
---

# ecosystem-status

## When to use

This Skill is the right entry point when the user wants a cross-
component health snapshot of the Bodai ecosystem — the canonical
"what's the state of the cluster right now?" view that Mahavishnu
publishes. Common cases:

- "Give me the Bodai ecosystem status."
- "Is Akosha reachable from here? Is Oneiric responding?"
- "Show only the workflow and adapter sections of the ecosystem report."
- "Surface the degraded components in the current ecosystem."

The Skill uses `mcp__mahavishnu__ecosystem_status` as the primary entry
point. The tool's `sections` parameter accepts a list of section
names so the user can request a focused slice (`["workflows", "alerts"]`)
or the full snapshot (`sections=None`).

## What the tool does

`mcp__mahavishnu__ecosystem_status(sections=None)` aggregates per-
component state across the Bodai fleet into a single report.

The report always carries four envelope fields — `schema_version`,
`status`, `generated_at`, `duration_ms` — and then one key per
section. The eight sections are:

- **services** — per-dependency health for each ecosystem component
  (Mahavishnu, Akosha, Session-Buddy, ...): `status`, `liveness`,
  `readiness`, `last_check`, `capacity_pct`, `required`,
  `degradation_mode`, `latency_ms`.
- **adapters** — Mahavishnu's own adapter health (prefect, llamaindex,
  agno). Includes each adapter's `status` and the per-adapter
  `capabilities` list (RAG, Workflow Orchestration, AI Agents, etc.),
  plus `degradation_trend` and `preference_score`.
- **workflows** — counts of active, recent, and failed workflows, plus
  `last_completed_at`.
- **recovery** — durable recovery state: how many workflows, approvals,
  pools, and routing decisions were recovered, and whether the MCP
  recovery substrate is available.
- **alerts** — active alert counts broken down by severity, plus the
  top alerts.
- **capabilities** — per-capability health across the ecosystem:
  `status`, which components `provided_by` it, its `category`, and
  `last_verified`.
- **recommendations** — deterministic operator guidance derived from the
  current state; each entry carries a `severity`, `component`,
  `message`, and often a `suggested_command` and `runbook_url`.
- **errors** — sections that could not be collected. Each entry names
  the `section`, the `message`, and the `original_exception`.

The top-level `status` field is the aggregate verdict — one of `ok`,
`degraded`, `unhealthy`, `unknown`, or `disabled`. There is no separate
`degraded` boolean. When the aggregate is `degraded`, read the
per-section `status` values to find which components are responsible
and surface those component names verbatim.

## Sections parameter — focus vs full

The `sections` parameter is a list of section names from the canonical
set above. Common focused slices:

- `["adapters"]` — just the adapter health snapshot. Use this when
  the user is debugging a specific adapter (e.g. "is Prefect up?").
- `["workflows", "alerts"]` — execution and alerting snapshot. Use this
  when the user is planning a dispatch and wants to know whether work
  is failing.
- `["services", "capabilities"]` — fleet reachability and capability
  coverage. Use this when the user is debugging a telemetry gap.
- `["recovery", "recommendations"]` — what the platform already healed,
  and what it suggests doing next.
- `None` (the default) — full snapshot. Use this when the user asks
  for "the whole thing" or "the complete status."

When the user specifies an unknown section name, the tool does not drop
it silently. The response carries the unrecognized names under
`invalid_sections` and the canonical list under `available_sections`,
so the Skill should read those, tell the user which name was not
recognized, and re-issue the request with a valid name from
`available_sections`.

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
  or "show me alerts only", the Skill translates that phrasing into
  the right `sections` value. Use only names from the canonical set
  above; a name that is not in that set comes back under
  `invalid_sections`.
- Optional user signal about degraded-handling — "ignore the
  degraded adapters", "explain what they mean", "skip LlamaIndex
  entirely". The Skill honors the explicit instruction.

## Outputs the Skill returns

A bulleted summary of the requested sections with the per-section
status (ok / degraded / unhealthy / unknown / disabled), the aggregate
`status` verdict, and a one-paragraph recommendation for the next
action (proceed, defer, reroute, or escalate). Long section
payloads (e.g. workflow lists) are summarized to top-three with
counts; the user can re-query with a focused `sections` list to
see more.
