# Deprecation & Migration Guide

**Date**: 2026-04-05
**Scope**: Bottom-quintile tool modules identified by I10-1 ranking
**Source**: `docs/reports/tool-ranking-report.md`

## Overview

Three tool modules scored in the deprecation zone (quality score < 0.642). This document
provides per-module deprecation timelines, migration paths, and the rationale for each
decision.

**Key principle**: No tools will be removed without a migration path. Deprecation warnings
appear at runtime for at least one minor release before removal.

______________________________________________________________________

## Module 1: `content_ingestion_tools.py`

| Field | Value |
|-------|-------|
| **Score** | 0.623 |
| **Tools** | `ingest_url`, `ingest_file`, `batch_ingest_urls`, `detect_content_type`, `get_ingestion_stats` (5) |
| **Lines** | 213 |
| **Registration** | Not currently wired into `server_core.py` — tools exist but are unreachable via MCP |
| **Primary Concern** | Zero error handling; private API access (`ingester._initialized`, `ingester._detect_content_type`) |
| **Severity** | 🟡 Low — tools are dormant (not registered), so no active user impact |

### Migration Path

| Tool | Replacement | Notes |
|------|-------------|-------|
| `ingest_url` | External web-fetch tools (nanobot `web_search`/`web_fetch`) | Content fetching is better handled at the consumer layer |
| `ingest_file` | Direct `ContentIngester` API or nanobot summarization skill | Removes unnecessary MCP indirection |
| `batch_ingest_urls` | Consumer-side concurrency (e.g., `asyncio.gather` with web-fetch) | Batch orchestration belongs in workflow code, not MCP |
| `detect_content_type` | `ContentIngester._detect_content_type()` directly | Trivial wrapper with no added value |
| `get_ingestion_stats` | `ContentIngester` inspection or health tools | Overlaps with `health_tools` |

### Deprecation Timeline

1. **v0.5.0** (current): Mark module with `warnings.warn(DeprecationWarning)` on import
1. **v0.6.0**: Remove module file; clean up `tool_versions.py` entries
1. No action needed in `server_core.py` (already not registered)

______________________________________________________________________

## Module 2: `worktree_tools.py`

| Field | Value |
|-------|-------|
| **Score** | 0.642 |
| **Tools** | `create_ecosystem_worktree`, `remove_ecosystem_worktree`, `list_ecosystem_worktrees`, `prune_ecosystem_worktrees`, `get_worktree_safety_status`, `get_worktree_provider_health` (6) |
| **Lines** | 226 |
| **Registration** | `server_core.py:1575` via `register_worktree_tools()` — conditionally loaded if `WorktreeCoordinator` exists |
| **Primary Concern** | Zero error handling around coordinator calls; entire module is a thin pass-through to `WorktreeCoordinator` |
| **Severity** | 🟡 Low — `WorktreeCoordinator` may not be initialized (graceful early return), and the registration is guarded |

### Migration Path

The worktree tools are thin wrappers around `WorktreeCoordinator`. Rather than
exposing 6 separate MCP tools, the recommendation is:

1. **Consolidate** into a single `worktree_manage` tool that accepts a subcommand
   parameter (`create`, `remove`, `list`, `prune`, `safety_status`, `provider_health`),
   reducing surface area from 6 tools to 1.
1. **Add error handling** — wrap all `coordinator.*` calls in try/except with
   structured error responses.
1. **Alternative**: If worktree management moves to git CLI tooling or Crackerjack,
   remove the MCP layer entirely and use `git worktree` commands directly.

| Current Tool | Merged Into |
|-------------|-------------|
| `create_ecosystem_worktree` | `worktree_manage(action="create")` |
| `remove_ecosystem_worktree` | `worktree_manage(action="remove")` |
| `list_ecosystem_worktrees` | `worktree_manage(action="list")` |
| `prune_ecosystem_worktrees` | `worktree_manage(action="prune")` |
| `get_worktree_safety_status` | `worktree_manage(action="safety_status")` |
| `get_worktree_provider_health` | `worktree_manage(action="provider_health")` |

### Deprecation Timeline

1. **v0.5.0** (current): Add `DeprecationWarning` to each tool's docstring and runtime log
1. **v0.5.0**: Add consolidated `worktree_manage` tool alongside existing tools
1. **v0.6.0**: Remove individual tools, keep consolidated version
1. **v0.7.0** (conditional): Remove entirely if worktree management migrates to CLI tools

______________________________________________________________________

## Module 3: `oneiric_tools.py`

| Field | Value |
|-------|-------|
| **Score** | 0.600 |
| **Tools** | `oneiric_list_adapters`, `oneiric_resolve_adapter`, `oneiric_check_health`, `oneiric_get_adapter`, `oneiric_invalidate_cache`, `oneiric_health_check` (6) |
| **Lines** | 474 |
| **Registration** | Uses `@app.mcp.tool()` directly (not via `server_core.py`) |
| **Primary Concern** | Depends on optional `oneiric-mcp` package; already has a graceful disabled path |
| **Severity** | 🟢 Informational — already conditionally loaded, already returns safe defaults when unavailable |

### Migration Path

These tools overlap with `adapter_registry_tools.py` (score: 0.858), which provides:

| Oneiric Tool | Adapter Registry Equivalent |
|-------------|---------------------------|
| `oneiric_list_adapters` | `adapter_list` |
| `oneiric_resolve_adapter` | `adapter_resolve` |
| `oneiric_check_health` | `adapter_health` |
| `oneiric_get_adapter` | `adapter_metadata` |
| `oneiric_invalidate_cache` | `adapter_cache_invalidate` |
| `oneiric_health_check` | `adapter_health` (with adapter_name=None) |

**Recommendation**: Mark as deprecated and direct users to `adapter_registry_tools`.
The `adapter_registry_tools` module is always available, better documented, and
scored 0.858 vs 0.600.

### Deprecation Timeline

1. **v0.5.0** (current): Add `DeprecationWarning` at module import; log warning on each tool call directing to adapter_registry equivalent
1. **v0.6.0**: Remove module; update `__init__.py` comment
1. Clean up `tool_versions.py` entries for oneiric tools

______________________________________________________________________

## Implementation Checklist

- [ ] Add `DeprecationWarning` imports and runtime warnings to `content_ingestion_tools.py`
- [ ] Add `DeprecationWarning` imports and runtime warnings to `worktree_tools.py`
- [ ] Add `DeprecationWarning` imports and runtime warnings to `oneiric_tools.py`
- [ ] Update `tool_versions.py` to mark deprecated tools
- [ ] Update initiative doc I10 checkbox for I10-2
- [ ] (I10-3) Remove tools in v0.6.0 release

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| User disruption from removal | Low — content_ingestion not wired; worktree conditionally loaded; oneiric has disabled fallback | One full minor release with warnings before removal |
| Missing migration guidance | Medium | This document serves as the migration guide; linked from initiative tracker |
| Overlap confusion during deprecation period | Low | Runtime warnings include the specific replacement tool name |

## Appendix: Tool Versions to Deprecate

From `mahavishnu/mcp/tool_versions.py`, these entries should be marked deprecated:

```
# content_ingestion_tools.py
"batch_ingest_urls": "1.0.0" → "1.0.0-deprecated"
"detect_content_type": "1.0.0" → "1.0.0-deprecated"
"get_ingestion_stats": "1.0.0" → "1.0.0-deprecated"
"ingest_file": "1.0.0" → "1.0.0-deprecated"
"ingest_url": "1.0.0" → "1.0.0-deprecated"

# oneiric_tools.py (not in tool_versions.py but registered via @app.mcp.tool)
# No tool_versions.py entries to update — add note in version registry
```

Worktree tools are registered dynamically and don't appear in `tool_versions.py` —
the deprecation warning should be added in the `register_worktree_tools()` function
in `server_core.py`.
