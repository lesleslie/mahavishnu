# Initiative 0: Phase 0 Cleanup

## Metadata
- Status: `in_progress`
- Owner Role: `Platform Eng`
- Target Window: `2026-04-06` to `2026-04-10`
- Parent Plan: `docs/plans/2026-04-04-ecosystem-execution-board.md`

## Outcome
Remove obsolete backup artifacts and consolidate duplicate monitoring primitives to reduce debt and simplify future implementation.

## Work Package Checklist
- [x] `I0-1` Inventory and classify all `.bak` files
- [x] `I0-2` Remove `.bak` files and update ignore rules
- [ ] `I0-3` Consolidate `AlertManager` implementation
- [ ] `I0-4` Resolve dashboard config split and imports

## Dependencies
- None

## Exit Criteria
- `.bak` files in source tree: `0`
- Single canonical `AlertManager`
- Monitoring tests pass

## Risks
- Accidental deletion of needed artifacts
- Hidden imports to old monitoring classes

## Progress Log
- 2026-04-04: Plan file created.
- 2026-04-04: Completed backup artifact inventory, removed tracked `.bak` files, and added ignore rules for backup/temp suffixes.
