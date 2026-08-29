---
status: active
role: canonical
date: 2026-07-26
last_reviewed: 2026-07-26
topic: decision-index
---

# `.claude/decisions/` index

One-line summary: the directory holds repo-local decisions and
follow-up trackers. This file is the index — update it when adding
a new file.

## Files

Sorted newest-first. The first column is the file, the second is
the topic, the third is the most recent state.

| File | Topic | Status |
|------|-------|--------|
| `README.md` | This file — index of repo-local decisions and follow-up trackers. | Active. |
| `2026-08-28-cross-repo-fanout-cwd-isolation.md` | Rules for parallel-fanout CWD isolation: default to sequential per-repo dispatch; if parallel required, parent must `ExitWorktree` first; each agent creates its own `/tmp/<branch>` worktree; aggregate gate on 3 conditions (booleans + commit_sha + branch HEAD). Layer 4 (PreToolUse hook) deferred. Adopted after the 2026-08-26 Phase 3 fanout and the 2026-08-27 cleanup of 16 abandoned worktrees from the 2026-08-21 fanout. | Active. |
| `2026-08-25-bodai-cli-contract.md` | Bodai CLI contract (`OneiricCLIBase`, ExitCode, `bodai.apps` entry-points); renamed from `BodaiCLIBase` 2026-08-26. Established after the 2026-08-25 ultracode CLI audit. | Active. |
| `2026-08-24-bodai-mcp-routing-pattern.md` | MCP/agent scoping rules for the Bodai ecosystem: secrets in shell env, MCP config in per-project `.mcp.json`, agents scoped to project, plugins preferred over bare URL. Established after the 2026-08-24 ultracode audit. | Active. |
| `ty-ignore-codes.md` | Canonical ty diagnostic codes for `# ty: ignore[...]`; rules for which code fits which boundary; crackerjack hook's `KNOWN_TY_CODES` is kept in sync via `tests/unit/tools/test_ty_ignore_syntax.py`. | Active. |
| `worktree-autoremove-policy.md` | Narrow Rule 2 amendment permitting explicitly invoked `worktree prune-merged`; hook and cron remain prohibited. | Active. |
| `agent-curation-strategy.md` | Rules for adding/archiving agents: mycelium-core deduplication, Bodai-stack relevance, 15k token limit. | Active. |
| `skill-vs-agent-strategy.md` | When to write a skill vs. an agent: trigger-driven procedures → skill, domain persona → agent. | Active. |
| `technical-debt-roadmap.md` | Side discoveries from the recent `.claude/agents/` and `scripts/test_matrix.py` cleanup work. 5 items, 3 size classes. | 4/5 RESOLVED (TD-1..TD-4 done; TD-5 open). |
| `test-matrix-review-followups.md` | Deferred MEDIUM/LOW items from the `scripts/test_matrix.py` review. | All 4 groups RESOLVED. |
| `removed-scripts.md` | Policy for `required_scripts:` references in tool command frontmatter. | Active. |
| `wire-up-contract.md` | Integration Contract template + orphan audit gate; prevents "built but not wired" deliveries. | Active. |
| `mahavishnu-tool-preference-policy.md` | Tool-selection steering lives only in `MAHAVISHNU_TOOL_PROFILE` and `CLAUDE.md` `## Tool Preferences`; docstrings narrate, do not market. | Active. |
| `followups-lifecycle.md` | Lifecycle for `docs/followups/`: README index + `.archive/` on completion (never delete), Status-line convention. Mirrors this directory's conventions. | Active. |
