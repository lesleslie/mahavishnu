-- Mahavishnu PostgreSQL Schema
-- Version: 1.0.0
-- Created: 2026-02-18
--
-- This schema supports:
-- - Task orchestration with status tracking
-- - Event sourcing for audit trail
-- - Vector embeddings for semantic search
-- - Multi-tenancy via repository isolation

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Create custom types
CREATE TYPE task_status AS ENUM (
    'pending',
    'in_progress',
    'completed',
    'failed',
    'cancelled',
    'blocked'
);

CREATE TYPE task_priority AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);

CREATE TYPE event_type AS ENUM (
    'created',
    'updated',
    'status_changed',
    'assigned',
    'blocked',
    'unblocked',
    'completed',
    'deleted',
    'comment_added',
    'dependency_added',
    'dependency_removed'
);

-- Tasks table (main entity)
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id VARCHAR(255) UNIQUE,  -- GitHub issue ID, etc.
    title VARCHAR(500) NOT NULL,
    description TEXT,
    repository VARCHAR(255) NOT NULL,
    status task_status NOT NULL DEFAULT 'pending',
    priority task_priority NOT NULL DEFAULT 'medium',
    assignee VARCHAR(255),
    tags TEXT[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    due_date TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    created_by VARCHAR(255) NOT NULL DEFAULT 'system',

    -- Constraints
    CONSTRAINT valid_title CHECK (LENGTH(TRIM(title)) >= 3),
    CONSTRAINT valid_repository CHECK (LENGTH(TRIM(repository)) >= 1)
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_tasks_repository ON tasks(repository);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assignee);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date) WHERE due_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_tags ON tasks USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_tasks_metadata ON tasks USING GIN(metadata);

-- Full-text search index on title and description
CREATE INDEX IF NOT EXISTS idx_tasks_search ON tasks
    USING GIN(to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(description, '')));

-- Task dependencies table
CREATE TABLE IF NOT EXISTS task_dependencies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    dependency_type VARCHAR(50) NOT NULL DEFAULT 'blocks',  -- blocks, requires, related
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Prevent duplicate dependencies
    CONSTRAINT unique_dependency UNIQUE (task_id, depends_on_task_id),
    -- Prevent self-dependency
    CONSTRAINT no_self_dependency CHECK (task_id != depends_on_task_id)
);

CREATE INDEX IF NOT EXISTS idx_task_dependencies_task ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_task_dependencies_depends_on ON task_dependencies(depends_on_task_id);

-- Event store for audit trail and event sourcing
CREATE TABLE IF NOT EXISTS task_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    event_type event_type NOT NULL,
    event_data JSONB NOT NULL DEFAULT '{}',
    actor VARCHAR(255) NOT NULL DEFAULT 'system',
    occurred_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    correlation_id UUID,  -- For linking related events
    idempotency_key VARCHAR(255) UNIQUE,  -- For deduplication

    -- Partitioning by time for performance
    CONSTRAINT valid_event_data CHECK (jsonb_typeof(event_data) = 'object')
);

-- Create indexes for event sourcing queries
CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id);
CREATE INDEX IF NOT EXISTS idx_task_events_type ON task_events(event_type);
CREATE INDEX IF NOT EXISTS idx_task_events_occurred ON task_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_task_events_correlation ON task_events(correlation_id);

-- Task embeddings for semantic search (pgvector)
CREATE TABLE IF NOT EXISTS task_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
    embedding VECTOR(384),  -- Adjust dimension based on model (384 for all-MiniLM-L6-v2)
    embedding_model VARCHAR(100) NOT NULL DEFAULT 'all-MiniLM-L6-v2',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Create HNSW index for vector similarity search
CREATE INDEX IF NOT EXISTS idx_task_embeddings_vector ON task_embeddings
    USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Saga log for distributed transactions
CREATE TABLE IF NOT EXISTS saga_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    saga_id VARCHAR(255) NOT NULL,
    saga_type VARCHAR(100) NOT NULL,
    current_step INTEGER NOT NULL DEFAULT 0,
    total_steps INTEGER NOT NULL,
    step_name VARCHAR(255),
    state JSONB NOT NULL DEFAULT '{}',
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- pending, in_progress, completed, failed, compensating
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT valid_state CHECK (jsonb_typeof(state) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_saga_log_saga_id ON saga_log(saga_id);
CREATE INDEX IF NOT EXISTS idx_saga_log_status ON saga_log(status);
CREATE INDEX IF NOT EXISTS idx_saga_log_created ON saga_log(created_at DESC);

-- Comments table for task discussions
CREATE TABLE IF NOT EXISTS task_comments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES task_comments(id) ON DELETE CASCADE,
    author VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMP WITH TIME ZONE,

    CONSTRAINT valid_content CHECK (LENGTH(TRIM(content)) >= 1)
);

CREATE INDEX IF NOT EXISTS idx_task_comments_task ON task_comments(task_id);
CREATE INDEX IF NOT EXISTS idx_task_comments_author ON task_comments(author);
CREATE INDEX IF NOT EXISTS idx_task_comments_created ON task_comments(created_at DESC);

-- Row-level security policies (optional, for multi-tenancy)
-- ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY repository_isolation ON tasks USING (repository = current_setting('app.current_repository'));

-- Functions

-- Update timestamp trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to tables
CREATE TRIGGER update_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_task_embeddings_updated_at
    BEFORE UPDATE ON task_embeddings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_saga_log_updated_at
    BEFORE UPDATE ON saga_log
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_task_comments_updated_at
    BEFORE UPDATE ON task_comments
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Function to search tasks using full-text search
CREATE OR REPLACE FUNCTION search_tasks(search_query TEXT, repo_filter VARCHAR DEFAULT NULL)
RETURNS SETOF tasks AS $$
BEGIN
    RETURN QUERY
    SELECT *
    FROM tasks
    WHERE
        to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(description, ''))
        @@ plainto_tsquery('english', search_query)
        AND (repo_filter IS NULL OR repository = repo_filter)
    ORDER BY ts_rank(
        to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(description, '')),
        plainto_tsquery('english', search_query)
    ) DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to find similar tasks using vector similarity
CREATE OR REPLACE FUNCTION find_similar_tasks(
    query_embedding VECTOR,
    match_threshold FLOAT DEFAULT 0.7,
    match_count INTEGER DEFAULT 10,
    repo_filter VARCHAR DEFAULT NULL
)
RETURNS TABLE (
    task_id UUID,
    title VARCHAR(500),
    repository VARCHAR(255),
    similarity FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.id::UUID,
        t.title,
        t.repository,
        1 - (e.embedding <=> query_embedding) AS similarity
    FROM task_embeddings e
    JOIN tasks t ON e.task_id = t.id
    WHERE
        1 - (e.embedding <=> query_embedding) > match_threshold
        AND (repo_filter IS NULL OR t.repository = repo_filter)
    ORDER BY e.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- OpenTelemetry Trace Storage with pgvector
-- ============================================================================

-- OTel traces table for semantic search
CREATE TABLE IF NOT EXISTS traces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trace_id VARCHAR(255) NOT NULL,
    span_id VARCHAR(255) NOT NULL,
    parent_span_id VARCHAR(255),
    service_name VARCHAR(255) NOT NULL,
    operation_name VARCHAR(500) NOT NULL,
    kind VARCHAR(50) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_ns BIGINT,
    status_code VARCHAR(50),
    status_message TEXT,
    attributes JSONB DEFAULT '{}',
    resource_attributes JSONB DEFAULT '{}',
    events JSONB DEFAULT '[]',
    links JSONB DEFAULT '[]',

    -- Embedding for semantic search
    embedding VECTOR(384),
    embedding_model VARCHAR(100) DEFAULT 'all-MiniLM-L6-v2',
    embedding_text TEXT,  -- The text that was embedded

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT unique_span UNIQUE (trace_id, span_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_traces_trace_id ON traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_traces_service ON traces(service_name);
CREATE INDEX IF NOT EXISTS idx_traces_operation ON traces(operation_name);
CREATE INDEX IF NOT EXISTS idx_traces_start_time ON traces(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status_code);
CREATE INDEX IF NOT EXISTS idx_traces_attributes ON traces USING GIN(attributes);
CREATE INDEX IF NOT EXISTS idx_traces_resource ON traces USING GIN(resource_attributes);

-- Full-text search on operation names and attributes
CREATE INDEX IF NOT EXISTS idx_traces_search ON traces
    USING GIN(to_tsvector('english', COALESCE(operation_name, '') || ' ' || COALESCE(embedding_text, '')));

-- HNSW index for vector similarity search (10K+ QPS performance)
-- This is the key index for fast approximate nearest neighbor search
-- m: Number of bi-directional links (higher = better recall, more memory)
-- ef_construction: Search depth during build (higher = better index, slower build)
CREATE INDEX IF NOT EXISTS idx_traces_embedding_hnsw ON traces
    USING hnsw(embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- IVFFlat alternative (faster builds, slightly lower recall)
-- Uncomment if HNSW memory usage is too high:
-- CREATE INDEX IF NOT EXISTS idx_traces_embedding_ivf ON traces
--     USING ivfflat(embedding vector_cosine_ops)
--     WITH (lists = 100);

-- Trigger for updated_at
CREATE TRIGGER update_traces_updated_at
    BEFORE UPDATE ON traces
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Function to find similar traces using vector similarity
CREATE OR REPLACE FUNCTION find_similar_traces(
    query_embedding VECTOR,
    match_threshold FLOAT DEFAULT 0.7,
    match_count INTEGER DEFAULT 10,
    service_filter VARCHAR DEFAULT NULL,
    ef_search INTEGER DEFAULT 40
)
RETURNS TABLE (
    trace_id UUID,
    service_name VARCHAR(255),
    operation_name VARCHAR(500),
    similarity FLOAT,
    start_time TIMESTAMP WITH TIME ZONE
) AS $$
BEGIN
    -- Set ef_search for this query (higher = better recall, slower)
    EXECUTE format('SET LOCAL hnsw.ef_search = %s', ef_search);

    RETURN QUERY
    SELECT
        t.id::UUID,
        t.service_name,
        t.operation_name,
        1 - (t.embedding <=> query_embedding) AS similarity,
        t.start_time
    FROM traces t
    WHERE
        t.embedding IS NOT NULL
        AND 1 - (t.embedding <=> query_embedding) > match_threshold
        AND (service_filter IS NULL OR t.service_name = service_filter)
    ORDER BY t.embedding <=> query_embedding
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Function to search traces with combined full-text and vector search
CREATE OR REPLACE FUNCTION search_traces_hybrid(
    search_query TEXT,
    query_embedding VECTOR DEFAULT NULL,
    text_weight FLOAT DEFAULT 0.3,
    vector_weight FLOAT DEFAULT 0.7,
    match_count INTEGER DEFAULT 10
)
RETURNS TABLE (
    id UUID,
    service_name VARCHAR(255),
    operation_name VARCHAR(500),
    text_rank FLOAT,
    vector_similarity FLOAT,
    combined_score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.id,
        t.service_name,
        t.operation_name,
        COALESCE(ts_rank(
            to_tsvector('english', COALESCE(t.operation_name, '') || ' ' || COALESCE(t.embedding_text, '')),
            plainto_tsquery('english', search_query)
        ), 0) AS text_rank,
        CASE
            WHEN query_embedding IS NOT NULL AND t.embedding IS NOT NULL
            THEN 1 - (t.embedding <=> query_embedding)
            ELSE 0
        END AS vector_similarity,
        (
            text_weight * COALESCE(ts_rank(
                to_tsvector('english', COALESCE(t.operation_name, '') || ' ' || COALESCE(t.embedding_text, '')),
                plainto_tsquery('english', search_query)
            ), 0)
            +
            vector_weight * CASE
                WHEN query_embedding IS NOT NULL AND t.embedding IS NOT NULL
                THEN 1 - (t.embedding <=> query_embedding)
                ELSE 0
            END
        ) AS combined_score
    FROM traces t
    WHERE
        to_tsvector('english', COALESCE(t.operation_name, '') || ' ' || COALESCE(t.embedding_text, ''))
        @@ plainto_tsquery('english', search_query)
        OR (query_embedding IS NOT NULL AND t.embedding IS NOT NULL)
    ORDER BY combined_score DESC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Grant permissions (adjust as needed for your security model)
-- GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO mahavishnu;
-- GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO mahavishnu;
-- GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO mahavishnu;

-- Insert sample data for testing (optional)
-- INSERT INTO tasks (title, repository, status, priority, tags)
-- VALUES
--     ('Implement user authentication', 'session-buddy', 'in_progress', 'high', ARRAY['backend', 'security']),
--     ('Add API documentation', 'mahavishnu', 'pending', 'medium', ARRAY['docs', 'api']),
--     ('Fix database connection issue', 'crackerjack', 'blocked', 'critical', ARRAY['bug', 'database']);
