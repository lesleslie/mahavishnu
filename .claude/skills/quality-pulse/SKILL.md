---
name: quality-pulse
description: Use when analyzing quality trends, adapter performance, or degradation signals across the Bodai ecosystem. Use when user asks "are any adapters slowing down?", "is X getting better/worse?", "any unusual quality patterns?", "show me quality trends", "detect quality anomalies", "are repos correlated on metric X?", or "what's the quality health across repos?". Also use when user wants a quality dashboard or health summary.
---

# Quality Pulse

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| akosha | 8682 | summary | mcp__akosha__analyze_trends, mcp__akosha__detect_anomalies | 60s |
| crackerjack | 8676 | summary | mcp__crackerjack__get_comprehensive_status, mcp__crackerjack__get_stage_status | 120s |

Analyzes quality trends, anomalies, and cross-system correlations using Akosha's time-series analytics. Answers "is something getting worse?" across adapter execution, error rates, and workflow metrics collected by Crackerjack's adapter learning system.

**Core principle:** Detect quality degradation before it becomes an incident.

## When to Use

**Use when:**
- Checking quality trends across repos or adapters
- Detecting unusual patterns or anomalies in quality metrics
- Correlating quality metrics between systems
- Getting a health snapshot of the ecosystem
- After activating adapter learning in Crackerjack, to verify data is flowing

**Don't use when:**
- Running quality checks (use `run-quality-checks`)
- Searching for cross-repo code patterns (use `code-archaeologist`)
- Searching for past quality conversations (use `search-insights`)
- Discovering available repos (use `ecosystem-awareness`)

## Data Source

Quality data flows through this pipeline:
1. Crackerjack runs adapters with timing (`HookExecutor`, `AutofixCoordinator`)
2. Adapter execution data stored in `.crackerjack/adapter_learning.db` (SQLite)
3. Session-Buddy syncs memories to Akosha (cloud or HTTP)
4. Akosha aggregates into time-series metrics
5. This skill queries Akosha's analytics API

**Note:** Adapter learning was activated 2026-04-14 in Crackerjack. Data accumulates with each `crackerjack run`. Early analyses may have sparse data.

## Sub-Modes

| Mode | When to Use | Primary Tools |
|------|-------------|---------------|
| **Health snapshot** | "How's quality across repos?" | `get_system_metrics` |
| **Trend analysis** | "Are adapters slowing down?" | `analyze_trends` |
| **Anomaly alert** | "Any unusual quality patterns?" | `detect_anomalies` |
| **Correlation** | "Is X related to Y?" | `correlate_systems` |

## Implementation

### Step 1: Check Akosha Availability

Verify Akosha MCP tools are accessible:

```
mcp__akosha__get_liveness()
```

If Akosha is unavailable, proceed to **Fallback** (Step 5).

### Step 2: Discover Available Metrics

```
mcp__akosha__get_system_metrics()
```

This returns all metric names currently being tracked. Common metrics include:
- `conversation_count` — sessions per system
- `quality_score` — aggregate quality (if tracked)
- `error_rate` — failure frequency

If no metrics are returned, inform the user:
> "No metrics are tracked yet. Quality data comes from Crackerjack's adapter learning (activated 2026-04-14). Run `crackerjack run` a few times to generate data, then retry."

### Step 3: Route to Sub-Mode

**Health snapshot workflow:**

1. Call `mcp__akosha__get_system_metrics` to get current state
2. For each system, classify status:
   - **Green**: All metrics within normal range
   - **Yellow**: One metric trending negative (flagged by `analyze_trends`)
   - **Red**: Anomaly detected (flagged by `detect_anomalies`)
3. Present as a traffic-light table

**Trend analysis workflow:**

1. Identify the metric the user is asking about (default: all metrics)
2. Call `mcp__akosha__analyze_trends` with the metric name and appropriate time window
3. Present:
   - Trend direction (increasing/decreasing/stable)
   - Confidence (R-squared score)
   - Percent change
   - Recommendation based on direction

**Anomaly alert workflow:**

1. Call `mcp__akosha__detect_anomalies` on error-related metrics
2. Use threshold 2.0 (default) — 2 standard deviations
3. Present anomalies ranked by severity:
   - High: >3.0 standard deviations from mean
   - Medium: 2.0-3.0
   - Low: 1.5-2.0

**Correlation workflow:**

1. Identify the two metrics/systems the user wants to compare
2. Call `mcp__akosha__correlate_systems` with the metric name
3. Present correlation matrix:
   - Strong: |r| > 0.7
   - Moderate: 0.4 < |r| < 0.7
   - Weak: |r| < 0.4
4. Include interpretation: "High positive correlation between system A and B on error_rate — when one degrades, the other tends to follow."

### Step 4: Present Findings

Format results as structured markdown:

```markdown
## Quality Pulse: [date]

### Health Summary

| System | Status | Key Metric | Trend |
|--------|--------|-----------|-------|
| crackerjack | :green_circle: | error_rate: 2.1% | stable |
| mahavishnu | :yellow_circle: | workflow_duration: 45s | +12% |
| session-buddy | :red_circle: | conversation_count: 12 | anomaly |

### Anomalies Detected

| Severity | System | Metric | Expected | Actual | When |
|----------|--------|--------|----------|--------|------|
| High | system-b | error_rate | 3.0% | 12.1% | 2026-04-13 |

### Recommendation

[System] is showing [pattern]. Suggested action: [specific recommendation].
```

### Step 5: Fallback (Akosha Unavailable)

If Akosha MCP tools are not available:

1. Direct user to check Crackerjack's local data directly:
   ```
   sqlite3 .crackerjack/adapter_learning.db "SELECT adapter_name, COUNT(*), AVG(execution_time_ms) FROM executions GROUP BY adapter_name ORDER BY AVG(execution_time_ms) DESC;"
   ```
2. Inform the user: "Akosha is not available. Showing local Crackerjack data only. For cross-system trends, ensure Akosha is running."

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| **Too-low anomaly threshold** | False positives on normal variation | Use threshold 2.0+ for production data |
| **Not checking metric availability** | Errors on non-existent metrics | Always call `get_system_metrics` first |
| **Ignoring sparse data warnings** | Misleading trends from 2-3 data points | Report confidence level with every trend |

## Related Skills

- **RELATED:** `code-archaeologist` - After Quality Pulse surfaces degradation, find how other repos solved it
- **RELATED:** `search-insights` - Broader Akosha analytics (conversations, knowledge graph)
- **RELATED:** `run-quality-checks` - Trigger quality data collection before analyzing trends
```