#!/usr/bin/env python3
"""Initialize Learning Database Schema.

This script creates the initial DuckDB schema for the learning database,
including the executions table with optimized columnar storage.

Usage:
    python scripts/init_learning_db.py [--db-path PATH]

Schema:
    - executions: Main table for task execution telemetry
    - embedding column: FLOAT[384] or FLOAT[768] for semantic search
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

logger = logging.getLogger(__name__)

# Database path
DEFAULT_DB_PATH = "data/learning.db"


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration.

    Args:
        verbose: Enable verbose logging
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


def create_schema(conn: duckdb.DuckDBPyConnection) -> bool:
    """Create database schema.

    Args:
        conn: DuckDB connection

    Returns:
        True if schema created successfully, False otherwise
    """
    try:
        logger.info("Creating executions table...")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS executions (
                task_id UUID PRIMARY KEY,
                timestamp TIMESTAMP NOT NULL,
                task_type VARCHAR NOT NULL,
                task_description TEXT NOT NULL,
                repo VARCHAR NOT NULL,
                file_count INT NOT NULL,
                estimated_tokens INT NOT NULL,
                model_tier VARCHAR NOT NULL,
                pool_type VARCHAR NOT NULL,
                swarm_topology VARCHAR,
                routing_confidence FLOAT NOT NULL,
                complexity_score INT NOT NULL,
                success BOOLEAN NOT NULL,
                duration_seconds FLOAT NOT NULL,
                quality_score INT,
                cost_estimate FLOAT NOT NULL,
                actual_cost FLOAT NOT NULL,
                error_type VARCHAR,
                error_message TEXT,
                user_accepted BOOLEAN,
                user_rating INT,
                peak_memory_mb FLOAT,
                cpu_time_seconds FLOAT,
                solution_summary TEXT,
                embedding FLOAT[],
                metadata JSON,
                uploaded_at TIMESTAMP DEFAULT NOW()
            )
        """
        )

        logger.info("Executions table created successfully")

        # Create indexes for frequently queried columns
        logger.info("Creating indexes...")

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_task_type
            ON executions(task_type)
        """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_repo
            ON executions(repo)
        """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_success
            ON executions(success)
        """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_timestamp
            ON executions(timestamp)
        """
        )

        logger.info("Indexes created successfully")

        return True

    except Exception as e:
        logger.error(f"Failed to create schema: {e}")
        import traceback

        traceback.print_exc()
        return False


def init_database(db_path: str, force: bool = False) -> bool:
    """Initialize database with schema.

    Args:
        db_path: Path to database file
        force: Drop and recreate if exists

    Returns:
        True if initialization successful, False otherwise
    """
    logger.info(f"Initializing database: {db_path}")

    try:
        # Create parent directory if needed
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Check if database exists
        if Path(db_path).exists():
            if force:
                logger.warning(f"Database exists, recreating (--force)")
                Path(db_path).unlink()
            else:
                logger.error(f"Database already exists: {db_path}")
                logger.error("Use --force to drop and recreate")
                return False

        # Connect to database (creates if not exists)
        conn = duckdb.connect(db_path)

        try:
            # Create schema
            if not create_schema(conn):
                return False

            logger.info("Database initialized successfully")
            logger.info(f"Database: {db_path}")
            logger.info("Schema: executions table with embedding support")

            return True

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        import traceback

        traceback.print_exc()
        return False


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="Initialize learning database schema"
    )

    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Drop and recreate if exists",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Initialize database
    success = init_database(args.db_path, args.force)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
