---
status: active
role: canonical
kind: decision
date: 2026-11-15
last_reviewed: 2026-11-15
superseded_by: null
blocks_on: []
topic: merge-review
title: "The ensemble review dispatches its reviewers concurrently, each in its own worktree"
---

# The ensemble review dispatches its reviewers concurrently, each in its own worktree

## Context

The stage-2 ensemble review dispatches three reviewers: a domain
specialist, a code-quality specialist, and a random generalist. Until
2026-11-15 it dispatched them **one after another**, and each dispatch is
an I/O-bound MCP round trip to a Mahavishnu worker pool. The pipeline
therefore paid the slowest reviewer's latency three times over: a review
that should have cost the slowest reviewer cost the sum of all three. A
merge whose review took twenty minutes was really three concurrent
reviews.

Making them concurrent raises a question the sequential version never
had to answer: where do three reviewer sessions run? They all inherit
the pool server's working directory, which is the shared main checkout.
On 2026-11-06 a reviewer in this same ensemble ran `git stash` in that
checkout and disturbed another reviewer's work. The repo's rule for
parallel agents on one repo is worktree isolation, and the dispatch was
not using it.

## Decision rule

**The three reviewers are dispatched concurrently, and each is dispatched
into its own worktree — and that isolation is verified, not assumed.**

- Concurrency is in `merge_to_main.run_review`: the three dispatches
  run on a `ThreadPoolExecutor`. Each dispatch already owns its event
  loop (`asyncio.run` per call), so the three do not share one. The
  synchronous dispatcher signature and the per-agent retry loop are
  unchanged, and the verdict list is still returned in dispatch order,
  so the aggregation rule the caller applies is unchanged.
- Isolation is in the dispatch itself: `pool_route_execute` is called
  with `worktree={"isolation": "worktree", "on_completion":
  "discard"}`. A reviewer gets its own checkout, and anything it writes
  there is discarded — a reviewer must not merge anything back.
- The worktree is created **from the branch under review**, not from
  the merge base. The base branch belongs to stage 4's rebase; a
  reviewer's checkout has to hold the code being reviewed.
- Isolation is **verified**. The pool skips the worktree silently when
  it cannot resolve the repository, and a pool type that cannot honour
  a working directory refuses the task outright. Either way the
  reviewer would be sharing the main checkout with every other
  session — the situation where a reviewer ran `git stash` in another
  session's work on 2026-11-06. A dispatch that comes back without an
  isolated checkout returns an explicit block verdict, and the merge
  stops.
- **Isolation that cannot be provided is refused before the worker
  runs**, not after. The check that follows a dispatch is post-hoc by
  construction — the reviewer has already run by then — so it is a
  detector, not a guard. The guard is upstream: the pool refuses to
  dispatch when the repository to isolate cannot be resolved, so the
  reviewer is never started in the shared checkout. The post-hoc
  check stays, because the pool can still hand the task to a pool
  type that ignores the directory.
- **The repository to isolate is named in the prompt.** The server
  resolves it from a `.git`-suffixed token, and the merge pipeline
  puts that token in the prompt. The server's own working directory
  is its *own* checkout, so a relative token can only ever name a
  repository beside it — which is why the token is absolute for a
  repository that is not the server's own. Without it, every
  cross-repo merge — into session-buddy, crackerjack, akosha, oneiric
  or mcp-common — asked for a worktree of a branch that does not
  exist in the server's repository, and died at stage 2.
- **A token is read from a `Repository:` line, not from anywhere in
  the prompt.** The first implementation scanned every token for a
  `.git` suffix, which meant a prompt that merely *mentioned* a
  repository named one: a URL in a bug report
  (`https://example.com/repo.git`) or an SSH remote in a clone
  instruction became the isolation target, was refused as
  unauthorized, and the dispatch never happened. Only a line that
  introduces the repository counts now, so prose stays prose and the
  caller gets the behaviour it had before this decision.
- **Naming a repository is a security boundary, and the server checks
  it.** Creating a worktree of a repository and running a worker in it
  means the repository is a privilege, not a convenience, so the
  resolved path is canonicalized and required to sit inside one of the
  operator's allowed repository roots (`allowed_repo_paths`), using the
  same `PathValidator` the rest of the codebase uses. A repository the
  operator has not authorized is refused the same way an unresolvable
  one is: the dispatch does not happen. The token travels in the
  prompt rather than in a new request field, so a pool server that
  predates the change still accepts the request — it simply ignores
  the token and falls back to its own repository.
- **The server's own checkout is authorized by configuration.** The
  operator installed it there, and a dispatch that names no repository
  resolves to it. The configured default for `allowed_repo_paths` used
  to be one operator's directory, so on a host that does not have it
  every isolation dispatch was refused — and the refusal read as "your
  prompt is wrong" rather than "this host's settings do not match".
  The default is now the server's own checkout, and the deployment
  config adds the fleet's roots beside it.
  **The allowlist is never widened at validation time.** Appending the
  process's working directory to the configured roots would make the
  effective boundary depend on where the server happens to be running,
  which is not a decision the operator made about which repositories
  may be isolated. The boundary is the configured set, checked with the
  shared `PathValidator` — which resolves the path, resolves the roots,
  and requires the path to sit inside one of them.
  An empty allowlist still authorizes nothing: that is a deliberate
  deny-all, not an unconfigured default.
  **The blast radius is still the operator's to configure:** isolating
  a branch in *another* repository needs that repository inside
  `allowed_repo_paths`, and on a host that does not share the
  configured roots, a cross-repo merge stops at stage 2 until the
  operator adds it. The server's own repository is the only one that
  works out of the box.
- **The reviewer is told the budget that is real.** The dispatch's
  server-side budget is an hour, but the call cannot last that long:
  the MCP client's read timeout cuts a response stream that has gone
  quiet, so the reviewer is torn down mid-review after a few minutes
  — and a reviewer that is torn down has no verdict at all, so its
  review counts for nothing rather than counting as a failure. The
  prompt states the budget that binds and tells the reviewer to work
  from the diff summary and read only the files it needs. Pinning the
  constant would not have caught this: the constant can be an hour
  while the transport allows three minutes.
- **A refusal names the reason, because the remedy differs.** An
  unauthorized repository is a policy decision, a repository that does
  not resolve is a wrong prompt, a path that is not a git working tree
  is the wrong path, and unreadable settings are a broken server.
  One message covering all four sends the operator to fix the wrong
  thing, so each has its own text — and each is counted under its own
  `worktree_isolation_refusals_total{reason=...}` label.
- **The pipeline supplies the capability its own dispatch needs.**
  Isolation needs a pool whose worker session *starts* in the
  worktree, and only a one-shot SHELL worker does that. The
  auto-spawned pool is a pre-spawned shepherd pool, which cannot, so
  enforcing the capability without providing it meant every merge
  stopped at stage 2 with an instruction to spawn a pool by hand. The
  merge pipeline provisions one (`merge-review`, a one-shot
  `terminal-claude` pool), and skips the work entirely when a
  registered pool already reports `supports_working_directory`. The
  pool list carries that flag so a client can tell which pools can
  honour a directory at all.
- **A dispatch that never happened is reported as what it is.** When
  the pool raises — no pool can honour the directory, the repository
  cannot be resolved — the error text comes back instead of a result.
  Reporting that as "the review ran without an isolated checkout"
  replaces the real reason with a misleading one.
- **The reviewer's reply has a budget, and the prompt says so.** The
  pool captures the worker's terminal scrollback and keeps the newest
  bytes within a fixed bound. A reply that runs past the bound arrives
  with its beginning cut off, and a verdict block whose opening tag was
  cut cannot be read, so the review is lost rather than counted. The
  prompt tells the reviewer the budget and that the verdict block must
  be the last thing it writes. (The capture used to read only the
  visible screenful — about 1,500 characters — which put that bound far
  lower than it needed to be; see
  `2026-11-15-review-capture-window.md`.)
- The capability constraint travels with the **re-ranking** steps. The
  queueing re-rank picks the pool with the lowest predicted wait across
  the candidate set, and the GPU override prefers a runpod pool — either
  can move a directory-bearing task onto a pool that ignores the
  directory (`SessionBuddyPool`, `RunPodPool` and `PiPool` all do).
  That lands the reviewer in the shared checkout: the 2026-11-06
  failure, reached through a different door — and the isolation check
  still passes, because the worktree key says a worktree was
  *created*, not where the worker ran. So the constraint narrows the
  re-rank's candidate set rather than being checked once and
  forgotten, and a final fail-closed check refuses a dispatch that
  ended up on a pool that cannot honour the directory.
- The ephemeral branch is discarded with the worktree.
  `git worktree add -b` creates a branch as a side effect, and removing
  the worktree does not remove that branch — so every isolated dispatch
  leaked a branch, and three concurrent reviewers leaked three per
  merge. `on_completion="discard"` now deletes the branch too.
- The retry-on-unreadable-verdict behaviour is untouched: a reviewer
  whose reply could not be read is still retried once, and a second
  failure still blocks. Concurrency did not weaken the gate; it changed
  how long the gate takes.

## Consequences

- A review costs the slowest reviewer, not the sum of the three.
- A reviewer can no longer disturb another reviewer, because it is not
  in the same checkout.
- The review prompt spells out the worktree path and tells the
  reviewer that its shell is a separate checkout, so a reviewer reads
  the branch under review by absolute path whatever its shell landed
  on.
- Each verdict carries the wall-clock seconds its dispatch took, and
  the operator's summary prints it — the concurrency win is measurable
  rather than asserted.
- One behavioural difference: if a dispatcher raises outright, the
  sequential version aborted at once, while the concurrent version waits
  for the other two reviews to finish (they cannot be cancelled — a
  running thread cannot be killed). In practice `dispatch_review`
  catches every transport failure and returns a fail-loud reply, so the
  raise path is a corner case.
- A merge whose pool cannot isolate now stops at stage 2 with an
  explicit reason instead of running three reviewers in the shared
  checkout. That is a stricter gate than the sequential version had,
  and deliberately so.
- **The new failure modes are counted.** Every refusal — an
  unauthorized repository, an unresolved one, a path that is not a git
  tree, unreadable settings, no pool able to honour a directory — is a
  `worktree_isolation_refusals_total{reason=...}` increment, and the
  worktree counters the runbook cites (`worktree_creation_total`,
  `worktree_active_count`) are now written by the dispatch path that
  owns them. A refusal that only logs is a silence the on-call
  engineer cannot hear, and a gauge that always reads zero is worse
  than no gauge: it says the disk is free while worktrees exist. The
  `worktree_disk_bytes` gauge was retired for that reason — it was
  declared and never written — and the runbook says to use `df -h`
  and `git worktree list` instead.

## Known boundaries

Two limits of the isolation check, stated so the next reader does not
have to rediscover them.

- **The check proves a worktree was created, not that the worker ran
  in it.** The dispatch result reports the worktree the pool created;
  it does not report the directory the worker session actually started
  in. A pool type that ignores `task["cwd"]` would create the
  worktree and run the worker somewhere else, and the check would
  still pass. `MahavishnuPool` refuses a task it cannot honour
  (`mahavishnu/pools/mahavishnu_pool.py:447`) rather than ignoring
  it, so the fleet's own pools fail loud. The routing that ships here
  narrows the candidate set to pools that report
  `supports_working_directory`, so `SessionBuddyPool`, `RunPodPool`
  and `PiPool` — which ignore the directory — are not reachable by a
  task that names one, rather than being reachable and ignoring it.
  The residual limit is a pool that *reports* the capability and does
  not honour it; closing that needs the pool to report the cwd it
  used, which is a pool-protocol change beyond this decision's scope.
- **The `path` field needs a server that carries it.** The check
  verifies on the presence and non-emptiness of the `worktree` key,
  which every server version sets after a worktree is created, so a
  server that predates `path` still verifies. `path` is logged when
  present.

The context the check reads is **server-attested**, not
agent-controlled: it is a sibling key of the dispatch envelope, set by
the pool tool after `create_worktree` succeeds. The reviewer's reply
travels in the separate `output` field, where a string cannot forge a
sibling key of the envelope it sits in.

## References

- `mahavishnu/core/merge_to_main.py` — `run_review` (concurrency) and
  `run_pipeline` (the isolation option).
- `mahavishnu/core/merge_review_dispatcher.py` — `dispatch_review`,
  which forwards the option to the pool tool.
- `docs/decisions/2026-11-15-dispatch-worker-working-directory.md` —
  the fix that makes a worktree-isolated worker actually *run* in its
  worktree rather than editing the source checkout.
- `docs/runbooks/WORKTREE_ISOLATION.md` — the operational guide for
  worktree-isolated dispatch.
