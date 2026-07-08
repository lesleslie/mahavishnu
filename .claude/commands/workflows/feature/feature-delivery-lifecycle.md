______________________________________________________________________

title: Feature Delivery Lifecycle
owner: Product Leadership
last_reviewed: 2025-02-06
related_tools:

- commands/tools/development/code-quality/dependency-lifecycle.md
- commands/tools/development/testing/quality-validation.md
- commands/tools/workflow/support-readiness.md
- docs/plans/TEMPLATE.md
  risk: medium
  status: active
  id: 01K6EF5K3VBN8NXFCZMV04VZSM

______________________________________________________________________

## Feature Delivery Lifecycle

Use this workflow for end-to-end delivery of a feature from discovery to adoption monitoring.

## Focus areas

- Outcomes, research, and system design
- Implementation planning and validation
- Launch enablement and rollback
- Post-launch metrics and learning

## Workflow

1. Define the product outcome and success metrics.
1. Design the solution and break it into implementable work.
1. Wiring — wire the components and verify integration end-to-end.
1. Validate with the right tests and checks.
1. Launch with enablement and rollback readiness.
1. Monitor adoption and capture follow-up actions.

### Wiring Checklist

Before marking step 3 complete, confirm every item below. Use the
Integration Contract block from `docs/plans/TEMPLATE.md` for each
phase deliverable in the active plan.

- [ ] Trigger path identified (which entry point invokes this feature).
- [ ] Integration point identified (which app, CLI subcommand, MCP tool, workflow, or pool handler consumes the new code).
- [ ] End-to-end check documented (one CLI command, HTTP request, or test name that exercises trigger → integration → observable result).
- [ ] Observability added (log line, OTel span, or metric) so the wiring is visible in production.
- [ ] Integration Contract block from `docs/plans/TEMPLATE.md` filed for every phase deliverable in the active plan.

## Output

- Discovery artifacts and technical design
- Validation and acceptance evidence
- Integration Contract for every deliverable in the active plan
- Launch plan and monitoring checklist

## Inputs

- `$ARGUMENTS`
- `$SCENARIOS`
- `$LAUNCH_TARGET`
