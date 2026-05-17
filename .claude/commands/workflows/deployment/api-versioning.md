______________________________________________________________________

title: API Versioning & Deprecation Workflow
owner: Delivery Operations
last_reviewed: 2025-10-01
related_tools:

- commands/tools/deployment/release-management.md
- commands/tools/monitoring/observability-lifecycle.md
- commands/tools/workflow/support-readiness.md
  risk: high
  status: active
  id: 01K6HMR2VXQWZ7N8KP4JT5YH6R

______________________________________________________________________

## API Versioning & Deprecation Workflow

Use this workflow to introduce API changes safely and retire old versions without breaking consumers.

## Focus areas

- Versioning strategy and compatibility rules
- Breaking change detection
- Contract tests and usage analytics
- Deprecation notices and migration guides
- Sunset timing and customer communication

## Workflow

1. Classify the change as compatible, breaking, or deprecation-only.
1. Verify the current API docs, contracts, and consumer usage.
1. Choose the right versioning approach and release plan.
1. Define the deprecation timeline and migration support.
1. Monitor usage before fully sunsetting old versions.

## Output

- Versioning plan
- Deprecation and migration checklist
- Customer communication brief

## Inputs

- `$ARGUMENTS`
- `$CHANGE_TYPE`
- `$AFFECTED_VERSION`
- `$NEW_VERSION`
