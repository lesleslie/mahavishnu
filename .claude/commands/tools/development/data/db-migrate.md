______________________________________________________________________

title: Db Migrate
owner: Developer Enablement Guild
last_reviewed: 2025-02-06
supported_platforms:

- macOS
- Linux
  required_scripts: []
  risk: medium
  status: active
  id: 01K6EEXC7CT7WT6ENVYFFGMAC3
  category: development/data

______________________________________________________________________

## Database Migration Strategy

Use this tool to design safe schema and data migrations with minimal downtime.

## Focus areas

- Expand-contract sequencing
- Backward-compatible schema changes
- Batch backfills and throttling
- Index creation strategy
- Rollback and validation steps
- Large table safety and lock avoidance

## Workflow

1. Classify the change: schema, data, index, or constraint.
1. Decide whether the migration can be backward compatible.
1. Plan deploy order: code first, schema first, or parallel.
1. Add validation and rollback steps.
1. Call out any lock, backfill, or data-loss risk.

## Output

- Migration plan
- Example SQL or Alembic migration when needed
- Validation and rollback checklist

## Requirements

$ARGUMENTS
