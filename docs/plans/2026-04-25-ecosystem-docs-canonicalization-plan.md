# Ecosystem Docs Canonicalization Plan

**Date:** 2026-04-25
**Status:** Complete (all phases shipped 2026-04-30)
**Scope:** Clean up `docs/` directories across active Bodai ecosystem repositories while preserving accurate current documentation, reviewable historical context, and implementation-critical specs/plans.

## 1. Objective

Make ecosystem documentation easier to trust, search, review, and implement from.

The goal is not to delete history aggressively. The goal is to make current truth obvious and move stale, duplicated, generated, or historical material out of the default path.

## 2. Active Repo Scope

Use `settings/ecosystem.yaml` as the phase 1 source of truth.

| Repo | Path | Role | Initial docs inventory |
|---|---|---|---|
| `mahavishnu` | `/Users/les/Projects/mahavishnu` | orchestrator | 651 files, 638 markdown, 372 archived, 0 backup-like |
| `crackerjack` | `/Users/les/Projects/crackerjack` | inspector | 503 files, 457 markdown, 264 archived, 0 backup-like |
| `session-buddy` | `/Users/les/Projects/session-buddy` | manager | 322 files, 301 markdown, 219 archived, 0 backup-like |
| `oneiric` | `/Users/les/Projects/oneiric` | resolver | 136 files, 126 markdown, 32 archived, 0 backup-like |
| `mcp-common` | `/Users/les/Projects/mcp-common` | foundation | 29 files, 28 markdown, 18 archived, 0 backup-like |
| `mdinject` | `/Users/les/Projects/mdinject` | app | 7 files, 7 markdown, 0 archived, 0 backup-like |
| `akosha` | `/Users/les/Projects/akosha` | seer | 63 files, 62 markdown, 26 archived, 0 backup-like |
| `dhara` | `/Users/les/Projects/dhara` | curator | 43 files, 43 markdown, 31 archived, 0 backup-like |

Later phases may include the larger `settings/repos.yaml` set, but phase 1 should stay limited to the active ecosystem repos.

## 3. Problems To Solve

Current docs drift patterns:

- active docs mixed with old phase plans, completion reports, and one-off summaries
- multiple plans for the same feature without a visible canonical replacement
- backup artifacts committed under `docs/.backups`, `docs/backups`, or `*.backup*`
- generated test artifacts stored under docs archive folders
- root-level docs overloaded with implementation reports that should be in `archive/`
- missing or weak `docs/README.md` indexes in some repos
- inconsistent directory naming across repos
- old names still present after ecosystem renames, such as the legacy storage name versus `dhara`
- completion reports treated like active implementation plans

## 4. Target Docs Contract

Every active repo should converge on this minimal structure:

```text
docs/
  README.md
  architecture/
  guides/
  reference/
  runbooks/
  plans/
  specs/
  decisions/ or adr/
  reviews/
  archive/
```

Not every repo needs every directory. Empty directories should not be created just to satisfy the layout.

### 4.1 Required `docs/README.md`

Each active repo should have a docs index that includes:

- current canonical docs
- active plans/specs
- operational runbooks
- architecture/ADR entry points
- known superseded docs
- archive policy

### 4.2 Required Plan Index For Planning-Heavy Repos

Repos with many plans should have:

- `docs/plans/README.md` or `docs/plans/PLAN_INDEX.md`
- status legend
- active canonical plans
- supersession map
- implementation priority
- historical plan pointers

This applies at least to:

- `mahavishnu`
- `crackerjack`
- `session-buddy`
- `akosha`

`oneiric` and `dhara` do not currently trigger the plan-index threshold in the structural audit, but they should still get an index if active plan volume increases.

## 5. Classification Rules

Classify every doc into exactly one primary state.

| State | Meaning | Default location |
|---|---|---|
| `current` | accurate user/operator/developer information | topic directory |
| `canonical` | source of truth for a current architecture, spec, or plan | topic directory or `plans/` |
| `active-plan` | approved or proposed implementation work not done yet | `plans/` |
| `reference` | stable API/schema/config reference | `reference/` |
| `runbook` | operational response or maintenance procedure | `runbooks/` |
| `decision` | ADR or durable design decision | `adr/` or `decisions/` |
| `review` | review/audit input that may inform work but is not an active plan | `reviews/` |
| `historical` | old implementation report, completion summary, checkpoint, or superseded plan | `archive/` |
| `generated` | coverage, JSON output, backup tarball, temporary report | remove from docs or move to ignored artifact storage |
| `duplicate` | materially replaced by another doc | archive with pointer or remove after confirmation |

## 6. Safe Migration Rules

- Do not delete historical markdown in the first pass; move or index it.
- Do not move docs without leaving a pointer if other docs link to them.
- Do not keep generated artifacts in `docs/`.
- Do not keep backup tarballs or `.backup.json` files in `docs/`.
- Do not treat completion reports as active implementation plans.
- Do not create a new canonical plan if an active one already exists; update the existing plan index.
- Do not edit source facts without checking code or current config.
- Keep all cross-repo ecosystem docs linked from Mahavishnu’s plan index or ecosystem docs index.

## 7. Proposed Directory Policy

### Root `docs/`

Allowed:

- `README.md`
- a small number of top-level evergreen docs, only if they are primary entry points

Not allowed:

- phase completion reports
- transient implementation summaries
- backup files
- generated test artifacts
- one-off investigation notes

### `docs/archive/`

Allowed:

- completion reports
- superseded plans
- historical analyses
- checkpoints and handoffs
- old migration reports

Required:

- `docs/archive/README.md` explaining that archive docs are not current authority

### `docs/plans/`

Allowed:

- active implementation plans
- proposed plans awaiting review
- plan indexes

Required:

- plan index for planning-heavy repos
- status values
- supersession notes

### `docs/reviews/`

Allowed:

- architecture, security, SRE, UX, delivery, and quality reviews
- audits that inform active plans

Not allowed:

- implementation plans unless converted into `docs/plans/`

## 8. Implementation Phases

### Phase 0: Audit And Index

Status: complete for structural inventory and entrypoint creation. File-level classification is heuristic and should be reviewed before destructive cleanup.

Goal: create a repo-by-repo inventory without moving files.

Tasks:

- Generate a docs inventory for each active repo.
- Count files by type, directory, and state heuristic.
- Identify missing `docs/README.md` and plan indexes.
- Identify backup/generated artifacts.
- Identify obvious duplicate/stale plan groups.
- Create one cleanup issue/plan per repo.

Deliverables:

- `docs/reports/ecosystem-docs-inventory.md` in Mahavishnu
- per-repo cleanup sections with proposed moves
- no cross-repo file movement yet

Acceptance criteria:

- every active repo has a docs inventory
- every file is at least preliminarily classified
- no destructive changes are made

### Phase 1: Mahavishnu Reference Cleanup

Status: complete for structural cleanup. Remaining Mahavishnu docs work should be content accuracy review, not root/archive hygiene.

Goal: use Mahavishnu as the model because it is the orchestrator and already has the most plan structure.

Tasks:

- Finish `docs/plans/PLAN_INDEX.md` as the canonical plan map.
- Keep active plans in `docs/plans/`.
- Mark old TUI spec as superseded.
- Mark dashboard initiative as partial until live data is implemented.
- Move or index root-level stale reports into archive categories.
- Remove or ignore backup/generated artifacts after review.
- Add or update `docs/archive/README.md`.

Acceptance criteria:

- a reviewer can find the current TUI, control-plane, health, and storage plans in under 30 seconds
- root `docs/` is mostly evergreen documentation
- stale plans have supersession pointers

### Phase 2: Core Service Repos

Status: complete for structural cleanup. Remaining work should be content accuracy review, not root/archive hygiene.

Goal: clean the active service docs in priority order.

Order:

1. `session-buddy`
2. `akosha`
3. `oneiric`
4. `dhara`
5. `mcp-common`

Tasks per repo:

- add/update `docs/README.md`
- add/update `docs/plans/PLAN_INDEX.md` where needed
- classify current vs historical docs
- move completion reports into `archive/completion-reports/`
- move stale implementation plans into `archive/implementation-plans/`
- remove backup/generated artifacts only after explicit review
- fix links after moves

Acceptance criteria:

- current architecture, setup, API/reference, and runbooks are visible from `docs/README.md`
- active plans are listed in one place
- archive docs are clearly non-authoritative

### Phase 3: Tooling And App Repos

Status: complete for structural cleanup. `crackerjack` and `mdinject` have no immediate structural recommendations in the latest audit.

Goal: clean smaller repos after the core docs contract is proven.

Order:

1. `crackerjack`
2. `mdinject`

Tasks:

- same per-repo cleanup process as phase 2
- for Crackerjack, separate active quality docs from historical refactor/completion reports
- for MdInject, preserve the compact docs set and avoid over-structuring

### Phase 4: Ecosystem-Wide Link And Drift Checks

**Status: Complete (2026-04-30)**

Goal: prevent re-drift.

Tasks:

- [x] Add a lightweight docs audit script or Mahavishnu command — `mahavishnu docs audit`
  - `scripts/audit_ecosystem_docs.py` (read-only, JSON/text/markdown output)
  - `mahavishnu/cli/docs_cli.py` wraps it as `mahavishnu docs audit [--output text|json|markdown] [--write FILE]`
- [x] Check for backup artifacts under docs (backup_like_files counter in report)
- [x] Check for stale root patterns (stale_root_candidates counter in report)
- [ ] Check for missing `docs/README.md` (not implemented — low priority, skipped)
- [ ] Check for broken relative links (not implemented — deferred to v0.6.0)
- [x] Add docs hygiene guidance via CLI recommendations output

Acceptance criteria:

- [x] docs drift checks can be run locally across active repos (`uv run mahavishnu docs audit`)
- [x] new stale/generated docs are flagged before review (backup_like and stale_root counters)

## 9. Suggested Automation

Add a Mahavishnu-local audit command first, then decide whether to promote it to a shared ecosystem tool.

Current script:

```bash
python scripts/audit_ecosystem_docs.py --output text
python scripts/audit_ecosystem_docs.py --output markdown --write docs/reports/ecosystem-docs-audit.md
python scripts/audit_ecosystem_docs.py --output markdown --include-files --write docs/reports/ecosystem-docs-cleanup-candidates.md
python scripts/standardize_ecosystem_docs_structure.py
```

Future candidate command:

```bash
uv run mahavishnu docs audit --active-ecosystem --json
```

Candidate implementation:

- read `settings/ecosystem.yaml`
- inspect each active repo docs tree
- classify docs by path/name/frontmatter heuristics
- emit markdown and JSON reports
- do not move/delete files

Candidate report:

```text
repo
path
status
state
reason
recommended_action
canonical_replacement
```

## 10. Review Questions

1. Should phase 1 clean only Mahavishnu first, or should it also clean `session-buddy` and `akosha` as the most important dependent services?
2. Should generated artifacts under `docs/archive/test-artifacts` be deleted immediately, or moved to ignored local artifact storage first?
3. Should archived docs keep their original paths via stub redirect files, or is updating links enough?
4. Should each repo use the same exact docs structure, or only the same classification rules?
5. Should Mahavishnu own the cross-repo docs audit command?

## 11. Definition Of Done

This cleanup is done when:

- every active repo has a usable `docs/README.md`
- every planning-heavy repo has one plan index
- current docs are clearly separated from archived/historical docs
- backup/generated artifacts are no longer committed under active docs paths
- superseded specs and plans point to their canonical replacements
- Mahavishnu can produce a cross-repo docs inventory report
- reviewers can find current plans/specs/runbooks without searching through stale completion reports

## 12. Progress Log

- 2026-04-25: Plan created and linked from `docs/plans/PLAN_INDEX.md`.
- 2026-04-25: Initial active-repo inventory captured in `docs/reports/ecosystem-docs-inventory.md`.
- 2026-04-25: Added Mahavishnu root `docs/README.md` and `docs/archive/README.md` as the first Phase 1 discoverability cleanup.
- 2026-04-25: Identified Mahavishnu backup/generated artifact cleanup candidates; no destructive cleanup performed yet.
- 2026-04-25: Added read-only `scripts/audit_ecosystem_docs.py` and generated `docs/reports/ecosystem-docs-audit.md`.
- 2026-04-25: Moved historical markdown from `docs/backups/` to `docs/archive/backups/`.
- 2026-04-25: Removed generated docs artifacts after explicit approval: four `docs/.backups/*/backup.tar.gz` files and `docs/archive/test-artifacts/coverage.json`.
- 2026-04-25: Added `docs/reports/mahavishnu-root-docs-cleanup-candidates.md` for root-level stale report/action-plan review.
- 2026-04-25: Removed 11 Mahavishnu duplicate root reports with exact archive copies, moved the remaining stale root action plans/reports into archive categories, and updated active links.
- 2026-04-25: Added `scripts/standardize_ecosystem_docs_structure.py` and created missing docs entrypoints/indexes across `crackerjack`, `session-buddy`, `mcp-common`, `mdinject`, `akosha`, and `dhara` after approval.
- 2026-04-25: Added file-level candidate output to `scripts/audit_ecosystem_docs.py` and generated `docs/reports/ecosystem-docs-cleanup-candidates.md`.
- 2026-04-25: Refreshed generated scaffold docs after correcting plan-index link generation to be relative to `docs/plans/`.
- 2026-04-25: Completed structural cleanup for `session-buddy`, `oneiric`, `mcp-common`, `akosha`, and `dhara`: removed generated/backup artifacts after approval, moved stale root reports/plans into archive categories, and updated moved-doc references.
- 2026-04-25: Added `.hypothesis/` and `.idea/` ignore rules to Oneiric; existing tracked files still require `git rm --cached` if they should leave version control.
- 2026-04-25: Completed structural cleanup for `crackerjack`: removed generated/backup artifacts after approval, moved stale root reports/summaries/progress docs into `docs/archive/completion-reports/`, and updated active references.
- 2026-04-25: Latest `scripts/audit_ecosystem_docs.py --output text` reports all active ecosystem repos as `OK`.
