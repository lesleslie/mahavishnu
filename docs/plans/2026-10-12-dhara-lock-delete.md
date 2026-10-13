---
status: active
role: canonical
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
topic: dhara-lock-substrate-compat-rot
title: "Delete dhara/dhara/lock/ — substrate-compat shim rot"
---

# Delete `dhara/dhara/lock/` — Substrate-Compat Shim Rot

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the substrate-compat shim `dhara/dhara/lock/` (the `DharaLock` Protocol + 3 implementations) and confirm `mahavishnu.core._lock_sentinel.Lock` is the canonical substrate-agnostic home for in-process lock coordination. This is a substrate-compat rot cleanup per `feedback-substrate-compat-shim-rot.md`: the substrate was decommissioned (the SHA was rebased away; the active top-of-tree in `/Users/les/Projects/dhara/` is `5593d89 chore(slash): remove dhara 1:1 wrapper slash commands`), the lock primitive was re-homed to `mahavishnu.core._lock_sentinel` per the MCP retirement plan's Phase 8 Task 5, and the surviving `dhara/dhara/lock/` module is now a tombstone.

**Architecture:** The `dhara/dhara/lock/` package currently contains 7 modules: `__init__.py`, `events.py`, `in_memory.py`, `postgres.py`, `protocol.py`, `routes.py`, `sql.py`. None of them have active consumers in the current Bodai code (verified 2026-10-12: zero `DharaLock` imports in `akosha/`, `session-buddy/`, `crackerjack/`, `mcp-common/`, `oneiric/`; exactly one direct consumer in `mahavishnu/` is `_lock_sentinel.py`, which does NOT import `DharaLock` — it's a self-contained dict-backed sentinel that intentionally mirrors the shape). The M-* plans (`M-APPROVAL-LOG`, `M-WEBHOOK-DURABLE`, `M-WORKFLOW-OUTCOME`) route through `mahavishnu/core/models/persistence.py` + `mcp.put` and do not directly import `DharaLock` either.

The lock module itself contains **1 Protocol** (`DharaLock` at `dhara/dhara/lock/protocol.py:41`) and **3 implementations** (`InMemoryDharaLock` at `dhara/dhara/lock/in_memory.py:19`, `SQLBackendLock` at `dhara/dhara/lock/sql.py:98`, `PostgresBackendLock` at `dhara/dhara/lock/postgres.py:154`). The original plan draft's "5 implementations" claim was overcounted. Verified 2026-10-12.

**Tech Stack:** Python 3.14, git, no new dependencies.

## Global Constraints

- `from __future__ import annotations` first non-comment line of every new module (if any).
- No new lock primitives: this is a deletion + verification plan, not an implementation plan.
- Path: `dhara/dhara/lock/` is in the `dhara` repo (`/Users/les/Projects/dhara/`), NOT in `mahavishnu/`. The deletion must be committed to the `dhara` repo and pushed (per the user-controlled push policy) — no PR.

## Phase 1 — Verify no consumers

- [ ] Run from mahavishnu repo root: `rg -ln 'DharaLock\|from dhara.lock\|import dhara.lock' --type py` — expected output: `mahavishnu/core/_lock_sentinel.py` ONLY (and that file does NOT actually `import DharaLock`; verify with `rg -n 'DharaLock' mahavishnu/core/_lock_sentinel.py` which should return 0 hits).
- [ ] Run from each sibling repo root: `akosha/`, `session-buddy/`, `crackerjack/`, `mcp-common/`, `oneiric/` — all should return 0 hits.
- [ ] Run from `dhara/` repo: `rg -ln 'DharaLock' dhara/ --type py` — should only show the module itself.
- [ ] If any consumer is found, STOP and revise the plan to migrate them to `mahavishnu.core._lock_sentinel.Lock` first.
- [ ] **Special case — `medium-mcp`**: it imports `from dhara.lock.in_memory import InMemoryDharaLock` at `medium-mcp/medium_mcp/dhara/client.py:7` (used at :29/:47/:70) for budget-counter atomicity in the `DharaClient`. `medium-mcp` is a `*-mcp` repo (per `feedback-no-bodai-mentions-in-mcp-repos`) but the import is real. Scope this Phase 1 rg to Bodai-core repos (`mahavishnu/`, `akosha/`, `session-buddy/`, `crackerjack/`, `mcp-common/`, `oneiric/`, `dhara/`) — the `medium-mcp` consumer is addressed by the separate `2026-10-13-medium-mcp-migrate-off-dhara.md` plan, not by Phase 1. Phase 1.5 below sequences the dependency.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent confirming no consumers before deleting the module.
- **Returns to / updates**: nothing persisted; a documented consumer inventory (a list of paths with `DharaLock` references and what each does).
- **Demonstrable by**: the `rg` commands return the expected counts; a paste of the output to the commit message is sufficient evidence.
- **Rollback signal**: not applicable — Phase 1 is read-only.
- **Observability added**: none.

## Phase 1.5 — Wait for `medium-mcp` migration to land (cross-repo sequencing gate)

This plan **must not** delete `dhara/dhara/lock/` until the `medium-mcp` consumer is migrated off. The medium-mcp migration is a separate plan (`2026-10-13-medium-mcp-migrate-off-dhara.md`, lives in `/Users/les/Projects/medium-mcp/docs/plans/`) that replaces the `InMemoryDharaLock` import with a substrate-agnostic in-process lock primitive (~30-line `medium_mcp/utils/in_process_lock.py` mirroring `mahavishnu.core._lock_sentinel.Lock`'s shape).

- [ ] Confirm the medium-mcp migration plan exists: `test -f /Users/les/Projects/medium-mcp/docs/plans/2026-10-13-medium-mcp-migrate-off-dhara.md`.
- [ ] Confirm the migration has landed: `rg -n 'from dhara.lock\|import dhara.lock' /Users/les/Projects/medium-mcp/ --type py` should return 0 hits after the migration.
- [ ] **No `blocks_on:` frontmatter dep** on the medium-mcp migration — Phase 1.5 is a sequencing note, not a hard dep, because the medium-mcp migration can land in any order before Phase 1 here.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent checking the sequencing gate before Phase 2 (the `git rm`).
- **Returns to / updates**: nothing persisted; the medium-mcp consumer is migrated off Dhara before this plan deletes the Dhara substrate.
- **Demonstrable by**: `rg -n 'from dhara.lock\|import dhara.lock' /Users/les/Projects/medium-mcp/ --type py` returns 0 hits.
- **Rollback signal**: medium-mcp migration breaks tests (`pytest medium-mcp/` fails) — the migration must be reworked before Phase 2 here proceeds.
- **Observability added**: none.

## Phase 2 — Delete the module

- [ ] From `dhara/` repo: `git rm -r dhara/lock/`
- [ ] Run `rg -n 'lock' dhara/dhara/__init__.py` to confirm no re-exports exist (the original plan's "if it re-exports" check was a no-op — `dhara/dhara/__init__.py` does not re-export any lock symbol; verified 2026-10-12). No edit needed to `__init__.py`.
- [ ] Search `dhara/` for any other references: `rg -n 'dhara.lock\|DharaLock' dhara/ --type py` — should be 0 hits after the deletion.

#### Integration Contract ← REQUIRED
- **Triggered from**: `git rm -r dhara/lock/` (Phase 2 step 1).
- **Returns to / updates**: `dhara/dhara/lock/` is removed from the working tree and staged for commit.
- **Demonstrable by**: `test -d dhara/dhara/lock` returns 1 (directory does not exist); `git status --short` shows the deletion staged.
- **Rollback signal**: not applicable pre-commit; post-commit, `git revert <commit-hash>` restores the directory.
- **Observability added**: none.

## Phase 3 — Verification

- [ ] `crackerjack run -v` clean (or `pytest -q dhara/tests/` if crackerjack isn't configured for the dhara repo).
- [ ] From `mahavishnu` repo: `rg -ln 'DharaLock\|from dhara.lock' --type py` — expected: 0 hits.
- [ ] `M-APPROVAL-LOG`, `M-WEBHOOK-DURABLE`, `M-WORKFLOW-OUTCOME` integration tests still pass (these are the most Dhara-touched surfaces; they should pass since they go through the persistence mirror, not directly through `DharaLock`).

#### Integration Contract ← REQUIRED
- **Triggered from**: `pytest` / `crackerjack run` post-deletion.
- **Returns to / updates**: nothing persisted; the M-* integration tests pass.
- **Demonstrable by**: `pytest -q` exits 0; `rg 'DharaLock' --type py` returns 0 hits across the fleet.
- **Rollback signal**: any test in `M-APPROVAL-LOG` / `M-WEBHOOK-DURABLE` / `M-WORKFLOW-OUTCOME` fails.
- **Observability added**: none.

## Phase 4 — Documentation

- [ ] Add a 1-paragraph entry to `dhara/CHANGELOG.md` under the next version: "Removed `dhara.lock` module; lock primitive moved to substrate-agnostic `mahavishnu.core._lock_sentinel.Lock`. The `DharaLock` Protocol had 1 Protocol + 3 implementations (InMemory, SQL, Postgres) at the time of removal; zero active consumers."
- [ ] Update `docs/decisions/` if a prior ADR cited the lock surface; the `2026-09-24-legacy-worker-deprecation.md` decision may need a sibling decision.
- [ ] Demonstrate by `grep "Removed dhara.lock" dhara/CHANGELOG.md` exits 0.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent editing `dhara/CHANGELOG.md`.
- **Returns to / updates**: `dhara/CHANGELOG.md` gains a one-paragraph removal note under the next version; `docs/decisions/` gains a sibling decision if needed.
- **Demonstrable by**: `grep "Removed dhara.lock" dhara/CHANGELOG.md` exits 0; the changelog is committed in the same commit as the deletion (or a paired commit if a sibling decision was added).
- **Rollback signal**: the changelog entry is wrong (factual error) post-merge.
- **Observability added**: none.

## Phase 5 — Commit

- [ ] Single commit on `main` (dhara repo) with message: `chore(dhara): delete lock/ module — substrate-compat shim rot (1 Protocol + 3 implementations, 0 consumers)`
- [ ] Use `git -c user.email="les@wedgwoodwebworks.com" commit ...` (per `git-author-email-correct-domain.md`)
- [ ] Do NOT add `Co-Authored-By` trailer (per `feedback-no-claude-code-coauthor-attribution.md`)
- [ ] Do NOT push (per `feedback-bodai-push-is-user-controlled.md`)

#### Integration Contract ← REQUIRED
- **Triggered from**: `git commit` (with the staged deletion + the changelog edit).
- **Returns to / updates**: a single commit on `dhara` repo `main` that removes the lock module and updates the changelog.
- **Demonstrable by**: `git log --oneline -1` shows the commit message; `git show --stat HEAD` shows the deletion + the changelog edit.
- **Rollback signal**: not applicable pre-push; post-push, `git revert <commit-hash>` restores.
- **Observability added**: none.

## Rollback signal

If any Phase 3 test fails after the deletion, the rollback is `git revert <commit-hash>` (the deletion is a single file-tree change, so revert is a clean restore).

## Observability added

- The `mahavishnu.core._lock_sentinel.Lock` class already emits `info`-level log lines on `try_acquire` collisions (existing behavior). No new observability needed for the deletion itself; any consumer that breaks will surface as an `ImportError` at module load time, which is the natural failure mode.

## Cross-references

- `feedback-substrate-compat-shim-rot.md` — the memory rule this plan implements
- `docs/plans/2026-09-16-dhara-mcp-retirement-plan.md` (status: complete) — the parent decommissioning event
- `mahavishnu/core/_lock_sentinel.py` — the canonical substrate-agnostic home
- `docs/plans/2026-08-03-crackerjack-c-wire-plan.md` Task 6 (active) — the next consumer of the lock primitive; C-WIRE Task 6 follow-up plan will reference the canonical `Lock` sentinel, not the deleted `DharaLock`
