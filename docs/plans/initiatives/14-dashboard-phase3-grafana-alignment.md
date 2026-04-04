# Initiative 14: Dashboard Phase 3 (Grafana Alignment)

## Metadata
- Status: `not_started`
- Owner Role: `SRE + Platform UI`
- Target Window: `2026-06-15` to `2026-06-26`

## Outcome
Align TUI and Grafana to a single canonical metrics model.

## Work Package Checklist
- [ ] `I14-1` Map TUI metrics to canonical Prometheus inventory
- [ ] `I14-2` Add sweep history dashboard and panel tests
- [ ] `I14-3` Remove corrupted legacy dashboard assets

## Dependencies
- `I13-3`

## Exit Criteria
- Dashboard query errors `<2%`
- Metric parity between TUI and Grafana for core panels

## Risks
- Drift between dashboard query definitions and instrumentation
- Stale panels persisting after contract changes

## Progress Log
- 2026-04-04: Plan file created.
