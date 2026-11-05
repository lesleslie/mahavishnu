---
status: complete
role: superseded
kind: plan
date: 2026-11-01
last_reviewed: 2026-11-01
superseded_by: docs/plans/2026-11-01-control-plane-consolidation.md
topic: worker-dispatch-trustworthiness
title: "Terminal CLI harness demos and a trustworthy one-shot dispatch protocol"
---

> **SUPERSEDED (2026-11-01)** by
> `docs/plans/2026-11-01-control-plane-consolidation.md`. This plan is
> retained for traceability only. Its Phase 1 and Phases 3-4 become that
> plan's Phase 7 and Phase 8; its Phase 2 is replaced by reuse of
> `WorkerLifecycleState`; its REQ-009 becomes that plan's Phase 6; its
> REQ-010 becomes that plan's Phase 8. Two of its claims are corrected
> there: the worker adapter already existed and was already registered
> in `app.adapters`, and no substrate — engine or worker — is costed,
> because `enable_cost_tracking` is a dead parameter and `CostOptimizer`
> has no production caller.

# Terminal CLI harness demos and a trustworthy one-shot dispatch protocol

## 1. Outcome

A `mahavishnu demo terminal-claude`, `demo terminal-qwen`, and
`demo terminal-codex` exist, and each one **proves the whole one-shot
dispatch chain works** — the prompt reaches the CLI, the CLI's answer
comes back, and a failed CLI is reported as a failure rather than as a
success.

Underneath the demos, the one-shot dispatch protocol gains the three
properties Claude Code's background-worker daemon has and we did not:

- **Explicit terminal state** — "completed" means the work settled, not
  that a process ended.
- **A readiness handshake** — the dispatch is not "running" until the
  CLI demonstrably has the prompt.
- **Prompt integrity** — the bytes the CLI read are verified against a
  digest the worker wrote.

Success signal:

```bash
mahavishnu demo terminal-claude
# -> status: completed
# -> answer: DISPATCH-OK
# -> the CLI's answer is echoed, not just its exit status

mahavishnu demo terminal-codex      # on a limited account
# -> status: skipped
# -> reason: codex account is usage-limited until 2026-11-19
```

## 2. Goals

1. Add `demo terminal-claude`, `demo terminal-qwen`, and
   `demo terminal-codex`, each driving a real one-shot pool dispatch of
   a prompt and asserting the CLI's answer.
2. Make the demos **skip cleanly** when the CLI is missing, unauthenticated,
   or usage-limited — a demo that fails because the operator's codex
   account is exhausted is noise, not signal.
3. Replace "the process ended" with "the work settled": the pool owns a
   dispatch state machine whose terminal states cannot be reversed by a
   later poll.
4. Add a readiness handshake so a dispatch is not reported as running
   until the CLI has demonstrably received the prompt.
5. Verify the prompt the CLI read against a digest the worker wrote,
   and fail the dispatch on a mismatch.
6. Add a demo that composes an **engine adapter with a terminal
   worker** in one workflow — the composition no demo currently
   exercises, and the one the `workflow-pool-worker-terminal`
   docstring already promises.
7. Correct the `workflow-pool-worker-terminal` docstring, which
   advertises a "Prefect -> pool -> worker -> terminal" E2E that its
   implementation does not contain.

## 3. Non-Goals

1. **Not** building a daemon, a rendezvous socket, or a lease manager.
   Claude Code's daemon exists to serve *long-lived background agents
   you attach to*. Our workers are *one-shot CLI harnesses*: a session
   per prompt, torn down when it is done. The transferable part is the
   **state machine**, not the process architecture. (See §4.4.)
2. **Not** replacing the worker layer with an engine's built-in workers.
   The engines cannot run a third-party agent CLI. (See §4.3.)
3. **Not** changing the `terminal-crow`, `terminal-shell`,
   `terminal-python` and other non-one-shot worker types.
4. **Not** adding a `demo terminal-deepagents` / `demo terminal-clai`.
   The three in scope are the ones with a working CLI on this host and
   a documented non-interactive invocation. The other two are covered by
   the same registry tests.

## 4. Current Findings

### 4.1 The broken path, and why the demos never caught it

Four bugs sat on the one-shot dispatch path, and **every unit test was
green through all four**. They were found only by a live dispatch
(2026-11-01):

| Bug | Symptom | Root cause |
|---|---|---|
| `claude -p` without `--verbose` | CLI exits instantly, dispatch reports `completed` with empty output | `claude --help`: `--output-format=stream-json` requires `--verbose` with `--print` |
| completion marker as a false success | same | the shell printed `__MAHAVISHNU_DONE__` when the CLI exited, whatever the exit status |
| `WorkerManager(settings=None)` | every dispatch refused: `[MHV-312] workers disabled by config` | `MahavishnuPool` never passed settings, so `workers.enabled` resolved to `None` → False |
| `worker_ids` unbound | `pool_spawn` failed | `MahavishnuPool.start()` referenced the variable outside the branch that assigns it |

**Why the demo suite missed all of it:** no `mahavishnu demo` command
uses `terminal-claude`. The demos split around the broken path:

- `demo prefect` / `agno` / `llamaindex` / `pydantic_ai` / `hatchet`
  drive the **engine adapters** directly and use no worker at all.
- `demo pool-mahavishnu` and `demo workflow-pool-worker-terminal`
  dispatch a **command** — their own docstring says *"the dispatched
  task is a command, not a prompt"* — to the shepherd/isolated worker.
- `demo pool-pi` and `demo workflow-pi-*` use **PiPool**, which passes
  the prompt as a subprocess **argv** entry, not through tmux.

The broken path was a **prompt** delivered to a **terminal CLI
harness** — exactly the one no demo exercised. That is the gap this
plan closes.

### 4.2 Which fixes are universal and which are per-CLI

The fixes applied on 2026-11-01 split cleanly by layer:

| Fix | Layer | Applies to |
|---|---|---|
| prompt travels in a file (tmux argv caps at ~16-24 KB) | tmux | **all** one-shot workers |
| per-task session instead of a pre-spawned pool of idle sessions | pool | **all** SHELL-runtime one-shot workers |
| settings wired into `WorkerManager` | pool | **all** worker types |
| `rc=$?` in the completion marker | registry/shell | **all** one-shot workers |
| `--verbose` on `claude -p` | CLI flag | **claude only** |

So the qwen and codex paths received the universal fixes. What remains
**per-CLI** is the invocation shape, and it differs:

- **claude** — `claude -p --verbose --output-format stream-json`. Needs
  `-p` (non-interactive) *and* `--verbose`.
- **qwen** — `qwen -o stream-json --approval-mode yolo "<prompt>"`.
  Verified live on this host: emits a `{"type":"result","subtype":"success"}`
  envelope and exits 0. **No further change needed.**
- **codex** — `codex exec --json --sandbox workspace-write "<prompt>"`.
  Two defects in the current registry command, both found by smoke test:
  1. `codex exec` **reads additional input from stdin**. In a tmux pane
     stdin is the terminal, so the CLI *blocks* waiting for input that
     never comes. The command must close stdin (`< /dev/null`).
  2. Outside a trusted directory it refuses with *"Not inside a trusted
     directory and --skip-git-repo-check was not specified"* and exits
     non-zero. It needs `--skip-git-repo-check`.

  With both fixed, codex ran and exited **rc=1** with
  `{"type":"error","message":"You've hit your usage limit..."}` — the
  account is usage-limited until 2026-11-19. That is exactly the shape
  the new exit-code protocol is for: a genuine failure, reported as a
  failure.

### 4.3 The engine adapters have their own workers — and that is not the same thing

**No engine adapter calls our `WorkerManager`.** The only reference is a
stub in `mahavishnu/engines/__init__.py:84` whose `spawn_workers`
returns `[]`, used for capability loading only. The engines run work
through their own substrates:

| Engine | Its own execution substrate |
|---|---|
| Prefect | `client.create_flow_run(...)` → **Prefect's** work pools and process workers |
| Hatchet | Hatchet's own workers |
| LlamaIndex | in-process, no workers |
| Agno | in-process agent loop, no workers |

**Do we still need our own workers?** Yes — but for a different job.
The distinction is *what is being executed*:

- **Engine workers** execute a *flow or agent loop the engine defines*.
  The engine owns the lifecycle, the retries, the concurrency limits.
- **Our workers** execute *third-party agent CLIs* — the `claude`,
  `qwen`, `codex` binaries — that no engine knows about. Prefect's
  process work pool could run `claude -p "..."` as a task, but then
  Mahavishnu's worker registry, the permission modes, the Bifrost env
  injection, and the prompt-integrity guarantees would all have to be
  rebuilt as Prefect tasks.
- The **shepherd** worker is a separate reason: it provides an OS-level
  syscall jail (fail-closed). Prefect's process worker has no jail.

So the worker layer earns its place by doing what the engines cannot,
not by competing with them. The corollary for this plan: the worker
layer must be *trustworthy on its own terms*, because it is not backed
by an engine's state tracking. That is precisely the gap the three
adopted capabilities close.

**No demo composes an engine adapter with a terminal worker, and no
code path executes a sequence of adapters.** The evidence:

| Demo | Composes | Engine leg? |
|---|---|---|
| `prefect`, `agno`, `llamaindex`, `pydantic_ai`, `hatchet` | one engine adapter | ✅ but no worker |
| `workflow-pool-worker-terminal` | pool → worker → terminal (3 stages) | ❌ |
| `workflow-multi-pool-handoff` | two pools | ❌ |
| `workflow-adapter-swap` | pool twice, swapping the **terminal** adapter (mock ↔ tmux) | ❌ |
| `workflow-pi-cascade`, `workflow-pi-then-local` | PiPool + local path | ❌ |
| `crow` | the crow **terminal adapter** — not a terminal *worker* | ❌ |

The `workflow-pool-worker-terminal` docstring says *"For the
operator-facing E2E (Prefect -> pool -> worker -> terminal), use
`mahavishnu demo workflow-pool-worker-terminal` instead."* — but its
implementation is three stages with **no Prefect leg**. The docstring
advertises exactly the composition this plan adds, and it is not
there.

The mechanism is a **fallback, not a sequence**. `TaskRouter`'s chains
are AGNO / LLAMAINDEX / PREFECT, and `execute_workflow_with_fallback`
(`mahavishnu/core/workflow_execution.py:647`) tries each until one
succeeds. `AdapterType.WORKER` is in **no** chain, so the router
structurally cannot produce an engine→worker composition. The two
substrates meet only at the MCP tool surface (`pool_route_execute`
vs an engine's `execute`).

Two costs of that gap, both concrete:

- **No unified execution.** An engine run gets an `execution_id` and a
  cost rollup through `mahavishnu/core/cost_optimizer.py`
  (`ADAPTER_COSTS` per adapter, `record_cost`). A pool dispatch has
  **no cost accounting at all** — `PoolMetrics` carries
  `tasks_completed`, `tasks_failed`, `avg_task_duration`, and no cost.
  A composition therefore has two cost accounts and no rollup.
- **No unified observability.** The two legs have separate execution
  ids and separate span trees, so "what did this workflow cost, end to
  end" has no answer today.

Making that a *product* capability rather than a demo is option B, and
it is scoped separately in
`docs/plans/2026-11-01-adapter-composition-executor.md`. This plan
delivers only the **demo-level** composition (option A), because the
executor is an architectural change to the control plane and does not
belong inside a dispatch-trustworthiness plan.

### 4.4 What to take from Claude Code's daemon — and what not to

Claude Code's background workers use a daemon plus a rendezvous socket
and a structured control protocol. The relevant protocol fields are
`onDispatch`, `carriedPromptsFormat`, `CLAUDE_BG_CARRIED_PROMPTS_SHA256`,
`addLease`/`listLeases`, `whenReady`, `settledDispatches`, `nextTurn`,
`alive`, `reapWorkers`.

**Take:**

- *Settled dispatches and terminal states* — a dispatch is settled once,
  and settling is final. Our bug #2 was the absence of exactly this.
- *`whenReady`* — an explicit readiness signal before dispatch proceeds.
  We have `_await_ready()`, but it is a **blind wait** on the interactive
  path only (it waits for the pane to draw), and the one-shot path has
  no equivalent at all.
- *Carried prompts with an integrity digest* — the prompt that crosses a
  process boundary is hashed, so a truncated or swapped payload is
  detectable rather than silently wrong.

**Do not take:**

- *The daemon, the rendezvous socket, PTY auth, leases.* They exist to
  support long-lived background agents with attach/detach semantics. Our
  worker is one-shot: a session per prompt, torn down on completion.
  A per-task session **is** the lease. Building a daemon would add a
  persistent process, a wire protocol, and a class of bugs we do not
  have.
- *The teammate pane backends.* We already have the equivalent shape:
  `mahavishnu/terminal/adapters/` (tmux / crow / mock) is our
  `teammateMode` registry.

Claude Code's own teammate backends are `auto | tmux | iterm2 |
in-process` — it *does* use tmux as a pane backend for agent swarms,
with an in-process fallback. Ours already matches.

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-001
    title: "A demo terminal-claude command dispatches a prompt through a one-shot terminal-claude pool and asserts the CLI's answer"
  - id: REQ-002
    title: "A demo terminal-qwen command dispatches a prompt through a one-shot terminal-qwen pool and asserts the CLI's answer"
  - id: REQ-003
    title: "A demo terminal-codex command dispatches a prompt through a one-shot terminal-codex pool and asserts the CLI's answer"
  - id: REQ-004
    title: "The three demos skip rather than fail when the CLI is absent, unauthenticated, or usage-limited"
  - id: REQ-005
    title: "The pool owns a dispatch state machine whose settled states are terminal and cannot be reversed by a later poll"
  - id: REQ-006
    title: "A one-shot dispatch reports a non-zero CLI exit as FAILED, distinct from a successful settle"
  - id: REQ-007
    title: "A one-shot dispatch waits for an explicit readiness signal before it is reported as running"
  - id: REQ-008
    title: "The prompt the CLI read is verified against a digest the worker wrote, and a mismatch fails the dispatch"
  - id: REQ-009
    title: "A demo composes an engine adapter with a terminal worker in one workflow and shows both legs settling"
  - id: REQ-010
    title: "The workflow-pool-worker-terminal docstring describes the stages its implementation actually contains"
```

Marker placement (the `scripts/audit_requirements.py` gate reads these):

- REQ-001/002/003 → `# req: REQ-00N` in `mahavishnu/cli/demo_cli.py` at
  each demo function.
- REQ-004 → `# req: REQ-004` on the demo's skip helper.
- REQ-005/006 → `# req: REQ-00N` in `mahavishnu/pools/mahavishnu_pool.py`.
- REQ-007/008 → `# req: REQ-00N` in `mahavishnu/workers/shell_backend.py`.

## 5. Implementation Phases

### Phase 1: Three CLI harness demos

**Goal:** every one-shot CLI harness on this host has a demo that
drives a real dispatch and asserts the CLI's answer.

**Tasks:**

1. **Fix the codex invocation** in `mahavishnu/workers/registry.py`
   and its mirror in `settings/mahavishnu.yaml`:
   - add `--skip-git-repo-check`,
   - close stdin (`< /dev/null`) so `codex exec` does not block
     waiting for terminal input.
   Add a registry test that every one-shot command closes stdin, or
   documents why it does not need to.
2. **Add a shared demo helper** in `mahavishnu/cli/demo_cli.py`:
   `_run_terminal_harness_demo(worker_type, *, prompt, timeout)`, which
   spawns a one-shot `MahavishnuPool` for that worker type, dispatches
   the prompt, asserts the answer appears in the output, and tears the
   pool down. The demo prints the CLI's **answer**, not just its status
   — the answer is the thing that proves the chain.
3. **Add the three commands** — `demo terminal-claude`,
   `demo terminal-qwen`, `demo terminal-codex` — each with a `--timeout`
   and a `--keep` flag for debugging.
4. **Skip logic** (REQ-004): before dispatching, check the CLI is
   present (`shutil.which`) and, for codex, that the account is usable.
   A usage-limited or unauthenticated CLI is a **skip** with a reason
   printed, not a failure.
5. **Register the demos in the demo index** and add them to
   `demo all` only if the skip logic makes that safe — `demo all` must
   not go red because one account is exhausted.
6. **Add the engine + worker composition demo** (REQ-009):
   `demo workflow-engine-and-worker`. It runs an engine adapter leg
   (Prefect by default) to produce a task, then hands the result to a
   `terminal-claude` pool to execute it, and narrates both legs as
   stages. It is the composition no demo currently exercises.
   - The composition is written **in the demo**, not in the engine: the
     demo calls the engine adapter and then the pool explicitly. It
     does not require a chain executor (option B, scoped separately).
   - It is **slow** — a CLI-harness leg is ~115 s for a trivial prompt
     (the CLI's own startup and repo-context load dominate), so the
     demo carries a generous default timeout and is **not** added to
     `demo all`.
   - It reuses the Phase 1 skip logic for the harness leg.
7. **Fix the stale docstring** on `workflow-pool-worker-terminal`
   (REQ-010): it currently claims to be the "Prefect -> pool -> worker
   -> terminal" E2E while implementing three stages with no Prefect
   leg. Either implement the Prefect leg or correct the text — this
   plan corrects the text and points at the new composition demo.

**Exit criteria:** all three demos run; claude and qwen print
`DISPATCH-OK`; codex prints a skip reason on this host; a demo run on
a machine with no `qwen` skips rather than fails; the composition
demo shows both legs settling.

#### Integration Contract

- **Triggered from:** `mahavishnu demo terminal-claude` (Typer command
  `demo_terminal_claude` in `mahavishnu/cli/demo_cli.py`), also
  reachable as `mahavishnu demo all`. The composition demo is
  `mahavishnu demo workflow-engine-and-worker`.
- **Returns to / updates:** mutates nothing persistent. The demo spawns
  and tears down a pool in-process; the pool's `tasks_completed` /
  `tasks_failed` counters and the dispatch state are in-process only.
- **Demonstrable by:** `mahavishnu demo terminal-claude` prints
  `status: completed` and `answer: DISPATCH-OK`; and
  `pytest tests/unit/cli/test_demo_terminal_harnesses.py` passes.
- **Rollback signal:** the demo prints `status: failed` — a demo that
  cannot drive its own harness is noise, and `demo all` goes red.
- **Observability added:** structured log lines
  `demo.terminal_harness.started` / `.settled` / `.skipped` carrying
  `worker_type`, `status`, `duration_seconds`, `skip_reason`; and for
  the composition demo, `demo.composition.stage_settled` carrying
  `stage`, `engine`, `worker_type`, `status`, `duration_seconds`.

### Phase 2: The pool owns the dispatch state machine

**Goal:** "completed" means the dispatch *settled*, and settling is
final.

**Tasks:**

1. Add a `DispatchState` enum to `mahavishnu/pools/base.py`:
   `IDLE → DISPATCHED → RUNNING → SETTLED`, where `SETTLED` carries the
   outcome (`COMPLETED` / `FAILED` / `TIMEOUT` / `CANCELLED`).
2. Move the transition ownership into `MahavishnuPool`: the pool is the
   single writer of a dispatch's state. `ShellWorker` reports an
   *outcome*; the pool decides the *state*.
3. Make the settled state terminal — a later poll (the worker's
   progress callback, a `pool_monitor` read) may not move a settled
   dispatch back to `RUNNING`. This is the "a stale poll can assert a
   completed" hole.
4. Extend the completion marker to carry the outcome explicitly rather
   than inferring it:
   `__MAHAVISHNU_DONE__ rc=<code>` already exists; add
   `state=<settled-state>` so the marker and the pool agree.
5. When the CLI's output format provides its own result envelope,
   **parse it** rather than trusting the exit code alone. Claude's
   `stream-json` ends with `{"type":"result","subtype":"success","is_error":false}`;
   qwen's with `{"type":"result","subtype":"success","is_error":false}`. A
   non-zero `is_error` or a non-`success` subtype is a failure even
   when the process exited 0.
6. Expose the state: `pool_route_execute` returns it, `pool_monitor`
   reports it, and the pool's metrics gain a `dispatches_settled`
   counter.

**Exit criteria:** a dispatch whose CLI exited 0 but whose result
envelope says `is_error: true` is reported FAILED; a settled dispatch
never reverts; the state is visible in the MCP responses.

#### Integration Contract

- **Triggered from:** `mcp__mahavishnu__pool_route_execute` →
  `MahavishnuPool.execute_task` (`mahavishnu/pools/mahavishnu_pool.py`).
- **Returns to / updates:** the dispatch's state in the pool's
  in-memory dispatch record, and the `status` field of the
  `pool_route_execute` response. Surfaced by
  `mcp__mahavishnu__pool_monitor`.
- **Demonstrable by:** `pytest tests/unit/pools/test_dispatch_states.py`
  — a CLI that exits 0 with `is_error: true` yields FAILED; a settled
  dispatch stays settled across a later poll.
- **Rollback signal:** `pool_route_execute` returning `status:
  running` for a dispatch that has already returned is a regression;
  the metric `mahavishnu.pool.dispatches_settled` stops incrementing.
- **Observability added:** metric `mahavishnu.pool.dispatches_settled`
  (labelled by `state` and `worker_type`) and log line
  `pool.dispatch.settled` carrying `pool_id`, `worker_id`, `state`,
  `exit_code`, `duration_seconds`.

### Phase 3: The generated launcher and the readiness handshake

**Goal:** the dispatch is not "running" until the CLI demonstrably has
the prompt.

**Tasks:**

1. **Move the launch protocol out of the command string and into a
   generated script.** Today `render_command` prepends a shell prologue
   to read the prompt file. That prologue grows unreadable as it takes
   on hashing and readiness. Instead the worker writes a small generated
   launcher next to the prompt file and the registry command invokes it:
   - the launcher reads the prompt file into `MAHAVISHNU_PROMPT`,
   - exports it,
   - emits `__MAHAVISHNU_READY__` with the prompt's byte count,
   - then `exec`s the registry command.
   The prompt still never becomes shell text — the launcher reads it
   into a variable and expands it quoted — so the injection property is
   preserved.
2. **The worker waits for `__MAHAVISHNU_READY__`** before the dispatch
   is reported as running (REQ-007). Today the one-shot path has no
   readiness step at all: the worker starts polling for the completion
   marker immediately.
3. **Replace the blind `_await_ready()` wait** on the interactive path
   with the same explicit signal where the CLI provides one, keeping
   the pane-draw wait as the fallback for CLIs that do not.
4. **A readiness timeout is a failure**, not a hang: a CLI that never
   signals ready within the task's timeout fails with a distinct error.

**Exit criteria:** the dispatch record shows `DISPATCHED` until READY
arrives, then `RUNNING`; a launcher that cannot read the prompt file
fails the dispatch instead of starting a CLI with an empty prompt.

#### Integration Contract

- **Triggered from:** `ShellWorker.start` →
  `mahavishnu/workers/shell_backend.py`, and
  `ShellWorker._await_completion` / `execute` for the wait.
- **Returns to / updates:** the dispatch's state (Phase 2) moves
  `DISPATCHED → RUNNING` only on READY; the readiness detail
  (`prompt_bytes`) is recorded in the worker's result metadata.
- **Demonstrable by:** `pytest tests/unit/workers/test_shell_launcher.py`
  — a launcher that exits before READY yields FAILED with a
  readiness error, not a timeout.
- **Rollback signal:** a `pool.dispatch.settled` for a dispatch that
  never logged a `pool.dispatch.ready` — a dispatch that settled
  without ever becoming ready means the handshake was bypassed.
- **Observability added:** log line `pool.dispatch.ready` carrying
  `pool_id`, `worker_id`, `prompt_bytes`, `ready_latency_seconds`.

### Phase 4: Prompt integrity

**Goal:** the bytes the CLI read are verified, not assumed.

**Tasks:**

1. The worker computes the **sha256** of the prompt it wrote and
   records it (REQ-008). The launcher computes the sha256 of the value
   it actually read and reports it in the READY marker.
2. The worker compares the two. A mismatch **fails the dispatch** with
   a distinct error naming the digest — a truncated or swapped prompt
   must never be silently wrong.
3. Where no portable hashing tool is available in the launch
   environment, the READY marker says `sha256=unavailable` and the
   worker records `integrity: "unverified"` in the result metadata
   rather than reporting a pass it did not perform.
4. The expected digest is also returned in the dispatch result, so an
   operator can verify a prompt after the fact.

**Exit criteria:** a prompt file modified between the worker's write
and the launcher's read fails the dispatch; an unverified prompt is
visibly marked unverified.

#### Integration Contract

- **Triggered from:** `ShellWorker._write_prompt_file` and the
  generated launcher (Phase 3).
- **Returns to / updates:** `prompt_sha256` and `integrity` in the
  dispatch result metadata, and the dispatch state (Phase 2) when the
  digests disagree.
- **Demonstrable by:** `pytest tests/unit/workers/test_shell_prompt_integrity.py`
  — a tampered prompt file fails the dispatch with the digest mismatch
  named.
- **Rollback signal:** any dispatch whose result reports
  `integrity: "unverified"` on a host that has `shasum` — the check
  silently stopped running.
- **Observability added:** log line `pool.dispatch.integrity` carrying
  `pool_id`, `worker_id`, `prompt_sha256`, `integrity`.

## 6. Required Code Changes

**`mahavishnu/workers/`**
- [ ] `registry.py` — codex invocation: `--skip-git-repo-check`, stdin
      closed.
- [ ] `shell_backend.py` — generated launcher (Phase 3), readiness
      wait (REQ-007), integrity verification (REQ-008), outcome parsing
      (Phase 2 step 5).
- [ ] `shell_backend.py` — `# req: REQ-007`, `# req: REQ-008`.

**`mahavishnu/pools/`**
- [ ] `base.py` — `DispatchState` enum.
- [ ] `mahavishnu_pool.py` — pool-owned transitions, terminal settled
      state, marker/outcome agreement.
- [ ] `mahavishnu_pool.py` — `# req: REQ-005`, `# req: REQ-006`.

**`mahavishnu/cli/`**
- [ ] `demo_cli.py` — `_run_terminal_harness_demo` helper, the three
      demo commands, the skip logic.
- [ ] `demo_cli.py` — the engine + worker composition demo
      (`workflow-engine-and-worker`) and the corrected
      `workflow-pool-worker-terminal` docstring.
- [ ] `demo_cli.py` — `# req: REQ-001`, `# req: REQ-002`,
      `# req: REQ-003`, `# req: REQ-004`, `# req: REQ-009`,
      `# req: REQ-010`.

**`settings/`**
- [ ] `mahavishnu.yaml` — mirror the codex invocation change (the
      registry-mirror test enforces this).

**`tests/`**
- [ ] `tests/unit/cli/test_demo_terminal_harnesses.py` — the demos are
      registered, skip cleanly, and assert the CLI's answer.
- [ ] `tests/unit/pools/test_dispatch_states.py` — the state machine.
- [ ] `tests/unit/workers/test_shell_launcher.py` — the launcher and
      the readiness handshake.
- [ ] `tests/unit/workers/test_shell_prompt_integrity.py` — the digest
      check.

**`docs/`**
- [ ] `docs/plans/PLAN_INDEX.md` — regenerated (not hand-edited) after
      this plan is promoted out of `draft`.

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `mahavishnu demo terminal-claude` | `status: completed`, `answer: DISPATCH-OK` | terminal output |
| `mahavishnu demo terminal-qwen` | `status: completed`, `answer: DISPATCH-OK` | terminal output |
| `mahavishnu demo terminal-codex` | `status: skipped` (account limited) or `completed` | terminal output |
| `mahavishnu demo workflow-engine-and-worker` | both legs settle; the harness leg's answer is shown | terminal output |
| `pytest tests/unit/cli/test_demo_terminal_harnesses.py` | pass | pytest |
| `pytest tests/unit/pools/test_dispatch_states.py` | pass | pytest |
| `pytest tests/unit/workers/test_shell_launcher.py` | pass | pytest |
| `pytest tests/unit/workers/test_shell_prompt_integrity.py` | pass | pytest |
| `pytest tests/unit/workers/ tests/unit/pools/ tests/unit/cli/` | pass | pytest |
| `crackerjack run -c -v` | 11/11 comprehensive hooks, 0 issues | hook report |
| `crackerjack run -f -v` | 18/18 fast hooks, 0 issues | hook report |
| `python scripts/audit_requirements.py` | every REQ id traced to code | script output |
| `python scripts/audit_orphans.py` | no new orphans | script output |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| The codex account stays usage-limited past 2026-11-19, so `demo terminal-codex` never goes green | medium | the demo skips with a reason; REQ-004 makes that a supported outcome, not a failure |
| The generated launcher becomes a second place the protocol lives | medium | keep the registry commands as the single source of the *CLI invocation*; the launcher only carries the protocol (read prompt, signal ready, exec) |
| The readiness handshake deadlocks a CLI that never signals it | low | a readiness timeout distinct from the task timeout, reported as FAILED |
| Hashing is unavailable in some launch environment | medium | `integrity: "unverified"` is recorded and logged, never silently passed |
| The pool-owned state machine conflicts with the legacy `WorkerOrchestratorAdapter` path | medium | Phase 2 changes the pool only; the adapter keeps its own contract until it is migrated, and the adapter is already covered by `test_submit_workers_runs_one_shot_lifecycle` |
| Adding three demos lengthens `demo all` | low | the demos skip fast when the CLI is absent; `demo all` treats a skip as a skip |
| The engine + worker composition demo is very slow (a CLI-harness leg is ~115 s) and nobody runs it | medium | it is excluded from `demo all`; it carries a generous timeout; its value is also as a CI nightly, not a per-commit gate |
| The state machine duplicates `WorkerStatus` | medium | `DispatchState` is the *pool's* view of a dispatch; `WorkerStatus` stays the *worker's* view. The mapping is explicit and tested |

## 9. Decision Rule

**This plan is done when:**

1. All three demos exist, run, and either assert the CLI's answer or
   skip with a reason — and the demo suite would have caught the four
   2026-11-01 bugs had it existed.
2. A dispatch's reported status comes from a state the pool owns, and
   that state is terminal once settled.
3. A dispatch is not reported as running until the CLI has the prompt,
   and the prompt's integrity is verified or explicitly marked
   unverified.
4. `crackerjack run -c -v` and `-f -v` are green, the new test files
   pass, and `audit_requirements.py` traces every REQ id.

**Cut order if scope must shrink:** Phase 4 (integrity) first — it is
defence in depth against a race with a tiny window. Then Phase 3's
interactive-path replacement (step 3), keeping the one-shot handshake.
Phases 1 and 2 are the irreducible core: without the demos the next
regression is invisible, and without the state machine a failed run
can still be reported as a success.

## References

- `docs/decisions/wire-up-contract.md` — the policy this plan
  implements.
- `docs/feature-tracking/TEMPLATE.md` — feature-state tracking for each
  wiring's lifecycle.
- `docs/plans/2026-07-21-worker-readiness.md` — the one-shot worker
  contract this plan extends.
- `docs/followups/2026-10-09-spawn-cli-stale-worker-allowlist.md` —
  the spawn-time allowlist contract.
- `docs/plans/2026-10-03-agent-reviewed-trunk-based-dev.md` — the
  review workflow a delivery of this plan goes through.
- `docs/plans/2026-11-01-adapter-composition-executor.md` — the
  separately-scoped plan for making the engine→worker composition a
  product capability (option B) rather than a demo.
- `mahavishnu/workers/shell_backend.py` — the launcher, readiness, and
  integrity code.
- `mahavishnu/pools/mahavishnu_pool.py` — the dispatch state machine.
- `mahavishnu/cli/demo_cli.py` — the demos.
