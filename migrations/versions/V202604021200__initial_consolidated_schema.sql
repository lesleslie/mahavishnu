-- Migration: V202604021200__initial_consolidated_schema.sql
-- Purpose: Initial baseline for PostgreSQL + pgvector consolidation
-- Owner: Mahavishnu (orchestration, search, audit, integration)
-- Date: 2026-04-02
--
-- This migration establishes the consolidated schema architecture where
-- Mahavishnu owns operational persistence and semantic search within a
-- single PostgreSQL cluster with pgvector extension.

-- =============================================================================
-- EXTENSION SETUP
-- =============================================================================

-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- =============================================================================
-- SCHEMA CREATION
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS orchestration;
CREATE SCHEMA IF NOT EXISTS search;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS integration;

-- =============================================================================
-- ORCHESTRATION SCHEMA
-- =============================================================================

-- Primary task table for orchestration lifecycle
CREATE TABLE orchestration.tasks (
    id UUID PRIMARY KEY,
    external_id TEXT UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    repository TEXT,
    pool_name TEXT,
    worker_type TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled', 'blocked')),
    priority TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    created_by TEXT,
    assigned_to TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    deadline TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Task indexes for common query patterns
CREATE INDEX idx_tasks_status ON orchestration.tasks (status);
CREATE INDEX idx_tasks_repository ON orchestration.tasks (repository);
CREATE INDEX idx_tasks_assigned_to
    ON orchestration.tasks (assigned_to)
    WHERE assigned_to IS NOT NULL;
CREATE INDEX idx_tasks_created_at ON orchestration.tasks (created_at DESC);
CREATE INDEX idx_tasks_metadata_gin ON orchestration.tasks USING gin (metadata);

-- Task execution runs table
CREATE TABLE orchestration.task_runs (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    run_number INT NOT NULL,
    pool_name TEXT,
    worker_id TEXT,
    worker_type TEXT,
    engine TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled', 'blocked')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    exit_code INT,
    error_message TEXT,
    result_summary TEXT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (task_id, run_number)
);

-- Task runs indexes
CREATE INDEX idx_task_runs_task_id ON orchestration.task_runs (task_id);
CREATE INDEX idx_task_runs_status ON orchestration.task_runs (status);
CREATE INDEX idx_task_runs_started_at ON orchestration.task_runs (started_at DESC);

-- Task dependencies table
CREATE TABLE orchestration.task_dependencies (
    task_id UUID NOT NULL REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    depends_on_task_id UUID NOT NULL REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    dependency_type TEXT NOT NULL DEFAULT 'blocks'
        CHECK (dependency_type IN ('blocks', 'requires', 'relates_to')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (task_id, depends_on_task_id)
);

-- =============================================================================
-- AUDIT SCHEMA
-- =============================================================================

-- Task events table (partitioned by event_time for retention management)
CREATE TABLE audit.task_events (
    id BIGSERIAL,
    task_id UUID REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    run_id UUID REFERENCES orchestration.task_runs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (id, event_time)
) PARTITION BY RANGE (event_time);

-- Default partition for events outside defined ranges
CREATE TABLE audit.task_events_default
    PARTITION OF audit.task_events DEFAULT;

-- Initial partition for April 2026
CREATE TABLE audit.task_events_2026_04
    PARTITION OF audit.task_events
    FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');

-- Task events indexes
CREATE INDEX idx_task_events_task_id ON audit.task_events (task_id);
CREATE INDEX idx_task_events_run_id ON audit.task_events (run_id);
CREATE INDEX idx_task_events_type_time ON audit.task_events (event_type, event_time DESC);
CREATE INDEX idx_task_events_payload_gin ON audit.task_events USING gin (payload);

-- =============================================================================
-- SEARCH SCHEMA
-- =============================================================================

-- Documents table for searchable content
-- Note: source_id intentionally does not have a foreign key to orchestration.tasks(id).
-- This table is polymorphic by design so documents can represent tasks, runs,
-- reports, docs, and other searchable artifacts without forcing all sources
-- into one ownership model.
CREATE TABLE search.documents (
    id UUID PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id UUID,
    source_key TEXT,
    title TEXT,
    content TEXT NOT NULL,
    content_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content, ''))
    ) STORED,
    repository TEXT,
    system_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Document indexes for hybrid search
CREATE INDEX idx_search_documents_source ON search.documents (source_type, source_id);
CREATE INDEX idx_search_documents_repo ON search.documents (repository);
CREATE INDEX idx_search_documents_tsv ON search.documents USING gin (content_tsv);
CREATE INDEX idx_search_documents_metadata_gin ON search.documents USING gin (metadata);

-- Document embeddings table with vector(384) for v1 baseline
CREATE TABLE search.document_embeddings (
    document_id UUID PRIMARY KEY REFERENCES search.documents(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    embedding_dim INT NOT NULL,
    embedding vector(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for fast approximate nearest neighbor search with cosine distance
CREATE INDEX idx_document_embeddings_hnsw
    ON search.document_embeddings
    USING hnsw (embedding vector_cosine_ops);

-- =============================================================================
-- INTEGRATION SCHEMA
-- =============================================================================

-- Session-Buddy context synchronization tracking
-- Records sync state for async mirroring to Session-Buddy
CREATE TABLE integration.session_context_links (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES orchestration.tasks(id) ON DELETE CASCADE,
    session_buddy_id TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (sync_status IN ('pending', 'synced', 'failed', 'retrying', 'skipped')),
    last_attempt_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- Session context link indexes
CREATE INDEX idx_session_context_links_task_id ON integration.session_context_links (task_id);
CREATE INDEX idx_session_context_links_status ON integration.session_context_links (sync_status);

-- =============================================================================
-- MIGRATION METADATA
-- =============================================================================

-- Record migration completion
COMMENT ON SCHEMA orchestration IS 'Mahavishnu orchestration schema: tasks, runs, dependencies';
COMMENT ON SCHEMA search IS 'Mahavishnu search schema: documents and embeddings with pgvector';
COMMENT ON SCHEMA audit IS 'Mahavishnu audit schema: partitioned task events for retention';
COMMENT ON SCHEMA integration IS 'Mahavishnu integration schema: external system sync tracking';

COMMENT ON TABLE orchestration.tasks IS 'Primary task lifecycle table owned by Mahavishnu';
COMMENT ON TABLE orchestration.task_runs IS 'Task execution runs with worker and engine details';
COMMENT ON TABLE orchestration.task_dependencies IS 'Task dependency relationships (blocks, requires, relates_to)';
COMMENT ON TABLE audit.task_events IS 'Partitioned task event audit log (monthly partitions)';
COMMENT ON TABLE search.documents IS 'Polymorphic searchable documents with full-text search';
COMMENT ON TABLE search.document_embeddings IS 'Vector embeddings (384-dim) for semantic search';
COMMENT ON TABLE integration.session_context_links IS 'Session-Buddy async sync state tracking';
