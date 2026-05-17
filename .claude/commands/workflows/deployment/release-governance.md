______________________________________________________________________

title: Release Governance Workflow
owner: Delivery Operations
last_reviewed: 2025-02-06
related_tools:

- commands/tools/deployment/release-management.md
- commands/tools/development/testing/quality-validation.md
- commands/tools/monitoring/observability-lifecycle.md
  risk: high
  status: active
  id: 01K6EF5K31G84FC47F8TFBZ1EN

______________________________________________________________________

## Release Governance Workflow

Use this workflow to move a release from readiness review to launch and stabilization.

## Focus areas

- Release artifacts and readiness evidence
- Testing, security, and compliance gates
- Stakeholder approvals and communications
- Rollback readiness and monitoring
- Post-release reporting

## Workflow

1. Validate notes, manifests, test results, and security evidence.
1. Confirm approvals and launch window readiness.
1. Check infrastructure, monitoring, and rollback options.
1. Make the go/no-go decision and execute the launch.
1. Capture stabilization notes and the final report.

## Output

- Signed release checklist
- Go/no-go decision log
- Launch communication packet
- Post-release report

## Inputs

- `$ARGUMENTS`
- `$RELEASE_WINDOW`
- `$RISK_PROFILE`
