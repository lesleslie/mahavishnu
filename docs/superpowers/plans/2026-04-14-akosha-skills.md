# Akosha Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create two standalone Claude Code skills (SKILL.md files) that compose existing Akosha MCP tools into focused workflows: Code Archaeologist for cross-repo code discovery and Quality Pulse for adapter execution trend analysis.

**Architecture:** Pure SKILL.md prompt files in `~/.claude/skills/`. No Python code, no new MCP tools. Each skill composes existing Akosha MCP tools into multi-step workflows with smart defaults, structured output, and Mahavishnu-config-aware fallback.

**Tech Stack:** Claude Code skills (SKILL.md with YAML frontmatter), Akosha MCP tools, Mahavishnu ecosystem.yaml/repos.yaml resolution

**Spec:** `docs/superpowers/specs/2026-04-14-akosha-skills-design.md`

______________________________________________________________________

## File Structure

| File | Responsibility |
|------|---------------|
| `~/.claude/skills/code-archaeologist/SKILL.md` | Cross-repo code discovery skill |
| `~/.claude/skills/quality-pulse/SKILL.md` | Adapter execution trend analysis skill |

No other files are created or modified. These are pure prompt files.

**Pattern reference** (read-only, for consistency):

- `~/.claude/skills/search-insights/SKILL.md` — Akosha search skill (same backend)
- `~/.claude/skills/ecosystem-awareness/SKILL.md` — Mahavishnu ecosystem discovery (same fallback pattern)
- `~/.claude/skills/run-quality-checks/SKILL.md` — Crackerjack quality skill (same domain)

______________________________________________________________________

### Task 1: Create Code Archaeologist SKILL.md

**Files:**

- Create: `~/.claude/skills/code-archaeologist/SKILL.md`

- [x] **Step 1: Create the directory**

Run: `mkdir -p ~/.claude/skills/code-archaeologist`

- [x] **Step 2: Write the SKILL.md file**

Create `~/.claude/skills/code-archaeologist/SKILL.md` with this content:

```markdown
---
name: code-archaeologist
description: Use when searching for code patterns, implementations, or solutions across multiple repositories. Use when user asks "how did other repos handle X?", "who uses function/class X?", "what repos implement X?", "show me similar implementations", "find cross-repo patterns", or "has anyone solved X before?". Also use when user wants to discover shared code patterns across the Bodai ecosystem.
---

# Code Archaeologist

## Overview

Discovers implementations, shared patterns, and past decisions across all repositories ingested into Akosha's code graph. Combines structural code similarity with conversation context from Session-Buddy to answer "how did someone else solve this?"

**Core principle:** Search across all repos' code and conversations, not just the current one.

## When to Use

**Use when:**
- Searching for how other repos implemented a specific pattern
- Finding which repos use a specific function, class, or module
- Discovering similar implementations across the ecosystem
- Looking for past decisions about an approach or pattern
- Understanding cross-repo dependencies and shared code

**Don't use when:**
- Searching within a single repo (use Grep/Glob directly)
- Searching for past conversations without code context (use `search-insights`)
- Running quality checks (use `run-quality-checks`)
- Discovering available repos (use `ecosystem-awareness`)

## Sub-Modes

The skill routes to the appropriate workflow based on the user's question:

| Mode | When to Use | Primary Tools |
|------|-------------|---------------|
| **Similar repos** | "What repos are like X?" "Show me repos similar to Y" | `list_ingested_code_graphs` -> `find_similar_repositories` |
| **Function archaeology** | "Who uses function/class X?" "Where is X implemented?" | `get_cross_repo_function_usage` -> `search_all_systems` |
| **Pattern mining** | "How do repos handle X?" "What patterns exist for X?" | `search_all_systems` + code graph context |

## Implementation

### Step 1: Check Akosha Availability

Verify Akosha MCP tools are accessible by calling a lightweight probe:

```

mcp\_\_akosha\_\_get_liveness()

```

If Akosha is unavailable, proceed to **Fallback** (Step 5).

### Step 2: List Ingested Code Graphs

Discover which repos have been indexed:

```

mcp\_\_akosha\_\_list_ingested_code_graphs()

````

If no code graphs exist, inform the user:
> "No code graphs are ingested yet. Run `code_ingest_directory` on your target repos via Session-Buddy to enable cross-repo search."

### Step 3: Route to Sub-Mode

**Similar repos workflow:**

1. Call `mcp__akosha__find_similar_repositories` with the target repo path
2. Present results ranked by structural similarity score
3. For top matches, call `mcp__akosha__search_all_systems` to find relevant conversations about architectural decisions

**Function archaeology workflow:**

1. Call `mcp__akosha__get_cross_repo_function_usage` with the function/class name
2. If the result is empty or contains no usages, inform the user: "No cross-repo usages found for `[name]`. It may not be indexed yet — run `code_ingest_directory` on the target repos first." Then stop.
3. Present file locations with line numbers across all repos
4. For each usage site, call `mcp__akosha__search_all_systems` for context about why it was used that way

**Pattern mining workflow:**

1. Call `mcp__akosha__search_all_systems` with the pattern query
2. If no results are returned, inform the user: "No matching patterns found across ingested repos. Try a broader query or ingest more repos." Then stop.
3. Extract repo and file references from conversation results
4. Cross-reference with code graph data for structural context
5. Present a summary: which repos implement this pattern, how they differ, and what trade-offs were discussed

### Step 4: Present Findings

Format results as structured markdown:

```markdown
## Findings: [query topic]

### Repos with Similar Implementations

| Repo | Similarity | Key Difference |
|------|-----------|----------------|
| repo-a | 0.87 | Uses strategy pattern |
| repo-b | 0.82 | Simpler, single-function approach |

### Relevant Conversations

**repo-a (2026-03-15):**
> "We chose the strategy pattern because..."

### Recommendation

Based on [N] repos, the most common approach is [X].
Repo [Y] has the cleanest implementation at `path/to/file.py:42`.
````

### Step 5: Fallback (Akosha Unavailable)

If Akosha MCP tools are not available, fall back to direct filesystem search across repos:

1. Read repo paths from Mahavishnu's config, respecting the resolution chain:
   - Primary: `settings/ecosystem.yaml` (canonical)
   - Fallback: `settings/repos.yaml` (legacy)
   - If neither exists and Mahavishnu MCP is available: `mcp__mahavishnu__list_repos`
1. Use Grep/Glob to search across resolved repo paths
1. Inform the user: "Akosha is not available. Falling back to direct filesystem search across [N] repos. For richer semantic search, ensure Akosha is running."

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| **Searching current repo only** | Missing cross-repo solutions | Always start with `list_ingested_code_graphs` |
| **Not enriching with conversation context** | Results lack reasoning | Follow up code results with `search_all_systems` |
| **Ignoring similarity scores** | Including irrelevant matches | Filter results below 0.5 similarity |

## Related Skills

- **REQUIRED:** `ecosystem-awareness` - Discover which repos exist before searching
- **RELATED:** `search-insights` - Broader Akosha semantic search (conversations, not code)
- **RELATED:** `quality-pulse` - After finding patterns, check if quality is degrading

````

- [x] **Step 3: Verify the file**

Run: `cat ~/.claude/skills/code-archaeologist/SKILL.md | head -3`
Expected: YAML frontmatter with `name: code-archaeologist`

- [x] **Step 4: Commit**

Run:
```bash
git add ~/.claude/skills/code-archaeologist/SKILL.md
git commit -m "feat: add code-archaeologist skill for cross-repo code discovery"
````

______________________________________________________________________

### Task 2: Create Quality Pulse SKILL.md

**Files:**

- Create: `~/.claude/skills/quality-pulse/SKILL.md`

- [x] **Step 1: Create the directory**

Run: `mkdir -p ~/.claude/skills/quality-pulse`

- [x] **Step 2: Write the SKILL.md file**

Create `~/.claude/skills/quality-pulse/SKILL.md` with this content:

```markdown
---
name: quality-pulse
description: Use when analyzing quality trends, adapter performance, or degradation signals across the Bodai ecosystem. Use when user asks "are any adapters slowing down?", "is X getting better/worse?", "any unusual quality patterns?", "show me quality trends", "detect quality anomalies", "are repos correlated on metric X?", or "what's the quality health across repos?". Also use when user wants a quality dashboard or health summary.
---

# Quality Pulse

## Overview

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

mcp\_\_akosha\_\_get_liveness()

```

If Akosha is unavailable, proceed to **Fallback** (Step 5).

### Step 2: Discover Available Metrics

```

mcp\_\_akosha\_\_get_system_metrics()

````

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
3. If the result includes fewer than 5 data points, prepend a warning to the output:
   > "⚠️ Low data volume: trend based on [N] data points — results may not be statistically reliable. Run `crackerjack run` more times to build a larger sample."
4. Present:
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
````

### Step 5: Fallback (Akosha Unavailable)

If Akosha MCP tools are not available, use this three-tier fallback chain:

**Tier 1 (Akosha):** Unavailable — skip.

**Tier 2 (Mahavishnu MCP):** If `mcp__mahavishnu__*` tools are available, call `mcp__mahavishnu__get_health` to retrieve service health status across ecosystem components. Present as a simplified health table without trend data.

**Tier 3 (Local Crackerjack data):** If Mahavishnu MCP is also unavailable, direct user to check Crackerjack's local data directly:

```
sqlite3 .crackerjack/adapter_learning.db "SELECT adapter_name, COUNT(*), AVG(execution_time_ms) FROM executions GROUP BY adapter_name ORDER BY AVG(execution_time_ms) DESC;"
```

Inform the user at each tier: "Akosha is not available. Showing [tier description] only. For cross-system trends, ensure Akosha is running at `http://localhost:8682`."

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

````

- [x] **Step 3: Verify the file**

Run: `cat ~/.claude/skills/quality-pulse/SKILL.md | head -3`
Expected: YAML frontmatter with `name: quality-pulse`

- [x] **Step 4: Commit**

Run:
```bash
git add ~/.claude/skills/quality-pulse/SKILL.md
git commit -m "feat: add quality-pulse skill for adapter execution trend analysis"
````

______________________________________________________________________

### Task 3: Validate Both Skills

**Files:**

- Read: `~/.claude/skills/code-archaeologist/SKILL.md`

- Read: `~/.claude/skills/quality-pulse/SKILL.md`

- [x] **Step 1: Verify frontmatter consistency**

Check both files have:

- `name` field (no spaces, lowercase-with-hyphens matching directory name)
- `description` field contains specific trigger phrases for auto-detection
- `description` field mentions the skill name explicitly

Run:

```bash
# Extract and compare frontmatter
for f in code-archaeologist quality-pulse; do
  echo "=== $f ==="
  head -5 ~/.claude/skills/$f/SKILL.md
  echo
done
```

- [x] **Step 2: Verify no overlap with search-insights**

Read `~/.claude/skills/search-insights/SKILL.md` and confirm:

- Code Archaeologist focuses on code graphs + function usage (not in search-insights)

- Quality Pulse focuses on time-series analytics + anomaly detection (not in search-insights)

- Both reference search-insights as "RELATED" not "REQUIRED"

- [x] **Step 3: Verify fallback chain is consistent**

Both skills reference the same fallback chain:

1. Akosha MCP tools (primary)
1. Mahavishnu config resolution: `settings/ecosystem.yaml` then `settings/repos.yaml`
1. Direct filesystem / sqlite3

Verify this matches Mahavishnu's `_load_repos()` at `mahavishnu/core/app.py:615-688`.

- [x] **Step 4: Verify cross-references are correct**

- Code Archaeologist references `ecosystem-awareness` and `quality-pulse` correctly

- Quality Pulse references `code-archaeologist` and `run-quality-checks` correctly

- Neither skill references non-existent skills

- [x] **Step 5: Final commit (if any fixes needed)**

If validation found issues, fix and commit. If no issues, this step is a no-op.
