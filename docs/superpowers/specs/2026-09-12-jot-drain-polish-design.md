---
status: complete
role: implementation
kind: plan
date: 2026-09-12
last_reviewed: 2026-09-19
superseded_by: null
blocks_on: []
topic: jot-drain-polish
---

# Jot Drain Polish Spec

> **Status:** Complete — implementation delivered 2026-09-19 (7 commits on main, drain.py coverage 97.41%).
> **Date:** 2026-09-12
> **Sub-plan:** Polish pass for the Jot Drain subsystem (sub-plan 3 of 3 in the Jot Inbox trilogy).
> **Author:** Brainstorming session output, validated by user.
> **Parent spec:** `docs/superpowers/specs/2026-09-10-jot-drain-design.md` (commits `aa43fe26` → `2f36d878` → `5361559f` → `50a8c7fb`).
> **Parent plan:** `docs/superpowers/plans/2026-09-10-jot-drain.md` (COMPLETE on main, last commit `ce27c697`).

## 1. Context and Scope

### 1.1 What shipped

The Jot Drain sub-plan landed on `main` between 2026-09-10 and 2026-09-12 across 13 commits:

- `mahavishnu/jot/drain.py` — state machine, dispatch orchestration, retry policy, surfacing scorer
- 6 high-level drain primitives (`drain_plan`, `dispatch_jot`, `retry_dispatch`, `defer_jot`, `delete_jot`, `surface_relevant`)
- 6 MCP tools + 6 Typer CLI subcommands
- 3 hook wrappers (SessionStart, PostToolUse, UserPromptSubmit)
- 29 Hypothesis property tests (all passing)
- Two-tier reconciler (lazy Tier-1 + background Tier-2)

The system meets every load-bearing acceptance criterion from the parent spec. **413 unit/integration tests pass; coverage gate met for fold.py (96.06% > 89%).**

### 1.2 What this polish set fixes

Six concerns were parked during execution because they were either (a) out-of-scope for their parent task, (b) spec-vs-implementation drift discovered late, or (c) production trade-offs that needed adversarial tests before reverting. They are now a bounded polish set:

| # | Item | Type | Why parked |
|---|------|------|------------|
| 1 | `/jot drain` slash command | Code + docs | Parent spec §3.5 deferred it as future work |
| 2 | Reconciler production-revert + adversarial tests | Code (production behavior change) | Task 19 trade-off: `await _auto_retry_after` blocks 30s per FAILED-but-retriable jot; tests used a patched fake to observe the call |
| 3 | `_validate_ctx` unknown-key rejection | Type tightening (correctness) | Parent spec required keys but not unknown-key whitelist |
| 4 | SDD bundling-pattern defensive note | Doc | Task 19 accidentally bundled Task 17's staged work; lesson not yet recorded |
| 5 | `_propose_action` heuristic spec-lock | Doc | Mapping is currently heuristic per task-19-brief; spec needs the rules |
| 6 | `DrainPlan.action_proposals` docstring + JSON-schema sync | Doc | Task 19 restored the field per spec §3.3; runtime shape not yet documented in the surface comment |

### 1.3 Non-goals

- **Re-opening locked §2 decisions** from the parent spec. UX shape, retry budget, dispatch agency, and architectural integration remain frozen.
- **Items deferred per parent spec §10** — tag/priority filtering for surfacing, drain TUI. Stay parked.
- **Sibling-session-integration.** Out of scope per the original trilogy decomposition.
- **Capture (sub-plan 1) or read (sub-plan 2) changes.** Polish is drain-only.
- **New persistence layer, new MCP server, new event types.** All polish uses existing surfaces.

## 2. Locked Design Decisions

These decisions were resolved during brainstorming and are not revisitable during plan-writing without re-opening brainstorming.

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Items 1-6 only (bounded set) | Items 7-8 explicitly deferred per parent spec §10 |
| Item 1 inclusion | Yes — re-open parent spec §3.5 | User confirmed during brainstorming 2026-09-12 |
| Execution mode | Spec + plan artifacts only; execute in a future session | User wants durability over speed this round |
| Production-revert authority | Reconciler change (item 2) requires adversarial tests first | Restore `asyncio.create_task` only after tests prove observability without `await` |
| `_validate_ctx` tightening | Reject **unknown** keys per op (whitelist), not constrain values | Existing Literal/Int/Bool/Str checks already constrain values |
| Bundle-defensive note location | `.claude/decisions/sdd-bundling-defensive-pattern.md` | Repo-local decision file (per CLAUDE.md); not architectural, so not `docs/adr/` |
| Spec-lock format for item 5 | Table in parent spec §3.3.4 mapping `dispatch_state → suggested_action` (single input dimension; `deleted` is filtered upstream by `_is_drain_eligible`, NOT by `_propose_action`) | Locks current heuristic as policy without changing behavior |

## 3. The Six Polish Items

### Item 1: `/jot drain` slash command

**Motivation.** Parent spec §3.5 deferred `/jot drain` as future work. With the underlying `drain_plan` primitive now stable, the slash-command surface is a 1-task add — extending `mahavishnu/commands/jot.md` (currently 8 lines, only supports `/jot vitals`) to support `/jot drain [--query Q] [--limit N] [--include-in-flight]`. The slash command wraps the `drain_plan` primitive, returning the same `DrainPlanDict` shape that the MCP tool and CLI subcommand return.

**Change scope.**

| File | Change |
|---|---|
| `mahavishnu/commands/jot.md` | Add second command (after `/jot vitals`) for `/jot drain`. Mirror the existing `--query` / `--limit` / `--include-in-flight` flags from `mahavishnu jot drain`. Document the surface as "shows top-N drain candidates with suggested actions" |
| `mahavishnu/jot/cli.py` | No code change — `cmd_drain` already supports the query/limit/include-in-flight flag set |
| `tests/integration/jot/test_drain_slash_command.py` (NEW) | Add 1 static-content test asserting `mahavishnu/commands/jot.md` contains a `/jot drain` block with the correct frontmatter (`description`, `allowed-tools`). Distinct from `test_drain_cli.py` (which exercises the Typer surface) because slash commands aren't Typer |
| `docs/superpowers/specs/2026-09-10-jot-drain-design.md` §3.5 | Update from "deferred" to "shipped" with the new artifact path |

**Command contract.**

```markdown
---
description: Show drain candidates with suggested actions (open jots ranked for dispatch/defer/done/delete/skip)
allowed-tools: []
---

Run `mahavishnu jot drain {{query}} --limit {{limit | default:5}} --include-in-flight {{include_in_flight | default:false}}` and display the output verbatim.

Defaults: limit=5, include_in_flight=false. Pass `--query` to scope by surface text.
```

(The `allowed-tools: []` mirrors the existing `/jot vitals` block in the same file, even though the command does run bash via the file's automatic `Run` block.)

**Rollback.** Remove the slash command block from `jot.md`. Revert the spec status line. No code revert needed (primitive is shared with CLI/MCP).

**Tests.** Single integration test asserting the command file contains a `/jot drain` block with the correct frontmatter (`description`, `allowed-tools`). The bash-runner surface (which already exists for `/jot vitals`) is unchanged. Test file: `tests/integration/jot/test_drain_slash_command.py` (NEW), distinct from the Typer-CLI tests in `test_drain_cli.py`.

### Item 2: Reconciler production-revert + adversarial tests

**Motivation.** Task 19's implementer replaced `asyncio.create_task(_auto_retry_after(...))` with `await _auto_retry_after(...)` at two call sites (`_reconcile_if_in_flight` lines 495 and 553) to make a patched-fake test assertion observe the call. This was a test-observation hack, not a production-correctness fix. In production, each FAILED-but-retriable jot now **blocks the reconciler for `RETRY_BACKOFF_SECONDS` (30s) before the next jot is reconciled** — a denial-of-service vector at any non-trivial jot volume.

**Change scope.**

| File | Change |
|---|---|
| `mahavishnu/jot/drain.py` lines 495, 553 | Replace `await _auto_retry_after(...)` with `asyncio.create_task(_auto_retry_after(...))`; capture task in a local var `task = asyncio.create_task(...)`; do NOT `await task`. Add a module-level `_retry_waiters: dict[str, asyncio.Event] = {}` — `_auto_retry_after` sets the event after `asyncio.sleep` returns; tests `await _retry_waiters[handle]` to observe (pattern 2 — per-jot waiter dict). Cleanup is per-key after test observation. |
| `tests/unit/jot/test_drain_reconciler.py` | Rewrite in place the 9 patched-fake `_auto_retry_after` tests as adversarial tests that observe the call via `_retry_waiters` (NOT delete-and-recreate — the existing test function names stay so `tests/unit/jot/test_drain.py::test_drain_reconciler` lookup keeps working) |
| `tests/integration/jot/test_drain_auto_retry_e2e.py` | Add 1 adversarial test: dispatch fails → reconciler picks up the failure → reconciler schedules retry → reconciler moves on to next jot **without waiting 30s** |
| `docs/superpowers/specs/2026-09-10-jot-drain-design.md` §6.3 | Update reconciler diagram: "Auto-retry scheduled as background task (fire-and-forget) via `asyncio.create_task`" |

**Observability pattern (locked: pattern 2).** Adversarial tests observe `_auto_retry_after` running without blocking the reconciler via a per-jot waiter dict:

- `_retry_waiters: dict[str, asyncio.Event]` is module-level state.
- `_auto_retry_after(handle, backoff_s)` records `event = asyncio.Event()` keyed by handle before sleeping, then `event.set()` after the post-sleep fold/validate path completes (success or failure — set unconditionally so tests aren't sensitive to the failure path).
- Tests do `await _retry_waiters[handle]` to observe. Per-key cleanup after observation: `del _retry_waiters[handle]`.

Alternative patterns (module-level set; patched fake) were considered and rejected: module-level set has GC lifecycle risk; patched fake re-introduces the observation hack that created the original bug.

**Rollback signal.** If adversarial tests fail or flake, the revert is blocked — revert the revert and re-investigate. A 5%+ flake rate over 100 runs is the rollback threshold.

**Coverage impact.** drain.py coverage was 85.54% (above lower bound, below 90% aspirational). The new adversarial tests target the previously-patched branch directly, expected to push coverage of `_reconcile_if_in_flight` above 90%.

### Item 3: `_validate_ctx` unknown-key rejection (whitelist)

**Motivation.** `_validate_ctx` (drain.py line 175) checks **required keys** (from `_REQUIRED_KEYS`) and **type/Literal** for known keys. It does NOT reject unknown keys. A caller passing `ctx={"attempt": 2, "dispatched_from": "mcp", "pool_selector": "least_loaded", "workflow_id": "wf-1", "mistyped_key": "typo"}` succeeds silently — the typo never lands in the log (because the event builder reads from a typed shape, not from ctx) but also never errors. This masks upstream bugs.

**Change scope.**

| File | Change |
|---|---|
| `mahavishnu/jot/drain.py` line 89 (after `_REQUIRED_KEYS`) | Add `_AUTO_FILLED_KEYS: tuple[str, ...] = ("started_at_ms",)` (currently auto-filled by `_append_event` line 285 — must be in the whitelist or dispatch breaks at runtime). Then add `_KNOWN_KEYS_PER_OP: dict[str, frozenset[str]] = {op: frozenset(_REQUIRED_KEYS[op]).union(_INT_KEYS, _BOOL_KEYS, _STR_KEYS, _AUTO_FILLED_KEYS, _LITERAL_KEYS.keys()) for op in _REQUIRED_KEYS}`. Note the `.union(...)` form — `frozenset.__or__` rejects tuples, the bare `|` chain raises `TypeError`. |
| `mahavishnu/jot/drain.py` line 188 | In `_validate_ctx`, after the required-keys check, add: `unknown = set(ctx) - _KNOWN_KEYS_PER_OP[op]; if unknown: raise JotValidationError(f"unknown keys for op={op!r}: {sorted(unknown)}", ...)` |
| `tests/unit/jot/test_drain.py` | Add 4 tests: (1) extra key on `dispatch` raises; (2) extra key on `dispatch_failed` raises; (3) extra key on `defer` raises; (4) all current callers pass (regression guard — fail loudly if a caller accidentally drops a key, including the auto-fill path for `started_at_ms`) |

**Compatibility.** Per-op `_REQUIRED_KEYS` declares what each op MUST have. `_INT_KEYS` / `_BOOL_KEYS` / `_STR_KEYS` / `_AUTO_FILLED_KEYS` / `_LITERAL_KEYS.keys()` are the optional keys. Together they form the whitelist. The `_AUTO_FILLED_KEYS` tuple is a new constant — it captures keys that `_append_event` injects before `_validate_ctx` runs (currently just `started_at_ms` for `op == "dispatch"`). **Without this constant in the whitelist, dispatch from every surface (CLI, MCP, slash, auto-retry, reconciler) raises `JotValidationError("unknown keys for op='dispatch': ['started_at_ms']")` at runtime — this is BLOCKING, not a lint.**

**Rollback.** Delete the `_KNOWN_KEYS_PER_OP` lookup and the unknown-key branch in `_validate_ctx`. The rest of the validation is unchanged.

### Item 4: SDD bundling-pattern defensive note

**Motivation.** During the parent plan's execution, Task 19's implementer committed `def3eb7a3346708d393225e5e04f8e92e7c3927f` with `git add .`-style bundling, accidentally landing Task 17's staged-but-uncommitted files (3 hook wrappers + `.claude/settings.json` + `capture_hook` + integration tests). Final state was correct (no harm done, no extra files), but the next SDD run on this repo is at risk of repeating the pattern. The lesson needs to be recorded in `.claude/decisions/` (per CLAUDE.md's "repo-local decisions" rule, NOT `docs/adr/` which is for architectural choices).

**Change scope.**

| File | Change |
|---|---|
| `.claude/decisions/sdd-bundling-defensive-pattern.md` | NEW. One short note (per the `removed-scripts.md` template shape in `.claude/decisions/README.md`): **Context** (Task 19's bundling incident, commit hash, files affected), **Decision rule** ("downstream SDD tasks must use `git add <specific-paths>` not `git add .` whenever the working tree is dirty with staged-but-uncommitted work from an upstream task"), **Status** (active) |
| `.claude/decisions/README.md` | Add the new file to the index list (one-line entry, alphabetical insertion) |

**Content draft for the decision file** (final wording in the plan's brief):

```markdown
# SDD Bundling Defensive Pattern

## Context

During plan `2026-09-10-jot-drain` execution, Task 19's implementer
committed `def3eb7a` with `git add .`-style staging. The working tree
held Task 17's staged-but-uncommitted files (3 hook wrappers +
`.claude/settings.json` + capture_hook + integration tests). All
landed on `main` in a single commit. Final state was correct (no
extra files beyond what both tasks intended), but a downstream task's
`git add` reached into an upstream task's staged state.

## Decision rule

In a multi-task SDD plan where upstream tasks have staged-but-uncommitted
work:

- **Downstream tasks MUST use `git add <specific-paths>`** — never
  `git add .` or `git add -A`.
- **Detect dirty trees before committing** — `git status --porcelain`
  is cheap; do it once before each commit. If staged entries exist
  that this task didn't produce, stop and reconcile.
- **The SDD controller runs the audit** — if a task lands with
  unexpected files in the diff, the controller flags the bundling
  and either (a) splits the commit or (b) accepts the bundle with
  an explicit ruling in the ledger.

## Status

Active. First rule for any new SDD plan run on this repo.
```

**Rollback.** Delete the file. Remove the index entry. No code revert.

### Item 5: `_propose_action` heuristic spec-lock

**Motivation.** `_propose_action` (drain.py line 705) maps each drain candidate to a `Literal["dispatch", "defer", "done", "delete", "skip"]` based on `jot.dispatch_state`. The mapping is documented in the function's docstring (a 4-row policy table) but is NOT in the parent spec. Task-19's reviewer flagged this as "heuristic not spec-locked" — meaning future implementers changing the heuristic could ship a behavior change without a spec revision.

**Change scope.**

| File | Change |
|---|---|
| `docs/superpowers/specs/2026-09-10-jot-drain-design.md` §3.3 (insert §3.3.4) | Insert subsection "\_propose_action policy (locked)" with the exact 4-row table below, with `reason` strings copied verbatim from drain.py lines 710-713. Reference the implementation at `mahavishnu/jot/drain.py:705` for traceability |
| `mahavishnu/jot/drain.py` line 706 | Update the docstring to point to the spec section: "Suggested action for a drain candidate (spec §3.3.4 — locked policy). Local implementation MUST match the spec table; spec changes require brainstorming re-open." Note: the word "heuristic" is removed — the policy is locked, not heuristic. |

**Spec content to insert** (parent spec §3.3, after the existing surface definitions):

```markdown
#### 3.3.4 `_propose_action` policy (locked)

For each `JotSummary` in a `DrainPlan.candidates` list, the
`DrainPlan.action_proposals` field is computed by the following
deterministic mapping. The mapping is policy, not heuristic — any
change requires a brainstorming re-open.

| `jot.dispatch_state` | `suggested_action` | `reason` |
|---|---|---|
| `IN_FLIGHT` | `skip` | already in flight |
| `FAILED` | `dispatch` | retry via dispatch_jot — budget exhausted |
| `SUCCEEDED` | `done` | workflow succeeded; mark done |
| `None` (never dispatched) | `dispatch` | never dispatched |

The `handle` field of each proposal is `jot.short_id` (6-hex), so
callers can resolve it without an extra id field. Implementation:
`mahavishnu/jot/drain.py:705` (`_propose_action`).
```

**Rollback.** Revert the docstring. Remove the spec section. No code behavior change.

### Item 6: `DrainPlan.action_proposals` docstring + JSON-schema sync

**Motivation.** Task 19 restored `action_proposals` on `DrainPlan` per parent spec §3.3, but the field's runtime shape (`list[ActionProposalDict]`) and per-element schema (`ActionProposalDict` with `handle: str`, `suggested_action: Literal[...]`, `reason: str`) are only documented by the `TypedDict` declarations (drain.py line 244). A user reading the `DrainPlan` surface (e.g. from the MCP tool spec at `docs/MCP_TOOLS_SPECIFICATION.md` or the rendered `mahavishnu jot drain --help`) cannot see what `action_proposals` contains without reading the implementation.

**Change scope.**

| File | Change |
|---|---|
| `mahavishnu/jot/drain.py` line 636 (the field declaration) | Add a field-level docstring on `DrainPlan.action_proposals` documenting: (a) the 1:1 correspondence with `candidates` (same length, same order), (b) the element shape via `ActionProposalDict`, (c) the policy source (spec §3.3.4 from item 5), (d) a 1-line JSON-schema-style snippet. **Note:** the existing class-level docstring at `drain.py` lines 620-631 (which documents the `error` field) stays intact — only the field-level docstring is added at line 636 |
| `mahavishnu/jot/drain.py` line 244 (`ActionProposalDict`) | Add a 4-line docstring: "Suggested action for one drain candidate. See spec §3.3.4 for policy. Locked — behavior change requires brainstorming re-open." |
| `docs/MCP_TOOLS_SPECIFICATION.md` | Add a 6-line section under the `jot_drain` MCP tool entry documenting the `action_proposals` field shape (handle / suggested_action / reason) |

**Docstring draft** (final wording in the plan's brief):

```python
action_proposals: list[ActionProposalDict] = field(default_factory=list)
"""Suggested action per drain candidate, 1:1 with `candidates` (same
length, same order). Each element is an `ActionProposalDict` with:

  {
    "handle": str,           # 6-hex short_id; resolves via JotSummary
    "suggested_action": "dispatch" | "defer" | "done" | "delete" | "skip",
    "reason": str,           # short human-readable rationale
  }

Policy is locked in spec §3.3.4 (see `_propose_action`).
"""
```

**Rollback.** Remove the field-level docstring. Remove the MCP_TOOLS_SPECIFICATION.md addition. No behavior change.

## 4. Cross-Cutting Concerns

### 4.1 Test strategy

All polish items are additive or tightening — no spec-level rewrite. The test footprint per item:

| Item | New tests | Modified tests | Total |
|---|---|---|---|
| 1. `/jot drain` slash command | 1 integration (`tests/integration/jot/test_drain_slash_command.py`) | 0 | 1 |
| 2. Reconciler revert + adversarial | 2 (1 unit + 1 e2e) | 9 (patched-fake replacement) | 11 |
| 3. `_validate_ctx` unknown-key | 4 | 0 | 4 |
| 4. SDD bundling defensive note | 0 (doc-only) | 0 | 0 |
| 5. `_propose_action` spec-lock | 0 (doc-only) | 0 | 0 |
| 6. `action_proposals` docstring | 0 (doc-only) | 0 | 0 |
| **Total** | **7 new + 9 modified** | | **16 tests touched** |

All new tests use existing fixtures (`tests/conftest.py`) — no new fixture work.

### 4.2 Coverage impact

drain.py is currently 85.54%. Project-wide pytest gate is **89.02%** per `pyproject.toml` (also referenced in CLAUDE.md). Polish target: **drain.py reaches the gate** — i.e., ≥ 89% — by item 2's adversarial tests. Item 2's adversarial tests target `_reconcile_if_in_flight`'s auto-retry branch directly, which is currently under-covered because Task 19's patched-fake tests bypassed the real code path. Expected post-polish: drain.py 89-92%.

fold.py is at 96.06% — no polish items touch fold.py.

**Coverage non-goal for polish.** Item 3 (whitelist tightening) does not move coverage materially — its 4 new tests cover an existing branch with new scenarios. Items 1, 4, 5, 6 are doc/slash-command additions.

### 4.3 No new dependencies

All polish items use existing imports. No `pyproject.toml` changes.

### 4.4 File map (summary)

| File | Items touching |
|---|---|
| `mahavishnu/jot/drain.py` | 2, 3, 5, 6 |
| `mahavishnu/commands/jot.md` | 1 |
| `tests/unit/jot/test_drain.py` | 3 |
| `tests/unit/jot/test_drain_reconciler.py` | 2 |
| `tests/integration/jot/test_drain_cli.py` | (no polish touch — Typer CLI tests; item 1's slash-command test is in a new file, not this one) |
| `tests/integration/jot/test_drain_slash_command.py` | 1 (NEW, item 1 — slash-command frontmatter test) |
| `tests/integration/jot/test_drain_auto_retry_e2e.py` | 2 |
| `docs/superpowers/specs/2026-09-10-jot-drain-design.md` | 1, 2, 5 |
| `docs/MCP_TOOLS_SPECIFICATION.md` | 6 |
| `.claude/decisions/sdd-bundling-defensive-pattern.md` | 4 (NEW) |
| `.claude/decisions/README.md` | 4 (index entry) |

11 files touched. 2 NEW: `tests/integration/jot/test_drain_slash_command.py` (item 1) and `.claude/decisions/sdd-bundling-defensive-pattern.md` (item 4). The 9 others are modifications or spec updates.

### 4.5 Commit hygiene (carried from parent plan)

- Author: `git -c user.email="les@wedgwoodwebworks.com" -c user.name="les"`
- Bodai pre-1.0: direct-to-main, no PRs
- `git commit --only <specific-paths>` — never `git add .` (per the item-4 defensive note)
- `--no-verify` if the pre-commit hook hangs (parent plan precedent)
- Never `git push` without explicit user approval

## 5. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Item 2 revert introduces reconciler regression (retry no longer fires) | Low (adversarial tests catch it) | High (silent retry loss) | 5% flake budget over 100 runs is rollback signal; integration test asserts retry actually completes |
| Item 3 unknown-key check breaks a caller passing `started_at_ms` | Low (audited above) | Medium (validation rejects auto-fill) | Add `started_at_ms` to `_KNOWN_KEYS_PER_OP["dispatch"]` whitelist before merge |
| Item 5 spec-lock makes future heuristic tweaks require brainstorming | Intentional | Low (locked decisions have explicit re-open path) | None — this is the goal |
| Items 5, 6 doc changes ship with no test verification | By design | None (doc-only items) | Each item has a precise pre/post condition in the spec; item 1 has its own integration test, NOT in this risk class |
| Polish set itself runs out of session tokens | Inherited from parent's risk register | Medium (spec/plan artifacts ship, execution deferred) | Execution is explicitly future-session per user decision |

## 6. Acceptance Criteria

The polish set is complete when ALL of the following hold:

1. `/jot drain` slash command is documented in `mahavishnu/commands/jot.md` with the contract in §3 item 1.
1. `drain.py` reconciler uses `asyncio.create_task(_auto_retry_after(...))` (fire-and-forget), NOT `await`. Adversarial tests prove the retry still runs.
1. `_validate_ctx` rejects unknown ctx keys per op. New tests cover this. All existing tests still pass.
1. `.claude/decisions/sdd-bundling-defensive-pattern.md` exists and is indexed.
1. Parent spec §3.3.4 documents the `_propose_action` policy table with `reason` strings copied verbatim from drain.py lines 710-713 (not paraphrased).
1. `DrainPlan.action_proposals` field has a full docstring at line 636 + `ActionProposalDict` has a docstring at line 244 + `MCP_TOOLS_SPECIFICATION.md` documents the field. The existing class-level docstring at drain.py lines 620-631 is preserved.
1. drain.py coverage is ≥ 89% (project-wide pytest gate per `pyproject.toml` / CLAUDE.md).
1. All 413 pre-polish tests still pass (with 9 rewritten-in-place in item 2) + 7 net-new tests (1 + 2 + 4) = **420 tests pass**.
1. `crackerjack run` does not regress (per Bodai pre-1.0 direct-to-main policy; `crackerjack` is informational, not blocking).
1. The change graph lands on `main` with no `git push` and no PR.
