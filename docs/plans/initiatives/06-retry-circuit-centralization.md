# Initiative 6: Retry/Circuit-Breaker Centralization

## Metadata
- Status: `not_started`
- Owner Role: `SRE + Core Eng`
- Target Window: `2026-04-27` to `2026-05-15`

## Outcome
Replace ad hoc retry logic with policy-driven resilience behavior.

## Work Package Checklist
- [ ] `I6-1` Dependency taxonomy and policy matrix
- [ ] `I6-2` Shared retry/circuit module
- [ ] `I6-3` Migrate top 3 critical flows
- [ ] `I6-4` Add retry amplification and circuit metrics

## Dependencies
- `I5-1`

## Exit Criteria
- Retry amplification `<1.3x`
- MTTR improvement of `>=20%`

## Risks
- Retry storms from poor default policy
- Hidden callsites retaining old behavior

## Progress Log
- 2026-04-04: Plan file created.
