CREATE SEQUENCE IF NOT EXISTS memory_outbox_seq START 1;

CREATE TABLE IF NOT EXISTS memory_outbox (
    id BIGINT PRIMARY KEY DEFAULT nextval('memory_outbox_seq'),
    key TEXT NOT NULL,
    payload JSON NOT NULL,
    enqueued_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attempts INT NOT NULL DEFAULT 0,
    last_error TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
);

-- The status column is constrained to ('pending','drained','failed') by the
-- writer (see MemoryOutboxWriter.mark_drained/mark_failed); DuckDB does not
-- support CHECK constraints or partial indexes, so both invariants are
-- enforced at the application boundary. Pending drainer (Task 2) will keep
-- this invariant during drain.
--
-- The index covers all rows; the WHERE status='pending' predicate in
-- pending_batch()/pending_count() still benefits from the enqueued_at ordering.
CREATE INDEX IF NOT EXISTS idx_memory_outbox_pending
    ON memory_outbox (enqueued_at, id);
