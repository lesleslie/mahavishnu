---
title: Incident Response Workflow
owner: Platform Reliability Guild
last_reviewed: '2026-11-17'
risk: critical
status: active
id: 01a1e928ac5574babff78eb035f245b4
category: maintenance
description: Use this workflow when a service degradation or outage is declared, covering triage, containment, recovery, and postmortem actions.
---

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
