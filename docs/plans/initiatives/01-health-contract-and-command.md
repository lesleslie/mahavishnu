# Initiative 1: Health/Readiness/Metrics Contract + `mahavishnu health`

## Metadata
- Status: `not_started`
- Owner Role: `Platform Eng + SRE`
- Target Window: `2026-04-06` to `2026-04-17`

## Outcome
Create a consistent health contract across ecosystem services and a single command for operators.

## Work Package Checklist
- [ ] `I1-1` Author health schema spec (`v1`)
- [ ] `I1-2` Implement schema in Mahavishnu endpoint
- [ ] `I1-3` Implement `mahavishnu health` + `--json`
- [ ] `I1-4` Timeout/failure behavior tests + telemetry

## Dependencies
- `I0-4`

## Exit Criteria
- `mahavishnu health` p95 `< 2s`
- `--json` schema validated in tests
- Adoption gate met (`>=3` active developers weekly)

## Risks
- Contract mismatch across services
- Timeout handling regressions

## Progress Log
- 2026-04-04: Plan file created.
