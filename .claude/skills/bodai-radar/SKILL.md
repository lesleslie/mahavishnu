______________________________________________________________________

## name: bodai-radar description: Use when checking ecosystem health across all Bodai components. Use when user asks "how's the ecosystem?", "system health", "is everything green?", "bodai status", "morning standup", "radar check", "ecosystem health", "show me the radar", "are any systems down?", or "give me the radar". Also use when user wants a quick health snapshot across Crackerjack, Mahavishnu, Akosha, Dhara, and Session-Buddy.

# Bodai Radar

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| session-buddy | 8678 | grep | mcp\_\_session-buddy\_\_get_activity_summary, mcp\_\_session-buddy\_\_checkpoint | 30s |
| mahavishnu | 8680 | grep | mcp\_\_mahavishnu\_\_get_health, mcp\_\_mahavishnu\_\_pool_health | 60s |
| akosha | 8682 | summary | mcp\_\_akosha\_\_detect_anomalies, mcp\_\_akosha\_\_correlate_systems | 60s |

Provides a unified traffic-light health dashboard across all 5 Bodai components in a single command. Each component contributes its single best health signal, synthesized into a quick-to-read summary.

**Core principle:** One command, five components, thirty seconds.

## When to Use

**Use when:**

- Starting a work session and want a quick ecosystem health check
- Checking if any Bodai component is degraded or down
- Getting a morning standup overview of the entire ecosystem
- Verifying system health after a deployment or configuration change

**Don't use when:**

- Running quality checks (use `run-quality-checks`)
- Analyzing quality trends over time (use `quality-pulse`)
- Recovering past decisions or context (use `session-archaeologist`)
- Searching across system memories (use `search-insights`)
- Discovering available repos and capabilities (use `ecosystem-awareness`)
- Managing pool lifecycle (use `manage-pools`)

## The Five Signals

Each Bodai component provides exactly one primary health signal:

| Component | Tool | What it returns | Traffic light logic |
|-----------|------|----------------|-------------------|
| **Crackerjack** | `mcp__session-buddy__get_crackerjack_quality_metrics` | Quality scores, pass/fail rates, adapter performance | Green: all adapters passing. Yellow: 1+ adapter degrading. Red: adapter failures |
| **Mahavishnu** | `mcp__mahavishnu__get_health` | Overall health, active workflows, pool status | Green: healthy. Yellow: degraded dependency. Red: critical failure |
| **Akosha** | `mcp__akosha__detect_anomalies` on `conversation_count` | Conversation volume anomalies detected across systems | Green: no anomalies. Yellow: anomaly detected (2.0-2.9 std dev). Red: strong anomaly (>= 3.0 std dev) |
| **Dhara** | `mcp__dhara__get_adapter_health` | Storage tier health and availability | Green: all tiers healthy. Yellow: one tier degraded. Red: tier unavailable |
| **Session-Buddy** | `mcp__session-buddy__get_activity_summary` | Recent session activity | Green: normal activity. Yellow: low activity (stale). Red: no activity (may be stuck) |

## Implementation

### Step 1: Fan-Out to All Five Components

Call all five signal tools. Each call is independent — a failure in one does not block the others. Execute all five in parallel when possible:

```
mcp__session-buddy__get_crackerjack_quality_metrics(days=7)
mcp__mahavishnu__get_health()
mcp__akosha__detect_anomalies(metric_name="conversation_count", time_window_days=7, threshold_std=2.0)
mcp__dhara__get_adapter_health()
mcp__session-buddy__get_activity_summary(hours=2)
```

### Step 2: Apply Traffic Light Logic Per Component

For each component, classify the result into green, yellow, red, or grey (unavailable):

**Crackerjack classification:**

- Grey: No data returned (no recent Crackerjack runs)
- Green: All quality metrics within normal range
- Yellow: 1+ adapter showing degraded scores
- Red: Adapter failures detected

**Mahavishnu classification:**

- Grey: `get_health` call failed or timed out
- Green: Health status is "healthy" or equivalent
- Yellow: One or more dependencies degraded
- Red: Critical failure in workflow/pool system

**Akosha classification:**

- Grey: No metrics tracked yet or call failed
- Green: No anomalies detected
- Yellow: Anomaly detected between 2.0 and 2.9 standard deviations (unusual but not critical)
- Red: Anomaly detected at 3.0+ standard deviations (strong signal)

**Note:** Akosha's signal measures ecosystem activity anomalies (unusual patterns in conversation volume), not Akosha's own operational health. Yellow/red here means "Akosha detected something unusual in the ecosystem," not "Akosha is broken."

**Dhara classification:**

- Grey: `get_storage_status` call failed or timed out
- Green: All storage tiers operational
- Yellow: One tier degraded but functional
- Red: Tier unavailable

**Session-Buddy classification:**

- Grey: `get_activity_summary` call failed or timed out
- Green: Normal session activity detected
- Yellow: Low activity (fewer than expected sessions for the time window)
- Red: No activity at all (may indicate a stuck or disconnected service)

### Step 3: Synthesize Dashboard

Format all five component signals into the unified dashboard:

```markdown
## Bodai Radar — [current date]

| Component | Status | Signal | Detail |
|-----------|--------|--------|--------|
| Crackerjack | [status emoji] | [signal summary] | [key detail] |
| Mahavishnu | [status emoji] | [signal summary] | [key detail] |
| Akosha | [status emoji] | [signal summary] | [key detail] |
| Dhara | [status emoji] | [signal summary] | [key detail] |
| Session-Buddy | [status emoji] | [signal summary] | [key detail] |

### Summary
[auto-generated summary based on state]
```

Status emojis:

- Green: `:green_circle:`
- Yellow: `:yellow_circle:`
- Red: `:red_circle:`
- Grey/unavailable: `:grey_circle:`

### Step 4: Generate Summary

Write the summary based on the overall dashboard state:

**All green:**

> All 5 components healthy. No action needed.

**One or more yellow:**

> N/5 components healthy. [Component] shows [signal detail]. Run `[recommended skill]` for details.

**One or more red:**

> N/5 components healthy. **[Component] requires attention**: [detail].

**Components unavailable:**

> N/5 components reachable. [Unavailable list]. Ensure all MCP servers are running.

### Step 5: Route to Related Skills

When the summary flags a problem, include a skill recommendation:

| Component flagged | Recommended skill | Why |
|-------------------|-------------------|-----|
| Crackerjack yellow/red | `run-quality-checks` | Trigger quality gates for immediate action |
| Crackerjack yellow/red (trends) | `quality-pulse` | Analyze quality trends over time |
| Mahavishnu yellow/red | `manage-pools` | Pool lifecycle management |
| Mahavishnu yellow/red (workflows) | `orchestrate-workflow` | Workflow orchestration issues |
| Akosha yellow/red | `quality-pulse` | Trend analysis on anomalies |
| Akosha yellow/red (search) | `search-insights` | Deep semantic search across systems |
| Dhara yellow/red | Run `mcp__dhara__health_check_all` | Check storage tier and dependency health |
| Session-Buddy yellow/red | `session-archaeologist` | Recover lost context |
| Session-Buddy yellow/red (recent) | `search-sessions` | Search recent session history |

## Graceful Degradation

This skill uses **parallel graceful degradation** — each component is queried independently:

1. If a component's MCP tool call fails, catch the error
1. Mark that component as `:grey_circle: Unavailable`
1. Continue with the remaining components
1. At the bottom of the dashboard, add: "[N] component(s) unreachable: [list]. For full radar, ensure all MCP servers are running."

**No filesystem fallback.** A health check that silently falls back to stale data would give a false sense of health. If an MCP server is down, the signal is simply unavailable — that's the correct answer.

## Edge Cases

| Situation | Response |
|-----------|----------|
| **No Crackerjack data** | Mark Crackerjack as `:grey_circle: No recent data`. Suggest running `crackerjack run`. |
| **Akosha has no metrics** | Mark Akosha as `:grey_circle: No metrics tracked`. Note data accumulates with sessions. |
| **All components down** | Report "All 5 components unreachable. Check MCP server status." Suggest verifying `.mcp.json`. |
| **Conflicting signals** | Present both without reconciling. The dashboard is a signal, not a diagnosis. |
| **Component returns unexpected format** | Mark as `:grey_circle: Unexpected response`. Continue with remaining components. |

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| **Blocking on one component** | Slow radar when one server is slow | Always parallel, always graceful |
| **Adding drill-down analysis** | Radar becomes slow and complex | One signal per component. Route to dedicated skills for depth. |
| **Silent fallback to stale data** | False sense of health | Mark unavailable as grey, never fabricate a signal |
| **Ignoring empty results** | Misleading green status | Empty/missing data should be grey, not green |

## Related Skills

- **RELATED:** `run-quality-checks` - Trigger quality gates (bodai-radar reads metrics passively)
- **RELATED:** `quality-pulse` - Deep quality trend analysis (bodai-radar shows single score)
- **RELATED:** `session-archaeologist` - Recover past context (bodai-radar shows current activity)
- **RELATED:** `search-insights` - Semantic search across systems (bodai-radar shows health signals)
- **RELATED:** `ecosystem-awareness` - Discover repo structure and roles (bodai-radar checks operational health)
- **RELATED:** `manage-pools` - Manage pool lifecycle (bodai-radar reports pool health)
