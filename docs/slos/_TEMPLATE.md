# SLO Template

> Copy this file when adding an SLO document for a new plan or service.
> Name the copy with the date the SLO was ratified: `YYYY-MM-DD-<service>.md`.

## Service

- **Name**:
- **Owner**:
- **Plan / RFC**:
- **Date ratified**:

## SLOs

Define 3-5 SLOs. Each one gets:

- **Name** (action-oriented): e.g. "Request success rate"
- **SLI** (Service Level Indicator): the metric being measured.
- **Objective**: the target value (e.g. `>= 99.5% over 30 days`).
- **Window**: the measurement window (rolling).
- **Exclusions**: optional list of known-bad inputs not counted.

### SLO 1 — <Name>

| Field | Value |
|-------|-------|
| SLI | `<metric query>` |
| Objective | `<value>` over `<window>` |
| Burn-rate alert | `<threshold>×` over `<short window>` |
| Page after | `<duration>` |
| Runbook | `<link>` |

### SLO 2 — <Name>

| Field | Value |
|-------|-------|
| SLI | |
| Objective | |
| Burn-rate alert | |
| Page after | |
| Runbook | |

### SLO 3 — <Name>

| Field | Value |
|-------|-------|
| SLI | |
| Objective | |
| Burn-rate alert | |
| Page after | |
| Runbook | |

## Rollback

- **Command**: `mahavishnu rollback <plan> --<selector> <value>`
- **Selector options**:
- **What it reverts**:
- **What it preserves**:
- **Average time to complete**:

## Error budget policy

- **Window**:
- **Actions when exhausted**:

## Change log

| Date | Author | Change |
|------|--------|--------|
