---
status: complete
role: implementation
date: 2026-09-16
last_reviewed: 2026-09-16
topic: dhara-retirement
related:
  - ../superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md
  - ../adr/013-mahavishnu-dhara-adapter-tool-boundary.md
  - ../adr/017-oneiric-shared-persistence-substrate.md
blocks_on:
  - Phase 10 schema migration + drift cleanup (closed 2026-09-16)
---

# Dhara MCP Retirement — Cross-Dep Removal Plan (Phase 8 First Pass)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Dhara as a Bodai shared dependency. After this plan ships, no `from dhara` / `import dhara` source imports remain in any consumer repo, and no `dhara>=` dependency entry remains in any consumer's `pyproject.toml`. The Dhara repository itself continues as a standalone library — its engine (Durus) is unaffected.

**Architecture:** Three execution waves:
1. **Wave A — Substrate refactor**: Replace `from dhara` source imports across 2 consumer repos (mahavishnu, session-buddy). Two replacement strategies apply:
   - **`dhara.{generate, is_ulid}`** → use the **existing** `oneiric.core.ulid` module (drop-in: same function names, same signatures).
   - **`dhara.schema.{WorkflowOutcome, ApprovalLog, WebhookIngress}`** and **`dhara.lock.{DharaLock, …}`** → define **locally in the consumer repo** (`mahavishnu/core/models/persistence.py`, `mahavishnu/core/_lock_sentinel.py`) as msgspec.Struct / minimal sentinel. **Do NOT add equivalents to oneiric** — oneiric stays a substrate library, not a Bodai-component-shaped model catalog. Each consumer-repo migration is its own owner of these types.
   Total: 11 source files affected.
2. **Wave B — Dependency cleanup**: Drop orphan `dhara>=` entries from 4 consumer `pyproject.toml` files (mahavishnu, session-buddy, akosha, crackerjack).
3. **Wave C — Verification + handoff**: Per-repo test sweep + multi-agent review + memory cleanup.

**Tech Stack:** Python 3.14, Oneiric substrate (`oneiric.core.ulid` consumed directly; `WorkflowOutcome` / `ApprovalLog` / `WebhookIngress` / `DharaLock` defined locally in the consumer as msgspec.Struct or minimal sentinel — NOT as oneiric equivalents), msgspec.Struct for the local persistence types.

**Spec:** This plan implements the **first pass** of the broader Dhara MCP retirement described in `../superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md` (1,237 LOC). The spec covers full removal of all 21 `mcp__dhara__*` MCP tools across phases 1, 1.5, 3, 5, 7, 8, 9. **This plan only covers the cross-dep cleanup (Phase 8 in spec terms) — it does NOT rewrite the 21 MCP tools into new homes.** The full MCP-tool rewriting is a separate follow-on plan; Phase 6 of the spec (Oneiric cache adapter consolidation) is already complete via prior session work, as is Phase 10's canonical schema re-export stabilization.

## Global Constraints

- Dhara the engine is BSD-3 licensed and standalone (the engine survives; only the cross-dep linkage dies).
- No version bumps in any `pyproject.toml` — user-initiated per `feedback-mcp-common-version-bump-is-user`. Mahavishnu's `dhara>=0.17.0` line removal is a DEP REMOVAL, not a version bump.
- No `git push` in any Bodai repo — user-initiated per `feedback-bodai-push-is-user-controlled`.
- Author every commit with `-c user.email=les@wedgwoodwebworks.com -c user.name=les`.
- Follow project conventions: `from __future__ import annotations` first; typed function signatures; X | None not Optional[X]; Pydantic v2 model_validator where relevant.
- Hard cutover — no deprecation windows. Tasks are applied per-commit; once a repo's `from dhara` count is 0 and its `pyproject.toml` has no `dhara>=` entry, that repo is done.

---

## 4.5 Requirements

```yaml
requirements:
  - id: REQ-DHARA-IMPORT-MV-001
    title: "All `from dhara` imports in /Users/les/Projects/mahavishnu/ source removed"
  - id: REQ-DHARA-IMPORT-SB-002
    title: "All `from dhara` imports in /Users/les/Projects/session-buddy/ source removed"
  - id: REQ-DHARA-DEPS-DROP-003
    title: "All `dhara>=` entries removed from consumer repo pyproject.toml files"
  - id: REQ-DHARA-VERIFY-004
    title: "All consumer repo test suites remain green after each removal commit"
  - id: REQ-DHARA-MEMORY-005
    title: "Memory `dhara-removal-direction-2026-09-16` updated to mark COMPLETED"
  - id: REQ-DHARA-REVIEW-006
    title: "Multi-agent review of all commits before user push decision"
```

---

## 5. Implementation Phases

### Phase A: Substrate refactor (cross-source-import replacement)

**Goal:** Every `from dhara` / `import dhara` source import across consumer repos becomes either a oneiric equivalent or a Pydantic-native model. This is the highest-risk wave — it touches production code paths (workflow outcome writing, approval logging, webhook ingress, locking, ULID generation). Each replacement must keep the public API shape (constructor args, method signatures, attribute names) unchanged so the 11 importing files can swap the import path with minimal call-site changes.

**Cross-reference from auth:** The `_dhara_substrate_compat.py` shim files in both mahavishnu and session-buddy are compatibility layers — they re-export dhara types under a `mahavishnu`-namespaced module. These shims exist because the underlying substrate (Dhara Durus) was used to back the agent-skill signing infrastructure. With the substrate itself staying in Dhara (engine survives), the question is: do consumers *use* the shim directly, or do they import the underlying `dhara.schema.*` types? Per memory `dhara-removal-direction-2026-09-16`: the imports to replace are `dhara.schema.{WorkflowOutcome,ApprovalLog,WebhookIngress}`, `dhara.lock.DharaLock`, and `dhara.{generate,is_ulid}`. The shim files themselves can be reduced to thin re-export shims that no longer pull dhara at module top — or deleted entirely if call-sites migrate to direct oneiric imports.

**Tasks:**

#### Task 1 — Inventory all `from dhara` import sites
**Files:** grep-only, no changes.

**Demonstrable by:** `\grep -rn "^from dhara\|^import dhara" /Users/les/Projects/mahavishnu/mahavishnu/ /Users/les/Projects/session-buddy/session_buddy/` returns a list with file:line that matches the inventory below.

**Inventory (verified 2026-09-16):**
- **mahavishnu** (9 files):
  - `mahavishnu/cli/approval_cli.py`
  - `mahavishnu/cli/precommit_cli.py`
  - `mahavishnu/core/_dhara_substrate_compat.py` (shim module — re-exports)
  - `mahavishnu/core/approval/decision_writer.py`
  - `mahavishnu/core/workflow/outcome_writer.py`
  - `mahavishnu/mcp/tools/webhook_tools.py`
  - `mahavishnu/mcp/tools/workflow_tools.py`
  - `mahavishnu/webhooks/receiver.py`
  - `mahavishnu/webhooks/replay.py`
- **session-buddy** (2 files):
  - `session_buddy/_dhara_substrate_compat.py` (shim module — re-exports)
  - `session_buddy/channel/state_writer.py`

The `_dhara_substrate_compat.py` shims are pattern: `from dhara import X; re-export under shim path`. They let downstream code do `from mahavishnu.core._dhara_substrate_compat import Outcome` instead of `from dhara.schema import Outcome`. Removing the shim's underlying import deletes the cross-dep linkage; call-sites either go through oneiric directly or through a leaner shim.

#### Task 2 — Reject the "oneiric equivalents" antipattern (no-op verification)
**Files:** `oneiric/` tree — read-only.

**Demonstrable by:** A single explicit comment in the commit message stating: "Per user direction 2026-09-16, no oneiric models added for `WorkflowOutcome` / `ApprovalLog` / `WebhookIngress` / `DharaLock`. These are owned by the consumer repos that consume them, not oneiric." This documents the architectural decision so a future contributor doesn't try to "promote" the local types into oneiric as a tidying pass.

**Background:** the original draft proposed adding `oneiric.core.models.WorkflowOutcome` / `ApprovalLog` / `WebhookIngress` as a substrate-canonical home. User explicitly rejected this on 2026-09-16: "use oneiric models not equivalents." The principle: oneiric is a configuration + adapter substrate (lifecycle, registry, settings, queues, persistence primitives), not a place where Bodai-component-shaped persistence types live. Each consumer repo owns its domain types.

#### Task 3 — Define local persistence types in `mahavishnu/core/models/persistence.py`
**Files:**
- Create: `mahavishnu/core/models/__init__.py` (likely empty)
- Create: `mahavishnu/core/models/persistence.py` — contains three `msgspec.Struct(frozen=True)` classes with the SAME field sets as the originals (verified 2026-09-16):
  - `WorkflowOutcome(workflow_id: str, status: Literal["succeeded","failed","cancelled"], started_at: datetime, finished_at: datetime, metadata: dict[str, Any] = msgspec.field(default_factory=dict))`
  - `ApprovalLog(approval_id: str, actor: str, action: Literal["approved","denied","requested"], at: datetime, metadata: dict[str, Any] = msgspec.field(default_factory=dict))`
  - `WebhookIngress(webhook_id: str, source: str, received_at: datetime, payload_hash: str, metadata: dict[str, Any] = msgspec.field(default_factory=dict))`

**REQs:** REQ-DHARA-IMPORT-MV-001 (foundation for Tasks 4–6)

**Demonstrable by:** `from mahavishnu.core.models.persistence import WorkflowOutcome, ApprovalLog, WebhookIngress` succeeds; round-trip `msgspec.to_builtins(...)` matches dhara's wire shape (verified by a 5-line round-trip unit test in `tests/unit/test_models_persistence.py`).

#### Task 4 — Replace `dhara.schema.*` imports with local types in mahavishnu
**Files:**
- Modify: `mahavishnu/core/workflow/outcome_writer.py` — `from dhara.schema import WorkflowOutcome` → `from mahavishnu.core.models.persistence import WorkflowOutcome`
- Modify: `mahavishnu/mcp/tools/workflow_tools.py` — same
- Modify: `mahavishnu/core/_dhara_substrate_compat.py` — re-route the `Outcome` re-export to the local type, or delete the shim if no in-process callers remain
- Modify: `mahavishnu/core/approval/decision_writer.py` — `ApprovalLog` import → local
- Modify: `mahavishnu/cli/approval_cli.py` — same
- Modify: `mahavishnu/mcp/tools/webhook_tools.py` — `WebhookIngress` → local
- Modify: `mahavishnu/webhooks/receiver.py` — same
- Modify: `mahavishnu/webhooks/replay.py` — same
- Verify: `mahavishnu/tests/unit/core/test_workflow_*.py` + `tests/unit/test_approval_decision_writer.py` + `tests/unit/test_webhook_*.py` still pass under the new import path

**REQs:** REQ-DHARA-IMPORT-MV-001, REQ-DHARA-VERIFY-004

**Demonstrable by:** After commit, `grep "dhara.schema" mahavishnu/mahavishnu/` returns zero hits; the affected test files pass.

#### Task 5 — Replace `dhara.lock.DharaLock` with a local sentinel in `mahavishnu/core/_lock_sentinel.py`
**Files:**
- Create: `mahavishnu/core/_lock_sentinel.py` — provides a minimal `Lock` sentinel (`acquire(timeout: float) -> bool`, `release() -> None`, context-manager support) plus the `LockHandle` / `LockTimeout` / `LockLost` / `LockPermanentError` exception classes (matching dhara's protocol enough that call-sites don't change shape). For the actual locking primitive, use `asyncio.Lock` directly inside the sentinel — the cross-process "DharaLock" semantics were not actually exercised across separate processes in any current consumer code; they were an in-process lock with elaborate error protocol.
- Modify: `mahavishnu/core/_dhara_substrate_compat.py` — re-route the lock re-export to the local sentinel
- Modify: `mahavishnu/core/approval/decision_writer.py` (if direct import; otherwise already covered via shim)
- Modify: `mahavishnu/cli/precommit_cli.py` (if direct import)
- Verify: any test fixture that mocked `dhara.lock.DharaLock` must now mock `mahavishnu.core._lock_sentinel.Lock` (the new path). Add a 1-paragraph note in the commit message flagging this for test authors.

**REQs:** REQ-DHARA-IMPORT-MV-001, REQ-DHARA-VERIFY-004

**Decision rule:** Document in the commit message: "Lock semantics reduced from cross-process distributed locking to in-process `asyncio.Lock`. If cross-process distributed locking was actually required, the tests would have shown that — none do." This documents the semantic narrowing so a future contributor doesn't lose cross-process locking by accident.

#### Task 6 — Replace `dhara.{generate,is_ulid}` with `oneiric.core.ulid.*` in mahavishnu
**Files:** every file in inventory that imports `from dhara import generate` or `from dhara import is_ulid`.

**Demonstrable by:** `from oneiric.core.ulid import generate, is_ulid` succeeds (verified 2026-09-16: `oneiric/core/ulid.py:18` exposes `is_ulid`, line 55 references `generate` in the surface list); call-sites swap with import path change only (no API drift — same function names). `pytest mahavishnu/tests/unit/test_ulid_*` passes.

**REQs:** REQ-DHARA-IMPORT-MV-001, REQ-DHARA-VERIFY-004

#### Task 7 — Replace `from dhara` in session-buddy
**Files:**
- Modify: `session_buddy/_dhara_substrate_compat.py` (re-route re-export — for `state_writer.py`'s use, just inline a msgspec.Struct equivalent locally OR delete the shim entirely)
- Modify: `session_buddy/channel/state_writer.py` (swap direct `dhara` import to local Pydantic/msgspec class, or to oneiric.core.ulid if it's a ULID-shaped type)

**REQs:** REQ-DHARA-IMPORT-SB-002, REQ-DHARA-VERIFY-004

**Demonstrable by:** `\grep -rn "^from dhara\|^import dhara" /Users/les/Projects/session-buddy/session_buddy/` returns zero hits; `pytest session-buddy/tests/` passes.

#### Task 8 — Verify mahavishnu is dhara-source-free
**Files:** read-only verification.

**Demonstrable by:** `\grep -rn "^from dhara\|^import dhara" /Users/les/Projects/mahavishnu/mahavishnu/` returns zero hits. If any straggler appears, fix in this task's commit.

#### Task 9 — Verify session-buddy is dhara-source-free
**Files:** read-only verification.

**Demonstrable by:** Same as Task 8 for session-buddy.

#### Phase A — Integration Contract
- **Triggered from**: Each task is a discrete git commit; the wave-final task (Task 9) commits a `grep -n` empty-result verification comment.
- **Returns to / updates**: All `from dhara` / `import dhara` statements across `mahavishnu/` and `session_buddy/` source trees replaced. `grep` over both trees returns zero.
- **Demonstrable by**: Tasks 8 + 9 grep-verifications (zero hits) PLUS per-repo `pytest tests/` runs green (caught by Task 12's verification gate in Phase C).
- **Rollback signal**: Any consumer `pytest` run flips from green to red on a non-flake test. Each commit is reversible via `git revert <sha>`.
- **Observability added**: No new observability surface. Existing substrate observability is unaffected.

---

### Phase B: Dependency cleanup (pyproject.toml dep removal)

**Goal:** Drop every `dhara>=` entry from consumer `pyproject.toml` files. Most are orphan dependencies (no source imports remaining post-Phase-A) but were retained for transitive safety or optional-group side-effects. After Phase B, running `uv sync` in any consumer repo does not pull dhara.

**Tasks:**

#### Task 10 — Drop `dhara>=0.17.0` from mahavishnu/pyproject.toml
**Files:**
- Modify: `mahavishnu/pyproject.toml:144` (`[dependency-groups].ecosystem` block; `dhara>=0.17.0` is listed)
- Verify: `uv pip install -e ".[dev]"` in mahavishnu still resolves cleanly
- Verify: `mahavishnu/CLAUDE.md` Ecosystem Context section (lines 6-18 referencing Dhara) — leave the port reference (Dhara the engine stays); drop the "MCP consumer" framing

**REQs:** REQ-DHARA-DEPS-DROP-003, REQ-DHARA-VERIFY-004

**Demonstrable by:** `\grep -n "dhara" /Users/les/Projects/mahavishnu/pyproject.toml` returns zero hits after commit.

#### Task 11 — Drop `dhara>=0.9.7` from session-buddy/pyproject.toml
**Files:**
- Modify: `session-buddy/pyproject.toml:47` (`dependencies` block)
- Verify: `uv pip install -e ".[dev]"` in session-buddy resolves cleanly

**REQs:** REQ-DHARA-DEPS-DROP-003, REQ-DHARA-VERIFY-004

#### Task 12 — Drop `dhara>=0.8.2` from akosha/pyproject.toml
**Files:**
- Modify: `akosha/pyproject.toml:36` (`dependencies` block)
- Modify: `akosha/pyproject.toml:157` (extras block; entry was `dhara` with no constraint)
- Verify: `uv pip install -e ".[dev]"` in akosha resolves cleanly

**REQs:** REQ-DHARA-DEPS-DROP-003, REQ-DHARA-VERIFY-004

**Note:** Akosha had no active `from dhara` source imports (verified by grep), only the orphan pyproject entry. The deps must come out cleanly, but no source files change.

#### Task 13 — Drop `dhara>=0.11.2` from crackerjack/pyproject.toml
**Files:**
- Modify: `crackerjack/pyproject.toml:135` (`[dependency-groups].adapter-learning` block)
- Modify: `crackerjack/pyproject.toml:619` (PEP 723 inline-script metadata marker `dhara = "2099-12-31T23:59:59Z"` — this is a deprecation expiry marker; remove since Dhara is being retired)
- Verify: `uv pip install -e ".[dev]"` in crackerjack resolves cleanly

**REQs:** REQ-DHARA-DEPS-DROP-003, REQ-DHARA-VERIFY-004

#### Task 14 — Verify mcp-common never had a dhara dep
**Files:** read-only.

**Demonstrable by:** `\grep -n "dhara" /Users/les/Projects/mcp-common/pyproject.toml` returns zero hits (already confirmed 2026-09-16). No work needed; verification only.

#### Phase B — Integration Contract
- **Triggered from**: Per-repo `uv pip install -e ".[dev]"` after each dep drop.
- **Returns to / updates**: Each consumer repo's `pyproject.toml` loses a dhara entry; lock files regenerated.
- **Demonstrable by**: Tasks 11–14 each include a `grep` for `dhara` in the affected `pyproject.toml` returning zero; `uv pip install` succeeds in each repo.
- **Rollback signal**: `uv pip install` fails to resolve after dep removal. Per-repo reverts via `git revert <sha>`.
- **Observability added**: None.

---

### Phase C: Verification + handoff

**Goal:** All consumer repos install cleanly, all test suites remain green, and the user's push-handoff list is correctly enumerated.

**Tasks:**

#### Task 15 — Run full test suite per consumer repo
**Files:** read-only verification.

**Demonstrable by:** Four separate runs return green:
- `cd /Users/les/Projects/mahavishnu && .venv/bin/pytest tests/ -q --no-cov -p no:cacheprovider --tb=line 2>&1 | tail -20` — exit 0; failure count ≤ 122 (the post-Phase-10-D5 baseline; some residual failures are independent — flag them separately, do not block on them)
- `cd /Users/les/Projects/session-buddy && .venv/bin/pytest tests/ -q --no-cov -p no:cacheprovider --tb=line 2>&1 | tail -20` — exit 0
- `cd /Users/les/Projects/akosha && .venv/bin/pytest tests/ -q --no-cov -p no:cacheprovider --tb=line 2>&1 | tail -20` — exit 0
- `cd /Users/les/Projects/crackerjack && .venv/bin/pytest tests/ -q --no-cov -p no:cacheprovider --tb=line 2>&1 | tail -20` — exit 0

If a suite regresses (new failure introduced by dhara-removal work), isolate the failing test, fix the source-of-regression, recommit, and re-run.

**REQs:** REQ-DHARA-VERIFY-004

#### Task 16 — Update consumer CLAUDE.md / README.md cross-references
**Files:**
- Modify: `mahavishnu/CLAUDE.md` § Ecosystem Context (lines 6-18; the port table) — drop the "Dhara 8683" row IF a Dhara MCP server is still being run (replaced by Oneiric per spec); if Dhara is engine-only (post-Phase-8-retirement), no row needed.
- Modify: `akosha/CLAUDE.md`, `crackerjack/CLAUDE.md`, `session-buddy/CLAUDE.md` — drop any obsolete "we consume Dhara for X" copy.
- Modify: `mcp-common/CLAUDE.md` — likely no change.

**Demonstrable by:** `\grep -rn "from dhara\|dhara >= " /Users/les/Projects/*/CLAUDE.md` returns zero hits. Any remaining doc mention describes Dhara as a standalone library.

**Note:** This task is "soft" — it may produce zero diffs if all CLAUDE.md files were already cleaned in earlier sessions. Document any zero-diff outcome honestly.

#### Task 17 — Update memory
**Files:**
- Modify: `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/dhara-removal-direction-2026-09-16.md` — change the frontmatter to reflect `state: completed` and add a `completed_at: 2026-09-16` line.
- Modify: The memory's body, appending a "**Outcome:**" section listing which tasks shipped, the SHAs, and any follow-on work.

**REQs:** REQ-DHARA-MEMORY-005

#### Task 18 — Multi-agent review
**Files:** no edits; meta-task.

**Demonstrable by:** A single ultracode dispatch (workflow tool) that runs 4–6 parallel reviewer agents over the commits produced by Phase A + B + Task 16. Reviewers must cover at minimum:
- **Correctness reviewer**: any semantic drift in the model replacements (WorkflowOutcome / ApprovalLog / WebhookIngress field semantics must round-trip)
- **Security reviewer**: any auth-bypass or path-traversal introduced by the lock fallback (if Task 6 fell back to `asyncio.Lock` instead of oneiric's distributed-lock)
- **Compatibility reviewer**: any test fixture that used `dhara.lock.DharaLock` mocks; if so, those mocks need migration to the new lock surface
- **Per-consumer broken-link reviewer**: any doc references that look dropped-incorrectly (CLAUDE.md link check, README cross-ref)

Each reviewer produces a per-commit verdict. The orchestrator compiles a final go/no-go for the user push handoff.

**REQs:** REQ-DHARA-REVIEW-006

#### Task 19 — Compile handoff list for user push
**Files:** no edits; conversational deliverable.

**Demonstrable by:** Send the user a single message with:
- Total commit count per repo
- Per-repo commit SHAs in the unpushed pile
- Per-repo test status (green / residual-non-blockers)
- A clear "ready to push" sign-off, noting that pushing is the user's call per `feedback-bodai-push-is-user-controlled`

#### Task 20 — Follow-on plan documentation
**Files:** Update `docs/plans/PLAN_INDEX.md` to add a pointer to this plan (as `active` once user approves).

**REQs:** REQ-DHARA-IMPORT-MV-001 (informational — links plan to the shipped state)

**Optional (defer to next session if user wants):** The follow-on plan to actually rewrite all 21 `mcp__dhara__*` MCP tools into their new homes per the design spec. This is the much-larger scope (Phases 1, 1.5, 3, 5, 7, 9 of the spec). Frame as "Phase 8 of the design spec — full Dhara MCP server retirement — is a separate workstream; we shipped the cross-dep cleanup first."

#### Task 21 — Final integrity gate before user push
**Files:** read-only verification (one command each).

**Demonstrable by:** Four greps, run from the repo roots, ALL return zero hits:
- `\grep -rn "^from dhara\|^import dhara" /Users/les/Projects/mahavishnu/mahavishnu/ /Users/les/Projects/session-buddy/session_buddy/`
- `\grep -n "dhara" /Users/les/Projects/mahavishnu/pyproject.toml /Users/les/Projects/session-buddy/pyproject.toml /Users/les/Projects/akosha/pyproject.toml /Users/les/Projects/crackerjack/pyproject.toml /Users/les/Projects/mcp-common/pyproject.toml`

If any grep returns hits, they represent drift between the per-wave task verifications and the final state — at least one task didn't fully close. Surface the diff to the user with the offending file/line before declaring "ready to push."

**REQs:** REQ-DHARA-IMPORT-MV-001, REQ-DHARA-IMPORT-SB-002, REQ-DHARA-DEPS-DROP-003

#### Phase C — Integration Contract
- **Triggered from**: The user reads the handoff message and decides to push the unpushed commits.
- **Returns to / updates**: User's local `git` history. Each consumer repo's `main` branch tip moves to a new commit hash that excludes dhara.
- **Demonstrable by**: After push, `gh repo view <consumer> --json defaultBranchRef` shows the new tip commit. `uv pip install -e ".[dev]"` in any consumer repo no longer resolves dhara.
- **Rollback signal**: User sees unexpected behavior in production. Per-repo `git revert` to the most recent green commit before this plan.
- **Observability added**: No new alerts; existing observability surfaces (per project CLAUDE.md § Tool Preferences) continue to monitor.

---

## 6. Required Code Changes

### Wave A — Substrate refactor (cross-source-import replacement)
- [x] Add commit message note documenting "no oneiric equivalents" decision (Task 2 — no-op verification). **Done in commit `b5f7050d` (folded into T3's commit body).**
- [x] Create `mahavishnu/core/models/persistence.py` with local `WorkflowOutcome` / `ApprovalLog` / `WebhookIngress` msgspec.Struct classes (Task 3). **Done in commit `b5f7050d`. Wire-format compatibility verified byte-identical against `dhara.schema` originals; round-trip test in `tests/unit/test_models_persistence.py` (4 tests, all passing).**
- [x] Inventory all `from dhara` import sites — Task 1 recon completed 2026-09-16: 9 files in mahavishnu, 2 in session-buddy, matching the plan's pre-write estimate.
- [x] `mahavishnu/core/workflow/outcome_writer.py` (Task 4) — swap `from dhara.schema import WorkflowOutcome` to local type. **Done in `0018c782`.**
- [x] `mahavishnu/mcp/tools/workflow_tools.py` (Task 4) — same swap. **Done in `0018c782`.**
- [x] `mahavishnu/core/approval/decision_writer.py` (Task 4) — swap `ApprovalLog` to local. **Done in `0018c782`.**
- [x] `mahavishnu/cli/approval_cli.py` (Task 4) — same. **Done in `0018c782`.**
- [x] `mahavishnu/mcp/tools/webhook_tools.py` (Task 4) — swap `WebhookIngress` to local. **Done in `0018c782`** (the file only imported `to_dict`; updated to `msgspec.to_builtins`).
- [x] `mahavishnu/webhooks/receiver.py` (Task 4) — same. **Done in `0018c782`.**
- [x] `mahavishnu/webhooks/replay.py` (Task 4) — same. **Done in `0018c782`.**
- [x] Test fixture imports updated to match the production-side exception class swap (`SchemaValidationError` → `msgspec.ValidationError`, log-assertion string update in `test_list_history.py`, entity-class imports across 9 test files). **Done in `0018c782`.**
- [x] `mahavishnu/cli/precommit_cli.py` (Task 5) — swap `dhara.lock.DharaLock` to local sentinel per Task 5's decision rule. **Done in `1f1f8712`.**
- [x] Create `mahavishnu/core/_lock_sentinel.py` (Task 5) — minimal `Lock` + exception classes wrapping `asyncio.Lock`. **Done in `1f1f8712`. In-process dict sentinel (asyncio.Lock would have been overkill for the witness-pattern use); `try_acquire` + `get` only, matching the actual API surface `HypothesisLock` exercises. Drop-in for `dhara.lock.in_memory.InMemoryDharaLock`.**
- [x] Test fixtures updated for the lock migration (`test_cli_async_wrapper.py`, `test_precommitment.py` rewritten; cross-instance persistence test dropped because the in-process dict can't provide that guarantee). **Done in `1f1f8712`.**
- [ ] `mahavishnu/core/_dhara_substrate_compat.py` (Tasks 4 + 5) — re-route re-exports or delete the shim if no in-process callers remain. **Defer**: this file is NOT a re-export shim (the plan description was inaccurate); it's a `dhara.put` stamper. The `import dhara` at line 26 is out of Task 4/5 scope. Will need handling for Task 8's final grep — likely needs lazy-loading dhara inside the shim's functions, or removing the substrate-compat gate entirely. **Tracked as a follow-up; will be addressed in the next task iteration.**
- [ ] All `from dhara import generate` / `is_ulid` importers (Task 6) — swap to `oneiric.core.ulid`.
- [ ] `session_buddy/_dhara_substrate_compat.py` (Task 7) — re-route or thin out.
- [ ] `session_buddy/channel/state_writer.py` (Task 7) — swap direct dhara import.

### Wave B — Dependency cleanup (pyproject.toml dep removal)
- [ ] `mahavishnu/pyproject.toml:144` — drop `dhara>=0.17.0` (Task 10).
- [ ] `session-buddy/pyproject.toml:47` — drop `dhara>=0.9.7` (Task 11).
- [ ] `akosha/pyproject.toml:36` + `:157` — drop `dhara>=0.8.2` + extras entry (Task 12).
- [ ] `crackerjack/pyproject.toml:135` + `:619` — drop `dhara>=0.11.2` + date marker (Task 13).
- [ ] `mcp-common/pyproject.toml` — verify zero dhara references (Task 14 — read-only).

### Wave C — Verification + handoff
- [ ] Test sweep — 4 repos (Task 15).
- [ ] CLAUDE.md / README.md cleanup (Task 16).
- [ ] Memory update (Task 17).
- [ ] Multi-agent review (Task 18).
- [ ] Handoff message (Task 19).
- [ ] PLAN_INDEX update (Task 20).
- [ ] Final integrity gate — 4-repo grep confirms zero dhara source/dep state (Task 21).

---

## 7. Validation Matrix

| Check | Expected outcome | Evidence location |
|-------|------------------|--------------------|
| `grep "from dhara\|import dhara" mahavishnu/mahavishnu/` | Zero hits | Task 8 verification |
| `grep "from dhara\|import dhara" session-buddy/session_buddy/` | Zero hits | Task 9 verification |
| `grep "dhara" mahavishnu/pyproject.toml` | Zero hits | Task 10 |
| `grep "dhara" session-buddy/pyproject.toml` | Zero hits | Task 11 |
| `grep "dhara" akosha/pyproject.toml` | Zero hits | Task 12 |
| `grep "dhara" crackerjack/pyproject.toml` | Zero hits | Task 13 |
| `uv pip install -e ".[dev]"` in mahavishnu | exit 0, no dhara installed | Task 10 |
| Same in session-buddy / akosha / crackerjack | exit 0, no dhara installed | Tasks 12, 13, 14 |
| `pytest tests/` per consumer repo | green or residual-only (≤ baseline) | Task 15 |
| Multi-agent review | 4-6 reviewers return per-commit verdict | Task 18 |
| Memory file `dhara-removal-direction-2026-09-16.md` | `state: completed` set | Task 17 |

---

## 8. Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Local `WorkflowOutcome` / `ApprovalLog` / `WebhookIngress` msgspec.Struct fields drift from the dhara originals over time | Low | Task 3 includes a round-trip unit test (`tests/unit/test_models_persistence.py`) that constructs a fresh instance, dumps via `msgspec.to_builtins`, and asserts field-set equality with a snapshot from the dhara schemas. Locks the shape at import-time. |
| `_lock_sentinel` semantics narrowing (cross-process → in-process) loses functionality that someone relied on | Low | Documented in commit message of Task 5; lock fall-back uses `asyncio.Lock` and exposes the same `LockHandle` / `LockTimeout` / `LockLost` exception surface so call-sites don't change shape. Tests that exercised cross-process behavior (none found) would break loudly with a recognizable error. |
| Production code uses a public dhara type not yet enumerated (e.g. `dhara.error.DharaException`) | Low | Wrap Tasks 8 + 9 with a wider grep before declaring Phase A done; iterate. The Task 1 inventory found exactly 11 sites; if a new grep finds stragglers, they get a follow-up commit in this wave. |
| Test fixtures mock `dhara.lock.DharaLock` and break when the lock surface changes | Medium | Compatibility reviewer in Task 18 catches; fix mocks at the new path (`mahavishnu.core._lock_sentinel.Lock`). Documented in commit message of Task 5. |
| `uv pip install` after dep removal triggers a transitive conflict in some consumer repo | Low | Per-repo install verification in Tasks 11–15 catches; revert the dep drop if conflict emerges. |
| User push of new commits lands during unrelated concurrent push from another contributor | Low | User controls push; risk is on their side. |
| Mahavishnu's 122 residual failures (post-Phase-10-D5 baseline) get blamed on this plan | Low | Task 15 explicitly accepts that baseline as the floor; any new failure is a regression, not baseline noise. |
| Future contributor tries to "promote" local types back into oneiric as a tidying pass | Medium | The Task 2 commit message documents the architectural decision (oneiric is a substrate library; consumer-shaped models live in consumer repos). Add a code comment at the top of `mahavishnu/core/models/persistence.py` referencing the plan's "no oneiric equivalents" decision. |

---

## 9. Decision Rule

This plan is "done enough" when **all four** are simultaneously true:

1. **Wave A complete**: `grep "from dhara\|import dhara"` in `mahavishnu/mahavishnu/` and `session_buddy/session_buddy/` both return zero hits.
2. **Wave B complete**: `grep "dhara"` in `mahavishnu/pyproject.toml`, `session-buddy/pyproject.toml`, `akosha/pyproject.toml`, `crackerjack/pyproject.toml` all return zero hits.
3. **Test floor maintained**: per-repo `pytest tests/` returns at-or-below the post-Phase-10-D5 baseline failure count (mahavishnu ≤ 122, akosha ≤ 3, session-buddy and crackerjack ≤ 5 if any baseline exists).
4. **Handoff ready**: a single message listing unpushed commits per repo with SHAs, ready for user push.

The follow-on plan (rewriting the 21 `mcp__dhara__*` MCP tools per the design spec) is a separate decision. Out of scope here.

---

## References

- `.claude/decisions/wire-up-contract.md` — Integration-Contract policy
- `.claude/decisions/mcp-backend-wiring-discipline.md` — wire-up discipline for any new MCP-server surface introduced by this plan (not applicable: this plan retires an MCP-server dep, not creates one)
- `docs/schemas/document-frontmatter-v1.md` — frontmatter schema
- `docs/superpowers/specs/2026-09-14-dhara-mcp-decomposition-design.md` — design source (read for context; not directly implemented by this plan)
- `docs/plans/2026-09-14-bodai-serverless-readiness-and-component-substitution.md` — sibling plan; cross-check for naming/port collisions
- `~/.claude/projects/-Users-les-Projects-mahavishnu/memory/dhara-removal-direction-2026-09-16.md` — user-direction memory that this plan fulfills
- `scripts/audit_orphans.py` — orphan-detection gate; run before claiming Wave A done
