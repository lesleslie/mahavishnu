______________________________________________________________________

## name: code-knowledge-builder description: > Proactive code knowledge graph enrichment. Use automatically when exploring unfamiliar code, making significant edits, or reasoning through design decisions. Ingests key files into the Session-Buddy knowledge graph, creates entities for architectural decisions, and maintains graph freshness. NOT user-invoked — Claude activates this autonomously during code work.

# Code Knowledge Builder

## Overview

## Available MCP Servers

| Server | Port | Context Mode | Relevant Tools | Default Timeout |
|--------|------|-------------|---------------|----------------|
| session-buddy | 8678 | full | mcp\_\_session-buddy\_\_\_code_ingest_file_impl, mcp\_\_session-buddy\_\_\_code_ingest_directory_impl, mcp\_\_session-buddy\_\_\_code_search_symbols_impl | 30s |
| akosha | 8682 | summary | mcp\_\_akosha\_\_search_code_patterns, mcp\_\_akosha\_\_find_function_usage | 60s |

Every code exploration and significant edit should enrich the knowledge graph for future sessions. This skill teaches Claude to selectively ingest code, capture design decisions, and keep the knowledge graph current.

**Core principle:** Read code once, understand it forever. Every exploration should reduce future exploration time.

## Activation

**Reactive** — triggers automatically when Claude:

- Starts exploring an unfamiliar module, package, or codebase area
- Completes a significant code change (new class, refactor, new adapter, interface change)
- Is asked "how does X work?" about code it hasn't seen before
- Encounters architecturally significant code (base classes, protocols, abstract interfaces)

**Not a slash command.** Claude uses this autonomously during code work.

## Quick Reference

```
# 1. Check if project is already tracked
code_list_projects()

# 2. Search for relevant symbols
code_search_symbols(query, project, symbol_kind, limit)

# 3. Understand symbol relationships
code_get_symbol_graph(symbol_name, depth)

# 4. After significant edits, re-ingest the file
code_ingest_file(file_path, project, language)

# 5. Capture architectural decisions as entities
create_entity(name="decision:<topic>", entity_type="design_decision", observations=[...])
create_relation(from="decision:<topic>", to="<code_symbol>", relation_type="design_for")

# 6. Periodically check for duplicate content
find_duplicates(content, content_type, threshold)
```

## Implementation

### Step 1: Check Project Tracking Status

**Before any code exploration, check if the project is already in the knowledge graph.**

```
Call mcp__session-buddy___code_list_projects_impl with: {}
```

**If project is NOT tracked:**

- Ingest the relevant directory (not the whole project — use `max_files=50` to bound the operation)

```
Call mcp__session-buddy___code_ingest_directory_impl with:
  - directory: <project_path>
  - pattern: "**/*.py"  (or language-appropriate pattern)
  - project: <project_name>
  - max_files: 50
```

**If project IS tracked:**

- Skip bulk ingestion, proceed to symbol search

### Step 2: Search for Relevant Symbols

When exploring unfamiliar code, search for symbols before reading files:

```
Call mcp__session-buddy___code_search_symbols_impl with:
  - query: <what you're looking for — class name, function name, concept>
  - project: <project_name>
  - symbol_kind: <optional — "class", "function", "module", or null for all>
  - limit: 20
```

**Use this to:**

- Discover which files contain relevant code
- Find the class hierarchy before reading implementation details
- Identify related functions that might also need modification

### Step 3: Get Symbol Relationships

For key symbols found in Step 2, understand their relationships:

```
Call mcp__session-buddy___code_get_symbol_graph_impl with:
  - symbol_name: <the symbol name>
  - depth: 2  (default — 1 for immediate neighbors, 3 for deep traversal)
```

**This returns:**

- The symbol's definition location
- Symbols it calls (outgoing edges)
- Symbols that call it (incoming edges)
- Related symbols (same module, same base class, etc.)

**Use this to:**

- Understand the impact of modifying a function (who calls it?)
- Find the base class before implementing a subclass
- Discover utility functions that are used alongside the target code

### Step 4: Re-ingest After Significant Edits

**Only re-ingest files that changed significantly.** This is NOT triggered by every edit.

**Ingest when:**

- A new class, function, or module is added
- An interface, protocol, or abstract base class is changed
- A significant refactor changes a file's structure (not line-level changes)
- A base class or shared utility is modified
- An adapter or integration point is added/changed

**Do NOT ingest when:**

- Only reading a file for context
- Making trivial changes (typo fixes, formatting, import reordering)
- The file is auto-generated, boilerplate, or configuration
- The change is a simple bug fix (that's `learn-from-errors` territory)

```
Call mcp__session-buddy___code_ingest_file_impl with:
  - file_path: <absolute path to the file>
  - project: <project_name>
  - language: <optional — "python", "typescript", etc. or null for auto-detect>
```

### Step 5: Capture Design Decisions

When Claude reasons through a design choice during code work, capture it as an entity.

**Capture when:**

- Choosing between multiple approaches ("I chose X over Y because...")
- Making an architectural decision ("I used the adapter pattern because...")
- Discovering a non-obvious constraint ("This has to be async because...")
- Setting a convention or pattern for the codebase

```
Call mcp__session-buddy__create_entity with:
  - name: "decision:<short_topic>"  (e.g., "decision:adapter pattern for engines")
  - entity_type: "design_decision"
  - observations: [
      "Decision: <what was decided>",
      "Rationale: <why this approach was chosen>",
      "Trade-off: <what was sacrificed>",
      "Context: <feature, bug, or refactor that prompted this>",
      "Files: <affected files>"
    ]
```

**Link the decision to the relevant code:**

```
Call mcp__session-buddy__create_relation with:
  - from_entity: "decision:<topic>"
  - to_entity: "<code_symbol_name>"
  - relation_type: "design_for"
```

### Step 6: Check for Duplicates

**After creating 2+ entities in a session, check for knowledge bloat.**

```
Call mcp__session-buddy__find_duplicates with:
  - content: <the content you just created>
  - content_type: "reflection"  (design decisions are stored as reflections)
  - threshold: 0.85
  - limit: 5
```

**If duplicates found (similarity > 0.85):**

- Do NOT create a new entity — the existing one already covers this
- Instead, add a new observation to the existing entity using `add_observation`
- This prevents the knowledge graph from accumulating redundant entries

```
Call mcp__session-buddy__add_observation with:
  - entity_name: "<existing entity name>"
  - observation: "<additional context to add>"
```

## When NOT to Activate

- **Simple file reads:** Reading a file for context does not trigger knowledge building
- **Auto-generated code:** Don't ingest files that are generated by tools
- **Configuration files:** YAML, TOML, JSON configs don't benefit from symbol analysis
- **Test files:** Only ingest test files if they define shared fixtures or test utilities
- **User declines:** If the user says "skip the knowledge step"

## Entity Naming Convention

| Entity Type | Format | Example |
|---|---|---|
| Design decision | `decision:<short topic>` | `decision:adapter pattern for engines` |

Keep names under 60 characters. Use lowercase.

## Common Mistakes

| Mistake | Symptom | Fix |
|---|---|---|
| **Ingesting every file read** | Knowledge graph bloat, slow queries | Only ingest after significant edits |
| **Not checking project status** | Re-ingesting already-tracked projects | Always call `code_list_projects` first |
| **Creating entities for trivia** | Noisy search results | Only create entities for architectural decisions |
| **Forgetting to link decisions** | Orphaned entities with no connections | Always `create_relation` after `create_entity` |
| **Not checking for duplicates** | Near-identical entries polluting results | Call `find_duplicates` periodically |

## Related Skills

- `learn-from-errors` — Error learning (complementary — reactive knowledge)
- `capture-insights` — Broader insight capture format
- `search-sessions` — Search the knowledge graph built by this skill
- `ecosystem-awareness` — Repository discovery (upstream of code exploration)

## MCP Tools Used

| Tool | Purpose |
|---|---|
| `mcp__session-buddy___code_list_projects_impl` | Check if project is tracked |
| `mcp__session-buddy___code_search_symbols_impl` | Find relevant code symbols |
| `mcp__session-buddy___code_get_symbol_graph_impl` | Understand symbol relationships |
| `mcp__session-buddy___code_ingest_file_impl` | Index a file after significant edit |
| `mcp__session-buddy___code_ingest_directory_impl` | Bulk index new project (first time only) |
| `mcp__session-buddy__create_entity` | Create design decision entities |
| `mcp__session-buddy__create_relation` | Link decisions to code symbols |
| `mcp__session-buddy__add_observation` | Add context to existing entities |
| `mcp__session-buddy__find_duplicates` | Prevent knowledge bloat |
