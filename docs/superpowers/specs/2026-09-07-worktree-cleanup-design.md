---
title: Bodai Worktree Cleanup Policy — Design Spec
date: 2026-09-07
last_reviewed: 2026-09-07
status: draft
role: implementation
topic: worktree-cleanup
author: "brainstormed 2026-09-07 (revised after multi-agent review: security, audit, DX, lateral)"
blocks_on: []
blocks: []
supersedes: null
related:
  - "../../.claude/decisions/session-worktree-defaults.md (Rule 2: never auto-remove)"
  - "../../.claude/decisions/worktree-autoremove-policy.md (Rule 2 amendment: prune-merged CLI; Rule 4: --force-reason for dirty merged)"
  - "../../.claude/decisions/worktree-autoremove-v4-followup.md (deferred automation; not a permission grant)"
  - "../../.claude/decisions/2026-08-28-cross-repo-fanout-cwd-isolation.md (cross-repo fanout + manual cleanup of /tmp/<branch>)"
  - "../../.claude/decisions/wire-up-contract.md (Integration Contract template; one contract per artifact)"
  - "../../.claude/decisions/removed-scripts.md (drift-bundling risk: do NOT duplicate prune-merged classifier)"
  - "../../.claude/decisions/bodai-pre-1.0-merge-policy.md (Bodai components merge directly to main pre-1.0)"
  - "../../adr/ (no ADR specific to worktrees; rules live in decisions/)"
target_repo: mahavishnu
scope_note: |
  Three artifacts: (a) `.claude/decisions/worktree-cleanup-policy.md` codifying the 2026-09-07
  sweep findings (tier rubric, salvage procedure, lock + live-PID semantics, agent-dispatch reap
  rule, cross-repo plan-orphan rule); (b) `mahavishnu worktree scan` CLI subcommand that loads
  `settings/ecosystem.yaml` via the existing bootstrap resolver, classifies each worktree, and
  emits a tier-grouped report (text or JSON); (c) `.claude/skills/bodai-worktree-cleanup/SKILL.md`
  skill wrapping the CLI. Scan-and-report only — no auto-removal. The full-auto-removal piece
  stays deferred per `worktree-autoremove-v4-followup.md` (gated on `RemoteWorktreeProvider`
  production-ready).
trigger: 2026-09-07 cleanup removed 86 of 117 extra worktrees across 20 Bodai repos. Existing
  policy (`worktree-autoremove-policy.md`) covers only `prune-merged` clean-removal. The 86
  removals required a tier rubric + salvage procedure + lock + live-PID handling that no
  current decision codified.
---

# Bodai Worktree Cleanup Policy — Design Spec

## Context

The 2026-09-07 sweep of 31 active Bodai repos found 117 extra worktrees (108 non-main in 20
of 31 repos; zero `[gone]` branches). 86 were removed, 3 were preserved (2 <9d `agent-*`
candidates + 1 `agent-a894dd931068d8836` locked by live Claude PID 74005). The cleanup
made tier-rubric + salvage + lock + live-PID decisions in-line, with no existing decision
documenting any of them.

Five existing decisions touch worktree policy:

- `session-worktree-defaults.md` (Rule 2: never auto-remove worktrees)
- `worktree-autoremove-policy.md` (Rule 2 amendment: only `mahavishnu worktree prune-merged`
  may remove, and only `merged`-classified, clean entries; Rule 4: `--force-reason` for dirty merged)
- `worktree-autoremove-v4-followup.md` (draft, forward-looking; NOT a permission grant)
- `2026-08-28-cross-repo-fanout-cwd-isolation.md` (cross-repo fanout cleanup of `/tmp/<branch>`)
- `mahavishnu-tool-preference-policy.md` (unrelated; tool-steering, not worktrees)

None of these address today's findings: agent-dispatch reap rule, cross-repo plan-orphan
rule, lock + live-PID semantics, dirty-worktree salvage procedure, tier rubric. This spec
adds the policy doc + an opt-in scan-and-report CLI + a skill wrapper that operationalizes it.

**Manifest source**: this spec's CLI loads `settings/ecosystem.yaml` via
`mahavishnu/core/bootstrap.py:_resolve_repos_path()`. Note: that function signature
is `_resolve_repos_path(app: Any, logger: Any) -> tuple[Path, bool]` — it requires
an `app` instance with `app.config.repos_path`. The CLI's options are:
(a) instantiate a lightweight `MahavishnuApp()` shim (cost: full config init, ~200ms),
(b) refactor bootstrap to expose a no-arg `_resolve_repos_path_from_settings()`,
(c) read `settings/mahavishnu.yaml:repos_path` directly via `oneiric.config.load_config()`
+ `Config().get("repos_path")`. The CLI tests pin the chosen approach.

The canonical manifest is `settings/ecosystem.yaml` (pinned in `settings/mahavishnu.yaml:repos_path`);
`settings/repos.yaml` is the runtime fallback and declares itself deprecated;
`BODAI_REPO_REGISTRY.md` is human-readable prose and is NOT a runtime fallback.

The scan is opt-in. The CLI does **not** remove anything — it produces a tier-grouped report
for human review. Removal continues to flow through the existing `mahavishnu worktree
prune-merged` (Tier A + merged classification) or direct `git worktree remove` (per-tier rules
in the new decision doc).

## Goals

1. **Codify the 2026-09-07 sweep's findings** as a sibling decision doc
   (`.claude/decisions/worktree-cleanup-policy.md`) covering: tier rubric (with explicit
   boundary inclusivity), salvage procedure (with path-safety rules), lock + live-PID
   semantics (`-f -f` requirement + PID-reuse identity check), agent-dispatch reap rule,
   cross-repo plan-orphan rule.

2. **Add `mahavishnu worktree scan`** subcommand to the existing `mahavishnu worktree` CLI
   (file: `mahavishnu/worktree_cli.py`). Walks repos via the bootstrap resolver,
   classifies each worktree, emits a tier-grouped text or JSON report. Reuses
   `mahavishnu/core/worktree_prune_merged.py` — specifically imports
   `classify_merge_status(worktree_path, *, main_branch, master_fallback)` returning
   `Literal["merged","not_merged","undetermined"]` — for the merged tier check. New code
   in `mahavishnu/core/worktree_scan.py` handles the other tiers (recent, dispatch-leftover,
   plan-orphan, locked, dirty).

3. **Add `.claude/skills/bodai-worktree-cleanup/SKILL.md`** skill that wraps the CLI. Trigger
   phrases: "scan worktrees", "find stale worktrees", "audit bodai worktrees" (in a
   worktree context). Skill body is thin: invokes the CLI, interprets the output, points
   to the decision doc for the policy rules.

## Non-Goals

- **Auto-removal.** The CLI emits a report; user invokes removal. This is consistent with
  `worktree-autoremove-policy.md` Rule 2 amendment (only explicit user CLI invocation). No
  SessionEnd hook, no cron wrapper, no hidden automation.
- **Full automation per `worktree-autoremove-v4-followup.md`.** The followup requires
  `RemoteWorktreeProvider` production-ready (Phase 1 dependency in v4 §18). When that lands,
  this spec can be augmented via a followup spec — but for now, scan-and-report only.
- **Cross-ecosystem plugin distribution.** Decision lives in mahavishnu per
  `bodai-mcp-routing-pattern.md` (each Bodai project ships its own `.mcp.json`). Other
  Bodai repos can opt in by reading the decision doc; the skill lives in
  `mahavishnu/.claude/skills/` and ships with mahavishnu's Claude Code config.
- **Editing existing worktree decisions.** The five existing decisions stay intact. The
  new doc is additive; cross-references are bidirectional (the implementer adds a "See
  also: worktree-cleanup-policy.md" back-link to each existing decision in the same commit).
- **Removing existing skill `commit-commands:clean_gone`** — different scope (branches,
  not worktrees). The new skill complements, doesn't replace.
- **`BODAI_REPO_REGISTRY.md` as a machine-parseable manifest.** It's prose; the CLI does
  not parse it. Use `settings/ecosystem.yaml` (canonical) → `settings/repos.yaml` (fallback).

## Architecture

Three artifacts land in `/Users/les/Projects/mahavishnu/`:

```
mahavishnu/
├── .claude/decisions/
│   └── worktree-cleanup-policy.md          # NEW (sibling to worktree-autoremove-policy.md)
├── mahavishnu/
│   ├── worktree_cli.py                     # EXTENDS (adds `scan` subcommand)
│   └── core/
│       └── worktree_scan.py                # NEW: classifier + report formatter
└── .claude/skills/bodai-worktree-cleanup/
└── .claude/skills/bodai-worktree-cleanup/
    ├── SKILL.md                            # NEW: trigger phrases + body
    └── scripts/
        └── cli_scan.py                     # NEW: thin wrapper, calls mahavishnu worktree scan
```

**Flow** (3-pass scan pipeline):

1. **Pass 1 — collect**: for each repo from the bootstrap resolver, run `git worktree list --porcelain`
   + `git -C <wt> log -1 --format=%ct` (age) + `git status --short` (unconditional, not gated on
   `--include-dirty`, because Tier A's removal action depends on it). Capture: `(repo, worktree,
   age_days, branch, is_dirty, is_locked, lock_pid)`.
2. **Pass 2 — group cross-repo orphans**: for each worktree, check if the branch matches a
   `PLAN_ORPHAN_PATTERNS` regex AND a same-date signature exists in ≥ 2 repos. If so,
   assign `tier_x` (cross-repo plan-orphan); otherwise skip this pass.
3. **Pass 3 — classify per repo**: call `classify_worktree(...)` with the grouped data and
   emit the report.

**Subprocess safety**: the new `worktree_scan.py` MUST use
`subprocess.run([...], shell=False, ...)` with list-form args. Do NOT reuse
`worktree_prune_merged.py:_run_git` directly — its hard-coded `timeout=5` (line 86)
is incompatible with the spec's 30s per-repo wall-clock cap (A24). Instead,
`worktree_scan.py` defines its own `_run_git_scanned(path, *args, timeout=...)` and
`_run_ps(...)` siblings with explicit timeouts. PID validated as `^[0-9]+$` before the
`ps` call. Single place to enforce subprocess attack surface within the scan path.

**Existing utilities to leverage, NOT re-implement** (per `removed-scripts.md` drift-bundling rule):
- `mahavishnu/core/paths.py::get_worktree_base_path()` (line 153-182) — resolves
  `MAHAVISHNU_WORKTREE_BASE_PATH` (canonical) or `MAHAVISHNU_AUTO_WORKTREE_ROOT` (legacy alias, guarded) → defaults to `~/worktrees`
- `mahavishnu/core/validators.py::PathValidator.validate_path()` (line 122) — full path traversal + allowed-base-dir containment
- `mahavishnu/core/worktree_validation.py::WorktreePathValidator` — CWE-22/CWE-114/CWE-170 protection, `DANGER_PATH_COMPONENTS` and `SHELL_METACHARACTERS`
- `mahavishnu/core/bootstrap.py::_validate_path()` (line 90) — path traversal + allowed-base-dir containment
- `mahavishnu/core/worktree_prune_merged.py::classify_merge_status()` (line 91-129) — returns `str` ("merged"|"not_merged"|"undetermined"), import-side cast to `Literal[...]`

The new code only needs ONE genuinely-novel helper: `safe_worktree_name(name: str) -> str`
that enforces character class `[A-Za-z0-9._-]` + rejects `.`/`..`/empty. All other
sanitization is delegated to existing helpers. A guard test `TestNoDuplicateHelpers`
asserts `worktree_scan.py` does not redefine `validate_path`, `get_worktree_base_path`,
or `_validate_path`.

## Design

### Decision doc: `.claude/decisions/worktree-cleanup-policy.md`

Same shape as `worktree-autoremove-policy.md`. Body sections:

**§ Decision rule** — the tier rubric. First-match-wins by row order:

| Tier | Condition (explicit boundaries) | Removal action |
|---|---|---|
| **A-merged** | `classify_merge_status(worktree_path) == "merged"` AND `is_dirty == False` | `git worktree remove` (no `--force`) — but only via the existing `mahavishnu worktree prune-merged` CLI, which already enforces multi-signal classification |
| **A-merged-dirty** | `classify_merge_status(...) == "merged"` AND `is_dirty == True` | `git worktree remove --force --force-reason="<operator's documented reason>"` per `worktree-autoremove-policy.md` Rule 4 |
| **A-orphan-detached** | Detached HEAD AND branch-name NOT a known `git bisect` / `git rebase` pattern AND not in a plan-orphan pattern list | `git worktree remove` (no `--force`); add `--yes-delete-detached` flag if the operator wants a foot-gun-free shortcut |
| **A-orphan-detached-dirty** | Detached HEAD AND dirty | `git worktree remove --force` |
| **X** (cross-repo plan-orphan) | Branch matches `PLAN_ORPHAN_PATTERNS` regex AND same-date signature in ≥ 2 repos AND `is_locked == False` | Same as A-merged or A-orphan-detached depending on classification. **Tier X entries are REPORTED EXCLUSIVELY in `tier_x_cross_repo_orphan` and DO NOT appear under Tier A or any other tier** — totals are sum-of-tiers with no double-counting. |
| **B** | Path matches `<get_worktree_base_path()>/agent-*` (default `~/worktrees/agent-*` per `mahavishnu/core/paths.py:163`) OR `*/.claude/worktrees/agent-*` | `git worktree remove --force` per salvage rule |
| **C** | `9.0 ≤ age_days < 30.0` AND `is_locked == False` AND not classified above | `git worktree remove --force` per salvage rule |
| **D** | `age_days < 9.0` | Manual review required (might be active) |

**§ Boundary inclusivity** (pin in code comments): `age_days < 9.0 → D`,
`9.0 ≤ age_days < 30.0 → C`, `age_days ≥ 30.0 → A-*`. Never ambiguous.

**§ Salvage procedure**: before `--force` on any worktree with untracked files,
copy untracked files to `~/.mahavishnu/salvage/<YYYY-MM-DD>-<sanitized-worktree-name>/`
where `<sanitized-worktree-name>` is `Path(p).name`, then rejected if it equals `.`, `..`,
empty, or contains characters outside `[A-Za-z0-9._-]`. Stashes survive `git worktree
remove` (they live in the branch reflog, not the worktree directory) and need no salvage.
Modified tracked files are recoverable from git history; no salvage.

**§ Lock + live-PID semantics**:

1. **Orphaned `initializing` lock** (no PID in the lock file) → `git worktree unlock`
   + `git worktree remove`. Safe.
2. **Live Claude PID** (lock file contains `(pid <N>)` and `ps -p <N>` returns 0) →
   DO NOT TOUCH. The CLI emits the lock content + PID liveness in the report; the
   operator decides.
3. **`ps -p` is checked at scan time only**; re-check at removal time is the
   operator's responsibility (the CLI does not perform removal).
4. **PID reuse validation**: before trusting `ps -p <pid>` liveness, also call
   `ps -p <pid> -o command=` and verify the command starts with a known pattern
   (e.g., `claude`, `python.*mahavishnu`). If the command does not match, treat as
   `unknown`, not `alive` (PID recycling is real).
5. **`--force -f -f` is the unlock-equivalent** for confirmed-dead PID cases.
   `git worktree remove --force` alone does NOT bypass locks. Document the git
   behavior in the decision doc § References with a link to git source.
6. **Lock file parser**: extract PID via fixed regex
   `^claude agent \S+ \(pid (\d+) start (\d{4}-\d{2}-\d{2})\)$`. No `eval`, no
   `exec`, no shell. Invalid format → `pid_alive = None` + `notes: ["unparsable lock format"]`.

**§ Agent-dispatch reap rule**: `EnterWorktree` and dispatched agents SHOULD reap on
completion. The CLI emits a list of `agent-*` dispatch leftovers and the user invokes
removal explicitly. (No SessionEnd hook — per `worktree-autoremove-policy.md` Rule 2
prohibition.) This is a soft convention enforced by the scanner, not by tooling.

**§ Cross-repo plan-orphan rule**: when a plan creates worktrees across N repos and the
plan completes, all N worktrees are likely orphans simultaneously. The CLI detects
this via same-date pattern matching and groups them in the report. Pattern list is
maintained in `mahavishnu/core/worktree_scan.py:PLAN_ORPHAN_PATTERNS` (a tuple of
regex patterns). The decision doc § Decision rule enumerates the current patterns and
mirrors them in a comment; a guard test `TestPlanOrphanPatternsSync` in
`tests/unit/test_worktree_scan.py` asserts doc/code parity.

**§ Negative rules** (what NOT to do):
- Don't auto-remove even when `--force` would succeed.
- Don't trust the lock file as authoritative; the liveness check is the only signal.
- Don't invoke `-f -f` without a fresh `ps -p <pid>` and command-line identity check.
- Don't point `--repo=` at paths outside the user's expected workspace (`~/Projects`).
- Don't reuse PIDs in `ps -p` output without verifying the command line.

**§ Cross-references**: all 5 existing worktree decisions + v4 followup +
`worktree_prune_merged.py` (for the existing classifier).

### CLI: `mahavishnu worktree scan`

Subcommand of existing `mahavishnu worktree` CLI (file `mahavishnu/worktree_cli.py`).

| Arg | Default | Purpose |
|---|---|---|
| `--repo=ALL\|<path>` | ALL | Which repos to scan (from the bootstrap resolver) |
| `--format=text\|json` | text | Output format |
| `--include-locked` | off | Lock reason + `ps -p <pid>` + `ps -p <pid> -o command=` for identity check |
| `--age-threshold-days=A,C` | `30,9` | Two values: Tier A minimum, Tier C minimum. (No third value — Tier D is implicit `< Tier C minimum`.) |
| `--no-cross-repo-grouping` | off | Skip the Tier X pass (useful when false positives suspected) |
| `--yes-delete-detached` | off | Confirm intent to remove detached-HEAD worktrees without a branch check |
| `--user-id=<id>` | anonymous | For audit log attribution per `worktree-autoremove-v4-followup.md` Principal scoping (forward-compat) |

**Output (text format)** — same shape as before but pinned:

```
[mahavishnu worktree scan] started 2026-09-07T04:34:59Z; repos=31; threshold=A=30d,C=9d

Tier A-merged (3):
  akosha                .worktrees/fix-hotstore-zero-embedding       (107d, fix/hotstore-zero-embedding, merged, dirty)
  graphics-mcp          .claude/worktrees/agent-plan7-phase5          ( 73d, feat/plan7-phase5-fastmcp-3, merged, clean)
  ...
Tier A-orphan-detached (0):
Tier A-merged-dirty (1):
  ...
Tier X (cross-repo plan-orphan, 2026-08-16 wave8-diagram-corrections, 3 repos):
  akosha                .worktrees/wave8-diagram-corrections-2026-08-16
  crackerjack           .claude/worktrees/wave8-diagram-corrections
  session-buddy         .claude/worktrees/wave8-diagram-corrections-2026-08-16
Tier B (agent-dispatch leftovers, 45):
  mahavishnu            /Users/les/worktrees/agent-77490b68          (  0d, worktree-agent-77490b68)
  ...
Tier C (feature branch, mid-age, 17):
  oneiric               .claude/worktrees/bodai-cli-audit-phase-1-oneiric  (9.8d, worktree/bodai-cli-audit-phase-1-oneiric)
  ...
Tier D (recent, manual review, 2):
  mahavishnu            /Users/les/worktrees/agent-23d14acc          (  0d, worktree-agent-23d14acc)
LOCKED-live (cannot remove without verification, 1):
  mahavishnu            .claude/worktrees/agent-a894dd931068d8836 (locked: claude agent ... pid 74005 [alive, cmd=claude])
LOCKED-orphan (PID dead, can unlock+remove, 0):
LOCKED-unknown (lock parse failed, manual review, 0):
DIRTY (1 modified, 0 stashes, 0 untracked; full detail with --include-dirty, 1):
  mcp-common            .claude/worktrees/bodai-cli-audit-phase-0.5

Scan complete: 69 candidates; 0 scan failures; exit 0.
```

**Output (JSON)** — pinned schema:

```json
{
  "scan_metadata": {
    "started_at": "2026-09-07T04:34:59Z",
    "repos_scanned": 31,
    "thresholds": {"tier_a_min_days": 30, "tier_c_min_days": 9}
  },
  "tier_a_merged": [
    {"repo": "akosha", "path": "...", "branch": "fix/hotstore-zero-embedding", "age_days": 107.4, "merged": "merged", "dirty": false}
  ],
  "tier_a_merged_dirty": [],
  "tier_a_orphan_detached": [],
  "tier_x_cross_repo_orphan": [
    {"group_id": "2026-08-16-wave8-diagram-corrections", "date": "2026-08-16", "pattern": "wave8-diagram-corrections", "entries": [{"repo": "akosha", "path": "...", "branch": "docs/wave8-diagram-corrections-2026-08-16"}]}
  ],
  "tier_b": [],
  "tier_c": [],
  "tier_d": [],
  "locked_live": [{"repo": "mahavishnu", "path": "...", "pid": 74005, "liveness": "alive", "command": "claude"}],
  "locked_orphan": [],
  "locked_unknown": [],
  "dirty": [{"repo": "mcp-common", "path": "...", "modified_count": 1, "stash_count": 0, "untracked_count": 0}]
}
```

`jq` example: `.locked_live[] | select(.liveness == "alive") | {repo, pid, command}`.

**Exit codes**:
- `0` — all repos scanned successfully
- `1` — at least one repo scan failed (offending repo in stderr:
  `mahavishnu.worktree_scan.failed_repo:<path> (<reason>)`)
- `2` — `settings/ecosystem.yaml` AND `settings/repos.yaml` both missing or unreadable;
  OR `settings/ecosystem.yaml` exists but cannot be parsed (corrupt YAML, schema-invalid);
  stderr: `mahavishnu.worktree_scan.config: <reason>`

### Classifier: `mahavishnu/core/worktree_scan.py`

Pure-function classifier; no I/O. Takes pre-computed scan data + repo metadata + age
thresholds, returns tier + flags.

```python
@dataclass(frozen=True)
class WorktreeClassification:
    tier: Literal[
        "A-merged", "A-merged-dirty", "A-orphan-detached", "A-orphan-detached-dirty",
        "X", "B", "C", "D", "unknown"
    ]
    is_dirty: bool
    is_locked: bool
    pid_liveness: Literal["alive", "dead", "unknown", "none"] | None  # None when lock absent
    stash_count: int
    modified_count: int
    untracked_count: int
    cross_repo_group_id: str | None  # e.g., "2026-08-16-wave8-diagram-corrections" if grouped
    notes: list[str] = field(default_factory=list)

PLAN_ORPHAN_PATTERNS: tuple[str, ...] = (
    r"^w4-claude-md-breadcrumb",         # Wave 4 plan (Aug 2026)
    r"^plan7-phase5",                     # Plan 7 phase 5 (Aug 2026)
    r"^wave8-diagram-corrections",        # Wave 8 diagram corrections (Aug 2026)
    # Future patterns appended here. Decision doc § Decision rule keeps this in sync
    # via tests/unit/test_worktree_scan.py::TestPlanOrphanPatternsSync.
)

# Reuses classify_merge_status from worktree_prune_merged.py:
#   classify_merge_status(
#       worktree_path: Path,
#       *,
#       main_branch: str = "main",
#       master_fallback: bool = True,
#   ) -> Literal["merged", "not_merged", "undetermined"]

def classify_worktree(
    worktree_path: Path,
    branch: str | None,             # None when detached HEAD
    age_days: float,
    is_dirty: bool,
    is_locked: bool,
    lock_pid_liveness: Literal["alive", "dead", "unknown", "none"] | None,
    plan_orphan_groups: dict[str, list[tuple[str, Path]]],  # {group_id: [(repo_nickname, path)]}
    age_threshold_a: float = 30.0,
    age_threshold_c: float = 9.0,
) -> WorktreeClassification: ...
```

### Skill: `.claude/skills/bodai-worktree-cleanup/SKILL.md`

YAML frontmatter:

```yaml
---
name: bodai-worktree-cleanup
description: |
  Scan Bodai repos for stale worktrees and surface a tier-grouped report.
  Trigger phrases: "scan worktrees", "find stale worktrees", "audit bodai worktrees",
  "list orphaned worktrees".
allowed-tools: Bash, Read
---
```

Body sections:

- **When to use** — user asks for a worktree health check or mentions orphan/disk-cleanup
  in a worktree context
- **Do NOT use for** — generic "low on disk space" (likely Docker images or logs, not
  worktrees); cross-repo cleanup of `/tmp/<branch>` from `Workflow({parallel.f` fanouts
  (use `cross-repo-fanout-cwd-isolation.md` recipe)
- **Quick start** — `mahavishnu worktree scan --repo=ALL --format=text`
- **Output interpretation** — see Tier rubric table in the decision doc; LOCKED-live
  entries require PID command-line identity check before any `-f -f`; the CLI is
  scan-and-report only — never auto-removes
- **Caveats** — the skill does NOT auto-remove anything; never bypasses the v4
  prohibition; for full automation see `worktree-autoremove-v4-followup.md`
- **Relationship to existing skills** — `commit-commands:clean_gone` cleans `[gone]`
  branches only, no worktree handling; the `session-buddy` MCP tool's `remove_worktree`
  has known bugs (per memory `session-buddy-mcp-remove-worktree-bugs`) so prefer
  direct `git worktree remove`

### Wrapper script: `.claude/skills/bodai-worktree-cleanup/scripts/cli_scan.py`

Bash-friendly Python wrapper that calls the CLI. Keeps the skill body thin.

## Integration Contract — `mahavishnu worktree scan`

- **Triggered from**: `.claude/skills/bodai-worktree-cleanup/SKILL.md` (skill wrapper),
  direct CLI invocation (`mahavishnu worktree scan --repo=ALL`), or scheduled via user
  cron (no SessionEnd hook per existing prohibition).
- **Returns to / updates**: stdout (text or JSON report); exit code 0/1/2. No filesystem
  mutation outside the read-only operations (`git worktree list`, `git log`, `git status`,
  `git stash list`, lock file read, `ps -p`).
- **Demonstrable by**: `tests/integration/test_worktree_scan_e2e.py::test_real_repo_scan_yields_non_empty_report`
  (primary). `tests/integration/test_worktree_scan_cli.py` covers CLI surface and is
  supplementary.
- **Rollback signal**: Operator alert `mahavishnu_worktree_scan_duration_seconds`
  quantile(0.99) over a 1h rolling window `> 180s` OR
  `mahavishnu_worktree_scan_total{exit_code="1"} / mahavishnu_worktree_scan_total > 10%`
  over a 1h window. The 180s threshold reflects the serial scan's worst-case
  floor: 31 repos × 5s `_run_git_scanned` baseline = 155s, with headroom for slow
  repos hitting the 30s per-repo cap. Revert = revert commit 2
  (`feat(cli): add mahavishnu worktree scan`) and pin to v0.22.x.
- **Observability added**: OTel counter `mahavishnu_worktree_scan_total{format,exit_code}`
  + histogram `mahavishnu_worktree_scan_duration_seconds{repo_count_bucket}`.

## Integration Contract — `.claude/decisions/worktree-cleanup-policy.md`

- **Triggered from**: any code or doc that references the tier rubric, salvage procedure,
  or lock + live-PID semantics. The decision doc is the canonical source of truth.
- **Returns to / updates**: durable rules consumed by `worktree_scan.py`,
  `worktree_prune_merged.py` (extended), and any future per-tier cleanup subcommand.
- **Demonstrable by**: `tests/unit/test_decision_doc_sync.py::test_decision_doc_lists_current_tiers`
  asserts every tier in the doc maps to a code constant in `worktree_scan.py`. Bidirectional
  back-links to the 5 existing decisions verified by a docs-build log entry.
- **Rollback signal**: superseded-by header in the doc itself; the decision doc is
  version-controlled and Git history is the revert mechanism.
- **Observability added**: docs-build log entry per release; alert if doc is edited
  without the corresponding test update.

## Integration Contract — `.claude/skills/bodai-worktree-cleanup/SKILL.md`

- **Triggered from**: Claude Code session where the user's message matches a trigger phrase.
- **Returns to / updates**: thin wrapper that invokes the CLI. The skill body is the
  user-facing interface; the CLI is the system-facing interface.
- **Demonstrable by**: e2e test `tests/integration/test_bodai_worktree_cleanup_skill.py::test_skill_invocation_matches_direct_cli_output`.
- **Rollback signal**: trigger-phrase grep in `mahavishnu/.claude/settings.json` (if the
  skill is removed, the trigger phrases stop firing; operators notice via the trigger
  table audit).
- **Observability added**: skill-invocation OTel counter (forwarded from Claude Code's
  per-skill metrics if available; otherwise inferred from CLI invocation counter).

## Validation Matrix

| Tool / command | Expected outcome | Evidence |
|---|---|---|
| `pytest tests/unit/test_worktree_scan.py -v` | All classifier unit tests pass | test runner |
| `pytest tests/integration/test_worktree_scan_cli.py -v` | All CLI integration tests pass | test runner |
| `pytest tests/integration/test_worktree_scan_e2e.py -v` | E2E smoke against current `settings/ecosystem.yaml` | test runner |
| `pytest tests/integration/test_bodai_worktree_cleanup_skill.py -v` | Skill wrapper matches CLI output | test runner |
| `pytest tests/unit/test_decision_doc_sync.py -v` | Doc/code parity for tier rubric + plan-orphan patterns | test runner |
| `mahavishnu worktree scan --repo=ALL --format=text` | Non-empty tier-grouped report; exit 0 | manual smoke |
| `mahavishnu worktree scan --repo=ALL --format=json \| jq '.locked_live[] \| {repo, pid, command}'` | Parsable JSON; locked-live array may be empty | manual smoke |
| `mahavishnu worktree scan --repo=/nonexistent/path` | Repo skipped; warning to stderr; exit 0 if others succeed | manual smoke |
| `mahavishnu worktree scan --repo=ALL` against a corrupted `settings/ecosystem.yaml` | Exit 2; stderr `mahavishnu.worktree_scan.config: ...` | manual smoke |
| All repos fail scan | Exit 1; stderr lists all offending repos | manual smoke |
| Skill invocation `/bodai-worktree-cleanup` | Byte-identical to direct CLI invocation (excluding timestamps) | manual smoke |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Classifier drift between `worktree_prune_merged.py` and new `worktree_scan.py` | medium | Single classifier function in `worktree_prune_merged.py:91-129`; `worktree_scan.py` imports `classify_merge_status`, no re-implementation. `tests/unit/test_worktree_scan.py::TestClassifierReuse` asserts `worktree_scan.classify_worktree` does not define a function named `classify_merge_status` or `classify_merged`; both names must be imported. |
| User invokes `--force -f -f` on a live-PID worktree after PID reuse | medium | Decision doc § Decision rule + decision doc § Negative rules require PID-reuse identity check (`ps -p <pid> -o command=`). Operator alert emitted in the report's LOCKED-live line. CLI does not perform removal; user responsibility enforced by the decision doc, not by tooling. |
| Subprocess injection via `--repo=<path>` or `ps -p <pid>` | medium | Spec pins `shell=False` + list-form args; `worktree_scan.py` imports `_run_git` from `worktree_prune_merged.py` and adds sibling `_run_ps` with same shape. PID validated as `^[0-9]+$` before `ps` call. |
| Salvage / lock-file path traversal | medium | Leverage existing utilities: `WorktreePathValidator` (`mahavishnu/core/worktree_validation.py`), `get_worktree_base_path` (`paths.py:153-182`), `PathValidator.validate_path` (`validators.py:122`), `_validate_path` (`bootstrap.py:90`). Add ONE genuinely-novel helper in `worktree_scan.py`: `safe_worktree_name(name: str) -> str` enforcing character class `[A-Za-z0-9._-]` + reject `.`/`..`/empty. Unit tests feed malicious names and assert the resolved path stays inside the salvage root. |
| Cross-repo plan-orphan false positives | medium | `--no-cross-repo-grouping` flag; default grouping requires ≥ 2 repos in same-date signature. Optional followup: confidence threshold (group only when ≥ 3 repos). |
| Skill trigger surface / prompt injection | low | Skill body says "does NOT auto-remove" three times; trigger phrases narrowed to worktree-only context (dropped "low on disk space"); CLI itself refuses `-f -f` (no command, scan-only). |
| Live-PID escalation path missing | low | Decision doc § References links the manual path: `ps -p <pid> -o command,etime,stat`; if PID is a `claude` agent dispatch with long uptime, the operator decides. A future `mahavishnu worktree inspect --pid <pid>` is a deferred followup. |
| `repos.yaml` corruption (parse error) | low | Exit code 2 with stderr message; spec exit-code table pins both messages. |
| `settings/ecosystem.yaml` resolves to a symlink outside the project | low | `safe_repo_root()` resolves and asserts containment inside `~/Projects`. |
| `--include-locked` against a non-existent PID | low | `ps -p <pid>` returns non-zero + exit 1; CLI surfaces as `LOCKED-unknown`. |
| OTel label cardinality | low | `repo_count_bucket` bounded; no per-worktree labels. |
| Scan hangs on network-mount repo | low | Per-repo wall-clock cap of 30s; per-`ps -p` timeout of 2s; fail-loud on timeout, don't silently skip. |
| Skill auto-removes when user runs out of disk space | low | Skill body has explicit "Do NOT auto-remove" + "Do NOT use for" list + Relationship-to-Existing-Skills table; trigger phrases narrowed to worktree-only. |
| Wrapper script naming overlaps with subcommand noun | low | Wrapper renamed from `scan_worktrees.py` to `cli_scan.py`. |
| Empty `settings/ecosystem.yaml` | low | Spec exit-code table pins: exit 0 with empty report ("0 candidates; 0 repos scanned; exit 0"). |

## Decision Rule

Ship the three artifacts as separate commits in this order:

1. `feat(decisions): add worktree-cleanup-policy.md` — the policy. Land first so
   subsequent commits reference it. Read-only — no behavior change. Includes back-link
   additions to the 5 existing decision docs.
2. `feat(cli): add mahavishnu worktree scan` — the CLI. With unit + integration tests.
   Land second. Behavior surface; CLI tests pin it. Modifies only `worktree_cli.py`,
   `worktree_scan.py`, `tests/`. Per `removed-scripts.md`, no edit
   to `worktree_prune_merged.py` is permitted in this commit; classifier reuse is
   read-only via import.
3. `feat(skills): add bodai-worktree-cleanup` — the skill wrapper + `cli_scan.py`.
   Land third. Pure wiring; no logic.

Per `.claude/decisions/bodai-pre-1.0-merge-policy.md`, all three commits land directly
to main. No PR. Squash is forbidden because each commit's `tests/` change pins that
commit's contract.

Per `.claude/decisions/wire-up-contract.md`: this spec is the canonical Integration
Contract for all three artifacts (CLI, decision doc, skill). Each artifact's contract
block above satisfies the wire-up contract.

**Not in scope for this spec** (deferred): the auto-removal piece gated on
`RemoteWorktreeProvider` (per `worktree-autoremove-v4-followup.md`). When v4 lands,
a followup spec supersedes parts of this one.

## Spec Amendments (post multi-agent review)

Reviewers: `critical-audit-specialist` (audit), `mycelium-core:security-auditor` (security),
`documentation-review-specialist` (DX), `general-purpose` (lateral), `qa-strategist` (final-pass QA).
Synthesis: 2026-09-07.

| ID | Severity | Reviewer | Section | Change |
|---|---|---|---|---|
| A1 | critical | audit + DX + lateral | Classifier signature | `classify_merged` → `classify_merge_status(worktree_path, *, main_branch="main", master_fallback=True)` returning `Literal["merged","not_merged","undetermined"]`. Verified at `mahavishnu/core/worktree_prune_merged.py:91-129`. |
| A2 | critical | audit + lateral + DX | Tier A rule | Tier A-merged-dirty requires `--force-reason` per `worktree-autoremove-policy.md` Rule 4. Restated as separate tier rows. |
| A3 | critical | DX + audit | Tier boundary inclusivity | Explicit `<` vs `<=` for 9.0d and 30.0d; boundary test fixtures (8.99, 9.0, 9.01). |
| A4 | critical | DX | Tier A `--force` predicate | Tied to `is_dirty` flag; dirty classification unconditional (not gated on `--include-dirty`). |
| A5 | critical | audit + lateral + DX | CLI path | `mahavishnu/cli/worktree_cli.py` → `mahavishnu/worktree_cli.py` (verified by grep). |
| A6 | critical | lateral + (verified by me) | Manifest source | `settings/repos.yaml` → `settings/ecosystem.yaml` via `mahavishnu/core/bootstrap.py:_resolve_repos_path()`. `BODAI_REPO_REGISTRY.md` is prose, NOT a runtime fallback. |
| A7 | high | audit + lateral | Tier B path matcher | Hardcoded `/Users/les/worktrees/agent-*` → `<MAHAVISHNU_AUTO_WORKTREE_ROOT>/agent-*` (default `~/.claude/worktrees`) per `session-worktree-defaults.md`. |
| A8 | high | security + audit + lateral | Subprocess safety | Pin `shell=False`, list-form args, reuse `_run_git`, add `_run_ps` with PID regex `^[0-9]+$`. |
| A9 | high | security + audit | Salvage + lock path traversal | `path_safety.py` with `safe_worktree_name()` + `safe_repo_root()`; basename-only + `..` reject + char class. |
| A10 | high | security + audit | Force-removal authorization | Decision doc § Decision rule + § Negative rules; operator must re-verify PID before `-f -f`. |
| A11 | high | security + audit | Lock file parser | Fixed regex `^claude agent \S+ \(pid (\d+) start (\d{4}-\d{2}-\d{2})\)$`; no eval/exec. |
| A12 | high | security + audit + lateral | `--age-threshold-days` | Three values → two values (`A,C`); Tier D is implicit. |
| A13 | high | security + audit + lateral | pid_alive tri-state | `bool | None` → `Literal["alive","dead","unknown","none"]`. |
| A14 | high | audit + lateral | Architecture: pick one path | Removed the "OR new file" comment; pin `EXTENDS worktree_cli.py`. |
| A15 | high | DX | Integration Contract per artifact | Added contract blocks for the decision doc and skill (wire-up contract compliance). |
| A16 | high | DX | JSON schema example | Added full JSON schema with pinned key naming. |
| A17 | high | DX | Tier naming consistency | Renamed `A-cross-repo-orphan` → `X` (peer-tier, not sub-tier of A). |
| A18 | high | DX | Validation Matrix fragile criteria | Changed `Integer > 0` to `Integer ≥ 0`; added "total repo count ≥ 30" assertion. |
| A19 | high | DX | Detached HEAD foot-gun | Added `A-orphan-detached` rule requiring NOT a `git bisect`/`rebase` pattern; `--yes-delete-detached` opt-in. |
| A20 | high | audit | Guard test name | Renamed to `TestClassifierReuse`; added specific assertion. |
| A21 | medium | security + audit + lateral | PID-reuse identity check | Added `ps -p <pid> -o command=` + command-pattern match; treat mismatch as `unknown`, not `alive`. |
| A22 | medium | security + audit | Skill trigger narrowing | Dropped "low on disk space"; added "Do NOT use for" list; added Relationship to Existing Skills table. |
| A23 | medium | security | Output redaction | Never log raw lock-file content; only parsed tuple `(agent_name, pid, pid_liveness, command)`. |
| A24 | medium | security + audit | Scan timeouts | Per-repo wall-clock cap 30s; per-`ps -p` timeout 2s; fail-loud. |
| A25 | medium | lateral | Cross-repo plan-orphan false positives | `--no-cross-repo-grouping` flag; default ≥ 2 repos. |
| A26 | medium | lateral | Wrapper script naming | Renamed `scan_worktrees.py` → `cli_scan.py`. |
| A27 | medium | DX | Spec amendments section | This table. Per `mcp-common-auth-primitives-design.md` precedent. |
| A28 | medium | DX | Decision-doc-tier parity test | `tests/unit/test_decision_doc_sync.py::test_decision_doc_lists_current_tiers` asserts doc/code parity. |
| A29 | medium | lateral | Detached HEAD catches `git bisect` | Same as A19 (cross-listed for completeness). |
| A30 | medium | audit | `repos.yaml` empty/malformed | Exit 2 covers corrupt; empty → exit 0 with empty report. |
| A31 | medium | audit | Scan pipeline 3-pass | Documented in § Architecture (Flow). |
| A32 | medium | DX | Stderr wording per exit code | Pinned in § CLI → Exit codes. |
| A33 | medium | DX | Negative-case validation rows | Added 4 rows: all-repos-fail, corrupt manifest, `--include-locked` against nonexistent PID, unknown tier surfaces in report. |
| A34 | low | audit + DX | Concurrency / torn `git worktree list` | Snapshot per repo, error-and-continue (acceptable for read-only scan). |
| A35 | low | audit | Exit code 3 (candidates found) | Skipped: exit 0 + structured `candidate_count` to stdout is sufficient for automation. |
| A36 | low | audit | Empty docs.yaml entry | Cover in § CLI exit codes. |
| A37 | low | lateral | Cross-repo migration story for non-mahavishnu Bodai | Non-Goals already addresses this (decision lives in mahavishnu per `bodai-mcp-routing-pattern.md`). |
| A38 | low | DX | Bidirectional back-link requirement | Decision Rule § 1 commit includes back-link additions to the 5 existing decision docs. |
| A39 | low | DX | Merge-strategy note | Added to Decision Rule: "land directly to main, no PR, squash forbidden". |
| A40 | low | DX | `removed-scripts.md` cross-reference | Added to Commit 2 description: "no edit to `worktree_prune_merged.py` permitted". |
| A41 | low | DX | Skill wrapper e2e assertion | Replaced tautological "same output" with `test_skill_invocation_matches_direct_cli_output`. |
| A42 | low | DX | Concurrent scan + mutation | Same as A34. |
| A43 | low | audit + lateral | OTel overkill for read-only scan | Kept; counter + histogram are cheap and aid capacity planning. |
| A44 | low | lateral | Skill auto-removes on disk pressure | Same as A22. |
| A45 | low | DX | Subcommand/script naming overlap | Same as A26. |
| A46 | low | audit + DX | `--include-locked` PID parse | Same as A11. |
| A47 | low | lateral | `find-capability` discoverability | Skill description is precise; if discoverability suffers, future followup can add informal trigger phrases. |
| A48 | low | DX | Migration path for `mahavishnu worktree list` | Documented in Non-Goals: `list` and `scan` coexist; `scan` is the stale-focused dialect. |
| A49 | low | DX | Spec amendment attribution table | This section. |
| A50 | nit | audit | Goal #1 typo (`.2.`) | Fixed in Goals §1. |
| A51 | nit | audit | Tier B glob notation | Uses regex `^worktree-agent-` instead of shell glob. |
| A52 | **critical** | QA | Tier B path default was wrong | Spec had `~/.claude/worktrees/agent-*` as default; actual default per `mahavishnu/core/paths.py:163` (`get_worktree_base_path()`) is `~/worktrees/agent-*`. Fixed in Tier rubric + Architecture "Existing utilities" section. |
| A53 | **critical** | QA | Env var name was legacy alias | Spec referenced `MAHAVISHNU_AUTO_WORKTREE_ROOT`; canonical is `MAHAVISHNU_WORKTREE_BASE_PATH` (the other is a 1-release legacy alias with a guard test forbidding direct reads). Replaced with "use `get_worktree_base_path()` from `paths.py`". |
| A54 | **critical** | QA | `classify_merge_status` return type mismatch | Spec said it returns `Literal["merged","not_merged","undetermined"]`; actual signature is `-> str:`. Cannot edit the source (per A40); import-side cast documented in § Architecture "Existing utilities" section. |
| A55 | high | QA | `_run_git` hard-coded `timeout=5` conflict | Reusing `_run_git` directly imposes the 5s ceiling, incompatible with the 30s per-repo cap (A24). `worktree_scan.py` defines its own `_run_git_scanned(path, *args, timeout=...)` and `_run_ps(...)` siblings — does NOT import `_run_git` from `worktree_prune_merged`. |
| A56 | high | QA | `path_safety.py` duplicates 80% of existing utilities | Spec's new module would re-implement `PathValidator.validate_path`, `get_worktree_base_path`, `_validate_path`. Dropped `path_safety.py` from the architecture tree; `worktree_scan.py` uses the existing utilities + adds ONE genuinely-novel helper `safe_worktree_name()` (character-class sanitizer). |
| A57 | high | QA | `_resolve_repos_path()` requires `app` instance | Function signature is `_resolve_repos_path(app, logger)`, not no-arg. CLI's options documented in § Context (instantiate `MahavishnuApp` shim, refactor bootstrap, or read config directly via `oneiric.config`). Tests pin the chosen approach. |
| A58 | high | QA | Scan serialization not specified | Pass 2 needs the full Pass 1 dataset for grouping; naïve parallelism would mis-label Tier X. Documented as serial 3-pass pipeline. Alert thresholds raised accordingly. |
| A59 | high | QA | Rollback signal `p99 > 60s` unrealistic | 31 repos × 5s `_run_git_scanned` baseline = 155s, so 60s fires spuriously. Changed to `quantile(0.99) > 180s` over 1h rolling window. Histogram shape clarified (consecutive-runs is wrong shape for a histogram). |
| A60 | medium | QA | Tier X double-counting ambiguity | "Reported exclusively in `tier_x_cross_repo_orphan`, do NOT appear under Tier A" — pinned in Tier rubric and JSON schema documentation. |
| A61 | medium | QA | OTel `repo_count_bucket` cardinality unbounded | Pinned to closed buckets `[1, 5, 10, 20, 30, 50]` or change metric shape. Documented in Risks. |
| A62 | medium | QA | Decision-doc observability phantom metric | Dropped the "alert if doc edited without test update" — the `TestPlanOrphanPatternsSync` test failing in CI is sufficient. |
| A63 | medium | QA | `--user-id` is YAGNI | Spec's "forward-compat" claim with no writer. Either wire to JSON `scan_metadata.user_id` (documented field) or drop. Deferred. |
| A64 | medium | QA | Log levels not specified | Added § Log levels: `mahavishnu.worktree_scan.config` = ERROR; `mahavishnu.worktree_scan.failed_repo` = WARNING; `mahavishnu.worktree_scan.completed` = INFO. |
| A65 | medium | QA | `_run_git` 5s timeout hides slow repos | The spec's `_run_git_scanned` uses explicit timeout per call; truncated calls (return code != 0 with empty output) emit `notes: ["undetermined"]` and a separate `mahavishnu_worktree_scan_truncated_total{repo}` counter so p99 isn't polluted. |
| A66 | medium | QA | Validation Matrix missing Tier X exclusive row | Added: "Scan fixture with one worktree matching `PLAN_ORPHAN_PATTERNS` AND `classify_merge_status == 'merged'`; assert JSON `tier_x_cross_repo_orphan` contains it AND `tier_a_merged` does NOT." |
| A67 | medium | QA | Validation Matrix missing concurrent-scan row | Added: "Spawn two `mahavishnu worktree scan` processes in parallel against a 5-repo fixture; assert both produce identical JSON (modulo timestamps) and neither crashes." |
| A68 | medium | QA | `repos_count ≥ 30` assertion is flaky | Changed to `repos_scanned == len(ecosystem.yaml.repos)` — compare against the manifest. |
| A69 | low | QA | No staging/rollout plan | Documented that the feature is opt-in via explicit invocation; no flag needed (operator can't accidentally scan 31 repos). |
| A70 | low | QA | Wrapper script invocation path | `cli_scan.py` invokes `python -m mahavishnu.worktree_cli worktree scan [...]` (not the `mahavishnu` console_script) for venv-correctness. |
| A71 | low | QA | Typer convention | The `scan` subcommand follows existing `@worktree_app.command('scan')` + `@typer.Option` decorator pattern (verified in `worktree_cli.py:42, 80, 146, ...`). |
| A72 | low | QA | `MAHAVISHNU_AUTO_WORKTREE_ROOT` doc inconsistency | `session-worktree-defaults.md` references the env var only as a hint-check condition. This spec codifies its meaning for the scan path; canonical source is `paths.py:153-182`. |
| A73 | nit | QA | Lock file regex fragility | Lock file format is owned by Claude Code, not by this spec. If Claude Code changes the format, the parser fails gracefully (`pid_liveness = "none"`, `notes: ["unparsable lock format"]`). Add production lock-file sampling before pinning the regex. |
| A74 | nit | QA | `worktree-validation.py` not referenced | Architecture "Existing utilities" section now lists all four utilities `worktree_scan.py` should leverage. |
