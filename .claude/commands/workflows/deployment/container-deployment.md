______________________________________________________________________

title: Container Deployment Workflow
owner: Delivery Operations
last_reviewed: 2025-02-06
related_tools:

- commands/tools/development/code-quality/dependency-lifecycle.md
- commands/tools/deployment/release-management.md
- commands/tools/monitoring/observability-lifecycle.md
  risk: high
  status: active
  id: 01K6EF8EGDYJX8PH521SW7TV6R

______________________________________________________________________

## Container Deployment Workflow

Use this workflow to plan, secure, and roll out containerized services.

## Focus areas

- Image hardening and registry access
- Orchestration manifests and namespaces
- CI/CD and rollback readiness
- Secrets, config, and observability
- Resource quotas and policy enforcement

## Workflow

1. Validate the registry, cluster, and pipeline access.
1. Check secrets, config, quotas, and monitoring.
1. Confirm network, DNS, and policy prerequisites.
1. Deploy with a rollback path and health checks.
1. Capture the runbook and follow-up items.

## Output

- Container deployment plan
- Validation and rollout checklist
- Monitoring and rollback notes

## Inputs

- `$ARGUMENTS`
- `$PLATFORMS`
- `$COMPLIANCE_FLAGS`
