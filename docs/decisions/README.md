---
status: active
role: canonical
date: 2026-07-26
last_reviewed: 2026-10-14
backfilled: 2026-10-14 (2026-10-14-decision-adapter-category, 2026-10-14-fast-hooks-vs-comprehensive)
topic: decision-index
---
# `docs/decisions/` index

One-line summary: the directory holds repo-local decisions and
follow-up trackers. This file is the index — update it when adding
a new file.

## Files

Sorted newest-first. The first column is the file, the second is
the topic, the third is the most recent state.

| File | Topic | Status |
|------|-------|--------|
| `README.md` | This file — index of repo-local decisions and follow-up trackers. | Active. |
| `2026-10-09-slash-commands-multi-call-only.md` | Slash commands are for multi-call user-invoked workflows only; single-tool wrappers are forbidden because MCP tools are the cross-harness capability (Claude Code / Cursor / Windsurf / Cline). Documents the 15 1:1 wrappers deleted 2026-10-09 (3 user-level, 10 in Bodai repos, 2 outliers in non-Bodai MCP server repos). | Active. |
| `2026-10-03-main-branch-protection.md` | GitHub branch protection on `main` across all 6 Bodai core repos: blocks force-push + branch deletion, leaves admin direct-push intact, no PR/CI requirements yet (pre-1.0). Future CI addition is an amendment, not an inline change. | Active. |
| `2026-10-03-plans-specs-canonical-paths.md` | Plans → `docs/plans/`, specs → `docs/specs/`. Both skills (`writing-plans`, `brainstorming`) document the CLAUDE.md preference override hook. `.superpowers/` blanket-gitignored via crackerjack template; fleet rollout is operator-driven via `crackerjack gitignore sync`. | Active. |
| `2026-10-13-prepushconsolidationgate.md` | Further narrowing of the auto-push exception: pre-push gate that holds back stage 5 push when co-located worktrees have unmerged WIP or pending commits are not squash-merge-shaped. Held back = sticky-failure marker + stage 6 skipped + EXIT_OK. | Active. |
| `2026-10-14-bypass-gate-parallel-sessions.md` | Tightens the `--no-consolidation-gate` operator escape hatch with a parallel-session pre-condition: before invocation, `git stash list` is checked for path overlaps with the target commit; any overlap = bypass REFUSED. Recorded from the 2026-10-14 `fd9b61ed` → `b11c72ed` incident (1.5K lines of conflict markers landed on `main`). | Active. |
| `2026-10-14-fast-hooks-vs-comprehensive.md` | Splits the Crackerjack merge gate: `fast_hooks` runs per-merge, `comprehensive` runs at publish stage only. Phase 1 ships a `--no-crackerjack` operator-approved bypass on `merge_to_main.py:run_crackerjack_gate`. Phase 2 (full fast_hooks/comprehensive split) is a follow-up. **NOTE: this file currently has unresolved `<<<<<<< HEAD` conflict markers in the Status section** — to be resolved in a separate commit. | Active (with conflict markers). |
| `2026-10-03-mainautopush.md` | Narrow exception to `feedback-bodai-push-is-user-controlled`: `git push origin main` permitted only after stages 1–4 of the trunk-based workflow, only by the Python module + SessionEnd hook + slash command. | Active. |
| `2026-10-03-trunk-based-agent-review.md` | Trunk-based agent-review workflow contract: worktree → branch → ensemble review → `crackerjack run -v` gate → squash-merge to `main` → optional auto-push. | Active. |
| `sdd-bundling-defensive-pattern.md` | In multi-task SDD plans, downstream tasks MUST use `git add <specific-paths>` (never `git add .`) when an upstream task left staged files; detect dirty trees before each commit; the SDD controller audits for unexpected files. Captured from `def3eb7a` in `2026-09-10-jot-drain` execution. | Active. |
| `2026-10-14-decision-adapter-category.md` | Oneiric gets a `decision/` adapter category with three Phase 0 adapters: `JevAdapter` (TypeSafe Jev, closed hosted), `Decision3Adapter` (vLLM Semantic Router Decision 3.0, default `vllm-sr/d3-mini` for Apple Silicon fit), `BgeTeiRerankAdapter` (HuggingFace TEI). All subclass `DecisionBase[SettingsT]` and satisfy the `OneiricAdapter` Protocol structurally. Hard sequencing rule: `task_router.py` migration off `HybridAdapterRegistry` must land before Mahavishnu consumption. Spec at `docs/specs/2026-10-14-decision-adapter-category-design.md`; plan at `docs/plans/2026-10-14-decision-adapter-category.md`. | Active. |
| `2026-08-28-cross-repo-fanout-cwd-isolation.md` | Rules for parallel-fanout CWD isolation: default to sequential per-repo dispatch; if parallel required, parent must `ExitWorktree` first; each agent creates its own `/tmp/<branch>` worktree; aggregate gate on 3 conditions (booleans + commit_sha + branch HEAD). Layer 4 (PreToolUse hook) deferred. Adopted after the 2026-08-26 Phase 3 fanout and the 2026-08-27 cleanup of 16 abandoned worktrees from the 2026-08-21 fanout. | Active. |
| `2026-08-24-bodai-mcp-routing-pattern.md` | MCP/agent scoping rules for the Bodai ecosystem: secrets in shell env, MCP config in per-project `.mcp.json`, agents scoped to project, plugins preferred over bare URL. Established after the 2026-08-24 ultracode audit. | Active. |
| `ty-ignore-codes.md` | Canonical ty diagnostic codes for `# ty: ignore[...]`; rules for which code fits which boundary; crackerjack hook's `KNOWN_TY_CODES` is kept in sync via `tests/unit/tools/test_ty_ignore_syntax.py`. | Active. |
| `worktree-autoremove-policy.md` | Narrow Rule 2 amendment permitting explicitly invoked `worktree prune-merged`; hook and cron remain prohibited. | Active. |
| `agent-curation-strategy.md` | Rules for adding/archiving agents: mycelium-core deduplication, Bodai-stack relevance, 15k token limit. | Active. |
| `skill-vs-agent-strategy.md` | When to write a skill vs. an agent: trigger-driven procedures → skill, domain persona → agent. | Active. |
| `technical-debt-roadmap.md` | Side discoveries from the recent `.claude/agents/` and `scripts/test_matrix.py` cleanup work. 5 items, 3 size classes. | 4/5 RESOLVED (TD-1..TD-4 done; TD-5 open). |
| `test-matrix-review-followups.md` | Deferred MEDIUM/LOW items from the `scripts/test_matrix.py` review. | All 4 groups RESOLVED (verified 2026-09-06). Historical record only. |
| `removed-scripts.md` | Policy for `required_scripts:` references in tool command frontmatter. | Active. |
| `wire-up-contract.md` | Integration Contract template + orphan audit gate; prevents "built but not wired" deliveries. | Active. |
| `mcp-backend-wiring-discipline.md` | Required feed observability + `/health` aggregation + smoke tests for every Bodai MCP server. **Amended 2026-09-06 with §7**: extends coverage to consumer-side MCP aggregations (e.g., Flowscape calling scapy-mcp). Trigger: ADR 0016 L1 BLOCKER B4 in `docs/adr/0016-multi-agent-review.md`. | Active. |
| `mahavishnu-tool-preference-policy.md` | Tool-selection steering lives only in `MAHAVISHNU_TOOL_PROFILE` and `CLAUDE.md` `## Tool Preferences`; docstrings narrate, do not market. | Active. |
| `followups-lifecycle.md` | Lifecycle for `docs/followups/`: README index + `.archive/` on completion (never delete), Status-line convention. Mirrors this directory's conventions. | Active. |
| `worktree-cleanup-policy.md` | Codified 4-tier cleanup rubric (A-merged / A-orphan-detached / X / B / C / D) for stale git worktrees, plus salvage / lock + live-PID / agent-dispatch reap / cross-repo plan-orphan rules. Codified after the 2026-09-07 sweep of 31 active Bodai repos. Adds the absent coverage from existing `worktree-autoremove-policy.md` (which only covers prune-merged removal). | Active. |
| `2026-08-25-bodai-tui-contract.md` | TUI contract for bodai shell/dashboard + mahavishnu monitor watch: AdminShell reuse pattern (per-component IPython shells), bodai-TUI-as-aggregator pattern (cross-component dashboard), per-component vs cross-component split (no TUI may duplicate either scope). Captured from `docs/plans/2026-08-25-bodai-tui-shell-surface.md` Phase B-1 polish pass. | Active. |
