______________________________________________________________________

## name: code-archaeologist description: Use when searching for code patterns, implementations, or solutions across multiple repositories. Use when user asks "how did other repos handle X?", "who uses function/class X?", "what repos implement X?", "show me similar implementations", "find cross-repo patterns", or "has anyone solved X before?". Also use when user wants to discover shared code patterns across the Bodai ecosystem.

# Code Archaeologist

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| akosha | 8682 | summary | mcp\_\_akosha\_\_search_all_systems, mcp\_\_akosha\_\_find_function_usage, mcp\_\_akosha\_\_search_code_patterns | 60s |
| session-buddy | 8678 | full | mcp\_\_session-buddy\_\_search_conversations, mcp\_\_session-buddy\_\_\_code_search_symbols_impl | 30s |

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

| Mode | When to Use | Primary Tools |
|------|-------------|---------------|
| **Similar repos** | "What repos are like X?" "Show me repos similar to Y" | `search_code_patterns` -> `search_all_systems` |
| **Function archaeology** | "Who uses function/class X?" "Where is X implemented?" | `find_function_usage` -> `search_all_systems` |
| **Pattern mining** | "How do repos handle X?" "What patterns exist for X?" | `search_all_systems` + code graph context |

## Implementation

### Step 1: Check Akosha Availability

Verify Akosha MCP tools are accessible by calling a lightweight probe:

```
mcp__akosha__get_liveness()
```

If Akosha is unavailable, proceed to **Fallback** (Step 5).

### Step 2: List Ingested Code Graphs

Discover which repos have been indexed:

```
mcp__akosha__search_code_patterns(query="*")
```

If no code graphs exist, inform the user:

> "No code graphs are ingested yet. Run `code_ingest_directory` on your target repos via Session-Buddy to enable cross-repo search."

### Step 3: Route to Sub-Mode

**Similar repos workflow:**

1. Call `mcp__akosha__search_code_patterns` with a representative query for the target repo
1. Present results ranked by structural similarity score
1. For top matches, call `mcp__akosha__search_all_systems` to find relevant conversations about architectural decisions

**Function archaeology workflow:**

1. Call `mcp__akosha__find_function_usage` with the function/class name
1. Present file locations with line numbers across all repos
1. For each usage site, call `mcp__akosha__search_all_systems` for context about why it was used that way

**Pattern mining workflow:**

1. Call `mcp__akosha__search_all_systems` with the pattern query
1. Extract repo and file references from conversation results
1. Cross-reference with code graph data for structural context
1. Present a summary: which repos implement this pattern, how they differ, and what trade-offs were discussed

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
```

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
| **Searching current repo only** | Missing cross-repo solutions | Always start with `search_code_patterns` to find indexed repos |
| **Not enriching with conversation context** | Results lack reasoning | Follow up code results with `search_all_systems` |
| **Ignoring similarity scores** | Including irrelevant matches | Filter results below 0.5 similarity |

## Related Skills

- **REQUIRED:** `ecosystem-awareness` - Discover which repos exist before searching
- **RELATED:** `search-insights` - Broader Akosha semantic search (conversations, not code)
- **RELATED:** `quality-pulse` - After finding patterns, check if quality is degrading

```
```
