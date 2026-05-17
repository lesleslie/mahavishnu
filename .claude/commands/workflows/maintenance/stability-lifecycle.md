______________________________________________________________________

title: Stability Response Lifecycle
owner: Platform Reliability Guild
last_reviewed: 2025-02-06
related_tools:

- commands/tools/monitoring/observability-lifecycle.md
- commands/tools/maintenance/maintenance-cadence.md
- commands/tools/development/testing/quality-validation.md
  risk: high
  status: active
  id: 01K6EF5K54WWNSV9ZSCT17CF06

______________________________________________________________________

## Stability Response Lifecycle

## Inputs

- `$ARGUMENTS` - incident description or degradation summary.
- `$IMPACTED_SERVICES` - affected services or components.
- `$SCENARIOS` - one of `hotfix`, `performance`, `hardening`.

## Outputs

- Mitigation plan with owners and timelines.
- Validated fix with supporting evidence.
- Post-incident review with preventative actions tracked.

## Phases

1. Triage and contain using telemetry, logs, and rollback or feature-flag options.
1. Remediate with the smallest safe fix, then validate with the targeted test suites.
1. Harden by scheduling rollout guardrails, maintenance follow-up, and monitoring updates.

## Handoffs

- Update runbooks and alert thresholds.
- Track follow-up items in the maintenance backlog.
- Close the loop in a post-incident review within five business days.
