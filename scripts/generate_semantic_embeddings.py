#!/usr/bin/env python3
"""Generate Semantic Embeddings for Learning Database.

This script generates real semantic embeddings using sentence-transformers
for task descriptions in the learning database, enabling semantic search.

Usage:
    # Generate embeddings for all records without embeddings
    python scripts/generate_semantic_embeddings.py

    # Regenerate all embeddings (overwrite existing)
    python scripts/generate_semantic_embeddings.py --regenerate

    # Generate with specific model
    python scripts/generate_semantic_embeddings.py --model all-MiniLM-L6-v2

    # Test semantic search with sample query
    python scripts/generate_semantic_embeddings.py --test-search "database query optimization"

Performance Targets:
    - Model: all-MiniLM-L6-v2 (384 dimensions, ~80MB)
    - Speed: ~1000 embeddings/second on CPU
    - Quality: Good semantic similarity for task descriptions
    - Search: <100ms for 1M records with HNSW index
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

# Embedding model configuration
DEFAULT_MODEL = "all-MiniLM-L6-v2"  # 384 dims, fast, good quality
EMBEDDING_DIM = 384

# Model cache (singleton)
_embedding_model = None


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


def get_embedding_model(model_name: str = DEFAULT_MODEL):
    """Get or initialize sentence-transformer model.

    Args:
        model_name: Name of the sentence-transformer model

    Returns:
        SentenceTransformer model instance
    """
    global _embedding_model

    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading sentence-transformer model: {model_name}")
            logger.info("This may take a minute on first run (downloading model)...")

            _embedding_model = SentenceTransformer(model_name)

            logger.info(f"Model loaded successfully")
            logger.info(f"  - Model: {model_name}")
            logger.info(f"  - Dimensions: {_embedding_model.get_sentence_embedding_dimension()}")
            logger.info(f"  - Max sequence length: {_embedding_model.max_seq_length}")

        except ImportError:
            logger.error(
                "sentence-transformers not installed. "
                "Install with: uv pip install sentence-transformers"
            )
            raise
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            raise

    return _embedding_model


def generate_embedding(text: str, model_name: str = DEFAULT_MODEL) -> list[float]:
    """Generate semantic embedding for text.

    Args:
        text: Input text to encode
        model_name: Name of sentence-transformer model

    Returns:
        Vector embedding as list of floats
    """
    model = get_embedding_model(model_name)

    # Generate embedding
    embedding = model.encode(
        text,
        convert_to_numpy=True,
        normalize_embeddings=True,  # L2 normalize for cosine similarity
        show_progress_bar=False,
    )

    return embedding.tolist()


def generate_batch_embeddings(
    texts: list[str], model_name: str = DEFAULT_MODEL
) -> list[list[float]]:
    """Generate embeddings for multiple texts (batch processing).

    Args:
        texts: List of input texts to encode
        model_name: Name of sentence-transformer model

    Returns:
        List of vector embeddings
    """
    model = get_embedding_model(model_name)

    # Generate embeddings in batch
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
        batch_size=32,
    )

    return embeddings.tolist()


def generate_embeddings(
    db_path: str,
    model_name: str = DEFAULT_MODEL,
    regenerate: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Generate semantic embeddings for execution records.

    Args:
        db_path: Path to database file
        model_name: Name of sentence-transformer model
        regenerate: Whether to regenerate all embeddings (overwrite existing)
        limit: Maximum number of records to process (None = all)

    Returns:
        Dictionary with generation metrics
    """
    logger.info(f"Generating semantic embeddings: {db_path}")
    logger.info(f"  - Model: {model_name}")
    logger.info(f"  - Regenerate: {regenerate}")
    logger.info(f"  - Limit: {limit or 'unlimited'}")

    metrics = {
        "total_records": 0,
        "processed": 0,
        "generated": 0,
        "skipped": 0,
        "errors": 0,
        "duration_seconds": 0.0,
        "embeddings_per_second": 0.0,
    }

    start_time = time.time()

    try:
        if not Path(db_path).exists():
            logger.error(f"Database does not exist: {db_path}")
            return metrics

        # Connect to database
        conn = duckdb.connect(db_path)

        try:
            # Get records to process
            if regenerate:
                where_clause = ""
            else:
                where_clause = "WHERE embedding IS NULL"

            limit_clause = f"LIMIT {limit}" if limit else ""

            result = conn.execute(
                f"""
                SELECT task_id, task_description, task_type, repo
                FROM executions
                {where_clause}
                {limit_clause}
            """
            ).fetchall()

            if not result:
                logger.info("No records found to process")
                return metrics

            metrics["total_records"] = len(result)
            logger.info(f"Found {len(result)} records to process")

            # Process records in batches
            batch_size = 32
            for i in range(0, len(result), batch_size):
                batch = result[i : i + batch_size]
                metrics["processed"] += len(batch)

                logger.info(
                    f"Processing batch {i // batch_size + 1}/{(len(result) + batch_size - 1) // batch_size} "
                    f"({metrics['processed']}/{len(result)} records)"
                )

                # Prepare texts
                texts = []
                task_ids = []
                for task_id, description, task_type, repo in batch:
                    # Create rich text representation for better embeddings
                    text = f"{task_type} {repo} {description}".strip()
                    texts.append(text)
                    task_ids.append(task_id)

                try:
                    # Generate embeddings in batch
                    embeddings = generate_batch_embeddings(texts, model_name)

                    # Update records
                    for task_id, embedding in zip(task_ids, embeddings):
                        conn.execute(
                            """
                            UPDATE executions
                            SET embedding = ?
                            WHERE task_id = ?
                        """,
                            [embedding, task_id],
                        )
                        metrics["generated"] += 1

                except Exception as e:
                    logger.error(f"Error processing batch: {e}")
                    metrics["errors"] += len(batch)

            # Calculate metrics
            metrics["duration_seconds"] = time.time() - start_time
            if metrics["duration_seconds"] > 0:
                metrics["embeddings_per_second"] = (
                    metrics["generated"] / metrics["duration_seconds"]
                )

            logger.info(f"Embedding generation complete:")
            logger.info(f"  - Generated: {metrics['generated']}")
            logger.info(f"  - Skipped: {metrics['skipped']}")
            logger.info(f"  - Errors: {metrics['errors']}")
            logger.info(f"  - Duration: {metrics['duration_seconds']:.2f}s")
            logger.info(f"  - Speed: {metrics['embeddings_per_second']:.1f} embeddings/s")

            return metrics

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Failed to generate embeddings: {e}")
        import traceback

        traceback.print_exc()
        return metrics


def test_semantic_search(
    db_path: str, query: str, model_name: str = DEFAULT_MODEL, top_k: int = 5
) -> dict[str, Any]:
    """Test semantic search with a query.

    Args:
        db_path: Path to database file
        query: Search query text
        model_name: Name of sentence-transformer model
        top_k: Number of results to return

    Returns:
        Search results dictionary
    """
    logger.info(f"Testing semantic search: '{query}'")
    logger.info(f"  - Model: {model_name}")
    logger.info(f"  - Top K: {top_k}")

    results = {
        "query": query,
        "embedding_time": 0.0,
        "search_time": 0.0,
        "total_time": 0.0,
        "results": [],
    }

    start_time = time.time()

    try:
        if not Path(db_path).exists():
            logger.error(f"Database does not exist: {db_path}")
            return results

        conn = duckdb.connect(db_path)

        try:
            # Check embeddings exist
            embedding_count = conn.execute(
                "SELECT COUNT(*) FROM executions WHERE embedding IS NOT NULL"
            ).fetchone()[0]

            if embedding_count == 0:
                logger.warning("No embeddings found in database")
                return results

            logger.info(f"Found {embedding_count} records with embeddings")

            # Generate query embedding
            embed_start = time.time()
            query_embedding = generate_embedding(query, model_name)
            results["embedding_time"] = time.time() - embed_start

            logger.info(f"Query embedding generated in {results['embedding_time']:.4f}s")

            # Perform semantic search
            search_start = time.time()
            search_results = conn.execute(
                f"""
                SELECT
                    task_id,
                    task_type,
                    task_description,
                    repo,
                    success,
                    array_distance(embedding, ?::FLOAT[EMBEDDING_DIM]) as distance
                FROM executions
                WHERE embedding IS NOT NULL
                ORDER BY distance
                LIMIT {top_k}
            """,
                [query_embedding],
            ).fetchall()
            results["search_time"] = time.time() - search_start

            logger.info(f"Search completed in {results['search_time']:.4f}s")
            logger.info(f"Found {len(search_results)} results")

            # Format results
            for task_id, task_type, description, repo, success, distance in search_results:
                results["results"].append(
                    {
                        "task_id": str(task_id),
                        "task_type": task_type,
                        "description": description,
                        "repo": repo,
                        "success": success,
                        "distance": float(distance),
                        "similarity": float(1.0 - distance),  # Convert distance to similarity
                    }
                )

            results["total_time"] = time.time() - start_time

            # Print results
            logger.info(f"\nSearch Results (query: '{query}'):")
            logger.info("=" * 80)
            for i, result in enumerate(results["results"], 1):
                logger.info(f"\n{i}. Similarity: {result['similarity']:.2%}")
                logger.info(f"   Task: {result['task_type']} - {result['repo']}")
                logger.info(f"   Description: {result['description'][:100]}...")
                logger.info(f"   Success: {result['success']}")

            return results

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Semantic search failed: {e}")
        import traceback

        traceback.print_exc()
        return results


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="Generate semantic embeddings for learning database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate embeddings for all records without embeddings
  python scripts/generate_semantic_embeddings.py

  # Regenerate all embeddings (overwrite existing)
  python scripts/generate_semantic_embeddings.py --regenerate

  # Generate with specific model
  python scripts/generate_semantic_embeddings.py --model all-MiniLM-L6-v2

  # Test semantic search
  python scripts/generate_semantic_embeddings.py --test-search "database query optimization"

Available Models:
  - all-MiniLM-L6-v2 (default): 384 dims, fast, good quality
  - all-mpnet-base-v2: 768 dims, slower, best quality
  - paraphrase-MiniLM-L6-v2: 384 dims, optimized for paraphrases
        """,
    )

    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Sentence-transformer model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Regenerate all embeddings (overwrite existing)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of records to process",
    )
    parser.add_argument(
        "--test-search",
        metavar="QUERY",
        help="Test semantic search with a query",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Check if sentence-transformers is installed
    try:
        import sentence_transformers

        logger.info(f"sentence-transformers version: {sentence_transformers.__version__}")
    except ImportError:
        logger.error("sentence-transformers not installed!")
        logger.error("Install with: uv pip install sentence-transformers")
        return 1

    try:
        # Execute action
        if args.test_search:
            # Test semantic search
            results = test_semantic_search(
                args.db_path, args.test_search, args.model
            )
            success = len(results["results"]) > 0
        else:
            # Generate embeddings
            metrics = generate_embeddings(
                args.db_path,
                args.model,
                args.regenerate,
                args.limit,
            )
            success = metrics["generated"] > 0

        return 0 if success else 1

    except Exception as e:
        logger.error(f"Execution failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
