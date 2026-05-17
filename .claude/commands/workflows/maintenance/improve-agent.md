______________________________________________________________________

title: Agent Improvement Workflow
owner: Developer Enablement Guild
last_reviewed: 2025-02-06
related_tools:

- commands/tools/development/code-quality/dependency-lifecycle.md
- commands/tools/development/testing/quality-validation.md
  risk: medium
  status: active
  id: 01K6EF8EM6WQWW9KGRHXS02CMP

______________________________________________________________________

## Agent Improvement Workflow

## Inputs

- `$ARGUMENTS` - target agent name and desired improvement.
- `$IMPROVEMENT_TYPE` - `scope`, `tone`, `playbook`, or `metadata`.
- `$SUCCESS_METRICS` - criteria that show the update worked.

## Outputs

- Revised agent instructions and metadata.
- Validation results for the new behavior.
- Changelog entry for catalog governance.

## Phases

1. Review usage, feedback, and the improvement goal.
1. Draft the changes and keep the structure clear and consistent.
1. Validate the updated prompts and telemetry hooks.
1. Publish the update and record the change.

## Handoffs

- Schedule a follow-up review.
- Archive the previous agent version for auditability.
