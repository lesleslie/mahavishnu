---
date: 2026-07-25
last_reviewed: 2026-07-25
superseded_by: null
topic: license-false-intent-postmortem
status: complete
role: historical
---

# 2026-07-20 LICENSE False-Intent Incident: Postmortem and Forward Rules

> **For agentic workers:** This is a postmortem, not an implementation plan. Read it before any cross-repo commit pass that touches tracked files. The forward-looking rules in §5 are binding.

## 1. Context

On 2026-07-20, a parent Claude subagent session
(`/Users/les/.claude/projects/-Users-les-Projects-mahavishnu/c67fdb73-2e4a-4a8b-bc14-ad475a1f1af1.jsonl:2535-2540`)
encountered `D LICENSE` working-tree state across multiple Bodai repositories and incorrectly inferred that the deletion was "probably intentional coordinated removal." The parent then dispatched a subagent which committed the deletion in five repositories within a six-minute window. The original filesystem unlink that produced the `D` state is unattributed; no transcript, shell history, or cleanup code path preserves it. Restoration on 2026-07-25 required twelve or more commits across twenty-one repos. The incident matters because the parent's inference was the only thing standing between a transient working-tree anomaly and a permanent, distributed, license-bearing repository-state change.

## 2. Timeline

| When (PDT) | Event |
|---|---|
| 2026-07-17 00:53 | Crackerjack already shows `D LICENSE` (earliest preserved observation of the `D` state on a Bodai repo) |
| 2026-07-20 20:26 | Parent Claude subagent session infers "probably intentional coordinated removal" |
| 2026-07-20 20:33–20:39 | Subagent commits 5 deletion commits in a 6-minute window: |
| | — session-buddy `67aca598` |
| | — akosha `ab98f40` |
| | — mcp-common `887deeb` |
| | — oneiric `a3c8ec1` (reverted via `86d74ac` "chore: restore LICENSE" on 2026-07-25) |
| | — dhara `94113d6` |
| 2026-07-20 23:54 | CSS-MCP `D LICENSE` observed |
| 2026-07-21 00:15 | Graphics-MCP, Penpot-API-MCP, Splashstand `D LICENSE` observed |
| 2026-07-21 05:58 | `uv sync --upgrade --all-groups` ran across the workspace (exonerated as a vector) |
| 2026-07-25 | Audit + restoration across 21 Bodai repos (14 `-mcp` standalone servers + 5 Bodai core repos + splashstand; oneiric was restored to HEAD) |

## 3. Commits referenced

**False-intent deletion commits (5):** session-buddy `67aca598`, akosha `ab98f40`, mcp-common `887deeb`, oneiric `a3c8ec1`, dhara `94113d6`. All five committed in a 6-minute window by a single dispatched subagent acting on the parent's "probably intentional" inference.

**Restoration commits (12+):** broken into three categories — (a) `git revert` of the 5 deletion commits where still applicable, (b) explicit `git checkout HEAD~N -- LICENSE` plus amend or follow-up commit in repos where the deletion was not the commit subject, (c) re-introduce `LICENSE` from the canonical Bodai template in repos where the file had never existed at the deleted commit's ancestor. Categories (a) and (b) cover the five originally affected repos; category (c) covers the remaining sixteen repos whose `D LICENSE` state was either pre-existing or produced by the same undetected mechanism but never had a deletion commit to revert.

**Restoration commits used varying wording across three groups:**

- **7 `-mcp` repos** (porkbun-dns-mcp, porkbun-domain-mcp, raindropio-mcp, spline-mcp, synxis-crs-mcp, synxis-pms-mcp, unifi-mcp): `chore: restore LICENSE and normalize attribution`
- **4 Bodai core repos** (akosha, dhara, session-buddy, mcp-common): `chore: normalize LICENSE attribution to Robert Leslie and Wedgwood Web Works`
- **oneiric**: `chore: restore LICENSE` (commit `86d74ac`)

The wording variance reflects per-repo conventions about whether the commit's primary purpose was restoration or attribution normalization.

## 4. Root cause analysis

**The original filesystem unlink is not preserved in any transcript, shell history, or cleanup code path.** Three independent investigations (crackerjack working-tree log scan, parent-session transcript audit across all sibling sessions, and `.gitignore`/Oneiric/MCP supervisor hook log review) cross-confirmed this. The unlink happened, was never logged, and is unattributed.

**The five false-intent commits were caused by a parent-agent prompt** at `c67fdb73-…:2535-2540` that classified the `D LICENSE` working-tree state as intentional based on the (correct) observation that the deletion appeared to be coordinated across multiple repos. The coordination was real; the inference that coordination implied intent was not. The subagent receiving the dispatch had no basis to second-guess the parent.

**Exonerated vectors:**

- **Crackerjack.** Reported the `D` state but did not act on it; no commit path goes through Crackerjack.
- **Oneiric.** Configuration layer was untouched; no cleanup task targets tracked files.
- **MCP supervisor.** No MCP server removes tracked files; the only write paths are session-buddy checkpoints (which add, not remove).
- **Git hooks.** No pre-commit, post-commit, or post-checkout hook on any of the 21 affected repos removes tracked files.
- **`.gitignore`.** Cannot cause a deletion of a tracked file; ignores are read-side only.
- **`uv sync --upgrade --all-groups` (2026-07-21 05:58).** Runs against the venv and `pyproject.toml` lock; cannot affect tracked LICENSE files. Confirmed by running the same command in an isolated worktree with the same outcome (LICENSE unchanged).

## 5. Forward-looking rules (binding)

The following rules are binding on all future agents — subagents, parent agents, and humans operating through the same workflow.

1. **Never assume `D <file>` is intentional.** When a tracked file appears deleted in a working tree, treat the deletion as accidental until proven otherwise. A coordinated `D` state across multiple repos is *not* proof of intent — it is proof that the same accidental mechanism is affecting multiple repos. Surface the `D` state to the user and wait for explicit confirmation before committing.

2. **Pre-task inspection gate.** Before any cross-repo commit pass, run `git status` in each repo and explicitly enumerate any `D` states. If a deletion matches a hand-curated file — `LICENSE`, `COPYING`, `NOTICE`, `README`, `pyproject.toml`, `CLAUDE.md`, `AGENTS.md`, `settings/*.yaml`, `.gitignore` — STOP and ask the user. Do not proceed under any inference of intent.

3. **The 2026-07-20 prompt is a counter-example.** Future agents reading this plan should treat the parent agent's "probably intentional" inference at `c67fdb73-…:2535-2540` as a teaching example. The inference was wrong; the cost of acting on it was ~12 commits across 21 repos and a full re-audit. The correct response to a coordinated `D LICENSE` is *not* to commit the deletion; it is to ask the user.

## 6. Recommended safeguards (out of scope to implement here)

These safeguards would have prevented or contained the 2026-07-20 incident. Documenting them here so they can be picked up by a follow-up plan; implementation is out of scope for this postmortem.

1. **Pre-commit hook** that fails when `git diff --cached --diff-filter=D --name-only` includes any of `LICENSE`, `COPYING`, or `NOTICE` without explicit per-file authorization (e.g., a `LICENSE-DELETE-AUTHORIZED: <reason>` trailer on the commit message).
2. **Claude `PreToolUse` hook** that rejects `Bash` commands capable of removing tracked `LICENSE`/`COPYING`/`NOTICE` files (i.e., any `rm`, `git rm`, or `find … -delete` whose expansion includes a tracked license-bearing path).
3. **Cross-repo automation rule** that requires, for any commit pass touching more than one repo: an explicit allowlist of files to be modified, a dry-run commit, a staged-deletion review showing the proposed `D` set, and a per-repo user confirmation. The current "sweep" pattern (subagent dispatched with a free hand) is the failure mode.

## 7. Acceptance criteria

This postmortem is "done" when:

- [ ] Filed at `/Users/les/Projects/mahavishnu/docs/superpowers/plans/2026-07-25-license-false-intent-postmortem.md`
- [ ] Cross-referenced from [2026-07-13-mcp-server-family-mcpbase-migration.md](./2026-07-13-mcp-server-family-mcpbase-migration.md) (the re-anchor Edit G already added this note)
- [ ] Future agents load this plan when they encounter unexpected `D` states in any Bodai repo

## 8. Out of scope

- The original filesystem unlink remains unattributed. Do not speculate about its origin; three independent investigations failed to preserve it.
- The 2026-07-21 `uv sync` sweep is exonerated. Do not blame it.
- Implementation of the safeguards in §6 is out of scope for this postmortem.
