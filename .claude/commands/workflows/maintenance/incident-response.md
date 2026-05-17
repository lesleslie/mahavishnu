______________________________________________________________________

title: Incident Response Workflow
owner: Platform Reliability Guild
last_reviewed: 2025-02-06
related_tools:

- commands/tools/monitoring/observability-lifecycle.md
  risk: critical
  status: active
  id: 01K6EF8EJN8EVC240V87X7KH92

______________________________________________________________________

## Incident Response Workflow

Use this workflow when a service degradation or outage is declared.

## Focus areas

- Severity classification and command structure
- Containment, mitigation, and recovery
- Customer and executive communications
- Postmortem and prevention follow-up

## Workflow

1. Assign an incident commander and confirm severity.
1. Triage the issue, contain blast radius, and gather evidence.
1. Implement and validate the fix or rollback.
1. Communicate status during and after recovery.
1. Capture action items and prevention measures.

## Output

- Mitigation timeline and incident log
- Verified fix and recovery evidence
- Post-incident report and action list

## Inputs

- `$ARGUMENTS`
- `$SEVERITY`
- `$AFFECTED_AREAS`
