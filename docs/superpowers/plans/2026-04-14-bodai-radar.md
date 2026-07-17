---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: bodai-radar
---

# Bodai Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone Claude Code skill (SKILL.md file) that provides a unified traffic-light health dashboard across all 5 Bodai components in a single command.

**Architecture:** Pure SKILL.md prompt file in `~/.claude/skills/`. No Python code, no new MCP tools. Composes one "best signal" tool from each component (Crackerjack, Mahavishnu, Akosha, Dhara, Session-Buddy) into a parallel fan-out sweep with graceful degradation.

**Tech Stack:** Claude Code skills (SKILL.md with YAML frontmatter), MCP tools from all 5 Bodai components.

**Spec:** `docs/superpowers/specs/2026-04-14-bodai-radar-design.md`

______________________________________________________________________

## File Structure

| File | Responsibility |
|------|---------------|
| `~/.claude/skills/bodai-radar/SKILL.md` | Unified ecosystem health dashboard skill |

No other files are created or modified. This is a pure prompt file.

**Pattern reference** (read-only, for consistency):

- `~/.claude/skills/session-archaeologist/SKILL.md` — Most recent Akosha skill (same fallback pattern)
- `~/.claude/skills/quality-pulse/SKILL.md` — Quality analytics skill (same backend, same degradation pattern)
- `~/.claude/skills/ecosystem-awareness/SKILL.md` — Ecosystem discovery skill (complementary, not overlapping)
- `~/.claude/skills/search-insights/SKILL.md` — Generic Akosha search skill (different output format)
- `~/.claude/skills/run-quality-checks/SKILL.md` — Quality gate skill (triggers checks, bodai-radar reads metrics)

______________________________________________________________________

### Task 1: Create Bodai Radar SKILL.md

**Files:**

- Create: `~/.claude/skills/bodai-radar/SKILL.md`

- [x] **Step 1: Create the directory**

Run: `mkdir -p ~/.claude/skills/bodai-radar`

- [x] **Step 2: Write the SKILL.md file**

Create `~/.claude/skills/bodai-radar/SKILL.md` with this content:

```markdown
---
name: bodai-radar
description: Use when checking ecosystem health across all Bodai components. Use when user asks "how's the ecosystem?", "system health", "is everything green?", "bodai status", "morning standup", "radar check", "ecosystem health", "show me the radar", "are any systems down?", or "give me the radar". Also use when user wants a quick health snapshot across Crackerjack, Mahavishnu, Akosha, Dhara, and Session-Buddy.
---

# Bodai Radar

## Overview

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
| **Akosha** | `mcp__akosha__detect_anomalies` on `conversation_count` | Anomalies in cross-system metrics | Green: no anomalies. Yellow: low-confidence (< 2 std dev). Red: high-confidence (>= 2 std dev) |
| **Dhara** | `mcp__dhara__get_adapter_health` | Storage adapter health and availability | Green: all tiers healthy. Yellow: one tier degraded. Red: tier unavailable |
| **Session-Buddy** | `mcp__session-buddy__get_activity_summary` | Recent session activity | Green: normal activity. Yellow: low activity (stale). Red: no activity (may be stuck) |

## Implementation

### Step 1: Fan-Out to All Five Components

Call all five signal tools. Each call is independent — a failure in one does not block the others. Execute all five in parallel when possible:

```

mcp\_\_session-buddy\_\_get_crackerjack_quality_metrics(days=7)
mcp\_\_mahavishnu\_\_get_health()
mcp\_\_akosha\_\_detect_anomalies(metric_name="conversation_count", time_window_days=7)
mcp\_\_dhara\_\_get_adapter_health()
mcp\_\_session-buddy\_\_get_activity_summary(hours=2)

````

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
- Yellow: Low-confidence anomaly (below threshold or borderline)
- Red: High-confidence anomaly detected

**Dhara classification:**
- Grey: `get_adapter_health` call failed or timed out
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
````

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
| Mahavishnu yellow/red (workflows) | `search-insights` + direct Mahavishnu CLI | `orchestrate-workflow` skill may not exist — use MCP tools or CLI directly |
| Akosha yellow/red | `quality-pulse` | Trend analysis on anomalies |
| Akosha yellow/red (search) | `search-insights` | Deep semantic search across systems |
| Dhara yellow/red | Direct user to check Dhara MCP server | Infrastructure issue |
| Session-Buddy yellow/red | `session-archaeologist` | Recover lost context |
| Session-Buddy yellow/red (recent) | `search-insights` | `search-sessions` skill may not exist — use `search-insights` instead |

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

````

- [x] **Step 3: Verify the file**

Run: `head -3 ~/.claude/skills/bodai-radar/SKILL.md`
Expected: YAML frontmatter with `name: bodai-radar`

- [x] **Step 4: Commit**

Run:
```bash
cd ~/.claude && git add skills/bodai-radar/SKILL.md
git commit -m "feat: add bodai-radar skill for unified ecosystem health dashboard"
````

______________________________________________________________________

### Task 2: Validate the Skill

**Files:**

- Read: `~/.claude/skills/bodai-radar/SKILL.md`

- Read: `~/.claude/skills/quality-pulse/SKILL.md`

- Read: `~/.claude/skills/ecosystem-awareness/SKILL.md`

- Read: `~/.claude/skills/session-archaeologist/SKILL.md`

- Read: `~/.claude/skills/run-quality-checks/SKILL.md`

- Read: `~/.claude/skills/search-insights/SKILL.md`

- [x] **Step 1: Verify frontmatter consistency**

Check the file has:

- `name` field matching directory name (`bodai-radar`)
- `description` field contains specific trigger phrases for auto-detection
- `description` field mentions the skill name explicitly ("bodai radar")

Run:

```bash
head -5 ~/.claude/skills/bodai-radar/SKILL.md
```

- [x] **Step 2: Verify no overlap with quality-pulse**

Read `~/.claude/skills/quality-pulse/SKILL.md` and confirm:

- quality-pulse does deep trend analysis with `analyze_trends`, `correlate_systems`

- bodai-radar reads a single health signal and routes to quality-pulse for depth

- Both use `detect_anomalies` but with different workflows (quality-pulse is trend-focused, bodai-radar is snapshot-focused)

- [x] **Step 3: Verify no overlap with ecosystem-awareness**

Read `~/.claude/skills/ecosystem-awareness/SKILL.md` and confirm:

- ecosystem-awareness discovers repo structure and roles via `list_repos`

- bodai-radar checks operational health via `get_health`

- Different tools, different purpose, no overlap

- [x] **Step 4: Verify no overlap with session-archaeologist**

Read `~/.claude/skills/session-archaeologist/SKILL.md` and confirm:

- session-archaeologist recovers past decisions via `search_all_systems`

- bodai-radar checks current activity via `get_activity_summary`

- Different tools, different time horizon, no overlap

- [x] **Step 5: Verify no overlap with run-quality-checks**

Read `~/.claude/skills/run-quality-checks/SKILL.md` and confirm:

- run-quality-checks triggers quality gates via `crackerjack run`

- bodai-radar reads recent quality metrics via `get_crackerjack_quality_metrics`

- One triggers action, the other reads status

- [x] **Step 6: Verify no overlap with search-insights**

Read `~/.claude/skills/search-insights/SKILL.md` and confirm:

- search-insights does semantic search across system memories

- bodai-radar shows health signals

- Completely different purpose and tools

- [x] **Step 7: Verify all five component tools are referenced**

Confirm the SKILL.md references one tool from each component:

1. Crackerjack: `mcp__session-buddy__get_crackerjack_quality_metrics`
1. Mahavishnu: `mcp__mahavishnu__get_health`
1. Akosha: `mcp__akosha__detect_anomalies`
1. Dhara: `mcp__dhara__get_adapter_health`
1. Session-Buddy: `mcp__session-buddy__get_activity_summary`

- [x] **Step 8: Verify cross-references are correct**

- bodai-radar references `run-quality-checks`, `quality-pulse`, `session-archaeologist`, `search-insights`, `ecosystem-awareness`, `manage-pools`, `orchestrate-workflow`, `search-sessions`

- All referenced skills exist in `~/.claude/skills/`

- No references to non-existent skills

- [x] **Step 9: Verify graceful degradation is consistent**

Confirm:

- Each component can fail independently without blocking others

- Grey circle used for unavailable components

- No filesystem fallback (intentional — prevents false health signals)

- Summary template handles partial availability

- [x] **Step 10: Final commit (if any fixes needed)**

If validation found issues, fix and commit. If no issues, this step is a no-op.
