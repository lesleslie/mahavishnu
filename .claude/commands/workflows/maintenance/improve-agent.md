---
title: Agent Improvement Workflow
owner: Developer Enablement Guild
last_reviewed: '2026-11-17'
risk: medium
status: active
id: 01a1e928ac5171ae9a582b03f5343b23
category: maintenance
description: Improves a named agent's scope, tone, playbook, or metadata, then validates the updated prompts and telemetry hooks before publishing.
---

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
