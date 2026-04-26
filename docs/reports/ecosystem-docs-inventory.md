# Ecosystem Docs Inventory

**Date:** 2026-04-25
**Source:** `settings/ecosystem.yaml`
**Scope:** Active Bodai ecosystem repos only.
**Related Plan:** [../plans/2026-04-25-ecosystem-docs-canonicalization-plan.md](../plans/2026-04-25-ecosystem-docs-canonicalization-plan.md)

## Summary

The active ecosystem repos have substantial documentation drift. Most repos already have some archive structure, but current docs, old plans, completion reports, backup files, and generated artifacts are still mixed enough that reviewers cannot reliably tell which docs are current without extra investigation.

## Inventory

| Repo | Docs path | Total files | Markdown files | Archive files | Backup-like files |
|---|---|---:|---:|---:|---:|
| `mahavishnu` | `/Users/les/Projects/mahavishnu/docs` | 651 | 638 | 372 | 0 |
| `crackerjack` | `/Users/les/Projects/crackerjack/docs` | 503 | 457 | 264 | 0 |
| `session-buddy` | `/Users/les/Projects/session-buddy/docs` | 322 | 301 | 219 | 0 |
| `oneiric` | `/Users/les/Projects/oneiric/docs` | 136 | 126 | 32 | 0 |
| `mcp-common` | `/Users/les/Projects/mcp-common/docs` | 29 | 28 | 18 | 0 |
| `mdinject` | `/Users/les/Projects/mdinject/docs` | 7 | 7 | 0 | 0 |
| `akosha` | `/Users/les/Projects/akosha/docs` | 63 | 62 | 26 | 0 |
| `dhara` | `/Users/les/Projects/dhara/docs` | 43 | 43 | 31 | 0 |

## Immediate Observations

- All active ecosystem repos have no immediate structural recommendations in the latest audit.
- `mdinject` is already compact and should not be over-structured.
- `mcp-common`, `akosha`, and `dhara` are small enough for one focused cleanup pass after the pattern is proven.
- Backup-like and generated artifacts have been removed from the active ecosystem docs scope.
- Archive volume is not inherently bad, but each archive needs clear non-authoritative status.

## Recommended First Pass

1. Finish Mahavishnu plan indexing and archive policy.
2. Generate detailed per-file classifications for `mahavishnu`, `session-buddy`, and `akosha`.
3. Add or update `docs/README.md` in each active repo.
4. Add `docs/plans/PLAN_INDEX.md` where a repo has multiple active or historical plans.
5. Remove or ignore generated/backup artifacts only after repo-local review.

## Mahavishnu Cleanup Outcome

Backup/generated artifacts removed from Mahavishnu docs after explicit approval:

- `docs/.backups/20260129-195143/backup.tar.gz`
- `docs/.backups/20260210-034304/backup.tar.gz`
- `docs/.backups/20260404-172646/backup.tar.gz`
- `docs/.backups/20260416-060941/backup.tar.gz`
- `docs/archive/test-artifacts/coverage.json`

Historical backup markdown moved from `docs/backups/` to `docs/archive/backups/`:

- `DOCUMENTATION_CORRECTIONS.md`
- `DOCUMENTATION_UPDATES_JAN_2025.md`
- `ECOSYSTEM_REMEDIATION_STATUS.md`
- `ECOSYSTEM_STATUS_FINAL.md`
- `IMPLEMENTATION_PLAN_ENHANCED.md`
- `MCP_SERVER_CRITICAL_REVIEW.md`
- `PRODUCTION_READINESS_CHECKLIST.md`
- `PROGRESS.md`
- `QWEN.md`
- `README_ONEIRIC.md`
- `RELEASE_NOTES.md`
- `REMAINING_TASKS.md`
- `TRIFECTA_REVIEW_FINAL.md`
- `TRIFECTA_REVIEW_Oneiric.md`
- `VECTOR_DATABASE_EVALUATION.md`
- `WORKFLOW_OPTIMIZATION.md`

Completed handling:

- removed backup tarballs and generated coverage artifacts after explicit approval
- moved historical backup markdown to `docs/archive/backups/`
- removed exact duplicate root reports that already had archive copies
- moved remaining stale root action plans to `docs/archive/implementation-plans/`
- moved remaining stale root reports and summaries to `docs/archive/completion-reports/`
- regenerated `docs/reports/ecosystem-docs-audit.md`; Mahavishnu now has zero backup-like files, zero generated docs artifacts, and zero root stale candidates

Remaining handling:

- review `docs/archive/backups/*.md` for unique current information before any future removal
- keep no `.backups` or `backups` directory under active docs long-term
- continue ecosystem-wide cleanup in the repo order below

## Ecosystem Structure Standardization

Created missing docs entrypoint/index files using `scripts/standardize_ecosystem_docs_structure.py --apply` after approval:

- `/Users/les/Projects/crackerjack/docs/plans/PLAN_INDEX.md`
- `/Users/les/Projects/session-buddy/docs/README.md`
- `/Users/les/Projects/session-buddy/docs/plans/PLAN_INDEX.md`
- `/Users/les/Projects/mcp-common/docs/README.md`
- `/Users/les/Projects/mcp-common/docs/archive/README.md`
- `/Users/les/Projects/mdinject/docs/README.md`
- `/Users/les/Projects/akosha/docs/README.md`
- `/Users/les/Projects/akosha/docs/archive/README.md`
- `/Users/les/Projects/akosha/docs/plans/PLAN_INDEX.md`
- `/Users/les/Projects/dhara/docs/README.md`

The follow-up dry run reported no missing docs structure files.

## Core Service Cleanup Outcome

Completed structural cleanup for `session-buddy`, `oneiric`, `mcp-common`, `akosha`, and `dhara` after explicit approval:

- removed generated backup tarballs and coverage JSON artifacts
- removed `.backup` and `.backup.json` sidecars in `session-buddy` and `oneiric`
- moved stale root reports and summaries into `docs/archive/completion-reports/`
- moved Akosha's stale integration review into `docs/archive/analysis/`
- moved Akosha's dated post-audit action plan into `docs/archive/implementation-plans/`
- updated active references to moved docs

The latest audit reports no immediate structural recommendations for these repos.

## Crackerjack Cleanup Outcome

Completed structural cleanup for `crackerjack` after explicit approval:

- removed generated backup tarballs, coverage JSON artifacts, and `.backup` sidecars
- moved stale root reports, summaries, completion reports, and progress notes into `docs/archive/completion-reports/`
- updated active references to moved docs

The latest audit reports no immediate structural recommendations for Crackerjack.

## Proposed Repo Order

1. `mahavishnu`
2. `session-buddy`
3. `akosha`
4. `oneiric`
5. `dhara`
6. `mcp-common`
7. `crackerjack`
8. `mdinject`

Rationale:

- Start with Mahavishnu because it is the ecosystem index and orchestrator.
- Clean Session-Buddy and Akosha early because they are central dependencies for memory/session/search context.
- Delay Crackerjack despite its high drift because its docs are likely tied to quality tooling and should be cleaned with extra care.
- Keep MdInject last because its docs directory is already small.
