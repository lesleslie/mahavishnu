# Docs Archive

This directory contains historical Mahavishnu documentation.

Archive documents are retained for provenance, audits, migration history, and context recovery. They are not current authority unless a current plan or `docs/README.md` explicitly points here.

## Use Current Docs First

For current review and implementation work, start with:

- [Docs README](../README.md)
- [Plan Index](../plans/PLAN_INDEX.md)
- [Current Plans README](../plans/README.md)

## Archive Categories

- `analysis/` - historical investigations and review notes
- `implementation-plans/` - superseded or completed implementation plans
- `completion-reports/` - reports for completed work
- `guides/` - older guides that may have current replacements elsewhere
- `quick-references/` - older quick references
- `migration/` - historical migration material
- `phase-reports/` - historical phase completion/status reports
- `test-reports/` - historical test summaries
- `test-artifacts/` - generated test artifacts; candidates for removal from committed docs
- `backups/` - historical markdown formerly stored under `docs/backups/`

## Archive Policy

- Do not implement directly from archive docs without checking current code and current plans.
- Do not add new active plans here.
- Prefer moving stale root-level reports here over leaving them in the active docs path.
- Generated files, coverage reports, tarballs, and temporary artifacts should not live here long-term.
- If an archived document is superseded by a current plan, add a pointer in the current plan index or the archived document when practical.
