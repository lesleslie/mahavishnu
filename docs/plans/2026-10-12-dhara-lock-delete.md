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

**Goal:** Remove the substrate-compat shim `dhara/dhara/lock/` (the `DharaLock` Protocol + 5 implementations) and confirm `mahavishnu.core._lock_sentinel.Lock` is the canonical substrate-agnostic home for in-process lock coordination. This is a substrate-compat rot cleanup per `feedback-substrate-compat-shim-rot.md`: the substrate was decommissioned (commit `056e1b77`, `.mcp.json`), the lock primitive was re-homed to `mahavishnu.core._lock_sentinel` per the MCP retirement plan's Phase 8 Task 5, and the surviving `dhara/dhara/lock/` module is now a tombstone.

**Architecture:** The `dhara/dhara/lock/` package currently contains 7 modules: `__init__.py`, `events.py`, `in_memory.py`, `postgres.py`, `protocol.py`, `routes.py`, `sql.py`. None of them have active consumers in the current Bodai code (verified 2026-10-12: zero `DharaLock` imports in `akosha/`, `session-buddy/`, `crackerjack/`, `mcp-common/`, `oneiric/`; exactly one direct consumer in `mahavishnu/` is `_lock_sentinel.py`, which does NOT import `DharaLock` — it's a self-contained dict-backed sentinel that intentionally mirrors the shape). The M-* plans (`M-APPROVAL-LOG`, `M-WEBHOOK-DURABLE`, `M-WORKFLOW-OUTCOME`) route through `mahavishnu/core/models/persistence.py` + `mcp.put` and do not directly import `DharaLock` either.

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

## Phase 2 — Delete the module

- [ ] From `dhara/` repo: `git rm -r dhara/lock/`
- [ ] Update `dhara/dhara/__init__.py` (if it re-exports the lock surface) to remove the lock re-exports.
- [ ] Search `dhara/` for any other references: `rg -n 'dhara.lock\|DharaLock' dhara/ --type py` — should be 0 hits after the deletion.

## Phase 3 — Verification

- [ ] `crackerjack run -v` clean (or `pytest -q dhara/tests/` if crackerjack isn't configured for the dhara repo).
- [ ] From `mahavishnu` repo: `rg -ln 'DharaLock\|from dhara.lock' --type py` — expected: 0 hits.
- [ ] `M-APPROVAL-LOG`, `M-WEBHOOK-DURABLE`, `M-WORKFLOW-OUTCOME` integration tests still pass (these are the most Dhara-touched surfaces; they should pass since they go through the persistence mirror, not directly through `DharaLock`).

## Phase 4 — Documentation

- [ ] Add a 1-paragraph entry to `dhara/CHANGELOG.md` under the next version: "Removed `dhara.lock` module; lock primitive moved to substrate-agnostic `mahavishnu.core._lock_sentinel.Lock`. The `DharaLock` Protocol had zero active consumers at the time of removal."
- [ ] Update `docs/decisions/` if a prior ADR cited the lock surface; the `2026-09-24-legacy-worker-deprecation.md` decision may need a sibling decision.

## Phase 5 — Commit

- [ ] Single commit on `main` (dhara repo) with message: `chore(dhara): delete lock/ module — substrate-compat shim rot`
- [ ] Do NOT push. Per `feedback-bodai-push-is-user-controlled.md`, push is the user's call.

## Rollback signal

If any Phase 3 test fails after the deletion, the rollback is `git revert <commit-hash>` (the deletion is a single file-tree change, so revert is a clean restore).

## Observability added

- The `mahavishnu.core._lock_sentinel.Lock` class already emits `info`-level log lines on `try_acquire` collisions (existing behavior). No new observability needed for the deletion itself; any consumer that breaks will surface as an `ImportError` at module load time, which is the natural failure mode.

## Cross-references

- `feedback-substrate-compat-shim-rot.md` — the memory rule this plan implements
- `docs/plans/2026-09-16-dhara-mcp-retirement-plan.md` (status: complete) — the parent decommissioning event
- `mahavishnu/core/_lock_sentinel.py` — the canonical substrate-agnostic home
- `docs/plans/2026-08-03-crackerjack-c-wire-plan.md` Task 6 (active) — the next consumer of the lock primitive; C-WIRE Task 6 follow-up plan will reference the canonical `Lock` sentinel, not the deleted `DharaLock`
