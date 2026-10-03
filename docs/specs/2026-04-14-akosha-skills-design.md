---
status: draft
role: implementation
topic: learning-pipeline
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Akosha Skills Design: Code Archaeologist & Quality Pulse

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Goal:** Two standalone Claude Code skills that make Akosha's cross-system intelligence discoverable and actionable from developer workflows.
> **Architecture:** Pure SKILL.md prompt files — no Python code, no new MCP tools. Each skill composes existing Akosha MCP tools into focused workflows with smart defaults and structured output. Falls back to Mahavishnu's repo resolution chain when Akosha is unavailable.
> **Tech Stack:** Claude Code skills (SKILL.md), Akosha MCP tools, Mahavishnu ecosystem.yaml/repos.yaml

______________________________________________________________________

## Skill 1: Code Archaeologist

**Name:** `code-archaeologist`
**File:** `~/.claude/skills/code-archaeologist/SKILL.md`
**Invocation:** `/code-archaeologist` (manual) + auto-detect on cross-repo code questions
**Auto-detect patterns:** "how did other repos handle X?", "who uses function/class X?", "what repos implement X?"

### Core Workflow

```
User asks cross-repo code question
    |
    v
1. Detect intent: cross-repo code question
    |
    v
2. List ingested code graphs (mcp__akosha__list_ingested_code_graphs)
    |
    v
3. Route to appropriate sub-mode based on intent
    |
    +-- Similar repos: find_similar_repositories
    +-- Function archaeology: get_cross_repo_function_usage
    +-- Pattern mining: search_all_systems + code graph context
    |
    v
4. Enrich with conversation context (mcp__akosha__search_all_systems)
    |
    v
5. Present findings: similar implementations, shared patterns, decisions
```

### Sub-Modes

| Mode | Trigger | Primary Tools | Output |
|------|---------|---------------|--------|
| **Similar repos** | "What repos are like X?" | `list_ingested_code_graphs` -> `find_similar_repositories` | Ranked repo list with similarity scores |
| **Function archaeology** | "Who uses function/class X?" | `get_cross_repo_function_usage` -> `search_all_systems` | File locations, line numbers, usage context |
| **Pattern mining** | "How do repos handle X?" | `search_all_systems` + code graph context | Relevant implementations + decision excerpts |

### Output Format

Structured markdown:

- Ranked results with similarity scores
- File locations with line numbers
- Relevant conversation excerpts (decisions, reasoning)
- Actionable suggestions ("Repo Y solved this by...")

### Edge Cases

- **No code graphs ingested**: Prompt user to run `code_ingest_directory` on target repos via Session-Buddy
- **Akosha unavailable**: Fall back to direct Grep/Glob across repo paths resolved from Mahavishnu's config chain:
  1. `settings/ecosystem.yaml` (canonical, has roles + coordination)
  1. `settings/repos.yaml` (legacy, repos-only)
  1. Mahavishnu MCP `list_repos` tool (if Mahavishnu available)
- **No matches**: Suggest broadening query or checking ingestion status via `list_ingested_code_graphs`

### Relationship to Existing Skills

- **Does NOT overlap** `search-insights`: that skill covers generic Akosha queries. This skill is narrowly focused on cross-repo code discovery.
- **Complements** `ecosystem-awareness`: that skill discovers which repos exist; this skill finds what's inside them.

______________________________________________________________________

## Skill 2: Quality Pulse

**Name:** `quality-pulse`
**File:** `~/.claude/skills/quality-pulse/SKILL.md`
**Invocation:** `/quality-pulse` (manual) + auto-detect on quality trend/degradation questions
**Auto-detect patterns:** "are any adapters slowing down?", "is X getting better/worse?", "any unusual quality patterns?"

### Core Workflow

```
User asks quality metrics question
    |
    v
1. Detect intent: quality metrics / adapter performance question
    |
    v
2. Discover available metrics (mcp__akosha__get_system_metrics)
    |
    v
3. Route to appropriate sub-mode based on intent
    |
    +-- Health snapshot: summarize current metrics
    +-- Trend analysis: analyze_trends on specific metric
    +-- Anomaly alert: detect_anomalies on error rates
    +-- Correlation: correlate_systems between repos
    |
    v
4. Present findings: trend direction, anomalies, correlations
```

### Sub-Modes

| Mode | Trigger | Primary Tools | Output |
|------|---------|---------------|--------|
| **Health snapshot** | "How's quality across repos?" | `get_system_metrics` | Traffic-light status per system |
| **Trend analysis** | "Are adapters slowing down?" | `analyze_trends` | Trend arrows with confidence |
| **Anomaly alert** | "Any unusual quality patterns?" | `detect_anomalies` | Ranked anomaly table with severity |
| **Correlation** | "Is X related to Y?" | `correlate_systems` | Correlation matrix |

### Output Format

Structured markdown:

- Traffic-light status per system (green/yellow/red)
- Trend arrows with confidence (increasing/stable/decreasing + R-squared)
- Anomaly table: severity, timestamp, expected vs actual
- Correlation matrix when comparing systems
- Actionable suggestions ("ruff failure rate up 40% in repo X -- check recent config changes")

### Edge Cases

- **No metrics tracked yet**: Guide user -- data comes from Session-Buddy sync and adapter learning (activated 2026-04-14 in Crackerjack). Suggest running `crackerjack run` to generate data.
- **Akosha unavailable**: Direct user to check Crackerjack's local `.crackerjack/adapter_learning.db` via `sqlite3`
- **Insufficient data points**: Warn that trend analysis needs minimum data; suggest waiting for more Crackerjack runs

### Relationship to Code Archaeologist

Complementary but independent:

- Code Archaeologist answers "how did someone solve this?"
- Quality Pulse answers "is something getting worse?"
- Can be chained: Quality Pulse surfaces a degradation -> Code Archaeologist finds how another repo solved it

______________________________________________________________________

## Shared Design Decisions

### Auto-Detection

Both skills auto-detect relevant questions via the SKILL.md frontmatter `description` field. Claude's skill matching reads the description and triggers when the user's question matches the intent patterns. The description must include explicit trigger phrases so the matching is reliable. No code changes needed; Claude Code's native skill system handles this.

### Fallback Strategy

Both skills follow the same three-tier fallback:

1. **Akosha MCP tools** (primary -- semantic intelligence)
1. **Mahavishnu MCP tools** (secondary -- repo discovery + orchestration)
1. **Direct filesystem** (last resort -- grep across resolved repo paths)

Repo path resolution for fallback follows Mahavishnu's `_load_repos()` chain:

- Primary: `settings/ecosystem.yaml`
- Fallback: `settings/repos.yaml` (legacy)
- Validation: `MahavishnuApp._load_repos()` at `mahavishnu/core/app.py:615`

### No New Code Required

These are pure SKILL.md files. They compose existing MCP tools into focused workflows. No Python changes to Akosha, Mahavishnu, or Crackerjack. This keeps deployment to zero -- just drop the files in `~/.claude/skills/`.

### Backlog Items

The following skills are deferred to future sessions:

- **Ecosystem Pulse**: Quick health + trend summary across all Bodai components in one shot. Uses `get_system_metrics`, `analyze_trends`, `detect_anomalies`, `get_graph_statistics`, `get_storage_status`.
- **Session Archaeologist**: Search across all Session-Buddy instances for past conversations, decisions, and solutions. Uses `search_all_systems`, `generate_embedding`, `query_knowledge_graph`.
