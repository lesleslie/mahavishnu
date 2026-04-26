# Agent & Skill Modernization: Ecosystem Tool Integration

**Date:** 2026-04-26
**Status:** Draft
**Approach:** Layered context enrichment (Approach A)
**Prerequisite:** Config Consolidation spec (2026-04-26-config-consolidation-design.md)

## 1. Problem Statement

After consolidating all Claude Code configuration into the Mahavishnu project directory, the content of agents and skills needs to be modernized to take full advantage of the ecosystem's MCP servers and tools.

**Current state:**
- **101 agents**: Only 5 (5%) reference any ecosystem component. The remaining 97 are generic stubs with no awareness of Mahavishnu, Akosha, Session-Buddy, Crackerjack, or Dhara.
- **22 skills** (20 native + 5 symlinked from `~/.agents/`): 18 (82%) already reference ecosystem tools, but many have stale references (wrong tool names, outdated ports, missing new tools).

**Impact:** When Claude dispatches to a subagent or invokes a skill, it doesn't know what ecosystem MCP tools are available, leading to redundant work, missed optimization opportunities, and inconsistent tool usage patterns.

## 2. Goals

- Enrich 15 agent descriptions with ecosystem MCP tool references
- Add MCP server reference tables to all 20 skills
- Fix stale references across all skills (wrong names, missing tools, outdated ports)
- Establish a standard format for ecosystem awareness in both agents and skills
- Add validation to `mahavishnu config validate` to catch stale references

## 3. Non-Goals

- Rewriting agents as full instruction documents (they stay as compact stubs)
- Adding new agents or skills (this is content modernization only)
- Changing agent/skill file formats or directory structure
- Modifying plugins or non-ecosystem configs

## 4. Current State Audit

### 4.1 Agent Awareness

| Category | Count | Percentage |
|----------|-------|------------|
| Reference ecosystem components | 4 | 4% |
| No ecosystem references | 97 | 96% |

**Ecosystem-aware agents (4):**
- `mahavishnu-specialist.md` — references Mahavishnu
- `akasha-specialist.md` — references "Akasha" (misspelled — should be "Akosha", grep misses it)
- `mcp-integration-expert.md` — references Crackerjack, MCP, WebSocket
- `refactoring-specialist.md` — references Crackerjack
- `oneiric-specialist.md` — references Oneiric

### 4.2 Skill MCP Integration

| Category | Count | Percentage |
|----------|-------|------------|
| Reference ecosystem MCP tools | 18 | 82% |
| Missing ecosystem MCP refs | 2 | 9% (swiftui-ipc-client, testing-strategies) |
| Have stale references (estimated) | ~10 | ~45% |

**Most-used skills (by usage count):**
1. `session-buddy:checkpoint` — 323 invocations
2. `session-buddy:crackerjack-run` — 24 invocations
3. `crackerjack:init` / `crackerjack:run` — 14 invocations each

### 4.3 Available MCP Servers (33 total)

| Server | Port | Type | Primary Tools |
|--------|------|------|---------------|
| akosha | 8682 | HTTP | search_all_systems, find_function_usage, search_code_patterns, detect_anomalies |
| session-buddy | 8678 | HTTP | search_conversations, store_reflection, checkpoint, code_ingest_file |
| crackerjack | 8676 | HTTP | crackerjack_run, search_code, smart_error_analysis |
| mahavishnu | 8680 | HTTP | pool_spawn, trigger_workflow, list_repos, pool_health |
| dhara | 8683 | HTTP | put, get, list_adapters, upsert_service, record_event |
| context7 | N/A | Plugin | query-docs, resolve-library-id |
| zai-mcp-server | N/A | NPX | analyze_image, extract_text_from_screenshot |
| web-reader | N/A | HTTP | webReader |
| web-search-prime | N/A | HTTP | web_search_prime |

## 5. Design: Agent Description Enrichment

### 5.1 Target Agents

**5 ecosystem agents** (refresh existing references):
1. `mahavishnu-specialist` — update with current Mahavishnu MCP tools
2. `akasha-specialist` — rename reference to "Akosha", update tool names
3. `oneiric-specialist` — update with current Oneiric/Dhara MCP tools
4. `mcp-integration-expert` — update with full MCP tool inventory
5. `refactoring-specialist` — update with Akosha pattern search tools

**10 generic agents** (add ecosystem awareness):

| Agent | Ecosystem MCP Tools to Reference |
|-------|----------------------------------|
| `code-reviewer` | crackerjack (quality gates), akosha (cross-repo patterns) |
| `security-auditor` | crackerjack (security scans), mahavishnu (auth), session-buddy (error logs) |
| `python-pro` | crackerjack (pytest), akosha (code patterns), mahavishnu (pools) |
| `architecture-council` | akosha (cross-repo patterns), dhara (adapter patterns) |
| `devops-troubleshooter` | mahavishnu (health checks), akosha (metrics), session-buddy (logs) |
| `pytest-hypothesis-specialist` | crackerjack (test runner), akosha (error patterns) |
| `database-operations-specialist` | dhara (persistence), akosha (trend analysis) |
| `frontend-developer` | mahavishnu (workflow routing), session-buddy (component search) |
| `documentation-specialist` | akosha (semantic search), session-buddy (conversation context) |
| `incident-responder` | akosha (anomaly detection), mahavishnu (workflow status), session-buddy (error logs) |

### 5.2 Enrichment Format

**Before (5 lines):**
```yaml
---
name: python-pro
description: Write idiomatic Python code advanced features like decorators, generators, async/await. Optimizes performance, implements design patterns, ens...
model: sonnet
---
```

**After (8-10 lines):**
```yaml
---
name: python-pro
description: >-
  Write idiomatic Python code with advanced features like decorators, generators,
  async/await. Optimizes performance, implements design patterns, ensures type safety.
  Ecosystem: use mcp__crackerjack__crackerjack_run for quality gates,
  mcp__akosha__search_code_patterns for cross-repo Python patterns,
  mcp__mahavishnu__pool_route_execute for distributed test execution.
model: sonnet
---
```

### 5.3 Enrichment Rules

1. **Keep descriptions under 300 characters** — agents are persona stubs, not instruction documents
2. **Use exact `mcp__<server>__<tool>` names** — match the Claude Code tool registry
3. **Only reference tools the agent would realistically use** — don't add irrelevant tools
4. **Don't reference tools requiring secrets** — agents don't have auth context
5. **Ecosystem line is a routing hint** — it helps Claude decide when to dispatch to this agent
6. **Fix existing misspellings** — e.g., "Akasha" → "Akosha" in akasha-specialist.md
7. **Preserve existing description content** — the enrichment appends, doesn't replace

## 6. Design: Skills MCP Reference Table

### 6.1 Standard Format

Add an "Available MCP Servers" section to each skill's SKILL.md, positioned after "Overview" and before "Implementation."

**Full table format** (for skills using 3+ servers):
```markdown
## Available MCP Servers

| Server | Port | Relevant Tools | Use When |
|--------|------|---------------|----------|
| akosha | 8682 | search_all_systems, find_function_usage, search_code_patterns | Cross-repo semantic search, pattern discovery |
| session-buddy | 8678 | search_conversations, store_reflection, checkpoint | Session context, knowledge persistence |
| crackerjack | 8676 | crackerjack_run, get_skills_for_issue, smart_error_analysis | Quality gates, test execution, error analysis |
```

**Inline format** (for skills using 1-2 servers):
```markdown
## Available MCP Servers

Primary: **session-buddy** (8678) — search_conversations, store_reflection
Secondary: **akosha** (8682) — search_all_systems (for cross-repo context)
```

### 6.2 Server Selection Per Skill

| Skill | Primary Server | Secondary Server | Tertiary Server |
|-------|---------------|-----------------|-----------------|
| manage-pools | mahavishnu | session-buddy | — |
| code-archaeologist | akosha | session-buddy | — |
| orchestrate-workflow | mahavishnu | crackerjack | — |
| run-quality-checks | crackerjack | mahavishnu | — |
| search-insights | akosha | session-buddy | — |
| persistent-state | dhara | session-buddy | — |
| learn-from-errors | session-buddy | crackerjack | — |
| ecosystem-awareness | mahavishnu | akosha | — |
| quality-pulse | akosha | crackerjack | — |
| session-archaeologist | akosha | session-buddy | — |
| bodai-radar | session-buddy | mahavishnu | akosha |
| auto-coordinate | mahavishnu | session-buddy | — |
| smart-scaling | mahavishnu | — | — |
| capture-insights | session-buddy | akosha | — |
| search-sessions | session-buddy | — | — |
| sweep-repositories | mahavishnu | — | — |
| resolve-components | dhara | mahavishnu | — |
| configure-oneiric | dhara | — | — |
| swiftui-ipc-client | session-buddy | mahavishnu | — |
| testing-strategies | crackerjack | session-buddy | akosha |

### 6.3 Table Rules

1. **Only include servers the skill actually uses** — not all 33
2. **Port numbers included** for quick reference
3. **"Use When" column** provides guidance on when each server is relevant
4. **Position after Overview** — visible early in the skill document
5. **List relevant tools only** — don't dump every tool from a server
6. **Order by relevance** — primary server first

## 7. Design: Stale Reference Cleanup

### 7.1 Categories of Staleness

| Issue | Example | Fix |
|-------|---------|-----|
| **Wrong tool names** | `code_ingest_file` instead of `mcp__session-buddy___code_ingest_file_impl` | Update to exact `mcp__<server>__<tool>` format |
| **Missing new tools** | Skill doesn't reference `code_search_symbols` or `get_symbol_graph` (added with code indexing) | Add relevant new tools |
| **Outdated server info** | "Session-Buddy on port 8765" (actual: 8678) | Update port numbers |
| **Missing alternatives** | Only references `grep` when `mcp__akosha__search_code_patterns` would be better | Add MCP alternative |
| **Dead references** | References a tool that was renamed or removed | Remove or update |
| **Misspelled names** | "Akasha" instead of "Akosha" in agent descriptions | Fix spelling |

### 7.2 Validation

Add a stale reference check to `mahavishnu config validate`:

```python
# Pseudocode for validation
for skill_file in all_skills:
    content = read(skill_file)
    mcp_references = extract_mcp_references(content)  # Find all mcp__* patterns
    for ref in mcp_references:
        if ref not in registered_tools:
            report(f"Stale reference in {skill_file}: {ref} not found in tool registry")
```

This validation runs as part of `mahavishnu config validate` and reports:
- Unknown MCP tool references
- References to servers not in `.mcp.json`
- Tool name format violations (missing `mcp__` prefix)

## 8. Delivery Order

| # | Item | Depends On | Effort |
|---|------|-----------|--------|
| 1 | Enrich 5 ecosystem agent descriptions | Config consolidation complete | Small |
| 2 | Enrich 10 generic agent descriptions | Config consolidation complete | Small |
| 3 | Add MCP reference tables to 18 existing skills | Config consolidation complete | Medium |
| 4 | Add MCP reference tables to 2 missing skills | Config consolidation complete | Small |
| 5 | Fix stale references across all 20 skills | Items 3-4 | Medium |
| 6 | Add stale reference validation to `mahavishnu config validate` | Config consolidation complete | Small |
| 7 | Commit and verify with fresh Claude Code session | Items 1-6 | Small |

## 9. Acceptance Criteria

1. All 15 enriched agents include at least one `mcp__` tool reference in their description
2. All 20 skills have an "Available MCP Servers" section
3. `mahavishnu config validate` passes with zero stale reference warnings
4. No agent description exceeds 300 characters
5. All `mcp__` references in skills use exact tool names from the registry
6. No port number references are outdated (all match `.mcp.json`)
7. "Akasha" misspelling is corrected to "Akosha" in all files
8. `swiftui-ipc-client` skill references at least one ecosystem MCP server
9. `testing-strategies` skill references Crackerjack tools
10. A fresh Claude Code session from Mahavishnu correctly routes to enriched agents

## 10. ADR Reference

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent format | Compact stub enrichment | Agents are personas, not instruction documents. Keep them lightweight. |
| Skill MCP table | Standardized section after Overview | Visible early, consistent format, easy to maintain. |
| Tool name format | `mcp__<server>__<tool>` | Exact Claude Code format. Enables automated validation. |
| Top 10 agents | Usage + ecosystem relevance | Balances actual usage data with ecosystem value. |
| Validation | Integrated into `mahavishnu config validate` | Catches staleness at config validation time, not just at write time. |
