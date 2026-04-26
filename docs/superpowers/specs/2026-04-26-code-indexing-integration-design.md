# Code Knowledge Graph Integration Design

**Status:** Draft
**Date:** 2026-04-26
**Source:** Multi-agent review of GitNexus integration alternatives

## 1. Objective

Add three missing code intelligence capabilities to the Bodai ecosystem by extending existing infrastructure rather than introducing new dependencies:

1. **Call chain resolution** — "find all transitive callers/callees of function X"
2. **Change impact analysis** — "if function X changes, what files and functions are affected?"
3. **Incremental re-indexing** — re-parse only changed files on git events

This design was shaped by a four-agent review (Architecture Council, Plan Agent, Delivery Lead, Explore Agent) that evaluated GitNexus (PolyForm Noncommercial license — blocked), LlamaIndex PropertyGraphIndex (wrong tool for code graphs — blocked), and multiple open-source alternatives before converging on extending existing infrastructure.

## 2. Background

### 2.1 What the ecosystem already has

| Layer | Component | Location | Status |
|-------|-----------|----------|--------|
| AST parsing | `CodeGraphAnalyzer` | `mcp-common/mcp_common/code_graph/analyzer.py` | Built — Python only (uses `ast` module, not tree-sitter) |
| Symbol extraction | Symbol/relationship extraction | `mcp-common/mcp_common/code_graph/` | Built — Python only |
| Graph storage (general) | DuckDB with DuckPGQ | `session-buddy/session_buddy/knowledge_graph_db.py` | Built — PGQ queries on `kg_entities`/`kg_relationships` |
| Graph storage (code-specific) | Reflection database | `session-buddy/session_buddy/` | Built — `store_code_graph_from_mahavishnu` stores here |
| Cross-repo ingestion | `CodeGraphIngester` | `akosha/akosha/ingestion/code_graph_ingester.py` | Built — pulls from Session-Buddy reflection DB |
| Symbol search | `code_search_symbols_impl` | Session-Buddy MCP tools | Built |
| Symbol graph | `code_get_symbol_graph_impl` | Session-Buddy MCP tools | Built |
| Tree-sitter MCP tools | 7 tools (parse, query, extract, batch) | Mahavishnu MCP server | Built — separate from CodeGraphAnalyzer |

> **Dual storage path discovery:** Session-Buddy has two separate code graph storage paths. (1) The DuckPGQ property graph uses `kg_entities`/`kg_relationships` tables and is populated by `KGExtractor` for general knowledge graph queries. (2) The reflection database is used by `store_code_graph_from_mahavishnu` for code-specific graph storage. Akosha pulls from the reflection DB, not from DuckPGQ. These paths must be reconciled — see Section 6.3.

### 2.2 What GitNexus provides that is missing

| Capability | Gap in ecosystem |
|-----------|-----------------|
| Precomputed call chains | No multi-hop call graph traversal |
| Change impact analysis | No reverse dependency queries |
| Incremental re-indexing | No git event triggers |
| Code clustering | Future — Phase 4 candidate |
| Code evolution tracking | Future — Phase 4 candidate |

### 2.3 What was evaluated and rejected

| Option | Rejection Reason |
|--------|-----------------|
| GitNexus (MCP server) | PolyForm Noncommercial 1.0.0 license restricts use, not just modification |
| LlamaIndex PropertyGraphIndex | Wrong data model for code graphs; `get_rel_map` limited to depth 2, limit 30; no directed path queries; requires external DB (Neo4j/TiDB) for production use; creates third graph authority |
| CodeSee | Commercial SaaS visualization product, not an embeddable engine |
| Sourcetrail | Archived (2021), no maintenance, no MCP |
| CodeQL | Heavyweight (GBs), designed for security auditing, not real-time agent queries |
| pyan | GPL license; call graphs only, no import resolution |
| Neo4j standalone | New infrastructure dependency; conflicts with plan non-goals |

## 3. Architecture

### 3.1 Component ownership

```
┌─────────────────────────────────────────────────────────────┐
│  Git hooks / CLI / Scheduled sweep                          │
│  (trigger mechanism)                                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Mahavishnu (orchestrator)                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Prefect workflow: index-code-graph                    │  │
│  │  1. Detect changed files (git diff)                   │  │
│  │  2. Parse with CodeGraphAnalyzer (Python ast)         │  │
│  │     or tree-sitter MCP tools (multi-lang)             │  │
│  │  3. Build call edges from AST                          │  │
│  │  4. Upsert nodes/edges to Session-Buddy               │  │
│  │  5. Notify Akosha to refresh                           │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │ MCP protocol
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Session-Buddy (graph owner — single authority)             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Storage path A: DuckPGQ property graph                │  │
│  │  - Tables: kg_entities, kg_relationships              │  │
│  │  - Used by: KGExtractor, general KG queries           │  │
│  │  - Reconciliation target for code graph (see 6.3)     │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │  Storage path B: Reflection database                   │  │
│  │  - Used by: store_code_graph_from_mahavishnu          │  │
│  │  - Pulled by: Akosha CodeGraphIngester                │  │
│  │  - Current code graph authority                        │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │  New MCP tools: code_call_chain, code_impact_analysis │  │
│  │  Query layer: PGQ for call chains, impact analysis     │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │ pull-based (from reflection DB)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Akosha (cross-system aggregation)                          │
│  - Pulls code graphs from Session-Buddy reflection DB       │
│  - Cross-repo similarity and function usage analysis       │
│  - Import pattern analysis across repositories              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Ownership model

| Concern | Owner | Authority type |
|---------|-------|---------------|
| Code graph storage and queries | **Session-Buddy** | Canonical (single authority) |
| AST parsing | **mcp-common** | Library (shared dependency) |
| Indexing workflow orchestration | **Mahavishnu** via Prefect | Orchestrator (dispatches, does not store) |
| Cross-repo aggregation | **Akosha** | Derived view (pulls from Session-Buddy) |
| Indexing trigger mechanism | **Mahavishnu** CLI | Entry point (forwards to Prefect workflow) |

### 3.3 Principle compliance

| Principle | Compliance |
|-----------|-----------|
| 1. One owner per concern | Session-Buddy owns the graph. No competing authorities. |
| 2. Cache is not authority | DuckDB is persistent storage, not cache. |
| 3. UI is presentation | Any TUI views of the code graph are read-only, querying Session-Buddy. |
| 4. Review-gated learning | Code graph is infrastructure, not learning. Learning pipeline consumes it. |
| 5. Reuse mature systems | Extends DuckDB/DuckPGQ, tree-sitter, mcp-common — all existing. |
| 6. Security boundaries | MCP protocol crossing between Mahavishnu and Session-Buddy (existing boundary). |
| 7. Typed contracts | All new MCP tools use Pydantic models for input/output. |
| 8. Degradation mode | Four-tier degradation defined in Section 5. |

## 4. New Components

### 4.1 Call chain resolution (Session-Buddy MCP tool)

**Tool name:** `code_call_chain`

**Input (Pydantic model):**
```python
class CallChainRequest(BaseModel):
    symbol_name: str           # qualified: "{repo_path}|||{file_path}|||{symbol_type}|||{symbol_name}" or bare for single-repo
    direction: Literal["callers", "callees", "both"]
    max_depth: int = 5
    repo_path: str | None = None  # disambiguates bare symbol_name
    edge_filter: list[str] | None = None  # e.g., ["calls", "imports"]
```

**Output:**
```python
class CallChainResult(BaseModel):
    root_symbol: str
    chains: list[CallChain]
    total_nodes: int
    truncated: bool
    stale: bool = False        # True if index is > 24 hours old
    last_indexed_at: datetime | None = None

class CallChain(BaseModel):
    path: list[str]            # qualified symbol names in traversal order
    depth: int
    edge_types: list[str]      # edge type at each hop
    files: list[str]           # file paths involved
```

**Implementation:** PGQ query on DuckDB knowledge graph. Bounded BFS with configurable max depth. Truncation flag indicates if results were cut off.

### 4.2 Change impact analysis (Session-Buddy MCP tool)

**Tool name:** `code_impact_analysis`

**Input (Pydantic model):**
```python
class ImpactAnalysisRequest(BaseModel):
    symbol_name: str           # qualified: "{repo_path}|||{file_path}|||{symbol_type}|||{symbol_name}" or bare (with repo_path to disambiguate)
    repo_path: str | None = None
    include_indirect: bool = True  # transitive dependents
    max_depth: int = 5
```

**Output:**
```python
class ImpactAnalysisResult(BaseModel):
    target: str
    direct_dependents: list[SymbolImpact]
    indirect_dependents: list[SymbolImpact]
    affected_files: list[str]
    risk_level: Literal["low", "medium", "high"]  # based on direct caller count
    blast_radius: int  # total transitive reach (all depths)
    stale: bool = False
    last_indexed_at: datetime | None = None

class SymbolImpact(BaseModel):
    symbol_name: str           # qualified symbol ID
    symbol_type: Literal["function", "class", "module"]
    file_path: str
    depth: int
    dependency_type: Literal["calls", "imports", "inherits", "contains", "implements"]
```

**Implementation:** Reverse call graph traversal via PGQ. `risk_level` is computed from direct dependents only: low (< 3 direct), medium (3-10 direct), high (> 10 direct). `blast_radius` counts total transitive reach (all depths) to give a holistic impact picture.

### 4.3 Incremental re-indexing workflow (Mahavishnu Prefect flow)

**Flow name:** `index-code-graph`

**Trigger mechanisms (priority order):**
1. **Git hook** — `.git/hooks/post-commit` calls `mahavishnu index --trigger git-event --repo <path>`
2. **Scheduled sweep** — Prefect schedule (default: every 15 minutes) calls `mahavishnu index --all-repos`
3. **Manual CLI** — `mahavishnu index --repo <path>` for on-demand full re-index

**Workflow steps:**
```
1. Detect changes
   - Git trigger: git diff HEAD~1 --name-only
   - Sweep: compare last-indexed commit hash to HEAD
   - Merge conflict: use merge base explicitly
     git diff $(git merge-base HEAD MERGE_HEAD) HEAD --name-only
   - Force push: if last-indexed commit hash is not an ancestor of HEAD,
     fall back to full re-index (commit history was rewritten)
   - Branch deletion: on branch prune events, mark all symbols from
     the deleted branch's files as candidates for cleanup sweep
     (soft delete, not hard delete — retained for code evolution in Phase 4)

2. Filter files
   - Skip non-code files (binary, generated, vendored)
   - Skip languages without parser support (currently Python via ast;
     tree-sitter MCP tools available for multi-lang but not yet wired)
   - Deduplicate across repos
   - Validate all paths against repos.yaml (reject unregistered repos)

3. Parse changed files
   - Use mcp-common CodeGraphAnalyzer for Python files
   - Fall back to tree-sitter MCP tools for non-Python files when available
   - Extract: functions, classes, imports, calls, inherits
   - Build edge list: (caller, callee, "calls"), (module, import, "imports")
   - Per-file parse failure handling:
     - Log the failure with file path, error message, and timestamp
     - Skip the failed file (do not abort the batch)
     - Increment a parse_failure_count metric
     - If parse_failure_count / total_files > 0.25, emit a warning
       and continue (do not silently skip majority failures)

4. Compute deletions
   - For removed/renamed symbols: mark as deleted in graph (soft delete)
   - Retain historical edges for code evolution (Phase 4)
   - Soft delete mechanism: set is_deleted=True, update last_indexed_at
     (no hard DELETE — historical edges remain traversable in Phase 4)

5. Upsert to Session-Buddy
   - Call Session-Buddy's code graph ingest MCP tools
   - Build ON CONFLICT DO UPDATE logic (upsert) — not currently
     implemented in KGExtractor (sequential inserts only)
   - Batch upserts for efficiency
   - Atomic replacement guarantee: write to a temporary table first,
     then INSERT INTO ... SELECT from temp to target in a single statement.
     DuckDB's single-writer model serializes writes but does not provide
     multi-statement DDL transactional atomicity (CREATE/DROP TABLE within
     a transaction may not be fully rollback-safe). Therefore, the approach is:
     (a) CREATE temporary table (connection-scoped, auto-dropped on disconnect),
     (b) INSERT all data into the temp table,
     (c) INSERT INTO target SELECT * FROM temp (single statement),
     (d) If step (c) fails, the temp table is auto-cleaned by DuckDB on disconnect.
     On startup, scan for and drop any orphaned temp tables older than 1 hour.
   - Record last-indexed commit hash per repo

6. Notify Akosha
   - Call Akosha's code graph refresh MCP tool to invalidate cached data
   - Akosha pulls updated graph on its next polling cycle (existing behavior)

7. Concurrent indexing safety
   - Use a per-repo PID-based lock file: `.git/mahavishnu-index.lock`
   - Lock file format: `{pid}\n{timestamp}\n{repo_path}`
   - On lock acquisition: write PID and timestamp. If lock file exists,
     read PID and check if process is alive (os.kill(pid, 0) on Unix).
     If PID is dead or lock is > 10 minutes old, acquire (stale lock recovery).
   - If lock is held by a live process, the second indexing operation skips
     with a log message (does not queue or retry)
   - Git hook fires asynchronously: `mahavishnu index --trigger git-event --repo <path> &`
     to avoid blocking the commit

8. Indexing audit trail
   - Log events using the existing TaskAuditLogger infrastructure:
     - `index_started` (repo, trigger type, commit hash)
     - `index_completed` (repo, files processed, nodes/edges upserted, duration)
     - `index_failed` (repo, error details, files processed before failure)
     - `signature_redacted` (file, symbol, pattern matched — not the value)
     - `hook_installed` / `hook_removed` (repo, hook type, user)
     - `path_validation_failed` (rejected path, requesting source)
```

**CLI interface:**
```bash
# Triggered by git hook
mahavishnu index --trigger git-event --repo /path/to/repo

# Scheduled sweep
mahavishnu index --all-repos --schedule "*/15 * * * *"

# Manual full re-index
mahavishnu index --repo /path/to/repo --full

# Check indexing status
mahavishnu index --status
```

### 4.4 Git hook installation

```bash
# One-time setup per repo
mahavishnu index --install-hooks --repo /path/to/repo

# Uninstall hooks
mahavishnu index --uninstall-hooks --repo /path/to/repo

# Force reinstall (overwrites existing hooks — requires confirmation)
mahavishnu index --install-hooks --repo /path/to/repo --force
```

**What `--install-hooks` does:**
1. Validates `--repo` path against `repos.yaml` (rejects unregistered repos)
2. Creates `.git/hooks/post-commit` with header comment identifying mahavishnu:
   ```sh
   #!/bin/sh
   # Managed by mahavishnu index --install-hooks
   # Remove with: mahavishnu index --uninstall-hooks --repo <path>
   mahavishnu index --trigger git-event --repo "$(pwd)"
   ```
3. Creates `.git/hooks/post-merge` and `.git/hooks/post-rewrite` with same content
4. If a hook file already exists and lacks the mahavishnu header comment, refuses to overwrite unless `--force` is passed
5. Sets file permissions to 0755 (owner read/write/execute, group/other read/execute)
6. Verifies hook file owner matches the repo directory owner (refuses if mismatch)

**What `--uninstall-hooks` does:**
1. Removes only hooks that contain the mahavishnu header comment
2. Leaves non-mahavishnu hooks untouched

### 4.5 Repo skill generation (--skills)

When `mahavishnu index --skills --repo <path>` is run, the system detects functional areas of the codebase and generates a `SKILL.md` file for each area. These skills give AI agents targeted context for the exact area of code being worked on.

**CLI interface:**
```bash
# Generate skills for a single repo
mahavishnu index --skills --repo /path/to/repo

# Generate skills for all repos
mahavishnu index --skills --all-repos

# Regenerate skills as part of scheduled sweep
mahavishnu index --all-repos --schedule "*/15 * * * *" --with-skills
```

**What `--skills` does:**

1. **Run community detection on the code graph**
   - Query all code nodes and edges from Session-Buddy for the target repo
   - Build an undirected NetworkX graph: nodes = symbols (functions, classes, modules), edges = calls + imports (weighted by frequency)
   - Run Leiden community detection (`leidenalg` package) to partition the graph into functional areas
   - Each community represents a cohesive functional area (e.g., "authentication", "content ingestion", "pool management")

2. **Analyze each community**
   - Identify entry points: symbols with high betweenness centrality (called by other communities)
   - Identify internal execution flows: topological ordering within the community
   - Identify cross-area connections: edges that cross community boundaries
   - Compute community metrics: size (symbol count), cohesion (edge density), coupling (cross-community edge ratio)

3. **Generate SKILL.md per community**
   - Output directory: `.claude/skills/generated/{community_name}/SKILL.md`
   - Follow the existing skill format (frontmatter + sections)
   - Include: key files, entry points, execution flows, cross-area connections, related communities

4. **Regeneration semantics**
   - Skills are regenerated on each `--skills` run (no incremental update — full regeneration)
   - Previous generated skills are overwritten
   - A `generated/` directory prefix distinguishes auto-generated skills from hand-written ones
   - If a community is too small (< 3 symbols), it is merged into the nearest neighboring community

**Community detection algorithm:**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Algorithm | Leiden (via `leidenalg`) | Guarantees well-connected communities; fixes Louvain's bad-connectivity defect where nodes can have zero intra-community edges |
| Resolution | 1.0 (default) | Higher resolution = more, smaller communities |
| Minimum community size | 3 symbols | Prevents trivial single-function "communities" |
| Edge weights | Call frequency + import indicator | Calls weighted higher than imports |

**SKILL.md template:**

```markdown
---
name: {community_name}
description: Auto-generated skill for the {community_name} functional area in {repo_name}. Covers {N} symbols across {M} files. Generated by mahavishnu index --skills.
---

# {community_name}

## Overview

Auto-detected functional area in `{repo_name}` containing {N} symbols across {M} files. Detected via Leiden community detection on the code graph.

**Community metrics:**
- Symbol count: {N}
- Edge density: {D}
- Cross-area connections: {C} edges to {K} other communities
- Last generated: {timestamp}

## Key Files

| File | Symbols | Role |
|------|---------|------|
| `path/to/file.py` | 12 | Core implementation |
| `path/to/module.py` | 8 | Data models |

## Entry Points

- `{symbol_name}` (`path/to/file.py:42`) — primary entry point, called by {K} other communities
- `{symbol_name}` (`path/to/file.py:108`) — secondary entry point

## Execution Flow

1. `{symbol_a}` calls `{symbol_b}` which calls `{symbol_c}`
2. `{symbol_d}` is the data transformation layer
3. Output flows to `{cross_area_target}` in the `{other_community}` area

## Cross-Area Connections

| Target Area | Connection Point | Direction |
|-------------|-----------------|-----------|
| `{community_b}` | `{symbol_x}` → `{symbol_y}` | Outgoing (this area calls target) |
| `{community_c}` | `{symbol_z}` → `{symbol_w}` | Incoming (target calls this area) |

## Degradation

This skill was auto-generated from the code graph. If the code graph is stale (> 24 hours old), the skill content may not reflect recent changes. Run `mahavishnu index --skills --repo {path}` to regenerate.
```

**Acceptance criteria:**

- `mahavishnu index --skills --repo <path>` generates at least one `SKILL.md` in `.claude/skills/generated/`
- Each generated skill follows the existing skill format (frontmatter + required sections)
- Entry points list symbols with betweenness centrality > community mean
- Communities with < 3 symbols are merged into neighboring communities
- No duplicate skill names generated for the same repo
- `mahavishnu index --skills --all-repos` generates skills for all registered repos without errors
- Generated skills are placed under `generated/` prefix and do not overwrite hand-written skills

**Dependency:** Requires the code graph to exist for the target repo (Section 4.1-4.3 must complete first). If no graph data exists, `--skills` fails with a structured `CodeGraphRequired` error suggesting the user run `mahavishnu index --repo <path>` first.

## 5. Degradation Modes

When the code graph is unavailable or incomplete, the system degrades in four tiers:

| Tier | Condition | Behavior |
|------|-----------|----------|
| **Tier 1: Full** | DuckDB graph available, recent index (< 24 hours old) | All tools return complete results |
| **Tier 2: Partial** | DuckDB available, stale index (last upsert > 24 hours ago) | Results include `stale: true` flag and `last_indexed_at` timestamp. Caller decides whether to act on stale data. |
| **Tier 3: Degraded** | DuckDB available, partial parse failures (> 0% but < 25% files failed) | Results include `parse_failures: int` count and `failed_files: list[str]`. Call chains may be incomplete — truncated edges are flagged. |
| **Tier 4: Unavailable** | DuckDB unavailable or corrupted, or parse failure rate > 25% | Tools return structured `CodeGraphUnavailable` response with `reason` field. Call chain falls back to tree-sitter single-file AST queries via Mahavishnu MCP tools. Impact analysis returns a list of files that would need manual review. No silent empty results. |

**Additional failure modes:**

| Failure | Detection | Response |
|---------|-----------|----------|
| DuckDB file corruption | DuckDB `PRAGMA integrity_check` on startup or query failure | Copy last-known-good snapshot (if available). Re-index from scratch. Log corruption event. |
| Atomic replacement failure | Staging table write succeeds but swap transaction fails | Roll back staging table. Existing graph remains intact. Alert via monitoring. |
| Per-file parse exception | Caught during parsing step | Log file path + error. Skip file. Continue batch. Emit metric. |

Each tier is documented, tested, and returns typed Pydantic responses — never raw errors or empty lists.

## 6. Data Model

### 6.1 Graph nodes

```python
class CodeGraphNode(BaseModel):
    symbol_id: str                    # qualified: "{repo_path}|||{file_path}|||{symbol_type}|||{symbol_name}"
    symbol_name: str                  # human-readable name (for display)
    symbol_type: Literal["function", "class", "module", "file", "variable"]
    file_path: str
    repo_path: str
    start_line: int | None = None
    end_line: int | None = None
    language: str
    signature: str | None = None       # for functions/classes
    complexity: int | None = None      # cyclomatic complexity
    is_deleted: bool = False           # soft delete for renamed/removed symbols (NEW — does not exist in current tables)
    last_indexed_at: datetime
    commit_hash: str
```

> **Qualified symbol IDs:** The `symbol_id` field uses the format `"{repo_path}|||{file_path}|||{symbol_type}|||{symbol_name}"` to guarantee uniqueness across repos and files. The `|||` sentinel delimiter is used instead of colons because colons appear in macOS paths (`/Users/name:folder/`), Python symbol names (type annotations, lambdas), and could cause ambiguous parsing. The `id` field in `kg_entities` stores a UUID; the `name` field stores the qualified symbol ID. This replaces bare `symbol_name` as the primary identifier in all graph queries. The `symbol_name` field is retained for display purposes and single-repo queries.

### 6.2 Graph edges

```python
class CodeGraphEdge(BaseModel):
    source: str          # qualified symbol_id
    target: str          # qualified symbol_id
    edge_type: Literal["calls", "imports", "inherits", "contains", "implements"]
    source_file: str
    target_file: str
    repo_path: str
    confidence: float = 1.0    # static analysis = 1.0; inferred < 1.0
    created_at: datetime
```

### 6.3 Storage path reconciliation

Session-Buddy currently has two code graph storage paths that must be reconciled:

| Path | Tables | Populated by | Consumer |
|------|--------|-------------|----------|
| DuckPGQ property graph | `kg_entities`, `kg_relationships` | `KGExtractor` | General KG queries |
| Reflection database | Code graph tables | `store_code_graph_from_mahavishnu` | Akosha `CodeGraphIngester` |

**Chosen approach: Option A** — extend the DuckPGQ tables with code-graph-specific columns stored as JSON properties (since `kg_entities.properties` is already a JSON blob). This avoids a schema migration on the relational columns while adding the fields PGQ queries need. Akosha's ingestion path would then switch from reflection DB to DuckPGQ (a one-time migration of existing data). This decision is binding for all subsequent sections in this spec — all SQL, PGQ queries, and acceptance criteria are written against Option A.

| Option | Description | Tradeoff |
|--------|-------------|----------|
| A: Extend DuckPGQ tables | Add `repo_path`, `commit_hash`, `is_deleted`, `complexity` columns to `kg_entities` | One storage path; PGQ queries are native; requires schema migration |
| B: Extend reflection DB | Add PGQ-compatible query layer to reflection DB | No migration; Akosha already pulls from here; PGQ support unclear |
| C: New dedicated tables | Create `code_nodes` / `code_edges` alongside existing tables | Clean separation; two code graph stores; more operational complexity |

### 6.4 Upsert logic

The reflection DB already implements upsert via `INSERT OR REPLACE` in `storage.py`. However, the DuckPGQ path (`kg_entities`/`kg_relationships`) uses sequential `INSERT` statements in `KGExtractor` with no conflict handling. The indexing workflow requires upsert semantics on whichever path becomes canonical:

- If **Option A** (extend DuckPGQ): implement `ON CONFLICT DO UPDATE` for `kg_entities` and `kg_relationships`
- If **Option B** (extend reflection DB): the existing `INSERT OR REPLACE` is sufficient; verify it handles the new code-graph-specific columns
- If **Option C** (new tables): implement `ON CONFLICT DO UPDATE` for the new tables

```sql
-- Upsert pattern for code nodes (Option A: DuckPGQ tables)
-- NOTE: kg_entities uses `id` as PRIMARY KEY, not `name`.
-- The qualified symbol_id is stored in `name` for display,
-- and in `properties` for structured access.
INSERT INTO kg_entities (id, name, entity_type, properties)
VALUES (?, ?, ?)
ON CONFLICT (id) DO UPDATE SET
    properties = json_patch(
        json_set(
            CASE WHEN json_extract(properties, '$.is_deleted') = true
            THEN json_set(properties, '$.is_deleted', false)
            ELSE properties
            END,
            '$.last_indexed_at', ?,
            '$.commit_hash', ?
        ),
        EXCLUDED.properties
    );
```

> **Note:** DuckDB uses `?` for parameterized queries, not `$1`. The example above uses PostgreSQL-style placeholders for readability; implementation must use DuckDB-compatible syntax. All PGQ queries must use parameterized statements — no string interpolation of symbol IDs into queries.

### 6.5 PGQ schema

```sql
-- Property graph schema for DuckDB/DuckPGQ (Option A: extend existing tables)
-- Uses kg_entities/kg_relationships from Session-Buddy's DuckPGQ property graph
-- Code-graph-specific fields are stored in the existing JSON properties blob
CREATE PROPERTY GRAPH code_graph
  VERTEX TABLES (
    kg_entities
      PRIMARY KEY (id)
      LABEL symbol
  )
  EDGE TABLES (
    kg_relationships
      SOURCE KEY (source) REFERENCES kg_entities (id)
      DESTINATION KEY (target) REFERENCES kg_entities (id)
      -- relation_type column stores the edge type (calls, imports, inherits, etc.)
      -- Note: The model uses `edge_type` (CodeGraphEdge) but the existing
      -- table uses `relation_type`. PGQ queries must reference `relation_type`.
  );
```

> **PGQ edge-type filtering caveat:** DuckPGQ edge-type filtering via WHERE clauses on `relation_type` column is unproven at scale. Performance testing is required before relying on this for repos with > 50k symbols (see Acceptance Criterion 10). If performance is insufficient, a pre-filtered materialized view per edge type may be needed.

## 7. Plan Placement

### 7.1 Phase and section

**Phase 2 (I2), Section 6 (Engine Surface Expansion)** — as a new sub-section "6.4 Code Knowledge Graph" alongside the existing Prefect (6.1), LlamaIndex (6.2), and Agno (6.3) sections.

Rationale from Delivery Lead review:
- Phase 0 (boundary hardening) does not need to complete first — indexing is self-contained
- Learning pipeline (Phase 1) has a soft dependency only — improves evidence quality, not a gate
- Nothing downstream (Phase 3, 4) depends on this — low slippage risk
- This is a natural extension of the existing LlamaIndex section, not scope creep
- Shares the same auth prerequisite as the rest of Phase 2

### 7.2 Incremental delivery order

| Delivery | Capability | Effort | Value |
|----------|-----------|--------|-------|
| **1st** | Call chain resolution | Medium | Highest — enables "who calls this?" queries |
| **2nd** | Change impact analysis | Medium | High — enables "what breaks if I change this?" |
| **3rd** | Incremental re-indexing | Low | Medium — automation, not strictly required |
| **4th** | Repo skill generation (--skills) | Low-Medium | High — gives agents targeted code context per functional area |

### 7.3 Prerequisites

- Phase 0 Section 4.1 (canonical routing) must complete before integrating code graph results into routing decisions
- Inter-service authentication between Mahavishnu and Session-Buddy must be defined before Phase 2 (documented blocker in Section 6 prerequisite note) — **auth is a hard gate, not soft**
- Storage path reconciliation decision (Section 6.3: Option A/B/C) must be resolved before call chain and impact analysis tools are implemented
- Upsert logic (ON CONFLICT DO UPDATE) must be implemented in Session-Buddy before incremental re-indexing can run safely
- CodeGraphAnalyzer is Python-only; multi-language support requires wiring tree-sitter MCP tools from Mahavishnu (not a blocker for initial delivery)

## 8. Security Hardening

### 8.1 Path validation

All `--repo` arguments must be validated against the registered repositories in `repos.yaml` before any indexing operation begins. Unregistered paths are rejected with a structured error response.

### 8.2 Signature redaction

Function signatures extracted during parsing must be scanned for secret-bearing patterns before storage:

```python
SECRET_PATTERNS = [
    r"(?i)(api_key|apikey|api_secret)\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)(password|passwd|pwd)\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)(token|auth_token|access_token)\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)(secret|client_secret)\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)(private_key|rsa_private|ec_private|ssh_key)\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)(connection_string|database_url|redis_url)\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)(webhook_secret|bearer|credential)\s*=\s*['\"][^'\"]+['\"]",
    r"(?i)(aws_secret_access_key|github_token|slack_token)\s*=\s*['\"][^'\"]+['\"]",
]
```

Matches are replaced with `"<REDACTED>"` in the stored signature. The original signature is never written to the graph.

**Patterns must also catch:** default parameter values (`def connect(api_key="sk-...")`), type annotations with defaults (`api_key: str = os.environ["..."]`), and f-strings (`f"Bearer {token}"`).

**Audit logging:** When a signature is redacted, log the file path and symbol name (but not the matched secret value) using the existing `TaskAuditLogger` infrastructure.

### 8.3 DuckDB file permissions

The DuckDB database file used for the code graph must have restrictive permissions:
- Database file: `0600` (owner read/write only)
- Database directory: `0700` (owner access only)
- Applied at creation time; verified on startup

### 8.4 Auth gate

Inter-service authentication between Mahavishnu and Session-Buddy is a **hard prerequisite** for Phase 2 (documented in the master implementation plan Section 6 prerequisite note). The code indexing workflow must not execute MCP calls to Session-Buddy without a valid auth token. If auth is not configured, the workflow fails immediately with a structured `AuthenticationRequired` error — no silent fallback to unauthenticated calls.

### 8.5 MCP trust boundary (Session-Buddy side)

Session-Buddy must independently validate all inputs received from Mahavishnu, not rely on Mahavishnu's validation:

- **Input validation:** Session-Buddy must validate `CallChainRequest` and `ImpactAnalysisRequest` using the same Pydantic models, regardless of what Mahavishnu sends
- **Symbol ID sanitization:** Validate qualified symbol IDs against the expected format using a regex like `^[^|]+(\|\|\|[^|]+){3}[^|]+$` to prevent injection via malformed IDs
- **Parameterized queries:** All PGQ queries must use DuckDB's `?` parameterized placeholders — no string interpolation of symbol IDs or edge types
- **max_depth bounds:** `max_depth` field must have an `@field_validator` with upper bound of 10 (default 5) to prevent expensive graph traversals
- **Result size limit:** Graph traversal queries must have a maximum result size (1000 nodes) and query timeout (30 seconds)
- **Per-repo access control:** Session-Buddy should verify the requesting Mahavishnu instance is authorized to query symbols from the requested `repo_path`

### 8.6 Git hook integrity

- **Content hash verification:** At execution time (not just installation), the hook script should verify its own SHA-256 hash against a stored value in `.git/mahavishnu-hook-hash`. If the hash mismatches, log a warning and exit silently (do not abort the commit)
- **Environment scrubbing:** The hook script should unset sensitive environment variables (`MAHAVISHNU_AUTH_SECRET`, `MAHAVISHNU_CROSS_PROJECT_AUTH_SECRET`) before invoking `mahavishnu`, relying on the CLI to re-read secrets from its own configuration

## 9. Acceptance Criteria

1. `code_call_chain` returns transitive callers/callees up to 5 hops with correct qualified symbol IDs, file paths, and edge types
2. `code_impact_analysis` returns all direct and indirect dependents with risk level classification (based on direct dependents only) and blast_radius (total transitive reach)
3. Both tools include `stale` and `last_indexed_at` fields in responses when the index is > 24 hours old
4. Incremental re-indexing processes only changed files (verified by comparing parse count to diff count)
5. Per-file parse failures are logged and skipped without aborting the batch; failure rate > 25% emits a warning
6. Full re-index of a single repo completes in under 60 seconds for repos under 100k LOC (per-repo, not cumulative)
7. All new tools return Pydantic-typed responses with no raw dicts
8. Degradation Tier 4 returns structured `CodeGraphUnavailable` responses, never empty results or untyped errors
9. DuckDB corruption triggers automatic re-index from scratch with a logged corruption event
10. Atomic replacement guarantee: failed staging table swaps leave the existing graph intact
11. `mahavishnu index --install-hooks` creates executable git hooks with mahavishnu header comment
12. `mahavishnu index --install-hooks --force` overwrites existing non-mahavishnu hooks with confirmation
13. `mahavishnu index --uninstall-hooks` removes only mahavishnu-managed hooks
14. `--repo` path validation rejects unregistered repositories
15. Function signatures containing secret patterns (API_KEY, PASSWORD, TOKEN) are redacted before storage
16. DuckDB database file has permissions 0600; database directory has permissions 0700
17. No MCP calls to Session-Buddy execute without valid auth token (hard blocker, not soft)
18. No new infrastructure dependencies (no Neo4j, no TiDB, no external graph DB)
19. Session-Buddy remains the single authority for code graph storage (verified by grep: no other service writes to the code graph)
20. PGQ queries on DuckDB handle call chains of depth 5 without truncation on repos under 50k symbols; if performance is insufficient, materialized views per edge type are created
21. Upsert logic (ON CONFLICT DO UPDATE) is implemented and tested for code node and edge tables
22. Soft delete mechanism (is_deleted flag) is implemented and verified for renamed/removed symbols

## 10. Validation

```bash
# Unit tests
uv run pytest tests/unit/test_code_call_chain.py
uv run pytest tests/unit/test_code_impact_analysis.py
uv run pytest tests/unit/test_reindex_workflow.py
uv run pytest tests/unit/test_code_graph_degradation.py
uv run pytest tests/unit/test_signature_redaction.py
uv run pytest tests/unit/test_hook_installation.py

# Integration tests
uv run pytest tests/integration/test_code_graph_e2e.py
uv run pytest tests/integration/test_upsert_semantics.py

# Security tests
uv run pytest tests/unit/test_path_validation.py
uv run pytest tests/unit/test_auth_gate.py

# Skill generation tests
uv run pytest tests/unit/test_skill_generation.py
uv run pytest tests/unit/test_community_detection.py

# Authority verification
grep -r "PropertyGraphIndex" mahavishnu/ session-buddy/  # should return zero results
grep -r "code_graph" mahavishnu/ --include="*.py" | grep -v "mcp" | grep -v "test"  # no direct writes
```

## 11. External Research Enhancements

Analysis of multi-agent orchestration projects identified patterns applicable to the code indexing workflow.

### 11.1 Adaptive Indexing Intervals (from Agent Farm)

Agent Farm calculates timing dynamically: 3x median cycle time bounded to 30s-600s. Apply to the scheduled sweep in Section 4.3:

```python
# Instead of fixed "*/15 * * * *" schedule
# Calculate adaptive sweep interval based on actual commit frequency
def calculate_sweep_interval(repo_path: str) -> int:
    """Return sweep interval in minutes based on recent commit cadence."""
    commits_last_hour = count_commits_since(repo_path, hours=1)
    if commits_last_hour > 10:
        return 5   # Active repo — sweep every 5 minutes
    elif commits_last_hour > 2:
        return 15  # Moderate — default interval
    else:
        return 60  # Quiet repo — sweep hourly
```

### 11.2 WorkItem Graph for Indexing (from MCP Task Orchestrator)

MCP Task Orchestrator uses a WorkItem graph with role-based lifecycle (`queue → work → review → terminal`) and dependency blocking. The indexing workflow (Section 4.3) could track its state as WorkItems:

```python
class IndexWorkItem(BaseModel):
    repo_path: str
    trigger: Literal["git-event", "schedule", "manual"]
    files_changed: list[str]
    status: Literal["queued", "parsing", "upserting", "notifying", "complete", "failed"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parse_failures: int = 0
```

This enables:
- `mahavishnu index --status` to show a real-time WorkItem dashboard
- Dependency blocking: don't notify Akosha until upsert is confirmed
- Retry semantics: failed WorkItems get requeued automatically

### 11.3 Filesystem Coordination Fallback (from Agent Farm)

When Session-Buddy MCP is unavailable during indexing, fall back to filesystem-based persistence:

1. Write parsed nodes/edges to `~/.claude/data/mahavishnu-index-queue/{repo_name}_{timestamp}.json`
2. On Session-Buddy recovery, batch-replay all pending JSON files
3. Delete processed files after successful upsert
4. Deduplicate replay: skip files whose `(repo_path, commit_hash, file_path)` tuple matches a recently processed entry
5. Maximum queue age: 48 hours — items older than this are discarded with a warning

This ensures indexing never blocks on MCP availability — work queues locally and replays when the graph owner is reachable. The persistent directory (`~/.claude/data/`) survives reboots, unlike `/tmp/`.

### 11.4 Heartbeat for Long-Running Index Operations (from Agent Farm)

For repos with 100k+ LOC, indexing can exceed 60 seconds. Add per-file heartbeat logging:

```python
async def parse_file(file_path: str):
    write_heartbeat(f"parsing:{file_path}")
    result = await CodeGraphAnalyzer._analyze_python_file(file_path)
    write_heartbeat(f"parsed:{file_path}:nodes={result.node_count}")
    return result
```

Heartbeat files in `~/.claude/data/mahavishnu-index/heartbeats/` enable external monitoring tools to track indexing progress without polling the MCP server.

## 12. ADR Reference

This design should be accompanied by an ADR in `docs/adr/` documenting:
- Decision to extend Session-Buddy's DuckDB/DuckPGQ vs. alternatives
- Rejection of GitNexus (PolyForm Noncommercial license)
- Rejection of LlamaIndex PropertyGraphIndex (data model mismatch, traversal limitations)
- Rejection of Neo4j (infrastructure dependency conflict)
- Ownership assignment: Session-Buddy as single code graph authority
- Storage path reconciliation: extend DuckPGQ tables vs. reflection DB vs. new tables
- Qualified symbol IDs: `{repo_path}|||{file_path}|||{symbol_type}|||{symbol_name}` format (uses `|||` sentinel to avoid colon ambiguity in paths)
- Security hardening: path validation, signature redaction, DuckDB permissions, auth gate
