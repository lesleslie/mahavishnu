---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
topic: observability
---

# Bodai Radar Design

**Goal:** A Claude Code skill that provides a unified health dashboard across all 5 Bodai components in a single command. Fire once, get a traffic-light summary in thirty seconds.

**Architecture:** Pure SKILL.md prompt file in `~/.claude/skills/`. No Python code, no new MCP tools. Composes one "best signal" tool from each Bodai component into a parallel fan-out sweep with graceful degradation.

**Tech Stack:** Claude Code skills (SKILL.md with YAML frontmatter), MCP tools from Crackerjack, Mahavishnu, Akosha, Dhara, and Session-Buddy.

______________________________________________________________________

## Skill Definition

**Name:** `bodai-radar`
**File:** `~/.claude/skills/bodai-radar/SKILL.md`
**Invocation:** `/bodai-radar` (manual) + auto-detect on ecosystem health questions
**Auto-detect patterns:** "how's the ecosystem?", "system health", "is everything green?", "bodai status", "morning standup", "radar check", "ecosystem health", "show me the radar"

## Core Principle

One command, five components, thirty seconds. Each Bodai component contributes its single best health signal. The skill synthesizes all five into a unified traffic-light dashboard. No drill-down, no deep analysis — that's what the dedicated skills are for.

## The Five Signals

Each component provides exactly one primary signal. The skill calls these in parallel and synthesizes:

| Component | Tool | What it returns | Traffic light logic |
|-----------|------|----------------|-------------------|
| **Crackerjack** | `mcp__session-buddy__get_crackerjack_quality_metrics` | Quality scores, pass/fail rates, adapter performance over N days | Green: all adapters passing. Yellow: 1+ adapter score degrading. Red: adapter failures detected |
| **Mahavishnu** | `mcp__mahavishnu__get_health` | Overall health status, active workflows, pool status | Green: healthy. Yellow: degraded dependency. Red: critical failure |
| **Akosha** | `mcp__akosha__detect_anomalies` on `conversation_count` | Anomalies in cross-system activity metrics | Green: no anomalies. Yellow: low-confidence anomaly (< 2 std dev). Red: high-confidence anomaly (>= 2 std dev) |
| **Dhara** | `mcp__dhara__get_storage_status` | Storage tier health and availability | Green: all tiers healthy. Yellow: one tier degraded. Red: tier unavailable |
| **Session-Buddy** | `mcp__session-buddy__get_activity_summary` | Recent session activity (conversations, reflections, code graphs) | Green: normal activity. Yellow: low activity (potential staleness). Red: no activity (may be stuck) |

**Why these specific tools:** Each was chosen as the single most informative "pulse check" for its component — the one call that answers "is this component healthy right now?" without requiring additional context or follow-up.

## Core Workflow

```
User runs /bodai-radar (or asks an ecosystem health question)
    |
    v
1. Fan-out: call all 5 signal tools (parallel, independent)
    |
    v
2. Collect results, apply traffic-light logic per component
    |
    v
3. Synthesize into unified dashboard
    |
    v
4. Write summary with actionable recommendation
    |
    v
5. If any component was unreachable, note at bottom
```

## Output Format

Single markdown dashboard:

```markdown
## Bodai Radar — [date]

| Component | Status | Signal | Detail |
|-----------|--------|--------|--------|
| Crackerjack | :green_circle: | Quality: 92/100 | All adapters passing |
| Mahavishnu | :green_circle: | Healthy | 3 active pools, 8 workers |
| Akosha | :yellow_circle: | Anomaly detected | conversation_count spike on session-buddy |
| Dhara | :green_circle: | Storage healthy | 3 tiers operational |
| Session-Buddy | :green_circle: | 12 sessions (2h) | 8 conversations, 4 reflections |

### Summary
4/5 components healthy. Akosha detected a conversation_count anomaly — may indicate unusual activity on session-buddy. Run `/quality-pulse` for trend details.
```

### Summary Logic

The summary line adapts based on the overall state:

| State | Summary template |
|-------|-----------------|
| All green | "All 5 components healthy. No action needed." |
| 1+ yellow | "N/5 components healthy. [Component] shows [signal]. Run `[related-skill]` for details." |
| 1+ red | "N/5 components healthy. **[Component] requires attention**: [detail]." |
| Components unavailable | "N/5 components reachable. [Unavailable list]. Ensure all MCP servers are running." |

### Skill Routing

When the summary flags a problem, it routes to the appropriate dedicated skill:

| Component flagged | Recommended skill |
|-------------------|-------------------|
| Crackerjack yellow/red | `run-quality-checks` (for immediate action) or `quality-pulse` (for trends) |
| Mahavishnu yellow/red | `manage-pools` (pool issues) or `orchestrate-workflow` (workflow issues) |
| Akosha yellow/red | `quality-pulse` (trend analysis) or `search-insights` (deep search) |
| Dhara yellow/red | Direct user to check Dhara MCP server |
| Session-Buddy yellow/red | `session-archaeologist` (context recovery) or `search-sessions` (recent sessions) |

## Graceful Degradation

If a component's MCP server is unreachable:

1. Catch the failure gracefully — never let one component failure block the others
1. Mark the unreachable component as `:grey_circle: Unavailable`
1. Continue collecting results from remaining components
1. Include a note at the bottom of the dashboard: "[N] component(s) unreachable: [list]. For full radar, ensure all MCP servers are running."

## Edge Cases

- **No Session-Buddy crackerjack metrics**: If `get_crackerjack_quality_metrics` returns empty data (no recent Crackerjack runs), mark Crackerjack as `:grey_circle: No recent data` and suggest running `crackerjack run`.
- **Akosha has no tracked metrics**: If `detect_anomalies` returns no data, mark Akosha as `:grey_circle: No metrics tracked` and note that data accumulates with sessions.
- **All components down**: Report "All 5 components unreachable. Check MCP server status." and suggest verifying `.mcp.json` configuration.
- **Conflicting signals**: If one component reports green but another reports red in a related area (e.g., Crackerjack red but Mahavishnu green), present both without trying to reconcile — the dashboard is a signal, not a diagnosis.

## Relationship to Existing Skills

| Skill | Overlap | Boundary |
|-------|---------|----------|
| `quality-pulse` | None | quality-pulse does deep trend analysis on quality metrics; bodai-radar shows a single quality score |
| `session-archaeologist` | None | session-archaeologist recovers past decisions; bodai-radar shows current activity level |
| `ecosystem-awareness` | Minimal | ecosystem-awareness discovers repo structure and roles; bodai-radar checks operational health |
| `run-quality-checks` | None | run-quality-checks triggers quality gates; bodai-radar reads recent quality metrics passively |
| `search-insights` | None | search-insights does semantic search; bodai-radar shows system health signals |
| `manage-pools` | None | manage-pools manages pool lifecycle; bodai-radar reports pool health |

## Fallback Strategy

Unlike most skills that have a three-tier fallback, Bodai Radar uses **parallel graceful degradation**:

- Each component is queried independently
- A failure in one does not affect the others
- No filesystem fallback — if an MCP server is down, the signal is simply unavailable
- This is intentional: a health check that silently falls back to stale data would give a false sense of health

## No New Code Required

Pure SKILL.md file. Composes existing MCP tools into a focused workflow. No Python changes to any Bodai component. Deployment is zero — drop the file in `~/.claude/skills/`.
