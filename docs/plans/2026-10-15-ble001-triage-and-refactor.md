---
status: active
role: canonical
kind: plan
date: 2026-10-15
last_reviewed: 2026-10-15
superseded_by: null
topic: lint-coverage-gap
title: "BLE001 Triage and Per-Site Refactor — close the coverage gap behind the durable defense"
---

# BLE001 Triage and Per-Site Refactor

> **Why this plan exists**: the BLE001 cycle was structurally closed (RUF100
> defense on all 753 `# noqa: BLE001, RUF100` directives — commits
> `41e43ff4`, `a82acf48`, `6edbb75f`, `df418f54` on local main; pushed to
> `origin/main` in the prior session), but the underlying pattern
> (`except Exception:`) is still in 753 sites. Those sites are *covered*
> with noqas, not *addressed*. The crackerjack gate passes, but BLE001's
> design intent — "broad-catch hides bugs; narrow it or use the project's
> error hierarchy" — is not met. This plan does the actual triage and
> refactor that the gate defense defers.
>
> **Scope of this plan**: only the 753 BLE001 noqas + adjacent gate-blockers
> the user surfaced in the 2026-10-15 session. The general "audit
> lifecycle" is owned by the `feature-delivery-lifecycle` workflow; this
> plan does not change that.

## 1. Outcome

Each of the 753 `# noqa: BLE001, RUF100` markers is replaced with one of:

- **Refactored catch** — `except (SpecificError1, SpecificError2):` (or
  re-raise as a domain error from `mahavishnu/core/errors.py`).
- **Suppression as last resort** — `# noqa: BLE001, RUF100` with an
  inline rationale: a top-level CLI / MCP / background-task handler where
  any exception must be caught. Per-site justification must name the
  contract that makes broad catch correct (e.g., "top-level handler — any
  error must be caught and converted to a typed exit code").
- **Deleted line** — for cases where the assignment / call inside the
  `except` is dead code (see the `publisher.py` discovery below), the
  entire block is removed.

The gate is the demonstrable signal: after this plan, the only `# noqa:
BLE001` left in `mahavishnu/` is on lines whose justification is a
named contract. The post-refactor ruff count of `# noqa: BLE001` lines
in `mahavishnu/` is target ≤ 60 (current 753; the residual 60-or-fewer
is the legitimate top-level-handler subset). Test code follows the
project's existing `tests/**/*.py` per-file-ignore convention.

## 2. Goals

1. **Triage**: produce a single spreadsheet (or `docs/ble001-triage.md`)
   that classifies each of the 753 sites as **legitimate** (keep
   suppression with named contract) or **needs-refactor** (replace
   with a specific catch or re-raise).
2. **Per-site refactor**: convert every "needs-refactor" site to a
   specific catch (or remove the dead block). Net reduction in `# noqa:
   BLE001` count ≥ 80 % (target: 753 → ≤ 150; stretch: ≤ 60).
3. **Pattern tooling**: ship a `crackerjack` hook (or pyproject rule)
   that fails new BLE001 sites on `main` without a `TICKET-` prefix in
   the justification, so the count cannot regress.
4. **Adjacent gate cleanups**: fix the 3 remaining `tc-refs` violations
   in `docs/plans/2026-10-15-session-buddy-wrapper-cleanup.md` and
   `docs/README.md` that were deferred when the user said "we'll re-run
   cj ourselves and fix the issues in another session".

## 3. Non-Goals

- **The full lint cleanup** (F401 unused-imports, B019 lru_cache on
  methods, N811/N817 naming, PLW1510 subprocess-without-check, etc.).
  These are tracked in the per-file-ignore work for tests already;
  the follow-up is captured in `crackerjack-fast-hooks-ruff-autofix`
  memory. This plan does **not** bundle them — mixing the work blurs
  the BLE001 diff and makes the gate verification harder to read.
- **Refactoring BLE001-adjacent patterns** (`BLE001`-style broad
  `with contextlib.suppress(Exception):` calls, the equivalent
  `try: ... except: pass` swallower in `mahavishnu/automation/`). These
  are tracked in the follow-up plan
  `docs/plans/2026-10-15-broad-exception-shape-audit.md` (to be created
  if scope is confirmed).
- **Resurrecting the RUF100-only tool that introduced the original
  regression**. The defense is now structural; we do not need the
  one-shot apply script once triage is done.
- **Lowering the gate threshold**. The current `crackerjack` gate is
  the project's contract; we make the codebase pass it, not the other
  way around.

## 4. Current Findings

### 4.1 The structural defense is in place

Commits on `origin/main` (verified 2026-10-15 ~18:00 UTC):

- `41e43ff4` merge: BLE001 noqa sweep + spell check + broken link/tc-refs fixes
- `a82acf48` fix(lint): re-apply per-site `# noqa: BLE001` to regression sites
- `6edbb75f` docs(plans): flip 22 plan/spec/ADR frontmatter statuses (also carries the RUF100 defense across 237 files)
- `df418f54` docs(plans): resolve Cluster 3 conflict
- 3 more cluster-resolution commits pushed in the same batch

Empirical proof (2026-10-15 session): `ruff check --select RUF100
--fix --unsafe-fixes` (the crackerjack fast_hooks command that stripped
753 noqas in the prior run) now strips **0** lines.

### 4.2 The underlying pattern is unchanged

The 753 sites are *covered*, not *addressed*. Examples from
`crackerjack run -v` output of the original 168 violation
pre-defense run:

- `mahavishnu/_main_cli.py:401` — `except Exception as e:` in a CLI
  top-level handler. The catch is correct here; the noqa should stay
  with an explicit contract rationale.
- `mahavishnu/automation/backends/pyautogui.py:74` — broad catch in a
  desktop-automation backend. **Likely needs refactor** — the
  automation can enumerate the specific exceptions raised by the
  pyautogui primitives it calls.
- `mahavishnu/core/events/publisher.py:35` — comment said "code never
  reads it", but the next line (`logger = get_logger(__name__)`) **was**
  read by line 83 (`logger.exception(...)`). The original author
  confused `_capture_singleton` (truly dead) with `logger` (used).
  The fix was to keep the `logger` assignment; the noqa is correct.

### 4.3 A second failure mode: dead-code deletion

During the defense application, deleting an "unused" `logger =
get_logger` line in `mahavishnu/core/events/publisher.py` and
`mahavishnu/core/events/confidence_ceiling.py` introduced `F821
Undefined name 'logger'` regressions. The lesson: "comment says it's
unused" is not the same as "the symbol is unused" — the
`_capture_singleton` annotation about "code never reads it" referred
to a different line. Future triage must verify with `grep -n` or
`Read` before deleting.

### 4.4 The RUF100/extend-select cycle (one-time learning)

The auto-fix that stripped the BLE001 noqas in the prior session was
the crackerjack fast_hooks running `ruff check --fix --unsafe-fixes`.
With `--select RUF100`, RUF100 in isolation does not see rules in
`extend-select` (where BLE001 lives), so the noqa looked "unused" and
got stripped. The defense is to add `, RUF100` to every BLE001 noqa
so RUF100 sees itself in the directive list. This generalizes: any
`# noqa: X` where X is in `extend-select` (not `select`) is at risk
of the same cycle. The pattern to apply to other at-risk noqas (the
TRY004 / N811 / N817 sites added during the gate-blocker work) is
identical.

### 4.5 The still-broken tc-refs (deferred 2026-10-15)

The user explicitly said "we'll re-run cj ourselves and fix the issues
in another session" on 2026-10-15, deferring:

- `docs/plans/2026-10-15-session-buddy-wrapper-cleanup.md:42` — broken
  link to `../2026-10-04-session-buddy-lifespan-publisher-inline.md`
  (the file is at `docs/plans/.archive/2026-10-04-session-buddy-lifespan-publisher-inline.md`).
- `docs/plans/2026-10-15-session-buddy-wrapper-cleanup.md:43` — broken
  link to `../2026-10-02-bodai-task-system-v1.1.md` (the file is at
  `docs/plans/2026-10-02-bodai-task-system-v1.1.md`).
- `docs/README.md:58` — broken link to `./.archive/` (directory
  reference, not a file).

These are 3-of-3 in the `tc-refs` check; the fix is mechanical
(`]` → `text` for the first two,
and `./.archive/` → `./.archive/README.md` or remove for the third).

## 4.5 Requirements

- `REQ-LINT-001` — Every `# noqa: BLE001` marker in `mahavishnu/`
  has a justification that names the contract making broad catch
  correct (top-level CLI / MCP / background-task handler, with the
  specific name).
- `REQ-LINT-002` — No `# noqa: BLE001` line in `mahavishnu/` is a
  `logger = X; ... logger.something(...)` pattern with a real
  reference below it (the dead-code-deletion failure mode from §4.3).
- `REQ-LINT-003` — A new `crackerjack` hook (or pyproject rule) fails
  any new BLE001 site on `main` whose justification does not include
  a `TICKET-` prefix, preventing regression.
- `REQ-LINT-004` — The 3 deferred `tc-refs` violations in
  §4.5 are fixed; `crackerjack run -v` exits 0 on the full gate.

## 5. Phases

### Phase 1: Triage (estimated 2–3 days, 1 engineer)

**Deliverable**: `docs/ble001-triage.md` (or a sheet) listing every
one of the 753 sites with columns:

| File | Line | Triage | Contract name / Refactor | Notes |
|---|---|---|---|---|
| `mahavishnu/_main_cli.py` | 401 | Keep | `cli_top_level` | entry point: exit code 1 on error |

Categorization rules:

- **Keep** if the except is in a top-level CLI / MCP / background-task
  handler where the function is documented as "any error → exit /
  log / continue". The contract name must be one of:
  - `cli_top_level` — `_main_cli.py` top-level command handlers
  - `mcp_tool_handler` — `mcp/tools/*.py` MCP tool functions
  - `tui_handler` — `tui/*.py` TUI event handlers
  - `background_task` — workers/pools background loops
  - `health_probe` — health-check / metrics endpoints
- **Refactor** if the except is in a function whose purpose is
  specific (e.g., a `pyautogui` wrapper should enumerate the
  pyautogui-specific exceptions). The replacement must be one of:
  - `except (SpecificError1, SpecificError2):` (list the actual
    exception types the called API raises — verify with the
    underlying library's docs)
  - re-raise as a domain error from `mahavishnu/core/errors.py`:
    `except OSError as e: raise BackupFailed(...) from e`
  - propagate the exception (delete the try/except entirely)
- **Delete** if the body of the except is dead code (verified with
  `grep -n <var>` across the file).

**Integration Contract**:

- **Triggered from**: Manual — `python scripts/audit_orphans.py` to
  list the 753 sites; sort and triage.
- **Returns to / updates**: `docs/ble001-triage.md` (new file);
  `mahavishnu/core/errors.py` may need new exception subclasses
  (add to the `Error` hierarchy: see
  `docs/decisions/mahavishnu-tool-preference-policy.md` for the
  `no-bodai-prefix-in-config-names` rule).
- **Demonstrable by**: `wc -l docs/ble001-triage.md` ≥ 753; the file
  has columns matching the table above; no row is left as "TODO".
- **Rollback signal**: if `grep '# noqa: BLE001' mahavishnu/ -r |
  wc -l` exceeds 753 between Phase 1 and Phase 2, abort Phase 2 and
  re-derive the triage from `git log -p -- mahavishnu/`.
- **Observability added**: `python scripts/audit_orphans.py --kind
  noqa-BLE001` (extend the script) emits the 753-site list each
  nightly; a CI failure fires if the count is > the previous
  day's count (regression detector).
- **Fulfils**: `REQ-LINT-001`, `REQ-LINT-002`.

### Phase 2: Per-site refactor (estimated 2–4 weeks, 1 engineer, gated per PR)

**Deliverable**: a series of merge-ready branches (one per
file-cluster, ≤ 20 files per PR for reviewability) that:

- Replaces every "Refactor" site from Phase 1 with a specific catch
  or re-raise.
- Adds the contract-name inline rationale to every "Keep" site:
  `# noqa: BLE001, RUF100  # cli_top_level: entry point, any error → exit 1`
- Deletes every "Delete" site entirely.

The work is broken into per-cluster PRs to keep the diff reviewable:

| Cluster | Files | Estimated size |
|---|---|---|
| `mahavishnu/_main_cli.py` + CLI entry points | 1 | 50 sites |
| `mahavishnu/backup_cli.py` + `quality_cli.py` + `metrics_cli.py` | 3 | 20 sites |
| `mahavishnu/mcp/tools/*` | ~10 | 200 sites |
| `mahavishnu/tui/*` | 2 | 20 sites |
| `mahavishnu/core/*` | ~15 | 100 sites |
| `mahavishnu/pools/*` | 4 | 30 sites |
| `mahavishnu/jot/*` | 3 | 20 sites |
| `mahavishnu/engines/*` + `adapters/*` | 6 | 50 sites |
| `mahavishnu/automation/*` | 4 | 20 sites |
| `mahavishnu/integrations/*` | 2 | 10 sites |
| `mahavishnu/workers/*` | 5 | 30 sites |
| `mahavishnu/cli/*` (sub-CLI) | 3 | 20 sites |

Each PR:

1. **Triggers** a `crackerjack run -v` before push (per
   `feedback-crackerjack-run-vf-not-f.md`: `-v` not `-f`).
2. **Returns to** the local `main` branch via squash-merge
   (per `bodai-pre-1.0-merge-policy.md`).
3. **Demonstrable by**:
   - `git diff main~1 main -- mahavishnu/ | grep '^-.*noqa: BLE001'
     | wc -l` is negative (line count decreases) OR the added
     contract names match the triage.
   - `pytest -m "not slow"` passes locally.
4. **Rollback signal**: a single PR that breaks the gate gets
   reverted via `git revert`; the contract name and `# noqa: BLE001,
   RUF100` pattern are unchanged.
5. **Observability added**: per-PR, the `crackerjack` gate must
   exit 0. The post-merge `git log -p` diff for the cluster is
   reviewed for "Add Exception import" lines (new exception
   subclasses in `mahavishnu/core/errors.py`).

**Integration Contract**:

- **Triggered from**: Phase 1 triage deliverable.
- **Returns to**: the local `main` branch (one PR per cluster).
- **Demonstrable by**: `grep -rn '# noqa: BLE001' --include='*.py'
  mahavishnu/ | wc -l` ≤ 60 at the end of Phase 2.
- **Rollback signal**: if any post-merge PR causes the gate to
  fail, revert that PR (squash-revert). Do not re-merge without
  first re-running the affected file's unit tests.
- **Observability added**: each PR's diff is reviewed for the
  ratio of "specific catch" to "broad catch with contract name"
  changes; the target is ≥ 4:1.
- **Fulfils**: `REQ-LINT-001`, `REQ-LINT-002`.

### Phase 3: Pattern tooling — prevent regression (estimated 1 day, 1 engineer)

**Deliverable**: a `crackerjack` hook (in the crackerjack project,
not mahavishnu) and a `pyproject.toml` rule that together ensure
future BLE001 sites on `main` must include a `TICKET-` prefix in
their justification.

Implementation in `pyproject.toml`:

```toml
[tool.ruff.lint.flake8-blind-except]
# Require a TICKET- prefix in any new BLE001 justification. Hook
# validates at CI time, not at lint time; this stanza documents
# the contract.
check-blank-except = "TICKET-"
```

Implementation in `crackerjack/hooks/check_ble001_justification.py`:

- Run on `git diff main..HEAD -- mahavishnu/` (new sites only).
- For each added `except.*:` line, look for a `# noqa: BLE001`
  comment in the next 5 lines.
- If found, check the comment includes `TICKET-` (regex
  `TICKET-[A-Z]+-\d+`).
- If missing, exit non-zero with the file:line and a message:
  `BLE001 site at FILE:LINE lacks TICKET-NNN rationale — see
  docs/plans/2026-10-15-ble001-triage-and-refactor.md §2 for the
  contract pattern.`

**Integration Contract**:

- **Triggered from**: `crackerjack run` on the mahavishnu project.
- **Returns to**: a new fast_hooks entry in
  `crackerjack/configs/fast_hooks.yaml` (in the crackerjack repo,
  tracked separately as `crackerjack` task `REQ-CJ-BLE-001`).
- **Demonstrable by**: adding a new `except Exception:` in any
  file under `mahavishnu/` without a `TICKET-` justification
  fails the gate locally.
- **Rollback signal**: a `TICKET-` justification that names the
  wrong contract (e.g., `TICKET-FAKE-0001`) is caught by code
  review; the hook itself only validates the format, not the
  semantic correctness — semantic correctness is the PR reviewer's
  job.
- **Observability added**: the hook emits a structured log line
  per BLE001 site, with `kind=ble001_check`, `path=...`,
  `line=...`, `result=pass|fail` for the per-day metrics
  dashboard.
- **Fulfils**: `REQ-LINT-003`.

### Phase 4: Adjacent gate cleanups (estimated 30 min, 1 engineer)

**Deliverable**: 3 line-level fixes.

- `docs/plans/2026-10-15-session-buddy-wrapper-cleanup.md:42`:
  change `]`
  → `text`.
- `docs/plans/2026-10-15-session-buddy-wrapper-cleanup.md:43`:
  change `text` →
  `text`.
- `docs/README.md:58`: change `[Archive](./.archive/)` to
  `[Archive]` (after creating the README,
  which is itself a follow-up).

**Integration Contract**:

- **Triggered from**: Manual — the user said "we'll re-run cj
  ourselves and fix the issues in another session" on 2026-10-15.
- **Returns to**: a single commit on local `main`.
- **Demonstrable by**: `crackerjack run -v` exits 0; specifically,
  the `tc-refs` check reports 0 violations.
- **Rollback signal**: if the path rewrites break in-page
  navigation, revert; the original paths may be referenced by
  static-site generators.
- **Observability added**: the fix is a 2-line `git diff`; no
  metric.
- **Fulfils**: `REQ-LINT-004`.

## 6. Open Questions

1. **Custom exception naming**: when refactoring a `raise SomeError`
   to `raise MahavishnuSpecificError`, what naming convention? The
   project has `mahavishnu/core/errors.py` with classes like
   `ConfigurationError`, `BackupFailed`, `MahavishnuError`. New
   exceptions should follow `<Domain><Error>` (e.g.,
   `PoolDispatchError`, `EmbeddingCacheError`). Confirm in
   `docs/adr/006-simplify-storage-architecture.md` precedent.
2. **Logging convention for refactored catches**: when a specific
   catch logs and re-raises, the project's CLAUDE.md says
   `logger.exception(...)`, not `logger.error(..., exc_info=True)`.
   The exception chain is preserved via `raise X from e` — this
   is the convention.
3. **The contract-name vocabulary** (Phase 1) — should it be
   `cli_top_level` or `top_level_cli`? Pick a convention and stick
   to it. Proposed: `cli_top_level`, `mcp_tool_handler`,
   `tui_handler`, `background_task`, `health_probe` (noun-first,
   snake_case, file-agnostic).

## 7. Decision Log

- 2026-10-15: Plan created. The structural RUF100 defense landed
  on `origin/main` in the prior session; this plan covers the
  follow-up refactor. The 3 deferred `tc-refs` violations are
  in scope for Phase 4.
