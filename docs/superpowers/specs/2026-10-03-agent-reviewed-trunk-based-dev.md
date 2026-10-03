---
status: draft
role: implementation
topic: dev-workflow
date: 2026-10-03
last_reviewed: 2026-10-03
superseded_by: null
blocks_on: []
---

# Agent-Reviewed Trunk-Based Development

## **Goal:** A dev workflow for Bodai where AI workers create short-lived worktrees, an AI ensemble reviews, `crackerjack run` gates the merge, and `main` auto-pushes to `origin/main` — eliminating GitHub PRs and the dead-branch litter they create. **Architecture:** A `merge-to-main` slash command orchestrates the per-worktree cycle; a SessionEnd hook auto-runs the same cycle when the worker is done; the existing `feedback-bodai-push-is-user-controlled` rule gains a single, narrow exception for `origin/main` after a successful squash-merge. **Tech Stack:** Python 3.14 (target per `CLAUDE.md`), existing `mahavishnu` orchestrator, existing `crackerjack` quality tool, existing `session-buddy` checkpoint + reflection store for audit log, existing `.claude/hooks/` SessionEnd contract, no new MCP server.

## Context

As of 2026-10-03, `origin` has 25 remote branches on `github.com/lesleslie/mahavishnu`. All 25 are `0 ahead of main` — fully merged. Ages 39–78 days. None protected. Three clusters:

- 10 `task-*` branches (74–78d): the `mahavishnu` plugin manifest + wave plan rollout that became the plugin shipped today.
- 12 `worktree-*` branches (39–43d): the ADR-015 worktree/storage refactor that just shipped.
- 2 `triage-fix-*` branches (77d): doc triage cleanup folded into the wave above.

These are not worktree sprawl — they are PR-side branch litter. They were pushed for review, merged, and never deleted. The local convention was "delete the branch after merge"; the discipline never automated.

Separately, the user wants to dev **remove the GitHub-PR-shaped review step** for AI-driven dev. PRs are a 2010s artifact designed to gate human reviewers from pushing directly to `main` — a gate whose value is "force a second human to look at the diff before it's shared." In an AI-only review pipeline the gate still has value (force an AI ensemble to look at the diff) but the GitHub-shaped gate is wrong: it is async-by-default (designed for humans who need hours/days), heavyweight (checks, statuses, required reviewers), and creates branch persistence nobody owns.

This spec replaces the PR-shaped gate with an AI-ensemble-shaped gate that lives in the worktree itself, with a single narrow auto-push rule that fills the gap between "merged locally" and "backup on origin." Human review stays exactly where it is today: at the publish cycle (`crackerjack run -p <level>`, version bump, tag, release).

## Goals & Non-Goals

### Goals

1. **Ephemeral branches by construction.** A branch exists only for the lifetime of its worktree; deleted with it. Eliminates the 25-dead-branches class of litter by construction.
2. **AI-ensemble review at the merge boundary.** Three agents review the diff: two specialized for the task domain, one drawn at random from a small generalist pool. If the verdict is "needs adjustment," the worker iterates; the ensemble re-reviews.
3. **`crackerjack run` as the merge gate.** Existing quality tool, existing operator standard (`crackerjack-cli-run-subcommand` memory). Fail-closed: a non-zero exit blocks the merge.
4. **Auto-push `main` to `origin/main` after a successful squash-merge.** Mechanical backup. The exception to `feedback-bodai-push-is-user-controlled` is narrow and explicit.
5. **Audit trail.** Every merged piece of work writes a local audit file recording the worker's work, the three agent reviewers, and the gate verdict. Purely local; not pushed.
6. **Cross-session continuity.** If a session ends mid-cycle, the next session resumes from a `.review-state.json` in the worktree. No silent abandonment.

### Non-Goals (v1)

- **Not a GitHub-PR replacement for human review.** Human review still happens at the publish cycle. No GitHub UI, no required reviewers, no status checks via GitHub.
- **Not a remote-push of ephemeral branches.** The whole point is no remote branch litter. Push to `origin` only on `main`.
- **Not a force-push escape hatch.** `git push --force` remains user-controlled in all contexts.
- **Not an automated version bump, tag, or `crackerjack run -p` cycle.** Publish is its own concern, owned by the human.
- **Not a multi-machine sync story.** Local only during dev. Multi-machine access at review-time is solved by pushing `main` (already covered by goal 4) or by ssh'ing the `.git` dir (out of scope).
- **Not a stacked-diff model.** `git-stack` / `gh-stack` are noted as alternatives in this spec's appendix but not adopted here. Ephemeral branches are simpler and align with current SoloAI dev patterns.
- **Not a trunk-based-with-feature-flags model.** Would require restructuring every commit as feature-flagged, out of scope for v1.
- **Not a CI-on-`main` story.** GitHub Actions or equivalent on `main` is a separate decision; in v1, `crackerjack run` is the only automated safety net, and it fires before merge, not after.

## The Workflow

A piece of work proceeds through seven stages. Stages 1–6 are owned by the AI worker (slash command + SessionEnd hook); stage 7 is owned by the human at publish time.

| Stage | Owner | Action | Gate | Failure mode |
|---|---|---|---|---|
| **1. Worktree** | AI worker | `git worktree add -b <ephemeral> <path> <main>`; commit normally | Path outside repo, branch name unique | Branch name collision → choose another |
| **2. Review** | AI ensemble | 2 specialized agents + 1 random generalist review the diff; iterate if rejected | Consensus or 2/3 verdict | If all three disagree with each other → escalate to user |
| **3. Quality gate** | AI worker | `crackerjack run` | non-zero exit blocks merge | Worker fixes and re-enters stage 2 |
| **4. Squash-merge** | AI worker | `git rebase origin/main` (catch-up if remote moved) → `git checkout main` → `git merge --squash <branch>` → single semantic `git commit` | Rebase is clean (no conflicts); pre-merge `git status` clean | Conflict → return to stage 1 in worktree |
| **5. Auto-push** | AI worker | `git push origin main` | Non-fast-forward fails loudly; never force-pushes | Divergence → user resolves manually |
| **6. Cleanup** | AI worker | `git worktree remove <path>` + `git branch -d <ephemeral>` + `git worktree prune` + write audit log | None | Cleanup failure → log warning, continue |
| **7. Publish** | Human | `crackerjack run -p <level>` + version bump + tag + `git push origin --tags` (existing convention) | `feedback-bodai-push-is-user-controlled` still applies for tag + version bump | Out of scope for this spec |

Stages 2 and 3 are repeatable: if the review verdict is "needs adjustment" or the gate fails, the worker iterates within the same worktree and re-enters stage 2 at the top.

Stage 4 (squash-merge) is the only stage that touches `main`. The worktree's branch is never pushed; only the squashed result lands on `main`, and only `main` is pushed to `origin`.

## Components

### 4.1 Slash command `merge-to-main`

**Location:** `.claude/commands/merge-to-main.md`

**Contract:** Orchestrates stages 2–6 on the current worktree. Triggered by the user (`/merge-to-main`) or by the SessionEnd hook (automatic). Idempotent: if a `.review-state.json` exists in the worktree, resumes from there.

**Inputs (all optional, inferred from cwd/worktree):**
- `--branch <name>`: the ephemeral branch to merge (default: current branch of cwd)
- `--review <mode>`: `quick` (skip ensemble), `default` (3-agent), `thorough` (3-agent + crackerjack + crackerjack)
- `--no-push`: skip stage 5 (default: push)
- `--no-cleanup`: skip stage 6 (default: cleanup)
- `--from <base>`: override rebase base (default: `origin/main` if remote exists, else `main`)

**Outputs:** Audit log entry at `~/.local/state/mahavishnu/dev-log/<YYYY-MM-DD>-<branch-slug>.md`. Exit code 0 on full success, non-zero on first failure.

### 4.2 SessionEnd hook

**Location:** `.claude/hooks/agent-merge-on-end.py`

**Contract:** Runs at SessionEnd. If the cwd is a worktree of a known repo (the repo's `.git/worktrees/<id>/gitdir` exists), and the worktree has commits not yet in `<repo>/main`, invokes the slash command. If the worktree is clean against `main` (no diff), no-op.

**Skip conditions:**
- Cwd is not a worktree (regular checkout or detached HEAD).
- Worktree's commits are already in `<repo>/main` (worker already merged).
- `MAHAVISHNU_AUTO_MERGE=0` is set in the environment.
- Cwd is `~` or `/tmp` or another non-repo path.

### 4.3 Audit log

**Location:** `~/.local/state/mahavishnu/dev-log/<YYYY-MM-DD>-<branch-slug>.md`

**Format:**
```markdown
---
date: 2026-10-03T15:32:11-07:00
repo: mahavishnu
worktree_path: ~/.local/state/mahavishnu/worktrees/mahavishnu/fix-ty-errors
ephemeral_branch: fix-ty-errors
commits_merged: 4
reviewers:
  - agent: python-pro
    verdict: pass
    note: ""
  - agent: pr-review-toolkit:code-reviewer
    verdict: pass
    note: ""
  - agent: mycelium-core:code-reviewer
    verdict: pass
    note: ""
gate:
  tool: crackerjack
  exit_code: 0
  duration_s: 142
merge:
  strategy: squash
  base: origin/main
  pre_merge_local_main_sha: b116d395
  post_merge_local_main_sha: <new>
push:
  remote: origin
  branch: main
  result: success
  duration_s: 3
cleanup:
  worktree_removed: true
  branch_deleted: true
  pruned: true
---

# fix-ty-errors

Worker prompt: <full prompt>
Squash-merge message: <full message>
Diff summary: <stat -N lines, M files>
```

**Retention:** indefinitely, local only. A redactor (`MAHAVISHNU_DEVLOG_REDACT=<glob>`) can strip commit bodies or messages if a future need arises; not in v1.

### 4.4 Review ensemble contract

**Default ensemble (3 agents):**
- Agent 1: domain-specialist (task-type-aware). Today the slash command selects from: `python-pro`, `typescript-pro`, `rust-engineer`, `go-pro`, `jinja2-template-designer`, `docker-specialist`, `terraform-specialist`, `mcp-integration-expert`, `mahavishnu-specialist`, `session-buddy-specialist`-when-merged-into-mahavishnu, `oneiric-specialist`, `crackerjack-specialist`-when-merged-into-mahavishnu. Selection rule: the worker specifies `--review-domain <name>`; default is `python-pro`.
- Agent 2: code-quality specialist. Always `pr-review-toolkit:code-reviewer` (the official Code-Reviewer agent, not the mycelium one).
- Agent 3: random generalist. Drawn uniformly from `[mycelium-core:code-reviewer, mycelium-core:refactoring-specialist, pr-review-toolkit:silent-failure-hunter, pr-review-toolkit:pr-test-analyzer, pr-review-toolkit:comment-analyzer]`. Each invocation re-shuffles.

**Verdict contract:** Each agent returns `{verdict: "pass" | "needs_adjustment" | "block", note: "..."}`. The merge proceeds if:
- At least 2 of 3 say `pass`, OR
- 2 specialized say `pass` and the random says `needs_adjustment` (random is advisory).
- `block` from any agent blocks the merge.

**Quick mode:** `--review quick` skips the ensemble entirely. Allowed only for: doc-only changes (`.md`, `.txt`, no path-dict), pure-comment changes, or changes explicitly flagged `--trivial` by the user. `crackerjack run` still runs.

**Override:** `--review none` skips review entirely; user responsibility.

### 4.5 Merge strategy

- **Branch lifetime:** created at `git worktree add` time, deleted at `git worktree remove` time. Never pushed to a remote (no exception).
- **Squash, not fast-forward:** the worker's N intermediate commits become 1 commit on `main`. The semantic message summarizes the work (auto-generated from agent prompt + diff stat; editable by the worker before commit).
- **Rebase before merge:** `git rebase <base>` runs before `git merge --squash`. Catches conflicts early. Failure → return to stage 1 in the worktree.
- **Merge commit style:** `git merge --squash <branch>` stages changes but does NOT auto-commit. The worker writes the final commit message via a Claude call summarizing the diff.
- **Local-only between commits and push:** stages 4 and 5 are atomic in the SessionEnd hook (push follows merge). If push fails, the local `main` is ahead of `origin/main` until the user resolves manually. No automatic force-push, ever.

### 4.6 Push rule

**Auto-push scope:** `git push origin main`, only on `main`, only after a successful squash-merge in stages 1–4, only by the SessionEnd hook or the `/merge-to-main` slash command.

**What is NOT auto-pushed:**
- Ephemeral branches (`fix-ty-errors`, `agent-<short>`, etc.)
- Tags (e.g. `v0.32.0`)
- Any branch other than `main`
- Any remote other than `origin`
- Force-pushes of any kind

**Divergence handling:** If `git push origin main` returns a non-fast-forward error, the hook:
1. Captures the error verbatim.
2. Writes the failure to the audit log (with `push.result: "diverged"`).
3. Surfaces the failure as a non-zero SessionEnd exit code.
4. Does **not** retry, force-push, rebase, or merge. Manual resolution.

## Failure Modes

| Mode | Detection | Handling |
|---|---|---|
| **Remote `main` has diverged** | `git push` returns non-fast-forward | Hook fails loudly with the local/remote SHA pair; user rebase + retry. No force-push. |
| **Concurrent merges** (two sessions, both squash into local `main`, both push) | git's ref lock on merge; second push hits FF check and fails | First succeeds; second surfaces divergence. User resolves manually. No data loss. |
| **No remote configured** | `git remote` returns empty | Push is a no-op; hook logs `push.result: "no_remote"` and exits 0. |
| **Push auth/network failure** | `git push` returns non-zero for any reason other than FF | Hook exits non-zero; audit log records `push.result: "error:<message>"`. |
| **GitHub branch protection rejects direct push to `main`** | `git push` returns HTTP 403 with protection error | Hook surfaces the message verbatim; user disables protection or configures a bypass. |
| **Worktree dirty state at merge time** | `git status --porcelain` returns non-empty in the worktree | Hook refuses to merge; user commits/stashes the uncommitted work. |
| **Pre-merge `crackerjack run` failure** | Hook detects non-zero exit | Hook refuses to merge; worker iterates. |
| **Session ends mid-review** | `.review-state.json` exists in the worktree | Next session reads it; slash command resumes from the current review step. |
| **Cleanup failure** (worktree remove errors because of stale locks) | `git worktree remove` returns non-zero | Hook logs warning; next `git worktree prune` cleans metadata. Branch stays until next manual `git branch -d`. |
| **Branch-name collision** (two sessions both pick `fix-ty-errors`) | `git worktree add` fails | Session retries with `agent-<short>` or `<branch>-<short>`. |

## Memory + CLAUDE.md Edits

### Memory

**Update `feedback-bodai-push-is-user-controlled`** to add an exception clause:

> **Exception (added 2026-10-03)**: Auto-push of `main` → `origin/main` after a successful squash-merge in the trunk-based-agent-review workflow is allowed. Triggered by the SessionEnd hook (`agent-merge-on-end.py`) or the `/merge-to-main` slash command. Fail-fast on divergence. All other push types (tags, ephemeral branches, force-push, non-origin remotes) remain user-controlled.

**Create new memory `feedback-bodai-merge-workflow.md`** capturing the workflow contract (which CLAUDE.md readers can use to know what the slash command and SessionEnd hook do).

### CLAUDE.md

**Update user-level `~/.claude/CLAUDE.md`** (the "Worktree location preference" block) to add a "Dev workflow" subsection stating the 7-stage workflow in two paragraphs. Keeps the worktree-location convention + the merge convention in one place.

**Update `~/Projects/mahavishnu/CLAUDE.md`** (the "Tool Preferences" block) to note that the merge command lives in this repo. The other 5 core repos (`akosha`, `session-buddy`, `crackerjack`, `oneiric`, `mcp-common`) inherit the convention without per-repo edits — their workers all run inside mahavishnu's slash command.

**No per-repo edits beyond mahavishnu.** The convention is orchestrator-level (mahavishnu dispatches, audits, pushes). Worker-level (crackerjack, session-buddy, etc.) is unchanged.

### `.claude/decisions/`

**Create `.claude/decisions/2026-10-03-trunk-based-agent-review.md`** with the same content as this spec's "Workflow" section in shorter form, plus the exception clause. This is the per-repo policy document that future readers in this repo can find without spelunking into `docs/superpowers/specs/`.

## Verification

**Smoke test (in a real worktree):**

1. Create a worktree at `~/.local/state/mahavishnu/worktrees/mahavishnu/test-merge` with a trivial change (typo fix in a comment).
2. Run `/merge-to-main --review quick`. Verify:
   - `git log --oneline origin/main..main` returns 0 after merge + push.
   - Worktree removed; branch deleted.
   - Audit log entry exists.
3. Repeat with `--review default` to exercise the ensemble.

**Failure-mode tests:**

1. **Diverged remote:** manually move `origin/main` forward (via a dummy commit on a throwaway branch and `git push origin <throwaway>:main` on a different machine or via `gh api`), then run `/merge-to-main`. Verify hook exits non-zero, no force-push, audit log records `diverged`.
2. **Pre-merge `crackerjack` failure:** introduce a known-failing change, run `/merge-to-main`. Verify hook refuses to merge.
3. **Concurrent merges:** run two `Agent(...)` calls in parallel that both squash into local `main`. Verify one succeeds, one fails on push with FF error.
4. **Session-end mid-review:** start a `--review default`, end the session mid-ensemble. Start a new session, navigate to the worktree, run `/merge-to-main`. Verify it resumes from the saved state.

**Cross-repo consistency:**

1. Create a worktree in `~/Projects/akosha/`, run `/merge-to-main`. Verify the hook fires the same way (the slash command is repo-agnostic; the orchestrator inspects `cwd` to find the parent repo).
2. Same in `~/Projects/session-buddy/`. (Per the prior session-buddy follow-up, `session_buddy/core/paths.py` already resolves to the same `~/.local/state/mahavishnu/worktrees` path.)

**Pre-deploy gate:** before tagging a release, run `git log --oneline` to confirm every merge commit on `main` has a corresponding audit log entry at `~/.local/state/mahavishnu/dev-log/`. Any commit lacking an audit entry is a hole; the gate fails.

## Open Questions

1. **Ensemble cost.** Three-agent review costs tokens. For trivial changes the overhead is wasted. Mitigation: `--review quick` for trivial; users learn the threshold. No automated trivial-detection in v1 (avoid over-engineering).
2. **Audit log location on multi-machine users.** The path is `~/.local/state/mahavishnu/dev-log/` which is per-machine. A user with two machines will have two logs. Not solved in v1; could be solved with `MAHAVISHNU_DEVLOG_BACKEND=session-buddy` in v2.
3. **Cherry-pick from a merged commit.** If a user wants to revert a single squash commit, they need to know the original worktree's ephemeral branch. Mitigation: each audit log entry includes `ephemeral_branch` and `commits_merged`. `git revert -m 1 <merge-sha>` works for true merge commits but not for squash commits; users use `git revert <sha>` instead. Not solved in v1.
4. **`auto-coordinate` skill interaction.** The existing `auto-coordinate` skill may auto-link tasks to git branches; it needs to learn that ephemeral branches aren't persistent and shouldn't be the "link target" for cross-session tasks. Out of scope for v1; flag in the PR for `auto-coordinate` maintainers.

## Appendix: Alternatives Considered

| Alternative | Why not v1 |
|---|---|
| **GitHub PRs with auto-delete** (`gh pr merge --delete-branch`) | Still async-by-default; still heavyweight; still requires GitHub-shaped review UI. Same "PR gate, just smaller" complaint applies. |
| **Stacked diffs (`git-stack`, `gh-stack`)** | Cleaner PR model for layered work, but no current user familiarity. Higher learning curve; revisit if "lots of layered PRs" becomes a real workflow. |
| **Trunk-based with feature flags** | Eliminates branches but eliminates PR-shaped review too. Only works for solo dev with low-stakes surface. Worth revisiting if v1 proves the team values review and remix. |
| **Force-push with safety check** | Never. `feedback-bodai-push-is-user-controlled` exists for a reason. |

## Cross-references

- `docs/superpowers/specs/2026-04-14-akosha-skills-design.md` — parallel skill catalog pattern; the new `merge-to-main` slash command follows the same discoverability rules.
- `docs/superpowers/specs/2026-09-29-task-system-design.md` — the new Task system uses ephemeral branches for `auto-coordinate`-linked work; this spec's merge workflow is compatible (Tasks already commit to the worktree's branch, which gets squashed here).
- `.claude/decisions/worktree-cleanup-policy.md` — the tier rubric and `LOCKED-live`/`LOCKED-orphan` semantics from this spec's stage-6 cleanup.
- `feedback-bodai-push-is-user-controlled` — the rule this spec adds an exception to.
- `feedback-worktree-update-ref-drops-parallel-commits` — stage-4's rebase-before-merge is the inverse of this anti-pattern; rebase is safe only when worktree-branch is fast-forward of `main`.
- `feedback-bodai-atomic-commit-recurring-fixes` — the squash-merge strategy aligns with this: one logical commit per piece of work means recurring fixes land as one commit, not five.
- `feedback-bodai-push-is-user-controlled` and `feedback-mcp-common-version-bump-is-user` — stage-7 (publish) preserves both rules.