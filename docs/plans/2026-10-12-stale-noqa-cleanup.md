---
status: active
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
# Hard dep: this plan needs RUF100 to be an active rule, which is
# enabled by `2026-10-12-ruff-cleanup-post-regrowth.md` Phase 0
# (the rule-family enablement in `pyproject.toml extend-select`).
# Without that, `ruff check --select RUF100` returns 0 findings on
# `main` and the `--fix` has nothing to do.
blocks_on:
  - docs/plans/2026-10-12-ruff-cleanup-post-regrowth.md
topic: stale-noqa-cleanup
title: "Stale `# noqa` Marker Cleanup (RUF100, 2026-10-12)"

---

# Stale `# noqa` Marker Cleanup (RUF100, 2026-10-12)

> **For agentic workers:** Mechanical cleanup. One phase, one
> command, one PR. Do not edit the source unless the autofix produces
> an output that the user has approved.

## Why this plan exists

RUF100 ("unused-noqa") went from **239 markers (2026-07-29)** to
**305 markers (2026-10-13, re-measured)** because new code added
`# noqa` markers that have since become stale — the rule violation
they suppressed was either fixed upstream or never applied to that
line. The original 2026-10-12 snapshot claimed 912; the 2026-10-13
re-measurement via `cd /Users/les/Projects && /Users/les/Projects/mahavishnu/.venv/bin/ruff check ... --select RUF100 --statistics`
shows 305 (the 912 figure was an estimate that overcounted by 3x,
likely because the snapshot was taken before recent merges like
`OneiricSettings.substrate` adoption that reduced the marker count).
The `2026-10-12-ruff-cleanup-post-regrowth.md` plan covers the 8
active rules but explicitly defers RUF100 to this companion plan:
RUF100 is mechanical (one `--fix` pass deletes the stale markers) but
its blast radius (305 lines across the 6 packages) is large enough
to deserve a separate commit and review surface.

The companion plan's separation also ensures that, if `ruff
check --fix --select RUF100` produces any unexpected output, the
post-regrowth work can still merge cleanly while we triage the RUF100
diff.

## Goal

1. Reduce RUF100 findings from **305 → 0** with `ruff check
   --select RUF100 --fix`.
2. Verify Crackerjack gate stays green.

## Non-Goals

- The 8 in-scope rules (BLE001, RUF012, S110, DTZ001, PLW1510,
  ASYNC221, ASYNC230, PYI036, DTZ005) — those are in
  `docs/plans/2026-10-12-ruff-cleanup-post-regrowth.md`.
- Hand-curating `# noqa: <rule> <justification>` rewrites — that
  happens inside Phase 6 of the post-regrowth plan where `# noqa`
  markers are load-bearing (boundary handlers, returncode inspection).
  RUF100 deletes stale *unused* markers; the load-bearing ones stay.
- Migrating the surviving `# noqa` markers to inline per-file ignores
  in `pyproject.toml` (`[tool.ruff.lint.per-file-ignores]`) — deferred
  to a future plan.

## Current Findings

```bash
ruff check mahavishnu/ oneiric/ session-buddy/ akosha/ crackerjack/ mcp-common/ \
  --select RUF100 --statistics
# → 305 findings (2026-10-13 re-measurement), 6 packages, scattered across roughly 200 files
```

The markers are scattered evenly — no single file has more than ~40
entries, so the diff is wide but shallow. A single `--fix` pass will
delete each marker only if ruff itself can prove the rule no longer
fires on that line. If any marker must survive for the reasons in the
[post-regrowth plan Phase 1 boundary-handler convention](../plans/2026-10-12-ruff-cleanup-post-regrowth.md#phase-1--ble001-11-narrow-bare-except-exception),
that marker carries a `<justification>` suffix, which we don't expect
RUF100 to flag (RUF100 only flags markers whose rule is no longer
firing).

## Sequencing with companion plans

**Prerequisite (hard dep):** `2026-10-12-ruff-cleanup-post-regrowth.md` Phase 0
must land first. That phase enables the RUF family (and the 8 in-scope
rule codes) in `pyproject.toml [tool.ruff.lint] extend-select`.
Without that, RUF100 is not being checked on `main` and the `--fix`
has nothing to delete — the reported "912 markers" baseline is
aspirational. The post-Phase-0 actual baseline (run
`ruff check ... --select RUF100 --statistics`) is what this plan works
against. Update the "Current Findings" baseline in this plan with the
post-Phase-0 actual count before running the fix.

The recommended execution order is:

1. `2026-10-12-ruff-cleanup-post-regrowth.md` **Phase 0** (rule enablement)
   lands first. The 912 RUF100 count gets re-measured.
2. `2026-10-12-ruff-cleanup-post-regrowth.md` **Phase 1 (BLE001)** lands
   next. This adds justified `# noqa: BLE001 <reason>` markers on
   boundary handlers that the BLE001 narrowing wants to keep.
3. `2026-10-12-ruff-cleanup-post-regrowth.md` **Phases 2-8** land in
   any order. None of them depend on RUF100.
4. **This plan (RUF100)** lands last. RUF100 only deletes markers whose
   rule is no longer firing. The just-added justified BLE001 markers
   survive because the rule IS firing on them.

If RUF100 lands before Phase 1, the existing unjustified BLE001
markers get deleted (they're stale). Phase 1 then re-adds justified
markers for the new boundary handlers, and a follow-up RUF100 sweep
leaves them alone. Either order converges to the same end state; the
recommended order minimizes the chance of two-PR churn on the same
lines.

## Ruff version pin

`ruff check --fix --select RUF100` is stable across the active
`ruff>=0.16.0` pin (per `pyproject.toml:124`). Local re-runs that
drift across minor versions may see whitespace-handling changes in
`--fix` output. The verification rejects any PR with unrelated
whitespace churn (`git diff --stat` should show deletions-only on the
RUF100 commit).

## Implementation Phases

### Phase 1 — Mechanical `--fix` and review

**Tasks:**

- Run:

  ```bash
  ruff check mahavishnu/ oneiric/ session-buddy/ akosha/ crackerjack/ mcp-common/ \
    --select RUF100 --fix
  ```

- Verify the diff is deletion-only (`git diff --stat` should show
  *only removed lines*; any reformatting or unrelated change is a bug
  in our invocation and must be reverted before committing).
- Run `pytest -m "not slow"` — RUF100 is purely a marker-cleanup, but
  a stale marker might be the *only* line guarding a true violation
  that just got re-introduced (e.g. a refactor restored a `BLE001`
  violation that the still-needed `# noqa: BLE001 <reason>` was
  hiding). If any test fails, re-investigate the marker — do not
  delete it.
- Run `crackerjack run -v` for the gate confirmation.

**Exit criteria:**

- `ruff check ... --select RUF100` returns 0 findings.
- `git diff --stat` shows `X files changed, Y insertions(+), Y
  deletions(-)` with insertions only from trailing-newline bookkeeping
  (the `write-tool-trailing-newline` memory note acknowledges Write/Edit
  can drop trailing newlines; verify with `git diff | grep -c '^+'`).
- `pytest -m "not slow"` green.
- `crackerjack run -v` green.

#### Integration Contract
- **Triggered from**: developer (or `crackerjack` MCP tool) running
  `ruff check ... --select RUF100 --fix`.
- **Returns to / updates**: no state change beyond marker deletion;
  ruff-gate now reads 0 findings for RUF100.
- **Demonstrable by**: the gate command above exits 0; `git show
  --stat HEAD` shows ~912 deletions and 0 substantive insertions.
- **Rollback signal**: `git revert <phase-1-commit>` — single commit,
  re-introduces all 912 markers.
- **Observability added**: none.

## Cross-cutting Acceptance

```bash
ruff check mahavishnu/ oneiric/ session-buddy/ akosha/ crackerjack/ mcp-common/ \
  --select RUF100
```

Must return 0 findings. Combined with the post-regrowth plan, the
ruff-gate becomes cleaner than the 2026-07-29 baseline (the wave-plan
had not yet begun the post-regrowth-driven improvements).

## Validation Matrix

| Command | Expected | Evidence |
|---------|----------|----------|
| `ruff --version` | `ruff 0.6.0` (the pinned version; per `requirements/lint-constraints.txt`) | shell |
| `ruff check … --select RUF100` (read-only, before fix) | 305 findings (2026-10-13 baseline) | shell |
| `ruff check … --select RUF100 --fix` | runs to completion, no errors | shell |
| `ruff check … --select RUF100` (after fix) | 0 findings | CI log |
| `git diff --stat` of the PR | deletions-only (or near-only — whitespace churn from `--fix` is accepted) | PR description |
| `pytest -m "not slow"` | green | CI log |
| `crackerjack run -v` | gate green | CI log |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| A `# noqa` marker is load-bearing but the violation has been re-introduced by upstream refactor | Low | `pytest -m "not slow"` is the canary; a fresh violation surfaces as a test failure |
| `--fix` does more than delete markers (e.g. rewrites imports) | Low | `git diff --stat` review before commit; if it happens, abort and bisect which rule fired |
| Trailing-newline churn confuses the reviewer (`write-tool-trailing-newline` memory) | Med | Verify deletions-only; reject unrelated edits |

## References

- `docs/plans/2026-10-12-ruff-cleanup-post-regrowth.md` — primary
  companion; covers the 8 *active* rules.
- `docs/plans/2026-07-29-ruff-cleanup-waves.md` — predecessor; will
  move to `docs/plans/.archive/` once both follow-up plans land.
- `CLAUDE.md` § Missing built-in tools in MiniMax-modeled sessions —
  the `Write/Edit often drops trailing newline` rule from
  `feedback-write-tool-trailing-newline.md` is why Phase 1 verifies
  deletions-only via `git diff`.
