# Semantic Embeddings Quick Start

## Prerequisites

```bash
# Install FastEmbed (default embedding provider)
uv pip install fastembed
```

## Initialization

```bash
# Initialize database (one-time)
python scripts/init_learning_db.py --db-path data/learning.db

# Generate test data (optional)
python3 -c "
import duckdb
conn = duckdb.connect('data/learning.db')
# ... add test records
"
```

## Generate Embeddings

```bash
# Generate embeddings for all records
python scripts/generate_embeddings.py --db-path data/learning.db

# Regenerate all embeddings
python scripts/generate_embeddings.py --db-path data/learning.db --regenerate
```

## Test Semantic Search

```bash
# Test search with query
python scripts/generate_embeddings.py \
  --db-path data/learning.db \
  --test-search "database query optimization"
```

## Programmatic Usage

```python
import duckdb
from fastembed import TextEmbedding

# Setup
conn = duckdb.connect('data/learning.db')
conn.execute("INSTALL vss")
conn.execute("LOAD vss")

# Generate query embedding
embed_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
query_emb = next(embed_model.embed(["your query"])).tolist()

# Search
array_str = "[" + ",".join(str(x) for x in query_emb) + "]"
results = conn.execute(f"""
    SELECT task_description, list_cosine_similarity(embedding, '{array_str}'::FLOAT[]) as sim
    FROM executions
    WHERE embedding IS NOT NULL
    ORDER BY sim DESC
    LIMIT 10
""").fetchall()
```

## Performance

- **Search Time:** ~8-10ms
- **Embedding Time:** ~400ms
- **Accuracy:** 75-85% similarity
- **Dimensions:** 384 (BAAI/bge-small-en-v1.5)

## Troubleshooting

**FastEmbed model not downloaded:**

```bash
# Pre-download model
python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5')"
```

**Database not initialized:**

```bash
python scripts/init_learning_db.py --db-path data/learning.db
```

## Files

- `scripts/init_learning_db.py` - Database initialization
- `scripts/generate_embeddings.py` - Embedding generation
- ~~`docs/archive/completion-reports/SEMANTIC_EMBEDDINGS_COMPLETE.md` - Full documentation~~ (target removed in 2026-10-14 archive consolidation; see `EMBEDDINGS_SETUP_GUIDE.md` for the current canonical reference)
