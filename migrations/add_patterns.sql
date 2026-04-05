-- Phase 2: Pattern Detection & Prediction Storage
-- Created: 2026-04-03
--
-- This migration adds tables for storing detected patterns,
-- blocker patterns, and prediction data.

-- Pattern types enum
CREATE TYPE pattern_type AS ENUM (
    'task_duration',
    'blocker_recurring',
    'completion_sequence',
    'repository_specific',
    'tag_specific',
    'priority_correlation'
);

-- Pattern severity enum
CREATE TYPE pattern_severity AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);

-- Pattern frequency enum
CREATE TYPE pattern_frequency AS ENUM (
    'rare',
    'occasional',
    'common',
    'frequent',
    'very_frequent'
);

-- Detected patterns storage
CREATE TABLE IF NOT EXISTS detected_patterns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pattern_type pattern_type NOT NULL,
    pattern_name VARCHAR(255) NOT NULL,
    description TEXT,
    severity pattern_severity NOT NULL DEFAULT 'medium',
    frequency pattern_frequency NOT NULL DEFAULT 'occasional',
    confidence FLOAT NOT NULL DEFAULT 0.0 CHECK (confidence >= 0 AND confidence <= 1.0),
    occurrence_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}',
    -- Pattern matching data
    match_criteria JSONB NOT NULL DEFAULT '{}',
    -- Scope
    repository VARCHAR(255),
    tag VARCHAR(100),
    -- Statistics
    avg_duration_hours FLOAT,
    median_duration_hours FLOAT,
    std_deviation_hours FLOAT,
    blocker_probability FLOAT CHECK (blocker_probability IS NULL OR (blocker_probability >= 0 AND blocker_probability <= 1.0)),
    -- Timestamps
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Constraints
    CONSTRAINT unique_pattern UNIQUE (pattern_type, pattern_name, repository, tag)
);

-- Index for pattern lookups
CREATE INDEX idx_patterns_type ON detected_patterns (pattern_type);
CREATE INDEX idx_patterns_repository ON detected_patterns (repository);
CREATE INDEX idx_patterns_tag ON detected_patterns (tag);
CREATE INDEX idx_patterns_severity ON detected_patterns (severity);
CREATE INDEX idx_patterns_frequency ON detected_patterns (frequency);

-- Blocker pattern storage
CREATE TABLE IF NOT EXISTS blocker_patterns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pattern_id UUID REFERENCES detected_patterns(id) ON DELETE CASCADE,
    -- Blocker identification
    blocker_keyword VARCHAR(255) NOT NULL,
    blocker_category VARCHAR(100),
    -- Frequency metrics
    total_occurrences INTEGER NOT NULL DEFAULT 0,
    resolved_count INTEGER NOT NULL DEFAULT 0,
    resolution_rate FLOAT DEFAULT 0.0,
    -- Scope
    affected_repositories TEXT[] DEFAULT '{}',
    affected_tags TEXT[] DEFAULT '{}',
    -- Impact metrics
    avg_blocking_duration_hours FLOAT,
    max_blocking_duration_hours FLOAT,
    -- Alerting
    alert_threshold FLOAT NOT NULL DEFAULT 0.7,
    is_alerting BOOLEAN NOT NULL DEFAULT FALSE,
    last_alert_at TIMESTAMPTZ,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Constraints
    CONSTRAINT unique_blocker_keyword UNIQUE (blocker_keyword, blocker_category)
);

CREATE INDEX idx_blocker_patterns_keyword ON blocker_patterns (blocker_keyword);
CREATE INDEX idx_blocker_patterns_category ON blocker_patterns (blocker_category);
CREATE INDEX idx_blocker_patterns_alerting ON blocker_patterns (is_alerting) WHERE is_alerting = TRUE;

-- Task duration patterns
CREATE TABLE IF NOT EXISTS duration_patterns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pattern_id UUID REFERENCES detected_patterns(id) ON DELETE CASCADE,
    -- Duration statistics
    avg_duration_hours FLOAT NOT NULL,
    median_duration_hours FLOAT NOT NULL,
    p90_duration_hours FLOAT,
    p95_duration_hours FLOAT,
    std_deviation_hours FLOAT,
    -- Breakdown by dimensions
    by_priority JSONB DEFAULT '{}',
    by_repository JSONB DEFAULT '{}',
    by_tag JSONB DEFAULT '{}',
    -- Sample size
    sample_count INTEGER NOT NULL DEFAULT 0,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Prediction history for tracking accuracy
CREATE TABLE IF NOT EXISTS prediction_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID,
    -- Prediction details
    prediction_type VARCHAR(50) NOT NULL, -- 'blocker', 'duration', 'ordering'
    predicted_value JSONB NOT NULL,
    confidence FLOAT NOT NULL CHECK (confidence >= 0 AND confidence <= 1.0),
    confidence_lower FLOAT,
    confidence_upper FLOAT,
    -- Actual outcome (filled in later)
    actual_value JSONB,
    accuracy FLOAT CHECK (accuracy IS NULL OR (accuracy >= 0 AND accuracy <= 1.0)),
    -- Metadata
    model_version VARCHAR(50),
    features_used TEXT[],
    -- Timestamps
    predicted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX idx_prediction_history_task ON prediction_history (task_id);
CREATE INDEX idx_prediction_history_type ON prediction_history (prediction_type);
CREATE INDEX idx_prediction_history_resolved ON prediction_history (resolved_at) WHERE resolved_at IS NOT NULL;

-- Pattern match log for tracking which patterns matched which tasks
CREATE TABLE IF NOT EXISTS pattern_match_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pattern_id UUID NOT NULL REFERENCES detected_patterns(id) ON DELETE CASCADE,
    task_id UUID,
    match_score FLOAT NOT NULL CHECK (match_score >= 0 AND match_score <= 1.0),
    matched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pattern_match_log_pattern ON pattern_match_log (pattern_id);
CREATE INDEX idx_pattern_match_log_task ON pattern_match_log (task_id);
CREATE INDEX idx_pattern_match_log_time ON pattern_match_log (matched_at);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_patterns_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at triggers
CREATE TRIGGER trigger_detected_patterns_updated
    BEFORE UPDATE ON detected_patterns
    FOR EACH ROW EXECUTE FUNCTION update_patterns_updated_at();

CREATE TRIGGER trigger_blocker_patterns_updated
    BEFORE UPDATE ON blocker_patterns
    FOR EACH ROW EXECUTE FUNCTION update_patterns_updated_at();

CREATE TRIGGER trigger_duration_patterns_updated
    BEFORE UPDATE ON duration_patterns
    FOR EACH ROW EXECUTE FUNCTION update_patterns_updated_at();
