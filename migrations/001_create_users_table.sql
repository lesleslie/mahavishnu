-- Migration: 001_create_users_table.sql
-- Created: 2026-02-18
-- Version: 3.1
-- Purpose: Create users table with foreign key constraints
-- Related: 4-Agent Opus Review P0 issue - missing users table

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    display_name VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}'
);

-- Users table indexes
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_created_at ON users(created_at);

-- Add foreign key constraints to tasks table (if tasks table exists)
-- These are added as separate statements to handle existing tables
DO $$
BEGIN
    -- Check if tasks table exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'tasks') THEN
        -- Add created_by foreign key if not exists
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_tasks_created_by'
        ) THEN
            ALTER TABLE tasks
                ADD CONSTRAINT fk_tasks_created_by
                FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT;
        END IF;

        -- Add assigned_to foreign key if not exists
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.table_constraints
            WHERE constraint_name = 'fk_tasks_assigned_to'
        ) THEN
            ALTER TABLE tasks
                ADD CONSTRAINT fk_tasks_assigned_to
                FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL;
        END IF;

        -- Add composite indexes for common queries
        IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_tasks_status_priority') THEN
            CREATE INDEX idx_tasks_status_priority ON tasks(status, priority);
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_tasks_repository_status') THEN
            CREATE INDEX idx_tasks_repository_status ON tasks(repository, status);
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_tasks_assigned_status') THEN
            CREATE INDEX idx_tasks_assigned_status ON tasks(assigned_to, status) WHERE assigned_to IS NOT NULL;
        END IF;
    END IF;
END $$;

-- Create a default system user for migrations
INSERT INTO users (id, username, email, display_name, metadata)
VALUES (
    '00000000-0000-0000-0000-000000000000'::UUID,
    'system',
    'system@mahavishnu.local',
    'System User',
    '{"is_system": true}'
) ON CONFLICT (id) DO NOTHING;

-- Create updated_at trigger for users table
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
