---
status: active
role: implementation
kind: plan
date: 2026-10-29
last_reviewed: 2026-10-29
superseded_by: null
blocks_on: []
topic: resolver
title: "Oneiric Resolver — Precedence Contract and Scope Deferrals (pointer to oneiric plans)"
---

# Oneiric Resolver — Precedence Contract and Scope Deferrals

> **This is a pointer, not an implementation plan.** The work is specified in two
> plans that live in the **oneiric** repository, because that is where the code
> they change lives. Do not implement from this file — read the linked plans.

## Purpose

Two implementation plans for Oneiric's resolver layer were authored on
2026-10-29 and parked for a dedicated implementation session. They live in
oneiric's plan store, so a session starting in mahavishnu would not otherwise
find them. This file makes them discoverable from mahavishnu's plan index.

## The plans

| Plan | Location | Status | Tasks |
|---|---|---|---|
| Resolver precedence contract and empty-result explanation | `~/Projects/oneiric/docs/plans/2026-10-29-resolver-precedence-contract-and-empty-result-explanation.md` | `active` | 3 |
| Resolver scope deferrals and reopening triggers | `~/Projects/oneiric/docs/plans/2026-10-29-resolver-scope-deferrals-and-triggers.md` | `active` | 3 |

Committed in oneiric as `6fc38a3` ("docs(plans): add resolver precedence and scope-deferral plans").
Both are indexed in `~/Projects/oneiric/docs/plans/PLAN_INDEX.md` — that is the
authoritative index for them.

## What they cover

**Plan A — precedence contract and empty-result explanation.** No ranking
behavior changes.

1. Reconcile `oneiric/docs/RESOLUTION_LAYER_SPEC.md` with the code's
   capability-coverage tier, which ranks *above* priority but is absent from
   the spec's precedence list. Pin the registration-order tiebreak (last
   registered wins) with characterization tests, plus a spec↔code sync guard.
2. Rewrite `~/.claude/skills/resolve-components/SKILL.md`, which documents a
   **fictional API** — the module path `oneiric.core.resolver`, an
   `oneiric.core.priority` module with an `@priority` decorator, and eleven
   methods (`select`, `clear_selection`, `candidates`, `conflicts`,
   `set_priority`, `register_hook`, `ResolutionHook`, and others) that have
   zero definitions in the oneiric source tree.
3. Report capability-filtered candidates in `explain()` instead of dropping
   them silently, so "nothing won" is distinguishable from "nothing was
   registered".

**Plan B — scope deferrals and reopening triggers.** Records six resolver
scope decisions — provider protocol, joint/set resolution, config
interpolation for action kits, priority sentinels, plugin position
directives, and conflict-chain explanation — each with an observable
reopening trigger, plus a guard test that fails when `CandidateSource` gains
a fifth member.

## Why they live in oneiric

The resolver implementation is `oneiric/core/resolution.py`; the canonical
contract is `oneiric/docs/RESOLUTION_LAYER_SPEC.md` (`status: active`,
`role: canonical`). Both plans name oneiric source files, oneiric test files,
and oneiric's plan-index tooling, so they belong in the repository that owns
the code. Moving them into mahavishnu would put an implementation plan in a
repo that does not own the code it changes.

## Picking them up

1. Read `oneiric/docs/RESOLUTION_LAYER_SPEC.md` first — it is the canonical
   contract, and Plan A amends it.
2. Work in a worktree at `~/.local/state/mahavishnu/worktrees/oneiric/`
   (per the user-level worktree convention). Not inside the oneiric repository.
3. The two plans are independent; neither blocks the other. Plan B Task 2
   touches `oneiric/core/resolution.py` temporarily and reverts it in the
   same step.
4. Use `superpowers:subagent-driven-development` (recommended) or
   `superpowers:executing-plans`. Each plan's Parking section records the
   same guidance.

## Integration Contract

- **Triggered from**: Any session that needs to change resolver precedence,
  resolver explainability, resolver documentation, or resolver scope.
- **Returns to / updates**: Nothing in mahavishnu. Implementation happens in
  the oneiric repository and lands in oneiric's plan store.
- **Demonstrable by**: `grep -n "resolver" ~/Projects/oneiric/docs/plans/PLAN_INDEX.md`
  lists both plans with status `active`.
- **Rollback signal**: This pointer becomes stale — either plan is
  implemented, superseded, or moved out of oneiric's plan store. Update the
  table above and set `superseded_by` or the status accordingly.
- **Observability added**: None. This file exists so the parked plans are
  reachable from the session's primary repository's plan index.

## Related

- Oneiric canonical spec: `~/Projects/oneiric/docs/RESOLUTION_LAYER_SPEC.md`
- Oneiric decisions: `~/Projects/oneiric/docs/decisions/0004-resolver-scope-deferrals.md`
  (created by Plan B Task 1)
- Memory: `resolve-components-skill-is-fictional` — the fictional-skill finding,
  dual-stored in Session-Buddy as a `reference` reflection.
