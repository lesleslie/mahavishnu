#!/usr/bin/env python3
"""Generate Embeddings for Learning Database using Ollama.

This script generates semantic embeddings using Ollama's local embedding models
for task descriptions in the learning database, enabling semantic search.

This approach is ideal for x86_64 macOS systems where sentence-transformers/PyTorch
is not available for Python 3.13.

Usage:
    # Generate embeddings for all records without embeddings
    python scripts/generate_ollama_embeddings.py

    # Regenerate all embeddings (overwrite existing)
    python scripts/generate_ollama_embeddings.py --regenerate

    # Generate with specific Ollama model
    python scripts/generate_ollama_embeddings.py --model nomic-embed-text

    # Test semantic search with sample query
    python scripts/generate_ollama_embeddings.py --test-search "database query optimization"

Requirements:
    - Ollama installed: brew install ollama
    - Ollama running: ollama serve
    - Model pulled: ollama pull nomic-embed-text

Performance Targets:
    - Model: nomic-embed-text (768 dimensions)
    - Speed: ~100 embeddings/second (depends on Ollama performance)
    - Quality: Good semantic similarity for task descriptions
    - Search: <100ms for 1M records with HNSW index
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any

import httpx

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import duckdb

logger = logging.getLogger(__name__)

# Database path
DEFAULT_DB_PATH = "data/learning.db"

# Ollama configuration
DEFAULT_OLLAMA_MODEL = "nomic-embed-text"  # 768 dims, good quality
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
EMBEDDING_DIM = 768  # nomic-embed-text produces 768-dim embeddings


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


async def check_ollama(host: str = DEFAULT_OLLAMA_HOST) -> bool:
    """Check if Ollama is running and accessible.

    Args:
        host: Ollama host URL

    Returns:
        True if Ollama is accessible, False otherwise
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{host}/api/tags")
            if response.status_code == 200:
                logger.info(f"Ollama is running at {host}")
                return True
            else:
                logger.error(f"Ollama returned status {response.status_code}")
                return False
    except Exception as e:
        logger.error(f"Cannot connect to Ollama at {host}: {e}")
        logger.error("Make sure Ollama is running: ollama serve")
        return False


async def generate_embedding(
    text: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    host: str = DEFAULT_OLLAMA_HOST,
) -> list[float] | None:
    """Generate embedding using Ollama.

    Args:
        text: Input text to encode
        model: Ollama model name
        host: Ollama host URL

    Returns:
        Vector embedding as list of floats, or None if failed
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{host}/api/embeddings",
                json={
                    "model": model,
                    "prompt": text,
                },
            )

            if response.status_code != 200:
                logger.error(f"Ollama returned status {response.status_code}")
                return None

            data = response.json()
            if "embedding" not in data:
                logger.error("No embedding in Ollama response")
                return None

            return data["embedding"]

    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        return None


async def generate_batch_embeddings(
    texts: list[str],
    model: str = DEFAULT_OLLAMA_MODEL,
    host: str = DEFAULT_OLLAMA_HOST,
) -> list[list[float] | None]:
    """Generate embeddings for multiple texts concurrently.

    Args:
        texts: List of input texts to encode
        model: Ollama model name
        host: Ollama host URL

    Returns:
        List of vector embeddings (None for failed embeddings)
    """
    tasks = [generate_embedding(text, model, host) for text in texts]
    return await asyncio.gather(*tasks)


async def generate_embeddings(
    db_path: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    host: str = DEFAULT_OLLAMA_HOST,
    regenerate: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Generate embeddings for execution records using Ollama.

    Args:
        db_path: Path to database file
        model: Ollama model name
        host: Ollama host URL
        regenerate: Whether to regenerate all embeddings (overwrite existing)
        limit: Maximum number of records to process (None = all)

    Returns:
        Dictionary with generation metrics
    """
    logger.info(f"Generating embeddings using Ollama: {db_path}")
    logger.info(f"  - Model: {model}")
    logger.info(f"  - Host: {host}")
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

        # Check Ollama is running
        if not await check_ollama(host):
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
            batch_size = 10  # Ollama is slower than local models
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
                    # Generate embeddings concurrently
                    embeddings = await generate_batch_embeddings(texts, model, host)

                    # Update records
                    for task_id, embedding in zip(task_ids, embeddings):
                        if embedding is None:
                            logger.warning(f"Failed to generate embedding for {task_id}")
                            metrics["errors"] += 1
                            continue

                        conn.execute(
                            """
                            UPDATE executions
                            SET embedding = ?
                            WHERE task_id = ?
                        """,
                            [embedding, task_id],
                        )
                        metrics["generated"] += 1

                    # Small delay to avoid overwhelming Ollama
                    await asyncio.sleep(0.1)

                except Exception as e:
                    logger.error(f"Error processing batch: {e}")
                    import traceback

                    traceback.print_exc()
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


async def test_semantic_search(
    db_path: str,
    query: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    host: str = DEFAULT_OLLAMA_HOST,
    top_k: int = 5,
) -> dict[str, Any]:
    """Test semantic search with a query.

    Args:
        db_path: Path to database file
        query: Search query text
        model: Ollama model name
        host: Ollama host URL
        top_k: Number of results to return

    Returns:
        Search results dictionary
    """
    logger.info(f"Testing semantic search: '{query}'")
    logger.info(f"  - Model: {model}")
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

        # Check Ollama is running
        if not await check_ollama(host):
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

            # Get embedding dimension from database
            sample_embedding = conn.execute(
                "SELECT embedding FROM executions WHERE embedding IS NOT NULL LIMIT 1"
            ).fetchone()

            if not sample_embedding:
                logger.warning("Cannot determine embedding dimension")
                return results

            embedding_dim = len(sample_embedding[0])

            # Generate query embedding
            embed_start = time.time()
            query_embedding = await generate_embedding(query, model, host)

            if query_embedding is None:
                logger.error("Failed to generate query embedding")
                return results

            results["embedding_time"] = time.time() - embed_start

            logger.info(f"Query embedding generated in {results['embedding_time']:.4f}s")
            logger.info(f"Embedding dimension: {len(query_embedding)}")

            # Create array string for SQL
            array_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
            
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
                    list_cosine_similarity(embedding, '{array_str}'::FLOAT[]) as similarity
                FROM executions
                WHERE embedding IS NOT NULL
                ORDER BY similarity DESC
                LIMIT {top_k}
            """
            ).fetchall()
            results["search_time"] = time.time() - search_start

            logger.info(f"Search completed in {results['search_time']:.4f}s")
            logger.info(f"Found {len(search_results)} results")

            # Format results
            for task_id, task_type, description, repo, success, similarity in search_results:
                results["results"].append(
                    {
                        "task_id": str(task_id),
                        "task_type": task_type,
                        "description": description,
                        "repo": repo,
                        "success": success,
                        "similarity": float(similarity),
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


async def main_async(args: argparse.Namespace) -> int:
    """Async main entry point.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        # Execute action
        if args.test_search:
            # Test semantic search
            results = await test_semantic_search(
                args.db_path, args.test_search, args.model, args.host
            )
            success = len(results["results"]) > 0
        else:
            # Generate embeddings
            metrics = await generate_embeddings(
                args.db_path,
                args.model,
                args.host,
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


def main() -> int:
    """Main entry point.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="Generate embeddings for learning database using Ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate embeddings for all records without embeddings
  python scripts/generate_ollama_embeddings.py

  # Regenerate all embeddings (overwrite existing)
  python scripts/generate_ollama_embeddings.py --regenerate

  # Generate with specific Ollama model
  python scripts/generate_ollama_embeddings.py --model nomic-embed-text

  # Test semantic search
  python scripts/generate_ollama_embeddings.py --test-search "database query optimization"

Requirements:
  1. Install Ollama: brew install ollama
  2. Start Ollama: ollama serve
  3. Pull model: ollama pull nomic-embed-text

Available Models:
  - nomic-embed-text (default): 768 dims, good quality
  - mxbai-embed-large: 1024 dims, higher quality
  - llama2: 4096 dims, general purpose
        """,
    )

    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_OLLAMA_MODEL,
        help=f"Ollama model (default: {DEFAULT_OLLAMA_MODEL})",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_OLLAMA_HOST,
        help=f"Ollama host URL (default: {DEFAULT_OLLAMA_HOST})",
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

    # Check if httpx is installed
    try:
        import httpx

        logger.info(f"httpx version: {httpx.__version__}")
    except ImportError:
        logger.error("httpx not installed!")
        logger.error("Install with: uv pip install httpx")
        return 1

    # Run async main
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
