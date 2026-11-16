---
status: active
role: canonical
date: 2026-11-15
last_reviewed: 2026-11-15
superseded_by: null
topic: dispatch-isolation
title: "A dispatched worker runs in the directory the dispatch names"
---

# A dispatched worker runs in the directory the dispatch names

## Context

`mahavishnu_pool_route_execute(worktree={"isolation": "worktree"})` creates a
git worktree, dispatches the task, and captures the worktree's diff on
completion. Until 2026-11-15 the worktree protected nothing:

- `WorktreeManager.create_worktree` computed `worktree_path` and then dropped
  it — `WorktreeInfo` had no field to carry it.
- `_prepare_worktree` returned the **source** repository path, not the
  worktree path, and `_dispatch_internal` never received either.
- `PoolManager.route_task` has no working-directory concept at all
  (`rg "cwd" mahavishnu/pools/*.py` returned nothing), so nothing told the
  worker session where to start.
- `ShellWorker` — the backend every `terminal-*` worker type runs on — had no
  cwd parameter, and `render_command` had no way to apply one.

The result was silent: the worker edited the source checkout while the diff
was captured from the untouched worktree. The dispatch returned an empty
`files_touched` and an empty diff, which reads exactly like "the worker did
nothing" — and the source checkout carried the changes, so a parallel
dispatch against the same repo would race on them. This is the same failure
mode the repo's own memory records for parallel same-repo agents
(`feedback-workflow-parallel-same-repo-no-isolation`).

## Decision rule

**A worker's working directory is a property of the dispatch, and it must
reach the session that runs the task.**

1. The directory rides the task dict, next to `timeout` — the same carrier
   `route_task` already forwards unchanged to `pool.execute_task(task)`.
   The key is `task["cwd"]`.
2. The path reaches the shell as a **quoted** `cd` applied to the whole
   launch command: `cd <dir> && ( <command> )`. The parenthesised group is
   not decoration — the prompt prologue is `;`-separated, so a bare
   `cd <dir> && <cmd>` would leave the trailing commands running in the
   previous directory when the `cd` fails. The path is quoted because it
   reaches `/bin/sh -c` as shell text.
3. The path is applied **when the session launches**, not when the task is
   executed. A pre-spawned session is already running somewhere else, so a
   pool that cannot honour `task["cwd"]` **fails loudly** rather than
   running the worker in the wrong directory.
4. `WorktreeInfo.worktree_path` carries the path so it cannot be dropped
   again.

### Which pool types honour `task["cwd"]`

Rule 3 is implemented **only by `MahavishnuPool`** — the pool type every
`terminal-*` SHELL worker runs on, and the one `pool_route_execute` uses
for worktree isolation. The other pool types do not read the key:

| Pool type | Reads | Behaviour with `task["cwd"]` |
|---|---|---|
| `MahavishnuPool` | `task["cwd"]` | honoured; a pre-spawned pool raises `ValueError` |
| `SessionBuddyPool` | `task["working_dir"]` (a different thing) | **refused** — the pool cannot start a worker in a named directory |
| `RunPodPool` | — | **refused** |
| `PiPool` | — | **refused** |

So the fail-loud guarantee covers the pool layer as a whole: a task that
names a directory is either run in that directory or refused. Only
`MahavishnuPool` can run it in that directory, because the other three
have no working-directory concept to run it in — and they cannot be given
one on this side of the boundary. `task["working_dir"]` is *not* the key
they are missing: in `SessionBuddyPool` it is session-buddy's
`subagent_marker` bookkeeping about which directory a subagent is
associated with, not a directory the worker starts in, and session-buddy's
`execute_on_pool` takes no directory argument at all. Closing the remaining
gap means teaching those pools the key — a cross-repo change — rather than
aliasing a key that means something else.

## Status

**Active** — fixed 2026-11-15. `WorktreeInfo.worktree_path` added;
`pool_route_execute` passes the worktree path as `task["cwd"]`;
`MahavishnuPool._execute_one_shot_task` forwards it to the worker factory;
`WorkerManager._create_worker` hands it to `ShellWorker`; `render_command`
applies it as a quoted `cd`. Covered by
`tests/integration/test_pool_worktree_isolation.py` (the dispatch receives
the worktree path, and a dispatch without isolation receives none) and
`tests/unit/workers/test_shell_working_directory.py` (quoting, the
failed-`cd` skip, and the untouched default).

**Known gaps:**

- `WorktreeManager._get_worktree_path` places worktrees at
  `<repo>/.worktrees/<id>`, inside the repository. That is the C-8 canonical
  layout and `.worktrees/` is gitignored, but it does not match the
  repo-wide convention in `~/.claude/CLAUDE.md`
  (`~/.local/state/mahavishnu/worktrees/<repo>/`). Left alone here — it is a
  separate decision from the cwd contract, and changing it moves every
  worktree the fleet creates.
- The fail-loud guarantee now covers every pool, but only
  `MahavishnuPool` can actually *honour* a directory. `SessionBuddyPool`,
  `RunPodPool` and `PiPool` refuse a task that names one rather than
  running it in the wrong place. The refusal is the whole of what can be
  done on this side of the boundary: `task["working_dir"]` is a different
  thing — session-buddy's `subagent_marker` bookkeeping about which
  directory a subagent is associated with, not a directory the worker
  starts in — and session-buddy's `execute_on_pool` takes no directory
  argument at all, so there is nothing for the pool to pass on. Honouring
  `task["cwd"]` on those pools is a cross-repo change (session-buddy's
  executor needs a directory parameter; a RunPod pod needs the directory
  mounted; a Pi subprocess needs its cwd set), and until it lands,
  refusing is the honest answer. See the table above.
