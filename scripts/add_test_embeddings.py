#!/usr/bin/env python3
"""Add test embeddings to learning database for HNSW benchmarking."""

import hashlib
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

# Check current count
result = conn.execute("SELECT COUNT(*) FROM executions").fetchone()
print(f"Current record count: {result[0]}")

# Generate 1000 test records
now = datetime.now()
task_types = ["code_review", "testing", "deployment", "documentation", "optimization"]
descriptions = [
    "Review pull request for authentication module",
    "Write unit tests for API endpoints",
    "Deploy application to production",
    "Generate API documentation",
    "Optimize database query performance",
]

print("Generating 1000 test records with embeddings...")
start = time.time()

for i in range(1000):
    task_type = task_types[i % len(task_types)]
    desc = descriptions[i % len(descriptions)]

    # Generate embedding using hash
    text = f"{task_type} {desc} {i}"
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

    # Insert using parameterized query to avoid SQL parsing issues
    embedding_list = values.tolist()
    task_id = str(uuid.uuid4())
    timestamp = now - timedelta(days=i / 10.0)

    # Use prepared statement with proper parameter binding
    conn.execute(
        """
        INSERT INTO executions (
            task_id, timestamp, task_type, task_description, repo,
            file_count, estimated_tokens, model_tier, pool_type,
            routing_confidence, complexity_score, success, duration_seconds,
            cost_estimate, actual_cost, embedding, metadata
        ) VALUES (
            ?::UUID, ?::TIMESTAMP, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?::FLOAT[], ?::JSON
        )
    """,
        [
            task_id,
            timestamp,
            task_type,
            desc,
            "mahavishnu",
            i % 50 + 1,
            i * 10 + 100,
            "sonnet-4.5",
            "mahavishnu",
            0.9,
            i % 10 + 1,
            True,
            i + 10.5,
            0.1,
            0.15,
            embedding_list,
            '{"test": true}',
        ],
    )

    if (i + 1) % 100 == 0:
        print(f"  Inserted {i + 1}/1000")

elapsed = time.time() - start
print(f"Generated 1000 records in {elapsed:.2f}s")

# Check final count
result = conn.execute("SELECT COUNT(*) FROM executions").fetchone()
print(f"Total records in database: {result[0]}")

# Check embeddings
result = conn.execute("SELECT COUNT(*) FROM executions WHERE embedding IS NOT NULL").fetchone()
print(f"Records with embeddings: {result[0]}")

conn.close()
