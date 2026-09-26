-- V202609260003__execution_events.sql
-- Forward-only. No downgrade. Recovery is a follow-up forward migration if needed.
-- Pre-1.0 zero backcompat per feedback-no-backwards-compat-pre-1.0.
--
-- Implements: REQ-003 (Execution events persistence layer)
--
-- IMPORTANT: This revision uses CREATE INDEX (non-concurrent), which is safe inside
-- an Alembic transaction. The C-4 revision handles the unique-concurrent-index case.
--
-- BIGSERIAL (not SERIAL) supports >2B events per execution over the lifetime of an
-- installation. TIMESTAMPTZ (not TIMESTAMP) prevents timezone arithmetic bugs when
-- correlating events across pools in different regions.

BEGIN;

CREATE TABLE IF NOT EXISTS execution_events (
    id BIGSERIAL PRIMARY KEY,
    execution_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(64) NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor VARCHAR(255) NOT NULL,
    correlation_id VARCHAR(64),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_execution_events_execution_id
    ON execution_events (execution_id);
CREATE INDEX IF NOT EXISTS ix_execution_events_execution_id_occurred_at
    ON execution_events (execution_id, occurred_at);

COMMIT;