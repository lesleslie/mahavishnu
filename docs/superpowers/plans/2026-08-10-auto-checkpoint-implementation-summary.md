# Auto-Checkpoint Implementation — Summary

> One-screen summary for the greenlight decision. Companion to `2026-08-10-auto-checkpoint-safety-and-trigger.md`.

## Problem

session-buddy has the data layer for auto-checkpoints (`MergePrimitive`, `AmbientPuller`, `CrossRepoAccountant`, `_create_checkpoint_message`) but no automatic trigger. The MCP `checkpoint` tool only fires when something calls it. Three settings (`auto_checkpoint_interval`, `enable_auto_commit`, `commit_message_template`) are defined but never consumed. Worse, the existing checkpoint flow unconditionally runs `git add -A` — a documented race that has already clobbered subagent edits in production (2026-07-15 observation). Today the user has to remember to call `/mcp__session-buddy__checkpoint` manually and hope they aren't interrupting a subagent.

## Solution

Build the four-component design from the approved 2026-07-15 spec (`SubagentDetector` + `SnapshotMechanism` + `CheckpointPolicy` + `CheckpointOrchestrator`) under `session_buddy/checkpoint/`, wrap the existing `perform_git_checkpoint()` call via the `_checkpoint_with_safety_capture` helper in `session_buddy/core/session_manager.py`, and add an MCP-server-lifespan timer that fires mid-task checkpoints every `settings.auto_checkpoint_interval` seconds. Add a pending-checkpoint durability mechanism so end-of-task checkpoints deferred by a long-running subagent aren't silently dropped. Add a TTL-based cleanup so `/tmp/snap-*.patch` files don't accumulate forever. Net: 10 tasks, all four components read-only w.r.t. the working tree, all failures fail closed (with retry-once-with-backoff for transient 5xx).

## Trigger surface (after this work)

| When | What | How |
|---|---|---|
| Claude Code `Stop` event | End-of-task checkpoint (mandatory, always commits) | `~/.claude/settings.local.json` → `sb_checkpoint.py` → MCP `checkpoint` → orchestrator (already wired) |
| Every `settings.auto_checkpoint_interval` seconds (default 1800 =30 min) | Mid-task analytics tick (snapshots only, no commit) | New `AutoCheckpointLoop` in MCP server lifespan, `forward_to=_noop_forward` |
| Every `settings.midpoint_commit_interval_s` seconds (default 600 =10 min) **only when `midpoint_commits_enabled=True`** | Mid-task commit tick (snapshots AND commits when policy fires) | Same `AutoCheckpointLoop` with `forward_to=_midpoint_commit_forward` |
| Quality threshold (delta ≥10 or score ≥90, when quality source wired) | Mid-task commit trigger via `QualityDeltaSignal` | New signal added to `MidpointCriteria` when `midpoint_commits_enabled=True` |
| `SessionEnd` | Drain pending markers, end session | New: pending marker drain in `end()` |
| `SessionStart` | Init session (already works) | `sb_session_start.py` (already wired) |

## Safety invariants (the contract the design protects)

1. **Working tree is never mutated by a checkpoint.** All captures are `git diff HEAD > /tmp/snap-<uuid>.patch` with `chmod 0o444`. The legacy `git add -A && git commit` runs only after a successful snapshot AND no subagent is active.
2. **Subagent active → defer.** `LockfileSignalSource` at `<working_dir>/.session-buddy/subagent.lock`. Fail-open on lockfile error.
3. **End-of-task is mandatory.** If subagent doesn't go idle in 60s, persist a marker at `~/.session-buddy/pending/*.json`; the next loop tick or `SessionEnd` consumes it. NEVER silently drop.
4. **Failures fail closed.** Narrow exceptions: `(subprocess.SubprocessError, OSError, ValueError, httpx.HTTPStatusError)`. Programming errors propagate. Transient 5xx from `forward_to` retries once with 500ms backoff.
5. **Concurrency serialized.** `asyncio.Lock` per `CheckpointOrchestrator` instance; two simultaneous calls on the same working dir serialize, never race.

## Failure-mode handling

| Failure | Behavior |
|---|---|
| Subagent lock file missing/unreadable | Fail open to "active" → defer (safer to defer than to risk clobber) |
| Snapshot capture fails (git binary missing, timeout) | Log ERROR, increment `checkpoint_failures_total{reason}`, return `fired=False` |
| `forward_to` returns 5xx | Retry once with 500ms backoff |
| `forward_to` returns 4xx | No retry, fail closed |
| Subagent timeout during end-of-task wait | Persist pending marker; do NOT commit (working tree unsafe) |
| Concurrent checkpoint requests | `asyncio.Lock` per orchestrator; second waits |
| Empty working tree at capture time | Soft success, skip `forward_to` (no point committing a clean tree) |

## Config knobs (operator-visible)

| Knob | Default | Effect |
|---|---|---|
| `settings.auto_checkpoint_interval` | 1800s (30 min) | Analytics-only mid-task cadence. `ge=60` enforced. Set to 0 → no timer. |
| `settings.midpoint_commits_enabled` | **False** | Off → timer produces snapshots only. On → timer also commits (and switches cadence to `midpoint_commit_interval_s`). |
| `settings.midpoint_commit_interval_s` | 600s (10 min) | Active cadence when `midpoint_commits_enabled=True`. Used only when commits are on. |
| `settings.midpoint_commit_min_quality_delta` | 10 | When a quality source is wired (e.g., crackerjack), fires a commit when score delta exceeds this. Inactive when no source. |
| `ModeConfig.enable_auto_checkpoint` | True (standard) / False (lite) | Whether `SessionManager` routes through orchestrator. Lite mode bypasses. Also gates whether the MCP timer is started at all. |
| `MidpointCriteria.signals` | `[TimeElapsedSignal(300s), DirtyFilesSignal(5), QualityDeltaSignal(10)]` | Which signals fire a midpoint. OR semantics. QualityDeltaSignal only active when commits enabled AND quality source wired. |
| `~/.session-buddy/pending/*.json` | n/a | Persistent end-of-task deferral. Drained automatically; visible to operator via `ls`. |
| `session-buddy checkpoint cleanup-snapshots --older-than 7` | n/a | Manual cleanup command (spec line 388). |

## Testing

- **9 unit + 3 component tests** for the four components (Tasks 1-4, 6)
- **Property-based keystone** (Task 10): 50 hypothesis scenarios × 4 phases × subagent-on/off, asserting `working_tree_never_mutated`
- **Stash-clobber regression** (Task 10): defense-in-depth assertion that no `git stash` is invoked from any of the 5 checkpoint modules — the new design is stash-free (no `git stash` invocation exists in the checkpoint path), and the `subprocess.run` spy is a regression guard against any future reintroduction of `git stash`, not a verification of currently-existing behavior. The test pairs the spy with a working-tree SHA hash assertion (`_hash_working_tree`) that would catch any tree mutation regardless of mechanism.
- **Restore fail-loud tests** (Task 2): 3 failure modes (patch missing, git apply conflict, drift) with hunk detail in error messages
- **Orchestrator retry tests** (Task 4): 5xx retry-once, retry exhausted, 4xx no-retry
- **Lite-mode bypass + standard-mode wrap integration test** (Task 8): real `SessionManager` with both modes
- **90% coverage gate** (Task 10 Step 5): `pytest --cov=session_buddy.checkpoint --cov-fail-under=90`

## Risk assessment — what could still go wrong

- **Default `midpoint_commits_enabled=False` leaves a durability gap for autonomous sessions.** The plan delivers on "no manual `/mcp__session-buddy__checkpoint`" for interactive use out of the box. For autonomous/subagent-heavy use, operators must opt in via `midpoint_commits_enabled=True` (also drops cadence to 10 min). This is intentional — the default-off posture preserves the analytics-only spec semantics — but it means a long-running unattended Claude Code session without this opt-in will produce no git commits until `Stop` fires. *Documented in plan preamble; operator action required.*
- **Lockfile race across MCP server instances.** If two MCP servers target the same working dir, the per-tree lockfile prevents both from deferring each other, but doesn't prevent concurrent captures (the orchestrator's `asyncio.Lock` is per-instance). Multi-server deployments should ensure one MCP server per working dir. *Out of scope for this plan.*
- **Marker file loss.** If `~/.session-buddy/pending/` is on tmpfs and reboots between deferral and drain, the deferred checkpoint is lost. *Mitigation:* marker dir is `$HOME/.session-buddy/` which is on persistent storage on standard macOS/Linux. *Documented.*
- **Performance overhead from `git status --porcelain` polling.** Every timer tick polls git status. At 30-min cadence this is ~48 polls/day, negligible. At 10-min cadence (commits-enabled) it's ~144 polls/day, still negligible. *Out of scope.*
- **Cross-repo accounting positioning.** The existing `CheckpointCrossRepoAccountant.capture()` runs after `perform_git_checkpoint`. The orchestrator wraps the latter, so cross-repo accounting still fires. *Verified preserved.*
- **Midpoint commits skip cross-repo accounting and conversation storage** (they call `create_checkpoint_commit` directly). Intentional — midpoints don't have a `conversation_id`. If user wants cross-repo accounting on midpoint commits, the orchestrator forward needs session-manager plumbing — out of scope for v2.
- **C-1 (dormant Critical, final-review note): lockfile producer is not yet wired.** `SubagentDetector` only consumes the lockfile (reader side wired via `LockfileSignalSource`); no producer side actually creates `<working_dir>/.session-buddy/subagent.lock` from the subagent runtime yet. That producer is a separate Mahavishnu-side concern (the subagent executor that owns the lifecycle), and the dependency was left open in this plan rather than half-implemented. `LockfileSignalSource.write()` is intentionally unwired in this codebase (see docstring in `session_buddy/checkpoint/subagent_detector.py`). **Resulting risk:** until the producer lands, secondary protection against subagent-start-during-capture is effectively a no-op — `SubagentDetector.is_active()` returns False because the file does not exist, so the Re-check subagent branch (`subagent_active_during_capture`) never fires. The primary `wait_until_idle` check (which observes the lockfile *and* direct cancellation signals) still gates endpoint commits, so the stash-clobber race that motivated the entire plan is eliminated via the stash-free design. **Recommended follow-up:** track producer wiring as a follow-up plan owned by the subagent-runtime team — DO NOT silently merge a half-wired producer here.

## Greenlight criteria

- [ ] Spec reviewed and approved (yes — 2026-07-15)
- [ ] Three reviewer subagents have audited the plan (yes — coverage + integration + test, all back)
- [ ] All critical + major findings integrated (yes — retry, lock, durability, cleanup, metrics, coverage)
- [ ] Operator-visible config documented (yes — see "Config knobs" above)
- [ ] Failure modes enumerated (yes — see "Failure-mode handling" above)

## Files touched

- **New (10 production files + 12 test files)**: `session_buddy/checkpoint/{__init__,subagent_detector,snapshot,policy,orchestrator,cleanup,metrics,pending}.py` + `session_buddy/core/auto_checkpoint_loop.py` + `session_buddy/cli/checkpoint_cli.py` + `tests/unit/core/checkpoint/{__init__,conftest,test_cleanup,test_module_surface,test_orchestrator,test_pending,test_policy,test_session_manager_orchestrator_wiring,test_snapshot,test_subagent_detector,test_working_tree_invariant}.py` + `tests/unit/mcp/test_auto_checkpoint_timer.py`.
- **Modified (6 production files + tests/uv.lock)**: `session_buddy/checkpoint/orchestrator.py`, `session_buddy/checkpoint/pending.py`, `session_buddy/core/session_manager.py`, `session_buddy/mcp/server.py`, `session_buddy/settings.py`, `pyproject.toml` (hypothesis dep) — plus test files and `uv.lock`.

## Tracking

Originating observation: 2026-07-15 comprehensive-hooks-cleanup wave. Source spec: `docs/superpowers/specs/2026-07-15-sb-checkpoint-stash-clobber-fix-design.md`. Plan: `docs/superpowers/plans/2026-08-10-auto-checkpoint-safety-and-trigger.md`. This summary: `docs/superpowers/plans/2026-08-10-auto-checkpoint-implementation-summary.md`.

**Implementation commits**: 19 in `5af5cb48^..e9ee0d21` (auto-checkpoint landing window).