---
status: draft
role: implementation
date: 2026-08-29
last_reviewed: 2026-08-29
last_updated_phase_0: 2026-08-29
superseded_by: null
blocks_on: []
blocks_resolved:
  - docs/superpowers/plans/2026-08-29-worker-registry-capability-refactor.md  # shipped in v0.19.0 (commit bb51c537)
phase_0_status: refactor-solved  # see §5 Phase 0 update 2026-08-29; bug structurally impossible in v0.19.0's new tool pair
patch_doc_status: historical  # docs/fixes/2026-08-29-dispatch-to-pool-dead-letter-fallback.md — pattern reference only
topic: routing-composition
---

# Orchestrator Research Synthesis & Adoption Plan (v2 — Pivot)

**Date:** 2026-08-29
**Status:** `draft`, `implementation`
**Owner:** Core Eng
**Scope:** Mahavishnu (control plane), with cross-repo coordination for Oneiric, Crackerjack, Akosha, Session-Buddy.
**Purpose:** Adopt only what differentiates Bodai. Verify that v0.19.0's worker-registry refactor resolved the `dispatch_to_pool`/`workflow_result` contract violation, observe before committing to charter work, ship the cross-repo capability search that competitors structurally cannot build, and adopt Shepherd as a worker backend rather than reimplementing its security boundary in-house.

---

## Why this plan pivoted (v1 → v2)

v1 was a 6-phase feature list borrowed from four external projects (Shepherd, Prime Agent, Keystone, DeepSeek Harness) with no thesis about what Bodai uniquely is. The contrarian reviewer (`docs/plans/2026-08-29-orchestrator-research-synthesis.md` review #6, archived with this v2) caught the structural problem:

1. v1 spent five of six phases on capabilities competitors already ship (Keystone reimplementation, prime-agent-style goals, static-analysis security gates).
2. v1 had zero phases on the one thing competitors **structurally cannot build**: cross-repo state via Dhara + Akosha + Session-Buddy.
3. v1's Phase 2 was a quarter-scale architectural replacement routing around an **undiagnosed bug** (`workflow_result: not_found` — see memory `pool-dispatch-async-default.md`).
4. v1's Phase 6 proposed a static analyzer as a security boundary — defeated by `importlib`, `subprocess`, `socket`. Shepherd exists precisely because this approach doesn't work.
5. v1 cited a non-existent `docs/specs/2026-07-11-capability-driven-worker-registry.md` in `blocks_on` and a non-existent `mahavishnu/dispatch_to_pool.py` in §6 — the plan was not schedulable as written.

**v2 strategy:** Lead with the moat competitors can't build. Adopt Shepherd as a worker backend rather than reimplementing its security model. Bug-fix first, observe before charter work.

## 1. Outcome

When this plan ships, Bodai will have:

1. **`dispatch_to_pool(async_callback=True)` / `workflow_result` contract violation structurally eliminated by v0.19.0's worker-registry refactor** — `execute_capability` + `get_capability_result(trace_id)` is the new pair; the silent-no-op pattern that produced `not_found` cannot recur. Verified via MCP server restart + smoke-test (Phase 0).
2. **60-day Keystone observation window** completed with documented adoption data. Charter work is **conditional** on this observation, not committed.
3. **Cross-repo capability search and ecosystem-wide run history** shipped over Dhara + Akosha + Session-Buddy. The only capability in reach that Shepherd, Prime Agent, and Keystone structurally cannot build.
4. **Settle operations** shipped — "verify before trust," answering the 5 memories documenting unverified-agent-output failures (`agent-fix-verification.md`, `ty-small-fix-ghost-revert.md`, `drift-bundling-recovery.md`, `plumbing-commit-leaves-staged-revert.md`, `session-buddy-auto-checkpoint-bundling.md`).
5. **Shepherd as a worker backend** alongside `apple_container.py` and `e2b_sandbox.py` — real Seatbelt/Landlock syscall jails, no in-house static analyzer.
6. **Budget enforcement on `pool_route_execute`** — token/turn/wallclock limits without the per-turn bridge Non-Goal #3 forbids.

## 2. Goals

1. Verify the v0.19.0 worker-registry refactor resolved `workflow_result: not_found` structurally (the bug-path code was deleted at commit `30ebc0f3`); restart the MCP server and smoke-test the new `execute_capability` / `get_capability_result(trace_id)` round-trip.
2. Decide charter-framework investment based on 60 days of Keystone usage, not competitive analysis.
3. Ship the cross-repo capability-search moat that competitors structurally cannot build.
4. Adopt settle as a primitive that addresses documented failure modes, not as a Shepherd port.
5. Adopt Shepherd as a worker backend (one adapter) rather than reimplementing its capability-in-signature model (a static analyzer).
6. Enforce budgets on existing pool routing without introducing an in-kernel agent footprint.

## 3. Non-Goals

1. **Adopting Prime Agent's `/refine` self-improvement loop.** The Factorio eval demonstrates reward-hacking convergence. We borrow the *idea* of durable harness state but not the unconstrained loop.
2. **Replacing the Prefect adapter.** Prefect already provides durable run state, retries, and crash recovery. Phase 5 of v1 reinvented this without comparing against the incumbent. v2 stops at settling around Prefect, not replacing it.
3. **Reimplementing Keystone's 13-primitive type system in Oneiric.** If charter engineering proves valuable (Phase 0.5), `crackerjack charter` becomes a thin wrapper over `brew install tacoda/tap/keystone`. Vendoring an MIT binary beats owning a compiler for a 6-file problem.
4. **In-kernel agent primitives.** Non-Goal #3 from v1 stands: "Mahavishnu is a control plane, not an in-process agent." Phase 4 from v1's `await goal.get()` per-turn bridge is dead on arrival. v2's goal-equivalent is budget enforcement on pool runs, network-mediated only.
5. **In-house static analyzer as security boundary.** Phase 6 from v1. Defeated by `importlib`, `subprocess`, `socket`. Shepherd uses OS-level jails precisely because this approach is unsound. v2 adopts Shepherd; it does not reimplement its security model.
6. **Cross-repo file changes inside this repo.** v1 listed `oneiric/`, `crackerjack/`, and `akosha/` files under `mahavishnu/`. v2 explicitly opens PRs in the right repos; this repo's `Required Code Changes` lists only files that actually live here.
7. **Capability contracts** (signatures, capability registry, conductor, `execute_capability`, `get_capability_result`). These ship via [`docs/superpowers/plans/2026-08-29-worker-registry-capability-refactor.md`](../superpowers/plans/2026-08-29-worker-registry-capability-refactor.md) (Stage 2 + Stage 3a + Stage 3b). v2 does not duplicate that work. v2's Phase 1 (cross-repo capability search) depends on worker-registry's `Capability` registry but does not redefine it.

## 4. Current Findings

### 4.1 The four surveyed projects (recap)

| Project | Headline pattern | Verdict on adoption |
|---|---|---|
| **Shepherd** (`github.com/shepherd-agents/shepherd`, MIT, sponsored E2B/Tinker/Modal, arXiv 2605.10913) | Bodyless task signatures, OS-level sandboxing (Seatbelt/Landlock), settle operations | **Adopt as worker backend** (Phase 4) — get real enforcement for the cost of one adapter |
| **Prime Agent** (`github.com/primeintellect-ai/prime-agent`, 19k stars, arXiv 2608.23552) | RLM persistent IPython REPL, admission-handle sub-agent delegation, persistent goal primitive | **Borrow the durable-handle pattern; do not adopt `/refine` or in-kernel primitives** |
| **Keystone** (`github.com/tacoda/keystone`, v4.0.0 MIT, `brew install tacoda/tap/keystone`, no published adoption metrics) | Per-repo charter framework, hash-pinned policies, cascade resolution | **Observe for 60 days; thin wrapper if valuable, drop if not** |
| **DeepSeek Harness** (`github.com/deepseek-ai/deepseek-harness`) | Plugin-first via Cordis, host/client bundle split, vendored patches | **Borrow vendored-patches-for-pin, no other adoption** |

### 4.2 The competitor this plan was missing

| Project | Threat to v1's framing |
|---|---|
| **Prefect** (in-house, port 8675, "fully implemented, production-ready") | v1's Phase 2/3/4 reinvented durable execution; Prefect already provides it |
| **Anthropic Claude Skills** (`SKILL.md`, shipped Oct 2025, `anthropics/skills` repo, 6000+ plugins) | v1's Phase 1/5 are a projection layer Anthropic already shipped natively |
| **AGENTS.md** (60,000+ repos, OpenAI/Google/Cursor/Shopify/Block/Ramp/Canva backing) | Standards war decided; v1's "compile to many formats" value prop is obsolete |
| **LangGraph `interrupt()` + checkpointing** | Phase 2/3 settle pattern already shipped and adopted |
| **Temporal "Durable flexible multi-agent systems"** (Aug 2026) | Human-in-the-loop signals are settle ops, already shipped |
| **OpenAI Agents SDK / AgentKit** (handoffs, sessions, guardrails) | Phase 2 + Phase 6 in one SDK |

The internal `Prefect` adapter is the most directly relevant — `pool_route_execute` already routes through it. v2 respects this; v1 did not.

### 4.3 Why cross-repo state is the only durable moat

Shepherd is per-workspace. Prime Agent is per-session. Keystone is explicitly per-repo. **None of them have cross-repo persistent, searchable, ecosystem-wide memory.** Bodai does — Dhara + Akosha + Session-Buddy span every Bodai component. This is what Phase 1 of v2 ships.

## 5. Implementation Phases

### Phase 0: Verify v0.19.0's new tool pair resolves the `workflow_result: not_found` contract violation

**Goal:** Confirm that v0.19.0's worker-registry refactor (commit `bb51c537` / `30ebc0f3`) eliminated the silent-no-op + not_found bug pattern, and restart the running MCP server so the new tools are exposed. The dead-letter fallback pattern from `docs/fixes/2026-08-29-dispatch-to-pool-dead-letter-fallback.md` is kept as a *reference pattern* for future regressions of this shape — not a code patch to apply.

**Why this Phase pivoted:** As of v0.19.0:
- `dispatch_to_pool` and `workflow_result` are **deleted** (commit `30ebc0f3` "chore(mcp): remove deprecated pool/worker/dispatch tools (3b.3)"). The bug-path code no longer exists on `main`.
- `execute_capability` lives at `mahavishnu/mcp/tools/capability_tools.py:347`. Returns `status: "planned"` with `trace_id` (dispatch is Phase 4).
- `get_capability_result(trace_id)` lives at `mahavishnu/mcp/tools/get_capability_result_tool.py:21`. Reads Dhara envelopes via `mahavishnu/core/envelopes.py:list_envelopes`.
- The new `get_capability_result` requires `dhara: DharaClient` at registration time — passing `None` would fail registration loudly, not silently return `not_found`. The structural contract violation that produced the original bug **cannot recur** in the v0.19.0 tool pair.

**Tasks:**
1. `[Mahavishnu]` Read `mahavishnu/mcp/tools/get_capability_result_tool.py:21` and `mahavishnu/core/envelopes.py:64` to confirm the new read path. Document the contract: returns `status: "completed"|"pending"` with `envelopes: [...]` keyed by `trace_id`. Verify no silent-no-op fallback.
2. `[Mahavishnu]` Restart the running MCP server (PID 46863 is on a pre-v0.19.0 build per memory `2026-08-29-dispatch-to-pool-async-callback-root-cause.md`). Use `mahavishnu mcp stop && mahavishnu mcp start --background` or direct process replacement. Verify port 8680 responds to `discover_tools` and exposes `execute_capability` + `get_capability_result` (not the deleted pair).
3. `[Mahavishnu]` Smoke-test the new round-trip: call `mcp__mahavishnu__execute_capability(requires=["CODE_GENERATION"], prompt="phase-0-verify", trace_id="phase-0-verify-<timestamp>")` and read back via `mcp__mahavishnu__get_capability_result(trace_id=...)`. Confirm `status: "planned"` returns with a trace_id; `get_capability_result` reads back envelopes keyed by that trace_id.
4. `[Mahavishnu]` Verify failure-mode contract: if Dhara is intentionally disabled (`dhara_state.enabled=False`), `get_capability_result` should fail loudly (exception or `error` field), not silently return `pending`. Add a smoke test in `tests/integration/test_capability_result.py` for this scenario.
5. `[Docs]` Update `docs/feature-tracking/2026-07-11-dispatch-to-pool.md` to reflect that the bug was structurally eliminated by the v0.19.0 refactor, with the patch doc reclassified as a "pattern reference for silent-failure regressions" rather than an active fix.
6. `[Docs]` Add `docs/feature-tracking/2026-08-29-capability-tooling-migration.md` documenting the migration from `dispatch_to_pool`/`workflow_result` to `execute_capability`/`get_capability_result` for any external consumers.

**Exit criteria:**
- MCP server (port 8680) exposes `execute_capability` and `get_capability_result`; does not expose `dispatch_to_pool` or `workflow_result`.
- Smoke-test round-trip in Task 3 returns `status: "planned"` on dispatch and reads back via `get_capability_result` with matching `trace_id`.
- Dhara-disabled smoke test in Task 4 fails loudly (not `pending`).

#### Integration Contract — Phase 0

- **Triggered from:** MCP server startup (port 8680); test suite invoking `execute_capability` + `get_capability_result`.
- **Returns to / updates:** Tool registry on the running MCP server. Dhara envelope store at `akosha://envelopes/{trace_id}/*.json`.
- **Demonstrable by:** `pytest tests/integration/test_capability_result.py -v` exits 0 after dispatch + read-back. `mahavishnu mcp call execute_capability '{"requires":["CODE_GENERATION"],"prompt":"ping"}'` returns a `trace_id`; subsequent `mahavishnu mcp call get_capability_result '{"trace_id":"<id>"}'` reads back.
- **Rollback signal:** If `get_capability_result` returns `pending` instead of raising when Dhara is disabled, that means the silent-no-op pattern regressed. Apply the dead-letter fallback from `docs/fixes/2026-08-29-dispatch-to-pool-dead-letter-fallback.md` to the new code path (port the pattern, do not copy verbatim).
- **Observability added:** OTel span `capability.execute` and `capability.result`. Counter `capability.result.not_found_count` (target: 0 in 24h post-restart).

### Phase 0.5: Keystone observation window (60 days)

**Goal:** Decide charter-framework investment based on actual usage, not competitive analysis.

**Tasks:**
1. `[One-time]` `brew install tacoda/tap/keystone` (or download binary).
2. `[One-time]` Run `keystone init` against Mahavishnu, Akosha, Crackerjack repos.
3. `[One-time]` Run `keystone charter coverage` and `keystone charter conformance` against the three repos. Document results.
4. `[60-day window]` Re-run the coverage/conformance commands weekly. Track: does anyone (only the operator) open the dashboard? Does the conformance score improve over time? Do guides get added?
5. `[End of window]` Decision: thin `crackerjack charter` wrapper over `keystone` binary (if value demonstrated), or drop entirely (if not).
6. `[Followups]` Document the decision in `docs/followups/2026-XX-XX-keystone-observation.md`.

**Exit criteria:** After 60 days, either:
- (a) Thin wrapper plan exists and is approved for execution, OR
- (b) Decision recorded to drop charter work entirely.

#### Integration Contract — Phase 0.5

- **Triggered from:** Operator-initiated install (`brew install`) and weekly cron (`keystone charter coverage`).
- **Returns to / updates:** Observation log at `docs/followups/2026-XX-XX-keystone-observation.md`. No production artifacts.
- **Demonstrable by:** `keystone charter coverage` runs against all three repos without error; observation log shows 8 weekly snapshots.
- **Rollback signal:** Observation has no rollback because no production state is touched. If the binary breaks, observation pauses.
- **Observability added:** None. This is a manual observation, not a production system.

### Phase 1: Cross-Repo Capability Search & Run History (the moat)

**Goal:** Ship the capability competitors structurally cannot build — searchable ecosystem-wide context across Bodai components.

**Tasks:**
1. `[Akosha]` Add `cross_repo_capability_search(query, repo_filter?)` MCP tool. Indexes every Bodai component's adapter signatures, tool surface, error-handling conventions. (Akosha PR.)
2. `[Session-Buddy]` Add `ecosystem_run_history(workflow_id, scope?)` MCP tool that aggregates run records across all components. (Session-Buddy PR.)
3. `[Dhara]` Define substrate schemas for `akosha://capabilities/{repo}/{kind}/{name}.json` and `session-buddy://runs/{workflow_id}.json`. (Dhara PR.)
4. `[Mahavishnu]` Add MCP tool `cross_repo_search(query, scope=capabilities|runs|errors?)` that fans out to Akosha + Session-Buddy and aggregates results. Lives in `mahavishnu/mcp/tools/search_tools.py` (existing file).
5. `[Mahavishnu]` Wire WebSocket channel `cross-repo:{query_hash}` (admin only) for live result streaming.
6. `[Mahavishnu]` Update `mahavishnu/websocket/server.py:_can_subscribe_to_channel` (line 451) to allow `cross-repo:` channels for admin users.
7. `[Tests]` Integration test: dispatch a workflow, query `ecosystem_run_history` from a different MCP client, confirm aggregated result.

**Exit criteria:**
- `cross_repo_search` returns results spanning ≥3 Bodai components for a query like "code-review adapters" or "crash recovery patterns".
- `ecosystem_run_history(workflow_id)` returns the full call graph of a multi-component workflow.

#### Integration Contract — Phase 1

- **Triggered from:** `mcp__mahavishnu__cross_repo_search(query, scope)` MCP tool call.
- **Returns to / updates:** Read-only fan-out to Akosha + Session-Buddy; aggregate response. No writes.
- **Demonstrable by:** `mahavishnu mcp call cross_repo_search '{"query": "code-review adapters", "scope": "capabilities"}'` returns aggregated list spanning ≥3 repos.
- **Rollback signal:** p99 fan-out latency > 5s → on-call alert. Auth failure on Akosha or Session-Buddy → degraded single-source response with warning.
- **Observability added:** OTel span `cross_repo.search` with `query`, `scope`, `result_count`, `latency_ms`. Counter `cross_repo.fan_out.target_count` (target: 2 — Akosha + Session-Buddy).

### Phase 2: Settle Operations (reframed as "verify before trust")

**Goal:** Ship settle operations to address the **5 documented memories** of unverified-agent-output failures. Not a Shepherd port.

**Tasks:**
1. `[Mahavishnu]` Before writing code: compare against LangGraph `interrupt()` + checkpointing and Prefect paused-flow state. Document decision in `docs/decisions/2026-XX-XX-settle-vs-langgraph.md`.
2. `[Mahavishnu]` Add `worker_run_with_settle(task_signature, bindings)` MCP tool to `mcp/tools/worker_contract_tools.py` (existing file). Tools pair naturally with existing `launch_worker`, `send_input`, `capture_output`, `worker_status`, `wait_for_state`, `cancel_worker`, `worker_revoke`.
3. `[Mahavishnu]` Add `worker_settle(run_ref, action)` MCP tool to the same file. Actions: `select | apply | release | discard`. (v1's `settle_run` renamed to `worker_settle` for prefix-by-subsystem consistency with `pool_route_execute`.)
4. `[Mahavishnu]` For `apply`: shell out to `git merge-file` (not a hand-rolled algorithm). Use git's existing 3-way merge; conflict returns a structured error.
5. `[Mahavishnu]` Update `mahavishnu/websocket/server.py:_can_subscribe_to_channel` (line 451) to allow `settle:` and `run:` channels for `worker:read` permission.
6. `[Mahavishnu]` Document canonical idempotency contract in `docs/WEBSOCKET_CONSUMER_GUIDE.md`: consumers must be idempotent on `phase=completed`; handle out-of-order delivery; reconnect via `since_offset`.
7. `[Tests]` Unit tests for state machine transitions (proposed → selected → applied / released / discarded). Property-based test asserting no illegal transition is reachable and all terminal states are absorbing.
8. `[Tests]` Integration test: dispatch worker, observe `proposed` state, run `worker_settle --action apply`, confirm 3-way merge succeeds.

**Exit criteria:**
- `worker_run_with_settle` produces a `run_ref` and persists to Dhara before any file is written.
- `worker_settle --action apply` runs `git merge-file` against the target binding.
- All transitions are unit-tested; property-based test passes.

#### Integration Contract — Phase 2

- **Triggered from:** `mcp__mahavishnu__worker_run_with_settle` and `mcp__mahavishnu__worker_settle` MCP tools.
- **Returns to / updates:** Dhara record at `mahavishnu://runs/{run_ref}.json`. WebSocket broadcasts on `settle:{run_ref}` and `run:{run_ref}` channels.
- **Demonstrable by:** `pytest tests/integration/test_settle_e2e.py` runs a worker against a binding, applies the proposal via `git merge-file`, and verifies the change landed.
- **Rollback signal:** `apply` failure rate > 5% over 1h → on-call alert. Run state orphaned (no settle within 24h) → digest email + auto-`discard` after 7d.
- **Observability added:** OTel span `worker.run.propose`, `worker.run.settle`. Counter `worker.settle.action` (labels: `select|apply|release|discard`). Counter `worker.run.orphaned_count`.

### Phase 3: Budget Enforcement on Pool Runs (demoted from v1 Phase 4)

**Goal:** Token/turn/wallclock budgets on `pool_route_execute` without an in-kernel per-turn bridge. v1's `await goal.get()` violated Non-Goal #3; v2 keeps all reads through the network boundary.

**Tasks:**
1. `[Mahavishnu]` Add `budget_enforce(workflow_id, budget_tokens?, budget_turns?, budget_wallclock_seconds?)` MCP tool to `mcp/tools/pool_tools.py` (existing file).
2. `[Mahavishnu]` Add `budget_watchdog` background task to `mahavishnu/core/app.py` lifespan context. Runs every 60s. Uses lease-based leader election (only one replica runs watchdog per cycle).
3. `[Mahavishnu]` Inject `_now()` seam into watchdog for testing. Add `try/except CancelledError` with clean shutdown.
4. `[Mahavishnu]` Wire watchdog to Dhara unavailability: skip cycle (fail-open with WARN log), do not fail-closed.
5. `[Mahavishnu]` Add OTel span `budget.check`, counter `budget.exceeded.count` (label `dimension=tokens|turns|wallclock`).
6. `[Tests]` Unit test for state machine transitions. Integration test for multi-replica watchdog lease. Property-based test for budget arithmetic.
7. `[Docs]` Author `docs/BUDGET_ENFORCEMENT.md` explaining the per-turn vs per-run boundary (`Primitives whose natural read frequency is per-turn belong in-process; per-run belong in the control plane` — from contrarian review).

**Exit criteria:**
- Budget enforced across `pool_route_execute` runs.
- Watchdog is multi-replica-safe via lease.
- Dhara unavailability does not crash the watchdog.

#### Integration Contract — Phase 3

- **Triggered from:** `mcp__mahavishnu__budget_enforce(workflow_id, budget_*)` MCP tool. `budget_watchdog` background task (60s interval, lease-elected).
- **Returns to / updates:** Dhara record at `mahavishnu://budgets/{workflow_id}.json`. Counter increments on overflow.
- **Demonstrable by:** Run a pool task with `budget_wallclock_seconds=10`, confirm watchdog transitions to `budget_exceeded` after 10s without manual intervention.
- **Rollback signal:** Watchdog drift > 5 minutes → on-call alert. Dhara unavailable > 1 minute → degraded mode log entry, watchdog skips cycle.
- **Observability added:** OTel span `budget.check`. Counter `budget.exceeded.count`. Gauge `budget.active_count`.

### Phase 4: Shepherd as a Worker Backend (inverted from v1 Phase 6)

**Goal:** Real OS-level syscall-jail enforcement for one adapter's worth of code. No in-house static analyzer.

**Tasks:**
1. `[Mahavishnu]` `pip install shepherd-ai` (or add to `pyproject.toml`).
2. `[Mahavishnu]` Create `mahavishnu/workers/shepherd_backend.py` alongside `apple_container.py` (line 5) and `e2b_sandbox.py` (existing). Conform to existing `Worker` base class.
3. `[Mahavishnu]` Register `shepherd` as a worker type in `mahavishnu/workers/manager.py` and `mahavishnu/workers/__init__.py` lazy-import table.
4. `[Mahavishnu]` Map Shepherd task signatures to existing Mahavishnu task model (capability-driven registry from commit `efd9d705` — verify this commit exists in current `main` before starting).
5. `[Mahavishnu]` Cross-reference Shepherd's settle operations to v2 Phase 2's `worker_settle` tool. Avoid parallel settlement flows.
6. `[Tests]` Verify Seatbelt enforcement on macOS, Landlock on Linux (privileged container). Failure to enforce must fail the worker startup, not pass through.
7. `[Docs]` Author `docs/SHEPHERD_BACKEND.md` walking through the registration, capability mapping, and failure modes.

**Exit criteria:**
- `worker_type="shepherd"` is a valid routing option in `pool_route_execute`.
- A worker task attempting unauthorized file access (e.g., write outside granted root) is refused at the syscall.
- macOS Seatbelt and Linux Landlock enforcement verified on respective platforms.

#### Integration Contract — Phase 4

- **Triggered from:** `mcp__mahavishnu__pool_route_execute(prompt, worker_type="shepherd", ...)` MCP tool call.
- **Returns to / updates:** Worker spawn record at `mahavishnu://workers/{worker_id}.json`. Settle events integrate with v2 Phase 2's `run:{run_ref}` channel.
- **Demonstrable by:** Dispatch a worker with `worker_type="shepherd"` against a writable root; verify the worker writes succeed inside the root and fail outside.
- **Rollback signal:** Seatbelt/Landlock unavailable → fail worker startup with clear error. Do not silently fall back to a less-secure backend.
- **Observability added:** OTel span `worker.shepherd.start` with `seccomp_profile`, `capability_grants`. Counter `worker.shepherd.syscalls_refused_count`.

### Phase 5: Charter Observation Outcome (conditional)

**Goal:** If Phase 0.5 demonstrated Keystone value, ship a thin `crackerjack charter` wrapper. If not, drop entirely.

**Tasks (only if Phase 0.5 decision is "go"):**
1. `[Crackerjack]` Add `crackerjack charter init | coverage | conformance | verify | project` as thin CLI wrappers over the `keystone` Go binary. No reimplementation. (Crackerjack PR.)
2. `[Crackerjack]` Re-export Keystone's exit codes so existing Crackerjack pipelines work unchanged.
3. `[Crackerjack]` Wire `crackerjack charter conformance` as a pre-commit hook option.
4. `[Docs]` Author `docs/CHARTER_WRAPPER.md` documenting what `crackerjack charter` is (a wrapper) and what it is not (a reimplementation).

**Exit criteria:**
- `crackerjack charter coverage` calls `keystone charter coverage` and re-exits with the same code.
- No Bodai-specific code in `crackerjack/charter/*.py` beyond argument parsing.

**Exit criteria (drop):** If Phase 0.5 decision is "no," this phase produces only `docs/followups/2026-XX-XX-keystone-deferred.md` and exits.

#### Integration Contract — Phase 5

- **Triggered from:** `crackerjack charter <subcommand>` CLI (if shipped).
- **Returns to / updates:** Stdout/stderr from `keystone` Go binary. Exit codes re-exported.
- **Demonstrable by:** `crackerjack charter coverage` produces identical output to `keystone charter coverage`.
- **Rollback signal:** If Keystone breaks or the wrapper lags upstream, ship a "charter: deprecated" warning; do not maintain a fork.
- **Observability added:** None beyond what Keystone already emits. Wrapper is transparent.

## 6. Required Code Changes

### Phase 0 (this repo: Mahavishnu)
- [ ] `mahavishnu/mcp/tools/get_capability_result_tool.py` — verify Dhara-unavailable contract is loud (regression check on the new code path)
- [ ] `mahavishnu/core/envelopes.py` — confirm `list_envelopes` raises on Dhara-unavailable (or document why it doesn't)
- [ ] `tests/integration/test_capability_result.py` (new) — round-trip + Dhara-disabled failure-mode test
- [ ] `docs/feature-tracking/2026-07-11-dispatch-to-pool.md` (update existing file) — reclassify as "resolved by v0.19.0 refactor"
- [ ] `docs/feature-tracking/2026-08-29-capability-tooling-migration.md` (new) — migration guide for external consumers
- [ ] MCP server restart on v0.19.0 (operational, not code)

### Phase 0.5 (no production code; observation log)
- [ ] `docs/followups/2026-XX-XX-keystone-observation.md` (new)

### Phase 1 (this repo: Mahavishnu + cross-repo PRs)
- [ ] `mahavishnu/mcp/tools/search_tools.py` — add `cross_repo_search` tool
- [ ] `mahavishnu/mcp/tools/profiles.py` — register `_register_search_tools` (if new group) or extend existing
- [ ] `mahavishnu/websocket/server.py:451` — add `cross-repo:` channel branch
- [ ] Cross-repo PRs:
  - Akosha: `cross_repo_capability_search` MCP tool
  - Session-Buddy: `ecosystem_run_history` MCP tool
  - Dhara: substrate schemas `akosha://capabilities/...` and `session-buddy://runs/...`
- [ ] `tests/integration/test_cross_repo_search.py` (new)
- [ ] `docs/feature-tracking/2026-08-29-cross-repo-search.md` (new)

### Phase 2 (this repo: Mahavishnu)
- [ ] `mahavishnu/mcp/tools/worker_contract_tools.py` — add `worker_run_with_settle` and `worker_settle`
- [ ] `mahavishnu/websocket/server.py:451` — extend allowlist with `settle:` and `run:` channels
- [ ] `docs/WEBSOCKET_CONSUMER_GUIDE.md` (new) — canonical idempotency contract
- [ ] `docs/decisions/2026-XX-XX-settle-vs-langgraph.md` (new)
- [ ] `tests/unit/test_settle_state_machine.py` (new) + property-based tests
- [ ] `tests/integration/test_settle_e2e.py` (new)
- [ ] `docs/feature-tracking/2026-08-29-settle-ops.md` (new)

### Phase 3 (this repo: Mahavishnu)
- [ ] `mahavishnu/mcp/tools/pool_tools.py` — add `budget_enforce` tool
- [ ] `mahavishnu/core/app.py` lifespan — start `budget_watchdog` background task
- [ ] `tests/unit/test_budget_state_machine.py` (new) + property-based tests
- [ ] `tests/integration/test_budget_watchdog_lease.py` (new) — multi-replica safety
- [ ] `docs/BUDGET_ENFORCEMENT.md` (new)
- [ ] `docs/feature-tracking/2026-08-29-budget-enforcement.md` (new)

### Phase 4 (this repo: Mahavishnu)
- [ ] `pyproject.toml` — add `shepherd-ai` dependency
- [ ] `mahavishnu/workers/shepherd_backend.py` (new) — alongside `apple_container.py` and `e2b_sandbox.py`
- [ ] `mahavishnu/workers/manager.py` — register `shepherd` worker type
- [ ] `mahavishnu/workers/__init__.py:66-144` — add `shepherd` to lazy-import table
- [ ] `mahavishnu/mcp/tools/worker_tools.py` (or `worker_contract_tools.py`) — expose `worker_type="shepherd"` option
- [ ] `tests/integration/test_shepherd_backend.py` (new) — Seatbelt/Landlock verification
- [ ] `docs/SHEPHERD_BACKEND.md` (new)
- [ ] `docs/feature-tracking/2026-08-29-shepherd-backend.md` (new)

### Phase 5 (Crackerjack repo — separate PR)
- [ ] `crackerjack/commands/charter.py` (new) — thin wrapper over `keystone` Go binary
- [ ] `tests/integration/test_charter_wrapper.py` (new) — exit-code re-export test
- [ ] `docs/CHARTER_WRAPPER.md` (new)

## 7. Validation Matrix

| Tool / command | Expected outcome | Evidence location |
|---|---|---|
| `pytest tests/integration/test_capability_result.py -v` | Exit 0 after `execute_capability` dispatch + `get_capability_result` read-back | Phase 0 |
| `mahavishnu mcp call execute_capability '{"requires":["CODE_GENERATION"],"prompt":"phase-0-verify"}'` | Returns `{"status": "planned", "trace_id": "..."}` | Phase 0 |
| `mahavishnu mcp call get_capability_result '{"trace_id":"<id>"}'` | Returns `{"status": "completed"|"pending", "envelopes": [...]}` | Phase 0 |
| MCP server exposes `execute_capability` and `get_capability_result`; no `dispatch_to_pool` or `workflow_result` | Confirmed via `discover_tools` | Phase 0 |
| `python scripts/audit_orphans.py --days 14 --root mahavishnu` | Exit 0; no orphans in phase-N modules | `reports/orphans-phase-{N}.md` |
| `brew install tacoda/tap/keystone && keystone charter coverage` (Mahavishnu) | Exit 0; coverage report | Phase 0.5 |
| `mahavishnu mcp call cross_repo_search '{"query": "code-review adapters"}'` | Aggregated list spanning ≥3 repos | Phase 1 |
| `pytest tests/unit/test_settle_state_machine.py` + property tests | Exit 0; no illegal transitions | Phase 2 |
| `pytest tests/integration/test_settle_e2e.py` | Worker dispatches, `worker_settle --action apply` runs `git merge-file`, change lands | Phase 2 |
| `pytest tests/integration/test_budget_watchdog_lease.py` | Two replicas; only one watchdog leader per cycle | Phase 3 |
| `python -m pytest tests/integration/test_shepherd_backend.py` (macOS) | Seatbelt refuses out-of-root writes | Phase 4 |
| `crackerjack charter coverage` | Identical output to `keystone charter coverage` | Phase 5 (if shipped) |
| `mahavishnu pool health` | All pools reachable | Baseline |

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Phase 0 fix doesn't address the actual root cause and the bug persists | Medium | Single-fix scope. Reproduce first, fix second. If first fix fails, re-diagnose. |
| Phase 0.5 finds Keystone valuable but `crackerjack charter` wrapper work exceeds "thin wrapper" scope | Medium | Strict scope guard: wrapper must be ≤200 LOC of argument parsing only. Beyond that, re-evaluate. |
| Phase 0.5 finds Keystone worthless → Phase 5 is dropped, but `docs-audit-*` memories remain | High (likely) | Accept this outcome. The plan does not require Keystone to be valuable; it requires an evidence-based decision. |
| Cross-repo PRs (Akosha, Session-Buddy, Dhara) get out of sync with Mahavishnu PR | Medium | Phase 1 lands in dependency order: Akosha + Session-Buddy + Dhara first; Mahavishnu last. |
| `worker_settle` settle actions get rubber-stamped (same-session click, no real review) | High | v1's mitigation was weak. v2 requires out-of-band human approval (different process / different session). Settle state machine records `approver_session_id`; same-session approvals rejected. |
| Budget watchdog races across replicas | Medium | Lease-based leader election per cycle; only one watchdog active at a time. |
| `worker_settle --action apply` crashes mid-merge | Medium | Use `git merge-file` (atomic per file). If the shell-out crashes, the partial merge state is recoverable via `git status`. Document recovery in `docs/SHEPHERD_BACKEND.md` and `docs/WEBSOCKET_CONSUMER_GUIDE.md`. |
| Dhara unavailability during budget check or settle operation | Medium | Fail-open for read-only paths (skip cycle, WARN log); fail-closed for write paths (return `503` to caller). |
| Seccomp/Sandbox unavailability in dev environments | Low | Worker startup fails with clear error; not silently degraded. |
| Shepherd `pip install shepherd-ai` breaks on Python 3.14 (CLAUDE.md pins 3.14) | Low | Verify install on local venv before committing. Fallback: file issue upstream; don't fork. |
| Phase 4 Shepherd backend passes thin compliance test but fails deep syscall enforcement | Low | Test against actual macOS Seatbelt and Linux Landlock refusals, not just that the API accepts the call. |
| Conformance score becomes a Goodhart target | High | Phase 0.5 explicitly measures operator judgment work, not score alone. Score without usage is a false positive. |

## 9. Decision Rule

This plan is "done enough" when:

1. **Phase 0 ships and the new `execute_capability` / `get_capability_result(trace_id)` round-trip is verified on the running MCP server (v0.19.0).** Refactor eliminated the bug; verification is the deliverable.
2. **Phase 0.5 completes with a documented decision.** Charter work is conditional on evidence.
3. **Phase 1 ships.** Cross-repo capability search is the moat. This is the strategic deliverable.
4. **Phase 2 ships.** Settle addresses the 5 documented memory failures.

Phases 3, 4, 5 are sequenced by impact: budget enforcement (Phase 3) → Shepherd backend (Phase 4) → conditional charter wrapper (Phase 5). If scope pressure forces a cut, ship in this order and document deferred phases in `docs/followups/`.

## 10. References

- Shepherd: https://github.com/shepherd-agents/shepherd (arXiv 2605.10913)
- Prime Agent: https://github.com/primeintellect-ai/prime-agent (arXiv 2608.23552)
- Keystone: https://github.com/tacoda/keystone (`brew install tacoda/tap/keystone`, v4.0.0, MIT)
- DeepSeek Harness: https://github.com/deepseek-ai/deepseek-harness
- Anthropic Claude Skills: https://github.com/anthropics/skills, https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
- Temporal "Durable flexible multi-agent systems": https://temporal.io/blog/durable-flexible-multi-agent-systems
- LangGraph vs Temporal: https://www.langchain.com/resources/langgraph-vs-temporal
- Existing Mahavishnu files cited:
  - `mahavishnu/mcp/tools/pool_tools.py:685` (deprecated; deleted in v0.19.0 commit `30ebc0f3`)
  - `mahavishnu/mcp/tools/capability_tools.py:347` (`execute_capability` — Phase 0 read point)
  - `mahavishnu/mcp/tools/get_capability_result_tool.py:21` (`get_capability_result` — Phase 0 write point)
  - `mahavishnu/core/envelopes.py:64` (`list_envelopes` — Dhara envelope reader)
  - `docs/fixes/2026-08-29-dispatch-to-pool-dead-letter-fallback.md` (historical pattern reference; bug path no longer exists)
  - `mahavishnu/mcp/tools/worker_contract_tools.py:33` (existing `_durable_manager` pattern)
  - `mahavishnu/workers/apple_container.py` (existing isolated worker)
  - `mahavishnu/workers/e2b_sandbox.py` (existing isolated worker)
  - `mahavishnu/websocket/server.py:451` (`_can_subscribe_to_channel` allowlist)
  - `mahavishnu/mcp/tools/profiles.py:97-101` (registration patterns)
  - `mahavishnu/mcp/tools/profiles.py:67-91` (STANDARD/FULL registrations)
  - `mahavishnu/mcp/bootstrap.py:639-648` (optional-tool gating)
  - `scripts/audit_orphans.py` (orphan gate)
  - `docs/feature-tracking/` (12 prior tracking files)
  - `docs/plans/TEMPLATE.md` (plan template)
  - `docs/schemas/document-frontmatter-v1.md` (frontmatter contract)
- Memory citations: `agent-fix-verification.md`, `ty-small-fix-ghost-revert.md`, `drift-bundling-recovery.md`, `plumbing-commit-leaves-staged-revert.md`, `session-buddy-auto-checkpoint-bundling.md`, `pool-dispatch-async-default.md`, `mahavishnu-dispatch-prompt-mangling.md`, `docs-audit-*` series
- Commit reference (NOT a spec file — does not exist as a path): `efd9d705` capability-driven worker registry. Verify commit exists in `git log` before Phase 4 references it as `blocks_on`.

---

## v1 review summary (preserved for traceability)

This v2 supersedes v1 of the same file (saved earlier this session). v1 was reviewed by 6 agents with non-overlapping lenses. The most impactful findings were:

- **Contrarian (PIVOT verdict)**: v1 was a follower roadmap with no thesis; cross-repo state is the only moat competitors can't build; Phases 2/3/4 reinvented Prefect durable execution; Phase 6's static analyzer is unsound.
- **Architecture**: 4 must-change items including Dhara-unavailability handling and multi-replica watchdog races; `release` action vocabulary ambiguous.
- **Ecosystem fit**: Phase 4's `await goal.get()` violated Non-Goal #3; Phase 5 charter MCP server belongs in its own repo; Session-Buddy/Crow/Dhara missing from contracts.
- **Process discipline**: Missing `audit_orphans.py` in Validation Matrix; missing `{built, wired, adopted}` feature-tracking; new MCP tools not mapped to profile-gated groups; topic value not in frontmatter seed list.
- **Architecture soundness**: Phase 5 charter integrity alert WebSocket channel undefined; Phase 5 "embedded charter" fallback undefined; 10 missing architectural decisions.
- **Code-level**: Multiple wrong-repo paths (`oneiric/`, `crackerjack/`); `mahavishnu/dispatch_to_pool.py` doesn't exist (it's `pool_tools.py:685`); WebSocket allowlist blocker on new channels; `goal_team_tools.py` collision; insufficient tests for 89% coverage gate.

All findings addressed in v2 except where explicitly retained as out-of-scope (Non-Goals §3).
