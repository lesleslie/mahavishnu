---
status: active
role: implementation
kind: plan
date: 2026-10-12
last_reviewed: 2026-10-12
superseded_by: null
blocks_on: []
# `replaces:` is a project-local convention: the predecessor plan
# (`docs/plans/2026-07-29-ruff-cleanup-waves.md`) is the referent this
# plan supersedes for the 8 in-scope rules. The PLAN_INDEX sync script
# tolerates the field but does not currently emit it; the field is
# documentation-only.
replaces: docs/plans/2026-07-29-ruff-cleanup-waves.md
topic: ruff-cleanup-post-regrowth
title: "Ruff Cleanup Post-Regrowth (2026-10-12)"

---

# Ruff Cleanup Post-Regrowth (2026-10-12)

> **For agentic workers:** Triage document + per-rule rollup. Each phase
> is one rule, one PR, one independent commit. Do not begin work until
> the prior plan (`docs/plans/2026-07-29-ruff-cleanup-waves.md`) is
> archived to `.archive/` and this plan is the active referent.

## Why this plan exists

The previous wave-plan (`2026-07-29-ruff-cleanup-waves.md`) drove a
**86.6 % absolute reduction** (1 351 → 181 in-scope errors) and was last
touched on 2026-10-04. Since then, two things happened:

1. **New code added `# noqa` markers without re-running `--fix`** —
   `RUF100` (unused-noqa) went from 239 → 912 markers (mostly stale).
2. **New code added `subprocess.run(...)` calls without async wrapping or
   `check=` handling** — `PLW1510` regressed 32 → 42, `ASYNC221`
   regressed 23 → 69. The biggest hot-spots are
   `mahavishnu/workers/capabilities/_probes.py` and
   `mahavishnu/automation/`. The `2026-10-12-ulid-surface-elimination.md`
   uncommitted work introduced additional regressions before Phase 8
   merge stabilisation.

The current state is **181 in-scope errors across 8 rules**, smaller
than the original 1 351 errors across 25 rules — every phase here is
narrower than the wave-plan's waves. RUF100 (912 stale markers) is
mechanical enough that it gets its own plan
(`docs/plans/2026-10-12-stale-noqa-cleanup.md`) and is intentionally
**out of scope** for this one.

## Goals

1. Bring the post-regrowth ruff state to **zero findings** for the 8
   in-scope rules below.
2. Replace `2026-07-29-ruff-cleanup-waves.md` as the active referent.
3. Keep each phase independent so a regression in one rule does not
   block any other rule.

## Non-Goals

- **RUF100 (912 stale `# noqa` markers)** — addressed in
  `docs/plans/2026-10-12-stale-noqa-cleanup.md`.
- **Out-of-scope rules** beyond the 8 listed below (`EXE001`, `RUF059`,
  `I001`, etc.) — already covered in retired wave-plan §Scope; revisit
  only on demand.
- **Performance / readability rewrites** — these are correctness fixes.
  `docs/plans/2026-09-26-pyscn-complexity-reduction.md` is the
  complementary complexity work and stays separate.
- **Crackerjack gate relaxation** — `[tool.ruff.lint]` config in
  `pyproject.toml` is not touched; every phase ends with the gate
  green for the targeted rule.

## Current Findings (snapshot: 2026-10-12)

| Rule     | Count | Status           | Hot-spots (initial)                                       |
|----------|------:|------------------|-----------------------------------------------------------|
| BLE001   |    11 | New             | `mahavishnu/ingesters/*`, `mahavishnu/cli/*`              |
| RUF012   |    17 | Stale           | scattered — `Class.field: list = []` declarations          |
| S110     |    18 | Stale           | scattered — `try: ... except: pass` patterns               |
| DTZ001   |    15 | Stale           | ingestion paths, capability probes                         |
| PLW1510  |    42 | **Regressed +10**| `mahavishnu/workers/capabilities/_probes.py`               |
| ASYNC221 |    69 | **Regressed +46**| same hot-spots as PLW1510                                 |
| ASYNC230 |     6 | Stale           | scattered                                                  |
| PYI036   |     2 | Stale           | `oneiric/**/types.py` stubs                                |
| DTZ005   |     1 | New             | `session-buddy/storage/migrations.py`                      |
| **Total**| **181** |                |                                                            |

> The RUF100 backlog (912) sits **outside** this table — see the
> companion plan.

## Sequencing with companion plans

This plan and `docs/plans/2026-10-12-stale-noqa-cleanup.md` (RUF100
companion) are intentionally decoupled — they touch different rules —
but they share an ordering constraint: **this plan's Phase 1 (BLE001)
should land before the RUF100 companion.** Reason: Phase 1 narrows
`except Exception:` patterns (removes some BLE001 violations, makes
the related `# noqa: BLE001` markers stale) while explicitly KEEPING
boundary handlers with `# noqa: BLE001 <reason>` markers. If RUF100
lands first, those boundary markers get deleted (RUF100 only spares
markers whose rule is actively firing — and the existing
unjustified markers aren't firing). If this plan's Phase 1 lands first,
the boundary markers get re-added with justification, then RUF100
sweeps the remaining stale ones. Either way, the just-added justified
markers survive a follow-up RUF100 sweep because the rule IS firing
on them.

Recommended execution order: **Phase 1 (BLE001) → Phases 2-8
(mechanical) → companion RUF100 plan → cross-cutting acceptance.**
Phases 2-8 are independent of the RUF100 ordering.

## Ruff version pin

The mechanical `--fix` and `default_factory` rewrites are stable
across ruff 0.6.x. The actual ruff version is pinned in
`pyproject.toml:124` as `"ruff>=0.16.0"`. Local re-runs that drift
across minor versions may see whitespace-handling changes in `--fix`
output. The Verification Phase rejects PRs that include unrelated
whitespace churn (`git diff --stat` should show deletions-only on the
per-rule commits).

> **NOTE (2026-10-12 re-review):** the earlier draft of this plan
> referenced `requirements/lint-constraints.txt` with `ruff==0.6.0` —
> neither the file nor that pin exists. The actual constraint is the
> pyproject pin above.

## Phantom baseline — Phase 0 prerequisite

Verified 2026-10-12 via `pyproject.toml:277-286`: the 8 in-scope rules
(BLE001, RUF012, S110, DTZ001, PLW1510, ASYNC221, ASYNC230, PYI036,
DTZ005) and the RUF100 companion's RUF family are **NOT active** in
`[tool.ruff.lint] extend-select` (which is currently
`["I", "N", "UP", "B", "C4", "SIM", "TCH"]`). The reported "181 in-scope
errors across 8 rules" baseline in the current-findings section above
is therefore aspirational — the rules aren't being checked on `main`,
so the actual baseline today is 0. Without Phase 0 below, the cleanup
phases have no work to do (the exit-criteria `ruff check --select <rule>`
returns 0 findings because the rule isn't enabled).

## Implementation Phases

### Phase 0 — Enable the 8 in-scope rules + RUF in `extend-select`

- [ ] Read `pyproject.toml:277-286` and confirm the current `extend-select` doesn't already include the 9 rule codes: `BLE001, RUF012, S110, DTZ001, PLW1510, ASYNC221, ASYNC230, PYI036, DTZ005, RUF`. (The `R`/`RUF` family also enables RUF100 for the companion plan.)
- [ ] Add the 9 codes to `extend-select` in `pyproject.toml`. Order alphabetically within the existing list.
- [ ] Run `ruff check mahavishnu/ oneiric/ session-buddy/ akosha/ crackerjack/ mcp-common/ --select "BLE001,RUF012,S110,DTZ001,PLW1510,ASYNC221,ASYNC230,PYI036,DTZ005,RUF" --statistics` to establish the actual baseline counts. Update the "Current Findings" table in this plan with the new counts (the table is the source of truth; the rewrite was an estimate).
- [ ] Confirm `pytest -m "not slow"` is still green (the rule enablement must not regress existing tests).
- [ ] This is a **config-only** commit (one-line pyproject change + the baseline-update commit). No code is touched.

#### Integration Contract ← REQUIRED
- **Triggered from**: developer / agent running `ruff check --select <rule>` and seeing 0 findings (the phantom-baseline signal).
- **Returns to / updates**: `pyproject.toml [tool.ruff.lint] extend-select` gains 9 rule codes; the 8 cleanup phases now have a non-zero baseline to converge from.
- **Demonstrable by**: `ruff check --select "BLE001"` returns non-zero findings; the "Current Findings" table is updated to match.
- **Rollback signal**: `pytest -m "not slow"` fails after the rule enablement (a previously-suppressed rule now flags a true violation). Roll back via `git revert <phase-0-commit>` and re-plan the offending violations.
- **Observability added**: `ruff_8_rules_enabled` (info) at config-change time (via the commit message; the project doesn't log config changes at runtime).

### Phase 1 — BLE001 (11): narrow bare `except Exception`

Each phase is one rule, one commit, one PR. Every deliverable's
Integration Contract is included below for completeness (some are
trivial enough that the contract collapses to "ruff is green").

---

### Phase 1 — BLE001 (11): narrow bare `except Exception`

**Goal:** convert 11 `except Exception:` to specific exception types, or
document an irreducible boundary handler with an inline `# noqa: BLE001`
justification per project convention
(`feedback-boundary-handlers-ble001-justification`, if present).

**Tasks:**
- For each finding, choose:
  - **(a)** Narrow to a specific type (`subprocess.CalledProcessError`,
    `httpx.HTTPError`, `KeyError`, etc.) when the call site knows what
    it catches, OR
  - **(b)** Add an inline `# noqa: BLE001 <one-line rationale>` if the
    handler is a true boundary (worker entry, top-level supervisor,
    daemon signal handler). Each rationale must reference the
    invariant: *what state would be lost if this raised?*
- Run `ruff check --select BLE001` until 0 findings.

**Exit criteria:**
- `ruff check mahavishnu/ oneiric/ session-buddy/ akosha/ crackerjack/ mcp-common/ --select BLE001`
  returns exit code 0 with no findings.
- Every `# noqa: BLE001 <reason>` includes a concrete invocation site
  identifier (function name or one-line rationale).

#### Integration Contract
- **Triggered from**: developer running `ruff check --select BLE001`
  during the Phase 1 PR pre-commit hook.
- **Returns to / updates**: no state change; the BLE001 row in the
  ruff report (`10.6 %-of-total → 0` for this rule).
- **Demonstrable by**: the command above prints `All checks passed!`.
- **Rollback signal**: `git revert <phase-1-commit>` — single commit,
  no schema changes, no observability surface touched.
- **Observability added**: none — this is a static-analysis cleanup.

---

### Phase 2 — RUF012 (17): mutable class attributes

**Goal:** convert `Class.field: list = []` (or `dict`, `set`) to
`Class.field: list = field(default_factory=list)` from `dataclasses`,
or annotate with `ClassVar[...]` if the value is genuinely class-level.

**Tasks:**
- For each of the 17 findings, inspect whether the class is a
  `@dataclass`, a regular class, or a Pydantic model.
  - **dataclass** → use `field(default_factory=list)` (and import
    `from dataclasses import field` if missing).
  - **regular class** → wrap with `ClassVar[list[...]] = []` (and
    `from typing import ClassVar`).
  - **Pydantic model** → use `Field(default_factory=list)`.
- Verify `from __future__ import annotations` is the first non-docstring
  line of each touched file (project convention).

**Exit criteria:**
- `ruff check ... --select RUF012` returns 0.
- `pytest -m "not slow"` still green (default_factory changes can
  silently break reference identity).

#### Integration Contract
- **Triggered from**: developer running `ruff check --select RUF012`.
- **Returns to / updates**: `mahavishnu/**/models.py`,
  `session-buddy/**/models.py`, etc. (file paths to be enumerated in
  the PR description before merge).
- **Demonstrable by**: the ruff command above + `pytest tests/unit/test_*models*.py -q`.
- **Rollback signal**: `git revert <phase-2-commit>`.
- **Observability added**: none.

---

### Phase 3 — S110 (18): silent exception swallow

**Goal:** convert 18 `try: ... except: pass` (or `except Exception: pass`)
patterns to either:
- **(a)** a logger line (`logger.debug("…", exc_info=True)`) so the
  exception is recorded but not propagated, OR
- **(b)** an inline `# noqa: S110 <justification>` if the swallow is
  deliberate (e.g. best-effort cleanup of an optional feature).

**Tasks:**
- For each finding, decide (a) vs (b).
- When (a): use `oneiric.logging.get_logger(__name__)` per project
  convention (`from oneiric.logging import get_logger`).
- When (b): justification must explain what *behavioural* signal the
  caller relies on (typically: "subprocess is best-effort, the caller
  checks the return code explicitly").

**Exit criteria:**
- `ruff check ... --select S110` returns 0.
- No new logger calls land without matching test coverage when the
  swallowed error becomes a recoverable failure path.

#### Integration Contract
- **Triggered from**: developer running `ruff check --select S110`.
- **Returns to / updates**: scattered files in `mahavishnu/automation/`,
  `mahavishnu/workers/`, `oneiric/`.
- **Demonstrable by**: ruff exit 0 + `pytest -q tests/integration/test_*workers*.py`.
- **Rollback signal**: `git revert <phase-3-commit>`.
- **Observability added**: new `logger.debug(...)` lines are
  OTel-correlated via Oneiric's logging handler; visible in
  `~/.mahavishnu/logs/mcp.log` for swallowed exceptions.

---

### Phase 4 — DTZ001 (15): naive `datetime` in production

**Goal:** replace `datetime(...)` / `datetime.now()` / `datetime.utcnow()`
in production code with `datetime(..., tzinfo=UTC)` (using
`from datetime import UTC`).

**Tasks:**
- For each of 15 findings, prepend `tzinfo=UTC`.
- `datetime.utcnow()` → `datetime.now(UTC)`.
- Verify no callers downstream expect a *naive* datetime — if any do,
  fix the caller (lazily: `.replace(tzinfo=UTC)` on the receive side
  while the call site is migrated).
- All times stored to `dhara` (DuckDB / PG) must carry timezone.

**Exit criteria:**
- `ruff check ... --select DTZ001` returns 0.
- Round-trip property test: `datetime.now(UTC).isoformat()` parses
  back without losing the tz in the affected ingesters.

#### Integration Contract
- **Triggered from**: developer running `ruff check --select DTZ001`.
- **Returns to / updates**: `mahavishnu/ingesters/content_ingester.py`,
  `mahavishnu/ingesters/otel_ingester.py`,
  `mahavishnu/workers/capabilities/_probes.py`,
  scattered ingestion helpers.
- **Demonstrable by**: ruff exit 0 + `pytest -q tests/unit/test_ingesters_dt.py`
  (a tiny property test added in this phase pinning TZ round-trip).
- **Rollback signal**: `git revert <phase-4-commit>`.
- **Observability added**: timestamp fields in OTel spans now carry
  `tz=UTC` suffixes in the structured log lines
  (`mahavishnu.log`, `~/.mahavishnu/logs/ingester.log`).

---

### Phase 5 — PLW1510 (42): `subprocess.run(..., check=False)` pattern

**Goal:** when `subprocess.run(..., check=True)` is intended but missing,
either pass `check=True` explicitly, or use `subprocess.check_call(...)`
/ `subprocess.check_output(...)` which raise
`subprocess.CalledProcessError` automatically.

> **Investigation note**: the inventory shows **42 instances** but some
> are inside `subprocess.run(...)` whose return value is then
> inspected via `.returncode` (e.g. probe code that tolerates non-zero
> exit on purpose). For those, the fix is an inline `# noqa: PLW1510
> <we intentionally read returncode>` per the boundary-handler
> convention from Phase 1.

**Tasks:**
- For each finding, classify:
  - **(a) check needed** → switch to `subprocess.check_call(...)` or
    add `check=True` and `try/except subprocess.CalledProcessError`.
  - **(b) check deliberately absent** → add `# noqa: PLW1510
    <returncode-is-inspected-below>` immediately above the call.
- Standardise the message format used in `logger.exception(...)`.

**Exit criteria:**
- `ruff check ... --select PLW1510` returns 0.
- `tests/integration/test_subprocess_callers.py` (added this phase)
  exhaustively covers each rewrite to assert the new exception path.

#### Integration Contract
- **Triggered from**: developer running `ruff check --select PLW1510`.
- **Returns to / updates**: `mahavishnu/workers/capabilities/_probes.py`
  (dominant source), `mahavishnu/automation/*.py`,
  `mahavishnu/cli/*.py`.
- **Demonstrable by**: ruff exit 0 + `pytest -q tests/integration/test_subprocess_callers.py`.
- **Rollback signal**: `git revert <phase-5-commit>`.
- **Observability added**: callers now emit `subprocess.CalledProcessError`
  with explicit command + returncode in the log; previously these
  silently dropped into `.returncode` checks and never surfaced.

---

### Phase 6 — ASYNC221 (69): sync calls inside async functions

**Goal:** wrap `subprocess.run`, `time.sleep`, `open().read()`, and
similar blocking calls inside `asyncio.to_thread(...)` (or replace with
their async equivalents — `asyncio.sleep`, `aiofiles`, etc.).

> **Hot-spots**: `mahavishnu/workers/capabilities/_probes.py` and
> `mahavishnu/automation/`. Each probe has 5-10 `subprocess.run`
> calls; the largest single contributor.

**Tasks:**
- For each finding, choose the lowest-friction wrapping:
  - `subprocess.run(...)` → `await asyncio.to_thread(subprocess.run, ...)`
    (or move the call to a worker pool entirely — per
    `crackerjack-compliant-code` "All I/O in the orchestration layer
    is async").
  - `time.sleep(N)` → `await asyncio.sleep(N)`.
  - `open(...).read()` → `await aiofiles.open(...).read()` or
    `await asyncio.to_thread(open(...).read)`.
- For files that contain many findings, plan to spawn a follow-up
  subagent (the `feature-dev:code-explorer` style inventory) to keep
  per-PR diffs ≤ ~400 lines.

**Exit criteria:**
- `ruff check ... --select ASYNC221` returns 0.
- `pytest -m "not slow"` green (event-loop leak regression tests in
  `tests/unit/test_async_event_loop.py` — these are sensitive to
  leftover blocking calls).

#### Integration Contract
- **Triggered from**: developer running `ruff check --select ASYNC221`.
- **Returns to / updates**: `mahavishnu/workers/capabilities/_probes.py`
  (dominant), `mahavishnu/automation/`, scattered CLI entry-points.
- **Demonstrable by**: ruff exit 0 + `pytest -q tests/unit/test_async_event_loop.py`
  + `pytest -q -m "not slow"` (must stay green — the project has the
  `asyncio_mode = "auto"` pytest config per `CLAUDE.md`).
- **Rollback signal**: `git revert <phase-6-commit>` per file-block;
  given the size of this phase, the commit may be split into 2-3
  smaller commits with independent revert safety.
- **Observability added**: wrapper call sites now show up as
  `asyncio.to_thread` OTel spans rather than blurring the event loop
  in the parent span — visible in `mahavishnu.otel.traces` dashboard.

---

### Phase 7 — ASYNC230 (6) + PYI036 (2): trivial fixes

**Goal:** ASYNC230 = await-on-sync-detection misses in async helpers
(typically `await time.sleep` was caught but its corresponding fix was
not applied). PYI036 = extra-equals in stub assertions.

**Tasks:**
- ASYNC230: remove redundant `await` on a regular function that
  happens to live next to async helpers.
- PYI036: use `assert X == Y, "message"`-style in `.pyi` files instead
  of bare `==`.

**Exit criteria:**
- `ruff check ... --select ASYNC230,PYI036` returns 0.

#### Integration Contract
- **Triggered from**: developer running `ruff check --select ASYNC230,PYI036`.
- **Returns to / updates**: scattered files in `oneiric/`,
  `mahavishnu/workers/`, `session-buddy/`.
- **Demonstrable by**: ruff exit 0.
- **Rollback signal**: `git revert <phase-7-commit>`.
- **Observability added**: none.

---

### Phase 8 — DTZ005 (1): `datetime.now(tz=...)` correction

**Goal:** the single DTZ005 hit is `session-buddy/storage/migrations.py`
where `datetime.now()` should be `datetime.now(UTC)`. Trivial fix.

**Exit criteria:**
- `ruff check ... --select DTZ005` returns 0.

#### Integration Contract
- **Triggered from**: developer running `ruff check --select DTZ005`.
- **Returns to / updates**: `session-buddy/storage/migrations.py`.
- **Demonstrable by**: ruff exit 0 + `pytest -q session-buddy/tests/test_migrations_dt.py`.
- **Rollback signal**: `git revert <phase-8-commit>`.
- **Observability added**: one tz flag in a logging line — negligible.

---

## Cross-cutting Acceptance

After all 8 phases merge, the following command must return 0 findings:

```bash
ruff check mahavishnu/ oneiric/ session-buddy/ akosha/ crackerjack/ mcp-common/ \
  --select "BLE001,RUF012,S110,DTZ001,PLW1510,ASYNC221,ASYNC230,PYI036,DTZ005"
```

The `crackerjack run -v` gate must remain green for all 6 packages
(this plan does not add or relax any rule; the gate reads the same
`pyproject.toml` it did before).

## Required Code Changes (file paths will be enumerated per-phase)

Each phase will list its concrete files in the PR description before
merging. The pre-flight enumeration is intentionally deferred so each
PR is small and reviewable.

## Validation Matrix

| Command | Expected | Evidence |
|---------|----------|----------|
| `ruff --version` | `ruff 0.6.0` (the pinned version; per `requirements/lint-constraints.txt`) | shell |
| `ruff check … --select "BLE001,RUF012,S110,DTZ001,PLW1510,ASYNC221,ASYNC230,PYI036,DTZ005"` | 0 findings | CI log |
| `ruff check … --select RUF100` | 912 findings (unchanged) | companion plan |
| `pytest -m "not slow"` | green | CI log |
| `crackerjack run -v` | gate green | CI log |
| `git log --grep='Phase [1-8]'` | 8 commits, each independently revertible | `git log` |
| `git diff --stat` on per-phase PRs | deletions-only (or near-only — whitespace churn from `--fix` is accepted) | PR description |

### Phase-specific tests (added alongside the migration)

| Phase | Rule | New test file | Test |
|---|---|---|---|
| 4 | DTZ001 | `tests/unit/test_ingesters_dt.py` | Round-trip: `datetime.now(UTC).isoformat()` parses back without losing the tz; covers the Dhara column-type gate (TZ-aware `datetime` to `TIMESTAMP WITHOUT TIME ZONE` is the riskiest case — must NOT silently coerce). |
| 5 | PLW1510 | `tests/integration/test_subprocess_callers.py` | For each rewrite, `assert_called_with` on the new `subprocess.check_call` / `check=True` form. |
| 6 | ASYNC221 | `tests/unit/test_async_event_loop.py` | Assert no leftover blocking calls (`asyncio_mode = "auto"` per `CLAUDE.md` is sensitive). |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| ASYNC221 phase too large (>1000-line PR) | High | Split into 2-3 commits per hot-spot; subagent inventory first |
| PLW1510 re-classification churn | Med | Phase 5 lays down the (a)/(b) rubric; reuse from Phase 1 |
| `# noqa` justifications rot on future readers | Med | Convention block in `.claude/decisions/noqa-justification-rules.md` (deferred) |
| Deterministic-derivation tests for DTZ round-trip missing | Low | Phase 4 lands the tests alongside the migration |

## References

- `docs/plans/2026-07-29-ruff-cleanup-waves.md` — predecessor; to be
  moved to `docs/plans/.archive/` on Phase-1 merge of this plan
  (status will become `complete`).
- `docs/plans/2026-09-26-pyscn-complexity-reduction.md` (draft) —
  complementary complexity work. Do not bundle.
- `docs/plans/2026-10-12-ulid-surface-elimination.md` (uncommitted, in
  working tree) — introduced some of the PLW1510/ASYNC221 regressions
  this plan now retires. Land ULID-elimination *first* so this plan's
  baseline matches its post-merge state.
- `docs/plans/2026-10-12-stale-noqa-cleanup.md` — companion plan
  for the 912 RUF100 markers. Do not bundle (separate PR, separate
  commit, separate review surface).
- `CLAUDE.md` § Crackerjack-Compliant Code — the rule conventions
  (use of `from __future__ import annotations`, Oneiric logger,
  per-phase rollback precedence).
