---
status: draft
role: implementation
topic: learning-pipeline
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
blocks_on: []
---

# Session Archaeologist Design

## **Goal:** A Claude Code skill that recovers lost context from past sessions — decisions, solutions, and conversation history — by searching across all Session-Buddy instances via Akosha and synthesizing results into coherent narratives. **Architecture:** Pure SKILL.md prompt file in `~/.claude/skills/`. No Python code, no new MCP tools. Composes existing Akosha MCP tools (`search_all_systems`, `query_knowledge_graph`, `generate_embedding`) with a narrative-synthesis workflow that differentiates it from the generic `search-insights` skill. **Tech Stack:** Claude Code skills (SKILL.md with YAML frontmatter), Akosha MCP tools, Session-Buddy MCP tools (fallback)

## Skill Definition

**Name:** `session-archaeologist`
**File:** `~/.claude/skills/session-archaeologist/SKILL.md`
**Invocation:** `/session-archaeologist` (manual) + auto-detect on context recovery questions
**Auto-detect patterns:** "what did we decide about X?", "has anyone solved X before?", "what's the history of X?", "what happened in the session about X?", "why did we choose X?", "when did we change X?"

## Core Principle

Recover context, don't just search. The skill takes raw conversation fragments and weaves them into a coherent narrative of what happened, what was decided, and why. This is the key differentiator from `search-insights`, which returns ranked results.

## Sub-Modes

| Mode | Trigger | Primary Tools | Output Format |
|------|---------|---------------|---------------|
| **Decision archaeology** | "What did we decide about X?" | `search_all_systems` + `query_knowledge_graph` | Decision statement, rationale, alternatives considered, outcome |
| **Error archaeology** | "Has anyone solved X before?" | `search_all_systems` | Error description, root cause, fix applied, verification steps |
| **Context recovery** | "What happened in the session about X?" | `search_all_systems` + `query_knowledge_graph` | Chronological timeline of key moments with artifacts |

## Core Workflow

```
User asks a context recovery question
    |
    v
1. Detect intent: decision / error-solution / context recovery
    |
    v
2. Reformulate query for archaeology-specific search
    |  (e.g., "what did we decide about adapters?" becomes
    |   "adapter decision rationale alternative approach chosen")
    |
    v
3. Search conversations via Akosha (search_all_systems)
    |  - Primary query + expanded queries for completeness
    |  - Filter by system_id if user specifies a repo/project
    |
    v
4. Enrich with knowledge graph (query_knowledge_graph)
    |  - Find entities related to the topic
    |  - Trace relationships between decisions and implementations
    |
    v
5. Synthesize findings into narrative
    |  - Deduplicate across conversation fragments
    |  - Order chronologically
    |  - Extract: decision, rationale, alternatives, outcome
    |
    v
6. Present as structured report
```

## Query Reformulation

The skill reformulates the user's natural question into archaeology-specific queries to improve recall:

| User asks | Reformulated query |
|-----------|-------------------|
| "What did we decide about the adapter migration?" | "adapter migration decision rationale alternative approach chosen why" |
| "Has anyone debugged this exact error before?" | "[error message] root cause fix solution debug resolved" |
| "What's the history of the pool scaling decision?" | "pool scaling decision history evolution timeline rationale" |
| "Why did we choose X over Y?" | "X versus Y comparison trade-off decision rationale chosen" |

## Output Format

### Decision Archaeology

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

### Error Archaeology

```markdown
## Error Recovery: [topic]

**Error:** [what went wrong]

**Root cause:** [diagnosis from conversation]

**Fix applied:** [what was done]

**Verification:** [how it was confirmed fixed]

**Source sessions:**
- [session-id] ([date]) — [relevant excerpt]
```

### Context Recovery

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

## Edge Cases

- **No results found**: Suggest broadening the query, checking that Session-Buddy is syncing to Akosha, or trying a different phrasing. If Akosha has very few sessions, note that data accumulates with each session.
- **Multiple conflicting decisions**: Present both with dates, let the user determine which is current. Flag the conflict explicitly.
- **Akosha unavailable**: Fall back to Session-Buddy MCP tools directly (`search_conversations`, `search_reflections`). If Session-Buddy MCP is also unavailable, fall back to direct filesystem search on Session-Buddy data directories.
- **Too many results**: Focus on the most recent and highest-similarity results. Summarize rather than dumping all excerpts.

## Relationship to Existing Skills

| Skill | Overlap | Boundary |
|-------|---------|----------|
| `search-insights` | None | search-insights returns ranked search results; session-archaeologist returns synthesized narratives |
| `code-archaeologist` | None | code-archaeologist searches code graphs and function usage; session-archaeologist searches conversations |
| `quality-pulse` | None | quality-pulse analyzes time-series metrics; session-archaeologist recovers conversation context |
| `ecosystem-awareness` | None | ecosystem-awareness discovers repo structure; session-archaeologist mines session history |
| `run-quality-checks` | None | run-quality-checks triggers quality gates; session-archaeologist reviews past quality work |

## Fallback Strategy

Three-tier fallback (same pattern as code-archaeologist and quality-pulse):

1. **Akosha MCP tools** (primary) — `search_all_systems`, `query_knowledge_graph`, `generate_embedding`. Cross-system semantic search with knowledge graph enrichment.
1. **Session-Buddy MCP tools** (secondary) — `search_conversations`, `search_reflections`, `search_entities`. Direct search within the local Session-Buddy instance. No cross-system scope.
1. **Direct filesystem** (last resort) — Grep across Session-Buddy data directories (typically `~/.session-buddy/` or project-local `.session-buddy/`). Text search only, no semantic understanding.

When falling back, inform the user: "Akosha is not available. Falling back to [tier]. [Limitation note]."

## Auto-Detection

The `description` field in YAML frontmatter drives Claude Code's skill matching. It must include:

- Specific trigger phrases from real developer workflows
- The skill name explicitly
- Clear differentiation phrases ("past decisions", "conversation history", "context recovery")

## No New Code Required

Pure SKILL.md file. Composes existing MCP tools into a focused workflow. No Python changes to Akosha, Mahavishnu, or Session-Buddy. Deployment is zero — drop the file in `~/.claude/skills/`.
