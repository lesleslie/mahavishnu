#!/usr/bin/env python3
"""Quick test to add embeddings and benchmark HNSW."""

import hashlib
import time
import uuid
from datetime import datetime, timedelta

import duckdb
import numpy as np

# Connect
conn = duckdb.connect("data/learning.db")
conn.execute("INSTALL vss")
conn.execute("LOAD vss")
conn.execute("SET hnsw_enable_experimental_persistence=true")

# Generate 1000 test records using executemany with proper formatting
now = datetime.now()
task_types = ["code_review", "testing", "deployment", "documentation", "optimization"]
descriptions = [
    "Review pull request for authentication module",
    "Write unit tests for API endpoints",
    "Deploy application to production",
    "Generate API documentation",
    "Optimize database query performance",
]

print("Generating 1000 test records...")

# Prepare data as Python objects
records = []
for i in range(1000):
    task_type = task_types[i % len(task_types)]
    desc = descriptions[i % len(descriptions)]
    text = f"{task_type} {desc} {i}"

    # Generate embedding
    hash_obj = hashlib.sha256(text.encode())
    random_bytes = b""
    while len(random_bytes) < 384 * 4:
        hash_obj.update(random_bytes or text.encode())
        random_bytes += hash_obj.digest()

    values = np.frombuffer(random_bytes[: 384 * 4], dtype=np.uint8).astype(np.float32)
    values = (values - 128.0) / 128.0
    norm = np.linalg.norm(values)
    if norm > 0:
        values = values / norm

    embedding_list = values.tolist()

    timestamp = now - timedelta(days=i / 10.0)

    records.append(
        (
            str(uuid.uuid4()),  # task_id
            timestamp,  # timestamp
            task_type,  # task_type
            desc,  # task_description
            "mahavishnu",  # repo
            i % 50 + 1,  # file_count
            i * 10 + 100,  # estimated_tokens
            "sonnet-4.5",  # model_tier
            "mahavishnu",  # pool_type
            0.9,  # routing_confidence
            i % 10 + 1,  # complexity_score
            True,  # success
            i + 10.5,  # duration_seconds
            0.1,  # cost_estimate
            0.15,  # actual_cost
            embedding_list,  # embedding
            '{"test": true}',  # metadata
        )
    )

# Use executemany with explicit type casting
conn.execute(
    """
    CREATE OR REPLACE TABLE executions_temp AS
    SELECT * FROM executions LIMIT 0
    """
)

# Insert using prepared statement with appends
for record in records:
    (
        task_id,
        timestamp,
        task_type,
        desc,
        repo,
        file_count,
        estimated_tokens,
        model_tier,
        pool_type,
        routing_confidence,
        complexity_score,
        success,
        duration_seconds,
        cost_estimate,
        actual_cost,
        embedding,
        metadata,
    ) = record

    # Build embedding as DuckDB array string
    embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

    # Use direct SQL with formatted values
    conn.execute(
        f"""
        INSERT INTO executions (
            task_id, timestamp, task_type, task_description, repo,
            file_count, estimated_tokens, model_tier, pool_type,
            routing_confidence, complexity_score, success, duration_seconds,
            cost_estimate, actual_cost, embedding, metadata
        ) VALUES (
            '{task_id}'::UUID,
            '{timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')}'::TIMESTAMP,
            '{task_type}',
            '{desc}',
            '{repo}',
            {file_count},
            {estimated_tokens},
            '{model_tier}',
            '{pool_type}',
            {routing_confidence},
            {complexity_score},
            {str(success).lower()},
            {duration_seconds},
            {cost_estimate},
            {actual_cost},
            {embedding_str}::FLOAT[384],
            '{metadata}'::JSON
        )
    """
    )

    if len(records) % 100 == 0:
        print(f"  Inserted {len(records)}/1000")

result = conn.execute("SELECT COUNT(*) FROM executions").fetchone()
print(f"\nTotal records in database: {result[0]}")

# Get query embedding
query_result = conn.execute(
    "SELECT task_id, embedding FROM executions WHERE embedding IS NOT NULL LIMIT 1"
).fetchone()

query_id, query_embedding = query_result
query_vector_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

print(f"\nQuery task ID: {query_id}")

# Benchmark without HNSW
print("\nBenchmarking exact search (no HNSW)...")
times = []
for _ in range(5):
    start = time.time()
    results = conn.execute(
        f"""
        SELECT task_id, array_distance(embedding, '{query_vector_str}'::FLOAT[384]) as distance
        FROM executions
        WHERE embedding IS NOT NULL
        ORDER BY distance
        LIMIT 10
    """
    ).fetchall()
    times.append(time.time() - start)

avg_exact = sum(times) / len(times)
print(f"Average: {avg_exact*1000:.2f}ms")

# Create HNSW index
print("\nCreating HNSW index...")
start = time.time()
conn.execute("CREATE INDEX hnsw_embeddings ON executions USING HNSW (embedding)")
index_time = time.time() - start
print(f"Index created in {index_time:.2f}s")

# Benchmark with HNSW
print("\nBenchmarking approximate search (with HNSW)...")
times = []
for _ in range(5):
    start = time.time()
    results = conn.execute(
        f"""
        SELECT task_id, array_distance(embedding, '{query_vector_str}'::FLOAT[384]) as distance
        FROM executions
        WHERE embedding IS NOT NULL
        ORDER BY distance
        LIMIT 10
    """
    ).fetchall()
    times.append(time.time() - start)

avg_approx = sum(times) / len(times)
print(f"Average: {avg_approx*1000:.2f}ms")

# Results
speedup = avg_exact / avg_approx if avg_approx > 0 else 0
print(f"\n{'='*60}")
print(f"BENCHMARK RESULTS")
print(f"{'='*60}")
print(f"Records: {result[0]}")
print(f"Exact search:   {avg_exact*1000:.2f}ms")
print(f"Approx search:  {avg_approx*1000:.2f}ms")
print(f"Speedup:        {speedup:.2f}x")
print(f"{'='*60}")

conn.close()
