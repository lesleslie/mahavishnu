#!/usr/bin/env python3
"""Working HNSW test using DuckDB Python API correctly."""

import hashlib
import struct
import time
import uuid
from datetime import datetime, timedelta

import duckdb
import numpy as np

# Connect to database
conn = duckdb.connect("data/learning.db")
conn.execute("INSTALL vss")
conn.execute("LOAD vss")
conn.execute("SET hnsw_enable_experimental_persistence=true")

print("="*60)
print("HNSW Vector Search Benchmark")
print("="*60)

# Check current data
result = conn.execute("SELECT COUNT(*) FROM executions WHERE embedding IS NOT NULL").fetchone()
count = result[0] if result else 0
print(f"\nCurrent records with embeddings: {count}")

# Generate test data using append_to_table
if count < 1000:
    print(f"\nGenerating {1000 - count} test records...")

    now = datetime.now()
    task_types = ["code_review", "testing", "deployment", "documentation", "optimization"]
    descriptions = [
        "Review pull request for authentication module",
        "Write unit tests for API endpoints",
        "Deploy application to production",
        "Generate API documentation",
        "Optimize database query performance",
    ]

    for i in range(count, 1000):
        task_type = task_types[i % len(task_types)]
        desc = descriptions[i % len(descriptions)]
        text = f"{task_type} {desc} {i}"

        # Generate embedding correctly
        hash_obj = hashlib.sha256(text.encode())
        random_bytes = b""

        # Generate exactly 384 floats (1536 bytes)
        while len(random_bytes) < 384 * 4:
            hash_obj.update(random_bytes or text.encode())
            random_bytes += hash_obj.digest()

        # Convert bytes to floats properly
        # Each 4 bytes becomes one float32
        float_count = 384
        floats = struct.unpack(f'{float_count}f', random_bytes[:float_count * 4])

        values = np.array(floats, dtype=np.float32)
        values = (values - 128.0) / 128.0
        norm = np.linalg.norm(values)
        if norm > 0:
            values = values / norm

        embedding_array = values

        timestamp = now - timedelta(days=i/10.0)
        task_id = str(uuid.uuid4())

        # Use individual parameters instead of a list
        conn.execute(
            """
            INSERT INTO executions (
                task_id, timestamp, task_type, task_description, repo,
                file_count, estimated_tokens, model_tier, pool_type,
                routing_confidence, complexity_score, success, duration_seconds,
                cost_estimate, actual_cost, embedding, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            task_id, timestamp, task_type, desc, "mahavishnu",
            i % 50 + 1, i * 10 + 100, "sonnet-4.5", "mahavishnu",
            0.9, i % 10 + 1, True, i + 10.5, 0.1, 0.15,
            embedding_array, '{"test": true}'
        )

        if (i + 1) % 100 == 0:
            print(f"  Inserted {i + 1}/1000")

result = conn.execute("SELECT COUNT(*) FROM executions WHERE embedding IS NOT NULL").fetchone()
print(f"\nTotal records with embeddings: {result[0]}")

# Get query embedding
query_result = conn.execute(
    "SELECT task_id, embedding FROM executions WHERE embedding IS NOT NULL LIMIT 1"
).fetchone()

if not query_result:
    print("\nERROR: No embeddings found!")
    exit(1)

query_id, query_embedding = query_result
print(f"\nQuery task ID: {query_id}")

# Benchmark without HNSW
print("\n" + "-"*60)
print("Benchmark 1: Exact Search (No HNSW)")
print("-"*60)

# Drop index if exists
try:
    conn.execute("DROP INDEX IF EXISTS hnsw_embeddings")
    print("Dropped existing HNSW index")
except:
    pass

times = []
for run in range(10):
    start = time.time()
    results = conn.execute(
        """
        SELECT task_id, array_distance(embedding, ?::FLOAT[384]) as distance
        FROM executions
        WHERE embedding IS NOT NULL
        ORDER BY distance
        LIMIT 10
        """,
        query_embedding
    ).fetchall()
    elapsed = time.time() - start
    times.append(elapsed)
    print(f"  Run {run+1}: {elapsed*1000:.2f}ms")

avg_exact = sum(times) / len(times)
print(f"\nAverage: {avg_exact*1000:.2f}ms")

# Create HNSW index
print("\n" + "-"*60)
print("Creating HNSW Index")
print("-"*60)

start = time.time()
conn.execute("CREATE INDEX hnsw_embeddings ON executions USING HNSW (embedding)")
index_time = time.time() - start
print(f"Index created in {index_time:.2f}s")

# Benchmark with HNSW
print("\n" + "-"*60)
print("Benchmark 2: Approximate Search (With HNSW)")
print("-"*60)

times = []
for run in range(10):
    start = time.time()
    results = conn.execute(
        """
        SELECT task_id, array_distance(embedding, ?::FLOAT[384]) as distance
        FROM executions
        WHERE embedding IS NOT NULL
        ORDER BY distance
        LIMIT 10
        """,
        query_embedding
    ).fetchall()
    elapsed = time.time() - start
    times.append(elapsed)
    print(f"  Run {run+1}: {elapsed*1000:.2f}ms")

avg_approx = sum(times) / len(times)
print(f"\nAverage: {avg_approx*1000:.2f}ms")

# Calculate results
speedup = avg_exact / avg_approx if avg_approx > 0 else 0

print("\n" + "="*60)
print("FINAL RESULTS")
print("="*60)
print(f"Database records:     {result[0]}")
print(f"Embedding dimension:  384")
print(f"\nExact search (no index):   {avg_exact*1000:.2f}ms")
print(f"Approx search (HNSW):      {avg_approx*1000:.2f}ms")
print(f"\nSpeedup:                  {speedup:.2f}x")
if speedup > 1:
    print(f"Performance:               {(1-avg_approx/avg_exact)*100:.1f}% faster")
else:
    print(f"Performance:               {(avg_approx/avg_exact-1)*100:.1f}% slower")
print("="*60)

conn.close()
