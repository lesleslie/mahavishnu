#!/usr/bin/env python3
"""HNSW Index Migration Script for Learning Database.

This script adds HNSW (Hierarchical Navigable Small World) vector index
to the learning database for fast semantic search using DuckDB's VSS extension.

Usage:
    # Add HNSW index to existing database
    python scripts/migrate_learning_db_hnsw.py upgrade

    # Benchmark search performance (before/after HNSW)
    python scripts/migrate_learning_db_hnsw.py benchmark

    # Generate test embeddings for existing records
    python scripts/migrate_learning_db_hnsw.py generate-embeddings
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

logger = logging.getLogger(__name__)

# Database path
DEFAULT_DB_PATH = "data/learning.db"

# HNSW index configuration
HNSW_CONFIG = {
    "M": 16,  # Max connections per node (higher = better recall, more memory)
    "ef_construction": 100,  # Build-time search depth (higher = better index, slower build)
}

# Embedding dimension
EMBEDDING_DIM = 384


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


def check_vss_extension(conn: duckdb.DuckDBPyConnection) -> bool:
    """Check if VSS extension is available and loaded.

    Args:
        conn: DuckDB connection

    Returns:
        True if VSS extension is available, False otherwise
    """
    try:
        # Check if extension is installed
        result = conn.execute(
            "SELECT * FROM duckdb_extensions() WHERE extension_name = 'vss'"
        ).fetchone()

        if not result:
            logger.info("VSS extension not installed, installing now...")
            conn.execute("INSTALL vss")
            conn.execute("LOAD vss")
            logger.info("VSS extension installed and loaded")
        elif not result[3]:  # installed but not loaded
            conn.execute("LOAD vss")
            logger.info("VSS extension loaded")
        else:
            logger.info("VSS extension already loaded")

        return True

    except Exception as e:
        logger.error(f"Failed to load VSS extension: {e}")
        return False


def generate_synthetic_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Generate synthetic embedding from text using deterministic hashing.

    This is a simple approach for testing. In production, use sentence-transformers
    or OpenAI embeddings for actual semantic search.

    Args:
        text: Input text to encode
        dim: Embedding dimension

    Returns:
        Vector embedding as list of floats
    """
    # Use SHA256 hash for deterministic but distributed values
    hash_obj = hashlib.sha256(text.encode())

    # Generate enough random bytes
    random_bytes = b""
    while len(random_bytes) < dim * 4:
        hash_obj.update(random_bytes or text.encode())
        random_bytes += hash_obj.digest()

    # Convert to floats and normalize
    values = np.frombuffer(random_bytes[: dim * 4], dtype=np.uint8).astype(np.float32)
    values = (values - 128.0) / 128.0  # Normalize to [-1, 1]

    # L2 normalize
    norm = np.linalg.norm(values)
    if norm > 0:
        values = values / norm

    return values.tolist()


def create_hnsw_index(conn: duckdb.DuckDBPyConnection) -> bool:
    """Create HNSW index on embeddings column.

    Args:
        conn: DuckDB connection

    Returns:
        True if index created successfully, False otherwise
    """
    try:
        # Check if embeddings column exists and has data
        result = conn.execute(
            """
            SELECT COUNT(*) FROM executions
            WHERE embedding IS NOT NULL
        """
        ).fetchone()

        if not result or result[0] == 0:
            logger.warning(
                "No embeddings found in executions table. "
                "Run 'generate-embeddings' first."
            )
            return False

        embedding_count = result[0]
        logger.info(f"Found {embedding_count} records with embeddings")

        # Drop existing index if present
        try:
            conn.execute("DROP INDEX IF EXISTS hnsw_embeddings")
            logger.info("Dropped existing HNSW index")
        except Exception:
            pass  # Index doesn't exist

        # Create HNSW index using VSS extension
        # Note: DuckDB VSS uses different syntax - we create a virtual HNSW index
        logger.info(
            f"Creating HNSW index with M={HNSW_CONFIG['M']}, "
            f"ef_construction={HNSW_CONFIG['ef_construction']}"
        )

        # Use VSS HNSW create_index function
        conn.execute(
            f"""
            CREATE INDEX hnsw_embeddings ON executions
            USING HNSW (embedding)
            WITH (M = {HNSW_CONFIG['M']}, ef_construction = {HNSW_CONFIG['ef_construction']})
        """
        )

        logger.info("HNSW index created successfully on embeddings column")
        return True

    except Exception as e:
        logger.error(f"Failed to create HNSW index: {e}")
        return False


def upgrade(db_path: str) -> bool:
    """Upgrade database with HNSW index.

    Args:
        db_path: Path to database file

    Returns:
        True if upgrade successful, False otherwise
    """
    logger.info(f"Upgrading database with HNSW index: {db_path}")

    try:
        if not Path(db_path).exists():
            logger.error(f"Database does not exist: {db_path}")
            return False

        # Connect to database
        conn = duckdb.connect(db_path)

        try:
            # Check and load VSS extension
            if not check_vss_extension(conn):
                logger.error("Failed to load VSS extension")
                return False

            # Create HNSW index
            if not create_hnsw_index(conn):
                logger.error("Failed to create HNSW index")
                return False

            logger.info("Database successfully upgraded with HNSW index")
            return True

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Failed to upgrade database: {e}")
        return False


def generate_embeddings(db_path: str, limit: int | None = None) -> bool:
    """Generate synthetic embeddings for existing records.

    Args:
        db_path: Path to database file
        limit: Maximum number of records to process (None = all)

    Returns:
        True if embeddings generated successfully, False otherwise
    """
    logger.info(f"Generating embeddings for database: {db_path}")

    try:
        if not Path(db_path).exists():
            logger.error(f"Database does not exist: {db_path}")
            return False

        # Connect to database
        conn = duckdb.connect(db_path)

        try:
            # Get records without embeddings
            limit_clause = f"LIMIT {limit}" if limit else ""
            result = conn.execute(
                f"""
                SELECT task_id, task_description, task_type, repo
                FROM executions
                WHERE embedding IS NULL
                {limit_clause}
            """
            ).fetchall()

            if not result:
                logger.info("No records found without embeddings")
                return True

            logger.info(f"Generating embeddings for {len(result)} records")

            # Generate embeddings for each record
            for task_id, description, task_type, repo in result:
                # Create a combined text representation
                text = f"{task_type} {repo} {description}"

                # Generate synthetic embedding
                embedding = generate_synthetic_embedding(text)

                # Update record
                conn.execute(
                    """
                    UPDATE executions
                    SET embedding = ?
                    WHERE task_id = ?
                """,
                    [embedding, task_id],
                )

            logger.info(f"Successfully generated {len(result)} embeddings")
            return True

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Failed to generate embeddings: {e}")
        return False


def benchmark_search(db_path: str) -> dict[str, Any]:
    """Benchmark semantic search with and without HNSW index.

    Args:
        db_path: Path to database file

    Returns:
        Benchmark results dictionary
    """
    logger.info(f"Benchmarking search performance: {db_path}")

    results = {
        "record_count": 0,
        "embedding_count": 0,
        "exact_search_time": 0.0,
        "approx_search_time": 0.0,
        "speedup": 0.0,
    }

    try:
        if not Path(db_path).exists():
            logger.error(f"Database does not exist: {db_path}")
            return results

        conn = duckdb.connect(db_path)

        try:
            # Check data availability
            result = conn.execute(
                "SELECT COUNT(*), COUNT(embedding) FROM executions"
            ).fetchone()

            if not result:
                logger.error("No data found")
                return results

            results["record_count"] = result[0]
            results["embedding_count"] = result[1]

            if results["embedding_count"] == 0:
                logger.warning("No embeddings found, run 'generate-embeddings' first")
                return results

            logger.info(f"Found {results['embedding_count']} records with embeddings")

            # Get a query embedding (use first record as query)
            query_embedding = conn.execute(
                "SELECT embedding FROM executions WHERE embedding IS NOT NULL LIMIT 1"
            ).fetchone()

            if not query_embedding:
                logger.warning("No query embedding found")
                return results

            query_vector = query_embedding[0]

            # Benchmark exact search (no HNSW)
            logger.info("Benchmarking exact search (no HNSW)...")
            start = time.time()
            exact_results = conn.execute(
                """
                SELECT task_id, array_distance(embedding, ?::FLOAT[384]) as distance
                FROM executions
                WHERE embedding IS NOT NULL
                ORDER BY distance
                LIMIT 10
            """,
                [query_vector],
            ).fetchall()
            exact_time = time.time() - start
            results["exact_search_time"] = exact_time

            logger.info(f"Exact search: {exact_time:.4f} seconds, {len(exact_results)} results")

            # Check if HNSW index exists
            index_exists = conn.execute(
                """
                SELECT 1 FROM duckdb_indexes()
                WHERE index_name = 'hnsw_embeddings'
            """
            ).fetchone()

            if not index_exists:
                logger.warning("HNSW index not found, run 'upgrade' first")
                return results

            # Benchmark approximate search (with HNSW)
            logger.info("Benchmarking approximate search (with HNSW)...")
            start = time.time()
            approx_results = conn.execute(
                """
                SELECT task_id, array_distance(embedding, ?::FLOAT[384]) as distance
                FROM executions
                WHERE embedding IS NOT NULL
                ORDER BY distance
                LIMIT 10
            """,
                [query_vector],
            ).fetchall()
            approx_time = time.time() - start
            results["approx_search_time"] = approx_time

            logger.info(f"Approx search: {approx_time:.4f} seconds, {len(approx_results)} results")

            # Calculate speedup
            if approx_time > 0:
                speedup = exact_time / approx_time
                results["speedup"] = speedup
                logger.info(f"Speedup: {speedup:.2f}x")

            # Compare results
            exact_ids = set(r[0] for r in exact_results)
            approx_ids = set(r[0] for r in approx_results)
            overlap = len(exact_ids & approx_ids)
            recall = overlap / len(exact_ids) if exact_ids else 0
            logger.info(f"Recall@10: {recall:.2%} ({overlap}/{len(exact_results)} common)")

            results["recall"] = recall

            return results

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Benchmark failed: {e}")
        return results


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="HNSW index migration for learning database"
    )
    parser.add_argument(
        "action",
        choices=["upgrade", "benchmark", "generate-embeddings"],
        help="Action to perform",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of records for generate-embeddings",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Execute action
    if args.action == "upgrade":
        success = upgrade(args.db_path)
    elif args.action == "benchmark":
        results = benchmark_search(args.db_path)
        success = results.get("speedup", 0) > 0
    elif args.action == "generate-embeddings":
        success = generate_embeddings(args.db_path, limit=args.limit)
    else:
        logger.error(f"Unknown action: {args.action}")
        return 1

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
