#!/bin/bash
# Oneiric OTel Storage Database Setup Script
# This script sets up PostgreSQL + pgvector for OpenTelemetry trace storage

set -euo pipefail

# Configuration
DB_NAME="${OTEL_DB_NAME:-otel_traces}"
DB_USER="${OTEL_DB_USER:-otel_user}"
DB_PASSWORD="${OTEL_DB_PASSWORD:-changeme}"
DB_HOST="${OTEL_DB_HOST:-localhost}"
DB_PORT="${OTEL_DB_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
EMBEDDING_DIM="${EMBEDDING_DIMENSION:-384}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_postgres() {
    log_info "Checking PostgreSQL connection..."

    if ! command -v psql &> /dev/null; then
        log_error "psql command not found. Please install PostgreSQL client."
        exit 1
    fi

    if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" &> /dev/null; then
        log_error "PostgreSQL is not running at $DB_HOST:$DB_PORT"
        exit 1
    fi

    log_info "PostgreSQL connection OK"
}

check_pgvector() {
    log_info "Checking pgvector extension..."

    local has_pgvector
    has_pgvector=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d postgres -tAc \
        "SELECT 1 FROM pg_available_extensions WHERE extname = 'vector'")

    if [ "$has_pgvector" != "1" ]; then
        log_error "pgvector extension not found. Please install pgvector:"
        log_error "  git clone https://github.com/pgvector/pgvector.git"
        log_error "  cd pgvector && make && sudo make install"
        exit 1
    fi

    log_info "pgvector extension found"
}

create_database() {
    log_info "Creating database and user..."

    psql -h "$DB_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" <<EOF
-- Create database
SELECT 'CREATE DATABASE $DB_NAME'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\\gexec

-- Create user
SELECT 'CREATE USER $DB_USER WITH PASSWORD ''$DB_PASSWORD'''
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$DB_USER')\\gexec

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;
EOF

    log_info "Database and user created"
}

create_schema() {
    log_info "Creating database schema..."

    psql -h "$DB_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$DB_NAME" <<EOF
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Create traces table
CREATE TABLE IF NOT EXISTS traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id TEXT NOT NULL,
    span_id TEXT NOT NULL,
    parent_span_id TEXT,
    trace_state TEXT,
    name TEXT NOT NULL,
    kind TEXT,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE NOT NULL,
    status TEXT,
    attributes JSONB,
    events JSONB,
    links JSONB,
    summary TEXT,
    embedding vector($EMBEDDING_DIM),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_traces_trace_id ON traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_traces_start_time ON traces(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_traces_name ON traces(name);

-- Create vector index for semantic search
-- Adjust lists parameter based on expected row count:
-- - 10K rows: lists = 100
-- - 100K rows: lists = 300
-- - 1M rows: lists = 1000
DROP INDEX IF EXISTS idx_traces_embedding;
CREATE INDEX idx_traces_embedding ON traces USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_traces_status ON traces(status) WHERE status IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_traces_attributes ON traces USING GIN (attributes);
CREATE INDEX IF NOT EXISTS idx_traces_events ON traces USING GIN (events);

-- Create updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS \$\$BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;\$\$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_traces_updated_at ON traces;
CREATE TRIGGER update_traces_updated_at
    BEFORE UPDATE ON traces
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Grant permissions to otel_user
GRANT ALL PRIVILEGES ON TABLE traces TO $DB_USER;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;
EOF

    log_info "Schema created successfully"
}

verify_setup() {
    log_info "Verifying setup..."

    local table_exists
    table_exists=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$DB_NAME" -tAc \
        "SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'traces')")

    if [ "$table_exists" != "t" ]; then
        log_error "Traces table not found"
        exit 1
    fi

    local extension_enabled
    extension_enabled=$(psql -h "$DB_HOST" -p "$DB_PORT" -U "$POSTGRES_USER" -d "$DB_NAME" -tAc \
        "SELECT EXISTS (SELECT FROM pg_extension WHERE extname = 'vector')")

    if [ "$extension_enabled" != "t" ]; then
        log_error "pgvector extension not enabled"
        exit 1
    fi

    log_info "Setup verification passed"
}

test_connection() {
    log_info "Testing database connection..."

    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" <<EOF
-- Test connection
SELECT current_database(), current_user, version();

-- Test vector column
SELECT 'vector column test: ' || dim || ' dimensions'
FROM (
    SELECT embeddingdim as dim
    FROM pg_attribute
    WHERE attname = 'embedding'
    AND attrelid = 'traces'::regclass
) t;

-- Test vector similarity (example)
SELECT 1 - (embedding <=> '[0.1,0.2,0.3]'::vector) as similarity
FROM (SELECT '[0.1,0.2,0.3]'::vector as embedding) t
LIMIT 1;
EOF

    log_info "Database connection test passed"
}

show_config() {
    log_info "Configuration:"
    echo "  Database: $DB_NAME"
    echo "  User: $DB_USER"
    echo "  Host: $DB_HOST"
    echo "  Port: $DB_PORT"
    echo "  Embedding Dimension: $EMBEDDING_DIM"
    echo ""
    log_info "Update Mahavishnu configuration:"
    echo "  otel_storage:"
    echo "    enabled: true"
    echo "    connection_string: \"postgresql://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME\""
    echo "    embedding_dimension: $EMBEDDING_DIM"
}

# Main
main() {
    log_info "Oneiric OTel Storage Database Setup"
    echo ""

    check_postgres
    check_pgvector
    create_database
    create_schema
    verify_setup
    test_connection
    show_config

    echo ""
    log_info "Setup completed successfully!"
    log_info "You can now enable otel_storage in settings/mahavishnu.yaml"
}

# Run main
main
