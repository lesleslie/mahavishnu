# Initiative 13: Dashboard Phase 2 (Textual, Conditional)

## Metadata
- Status: `not_started`
- Owner Role: `Platform UI`
- Target Window: `2026-06-08` to `2026-06-26`

## Outcome
Provide live read-only ecosystem diagnostics in a unified Textual dashboard.

## Work Package Checklist
- [ ] `I13-1` Add `[tui]` dependency and bootstrap app shell
- [ ] `I13-2` Implement overview + sweep screens
- [ ] `I13-3` Implement routing/alerts screens + read-only constraints

## Dependencies
- `G1` Adoption gate: Initiative 1 command usage (`>=3` active weekly users)

## Exit Criteria
- Read-only dashboard renders all planned screens with live data for 5 consecutive days
- Dashboard crash-free sessions `>=99%` during pilot window
- Incident response median time does not degrade by more than `5%` in pilot window

## Risks
- Building UI before operational data contracts are stable
- Runtime overhead or operational fragility in TUI layer

## Progress Log
- 2026-04-04: Plan file created.
