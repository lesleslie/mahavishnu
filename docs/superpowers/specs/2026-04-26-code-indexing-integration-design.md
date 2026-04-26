# Code Knowledge Graph Integration Design

**Status:** Draft — pending multi-agent review
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
| AST parsing | `CodeGraphAnalyzer` | `mcp-common/mcp_common/code_graph/analyzer.py` | Built — Python, Go, JS, TS, Rust |
| Symbol extraction | Symbol/relationship extraction | `mcp-common/mcp_common/code_graph/` | Built |
| Graph storage | DuckDB with DuckPGQ | `session-buddy/session_buddy/knowledge_graph_db.py` | Built — PGQ queries supported |
| Cross-repo ingestion | `CodeGraphIngester` | `akosha/akosha/mcp/tools/code_graph_tools.py` | Built — pull from Session-Buddy |
| Code graph storage | `store_code_graph_from_mahavishnu` | Session-Buddy MCP tools | Built |
| Symbol search | `code_search_symbols_impl` | Session-Buddy MCP tools | Built |
| Symbol graph | `code_get_symbol_graph_impl` | Session-Buddy MCP tools | Built |
| Tree-sitter MCP tools | 7 tools (parse, query, extract, batch) | Mahavishnu MCP server | Built |

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
│  │  2. Parse with tree-sitter via mcp-common             │  │
│  │  3. Build call edges from AST                          │  │
│  │  4. Upsert nodes/edges to Session-Buddy               │  │
│  └───────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │ MCP protocol
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Session-Buddy (graph owner — authority)                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  DuckDB/DuckPGQ knowledge graph                        │  │
│  │  - Nodes: functions, classes, modules, files          │  │
│  │  - Edges: calls, imports, inherits, contains          │  │
│  │  - Queries: PGQ for call chains, impact analysis      │  │
│  └───────────────────────────────────────────────────────┘  │
│  MCP tools: call_chain, impact_analysis, reindex            │
└──────────────────────┬──────────────────────────────────────┘
                       │ pull-based
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Akosha (cross-system aggregation)                          │
│  - Pulls code graphs from Session-Buddy                    │
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
| 8. Degradation mode | Three-tier degradation defined in Section 5. |

## 4. New Components

### 4.1 Call chain resolution (Session-Buddy MCP tool)

**Tool name:** `code_call_chain`

**Input (Pydantic model):**
```python
class CallChainRequest(BaseModel):
    symbol_name: str
    direction: Literal["callers", "callees", "both"]
    max_depth: int = 5
    repo_path: str | None = None
    edge_filter: list[str] | None = None  # e.g., ["calls", "imports"]
```

**Output:**
```python
class CallChainResult(BaseModel):
    root_symbol: str
    chains: list[CallChain]
    total_nodes: int
    truncated: bool

class CallChain(BaseModel):
    path: list[str]          # symbol names in traversal order
    depth: int
    edge_types: list[str]    # edge type at each hop
    files: list[str]         # file paths involved
```

**Implementation:** PGQ query on DuckDB knowledge graph. Bounded BFS with configurable max depth. Truncation flag indicates if results were cut off.

### 4.2 Change impact analysis (Session-Buddy MCP tool)

**Tool name:** `code_impact_analysis`

**Input (Pydantic model):**
```python
class ImpactAnalysisRequest(BaseModel):
    symbol_name: str
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
    risk_level: Literal["low", "medium", "high"]  # based on fan-out

class SymbolImpact(BaseModel):
    symbol_name: str
    symbol_type: Literal["function", "class", "module"]
    file_path: str
    depth: int
    dependency_type: Literal["calls", "imports", "inherits", "contains", "implements"]
```

**Implementation:** Reverse call graph traversal via PGQ. Risk level is computed from direct dependents only (not transitive): low (< 3 direct), medium (3-10 direct), high (> 10 direct).

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

2. Filter files
   - Skip non-code files (binary, generated, vendored)
   - Skip languages without tree-sitter support
   - Deduplicate across repos

3. Parse changed files
   - Use mcp-common CodeGraphAnalyzer
   - Extract: functions, classes, imports, calls, inherits
   - Build edge list: (caller, callee, "calls"), (module, import, "imports")

4. Compute deletions
   - For removed/renamed symbols: mark as deleted in graph (not hard delete)
   - Retain historical edges for code evolution (Phase 4)

5. Upsert to Session-Buddy
   - Call Session-Buddy's code graph ingest MCP tools
   - Batch upserts for efficiency
   - Record last-indexed commit hash per repo

6. Notify Akosha
   - Call Akosha's code graph refresh MCP tool to invalidate cached data
   - Akosha pulls updated graph on its next polling cycle (existing behavior)
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

# What this does:
# Creates .git/hooks/post-commit with:
#   #!/bin/sh
#   mahavishnu index --trigger git-event --repo "$(pwd)"
# Creates .git/hooks/post-merge with same content
# Marks hooks as executable
```

## 5. Degradation Modes

When the code graph is unavailable or incomplete, the system degrades in three tiers:

| Tier | Condition | Behavior |
|------|-----------|----------|
| **Tier 1: Full** | DuckDB graph available, recent index | All tools return complete results |
| **Tier 2: Partial** | DuckDB available, stale index (last upsert > 24 hours ago) | Call chains and impact analysis return results with a `stale: true` flag and `last_indexed_at` timestamp |
| **Tier 3: Fallback** | DuckDB unavailable | Tools return structured "graph unavailable" response. Call chain tool falls back to tree-sitter single-file AST queries. Impact analysis returns a list of files that would need manual review. No silent empty results. |

Each tier is documented, tested, and returns typed Pydantic responses — never raw errors or empty lists.

## 6. Data Model

### 6.1 Graph nodes

```python
class CodeGraphNode(BaseModel):
    symbol_name: str
    symbol_type: Literal["function", "class", "module", "file", "variable"]
    file_path: str
    repo_path: str
    start_line: int | None = None
    end_line: int | None = None
    language: str
    signature: str | None = None       # for functions/classes
    complexity: int | None = None      # cyclomatic complexity
    is_deleted: bool = False           # soft delete for renamed/removed symbols
    last_indexed_at: datetime
    commit_hash: str
```

### 6.2 Graph edges

```python
class CodeGraphEdge(BaseModel):
    source: str          # symbol_name
    target: str          # symbol_name
    edge_type: Literal["calls", "imports", "inherits", "contains", "implements"]
    source_file: str
    target_file: str
    repo_path: str
    confidence: float = 1.0    # static analysis = 1.0; inferred < 1.0
    created_at: datetime
```

### 6.3 PGQ schema

```sql
-- Property graph schema for DuckDB/DuckPGQ
-- Note: DuckPGQ supports multiple edge tables with different labels
CREATE PROPERTY GRAPH code_graph
  VERTEX TABLES (
    code_nodes
      PRIMARY KEY (symbol_name)
      LABEL symbol
  )
  EDGE TABLES (
    code_edges
      SOURCE KEY (source) REFERENCES code_nodes (symbol_name)
      DESTINATION KEY (target) REFERENCES code_nodes (symbol_name)
      -- Edge type is stored as a property and filtered in PGQ queries
      -- DuckPGQ does not support per-row labels, so type filtering
      -- is done via WHERE clauses on edge_type property
  );
```

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

### 7.3 Prerequisites

- Phase 0 Section 4.1 (canonical routing) must complete before integrating code graph results into routing decisions
- Inter-service authentication between Mahavishnu and Session-Buddy must be defined before Phase 2 (documented blocker in Section 6 prerequisite note)

## 8. Acceptance Criteria

1. `code_call_chain` returns transitive callers/callees up to 5 hops with correct file paths and edge types
2. `code_impact_analysis` returns all direct and indirect dependents with risk level classification
3. Incremental re-indexing processes only changed files (verified by comparing parse count to diff count)
4. Full re-index of a single repo completes in under 60 seconds for repos under 100k LOC (per-repo, not cumulative)
5. All three new tools return Pydantic-typed responses with no raw dicts
6. Degradation Tier 3 returns structured responses, never empty results or untyped errors
7. `mahavishnu index --install-hooks` creates executable git hooks in the target repo
8. No new infrastructure dependencies (no Neo4j, no TiDB, no external graph DB)
9. Session-Buddy remains the single authority for code graph storage (verified by grep: no other service writes to the code graph)
10. PGQ queries on DuckDB handle call chains of depth 5 without truncation on repos under 50k symbols

## 9. Validation

```bash
# Unit tests
uv run pytest tests/unit/test_code_call_chain.py
uv run pytest tests/unit/test_code_impact_analysis.py
uv run pytest tests/unit/test_reindex_workflow.py

# Integration tests
uv run pytest tests/integration/test_code_graph_e2e.py

# Degradation tests
uv run pytest tests/unit/test_code_graph_degradation.py

# Authority verification
grep -r "PropertyGraphIndex" mahavishnu/ session-buddy/  # should return zero results
grep -r "code_graph" mahavishnu/ --include="*.py" | grep -v "mcp" | grep -v "test"  # no direct writes
```

## 10. ADR Reference

This design should be accompanied by an ADR in `docs/adr/` documenting:
- Decision to extend Session-Buddy's DuckDB/DuckPGQ vs. alternatives
- Rejection of GitNexus (PolyForm Noncommercial license)
- Rejection of LlamaIndex PropertyGraphIndex (data model mismatch, traversal limitations)
- Rejection of Neo4j (infrastructure dependency conflict)
- Ownership assignment: Session-Buddy as single code graph authority
