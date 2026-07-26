---
date: 2026-07-26
last_reviewed: 2026-07-26
superseded_by: null
topic: session-buddy-worktree-tools
status: draft
role: implementation
---

# Session-Buddy MCP worktree tools — Implementation Plan

> **Goal:** Add `list_worktrees`, `create_worktree`, and `remove_worktree` MCP tools to session-buddy so the `SessionBuddyWorktreeProvider` in mahavishnu can use them.

## Context

The `SessionBuddyWorktreeProvider` in mahavishnu (`mahavishnu/core/worktree_providers/session_buddy.py`) calls three MCP tools on the session-buddy server:
- `list_worktrees`
- `create_worktree`
- `remove_worktree`

The session-buddy MCP server does not currently expose any of these tools. The provider's `health_check()` only verifies TCP reachability, so the registry considers session-buddy "healthy" and dispatches to it — then the tool call fails with `Unknown tool: 'list_worktrees'`.

The mahavishnu `WorktreeCoordinator` is configured with both providers in the chain (SessionBuddyWorktreeProvider primary, DirectGitWorktreeProvider fallback). Until session-buddy exposes the tools, the smoke test for `mahavishnu worktree prune-merged` fails on the first `list_worktrees` call.

## Resolution

Add the three tools to session-buddy's MCP server. The existing worktree-handling code is already there in `session_buddy/utils/git_worktrees.py` (line 175, 201, 248, 275, 638, 639); the MCP server just needs to register the tool wrappers.

## Files to modify

- `session-buddy/session_buddy/mcp/server.py` or `server_core.py` — register three new `@mcp.tool()` functions
- `session-buddy/session_buddy/utils/git_worktrees.py` — may need helper functions exposed

## Tool signatures

```python
@mcp.tool()
async def list_worktrees(repository_path: str) -> dict[str, list[dict]]:
    """List git worktrees in the given repository.

    Returns:
        {"worktrees": [{"path": ..., "branch": ..., "head": ...}, ...]}
    """

@mcp.tool()
async def create_worktree(repository_path: str, worktree_path: str, branch: str, create_branch: bool = False) -> dict:
    """Create a new git worktree."""

@mcp.tool()
async def remove_worktree(repository_path: str, worktree_path: str, force: bool = False, force_reason: str | None = None) -> dict:
    """Remove a git worktree, with optional force + reason."""
```

## Re-enable in mahavishnu

Once the tools are exposed, the `worktree_providers.session_buddy_enabled: false` flag in `settings/mahavishnu.yaml` can be flipped to `true`, restoring the original provider chain.

## Related issues discovered during smoke testing

Two additional issues surfaced during the 2026-07-26 worktree-autoremove smoke test, after the Session-Buddy fix above is applied. Both block the `mahavishnu worktree prune-merged` CLI from running against real worktrees.

### Issue 2: `Repo has no canonical nickname` for 3 of 8 repos

The `Repository` Pydantic model requires a `nickname` field. After 5 nicknames were added (`mh`, `cj`, `sb`, `ak`, `dh`) on 2026-07-26, the CLI advances to the next failing repo. The remaining 3 are:

| Repo | Required nickname | Notes |
|---|---|---|
| `oneiric` | (suggested: `on` or `oi`) | Configuration / lifecycle management |
| `mcp-common` | (suggested: `mc`) | Foundation library for MCP servers |
| `mdinject` | (suggested: `md`) | macOS SwiftUI desktop app |

**Resolution:** add `nickname:` and `nicknames:` fields to each of these 3 repos in `settings/ecosystem.yaml`, following the same pattern as the 5 already-fixed entries (singular `nickname` plus a list with the same value).

**File:** `settings/ecosystem.yaml` — add 3 new fields (3-line change per repo).

### Issue 3: `WorktreeAuditLogger` has no attribute `log`

When `WorktreeAuditLogger._log_to_audit_trail` is called, the inner call `get_audit_logger().log(...)` raises `AttributeError: 'AuditLogger' object has no attribute 'log'`. The new audit methods (`log_prune_merged_attempt/success/partial/failure`) all funnel through this path, so every prune-merged sweep emits a `Failed to write to audit log: 'AuditLogger' object has no attribute 'log'` warning.

This is a pre-existing bug in `mahavishnu/mcp/auth.py` (the `AuditLogger` class) that the new audit methods inherit. The pre-existing methods (`log_removal_attempt`, `log_removal_success`, etc.) also route through `_log_to_audit_trail` and so are affected — but those methods have been working in practice, which suggests the `log` method does exist on the real audit logger object but is not declared on the `AuditLogger` class definition. Either the class definition is missing the `log` method signature, or the runtime object is a different class than the type hint suggests.

**Resolution:** investigate `mahavishnu/mcp/auth.py` `AuditLogger.log` to determine whether the method is missing from the class or whether the class hierarchy is wrong. The fix is likely a 1-line type-stub addition or a `__getattr__` fallback.

**File:** `mahavishnu/mcp/auth.py` — investigate; likely 1-line fix once root cause is known.

## Summary of this plan's scope

1. **Issue 1 (session-buddy):** add the 3 worktree MCP tools (this plan's primary task)
2. **Issue 2 (ecosystem.yaml nicknames):** add 3 missing nicknames
3. **Issue 3 (audit logger):** fix the missing `log` attribute

All three are blockers for the worktree-autoremove smoke test. Items 2 and 3 are smaller than item 1 and could be addressed independently.
