# MCP Tool Ranking Report

**Generated**: 2026-04-05  
**Scope**: All tool modules in `mahavishnu/mcp/tools/`

## Methodology

Each tool module is scored on four signals:

| Signal | Weight | Description |
|--------|--------|-------------|
| Tool count | 40% | Number of registered `@mcp.tool()` or `register_*_tools()` tools (log-normalized) |
| Documentation | 20% | Docstring coverage on tool functions (ratio: docstrings / tools) |
| Error handling | 20% | `try/except` blocks per tool (ratio: try blocks / tools) |
| Type safety | 20% | Functions with return type hints (ratio: typed defs / tools) |

Files using the programmatic `register_*_tools(server, ...)` pattern are noted — they have tools registered via a different mechanism than `@mcp.tool()`.

## Ranked Tool Modules

| Rank | Module | Tools | Lines | Docs | Err | Typed | Score |
|-----:|--------|------:|------:|-----:|----:|------:|------:|
| 1 | pool_tools.py | 10 | 413 | 12 | 10 | 11 | **0.898** |
| 2 | pycharm_tools.py | 8 | 406 | 13 | 12 | 12 | **0.873** |
| 3 | adapter_registry_tools.py | 7 | 378 | 9 | 7 | 8 | **0.858** |
| 4 | treesitter_tools.py | 7 | 493 | 11 | 11 | 9 | **0.858** |
| 5 | team_learning_tools.py | 5 | 623 | 7 | 5 | 6 | **0.823** |
| 6 | coordination_tools.py | 14 | 471 | 16 | 6 | 15 | **0.822** |
| 7 | search_tools.py | 4 | 327 | 7 | 4 | 6 | **0.800** |
| 8 | goal_team_tools.py | 3 | 783 | 5 | 5 | 4 | **0.772** |
| 9 | terminal_tools.py | 12 | 421 | 15 | 3 | 13 | **0.769** |
| 10 | self_improvement_tools.py | 4 | 493 | 15 | 3 | 12 | **0.750** |
| 11 | health_tools.py | 9 | 518 | 11 | 1 | 13 | **0.708** |
| 12 | worker_tools.py | 9 | 289 | 11 | 1 | 10 | **0.708** |
| 13 | desktop_automation_tools.py | 23 | 555 | 26 | 0 | 9 | **0.673** |
| 14 | worktree_tools.py | 6 | 226 | 8 | 0 | 6 | **0.642** |
| 15 | content_ingestion_tools.py | 5 | 213 | 8 | 0 | 7 | **0.623** |
| — | git_analytics.py* | 3 | 463 | 12 | 6 | 10 | **0.600** |
| — | oneiric_tools.py* | 5 | 474 | 9 | 7 | 8 | **0.600** |
| — | otel_tools.py* | 4 | 347 | 6 | 6 | 4 | **0.600** |
| — | repository_messaging_tools.py* | 5 | 308 | 9 | 13 | 7 | **0.600** |
| — | session_buddy_tools.py* | 5 | 246 | 9 | 8 | 7 | **0.600** |

*\* These modules use the programmatic `register_*_tools(server, ...)` pattern rather than `@mcp.tool()` decorators. They are functional but scored at the floor for tool count due to the different registration mechanism.*

## Summary Statistics

- **Total tool modules**: 20
- **Total registered tools**: ~140 (125 via `@mcp.tool()` + ~22 via programmatic registration)
- **Average quality score**: 0.724
- **Median quality score**: 0.750
- **Score range**: 0.600 – 0.898

## Bottom 10-20% — Deprecation Candidates (I10-3)

The bottom quintile (scores < 0.642) comprises:

| Module | Score | Primary Concern |
|--------|------:|-----------------|
| worktree_tools.py | 0.642 | Zero error handling |
| content_ingestion_tools.py | 0.623 | Zero error handling |
| git_analytics.py | 0.600 | Programmatic registration, may be redundant with Session-Buddy |
| oneiric_tools.py | 0.600 | Programmatic registration, Oneiric MCP optional dep |
| otel_tools.py | 0.600 | Programmatic registration, niche use case |
| repository_messaging_tools.py | 0.600 | Programmatic registration, overlap with coordination_tools |
| session_buddy_tools.py | 0.600 | Programmatic registration, depends on external service |

### Recommendations

1. **No immediate removals** — all modules serve functional purposes
2. **Add error handling** to `worktree_tools.py` and `content_ingestion_tools.py` (both have zero try/except blocks)
3. **Consolidate registration patterns** — migrate programmatic registrations to `@mcp.tool()` decorators for consistency and better quality scoring
4. **Evaluate overlap** between `repository_messaging_tools.py` and `coordination_tools.py` — both handle cross-repo communication
5. **Conditionally load** `oneiric_tools.py` and `otel_tools.py` behind feature flags since they depend on optional packages

## Re-runnable Script

Run `scripts/rank-tools.py` to regenerate this report with current data:

```bash
uv run python scripts/rank-tools.py
```
