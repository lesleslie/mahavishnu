#!/usr/bin/env python3
"""HNSW Vector Index Benchmark for Learning Database.

This script benchmarks semantic search performance with and without HNSW index.
"""

import hashlib
import time
import uuid
from datetime import datetime, timedelta

import duckdb
import numpy as np


def generate_embedding(text: str, dim: int = 384) -> list[float]:
    """Generate synthetic embedding from text using deterministic hashing."""
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

    return values.tolist()


def main():
    """Main benchmark function."""
    db_path = "data/learning.db"

    print("=" * 60)
    print("HNSW Vector Index Benchmark")
    print("=" * 60)

    # Connect to database
    conn = duckdb.connect(db_path)
    conn.execute("INSTALL vss")
    conn.execute("LOAD vss")
    conn.execute("SET hnsw_enable_experimental_persistence=true")

    # Check current data
    result = conn.execute("SELECT COUNT(*) FROM executions WHERE embedding IS NOT NULL").fetchone()
    embedding_count = result[0] if result else 0

    print(f"\nCurrent records with embeddings: {embedding_count}")

    if embedding_count < 1000:
        print(f"\nGenerating {1000 - embedding_count} additional test records...")

        now = datetime.now()
        task_types = ["code_review", "testing", "deployment", "documentation", "optimization"]
        descriptions = [
            "Review pull request for authentication module",
            "Write unit tests for API endpoints",
            "Deploy application to production",
            "Generate API documentation",
            "Optimize database query performance",
        ]

        start = time.time()

        for i in range(embedding_count, 1000):
            task_type = task_types[i % len(task_types)]
            desc = descriptions[i % len(descriptions)]
            text = f"{task_type} {desc} {i}"

            # Generate embedding
            embedding = generate_embedding(text)

            # Convert to array string format for DuckDB
            embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"
            timestamp = now - timedelta(days=i / 10.0)
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")

            # Build SQL with embedded values
            sql = f"""
                INSERT INTO executions (
                    task_id, timestamp, task_type, task_description, repo,
                    file_count, estimated_tokens, model_tier, pool_type,
                    routing_confidence, complexity_score, success, duration_seconds,
                    cost_estimate, actual_cost, embedding, metadata
                ) VALUES (
                    '{uuid.uuid4()}'::UUID,
                    '{timestamp_str}'::TIMESTAMP,
                    '{task_type}',
                    '{desc}',
                    'mahavishnu',
                    {i % 50 + 1},
                    {i * 10 + 100},
                    'sonnet-4.5',
                    'mahavishnu',
                    0.9,
                    {i % 10 + 1},
                    true,
                    {i + 10.5},
                    0.1,
                    0.15,
                    {embedding_str}::FLOAT[384],
                    '{{"test": true}}'::JSON
                )
            """

            conn.execute(sql)

            if (i + 1) % 100 == 0:
                print(f"  Inserted {i + 1}/1000")

        elapsed = time.time() - start
        print(f"Generated records in {elapsed:.2f}s ({1000/elapsed:.1f} records/s)")

    # Check final count
    result = conn.execute("SELECT COUNT(*) FROM executions WHERE embedding IS NOT NULL").fetchone()
    print(f"\nTotal records with embeddings: {result[0]}")

    # Get query embedding (use first record)
    query_result = conn.execute(
        "SELECT task_id, embedding FROM executions WHERE embedding IS NOT NULL LIMIT 1"
    ).fetchone()

    if not query_result:
        print("\nERROR: No embeddings found for query")
        return

    query_id, query_embedding = query_result
    query_vector_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    print(f"\nQuery task ID: {query_id}")

    # Benchmark exact search (no HNSW)
    print("\n" + "-" * 60)
    print("Benchmark 1: Exact Search (No HNSW Index)")
    print("-" * 60)

    # Drop HNSW index if exists
    try:
        conn.execute("DROP INDEX IF EXISTS hnsw_embeddings")
        print("Dropped existing HNSW index for fair comparison")
    except:
        pass

    # Run exact search 10 times
    exact_times = []
    for run in range(10):
        start = time.time()
        results = conn.execute(
            f"""
            SELECT task_id, task_type, array_distance(embedding, '{query_vector_str}'::FLOAT[384]) as distance
            FROM executions
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT 10
        """
        ).fetchall()
        elapsed = time.time() - start
        exact_times.append(elapsed)
        print(f"  Run {run + 1}: {elapsed*1000:.2f}ms")

    avg_exact = sum(exact_times) / len(exact_times)
    print(f"\nAverage: {avg_exact*1000:.2f}ms")
    print(f"Results found: {len(results)}")
    print(f"Top result: {results[0][0]} (distance: {results[0][2]:.4f})")

    # Create HNSW index
    print("\n" + "-" * 60)
    print("Creating HNSW Index...")
    print("-" * 60)

    start = time.time()
    conn.execute("CREATE INDEX hnsw_embeddings ON executions USING HNSW (embedding)")
    index_time = time.time() - start
    print(f"HNSW index created in {index_time:.2f}s")

    # Benchmark approximate search (with HNSW)
    print("\n" + "-" * 60)
    print("Benchmark 2: Approximate Search (With HNSW Index)")
    print("-" * 60)

    # Run approximate search 10 times
    approx_times = []
    for run in range(10):
        start = time.time()
        results = conn.execute(
            f"""
            SELECT task_id, task_type, array_distance(embedding, '{query_vector_str}'::FLOAT[384]) as distance
            FROM executions
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT 10
        """
        ).fetchall()
        elapsed = time.time() - start
        approx_times.append(elapsed)
        print(f"  Run {run + 1}: {elapsed*1000:.2f}ms")

    avg_approx = sum(approx_times) / len(approx_times)
    print(f"\nAverage: {avg_approx*1000:.2f}ms")
    print(f"Results found: {len(results)}")
    print(f"Top result: {results[0][0]} (distance: {results[0][2]:.4f})")

    # Calculate speedup
    speedup = avg_exact / avg_approx if avg_approx > 0 else 0

    print("\n" + "=" * 60)
    print("BENCHMARK RESULTS")
    print("=" * 60)
    print(f"Database: {db_path}")
    print(f"Records: {result[0]}")
    print(f"Embedding dimension: 384")
    print(f"\nExact search (no index):  {avg_exact*1000:.2f}ms")
    print(f"Approx search (HNSW):     {avg_approx*1000:.2f}ms")
    print(f"\nSpeedup: {speedup:.2f}x")
    print(f"Improvement: {(1-avg_approx/avg_exact)*100:.1f}% faster")

    if speedup > 1:
        print(f"\n✓ HNSW index provides {speedup:.2f}x performance improvement")
    else:
        print(f"\n✗ HNSW index slower (expected for small datasets)")

    print("=" * 60)

    conn.close()


if __name__ == "__main__":
    main()
