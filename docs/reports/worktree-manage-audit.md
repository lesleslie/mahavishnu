# Worktree Manage W0 Audit

**Date:** 2026-05-11
**Scope:** `worktree_tools.py` retirement planning
**Status:** audit-backed
**Owner:** Core Eng

## 1. Purpose

This report records the W0 audit for consolidating the deprecated six-tool
worktree MCP surface into a single `worktree_manage` dispatcher.

## 2. Audit Command

```bash
rg -n "register_worktree_tools|worktree_tools|create_ecosystem_worktree|remove_ecosystem_worktree|list_ecosystem_worktrees|prune_ecosystem_worktrees|get_worktree_safety_status|get_worktree_provider_health|worktree_manage" /Users/les/Projects/mahavishnu /Users/les/Projects/crackerjack /Users/les/Projects/session-buddy /Users/les/Projects/oneiric /Users/les/Projects/mcp-common /Users/les/Projects/mdinject /Users/les/Projects/akosha /Users/les/Projects/dhara
```

## 3. Audit Summary

### Active runtime call sites

- `mahavishnu/mcp/server_core.py`
  - registers `worktree_tools` conditionally through `register_worktree_tools()`
- `mahavishnu/worktree_cli.py`
  - calls `WorktreeCoordinator` directly for CLI worktree status/safety paths
- `tests/integration/test_worktree_mcp_tools.py`
  - imports the individual MCP tool functions directly for behavioral coverage
- `tests/unit/test_worktree_tools.py`
  - imports the individual MCP tool functions directly for behavior/deprecation coverage

### Documentation-only references

- `docs/reports/deprecation-migration.md`
- `docs/reviews/review-2-architecture.md`
- `docs/reports/tool-ranking-report.md`
- `docs/plans/initiatives/10-low-value-tool-retirement.md`

### Non-target references

- `session-buddy/CLAUDE.md` mentions `worktree_manager.py`, which is a Session-Buddy-internal file and not this MCP module

## 4. Replacement Contract

The replacement contract is a single action-dispatch tool:

```python
worktree_manage(
    action: str,
    user_id: str,
    repo_nickname: str | None = None,
    branch: str | None = None,
    worktree_name: str | None = None,
    create_branch: bool = False,
    worktree_path: str | None = None,
    force: bool = False,
    force_reason: str | None = None,
) -> dict[str, Any]
```

### Action vocabulary

- `create`
- `remove`
- `list`
- `prune`
- `safety_status`
- `provider_health`

### Field preservation

- `user_id` remains required for all actions.
- `repo_nickname` remains required for repo-scoped actions.
- `branch`, `worktree_name`, and `create_branch` are preserved for create.
- `worktree_path` is preserved for remove and safety-status.
- `force` and `force_reason` are preserved for remove.

## 5. Disposition

- `worktree_tools.py` remains live-but-deprecated until W1/W2 land.
- The migration path is a consolidation, not a behavioral rewrite.
- No deletion is approved from this W0 audit alone.

## 6. Next Steps

1. Implement the consolidated `worktree_manage` dispatcher.
1. Add MCP registration and dispatch tests.
1. Remove the individual tools only after parity is verified.
