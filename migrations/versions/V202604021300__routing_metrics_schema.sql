-- Migration: V202604021300__routing_metrics_schema.sql
-- Purpose: Routing metrics persistence for adaptive router
-- Owner: Mahavishnu (orchestration layer)
-- Date: 2026-04-02
--
-- This migration creates tables for persisting adaptive routing metrics
-- to PostgreSQL instead of Druva, completing PLAN_INDEX.md item 7.

-- =============================================================================
-- ROUTING METRICS SCHEMA
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS metrics;

-- =============================================================================
-- EXECUTION RECORDS TABLE
-- =============================================================================

-- Stores individual execution records for adapter performance tracking
CREATE TABLE metrics.execution_records (
    id BIGSERIAL PRIMARY KEY,
    execution_id TEXT UNIQUE NOT NULL,
    adapter TEXT NOT NULL
        CHECK (adapter IN ('prefect', 'agno', 'llamaindex')),
    task_type TEXT NOT NULL
        CHECK (task_type IN ('workflow', 'ai_task', 'rag_query', 'batch_task', 'critical_task', 'interactive_task')),
    start_timestamp TIMESTAMPTZ NOT NULL,
    end_timestamp TIMESTAMPTZ,
    status TEXT NOT NULL
        CHECK (status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled', 'blocked')),
    latency_ms INT,
    error_type TEXT,
    error_message TEXT,
    cost_usd DECIMAL(10, 6),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX idx_execution_records_adapter ON metrics.execution_records (adapter);
CREATE INDEX idx_execution_records_task_type ON metrics.execution_records (task_type);
CREATE INDEX idx_execution_records_status ON metrics.execution_records (status);
CREATE INDEX idx_execution_records_created_at ON metrics.execution_records (created_at DESC);
CREATE INDEX idx_execution_records_adapter_task ON metrics.execution_records (adapter, task_type);

-- =============================================================================
-- ADAPTER STATISTICS TABLE
-- =============================================================================

-- Stores aggregated adapter statistics by date
CREATE TABLE metrics.adapter_stats (
    id BIGSERIAL PRIMARY KEY,
    adapter TEXT NOT NULL
        CHECK (adapter IN ('prefect', 'agno', 'llamaindex')),
    stat_date DATE NOT NULL,
    success_rate DECIMAL(5, 4) NOT NULL CHECK (success_rate >= 0 AND success_rate <= 1),
    total_executions INT NOT NULL CHECK (total_executions >= 0),
    avg_latency_ms DECIMAL(10, 2),
    p50_latency_ms DECIMAL(10, 2),
    p95_latency_ms DECIMAL(10, 2),
    p99_latency_ms DECIMAL(10, 2),
    error_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    cost_total_usd DECIMAL(12, 4),
    uptime_percentage DECIMAL(5, 2) CHECK (uptime_percentage >= 0 AND uptime_percentage <= 100),
    sample_size INT NOT NULL CHECK (sample_size >= 1),
    confidence_interval DECIMAL(5, 4),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (adapter, stat_date)
);

-- Indexes for adapter stats queries
CREATE INDEX idx_adapter_stats_date ON metrics.adapter_stats (stat_date DESC);
CREATE INDEX idx_adapter_stats_adapter_date ON metrics.adapter_stats (adapter, stat_date DESC);

-- =============================================================================
-- ROUTING DECISIONS TABLE
-- =============================================================================

-- Stores routing decisions for analysis and learning
CREATE TABLE metrics.routing_decisions (
    id BIGSERIAL PRIMARY KEY,
    decision_id TEXT UNIQUE NOT NULL,
    task_type TEXT NOT NULL
        CHECK (task_type IN ('workflow', 'ai_task', 'rag_query', 'batch_task', 'critical_task', 'interactive_task')),
    selected_adapter TEXT NOT NULL
        CHECK (selected_adapter IN ('prefect', 'agno', 'llamaindex')),
    alternative_adapters JSONB NOT NULL DEFAULT '[]'::jsonb,
    reasoning TEXT NOT NULL,
    adapter_scores JSONB NOT NULL DEFAULT '{}'::jsonb,
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for routing decision analysis
CREATE INDEX idx_routing_decisions_task_type ON metrics.routing_decisions (task_type);
CREATE INDEX idx_routing_decisions_adapter ON metrics.routing_decisions (selected_adapter);
CREATE INDEX idx_routing_decisions_timestamp ON metrics.routing_decisions (timestamp DESC);

-- =============================================================================
-- COST TRACKING TABLE
-- =============================================================================

-- Stores cost tracking per execution
CREATE TABLE metrics.cost_tracking (
    id BIGSERIAL PRIMARY KEY,
    execution_id TEXT NOT NULL,
    adapter TEXT NOT NULL
        CHECK (adapter IN ('prefect', 'agno', 'llamaindex')),
    task_type TEXT NOT NULL
        CHECK (task_type IN ('workflow', 'ai_task', 'rag_query', 'batch_task', 'critical_task', 'interactive_task')),
    cost_usd DECIMAL(10, 6) NOT NULL CHECK (cost_usd >= 0),
    budget_type TEXT,
    budget_limit_usd DECIMAL(10, 6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for cost analysis
CREATE INDEX idx_cost_tracking_execution ON metrics.cost_tracking (execution_id);
CREATE INDEX idx_cost_tracking_adapter ON metrics.cost_tracking (adapter);
CREATE INDEX idx_cost_tracking_budget ON metrics.cost_tracking (budget_type);
CREATE INDEX idx_cost_tracking_created_at ON metrics.cost_tracking (created_at DESC);

-- =============================================================================
-- A/B TEST EXPERIMENTS TABLE
-- =============================================================================

-- Stores A/B test experiments for routing optimization
CREATE TABLE metrics.ab_tests (
    id BIGSERIAL PRIMARY KEY,
    experiment_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'rolled_back', 'cancelled')),
    traffic_split JSONB NOT NULL DEFAULT '{}'::jsonb,
    sample_size JSONB NOT NULL DEFAULT '{}'::jsonb,
    success_metric TEXT NOT NULL,
    significance_threshold DECIMAL(5, 4) NOT NULL CHECK (significance_threshold >= 0 AND significance_threshold <= 1),
    results JSONB,
    winner TEXT
        CHECK (winner IS NULL OR winner IN ('prefect', 'agno', 'llamaindex')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for A/B test queries
CREATE INDEX idx_ab_tests_status ON metrics.ab_tests (status);
CREATE INDEX idx_ab_tests_dates ON metrics.ab_tests (start_date, end_date);

-- =============================================================================
-- TASK TYPE STATISTICS TABLE
-- =============================================================================

-- Stores task-type specific routing performance
CREATE TABLE metrics.task_type_stats (
    id BIGSERIAL PRIMARY KEY,
    task_type TEXT NOT NULL
        CHECK (task_type IN ('workflow', 'ai_task', 'rag_query', 'batch_task', 'critical_task', 'interactive_task')),
    stat_date DATE NOT NULL,
    preferred_adapter TEXT NOT NULL
        CHECK (preferred_adapter IN ('prefect', 'agno', 'llamaindex')),
    alternative_adapters JSONB NOT NULL DEFAULT '[]'::jsonb,
    sample_count INT NOT NULL CHECK (sample_count >= 1),
    routing_confidence DECIMAL(5, 4) NOT NULL CHECK (routing_confidence >= 0 AND routing_confidence <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (task_type, stat_date)
);

-- Indexes for task type stats
CREATE INDEX idx_task_type_stats_date ON metrics.task_type_stats (stat_date DESC);
CREATE INDEX idx_task_type_stats_task_date ON metrics.task_type_stats (task_type, stat_date DESC);

-- =============================================================================
-- PARTITIONING FOR EXECUTION RECORDS (Monthly)
-- =============================================================================

-- Create partitioned table for execution records (long-term storage)
-- This replaces the main execution_records table for high-volume scenarios
-- Note: For initial deployment, we use the non-partitioned table above.
-- Partitioning can be added later by:
-- 1. Creating metrics.execution_records_partitioned PARTITION BY RANGE (created_at)
-- 2. Creating monthly partitions
-- 3. Swapping table names

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON SCHEMA metrics IS 'Mahavishnu routing metrics: adaptive router performance tracking';

COMMENT ON TABLE metrics.execution_records IS 'Individual execution records for adapter performance tracking';
COMMENT ON TABLE metrics.adapter_stats IS 'Aggregated daily statistics per adapter';
COMMENT ON TABLE metrics.routing_decisions IS 'Routing decisions for analysis and learning';
COMMENT ON TABLE metrics.cost_tracking IS 'Cost tracking per execution';
COMMENT ON TABLE metrics.ab_tests IS 'A/B test experiments for routing optimization';
COMMENT ON TABLE metrics.task_type_stats IS 'Task-type specific routing performance';

-- =============================================================================
-- GRANTS (adjust for production roles)
-- =============================================================================

-- GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA metrics TO mahavishnu_app;
-- GRANT USAGE ON ALL SEQUENCES IN SCHEMA metrics TO mahavishnu_app;
