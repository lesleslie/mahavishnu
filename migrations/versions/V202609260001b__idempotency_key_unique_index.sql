-- V202609260001b__idempotency_key_unique_index.sql
-- Forward-only. No downgrade. Recovery is a follow-up forward migration if needed.
-- Pre-1.0 zero backcompat per feedback-no-backwards-compat-pre-1.0.
--
-- REV B: Create the unique partial index via CONCURRENTLY (non-transactional).
-- CREATE UNIQUE INDEX CONCURRENTLY cannot run inside a transaction block.
-- This migration runs OUTSIDE the Alembic transaction — relies on
-- transaction_per_migration=False in env.py (set in C-3).
--
-- Implements: REQ-004 (Schema reconciliation — idempotency_key unique index on
-- audit.task_events).
--
-- Note: no BEGIN here. The op.execute() wrapper in Alembic skips autocommit
-- wrapping for this revision because env.py has transaction_per_migration=False.
--
-- FIX (round-5 critique): audit.task_events is PARTITION BY RANGE (event_time)
-- per V202604021200__initial_consolidated_schema.sql:112. Postgres requires the
-- partition key in any UNIQUE constraint on a partitioned table. Composite
-- index on (idempotency_key, event_time) preserves uniqueness for non-null
-- idempotency_key values while satisfying the partition requirement.
--
-- The WHERE idempotency_key IS NOT NULL clause makes this a partial unique
-- index — multiple NULL keys are allowed (the column is nullable; existing
-- rows have NULL), but non-null keys must be unique.
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_task_events_idempotency_key
    ON audit.task_events (idempotency_key, event_time)
    WHERE idempotency_key IS NOT NULL;
