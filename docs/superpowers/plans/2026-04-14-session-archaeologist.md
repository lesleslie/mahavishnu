# Session Archaeologist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a standalone Claude Code skill (SKILL.md file) that recovers past decisions, solutions, and session context from across all Session-Buddy instances via Akosha.

**Architecture:** Pure SKILL.md prompt file in `~/.claude/skills/`. No Python code, no new MCP tools. Composes existing Akosha MCP tools (`search_all_systems`, `query_knowledge_graph`, `generate_embedding`) with a narrative-synthesis workflow that differentiates it from the generic `search-insights` skill.

**Tech Stack:** Claude Code skills (SKILL.md with YAML frontmatter), Akosha MCP tools, Session-Buddy MCP tools (fallback)

**Spec:** `docs/superpowers/specs/2026-04-14-session-archaeologist-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `~/.claude/skills/session-archaeologist/SKILL.md` | Session context recovery skill |

No other files are created or modified. This is a pure prompt file.

**Pattern reference** (read-only, for consistency):
- `~/.claude/skills/code-archaeologist/SKILL.md` — Cross-repo code discovery skill (same backend, same fallback pattern)
- `~/.claude/skills/quality-pulse/SKILL.md` — Adapter execution trend analysis skill (same backend, same fallback pattern)
- `~/.claude/skills/search-insights/SKILL.md` — Generic Akosha search skill (same backend, but returns raw results, not narratives)

---

### Task 1: Create Session Archaeologist SKILL.md

**Files:**
- Create: `~/.claude/skills/session-archaeologist/SKILL.md`

- [ ] **Step 1: Create the directory**

Run: `mkdir -p ~/.claude/skills/session-archaeologist`

- [ ] **Step 2: Write the SKILL.md file**

Create `~/.claude/skills/session-archaeologist/SKILL.md` with this content:

```markdown
---
name: session-archaeologist
description: Use when recovering past decisions, solutions, or session context across the Bodai ecosystem. Use when user asks "what did we decide about X?", "has anyone solved X before?", "what's the history of X?", "what happened in the session about X?", "why did we choose X?", "when did we change X?", "show me the conversation about X", or "what was the outcome of X?". Also use when user wants to recover lost context from past development sessions.
---

# Session Archaeologist

## Overview

Recovers past decisions, solutions, and conversation history from across all Session-Buddy instances via Akosha. Unlike generic search, this skill **synthesizes raw conversation fragments into coherent narratives** — telling the story of what happened, what was decided, and why.

**Core principle:** Recover context, don't just search.

## When to Use

**Use when:**
- Recovering a past decision and its rationale ("what did we decide about the adapter migration?")
- Finding how someone solved a problem before ("has anyone debugged this exact error before?")
- Reconstructing session history ("what happened in the session about pool scaling?")
- Understanding why a choice was made ("why did we choose X over Y?")
- Tracing the evolution of a decision over time ("what's the history of X?")

**Don't use when:**
- Searching within current session only (use Session-Buddy's quick search)
- Searching for code patterns across repos (use `code-archaeologist`)
- Analyzing quality metrics and trends (use `quality-pulse`)
- Running quality checks (use `run-quality-checks`)
- Generic semantic search without narrative synthesis (use `search-insights`)
- Discovering available repos (use `ecosystem-awareness`)

## Data Source

Session data flows through this pipeline:
1. Claude Code sessions create conversations in Session-Buddy
2. Session-Buddy stores conversations, reflections, and entity knowledge graphs
3. Session-Buddy syncs memories to Akosha (cloud or HTTP)
4. Akosha indexes with vector embeddings for semantic search
5. This skill queries Akosha's `search_all_systems` and `query_knowledge_graph`

**Note:** The richness of results depends on how many sessions have been synced to Akosha. If data is sparse, the skill will note this and suggest running more sessions.

## Sub-Modes

| Mode | When to Use | Primary Tools |
|------|-------------|---------------|
| **Decision archaeology** | "What did we decide about X?" | `search_all_systems` + `query_knowledge_graph` |
| **Error archaeology** | "Has anyone solved X before?" | `search_all_systems` |
| **Context recovery** | "What happened in the session about X?" | `search_all_systems` + `query_knowledge_graph` |

## Implementation

### Step 1: Check Akosha Availability

Verify Akosha MCP tools are accessible:

```
mcp__akosha__get_liveness()
```

If Akosha is unavailable, proceed to **Fallback** (Step 6).

### Step 2: Detect Intent and Reformulate Query

Determine which sub-mode the user's question maps to, then reformulate for archaeology-specific search:

| User asks | Reformulated query |
|-----------|-------------------|
| "What did we decide about the adapter migration?" | "adapter migration decision rationale alternative approach chosen why" |
| "Has anyone debugged this exact error before?" | "[error message] root cause fix solution debug resolved" |
| "What's the history of the pool scaling decision?" | "pool scaling decision history evolution timeline rationale" |
| "Why did we choose X over Y?" | "X versus Y comparison trade-off decision rationale chosen" |
| "When did we change X?" | "X change timeline evolution when why modified" |

**Why reformulate?** Archaeology questions are often conversational ("what did we decide?"). Reformulating into keyword-rich queries improves recall by matching how decisions are actually discussed in session transcripts.

### Step 3: Search Conversations

Call `mcp__akosha__search_all_systems` with the reformulated query:

```
mcp__akosha__search_all_systems(query="<reformulated query>", limit=10)
```

If the user specified a project or repo, filter by `system_id`.

**For completeness**, run a second broader query if the first returns fewer than 3 results:
- Add related terms (e.g., if searching for "adapter migration", also search for "adapter refactor adapter rewrite")

### Step 4: Enrich with Knowledge Graph

For decision archaeology and context recovery modes, enrich findings:

```
mcp__akosha__query_knowledge_graph(entity_id="<topic entity>", limit=20)
```

This finds related entities, decisions, and implementations that may not have appeared in the conversation search.

### Step 5: Synthesize and Present Findings

Deduplicate across conversation fragments, order chronologically, and present in the appropriate narrative format:

**Decision archaeology output:**

```markdown
## Decision: [topic]

**Decision:** [what was decided]

**Rationale:** [why — extracted from conversation]

**Alternatives considered:**
- [Option A]: [why rejected]
- [Option B]: [why rejected]

**Outcome:** [what happened after — follow-up results if available]

**Source sessions:**
- [session-id] ([date]) — [relevant excerpt]
```

**Error archaeology output:**

```markdown
## Error Recovery: [topic]

**Error:** [what went wrong]

**Root cause:** [diagnosis from conversation]

**Fix applied:** [what was done]

**Verification:** [how it was confirmed fixed]

**Source sessions:**
- [session-id] ([date]) — [relevant excerpt]
```

**Context recovery output:**

```markdown
## Session Timeline: [topic]

| Date | Event | Key Detail |
|------|-------|------------|
| [date] | [what happened] | [notable detail] |

**Related entities:** [from knowledge graph]

**Key artifacts:** [files changed, decisions made, solutions applied]

**Source sessions:**
- [session-id] ([date]) — [relevant excerpt]
```

### Step 6: Fallback (Akosha Unavailable)

If Akosha MCP tools are not available, fall back to Session-Buddy MCP tools directly:

1. Try `mcp__session-buddy__search_conversations(query="<topic>", limit=10)`
2. Try `mcp__session-buddy__search_reflections(query="<topic>", limit=10)`
3. Try `mcp__session-buddy__search_entities(query="<topic>", limit=10)`

If Session-Buddy MCP is also unavailable, fall back to direct filesystem search:

1. Search across Session-Buddy data directories (typically `~/.session-buddy/` or project-local `.session-buddy/`)
2. Use Grep to search for topic keywords in conversation/reflection files

Inform the user: "Akosha is not available. Falling back to [Session-Buddy MCP / direct filesystem search]. [Limitation: no cross-system search / no semantic understanding]. For richer results, ensure Akosha is running."

## Edge Cases

| Situation | Response |
|-----------|----------|
| **No results found** | Suggest broadening the query, checking Session-Buddy → Akosha sync, or trying different phrasing. Note if data is sparse. |
| **Multiple conflicting decisions** | Present both with dates. Flag the conflict explicitly: "Two conflicting decisions found — [date] chose X, [date] chose Y." |
| **Too many results** | Focus on the most recent and highest-similarity results. Summarize rather than dumping all excerpts. |
| **Single fragment found** | Present what's available, note it's a partial picture. Suggest the user check related topics for more context. |

## Common Mistakes

| Mistake | Symptom | Fix |
|---------|---------|-----|
| **Not reformulating queries** | Missing results because conversational questions don't match session language | Always reformulate (see Step 2 table) |
| **Returning raw search results** | User gets a list of excerpts instead of a coherent story | Synthesize into narrative format (Step 5) |
| **Ignoring knowledge graph** | Missing related decisions and entities | Always enrich with `query_knowledge_graph` for decision and context modes |
| **Not checking data sparsity** | Misleading "no results" when Akosha simply has few sessions | Note data availability when results are thin |

## Related Skills

- **RELATED:** `search-insights` - Generic Akosha semantic search (returns ranked results, not narratives)
- **RELATED:** `code-archaeologist` - Cross-repo code discovery (searches code graphs, not conversations)
- **RELATED:** `quality-pulse` - Adapter execution trend analysis (searches metrics, not conversations)
- **RELATED:** `run-quality-checks` - Trigger quality checks (use before archaeology to generate fresh data)
```

- [ ] **Step 3: Verify the file**

Run: `head -3 ~/.claude/skills/session-archaeologist/SKILL.md`
Expected: YAML frontmatter with `name: session-archaeologist`

- [ ] **Step 4: Commit**

Run:
```bash
git add ~/.claude/skills/session-archaeologist/SKILL.md
git commit -m "feat: add session-archaeologist skill for past decision and context recovery"
```

---

### Task 2: Validate the Skill

**Files:**
- Read: `~/.claude/skills/session-archaeologist/SKILL.md`
- Read: `~/.claude/skills/search-insights/SKILL.md`
- Read: `~/.claude/skills/code-archaeologist/SKILL.md`

- [ ] **Step 1: Verify frontmatter consistency**

Check the file has:
- `name` field matching directory name (`session-archaeologist`)
- `description` field contains specific trigger phrases for auto-detection
- `description` field mentions the skill name explicitly

Run:
```bash
head -5 ~/.claude/skills/session-archaeologist/SKILL.md
```

- [ ] **Step 2: Verify no overlap with search-insights**

Read `~/.claude/skills/search-insights/SKILL.md` and confirm:
- Session Archaeologist focuses on narrative synthesis of decisions/solutions (not in search-insights)
- search-insights returns ranked results; session-archaeologist returns structured narratives
- Both reference `search_all_systems` as a tool but with different workflows

- [ ] **Step 3: Verify no overlap with code-archaeologist**

Read `~/.claude/skills/code-archaeologist/SKILL.md` and confirm:
- code-archaeologist searches code graphs and function usage (conversations are secondary enrichment)
- session-archaeologist searches conversations primarily (code is not in scope)
- Neither skill duplicates the other's sub-modes

- [ ] **Step 4: Verify cross-references are correct**

- Session Archaeologist references `search-insights`, `code-archaeologist`, `quality-pulse`, `run-quality-checks`, and `ecosystem-awareness`
- All referenced skills exist in `~/.claude/skills/`
- No references to non-existent skills

- [ ] **Step 5: Verify fallback chain is consistent**

Session Archaeologist uses a three-tier fallback:
1. Akosha MCP tools (primary)
2. Session-Buddy MCP tools (secondary)
3. Direct filesystem (last resort)

This differs from code-archaeologist/quality-pulse (which fall back to Mahavishnu config + filesystem) because session-archaeologist searches **conversation data**, not code or metrics. Session-Buddy is the correct fallback, not Mahavishnu.

- [ ] **Step 6: Final commit (if any fixes needed)**

If validation found issues, fix and commit. If no issues, this step is a no-op.
