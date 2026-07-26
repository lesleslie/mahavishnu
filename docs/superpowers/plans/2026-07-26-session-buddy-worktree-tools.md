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
