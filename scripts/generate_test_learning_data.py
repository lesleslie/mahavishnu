#!/usr/bin/env python3
"""Generate test data for learning database with embeddings.

This script creates sample execution records with synthetic embeddings
for testing HNSW vector search performance.

Usage:
    # Generate 1000 test records
    python scripts/generate_test_learning_data.py --count 1000

    # Generate with specific task types
    python scripts/generate_test_learning_data.py --count 500 --task-types code_review,testing,deployment
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import random
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

logger = logging.getLogger(__name__)

# Database path
DEFAULT_DB_PATH = "data/learning.db"

# Task types and descriptions for realistic test data
TASK_TEMPLATES = {
    "code_review": [
        "Review pull request for authentication module",
        "Analyze code quality in payment processing",
        "Security review of user registration flow",
        "Performance review of database queries",
    ],
    "testing": [
        "Write unit tests for API endpoints",
        "Create integration tests for workflow",
        "Generate test cases for error handling",
        "Set up E2E tests for user journey",
    ],
    "deployment": [
        "Deploy application to production",
        "Configure CI/CD pipeline",
        "Setup staging environment",
        "Rollback failed deployment",
    ],
    "documentation": [
        "Generate API documentation",
        "Update architecture diagrams",
        "Create deployment guide",
        "Write runbook for incident response",
    ],
    "optimization": [
        "Optimize database query performance",
        "Reduce memory usage in worker pool",
        "Improve API response times",
        "Refactor legacy code for maintainability",
    ],
}

REPOS = ["mahavishnu", "oneiric", "session-buddy", "akosha", "fastblocks", "crackerjack"]

MODEL_TIERS = ["sonnet-4.5", "opus-4.6", "haiku-3.5"]

POOL_TYPES = ["mahavishnu", "session-buddy", "kubernetes"]

ERROR_TYPES = [
    None,
    None,
    None,  # Mostly successful
    "timeout",
    "rate_limit",
    "validation_error",
    "network_error",
]


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )


def generate_embedding(text: str, dim: int = 384) -> str:
    """Generate synthetic embedding from text using deterministic hashing.

    Args:
        text: Input text to encode
        dim: Embedding dimension

    Returns:
        Vector embedding as SQL array string
    """
    hash_obj = hashlib.sha256(text.encode())
    random_bytes = b""

    while len(random_bytes) < dim * 4:
        hash_obj.update(random_bytes or text.encode())
        random_bytes += hash_obj.digest()

    values = np.frombuffer(random_bytes[: dim * 4], dtype=np.uint8).astype(np.float32)
    values = (values - 128.0) / 128.0

    norm = np.linalg.norm(values)
    if norm > 0:
        values = values / norm

    # Return as SQL array string
    return "[" + ",".join(str(v) for v in values) + "]"


def format_timestamp(dt: datetime) -> str:
    """Format datetime for SQL.

    Args:
        dt: DateTime object

    Returns:
        Formatted timestamp string
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def generate_test_data(
    conn: duckdb.DuckDBPyConnection,
    count: int,
    task_types: list[str] | None = None,
) -> int:
    """Generate test execution records.

    Args:
        conn: DuckDB connection
        count: Number of records to generate
        task_types: List of task types (None = all)

    Returns:
        Number of records inserted
    """
    if task_types is None:
        task_types = list(TASK_TEMPLATES.keys())

    logger.info(f"Generating {count} test records...")

    # Generate timestamps over the last 90 days
    now = datetime.now()
    start_time = time.time()

    for i in range(count):
        # Select random task type
        task_type = random.choice(task_types)
        description = random.choice(TASK_TEMPLATES[task_type])

        # Create combined text for embedding
        text = f"{task_type} {description}"

        # Generate embedding as SQL array string
        embedding_str = generate_embedding(text)

        # Create record values
        task_id = str(uuid.uuid4())
        timestamp = now - timedelta(
            days=random.uniform(0, 90),
            hours=random.uniform(0, 24),
            minutes=random.uniform(0, 60),
        )
        timestamp_str = format_timestamp(timestamp)
        file_count = random.randint(1, 50)
        estimated_tokens = random.randint(100, 10000)
        model_tier = random.choice(MODEL_TIERS)
        pool_type = random.choice(POOL_TYPES)
        swarm_topology = random.choice([None, "hierarchical", "flat", "dynamic"])
        swarm_value = f"'{swarm_topology}'" if swarm_topology else "NULL"
        routing_confidence = random.uniform(0.5, 1.0)
        complexity_score = random.randint(1, 10)
        success = random.random() > 0.2  # 80% success rate
        duration_seconds = random.uniform(5, 300)
        quality_score = random.randint(60, 100) if random.random() > 0.2 else None
        quality_value = quality_score if quality_score else "NULL"
        cost_estimate = random.uniform(0.01, 1.0)
        actual_cost = random.uniform(0.01, 1.5)
        error_type = random.choice(ERROR_TYPES)
        error_value = f"'{error_type}'" if error_type else "NULL"
        user_accepted = random.choice([None, True, False])
        user_value = (
            "true" if user_accepted is True else ("false" if user_accepted is False else "NULL")
        )
        user_rating = random.choice([None, 1, 2, 3, 4, 5])
        rating_value = user_rating if user_rating else "NULL"
        peak_memory_mb = random.uniform(100, 2000)
        cpu_time_seconds = random.uniform(1, 100)
        solution_summary = random.choice([None, f"Solution for {task_type}"])
        solution_value = f"'{solution_summary}'" if solution_summary else "NULL"

        # Build and execute SQL
        sql = f"""
            INSERT INTO executions (
                task_id, timestamp, task_type, task_description, repo,
                file_count, estimated_tokens, model_tier, pool_type, swarm_topology,
                routing_confidence, complexity_score, success, duration_seconds,
                quality_score, cost_estimate, actual_cost, error_type,
                user_accepted, user_rating, peak_memory_mb, cpu_time_seconds,
                solution_summary, embedding, metadata
            ) VALUES (
                '{task_id}'::UUID,
                '{timestamp_str}'::TIMESTAMP,
                '{task_type}',
                '{description}',
                '{random.choice(REPOS)}',
                {file_count},
                {estimated_tokens},
                '{model_tier}',
                '{pool_type}',
                {swarm_value}::VARCHAR,
                {routing_confidence},
                {complexity_score},
                {str(success).lower()},
                {duration_seconds},
                {quality_value},
                {cost_estimate},
                {actual_cost},
                {error_value}::VARCHAR,
                {user_value},
                {rating_value},
                {peak_memory_mb},
                {cpu_time_seconds},
                {solution_value}::VARCHAR,
                {embedding_str}::FLOAT[384],
                '{{"test": true}}'::JSON
            )
        """

        conn.execute(sql)

        if (i + 1) % 100 == 0:
            logger.debug(f"Inserted {i + 1}/{count} records")

    elapsed = time.time() - start_time
    logger.info(f"Generated {count} records in {elapsed:.2f}s ({count/elapsed:.1f} records/s)")

    return count


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate test data for learning database"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1000,
        help="Number of test records to generate (default: 1000)",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--task-types",
        help="Comma-separated list of task types (default: all)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Parse task types
    task_types = None
    if args.task_types:
        task_types = [t.strip() for t in args.task_types.split(",")]
        invalid_types = set(task_types) - set(TASK_TEMPLATES.keys())
        if invalid_types:
            logger.error(f"Invalid task types: {invalid_types}")
            logger.error(f"Valid types: {', '.join(TASK_TEMPLATES.keys())}")
            return 1

    try:
        # Connect to database
        logger.info(f"Connecting to database: {args.db_path}")
        conn = duckdb.connect(args.db_path)

        try:
            # Generate test data
            count = generate_test_data(conn, args.count, task_types)
            logger.info(f"Successfully generated {count} test records")
            return 0

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Failed to generate test data: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
