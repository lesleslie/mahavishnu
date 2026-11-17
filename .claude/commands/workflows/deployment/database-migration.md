---
title: Database Migration Workflow
owner: Delivery Operations
last_reviewed: '2026-11-17'
risk: critical
status: active
id: 01a1e928ac387772ba6c5d9294d22b69
category: deployment
description: Use this workflow to plan, execute, and validate database changes with rollback in mind.
---

______________________________________________________________________

## Database Migration Workflow

Use this workflow to plan, execute, and validate database changes with rollback in mind.

## Focus areas

- Zero-downtime schema changes
- Expand/contract planning
- Backfill and data validation
- Rollback strategy and backup checks
- Performance and lock-risk review

## Workflow

1. Validate backups, staging parity, and migration tooling.
1. Choose the smallest safe migration strategy.
1. Run the migration in stages with validation after each step.
1. Confirm data integrity and performance before broad rollout.
1. Keep rollback steps ready and rehearsed.

## Output

- Migration plan and script checklist
- Validation and rollback checklist
- Post-migration verification summary

## Inputs

- `$ARGUMENTS`
- `$DATABASE_TYPE`
- `$MIGRATION_RISK`
- `$DOWNTIME_ALLOWED`
