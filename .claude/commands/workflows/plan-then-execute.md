______________________________________________________________________

title: Plan-Then-Execute Feature Development
owner: orchestration
last_reviewed: 2025-01-15
category: feature/
status: active
risk_level: low

______________________________________________________________________

## Plan-Then-Execute Workflow

Use this workflow for complex work that needs a deliberate planning gate before implementation.

## When to use

- Multi-file refactors
- Architecture changes
- Complex integrations
- Cross-system performance work
- Migrations between approaches

## Workflow

1. Analyze requirements, current state, and constraints.
1. Design the solution and compare alternatives.
1. Create a phased implementation plan with risks and mitigations.
1. Wait for explicit approval before execution.
1. Review outcomes against the plan and capture lessons learned.

## Output

- Problem statement and requirements
- Architecture and implementation plan
- Risk and mitigation summary
- Success criteria and timeline

## Approval

- Only continue after an explicit `proceed`, `approved`, or `start`.
- Revise the plan if the user gives feedback.
