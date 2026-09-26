-- V202609260001__idempotency_key_column.sql
-- Forward-only. No downgrade. Recovery is a follow-up forward migration if needed.
-- Pre-1.0 zero backcompat per feedback-no-backwards-compat-pre-1.0.
--
-- REV A: Add the column (transactional — fast).
-- Companion revision V202609260001b adds the unique index via CONCURRENTLY
-- (cannot run inside a transaction block; relies on transaction_per_migration=False
--  set preemptively in C-3).
--
-- Implements: REQ-004 (Schema reconciliation — idempotency_key column on
-- audit.task_events to align with migrations/init.sql:110 declaration).

BEGIN;

-- Pre-flight: detect duplicate idempotency_keys before adding the constraint.
-- This DO $$ block runs BEFORE the ALTER TABLE. If duplicates exist, the
-- migration aborts BEFORE adding the column. This avoids the worse failure
-- mode where the column exists but the unique-index revision can't apply.
--
-- NOTE: The mahavishnu.core.migrations.apply_revision wrapper ALSO performs
-- this pre-flight check in Python before running the SQL. This block is the
-- belt-and-braces backstop for direct alembic CLI execution.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM (
            SELECT COUNT(*) - COUNT(DISTINCT idempotency_key) AS dup_count
            FROM audit.task_events
            WHERE idempotency_key IS NOT NULL
        ) sub WHERE dup_count > 0
    ) THEN
        RAISE EXCEPTION 'pre-flight: duplicate idempotency_keys detected; dedupe before migrating';
    END IF;
END$$;

-- Add the column (nullable — existing rows have NULL idempotency_key).
-- VARCHAR(255) matches migrations/init.sql:110. ADD COLUMN IF NOT EXISTS makes
-- this revision idempotent (re-runs are safe).
ALTER TABLE audit.task_events
    ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255);

COMMIT;
