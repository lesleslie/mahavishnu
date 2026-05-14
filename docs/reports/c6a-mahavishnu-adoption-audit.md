# C6a Mahavishnu Adoption Audit

**Date:** 2026-05-11
**Scope:** Initial local audit for the Mahavishnu rows in the C6a deletion/adoption ledger.
**Purpose:** Record the audit commands and hit dispositions for the local candidate families that are already visible in this worktree.

## Audit Commands

```bash
rg -n "team_learning|list_team_skills|goal_team|learning_pipeline" /Users/les/Projects/mahavishnu
rg -n "pool_manager|coordination_manager|approval_manager|skill_registry|session_buddy" /Users/les/Projects/mahavishnu
```

## Findings

### 1. Learning / Team-Learning Surface

Candidate modules:

- `cli/team_cli.py`
- `mcp/tools/team_learning_tools.py`
- `mcp/tools/goal_team_tools.py`

Canonical replacement:

- `core/skill_governance.py`
- `core/learning_pipeline.py`
- `core/skill_registry.py`

Hit disposition:

- `compatibility wrapper` for CLI/MCP entry points that still expose `team_learning` and `list_team_skills`
- `migrated` for the learning pipeline and skill registry call sites that already use the canonical modules
- `historical docs` for runbooks and guides that mention the older team-learning surface

Decision:

- Keep the surface as a compatibility wrapper for now.
- Do not delete the commands until review-gated skill lifecycle parity is proven and the canonical skill registry covers the current operator workflows.

Implementation note:

- `mcp/tools/team_learning_tools.py` remains importable for CLI/backward compatibility, but it is de-authorized from live MCP registration.
- `mcp/tools/goal_team_tools.py` and `cli/team_cli.py` still provide the live operator-facing team workflows, so the duplicate surface is currently a compatibility hold rather than a deletion target.

### 2. Composition-Root Surface

Candidate modules:

- `core/app.py`
- `mcp/server_core.py`
- `core/config.py`

Canonical replacement:

- smaller service wiring modules and adapter factories

Hit disposition:

- `refactor` for bootstrap wiring and service assembly points
- `migrated` for call sites already routed through `factories.py` or other service helpers
- `blocker` if a call site still owns domain logic instead of wiring only

Decision:

- Refactor before deletion.
- Keep the current entry points until the wiring is extracted and the contract tests prove the new composition-root split is safe.

## Follow-Up

The Oneiric, mcp-common, Crackerjack, Session-Buddy, Akosha, Dhara, and mdinject rows remain ledgered and matrixed, but their concrete implementation will need to happen in those repos' worktrees.
