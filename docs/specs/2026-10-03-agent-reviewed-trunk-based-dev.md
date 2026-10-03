---
status: draft
role: implementation
topic: dev-workflow
date: 2026-10-03
last_reviewed: 2026-10-03
superseded_by: null
blocks_on: []
title: "Agent-Reviewed Trunk-Based Development"

---

# Agent-Reviewed Trunk-Based Development

## **Goal:** A dev workflow for Bodai where AI workers create short-lived worktrees, an AI ensemble reviews, `crackerjack run -v` gates the merge, and `main` auto-pushes to `origin/main` — eliminating GitHub PRs and the dead-branch litter they create. **Architecture:** A `merge-to-main` slash command orchestrates the per-worktree cycle; a SessionEnd hook auto-runs the same cycle when the worker is done; a new `.claude/decisions/2026-10-03-main-autopush.md` documents the auto-push rule as a governance amendment superseding the relevant clause of `feedback-bodai-push-is-user-controlled`. **Tech Stack:** Python 3.14 (target per `CLAUDE.md`), existing `mahavishnu` orchestrator, existing `crackerjack` quality tool, existing `session-buddy` checkpoint + reflection store for audit-log mirror, existing `.claude/hooks/` SessionEnd contract, no new MCP server.

## Context

As of 2026-10-03, `origin` has 25 remote branches on `github.com/lesleslie/mahavishnu`. All 25 are `0 ahead of main` — fully merged. Ages 39–78 days. None protected. Three clusters: 10 `task-*` branches (74–78d, the `mahavishnu` plugin rollout), 12 `worktree-*` branches (39–43d, the ADR-015 worktree/storage refactor), and 2 `triage-fix-*` branches (77d, doc cleanup folded into the wave above).

These are not worktree sprawl — they are PR-side branch litter. Branches were pushed for review, merged, never deleted. The convention said "delete after merge"; the discipline never automated.

Separately, the user wants to dev **remove the GitHub-PR-shaped review step** for AI-driven dev. PRs are a 2010s artifact designed to gate human reviewers from pushing directly to `main` — a gate whose value is "force a second human to look at the diff before it's shared." In an AI-only review pipeline the gate still has value (force an AI ensemble to look at the diff) but the GitHub-shaped gate is wrong: it is async-by-default (designed for humans who need hours/days), heavyweight (checks, statuses, required reviewers), and creates branch persistence nobody owns.

This spec replaces the PR-shaped gate with an AI-ensemble-shaped gate that lives in the worktree itself, with a single narrow auto-push rule that fills the gap between "merged locally" and "backup on origin." Human review stays exactly where it is today: at the publish cycle (`crackerjack run -p <level>`, version bump, tag, release).

## Goals & Non-Goals

### Goals

1. **Ephemeral branches by construction.** A branch exists only for the lifetime of its worktree; deleted with it. Eliminates the 25-dead-branches class of litter by construction.
2. **AI-ensemble review at the merge boundary.** Three agents review the diff: two specialized for the task domain, one drawn at random from a small generalist pool. If the verdict is "needs adjustment," the worker iterates; the ensemble re-reviews.
3. **`crackerjack run -v` as the merge gate.** Existing quality tool, existing operator standard (`crackerjack-cli-run-subcommand` memory). Fail-closed. `crackerjack run -v` (NOT `-p` — the publish stage must never fire on the merge path).
4. **Auto-push `main` to `origin/main` after a successful squash-merge.** Mechanical backup. Lives in `.claude/decisions/2026-10-03-main-autopush.md` (governance amendment superseding the relevant clause of `feedback-bodai-push-is-user-controlled`).
5. **Audit trail.** Every merged piece of work writes a local audit file at the path resolved by `get_dev_log_path()` (a new helper mirroring `get_audit_path()` in `mahavishnu/core/paths.py`). Each entry is also reflected into `session-buddy` via `mcp__session-buddy__store_reflection` for cross-tool queryability (dual-store rule).
6. **Cross-session continuity.** If a session ends mid-cycle, the next session reads `.review-state.json` from the worktree root and resumes from the current stage. Schema is JSON; idempotency is enforced by stage markers.

### Non-Goals (v1)

- **Not a GitHub-PR replacement for human review.** Human review still happens at the publish cycle. No GitHub UI, no required reviewers, no status checks via GitHub.
- **Not a remote-push of ephemeral branches.** Push to `origin` only on `main`.
- **Not a force-push escape hatch.** `git push --force` remains user-controlled in all contexts.
- **Not an automated version bump, tag, or `crackerjack run -p` cycle.** Publish is its own concern, owned by the human.
- **Not a multi-machine sync story.** Local only during dev. Multi-machine access at review-time is solved by pushing `main` or by ssh'ing the `.git` dir (out of scope).
- **Not a stacked-diff model.** `git-stack` / `gh-stack` are noted as alternatives in this spec's appendix but not adopted here.
- **Not a trunk-based-with-feature-flags model.** Would require restructuring every commit as feature-flagged, out of scope for v1.
- **Not a CI-on-`main` story.** GitHub Actions or equivalent on `main` is a separate decision; in v1, `crackerjack run -v` is the only automated safety net, and it fires before merge, not after.

## The Workflow

A piece of work proceeds through seven stages. Stages 1–6 are owned by the AI worker (slash command + SessionEnd hook); stage 7 is owned by the human at publish time.

| Stage | Owner | Action | Gate | Failure mode |
|---|---|---|---|---|
| **1. Worktree** | AI worker | If `MAHAVISHNU_AUTO_WORKTREE=1` (default; SessionStart hook auto-provisions a session worktree), the worker's ephemeral branch lives **inside** the existing session worktree as a child commit (the ephemeral branch is named `<branch>`, not the session-worktree's auto-name). Otherwise: `git worktree add -b <ephemeral> <path> <base>`; commit normally | Path outside repo, branch name unique | Branch collision → choose another |
| **2. Review** | AI ensemble | 2 specialized agents + 1 random generalist review the diff; iterate if rejected | `block` from any agent blocks; otherwise 2/3 `pass` proceeds; `needs_adjustment` triggers iteration | All three disagree with each other → escalate to user |
| **3. Quality gate** | AI worker | `crackerjack run -v` | non-zero exit blocks merge | Worker fixes and re-enters stage 2 |
| **4. Squash-merge** | AI worker | `git rebase <base>` (catch-up) → re-verify base SHA unchanged → `git checkout <base>` → `git merge --squash <branch>` → semantic `git commit` | Rebase clean; pre-merge `git status` clean | Conflict → return to stage 1 in worktree |
| **5. Auto-push** | AI worker | `git push origin main` | Non-fast-forward fails loudly; never force-pushes | Divergence → user resolves manually |
| **6. Cleanup** | AI worker | `mahavishnu worktree prune-merged --one-off <path>` (uses existing tier-rubric) + `git branch -d <ephemeral>` | Worktree classified `merged` by existing classifier | Classifier returns `not_merged` → refuse cleanup, surface state |
| **7. Publish** | Human | `crackerjack run -p <level>` + version bump + tag + `git push origin --tags` | `feedback-bodai-push-is-user-controlled` still applies for tag + version bump | Out of scope for this spec |

Stages 2 and 3 are repeatable: if the review verdict is "needs adjustment" or the gate fails, the worker iterates within the same worktree and re-enters stage 2 at the top.

Stage 4 (squash-merge) is the only stage that **commits** to `main`. The worktree's branch is never pushed; only the squashed result lands on `main`, and only `main` is pushed to `origin`.

## Components

### 4.1 Slash command `merge-to-main`

**Location:** `.claude/commands/merge-to-main.md` (markdown entry point) + shared Python module at `mahavishnu/core/merge_to_main.py` (so both the slash command and the SessionEnd hook invoke the same logic).

**Invocation surfaces (in priority order):**

1. **SessionEnd hook** (primary surface for in-session merges; runs regardless of model) — `.claude/hooks/agent-merge-on-end.py` calls the Python module via `subprocess.run([sys.executable, "-m", "mahavishnu.core.merge_to_main", ...])`.
2. **`Skill(skill="merge-to-main", args=...)`** (always works, including on MiniMax-modeled sessions).
3. **`/merge-to-main`** (slash command shortcut; **disabled on MiniMax** because the upstream proxy at `https://api.minimax.io/anthropic` does not advertise `SlashCommand` in its tool schema — see `CLAUDE.md` § "Missing built-in tools in MiniMax-modeled sessions").

**Contract (idempotent, resumeable):** If a `.review-state.json` exists in the worktree, resumes from the current stage. Otherwise starts at stage 2.

**Inputs (all optional, inferred from cwd/worktree):**

- `--branch <name>`: the ephemeral branch to merge (default: current branch of cwd)
- `--review <mode>`: `quick` (skip ensemble), `default` (3-agent), `none` (user responsibility; explicit user opt-in required)
- `--no-push`: skip stage 5 (default: push)
- `--no-cleanup`: skip stage 6 (default: cleanup)
- `--from <base>`: override rebase base (default: `origin/main` if remote exists, else `main`)

**Outputs:** Audit log entry (via `get_dev_log_path()`); session-buddy `store_reflection` mirror. Exit codes: 0 (full success), 1 (review failure / not mergeable), 2 (`crackerjack run -v` failure), 3 (rebase conflict), 4 (push divergence), 5 (cleanup failure).

### 4.2 SessionEnd hook

**Location:** `.claude/hooks/agent-merge-on-end.py`

**Contract:** Runs at SessionEnd. If the cwd is a worktree of a known repo (resolved by `git rev-parse --git-dir` pointing into a `.git/worktrees/<id>/` path), and the worktree's branch has commits not yet in `<repo>/<base>`, invokes `python -m mahavishnu.core.merge_to_main`. If the worktree's branch is already merged, no-op.

**Skip conditions:**

- Cwd is empty, unresolvable, or not inside a known Bodai repo worktree.
- `MAHAVISHNU_AUTO_MERGE=0` is set (explicit opt-out).
- Worktree's branch is already fully merged into `<base>`.
- `.review-state.json` marks the worktree as "stage 6 cleanup failed; user must resolve" (sticky failure).

**Default value of `MAHAVISHNU_AUTO_MERGE`: 1 (auto-push and auto-cleanup on).** This deviates from the existing `MAHAVISHNU_AUTO_WORKTREE` opt-in convention (`session-worktree-defaults.md`); the user has explicitly chosen default-on for this workflow because (a) the workflow's failure modes are loud (non-FF push fails the hook), (b) cleanup routes through the existing `prune-merged` classifier (not silent), (c) the user is the operator. The spec does NOT recommend this default for any future workflow; it documents the deviation with rationale.

**Coexistence with `worktree-session-isolation.py`:** Both hooks fire at SessionEnd. Order matters: the existing hook runs first (marks worktree `abandoned`, runs bridge routing); the new hook runs second (decides whether to merge). Both fire regardless of order — the merge hook's "no-op if already merged" check handles the case where the existing hook already cleaned up.

### 4.3 Audit log

**Writer module:** `mahavishnu/core/dev_log.py` (new). Public API:

```python
def write_entry(
    metadata: DevLogMetadata,
    body: str,
    *,
    mirror_to_session_buddy: bool = True,
) -> Path:
    """Append an audit entry to the dev log. Returns the file path written.

    Concurrency: file-lock (fcntl.flock) on append. Atomic rename so a
    crash mid-write leaves the previous log intact.
    """
```

**Storage path:** Resolved by `get_dev_log_path(*path_parts)` in `mahavishnu/core/paths.py` (new helper, mirroring `get_audit_path()` line 137). Default: `STATE_DIR / "dev-log"`. Honors `XDG_STATE_HOME` via the existing platformdirs wiring.

**Frontmatter format:**

```yaml
---
date: 2026-10-03  # date only, no time-of-day (matches repo convention)
branch: fix-ty-errors
ephemeral_branch: fix-ty-errors
repo: mahavishnu
commits_merged: 4
reviewers:
  - agent: python-pro
    verdict: pass
    note: ""
  - agent: pr-review-toolkit-style-reviewer
    verdict: pass
    note: ""
  - agent: test-coverage-review-specialist
    verdict: pass
    note: ""
gate:
  tool: crackerjack
  invocation: run -v
  exit_code: 0
  duration_s: 142
merge:
  strategy: squash
  base: origin/main
  pre_merge_local_base_sha: b116d395
  post_merge_local_base_sha: <new>
push:
  remote: origin
  branch: main
  result: success
  duration_s: 3
cleanup:
  result: pruned-merged
  classifier: merged
session_buddy_reflection_id: <uuid>  # set when mirror succeeds
---
```

**Session-Buddy dual-store:** Each audit entry is mirrored to session-buddy via `mcp__session-buddy__store_reflection(content=entry_yaml, tags=["dev-log", "merge-workflow", repo])`. On mirror success, the audit entry's `session_buddy_reflection_id` is set to the returned UUID. On mirror failure, the field is set to `null` and the failure is logged (the audit entry is still written; session-buddy mirror is best-effort, local file is canonical).

**Retention:** indefinitely, local only. Rotation policy: `audit_orphans.py` extension (see §Verification) prunes entries older than 365 days with `commits_merged == 0` (orphan markers).

### 4.4 Review ensemble contract

**Default ensemble (3 agents):**

- **Agent 1 — domain specialist.** Selected from agents that **actually exist in `.claude/agents/`** today (verified 2026-10-03; 48 agents, deduped and sorted alphabetically): `accessibility-auditor`, `agent-creation-specialist`, `akosha-specialist`, `anthropic-claude-specialist`, `api-security-specialist`, `architecture-council`, `authentication-specialist`, `claude-environment-auditor`, `critical-audit-specialist`, `css-architect`, `data-pipeline-engineer`, `data-retention-specialist`, `database-operations-specialist`, `devops-troubleshooter`, `docker-specialist`, `documentation-review-specialist`, `documentation-specialist`, `grpc-specialist`, `helm-specialist`, `jinja2-template-designer`, `mahavishnu-orchestrator`, `mahavishnu-specialist`, `mcp-integration-expert`, `mermaid-expert`, `observability-incident-lead`, `oneiric-specialist`, `openai-specialist`, `orchestration-specialist`, `performance-review-specialist`, `playwright-specialist`, `postgresql-specialist`, `privacy-officer`, `pycharm-plugin-creator`, `pyo3-specialist`, `pytest-hypothesis-specialist`, `python-pro`, `qa-strategist`, `redis-specialist`, `reference-builder`, `rust-pro`, `sqlite-specialist`, `starlette-specialist`, `terraform-specialist`, `test-coverage-review-specialist`, `tui-designer`, `vector-database-specialist`, `vitest-specialist`, `websocket-specialist`. Selection rule: worker specifies `--review-domain <agent-name>`; default is `python-pro`.

- **Agent 2 — code-quality specialist.** Always `code-reviewer` (use whichever code-reviewer is available — `critical-audit-specialist` in this repo, or `pr-review-toolkit:code-reviewer` if the plugin is installed and discoverable).

- **Agent 3 — random generalist.** Drawn uniformly from a small in-repo pool of `[performance-review-specialist, test-coverage-review-specialist, critical-audit-specialist, documentation-review-specialist, qa-strategist, observability-incident-lead, architecture-council]`. Each invocation re-shuffles. **No namespaced agents** (`mycelium-core:*`, `pr-review-toolkit:*`) are required for v1; if the user installs those plugins later, the pool can grow via a config file.

**Invocation protocol:** Each agent is invoked via `mcp__mahavishnu__pool_route_execute` (NOT Claude Code's `Agent(...)` tool). Reasons: (a) routes through the orchestrator's pool (testable via existing pool integration tests), (b) returns a structured response the slash command can parse, (c) is observable in Akosha / Mahavishnu dashboards. The prompt template asks the agent to end its response with a marker the parser recognizes:

```
<verdict>
  decision: pass | needs_adjustment | block
  note: <one-paragraph explanation>
</verdict>
```

The Python module parses this block from the agent's response. If the block is missing or malformed, the verdict is `block` (fail-loud). The module exits with code `1` (review failure / not mergeable), records the parse failure in the audit log's `gate.reviewers` array, and emits a stderr message: `"Hook output: reviewer <agent-name> returned malformed verdict; merge blocked. Re-run with --review default to retry."`.

**Verdict rule order** (priority high to low, first match wins):

1. **Any `block` verdict → block the merge.** No further rules apply.
2. **≥2 of 3 verdicts are `pass` → proceed.**
3. **Otherwise → iterate** (worker fixes, re-enters stage 2). Covers the cases where all 3 are `needs_adjustment`, or 1 `pass` + 2 `needs_adjustment`.

**Cross-session resume schema (`.review-state.json`):** Written at the worktree root on every stage transition. JSON shape:

```json
{
  "schema_version": 1,
  "ephemeral_branch": "fix-ty-errors",
  "base": "origin/main",
  "pre_rebase_base_sha": "b116d395",
  "stages_completed": ["stage_1_worktree", "stage_2_review"],
  "current_stage": "stage_3_gate",
  "stage_failed": null,
  "reviewers_invoked": [
    {"agent": "python-pro", "verdict": "pass", "timestamp": "2026-10-03T15:32:11Z"}
  ],
  "stage_2_started_at": "2026-10-03T15:32:00Z",
  "stage_2_completed_at": "2026-10-03T15:32:11Z",
  "audit_log_path": "/Users/les/.local/state/mahavishnu/dev-log/2026-10-03-fix-ty-errors.md",
  "session_buddy_reflection_id": null
}
```

Idempotency: `stages_completed` is append-only. Resume reads `current_stage` to pick up. Corrupt JSON → fallback to stage 2 (per REQ-014). `session_buddy_reflection_id` is `null` until the session-buddy mirror succeeds.

**Quick mode (`--review quick`):** Skips the ensemble. Allowed only when **all** of:
- All changed paths match `^.*\.(md|txt|rst|yaml|yml|toml|json)$` AND
- No path contains `src/`, `tests/`, `migrations/`, or `settings/`.

Detection logic: `git diff --name-only <base>...HEAD` filtered by the regex `^.*\.(md|txt|rst|yaml|yml|toml|json)$`, with denylist `^(src|tests|migrations|settings)/`. `crackerjack run -v` still runs.

**Override (`--review none`):** Skips the ensemble entirely; user responsibility. `crackerjack run -v` still runs. Requires the user to explicitly pass `--review none`; not inferred.

### 4.5 Merge strategy

- **Branch lifetime:** created at `git worktree add` time, deleted at `mahavishnu worktree prune-merged` time. Never pushed to a remote.
- **Squash, not `git update-ref`:** the worker's N intermediate commits become 1 commit on `main`. Rationale for NOT using `git update-ref refs/heads/main <branch>` (the existing push-memory pattern): the worker's branch has intermediate commits ("wip", "fix typo", "address feedback") that are not logical units. Squash gives one reviewable commit per piece of work with a single semantic message.
- **Rebase before merge + SHA re-verify:** `git rebase <base>` runs first. After rebase, re-verify `<base>` SHA hasn't moved (`git rev-parse <base>` compared against the pre-rebase SHA stored in `.review-state.json`). If `<base>` moved during rebase, abort the squash and start over (the merged result would not be fast-forward of the new base).
- **Merge commit style:** `git merge --squash <branch>` stages changes but does NOT auto-commit. The Python module writes the final commit message via a prompt template that summarizes the diff (first line ≤ 72 chars, references the ephemeral branch, includes the worker's task_id if available).
- **Local-only between stages 4 and 5:** the squash-commit lands on local `main`. Stage 5 pushes local `main` to `origin/main`. If push fails (e.g. divergence), local `main` is ahead of `origin/main` until the user resolves manually.

### 4.6 Push rule

**Documented in:** `.claude/decisions/2026-10-03-main-autopush.md` (governance amendment superseding the relevant clause of `feedback-bodai-push-is-user-controlled`). The decision doc is the source of truth; this section is a summary.

**Auto-push scope:** `git push origin main`, only on `main`, only after a successful squash-merge in stages 1–4, only by the Python module invoked from the SessionEnd hook or the `/merge-to-main` slash command.

**What is NOT auto-pushed:**

- Ephemeral branches (`fix-ty-errors`, `agent-<short>`, etc.)
- Tags (e.g. `v0.32.0`)
- Any branch other than `main`
- Any remote other than `origin`
- Force-pushes of any kind

**Divergence handling:** If `git push origin main` returns a non-fast-forward error, the Python module:
1. Captures the error verbatim.
2. Writes the failure to the audit log (with `push.result: "diverged"`).
3. Surfaces the failure via stderr (e.g. `Hook output: origin/main has diverged; local=a1b2c3d remote=e4f6g8h. Pull + resolve + retry, or rebase your worktree on origin/main and re-merge.`).
4. Does **not** retry, force-push, rebase, or merge. Manual resolution.

**Recovery options** (documented for the user; not automated):
- `git fetch && git rebase origin/main && git push origin main` (rewrites local commits as fast-forward onto origin).
- `git fetch && git reset --hard origin/main` (discards local commits; **loses the squash work**; user must re-run stages 1–4).

## Failure Modes

| Mode | Detection | Handling |
|---|---|---|
| **Remote `main` has diverged** | `git push` returns non-fast-forward | Module fails loudly via stderr; user rebase + retry. No force-push. |
| **`<base>` moved during rebase** | SHA comparison fails against `.review-state.json` pre-rebase SHA | Abort squash; rebase again on the new base; re-verify. |
| **Concurrent merges** (two sessions both squash into local `main`, both push) | git's ref lock on merge; second push hits FF check and fails | First succeeds; second surfaces divergence via stderr. User resolves manually. No data loss. |
| **No remote configured** | `git remote` returns empty | Push is a no-op; module logs `push.result: "no_remote"` and exits 0. |
| **Push auth/network failure** | `git push` returns non-zero for any reason other than FF | Module exits non-zero; audit log records `push.result: "error:<message>"`. |
| **GitHub branch protection rejects direct push to `main`** | `git push` returns HTTP 403 with protection error | Module surfaces the message verbatim; user disables protection or configures a bypass. |
| **Worktree dirty state at merge time** | `git status --porcelain` returns non-empty in the worktree | Module refuses to merge; user commits/stashes the uncommitted work. |
| **Pre-merge `crackerjack run -v` failure** | Module detects non-zero exit | Module refuses to merge; worker iterates. |
| **Session ends mid-review** | `.review-state.json` exists in the worktree | Next session reads it; module resumes from the saved stage. |
| **Cleanup fails** (worktree's branch is `not_merged` per existing classifier) | `mahavishnu worktree prune-merged` refuses | Module surfaces classifier output; user resolves manually. Sticky marker in `.review-state.json` to prevent re-attempt. |
| **Branch-name collision** (two sessions both pick `fix-ty-errors`) | `git worktree add` fails | Session retries with `<branch>-<short>` suffix. |
| **Reviewer returns malformed verdict** | Parsing fails on `<verdict>` block | Verdict recorded as `block`; merge blocked. |
| **MAHAVISHNU_AUTO_MERGE=0 set** | Env-var check at SessionEnd hook | Hook no-ops; user must invoke `/merge-to-main` manually. |
| **Cwd is `~`, `/tmp`, or unresolvable** | `git rev-parse --git-dir` fails | Hook returns not-a-worktree, no-op. |

## Requirements

Per the repo's audit-script requirement, every plan-time deliverable maps to a `REQ-NNN` ID.

| ID | Requirement | Verifiable by |
|---|---|---|
| **REQ-001** | Ephemeral branches are never pushed to a remote | `git ls-remote origin` over a week shows zero new ephemeral branches |
| **REQ-002** | `mahavishnu/core/paths.py::get_dev_log_path(*path_parts)` exists and honors `XDG_STATE_HOME` | CI guard test pins the helper |
| **REQ-003** | `mahavishnu/core/dev_log.py::write_entry()` writes with file-lock + atomic rename, mirrors to session-buddy | Unit test for concurrency; integration test for session-buddy mirror |
| **REQ-004** | `.claude/commands/merge-to-main.md` exists with required frontmatter + body that calls `mahavishnu.core.merge_to_main` | `python scripts/agent_metadata_audit.py` + `python scripts/tool_frontmatter_validator.py` |
| **REQ-005** | `.claude/hooks/agent-merge-on-end.py` exists and fires at SessionEnd per the existing `_hook_io.py` contract | Manual test: end a session in a worktree, observe the hook runs |
| **REQ-006** | `.claude/settings.json` wires the new hook into the SessionEnd array, **appended after the existing `worktree-session-isolation.py` entry** (the existing hook runs first, this new hook runs second) | `cat .claude/settings.json | jq '.hooks.SessionEnd'` shows the new entry at position ≥ 1 of the array |
| **REQ-007** | `.claude/decisions/2026-10-03-main-autopush.md` exists and supersedes the relevant clause of `feedback-bodai-push-is-user-controlled` | Cross-link check |
| **REQ-008** | `.claude/decisions/2026-10-03-trunk-based-agent-review.md` exists | File exists |
| **REQ-009** | Session-buddy dual-store: every audit entry has a `session_buddy_reflection_id` field | `git log --oneline origin/main..main` for-each entry |
| **REQ-010** | `MAHAVISHNU_AUTO_MERGE` default is 1 (on) per user choice | Source inspection + `~/.zshenv` has explicit `export MAHAVISHNU_AUTO_MERGE=1` |
| **REQ-011** | Pre-deploy gate: every merge commit on `main` has a corresponding audit log entry | `audit_orphans.py` extension (new script); CI smoke runs it |
| **REQ-012** | SessionEnd cleanup routes through `mahavishnu worktree prune-merged` (NOT silent removal) | Code inspection of `mahavishnu/core/merge_to_main.py` |
| **REQ-013** | The merge path invokes `crackerjack run -v` (NEVER `-p`); any non-zero exit blocks the merge (exit code 2) | Code inspection + CI guard test that asserts the invocation string starts with `crackerjack run -v ` and does not contain `-p` |
| **REQ-014** | The audit-log writer handles corrupt `.review-state.json` gracefully (fallback to stage 2) | Unit test with malformed JSON |

## Integration Contract

Per `.claude/decisions/wire-up-contract.md`, every deliverable has the following block. One block per deliverable.

### Deliverable: `mahavishnu/core/dev_log.py` (audit-log writer)

- **Triggered from:** `merge_to_main.py::run_pipeline()` after stage 5 (push) or stage 4 failure.
- **Returns to / updates:** Writes YAML frontmatter + body to `<get_dev_log_path()>/<YYYY-MM-DD>-<branch-slug>.md`. Calls `mcp__session-buddy__store_reflection()` for dual-store.
- **Demonstrable by:** Run `python -c "from mahavishnu.core.dev_log import write_entry; from pathlib import Path; print(write_entry(metadata={'date': '2026-10-03', 'branch': 'test'}, body='test'))"` and observe a file created with the expected frontmatter.
- **Rollback signal:** Writer failure is logged via `oneiric.logging`; merge continues (local file is canonical).
- **Observability added:** Each write emits a `dev_log.entry_written` event on `mahavisd.events` (existing Redis Streams topic) with the entry ID; Akosha picks up via existing patterns.

### Deliverable: `mahavishnu/core/merge_to_main.py` (the orchestration module)

- **Triggered from:** `.claude/commands/merge-to-main.md` (slash command body); `.claude/hooks/agent-merge-on-end.py` (SessionEnd hook).
- **Returns to / updates:** Modifies local `main`, pushes to `origin/main`, removes the worktree, writes the audit log. Idempotent: resumes from `.review-state.json` if present.
- **Demonstrable by:** From a worktree, run `python -m mahavishnu.core.merge_to_main --review quick --branch <name>`; observe squash-merge to `main`, push to `origin/main`, worktree removed, audit log entry written.
- **Rollback signal:** Each stage writes a `.review-state.json` marker; if any stage fails, the marker records the failed stage for the next session to resume from.
- **Observability added:** Each stage transition emits a `merge_workflow.<stage>` event on `mahavisd.events` (e.g. `merge_workflow.stage_4_started`, `merge_workflow.stage_5_completed`); Akosha picks up via existing patterns.

### Deliverable: `.claude/hooks/agent-merge-on-end.py` (SessionEnd hook)

- **Triggered from:** Claude Code SessionEnd event per `.claude/settings.json` SessionEnd array.
- **Returns to / updates:** Invokes `python -m mahavishnu.core.merge_to_main` when conditions met; no-ops otherwise.
- **Demonstrable by:** End a session inside a worktree with unmerged commits, observe the hook stdout/stderr showing the merge invocation; audit log entry exists.
- **Rollback signal:** Hook failures exit non-zero; Claude Code surfaces them as a post-session summary; user retries or resolves manually.
- **Observability added:** Each hook invocation emits a `merge_workflow.session_end_hook_fired` event on `mahavisd.events`; merged-count vs. skipped-count tracked per session.

### Deliverable: `.claude/commands/merge-to-main.md` (slash command)

- **Triggered from:** User typing `/merge-to-main` (on native Anthropic models) or `Skill(skill="merge-to-main", args={...})` (on MiniMax or any model).
- **Returns to / updates:** Invokes `python -m mahavishnu.core.merge_to_main` with the user's args.
- **Demonstrable by:** From a worktree, run `Skill(skill="merge-to-main", args={"--review": "quick"})`; observe the same outcome as the SessionEnd hook case.
- **Rollback signal:** Exit codes per the Python module (1=review, 2=crackerjack, 3=rebase, 4=push, 5=cleanup); user reads the code and resolves.
- **Observability added:** None (the underlying Python module's events cover this).

### Deliverable: `.claude/decisions/2026-10-03-main-autopush.md` (governance amendment)

- **Triggered from:** This spec's creation; co-delivered with REQ-007.
- **Returns to / updates:** Documents the auto-push rule with cross-links to `feedback-bodai-push-is-user-controlled` (the rule it amends).
- **Demonstrable by:** `cat .claude/decisions/2026-10-03-main-autopush.md` shows the rule, the scope, the deviation rationale, and the cross-link.
- **Rollback signal:** The decision doc can be superseded by a later decision (`superseded_by:` field).
- **Observability added:** The audit log's `push.result` field is the runtime observable for whether the auto-push succeeded; Akosha can detect divergence over time.

### Deliverable: `.claude/decisions/2026-10-03-trunk-based-agent-review.md` (workflow doc)

- **Triggered from:** This spec's creation; co-delivered with REQ-008.
- **Returns to / updates:** Documents the workflow for future readers in this repo.
- **Demonstrable by:** File exists with the workflow steps and cross-references.
- **Rollback signal:** N/A (documentation).
- **Observability added:** None directly.

### Deliverable: `~/.zshenv` export (local config)

- **Triggered from:** This spec's creation; co-delivered with REQ-010.
- **Returns to / updates:** Adds `export MAHAVISHNU_AUTO_MERGE=1` to `~/.zshenv`.
- **Demonstrable by:** `grep MAHAVISHNU_AUTO_MERGE ~/.zshenv` shows the export.
- **Rollback signal:** User removes the line.
- **Observability added:** None directly.

## Memory + CLAUDE.md Edits

### Memory

**Update `feedback-bodai-push-is-user-controlled`** to add a **cross-link** (NOT an inline exception) pointing to the new decision doc:

> **Cross-reference (2026-10-03)**: The exception for `origin/main` after a successful squash-merge lives in `.claude/decisions/2026-10-03-main-autopush.md`. All other push types (tags, force-push, non-origin remotes) remain user-controlled per this memory.

**Create new memory `feedback-bodai-merge-workflow.md`** capturing the workflow contract (which CLAUDE.md readers can use to know what the slash command and SessionEnd hook do). Dual-store: also `mcp__session-buddy__store_reflection(content=..., tags=["feedback", "merge-workflow"])`.

**Add entry to the user-level `MEMORY.md` index at `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/MEMORY.md`** for `feedback-bodai-merge-workflow.md`. This is the Claude Code auto-memory index (NOT a project-level file — there is no project-level `MEMORY.md`; the index lives in the per-project user-state location).

### CLAUDE.md

**Update user-level `~/.claude/CLAUDE.md`** (the "Worktree location preference" block) to add a "Dev workflow" subsection stating the 7-stage workflow in two paragraphs.

**Update `~/Projects/mahavishnu/CLAUDE.md`** (the "Tool Preferences" block) to note that the merge command lives in this repo. The other 5 core repos (`akosha`, `session-buddy`, `crackerjack`, `oneiric`, `mcp-common`) inherit the convention without per-repo edits.

### Decisions

**Create `.claude/decisions/2026-10-03-main-autopush.md`** (REQ-007). Contents: rule, scope, deviation rationale, cross-link to `feedback-bodai-push-is-user-controlled`, threat model (divergence, accidental force-push, replay).

**Create `.claude/decisions/2026-10-03-trunk-based-agent-review.md`** (REQ-008). Contents: workflow steps, links to this spec, links to the components.

## Verification

**Smoke test (in a real worktree):**

1. Create a worktree at `~/.local/state/mahavishnu/worktrees/mahavishnu/test-merge` with a trivial change (typo fix in a comment).
2. Set `MAHAVISHNU_AUTO_MERGE=1` in the shell (matches `~/.zshenv`).
3. End the session; the hook invokes `merge-to-main`.
5. Verify:
   - `git log --oneline origin/main..main` returns 0 after merge + push.
   - Worktree removed; branch deleted.
   - Audit log entry exists at `<get_dev_log_path()>/<YYYY-MM-DD>-test-merge.md`.
   - Session-buddy reflection created with `merge-workflow` tag.
6. Repeat with `--review default` to exercise the ensemble.

**Failure-mode tests:**

1. **Diverged remote:** manually move `origin/main` forward (via a dummy commit on a throwaway branch and `git push origin <throwaway>:main` on a different machine or via `gh api`), then run `merge-to-main`. Verify module exits non-zero (code 4), no force-push, audit log records `diverged`.
2. **Pre-merge `crackerjack run -v` failure:** introduce a known-failing change, run `merge-to-main`. Verify module refuses to merge (exit 2).
3. **Concurrent merges:** run two `Agent(...)` calls in parallel that both squash into local `main`. Use a deterministic test fixture (a temp dir with a manually-held git ref lock) instead of timing races. Verify one succeeds, one fails on push with FF error.
4. **Session-end mid-review:** start a `--review default`, end the session mid-ensemble. Start a new session, navigate to the worktree, run `merge-to-main`. Verify it resumes from the saved stage.

**Cross-repo consistency:**

1. Create a worktree in `~/Projects/akosha/`, run `merge-to-main`. Verify the hook fires the same way.
2. Same in `~/Projects/session-buddy/`. Per the prior session-buddy follow-up, `session_buddy/core/paths.py::get_worktree_base_path()` already resolves to the same `~/.local/state/mahavishnu/worktrees` path.

**Pre-deploy gate (CI, REQ-014):** `scripts/audit_devlog.py` (new) runs in CI, asserts every merge commit on `main` produced in the last 90 days has a corresponding audit log entry. Failure exits non-zero.

**MiniMax compatibility test (manual):** From a MiniMax-modeled session, run `Skill(skill="merge-to-main", args={"--review": "quick"})` on a test worktree; verify it works. Confirm that typing `/merge-to-main` does **NOT** work in the same session (proxy doesn't advertise `SlashCommand`).

## Plans Derived From This Spec

Per the round-1 review (plan-readiness agent's recommendation), this spec ships **3 plans + 1 governance plan**, in dependency order:

- **Plan 1 — `dev_log` writer + `get_dev_log_path()` helper** (REQ-002, REQ-003). Foundation module, unit-testable, single Integration Contract.
- **Plan 2 — `merge_to_main` orchestration module + slash command** (REQ-004, REQ-009, REQ-011, REQ-013, REQ-014). Includes the markdown `.claude/commands/merge-to-main.md`, the `mahavishnu/core/merge_to_main.py` Python module, `.review-state.json` schema, and the 5 exit codes. No SessionEnd hook yet.
- **Plan 3 — SessionEnd hook `agent-merge-on-end.py`** (REQ-005, REQ-006, REQ-012). Wires into `.claude/settings.json`. Coexists with `worktree-session-isolation.py` (existing SessionEnd handler runs first, this one runs second). Default `MAHAVISHNU_AUTO_MERGE=1` per user choice.
- **Plan 4 — Governance amendments + memory + CLAUDE.md + decision docs + local env var** (REQ-007, REQ-008, REQ-010). Co-delivered per `wire-up-contract.md` §3. Includes: new decision doc, new workflow doc, memory update + dual-store, `~/.zshenv` export, `MEMORY.md` index entry, `audit_orphans.py` extension (for REQ-014/REQ-011).

Each plan is independently testable with a single Integration Contract deliverable.

## Open Questions

1. **Ensemble cost.** Three-agent review costs tokens. Quick mode covers the trivial case. The 3-agent overhead is amortized over the cost of the worker's actual implementation; if a piece of work is 1 turn of agent work + 3 turns of review, that's 4× the agent cost. Acceptable for v1 given the cleanup benefit; revisit if token cost is a real constraint.
2. **Audit log mirror reliability.** The session-buddy reflection mirror is best-effort. If the network is down or session-buddy is unreachable, the merge still succeeds (local file is canonical). Trade-off: the mirror can be backfilled later from the local file. Acceptable for v1.
3. **Cherry-pick from a merged commit.** If a user wants to revert a single squash commit, they use `git revert <sha>` (squash commits revert cleanly). Not solved in v1; documented in audit log.
4. **`auto-coordinate` skill interaction.** The existing `auto-coordinate` skill may auto-link tasks to git branches; it needs to learn that ephemeral branches aren't persistent. Out of scope for v1; flag in the PR for `auto-coordinate` maintainers.

## Appendix: Alternatives Considered

| Alternative | Why not v1 |
|---|---|
| **GitHub PRs with auto-delete** (`gh pr merge --delete-branch`) | Still async-by-default; still heavyweight; still requires GitHub-shaped review UI. Same "PR gate, just smaller" complaint applies. |
| **Stacked diffs (`git-stack`, `gh-stack`)** | Cleaner PR model for layered work, but no current user familiarity. Higher learning curve; revisit if "lots of layered PRs" becomes a real workflow. |
| **Trunk-based with feature flags** | Eliminates branches but eliminates PR-shaped review too. Only works for solo dev with low-stakes surface. |
| **Force-push with safety check** | Never. `feedback-bodai-push-is-user-controlled` exists for a reason. |
| **Inline exception clause in the push memory** | Governance-by-footnote; reviewers flagged as creating a contradiction future-me will trip over. Replaced with new decision doc. |
| **Single combined implementation plan** | Harder to roll back partial failure mid-implementation. Replaced with 3 + 1 plans per plan-readiness review. |

## Cross-references

- `docs/specs/2026-09-29-task-system-design.md` — the Task system uses ephemeral branches for `auto-coordinate`-linked work; this spec is compatible.
- `.claude/decisions/worktree-cleanup-policy.md` — tier rubric and `LOCKED-live`/`LOCKED-orphan` semantics used by stage 6 cleanup.
- `.claude/decisions/worktree-autoremove-policy.md` — Rule 5 (SessionEnd automation prohibition); the spec's default `MAHAVISHNU_AUTO_MERGE=1` deviates from the spirit of this rule. **The new governance decision** `.claude/decisions/2026-10-03-main-autopush.md` documents the deviation.
- `.claude/decisions/wire-up-contract.md` — Integration Contract requirement (per deliverable).
- `.claude/decisions/mcp-backend-wiring-discipline.md` — applies to SessionEnd hook if it touches MCP.
- `feedback-bodai-push-is-user-controlled` — the rule being cross-linked (NOT amended inline).
- `feedback-worktree-update-ref-drops-parallel-commits` — stage-4's rebase-before-merge + SHA-reverify is the inverse of this anti-pattern.
- `feedback-bodai-atomic-commit-recurring-fixes` — squash-merge aligns with this rule (one logical commit per piece of work).
- `feedback-mcp-common-version-bump-is-user` — stage-7 (publish) preserves this rule.
- `feedback-memories-must-be-dual-stored` — new memory `feedback-bodai-merge-workflow.md` is dual-stored.
- `crackerjack-cli-run-subcommand` — the user's release form is `-p`; bare `crackerjack run -v` is the merge-gate invocation.
